import json
import os
import textwrap
from typing import Annotated, Dict, List

from langchain.tools import tool
from langchain_chroma import Chroma
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
#from langchain_core.tools import InjectedState
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition, InjectedState
from typing_extensions import TypedDict


# 1. Custom Reducer to merge and deduplicate seen entries
def merge_seen_entries(left: list, right: list) -> list:
    """Merges two lists of seen entries, deduplicating by title."""
    seen = {entry["title"]: entry for entry in (left or [])}
    for entry in (right or []):
        seen[entry["title"]] = entry
    return list(seen.values())


# 2. Corrected State definition
class State(TypedDict):
    messages: Annotated[list, add_messages]
    seen_entries: Annotated[list[dict], merge_seen_entries]


llm = ChatOllama(
    model="ministral-3:14b",
    temperature=0.2,
    validate_model_on_init=True,
)

embedding_model = OllamaEmbeddings(model="all-minilm:l6-v2")


# 3. Use InjectedState to hide state from the LLM tool schema
@tool
def search_stories(
    query: str,
    state: Annotated[State, InjectedState],
    k: int = 5,
    db_dir: str = "vector_db",
    omit_previous: bool = True,
) -> list[dict]:
    """Search the Escape Pod stories database for stories matching the query.

    Args:
        query (str): The search query to find relevant stories
        k (int): Number of results to return (default: 5)
        db_dir (str): Path to the vector database directory (default: "vector_db")
        omit_previous (bool): Whether to exclude previously found stories (default: True)

    Returns:
        List of dictionaries containing story information.
    """
    # Initialize ChromaDB
    vector_db = Chroma(
        collection_name="escape_pod_summaries",
        persist_directory=db_dir,
        embedding_function=embedding_model,
    )

    # Create filter to exclude previously found stories if requested
    filter_dict = None
    if omit_previous and "seen_entries" in state:
        previous_titles = {entry["title"] for entry in state["seen_entries"]}
        if previous_titles:
            # Chroma DB uses mongo-style filtering (e.g. $nin for "not in")
            filter_dict = {"title": {"$nin": list(previous_titles)}}

    # Search the database with optional filter
    results = vector_db.similarity_search_with_score(query, k=k, filter=filter_dict)

    # Format the results
    formatted_results = []
    for doc, score in results:
        formatted_results.append(
            {
                "title": doc.metadata.get("title", "Unknown Title"),
                "author": doc.metadata.get("author", "Unknown Author"),
                "publication_date": doc.metadata.get("publication_date", "Unknown"),
                "source": doc.metadata.get("source", "Unknown"),
                "summary": doc.page_content,
                "relevance_score": round(score, 4),
            }
        )

    return formatted_results


@tool
def read_story_file(path: str) -> str:
    """Reads the full content of a story file.

    Args:
        path (str): The filename of the story file
    """
    path = "/skryn/code/rezdev/lizdeika/downloaded_stories/" + os.path.basename(path)
    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()
        return content
    except FileNotFoundError:
        return f"Error: File not found at path {path}"
    except PermissionError:
        return f"Error: Permission denied when trying to read {path}"
    except UnicodeDecodeError:
        return f"Error: Could not decode file at {path} (invalid characters)"
    except Exception as e:
        return f"Error reading file at {path}: {str(e)}"


tools = [search_stories, read_story_file]
tools_by_name = {t.name: t for t in tools}
llm = llm.bind_tools(tools)


# 4. Corrected Tool Node to format observation as a JSON string
def tool_node(state: dict) -> dict:
    """Executes tool calls made by the LLM."""
    results = []
    seen_entries = []

    for tool_call in state["messages"][-1].tool_calls:
        tool_func = tools_by_name[tool_call["name"]]
        tool_args = tool_call["args"].copy()

        # Inject the state argument
        if tool_call["name"] == "search_stories":
            tool_args["state"] = state

        observation = tool_func.invoke(tool_args)

        if tool_call["name"] == "search_stories":
            # Save raw dicts to append to seen_entries
            seen_entries.extend(observation)
            # 5. Convert list of dicts to a JSON string for ToolMessage
            content = json.dumps(observation, indent=2)
        else:
            content = str(observation)

        results.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))

    return {"messages": results, "seen_entries": seen_entries}


def llm_call(state: State):
    messages = state["messages"]
    response = llm.invoke(messages)
    if response.content:
        print(" ---")
        for line in response.content.split("\n"):
            print(
                "\033[33m "
                + textwrap.fill(
                    line,
                    os.get_terminal_size().columns - 2,
                    break_long_words=False,
                    replace_whitespace=False,
                )
                + "\033[0m"
            )
        print(" ---")
    return {"messages": [response], "seen_entries": state["seen_entries"]}


def define_graph():
    graph = StateGraph(State)
    graph.add_node("llm", llm_call)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "llm")

    return graph


def main():
    graph = define_graph()
    memory = InMemorySaver()
    build = graph.compile(checkpointer=memory)

    thread_id = "chat-session"
    state = {
        "messages": [
            SystemMessage(
                content="""
    You are a friendly and knowledgeable story search assistant named Lizdeika (short for Elizabeth Descartes). You have tools to search through a vector database of story summaries. adapt user requests into queries that are likely to match relevant story summaries. when listing the results include a plot summary all stories returned by the querry. If you think a story doesn't match the user request explain why, after summarising the story, because it could be a jumping off point for a new querry. Include the Escape Pod episode number together with the title and author. 
    """
            )
        ],
        "seen_entries": [],
    }

    # Initial interaction
    state["messages"].append(HumanMessage(content="introduce yourself"))
    result = build.invoke(state, config={"configurable": {"thread_id": thread_id}})

    end_keys = ["quit", "exit", "q", "bye"]

    while True:
        user_input_message = input("\nUser: ")
        if user_input_message.lower() in end_keys:
            break
        state["messages"].append(HumanMessage(content=user_input_message))
        result = build.invoke(state, config={"configurable": {"thread_id": thread_id}})


    while False:
        user_input_message = input("\nUser: ")
        if user_input_message.lower() in end_keys:
            break
        # Retrieve the updated state from the thread checkpointer to ensure state integrity
        current_state = build.get_state(config={"configurable": {"thread_id": thread_id}})
        # Add new user message to messages list
        current_messages = current_state.values["messages"] + [
            HumanMessage(content=user_input_message)
        ]

        build.update_state(
            config={"configurable": {"thread_id": thread_id}},
            values={"messages": current_messages},
        )
        result = build.invoke(None, config={"configurable": {"thread_id": thread_id}})


if __name__ == "__main__":
    main()
