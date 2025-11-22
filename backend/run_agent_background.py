"""
This background worker module, powered by Dramatiq, is the heart of agent execution.

It has been refactored to include a critical 'Compatibility Layer' to ensure that
the modern, streamlined backend can communicate with the legacy frontend without
requiring any changes on the client-side.
"""

dotenv.load_dotenv(".env")

import asyncio
import json
import traceback
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import dramatiq
import sentry_sdk
from dramatiq.brokers.redis import RedisBroker

from core.run import run_agent
from core.services import redis
from core.services.langfuse import langfuse
from core.services.supabase import DBConnection
from core.utils.logger import logger, structlog

# --- Dramatiq Broker Setup ---

redis_host = os.getenv('REDIS_HOST', 'localhost')
redis_port = int(os.getenv('REDIS_PORT', 6379))
redis_broker = RedisBroker(host=redis_host, port=redis_port, middleware=[dramatiq.middleware.AsyncIO()])
dramatiq.set_broker(redis_broker)

# --- Module Globals ---

db = DBConnection()

# --- Compatibility Layer ---

def _transform_tool_output_for_frontend(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms tool output from the new, structured format to the old, string-based
    format expected by the frontend. This is the core of the compatibility layer.
    """
    if response.get("type") != "tool_output" or not isinstance(response.get("output"), dict):
        return response # Not a tool output that needs transformation

    tool_name = response.get("tool_name", "")
    original_output = response["output"]

    # Only transform outputs for specific tools that the frontend has custom components for.
    if tool_name in ["browser_tool", "web_search_tool"]:
        logger.debug(f"Transforming output for '{tool_name}' for frontend compatibility.")
        # Create a copy to avoid modifying the original dictionary
        transformed_output = original_output.copy()
        
        # 1. Rename 'screenshot' to 'image_url' for browser_tool
        if 'screenshot' in transformed_output:
            transformed_output['image_url'] = transformed_output.pop('screenshot')

        # 2. Convert the entire output dictionary to a JSON string
        response["output"] = json.dumps(transformed_output)
        logger.debug(f"Transformed output: {response['output'][:200]}...")

    return response

# --- Dramatiq Actor ---

@dramatiq.actor
async def run_agent_background(
    agent_run_id: str,
    thread_id: str,
    model_name: str,
    agent_config: Dict[str, Any],
    request_id: Optional[str] = None
):
    """
    The main background task to run an agent, process its responses, and handle state.
    """
    structlog.contextvars.bind_contextvars(agent_run_id=agent_run_id, thread_id=thread_id, request_id=request_id)
    
    await db.initialize()
    agent_gen = run_agent(thread_id=thread_id, model_name=model_name, agent_config=agent_config)

    response_list_key = f"agent_run:{agent_run_id}:responses"
    control_channel = f"agent_run:{agent_run_id}:control"
    final_status = "running"

    try:
        async for response in agent_gen:
            # Apply the compatibility layer transformation
            transformed_response = _transform_tool_output_for_frontend(response)
            response_json = json.dumps(transformed_response)

            # Store and publish the (potentially transformed) response
            await redis.rpush(response_list_key, response_json)
            await redis.publish(control_channel, "NEW")

            # Check for run completion
            if response.get("type") == "status" and response.get("status") in ["completed", "failed", "stopped"]:
                final_status = response["status"]
                logger.info(f"Agent run {agent_run_id} finished with status: {final_status}")
                break
        
        if final_status == "running":
            final_status = "completed"
            completion_message = json.dumps({"type": "status", "status": "completed"})
            await redis.rpush(response_list_key, completion_message)
            await redis.publish(control_channel, "NEW")

    except Exception as e:
        final_status = "failed"
        error_message = f"An error occurred during agent execution: {e}"
        logger.error(error_message, exc_info=True)
        error_response = json.dumps({"type": "status", "status": "failed", "message": error_message})
        await redis.rpush(response_list_key, error_response)
        await redis.publish(control_channel, "NEW")
    
    finally:
        # Update the final status in the database
        client = await db.client
        await client.table('agent_runs').update({
            'status': final_status,
            'completed_at': datetime.now(timezone.utc).isoformat()
        }).eq('id', agent_run_id).execute()

        # Signal end of stream to any listeners
        await redis.publish(control_channel, "STOP")
        logger.info(f"Agent run {agent_run_id} concluded with final status: {final_status}")
