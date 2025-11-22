from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, Response, Depends, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from core.services import redis
# import sentry # Sentry is not configured, commenting out for now.
from contextlib import asynccontextmanager
from core.services.supabase import DBConnection
from datetime import datetime, timezone
from core.utils.config import config, EnvMode
import asyncio
from core.utils.logger import logger, structlog
import time
from collections import OrderedDict
import os
import sys
import uuid

from pydantic import BaseModel

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
from core import limits_api
from core.guest_session import guest_session_service


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

db = DBConnection()
# Generate unique instance ID per process/worker
# This is critical for distributed locking - each worker needs a unique ID
instance_id = str(uuid.uuid4())[:8]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Handles startup and shutdown events.
    """
    logger.debug(f"Starting up FastAPI application with instance ID: {instance_id} in {config.ENV_MODE.value} mode")
    try:
        await db.initialize()
        
        core_api.initialize(db, instance_id)
        sandbox_api.initialize(db)
        
        # Initialize Redis connection
        try:
            await redis.initialize_async()
            logger.debug("Redis connection initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
        
        # Initialize other modules
        triggers_api.initialize(db)
        credentials_api.initialize(db)
        template_api.initialize(db)
        composio_api.initialize(db)
        limits_api.initialize(db)
        
        guest_session_service.start_cleanup_task()
        logger.debug("Guest session cleanup task started")
        
        yield
        
        logger.debug("Cleaning up agent resources")
        await core_api.cleanup()
        
        logger.debug("Stopping guest session cleanup task")
        await guest_session_service.stop_cleanup_task()
        
        try:
            logger.debug("Closing Redis connection")
            await redis.close()
            logger.debug("Redis connection closed successfully")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

        logger.debug("Disconnecting from database")
        await db.disconnect()
    except Exception as e:
        logger.critical(f"Critical error during application lifespan: {e}", exc_info=True)
        raise

app = FastAPI(
    lifespan=lifespan,
    title="Super Agent API",
    description="A powerful, modular, and user-friendly agent framework.",
    version="1.0.0"
)

@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    """
    Middleware to log incoming requests and responses.
    """
    structlog.contextvars.clear_contextvars()

    request_id = str(uuid.uuid4())
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"

    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        client_ip=client_ip,
        method=request.method,
        path=request.url.path,
        query_params=str(request.query_params)
    )

    logger.info(f"Request started")
    
    try:
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000  # in ms
        
        structlog.contextvars.bind_contextvars(
            status_code=response.status_code,
            process_time_ms=round(process_time, 2)
        )
        logger.info(f"Request completed")
        
        return response
    except Exception as e:
        process_time = (time.time() - start_time) * 1000  # in ms
        structlog.contextvars.bind_contextvars(
            process_time_ms=round(process_time, 2)
        )
        logger.exception("Request failed")
        # Re-raising the exception to be handled by FastAPI's exception handlers
        raise

# Define allowed origins based on environment
allowed_origins = ["https://www.kortix.com", "https://kortix.com", "https://www.suna.so", "https://suna.so"]
allow_origin_regex = None

if config.ENV_MODE == EnvMode.LOCAL:
    allowed_origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"])

if config.ENV_MODE == EnvMode.STAGING:
    allowed_origins.extend(["https://staging.suna.so", "http://localhost:3000"])
    # Allow Vercel preview deployments
    allow_origin_regex = r"https://(suna|kortixcom)-.*-prjcts\.vercel\.app"

if config.ENV_MODE == EnvMode.PRODUCTION:
    allowed_origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"]) # For local access to prod if needed

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"], # Allowing all headers for now, can be restricted later
)

# Create a main API router
api_router = APIRouter(prefix="/api")

# --- System Endpoints ---
@api_router.get("/health", summary="Health Check", operation_id="health_check", tags=["System"])
async def health_check():
    """
    Standard health check endpoint.
    """
    logger.debug("Health check endpoint called")
    return {
        "status": "ok", 
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id
    }

@api_router.get("/health-deep", summary="Deep Health Check", operation_id="health_check_deep", tags=["System"])
async def health_check_deep():
    """
    A deep health check that verifies connections to dependencies like Redis and the database.
    """
    logger.debug("Deep health check endpoint called")
    results = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instance_id": instance_id,
        "dependencies": {}
    }
    
    # Check Redis
    try:
        client = await redis.get_client()
        await client.ping()
        results["dependencies"]["redis"] = "ok"
    except Exception as e:
        results["status"] = "error"
        results["dependencies"]["redis"] = f"failed: {e}"
        logger.error(f"Deep health check failed for Redis: {e}")

    # Check Database
    try:
        db_client = await db.get_client()
        await db_client.table("threads").select("thread_id", count="exact").limit(1).execute()
        results["dependencies"]["database"] = "ok"
    except Exception as e:
        results["status"] = "error"
        results["dependencies"]["database"] = f"failed: {e}"
        logger.error(f"Deep health check failed for Database: {e}")

    status_code = 200 if results["status"] == "ok" else 503
    return JSONResponse(content=results, status_code=status_code)


# --- Include all API routers ---
# Grouping routers for better organization
api_router.include_router(core_api.router)
api_router.include_router(sandbox_api.router)
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
    
    # Enable reload mode for local and staging environments
    is_dev_env = config.ENV_MODE in [EnvMode.LOCAL, EnvMode.STAGING]
    
    log_level = "debug" if is_dev_env else "info"
    
    logger.info(f"Starting server on 0.0.0.0:8000 (reload={is_dev_env})")
    uvicorn.run(
        "api:app", 
        host="0.0.0.0", 
        port=8000,
        reload=is_dev_env,
        log_level=log_level,
        loop="asyncio"
    )
