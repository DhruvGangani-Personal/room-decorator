# BRAIN.md — System Design & Engineering Notes

## Concept & Evolution
Atelier Tile transforms a raw or existing room photograph (`main_image`) into a photorealistic interior render with user-selected floor and wall tiles while locking camera perspective, room geometry, and architectural openings.

### Key Architectural Decisions

1. **Single-Origin Flask Serving (`templates/` + `static/`)**
   - Serving the UI from `GET /` on the same Flask app eliminates CORS friction, requires zero frontend build tooling, and keeps deployment to a single process (`python app.py`).

2. **3-Wall Spatial Concept (Left, Center, Right)**
   - Rooms typically have three visible vertical planes in perspective: Left Wall (`wall_tile_image_1`), Center/Back Wall (`wall_tile_image_3`), and Right Wall (`wall_tile_image_2`).
   - Instead of a rigid 2-wall `if/elif` matrix, `save_optional_image()` dynamically assigns ordinal references (`"second image"` through `"fifth image"`) as files are appended to `images_for_gemini`.
   - `generate_interior_prompt()` builds explicit per-wall instructions for each provided slot and instructs the model to keep any untiled walls plain and smooth.

3. **Client-Side Tile Color Extraction for Grout Recommendations**
   - When a user uploads a floor or wall tile swatch, `static/app.js` draws it onto a `24x24` offscreen `<canvas>` and averages opaque pixels to compute the tile's dominant RGB and luminance.
   - Based on luminance (`> 0.68` light, `< 0.35` dark, or mid-tone) and warmth (`r >= b`), `buildRecommendedGroutSwatches()` generates 4 tailored grout options (tonal match, soft contrast, deep contrast, and warm/cool neutral).
   - Users can pick **Auto**, one of the 4 **tile-matched swatches**, or any **Custom** hex color via `<input type="color">`.
   - **Wall-to-Floor Grout Grid Alignment** is always enforced whenever both floor and wall tiles are provided, connecting vertical wall grout joints directly into the floor grout lines at the wall-to-floor junction.
   - The **Sync with Floor** (`sync_grout`) toggle additionally mirrors the selected grout color across both wall and floor.

4. **Tile Size & Aspect-Ratio `.pkl` Model (`tile_size_model.py`)**
   - `Models/` holds flat reference tile images and `Models/Tile apply according to sized/` holds 9 full-room grid templates (`1200X1200_tile_used.jpg`, `1200X1800_tile_used.jpg`, `200X1200_tile_used.jpg`, `300X450_tile_used.jpg`, `600X1200_tile_used.jpg`, `600X600_tile_used.jpg`, `800X1600_tile_used.jpg`, `800X2400_tile_used.jpg`, `800X800_tile_used.jpg`) demonstrating exact wall-to-floor connected grout grids at each tile scale.
   - `build_tile_size_pkl()` indexes all 9 sizes into `Models/tile_size_model.pkl` with mm dimensions, aspect ratio, orientation (`square`, `rectangular`, `plank`), pixel resolution, 1-meter span tile density, and `grid_reference_image` path.
   - When a user enters any `mm` size in the UI or API, `analyze_tile_size()` matches it against `tile_size_model.pkl` (exact or closest aspect-ratio/dimension match) and injects the computed aspect ratio and 1-meter tile count into `floor_count_check` / `wall_count_check` for strict scale enforcement in the room render.

5. **Vertex AI Express Mode (`GOOGLE_CLOUD_API_KEY`)**
   - `genai.Client(vertexai=True, api_key=os.environ.get("GOOGLE_CLOUD_API_KEY"))` uses `MODEL_NAME=gemini-3.1-flash-image` from `.env`.
   - Note: `client.models.list()` is not supported with API-key auth on Vertex AI (returns 401), whereas `client.models.generate_content()` works directly.

## Future Ideas
- Persist generated renders and metadata in a lightweight SQLite gallery (`GET /api/history`).
- Add grout width controls (`1 mm`, `2 mm`, `3 mm`, `5 mm`) in the UI wired to `floor_grout_width` and `wall_grout_width`.
- Add aspect-ratio selector (`4:3`, `16:9`, `1:1`, `3:4`) wired to `types.ImageConfig`.
