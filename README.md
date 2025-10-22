# 🏗️ **MCP-Demo Application Explained**

Think of your application like a **restaurant system** where:
- **Dashboard** = The menu and ordering system  
- **MCP Server** = The kitchen that processes orders
- **Client** = The waiter who takes your requests and brings food
- **Google Sheets** = The inventory book in the kitchen

---

## 📁 **Folder Structure Overview**

```
mcp-demo/
├── dashboard/          # 🌐 Web interface (like a restaurant's menu)
├── mcp_server/        # 🔧 The brain that talks to Google Sheets  
├── client/            # 💬 Chat interface to ask questions
```

---

# 🌐 **DASHBOARD FOLDER - Your Web Interface**

## 📄 **dashboard.py - The Web App**

Think of this as your **restaurant's front desk**. It handles three main jobs:

### **Job 1: Welcome Page** (`/` route)
```python
@app.get("/", response_class=HTMLResponse)
def index():
```
**What it does:** Shows you a nice welcome page  
**Why we need it:** This is where users start - like walking into a restaurant  
**How it works:** When someone visits `http://localhost:8000`, they see a "Connect Google Sheets" button

### **Job 2: Google Authentication** (`/auth/start` route)
```python
@app.get("/auth/start")
def auth_start():
    flow = Flow.from_client_config(...)
    auth_url, state = flow.authorization_url(...)
    return RedirectResponse(auth_url)
```
**What it does:** Sends you to Google to log in  
**Why we need it:** We need permission to read your Google Sheets  
**How it works:** 
1. Creates a special "permission request" to Google
2. Sends you to Google's login page
3. Google asks: "Do you allow this app to read your sheets?"

### **Job 3: Handle Google's Response** (`/auth/callback` route)
```python
@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request):
    code = request.query_params.get("code")  # Google sends back a secret code
    flow.fetch_token(code=code)              # Trade code for access token
    creds = flow.credentials                 # Get the credentials
    
    # List all your Google Sheets
    drive = build("drive", "v3", credentials=creds_for_api)
    files = drive.files().list(...)
```
**What it does:** After Google login, shows you a list of your sheets to choose from  
**Why we need it:** We need to know which specific sheet has your inventory  
**How it works:**
1. Google sends back a secret "code" 
2. We trade that code for a "refresh token" (like a permanent pass)
3. We use that pass to get your list of Google Sheets
4. Show you a dropdown to pick which sheet has your inventory

### **Job 4: Save Your Choice** (`/select-sheet` route)
```python
@app.post("/select-sheet")
async def select_sheet(sheet_id: str = Form(...), refresh_token: str = Form(...)):
    data = {
        "sheet_id": sheet_id,
        "refresh_token": refresh_token
    }
    with open("connection.json", "w") as f:
        json.dump(data, f)
```
**What it does:** Saves which sheet you picked and the access token  
**Why we need it:** So the MCP server knows which sheet to read  
**How it works:** Creates a connection.json file with your sheet ID and access token

## 📄 **connection.json - The Memory File**
```json
{
  "sheet_id": "1UK4YuiuGfuR8y3bvdz...", 
  "refresh_token": "ya29.a0ARrd..."
}
```
**What it is:** A simple text file that remembers your choices  
**Why we need it:** So other parts of the app know which sheet to use  
**What's inside:** Your sheet ID and the "key" to access it

---

# 🔧 **MCP_SERVER FOLDER - The Brain**

## 📄 **mcp_server.py - The Google Sheets Reader**

This is like the **kitchen in your restaurant** - it takes orders and gets the data from your inventory book (Google Sheets).

### **Setting Up Credentials**
```python
# Load Google credentials from client secret file
CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "google_client_secret.json")
with open(CLIENT_SECRET_FILE, 'r') as f:
    client_secrets = json.load(f)
    
GOOGLE_CLIENT_ID = client_secrets["web"]["client_id"]
GOOGLE_CLIENT_SECRET = client_secrets["web"]["client_secret"]
```
**What it does:** Loads the "restaurant's license" to talk to Google  
**Why we need it:** Google needs to know WHO is asking for data  
**How it works:** Reads your Google app credentials from the JSON file

### **The Main Function - Reading Sheets**
```python
@mcp.tool()
def google_sheets_query_tool(query: str) -> str:
```
This is the **star of the show**! Let me break it down step by step:

#### **Step 1: Load Connection Info**
```python
conn = load_connection()
sheet_id = conn.get("sheet_id")
refresh_token = conn.get("refresh_token")
```
**What it does:** Reads the connection.json file  
**Why:** To know which sheet to read and how to access it  
**Like:** Checking the order ticket to know what table wants what

#### **Step 2: Get Permission to Read**
```python
service = build_sheets_service_from_refresh(refresh_token)
```
**What it does:** Uses the saved token to get permission from Google  
**Why:** The token might have expired, so we refresh it  
**Like:** Showing your restaurant pass to the security guard

#### **Step 3: Find All Sheets in Your Spreadsheet**
```python
spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
sheets = spreadsheet.get('sheets', [])
```
**What it does:** Gets info about your spreadsheet (like "Sheet1", "Sheet2", etc.)  
**Why:** We want to read ALL sheets, not just guess the names  
**Like:** Looking at all the pages in your inventory book

