# -*- coding: utf-8 -*-
"""
SedonaDB Processing Provider
------------------------------
Registers all SedonaDB algorithms into the QGIS Processing Framework.

To add a new algorithm:
  1. Create a new file under algorithms/
  2. Import the class inside loadAlgorithms() below
  3. Add an instance of it to the algorithms list

Compatible with QGIS 3.x and QGIS 4.x.
"""

import os
from qgis.core import QgsProcessingProvider


class SedonaDBProvider(QgsProcessingProvider):
    """
    QGIS Processing Provider for SedonaDB spatial tools.
    All algorithms appear under 'Spatial Database Tools' in the Processing Toolbox.
    """

    def __init__(self):
        super().__init__()

    def id(self):
        return 'sedonadb'

    def name(self):
        return 'SedonaDB Spatial Tools'

    def longName(self):
        return 'SedonaDB — High-Performance Out-of-Core Spatial Operations'

    def versionInfo(self):
        return '1.0.0'

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        if os.path.exists(icon_path):
            from qgis.PyQt.QtGui import QIcon
            return QIcon(icon_path)
        return super().icon()

    def loadAlgorithms(self):
        """
        Register every algorithm this provider exposes.
        Imports are local so a broken algorithm file cannot prevent the
        provider (or other algorithms) from loading.

        To add a new algorithm:
          from .algorithms.my_tool import MyToolAlgorithm
          algorithms.append(MyToolAlgorithm())
        """
        algorithms = []

        try:
            from .algorithms.clip import SedonaSpatialClipCanvasLayersAlgorithm
            algorithms.append(SedonaSpatialClipCanvasLayersAlgorithm())
        except Exception as e:
            import traceback
            print(f"[SedonaDB] Could not load Clip algorithm: {e}\n{traceback.format_exc()}")

        try:
            from .algorithms.join_attribute_by_location import SedonaSpatialJoinCanvasLayersAlgorithm
            algorithms.append(SedonaSpatialJoinCanvasLayersAlgorithm())
        except Exception as e:
            import traceback
            print(f"[SedonaDB] Could not load Join algorithm: {e}\n{traceback.format_exc()}")

        # ── Future algorithms ──────────────────────────────────────────────────
        # try:
        #     from .algorithms.dissolve import SedonaDissolveAlgorithm
        #     algorithms.append(SedonaDissolveAlgorithm())
        # except Exception as e:
        #     print(f"[SedonaDB] Could not load Dissolve algorithm: {e}")
        # ──────────────────────────────────────────────────────────────────────

        for alg in algorithms:
            self.addAlgorithm(alg)

    def supportedOutputRasterLayerExtensions(self):
        return []
