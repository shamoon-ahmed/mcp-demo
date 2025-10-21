#!/usr/bin/env python3
"""
Simple test to verify the Google Sheets function works directly
"""
import sys
import os
sys.path.append(os.path.dirname(__file__))

# Test the Google Sheets function directly
from mcp_server.mcp_server import google_sheets_query_tool

def test_google_sheets_function():
    print("🧪 Testing Google Sheets function directly...")
    
    try:
        result = google_sheets_query_tool("show me the inventory data")
        print(f"✅ Function executed successfully!")
        print(f"📊 Result preview: {result[:500]}...")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_google_sheets_function()
    if success:
        print("\n✅ The MCP server function works correctly!")
        print("🔧 To use it with an AI client, the MCP server should be running.")
        print("💡 The server waiting silently is normal behavior.")
    else:
        print("\n❌ There's an issue with the function.")