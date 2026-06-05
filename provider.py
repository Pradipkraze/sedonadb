"""
SedonaDB Spatial Tools — provider.py
Processing provider: registers all SedonaDB algorithms under one group.

Algorithm imports use importlib with hardcoded absolute package names.
Using __name__ to derive the package is unreliable on Windows when QGIS
loads the module before the package is fully initialised.
"""

import importlib
import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon


class SedonaDBProvider(QgsProcessingProvider):
    """Groups all SedonaDB Processing algorithms."""

    PROVIDER_ID = "sedonadb"

    # ------------------------------------------------------------------
    def id(self):  # noqa: A003
        return self.PROVIDER_ID

    def name(self):
        return "SedonaDB Spatial Tools"

    def longName(self):  # noqa: N802
        return "SedonaDB Spatial Tools"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.png")
        if os.path.isfile(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def loadAlgorithms(self):  # noqa: N802
        """Register algorithms.  Each is wrapped so one broken algorithm
        cannot prevent the others from loading."""
        _safe_add(self, "sedonadb_plugin.algorithms.clip",
                  "SedonaSpatialClipCanvasLayersAlgorithm")
        _safe_add(self, "sedonadb_plugin.algorithms.join_attribute_by_location",
                  "SedonaSpatialJoinCanvasLayersAlgorithm")
        _safe_add(self, "sedonadb_plugin.algorithms.install_dependencies",
                  "SedonaInstallDependenciesAlgorithm")

    def supportsNonFileBasedOutput(self):  # noqa: N802
        return False


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _safe_add(provider: QgsProcessingProvider, module_abs: str, class_name: str):
    """Import *class_name* from the absolute module path *module_abs* and
    add an instance to *provider*.  Prints a traceback and skips on error."""
    try:
        module = importlib.import_module(module_abs)
        cls = getattr(module, class_name)
        provider.addAlgorithm(cls())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[SedonaDB] Could not load {class_name} from {module_abs}: {exc}")
