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
        
        # Handle both old and new format
        if "inventory" in data and "orders" in data:
            # New dual-sheet format
            print("[DEBUG] New dual-sheet configuration detected")
            if "refresh_token" in data:
                data["refresh_token"] = decrypt_if_needed(data["refresh_token"])
            return data
        elif "sheet_id" in data:
            # Old single-sheet format - convert to new format
            print("[DEBUG] Old single-sheet configuration detected, converting...")
            new_data = {
                "inventory": {
                    "workbook_id": data["sheet_id"],
                    "worksheet_name": "Sheet1"  # Default assumption
                },
                "orders": {
                    "workbook_id": data["sheet_id"],
                    "worksheet_name": "Orders"  # Default assumption
                },
                "refresh_token": decrypt_if_needed(data.get("refresh_token"))
            }
            return new_data
        else:
            print("[ERROR] Invalid connection file format")
            return None
            
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
        scopes=["https://www.googleapis.com/auth/spreadsheets"]  # Removed .readonly for write access
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

def get_sheet_data(service, workbook_id, worksheet_name):
    """Helper function to get data from a specific worksheet"""
    print(f"[DEBUG] Getting data from workbook {workbook_id}, worksheet {worksheet_name}")
    
    # Get all data from the specified worksheet
    range_name = f"{worksheet_name}!A1:Z1000"  # Reasonable range
    
    res = service.spreadsheets().values().get(
        spreadsheetId=workbook_id, 
        range=range_name,
        valueRenderOption='UNFORMATTED_VALUE'
    ).execute()
    
    rows = res.get("values", [])
    
    if not rows:
        return {"headers": [], "data": [], "row_count": 0}
        
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
    
    return {
        'headers': headers,
        'data': sheet_data,
        'row_count': len(sheet_data)
    }

