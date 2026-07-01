"""Interactive CLI for the performance analytics chatbot (Ollama)."""

from __future__ import annotations

import sys

from chatbot.agent import PerformanceChatbot


def main() -> int:
    print("Performance Analytics Chatbot (test_db2 + Ollama)")
    print("Type 'quit' or 'exit' to stop, 'reset' to clear conversation.\n")

    try:
        bot = PerformanceChatbot()
        print(f"Primary model:  {bot.ollama.primary_model}")
        print(f"Fallback model: {bot.ollama.fallback_model}\n")
    except Exception as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 1

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
            result = bot.chat(user_input, model_mode="auto")
            print(f"\nAssistant [{result.model_used}]: {result.content}")
            if result.figure_json:
                print("  (chart generated)")
            if result.tool_calls_made:
                print(f"  (queried: {', '.join(result.tool_calls_made)})")
            print()
        except Exception as exc:
            print(f"\nError: {exc}\n", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
