import os
import json
import base64
import uuid
from datetime import datetime
import glob
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

INVOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_invoices')
os.makedirs(INVOICES_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cargoflowai-secret'
# Enable CORS for socket.io
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', max_http_buffer_size=1e8)

def get_api_key(client_key=None):
    """Retrieve API key from client or environment."""
    if client_key and client_key.strip():
        return client_key.strip()
    return os.getenv("GEMINI_API_KEY", "").strip()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/invoices')
def list_invoices():
    # Fetch all json files from INVOICES_DIR
    files = glob.glob(os.path.join(INVOICES_DIR, '*.json'))
    # Sort files by creation time descending (newest first)
    files.sort(key=os.path.getmtime, reverse=True)
    
    invoices = []
    for filepath in files:
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                invoices.append({
                    "id": os.path.basename(filepath),
                    "invoice_number": data.get("invoice_number", "Unknown"),
                    "carrier_name": data.get("carrier_name", "Unknown"),
                    "total_amount": data.get("total_amount", 0.0),
                    "currency": data.get("currency", ""),
                    "full_data": data # provide full data so frontend can show popup easily
                })
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
            
    return jsonify(invoices)


@socketio.on('connect')
def test_connect():
    emit('status_update', {'message': 'Connected to server'})

@socketio.on('upload_invoice')
def handle_upload(data):
    try:
        emit('status_update', {'message': 'File received by server. Preparing analysis...'})
        
        file_data = data.get('file')
        file_name = data.get('filename')
        client_key = data.get('api_key')
        
        if not file_data:
            raise ValueError("No file data received.")

        base_filename = os.path.splitext(file_name)[0]
        saved_id = f"{base_filename}.json"
        save_path = os.path.join(INVOICES_DIR, saved_id)

        # Skip extraction if we already have it saved
        if os.path.exists(save_path):
            emit('status_update', {'message': 'Invoice already processed. Loading from saved data...'})
            with open(save_path, 'r') as f:
                extracted_data = json.load(f)
            emit('upload_success', {'data': extracted_data, 'filename': file_name})
            return

        # Decode base64 file data
        try:
            header, encoded = file_data.split(",", 1)
            mime_type = header.split(":")[1].split(";")[0]
        except Exception:
            raise ValueError("Invalid file format. Must be a valid Data URL.")
            
        allowed_mimes = ["application/pdf", "image/jpeg", "image/png", "image/webp"]
        
        # Fallback to map extensions if mime_type from browser is weird
        if mime_type not in allowed_mimes:
            lower_name = file_name.lower()
            if lower_name.endswith('.pdf'): mime_type = 'application/pdf'
            elif lower_name.endswith(('.jpg', '.jpeg')): mime_type = 'image/jpeg'
            elif lower_name.endswith('.png'): mime_type = 'image/png'
            elif lower_name.endswith('.webp'): mime_type = 'image/webp'
            else:
                raise ValueError(f"Unsupported file type: {mime_type} / {file_name}. Please upload PDF or image files.")
                
        file_bytes = base64.b64decode(encoded)
        
        # Configure Gemini
        api_key = get_api_key(client_key)
        if not api_key:
            raise ValueError("Gemini API Key is missing. Please provide it in the UI or .env file.")
            
        genai.configure(api_key=api_key)
        
        emit('status_update', {'message': 'Calling Gemini AI for extraction...'})

        # System Prompt
        prompt = os.getenv("GEMINI_PROMPT", "")
        
        if not prompt:
            raise ValueError("GEMINI_PROMPT is missing from .env file.")
        
        # Configure model to output JSON natively
        generation_config = {"response_mime_type": "application/json"}
        model = genai.GenerativeModel("gemini-2.5-flash", generation_config=generation_config)
        
        # Pass document inline
        response = model.generate_content([
            {"mime_type": mime_type, "data": file_bytes},
            prompt
        ])
        
        result_text = response.text
        
        # Parse JSON
        extracted_data = json.loads(result_text)
        
        # Save invoice automatically as a JSON file
        base_filename = os.path.splitext(file_name)[0]
        saved_id = f"{base_filename}.json"
        save_path = os.path.join(INVOICES_DIR, saved_id)
        with open(save_path, 'w') as f:
            json.dump(extracted_data, f, indent=2)
        
        emit('status_update', {'message': 'Extraction completed & saved successfully!'})
        emit('upload_success', {'data': extracted_data, 'filename': file_name})

        
    except json.JSONDecodeError:
        emit('upload_error', {'error': 'Failed to parse AI response into JSON. The model may have returned invalid data.'})
    except Exception as e:
        emit('upload_error', {'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, debug=True, host='0.0.0.0', port=port)
