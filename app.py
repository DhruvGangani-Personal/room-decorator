from flask import Flask, request, jsonify, send_file, send_from_directory, render_template
from werkzeug.utils import secure_filename
import hashlib
import os
from pathlib import Path
from flask_cors import CORS
from google import genai
from google.genai import types
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
import io
import json
import uuid

register_heif_opener()
from datetime import datetime
from dotenv import load_dotenv
from tile_size_model import (
    analyze_tile_size,
    build_tiled_swatch_sheet,
    generate_grid_blueprint,
    load_tile_size_pkl,
)
from database import (
    add_tile,
    delete_render,
    init_db,
    list_renders,
    list_room_analyses,
    list_tiles,
    save_render,
    save_room_analysis,
)

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'generated_images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}

def convert_heic_to_jpg(filepath, quality=98):
    """Convert a HEIC/HEIF image to a 98%-quality RGB JPEG and return the new path."""
    ext = Path(filepath).suffix.lower()
    if ext not in {'.heic', '.heif'}:
        return filepath
    jpg_path = str(Path(filepath).with_suffix('.jpg'))
    with Image.open(filepath) as img:
        rgb_img = ImageOps.exif_transpose(img).convert('RGB')
        rgb_img.save(jpg_path, format='JPEG', quality=quality, subsampling=0)
    return jpg_path

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Create directories if they don't exist
Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
init_db()

# Initialize Gemini client
# client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

