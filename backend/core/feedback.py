"""
This module handles user feedback on agent interactions.

It has been refactored to remove the final dependency on the legacy core_utils.py
file by directly using the DBConnection class for database access.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel

# Core dependencies
from core.utils.auth_utils import verify_and_get_user_id_from_jwt, verify_and_authorize_thread_access
from core.utils.logger import logger
from core.services.supabase import DBConnection

router = APIRouter(tags=["feedback"])

# --- Pydantic Models ---

class FeedbackRequest(BaseModel):
    rating: float
    feedback_text: Optional[str] = None
    help_improve: bool = True
    thread_id: Optional[str] = None
    message_id: Optional[str] = None

class FeedbackResponse(BaseModel):
    feedback_id: str
    rating: float
    help_improve: bool
    created_at: str
    updated_at: str
    feedback_text: Optional[str] = None
    thread_id: Optional[str] = None
    message_id: Optional[str] = None

# --- Helper Functions ---

async def _get_db_client():
    """Dependency to get a Supabase client."""
    db = DBConnection()
    return await db.client

# --- API Endpoints ---

@router.post("/feedback", response_model=FeedbackResponse, summary="Submit Feedback", operation_id="submit_feedback")
async def submit_feedback(
    feedback_data: FeedbackRequest,
    user_id: str = Depends(verify_and_get_user_id_from_jwt),
    client = Depends(_get_db_client)
):
    """Submits or updates feedback for a given thread/message."""
    logger.debug(f"User {user_id} submitting feedback for thread {feedback_data.thread_id}")

    # Upsert logic: Update if feedback for this message exists, otherwise create new.
    try:
        if feedback_data.thread_id:
            await verify_and_authorize_thread_access(client, feedback_data.thread_id, user_id)

        feedback_payload = feedback_data.model_dump()
        feedback_payload['account_id'] = user_id
        feedback_payload['updated_at'] = datetime.now(timezone.utc).isoformat()

        # Use Supabase's upsert feature
        result = await client.table('feedback').upsert(feedback_payload).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to save feedback.")

        logger.info(f"Successfully saved feedback {result.data[0]['feedback_id']}")
        return result.data[0]

    except HTTPException as e:
        logger.warning(f"Auth or validation error submitting feedback: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred while saving feedback.")

@router.get("/feedback", response_model=List[FeedbackResponse], summary="Get Feedback", operation_id="get_feedback")
async def get_feedback(
    thread_id: Optional[str] = None,
    message_id: Optional[str] = None,
    user_id: str = Depends(verify_and_get_user_id_from_jwt),
    client = Depends(_get_db_client)
):
    """Retrieves a user's own feedback, with optional filters."""
    logger.debug(f"User {user_id} fetching feedback.")
    try:
        query = client.table('feedback').select('*').eq('account_id', user_id)
        if thread_id:
            await verify_and_authorize_thread_access(client, thread_id, user_id)
            query = query.eq('thread_id', thread_id)
        if message_id:
            query = query.eq('message_id', message_id)

        result = await query.order('created_at', desc=True).execute()
        return result.data or []

    except HTTPException as e:
        logger.warning(f"Auth error getting feedback: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error getting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve feedback.")
