"""
SedonaDB Spatial Tools — plugin.py
Registers and unregisters the Processing provider.

All imports of plugin-local modules use importlib with absolute names to
avoid relative-import timing issues on Windows (QGIS 3.44 / Python 3.12).
"""

import importlib

from qgis.core import QgsApplication


class SedonaDBPlugin:
    """QGIS Plugin implementation."""

    def __init__(self, iface):
        self.iface = iface
        self._provider = None

    # ------------------------------------------------------------------
    # QGIS plugin lifecycle
    # ------------------------------------------------------------------

    def initGui(self):  # noqa: N802
        """Called by QGIS after the plugin is enabled."""
        try:
            provider_module = importlib.import_module("sedonadb_plugin.provider")
            SedonaDBProvider = getattr(provider_module, "SedonaDBProvider")
            self._provider = SedonaDBProvider()
            QgsApplication.processingRegistry().addProvider(self._provider)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.iface.messageBar().pushWarning(
                "SedonaDB Spatial Tools",
                f"Provider registration failed: {exc}",
            )

    def unload(self):
        """Called by QGIS when the plugin is disabled or QGIS closes."""
        if self._provider is not None:
            try:
                QgsApplication.processingRegistry().removeProvider(self._provider)
            except Exception:
                pass
            self._provider = None