client = genai.Client(
      vertexai=True,
      api_key=os.environ.get("GOOGLE_CLOUD_API_KEY"),
  )

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_interior_prompt(
    main_image: str,
    floor_tile_image: str = None,
    wall_tile_image_1: str = None,
    wall_tile_image_2: str = None,
    wall_tile_image_3: str = None,
    floor_size_lable: str = None,
    wall_size_lable: str = None,
    floor_finish: str = None,
    wall_finish: str = None,
    scene: str = None,
    floor_grout_width: str = "2 mm",
    wall_grout_width: str = "2 mm",
    floor_grout_color: str = None,
    wall_grout_color: str = None,
    floor_orientation: str = "horizontal",
    wall_orientation: str = "horizontal",
    floor_pattern: str = "grid",
    wall_pattern: str = "grid",
    sync_grout: bool = False,
    floor_count_check: str = None,
    wall_count_check: str = None,
    floor_grid_ref: str = None,
    wall_grid_ref: str = None,
    enable_reflection: bool = False,
    enable_shadows: bool = True,
):
    """Generate interior design prompt based on provided parameters"""

    floor_orient_rule = (
        "Lay floor tiles HORIZONTALLY (long edge running left-to-right parallel to the back wall, short edge front-to-back)."
        if floor_orientation == "horizontal"
        else "Lay floor tiles VERTICALLY (long edge running front-to-back along the room depth, short edge left-to-right)."
    )
    wall_orient_rule = (
        "Lay wall tiles HORIZONTALLY (landscape orientation: long edge horizontal left-to-right, short edge vertical top-to-bottom)."
        if wall_orientation == "horizontal"
        else "Lay wall tiles VERTICALLY (portrait orientation: long edge vertical top-to-bottom, short edge horizontal left-to-right)."
    )

    pattern_map = {
        "grid": "Lay tiles in a straight STACKED GRID pattern with aligned horizontal and vertical joints.",
        "brick": "Lay tiles in a BRICK / RUNNING BOND pattern with a 50% staggered offset on alternating rows.",
        "herringbone": "Lay tiles in an interlocking HERRINGBONE zig-zag pattern at 90-degree alternating angles.",
        "diagonal": "Lay tiles in a 45-DEGREE DIAGONAL diamond pattern.",
        "bookmatch": "Lay tiles in a SYMMETRICAL BOOKMATCH & CONTINUOUS VEIN-FLOW pattern: mirror adjacent tiles horizontally and vertically across grout joints so stone/marble veins connect seamlessly into symmetrical butterfly and diamond patterns.",
    }
    floor_pattern_rule = pattern_map.get(floor_pattern, pattern_map["grid"])
    wall_pattern_rule = pattern_map.get(wall_pattern, pattern_map["grid"])

    # --- Helper: explicit rectangular proportion lock ---
    def _build_proportion_lock(size_label: str, orientation: str, surface: str) -> str:
        info = analyze_tile_size(size_label, orientation_mode=orientation)
        if not info.get("valid"):
            return ""
        w_mm, h_mm = info["width_mm"], info["height_mm"]
        if w_mm == h_mm:
            if surface == "wall":
                return (
                    f"PROPORTION & GRID LOCK (CRITICAL): Every single wall tile MUST be STRICTLY SQUARE (1:1, {w_mm} mm wide x {h_mm} mm tall) "
                    f"with EQUAL width and height — NEVER rectangular, NEVER vertically stretched, and NEVER horizontally elongated. "
                    f"Keep ALL horizontal grout rows at the EXACT SAME uniform height from ceiling to floor (do NOT stretch or shrink rows to align with mirrors, shelves, or countertops — grout lines must pass straight behind fixtures at equal {h_mm} mm intervals)."
                )
            return (
                f"PROPORTION LOCK (CRITICAL): Every {surface} tile MUST be STRICTLY SQUARE (1:1, {w_mm} mm x {h_mm} mm) "
                f"with equal left-to-right width and front-to-back depth in 3D perspective — NEVER rectangular or stretched."
            )
        short_mm, long_mm = min(w_mm, h_mm), max(w_mm, h_mm)
        eff_w, eff_h = (short_mm, long_mm) if orientation == "vertical" else (long_mm, short_mm)
        ratio_val = round(max(eff_w, eff_h) / max(1, min(eff_w, eff_h)), 2)
        if surface == "floor":
            if eff_w > eff_h:
                return (
                    f"PROPORTION LOCK (CRITICAL): Each floor tile is a {eff_w}x{eff_h} mm RECTANGLE — "
                    f"its left-to-right width ({eff_w} mm) is {ratio_val:g}x its front-to-back depth ({eff_h} mm). "
                    f"In perspective on the floor, every tile MUST appear as a wide, shallow horizontal rectangle "
                    f"(NEVER square 1:1!). Space the horizontal front-to-back grout lines {ratio_val:g}x closer together "
                    f"than a square tile so each floor tile clearly shows {eff_w}:{eff_h} rectangular proportions."
                )
            return (
                f"PROPORTION LOCK (CRITICAL): Each floor tile is a {eff_w}x{eff_h} mm RECTANGLE — "
                f"its front-to-back depth ({eff_h} mm) is {ratio_val:g}x its left-to-right width ({eff_w} mm). "
                f"In perspective on the floor, every tile MUST appear as an elongated vertical plank/strip "
                f"running into the room (NEVER square 1:1!)."
            )
        return (
            f"PROPORTION & GRID LOCK (CRITICAL): Every single wall tile MUST have the exact same "
            f"{eff_w} mm width x {eff_h} mm height ({info['aspect_ratio_label']} rectangular). "
            f"Never merge two rows into a tall square tile and never vary tile height or width across columns."
        )

    floor_prop_lock = _build_proportion_lock(floor_size_lable, floor_orientation, "floor") if floor_tile_image else ""
    wall_prop_lock = _build_proportion_lock(wall_size_lable, wall_orientation, "wall") if (wall_tile_image_1 or wall_tile_image_2 or wall_tile_image_3) else ""

    # --- Floor ---
    has_floor = bool(floor_tile_image and floor_finish)
    if has_floor:
        floor_instruction = (
            f"Replace the floor surface with the tile pattern from {floor_tile_image}. "
            f"Tile size: {floor_size_lable}. Finish: {floor_finish}. {floor_orient_rule} {floor_pattern_rule} "
            f"{floor_prop_lock} "
            f"Render the floor tiles in true architectural perspective with crisp, evenly spaced grid joints matching {floor_size_lable} — "
            f"do NOT render oversized slabs or square tiles when {floor_size_lable} is rectangular. "
            f"Preserve the tile's original color and pattern exactly. "
            f"Do not place any rugs, mats, or carpets over the tiles."
        )
    else:
        floor_instruction = (
            f"DO NOT apply any tiles to the floor. Keep the original floor from {main_image} "
            f"100% unchanged, untouched, and identical in material, color, texture, pattern, and finish."
        )

    # --- Walls (Left, Center, Right) ---
    wall_assignments = []
    if wall_tile_image_1:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_1} to the left wall.")
    if wall_tile_image_3:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_3} to the center/back wall.")
    if wall_tile_image_2:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_2} to the right wall.")

    has_wall = bool(wall_assignments and wall_finish)
    if has_wall:
        untiled_note = (
            "Keep any remaining walls without an assigned tile unchanged from the original room."
            if len(wall_assignments) < 3
            else ""
        )
        wall_instruction = (
            " ".join(wall_assignments)
            + f" All tiled walls use tile size {wall_size_lable} and {wall_finish} finish. {wall_orient_rule} {wall_pattern_rule} "
            + f"{wall_prop_lock} "
            + "Preserve each tile's original color and pattern exactly. "
            + untiled_note
        ).strip()
    else:
        wall_instruction = (
            f"DO NOT apply any tiles to any wall. Keep all original walls from {main_image} "
            f"100% unchanged, untouched, and identical in material, color, texture, and finish."
        )

    # --- Lighting rules per finish ---
    active_finishes = set(
        filter(
            None,
            [
                floor_finish if has_floor else None,
                wall_finish if has_wall else None,
            ],
        )
    )
    rules_map = {
        "glossy": (
            "Glossy finish: add subtle, diffused reflections of nearby furniture, windows, and room lights on the tile surface, "
            "with soft light glare near windows or doors. Keep tile colors rich and deep so the pattern remains clearly visible."
        ),
        "high glossy": (
            "High glossy finish: add clear, mirror-like reflections of furniture, room objects, and light sources on the polished tile surface, "
            "along with high shine and bright specular highlights."
        ),
        "matt": (
            "Matt finish: remove mirror reflections entirely. Surface should look smooth, flat, and non-reflective, while keeping natural contact shadows."
        ),
    }
    lighting_rules = "\n".join(
        f"- {rules_map[f]}" for f in active_finishes if f in rules_map
    )

    has_floor_and_wall = bool(has_floor and has_wall)
    aligned_patterns = {"grid", "bookmatch"}
    can_align_grid = (
        has_floor_and_wall
        and floor_pattern in aligned_patterns
        and wall_pattern in aligned_patterns
    )
    grid_alignment_rule = (
        "\n- WALL-TO-FLOOR GROUT GRID ALIGNMENT (MANDATORY):\n"
        "  - Connect and align floor grout lines directly with the vertical wall grout joints at the wall-to-floor junction (no offset or staggered seams), forming one continuous architectural tile grid across the wall and floor.\n"
        "  - Keep the grid lines razor-sharp, straight, and evenly spaced across every tile row and column — never resize or distort the declared tile dimensions."
        if can_align_grid
        else ""
    )

    if sync_grout:
        synced_color = floor_grout_color or wall_grout_color
        synced_rule = (
            f"Floor and wall grout MUST share the EXACT SAME color: {synced_color}."
            if synced_color
            else "Floor and wall grout MUST share the EXACT SAME contrasting grout color and tone across both surfaces."
        )
        floor_grout_color_rule = synced_rule
        wall_grout_color_rule = synced_rule
        grout_sync_rule = (
            grid_alignment_rule
            + "\n  - Floor and wall grout must look identical in color, width, recessed depth, and matte finish."
        )
    else:
        floor_grout_color_rule = (
            f"Floor grout color MUST be {floor_grout_color}."
            if floor_grout_color
            else "Floor grout color must contrast clearly against the floor tile surface (light gray on dark tiles, off-white/cream on light tiles)."
        )
        wall_grout_color_rule = (
            f"Wall grout color MUST be {wall_grout_color}."
            if wall_grout_color
            else "Wall grout color must contrast clearly against the wall tile surface (light gray on dark tiles, off-white/cream on light tiles)."
        )
        grout_sync_rule = grid_alignment_rule

    grid_ref_lines = []
    if floor_grid_ref:
        floor_orient_note = (
            " Follow the exact VERTICAL (portrait) perspective grid shown in the blueprint."
            if floor_orientation == "vertical"
            else " Follow the exact HORIZONTAL (landscape) perspective grid shown in the blueprint."
        )
        grid_ref_lines.append(
            f"- Floor Grid & Scale Blueprint: Use {floor_grid_ref} STRICTLY as the tile size, aspect ratio, grid density, and grout-spacing reference for the floor ({floor_size_lable}).{floor_orient_note}"
        )
    if wall_grid_ref:
        wall_orient_note = (
            " Follow the exact VERTICAL (portrait) grid shown in the blueprint."
            if wall_orientation == "vertical"
            else " Follow the exact HORIZONTAL (landscape) grid shown in the blueprint."
        )
        grid_ref_lines.append(
            f"- Wall Grid & Scale Blueprint: Use {wall_grid_ref} STRICTLY as the tile size, aspect ratio, grid density, and grout-spacing reference for the walls ({wall_size_lable}).{wall_orient_note}"
        )
    grid_ref_block = ("\n" + "\n".join(grid_ref_lines)) if grid_ref_lines else ""

    grout_surface_lines = []
    grout_width_parts = []
    size_enforcement_lines = []
    if has_floor:
        grout_surface_lines.append(
            f"- Floor grout: {floor_grout_width} wide lines for {floor_size_lable} tiles. {floor_grout_color_rule}"
        )
        grout_width_parts.append(f"{floor_grout_width} (floor)")
        size_enforcement_lines.append(f"Floor tile size is {floor_size_lable}. {floor_count_check}")
    if has_wall:
        grout_surface_lines.append(
            f"- Wall grout: {wall_grout_width} wide lines for {wall_size_lable} tiles. {wall_grout_color_rule}"
        )
        grout_width_parts.append(f"{wall_grout_width} (wall)")
        size_enforcement_lines.append(f"Wall tile size is {wall_size_lable}. {wall_count_check}")

    grout_surface_block = "\n".join(grout_surface_lines)
    grout_width_desc = " and ".join(grout_width_parts) if grout_width_parts else "2 mm"
    size_enforcement_block = "\n".join(size_enforcement_lines)

    if has_floor and not has_wall:
        surface_scope_rule = "ONLY replace the FLOOR surface with the provided floor tile. Do NOT modify, paint, or apply tiles to ANY wall."
    elif has_wall and not has_floor:
        surface_scope_rule = "ONLY replace the specified WALL surface(s) with the provided wall tile(s). Do NOT modify or apply tiles to the FLOOR."
    else:
        surface_scope_rule = "ONLY replace the specified floor and/or wall surfaces with the provided tiles."

    reflection_rule = (
        f"- REFLECTION (ENABLED — MANDATORY): Add realistic, perspective-accurate reflections of nearby furniture, windows, doors, plants, and room light sources onto the newly tiled surface(s) (softly diffused on matt, clear and luminous on glossy/high glossy), matching the lighting of {main_image}."
        if enable_reflection
        else "- REFLECTION (DISABLED): Do NOT add mirror reflections or bright glare onto the newly tiled surface(s); keep the tile surface clean and non-reflective so the tile pattern remains pure."
    )
    shadow_rule = (
        f"- SHADOWS & AMBIENT OCCLUSION (ENABLED — MANDATORY): Cast realistic contact shadows and soft ambient occlusion directly beneath all existing furniture legs, sofas, tables, bathtubs, planters, decor objects, and wall-floor corners onto the newly laid surface, matching the exact light direction of {main_image} so objects look physically grounded."
        if enable_shadows
        else "- SHADOWS (DISABLED): Do NOT add extra cast shadows or dark ambient occlusion onto the newly laid tile surface(s); keep lighting even and clean across the tiles."
    )

    prompt = f"""
STRICT IN-PLACE ROOM PRESERVATION (MANDATORY — DO NOT CHANGE THE ROOM):
- Treat {main_image} as an immutable photograph. Perform an IN-PLACE TILE SURFACE REPLACEMENT ONLY: {surface_scope_rule}
- Preserve camera angle, perspective, framing, lighting, and field of view 100% identically to {main_image}.
- Keep EVERY existing object in {main_image} completely untouched and unchanged: all furniture, chairs, tables, plants, windows, doors, curtains, ceiling, light fixtures, decor, background scenery, and shadows must remain in their exact original position, shape, and color.
- Do NOT add, remove, move, replace, crop, rotate, or restyle any furniture, decor, ceiling, or architectural structure.
- Do NOT add carpeting, rugs, or floor mats over the applied tiles.
- Do NOT change tile color or pattern from the provided tile reference images.

SCENE:
Keep the existing {scene} in {main_image} 100% unchanged — {surface_scope_rule}

FLOOR:
{floor_instruction}

WALL:
{wall_instruction}

CEILING & EXISTING FURNITURE (DO NOT MODIFY):
- Keep the ceiling from {main_image} 100% identical and untouched.
- Keep all existing furniture, lighting fixtures, windows, doors, plants, and decor from {main_image} 100% identical and untouched — do NOT invent, add, or remove any objects.

GROUT (CRITICAL — MUST BE VISIBLE):
Grout lines are a mandatory visible element — they must NOT be invisible, faint, blended into the tile, or omitted.
{grout_surface_block}
- All grout lines must be perfectly straight, evenly spaced, and continuous across the entire tiled surface without breaks or gaps.
- Grout channel must show slight physical depth — rendered as a recessed groove between tiles, not a flat painted line.
- Grout must remain clearly visible under all lighting conditions, including glossy and high-glossy finishes.
- Tile edges must be sharp and clean where they meet the grout channel.
- Grout texture should appear slightly rough and matte — never smooth, shiny, or matching the tile finish.{grout_sync_rule}

TILE SIZE ENFORCEMENT (CRITICAL — NON-NEGOTIABLE):
{size_enforcement_block}{grid_ref_block}
Before finalising the image, verify: count the tiles visible on any 1-meter span of the tiled surface(s).
The count MUST match the stated tile density above. If it does not match, the tile size is rendered incorrectly — fix it.
Do NOT make tiles larger or smaller than declared. Do NOT guess the scale.

LIGHTING & MATERIAL FINISH:
Adjust lighting, reflections, shadows, and surface rendering strictly according to the specified tile finishes and toggles:
{lighting_rules}
{reflection_rule}
{shadow_rule}
Overall scene lighting must be natural, well-balanced, and consistent — no harsh overexposure or underlit areas.

QUALITY:
Ultra-detailed, 16K UHD output. Sharp textures, crisp edges, and accurate material rendering throughout.
The final result must look fully photorealistic and production-ready for professional architectural visualization — polished, premium, and lifelike.

TILE & GROUT LOCK (ABSOLUTE — NO MODIFICATION ALLOWED):
- The tile color, texture, finish, and pattern must remain EXACTLY identical to the provided tile reference images.
- Do NOT enhance, restyle, recolor, retexture, or reinterpret the tiles in any way.
- Do NOT apply filters, lighting effects, or reflections that alter the perceived tile color or design.
- Tiles must be reproduced faithfully as real-world material surfaces, not artistically interpreted.

- Grout lines must remain EXACTLY as specified:
  - Width must be strictly {grout_width_desc} — no variation anywhere.
  - Grout must be fully visible across the entire tiled surface, with no fading, blending, or obstruction.
  - Do NOT reduce grout visibility due to lighting, reflections, or post-processing.
  - Grout must appear as a continuous recessed channel with consistent depth and sharp tile edges.
  - Do NOT stylize or smooth the grout — it must retain a natural matte, slightly rough finish.

- Under no circumstances should tile size, grout width, tile layout, or tile alignment be altered.
"""
    print(prompt,"##############################")
    return prompt


