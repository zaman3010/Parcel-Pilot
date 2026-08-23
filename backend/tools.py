from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from pymongo import MongoClient
import pandas as pd
import os
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

import shutil
import tempfile

CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")
MONGO_URI = os.getenv("MONGO_URI")

client = None
db = None
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client.get_database("parcelpilot")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")

# Initialize Chroma
embeddings = OpenAIEmbeddings(model="openai/text-embedding-3-small")

# Handle read-only filesystem on Vercel
try:
    TMP_CHROMA_PATH = os.path.join(tempfile.gettempdir(), "parcelpilot_chroma_db")
    if not os.path.exists(TMP_CHROMA_PATH):
        shutil.copytree(CHROMA_PATH, TMP_CHROMA_PATH)
    active_chroma_path = TMP_CHROMA_PATH
except Exception:
    active_chroma_path = CHROMA_PATH

vector_store = Chroma(embedding_function=embeddings, persist_directory=active_chroma_path)

class SearchInput(BaseModel):
    query: str = Field(description="The search query (e.g. 'cancellation policy')")
    account_id: Optional[str] = Field(None, description="The account ID if querying for a specific customer's agreement")

@tool("search_knowledge_base", args_schema=SearchInput)
def search_knowledge_base(query: str, account_id: Optional[str] = None) -> str:
    """Searches the knowledge base containing policies, SOPs, and customer agreements. 
    Use this to find rules, policies, and standard operating procedures."""
    
    docs = vector_store.similarity_search(query, k=5)
    
    results = []
    for doc in docs:
        source = doc.metadata.get('source_file', 'Unknown')
        status = doc.metadata.get('status', 'CURRENT')
        customer = doc.metadata.get('customer', 'General')
        
        if status == "CUSTOMER_AGREEMENT":
            results.append(f"Source: {source} (Status: {status}, Applies to: {customer})\nContent: {doc.page_content}\n")
        else:
            results.append(f"Source: {source} (Status: {status})\nContent: {doc.page_content}\n")
            
    return "\n---\n".join(results)


class QueryDataInput(BaseModel):
    collection: str = Field(description="The MongoDB collection to query ('accounts', 'orders', or 'tickets').")
    filter_query: str = Field(default="{}", description="A valid JSON string representing the MongoDB filter query (e.g., '{\"status\": \"open\"}').")
    account_id: Optional[str] = Field(None, description="The account ID to scope the query. REQUIRED for customer-facing agents.")

@tool("query_customer_data", args_schema=QueryDataInput)
def query_customer_data(collection: str, filter_query: str = "{}", account_id: Optional[str] = None) -> str:
    """Queries structured operational data (accounts, orders, tickets).
    The database contains collections:
    - accounts (account_id, account_name, plan, status, premium_support)
    - orders (order_id, account_id, carrier, status, booked_at, pickup_window_start, pickup_window_end, pickup_actual_at, shipment_fee_inr) 
    - tickets (ticket_id, account_id, created_at, status, subject, description, channel, assigned_to, historical_resolution, customer_contact)
    
    WARNING: For customer-facing queries, you MUST include 'account_id' in your filter JSON to ensure privacy."""
    
    if db is None:
        return "Database MONGO_URI not configured."
        
    try:
        import json
        query_dict = json.loads(filter_query)
        if account_id:
            query_dict["account_id"] = account_id
            
        if collection not in ["accounts", "orders", "tickets"]:
            return "Invalid collection name. Choose from 'accounts', 'orders', 'tickets'."
            
        results = list(db[collection].find(query_dict, {"_id": 0}).limit(50))
        if not results:
            return "No results found."
            
        df = pd.DataFrame(results)
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error executing query: {str(e)}"


class EscalateInput(BaseModel):
    order_id: str = Field(default="", description="The EXACT ID of the order to escalate.")
    reason: str = Field(default="", description="The reason for escalation.")
    customer_contact: str = Field(default="", description="The customer's contact details.")

@tool("escalate_order", args_schema=EscalateInput)
def escalate_order(order_id: str = "", reason: str = "", customer_contact: str = "") -> str:
    """Escalates an order issue to human support. WARNING: DO NOT call this tool until the user has explicitly given you both their order ID and their contact details."""
    
    if not order_id or not customer_contact:
        return "SYSTEM ERROR: You tried to escalate an order without providing both an order ID and customer contact details. Please ask the user for them."
    
    import datetime
    import random
    import string
    
    if db is None:
        return "Database MONGO_URI not configured."
        
    try:
        order = db.orders.find_one({"order_id": order_id})
        account_id = order["account_id"] if order else "ACC-UNKNOWN"
        
        ticket_id = "TKT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        current_time = datetime.datetime.utcnow().isoformat()
        
        db.tickets.insert_one({
            "ticket_id": ticket_id,
            "account_id": account_id,
            "created_at": current_time,
            "status": "open",
            "subject": f"Escalation for Order {order_id}",
            "description": reason,
            "channel": "chat",
            "assigned_to": "support_queue",
            "customer_contact": customer_contact
        })
        
        # Update the order status to reflect the escalation
        db.orders.update_one({"order_id": order_id}, {"$set": {"status": "ESCALATED"}})
        
        return f"Successfully escalated order {order_id} to human support (Ticket ID: {ticket_id}) for reason: {reason}. Contact details provided: {customer_contact}"
    except Exception as e:
        return f"Error creating ticket: {str(e)}"

class AnalyzeInput(BaseModel):
    collection: str = Field(description="The MongoDB collection to query ('accounts', 'orders', or 'tickets').")
    pipeline: str = Field(default="[]", description="A valid JSON string representing the MongoDB aggregation pipeline (e.g., '[{\"$match\": {\"status\": \"open\"}}]').")

@tool("analyze_trends", args_schema=AnalyzeInput)
def analyze_trends(collection: str, pipeline: str = "[]") -> str:
    """Internal tool only: Analyzes broader trends across all accounts (e.g. 'show me tickets by severity').
    Executes a MongoDB aggregation pipeline."""
    if db is None:
        return "Database MONGO_URI not configured."
    try:
        import json
        pipeline_list = json.loads(pipeline)
        
        if collection not in ["accounts", "orders", "tickets"]:
            return "Invalid collection name."
            
        results = list(db[collection].aggregate(pipeline_list))
        
        if not results:
            return "No results found."
            
        df = pd.DataFrame(results)
        return df.to_markdown(index=False)
    except Exception as e:
        return f"Error executing pipeline: {str(e)}"
