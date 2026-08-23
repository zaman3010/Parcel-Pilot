import operator
from typing import Annotated, Sequence, TypedDict, List
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from tools import search_knowledge_base, query_customer_data, escalate_order, analyze_trends

# Define the State
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    persona: str  # 'customer' or 'internal'
    account_id: str  # For customer persona

# Initialize LLM
llm = ChatOpenAI(model="openai/gpt-4o-mini", temperature=0)

# Define Tools per persona
customer_tools = [search_knowledge_base, query_customer_data, escalate_order]
internal_tools = [search_knowledge_base, query_customer_data, escalate_order, analyze_trends]

# Bind tools to LLMs
customer_llm = llm.bind_tools(customer_tools)
internal_llm = llm.bind_tools(internal_tools)

# System Prompts
CUSTOMER_SYSTEM_PROMPT = """You are a helpful customer support AI for ParcelPilot.
You must assist the customer with their questions. 
CRITICAL RULES:
1. You only have access to information for account_id: {account_id}.
2. When querying structured data, you MUST include 'WHERE account_id = "{account_id}"' in your SQL.
3. SOURCE PRECEDENCE: When sources conflict, strictly use this order of precedence:
   First: Signed Customer Agreement
   Second: Current Support Policy
   Third: Current Product Documentation
5. If a policy is marked as DEPRECATED, do not use it unless explicitly asked.
6. Before taking any state-changing action or if data conflicts, identify the conflict and request verification.
7. Do NOT promise a service credit if carrier fault, pickup timing, or customer fault is unknown. Any credit > INR 1,000 requires manager approval.
8. SwiftShip pickups have a 20-minute webhook delay. Do NOT tell a customer a SwiftShip pickup did not occur just because the status is BOOKED, without accounting for this delay.
9. Do not use resolved issues (e.g., KI-176 Address validation) to explain new incidents unless evidence strictly matches.
10. NEVER show raw SQL queries, database schema, or internal lookup steps to the customer. Only provide the final relevant data.
11. If the user asks to escalate an issue, DO NOT call the escalate_order tool immediately. You MUST FIRST reply with a normal message asking the user for their order ID and their contact details (email or phone number). ONLY AFTER they have provided both in the chat should you call the escalate_order tool. NEVER hallucinate or make up these values.
"""

INTERNAL_SYSTEM_PROMPT = """You are an internal operations AI for ParcelPilot support staff.
Your goal is to help investigate issues, analyze trends across accounts, and understand support activity.
CRITICAL RULES:
1. You have unrestricted access to all accounts and data.
2. You can use analyze_trends to write complex SQL and find recurring or unusual issues.
3. SOURCE PRECEDENCE: When sources conflict, strictly use this order of precedence:
   First: Signed Customer Agreement
   Second: Current Support Policy
   Third: Current Product Documentation
4. Historical tickets and internal notes are context only and may contain incorrect past guidance. Do NOT rely on them if they contradict the above sources.
5. If a policy is marked as DEPRECATED, do not use it unless explicitly asked.
6. Before taking any state-changing action or if data conflicts, identify the conflict and request verification.
7. Do NOT promise a service credit if carrier fault, pickup timing, or customer fault is unknown. Any credit > INR 1,000 requires manager approval.
8. SwiftShip pickups have a 20-minute webhook delay. Do NOT assume a SwiftShip pickup did not occur just because the status is BOOKED, without accounting for this delay.
9. Do not use resolved issues (e.g., KI-176 Address validation) to explain new incidents unless evidence strictly matches.
10. If asked to escalate an issue, DO NOT call the escalate_order tool immediately. You MUST FIRST reply with a normal message asking the user for their order ID and their contact details (email or phone number). ONLY AFTER they have provided both in the chat should you call the escalate_order tool. NEVER hallucinate or make up these values.
"""

def agent_node(state: AgentState):
    messages = state["messages"]
    persona = state["persona"]
    
    if persona == "customer":
        sys_msg = SystemMessage(content=CUSTOMER_SYSTEM_PROMPT.format(account_id=state.get("account_id", "UNKNOWN")))
        response = customer_llm.invoke([sys_msg] + messages)
    else:
        sys_msg = SystemMessage(content=INTERNAL_SYSTEM_PROMPT)
        response = internal_llm.invoke([sys_msg] + messages)
        
    return {"messages": [response]}

def tool_node(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    tools_by_name = {t.name: t for t in internal_tools} # Internal has all tools
    
    tool_responses = []
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        
        # We handle state-changing confirmation via API orchestration, 
        # but here we just execute it (the FastAPI layer will handle the pause).
        try:
            tool = tools_by_name[tool_name]
            result = tool.invoke(tool_call["args"])
            
            # Safely print to avoid charmap codec errors on Windows
            safe_result = str(result).encode('ascii', 'replace').decode('ascii')
            print(f"EXECUTED TOOL {tool_name} with args {tool_call['args']} -> RESULT: {safe_result}")
            
            tool_responses.append(ToolMessage(content=str(result), name=tool_name, tool_call_id=tool_call["id"]))
        except Exception as e:
            print(f"ERROR EXECUTING TOOL {tool_name}: {e}")
            tool_responses.append(ToolMessage(content=f"Error: {e}", name=tool_name, tool_call_id=tool_call["id"]))
            
    return {"messages": tool_responses}

def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    # If there are no tool calls, we are done
    if not last_message.tool_calls:
        return "end"
        
    # Check if any tool call is a state-changing action that requires confirmation
    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "escalate_order":
            # We return a special edge that pauses
            return "confirm_action"
            
    return "continue"

# Build Graph
workflow = StateGraph(AgentState)

workflow.add_node("agent", agent_node)
workflow.add_node("action", tool_node)
workflow.add_node("confirm_action", tool_node)

workflow.set_entry_point("agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "continue": "action",
        "confirm_action": "confirm_action",
        "end": END
    }
)

workflow.add_edge("action", "agent")
workflow.add_edge("confirm_action", "agent")

app = workflow.compile()