def generate_image_with_gemini(prompt, images, aspect_ratio="4:3"):
    """
    Generate image using Google Gemini
    
    Args:
        prompt: Text prompt for image generation
        images: List of PIL Image objects
        aspect_ratio: Output image aspect ratio ("4:3", "16:9", "1:1", "3:4")
    
    Returns:
        Tuple of (success, generated_image_path or error_message)
    """
    try:

        # Prepare contents list with prompt and images
        contents = [prompt] + images

        # Generate content with Gemini
        response = client.models.generate_content(
            model=os.environ.get("MODEL_NAME", "gemini-3.1-flash-image"),
            # model="gemini-3-pro-image-preview",
            contents=contents,
            config=types.GenerateContentConfig(response_modalities=['Image'],
                                               temperature = 1,
                                               image_config=types.ImageConfig(aspect_ratio=aspect_ratio)))

        # Process response
        for part in response.parts:
            if part.inline_data is not None:
                # Get generated image
                generated_image = part.as_image()
                
                # Generate unique filename
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"generated_{timestamp}.png"
                output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
                
                # Save image
                generated_image.save(output_path)
                
                return True, output_path
            elif part.text is not None:
                app.logger.info(f"Gemini response text: {part.text}")
        
        return False, "No image generated in response"
        
    except Exception as e:
        app.logger.error(f"Gemini API error: {str(e)}")
        return False, f"Gemini API error: {str(e)}"

