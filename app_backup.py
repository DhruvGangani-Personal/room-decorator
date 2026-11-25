from flask import Flask, request, jsonify, send_file
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
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_interior_prompt(
    main_image: str,
    floor_tile_image: str = None,
    wall_tile_image_1: str = None,
    wall_tile_image_2: str = None,
    floor_size: str = "600x1200 mm",
    wall_size: str = "600x1200 mm",
    floor_finish: str = None,
    wall_finish: str = None,
    scene: str = None
):
    """Generate interior design prompt based on provided parameters"""
    
    # Floor instruction
    if floor_tile_image and floor_finish:
        floor_instruction = f"Apply floor tiles design from {floor_tile_image} with tile size {floor_size} and finish {floor_finish}. Keep tiles color and design unchanged. "
    else:
        floor_instruction = "Floor should remain plain."
    
    # Wall instruction
    if wall_tile_image_1 and wall_tile_image_2 and wall_finish:
        wall_instruction = f"Apply wall tiles design to left from {wall_tile_image_1} with tile size {wall_size} and finish {wall_finish} and Apply tiles design to right from {wall_tile_image_2} with tile size {wall_size} and finish {wall_finish}. Keep tiles color and design unchanged"
    elif wall_tile_image_1 and wall_finish:
        wall_instruction = f"Apply wall tiles design from {wall_tile_image_1} with tile size {wall_size} and finish {wall_finish}. Keep tiles color and design unchanged"
    elif wall_tile_image_2 and wall_finish:
        wall_instruction = f"Apply wall tiles design from {wall_tile_image_2} with tile size {wall_size} and finish {wall_finish}. Keep tiles color and design unchanged"
    else:
        # wall_instruction = "all side Walls should remain plain. and walls color should according to tile color image. Any part of first image color should not contain construction materials color or material."

        wall_instruction = "all Walls should remain plain. and walls color should according to tile color image."

    # Collect unique finishes
    finishes = set(filter(None, [floor_finish, wall_finish]))
    
    # Dynamic lighting/material rules
    rules_map = {
        "glossy": "- Glossy: add very soft reflections and very low sunlight reflection if coming from door or window. keep tiles color dark so that it will be look visible clearly.",
        "high glossy": "- High glossy: add strong reflections, high shine, and brighter highlights.",
        "matt": "- Matt: reduce reflections, create a smooth and muted finish."
    }
    lighting_rules = "\n".join(rules_map[f] for f in finishes if f in rules_map)


    
    prompt = f"""
STRICT LAYOUT & CAMERA LOCK (MANDATORY):
- Use {main_image} as the exact spatial reference.
- Preserve camera angle, perspective, framing, and field of view.
- Do NOT change room geometry, proportions, walls, floor boundaries, ceiling height, or openings.
- Do NOT move, resize, crop, rotate, or reinterpret the layout.
- Do NOT change tiles color or pattern from the provided tile images.
- Architectural structure must remain 100% identical to {main_image}.
- Applied tiles should not covred by any carpet, rug, or floor mat. Keep tiles fully visible and unobstructed.
- Do NOT add carpeting, rugs, or floor mats that cover the tile image.

Recreate a premium interior scene for a space named {scene} using {main_image}. Layout of {main_image} should remain unchanged. 
Floor: {floor_instruction}
Wall: {wall_instruction}
Ceiling: The ceiling should be plain and simple, without any tiles or patterns. It should complement the overall design and color scheme of the room, ensuring a cohesive look that does not distract from the tiled walls and floor.

Beyond the floor and wall areas, decorate the remaining space with furniture, lighting, and accessories that match a modern interior concept for {scene}.

grout lines should be realistic, with appropriate width, color, and slight imperfections for a natural look.

remove any construction materials, tools,iron rods,wooden rods or objects that are not part of the final design.
Make sure the overall rendering looks photo-realistic, well-lit, and ready for architectural visualization.
Lighting & Material: Adjust the lighting and reflections according to the specified tile finishes:  
{lighting_rules}

Make sure no construction materials, tools, iron rods, or objects that are not part of the final design are visible in the render.

Ensure tiles are aligned seamlessly with realistic grout lines, soft shadows, and according to first image.

Quality: Ultra-detailed, 16K UHD, crisp, and well-lit with sharp textures. Output should look suitable for architectural visualization—polished, premium, and lifelike.
    """


    app.logger.info(f"Generated prompt: {prompt.strip()}")
    
    return prompt.strip()

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

        # dfsdf


        # Generate content with Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-image",
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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Interior Design Generator API Working'
    }), 200

