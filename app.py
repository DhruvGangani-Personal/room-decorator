from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
import os
from pathlib import Path
from flask_cors import CORS
from google import genai
from google.genai import types
from PIL import Image
import uuid
from datetime import datetime
from dotenv import load_dotenv
from tile_size_model import analyze_tile_size, load_tile_size_pkl

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'generated_images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER

# Create directories if they don't exist
Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)

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
    sync_grout: bool = False,
    floor_count_check: str = None,
    wall_count_check: str = None,
):
    """Generate interior design prompt based on provided parameters"""

    # --- Floor ---
    if floor_tile_image and floor_finish:
        floor_instruction = (
            f"Replace the floor surface with the tile pattern from {floor_tile_image}. "
            f"Tile size: {floor_size_lable}. Finish: {floor_finish}. "
            f"Render the floor tiles in true architectural perspective with crisp, evenly spaced grid joints matching {floor_size_lable} — "
            f"do NOT render oversized slabs or square tiles when {floor_size_lable} is rectangular. "
            f"Preserve the tile's original color and pattern exactly. "
            f"Do not place any rugs, mats, or carpets over the tiles."
        )
    else:
        floor_instruction = "if tiles is present, keep as it is otherwise all walls plain and smooth."

    # --- Walls (Left, Center, Right) ---
    wall_assignments = []
    if wall_tile_image_1:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_1} to the left wall.")
    if wall_tile_image_3:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_3} to the center/back wall.")
    if wall_tile_image_2:
        wall_assignments.append(f"Apply tiles from {wall_tile_image_2} to the right wall.")

    if wall_assignments and wall_finish:
        untiled_note = (
            "Keep any remaining walls without an assigned tile plain, smooth, and painted in a complementary neutral tone."
            if len(wall_assignments) < 3
            else ""
        )
        wall_instruction = (
            " ".join(wall_assignments)
            + f" All tiled walls use tile size {wall_size_lable} and {wall_finish} finish. "
            + "Preserve each tile's original color and pattern exactly. "
            + untiled_note
        ).strip()
    else:
        wall_instruction = (
            "if tiles is present, keep as it is otherwise all walls plain and smooth."
        )

    # --- Lighting rules per finish ---
    finishes = set(filter(None, [floor_finish, wall_finish]))
    rules_map = {
        "glossy": (
            "Glossy finish: add subtle reflections and very soft light glare near windows or doors. "
            "Keep tile colors rich and deep so the pattern remains clearly visible."
        ),
        "high glossy": (
            "High glossy finish: add strong mirror-like reflections, high shine, and bright specular highlights."
        ),
        "matt": (
            "Matt finish: remove reflections entirely. Surface should look smooth, flat, and non-reflective."
        ),
    }
    lighting_rules = "\n".join(
        f"- {rules_map[f]}" for f in finishes if f in rules_map
    )

    has_floor_and_wall = bool(floor_tile_image and wall_assignments)
    grid_alignment_rule = (
        "\n- WALL-TO-FLOOR GROUT GRID ALIGNMENT (MANDATORY):\n"
        "  - Connect and align floor grout lines directly with the vertical wall grout joints at the wall-to-floor junction (no offset or staggered seams), forming one continuous architectural tile grid across the wall and floor.\n"
        "  - Keep the grid lines razor-sharp, straight, and evenly spaced across every tile row and column — never resize or distort the declared tile dimensions."
        if has_floor_and_wall
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

    prompt = f"""
STRICT LAYOUT & CAMERA LOCK (MANDATORY):
- Use {main_image} as the exact spatial reference.
- Preserve camera angle, perspective, framing, and field of view exactly as shown in {main_image}.
- Do NOT change room geometry, proportions, walls, floor boundaries, ceiling height, or openings.
- Do NOT move, resize, crop, rotate, or reinterpret the layout in any way.
- Do NOT change tile color or pattern from the provided tile images.
- Architectural structure must remain 100% identical to {main_image}.
- Applied tiles must NOT be covered by any carpet, rug, or floor mat. Keep all tile surfaces fully visible and unobstructed.
- Do NOT add carpeting, rugs, or floor mats of any kind.
- Remove all construction materials, tools, iron rods, wooden rods, scaffolding, debris, or any objects not part of the final interior design.

SCENE:
Recreate a premium, photorealistic interior scene of a {scene} using {main_image} as the spatial anchor.
The layout, structure, and proportions of {main_image} must remain completely unchanged.

FLOOR:
{floor_instruction}

WALL:
{wall_instruction}

CEILING:
The ceiling must be plain, clean, and free of any tiles or surface patterns.
It should be finished in a neutral tone that complements the overall color palette of the {scene}.
If {main_image} appears to be a construction or bare unfinished space, recreate a complete, finished ceiling appropriate for a {scene} — such as a smooth painted surface or a simple false ceiling with recessed lighting.
The ceiling must never distract from the tiled wall and floor surfaces.

FURNITURE & DECOR:
Furnish all remaining space with furniture, lighting fixtures, and accessories appropriate for a modern {scene}.
All furniture and decor must be contextually suitable, well-proportioned, and placed naturally within the space.
Do not overcrowd the scene — maintain breathing room and a premium, curated feel.

GROUT (CRITICAL — MUST BE VISIBLE):
Grout lines are a mandatory visible element — they must NOT be invisible, faint, blended into the tile, or omitted.
- Floor grout: {floor_grout_width} wide lines for {floor_size_lable} tiles. {floor_grout_color_rule}
- Wall grout: {wall_grout_width} wide lines for {wall_size_lable} tiles. {wall_grout_color_rule}
- All grout lines must be perfectly straight, evenly spaced, and continuous across the entire surface without breaks or gaps.
- Grout channel must show slight physical depth — rendered as a recessed groove between tiles, not a flat painted line.
- Grout must remain clearly visible under all lighting conditions, including glossy and high-glossy finishes.
- Tile edges must be sharp and clean where they meet the grout channel.
- Grout texture should appear slightly rough and matte — never smooth, shiny, or matching the tile finish.{grout_sync_rule}

TILE SIZE ENFORCEMENT (CRITICAL — NON-NEGOTIABLE):
Floor tile size is {floor_size_lable}. {floor_count_check}
Wall tile size is {wall_size_lable}. {wall_count_check}
Before finalising the image, verify: count the tiles visible on any 1-meter span of floor or wall.
The count MUST match the stated tile density above. If it does not match, the tile size is rendered incorrectly — fix it.
Do NOT make tiles larger or smaller than declared. Do NOT guess the scale.

LIGHTING & MATERIAL FINISH:
Adjust lighting, reflections, and surface rendering strictly according to the specified tile finishes:
{lighting_rules}
Overall scene lighting must be natural, well-balanced, and consistent — no harsh overexposure or underlit areas.

QUALITY:
Ultra-detailed, 16K UHD output. Sharp textures, crisp edges, and accurate material rendering throughout.
The final result must look fully photorealistic and production-ready for professional architectural visualization — polished, premium, and lifelike.

TILE & GROUT LOCK (ABSOLUTE — NO MODIFICATION ALLOWED):
- The tile color, texture, finish, and pattern must remain EXACTLY identical to the provided tile reference images.
- Do NOT enhance, restyle, recolor, retexture, or reinterpret the tiles in any way.
- Do NOT apply filters, lighting effects, or reflections that alter the perceived tile color or design.
- Tiles must be reproduced 1:1 as real-world material surfaces, not artistically interpreted.

- Grout lines must remain EXACTLY as specified:
  - Width must be strictly {floor_grout_width} (floor) and {wall_grout_width} (wall) — no variation anywhere.
  - Grout must be fully visible across the entire tiled surface, with no fading, blending, or obstruction.
  - Do NOT reduce grout visibility due to lighting, reflections, or post-processing.
  - Grout must appear as a continuous recessed channel with consistent depth and sharp tile edges.
  - Do NOT stylize or smooth the grout — it must retain a natural matte, slightly rough finish.

- Under no circumstances should tile size, grout width, tile layout, or tile alignment be altered.
"""
    print(prompt,"##############################")
    return prompt


def generate_image_with_gemini(prompt, images):
    """
    Generate image using Google Gemini
    
    Args:
        prompt: Text prompt for image generation
        images: List of PIL Image objects
    
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
                                               image_config=types.ImageConfig(aspect_ratio="4:3")))

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
    return jsonify(analyze_tile_size(size_str)), 200

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
        
        # Save main image
        main_filename = secure_filename(main_file.filename)
        unique_main_filename = f"{uuid.uuid4().hex}_{main_filename}"
        main_filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_main_filename)
        main_file.save(main_filepath)
        uploaded_files.append(main_filepath)

        # Load main image as PIL Image
        main_pil_image = Image.open(main_filepath)
        images_for_gemini = [main_pil_image]
        ordinal_names = ["first image", "second image", "third image", "fourth image", "fifth image"]

        def save_optional_image(field_name):
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
            idx = len(images_for_gemini)
            images_for_gemini.append(Image.open(filepath))
            return ordinal_names[idx]

        first_img = "first image"
        second_img = save_optional_image('floor_tile_image')
        third_img = save_optional_image('wall_tile_image_1')
        forth_img = save_optional_image('wall_tile_image_2')
        fifth_img = save_optional_image('wall_tile_image_3')

        # Get form parameters
        floor_size_lable = request.form.get('floor_size_lable', '600x1200 mm')
        wall_size_lable = request.form.get('wall_size_lable', '600x1200 mm')
        floor_finish = request.form.get('floor_finish')
        wall_finish = request.form.get('wall_finish')
        floor_grout_color = request.form.get('floor_grout_color') or None
        wall_grout_color = request.form.get('wall_grout_color') or None
        sync_grout = request.form.get('sync_grout', 'false').lower() in ('true', '1', 'yes', 'on')
        scene = request.form.get('scene', 'living room')

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
        
        # Analyze tile sizes against Models/tile_size_model.pkl
        floor_size_info = analyze_tile_size(floor_size_lable)
        wall_size_info = analyze_tile_size(wall_size_lable)

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
            floor_grout_color=floor_grout_color,
            wall_grout_color=wall_grout_color,
            sync_grout=sync_grout,
            floor_count_check=floor_size_info['count_check'],
            wall_count_check=wall_size_info['count_check'],
            scene=scene
        )

        # Generate image with Gemini
        success, result = generate_image_with_gemini(prompt, images_for_gemini)
        
        if not success:
            return jsonify({
                'error': 'Image generation failed',
                'message': result
            }), 500
                
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


if __name__ == '__main__':
    # Use debug=True only when running locally for development
    app.run(debug=True, host='0.0.0.0', port=5000)