"""
This module handles the execution of agents within a thread.

It has been radically simplified to remove legacy concepts like projects, sandboxes,
billing, limits, and complex guest handling. The new model is clean, simple,
and focuses on the core task of running an agent in a thread.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request, Form
from fastapi.responses import StreamingResponse

# Core dependencies
from core.utils.auth_utils import (
    verify_and_get_user_id_from_jwt,
    get_optional_user_id_from_jwt,
    require_thread_ownership
)
from core.utils.logger import logger, structlog
from core.services import redis
from run_agent_background import run_agent_background
from core.ai_models import model_manager

# Local dependencies
from .api_models import UnifiedAgentStartResponse
from . import core_utils as utils
from .agent_loader import get_agent_loader

router = APIRouter(tags=["agent-runs"])

async def _get_agent_run_with_access_check(run_id: str, user_id: str) -> dict:
    """Fetches an agent run and verifies the user owns the associated thread."""
    client = await utils.db.client
    
    result = await client.table('agent_runs').select('*, threads!inner(account_id)').eq('id', run_id).single().execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    
    # The inner join and user_id check in require_thread_ownership is the source of truth
    if result.data['threads']['account_id'] != user_id:
        raise HTTPException(status_code=403, detail="You do not have permission to access this agent run.")

    # We don't need the joined 'threads' data anymore
    del result.data['threads']
    return result.data

@router.post("/runs/start", response_model=UnifiedAgentStartResponse, summary="Start Agent Run", operation_id="start_agent_run")
async def start_agent_run(
    thread_id: str = Form(...),
    agent_id: str = Form(...),
    prompt: str = Form(...),
    model_name: Optional[str] = Form(None),
    thread: dict = Depends(require_thread_ownership) # Authorizes thread access
):
    """
    Starts an agent run within an existing, user-owned thread.
    """
    user_id = thread['account_id']
    logger.debug(f"Starting agent run in thread {thread_id} for user {user_id}")
    
    try:
        client = await utils.db.client
        loader = await get_agent_loader()

        # 1. Load Agent Configuration
        agent_data = await loader.load_agent(agent_id, user_id, load_config=True)
        agent_config = agent_data.to_dict()

        # 2. Determine the model to use
        effective_model = model_name or agent_config.get('model') or await model_manager.get_default_model()
        logger.debug(f"Effective model for run: {effective_model}")

        # 3. Create the initial user message
        await client.table('messages').insert({
            "thread_id": thread_id,
            "type": "user",
            "is_llm_message": True,
            "content": {"role": "user", "content": prompt}
        }).execute()

        # 4. Create the agent run record
        run_id = str(uuid.uuid4())
        await client.table('agent_runs').insert({
            "id": run_id,
            "thread_id": thread_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "agent_id": agent_id,
            "agent_version_id": agent_config.get('current_version_id'),
            "metadata": {"model_name": effective_model, "user_id": user_id}
        }).execute()
        
        # 5. Register run in Redis for tracking by this instance
        instance_key = f"active_run:{utils.instance_id}:{run_id}"
        await redis.set(instance_key, "running", ex=redis.REDIS_KEY_TTL)

        # 6. Trigger the background task
        request_id = structlog.contextvars.get_contextvars().get('request_id')
        run_agent_background.send(
            agent_run_id=run_id, thread_id=thread_id,
            instance_id=utils.instance_id, model_name=effective_model,
            agent_config=agent_config, request_id=request_id,
        )

        logger.info(f"Successfully started agent run {run_id} in thread {thread_id}")
        return {"thread_id": thread_id, "agent_run_id": run_id, "status": "running"}

    except Exception as e:
        logger.error(f"Error starting agent run in thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start agent run.")

@router.post("/runs/{run_id}/stop", summary="Stop Agent Run", operation_id="stop_agent_run")
async def stop_agent_run(
    run_id: str,
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    """Stops a running agent, verifying ownership via the run's thread."""
    logger.debug(f"Received request to stop agent run: {run_id}")
    await _get_agent_run_with_access_check(run_id, user_id) # Verifies ownership

    await utils.stop_agent_run_with_helpers(run_id)
    return {"status": "stopped"}


