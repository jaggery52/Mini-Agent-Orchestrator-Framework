"""Build-time knowledge-base indexer.

Indexes every usecase's documents into its own Chroma collection and persists the
result to CHROMA_DIR. Intended to run at Docker BUILD time with the embedding API
key supplied as a build secret (e.g. `--mount=type=secret,id=openai_key`), so the
running server never needs an LLM key — the baked Chroma DB ships inside the image
and client-supplied keys only embed queries at runtime.

Convention: collection name == usecase slug == the sub-directory name under
knowledge_base/. The client must pass the matching `collection_name` in the `init`
handshake.

Usage:
    OPENAI_API_KEY=sk-... python -m mini_agent.build_kb
"""

import logging
import os
import sys

from mini_agent.settings import KNOWLEDGE_BASE_DIR
from mini_agent.states.ai.search.rag_search import RagSearch


def build_all() -> int:
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

    if not openai_api_key:
        logging.error("[BUILD_KB] OPENAI_API_KEY is required at build time (pass it as a build secret).")
        return 1

    if not KNOWLEDGE_BASE_DIR.exists():
        logging.error(f"[BUILD_KB] Knowledge base dir not found: {KNOWLEDGE_BASE_DIR}")
        return 1

    usecase_dirs = sorted(p for p in KNOWLEDGE_BASE_DIR.iterdir() if p.is_dir())
    if not usecase_dirs:
        logging.error(f"[BUILD_KB] No usecase sub-directories under {KNOWLEDGE_BASE_DIR}")
        return 1

    logging.info(f"[BUILD_KB] Indexing {len(usecase_dirs)} usecase(s) with model '{embedding_model}'")

    for usecase_dir in usecase_dirs:
        usecase = usecase_dir.name
        logging.info(f"[BUILD_KB] --- Building collection '{usecase}' from {usecase_dir}")
        rag = RagSearch(
            openai_api_key=openai_api_key,
            collection_name=usecase,
            docs_folder=str(usecase_dir),
            embedding_model=embedding_model,
        )
        rag.initialise()

    logging.info("[BUILD_KB] All collections built and persisted.")
    return 0


def main() -> None:
    sys.exit(build_all())


if __name__ == "__main__":
    main()
