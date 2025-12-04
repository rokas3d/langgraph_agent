from typing import Annotated, Literal
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from typing_extensions import TypedDict
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools import DuckDuckGoSearchRun,  DuckDuckGoSearchResults

from langchain_ollama import ChatOllama


search = DuckDuckGoSearchRun()

SANDBOX_PATH = "/skryn/code/django"

# Define state
class State(TypedDict):
    messages: Annotated[list, add_messages]
    plan: dict

llm = ChatOllama(
        model="devstral",
        temperature=0.2,
        validate_model_on_init=True,
    )

tools = [search]
tools_by_name = {t.name: t for t in tools}
print(tools_by_name)
llm = llm.bind_tools(tools)

def tool_node(state: dict) -> dict :
    """Executes tool calls made by the LLM."""

    results = []
    for tool_call in state["messages"][-1].tool_calls:
        tool = tools_by_name[tool_call["name"]]
        observation = tool.invoke( tool_call["args"])
        results.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
    return {"messages": results}

def llm_call(state: State):
    messages =  state["messages"]
    response = llm.invoke(messages)
    if response.content:
        print( " £££")
        print(response.content)
        print( " £££")
    return {"messages":[response]}

def user_input(state:State):
    user_input = input("\nUser: ")
    return {"messages":[HumanMessage(content=user_input)]}

def user_quit(state: State) -> Literal["Action", END]:
    last_message = state["messages"][-1]
    if last_message.content.lower() in ["quit", "exit", "q"]:
        return END
    if last_message.content.lower() in ["print plan", "print"]:
        print(state["plan"])
        return "user"
    return "Continue"

def main():
    # -------- Graph -------- #
    graph = StateGraph(State)
    graph.add_node("user", user_input)
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "user")
    graph.add_conditional_edges("user", user_quit, {"Continue": "llm", END: END, "user":"user"})
    graph.add_conditional_edges( "llm", tools_condition, {"tools":"tools", END:"user"} )
    #graph.add_edge("llm", "user")
    graph.add_edge("tools", "llm")

    memory = InMemorySaver()
    build = graph.compile(checkpointer=memory)

    thread_id = "chat-session"
    state = {"messages":[SystemMessage(content=""" you are a helpful coding assistant. You have access to a plan dictionary in your memory, this is where you plan out your tasks. 
        """)],
             "plan":{}}

    result = build.invoke(state, config={"configurable":{"thread_id":thread_id}})

if __name__ == "__main__":
    main()

