import os, json
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request as GoogleRequest
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FERNET_KEY = os.getenv("FERNET_KEY")

# Load Google credentials from client secret file
CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "google_client_secret.json")
with open(CLIENT_SECRET_FILE, 'r') as f:
    client_secrets = json.load(f)
    
GOOGLE_CLIENT_ID = client_secrets["web"]["client_id"]
GOOGLE_CLIENT_SECRET = client_secrets["web"]["client_secret"]

app = FastAPI()

# Mount static files with absolute path
# templates_dir = os.path.join(os.path.dirname(__file__), "templates")
# app.mount("/static", StaticFiles(directory=templates_dir), name="static")

CLIENT_SECRETS = {
  "web": {
    "client_id": GOOGLE_CLIENT_ID,
    "client_secret": GOOGLE_CLIENT_SECRET,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris":[f"{BASE_URL}/auth/callback"]
  }
}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",  # Full access for read/write
          "https://www.googleapis.com/auth/drive.metadata.readonly"]

def encrypt_secret(secret: str) -> str:
    # Encryption disabled for development
    return secret

def decrypt_secret(token: str) -> str:
    if not FERNET_KEY:
        print(f"No FERNET_KEY set, returning token as-is")
        return token
    try:
        from cryptography.fernet import Fernet
        f = Fernet(FERNET_KEY.encode())
        return f.decrypt(token.encode()).decode()
    except Exception as e:
        print(f"Decryption failed: {e}, returning token as-is")
        return token

@app.get("/", response_class=HTMLResponse)
def index():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Inventory Dashboard</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .container {
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                padding: 40px;
                text-align: center;
                max-width: 500px;
                width: 90%;
            }
            
            .logo {
                width: 64px;
                height: 64px;
                background: linear-gradient(135deg, #667eea, #764ba2);
                border-radius: 16px;
                margin: 0 auto 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 24px;
                font-weight: bold;
            }
            
            h1 {
                color: #2d3748;
                font-size: 28px;
                font-weight: 700;
                margin-bottom: 12px;
            }
            
            p {
                color: #718096;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 32px;
            }
            
            .btn {
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 12px;
                padding: 16px 32px;
                font-size: 16px;
                font-weight: 600;
                text-decoration: none;
                display: inline-block;
                transition: all 0.3s ease;
                cursor: pointer;
            }
            
            .btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px rgba(102, 126, 234, 0.4);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">📊</div>
            <h1>Inventory Dashboard</h1>
            <p>Connect your Google Sheets to start managing your inventory with AI-powered insights.</p>
            <a href="/auth/start" class="btn">Connect Google Sheets</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/auth/start")
def auth_start():
    flow = Flow.from_client_config(
        CLIENT_SECRETS,
        scopes=SCOPES,
        redirect_uri=f"{BASE_URL}/auth/callback"
    )
    # Force fresh consent to avoid scope conflicts
    auth_url, state = flow.authorization_url(access_type="offline", prompt="consent")
    return RedirectResponse(auth_url)

# API endpoint to get worksheets for a specific workbook
@app.get("/api/worksheets/{workbook_id}")
async def get_worksheets(workbook_id: str, token: str = Query(...)):
    try:
        print(f"API called with workbook_id: {workbook_id}")
        print(f"Token received: {token[:50]}...")  # Only print first 50 chars for security
        
        # Decrypt token if needed
        try:
            refresh_token = decrypt_secret(token)
            print(f"Token decrypted successfully")
        except Exception as decrypt_error:
            print(f"Token decryption failed: {decrypt_error}")
            return {"error": f"Token decryption failed: {decrypt_error}"}
        
        # Build credentials
        try:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                scopes=SCOPES
            )
            print(f"Credentials created successfully")
        except Exception as creds_error:
            print(f"Credentials creation failed: {creds_error}")
            return {"error": f"Credentials creation failed: {creds_error}"}
            
        try:
            creds.refresh(GoogleRequest())
            print(f"Credentials refreshed successfully")
        except Exception as refresh_error:
            print(f"Credentials refresh failed: {refresh_error}")
            return {"error": f"Credentials refresh failed: {refresh_error}"}
        
        # Build sheets service
        try:
            from googleapiclient.discovery import build
            sheets = build("sheets", "v4", credentials=creds)
            print(f"Sheets service built successfully")
        except Exception as sheets_error:
            print(f"Sheets service creation failed: {sheets_error}")
            return {"error": f"Sheets service creation failed: {sheets_error}"}
        
        # Get spreadsheet metadata to list all worksheets
        try:
            spreadsheet = sheets.spreadsheets().get(spreadsheetId=workbook_id).execute()
            print(f"Spreadsheet metadata retrieved successfully")
        except Exception as spreadsheet_error:
            print(f"Spreadsheet retrieval failed: {spreadsheet_error}")
            return {"error": f"Spreadsheet retrieval failed: {spreadsheet_error}"}
            
        worksheets = []
        
        try:
            for sheet in spreadsheet.get('sheets', []):
                worksheets.append({
                    'title': sheet['properties']['title'],
                    'sheet_id': sheet['properties']['sheetId']
                })
            print(f"Found {len(worksheets)} worksheets: {[w['title'] for w in worksheets]}")
        except Exception as parse_error:
            print(f"Worksheet parsing failed: {parse_error}")
            return {"error": f"Worksheet parsing failed: {parse_error}"}
            
        return {"worksheets": worksheets, "debug": "success"}
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in get_worksheets: {str(e)}")
        print(f"Full traceback: {error_details}")
        return {"error": str(e)}

