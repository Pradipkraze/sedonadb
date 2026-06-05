"""
SedonaDB — _deps_loader.py

Correct package / import name (confirmed from PyPI)
----------------------------------------------------
  pip install sedonadb          <- correct package name
  import sedona.db              <- correct import

Why this module exists
-----------------------
The top-level `try/except ImportError` in algorithm modules only fires
once at module import time. If the library wasn't installed when the
plugin first loaded, the name is absent from that module's namespace
forever until QGIS is restarted.

This module bypasses that by:
  1. Injecting the per-user site-packages dir into sys.path — pip --user
     puts packages there, but QGIS's embedded Python often omits it.
  2. Using importlib.import_module() which always reflects the current
     state of sys.modules / disk, bypassing the stale namespace.
"""

from __future__ import annotations

import importlib
import os
import site
import sys
import traceback

from qgis.core import QgsProcessingException


def _ensure_user_site_on_path() -> None:
    """Add per-user site-packages to sys.path if it isn't already present.

    pip --user on Windows installs to:
      %APPDATA%\\Python\\Python3XY\\site-packages
    QGIS's embedded Python typically does NOT include this path.
    """
    candidates: list[str] = []

    try:
        user_site = site.getusersitepackages()
        if user_site:
            candidates.append(user_site)
    except AttributeError:
        pass

    # Windows explicit fallback
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
            candidates.append(
                os.path.join(appdata, "Python", ver, "site-packages")
            )

    for path in candidates:
        if path and os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def _probe_sedona_db() -> tuple[object | None, str]:
    """Try to import sedona.db and return (module, error_detail).

    Returns (module, '') on success.
    Returns (None, detailed_error) on failure, including:
      - the original ImportError / ModuleNotFoundError message
      - the full traceback
      - what is actually present in the sedona package dir (if any)
    """
    try:
        mod = importlib.import_module("sedona.db")
        return mod, ""
    except Exception as exc:
        tb = traceback.format_exc()
        detail = f"{type(exc).__name__}: {exc}\n{tb}"

        # Extra diagnostic: check what's actually in sedona's package dir
        try:
            sedona_init = importlib.import_module("sedona")
            sedona_path = getattr(sedona_init, "__path__", ["<unknown>"])
            contents = []
            for p in sedona_path:
                if os.path.isdir(p):
                    contents.extend(os.listdir(p))
            detail += f"\nsedona package path: {list(sedona_path)}"
            detail += f"\nsedona package contents: {contents}"
        except Exception as sedona_exc:
            detail += f"\n(could not inspect sedona package: {sedona_exc})"

        return None, detail


def require_deps():
    """Return (sedona.db module, pyogrio module).

    pip install:  sedonadb
    import:       sedona.db

    On failure, raises QgsProcessingException with:
     - step-by-step fix instructions
     - the exact ImportError message and traceback
     - the contents of the sedona package directory (if partial install)
     - the full sys.path that was searched

    Safe to call multiple times — sys.modules caches successful imports.
    """
    _ensure_user_site_on_path()

    missing: list[str] = []
    import_errors: dict[str, str] = {}
    sedona_db_mod = None
    pyogrio_mod   = None

    sedona_db_mod, sedona_err = _probe_sedona_db()
    if sedona_db_mod is None:
        missing.append("sedonadb")
        import_errors["sedonadb"] = sedona_err

    try:
        pyogrio_mod = importlib.import_module("pyogrio")
    except Exception as exc:
        missing.append("pyogrio")
        import_errors["pyogrio"] = traceback.format_exc()

    if missing:
        searched = "\n".join(f"  {p}" for p in sys.path)
        noun = "library" if len(missing) == 1 else "libraries"

        err_details = ""
        for pkg, detail in import_errors.items():
            err_details += f"\n--- {pkg} import error ---\n{detail}\n"

        raise QgsProcessingException(
            f"Required {noun} not found: {', '.join(missing)}\n\n"
            "Steps to fix:\n"
            "  1. Open Processing Toolbox → SedonaDB Spatial Tools\n"
            "  2. Run 'Install SedonaDB Dependencies'\n"
            "  3. Wait for 'Installation complete' in the log\n"
            "  4. RESTART QGIS fully (close and reopen)\n"
            "  5. Run this tool again\n\n"
            f"sys.path searched:\n{searched}\n"
            f"{err_details}"
        )

    return sedona_db_mod, pyogrio_mod
