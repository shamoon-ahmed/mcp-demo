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
    <h2>Seller Dashboard</h2>
    <p>Click below to set up your inventory with Google Sheets.</p>
    <a href="/auth/start">Set up inventory with Google Sheets</a>
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
    <h2>Select your inventory sheet</h2>
    <form method="post" action="/select-sheet">
      <label>Choose sheet:</label>
      <select name="sheet_id">{options}</select>
      <input type="hidden" name="refresh_token" value="{encrypted}" />
      <br><br>
      <button type="submit">Save</button>
    </form>
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
    html = "<h3>Saved! You can now talk to the inventory agent (Chainlit) and it will use that sheet.</h3>"
    return HTMLResponse(html)
