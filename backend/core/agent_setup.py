"""
This module handles the creation of a new agent from a natural language description.

It has been refactored to remove legacy limit checks and to use a more streamlined
and consistent version activation process.
"""

import asyncio
import json
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# Core dependencies
from core.utils.auth_utils import verify_and_get_user_id_from_jwt
from core.utils.logger import logger
from core.services.llm import make_llm_api_call
from core.services.supabase import DBConnection
from core.versioning.version_service import get_version_service, VersionService
from core.ai_models import model_manager
from core.config_helper import _get_default_agentpress_tools, ensure_core_tools_enabled

router = APIRouter(tags=["agent-setup"])

# --- Pydantic Models ---

class AgentSetupFromChatRequest(BaseModel):
    description: str

class AgentSetupFromChatResponse(BaseModel):
    agent_id: str
    name: str
    system_prompt: str
    icon_name: str
    icon_color: str
    icon_background: str

# --- Helper Functions ---

async def _generate_agent_details_from_llm(description: str) -> Dict[str, str]:
    """Generates agent name, prompt, and icon details using an LLM call."""
    # This function can be expanded to generate more details or use a more complex prompt
    system_prompt_for_gen = (
        "You are an expert at creating configurations for AI agents. "
        "Based on the user's description, generate a concise name (3-4 words), a detailed system prompt, "
        "and suggest a relevant icon name (from Material Design Icons) with appropriate colors.\n\n"
        'Respond with JSON: {"name": "...", "system_prompt": "...", "icon_name": "...", "icon_color": "#...", "icon_background": "..."}'
    )
    user_message = f'Generate the configuration for an agent that: "{description}"'

    try:
        model_name = "openai/gpt-4-turbo-2024-04-09" # A capable model for this task
        response = await make_llm_api_call(
            messages=[{"role": "system", "content": system_prompt_for_gen}, {"role": "user", "content": user_message}],
            model_name=model_name,
            max_tokens=1024,
            temperature=0.5,
            response_format={"type": "json_object"}
        )
        content = response['choices'][0]['message']['content'].strip()
        return json.loads(content)
    except Exception as e:
        logger.error(f"LLM call for agent generation failed: {e}. Falling back to defaults.", exc_info=True)
        return {
            "name": "Custom Agent",
            "system_prompt": description, # Use raw description as fallback
            "icon_name": "smart_toy",
            "icon_color": "#FFFFFF",
            "icon_background": "#4A90E2"
        }

# --- API Endpoint ---

@router.post("/agents/setup/chat", response_model=AgentSetupFromChatResponse, summary="Setup Agent from Chat", operation_id="setup_agent_from_chat")
async def setup_agent_from_chat(
    request: AgentSetupFromChatRequest,
    user_id: str = Depends(verify_and_get_user_id_from_jwt),
    version_service: VersionService = Depends(get_version_service)
):
    """
    Creates and configures a new agent based on a natural language description.
    This process involves: 
    1. Using an LLM to generate a name, system prompt, and icon.
    2. Creating the agent record in the database.
    3. Creating and activating the initial version of the agent.
    """
    if not request.description.strip():
        raise HTTPException(status_code=400, detail="Description cannot be empty.")

    logger.info(f"Setting up new agent from chat for user {user_id}")

    try:
        # 1. Generate agent details using an LLM
        agent_details = await _generate_agent_details_from_llm(request.description)
        
        # 2. Create the agent record
        db = DBConnection()
        client = await db.client
        agent_insert_data = {
            "account_id": user_id,
            "name": agent_details['name'],
            "icon_name": agent_details['icon_name'],
            "icon_color": agent_details['icon_color'],
            "icon_background": agent_details['icon_background'],
        }
        new_agent_res = await client.table('agents').insert(agent_insert_data).execute()
        agent = new_agent_res.data[0]
        agent_id = agent['agent_id']

        # 3. Create and activate the initial version
        try:
            default_tools = ensure_core_tools_enabled(_get_default_agentpress_tools())
            default_model = await model_manager.get_default_model()

            new_version = await version_service.create_version(
                agent_id=agent_id, user_id=user_id,
                system_prompt=agent_details['system_prompt'],
                model=default_model, agentpress_tools=default_tools,
                change_description="Initial version from chat setup"
            )
            await version_service.activate_version(agent_id, new_version.version_id, user_id)

        except Exception as version_error:
            logger.error(f"Failed to create initial version for agent {agent_id}. Rolling back agent creation.", exc_info=True)
            await client.table('agents').delete().eq('agent_id', agent_id).execute()
            raise HTTPException(status_code=500, detail=f"Failed to configure agent: {version_error}")

        logger.info(f"Successfully created agent '{agent_details['name']}' (ID: {agent_id}) for user {user_id}")
        return AgentSetupFromChatResponse(
            agent_id=agent_id,
            **agent_details
        )

    except Exception as e:
        logger.error(f"Full process failed for agent setup from chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred while setting up the agent.")