@app.route('/generate-prompt', methods=['POST'])
def generate_prompt():
    """
    Generate interior design prompt and image
    
    Form data:
    - main_image: file (required)
    - floor_tile_image: file (optional)
    - wall_tile_image_1: file (optional)
    - wall_tile_image_2: file (optional)
    - floor_size: string (optional, default: "600x1200 mm")
    - wall_size: string (optional, default: "600x1200 mm")
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

        floor_file = wall_file = wall_file_2 = None

        # Handle optional floor tile image
        floor_tile_filepath = None
        if 'floor_tile_image' in request.files:
            floor_file = request.files['floor_tile_image']
            if floor_file.filename != '' and allowed_file(floor_file.filename):
                floor_filename = secure_filename(floor_file.filename)
                unique_floor_filename = f"{uuid.uuid4().hex}_{floor_filename}"
                floor_tile_filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_floor_filename)
                floor_file.save(floor_tile_filepath)
                uploaded_files.append(floor_tile_filepath)
                images_for_gemini.append(Image.open(floor_tile_filepath))
        
        # Handle optional wall tile image 1
        wall_tile_filepath = None
        if 'wall_tile_image_1' in request.files:
            wall_file = request.files['wall_tile_image_1']
            if wall_file.filename != '' and allowed_file(wall_file.filename):
                wall_filename = secure_filename(wall_file.filename)
                unique_wall_filename = f"{uuid.uuid4().hex}_{wall_filename}"
                wall_tile_filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_wall_filename)
                wall_file.save(wall_tile_filepath)
                uploaded_files.append(wall_tile_filepath)
                images_for_gemini.append(Image.open(wall_tile_filepath))

        # Handle optional wall tile image 2
        wall_2_tile_filepath = None
        if 'wall_tile_image_2' in request.files:
            wall_file_2 = request.files['wall_tile_image_2']
            if wall_file_2.filename != '' and allowed_file(wall_file_2.filename):
                wall_file_2_name = secure_filename(wall_file_2.filename)
                unique_wall_file_2_name = f"{uuid.uuid4().hex}_{wall_file_2_name}"
                wall_2_tile_filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_wall_file_2_name)
                wall_file_2.save(wall_2_tile_filepath)
                uploaded_files.append(wall_2_tile_filepath)
                images_for_gemini.append(Image.open(wall_2_tile_filepath))


        wall_file_2 = None
        
        # Get form parameters
        floor_size = request.form.get('floor_size', '600x1200 mm')
        wall_size = request.form.get('wall_size', '600x1200 mm')
        floor_finish = request.form.get('floor_finish')
        wall_finish = request.form.get('wall_finish')
        scene = request.form.get('scene', 'living room')

        # Determine image references for prompt
        first_img = "first image"
        second_img = third_img = forth_img = None

        if main_file:
            if floor_file and wall_file and wall_file_2:
                second_img = "second image"
                third_img = "third image"
                forth_img = "fourth image"
            elif wall_file and wall_file_2:
                second_img = "second image"
                forth_img = "third image"
            elif floor_file and wall_file:
                second_img = "second image"
                third_img = "third image"
            elif floor_file and wall_file_2:
                second_img = "second image"
                forth_img = "third image"
            elif floor_file:
                second_img = "second image"
            elif wall_file:
                third_img = "second image"
            elif wall_file_2:
                forth_img = "second image"
                
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
        
        # Generate prompt
        prompt = generate_interior_prompt(
            main_image=first_img,
            floor_tile_image=second_img,
            wall_tile_image_1=third_img,
            wall_tile_image_2=forth_img,
            floor_size=floor_size,
            wall_size=wall_size,
            floor_finish=floor_finish,
            wall_finish=wall_finish,
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