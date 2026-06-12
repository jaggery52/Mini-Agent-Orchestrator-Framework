import argparse
import asyncio
import json
import os
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


async def run_session(url: str, init_payload: dict) -> None:
    print(f"\nConnecting to {url} ...\n")

    try:
        async with websockets.connect(url) as ws:
            # The server requires an `init` handshake (auth token + LLM/search keys +
            # model names + usecase) as the very first message, before anything else.
            await ws.send(json.dumps(init_payload))

            async for raw_message in ws:
                message = json.loads(raw_message)
                message_type = message.get("type")

                if message_type == "acknowledgement":
                    session_id = message.get("session_id", "")
                    print(f"[Connected] Session ID: {session_id}  (usecase: {init_payload['usecase']})")
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
    # The client is the trusted holder of the keys. Defaults come from the client's
    # own environment so secrets aren't passed on the command line.
    parser.add_argument("--token", default=os.getenv("SERVER_ACCESS_TOKEN", ""),
                        help="Server access token (env: SERVER_ACCESS_TOKEN)")
    parser.add_argument("--usecase", default=os.getenv("USECASE", "tour_agency"),
                        help="Usecase to run (env: USECASE, default: tour_agency)")
    parser.add_argument("--collection", default=os.getenv("COLLECTION_NAME", ""),
                        help="KB collection name (env: COLLECTION_NAME; defaults to --usecase)")
    parser.add_argument("--openai-key", default=os.getenv("OPENAI_API_KEY", ""),
                        help="OpenAI API key for LLM + embeddings (env: OPENAI_API_KEY)")
    parser.add_argument("--tavily-key", default=os.getenv("TAVILY_API_KEY", ""),
                        help="Tavily key for web search; optional (env: TAVILY_API_KEY)")
    parser.add_argument("--model", default=os.getenv("DEFAULT_MODEL", "gpt-4.1-mini"),
                        help="Agent LLM model (env: DEFAULT_MODEL)")
    parser.add_argument("--embedding-model", default=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                        help="Embedding model — must match how the KB was indexed (env: EMBEDDING_MODEL)")
    args = parser.parse_args()

    missing = [name for name, value in (
        ("--token / SERVER_ACCESS_TOKEN", args.token),
        ("--openai-key / OPENAI_API_KEY", args.openai_key),
    ) if not value.strip()]
    if missing:
        print(f"[Error] Missing required value(s): {', '.join(missing)}")
        sys.exit(1)

    init_payload = {
        "type": "init",
        "token": args.token,
        "usecase": args.usecase,
        "collection_name": args.collection or args.usecase,
        "openai_api_key": args.openai_key,
        "tavily_api_key": args.tavily_key,
        "agent_model": args.model,
        "embedding_model": args.embedding_model,
    }

    try:
        asyncio.run(run_session(args.url, init_payload))
    except KeyboardInterrupt:
        print("\n\nDisconnected.")


if __name__ == "__main__":
    main()
