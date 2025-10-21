import os, json, time
from mcp.server.fastmcp import FastMCP   # keep using your MCP server lib
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from cryptography.fernet import Fernet

mcp = FastMCP("Inventory Server")

CONN_FILE = os.path.join(os.path.dirname(__file__), "..", "dashboard", "connection.json")
# load fernet key if you used encryption
FERNET_KEY = os.getenv("FERNET_KEY")

# Load Google credentials from client secret file
CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "google_client_secret.json")
with open(CLIENT_SECRET_FILE, 'r') as f:
    client_secrets = json.load(f)
    
GOOGLE_CLIENT_ID = client_secrets["web"]["client_id"]
GOOGLE_CLIENT_SECRET = client_secrets["web"]["client_secret"]

def decrypt_if_needed(token_enc: str) -> str:
    print(f"[DEBUG] Decrypting token... FERNET_KEY exists: {bool(FERNET_KEY)}")
    if not token_enc:
        print("[ERROR] No token provided for decryption")
        return None
    # Encryption disabled for development
    print("[DEBUG] Encryption disabled, returning token as-is")
    return token_enc

def load_connection():
    print(f"[DEBUG] Checking connection file: {CONN_FILE}")
    if not os.path.exists(CONN_FILE):
        print(f"[ERROR] Connection file does not exist: {CONN_FILE}")
        return None
    
    print("[DEBUG] Connection file exists, loading...")
    try:
        with open(CONN_FILE, "r") as f:
            data = json.load(f)
        print(f"[DEBUG] Connection file loaded successfully. Keys: {list(data.keys())}")
        # decrypt refresh token if encrypted
        if "refresh_token" in data:
            data["refresh_token"] = decrypt_if_needed(data["refresh_token"])
        return data
    except Exception as e:
        print(f"[ERROR] Failed to load connection file: {e}")
        return None

def build_sheets_service_from_refresh(refresh_token):
    print("[DEBUG] Building credentials from refresh token...")
    print(f"[DEBUG] Client ID: {GOOGLE_CLIENT_ID}")
    print(f"[DEBUG] Client Secret exists: {bool(GOOGLE_CLIENT_SECRET)}")
    
    # Decrypt the refresh token if needed
    decrypted_token = decrypt_if_needed(refresh_token)
    print(f"[DEBUG] Token decrypted successfully: {bool(decrypted_token)}")
    print(f"[DEBUG] Decrypted token length: {len(decrypted_token) if decrypted_token else 0}")
    
    creds = Credentials(
        token=None,
        refresh_token=decrypted_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    print("[DEBUG] Credentials object created, attempting refresh...")
    
    try:
        # refresh to get an access token
        creds.refresh(Request())
        print("[DEBUG] Token refresh successful!")
        print(f"[DEBUG] Access token exists: {bool(creds.token)}")
    except Exception as refresh_error:
        print(f"[ERROR] Token refresh failed: {refresh_error}")
        raise
    
    print("[DEBUG] Building Google Sheets service...")
    service = build("sheets", "v4", credentials=creds)
    print("[DEBUG] Google Sheets service built successfully")
    return service

@mcp.tool()
def google_sheets_query_tool(query: str) -> str:
    """
    Query the inventory data in Google Sheets using the sheet selected in dashboard.
    This reads connection.json (the selected sheet_id & refresh_token).
    """
    print("[DEBUG] Query from agent:", query)
    
    # Load connection file
    print(f"[DEBUG] Loading connection from: {CONN_FILE}")
    conn = load_connection()
    if not conn:
        print("[ERROR] No connection configured")
        return json.dumps({"error":"no_connection_configured"})
    
    print(f"[DEBUG] Connection loaded: {conn.keys()}")
    sheet_id = conn.get("sheet_id")
    refresh_token = conn.get("refresh_token")
    
    print(f"[DEBUG] Sheet ID: {sheet_id}")
    print(f"[DEBUG] Refresh token exists: {bool(refresh_token)}")
    print(f"[DEBUG] Refresh token length: {len(refresh_token) if refresh_token else 0}")
    
    if not (sheet_id and refresh_token):
        print("[ERROR] Missing sheet_id or refresh_token")
        return json.dumps({"error":"missing_sheet_or_token"})
    
    try:
        print("[DEBUG] Building Google Sheets service...")
        service = build_sheets_service_from_refresh(refresh_token)
        print("[DEBUG] Google Sheets service created successfully")
        
        print(f"[DEBUG] Getting spreadsheet metadata for ID: {sheet_id}")
        # Get spreadsheet metadata to find all sheets
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheets = spreadsheet.get('sheets', [])
        print(f"[DEBUG] Found {len(sheets)} sheets: {[s['properties']['title'] for s in sheets]}")
        
        all_data = {}
        
        for sheet in sheets:
            sheet_name = sheet['properties']['title']
            
            # Get the dimensions of the sheet to determine the range
            sheet_properties = sheet['properties']
            grid_properties = sheet_properties.get('gridProperties', {})
            row_count = grid_properties.get('rowCount', 1000)
            col_count = grid_properties.get('columnCount', 26)
            
            # Convert column count to letter (A, B, C, ..., Z, AA, AB, etc.)
            def num_to_col_letters(n):
                string = ""
                while n > 0:
                    n, remainder = divmod(n - 1, 26)
                    string = chr(65 + remainder) + string
                return string
            
            last_col = num_to_col_letters(col_count)
            range_name = f"{sheet_name}!A1:{last_col}{row_count}"
            
            # Get all data from the sheet
            res = service.spreadsheets().values().get(
                spreadsheetId=sheet_id, 
                range=range_name,
                valueRenderOption='UNFORMATTED_VALUE'
            ).execute()
            
            rows = res.get("values", [])
            
            if not rows:
                continue
                
            # Use first row as headers
            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []
            
            # Convert to list of dictionaries using headers
            sheet_data = []
            for row in data_rows:
                # Skip completely empty rows
                if not any(cell for cell in row if str(cell).strip()):
                    continue
                    
                row_dict = {}
                for i, header in enumerate(headers):
                    # Get cell value or empty string if column doesn't exist in this row
                    cell_value = row[i] if i < len(row) else ""
                    # Clean header name (remove spaces, special chars for cleaner keys)
                    clean_header = str(header).strip().lower().replace(' ', '_').replace('-', '_')
                    if clean_header:  # Only add if header is not empty
                        row_dict[clean_header] = str(cell_value).strip() if cell_value else ""
                
                if row_dict:  # Only add if row has some data
                    sheet_data.append(row_dict)
            
            if sheet_data:  # Only add sheet if it has data
                all_data[sheet_name] = {
                    'headers': headers,
                    'data': sheet_data,
                    'row_count': len(sheet_data)
                }
        
        return json.dumps({
            "query": query, 
            "spreadsheet_data": all_data,
            "total_sheets": len(all_data)
        })
    except Exception as e:
        print("Error accessing sheets:", e)
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()
