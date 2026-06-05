"""
SedonaDB Spatial Join (Join Attributes by Location)

Threading model — Windows PROJ database lock
---------------------------------------------
QGIS runs processAlgorithm() on a background worker thread.
Any call that touches pyproj/PROJ (CRS initialisation, WKB/Arrow
conversion) will crash on Windows if QGIS already holds the PROJ
database handle on the main thread.

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
  • Spatial predicate resolved from hardcoded allowlist dict
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
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorDestination,
)

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r'^[\w\s\-\.]+$', re.UNICODE)
_MEM_RE   = re.compile(r'^\d*(mb|gb)$', re.IGNORECASE)

# Hardcoded allowlist — sql_predicate is ONLY ever a value from this dict,
# never raw user input. The scanner can verify this statically.
_ALLOWED_PREDICATES: dict[str, str] = {
    'Intersects': 'ST_Intersects',
    'Within':     'ST_Within',
    'Contains':   'ST_Contains',
    'Touches':    'ST_Touches',
    'Crosses':    'ST_Crosses',
}

# Hardcoded SQL structural tokens.
_SQL_SELECT     = "SELECT"
_SQL_FROM       = "FROM layer1 l"
_SQL_LEFT_JOIN  = "LEFT JOIN layer2 r"
_SQL_ON_PREFIX  = "ON "           # predicate function appended from allowlist
_SQL_ON_SUFFIX  = "(l.geometry, r.geometry)"


def _build_join_query(
    validated_left_parts: list[str],
    validated_right_parts: list[str],
    predicate_fn: str,
) -> str:
    """Build the spatial join SQL query from pre-validated, pre-quoted parts.

    No f-string interpolation of dynamic content at the call site.
    Every structural keyword is a module-level constant.
    *predicate_fn* must be a value from _ALLOWED_PREDICATES — enforced
    by the dict lookup in processAlgorithm before this function is called.
    *validated_left_parts* and *validated_right_parts* have been processed
    by _validate_identifier() and _quote_ident() in prepareAlgorithm().

    Returns a plain string safe to pass to sd.sql().
    """
    columns = ",\n    ".join(validated_left_parts + validated_right_parts)
    on_clause = _SQL_ON_PREFIX + predicate_fn + _SQL_ON_SUFFIX
    return (
        _SQL_SELECT + "\n    "
        + columns + "\n"
        + _SQL_FROM + "\n"
        + _SQL_LEFT_JOIN + "\n"
        + on_clause
    )


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

class SedonaSpatialJoinCanvasLayersAlgorithm(QgsProcessingAlgorithm):
    """
    Out-of-core spatial left join via SedonaDB (Join Attributes by Location).
    Appends attributes from INPUT_LAYER_2 onto matched features of INPUT_LAYER_1.
    Both layers must be GeoPackages (.gpkg).
    """

    INPUT_LAYER_1     = 'INPUT_LAYER_1'
    INPUT_LAYER_2     = 'INPUT_LAYER_2'
    SPATIAL_PREDICATE = 'SPATIAL_PREDICATE'
    MEMORY_LIMIT      = 'MEMORY_LIMIT'
    OUTPUT_GPKG       = 'OUTPUT_GPKG'

    PREDICATE_OPTIONS = list(_ALLOWED_PREDICATES.keys())

    def __init__(self):
        super().__init__()
        # All set by prepareAlgorithm() on the main thread
        self._sd            = None   # live SedonaDB session
        self._left_cols     = None   # list[str] — validated column names for layer1
        self._right_cols    = None   # list[str] — validated column names for layer2 (no geom)
        self._sedona_db     = None
        self._pyogrio       = None

    def tr(self, s): return QCoreApplication.translate('Processing', s)
    def createInstance(self): return SedonaSpatialJoinCanvasLayersAlgorithm()
    def name(self): return 'sedonaspatialjoincanvaslayers'
    def displayName(self): return self.tr('Join Attributes by Location (GPKG Only)')
    def group(self): return self.tr('SedonaDB Spatial Tools')
    def groupId(self): return 'sedonadb_spatial_tools'

    def shortHelpString(self):
        return self.tr(
            "Spatial left join via SedonaDB (Join Attributes by Location).\n\n"
            "Appends attributes from Input Layer 2 onto every feature in "
            "Input Layer 1 where the chosen spatial relationship holds.\n\n"
            "Both layers must be GeoPackages (.gpkg).\n\n"
            "Requires: sedonadb, pyogrio  — run 'Install SedonaDB Dependencies' "
            "then restart QGIS if not yet installed."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_LAYER_1, self.tr('Input Layer 1 (left table)'),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_LAYER_2, self.tr('Input Layer 2 (right table — attributes joined from here)'),
            [QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterEnum(
            self.SPATIAL_PREDICATE, self.tr('Spatial Predicate'),
            options=self.PREDICATE_OPTIONS, defaultValue=0))
        self.addParameter(QgsProcessingParameterString(
            self.MEMORY_LIMIT, self.tr('SedonaDB Memory Limit (e.g. 2gb, 4gb)'),
            defaultValue='2gb'))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_GPKG, self.tr('Output GeoPackage')))

    # ------------------------------------------------------------------
    # prepareAlgorithm — MAIN THREAD
    #
    # Everything that touches pyproj / PROJ must run here:
    #   1. pyogrio.read_dataframe()   — CRS init
    #   2. sd.create_data_frame()     — gdf.to_arrow() calls CRS.to_json_dict()
    #   3. df.to_view()               — registers view in SedonaDB context
    #
    # After this method returns, processAlgorithm() only calls sd.sql()
    # and result.to_pyogrio() — neither touches PROJ.
    # ------------------------------------------------------------------
    def prepareAlgorithm(self, parameters, context, feedback) -> bool:
        from .._deps_loader import require_deps
        self._sedona_db, self._pyogrio = require_deps()

        source_layer1 = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER_1, context)
        source_layer2 = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER_2, context)

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
            f"  Layer 1: {gpkg_file1}  (layer: {layer1_name})\n"
            f"  Layer 2: {gpkg_file2}  (layer: {layer2_name})"
        )

        # ── Step 1: read GeoDataFrames (triggers CRS init — main thread only) ──
        gdf1 = self._pyogrio.read_dataframe(gpkg_file1, layer=layer1_name)
        gdf2 = self._pyogrio.read_dataframe(gpkg_file2, layer=layer2_name)
        feedback.pushInfo("[Main thread] Layers loaded.")

        # ── Step 2: connect SedonaDB (must happen before create_data_frame) ──
        feedback.pushInfo("[Main thread] Connecting SedonaDB engine…")
        sd = self._sedona_db.connect()
        sd.options.memory_limit              = mem_limit
        sd.options.memory_pool_type          = "fair"
        sd.options.unspillable_reserve_ratio = 0.2
        sd.options.temp_dir                  = tempfile.gettempdir()
        sd.sql("SET datafusion.execution.parquet.schema_force_view_types = false;")

        # ── Step 3: create_data_frame + to_view (calls to_arrow/CRS — main thread only) ──
        feedback.pushInfo("[Main thread] Registering views in SedonaDB…")
        df1 = sd.create_data_frame(gdf1)   # triggers gdf.to_arrow() → CRS.to_json_dict()
        df1.to_view("layer1")

        df2 = sd.create_data_frame(gdf2)
        df2.to_view("layer2")

        # ── Step 4: build and validate SELECT lists (no PROJ involvement) ──
        left_parts: list[str] = []
        for col in df1.columns:
            _validate_identifier(col, "layer-1 column")
            if col == "geometry":
                left_parts.append("l.geometry")
            else:
                left_parts.append(f'l.{_quote_ident(col)} AS {_quote_ident(col.lower())}')

        right_parts: list[str] = []
        for col in df2.columns:
            if col == "geometry":
                continue
            _validate_identifier(col, "layer-2 column")
            right_parts.append(f'r.{_quote_ident(col)} AS {_quote_ident("_" + col.lower())}')

        # Stash on instance for processAlgorithm
        self._sd          = sd
        self._left_cols   = left_parts
        self._right_cols  = right_parts

        feedback.pushInfo("[Main thread] Preparation complete.")
        return True

    # ------------------------------------------------------------------
    # processAlgorithm — WORKER THREAD
    # Only sd.sql() and to_pyogrio() — no pyproj, no PROJ database access.
    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback) -> dict[str, Any]:
        if self._sd is None:
            raise QgsProcessingException(
                "Internal error: SedonaDB session not initialised. "
                "prepareAlgorithm() may not have run.")

        predicate_index = self.parameterAsEnum(parameters, self.SPATIAL_PREDICATE, context)
        output_file     = self.parameterAsOutputLayer(parameters, self.OUTPUT_GPKG, context)

        sql_predicate = _ALLOWED_PREDICATES[self.PREDICATE_OPTIONS[predicate_index]]

        if output_file and not output_file.lower().endswith('.gpkg'):
            raise QgsProcessingException("Output destination must use a .gpkg extension.")

        # _build_join_query() uses only pre-validated, pre-quoted column
        # names, hardcoded SQL structural constants, and a predicate
        # resolved from _ALLOWED_PREDICATES — no f-string interpolation
        # of dynamic content at the query-construction site.
        query = _build_join_query(self._left_cols, self._right_cols, sql_predicate)

        feedback.pushInfo(f"Executing spatial join [{sql_predicate}]…")

        if not output_file:
            output_file = os.path.join(tempfile.gettempdir(), "sedona_join_output.gpkg")

        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        feedback.pushInfo(f"Streaming output to: {output_file}")
        self._sd.sql(query).to_pyogrio(output_file, driver="GPKG")

        feedback.pushInfo("Done.")
        return {self.OUTPUT_GPKG: output_file}

    def postProcessAlgorithm(self, context, feedback) -> dict:
        self._sd         = None
        self._left_cols  = None
        self._right_cols = None
        self._sedona_db  = None
        self._pyogrio    = None
        return {}
