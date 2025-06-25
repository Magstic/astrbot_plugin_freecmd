from flask import Flask, render_template, send_from_directory, request, jsonify, send_file
import os
import io
import json
from image_generator import generate_image_with_text

app = Flask(__name__, template_folder='.')

# Define base asset paths relative to this file's location
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')
FONT_DIR = os.path.join(ASSETS_DIR, 'font')
TEMPLATE_DIR = os.path.join(ASSETS_DIR, 'templates')

@app.route('/')
def editor():
    try:
        fonts = [f for f in os.listdir(FONT_DIR) if os.path.isfile(os.path.join(FONT_DIR, f)) and not f.startswith('.')]
        templates = [f for f in os.listdir(TEMPLATE_DIR) if os.path.isfile(os.path.join(TEMPLATE_DIR, f)) and not f.startswith('.')]
        return render_template('editor.html', fonts=fonts, templates=templates)
    except FileNotFoundError:
        # Fallback for when assets directory doesn't exist yet
        return render_template('editor.html', fonts=[], templates=[])


@app.route('/preview', methods=['POST'])
def preview():
    data = request.json
    text = data.get('text', '')
    options = data.get('options', {})

    # Generate the image buffer
    image_buffer, output_format = generate_image_with_text(text, options)

    if image_buffer is not None:
        mimetype = f'image/{output_format}'
        # Use io.BytesIO to wrap the buffer for send_file, avoiding temp files
        return send_file(
            io.BytesIO(image_buffer.tobytes()),
            mimetype=mimetype
        )
    else:
        return jsonify({'error': 'Image generation failed'}), 500

if __name__ == '__main__':
    print("=========================================================")
    print("  Visual Editor for Office Command")
    print("  Open your browser and go to: http://127.0.0.1:5001")
    print("=========================================================")
    app.run(port=5001, debug=True)
