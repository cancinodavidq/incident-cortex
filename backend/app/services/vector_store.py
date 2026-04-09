"""
Vector Store Service for Incident Cortex.

Provides ChromaDB abstraction for semantic search over codebase chunks
and incident deduplication using embeddings.
"""

import logging
from typing import Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

from app.config import get_settings

logger = logging.getLogger(__name__)


class OpenAIEmbeddingFunction(chromadb.EmbeddingFunction):
    """ChromaDB embedding function using OpenAI API."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        response = self.client.embeddings.create(
            model=self.model,
            input=input,
        )
        return [item.embedding for item in response.data]


class SentenceTransformerEmbeddingFunction(chromadb.EmbeddingFunction):
    """ChromaDB embedding function using Sentence Transformers."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings using Sentence Transformers."""
        embeddings = self.model.encode(input, convert_to_numpy=False)
        return [emb.tolist() for emb in embeddings]


class VectorStore:
    """ChromaDB-backed vector store for code and incident embeddings."""

    def __init__(self, settings=None):
        """
        Initialize vector store.

        Args:
            settings: App settings object (uses get_settings() if None)
        """
        self.settings = settings or get_settings()
        self._client = None
        self._collection = None
        self._dedup_collection = None
        self._embedding_function = None

    def _initialize_client(self):
        """Initialize ChromaDB client and embedding function."""
        if self._client is not None:
            return

        # Initialize embedding function
        if self.settings.openai_api_key and OPENAI_AVAILABLE:
            logger.info("Using OpenAI embeddings (text-embedding-3-small)")
            self._embedding_function = OpenAIEmbeddingFunction(
                api_key=self.settings.openai_api_key
            )
        elif SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.info(
                "Using Sentence Transformers embeddings (all-MiniLM-L6-v2)"
            )
            self._embedding_function = SentenceTransformerEmbeddingFunction()
        else:
            raise RuntimeError(
                "No embedding function available. "
                "Install sentence-transformers or set OPENAI_API_KEY"
            )

        # Initialize ChromaDB client (remote HTTP)
        self._client = chromadb.HttpClient(
            host=self.settings.chroma_host,
            port=self.settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    def get_collection(self, name: str = "code_chunks"):
        """Get or create a ChromaDB collection."""
        self._initialize_client()
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._embedding_function,
        )

    @property
    def collection(self):
        """Get code chunks collection."""
        if self._collection is None:
            self._collection = self.get_collection("code_chunks")
        return self._collection

    @property
    def dedup_collection(self):
        """Get incident embeddings collection for deduplication."""
        if self._dedup_collection is None:
            self._dedup_collection = self.get_collection("incident_embeddings")
        return self._dedup_collection

    def add_documents(self, chunks: list[dict]) -> None:
        """
        Add code chunks to the vector store.

        Args:
            chunks: List of dicts with keys:
                - content (str): The code content
                - file_path (str): Source file path
                - module (str): Module name
                - chunk_type (str): Type of chunk (function, class, etc.)
                - function_name (str, optional): Function/class name
        """
        if not chunks:
            return

        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{chunk['file_path']}_{i}"
            ids.append(chunk_id)
            documents.append(chunk["content"])
            metadatas.append(
                {
                    "file_path": chunk["file_path"],
                    "module": chunk.get("module", ""),
                    "chunk_type": chunk.get("chunk_type", ""),
                    "function_name": chunk.get("function_name", ""),
                }
            )

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(f"Added {len(chunks)} documents to vector store")

    def query(
        self,
        query_text: str,
        n_results: int = 10,
        where_filter: Optional[dict] = None,
    ) -> list[dict]:
        """
        Query the vector store for relevant code chunks.

        Args:
            query_text: Search query
            n_results: Number of results to return
            where_filter: ChromaDB where filter dict

        Returns:
            List of dicts with: file_path, module, chunk_type, function_name,
            content, relevance_score (0-1, higher is better)
        """
        kwargs = {"query_texts": [query_text], "n_results": n_results}
        if where_filter:
            kwargs["where"] = where_filter
        results = self.collection.query(**kwargs)

        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i]
            # Convert distance to relevance score (0-1, higher is better)
            relevance_score = 1 / (1 + distance)

            metadata = results["metadatas"][0][i]
            output.append(
                {
                    "file_path": metadata.get("file_path", ""),
                    "module": metadata.get("module", ""),
                    "chunk_type": metadata.get("chunk_type", ""),
                    "function_name": metadata.get("function_name", ""),
                    "content": doc,
                    "relevance_score": relevance_score,
                }
            )

        return output

    def file_exists(self, file_path: str) -> bool:
        """Check if a file has been indexed in the vector store."""
        try:
            results = self.collection.get(
                where={"file_path": {"$eq": file_path}},
                limit=1,
            )
            return len(results["ids"]) > 0
        except Exception as e:
            logger.error(f"Error checking file existence: {e}")
            return False

    def get_chunks_by_file(self, file_path: str) -> list[dict]:
        """
        Get all chunks from a specific file.

        Args:
            file_path: Path to the file

        Returns:
            List of chunk dicts
        """
        try:
            results = self.collection.get(
                where={"file_path": {"$eq": file_path}},
            )

            output = []
            for i, doc_id in enumerate(results["ids"]):
                metadata = results["metadatas"][i]
                output.append(
                    {
                        "id": doc_id,
                        "file_path": metadata.get("file_path", ""),
                        "module": metadata.get("module", ""),
                        "chunk_type": metadata.get("chunk_type", ""),
                        "function_name": metadata.get("function_name", ""),
                        "content": results["documents"][i],
                    }
                )

            return output
        except Exception as e:
            logger.error(f"Error getting chunks by file: {e}")
            return []

    def expand_context(
        self,
        top_files: list[str],
        query_text: str,
        n_results: int = 15,
    ) -> list[dict]:
        """
        Expand context by querying specific files.

        Args:
            top_files: List of file paths to search within
            query_text: Search query
            n_results: Total results to return

        Returns:
            List of relevant chunks from top_files
        """
        all_results = []

        # Try using $in filter
        try:
            where_filter = {"file_path": {"$in": top_files}}
            results = self.query(query_text, n_results, where_filter)
            if results:
                return results
        except Exception as e:
            logger.warning(f"$in filter not supported, falling back: {e}")

        # Fallback: query each file individually
        results_per_file = max(1, n_results // len(top_files))
        for file_path in top_files:
            try:
                where_filter = {"file_path": {"$eq": file_path}}
                results = self.query(
                    query_text, results_per_file, where_filter
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(
                    f"Error querying file {file_path}: {e}"
                )
                continue

        # Sort by relevance and limit
        all_results.sort(
            key=lambda x: x["relevance_score"], reverse=True
        )
        return all_results[:n_results]

    def add_incident_embedding(
        self,
        incident_id: str,
        title: str,
        description: str,
        service: str,
        resolution: str = "",
    ) -> None:
        """
        Add an incident embedding for deduplication.

        Args:
            incident_id: Unique incident ID
            title: Incident title
            description: Incident description
            service: Affected service
            resolution: Resolution (optional)
        """
        combined_text = f"{title} {description} {service}"

        self.dedup_collection.add(
            ids=[incident_id],
            documents=[combined_text],
            metadatas=[
                {
                    "incident_id": incident_id,
                    "title": title,
                    "service": service,
                    "resolution": resolution,
                }
            ],
        )

    def find_similar_incidents(
        self,
        query_text: str,
        n_results: int = 5,
    ) -> list[dict]:
        """
        Find similar incidents for deduplication.

        Args:
            query_text: Search query (typically title + description)
            n_results: Number of results to return

        Returns:
            List of dicts with: incident_id, title, service, resolution,
            relevance_score
        """
        results = self.dedup_collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )


        if not results["documents"] or not results["documents"][0]:
            return []

        output = []
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i]
            relevance_score = 1 / (1 + distance)

            metadata = results["metadatas"][0][i]
            output.append(
                {
                    "incident_id": metadata.get("incident_id", ""),
                    "title": metadata.get("title", ""),
                    "service": metadata.get("service", ""),
                    "resolution": metadata.get("resolution", ""),
                    "relevance_score": relevance_score,
                }
            )

        return output


# Singleton instance
_vector_store: VectorStore | None = None


async def get_vector_store() -> VectorStore:
    """Get or create vector store singleton."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
