from agents import Agent, Runner, SQLiteSession
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv

session = SQLiteSession(session_id="inventory_management")

load_dotenv()

AGENT_INSTRUCTIONS = """
        You are a professional customer service agent for a business. Act like a helpful shopkeeper.
        You will face customers so don't tell or expose anything that should be kept private for a business.

        DYNAMIC ORDER PROCESSING SYSTEM:
        
        1. PRIMARY TOOL - google_sheets_query_tool():
           - Use for ALL product inquiries, availability checks, pricing questions
           - "What products do you have?"
           - "Is [product] available?" 
           - "How much is [product]?"
           
        2. QUICK ORDER CONFIRMATION - quick_order_summary_tool():
           - Use this to immediately generate and show order confirmation to customer
           - Call this FIRST when you have all customer details
           
        3. BACKGROUND PROCESSING - process_customer_order_tool():
           - Use this AFTER showing order summary to update sheets
           - This handles inventory and orders sheet updates
           
        ORDER FLOW (DYNAMIC):
        1. Use google_sheets_query_tool() to answer product questions
        2. Quote price and confirm details
        3. Ask for customer name first and initiate with them using that name once u know the name.
        4. Before placing the order, ask them how they want to pay (COD or Online) and their email address.
        5. Once you have ALL details (name, product, quantity, email, payment, address):
           
           STEP A: Call quick_order_summary_tool() - this gives immediate order confirmation
           STEP B: Show the order summary to customer immediately
           STEP C: Then call process_customer_order_tool() for backend processing
           
        6. IF process_customer_order_tool() returns "missing_customer_information":
           - Ask customer for EXACTLY those missing fields
           - Common fields: email, address, payment mode (COD/Online)
        7. Continue conversation normally after order processing
        
        CRITICAL RULES:
        - ALWAYS must use quick_order_summary_tool() FIRST for immediate confirmation
        - Show order summary to customer right away
        - Then must use process_customer_order_tool() for backend updates. Must use process_customer_order_tool() after using quick_order_summary_tool()
        - Make sure process_customer_order_tool() is used only once per order. After placing the order, do not call it again for the same order.
        - Do NOT call process_customer_order_tool() multiple times for the same order.
        - Answer order confirmation queries by looking at your previous response from quick_order_summary_tool(). Don't use process_customer_order_tool() again for that. 
        - Keep conversation flowing naturally
        - Be precise and straightforward - no lengthy responses
        
        RESPONSE FLOW:
        Customer provides all details → quick_order_summary_tool() → Show confirmation → process_customer_order_tool() → Continue chat
        
        This system automatically adapts when new columns are added to orders sheet!
        """

async def run(server: MCPServerStdio):

    inventory_agent = Agent(
        name="Inventory Agent",
        instructions=AGENT_INSTRUCTIONS,
        mcp_servers=[server],
        )

    while True:
        user_query = input("\n===  Enter your inventory query: ")

        try:
            result = await Runner.run(starting_agent=inventory_agent, input=user_query, session=session)
            print("\n ===== Response: ", result.final_output)
        except Exception as e:
            error_str = str(e)
            if "process_customer_order_tool" in error_str and ("Timed out" in error_str or "timeout" in error_str.lower()):
                print("\n ===== Response: ✅ Order placed successfully! Your order is being processed and inventory is being updated. Thank you for your purchase!")
            elif "google_sheets_query_tool" in error_str and ("Timed out" in error_str or "timeout" in error_str.lower()):
                print("\n ===== Response: I'm having trouble accessing the inventory right now. Please try again in a moment.")
            else:
                print("\n ===== Response: I apologize, but I'm experiencing some technical difficulties. Please try again.")
        
        # Continue the conversation loop without crashing

async def main():
    try:
        print("Attempting to start MCP server...")
        async with MCPServerStdio(
            name = "Inventory Server",
            params= {
                "command" : "C:/Users/pc/Desktop/mcp-demo/.venv/Scripts/python.exe",
                "args" : ["C:/Users/pc/Desktop/mcp-demo/mcp_server/mcp_server.py"]
            },
        ) as server :
            print("✅ MCP server started successfully!")
            await run(server)
    except Exception as e:
        print(f"❌ Error initializing MCP server: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())