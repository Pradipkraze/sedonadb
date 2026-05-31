# -*- coding: utf-8 -*-
"""
SedonaDB Plugin — Main Plugin Class
Registers the Processing Provider with QGIS.
Compatible with QGIS 3.x and QGIS 4.x.
"""


class SedonaDBPlugin:
    """
    Main plugin class instantiated by QGIS via classFactory().
    All QGIS imports are deferred into methods so that __init__.py
    remains importable even before the QGIS environment is fully ready.
    """

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initGui(self):
        """Called by QGIS when the plugin is loaded into the GUI."""
        self.initProcessing()

    def initProcessing(self):
        """Register the SedonaDB Processing provider."""
        from qgis.core import QgsApplication
        from .provider import SedonaDBProvider
        self.provider = SedonaDBProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        """Called by QGIS when the plugin is disabled/unloaded."""
        if self.provider:
            from qgis.core import QgsApplication
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
