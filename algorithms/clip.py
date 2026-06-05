"""
SedonaDB Spatial Clip

Threading model — Windows PROJ database lock
---------------------------------------------
QGIS runs processAlgorithm() on a background worker thread.
Any call that touches pyproj/PROJ crashes on Windows due to the
PROJ database lock held by QGIS on the main thread.

Affected calls (ALL moved to prepareAlgorithm / main thread):
  • pyogrio.read_dataframe()      — triggers CRS init
  • sd.create_data_frame(gdf)     — calls gdf.to_arrow() → CRS.to_json_dict()
  • df.to_view(name)              — registers the view in the SedonaDB context

processAlgorithm() (worker thread) only runs:
  • sd.sql(query)                 — pure DataFusion SQL, no PROJ
  • result.to_pyogrio(output)     — writes Arrow → GPKG on disk

SQL-injection mitigations
  • Column names validated with _validate_identifier() allowlist
  • All identifiers double-quoted via _quote_ident()
  • Memory limit validated against strict regex
  • ST_* function names are hardcoded constants
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorDestination,
)

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r'^[\w\s\-\.]+$', re.UNICODE)
_MEM_RE   = re.compile(r'^\d*(mb|gb)$', re.IGNORECASE)


def _validate_identifier(value: str, label: str) -> str:
    if not value or not _IDENT_RE.match(value):
        raise QgsProcessingException(
            f"Security check failed: {label} '{value}' contains characters "
            "not permitted in a SQL identifier. "
            "Rename the layer/column and try again."
        )
    return value


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _validate_memory_limit(value: str) -> str:
    v = value.strip()
    if not _MEM_RE.match(v):
        raise QgsProcessingException(
            f"Memory limit '{v}' is not valid. Use a value like '2gb' or '512mb'."
        )
    return v.lower()


def _parse_gpkg_path_and_layer(layer) -> tuple[str, str]:
    uri = layer.source()
    gpkg_file = uri.split('|')[0]
    if 'layername=' in uri:
        layer_name = layer.dataProvider().dataSourceUri() \
            .split('layername=')[-1].split('|')[0]
    else:
        layer_name = layer.name()
    return gpkg_file, layer_name


# ---------------------------------------------------------------------------
# Algorithm
# ---------------------------------------------------------------------------

class SedonaSpatialClipCanvasLayersAlgorithm(QgsProcessingAlgorithm):
    """
    Out-of-core spatial clip via SedonaDB.
    Trims INPUT_LAYER features to the exact boundaries of CLIP_LAYER.
    Both layers must be GeoPackages (.gpkg).
    """

    INPUT_LAYER  = 'INPUT_LAYER'
    CLIP_LAYER   = 'CLIP_LAYER'
    MEMORY_LIMIT = 'MEMORY_LIMIT'
    OUTPUT_GPKG  = 'OUTPUT_GPKG'

    def __init__(self):
        super().__init__()
        # All set by prepareAlgorithm() on the main thread
        self._sd          = None   # live SedonaDB session
        self._select_cols = None   # list[str] — validated SELECT parts
        self._sedona_db   = None
        self._pyogrio     = None

    def tr(self, s): return QCoreApplication.translate('Processing', s)
    def createInstance(self): return SedonaSpatialClipCanvasLayersAlgorithm()
    def name(self): return 'sedonaspatialclipcanvaslayers'
    def displayName(self): return self.tr('Spatial Clip (GPKG Only)')
    def group(self): return self.tr('SedonaDB Spatial Tools')
    def groupId(self): return 'sedonadb_spatial_tools'

    def shortHelpString(self):
        return self.tr(
            "Spatial clip via SedonaDB.\n\n"
            "Trims Input Layer features to the exact boundaries of the Clip Layer.\n\n"
            "Both layers must be GeoPackages (.gpkg).\n\n"
            "Requires: sedonadb, pyogrio  — run 'Install SedonaDB Dependencies' "
            "then restart QGIS if not yet installed."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_LAYER, self.tr('Input Layer (to be clipped)'),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.CLIP_LAYER, self.tr('Clip Layer (bounding overlay)'),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterString(
            self.MEMORY_LIMIT, self.tr('SedonaDB Memory Limit (e.g. 2gb, 4gb)'),
            defaultValue='2gb'))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_GPKG, self.tr('Clipped Output GeoPackage')))

    # ------------------------------------------------------------------
    # prepareAlgorithm — MAIN THREAD
    #
    # Everything that touches pyproj / PROJ must run here:
    #   1. pyogrio.read_dataframe()   — CRS init
    #   2. sd.create_data_frame()     — gdf.to_arrow() calls CRS.to_json_dict()
    #   3. df.to_view()               — registers view in SedonaDB context
    # ------------------------------------------------------------------
    def prepareAlgorithm(self, parameters, context, feedback) -> bool:
        from .._deps_loader import require_deps
        self._sedona_db, self._pyogrio = require_deps()

        source_layer1 = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        source_layer2 = self.parameterAsVectorLayer(parameters, self.CLIP_LAYER, context)

        if not source_layer1 or not source_layer2:
            raise QgsProcessingException("Invalid input layers selected.")

        for lyr in (source_layer1, source_layer2):
            if lyr.providerType() != 'ogr' or '.gpkg' not in lyr.source().lower():
                raise QgsProcessingException(
                    f"Layer '{lyr.name()}' is not a GeoPackage layer.")

        gpkg_file1, layer1_name = _parse_gpkg_path_and_layer(source_layer1)
        gpkg_file2, layer2_name = _parse_gpkg_path_and_layer(source_layer2)

        mem_limit_raw = self.parameterAsString(parameters, self.MEMORY_LIMIT, context)
        mem_limit = _validate_memory_limit(mem_limit_raw)

        feedback.pushInfo(
            f"[Main thread] Reading layers:\n"
            f"  Input: {gpkg_file1}  (layer: {layer1_name})\n"
            f"  Clip:  {gpkg_file2}  (layer: {layer2_name})"
        )

        # ── Step 1: read GeoDataFrames (CRS init — main thread only) ──
        gdf1 = self._pyogrio.read_dataframe(gpkg_file1, layer=layer1_name)
        gdf2 = self._pyogrio.read_dataframe(gpkg_file2, layer=layer2_name)
        feedback.pushInfo("[Main thread] Layers loaded.")

        # ── Step 2: connect SedonaDB ──
        feedback.pushInfo("[Main thread] Connecting SedonaDB engine…")
        sd = self._sedona_db.connect()
        sd.options.memory_limit              = mem_limit
        sd.options.memory_pool_type          = "fair"
        sd.options.unspillable_reserve_ratio = 0.2
        sd.options.temp_dir                  = tempfile.gettempdir()
        sd.sql("SET datafusion.execution.parquet.schema_force_view_types = false;")

        # ── Step 3: create_data_frame + to_view (to_arrow/CRS — main thread only) ──
        feedback.pushInfo("[Main thread] Registering views in SedonaDB…")
        df1 = sd.create_data_frame(gdf1)   # triggers gdf.to_arrow() → CRS.to_json_dict()
        df1.to_view("layer1")

        df2 = sd.create_data_frame(gdf2)
        df2.to_view("layer2")

        # ── Step 4: build and validate SELECT list ──
        select_parts: list[str] = []
        for col in df1.columns:
            _validate_identifier(col, "column")
            if col == "geometry":
                select_parts.append(
                    "ST_Intersection(l.geometry, r.geometry) AS geometry")
            else:
                select_parts.append(
                    f'l.{_quote_ident(col)} AS {_quote_ident(col.lower())}')

        self._sd          = sd
        self._select_cols = select_parts

        feedback.pushInfo("[Main thread] Preparation complete.")
        return True

    # ------------------------------------------------------------------
    # processAlgorithm — WORKER THREAD
    # Only sd.sql() and to_pyogrio() — no pyproj, no PROJ database access.
    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback) -> dict[str, Any]:
        if self._sd is None:
            raise QgsProcessingException(
                "Internal error: SedonaDB session not initialised.")

        output_file = self.parameterAsOutputLayer(parameters, self.OUTPUT_GPKG, context)

        if output_file and not output_file.lower().endswith('.gpkg'):
            raise QgsProcessingException("Output destination must use a .gpkg extension.")

        select_clause = ",\n                    ".join(self._select_cols)

        query = f"""
            SELECT
                {select_clause}
            FROM layer1 l
            INNER JOIN layer2 r
              ON ST_Intersects(l.geometry, r.geometry)
        """

        feedback.pushInfo("Executing spatial clip query…")

        if not output_file:
            output_file = os.path.join(tempfile.gettempdir(), "sedona_clip_output.gpkg")

        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        feedback.pushInfo(f"Streaming output to: {output_file}")
        self._sd.sql(query).to_pyogrio(output_file, driver="GPKG")

        feedback.pushInfo("Done.")
        return {self.OUTPUT_GPKG: output_file}

    def postProcessAlgorithm(self, context, feedback) -> dict:
        self._sd          = None
        self._select_cols = None
        self._sedona_db   = None
        self._pyogrio     = None
        return {}
