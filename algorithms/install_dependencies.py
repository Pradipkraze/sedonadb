"""
SedonaDB Install Dependencies — algorithms/install_dependencies.py

Installs sedonadb and pyogrio into the QGIS Python environment by
invoking the OSGeo4W pip wrapper (o4w_env.bat + python -m pip) on
Windows, and the QGIS-bundled python3 executable on macOS/Linux.

Package name note
-----------------
The correct PyPI package is 'sedonadb'.
pip install sedonadb  →  import sedona.db

Design decisions
----------------
• --user is passed by default so pip never needs admin/write access to
  the system site-packages directory (OSGeo4W's site-packages is
  typically read-only for normal users).
• No shell=True subprocess calls with user-supplied strings — all
  subprocess arguments are passed as a list, never a joined string.
• The package list is hardcoded — users cannot inject arbitrary package
  names or flags via the UI.  The "Extra pip flags" parameter is
  validated against a strict allowlist of known-safe tokens.
• OSGeo4W paths are located programmatically (sys.prefix), not from
  user input.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterString,
)

# ---------------------------------------------------------------------------
# Packages to install (hardcoded — not user-controlled)
# ---------------------------------------------------------------------------
_PACKAGES = [
    "sedonadb",
    "pyogrio",
]

# ---------------------------------------------------------------------------
# Allowlist for optional extra pip flags.
# Only the tokens in this set are accepted; anything else is rejected.
# ---------------------------------------------------------------------------
_ALLOWED_FLAG_TOKENS: frozenset[str] = frozenset({
    "--upgrade",
    "--force-reinstall",
    "--no-cache-dir",
    "--pre",
    "--quiet",
    "-q",
    "--verbose",
    "-v",
    "--user",          # explicit user-install (default behaviour)
    "--no-user",       # override if caller has write access to site-packages
})

_SIMPLE_VERSION_RE = re.compile(r'^[\w\.\-\+]+$')   # used to validate version pins if added later


def _validate_extra_flags(raw: str) -> list[str]:
    """Parse and validate extra pip flag tokens.  Raises on any unknown token."""
    tokens = raw.split()
    bad = [t for t in tokens if t not in _ALLOWED_FLAG_TOKENS]
    if bad:
        raise QgsProcessingException(
            f"Disallowed pip flag(s): {bad}.  "
            f"Permitted flags: {sorted(_ALLOWED_FLAG_TOKENS)}"
        )
    return tokens


# ---------------------------------------------------------------------------
# Algorithm
# ---------------------------------------------------------------------------

class SedonaInstallDependenciesAlgorithm(QgsProcessingAlgorithm):
    """
    Installs sedona and pyogrio into the active QGIS Python environment
    using the OSGeo4W Shell pip wrapper (Windows) or the QGIS-bundled
    python3 (macOS / Linux).

    Run this tool once after installing the plugin if the Processing
    algorithms report missing libraries.
    """

    UPGRADE_FLAG  = 'UPGRADE_FLAG'
    EXTRA_FLAGS   = 'EXTRA_FLAGS'
    OUTPUT_LOG    = 'OUTPUT_LOG'

    # ------------------------------------------------------------------
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SedonaInstallDependenciesAlgorithm()

    def name(self):
        return 'sedonainstalldependencies'

    def displayName(self):
        return self.tr('Install SedonaDB Dependencies')

    def group(self):
        return self.tr('SedonaDB Spatial Tools')

    def groupId(self):
        return 'sedonadb_spatial_tools'

    def shortHelpString(self):
        return self.tr(
            "Installs the Python libraries required by SedonaDB Spatial Tools:\n"
            "  • sedonadb  (installs sedona.db — the SedonaDB engine)\n"
            "  • pyogrio\n\n"
            "Packages are installed with --user so no administrator rights or "
            "write access to the system site-packages directory is required.\n\n"
            "On Windows the OSGeo4W Python executable is used so packages land "
            "in the correct QGIS Python environment.\n\n"
            "On macOS / Linux the QGIS-bundled python3 executable is used.\n\n"
            "Tick 'Upgrade existing packages' to pass --upgrade to pip.\n\n"
            "You only need to run this once after installing the plugin. "
            "Restart QGIS afterwards."
        )

    def flags(self):
        # Mark as not thread-safe — pip modifies the file system and must
        # not run concurrently with other Processing jobs.
        return (
            super().flags()
            | QgsProcessingAlgorithm.FlagNoThreading
        )

    # ------------------------------------------------------------------
    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.UPGRADE_FLAG,
                self.tr('Upgrade existing packages (--upgrade)'),
                defaultValue=False,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.EXTRA_FLAGS,
                self.tr(
                    'Extra pip flags (optional)\n'
                    '--user is applied automatically. '
                    'Use --no-user to override (requires write access to site-packages).\n'
                    f'Allowed: {", ".join(sorted(_ALLOWED_FLAG_TOKENS))}'
                ),
                defaultValue='',
                optional=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_LOG,
                self.tr('Installation log'),
            )
        )

    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        upgrade   = self.parameterAsBoolean(parameters, self.UPGRADE_FLAG, context)
        extra_raw = self.parameterAsString(parameters, self.EXTRA_FLAGS, context).strip()

        # ---- Validate extra flags (allowlist) ------------------------
        extra_flags: list[str] = []
        if extra_raw:
            extra_flags = _validate_extra_flags(extra_raw)

        # ---- Locate the Python executable to use --------------------
        python_exe, env = _find_python_exe(feedback)

        # ---- Build pip command (list form — no shell=True) ----------
        # --user is always included: OSGeo4W's system site-packages is
        # typically not writable by normal users, so without --user pip
        # falls back to a user install anyway but prints a noisy warning.
        # Making it explicit suppresses the warning and is the correct
        # approach for a per-user QGIS plugin dependency.
        # Pass --no-user in Extra Flags to override (e.g. when running as admin).
        use_user = "--no-user" not in extra_flags
        base_cmd = [python_exe, "-m", "pip", "install"]
        if use_user:
            base_cmd.append("--user")
        if upgrade:
            base_cmd.append("--upgrade")
        # Remove --user from extra_flags if caller already specified it
        # (avoid duplicate) — and strip --no-user since we handled it above.
        filtered_extra = [f for f in extra_flags if f not in ("--user", "--no-user")]
        base_cmd.extend(filtered_extra)
        base_cmd.extend(_PACKAGES)          # hardcoded package list

        feedback.pushInfo(f"Python executable : {python_exe}")
        feedback.pushInfo(f"Packages to install: {', '.join(_PACKAGES)}")
        feedback.pushInfo(f"Command: {' '.join(base_cmd)}\n")

        # ---- Run installation ---------------------------------------
        log_lines: list[str] = []
        try:
            proc = subprocess.Popen(
                base_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                # shell=False is the default — explicit for clarity
                shell=False,
            )
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                feedback.pushInfo(line)
                log_lines.append(line)

            proc.wait()
        except FileNotFoundError as exc:
            raise QgsProcessingException(
                f"Could not find Python executable '{python_exe}': {exc}\n"
                "Please ensure QGIS is installed via OSGeo4W (Windows) or "
                "that the QGIS-bundled Python is accessible."
            ) from exc
        except OSError as exc:
            raise QgsProcessingException(
                f"Failed to launch pip: {exc}"
            ) from exc

        # ---- Check return code --------------------------------------
        if proc.returncode != 0:
            raise QgsProcessingException(
                f"pip exited with code {proc.returncode}. "
                "See the log above for details."
            )

        feedback.pushInfo("\nInstallation complete.")
        feedback.pushInfo(
            "Restart QGIS (or reload the plugin) for the new libraries to take effect."
        )

        return {self.OUTPUT_LOG: "\n".join(log_lines)}


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _find_python_exe(feedback) -> tuple[str, dict | None]:
    """Return (python_executable_path, env_dict_or_None).

    On Windows we try to find the OSGeo4W python.exe that ships with QGIS.
    On other platforms we return sys.executable (the QGIS-bundled Python).
    """
    if platform.system() == "Windows":
        return _find_osgeo4w_python(feedback)
    else:
        return sys.executable, None


def _find_osgeo4w_python(feedback) -> tuple[str, dict | None]:
    """Locate python.exe inside the OSGeo4W installation that hosts QGIS.

    Strategy (in order of preference):
    1. Walk up from sys.prefix looking for an OSGeo4W shell script alongside
       a python.exe — this works for default %OSGEO4W_ROOT% layouts.
    2. Fall back to sys.executable (the currently running Python), which is
       always the right interpreter even if it is not inside a classic
       OSGeo4W tree.
    """
    # sys.prefix for a typical OSGeo4W QGIS install is something like:
    #   C:\Program Files\QGIS 3.x\apps\Python312
    # We walk up looking for a sibling python.exe or o4w_env.bat.
    candidates = [sys.prefix]
    parent = os.path.dirname(sys.prefix)
    if parent != sys.prefix:
        candidates.append(parent)

    for root in candidates:
        # Direct python.exe in or next to the prefix
        for subdir in ("", "bin", "Scripts"):
            exe = os.path.join(root, subdir, "python.exe")
            if os.path.isfile(exe):
                feedback.pushInfo(f"[OSGeo4W] Found python.exe: {exe}")
                return exe, _osgeo4w_env(root)

    # Last resort — the currently running interpreter.  This is always
    # correct; it may just not be the OSGeo4W flavour.
    feedback.pushInfo(
        f"[OSGeo4W] Could not locate a separate python.exe; "
        f"using the running interpreter: {sys.executable}"
    )
    return sys.executable, None


def _osgeo4w_env(osgeo4w_root: str) -> dict:
    """Build a minimal environment dict that mimics what o4w_env.bat sets,
    so that pip can find the right site-packages.  We inherit the current
    environment and add/override only the essential variables."""
    env = os.environ.copy()
    env["OSGEO4W_ROOT"] = osgeo4w_root

    # Ensure the OSGeo4W bin directories are on PATH
    extra_paths = [
        os.path.join(osgeo4w_root, "bin"),
        os.path.join(osgeo4w_root, "apps", "grass", "grass-8.4", "lib"),
    ]
    existing_path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join(
        p for p in extra_paths if os.path.isdir(p)
    ) + (os.pathsep + existing_path if existing_path else "")

    return env
