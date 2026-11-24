# FLAME head model for BarBot

BarBot fits the **FLAME 2023 Open** head model to scans (`SCHeadModelFitting` in the
StandardCyborg fork). This folder converts FLAME's download into the small binary files
the app loads.

## Credit and license

FLAME 2023 Open is © Max Planck Institute for Intelligent Systems, released under the
[Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/)
(see https://flame.is.tue.mpg.de/modellicense.html). When reporting results, cite:

> T. Li, T. Bolkart, M. J. Black, H. Li and J. Romero. *Learning a model of facial shape
> and expression from 4D scans.* ACM Transactions on Graphics (Proc. SIGGRAPH Asia), 2017.

`FLAMEHead.bin` (converted from FLAME 2023 Open: average head, triangles, first 100 shape
components) is committed. `FLAMEMasks.bin` (vertex groups, from the separate "FLAME Vertex
Masks" download, which states no license) is **not** committed; regenerate it locally.

## Regenerating the files

1. Download from https://flame.is.tue.mpg.de/download.php (free registration):
   - **FLAME 2023 Open** → `FLAME2023Open/flame2023_Open.pkl`
   - **FLAME Vertex Masks** → `FLAME_masks/FLAME_masks.pkl`
2. Set up Python (once):
   ```
   cd tools/flame
   python3.11 -m venv .venv
   .venv/bin/pip install numpy scipy
   ```
3. Convert (writes into `ios/BarBot/Shared/HeadModel/`):
   ```
   .venv/bin/python -I convert_flame.py \
       ~/Downloads/FLAME2023Open/flame2023_Open.pkl \
       ~/Downloads/FLAME_masks/FLAME_masks.pkl
   ```

The `.pkl` files are loaded with `safe_pickle.py`, which only allows the numpy/scipy
array types these files use (a normal pickle load can run arbitrary code).
