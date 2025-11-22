from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import time
import uuid
import os

# Internal imports
from core.services.supabase import DBConnection
from core.services import redis
from core.utils.config import config, EnvMode
from core.utils.logger import logger, structlog

# --- API Routers ---
from core import api as core_api
from core.sandbox import api as sandbox_api
from core.services import transcription as transcription_api
from core.services import email_api
from core.triggers import api as triggers_api
from core.services import api_keys_api
from core.mcp_module import api as mcp_api
from core.credentials import api as credentials_api
from core.templates import api as template_api
from core.knowledge_base import api as knowledge_base_api
from core.composio_integration import api as composio_api
from core.settings_api import router as settings_api_router # Import the new settings router

# --- App Initialization ---

db = DBConnection()
instance_id = str(uuid.uuid4())[:8]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    logger.info(f"Starting up instance {instance_id} in {config.ENV_MODE.value} mode")
    await db.initialize()
    await redis.initialize_async()
    
    # Initialize modules that require it
    triggers_api.initialize(db)
    credentials_api.initialize(db)
    template_api.initialize(db)
    composio_api.initialize(db)
    
    yield
    
    logger.info(f"Shutting down instance {instance_id}")
    await redis.close()
    await db.disconnect()

app = FastAPI(
    lifespan=lifespan,
    title="Super Agent API",
    version="2.0.0",
    description="A powerful, modular, and extensible agent framework."
)

# --- Middleware ---

# CORS Middleware
allowed_origins = {
    EnvMode.LOCAL: ["http://localhost:3000", "http://127.0.0.1:3000"],
    EnvMode.STAGING: ["https://staging.suna.so", r"https://(suna|kortixcom)-.*-prjcts\.vercel\.app"],
    EnvMode.PRODUCTION: ["https://www.kortix.com", "https://kortix.com", "https://www.suna.so", "https://suna.so"]
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins.get(config.ENV_MODE, []),
    allow_origin_regex=allowed_origins[EnvMode.STAGING][1] if config.ENV_MODE == EnvMode.STAGING else None,
    allow_credentials=True,
    allow_methods=["*"]
    allow_headers=["*"]
)

@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=str(uuid.uuid4()))
    start_time = time.perf_counter()
    
    response = await call_next(request)
    
    process_time = (time.perf_counter() - start_time) * 1000
    logger.info(
        f'{request.method} {request.url.path} - {response.status_code} ({process_time:.2f}ms)',
        extra={
            'method': request.method,
            'path': request.url.path,
            'status_code': response.status_code,
            'process_time_ms': process_time
        }
    )
    return response


# --- API Router Setup ---

api_router = APIRouter(prefix="/api")

@api_router.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "instance_id": instance_id}

# Include all the modular routers
api_router.include_router(core_api.router)
api_router.include_router(sandbox_api.router)
api_router.include_router(settings_api_router, prefix="/settings", tags=["Settings"])
api_router.include_router(api_keys_api.router, prefix="/keys", tags=["API Keys"])
api_router.include_router(mcp_api.router, prefix="/mcp", tags=["MCP"])
api_router.include_router(credentials_api.router, prefix="/secure-mcp", tags=["Secure MCP"])
api_router.include_router(template_api.router, prefix="/templates", tags=["Templates"])
api_router.include_router(transcription_api.router, prefix="/transcription", tags=["Transcription"])
api_router.include_router(email_api.router, prefix="/email", tags=["Email"])
api_router.include_router(knowledge_base_api.router, prefix="/kb", tags=["Knowledge Base"])
api_router.include_router(triggers_api.router, prefix="/triggers", tags=["Triggers"])
api_router.include_router(composio_api.router, prefix="/composio", tags=["Composio"])

app.include_router(api_router)

# --- Main Entry Point ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=(config.ENV_MODE != EnvMode.PRODUCTION),
        log_level="debug" if (config.ENV_MODE != EnvMode.PRODUCTION) else "info"
    )