@app.route('/', methods=['GET'])
def index():
    """Serve the Interior Tile Visualizer UI"""
    return render_template('index.html')

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Interior Design Generator API Working'
    }), 200

@app.route('/api/tile-models', methods=['GET'])
def get_tile_models():
    """Return available tile size & aspect-ratio models from tile_size_model.pkl"""
    data = load_tile_size_pkl()
    return jsonify(data), 200

@app.route('/api/analyze-tile-size', methods=['GET'])
def api_analyze_tile_size():
    """Analyze a mm tile size string against tile_size_model.pkl"""
    size_str = request.args.get('size', '600x1200 mm')
    orientation = request.args.get('orientation', 'horizontal')
    return jsonify(analyze_tile_size(size_str, orientation_mode=orientation)), 200

@app.route('/api/preview-heic', methods=['POST'])
def preview_heic():
    """Convert an uploaded HEIC/HEIF file to 98% quality JPEG for browser preview."""
    file_obj = request.files.get('file')
    if not file_obj or file_obj.filename == '':
        return jsonify({'error': 'No file provided'}), 400
    with Image.open(file_obj.stream) as img:
        rgb_img = ImageOps.exif_transpose(img).convert('RGB')
        buf = io.BytesIO()
        rgb_img.save(buf, format='JPEG', quality=98, subsampling=0)
        buf.seek(0)
    return send_file(buf, mimetype='image/jpeg')

