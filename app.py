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
        prompt = """
### Role
Logistics Finance IDP Agent. Extract shipping invoices with **100% LINE ITEM ACCURACY** as top priority.

### PRIORITY ORDER (CRITICAL)

**PRIORITY 1: LINE ITEMS (MOST IMPORTANT)**
- Extract **EVERY** charge row from the charges table
- For each line item capture:
  - `description`: Exact charge name (e.g., "THC DESTINATION", "Ocean Freight", "Freight Charges")
  - `quantity`: Number (normalize "1.000" → 1.0, "2.00" → 2.0)
  - `unit`: Basis code (BIL, CTR, WM, KG, 40HC, 4RH, etc.)
  - `rate`: Unit price (e.g., 245.00)
  - `amount`: Line total (MUST equal quantity × rate)
- **DO NOT SKIP** any charge rows
- **DO NOT** extract cargo descriptions ("FRESH HERBS", "RUBBER SHEET") as line items
- **DO NOT** extract addresses or company names as line items
- **VALIDATE**: Sum of all line item amounts should match total_amount (±0.01)

**PRIORITY 2: SHIPPING REFERENCES**
- **Sea Freight**:
  - `bill_of_lading`: "B/L No", "LINE BILL OF LADING" (e.g., EGLV003400931104)
  - `sea_waybill`: "SWB-NO", pattern "HLCUSCL..." (e.g., HLCUSCL240753831, HLCUSCL240776178)
  - `house_bill_of_lading`: "AMS HB/L NO:", "HOUSE BILL OF LADING" (e.g., 83060385, B/L NR. : EGLV140503204907)
- **Air Freight**:
  - `mawb`: "MAWB" (exactly 11 digits: 23541142916)
  - `hawb`: "HAWB" (e.g., SE00095313)
- **Containers**:
  - Format: 4 letters + 7 digits (HLBU9951582, EITU9300701, TCNU5273976, EMCU5610174, MSDU9820720, MNBU3040994, HLXU8789237)
  - Remove spaces: "HLBU  9951582" → "HLBU9951582"
  - Extract ALL containers (often 2+)
  - **DO NOT** include types: 40HC, 20GP, 40RH

**PRIORITY 3: CORE FIELDS**
- `carrier_name`: Issuer (Hapag-Lloyd, Shipco, Evergreen, MSC, Abacus, LiftCargo, ICL Group)
- `invoice_number`: Invoice number
- `invoice_date`: YYYY-MM-DD
- `invoice_due_date`: YYYY-MM-DD (MUST be >= invoice_date)
- `total_amount`: Grand total
- `currency`: GBP, USD, EUR
- `transaction_type`: ICL in "Bill To" = Payable | ICL in "Header" = Receivable

**PRIORITY 4: VAT NUMBERS**
- `vat_numbers.issuer`: From issuer section
  - Hapag-Lloyd: DE813960018
  - Shipco: GB597108020
  - Evergreen: GB245743452
  - MSC: GB316821468
  - Abacus: 389038164
  - LiftCargo: P051311945S
- `vat_numbers.customer`: From Bill To (ICL = GB849450791)
- **NEVER** let both equal GB849450791

### LINE ITEM EXTRACTION BY CARRIER

**Hapag-Lloyd** (Sea Freight):
- Table columns: Description | Rate | Qty | Unit | Amount
- Example lines:
  - "POR ADMIN FEE DEST" | 55.00 | 1 | BIL | 55.00
  - "THC DESTINATION" | 245.00 | 2 | CTR | 490.00
  - "EQUIPM.MAINTEN.FEE" | 16.00 | 2 | CTR | 32.00

**Shipco** (Arrival Notice):
- Table: "FREIGHT CHARGES | BASIS | RATE | AMOUNT DUE"
- Example:
  - "Ocean Freight" | WM | 206.00 | 7,082.28
- **DO NOT** extract "CHLOROPRENE NEOPRENE RUBBER SHEET" (cargo description)

**Evergreen** (Sea Freight):
- Table: RVT/RVT-UNIT CODE CUR RATE/AMOUNT
- Example:
  - "ISPS/D" | 4RH | 16.00 | 16.00
  - "LOLO.D" | 4RH | 60.00 | 60.00
  - "THC/D" | 4RH | 285.00 | 285.00
  - "DOCUMENT FEE" | B/L | 35.00 | 35.00

**MSC** (Sea Freight):
- Table: Description | Qty@Rate | Amount
- Example:
  - "Terminal Handling Charge" | 1.00@ 235.00 | 235.00
  - "UK Documentation" | 1.00@ 45.00 | 45.00
  - "UK Equipment Condition Fee" | 1.00@ 12.00 | 12.00
  - "UK Land Tax" | 1.00@ 1.81 | 1.81

**Abacus** (Road Freight):
- Action table: Date | Action | Load | Location
- Extract actions as line items:
  - "COLLECT" | 1 | 40HC | (amount from total)
  - "WAIT AND UNLOAD 09:00" | 1 | 40HC
  - "DELIVER" | 1 | 40HC

**LiftCargo** (Air Freight):
- Table: DESCRIPTION | QTY | VAT | IN USD CHARGES
- Example:
  - "Freight Charges" | 1 | Zero Rated | 1,601.06
  - "Airway Bill Fee" | 1 | Zero Rated | 55.00

**ICL Group** (Receivable):
- Table: DESCRIPTION | AMOUNT | VAT RATE
- Example:
  - "Haulage Charges" | 561.00 | 20.00
  - "Addn Del/Col" | 45.00 | 20.00
  - "Fuel Surcharge" | 28.05 | 20.00
  - "VBS" | 5.00 | 20.00

### JSON SCHEMA
{
  "carrier_name": "string",
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "invoice_due_date": "YYYY-MM-DD",
  "transaction_type": "Payable|Receivable",
  "currency": "GBP|USD|EUR",
  "total_amount": 0.00,
  "line_items": [
    {"description": "string", "quantity": 0.0, "unit": "string", "rate": 0.00, "amount": 0.00}
  ],
  "bill_of_lading": "string",
  "house_bill_of_lading": "string",
  "sea_waybill": [],
  "mawb": "string",
  "hawb": "string",
  "container_numbers": [],
  "vat_numbers": {"issuer": "string", "customer": "string"},
  "vessel_name": "string",
  "voyage_number": "string",
  "flight_number": "string",
  "reference": "string",
  "job_id": "string",
  "bank_info": {"bank_name": "string", "account_number": "string", "sort_code": "string", "iban": "string", "swift_bic": "string"},
  "extraction_notes": []
}

### VALIDATION CHECKLIST (Before Return)
- [ ] ALL line items extracted (count matches document)
- [ ] Line item amounts sum to total_amount (±0.01)
- [ ] Each line: amount = quantity × rate
- [ ] No cargo descriptions in line items
- [ ] B/L, SWB, MAWB, HAWB extracted correctly
- [ ] All container numbers extracted (4 letters + 7 digits)
- [ ] VAT issuer ≠ VAT customer
- [ ] due_date >= invoice_date

### Constraints
- Return ONLY valid JSON. No markdown.
- **LINE ITEMS ARE #1 PRIORITY** - extract all with correct rates/amounts
- Use null for missing fields
- Numbers as float/int, not strings
"""
        
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