@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return HTMLResponse("No code in callback", status_code=400)
    flow = Flow.from_client_config(
        CLIENT_SECRETS,
        scopes=SCOPES,
        redirect_uri=f"{BASE_URL}/auth/callback"
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    refresh_token = creds.refresh_token
    # encrypt optionally
    encrypted = encrypt_secret(refresh_token)
    # get an access token to list sheets
    creds_for_api = Credentials(token=creds.token, refresh_token=refresh_token,
                                token_uri="https://oauth2.googleapis.com/token",
                                client_id=GOOGLE_CLIENT_ID, client_secret=GOOGLE_CLIENT_SECRET,
                                scopes=SCOPES)
    # refresh to ensure token valid
    creds_for_api.refresh(GoogleRequest())
    drive = build("drive", "v3", credentials=creds_for_api)
    # list spreadsheet files dynamically
    files = drive.files().list(q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                               fields="files(id,name)").execute().get("files", [])
    
    # Create options for workbook dropdowns
    workbook_options = "".join([f'<option value="{f["id"]}">{f["name"]}</option>' for f in files])
    
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Setup Your Business Sheets</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            
            .container {{
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                padding: 40px;
                max-width: 600px;
                width: 100%;
            }}
            
            .logo {{
                width: 64px;
                height: 64px;
                background: linear-gradient(135deg, #667eea, #764ba2);
                border-radius: 16px;
                margin: 0 auto 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 24px;
            }}
            
            h2 {{
                color: #2d3748;
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 8px;
                text-align: center;
            }}
            
            .subtitle {{
                color: #718096;
                text-align: center;
                margin-bottom: 32px;
                font-size: 16px;
            }}
            
            .sheet-section {{
                background: #f7fafc;
                border-radius: 12px;
                padding: 24px;
                margin-bottom: 24px;
                border: 2px solid #e2e8f0;
            }}
            
            .sheet-title {{
                color: #2d3748;
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 16px;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            
            .form-row {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 16px;
                margin-bottom: 16px;
            }}
            
            .form-group {{
                display: flex;
                flex-direction: column;
            }}
            
            label {{
                color: #4a5568;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 6px;
            }}
            
            select {{
                padding: 12px 16px;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                font-size: 14px;
                background: white;
                transition: border-color 0.3s ease;
            }}
            
            select:focus {{
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }}
            
            select:disabled {{
                background: #f1f5f9;
                color: #94a3b8;
                cursor: not-allowed;
            }}
            
            .btn {{
                width: 100%;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 16px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-top: 16px;
            }}
            
            .btn:hover {{
                transform: translateY(-1px);
                box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
            }}
            
            .btn:disabled {{
                background: #cbd5e0;
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }}
            
            @media (max-width: 640px) {{
                .form-row {{
                    grid-template-columns: 1fr;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">🏪</div>
            <h2>Setup Your Business Sheets</h2>
            <p class="subtitle">Configure your inventory and orders management</p>
            
            <form method="post" action="/setup-sheets" id="sheetForm">
                <!-- Inventory Sheet Section -->
                <div class="sheet-section">
                    <div class="sheet-title">
                        📦 Inventory Sheet
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="inventory_workbook">Select Workbook:</label>
                            <select name="inventory_workbook" id="inventory_workbook" onchange="loadWorksheets('inventory')">
                                <option value="">Choose a workbook...</option>
                                {workbook_options}
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="inventory_worksheet">Select Worksheet:</label>
                            <select name="inventory_worksheet" id="inventory_worksheet" disabled>
                                <option value="">First select a workbook</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <!-- Orders Sheet Section -->
                <div class="sheet-section">
                    <div class="sheet-title">
                        📋 Orders Sheet
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="orders_workbook">Select Workbook:</label>
                            <select name="orders_workbook" id="orders_workbook" onchange="loadWorksheets('orders')">
                                <option value="">Choose a workbook...</option>
                                {workbook_options}
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="orders_worksheet">Select Worksheet:</label>
                            <select name="orders_worksheet" id="orders_worksheet" disabled>
                                <option value="">First select a workbook</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <input type="hidden" name="refresh_token" value="{encrypted}" />
                <button type="submit" class="btn" id="saveBtn" disabled>Save Configuration</button>
            </form>
        </div>
        
        <script>
            // Function to load worksheets when workbook is selected
            async function loadWorksheets(type) {{
                const workbookSelect = document.getElementById(type + '_workbook');
                const worksheetSelect = document.getElementById(type + '_worksheet');
                const workbookId = workbookSelect.value;
                
                // Reset worksheet dropdown
                worksheetSelect.innerHTML = '<option value="">Loading worksheets...</option>';
                worksheetSelect.disabled = true;
                
                if (!workbookId) {{
                    worksheetSelect.innerHTML = '<option value="">First select a workbook</option>';
                    checkFormComplete();
                    return;
                }}
                
                try {{
                    console.log(`Loading worksheets for workbook: ${{workbookId}}`);
                    const response = await fetch(`/api/worksheets/${{workbookId}}?token={encrypted}`);
                    console.log(`Response status: ${{response.status}}`);
                    
                    if (!response.ok) {{
                        throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
                    }}
                    
                    const data = await response.json();
                    console.log('Response data:', data);
                    
                    if (data.error) {{
                        console.error('API returned error:', data.error);
                        worksheetSelect.innerHTML = `<option value="">Error: ${{data.error}}</option>`;
                        return;
                    }}
                    
                    if (!data.worksheets || data.worksheets.length === 0) {{
                        worksheetSelect.innerHTML = '<option value="">No worksheets found</option>';
                        return;
                    }}
                    
                    // Populate worksheet dropdown
                    worksheetSelect.innerHTML = '<option value="">Choose a worksheet...</option>';
                    data.worksheets.forEach(sheet => {{
                        const option = document.createElement('option');
                        option.value = sheet.title;
                        option.textContent = sheet.title;
                        worksheetSelect.appendChild(option);
                    }});
                    
                    worksheetSelect.disabled = false;
                    worksheetSelect.onchange = checkFormComplete;
                    
                }} catch (error) {{
                    console.error('Error loading worksheets:', error);
                    worksheetSelect.innerHTML = `<option value="">Error: ${{error.message}}</option>`;
                }}
            }}
            
            // Check if form is complete to enable save button
            function checkFormComplete() {{
                const inventoryWorkbook = document.getElementById('inventory_workbook').value;
                const inventoryWorksheet = document.getElementById('inventory_worksheet').value;
                const ordersWorkbook = document.getElementById('orders_workbook').value;
                const ordersWorksheet = document.getElementById('orders_worksheet').value;
                
                const isComplete = inventoryWorkbook && inventoryWorksheet && ordersWorkbook && ordersWorksheet;
                document.getElementById('saveBtn').disabled = !isComplete;
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.post("/setup-sheets")
async def setup_sheets(
    inventory_workbook: str = Form(...),
    inventory_worksheet: str = Form(...),
    orders_workbook: str = Form(...),
    orders_worksheet: str = Form(...),
    refresh_token: str = Form(...)
):
    # Save enhanced configuration with both inventory and orders sheets
    data = {
        "inventory": {
            "workbook_id": inventory_workbook,
            "worksheet_name": inventory_worksheet
        },
        "orders": {
            "workbook_id": orders_workbook,
            "worksheet_name": orders_worksheet
        },
        "refresh_token": refresh_token
    }
    
    with open("connection.json", "w") as f:
        json.dump(data, f, indent=2)
    
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Configuration Saved</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .container {
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                padding: 40px;
                text-align: center;
                max-width: 500px;
                width: 90%;
            }
            
            .success-icon {
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #48bb78, #38a169);
                border-radius: 50%;
                margin: 0 auto 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 36px;
            }
            
            h2 {
                color: #2d3748;
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 16px;
            }
            
            p {
                color: #718096;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 32px;
            }
            
            .config-summary {
                background: #f7fafc;
                border-radius: 8px;
                padding: 20px;
                margin-bottom: 24px;
                text-align: left;
            }
            
            .config-item {
                margin-bottom: 12px;
                font-size: 14px;
            }
            
            .config-label {
                font-weight: 600;
                color: #4a5568;
            }
            
            .config-value {
                color: #2d3748;
            }
            
            .btn {
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: 600;
                text-decoration: none;
                display: inline-block;
                transition: all 0.3s ease;
                cursor: pointer;
            }
            
            .btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 15px rgba(102, 126, 234, 0.4);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✓</div>
            <h2>Configuration Saved!</h2>
            <p>Your business sheets have been successfully configured. You can now use the MCP client to manage inventory and process orders.</p>
            
            <div class="config-summary">
                <div class="config-item">
                    <span class="config-label">📦 Inventory Sheet:</span><br>
                    <span class="config-value">Workbook ID: """ + inventory_workbook + """</span><br>
                    <span class="config-value">Worksheet: """ + inventory_worksheet + """</span>
                </div>
                <div class="config-item">
                    <span class="config-label">📋 Orders Sheet:</span><br>
                    <span class="config-value">Workbook ID: """ + orders_workbook + """</span><br>
                    <span class="config-value">Worksheet: """ + orders_worksheet + """</span>
                </div>
            </div>
            
            <a href="/" class="btn">Return to Dashboard</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)

@app.post("/select-sheet")
async def select_sheet(sheet_id: str = Form(...), refresh_token: str = Form(...)):
    # save to connection.json
    data = {
        "sheet_id": sheet_id,
        "refresh_token": refresh_token
    }
    with open("connection.json", "w") as f:
        json.dump(data, f)
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Configuration Saved</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            
            .container {
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                padding: 40px;
                text-align: center;
                max-width: 500px;
                width: 90%;
            }
            
            .success-icon {
                width: 80px;
                height: 80px;
                background: linear-gradient(135deg, #48bb78, #38a169);
                border-radius: 50%;
                margin: 0 auto 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 36px;
            }
            
            h2 {
                color: #2d3748;
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 16px;
            }
            
            p {
                color: #718096;
                font-size: 16px;
                line-height: 1.6;
                margin-bottom: 32px;
            }
            
            .btn {
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: 600;
                text-decoration: none;
                display: inline-block;
                transition: all 0.3s ease;
                cursor: pointer;
            }
            
            .btn:hover {
                transform: translateY(-1px);
                box-shadow: 0 6px 15px rgba(102, 126, 234, 0.4);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="success-icon">✓</div>
            <h2>Configuration Saved!</h2>
            <p>Your inventory sheet has been successfully connected. You can now use the MCP client to query your inventory data with AI-powered assistance.</p>
            <a href="/" class="btn">Return to Dashboard</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)