@app.route('/api/match-my-room', methods=['POST'])
def match_my_room():
    """Analyze the uploaded room photo and recommend 3 tile & grout palettes."""
    file_obj = request.files.get('main_image')
    if not file_obj or file_obj.filename == '':
        return jsonify({'error': 'main_image is required'}), 400

    temp_files = []
    try:
        safe_name = secure_filename(file_obj.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4().hex}_{safe_name}")
        file_obj.save(filepath)
        temp_files.append(filepath)

        converted = convert_heic_to_jpg(filepath, quality=98)
        if converted != filepath:
            temp_files.append(converted)
            filepath = converted

        room_img = Image.open(filepath)
        advisor_prompt = (
            "You are an expert architectural interior & tile designer. Analyze this room photo "
            "(room type, furniture, woodwork, wall colors, and lighting) and return ONLY valid JSON "
            "with this exact schema — focus ONLY on room type detection, best grout colors, and best laying patterns:\n"
            "{\n"
            '  "detected_scene": "living room | office | bathroom | kitchen | bedroom | hallway | commercial lobby | outdoor",\n'
            '  "style": "short 2-3 word style name",\n'
            '  "lighting_tone": "short 2-3 word lighting description",\n'
            '  "dominant_colors": ["#HEX1", "#HEX2", "#HEX3"],\n'
            '  "recommendations": [\n'
            "    {\n"
            '      "title": "short 2-4 word recommendation name",\n'
            '      "reason": "1 concise sentence explaining why this grout & laying pattern suits the room",\n'
            '      "floor_pattern": "grid | brick | herringbone | diagonal | bookmatch",\n'
            '      "floor_grout_color": "Name (#HEX)",\n'
            '      "wall_pattern": "grid | brick | herringbone | diagonal | bookmatch",\n'
            '      "wall_grout_color": "Name (#HEX)"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Provide exactly 3 diverse recommendations."
        )

        response = client.models.generate_content(
            model=os.environ.get("ADVISOR_MODEL", "gemini-2.5-flash"),
            contents=[advisor_prompt, room_img],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(response.text)
        image_hash = hashlib.sha256(Path(filepath).read_bytes()).hexdigest()
        analysis_id = save_room_analysis(image_hash, data)
        data['analysis_id'] = analysis_id
        return jsonify(data), 200
    except Exception as e:
        app.logger.error(f"Match My Room error: {str(e)}")
        return jsonify({'error': 'Room analysis failed', 'message': str(e)}), 500
    finally:
        for p in temp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

@app.route('/generate-prompt', methods=['POST'])
def generate_prompt():
    """
    Generate interior design prompt and image
    
    Form data:
    - main_image: file (required)
    - floor_tile_image: file (optional)
    - wall_tile_image_1: file (optional)
    - wall_tile_image_2: file (optional)
    - floor_size_lable: string (optional, default: "600x1200 mm")
    - wall_size_lable: string (optional, default: "600x1200 mm")
    - floor_finish: string (optional, values: "matt", "glossy", "high glossy")
    - wall_finish: string (optional, values: "matt", "glossy", "high glossy")
    - scene: string (optional)
    """
    uploaded_files = []
    try:
        # Check if main_image is provided
        if 'main_image' not in request.files:
            return jsonify({
                'error': 'main_image is required',
                'message': 'Please provide a main_image file'
            }), 400
        
        main_file = request.files['main_image']
        
        # Validate main image
        if main_file.filename == '':
            return jsonify({
                'error': 'No file selected',
                'message': 'main_image file is empty'
            }), 400
        
        if not allowed_file(main_file.filename):
            return jsonify({
                'error': 'Invalid file type',
                'message': f'Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Save main image (convert HEIC/HEIF to 98% JPG first)
        main_filename = secure_filename(main_file.filename)
        unique_main_filename = f"{uuid.uuid4().hex}_{main_filename}"
        main_filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_main_filename)
        main_file.save(main_filepath)
        uploaded_files.append(main_filepath)

        converted_main_filepath = convert_heic_to_jpg(main_filepath, quality=98)
        if converted_main_filepath != main_filepath:
            uploaded_files.append(converted_main_filepath)
            main_filepath = converted_main_filepath

        # Load main image as PIL Image
        main_pil_image = Image.open(main_filepath)
        images_for_gemini = [main_pil_image]
        ordinal_names = [
            "first image",
            "second image",
            "third image",
            "fourth image",
            "fifth image",
            "sixth image",
            "seventh image",
        ]

        # Get form parameters first so swatch sheets & blueprints match requested size/orientation
        floor_size_lable = request.form.get('floor_size_lable', '600x1200 mm')
        wall_size_lable = request.form.get('wall_size_lable', '600x1200 mm')
        floor_finish = request.form.get('floor_finish')
        wall_finish = request.form.get('wall_finish')
        floor_grout_color = request.form.get('floor_grout_color') or None
        wall_grout_color = request.form.get('wall_grout_color') or None
        floor_grout_width = request.form.get('floor_grout_width', '2 mm') or '2 mm'
        wall_grout_width = request.form.get('wall_grout_width', '2 mm') or '2 mm'
        floor_orientation = request.form.get('floor_orientation', 'horizontal')
        wall_orientation = request.form.get('wall_orientation', 'horizontal')
        floor_pattern = request.form.get('floor_pattern', 'grid')
        wall_pattern = request.form.get('wall_pattern', 'grid')
        aspect_ratio = request.form.get('aspect_ratio', '4:3')
        if floor_orientation not in ('horizontal', 'vertical'):
            floor_orientation = 'horizontal'
        if wall_orientation not in ('horizontal', 'vertical'):
            wall_orientation = 'horizontal'
        if floor_pattern not in ('grid', 'brick', 'herringbone', 'diagonal', 'bookmatch'):
            floor_pattern = 'grid'
        if wall_pattern not in ('grid', 'brick', 'herringbone', 'diagonal', 'bookmatch'):
            wall_pattern = 'grid'
        if aspect_ratio not in ('4:3', '16:9', '1:1', '3:4'):
            aspect_ratio = '4:3'
        sync_grout = request.form.get('sync_grout', 'false').lower() in ('true', '1', 'yes', 'on')
        enable_reflection = request.form.get('enable_reflection', 'false').lower() in ('true', '1', 'yes', 'on')
        enable_shadows = request.form.get('enable_shadows', 'true').lower() in ('true', '1', 'yes', 'on')
        scene = request.form.get('scene', 'living room')

        effective_floor_grout = (floor_grout_color or wall_grout_color) if sync_grout else floor_grout_color
        effective_wall_grout = (floor_grout_color or wall_grout_color) if sync_grout else wall_grout_color

        # Validate finish values
        valid_finishes = ['matt', 'glossy', 'high glossy', None]
        if floor_finish and floor_finish not in valid_finishes:
            return jsonify({
                'error': 'Invalid floor_finish',
                'message': 'Allowed values: matt, glossy, high glossy'
            }), 400
        
        if wall_finish and wall_finish not in valid_finishes:
            return jsonify({
                'error': 'Invalid wall_finish',
                'message': 'Allowed values: matt, glossy, high glossy'
            }), 400

        def save_optional_swatch(field_name, size_str, orientation_mode, grout_color, pattern_mode):
            if field_name not in request.files:
                return None
            file_obj = request.files[field_name]
            if not file_obj or file_obj.filename == '' or not allowed_file(file_obj.filename):
                return None
            safe_name = secure_filename(file_obj.filename)
            unique_name = f"{uuid.uuid4().hex}_{safe_name}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            file_obj.save(filepath)
            uploaded_files.append(filepath)
            converted_path = convert_heic_to_jpg(filepath, quality=98)
            if converted_path != filepath:
                uploaded_files.append(converted_path)
                filepath = converted_path
            idx = len(images_for_gemini)
            raw_tile = Image.open(filepath)
            swatch_sheet = build_tiled_swatch_sheet(
                raw_tile,
                size_input=size_str,
                orientation_mode=orientation_mode,
                grout_color=grout_color,
                pattern=pattern_mode,
            )
            images_for_gemini.append(swatch_sheet)
            return ordinal_names[idx]

        first_img = "first image"
        second_img = save_optional_swatch('floor_tile_image', floor_size_lable, floor_orientation, effective_floor_grout, floor_pattern)
        third_img = save_optional_swatch('wall_tile_image_1', wall_size_lable, wall_orientation, effective_wall_grout, wall_pattern)
        forth_img = save_optional_swatch('wall_tile_image_2', wall_size_lable, wall_orientation, effective_wall_grout, wall_pattern)
        fifth_img = save_optional_swatch('wall_tile_image_3', wall_size_lable, wall_orientation, effective_wall_grout, wall_pattern)
        
        # Analyze tile sizes against Models/tile_size_model.pkl (orientation-aware)
        floor_size_info = analyze_tile_size(floor_size_lable, orientation_mode=floor_orientation)
        wall_size_info = analyze_tile_size(wall_size_lable, orientation_mode=wall_orientation)

        # Print incoming request payload for debugging
        payload_debug = {
            "files": {
                k: f.filename
                for k, f in request.files.items()
                if f and f.filename
            },
            "form": {
                "scene": scene,
                "floor_size_lable": floor_size_lable,
                "floor_orientation": floor_orientation,
                "floor_pattern": floor_pattern,
                "floor_finish": floor_finish,
                "floor_grout_width": floor_grout_width,
                "floor_grout_color": floor_grout_color,
                "wall_size_lable": wall_size_lable,
                "wall_orientation": wall_orientation,
                "wall_pattern": wall_pattern,
                "wall_finish": wall_finish,
                "wall_grout_width": wall_grout_width,
                "wall_grout_color": wall_grout_color,
                "aspect_ratio": aspect_ratio,
                "sync_grout": sync_grout,
                "enable_reflection": enable_reflection,
                "enable_shadows": enable_shadows,
            },
        }
        print("=== /generate-prompt PAYLOAD ===", payload_debug, flush=True)

        # Attach clean, orientation-locked visual grid blueprints (floor perspective & wall frontal)
        def attach_blueprint(size_str, surface, orientation_mode, pattern_mode):
            idx = len(images_for_gemini)
            if idx >= len(ordinal_names):
                return None
            bp_img = generate_grid_blueprint(
                size_input=size_str,
                surface=surface,
                orientation_mode=orientation_mode,
                pattern=pattern_mode,
            )
            images_for_gemini.append(bp_img)
            return ordinal_names[idx]

        floor_grid_ref = attach_blueprint(floor_size_lable, "floor", floor_orientation, floor_pattern) if second_img else None
        wall_grid_ref = (
            attach_blueprint(wall_size_lable, "wall", wall_orientation, wall_pattern)
            if (third_img or forth_img or fifth_img)
            else None
        )

        # Generate prompt
        prompt = generate_interior_prompt(
            main_image=first_img,
            floor_tile_image=second_img,
            wall_tile_image_1=third_img,
            wall_tile_image_2=forth_img,
            wall_tile_image_3=fifth_img,
            floor_size_lable=floor_size_info['size_label'],
            wall_size_lable=wall_size_info['size_label'],
            floor_finish=floor_finish,
            wall_finish=wall_finish,
            floor_grout_width=floor_grout_width,
            wall_grout_width=wall_grout_width,
            floor_grout_color=floor_grout_color,
            wall_grout_color=wall_grout_color,
            floor_orientation=floor_orientation,
            wall_orientation=wall_orientation,
            floor_pattern=floor_pattern,
            wall_pattern=wall_pattern,
            sync_grout=sync_grout,
            floor_count_check=floor_size_info['count_check'],
            wall_count_check=wall_size_info['count_check'],
            floor_grid_ref=floor_grid_ref,
            wall_grid_ref=wall_grid_ref,
            enable_reflection=enable_reflection,
            enable_shadows=enable_shadows,
            scene=scene
        )

        # Generate image with Gemini
        success, result = generate_image_with_gemini(prompt, images_for_gemini, aspect_ratio=aspect_ratio)
        
        if not success:
            return jsonify({
                'error': 'Image generation failed',
                'message': result
            }), 500

        # Persist render history in SQLite3
        save_render({
            "scene": scene,
            "output_filename": os.path.basename(result),
            "output_image_path": result,
            "floor_size": floor_size_info['size_label'],
            "floor_finish": floor_finish,
            "floor_orientation": floor_orientation,
            "floor_pattern": floor_pattern,
            "floor_grout_width": floor_grout_width,
            "floor_grout_color": floor_grout_color,
            "wall_size": wall_size_info['size_label'],
            "wall_finish": wall_finish,
            "wall_orientation": wall_orientation,
            "wall_pattern": wall_pattern,
            "wall_grout_width": wall_grout_width,
            "wall_grout_color": wall_grout_color,
            "aspect_ratio": aspect_ratio,
            "sync_grout": sync_grout,
            "enable_reflection": enable_reflection,
            "enable_shadows": enable_shadows,
        })
                
        # Return response
        return send_file(result, mimetype="image/jpeg")
        
    except Exception as e:
        return jsonify({
            # 'error': 'Internal server error',
            'error': 'Please select other scene or tiles image',
            'message': str(e)
        }), 500
    finally:
        # Cleanup uploaded files
        for file_path in uploaded_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    # app.logger.info(f"Cleaned up uploaded file: {file_path}")
            except Exception as cleanup_error:
                app.logger.error(f"Error cleaning up file {file_path}: {str(cleanup_error)}")


@app.route('/generated/<path:filename>', methods=['GET'])
def serve_generated(filename):
    """Serve saved render images from generated_images/"""
    return send_from_directory(app.config['OUTPUT_FOLDER'], filename)

@app.route('/models-swatch/<path:filename>', methods=['GET'])
def serve_model_swatch(filename):
    """Serve showroom catalog swatch images from Models/"""
    return send_from_directory('Models', filename)

@app.route('/api/renders', methods=['GET'])
def api_list_renders():
    """Return persisted render history from SQLite3"""
    rows = list_renders(limit=24)
    for r in rows:
        r['image_url'] = f"/generated/{r['output_filename']}"
    return jsonify({'renders': rows}), 200

@app.route('/api/renders/<int:render_id>', methods=['DELETE'])
def api_delete_render(render_id):
    """Delete a render history record"""
    deleted = delete_render(render_id)
    return jsonify({'deleted': deleted}), 200 if deleted else 404

@app.route('/api/room-analyses', methods=['GET'])
def api_list_room_analyses():
    """Return persisted AI Room Advisor results from SQLite3"""
    return jsonify({'analyses': list_room_analyses(limit=20)}), 200

@app.route('/api/catalog', methods=['GET', 'POST'])
def api_catalog():
    """List or add tiles in the SQLite3 Tile Showroom Catalog"""
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        required = ('sku_code', 'name', 'swatch_filename', 'size_mm')
        if not all(payload.get(k) for k in required):
            return jsonify({'error': 'Missing required fields: sku_code, name, swatch_filename, size_mm'}), 400
        try:
            tile_id = add_tile(payload)
            return jsonify({'id': tile_id, 'status': 'created'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    tiles = list_tiles()
    for t in tiles:
        t['swatch_url'] = f"/models-swatch/{t['swatch_filename']}"
    return jsonify({'tiles': tiles}), 200


if __name__ == '__main__':
    # Use debug=True only when running locally for development
    app.run(debug=True, host='0.0.0.0', port=5000)