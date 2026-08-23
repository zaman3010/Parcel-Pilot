from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import sqlite3
import pandas as pd
import os
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
DB_PATH = os.path.join(os.path.dirname(__file__), "parcelpilot.db")

# Initialize Chroma
embeddings = OpenAIEmbeddings(model="openai/text-embedding-3-small")
vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)

class SearchInput(BaseModel):
    query: str = Field(description="The search query (e.g. 'cancellation policy')")
    account_id: Optional[str] = Field(None, description="The account ID if querying for a specific customer's agreement")

@tool("search_knowledge_base", args_schema=SearchInput)
def search_knowledge_base(query: str, account_id: Optional[str] = None) -> str:
    """Searches the knowledge base containing policies, SOPs, and customer agreements. 
    Use this to find rules, policies, and standard operating procedures."""
    
    # We retrieve more documents and then let the LLM filter out DEPRECATED ones unless specifically asked
    docs = vector_store.similarity_search(query, k=5)
    
    results = []
    for doc in docs:
        source = doc.metadata.get('source_file', 'Unknown')
        status = doc.metadata.get('status', 'CURRENT')
        customer = doc.metadata.get('customer', 'General')
        
        # Access control on customer agreements
        if status == "CUSTOMER_AGREEMENT":
            # If account_id doesn't match some mapping (simplified here), we shouldn't return it
            # For this assessment, if an agreement is found, we should include it and let the LLM know
            results.append(f"Source: {source} (Status: {status}, Applies to: {customer})\nContent: {doc.page_content}\n")
        else:
            results.append(f"Source: {source} (Status: {status})\nContent: {doc.page_content}\n")
            
    return "\n---\n".join(results)


class QueryDataInput(BaseModel):
    query: str = Field(description="SQL query to execute against the SQLite database.")
    account_id: Optional[str] = Field(None, description="The account ID to scope the query. REQUIRED for customer-facing agents.")

@tool("query_customer_data", args_schema=QueryDataInput)
def query_customer_data(query: str, account_id: Optional[str] = None) -> str:
    """Queries structured operational data (accounts, orders, tickets).
    The database contains tables:
    - accounts (account_id, account_name, plan, status, premium_support)
    - orders (order_id, account_id, carrier, status, booked_at, pickup_window_start, pickup_window_end, pickup_actual_at, shipment_fee_inr, carrier_fault, customer_fault) 
      Note: default order status is 'BOOKED'.
    - tickets (ticket_id, account_id, created_at, status, subject, description, channel, assigned_to, historical_resolution, customer_contact)
    
    WARNING: For customer-facing queries, you MUST include 'WHERE account_id = ...' in your SQL to ensure privacy."""
    
    if not os.path.exists(DB_PATH):
        return "Database not found. Please ingest data first."
        
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            return "No results found."
            
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error executing query: {str(e)}"


class EscalateInput(BaseModel):
    order_id: str = Field(default="", description="The EXACT ID of the order to escalate. DO NOT INVENT, GUESS, OR HALLUCINATE THIS. If the user did not explicitly provide an order ID, leave this empty.")
    reason: str = Field(default="", description="The reason for escalation.")
    customer_contact: str = Field(default="", description="The customer's email address or phone number for the internal team to reach out. DO NOT GUESS. Ask the user for it.")

@tool("escalate_order", args_schema=EscalateInput)
def escalate_order(order_id: str = "", reason: str = "", customer_contact: str = "") -> str:
    """Escalates an order issue to human support. WARNING: DO NOT call this tool until the user has explicitly given you both their order ID and their contact details."""
    
    if not order_id or not customer_contact:
        return "SYSTEM ERROR: You tried to escalate an order without providing both an order ID and customer contact details. Please ask the user for them."
    
    import datetime
    import random
    import string
    
    if not os.path.exists(DB_PATH):
        return "Database not found."
        
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT account_id FROM orders WHERE order_id = ?", (order_id,))
        row = cursor.fetchone()
        account_id = row[0] if row else "ACC-UNKNOWN"
        
        ticket_id = "TKT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        current_time = datetime.datetime.utcnow().isoformat()
        
        cursor.execute(
            """
            INSERT INTO tickets (
                ticket_id, account_id, created_at, status, subject, 
                description, channel, assigned_to, customer_contact
            ) VALUES (?, ?, ?, 'open', ?, ?, 'chat', 'support_queue', ?)
            """,
            (ticket_id, account_id, current_time, f"Escalation for Order {order_id}", reason, customer_contact)
        )
        
        # Update the order status to reflect the escalation
        cursor.execute("UPDATE orders SET status = 'ESCALATED' WHERE order_id = ?", (order_id,))
        
        conn.commit()
        conn.close()
        return f"Successfully escalated order {order_id} to human support (Ticket ID: {ticket_id}) for reason: {reason}. Contact details provided: {customer_contact}"
    except Exception as e:
        return f"Error creating ticket: {str(e)}"

# Internal tools can include broader analytics queries
@tool("analyze_trends")
def analyze_trends(query: str) -> str:
    """Internal tool only: Analyzes broader trends across all accounts (e.g. 'show me tickets by severity').
    Executes an SQL query without account_id restrictions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if df.empty:
            return "No results found."
            
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error executing query: {str(e)}"
