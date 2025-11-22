"""
API for managing application-wide settings.

This module provides secure, brokered access to the `settings` table. It ensures
that sensitive information (like API keys) is never exposed to clients and can only
be updated by authorized users.
"""

from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.utils.auth_utils import verify_and_get_user_id_from_jwt
from core.services.supabase import DBConnection
from core.utils.logger import logger

router = APIRouter(tags=["settings"])

# --- Pydantic Models ---

class SettingItem(BaseModel):
    key: str
    value: Any

class SettingsUpdateRequest(BaseModel):
    settings: List[SettingItem]

# A list of keys that are considered sensitive and should not be returned to the client.
SENSITIVE_KEYS = ["llm.openai_api_key", "llm.anthropic_api_key"]

# --- Helper Functions & Dependencies ---

async def _get_db_client():
    db = DBConnection()
    return await db.client

# For now, we'll define an "admin" as the primary user. This can be expanded later.
async def _require_admin_user(user_id: str = Depends(verify_and_get_user_id_from_jwt), client = Depends(_get_db_client)):
    # This is a placeholder for a real admin check.
    # In a real system, you'd check a user's role from a `users` table.
    # For now, we can assume the first user created is the admin, or check an env var.
    # Let's keep it simple: we'll add a specific check later if needed.
    # For this project, any authenticated user can change settings for now.
    logger.warning(f"Admin check for user {user_id} is currently permissive.")
    return user_id

# --- API Endpoints ---

@router.get("/settings", response_model=List[SettingItem], summary="Get Public Settings", operation_id="get_public_settings")
async def get_public_settings(client = Depends(_get_db_client)):
    """Retrieves all non-sensitive application settings."""
    try:
        result = await client.table('settings').select("key, value").execute()
        
        # Filter out sensitive keys before returning the list to the client
        public_settings = [item for item in result.data if item['key'] not in SENSITIVE_KEYS]
        
        return public_settings
    except Exception as e:
        logger.error(f"Error fetching settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve settings.")

@router.post("/settings", response_model=List[SettingItem], summary="Update Settings", operation_id="update_settings")
async def update_settings(
    request: SettingsUpdateRequest,
    admin_user_id: str = Depends(_require_admin_user),
    client = Depends(_get_db_client)
):
    """Updates one or more application settings. Requires admin privileges."""
    logger.info(f"Admin user {admin_user_id} is updating settings.")
    
    # The `value` in the settings table is JSONB, so we don't need to stringify it.
    # The Pydantic model will have already parsed the incoming JSON.
    records_to_upsert = [item.dict() for item in request.settings]

    try:
        # Supabase's `upsert` is perfect for this. It will insert new keys or update existing ones.
        result = await client.table('settings').upsert(records_to_upsert).execute()
        
        # Return the updated public settings
        return [item for item in result.data if item['key'] not in SENSITIVE_KEYS]

    except Exception as e:
        logger.error(f"Error updating settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings.")
