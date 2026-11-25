"""Build and query the tile size & aspect-ratio `.pkl` model from `Models/`."""

from __future__ import annotations

import math
import os
import pickle
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MODELS_DIR = BASE_DIR / "Models"
DEFAULT_GRID_REF_DIR = DEFAULT_MODELS_DIR / "Tile apply according to sized"
DEFAULT_PKL_PATH = DEFAULT_MODELS_DIR / "tile_size_model.pkl"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SIZE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*(?:\((\d+\s*:\s*\d+)\))?"
)


@dataclass
class TileSizeSpec:
    name: str
    filename: str
    filepath: str
    width_mm: int
    height_mm: int
    size_label: str
    aspect_ratio_label: str
    aspect_ratio: float
    image_width_px: int
    image_height_px: int
    tiles_per_meter_w: float
    tiles_per_meter_h: float
    orientation: str
    grid_reference_image: Optional[str] = None


def _simplify_ratio(w: int, h: int) -> str:
    divisor = math.gcd(w, h) or 1
    return f"{w // divisor}:{h // divisor}"


def _classify_orientation(w: int, h: int) -> str:
    if w == h:
        return "square"
    ratio = max(w, h) / max(1, min(w, h))
    if ratio >= 3.0:
        return "plank"
    return "rectangular"


def parse_mm_size(size_str: str) -> Optional[Tuple[int, int, Optional[str]]]:
    """Parse a tile size string like '600x1200 mm' or '1200X1800(2:3)'."""
    if not size_str:
        return None
    match = SIZE_PATTERN.search(size_str)
    if not match:
        return None
    w = int(round(float(match.group(1))))
    h = int(round(float(match.group(2))))
    if w <= 0 or h <= 0:
        return None
    ratio_str = match.group(3).replace(" ", "") if match.group(3) else None
    return w, h, ratio_str


