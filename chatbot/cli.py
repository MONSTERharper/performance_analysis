"""Interactive CLI for the test_db2 chatbot (single Ollama model)."""

from __future__ import annotations

import sys

from chatbot.agent import Chatbot


def main() -> int:
    print("test_db2 Assistant — ask about scanner performance data.")
    print("Type 'quit'/'exit' to stop, 'reset' to clear the conversation.\n")

    bot = Chatbot()
    print(f"Model: {bot.client.model}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye.")
            return 0
        if user_input.lower() == "reset":
            bot.reset()
            print("Conversation cleared.\n")
            continue

        try:
            answer = bot.ask(user_input, on_status=lambda s: print(f"  … {s}", flush=True))
            print(f"\nAssistant: {answer.content}")
            if answer.tools_used:
                print(f"  (queried: {', '.join(answer.tools_used)})")
            print()
        except Exception as exc:
            print(f"\nError: {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
