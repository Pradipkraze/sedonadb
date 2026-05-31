# -*- coding: utf-8 -*-
"""
SedonaDB QGIS Processing Plugin
Compatible with QGIS 3.x and QGIS 4.x
"""

# classFactory MUST be importable with zero side-effects.
# All heavy imports (qgis.core, provider, algorithms) are deferred
# into plugin.py so that a missing optional dependency cannot prevent
# QGIS from finding this function.

def classFactory(iface):
    from .plugin import SedonaDBPlugin
    return SedonaDBPlugin(iface)
