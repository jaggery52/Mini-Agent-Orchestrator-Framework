import asyncio
import logging
import pathlib

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from mini_agent.engine.state_machine import StateMachine
from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import SessionContext, set_session
from mini_agent.settings import SERVER_ACCESS_TOKEN

# Usecases are the sub-directories under configs/ (each holds a state_machine_config.json).
CONFIGS_DIR = pathlib.Path(__file__).resolve().parent / "configs"

# Fields the client must supply (non-empty) in the `init` handshake.
REQUIRED_INIT_FIELDS = (
    "usecase",
    "collection_name",
    "openai_api_key",
    "agent_model",
    "embedding_model",
)


def _known_usecases() -> set:
    if not CONFIGS_DIR.exists():
        return set()
    return {
        path.name
        for path in CONFIGS_DIR.iterdir()
        if path.is_dir() and (path / "state_machine_config.json").exists()
    }


app = FastAPI(title="mini-agent WebSocket Server")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _authenticate(websocket: WebSocket, session: SessionContext) -> bool:
    """Read and validate the first `init` message. Returns True if the session is
    authorised and configured; otherwise sends an error, closes the socket, and
    returns False."""
    try:
        message = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4001, reason="Expected init handshake")
        return False

    if message.get("type") != "init":
        await websocket.send_json({"type": "error", "content": "First message must be type 'init'."})
        await websocket.close(code=4001, reason="Missing init handshake")
        return False

    if not SERVER_ACCESS_TOKEN or message.get("token") != SERVER_ACCESS_TOKEN:
        logging.warning(f"[SERVER] Rejected connection — invalid token (session {session.session_id})")
        await websocket.send_json({"type": "error", "content": "Authentication failed."})
        await websocket.close(code=4001, reason="Invalid token")
        return False

    missing = [field for field in REQUIRED_INIT_FIELDS if not str(message.get(field, "")).strip()]
    if missing:
        await websocket.send_json({"type": "error", "content": f"Missing required init fields: {', '.join(missing)}"})
        await websocket.close(code=4001, reason="Incomplete init payload")
        return False

    usecase = message["usecase"]
    if usecase not in _known_usecases():
        await websocket.send_json({"type": "error", "content": f"Unknown usecase '{usecase}'."})
        await websocket.close(code=4001, reason="Unknown usecase")
        return False

    session.usecase = usecase
    session.collection_name = message["collection_name"]
    session.openai_api_key = message["openai_api_key"]
    session.tavily_api_key = message.get("tavily_api_key", "")
    session.agent_model = message["agent_model"]
    session.embedding_model = message["embedding_model"]
    return True


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_event_loop()
    session = SessionContext(websocket=websocket, loop=loop)
    set_session(session)

    if not await _authenticate(websocket, session):
        return

    logging.info(
        f"[SERVER] Client authenticated. Session: {session.session_id} | usecase: {session.usecase}"
    )

    await websocket.send_json({
        "type": "acknowledgement",
        "session_id": session.session_id,
        "content": "What would you like to do?",
    })

    async def run_machine():
        try:
            await asyncio.to_thread(_run_state_machine, session)
        except Exception as error:
            logging.error(f"[SERVER] State machine error — session {session.session_id}: {error}", exc_info=True)
            session.send_sync({"type": "error", "content": str(error)})

    machine_task = asyncio.create_task(run_machine())

    try:
        async for message in websocket.iter_json():
            if message.get("type") == "human_input":
                user_content = message.get("content", "")
                logging.info(f"[SERVER] human_input received — session {session.session_id}: {user_content[:80]}")
                session.input_queue.put(user_content)
    except WebSocketDisconnect:
        logging.info(f"[SERVER] Client disconnected — session {session.session_id}")
        session.should_stop = True

    await machine_task
    logging.info(f"[SERVER] Session complete: {session.session_id}")


def _run_state_machine(session: SessionContext) -> None:
    set_session(session)
    StateMemory.reset()
    machine = StateMachine(session.usecase)
    machine.run()


def main() -> None:
    """Console-script / `python -m mini_agent` entry point."""
    import uvicorn

    uvicorn.run("mini_agent.server:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
