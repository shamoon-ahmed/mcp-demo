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

def smart_column_detection(data_row, column_type):
    """
    Intelligently detect columns based on common business terminology.
    Supports various business types: fashion, beauty, electronics, etc.
    """
    column_mappings = {
        "product_name": [
            "item_name", "product_name", "product_title", "name", "product", "title", 
            "merchandise", "article", "sku_name"
        ],
        "quantity": [
            "quantity", "qty", "stock", "available", "inventory", "count",
            "units", "pieces", "amount", "availability", "in_stock"
        ],
        "price": [
            "unit_price", "price", "cost", "amount", "rate", "selling_price",
            "retail_price", "mrp", "value", "pkr", "usd", "inr"
        ],
        "id": [
            "item_id", "product_id", "id", "sku", "code", "barcode",
            "item_code", "product_code", "order_no", "order_id", "orderid"
        ],
        "status": [
            "status", "availability", "available", "active", "enabled",
            "payment_status", "order_status", "stock_status"
        ],
        "size": [
            "size", "dimensions", "variant", "option", "type"
        ],
        "color": [
            "color", "colour", "shade", "variant"
        ],
        "weight": [
            "weight", "mass", "volume", "ml", "grams", "kg", "oz"
        ]
    }
    
    result = {}
    
    for key, value in data_row.items():
        clean_key = str(key).strip().lower().replace(' ', '_').replace('-', '_').replace('(', '').replace(')', '')
        
        for col_type, possible_names in column_mappings.items():
            if column_type == "all" or column_type == col_type:
                for possible_name in possible_names:
                    # Use exact match or full word boundary match for better precision
                    if (clean_key == possible_name or 
                        clean_key.startswith(possible_name + '_') or
                        clean_key.endswith('_' + possible_name) or
                        ('_' + possible_name + '_' in clean_key)):
                        if col_type not in result:  # Take first match
                            result[col_type] = {"key": key, "value": value, "clean_key": clean_key}
                        break
    
    return result

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

