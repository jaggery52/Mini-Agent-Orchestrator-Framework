import asyncio
import logging
import pathlib
import shutil
import tempfile

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from mini_agent import db
from mini_agent.engine.state_machine import StateMachine
from mini_agent.engine.state_memory import StateMemory
from mini_agent.session import SessionContext, set_session
from mini_agent.settings import CHROMA_DIR
from mini_agent.states.ai.search.rag_search import RagSearch

CONFIGS_DIR = pathlib.Path(__file__).resolve().parent / "configs"

# Self-contained browser UI pages. parents[2] is the repo root (/app in the image),
# matching PROJECT_ROOT in settings.py.
WEB_DIR = pathlib.Path(__file__).resolve().parents[2] / "clients" / "web"
WEB_CLIENT_HTML = WEB_DIR / "index.html"
LOGIN_HTML = WEB_DIR / "login.html"
CREATE_ACCOUNT_HTML = WEB_DIR / "create-account.html"
FLOW_BUILDER_HTML = WEB_DIR / "flow-builder.html"

# Upper bound on the combined size of a session's uploaded KB docs. Keeps per-session
MAX_DOCS_BYTES = 2 * 1024 * 1024

# Fields the client must supply (non-empty)
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
        path.name for path in CONFIGS_DIR.iterdir() if path.is_dir() and (path / "state_machine_config.json").exists()
    }


app = FastAPI(title="mini-agent WebSocket Server")


@app.on_event("startup")
def _startup() -> None:
    """Create the user-account DB/schema once when the app boots."""
    db.init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse(url="/login")


@app.get("/login")
async def login_page():
    return FileResponse(LOGIN_HTML, media_type="text/html")


@app.get("/create-account")
async def create_account_page():
    return FileResponse(CREATE_ACCOUNT_HTML, media_type="text/html")


@app.get("/mini-agent-ui")
async def web_client():
    return FileResponse(WEB_CLIENT_HTML, media_type="text/html")


@app.get("/flow-builder")
async def flow_builder():
    return FileResponse(FLOW_BUILDER_HTML, media_type="text/html")


# User accounts (signup / login / per-user access token)


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenRequest(BaseModel):
    token: str


class ConfigSaveRequest(BaseModel):
    token: str
    name: str
    config: dict


class ConfigIdRequest(BaseModel):
    token: str
    id: int


def _is_valid_flow_config(config: dict) -> bool:
    return isinstance(config, dict) and isinstance(config.get("stateMachine"), dict)


@app.post("/api/register", status_code=201)
async def register(body: RegisterRequest):
    name = body.name.strip()
    email = body.email.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required.")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    try:
        return db.create_user(name, email, body.password)
    except db.DuplicateEmailError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")