@mcp.tool()
def get_inventory_tool(query: str = "all") -> str:
    """
    Get current inventory data from the inventory sheet.
    Use this to check product availability, stock levels, and product information.
    """
    print(f"[DEBUG] Inventory query from agent: {query}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    inventory_config = conn.get("inventory")
    refresh_token = conn.get("refresh_token")
    
    if not inventory_config or not refresh_token:
        return json.dumps({"error": "missing_inventory_config_or_token"})
    
    try:
        service = build_sheets_service_from_refresh(refresh_token)
        inventory_data = get_sheet_data(
            service, 
            inventory_config["workbook_id"], 
            inventory_config["worksheet_name"]
        )
        
        return json.dumps({
            "query": query,
            "inventory": inventory_data,
            "timestamp": time.time()
        })
    except Exception as e:
        print(f"[ERROR] Failed to get inventory: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def get_orders_tool(query: str = "recent") -> str:
    """
    Get orders data from the orders sheet.
    Use this to check recent orders, order history, and order status.
    """
    print(f"[DEBUG] Orders query from agent: {query}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    orders_config = conn.get("orders")
    refresh_token = conn.get("refresh_token")
    
    if not orders_config or not refresh_token:
        return json.dumps({"error": "missing_orders_config_or_token"})
    
    try:
        service = build_sheets_service_from_refresh(refresh_token)
        orders_data = get_sheet_data(
            service, 
            orders_config["workbook_id"], 
            orders_config["worksheet_name"]
        )
        
        return json.dumps({
            "query": query,
            "orders": orders_data,
            "timestamp": time.time()
        })
    except Exception as e:
        print(f"[ERROR] Failed to get orders: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def check_stock_tool(product_name: str, required_quantity: int = 1) -> str:
    """
    Check if sufficient stock is available for a product.
    Returns stock status and available quantity.
    """
    print(f"[DEBUG] Stock check: {product_name}, quantity: {required_quantity}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    inventory_config = conn.get("inventory")
    refresh_token = conn.get("refresh_token")
    
    if not inventory_config or not refresh_token:
        return json.dumps({"error": "missing_inventory_config_or_token"})
    
    try:
        service = build_sheets_service_from_refresh(refresh_token)
        inventory_data = get_sheet_data(
            service, 
            inventory_config["workbook_id"], 
            inventory_config["worksheet_name"]
        )
        
        # Search for the product
        product_found = False
        available_quantity = 0
        
        for item in inventory_data["data"]:
            # Check if product name matches (case insensitive)
            for key, value in item.items():
                if "name" in key.lower() or "product" in key.lower():
                    if product_name.lower() in value.lower():
                        product_found = True
                        # Look for quantity/stock column
                        for qty_key, qty_value in item.items():
                            if any(word in qty_key.lower() for word in ["quantity", "stock", "qty", "available"]):
                                try:
                                    available_quantity = int(float(qty_value)) if qty_value else 0
                                    break
                                except:
                                    available_quantity = 0
                        break
            if product_found:
                break
        
        stock_sufficient = available_quantity >= required_quantity
        
        return json.dumps({
            "product_name": product_name,
            "required_quantity": required_quantity,
            "available_quantity": available_quantity,
            "stock_sufficient": stock_sufficient,
            "product_found": product_found,
            "timestamp": time.time()
        })
        
    except Exception as e:
        print(f"[ERROR] Failed to check stock: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def record_order_tool(order_data: str) -> str:
    """
    Record a new order in the orders sheet.
    order_data should be JSON string with order details like:
    {"customer_name": "John Doe", "product": "Widget A", "quantity": 2, "price": 25.99}
    """
    print(f"[DEBUG] Recording order: {order_data}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    orders_config = conn.get("orders")
    refresh_token = conn.get("refresh_token")
    
    if not orders_config or not refresh_token:
        return json.dumps({"error": "missing_orders_config_or_token"})
    
    try:
        # Parse order data
        try:
            order = json.loads(order_data)
        except:
            return json.dumps({"error": "invalid_order_data_format"})
        
        service = build_sheets_service_from_refresh(refresh_token)
        
        # Get current orders to understand the structure
        current_orders = get_sheet_data(
            service, 
            orders_config["workbook_id"], 
            orders_config["worksheet_name"]
        )
        
        # Add timestamp and order ID
        order["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        order["order_id"] = f"ORD-{int(time.time())}"
        
        # Prepare the row data based on existing headers
        headers = current_orders["headers"]
        new_row = []
        
        for header in headers:
            clean_header = str(header).strip().lower().replace(' ', '_').replace('-', '_')
            value = order.get(clean_header, "")
            new_row.append(str(value))
        
        # If no headers exist, create them
        if not headers:
            headers = list(order.keys())
            new_row = list(order.values())
            
            # Add headers first
            service.spreadsheets().values().append(
                spreadsheetId=orders_config["workbook_id"],
                range=f"{orders_config['worksheet_name']}!A1",
                valueInputOption='RAW',
                body={'values': [headers]}
            ).execute()
        
        # Add the new order
        service.spreadsheets().values().append(
            spreadsheetId=orders_config["workbook_id"],
            range=f"{orders_config['worksheet_name']}!A:A",
            valueInputOption='RAW',
            body={'values': [new_row]}
        ).execute()
        
        return json.dumps({
            "success": True,
            "order_id": order.get("order_id"),
            "message": "Order recorded successfully",
            "timestamp": time.time()
        })
        
    except Exception as e:
        print(f"[ERROR] Failed to record order: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def update_inventory_tool(product_name: str, quantity_change: int) -> str:
    """
    Update inventory quantity for a product (e.g., reduce stock after an order).
    quantity_change can be negative (reduce stock) or positive (add stock).
    """
    print(f"[DEBUG] Updating inventory: {product_name}, change: {quantity_change}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    inventory_config = conn.get("inventory")
    refresh_token = conn.get("refresh_token")
    
    if not inventory_config or not refresh_token:
        return json.dumps({"error": "missing_inventory_config_or_token"})
    
    try:
        service = build_sheets_service_from_refresh(refresh_token)
        
        # Get current inventory data
        inventory_data = get_sheet_data(
            service, 
            inventory_config["workbook_id"], 
            inventory_config["worksheet_name"]
        )
        
        # Find the product and update quantity
        product_found = False
        row_index = -1
        quantity_col_index = -1
        
        for i, item in enumerate(inventory_data["data"]):
            # Check if product name matches
            for key, value in item.items():
                if "name" in key.lower() or "product" in key.lower():
                    if product_name.lower() in value.lower():
                        product_found = True
                        row_index = i + 2  # +2 because of 0-indexing and header row
                        
                        # Find quantity column
                        for j, header in enumerate(inventory_data["headers"]):
                            clean_header = header.lower()
                            if any(word in clean_header for word in ["quantity", "stock", "qty", "available"]):
                                quantity_col_index = j
                                break
                        break
            if product_found:
                break
        
        if not product_found:
            return json.dumps({"error": "product_not_found"})
        
        if quantity_col_index == -1:
            return json.dumps({"error": "quantity_column_not_found"})
        
        # Get current quantity
        current_qty_range = f"{inventory_config['worksheet_name']}!{chr(65 + quantity_col_index)}{row_index}"
        current_qty_result = service.spreadsheets().values().get(
            spreadsheetId=inventory_config["workbook_id"],
            range=current_qty_range
        ).execute()
        
        current_qty = 0
        if current_qty_result.get('values'):
            try:
                current_qty = int(float(current_qty_result['values'][0][0]))
            except:
                current_qty = 0
        
        # Calculate new quantity
        new_qty = current_qty + quantity_change
        
        # Update the cell
        service.spreadsheets().values().update(
            spreadsheetId=inventory_config["workbook_id"],
            range=current_qty_range,
            valueInputOption='RAW',
            body={'values': [[new_qty]]}
        ).execute()
        
        return json.dumps({
            "success": True,
            "product_name": product_name,
            "previous_quantity": current_qty,
            "quantity_change": quantity_change,
            "new_quantity": new_qty,
            "message": f"Inventory updated successfully",
            "timestamp": time.time()
        })
        
    except Exception as e:
        print(f"[ERROR] Failed to update inventory: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def google_sheets_query_tool(query: str) -> str:
    """
    Legacy tool for backward compatibility. 
    Query both inventory and orders data. Use specific tools like get_inventory_tool() for better performance.
    """
    print(f"[DEBUG] Legacy query from agent: {query}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"error": "no_connection_configured"})
    
    # Try to get both inventory and orders data
    result = {
        "query": query,
        "timestamp": time.time()
    }
    
    try:
        # Get inventory data
        inventory_result = get_inventory_tool("all")
        inventory_data = json.loads(inventory_result)
        if "error" not in inventory_data:
            result["inventory"] = inventory_data["inventory"]
    except Exception as e:
        print(f"[DEBUG] Could not get inventory: {e}")
    
    try:
        # Get orders data
        orders_result = get_orders_tool("all")
        orders_data = json.loads(orders_result)
        if "error" not in orders_data:
            result["orders"] = orders_data["orders"]
    except Exception as e:
        print(f"[DEBUG] Could not get orders: {e}")
    
    return json.dumps(result)

if __name__ == "__main__":
    mcp.run()