@router.get("/runs/{run_id}", summary="Get Agent Run", operation_id="get_agent_run")
async def get_agent_run(
    run_id: str,
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    """Gets the status and details of a specific agent run."""
    logger.debug(f"Fetching agent run details: {run_id}")
    agent_run_data = await _get_agent_run_with_access_check(run_id, user_id)
    return agent_run_data


@router.get("/threads/{thread_id}/runs", summary="List Thread Agent Runs", operation_id="list_thread_agent_runs")
async def get_agent_runs_for_thread(
    thread: dict = Depends(require_thread_ownership)
):
    """Gets all agent runs associated with a specific thread."""
    thread_id = thread['thread_id']
    logger.debug(f"Fetching agent runs for thread: {thread_id}")
    client = await utils.db.client
    
    result = await client.table('agent_runs').select('*').eq("thread_id", thread_id).order('created_at', desc=True).execute()
    return {"agent_runs": result.data}


@router.get("/runs/{run_id}/stream", summary="Stream Agent Run", operation_id="stream_agent_run")
async def stream_agent_run(
    run_id: str,
    token: Optional[str] = None, 
    request: Request = None
):
    """Streams the real-time output of an agent run."""
    user_id = await get_optional_user_id_from_jwt(request) # Supports unauthenticated stream for now
    if not user_id:
        # In a real app, you might want to decode a temporary token here
        logger.warning(f"Unauthenticated user attempting to stream run {run_id}")

    await _get_agent_run_with_access_check(run_id, user_id)
    
    response_list_key = f"agent_run:{run_id}:responses"
    control_channel = f"agent_run:{run_id}:control"

    async def stream_generator():
        logger.debug(f"Streaming responses for run {run_id}")
        pubsub, listener_task, queue = None, None, asyncio.Queue()

        try:
            # 1. Yield existing messages from the Redis list
            initial_responses = await redis.lrange(response_list_key, 0, -1)
            for response in initial_responses:
                yield f"data: {response}\n\n"
            
            # 2. Check if the run is already finished
            run_status = await redis.get(f"agent_run:{run_id}:status")
            if run_status and run_status.decode() in ['completed', 'failed', 'stopped']:
                logger.debug(f"Run {run_id} already finished. Ending stream.")
                yield f"data: {json.dumps({'type': 'status', 'status': run_status.decode()})}\n\n"
                return

            # 3. Set up a listener for new messages
            pubsub = await redis.create_pubsub()
            await pubsub.subscribe(control_channel)

            async def message_listener():
                async for message in pubsub.listen():
                    if message and message["type"] == "message":
                        await queue.put(message["data"].decode('utf-8'))
                        if message["data"].decode('utf-8') in ["STOP", "END_STREAM", "ERROR"]:
                            break
            
            listener_task = asyncio.create_task(message_listener())

            # 4. Main loop to yield new messages from the queue
            while True:
                data = await queue.get()
                if data in ["STOP", "END_STREAM", "ERROR"]:
                    logger.debug(f"Received control signal '{data}' for run {run_id}. Closing stream.")
                    yield f"data: {json.dumps({'type': 'status', 'status': data})}\n\n"
                    break
                
                # A 'new' signal means we should check the list again
                new_responses = await redis.lrange(response_list_key, len(initial_responses), -1)
                for response in new_responses:
                    yield f"data: {response}\n\n"
                initial_responses.extend(new_responses)

        except asyncio.CancelledError:
            logger.info(f"Stream for run {run_id} was cancelled by the client.")
        except Exception as e:
            logger.error(f"Error during stream for run {run_id}: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'status', 'status': 'error', 'message': 'Stream failed'})}\n\n"
        finally:
            if listener_task: listener_task.cancel()
            if pubsub: await pubsub.close()
            logger.debug(f"Stream cleanup complete for run {run_id}")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
