from typing import Annotated, Literal
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from typing_extensions import TypedDict
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

import asyncio
from langchain_ollama import ChatOllama


# Define state
class State(TypedDict):
    messages: Annotated[list, add_messages]


llm = ChatOllama(
    model="devstral",
    temperature=0.2,
    validate_model_on_init=True,
)

client = MultiServerMCPClient({

    "langchain-docs": {
        "url": "https://docs.langchain.com/mcp",
        "transport": "streamable_http",
    },})

# Register tools

# Register tools
async def register_tools():
    async with client.session("langchain-docs") as session:
        return await load_mcp_tools(session)

tools = asyncio.run(register_tools())

#async with client.session("langchain-docs") as session:
    #tools = await load_mcp_tools(session)
tools_by_name = {t.name: t for t in tools}
print(tools_by_name)
# ----------------- LLM WITH TOOLS -----------------
llm = llm.bind_tools(tools)


def llm_call(state: State):
    messages =  state["messages"]
    response = llm.invoke(messages)
    print( " £££")
    print(response.content)
    print( " £££")
    return {"messages":[response]}

def user_input(state:State):
    user_input = input("\nUser: ")

    return {"messages":[user_input]}

def should_continue(state: State) -> Literal["Action", END]:
    last_message = state["messages"][-1]
    if last_message.content.lower() in ["quit", "exit", "q"]:
        return END
    return "Continue"


def tool_node(state: dict):
    """Executes tool calls made by the LLM."""
    results = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke(tool_call["args"])
        results.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    return {"messages": results}

# -------- Graph -------- #
graph = StateGraph(State)
graph.add_node("user", user_input)
graph.add_node("llm", llm_call)
graph.add_node("tools", tool_node)

graph.add_edge(START, "user")
graph.add_conditional_edges("user", should_continue, {"Continue": "llm", END: END})
graph.add_edge("llm", "tools")
graph.add_edge("tools", "user")
memory = InMemorySaver()
build = graph.compile(checkpointer=memory)

thread_id = "chat-session"
state = {"messages":[SystemMessage(content=""" you are a helpful coding assistant
    """)]}

build.invoke(
            state, 
            config ={"configurable":{"thread_id":thread_id}}
                      )

