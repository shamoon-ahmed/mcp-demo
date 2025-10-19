from mcp.server.fastmcp import FastMCP
import gspread
from google.oauth2.service_account import Credentials
import json

mcp = FastMCP("Inventory Server")

@mcp.tool()
def google_sheets_query_tool(query: str) -> str:
    """
    Query the inventory data in Google Sheets.
    The LLM decides how to answer the query using the table data.
    """
    print("Query: ", query)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    print("Credentials loaded")

    client = gspread.authorize(creds)
    print("Client authorized")

    sheet_id = "1UK4YuiuGfuR8y3bvdz-t8y7QdFgCo3H_3SpxufIAKu4"
    workbook = client.open_by_key(sheet_id)
    worksheet = workbook.sheet1
    print("Worksheet accessed")

    # Get all records as dictionaries
    data = worksheet.get_all_records()
    print("Data retrieved from Google Sheets")

    # Just return the full dataset to the LLM
    return json.dumps({
        "query": query,
        "data": data
    })

if __name__ == "__main__":
    mcp.run()