#### **Step 4: Read Each Sheet Dynamically**
```python
for sheet in sheets:
    sheet_name = sheet['properties']['title']
    
    # Figure out how big the sheet is
    row_count = grid_properties.get('rowCount', 1000)
    col_count = grid_properties.get('columnCount', 26)
    
    # Read all the data
    res = service.spreadsheets().values().get(
        spreadsheetId=sheet_id, 
        range=range_name
    ).execute()
```
**What it does:** For each sheet, figures out its size and reads ALL the data  
**Why:** We don't want to miss any inventory items  
**Like:** Reading every page of your inventory book completely

#### **Step 5: Smart Data Processing**
```python
# Use first row as headers
headers = rows[0] if rows else []
data_rows = rows[1:] if len(rows) > 1 else []

# Convert to list of dictionaries
for row in data_rows:
    row_dict = {}
    for i, header in enumerate(headers):
        cell_value = row[i] if i < len(row) else ""
        clean_header = str(header).strip().lower().replace(' ', '_')
        row_dict[clean_header] = str(cell_value).strip()
```
**What it does:** 
- Takes the first row as column names (headers)
- Converts each row into a dictionary with those headers
- Cleans up the data (removes extra spaces, makes lowercase)

**Why:** So instead of confusing cell positions, we get nice data like:
```python
{"item_name": "Running Shoes", "quantity": "15", "price": "5500"}
```
**Like:** Instead of saying "the thing in column B row 3", we say "Running Shoes"

## 📄 **google_client_secret.json - Your Google App ID**
```json
{
  "web": {
    "client_id": "800472619238-dj54...",
    "client_secret": "GOCSPX-VG9usgB9..."
  }
}
```
**What it is:** Your app's "birth certificate" from Google  
**Why we need it:** Google needs to know which app is asking for permission  
**Like:** Your restaurant's business license

---

# 💬 **CLIENT FOLDER - The Waiter**

## 📄 **mcp_client.py - The Chat Interface**

This is like your **friendly waiter** who takes your questions and brings back answers.

### **Starting the MCP Server**
```python
async with MCPServerStdio(
    name = "Inventory Server",
    params= {
        "command" : "C:/Users/pc/Desktop/mcp-demo/.venv/Scripts/python.exe",
        "args" : ["C:/Users/pc/Desktop/mcp-demo/mcp_server/mcp_server.py"]
    },
) as server :
```
**What it does:** Starts up the MCP server (the kitchen)  
**Why:** The client needs the server running to get data  
**Like:** Making sure the kitchen is open before taking orders

### **The AI Agent**
```python
inventory_agent = Agent(
    name="Inventory Agent",
    instructions="""
    You are an inventory management agent.
    Use google_sheets_query_tool to access the inventory data.
    """,
    mcp_servers=[server],
)
```
**What it does:** Creates an AI assistant that knows how to use your inventory data  
**Why:** So you can ask natural questions like "How many shoes do we have?"  
**Like:** Training your waiter to understand the menu and kitchen

### **The Chat Loop**
```python
while True:
    user_query = input("Enter your inventory query: ")
    result = await Runner.run(starting_agent=inventory_agent, input=user_query)
    print("Response: ", result.final_output)
```
**What it does:** Keeps asking for your questions and giving answers  
**Why:** So you can have a conversation with your inventory data  
**Like:** The waiter keeps coming back to take more orders

---

# 🔄 **THE COMPLETE FLOW - How Everything Works Together**

## **Setup Phase (One Time):**
1. **You run the dashboard** → `uvicorn dashboard:app --reload --port 8000`
2. **You visit the website** → `http://localhost:8000`
3. **You click "Connect Google Sheets"** → Goes to Google for permission
4. **Google asks permission** → You say "Yes, this app can read my sheets"
5. **You pick your inventory sheet** → Dashboard saves this in connection.json

## **Usage Phase (Every Time You Ask Questions):**
1. **You run the client** → `python mcp_client.py`
2. **Client starts the MCP server** → The server wakes up and reads connection.json
3. **You ask a question** → "How many running shoes do we have?"
4. **The AI agent calls the MCP server** → Server reads your Google Sheet
5. **Server processes the data** → Finds all running shoes and counts them
6. **AI gives you a smart answer** → "You have 15 running shoes in stock"

---

# 🧠 **Why We Built It This Way**

## **Why Separate Files?**
- **Dashboard** = Web interface (easy to use)
- **MCP Server** = Data processor (reusable)
- **Client** = Chat interface (natural conversation)

## **Why Google Sheets?**
- Easy to edit your inventory
- No database setup needed
- Familiar interface for most people

## **Why MCP (Model Context Protocol)?**
- Lets AI tools talk to your data
- Standard way to connect different systems
- Future-proof for other AI applications

---

# 🎯 **In Simple Terms:**

**Your app is like a smart restaurant assistant:**

1. **Dashboard** = The ordering system where you set everything up
2. **MCP Server** = The kitchen that knows how to read your inventory book (Google Sheets)
3. **Client** = The friendly waiter who understands your questions and brings smart answers
4. **Google Sheets** = Your inventory book that you can edit anytime

**The magic:** You can ask natural questions like "How many blue shoes do we have?" and get intelligent answers based on your real Google Sheets data!

Does this help you understand how everything works together? Let me know which part you'd like me to explain further! 🚀