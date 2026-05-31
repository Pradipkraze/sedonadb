# SedonaDB QGIS Processing Plugin

High-performance, out-of-core spatial operations for QGIS 3.x and 4.x, powered by **SedonaDB**.

---

## Features

| Tool | Description |
|------|-------------|
| **Spatial Clip** | Trims Input Layer features to the exact boundaries of a Clip Layer (ST_Intersection inner join) |
| **Join Attributes by Location** | Appends Layer 2 attributes to Layer 1 features via a spatial LEFT JOIN with a configurable predicate |

Both tools:
- Operate entirely **out-of-core** — suitable for large datasets that don't fit in memory
- Accept layers loaded from the **QGIS Layers Panel**
- Require both inputs to be **GeoPackage (.gpkg)** files
- Stream output directly to a new GeoPackage on disk

---

## Requirements

```bash
pip install sedona pyogrio
```

Install inside the QGIS Python environment (OSGeo4W Shell on Windows, or the QGIS bundled Python on macOS/Linux).

---

## Installation

### Option A — Copy to QGIS plugins folder

1. Copy the entire `sedonadb/` folder to your QGIS plugins directory:

   | Platform | Path |
   |----------|------|
   | Windows  | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
   | macOS    | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |
   | Linux    | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |

2. Open QGIS → **Plugins → Manage and Install Plugins → Installed** → enable **SedonaDB Spatial Tools**.

3. The tools appear in **Processing Toolbox → SedonaDB Spatial Tools → Spatial Database Tools**.

### Option B — Install from ZIP

1. Zip the `sedonadb/` folder: `sedonadb.zip`
2. QGIS → **Plugins → Manage and Install Plugins → Install from ZIP**
3. Select `sedonadb.zip` → Install

---

## Usage

### Spatial Clip

| Parameter | Description |
|-----------|-------------|
| Input Layer | Layer whose features will be clipped (must be .gpkg) |
| Clip Layer | Bounding mask layer (must be .gpkg) |
| Memory Limit | SedonaDB memory cap, e.g. `2gb`, `8gb` |
| Output GeoPackage | Destination .gpkg file |

The tool performs an **INNER JOIN** on `ST_Intersects`, then replaces each geometry with `ST_Intersection(input, clip)`. All non-geometry attributes from the Input Layer are preserved.

### Join Attributes by Location

| Parameter | Description |
|-----------|-------------|
| Input Layer 1 | Left table — all features are always retained |
| Input Layer 2 | Right table — attributes joined from here |
| Spatial Predicate | Intersects / Within / Contains / Touches / Crosses |
| Memory Limit | SedonaDB memory cap |
| Output GeoPackage | Destination .gpkg file |

Performs a **LEFT JOIN**: every Layer 1 feature is present in the output. Layer 2 attributes are appended with a `_` prefix to avoid name collisions. Features with no spatial match receive `NULL` for all right-side columns.

---

## Adding New Algorithms

The plugin is designed to grow. To add a new algorithm:

1. Create `sedonadb/algorithms/my_new_tool.py` with a class that extends `QgsProcessingAlgorithm`.
2. Open `sedonadb/provider.py` and add two lines:

```python
# At the top of provider.py
from .algorithms.my_new_tool import MyNewToolAlgorithm

# Inside loadAlgorithms()
MyNewToolAlgorithm(),
```

3. Reload the plugin in QGIS (**Plugins → Manage and Install Plugins → Installed → Reload**).

---

## Bug Fixes vs Original Scripts

The following issue was corrected during packaging:

**`join_attribute_by_location.py`** — the original script contained a copy-paste bug where `layer2_name` was derived from `source_layer1` and `source_uri1` instead of their Layer 2 equivalents. This caused the tool to always read the same layer for both inputs. Fixed in `algorithms/join_attribute_by_location.py`.

---

## Project Structure

```
sedonadb/
├── __init__.py                         # QGIS plugin entry point
├── plugin.py                           # Plugin class — registers provider
├── provider.py                         # Processing provider — registers algorithms
├── metadata.txt                        # QGIS Plugin Manager metadata
├── icon.png                            # Toolbox icon
├── README.md                           # This file
└── algorithms/
    ├── __init__.py
    ├── clip.py                         # Spatial Clip algorithm
    ├── join_attribute_by_location.py   # Join Attributes by Location algorithm
    └── ...                             # Future algorithms go here
```

---

## License

MIT — see LICENSE file.
