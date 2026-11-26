"""SQLite3 persistence layer for Atelier Tile: renders, room_analyses, and tiles catalog."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_DIR = Path(__file__).resolve().parent
BASE_DIR = DB_DIR.parent
DB_PATH = DB_DIR / "atelier_tile.db"
MODELS_DIR = BASE_DIR / "Models"

SEED_TILES = [
    {
        "sku_code": "AT-6012-STD",
        "name": "Classic 600x1200 Porcelain",
        "category": "Porcelain",
        "swatch_filename": "600X1200(1:2).jpg",
        "size_mm": "600x1200 mm",
        "finish": "matt",
        "tiles_per_box": 2,
        "price_per_sqft": 68.0,
    },
    {
        "sku_code": "AT-6060-SQ",
        "name": "Square 600x600 Stone",
        "category": "Stone",
        "swatch_filename": "600X600(1:1).jpg",
        "size_mm": "600x600 mm",
        "finish": "matt",
        "tiles_per_box": 4,
        "price_per_sqft": 54.0,
    },
    {
        "sku_code": "AT-1218-SLAB",
        "name": "Grand 1200x1800 Slab",
        "category": "Marble",
        "swatch_filename": "1200X1800(2:3).jpg",
        "size_mm": "1200x1800 mm",
        "finish": "high glossy",
        "tiles_per_box": 1,
        "price_per_sqft": 125.0,
    },
    {
        "sku_code": "AT-2012-PLK",
        "name": "Slim 200x1200 Plank",
        "category": "Wood Plank",
        "swatch_filename": "200X1200(1:6).jpg",
        "size_mm": "200x1200 mm",
        "finish": "matt",
        "tiles_per_box": 6,
        "price_per_sqft": 72.0,
    },
    {
        "sku_code": "AT-8024-SLB",
        "name": "Tall 800x2400 Architectural",
        "category": "Architectural",
        "swatch_filename": "800X2400(1:3).jpg",
        "size_mm": "800x2400 mm",
        "finish": "glossy",
        "tiles_per_box": 1,
        "price_per_sqft": 140.0,
    },
]


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Create tables if missing and seed initial showroom catalog tiles."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS renders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                scene TEXT,
                output_filename TEXT NOT NULL,
                output_image_path TEXT NOT NULL,
                floor_size TEXT,
                floor_finish TEXT,
                floor_orientation TEXT,
                floor_pattern TEXT,
                floor_grout_width TEXT,
                floor_grout_color TEXT,
                wall_size TEXT,
                wall_finish TEXT,
                wall_orientation TEXT,
                wall_pattern TEXT,
                wall_grout_width TEXT,
                wall_grout_color TEXT,
                aspect_ratio TEXT,
                sync_grout INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS room_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                image_hash TEXT,
                detected_scene TEXT,
                style TEXT,
                lighting_tone TEXT,
                dominant_colors_json TEXT,
                recommendations_json TEXT
            );

            CREATE TABLE IF NOT EXISTS tiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku_code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT,
                swatch_filename TEXT NOT NULL,
                size_mm TEXT NOT NULL,
                finish TEXT DEFAULT 'matt',
                tiles_per_box INTEGER DEFAULT 2,
                price_per_sqft REAL DEFAULT 0.0,
                created_at TEXT NOT NULL
            );
            """
        )

        count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        if count == 0:
            now = datetime.utcnow().isoformat()
            for item in SEED_TILES:
                swatch_file = MODELS_DIR / item["swatch_filename"]
                if swatch_file.exists():
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tiles
                        (sku_code, name, category, swatch_filename, size_mm, finish, tiles_per_box, price_per_sqft, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["sku_code"],
                            item["name"],
                            item["category"],
                            item["swatch_filename"],
                            item["size_mm"],
                            item["finish"],
                            item["tiles_per_box"],
                            item["price_per_sqft"],
                            now,
                        ),
                    )


def save_render(record: Dict[str, Any], db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO renders (
                created_at, scene, output_filename, output_image_path,
                floor_size, floor_finish, floor_orientation, floor_pattern, floor_grout_width, floor_grout_color,
                wall_size, wall_finish, wall_orientation, wall_pattern, wall_grout_width, wall_grout_color,
                aspect_ratio, sync_grout
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                record.get("scene"),
                record["output_filename"],
                record["output_image_path"],
                record.get("floor_size"),
                record.get("floor_finish"),
                record.get("floor_orientation"),
                record.get("floor_pattern"),
                record.get("floor_grout_width"),
                record.get("floor_grout_color"),
                record.get("wall_size"),
                record.get("wall_finish"),
                record.get("wall_orientation"),
                record.get("wall_pattern"),
                record.get("wall_grout_width"),
                record.get("wall_grout_color"),
                record.get("aspect_ratio"),
                1 if record.get("sync_grout") else 0,
            ),
        )
        return cur.lastrowid


def list_renders(limit: int = 20, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM renders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_render(render_id: int, db_path: Path = DB_PATH) -> bool:
    with get_connection(db_path) as conn:
        cur = conn.execute("DELETE FROM renders WHERE id = ?", (render_id,))
        return cur.rowcount > 0


def save_room_analysis(
    image_hash: str, data: Dict[str, Any], db_path: Path = DB_PATH
) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO room_analyses (
                created_at, image_hash, detected_scene, style, lighting_tone,
                dominant_colors_json, recommendations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.utcnow().isoformat(),
                image_hash,
                data.get("detected_scene"),
                data.get("style"),
                data.get("lighting_tone"),
                json.dumps(data.get("dominant_colors", [])),
                json.dumps(data.get("recommendations", [])),
            ),
        )
        return cur.lastrowid


def list_room_analyses(limit: int = 20, db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM room_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["dominant_colors"] = json.loads(d.pop("dominant_colors_json") or "[]")
            d["recommendations"] = json.loads(d.pop("recommendations_json") or "[]")
            results.append(d)
        return results


def list_tiles(db_path: Path = DB_PATH) -> List[Dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM tiles ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]


def add_tile(item: Dict[str, Any], db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO tiles (
                sku_code, name, category, swatch_filename, size_mm, finish, tiles_per_box, price_per_sqft, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["sku_code"],
                item["name"],
                item.get("category", "Custom"),
                item["swatch_filename"],
                item["size_mm"],
                item.get("finish", "matt"),
                int(item.get("tiles_per_box", 2)),
                float(item.get("price_per_sqft", 0.0)),
                datetime.utcnow().isoformat(),
            ),
        )
        return cur.lastrowid
