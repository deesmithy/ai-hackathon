# Podium Hackathon — Autonomous Business Agents

LangGraph-based agent workflow with tool-calling via Claude.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

## Run

```bash
python -m src.main
```

## Project structure

```
src/
  agents/graph.py   # LangGraph workflow definition
  tools/            # Add business tools here (one file per tool)
  main.py           # CLI entrypoint
```

## Adding a new tool

1. Create a file in `src/tools/` with a `@tool`-decorated function
2. Import it in `src/agents/graph.py` and add it to the `tools` list
