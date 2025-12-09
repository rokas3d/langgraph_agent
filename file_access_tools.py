from typing import List, Dict  
from git import Repo
import os
from langchain.tools import tool

SANDBOX_PATH = None 

def get_directory_tree(path, hidden_files):
    """Recursively get directory tree structure as a nested dictionary."""
    tree = {}
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if hidden_files or not item.startswith("."):
            if os.path.isdir(item_path):
                tree[item] = get_directory_tree(item_path, hidden_files)
            else:
                tree[item] = None
    return tree

@tool
def list_files_and_directories(path: str, hidden_files: bool = False) -> dict:
    """Returns a tree of all subdirectories and files contained within the given path,
    only within SANDBOX_PATH.

    Args:
        path (str): The root path to start listing from
        hidden_files (bool): flag to ignore hidden files. By default ignore them because they add noise

    Returns:
        dict: Nested dictionary representing the directory tree
    """
    if not os.path.isabs(path):
        return {"error": "Path must be absolute"}
    if not path.startswith(SANDBOX_PATH):
        return {"error": f"Path must be within {SANDBOX_PATH}"}

    try:
        return get_directory_tree(path, hidden_files)
    except Exception as e:
        return {"error": str(e)}

@tool
def get_git_commits(repo_path: str, branch: str = "main") -> List[Dict[str, str]]:
    """For a given repository retrieves up to 100 latest git commits from the specified branch,
    ensuring the repo is within SANDBOX_PATH.

    Args:
        repo_path (str): The absolute path to the git repo directory
        branch (str): The name of the branch to retrieve commits from. Defaults to "main".

    Returns:
        (List[dict]): List of dictionaries containing information about each commit including hash, author, date and message.
    """
    if not os.path.isabs(repo_path):
        return "Path must be absolute"
    if not repo_path.startswith(SANDBOX_PATH):
        return f"Path must be within {SANDBOX_PATH}"

    try:
        repo = Repo(repo_path)

        commits = list(repo.iter_commits(branch, max_count=100))  # Use the specified branch

        commit_info_list = []
        for commit in commits:
            commit_info = {
                "hash": commit.hexsha,
                "author": commit.author.name if commit.author else None,
                "date": commit.committed_datetime.isoformat(),
                "message": commit.message
            }
            commit_info_list.append(commit_info)

        return commit_info_list

    except Exception as e:
        return str(e)

@tool
def read_text_file(path: str) -> str:
    """Reads a text file and returns its contents, ensuring the file is within SANDBOX_PATH.

    Args:
        path (str): The absolute path to the text file

    Returns:
        str: Contents of the text file or error message
    """
    if not os.path.isabs(path):
        return "Path must be absolute"

    if not path.startswith(SANDBOX_PATH):
        return f"Path must be within {SANDBOX_PATH}"

    try:
        with open(path, 'r', encoding='utf-8') as file:
            contents = file.read()
        return contents
    except FileNotFoundError:
        return "File not found"
    except IOError as e:
        return f"Error reading the file: {str(e)}"


