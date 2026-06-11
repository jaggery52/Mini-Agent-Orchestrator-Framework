import argparse
import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("Missing dependency. Install with:  pip install websockets")
    sys.exit(1)


DEFAULT_URL = "ws://localhost:80/ws"


async def prompt_user(prompt: str = "You: ") -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def run_session(url: str) -> None:
    print(f"\nConnecting to {url} ...\n")

    try:
        async with websockets.connect(url) as ws:
            async for raw_message in ws:
                message = json.loads(raw_message)
                message_type = message.get("type")

                if message_type == "acknowledgement":
                    session_id = message.get("session_id", "")
                    print(f"[Connected] Session ID: {session_id}")
                    print(f"\nAgent: {message.get('content', '')}\n")
                    user_input = await prompt_user("You: ")
                    user_input = user_input.strip()
                    if user_input:
                        await ws.send(json.dumps({"type": "human_input", "content": user_input}))

                elif message_type == "agent_thinking":
                    source = message.get("source", "")
                    if source == "planner":
                        print(f"\n[Planner] Goal: {message.get('goal', '')}")
                        for task in message.get("plan", []):
                            print(f"  - {task['title']}: {task['description']}")
                    elif source == "brain":
                        print(f"\n[Thinking] {message.get('thought', '')}")
                        print(f"[Decision] {message.get('decision', '')}")
                    elif source == "tool":
                        print(f"\n[Agent] {message.get('message', '')}")

                elif message_type == "follow_up_question":
                    print(f"\nAgent: {message.get('content', '')}\n")
                    user_input = await prompt_user("You: ")
                    user_input = user_input.strip()
                    if user_input:
                        await ws.send(json.dumps({"type": "human_input", "content": user_input}))

                elif message_type == "final_response":
                    print(f"\nAgent: {message.get('content', '')}\n")

                elif message_type == "session_end":
                    status = message.get("status", "unknown")
                    print(f"\n[Session ended — status: {status}]\n")
                    break

                elif message_type == "error":
                    print(f"\n[Error] {message.get('content', 'Unknown error')}\n")
                    break

                else:
                    print(f"\n[Unknown message type: {message_type}] {message}\n")

    except ConnectionRefusedError:
        print(f"[Error] Could not connect to {url}")
        print("Make sure the server is running:  docker compose up  or  uvicorn mini_agent.server:app --port 8000")
        sys.exit(1)
    except Exception as error:
        print(f"[Error] {error}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="mini-agent WebSocket test client")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"WebSocket URL to connect to (default: {DEFAULT_URL})",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_session(args.url))
    except KeyboardInterrupt:
        print("\n\nDisconnected.")


if __name__ == "__main__":
    main()
