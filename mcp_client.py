from agents import Agent, Agent, Runner, SQLiteSession
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv

session = SQLiteSession(session_id="inventory_management")

load_dotenv()

async def run(server: MCPServerStdio):

    inventory_agent = Agent(
        name="Inventory Agent",
        instructions="""
        You are an inventory management agent.
        Use google_sheets_query_tool to access the inventory data stored in Google Sheets.
        answer the user's queries based on the data retrieved.
        """,
        mcp_servers=[server],
        )

    while True:
        user_query = input("\n===  Enter your inventory query: ")

        result = await Runner.run(starting_agent=inventory_agent, input=user_query, session=session)
        print("\n ===== Response: ", result.final_output)

async def main():
    async with MCPServerStdio(
        name = "Inventory Server",
        params= {
            "command" : "mcp",
            "args" : ["run", "mcp_server.py"]
        },
    ) as server :
        print("Starting MCP server")
        await run(server)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())