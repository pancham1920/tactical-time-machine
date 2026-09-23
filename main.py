from langchain_core.messages import HumanMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from src.agents.graph import agent_app


def test_agent_brain():
    print("Initializing test query verification loop...\n")

    # Simulating a basic user message query input
    test_input = {
        "messages": [
            HumanMessage(content="Hello analyst! What tables do you have access to?")
        ]
    }

    # Stream the engine nodes execution steps directly to the screen
    try:
        for output in agent_app.stream(test_input, stream_mode="updates"):
            for node_name, state_data in output.items():
                print(f"--- Executing Node Trace: [ {node_name} ] ---")
                last_msg = state_data["messages"][-1]
                print(f"Agent Thought Process:\n{last_msg.content}\n")
    except ChatGoogleGenerativeAIError as exc:
        print("Gemini API call failed.")
        print("This is usually caused by model availability, quota, billing, or API-key access.")
        print(f"Details: {exc}")


if __name__ == "__main__":
    test_agent_brain()
