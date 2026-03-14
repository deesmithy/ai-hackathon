"""Core Claude agent loop with tool use handling."""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic
from dotenv import load_dotenv
from agent.tools import TOOL_DEFINITIONS, TOOL_FUNCTIONS
from agent import prompts

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-6"

# Map mode names to system prompts and allowed tools
MODE_CONFIG = {
    "plan_generator": {
        "system": prompts.PLAN_GENERATOR,
        "tools": ["get_contractor_roster", "create_task"],
    },
    "contractor_assigner": {
        "system": prompts.CONTRACTOR_ASSIGNER,
        "tools": ["get_project_context", "get_contractor_roster", "assign_contractor_to_task"],
    },
    "email_drafter": {
        "system": prompts.EMAIL_DRAFTER,
        "tools": ["get_project_context", "get_contractor_roster", "send_email"],
    },
    "status_monitor": {
        "system": prompts.STATUS_MONITOR,
        "tools": ["get_project_context", "get_email_threads", "create_alert", "update_project_status", "get_contractor_roster", "create_termination_flow", "get_outreach_queue", "mark_outreach_status", "send_email"],
    },
    "reply_processor": {
        "system": prompts.REPLY_PROCESSOR,
        "tools": ["get_project_context", "update_task_status", "create_alert", "get_email_threads", "get_termination_flow", "advance_termination_flow", "get_outreach_queue", "mark_outreach_status", "send_email", "get_contractor_roster"],
    },
    "termination_advisor": {
        "system": prompts.TERMINATION_ADVISOR,
        "tools": ["get_project_context", "get_contractor_roster", "get_email_threads", "create_termination_flow"],
    },
    "termination_executor": {
        "system": prompts.TERMINATION_EXECUTOR,
        "tools": ["get_termination_flow", "get_project_context", "send_email", "advance_termination_flow"],
    },
    "termination_summarizer": {
        "system": prompts.TERMINATION_SUMMARIZER,
        "tools": ["get_termination_flow", "get_email_threads", "get_project_context", "save_termination_summary"],
    },
}


def generate_tasks_direct(user_message: str) -> list[dict]:
    """Generate a task plan in a single Claude API call using forced structured output.

    Instead of the multi-round-trip agent loop, this fetches available specialties
    from the DB, passes them to Claude, and forces a single `submit_tasks` tool call
    that returns the full task list as structured JSON.
    """
    from agent.tools import get_contractor_roster

    roster = get_contractor_roster()
    specialties = sorted({c["specialty"] for c in roster})

    submit_tool = {
        "name": "submit_tasks",
        "description": "Submit the complete ordered list of construction tasks for this project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Short task name"},
                            "description": {"type": "string", "description": "What the task involves"},
                            "specialty_needed": {
                                "type": "string",
                                "enum": specialties,
                                "description": "Trade required for this task",
                            },
                            "estimated_days": {"type": "integer", "description": "Realistic working days"},
                            "sequence_order": {"type": "integer", "description": "Order this task occurs (1 = first)"},
                            "depends_on_sequence": {
                                "type": "integer",
                                "description": "sequence_order of the task that must finish before this one, or omit if none",
                            },
                        },
                        "required": ["name", "description", "specialty_needed", "estimated_days", "sequence_order"],
                    },
                }
            },
            "required": ["tasks"],
        },
    }

    full_message = user_message + f"\n\nAvailable contractor specialties: {', '.join(specialties)}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=prompts.PLAN_GENERATOR,
        tools=[submit_tool],
        tool_choice={"type": "tool", "name": "submit_tasks"},
        messages=[{"role": "user", "content": full_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_tasks":
            return block.input.get("tasks", [])

    return []


def run_agent(mode: str, user_message: str) -> str:
    """Run the Claude agent in a specific mode with an agentic tool-use loop."""
    config = MODE_CONFIG.get(mode)
    if not config:
        return f"Unknown agent mode: {mode}"

    # Filter tool definitions to only those allowed for this mode
    allowed_tools = [t for t in TOOL_DEFINITIONS if t["name"] in config["tools"]]

    messages = [{"role": "user", "content": user_message}]

    # Agentic loop: keep going until Claude stops calling tools
    max_iterations = 20
    for _ in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=config["system"],
            tools=allowed_tools,
            messages=messages,
        )

        # Check if there are any tool use blocks
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # No tool calls — extract final text response
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks) if text_blocks else "Agent completed with no response."

        # Process tool calls in parallel
        messages.append({"role": "assistant", "content": response.content})

        def _execute_tool(tool_block):
            tool_name = tool_block.name
            tool_input = tool_block.input
            if tool_name not in TOOL_FUNCTIONS:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps({"error": f"Unknown tool: {tool_name}"}),
                    "is_error": True,
                }
            try:
                result = TOOL_FUNCTIONS[tool_name](**tool_input)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps(result, default=str),
                }
            except Exception as e:
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps({"error": str(e)}),
                    "is_error": True,
                }

        with ThreadPoolExecutor(max_workers=len(tool_use_blocks)) as executor:
            futures = {executor.submit(_execute_tool, tb): tb.id for tb in tool_use_blocks}
            results_by_id = {}
            for future in as_completed(futures):
                result = future.result()
                results_by_id[result["tool_use_id"]] = result
            # Preserve original order
            tool_results = [results_by_id[tb.id] for tb in tool_use_blocks]

        messages.append({"role": "user", "content": tool_results})

    return "Agent reached maximum iterations."
