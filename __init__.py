"""
SedonaDB Spatial Tools — QGIS Plugin
__init__.py

classFactory must be defined at module scope unconditionally.
We avoid relative imports here because on Windows / QGIS 3.44 the package
may not be fully initialised when QGIS first calls classFactory, causing
a half-initialised module where the function never gets bound.

Instead we use importlib with the absolute package name so Python resolves
the module independently of the package init state.
"""

import importlib
import os
import sys


def classFactory(iface):  # noqa: N802 — QGIS naming convention
    """Entry point called by QGIS to instantiate the plugin."""

    # Make sure the plugin directory is on sys.path so absolute imports work
    # even if QGIS hasn't added it yet (edge-case on some Windows installs).
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)

    try:
        # Use importlib with the full dotted name — avoids relative-import
        # timing issues on Windows where the package __init__ may not be
        # fully executed before classFactory is called.
        plugin_module = importlib.import_module("sedonadb_plugin.plugin")
        SedonaDBPlugin = getattr(plugin_module, "SedonaDBPlugin")
        return SedonaDBPlugin(iface)
    except Exception as exc:
        # Re-raise with a clear message so the QGIS error dialog is useful.
        import traceback
        tb = traceback.format_exc()
        raise RuntimeError(
            f"SedonaDB Spatial Tools — classFactory failed:\n{exc}\n\n{tb}"
        ) from exc
