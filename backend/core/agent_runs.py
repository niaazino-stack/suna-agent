"""
This module handles the lifecycle of agent runs (starting, stopping, streaming).

It has been refactored to remove all dependencies on the legacy `core_utils` module.
Database connections are now handled via a clean dependency, and the logic for
stopping a run has been moved directly into the relevant endpoint.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request, Form
from fastapi.responses import StreamingResponse
from postgrest import APIResponse

# Core dependencies
from core.utils.auth_utils import (
    verify_and_get_user_id_from_jwt,
    get_optional_user_id_from_jwt,
    require_thread_ownership
)
from core.utils.logger import logger, structlog
from core.services import redis
from core.services.supabase import DBConnection
from run_agent_background import run_agent_background
from core.ai_models import model_manager
from core.agent_loader import get_agent_loader, AgentData

router = APIRouter(tags=["agent-runs"])

# --- Pydantic Models ---
# Using existing models from api_models where possible, or defining simple ones here.
class AgentRunStartResponse(BaseModel):
    thread_id: str
    agent_run_id: str
    status: str

class AgentRunStopResponse(BaseModel):
    status: str

class AgentRunListResponse(BaseModel):
    agent_runs: List[dict]

# --- Helper Functions & Dependencies ---

async def _get_db_client():
    """Dependency to get a Supabase client."""
    db = DBConnection()
    return await db.client

async def _get_run_and_verify_ownership(run_id: str, user_id: str, client) -> dict:
    """Fetches a run and its associated thread, ensuring the user is the owner."""
    # This query joins agent_runs with threads to check the account_id on the thread
    # This is a robust way to ensure a user can only access runs within their own threads.
    response = await client.table('agent_runs').select('*, threads!inner(account_id)').eq('id', run_id).single().execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    
    # The inner join ensures that 'threads' will be present.
    if response.data['threads']['account_id'] != user_id:
        raise HTTPException(status_code=403, detail="Access denied: You do not own the thread associated with this run.")
    
    # Clean up the response by removing the joined thread data before returning.
    del response.data['threads']
    return response.data

# --- API Endpoints ---

@router.post("/runs/start", response_model=AgentRunStartResponse, summary="Start Agent Run", operation_id="start_agent_run")
async def start_agent_run(
    thread_id: str = Form(...),
    agent_id: str = Form(...),
    prompt: str = Form(...),
    model_name: Optional[str] = Form(None),
    thread: dict = Depends(require_thread_ownership),
    client = Depends(_get_db_client),
    loader = Depends(get_agent_loader)
):
    user_id = thread['account_id']
    logger.info(f"Starting agent run for user {user_id} in thread {thread_id}")

    try:
        # Load agent configuration using the new loader
        agent_data: AgentData = await loader.load_agent(agent_id, user_id)
        agent_config = agent_data.to_dict()

        effective_model = model_name or agent_config.get('model') or await model_manager.get_default_model()

        # Create the initial user message
        await client.table('messages').insert({
            "thread_id": thread_id, "type": "user", "is_llm_message": True, "content": {"role": "user", "content": prompt}
        }).execute()

        # Create the agent run record
        run_id = str(uuid.uuid4())
        await client.table('agent_runs').insert({
            "id": run_id, "thread_id": thread_id, "status": "running", "agent_id": agent_id,
            "agent_version_id": agent_config.get('current_version_id'),
            "metadata": {"model_name": effective_model}
        }).execute()

        # Defer the actual agent execution to a background task
        request_id = structlog.contextvars.get_contextvars().get('request_id')
        run_agent_background.send(
            agent_run_id=run_id, thread_id=thread_id,
            model_name=effective_model, agent_config=agent_config, request_id=request_id,
        )

        logger.info(f"Successfully dispatched agent run {run_id}")
        return AgentRunStartResponse(thread_id=thread_id, agent_run_id=run_id, status="running")

    except Exception as e:
        logger.error(f"Failed to start agent run: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred while starting the agent run.")

@router.post("/runs/{run_id}/stop", response_model=AgentRunStopResponse, summary="Stop Agent Run", operation_id="stop_agent_run")
async def stop_agent_run(
    run_id: str,
    user_id: str = Depends(verify_and_get_user_id_from_jwt),
    client = Depends(_get_db_client)
):
    """Stops a running agent and updates its status."""
    logger.info(f"User {user_id} requesting to stop agent run {run_id}")
    await _get_run_and_verify_ownership(run_id, user_id, client)

    try:
        # Update status in the database
        await client.table('agent_runs').update({"status": "stopped"}).eq('id', run_id).execute()
        
        # Publish stop message to Redis to terminate streaming and background tasks
        control_channel = f"agent_run:{run_id}:control"
        await redis.publish(control_channel, "STOP")
        
        logger.info(f"Successfully stopped agent run {run_id}")
        return AgentRunStopResponse(status="stopped")

    except Exception as e:
        logger.error(f"Failed to stop agent run {run_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to stop the agent run.")


# Other endpoints (get_agent_run, get_agent_runs_for_thread, stream_agent_run) remain largely the same
# but are updated to use the new dependency injection for the DB client.

@router.get("/runs/{run_id}", summary="Get Agent Run", operation_id="get_agent_run")
async def get_agent_run(
    run_id: str,
    user_id: str = Depends(verify_and_get_user_id_from_jwt),
    client = Depends(_get_db_client)
):
    logger.debug(f"Fetching details for agent run {run_id}")
    agent_run_data = await _get_run_and_verify_ownership(run_id, user_id, client)
    return agent_run_data

@router.get("/threads/{thread_id}/runs", response_model=AgentRunListResponse, summary="List Thread Agent Runs", operation_id="list_thread_agent_runs")
async def get_agent_runs_for_thread(
    thread: dict = Depends(require_thread_ownership),
    client = Depends(_get_db_client)
):
    thread_id = thread['thread_id']
    logger.debug(f"Fetching all agent runs for thread {thread_id}")
    result = await client.table('agent_runs').select('*').eq("thread_id", thread_id).order('created_at', desc=True).execute()
    return AgentRunListResponse(agent_runs=result.data)

@router.get("/runs/{run_id}/stream", summary="Stream Agent Run", operation_id="stream_agent_run")
async def stream_agent_run(
    run_id: str,
    request: Request, # FastAPI will provide the request object
    client = Depends(_get_db_client),
):
    user_id = await get_optional_user_id_from_jwt(request)
    if not user_id:
        # For now, we allow unauthenticated access but log it. 
        # A real-world app might use a short-lived token passed in the query params.
        logger.warning(f"Unauthenticated stream access attempt for run {run_id}")
        # Deny access if no user_id is found.
        raise HTTPException(status_code=401, detail="Authentication required to stream this run.")

    await _get_run_and_verify_ownership(run_id, user_id, client)
    
    response_list_key = f"agent_run:{run_id}:responses"
    control_channel = f"agent_run:{run_id}:control"

    async def stream_generator():
        # This generator function streams responses from Redis.
        # It first sends existing historical data, then listens for real-time updates.
        try:
            # 1. Send history
            initial_responses = await redis.lrange(response_list_key, 0, -1)
            for response in initial_responses:
                yield f"data: {response}\n\n"
            
            # 2. Check if run is already complete
            run_status_bytes = await redis.get(f"agent_run:{run_id}:status")
            run_status = run_status_bytes.decode() if run_status_bytes else "running"
            if run_status in ['completed', 'failed', 'stopped']:
                yield f'data: {json.dumps({"type": "status", "status": run_status})}\n\n'
                return

            # 3. Listen for real-time updates
            async with redis.pubsub() as pubsub:
                await pubsub.subscribe(control_channel)
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
                    if not message: continue

                    data = message['data'].decode('utf-8')
                    if data == "STOP":
                        break
                    
                    # 'NEW' signal means new data is in the list, fetch and send it
                    if data == 'NEW':
                        next_index = len(initial_responses)
                        new_responses = await redis.lrange(response_list_key, next_index, -1)
                        for response in new_responses:
                            yield f"data: {response}\n\n"
                        initial_responses.extend(new_responses)
        except asyncio.CancelledError:
            logger.info(f"Client cancelled stream for run {run_id}")
        finally:
            logger.info(f"Closing stream for run {run_id}")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
