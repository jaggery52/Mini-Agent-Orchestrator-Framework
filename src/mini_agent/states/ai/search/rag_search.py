import hashlib
import logging
import pathlib
from typing import List, Optional

from mini_agent.settings import CHROMA_DIR, FORCE_REINDEX, KNOWLEDGE_BASE_DIR

CHUNK_SIZE = 500
CHUNK_OVERLAP = 150
CHROMA_PERSIST_DIR = str(CHROMA_DIR)
FINGERPRINT_FILE = pathlib.Path(CHROMA_PERSIST_DIR) / ".docs_fingerprint"


class RagSearch:
    def __init__(
        self,
        openai_api_key: str,
        collection_name: str = "mini-agent_docs",
        docs_folder: Optional[str] = None,
        embedding_model: str = "text-embedding-3-small",
    ):
        self.openai_api_key = openai_api_key
        self.collection_name = collection_name
        self.docs_folder = docs_folder or str(KNOWLEDGE_BASE_DIR)
        self.embedding_model = embedding_model
        self._collection = None
        self._openai_client = None


    def initialise(self) -> None:
        try:
            import chromadb
            from openai import OpenAI
        except ImportError as error:
            logging.error(f"[RAG] Required library not installed: {error}")
            raise

        self._openai_client = OpenAI(api_key=self.openai_api_key)

        chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self._collection = chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        current_fingerprint = self._docs_fingerprint()
        stored_fingerprint = (
            FINGERPRINT_FILE.read_text(encoding="utf-8").strip()
            if FINGERPRINT_FILE.exists()
            else None
        )

        if FORCE_REINDEX or self._collection.count() == 0 or stored_fingerprint != current_fingerprint:
            reason = (
                "FORCE_REINDEX set" if FORCE_REINDEX
                else "collection empty" if self._collection.count() == 0
                else "docs changed"
            )
            logging.info(f"[RAG] Reindexing ({reason}) — loading documents from '{self.docs_folder}'")
            self._clear_collection()
            self._load_documents()
            FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
            FINGERPRINT_FILE.write_text(current_fingerprint, encoding="utf-8")
        else:
            logging.info(
                f"[RAG] docs unchanged — skipping reload "
                f"(collection '{self.collection_name}' has {self._collection.count()} chunks)"
            )

    def _docs_fingerprint(self) -> str:
        docs_path = pathlib.Path(self.docs_folder)
        digest = hashlib.sha256()
        digest.update(f"chunk={CHUNK_SIZE}:{CHUNK_OVERLAP}".encode("utf-8"))
        if docs_path.exists():
            for file_path in sorted(docs_path.rglob("*")):
                if file_path.suffix.lower() not in (".txt", ".md"):
                    continue
                digest.update(file_path.name.encode("utf-8"))
                digest.update(file_path.read_bytes())
        return digest.hexdigest()

    def _clear_collection(self) -> None:
        existing_ids = self._collection.get(include=[]).get("ids", [])
        if existing_ids:
            self._collection.delete(ids=existing_ids)
            logging.debug(f"[RAG] Cleared {len(existing_ids)} existing chunks before reindex")

    def _load_documents(self) -> None:
        docs_path = pathlib.Path(self.docs_folder)
        if not docs_path.exists():
            logging.warning(f"[RAG] docs folder not found: {self.docs_folder}")
            return

        all_chunks: List[str] = []
        all_ids: List[str] = []
        all_metadatas: List[dict] = []
        chunk_index = 0

        for file_path in docs_path.rglob("*"):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            chunks = self._split_into_chunks(text)
            for chunk in chunks:
                all_chunks.append(chunk)
                all_ids.append(f"chunk_{chunk_index}")
                all_metadatas.append({"source": file_path.name})
                chunk_index += 1

        if not all_chunks:
            logging.warning("[RAG] No .txt or .md files found in docs folder")
            return

        embeddings = self._embed_texts(all_chunks)

        self._collection.upsert(
            ids=all_ids,
            documents=all_chunks,
            embeddings=embeddings,
            metadatas=all_metadatas,
        )
        logging.info(f"[RAG] Indexed {len(all_chunks)} chunks from {self.docs_folder}")


    def search(self, query: str, top_k: int = 5) -> str:
        if self._collection is None:
            self.initialise()

        logging.info(f"[RAG_SEARCH] Query: '{query}'")

        query_embedding = self._embed_texts([query])[0]

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count() or 1),
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        if not documents:
            logging.warning("[RAG_SEARCH] No documents retrieved")
            return f"No documents found for query: '{query}'"

        formatted = self._format_results(query, documents, metadatas, distances)
        logging.info(f"[RAG_SEARCH] Retrieved {len(documents)} chunks")
        return formatted

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        response = self._openai_client.embeddings.create(
            model=self.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _split_into_chunks(self, text: str) -> List[str]:
        words = text.split()
        chunks: List[str] = []
        start = 0
        while start < len(words):
            end = start + CHUNK_SIZE
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk)
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    def _format_results(
        self,
        query: str,
        documents: List[str],
        metadatas: List[dict],
        distances: List[float],
    ) -> str:
        parts = [f"RAG search results for: '{query}'\n"]
        for index, (doc, meta, dist) in enumerate(
            zip(documents, metadatas, distances), start=1
        ):
            source = meta.get("source", "unknown")
            similarity = round(1 - dist, 3)

            parts.append(
                f"[{index}] Source: {source} (similarity: {similarity})\n{doc}\n"
            )
        return "\n".join(parts)
