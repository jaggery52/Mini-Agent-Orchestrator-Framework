import asyncio
import logging
import queue
import uuid
from contextvars import ContextVar
from typing import Optional


class SessionContext:

    def __init__(self, websocket, loop: asyncio.AbstractEventLoop):
        self.session_id = str(uuid.uuid4())
        self.websocket = websocket
        self.loop = loop
        self.input_queue: queue.Queue = queue.Queue()
        self.should_stop: bool = False

        # Per-connection config supplied by the client in the `init` handshake.
        # The server holds no LLM/search keys of its own — these drive every state.
        self.usecase: str = ""
        self.collection_name: str = ""
        self.openai_api_key: str = ""
        self.tavily_api_key: str = ""
        self.agent_model: str = ""
        self.embedding_model: str = ""

    def send_sync(self, message: dict) -> None:
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.websocket.send_json(message), self.loop
            )
            future.result(timeout=10)
        except Exception as error:
            logging.warning(f"[Session {self.session_id}] send_sync failed: {error} — marking session stopped")
            self.should_stop = True

    def wait_for_input(self) -> str:
        while True:
            try:
                return self.input_queue.get(timeout=1.0)
            except queue.Empty:
                if self.should_stop:
                    raise RuntimeError(f"[Session {self.session_id}] Session stopped while waiting for user input")


_current_session: ContextVar[Optional[SessionContext]] = ContextVar("session", default=None)


def get_session() -> Optional[SessionContext]:
    return _current_session.get()


def set_session(context: SessionContext) -> None:
    _current_session.set(context)
