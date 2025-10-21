import os, json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request as GoogleRequest
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
FERNET_KEY = os.getenv("FERNET_KEY")

# Load Google credentials from client secret file
CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "google_client_secret.json")
with open(CLIENT_SECRET_FILE, 'r') as f:
    client_secrets = json.load(f)
    
GOOGLE_CLIENT_ID = client_secrets["web"]["client_id"]
GOOGLE_CLIENT_SECRET = client_secrets["web"]["client_secret"]

app = FastAPI()
app.mount("/static", StaticFiles(directory="templates"), name="static")

CLIENT_SECRETS = {
  "web": {
    "client_id": GOOGLE_CLIENT_ID,
    "client_secret": GOOGLE_CLIENT_SECRET,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris":[f"{BASE_URL}/auth/callback"]
  }
}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.metadata.readonly"]

def encrypt_secret(secret: str) -> str:
    # Encryption disabled for development
    return secret

def decrypt_secret(token: str) -> str:
    if not FERNET_KEY:
        return token
    from cryptography.fernet import Fernet
    f = Fernet(FERNET_KEY.encode())
    return f.decrypt(token.encode()).decode()

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
    # offline to get refresh_token; prompt=consent ensures refresh token is returned
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    # save state if you need; for simple flow we skip
    return RedirectResponse(auth_url)

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
    # list spreadsheet files
    files = drive.files().list(q="mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
                               fields="files(id,name)").execute().get("files", [])
    # render simple HTML to choose
    options = "".join([f'<option value="{f["id"]}">{f["name"]}</option>' for f in files])
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Select Inventory Sheet</title>
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
            }}
            
            .container {{
                background: white;
                border-radius: 16px;
                box-shadow: 0 20px 40px rgba(0,0,0,0.1);
                padding: 40px;
                max-width: 500px;
                width: 90%;
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
                margin-bottom: 24px;
                text-align: center;
            }}
            
            .form-group {{
                margin-bottom: 24px;
            }}
            
            label {{
                display: block;
                color: #4a5568;
                font-size: 14px;
                font-weight: 600;
                margin-bottom: 8px;
            }}
            
            select {{
                width: 100%;
                padding: 12px 16px;
                border: 2px solid #e2e8f0;
                border-radius: 8px;
                font-size: 16px;
                background: white;
                transition: border-color 0.3s ease;
            }}
            
            select:focus {{
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }}
            
            .btn {{
                width: 100%;
                background: linear-gradient(135deg, #667eea, #764ba2);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 14px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.3s ease;
            }}
            
            .btn:hover {{
                transform: translateY(-1px);
                box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="logo">📋</div>
            <h2>Select Your Inventory Sheet</h2>
            <form method="post" action="/select-sheet">
                <div class="form-group">
                    <label for="sheet_id">Choose your Google Sheet:</label>
                    <select name="sheet_id" id="sheet_id">{options}</select>
                </div>
                <input type="hidden" name="refresh_token" value="{encrypted}" />
                <button type="submit" class="btn">Save Configuration</button>
            </form>
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
