"""
Simplified API for managing conversation threads.

A thread is a simple container for a sequence of messages between a user and an agent.
This module removes the legacy concepts of 'projects' and 'sandboxes' and uses a
clean, ownership-based authorization model.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query, Body, Request

# Core dependencies
from core.utils.auth_utils import (
    verify_and_get_user_id_from_jwt,
    get_optional_user_id_from_jwt,
    require_thread_ownership
)
from core.utils.logger import logger
from core.guest_session import guest_session_service
from . import core_utils as utils

# Local API models
from .api_models import CreateThreadResponse, MessageCreateRequest, ThreadResponse, MessageResponse

router = APIRouter(tags=["threads"])

@router.post("/threads", response_model=CreateThreadResponse, summary="Create Thread", operation_id="create_thread")
async def create_thread(
    metadata: Optional[dict] = Body(None),
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    """Creates a new, empty conversation thread for the authenticated user."""
    logger.debug(f"Creating new thread for user: {user_id}")
    client = await utils.db.client
    
    try:
        thread_id = str(uuid.uuid4())
        thread_data = {
            "thread_id": thread_id,
            "account_id": user_id, # Using account_id as user_id for ownership
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        insert_result = await client.table('threads').insert(thread_data).execute()
        
        if not insert_result.data:
            raise HTTPException(status_code=500, detail="Failed to create the thread in the database.")

        logger.info(f"Successfully created thread {thread_id} for user {user_id}")
        return {"thread_id": thread_id}

    except Exception as e:
        logger.error(f"Error creating thread for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred while creating the thread.")

@router.get("/threads", response_model=List[ThreadResponse], summary="List User Threads", operation_id="list_user_threads")
async def get_user_threads(
    request: Request,
    user_id: Optional[str] = Depends(get_optional_user_id_from_jwt),
    page: int = Query(1, ge=1), 
    limit: int = Query(100, ge=1, le=1000)
):
    """Lists all threads owned by the user, with pagination."""
    if not user_id:
        guest_session_id = request.headers.get('X-Guest-Session')
        if not guest_session_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        session = await guest_session_service.get_session(guest_session_id)
        if not session:
             raise HTTPException(status_code=401, detail="Invalid guest session")
        user_id = session['session_id']

    logger.debug(f"Fetching threads for user: {user_id} (page={page}, limit={limit})")
    client = await utils.db.client
    try:
        offset = (page - 1) * limit
        threads_result = await client.table('threads')\
            .select('*')\
            .eq('account_id', user_id)\
            .order('created_at', desc=True)\
            .range(offset, offset + limit - 1)\
            .execute()
        
        return [ThreadResponse(**thread) for thread in threads_result.data]

    except Exception as e:
        logger.error(f"Error fetching threads for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch threads.")

@router.get("/threads/{thread_id}", response_model=ThreadResponse, summary="Get Thread", operation_id="get_thread")
async def get_thread(thread: dict = Depends(require_thread_ownership)):
    """Retrieves a specific thread by its ID, verifying ownership."""
    logger.debug(f"Successfully authorized and fetched thread: {thread['thread_id']}")
    return ThreadResponse(**thread)

@router.delete("/threads/{thread_id}", summary="Delete Thread", operation_id="delete_thread")
async def delete_thread(thread: dict = Depends(require_thread_ownership)):
    """Deletes a thread and all its associated messages and agent runs."""
    thread_id = thread['thread_id']
    logger.debug(f"Deleting thread: {thread_id}")
    client = await utils.db.client
    
    try:
        # Batch delete associated data
        await client.table('agent_runs').delete().eq('thread_id', thread_id).execute()
        await client.table('messages').delete().eq('thread_id', thread_id).execute()
        
        # Delete the thread itself
        thread_delete_result = await client.table('threads').delete().eq('thread_id', thread_id).execute()
        
        if not thread_delete_result.data:
            # This can happen in a race condition, it's not a critical error.
            logger.warning(f"Attempted to delete thread {thread_id}, but it was already gone.")
            raise HTTPException(status_code=404, detail="Thread not found, may have already been deleted.")
        
        logger.info(f"Successfully deleted thread {thread_id} and all associated data.")
        return {"message": "Thread deleted successfully", "thread_id": thread_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred during thread deletion.")


# --- Message-related endpoints ---

@router.get("/threads/{thread_id}/messages", response_model=List[MessageResponse], summary="Get Thread Messages", operation_id="get_thread_messages")
async def get_thread_messages(
    thread: dict = Depends(require_thread_ownership),
    order: str = Query("asc", description="Order by created_at: 'asc' or 'desc'"),
    limit: int = Query(1000, ge=1, le=2000)
):
    """Retrieves all messages within a specific thread, verifying ownership."""
    thread_id = thread['thread_id']
    logger.debug(f"Fetching messages for thread: {thread_id}, order={order}")
    client = await utils.db.client
    try:
        messages_result = await client.table('messages')\
            .select('*')\
            .eq('thread_id', thread_id)\
            .order('created_at', desc=(order == "desc"))\
            .limit(limit)\
            .execute()

        return [MessageResponse(**msg) for msg in messages_result.data]

    except Exception as e:
        logger.error(f"Error fetching messages for thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch messages.")

@router.post("/threads/{thread_id}/messages", response_model=MessageResponse, summary="Create Thread Message", operation_id="create_thread_message")
async def create_message(
    message_data: MessageCreateRequest,
    thread: dict = Depends(require_thread_ownership)
):
    """Adds a new message to a thread, verifying ownership."""
    thread_id = thread['thread_id']
    logger.debug(f"Creating message in thread: {thread_id}")
    client = await utils.db.client
    
    try:
        message_id = str(uuid.uuid4())
        content_payload = {
            "role": message_data.type.value,
            "content": message_data.content
        }
        
        insert_data = {
            "message_id": message_id,
            "thread_id": thread_id,
            "type": message_data.type.value,
            "is_llm_message": message_data.is_llm_message,
            "content": content_payload,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        message_result = await client.table('messages').insert(insert_data).execute()
        if not message_result.data:
            raise HTTPException(status_code=500, detail="Failed to create message.")
        
        logger.info(f"Created message {message_id} in thread {thread_id}")
        return MessageResponse(**message_result.data[0])
        
    except Exception as e:
        logger.error(f"Error creating message in thread {thread_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create message.")