@app.post("/api/login")
async def login(body: LoginRequest):
    user = db.verify_login(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return user


@app.post("/api/token/regenerate")
async def regenerate_token(body: TokenRequest):
    user = db.get_user_by_token(body.token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return {"token": db.regenerate_token(user["id"])}


def _require_user(token: str) -> dict:
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token.")
    return user


@app.post("/api/configs/save")
async def save_config(body: ConfigSaveRequest):
    user = _require_user(body.token)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A config name is required.")
    if not _is_valid_flow_config(body.config):
        raise HTTPException(status_code=400, detail="Invalid config: expected an object with a 'stateMachine' map.")
    return db.save_config(user["id"], name, body.config)


@app.post("/api/configs/list")
async def list_configs(body: TokenRequest):
    user = _require_user(body.token)
    return {"configs": db.list_configs(user["id"])}


@app.post("/api/configs/load")
async def load_config(body: ConfigIdRequest):
    user = _require_user(body.token)
    config = db.get_config(user["id"], body.id)
    if config is None:
        raise HTTPException(status_code=404, detail="Config not found.")
    return config


@app.post("/api/configs/delete")
async def delete_config(body: ConfigIdRequest):
    user = _require_user(body.token)
    if not db.delete_config(user["id"], body.id):
        raise HTTPException(status_code=404, detail="Config not found.")
    return {"deleted": body.id}


async def _authenticate(websocket: WebSocket, session: SessionContext) -> bool:
    try:
        message = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4001, reason="Expected init handshake")
        return False

    if message.get("type") != "init":
        await websocket.send_json({"type": "error", "content": "First message must be type 'init'."})
        await websocket.close(code=4001, reason="Missing init handshake")
        return False

    user = db.get_user_by_token(str(message.get("token", "")))
    if user is None:
        logging.warning(f"[SERVER] Rejected connection — invalid token (session {session.session_id})")
        await websocket.send_json({"type": "error", "content": "Authentication failed."})
        await websocket.close(code=4001, reason="Invalid token")
        return False
    session.user_email = user["email"]

    missing = [field for field in REQUIRED_INIT_FIELDS if not str(message.get(field, "")).strip()]
    if missing:
        await websocket.send_json({"type": "error", "content": f"Missing required init fields: {', '.join(missing)}"})
        await websocket.close(code=4001, reason="Incomplete init payload")
        return False

    config_source = message.get("config_source", "local")
    usecase = message["usecase"]

    if config_source == "user_config":
        flow_config = message.get("flow_config")
        if not _is_valid_flow_config(flow_config):
            await websocket.send_json({"type": "error", "content": "Invalid 'flow_config': expected an object with a 'stateMachine' map."})
            await websocket.close(code=4001, reason="Invalid flow_config")
            return False
        session.config_source = "user_config"
        session.flow_config = flow_config
    elif usecase not in _known_usecases():
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


async def _receive_documents(websocket: WebSocket, session: SessionContext) -> bool:
    try:
        message = await websocket.receive_json()
    except Exception:
        await websocket.close(code=4001, reason="Expected documents handshake")
        return False

    if message.get("type") != "documents":
        await websocket.send_json({"type": "error", "content": "Second message must be type 'documents'."})
        await websocket.close(code=4001, reason="Missing documents handshake")
        return False

    files = message.get("files") or []
    if not isinstance(files, list) or not files:
        await websocket.send_json({"type": "error", "content": "'documents' must include a non-empty 'files' list."})
        await websocket.close(code=4001, reason="No documents supplied")
        return False

    total_bytes = sum(len(str(file.get("content", "")).encode("utf-8")) for file in files)
    if total_bytes > MAX_DOCS_BYTES:
        await websocket.send_json(
            {
                "type": "error",
                "content": f"Uploaded documents exceed the {MAX_DOCS_BYTES // (1024 * 1024)} MB limit.",
            }
        )
        await websocket.close(code=4001, reason="Documents too large")
        return False

    # Per-session temp folder + collection so each connection has an isolated KB that is
    # torn down at session end. The collection name is the session id (overrides init).
    temp_dir = tempfile.mkdtemp(prefix="mini_agent_kb_")
    for index, file in enumerate(files):
        name = str(file.get("name") or f"doc_{index}.txt")
        # Flatten to a basename and force .txt/.md so RagSearch picks it up.
        safe_name = pathlib.Path(name).name or f"doc_{index}.txt"
        if pathlib.Path(safe_name).suffix.lower() not in (".txt", ".md"):
            safe_name = f"{safe_name}.txt"
        (pathlib.Path(temp_dir) / safe_name).write_text(str(file.get("content", "")), encoding="utf-8")

    session.docs_folder = temp_dir
    session.collection_name = session.session_id

    try:
        rag = RagSearch(
            openai_api_key=session.openai_api_key,
            collection_name=session.collection_name,
            docs_folder=session.docs_folder,
            embedding_model=session.embedding_model,
        )
        rag.initialise()
        chunk_count = rag._collection.count()
        session.rag_search = rag  # reused by every RAG_search query this session
    except Exception as error:
        logging.error(f"[SERVER] KB build failed — session {session.session_id}: {error}", exc_info=True)
        await websocket.send_json({"type": "error", "content": f"Failed to build knowledge base: {error}"})
        await websocket.close(code=4001, reason="KB build failed")
        _cleanup_session_kb(session)
        return False

    await websocket.send_json({"type": "kb_ready", "chunks": chunk_count})
    logging.info(f"[SERVER] KB built — session {session.session_id}: {chunk_count} chunks from {len(files)} file(s)")
    return True


def _cleanup_session_kb(session: SessionContext) -> None:
    session.rag_search = None
    if session.collection_name == session.session_id:
        try:
            import chromadb

            chromadb.PersistentClient(path=str(CHROMA_DIR)).delete_collection(session.collection_name)
        except Exception as error:
            logging.debug(f"[SERVER] delete_collection skipped — session {session.session_id}: {error}")
    if session.docs_folder:
        shutil.rmtree(session.docs_folder, ignore_errors=True)
        session.docs_folder = ""


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_event_loop()
    session = SessionContext(websocket=websocket, loop=loop)
    set_session(session)

    if not await _authenticate(websocket, session):
        return

    logging.info(
        f"[SERVER] Client authenticated. Session: {session.session_id} | "
        f"user: {session.user_email} | usecase: {session.usecase}"
    )

    if not await _receive_documents(websocket, session):
        return

    await websocket.send_json(
        {
            "type": "acknowledgement",
            "session_id": session.session_id,
            "content": "What would you like to do?",
        }
    )

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
    _cleanup_session_kb(session)
    logging.info(f"[SERVER] Session complete: {session.session_id}")


def _run_state_machine(session: SessionContext) -> None:
    set_session(session)
    StateMemory.reset()
    machine = StateMachine(session.usecase)
    machine.run()


def main() -> None:
    import uvicorn

    uvicorn.run("mini_agent.server:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
