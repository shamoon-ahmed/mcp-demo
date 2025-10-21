#!/usr/bin/env python3
"""
Simple test script to verify MCP server is working
"""
import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_mcp_server():
    # Create server parameters
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server/mcp_server.py"],
        env=None
    )
    
    print("🚀 Starting MCP server test...")
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                print("✅ Successfully connected to MCP server")
                
                # Initialize the session
                await session.initialize()
                print("✅ Session initialized")
                
                # List available tools
                tools = await session.list_tools()
                print(f"📋 Available tools: {[tool.name for tool in tools.tools]}")
                
                # Test the Google Sheets tool
                if tools.tools:
                    tool_name = tools.tools[0].name
                    print(f"🔧 Testing tool: {tool_name}")
                    
                    result = await session.call_tool(tool_name, {"query": "show inventory data"})
                    print(f"📊 Tool result: {result.content[0].text[:200]}...")
                    
                print("✅ MCP server test completed successfully!")
                
    except Exception as e:
        print(f"❌ Error testing MCP server: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_server())