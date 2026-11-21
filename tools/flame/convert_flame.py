"""Convert FLAME 2023 Open (and FLAME's vertex masks) into small binary files the
BarBot app loads for head-model fitting.

Usage (from this folder):
    .venv/bin/python -I convert_flame.py \
        ~/Downloads/FLAME2023Open/flame2023_Open.pkl \
        ~/Downloads/FLAME_masks/FLAME_masks.pkl

Writes into ios/BarBot/BarBot/HeadModel/:
    FLAMEHead.bin   average head, triangles, first N shape components (CC-BY-4.0, committed)
    FLAMEMasks.bin  named vertex groups (scalp, face, eyeballs, neck, ...) (not committed:
                    the masks download has no stated license, so it stays local)

All numbers are little-endian. FLAMEHead.bin:
    char[4]  "FLMH"
    uint32   version (1)
    uint32   vertex count V
    uint32   triangle count F
    uint32   shape component count K
    float32  template[V][3]          meters; x = left/right, y = up, z = toward the face
    uint32   triangles[F][3]
    float32  shape[K][V][3]          component-major; coefficients are ~N(0, 1)

FLAMEMasks.bin:
    char[4]  "FLMK"
    uint32   version (1)
    uint32   mask count M
    M times: uint8 name length, name bytes (ASCII), uint32 count, uint32 vertex indices[count]
"""

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I (isolated mode) leaves this folder off the path
import safe_pickle  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "ios" / "BarBot" / "BarBot" / "HeadModel"
SHAPE_COMPONENTS = 100  # FLAME 2023 Open has 300 shape + 100 expression; later ones barely matter


def convert_model(pkl_path: Path) -> Path:
    model = safe_pickle.load(pkl_path)
    template = np.asarray(model["v_template"], dtype=np.float32)  # (V, 3)
    faces = np.asarray(model["f"], dtype=np.uint32)  # (F, 3)
    shapedirs = np.asarray(model["shapedirs"], dtype=np.float32)  # (V, 3, 400)

    # The last 100 components are expressions (per the file's own metadata); take shape only.
    n_expr = int(model.get("supr_expression_metadata", {}).get("n_expr", 100))
    n_shape_available = shapedirs.shape[2] - n_expr
    k = min(SHAPE_COMPONENTS, n_shape_available)
    shape = np.ascontiguousarray(np.transpose(shapedirs[:, :, :k], (2, 0, 1)))  # (K, V, 3)

    v, f = template.shape[0], faces.shape[0]
    out = OUT_DIR / "FLAMEHead.bin"
    with open(out, "wb") as fh:
        fh.write(b"FLMH")
        fh.write(struct.pack("<IIII", 1, v, f, k))
        fh.write(template.astype("<f4").tobytes())
        fh.write(faces.astype("<u4").tobytes())
        fh.write(shape.astype("<f4").tobytes())

    print(f"{out.name}: {v} vertices, {f} triangles, {k} shape components "
          f"({out.stat().st_size / 1e6:.1f} MB)")
    return out


def convert_masks(pkl_path: Path) -> Path:
    masks = safe_pickle.load(pkl_path)
    out = OUT_DIR / "FLAMEMasks.bin"
    with open(out, "wb") as fh:
        fh.write(b"FLMK")
        fh.write(struct.pack("<II", 1, len(masks)))
        for name in sorted(masks):
            indices = np.asarray(masks[name], dtype=np.uint32)
            encoded = name.encode("ascii")
            fh.write(struct.pack("<B", len(encoded)))
            fh.write(encoded)
            fh.write(struct.pack("<I", len(indices)))
            fh.write(indices.astype("<u4").tobytes())
    print(f"{out.name}: {len(masks)} masks ({', '.join(sorted(masks))})")
    return out


def sanity_check(head_path: Path) -> None:
    """Re-read the file and check a few head sizes are believable."""
    data = head_path.read_bytes()
    v, f, k = struct.unpack_from("<III", data, 8)
    offset = 20
    template = np.frombuffer(data, "<f4", v * 3, offset).reshape(v, 3)
    offset += v * 3 * 4 + f * 3 * 4
    shape = np.frombuffer(data, "<f4", k * v * 3, offset).reshape(k, v, 3)

    def size(verts):
        width = verts[:, 0].max() - verts[:, 0].min()
        depth = verts[:, 2].max() - verts[:, 2].min()
        return width * 100, depth * 100

    w, d = size(template)
    print(f"average head: {w:.1f} cm wide (incl. ears), {d:.1f} cm front-to-back")
    for dial in range(2):
        for sign in (-2, 2):
            w, d = size(template + sign * shape[dial])
            print(f"  dial {dial + 1} at {sign:+d}: {w:.1f} cm wide, {d:.1f} cm front-to-back")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model_pkl", type=Path)
    parser.add_argument("masks_pkl", type=Path)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    head = convert_model(args.model_pkl.expanduser())
    convert_masks(args.masks_pkl.expanduser())
    sanity_check(head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
