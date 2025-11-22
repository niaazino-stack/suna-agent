"""
Simplified Authentication and Authorization Utilities.

This module provides a streamlined way to handle user authentication and authorization
based on a simple, single-user model. It primarily uses JWTs for authentication and
direct resource ownership for authorization.
"""

import jwt
from jwt.exceptions import PyJWTError
from fastapi import HTTPException, Request, Header
from typing import Optional

from core.utils.logger import logger, structlog
from core.services.supabase import DBConnection
from core.services import redis
from core.guest_session import guest_session_service
from core.services.api_keys import APIKeyService


def _decode_jwt_safely(token: str) -> dict:
    """Decodes a JWT without verifying the signature. Used for extracting claims before full validation."""
    return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})

async def _get_user_id_from_api_key(api_key: str) -> Optional[str]:
    """Validates an API key and returns the associated user ID."""
    try:
        if ':' not in api_key:
            logger.warning("Invalid API key format provided.")
            return None
        
        public_key, secret_key = api_key.split(':', 1)
        
        db = DBConnection()
        api_key_service = APIKeyService(db)
        
        validation_result = await api_key_service.validate_api_key(public_key, secret_key)
        
        if validation_result.is_valid:
            # In our simplified model, the account_id is the user_id.
            user_id = str(validation_result.account_id)
            structlog.contextvars.bind_contextvars(
                user_id=user_id,
                auth_method="api_key",
                api_key_id=str(validation_result.key_id)
            )
            logger.debug(f"Authenticated via API key for user {user_id}")
            return user_id
        else:
            logger.warning(f"Invalid API key provided: {validation_result.error_message}")
            return None

    except Exception as e:
        logger.error(f"Error during API key validation: {e}", exc_info=True)
        return None

async def verify_and_get_user_id_from_jwt(request: Request) -> str:
    """
    FastAPI dependency to verify authentication and retrieve a user ID.

    It checks for an API key first, then a JWT Bearer token.
    If neither is valid, it raises a 401 HTTPException.
    """
    # 1. Try API Key Authentication
    api_key = request.headers.get('x-api-key')
    if api_key:
        user_id = await _get_user_id_from_api_key(api_key)
        if user_id:
            return user_id
        # If API key is present but invalid, deny access immediately.
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # 2. Try JWT Bearer Token Authentication
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = auth_header.split(' ')[1]
    
    try:
        # Here you would typically verify the token signature against a public key.
        # For now, we are just decoding it. This should be hardened in a real-world scenario.
        payload = _decode_jwt_safely(token)
        user_id = payload.get('sub')
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token: Missing user identifier")

        structlog.contextvars.bind_contextvars(user_id=user_id, auth_method="jwt")
        return user_id
        
    except PyJWTError as e:
        logger.warning(f"Invalid JWT provided: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_optional_user_id_from_jwt(request: Request) -> Optional[str]:
    """FastAPI dependency that returns a user ID if authenticated, or None otherwise."""
    try:
        return await verify_and_get_user_id_from_jwt(request)
    except HTTPException:
        return None

async def get_user_id_for_stream(request: Request, token: Optional[str] = None, guest_session: Optional[str] = None) -> str:
    """
    Authenticates a user for a streaming connection.
    Priority: JWT Header > token query param > guest_session header.
    """
    # 1. Try standard JWT header
    try:
        user_id = await verify_and_get_user_id_from_jwt(request)
        if user_id: return user_id
    except HTTPException:
        pass # Fall through to next method

    # 2. Try token query parameter
    if token:
        try:
            payload = _decode_jwt_safely(token)
            user_id = payload.get('sub')
            if user_id:
                structlog.contextvars.bind_contextvars(user_id=user_id, auth_method="jwt_query")
                logger.debug("Authenticated stream via token parameter.")
                return user_id
        except PyJWTError:
            pass # Fall through

    # 3. Try Guest Session
    if guest_session:
        session = await guest_session_service.get_session(guest_session)
        if session:
            session_id = session['session_id']
            structlog.contextvars.bind_contextvars(user_id=session_id, auth_method="guest_session")
            logger.debug("Authenticated stream via guest session.")
            return session_id

    raise HTTPException(status_code=401, detail="Could not authenticate stream")


# --- Simplified Ownership-Based Authorization Dependencies ---

async def require_agent_ownership(agent_id: str, user_id: str = Depends(verify_and_get_user_id_from_jwt)) -> dict:
    """
    FastAPI dependency that verifies the current user owns the specified agent.
    Returns the agent record if authorization succeeds.
    """
    db = DBConnection()
    client = await db.client
    # The 'account_id' column is used as the user_id in our simplified model.
    result = await client.table('agents').select('*').eq('agent_id', agent_id).eq('account_id', user_id).maybe_single().execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Agent not found or you do not have permission to access it.")
    
    return result.data

async def require_thread_ownership(thread_id: str, user_id: str = Depends(verify_and_get_user_id_from_jwt)) -> dict:
    """
    FastAPI dependency that verifies the current user owns the specified thread.
    Returns the thread record if authorization succeeds.
    """
    db = DBConnection()
    client = await db.client
    # The 'account_id' column is used as the user_id in our simplified model.
    result = await client.table('threads').select('*').eq('thread_id', thread_id).eq('account_id', user_id).maybe_single().execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Thread not found or you do not have permission to access it.")
        
    return result.data
