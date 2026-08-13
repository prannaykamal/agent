from langchain_core.messages import HumanMessage
from src.db import init_db
from src.harness.graph import agent_app

def main():
    print("=" * 60)
    print("24x7 Personal Assistant - Core Harness CLI")
    print("Initializing SQLite database & loading system harness...")
    print("=" * 60)
    
    init_db()
    session_id = "cli_session_001"
    conversation_state = {
        "messages": [],
        "session_id": session_id,
        "summary": "",
        "token_count": 0
    }

    print("\nAssistant ready! Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user_input = input("You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            conversation_state["messages"].append(HumanMessage(content=user_input))

            result = agent_app.invoke(conversation_state)
            conversation_state["messages"] = result["messages"]
            conversation_state["summary"] = result.get("summary", "")

            # Last message is AI response
            latest_response = result["messages"][-1]
            print(f"\nAssistant > {latest_response.content}\n")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting assistant.")
            break

if __name__ == "__main__":
    main()
