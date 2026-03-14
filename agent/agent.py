"""Core Claude agent loop with tool use handling."""
import os
import json
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
        "tools": ["get_project_context", "get_email_threads", "create_alert", "update_project_status"],
    },
    "reply_processor": {
        "system": prompts.REPLY_PROCESSOR,
        "tools": ["get_project_context", "update_task_status", "create_alert", "get_email_threads"],
    },
}


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

        # Process tool calls
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_block in tool_use_blocks:
            tool_name = tool_block.name
            tool_input = tool_block.input

            if tool_name in TOOL_FUNCTIONS:
                try:
                    result = TOOL_FUNCTIONS[tool_name](**tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True,
                    })
            else:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": json.dumps({"error": f"Unknown tool: {tool_name}"}),
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    return "Agent reached maximum iterations."
