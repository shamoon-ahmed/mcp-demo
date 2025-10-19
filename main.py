from agents import Agent, Runner, function_tool, SQLiteSession
import gspread
from google.oauth2.service_account import Credentials
import json
from dotenv import load_dotenv

load_dotenv()

inventory_agent = Agent(
    name="Inventory Agent",
    instructions="""
    You are an inventory management agent.
    Use google_sheets_query_tool to access the inventory data stored in Google Sheets.
    answer the user's queries based on the data retrieved.
    """,
    mcp_servers=["Inventory Server"],
    )

starting_agent = inventory_agent

# async def run():
#     while True:
#         user_query = input("\n===  Enter your inventory query: ")

#         result = await Runner.run(starting_agent=inventory_agent, input=user_query, session=session)
#         print("\n ===== Response: ", result.final_output)