def build_tile_size_pkl(
    models_dir: Path = DEFAULT_MODELS_DIR,
    pkl_path: Path = DEFAULT_PKL_PATH,
    grid_ref_dir: Path = DEFAULT_GRID_REF_DIR,
) -> Dict:
    """Scan `models_dir` and `grid_ref_dir` for tile models and serialize to `.pkl`."""
    specs_by_size: Dict[Tuple[int, int], Dict] = {}

    if not models_dir.exists():
        raise FileNotFoundError(f"Models directory not found: {models_dir}")

    # 1. Scan primary Models/ directory
    for entry in sorted(models_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        parsed = parse_mm_size(entry.stem)
        if not parsed:
            continue

        width_mm, height_mm, ratio_str = parsed
        if not ratio_str:
            ratio_str = _simplify_ratio(width_mm, height_mm)

        with Image.open(entry) as img:
            px_w, px_h = img.size

        spec = TileSizeSpec(
            name=entry.stem,
            filename=entry.name,
            filepath=str(entry),
            width_mm=width_mm,
            height_mm=height_mm,
            size_label=f"{width_mm}x{height_mm} mm",
            aspect_ratio_label=ratio_str,
            aspect_ratio=round(width_mm / height_mm, 6),
            image_width_px=px_w,
            image_height_px=px_h,
            tiles_per_meter_w=round(1000.0 / width_mm, 2),
            tiles_per_meter_h=round(1000.0 / height_mm, 2),
            orientation=_classify_orientation(width_mm, height_mm),
            grid_reference_image=None,
        )
        specs_by_size[(width_mm, height_mm)] = asdict(spec)

    # 2. Scan "Tile apply according to sized/" room-grid reference images
    if grid_ref_dir.exists():
        for entry in sorted(grid_ref_dir.iterdir()):
            if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTENSIONS:
                continue

            parsed = parse_mm_size(entry.stem)
            if not parsed:
                continue

            width_mm, height_mm, ratio_str = parsed
            if not ratio_str:
                ratio_str = _simplify_ratio(width_mm, height_mm)

            key = (width_mm, height_mm)
            if key in specs_by_size:
                specs_by_size[key]["grid_reference_image"] = str(entry)
            else:
                with Image.open(entry) as img:
                    px_w, px_h = img.size
                spec = TileSizeSpec(
                    name=entry.stem,
                    filename=entry.name,
                    filepath=str(entry),
                    width_mm=width_mm,
                    height_mm=height_mm,
                    size_label=f"{width_mm}x{height_mm} mm",
                    aspect_ratio_label=ratio_str,
                    aspect_ratio=round(width_mm / height_mm, 6),
                    image_width_px=px_w,
                    image_height_px=px_h,
                    tiles_per_meter_w=round(1000.0 / width_mm, 2),
                    tiles_per_meter_h=round(1000.0 / height_mm, 2),
                    orientation=_classify_orientation(width_mm, height_mm),
                    grid_reference_image=str(entry),
                )
                specs_by_size[key] = asdict(spec)

    specs = sorted(specs_by_size.values(), key=lambda t: (t["width_mm"], t["height_mm"]))

    payload = {
        "version": 2,
        "models_dir": str(models_dir),
        "grid_ref_dir": str(grid_ref_dir),
        "count": len(specs),
        "tiles": specs,
    }

    with open(pkl_path, "wb") as f:
        pickle.dump(payload, f)

    return payload


def load_tile_size_pkl(pkl_path: Path = DEFAULT_PKL_PATH) -> Dict:
    """Load `tile_size_model.pkl`, building it automatically if missing."""
    if not pkl_path.exists():
        return build_tile_size_pkl(pkl_path.parent, pkl_path)
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


def analyze_tile_size(
    size_input: str,
    orientation_mode: str = "horizontal",
    pkl_path: Path = DEFAULT_PKL_PATH,
) -> Dict:
    """
    Analyze a user-provided mm tile size against `tile_size_model.pkl`.

    Returns parsed dimensions, orientation-adjusted aspect ratio, 1-meter span
    tile counts, closest reference model in `Models/`, and a prompt-ready
    `count_check` string.
    """
    model_data = load_tile_size_pkl(pkl_path)
    tiles = model_data.get("tiles", [])

    parsed = parse_mm_size(size_input or "")
    if not parsed:
        return {
            "valid": False,
            "input": size_input,
            "size_label": size_input or "600x1200 mm",
            "aspect_ratio_label": "unknown",
            "count_check": "",
            "matched_model": None,
        }

    width_mm, height_mm, explicit_ratio = parsed
    short_mm = min(width_mm, height_mm)
    long_mm = max(width_mm, height_mm)
    if width_mm == height_mm:
        eff_w, eff_h = width_mm, height_mm
    elif orientation_mode == "vertical":
        eff_w, eff_h = short_mm, long_mm
    else:
        eff_w, eff_h = long_mm, short_mm

    ratio_label = explicit_ratio or _simplify_ratio(width_mm, height_mm)
    target_ratio = width_mm / height_mm
    tiles_w = round(1000.0 / eff_w, 2)
    tiles_h = round(1000.0 / eff_h, 2)
    orientation = _classify_orientation(width_mm, height_mm)

    exact_match = None
    closest_match = None
    best_distance = float("inf")

    for tile in tiles:
        if tile["width_mm"] == width_mm and tile["height_mm"] == height_mm:
            exact_match = tile
            closest_match = tile
            break
        # Prioritize aspect ratio match, then physical dimension proximity
        ratio_diff = abs(tile["aspect_ratio"] - target_ratio)
        dim_diff = (
            abs(tile["width_mm"] - width_mm) + abs(tile["height_mm"] - height_mm)
        ) / 2000.0
        score = ratio_diff * 10.0 + dim_diff
        if score < best_distance:
            best_distance = score
            closest_match = tile

    match_note = (
        f"Exact model match: {exact_match['filename']}"
        if exact_match
        else (
            f"Closest reference model: {closest_match['filename']} "
            f"(aspect {closest_match['aspect_ratio_label']})"
            if closest_match
            else "Custom dimensions"
        )
    )

    shape_rule = (
        "STRICTLY SQUARE (1:1)."
        if width_mm == height_mm
        else (
            f"STRICTLY RECTANGULAR {ratio_label} laid {orientation_mode.upper()} "
            f"({eff_w} mm left-to-right width x {eff_h} mm height/depth — "
            f"NEVER square and NEVER oversized mega-slabs)."
        )
    )
    tiles_4m_w = round(4000.0 / eff_w, 1)
    tiles_4m_h = round(4000.0 / eff_h, 1)

    count_check = (
        f"{shape_rule} "
        f"On any 1-meter (1000 mm) span, fit ~{tiles_w} tiles across width and ~{tiles_h} tiles across height/depth "
        f"(~{tiles_4m_w} x ~{tiles_4m_h} tiles across a 4-meter room span in true perspective). "
        f"[{match_note}]"
    )

    return {
        "valid": True,
        "input": size_input,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "size_label": f"{width_mm}x{height_mm} mm",
        "aspect_ratio_label": ratio_label,
        "aspect_ratio": round(target_ratio, 6),
        "tiles_per_meter_w": tiles_w,
        "tiles_per_meter_h": tiles_h,
        "orientation": orientation,
        "exact_match": exact_match is not None,
        "matched_model": closest_match,
        "count_check": count_check,
    }


def load_grid_reference_image(
    size_input: str,
    max_dim: int = 768,
    pkl_path: Path = DEFAULT_PKL_PATH,
) -> Optional[Tuple[Image.Image, str]]:
    """
    Load and resize the room-grid reference image from `Tile apply according to sized/`
    for the given `size_input` using `tile_size_model.pkl`.

    Returns `(PIL.Image, filename)` or `None` if unavailable.
    """
    info = analyze_tile_size(size_input, pkl_path=pkl_path)
    matched = info.get("matched_model")
    if not matched:
        return None
    ref_path_str = matched.get("grid_reference_image") or matched.get("filepath")
    if not ref_path_str:
        return None
    ref_path = Path(ref_path_str)
    if not ref_path.exists():
        return None

    img = Image.open(ref_path).convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    return img, ref_path.name


if __name__ == "__main__":
    result = build_tile_size_pkl()
    print(f"Built {DEFAULT_PKL_PATH} with {result['count']} tile models:")
    for t in result["tiles"]:
        print(
            f" - {t['filename']}: {t['size_label']} | ratio {t['aspect_ratio_label']} "
            f"| {t['tiles_per_meter_w']}x{t['tiles_per_meter_h']} per 1m | {t['orientation']}"
        )
