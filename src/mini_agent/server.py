import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from mini_agent.engine.state_machine import StateMachine
from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import SessionContext, set_session
from mini_agent.settings import EMBEDDING_MODEL, KNOWLEDGE_BASE_DIR, OPENAI_API_KEY
from mini_agent.states.ai.search.rag_search import RagSearch


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info(f"[SERVER] Building knowledge base from {KNOWLEDGE_BASE_DIR} ...")
    rag = RagSearch(
        openai_api_key=OPENAI_API_KEY,
        docs_folder=str(KNOWLEDGE_BASE_DIR),
        embedding_model=EMBEDDING_MODEL,
    )
    rag.initialise()
    logging.info("[SERVER] Knowledge base ready.")
    yield


app = FastAPI(title="mini-agent WebSocket Server", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_event_loop()
    session = SessionContext(websocket=websocket, loop=loop)
    set_session(session)

    logging.info(f"[SERVER] Client connected. Session: {session.session_id}")

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
    machine = StateMachine("default")
    machine.run()


def main() -> None:
    """Console-script / `python -m mini_agent` entry point."""
    import uvicorn

    uvicorn.run("mini_agent.server:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
