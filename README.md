# Langgraph agent
A very basic example of interacting with an ollama llm using langgraph. Tools give it an ability to list directory trees, read files, get git history.
Run with :

```
python basic_agent.py -s /path/to/your/code
```

The -s or --sandbox_path flag takes in a path to a directory the agent is allowed to interact with. By default it's current directory the script is in. At the moment the agent can only perform read actions.
