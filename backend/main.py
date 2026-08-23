from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from fastapi.middleware.cors import CORSMiddleware
from agent import app as agent_app
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from pymongo import MongoClient
import datetime
import os
import random
import string
import json
from langchain_core.messages import AIMessageChunk
from fastapi.responses import StreamingResponse

MONGO_URI = os.getenv("MONGO_URI")
client = None
db = None

try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client.get_database("parcelpilot")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")

# We will re-compile the graph with a memory saver to support interrupts
from agent import workflow
memory = MemorySaver()
app_with_memory = workflow.compile(checkpointer=memory, interrupt_before=["confirm_action"])

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    persona: str
    account_id: Optional[str] = None
    thread_id: str

@app.post("/chat")
async def chat(request: ChatRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    
    state = {
        "messages": [HumanMessage(content=request.message)],
        "persona": request.persona,
        "account_id": request.account_id or "ACC-000"
    }
    
    async def event_generator():
        try:
            events = app_with_memory.astream(state, config=config, stream_mode="messages")
            async for chunk, metadata in events:
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
                    
            # Check current state after streaming completes
            current_state = app_with_memory.get_state(config)
            messages = current_state.values.get("messages", [])
            last_message = messages[-1] if messages else None
            
            if current_state.next and "confirm_action" in current_state.next:
                if last_message and hasattr(last_message, 'tool_calls') and last_message.tool_calls:
                    tool_call = last_message.tool_calls[0]
                    args = tool_call.get('args', {})
                    order_id = args.get('order_id', 'Unknown')
                    reason = args.get('reason', 'No reason provided')
                    
                    friendly_message = (
                        "\n\nI need your permission to escalate this issue to our human support team.\n\n"
                        f"**Order ID:** {order_id}\n"
                        f"**Reason:** {reason}\n\n"
                        "Would you like me to proceed?"
                    )
                    
                    yield f"data: {json.dumps({'type': 'confirmation', 'tool_call': tool_call, 'message': friendly_message})}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            print(f"Error in chat stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

class ConfirmRequest(BaseModel):
    thread_id: str
    confirm: bool

@app.post("/confirm")
async def confirm_action(request: ConfirmRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    current_state = app_with_memory.get_state(config)
    
    if not current_state.next or "confirm_action" not in current_state.next:
        raise HTTPException(status_code=400, detail="No action pending confirmation.")
        
    async def event_generator():
        try:
            if request.confirm:
                events = app_with_memory.astream(None, config=config, stream_mode="messages")
                async for chunk, metadata in events:
                    if isinstance(chunk, AIMessageChunk) and chunk.content:
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
            else:
                messages = current_state.values.get("messages", [])
                last_ai_message = messages[-1]
                if hasattr(last_ai_message, 'tool_calls') and last_ai_message.tool_calls:
                    tool_call = last_ai_message.tool_calls[0]
                    tool_msg = ToolMessage(
                        content="User denied the action.", 
                        tool_call_id=tool_call["id"],
                        name=tool_call["name"]
                    )
                    app_with_memory.update_state(config, {"messages": [tool_msg]}, as_node="confirm_action")
                    
                    events = app_with_memory.astream(None, config=config, stream_mode="messages")
                    async for chunk, metadata in events:
                        if isinstance(chunk, AIMessageChunk) and chunk.content:
                            yield f"data: {json.dumps({'type': 'token', 'content': chunk.content})}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            print(f"Error in confirm stream: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

class OrderCreate(BaseModel):
    account_id: str
    new_account_name: Optional[str] = None
    carrier: str
    status: str = "BOOKED"
    pickup_window_start: str
    pickup_window_end: str
    shipment_fee_inr: int

def insert_orders(orders: List[OrderCreate]):
    if db is None:
        raise HTTPException(status_code=500, detail="Database MONGO_URI not configured.")
        
    current_time = datetime.datetime.utcnow().isoformat()
    inserted_ids = []
    
    try:
        for order in orders:
            if order.new_account_name:
                existing = db.accounts.find_one({"account_id": order.account_id})
                if not existing:
                    db.accounts.insert_one({
                        "account_id": order.account_id,
                        "account_name": order.new_account_name,
                        "plan": "Standard",
                        "status": "ACTIVE",
                        "premium_support": 0
                    })

            order_id = "ORD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            
            db.orders.insert_one({
                "order_id": order_id,
                "account_id": order.account_id,
                "carrier": order.carrier,
                "status": order.status,
                "booked_at": current_time,
                "pickup_window_start": order.pickup_window_start,
                "pickup_window_end": order.pickup_window_end,
                "shipment_fee_inr": order.shipment_fee_inr
            })
            inserted_ids.append(order_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return inserted_ids

@app.post("/api/orders/single")
async def create_single_order(order: OrderCreate):
    inserted_ids = insert_orders([order])
    return {"message": f"Successfully created order {inserted_ids[0]}", "order_id": inserted_ids[0]}

@app.post("/api/orders/bulk")
async def create_bulk_orders(orders: List[OrderCreate]):
    inserted_ids = insert_orders(orders)
    return {"message": f"Successfully created {len(inserted_ids)} orders.", "order_ids": inserted_ids}

@app.get("/api/orders")
async def get_orders():
    if db is None:
        raise HTTPException(status_code=500, detail="Database MONGO_URI not configured.")
        
    try:
        orders = list(db.orders.find({}, {"_id": 0}).sort("booked_at", -1).limit(100))
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tickets")
async def get_tickets():
    if db is None:
        raise HTTPException(status_code=500, detail="Database MONGO_URI not configured.")
        
    try:
        tickets = list(db.tickets.find({}, {"_id": 0}).sort("created_at", -1))
        return tickets
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class TicketCloseRequest(BaseModel):
    resolution: str

@app.post("/api/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: str, req: TicketCloseRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database MONGO_URI not configured.")
        
    try:
        result = db.tickets.update_one(
            {"ticket_id": ticket_id},
            {"$set": {"status": "closed", "historical_resolution": req.resolution}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Ticket not found.")
            
        return {"message": f"Ticket {ticket_id} closed successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
