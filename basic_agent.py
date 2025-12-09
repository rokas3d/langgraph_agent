from typing import Annotated, Literal, List, Dict
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from typing_extensions import TypedDict
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_community.tools import DuckDuckGoSearchRun,  DuckDuckGoSearchResults
from langgraph.types import interrupt
from langchain_ollama import ChatOllama

import os
import argparse

#from tools import list_files_and_directories, get_git_commits, read_text_file , SANDBOX_PATH
import file_access_tools

search = DuckDuckGoSearchRun()



# Define state
class State(TypedDict):
    messages: Annotated[list, add_messages]

llm = ChatOllama(
        model="devstral",
        temperature=0.2,
        validate_model_on_init=True,
    )

tools = [search, 
         file_access_tools.list_files_and_directories, 
         file_access_tools.get_git_commits, 
         file_access_tools.read_text_file ]
tools_by_name = {t.name: t for t in tools}
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
        print(" ---")
        print(response.content)
        print(" ---")
    return {"messages":[response]}

def define_graph():
    graph = StateGraph(State)
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", tools_condition, {"tools":"tools", END:END})
    graph.add_edge("tools", "llm")

    return graph

def main():


    graph = define_graph()
    memory = InMemorySaver()
    build = graph.compile(checkpointer=memory)

    thread_id = "chat-session"
    state = {"messages":[SystemMessage(content=""" you are a helpful coding assistant. You have access to {0} directory. you can list directory tree, read files and get git history there to help research a codebase.
        """.format(file_access_tools.SANDBOX_PATH))],
             }
    end_keys = ["quit", "exit", "q", "bye"]
    print("keywords to end session: {0}".format(" , ".join(end_keys)))

    while True:
        user_input_message = input("\nUser: ")
        if user_input_message.lower() in end_keys:
            break
        state["messages"].append(HumanMessage(content=user_input_message))
        result = build.invoke(state, config={"configurable":{"thread_id":thread_id}})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
            prog="basic_agent.py",
            description=" session with an llm that can help analyse  a codebase"
            )
    parser.add_argument('-s', '--sandbox_path', type=str, 
                        help='Path to the sandbox directory')
    
    args = parser.parse_args()

    file_access_tools.SANDBOX_PATH = os.getcwd()
    if args.sandbox_path:
        # Convert relative paths to absolute paths
        abs_path = os.path.abspath(args.sandbox_path)

        # Check if the path exists and is a directory
        if os.path.exists(abs_path) and os.path.isdir(abs_path):
            file_access_tools.SANDBOX_PATH = abs_path
        else:
            print(f"Error: The specified sandbox path '{abs_path}' does not exist or is not a directory.")
    else:
        print("No sandbox path provided. SANDBOX_PATH remains {}".format(file_access_tools.SANDBOX_PATH))

    main()
