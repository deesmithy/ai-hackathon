"""Main agent graph — the starting point for your workflow."""

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode

from src.tools.example import lookup_inventory

load_dotenv()

# --- Model + Tools -----------------------------------------------------------

tools = [lookup_inventory]
model = ChatAnthropic(model="claude-sonnet-4-6").bind_tools(tools)

# --- Graph --------------------------------------------------------------------


def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: MessagesState):
    last = state["messages"][-1]
    if last.tool_calls:
        return "tools"
    return END


graph_builder = StateGraph(MessagesState)
graph_builder.add_node("agent", call_model)
graph_builder.add_node("tools", ToolNode(tools))

graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", should_continue, ["tools", END])
graph_builder.add_edge("tools", "agent")

graph = graph_builder.compile()