# @mcp.tool() - DISABLED: Redundant with google_sheets_query_tool()
def check_stock_tool(product_name: str, required_quantity: int = 1) -> str:
    """
    DEPRECATED: Use google_sheets_query_tool() instead.
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
        
        # Search for the product using smart column detection
        product_found = False
        available_quantity = 0
        
        for item in inventory_data["data"]:
            # Use smart column detection to find product name and quantity
            detected_cols = smart_column_detection(item, "all")
            
            # Check if product name matches
            if "product_name" in detected_cols:
                product_value = detected_cols["product_name"]["value"]
                if product_name.lower() in product_value.lower():
                    product_found = True
                    
                    # Get quantity using smart detection
                    if "quantity" in detected_cols:
                        try:
                            qty_value = detected_cols["quantity"]["value"]
                            available_quantity = int(float(qty_value)) if qty_value else 0
                        except:
                            available_quantity = 0
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
        
        # Add timestamp and order ID if not provided
        if "timestamp" not in order:
            order["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if "order_id" not in order and "order_no" not in order:
            order["order_id"] = f"ORD-{int(time.time())}"
        
        # Get current orders to understand the structure
        current_orders = get_sheet_data(
            service, 
            orders_config["workbook_id"], 
            orders_config["worksheet_name"]
        )
        
        headers = current_orders["headers"]
        
        # Smart mapping: map order data to existing column structure
        new_row = []
        
        if headers:
            # Map order fields to existing headers using smart detection
            for header in headers:
                clean_header = str(header).strip().lower().replace(' ', '_').replace('-', '_').replace('(', '').replace(')', '')
                
                # Try exact match first
                if clean_header in order:
                    new_row.append(str(order[clean_header]))
                else:
                    # Try intelligent mapping
                    mapped_value = ""
                    
                    # Map common variations
                    if any(word in clean_header for word in ["name", "product", "item"]):
                        mapped_value = order.get("product_name", order.get("customer_name", ""))
                    elif any(word in clean_header for word in ["quantity", "qty"]):
                        mapped_value = order.get("quantity", "")
                    elif any(word in clean_header for word in ["price", "cost", "amount"]):
                        mapped_value = order.get("price", "")
                    elif any(word in clean_header for word in ["order", "id", "no"]):
                        mapped_value = order.get("order_id", order.get("order_no", ""))
                    elif any(word in clean_header for word in ["customer", "buyer"]):
                        mapped_value = order.get("customer_name", "")
                    elif any(word in clean_header for word in ["email", "contact"]):
                        mapped_value = order.get("customer_email", "")
                    elif any(word in clean_header for word in ["status", "payment"]):
                        mapped_value = order.get("status", "confirmed")
                    elif any(word in clean_header for word in ["size"]):
                        mapped_value = order.get("size", "")
                    elif any(word in clean_header for word in ["color", "colour"]):
                        mapped_value = order.get("color", "")
                    elif any(word in clean_header for word in ["weight"]):
                        mapped_value = order.get("weight", "")
                    elif any(word in clean_header for word in ["date", "time"]):
                        mapped_value = order.get("timestamp", "")
                    
                    new_row.append(str(mapped_value))
        else:
            # No existing headers - create them from order data
            headers = list(order.keys())
            new_row = [str(v) for v in order.values()]
            
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
def process_customer_order_tool(customer_name: str, product_name: str, quantity: int, customer_email: str = "", notes: str = "", customer_address: str = "", payment_mode: str = "") -> str:
    """
    Complete end-to-end order processing with dynamic schema analysis.
    Automatically detects orders sheet columns and fills them with inventory data or provided customer data.
    Returns detailed info about what customer information is still needed.
    """
    print(f"[DEBUG] Dynamic order processing: {customer_name} wants {quantity}x {product_name}")
    
    conn = load_connection()
    if not conn:
        return json.dumps({"success": False, "error": "no_connection_configured"})
    
    inventory_config = conn.get("inventory")
    orders_config = conn.get("orders")
    refresh_token = conn.get("refresh_token")
    
    if not all([inventory_config, orders_config, refresh_token]):
        return json.dumps({"success": False, "error": "missing_configuration"})
    
    try:
        # Single Google Sheets service connection
        service = build_sheets_service_from_refresh(refresh_token)
        
        # Step 1: Get inventory data
        inventory_data = get_sheet_data(
            service, 
            inventory_config["workbook_id"], 
            inventory_config["worksheet_name"]
        )
        
        # Step 2: Get orders sheet schema for dynamic column analysis
        orders_data = get_sheet_data(
            service,
            orders_config["workbook_id"],
            orders_config["worksheet_name"]
        )
        orders_headers = orders_data["headers"]
        
        # Step 3: Find product and extract inventory details
        product_found = False
        available_quantity = 0
        product_row_index = -1
        product_details = {}
        
        for idx, item in enumerate(inventory_data["data"]):
            detected_cols = smart_column_detection(item, "all")
            
            if "product_name" in detected_cols:
                product_value = detected_cols["product_name"]["value"]
                if product_name.lower() in product_value.lower():
                    product_found = True
                    product_row_index = idx + 2
                    
                    # Extract all available product details
                    for col_type, col_info in detected_cols.items():
                        product_details[col_type] = str(col_info["value"]) if col_info["value"] else ""
                    
                    # Ensure we have quantity for stock check
                    if "quantity" in detected_cols:
                        try:
                            available_quantity = int(float(detected_cols["quantity"]["value"])) if detected_cols["quantity"]["value"] else 0
                        except:
                            available_quantity = 0
                    break
        
        if not product_found:
            return json.dumps({
                "success": False,
                "error": "product_not_found",
                "message": f"Product '{product_name}' not found in inventory"
            })
        
        if available_quantity < quantity:
            return json.dumps({
                "success": False,
                "error": "insufficient_stock",
                "message": f"Only {available_quantity} units available, but {quantity} requested",
                "available_quantity": available_quantity,
                "requested_quantity": quantity
            })
        
        # Step 4: Dynamic column mapping and customer data analysis
        order_row_data = []
        missing_customer_info = []
        customer_provided_data = {
            "customer_name": customer_name,
            "customer_email": customer_email,
            "customer_address": customer_address,
            "payment_mode": payment_mode,
            "notes": notes,
            "quantity": str(quantity),
            "status": "confirmed",
            "order_id": f"ORD-{int(time.time())}"
        }
        
        # Analyze each column in orders sheet
        for header in orders_headers:
            clean_header = header.lower().replace(' ', '_').replace('(', '').replace(')', '').replace('-', '_')
            filled = False
            value = ""
            
            # Try to fill from inventory data first
            inventory_mappings = {
                "item_name": product_details.get("product_name", product_name),
                "product_name": product_details.get("product_name", product_name),
                "size": product_details.get("size", ""),
                "color": product_details.get("color", ""),
                "colour": product_details.get("color", ""),
                "price": product_details.get("price", ""),
                "price_pkr": product_details.get("price", ""),
                "unit_price": product_details.get("price", ""),
                "cost": product_details.get("price", ""),
                "category": product_details.get("category", ""),
                "weight": product_details.get("weight", ""),
                "description": product_details.get("description", "")
            }
            
            # Check if this column can be filled from inventory
            for inv_key, inv_value in inventory_mappings.items():
                if inv_key in clean_header and inv_value:
                    value = inv_value
                    filled = True
                    break
            
            # If not filled from inventory, try customer-provided data
            if not filled:
                customer_mappings = {
                    "customer_name": customer_provided_data["customer_name"],
                    "name": customer_provided_data["customer_name"],
                    "customer_email": customer_provided_data["customer_email"],
                    "email": customer_provided_data["customer_email"],
                    "customer_address": customer_provided_data["customer_address"],
                    "address": customer_provided_data["customer_address"],
                    "payment_mode": customer_provided_data["payment_mode"],
                    "payment": customer_provided_data["payment_mode"],
                    "mode": customer_provided_data["payment_mode"],
                    "notes": customer_provided_data["notes"],
                    "note": customer_provided_data["notes"],
                    "quantity": customer_provided_data["quantity"],
                    "qty": customer_provided_data["quantity"],
                    "status": customer_provided_data["status"],
                    "order_id": customer_provided_data["order_id"],
                    "order_no": customer_provided_data["order_id"],
                    "order_number": customer_provided_data["order_id"]
                }
                
                for cust_key, cust_value in customer_mappings.items():
                    if cust_key in clean_header:
                        if cust_value:
                            value = cust_value
                            filled = True
                        else:
                            # Mark as missing customer info if not provided
                            missing_customer_info.append({
                                "column": header,
                                "field_type": cust_key,
                                "description": f"Please provide {header}"
                            })
                        break
            
            # If still not filled, add empty value but note it's missing
            if not filled and header not in [info["column"] for info in missing_customer_info]:
                missing_customer_info.append({
                    "column": header,
                    "field_type": "unknown",
                    "description": f"Unable to determine how to fill '{header}'"
                })
            
            order_row_data.append(value)
        
        # Step 5: Check if we have all required customer information
        if missing_customer_info:
            return json.dumps({
                "success": False,
                "error": "missing_customer_information",
                "message": "Additional customer information required to complete the order",
                "missing_fields": missing_customer_info,
                "product_details": {
                    "name": product_details.get("product_name", product_name),
                    "size": product_details.get("size", ""),
                    "color": product_details.get("color", ""),
                    "price": product_details.get("price", ""),
                    "available_quantity": available_quantity
                },
                "instructions": "Please provide the missing information and try the order again"
            })
        
        # Step 6: Update inventory (reduce stock)
        new_quantity = available_quantity - quantity
        quantity_col = None
        
        for col_letter, header in enumerate(inventory_data["headers"], start=1):
            if any(word in header.lower() for word in ["quantity", "qty", "stock"]):
                quantity_col = chr(64 + col_letter)
                break
        
        if quantity_col and product_row_index > 0:
            range_name = f"{inventory_config['worksheet_name']}!{quantity_col}{product_row_index}"
            service.spreadsheets().values().update(
                spreadsheetId=inventory_config["workbook_id"],
                range=range_name,
                valueInputOption="RAW",
                body={"values": [[str(new_quantity)]]}
            ).execute()
        
        # Step 7: Add order to orders sheet
        service.spreadsheets().values().append(
            spreadsheetId=orders_config["workbook_id"],
            range=f"{orders_config['worksheet_name']}!A:{chr(64 + len(orders_headers))}",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [order_row_data]}
        ).execute()
        
        return json.dumps({
            "success": True,
            "message": f"Order processed successfully for {customer_name}",
            "order_details": {
                "order_id": customer_provided_data["order_id"],
                "customer_name": customer_name,
                "product_name": product_details.get("product_name", product_name),
                "quantity": quantity,
                "previous_stock": available_quantity,
                "new_stock": new_quantity,
                "columns_filled": len(orders_headers),
                "complete_order_data": dict(zip(orders_headers, order_row_data))
            },
            "timestamp": time.time()
        })
        
    except Exception as e:
        print(f"[ERROR] Dynamic order processing failed: {e}")
        return json.dumps({
            "success": False,
            "error": "processing_failed",
            "details": str(e)
        })

# @mcp.tool() - DISABLED: Redundant with google_sheets_query_tool()
def get_product_info_tool(product_search: str) -> str:
    """
    DEPRECATED: Use google_sheets_query_tool() instead.
    Search for product information including name, price, description, and stock levels.
    Use this to help customers find products and get detailed information.
    """
    print(f"[DEBUG] Searching for product: {product_search}")
    
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
        
        # Search for products that match the search term
        matching_products = []
        search_term = product_search.lower()
        
        for item in inventory_data["data"]:
            product_matches = False
            product_info = {}
            
            # Look through all fields to find matches and gather info
            for key, value in item.items():
                clean_value = str(value).lower()
                
                # Check if this field contains the search term
                if search_term in clean_value:
                    product_matches = True
                
                # Collect product information
                if any(word in key.lower() for word in ["name", "product", "title"]):
                    product_info["name"] = value
                elif any(word in key.lower() for word in ["price", "cost", "amount"]):
                    product_info["price"] = value
                elif any(word in key.lower() for word in ["description", "desc", "details"]):
                    product_info["description"] = value
                elif any(word in key.lower() for word in ["quantity", "stock", "qty", "available"]):
                    product_info["stock"] = value
                elif any(word in key.lower() for word in ["category", "type", "group"]):
                    product_info["category"] = value
            
            if product_matches and product_info:
                matching_products.append(product_info)
        
        return json.dumps({
            "search_term": product_search,
            "found_products": len(matching_products),
            "products": matching_products,
            "timestamp": time.time()
        })
        
    except Exception as e:
        print(f"[ERROR] Failed to search products: {e}")
        return json.dumps({"error": str(e)})

@mcp.tool()
def google_sheets_query_tool(query: str) -> str:
    """
    Main tool for answering product queries, checking availability, pricing, and product information.
    Use this tool for all customer inquiries about products, stock, prices, and general inventory questions.
    """
    print(f"[DEBUG] Product query from agent: {query}")
    
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
            "timestamp": time.time(),
            "message": "Use this inventory data to answer the customer's query about products, availability, or pricing"
        })
        
    except Exception as e:
        print(f"[ERROR] Failed to query inventory: {e}")
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()
