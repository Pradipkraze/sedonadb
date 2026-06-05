# SedonaDB Spatial Tools — QGIS Plugin

High-performance, out-of-core spatial operations for QGIS 3 and QGIS 4, powered by **SedonaDB**.

---

## Features

| Tool | Description |
|------|-------------|
| **Spatial Clip** | Clips an input GeoPackage layer to the exact boundaries of a clip layer using `ST_Intersection`. |
| **Join Attributes by Location** | Spatial left-join that appends attributes from a second layer onto matched features of the first, with a configurable spatial predicate. |
| **Install SedonaDB Dependencies** | Installs `sedona` and `pyogrio` into the active QGIS Python environment via pip (OSGeo4W Shell on Windows). |

All tools operate exclusively on **GeoPackage (`.gpkg`)** layers and stream results directly to disk — no full dataset needs to fit in RAM.

---

## Requirements

- QGIS 3.0 or later (including QGIS 4.x)
- Python packages: `sedona`, `pyogrio`  
  *(install these using the bundled **Install SedonaDB Dependencies** tool)*

---

## Installation

### Method 1 — QGIS Plugin Manager (recommended)

1. In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP**.
2. Select `sedonadb.zip` and click **Install Plugin**.
3. Enable *SedonaDB Spatial Tools* in the Installed tab.

### Method 2 — Manual

1. Extract `sedonadb.zip` into your QGIS plugins folder:
   - **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
2. Restart QGIS, then enable the plugin via **Plugins → Manage and Install Plugins**.

---

## First-Time Setup — Installing Dependencies

After enabling the plugin, install the required Python libraries once:

1. Open **Processing Toolbox** (`Ctrl+Alt+T`).
2. Expand **SedonaDB Spatial Tools**.
3. Double-click **Install SedonaDB Dependencies**.
4. Optionally tick *Upgrade existing packages* if you need the latest versions.
5. Click **Run** and wait for the log to show `Installation complete.`
6. **Restart QGIS** for the new libraries to take effect.

### Windows — OSGeo4W note

The installer locates the OSGeo4W `python.exe` that ships with your QGIS installation automatically (walks up from `sys.prefix`). No manual path configuration is required. If the automatic detection fails, the tool falls back to the currently running Python interpreter, which is always correct.

---

## Usage

### Spatial Clip

1. Load two GeoPackage layers into the QGIS Layers Panel.
2. Open **SedonaDB Spatial Tools → Spatial Clip (GPKG Only)**.
3. Select the *Input Layer* (features to trim) and the *Clip Layer* (bounding mask).
4. Set a *Memory Limit* (e.g. `4gb`) appropriate to your dataset size.
5. Choose an output `.gpkg` path and click **Run**.

### Join Attributes by Location

1. Load two GeoPackage layers into the Layers Panel.
2. Open **SedonaDB Spatial Tools → Join Attributes by Location (GPKG Only)**.
3. Select *Input Layer 1* (left table) and *Input Layer 2* (right table — attributes joined from here).
4. Choose a *Spatial Predicate* (`Intersects`, `Within`, `Contains`, `Touches`, `Crosses`).
5. Set a *Memory Limit*, choose an output path, and click **Run**.

Right-side columns are prefixed with `_` in the output to avoid name collisions with left-side columns.

---

## Security Notes

All three algorithms apply the following protections against SQL injection:

- **Column names** are validated against a strict allowlist regex (`[\w\s\-\.]+`) before any SQL use.  
- **All SQL identifiers** (column names, aliases) are double-quoted and inner double-quotes are escaped per the SQL standard.  
- **The spatial predicate** is resolved from a hardcoded `dict` keyed by enum index — user input never reaches SQL text.  
- **Memory limit** is validated against the pattern `\d*(mb|gb)` — no free text can reach the engine options.  
- **Extra pip flags** (dependency installer) are validated against a fixed allowlist of known-safe tokens.  
- All `subprocess` calls use **list-form arguments** with `shell=False` — no user-supplied strings are shell-interpolated.

---

## Compatibility

| QGIS Version | Status |
|---|---|
| QGIS 3.x (3.0 – 3.x) | ✅ Supported |
| QGIS 4.x | ✅ Supported (`qgisMaximumVersion=4.99` in metadata) |

The plugin uses only stable, version-agnostic QGIS Processing API (`QgsProcessingAlgorithm`, `QgsProcessingProvider`) and carries no deprecated API calls.

---

## Troubleshooting

**"Required libraries missing" error**  
Run *Install SedonaDB Dependencies* and restart QGIS.

**"Validation Error: Layer is not a GeoPackage layer"**  
Only `.gpkg` layers loaded via the OGR provider are accepted. Convert your data to GeoPackage first using **Vector → Data Management Tools → Convert Format**.

**pip exits with a non-zero code on Windows**  
Open an OSGeo4W Shell manually and run:  
```
python -m pip install sedona pyogrio
```
This surfaces the exact error message from pip.

**Plugin fails to load (`classFactory` error)**  
Check the QGIS Python error log (**Help → Debugging/Development Tools → Python Console**) for the underlying exception. The `classFactory` wrapper in `__init__.py` always re-raises with the original cause.
