# AGENT.md — Coding & Architecture Guide for AI Agents

This file documents conventions, contracts, and guardrails for AI agents modifying **AiPhotoGenerated**.

## Mandatory Workflow for Every New Feature or Change

1. **Read First**: Before implementing any new concept or change, read both `AGENT.md` and `BRAIN.md` (the architectural brain of the project) to understand existing contracts and design decisions.
2. **Update After**: Every time a new feature, endpoint, UI control, or concept is implemented, **update `AGENT.md` and `BRAIN.md`** in the same task so they always reflect the current state of the project.

## Tech Stack

- **Backend**: Python, Flask (`app.py`), SQLite3 (`database/__init__.py` -> `database/atelier_tile.db`), Pillow (`PIL`), `pillow-heif` (HEIC/HEIF → 98% JPG conversion), `google-genai` SDK (`vertexai=True`), `python-dotenv`.
- **Frontend**: Vanilla HTML/CSS/JS served by Flask (`templates/index.html`, `static/style.css`, `static/app.js`). No Node/npm build step.
- **Python Environment**: Use `/home/ubuntu/Dhruv/AiPhotoGenerated/venv/bin/python` for running tests, compile checks, and the server.

## Critical Contracts

1. **In-Place Room Preservation (`app.py`)**:
   - `main_image` (`"first image"`) is immutable: `generate_interior_prompt()` instructs Gemini to perform **in-place tile surface replacement only** on the specified floor/walls while keeping 100% of existing furniture, decor, ceiling, windows, lighting, and layout untouched (never re-furnishing or restyling the room).

2. **Image Ordinal Mapping (`app.py`)**:
   - `images_for_gemini` always starts with `main_pil_image` at index `0` (`"first image"`).
   - Optional images (`floor_tile_image`, `wall_tile_image_1`, `wall_tile_image_2`, `wall_tile_image_3`) are appended sequentially via `save_optional_image(field_name)` so their `"second image"` … `"fifth image"` labels always match their exact position in `contents = [prompt] + images`.
   - Never hardcode image ordinal strings; always derive them from `len(images_for_gemini)` when appending.

3. **Wall Tile Slot Mapping**:
   - `wall_tile_image_1` -> **Left Wall**
   - `wall_tile_image_3` -> **Center / Back Wall**
   - `wall_tile_image_2` -> **Right Wall**
   - Keep `wall_tile_image_1` and `wall_tile_image_2` field names intact for backward compatibility.

4. **Grout Color & Finish Behavior**:
   - `floor_finish` and `wall_finish` only accept `None`, `"matt"`, `"glossy"`, or `"high glossy"`.
   - In the UI (`static/app.js`), uploading a floor or wall tile auto-selects `"matt"` if the corresponding finish is currently unset, because `generate_interior_prompt` requires a finish to apply tile instructions.
   - `floor_grout_color` and `wall_grout_color` are optional strings (e.g., `"Warm Almond (#DDD0C0)"` or `"#3B3F45"`). When omitted/empty, the prompt falls back to automatic contrasting grout.
   - **Wall-to-Floor Grout Grid Alignment**: Always enforced whenever both floor and wall tiles are present so vertical wall grout joints connect seamlessly with floor grout lines at the wall-floor junction.
   - `floor_orientation` & `wall_orientation`: `"horizontal"` (default) or `"vertical"` — controls whether rectangular tiles are laid horizontally (landscape) or vertically (portrait).
   - `floor_pattern` & `wall_pattern`: `"grid"` (default), `"brick"`, `"herringbone"`, `"diagonal"`, or `"bookmatch"` (4-way symmetrical vein-flow mirroring) — applied both in `build_tiled_swatch_sheet()` / `generate_grid_blueprint()` and in prompt rules.
   - `floor_grout_width` & `wall_grout_width`: `"1 mm"`, `"2 mm"` (default), `"3 mm"`, or `"5 mm"`.
   - **Shadows & Reflections (`app.py`)**: `enable_reflection` (boolean form field `"true"`/`"false"`, default `false`) and `enable_shadows` (boolean form field `"true"`/`"false"`, default `true`) control whether `LIGHTING & MATERIAL FINISH` adds room/object reflections and contact shadows & ambient occlusion onto the newly laid tiles.
   - `aspect_ratio`: `"4:3"` (default), `"16:9"`, `"1:1"`, or `"3:4"` passed to `types.ImageConfig`.
   - `sync_grout` (boolean form field `"true"`/`"false"`): when enabled, additionally locks floor and wall grout to the exact same color.

5. **Tile Size `.pkl` Model (`tile_size_model.py` & `Models/tile_size_model.pkl`)**:
   - Reference tile size images live in `Models/` and room-grid reference renders live in `Models/Tile apply according to sized/` (covering 9 sizes: `200x1200`, `300x450`, `600x600`, `600x1200`, `800x800`, `800x1600`, `800x2400`, `1200x1200`, `1200x1800` mm).
   - `tile_size_model.py` builds `Models/tile_size_model.pkl` from both directories and exposes `analyze_tile_size(size_input, orientation_mode="horizontal")`, `load_tile_size_pkl()`, `build_tiled_swatch_sheet()`, and `generate_grid_blueprint()`.
   - `POST /generate-prompt` converts each uploaded tile swatch into an orientation-locked multi-tile grid sheet (`build_tiled_swatch_sheet`) and attaches clean, furniture-free floor perspective and wall frontal grid blueprints (`generate_grid_blueprint`).
   - If new tile images are added to `Models/`, re-run `venv/bin/python tile_size_model.py` to rebuild `Models/tile_size_model.pkl`.

6. **Vertex AI Models**:
   - Image generation model is loaded from `MODEL_NAME` in `.env` (defaulting to `gemini-3.1-flash-image`). Do not hardcode deprecated preview model IDs.
   - Room advisor (`POST /api/match-my-room`) uses `ADVISOR_MODEL` (defaulting to `gemini-2.5-flash`) with `response_mime_type="application/json"` to detect room type (`detected_scene`) and recommend the best grout colors (`floor_grout_color`, `wall_grout_color`) and laying patterns (`floor_pattern`, `wall_pattern`).

## Verification Checklist

After editing backend or frontend files:

1. Run syntax check:
   ```bash
   /home/ubuntu/Dhruv/AiPhotoGenerated/venv/bin/python -m py_compile /home/ubuntu/Dhruv/AiPhotoGenerated/app.py
   ```
2. Verify Flask routes (`/`, `/health`, `/static/style.css`, `/static/app.js`, and `/generate-prompt` prompt assembly) with `app.test_client()`.
