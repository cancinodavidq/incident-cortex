"""
Codebase indexer for Incident Cortex.
Clones Reaction Commerce repo, extracts code chunks, generates embeddings, stores in ChromaDB.
Sets system_status.indexing_complete=true when done.
"""
import os
import re
import fnmatch
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import time

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config from env
REPO_URL = os.getenv("ECOMMERCE_REPO_URL", "https://github.com/reactioncommerce/reaction.git")
REPO_BRANCH = os.getenv("ECOMMERCE_REPO_BRANCH", "trunk")
REPO_PATH = os.getenv("REPO_PATH", "/tmp/reaction")
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "ecommerce_codebase")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

INCLUDE_PATTERNS = ["*.js", "*.ts", "*.graphql"]
EXCLUDE_DIRS = {"node_modules", "dist", "build", "assets", ".git", "coverage", "__tests__", ".next", "public"}
EXCLUDE_PATTERNS = ["*.test.js", "*.spec.js", "*.min.js", "*.test.ts", "*.spec.ts"]

FUNCTION_PATTERNS = [
    r"(export\s+)?(async\s+)?function\s+(?P<name>\w+)",
    r"const\s+(?P<name>\w+)\s*=\s*(async\s+)?\(",
    r"(?P<name>\w+)\s*:\s*(async\s+)?(?:function|\()",
    r"class\s+(?P<name>\w+)",
]

MAX_CHUNK_TOKENS = 500
CHUNK_OVERLAP = 50

def clone_repo():
    """Clone repo with git, skip if already cloned"""
    repo_path = Path(REPO_PATH)

    if repo_path.exists():
        logger.info(f"Repository already exists at {REPO_PATH}, skipping clone")
        return REPO_PATH

    logger.info(f"Cloning repository from {REPO_URL} (branch: {REPO_BRANCH})")
    try:
        cmd = [
            "git", "clone",
            "--branch", REPO_BRANCH,
            "--depth", "1",
            REPO_URL,
            REPO_PATH
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"Repository cloned to {REPO_PATH}")
        return REPO_PATH
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to clone repository: {e.stderr.decode()}")
        return None

def should_include_file(file_path: Path) -> bool:
    """Check if file matches include/exclude patterns"""
    # Check if in excluded directory
    for part in file_path.parts:
        if part in EXCLUDE_DIRS:
            return False

    # Check exclude patterns
    name = file_path.name
    for pattern in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return False

    # Check include patterns
    for pattern in INCLUDE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True

    return False

def get_files(repo_path: str) -> List[Path]:
    """Walk directory tree filtering by include/exclude patterns"""
    repo = Path(repo_path)
    files = []

    for file_path in repo.rglob("*"):
        if file_path.is_file() and should_include_file(file_path):
            files.append(file_path)

    return files

def extract_chunks(file_path: Path, content: str) -> List[Dict]:
    """Parse functions/classes; fallback to fixed-size chunks"""
    chunks = []

    # Try to extract named functions/classes
    named_chunks = []
    for pattern in FUNCTION_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            start = max(0, match.start() - 100)
            # Find reasonable end (next function or 500 chars)
            end = min(len(content), match.start() + 400)
            chunk_text = content[start:end]
            named_chunks.append({
                "text": chunk_text,
                "type": "function",
                "name": match.group("name") if "name" in match.groupdict() else "unknown"
            })

    if named_chunks:
        chunks.extend(named_chunks)
    else:
        # Fallback: split into fixed-size chunks
        chunk_size = 400
        for i in range(0, len(content), chunk_size - CHUNK_OVERLAP):
            chunk_text = content[i:i + chunk_size]
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text,
                    "type": "fixed",
                    "name": f"chunk_{i}"
                })

    return chunks

def get_embedding_function():
    """OpenAI if key present, else sentence-transformers"""
    if OPENAI_API_KEY:
        logger.info("Using OpenAI embeddings")
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=OPENAI_API_KEY,
            model_name="text-embedding-3-small"
        )
    else:
        logger.info("Using sentence-transformers (no OpenAI key)")
        return embedding_functions.DefaultEmbeddingFunction()

def index_file(collection, file_path: Path, chunks: List[Dict]) -> int:
    """Add to ChromaDB with metadata"""
    indexed = 0

    for chunk in chunks:
        try:
            chunk_id = f"{file_path.name}_{chunk['name']}"

            collection.add(
                ids=[chunk_id],
                documents=[chunk["text"]],
                metadatas=[{
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "chunk_type": chunk.get("type", "unknown"),
                    "chunk_name": chunk.get("name", "unknown"),
                    "indexed_at": datetime.utcnow().isoformat()
                }]
            )
            indexed += 1
        except Exception as e:
            logger.error(f"Failed to index chunk {chunk['name']} from {file_path}: {e}")

    return indexed

def mark_indexing_complete():
    """Update PostgreSQL system_status table (placeholder)"""
    # In a real implementation, this would connect to PostgreSQL
    # For now, write a marker file
    marker_file = Path("/tmp/indexing_complete.txt")
    marker_file.write_text(datetime.utcnow().isoformat())
    logger.info(f"Indexing marked complete at {marker_file}")

async def main():
    """Orchestrate the full pipeline with progress logging"""
    start_time = time.time()

    logger.info("Starting Incident Cortex codebase indexer...")

    # Clone repo
    repo_path = clone_repo()
    if not repo_path:
        logger.error("Failed to clone repository, aborting")
        return

    # Initialize ChromaDB
    if chromadb is None:
        logger.warning("ChromaDB not installed, skipping indexing")
        return

    try:
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        logger.info(f"Connected to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}")
    except Exception as e:
        logger.warning(f"Failed to connect to ChromaDB: {e}, using in-memory storage")
        client = chromadb.Client()

    embedding_fn = get_embedding_function()
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn
    )

    # Get all files
    logger.info("Scanning repository for source files...")
    files = get_files(repo_path)
    logger.info(f"Found {len(files)} source files")

    # Process files
    total_chunks = 0
    total_files = 0

    for i, file_path in enumerate(files, 1):
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            chunks = extract_chunks(file_path, content)
            indexed = index_file(collection, file_path, chunks)
            total_chunks += indexed
            total_files += 1

            if i % 10 == 0:
                logger.info(f"Processed {i}/{len(files)} files, {total_chunks} chunks indexed")
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")

    # Mark complete
    mark_indexing_complete()

    elapsed = time.time() - start_time
    logger.info(f"Indexed {total_files} files, {total_chunks} chunks in {elapsed:.1f}s")

if __name__ == "__main__":
    asyncio.run(main())
