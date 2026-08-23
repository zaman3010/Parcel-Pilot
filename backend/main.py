from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
from fastapi.middleware.cors import CORSMiddleware
from agent import app as agent_app
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
import sqlite3
import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "parcelpilot.db")

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

from fastapi.responses import StreamingResponse
import json
from langchain_core.messages import AIMessageChunk

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
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found.")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    current_time = datetime.datetime.utcnow().isoformat()
    inserted_ids = []
    
    try:
        for order in orders:
            import random
            import string
            
            # If new_account_name is provided, we must create the account first
            if order.new_account_name:
                # Check if account already exists to be safe
                cursor.execute("SELECT account_id FROM accounts WHERE account_id = ?", (order.account_id,))
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO accounts (account_id, account_name, plan, status, premium_support)
                        VALUES (?, ?, 'Standard', 'ACTIVE', 0)
                        """,
                        (order.account_id, order.new_account_name)
                    )

            order_id = "ORD-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            
            cursor.execute(
                """
                INSERT INTO orders (
                    order_id, account_id, carrier, status, booked_at, 
                    pickup_window_start, pickup_window_end, shipment_fee_inr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id, order.account_id, order.carrier, order.status, 
                    current_time, order.pickup_window_start, order.pickup_window_end, 
                    order.shipment_fee_inr
                )
            )
            inserted_ids.append(order_id)
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
        
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
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found.")
        
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM orders ORDER BY booked_at DESC LIMIT 100")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if 'conn' in locals():
            conn.close()

@app.get("/api/tickets")
async def get_tickets():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found.")
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM tickets ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

class TicketCloseRequest(BaseModel):
    resolution: str

@app.post("/api/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: str, req: TicketCloseRequest):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Database not found.")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Ticket not found.")
            
        cursor.execute(
            """
            UPDATE tickets 
            SET status = 'closed', historical_resolution = ? 
            WHERE ticket_id = ?
            """,
            (req.resolution, ticket_id)
        )
        conn.commit()
        return {"message": f"Ticket {ticket_id} closed successfully."}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()
