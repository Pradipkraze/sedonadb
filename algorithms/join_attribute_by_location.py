# -*- coding: utf-8 -*-
"""
SedonaDB Spatial Join / Join Attributes by Location Algorithm
--------------------------------------------------------------
Executes an out-of-core spatial LEFT JOIN using SedonaDB.
Attributes from Layer 2 are appended to Layer 1 features based on a
chosen spatial predicate relationship.

Both layers must be GeoPackage (.gpkg) files loaded in the QGIS Layers Panel.

Compatible with QGIS 3.x and QGIS 4.x.

Bug-fix note (vs original script):
  The original script duplicated the layer1_name parse for both layers.
  layer2_name is now correctly derived from source_layer2 / source_uri2.
"""

import os
import tempfile

# Deferred imports isolate C-bindings and prevent PROJ database threading
# access violations on Windows when QGIS loads the plugin.
try:
    import sedona.db
    import pyogrio
except ImportError:
    pass

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingParameterVectorDestination,
)


class SedonaSpatialJoinCanvasLayersAlgorithm(QgsProcessingAlgorithm):
    """
    Spatial Join (Join Attributes by Location) powered by SedonaDB.

    Performs a LEFT JOIN: every feature in Layer 1 is retained; attributes
    from Layer 2 are appended where the chosen spatial predicate is satisfied.
    Right-side attributes are prefixed with '_' to avoid column-name clashes.
    """

    # ── Parameter keys ────────────────────────────────────────────────────────
    INPUT_LAYER_1    = 'INPUT_LAYER_1'
    INPUT_LAYER_2    = 'INPUT_LAYER_2'
    SPATIAL_PREDICATE = 'SPATIAL_PREDICATE'
    MEMORY_LIMIT     = 'MEMORY_LIMIT'
    OUTPUT_GPKG      = 'OUTPUT_GPKG'
    # ─────────────────────────────────────────────────────────────────────────

    # Dropdown options and their corresponding SedonaDB SQL functions
    PREDICATE_OPTIONS = ['Intersects', 'Within', 'Contains', 'Touches', 'Crosses']
    PREDICATE_MAPPING = {
        'Intersects': 'ST_Intersects',
        'Within':     'ST_Within',
        'Contains':   'ST_Contains',
        'Touches':    'ST_Touches',
        'Crosses':    'ST_Crosses',
    }

    # ── QgsProcessingAlgorithm identity ──────────────────────────────────────
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SedonaSpatialJoinCanvasLayersAlgorithm()

    def name(self):
        return 'sedonaspatialjoincanvaslayers'

    def displayName(self):
        return self.tr('Join Attributes by Location (GPKG Only)')

    def group(self):
        return self.tr('Spatial Database Tools')

    def groupId(self):
        return 'database_tools'

    def shortHelpString(self):
        return self.tr(
            "Executes a high-performance spatial LEFT JOIN using SedonaDB.\n\n"
            "Appends attributes from Layer 2 to every feature in Layer 1 where the "
            "chosen spatial predicate is satisfied. Right-side columns are prefixed "
            "with '_' to avoid name collisions.\n\n"
            "Both layers must be GeoPackage (.gpkg) files loaded in the QGIS Layers Panel.\n\n"
            "Spatial predicates: Intersects · Within · Contains · Touches · Crosses\n\n"
            "Requirements: sedona, pyogrio  (pip install sedona pyogrio)"
        )
    # ─────────────────────────────────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        # Left table
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER_1,
                self.tr('Input Layer 1 (Left Table)'),
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )
        # Right table
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER_2,
                self.tr('Input Layer 2 (Right Table — attributes joined from here)'),
                [QgsProcessing.TypeVectorAnyGeometry],
            )
        )
        # Spatial predicate dropdown
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SPATIAL_PREDICATE,
                self.tr('Spatial Predicate'),
                options=self.PREDICATE_OPTIONS,
                defaultValue=0,
            )
        )
        # SedonaDB memory limit
        self.addParameter(
            QgsProcessingParameterString(
                self.MEMORY_LIMIT,
                self.tr('SedonaDB Memory Limit (e.g. 2gb, 4gb)'),
                defaultValue='2gb',
            )
        )
        # Output GeoPackage destination
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT_GPKG,
                self.tr('Output GeoPackage'),
            )
        )

    # ── Core processing ───────────────────────────────────────────────────────
    def processAlgorithm(self, parameters, context, feedback):
        # Dependency check
        if 'sedona' not in globals() or 'pyogrio' not in globals():
            raise QgsProcessingException(
                "Required libraries missing. "
                "Install them with: pip install sedona pyogrio"
            )

        # Resolve parameters
        source_layer1    = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER_1, context)
        source_layer2    = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER_2, context)
        predicate_index  = self.parameterAsEnum(parameters, self.SPATIAL_PREDICATE, context)
        mem_limit        = self.parameterAsString(parameters, self.MEMORY_LIMIT, context)
        output_file      = self.parameterAsOutputLayer(parameters, self.OUTPUT_GPKG, context)

        if not source_layer1 or not source_layer2:
            raise QgsProcessingException("Invalid input layers selected.")

        # Map enum index → SQL predicate function
        selected_predicate = self.PREDICATE_OPTIONS[predicate_index]
        sql_predicate      = self.PREDICATE_MAPPING[selected_predicate]

        # ── GeoPackage validation ─────────────────────────────────────────────
        source_uri1, provider1 = source_layer1.source(), source_layer1.providerType()
        if provider1 != 'ogr' or '.gpkg' not in source_uri1.lower():
            raise QgsProcessingException(
                f"Validation Error: Layer '{source_layer1.name()}' is not a GeoPackage layer. "
                f"Detected provider: '{provider1}'."
            )

        source_uri2, provider2 = source_layer2.source(), source_layer2.providerType()
        if provider2 != 'ogr' or '.gpkg' not in source_uri2.lower():
            raise QgsProcessingException(
                f"Validation Error: Layer '{source_layer2.name()}' is not a GeoPackage layer. "
                f"Detected provider: '{provider2}'."
            )

        if output_file and not output_file.lower().endswith('.gpkg'):
            raise QgsProcessingException(
                "Output destination must use a .gpkg extension."
            )
        # ─────────────────────────────────────────────────────────────────────

        # Parse file paths and layer names
        gpkg_file1  = source_uri1.split('|')[0]
        layer1_name = self._parse_layer_name(source_layer1, source_uri1)

        gpkg_file2  = source_uri2.split('|')[0]
        # BUG FIX: original code re-used source_layer1/source_uri1 here
        layer2_name = self._parse_layer_name(source_layer2, source_uri2)

        feedback.pushInfo("Initializing SedonaDB engine connection...")

        # Configure SedonaDB session
        sd = sedona.db.connect()
        sd.options.memory_limit              = mem_limit
        sd.options.memory_pool_type          = 'fair'
        sd.options.unspillable_reserve_ratio = 0.2
        sd.options.temp_dir                  = tempfile.gettempdir()
        sd.sql("SET datafusion.execution.parquet.schema_force_view_types = false;")

        feedback.pushInfo(
            f"Validated layers:\n"
            f"  Layer 1 (left) : {gpkg_file1}  (layer: {layer1_name})\n"
            f"  Layer 2 (right): {gpkg_file2}  (layer: {layer2_name})\n"
            f"  Predicate      : {selected_predicate} → {sql_predicate}"
        )

        if feedback.isCanceled():
            return {}

        # Read GeoPackages via pyogrio
        input_layer1 = pyogrio.read_dataframe(gpkg_file1, layer=layer1_name)
        input_layer2 = pyogrio.read_dataframe(gpkg_file2, layer=layer2_name)

        df1 = sd.create_data_frame(input_layer1)
        df1.to_view("layer1")

        df2 = sd.create_data_frame(input_layer2)
        df2.to_view("layer2")

        # Dynamically build LEFT side SELECT (geometry kept as-is)
        layer1_parts = []
        for col in df1.columns:
            if col == 'geometry':
                layer1_parts.append('l.geometry')
            else:
                layer1_parts.append(f'l."{col}" AS "{col.lower()}"')
        layer1_select = ', '.join(layer1_parts)

        # Dynamically build RIGHT side SELECT (geometry excluded; columns prefixed with '_')
        layer2_parts = []
        for col in df2.columns:
            if col == 'geometry':
                continue
            layer2_parts.append(f'r."{col}" AS "_{col.lower()}"')
        layer2_select = ', '.join(layer2_parts)

        # Full SELECT clause — guard against empty right-side schema
        if layer2_select:
            full_select = f"{layer1_select}, {layer2_select}"
        else:
            full_select = layer1_select

        # Spatial LEFT JOIN
        query = f"""
            SELECT
                {full_select}
            FROM layer1 l
            LEFT JOIN layer2 r
                ON {sql_predicate}(l.geometry, r.geometry)
        """

        feedback.pushInfo("Executing spatial join query...")

        if feedback.isCanceled():
            return {}

        # Resolve output path
        if not output_file:
            output_file = os.path.join(
                tempfile.gettempdir(), 'sedona_join_output.gpkg'
            )

        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        feedback.pushInfo(f"Writing joined output to: {output_file}")

        sd.sql(query).to_pyogrio(output_file, driver='GPKG')

        feedback.pushInfo("Spatial join complete. Output registered with QGIS.")

        return {self.OUTPUT_GPKG: output_file}

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _parse_layer_name(layer, uri):
        """Extract the layer name from a QGIS datasource URI."""
        if 'layername=' in uri:
            return (
                layer.dataProvider()
                     .dataSourceUri()
                     .split('layername=')[-1]
                     .split('|')[0]
            )
        return layer.name()
