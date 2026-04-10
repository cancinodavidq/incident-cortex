from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from app.config import get_settings
from app.services.event_store import get_event_store
from app.services.vector_store import get_vector_store
from app.api.routes import router
from app.api.websocket import ws_router
from app.observability.tracing import setup_tracing

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifespan context manager."""
    # Startup
    logging.basicConfig(
        level=settings.log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        await get_event_store()
        logger.info("EventStore initialized")

        await get_vector_store()
        logger.info("VectorStore initialized")

        setup_tracing()
        logger.info("Tracing configured")

        logger.info("Incident Cortex backend started")
    except Exception as e:
        logger.error(f"Startup failed: {e}", exc_info=True)
        raise

    yield

    # Shutdown
    logger.info("Shutting down Incident Cortex")


app = FastAPI(
    title="Incident Cortex API",
    description="SRE Incident Triage Agent powered by LangGraph",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if hasattr(settings, 'cors_origins') else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router, prefix="/api")
app.include_router(ws_router)


@app.get("/health")
async def health_check():
    """Health check endpoint with system status."""
    event_store = await get_event_store()

    try:
        # Check if indexing is complete: first try DB, then fall back to ChromaDB count
        indexing_complete = await event_store.check_indexing_status()
        if not indexing_complete:
            from app.services.vector_store import VectorStore
            vs = VectorStore()
            count = vs.collection.count() if vs.collection else 0
            indexing_complete = count > 0
    except Exception as e:
        logger.warning(f"Failed to check indexing status: {e}")
        indexing_complete = False

    return {
        "status": "healthy",
        "indexing_complete": indexing_complete,
        "version": "1.0.0"
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Incident Cortex API",
        "version": "1.0.0",
        "description": "SRE Incident Triage Agent"
    }
