"""Quick entrypoint to chat with the agent."""

from langchain_core.messages import HumanMessage

from src.agents.graph import graph


def main():
    print("Agent ready — type 'quit' to exit.\n")
    while True:
        user_input = input("You: ")
        if user_input.strip().lower() in ("quit", "exit", "q"):
            break
        result = graph.invoke({"messages": [HumanMessage(content=user_input)]})
        print(f"Agent: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    main()
