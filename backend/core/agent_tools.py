"""
This module provides endpoints for managing the tools configured for an agent.

It has been refactored to use a simplified, ownership-based authorization model
and to remove legacy concepts like limit checks and public resources.
"""

from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends

# Core dependencies
from core.utils.auth_utils import require_agent_ownership
from core.utils.logger import logger
from core.versioning.version_service import get_version_service, VersionService, AgentVersion

# Local dependencies
from .api_models import AgentToolsResponse, AgentToolsUpdateRequest

router = APIRouter(tags=["agent-tools"])

async def _get_active_version_for_agent(agent: dict, version_service: VersionService) -> AgentVersion:
    """Helper to retrieve the active version for an authorized agent."""
    version_id = agent.get('current_version_id')
    if not version_id:
        # This can happen for newly created agents before the first version is fully set.
        # Return a default/empty version object.
        logger.warning(f"Agent {agent['agent_id']} has no active version. Using default empty config.")
        return AgentVersion(
            version_id="", agent_id=agent['agent_id'], version_number=0, version_name="",
            system_prompt="", created_by=agent['account_id']
        )
    try:
        return await version_service.get_version_by_id(version_id, agent['account_id'])
    except Exception as e:
        logger.error(f"Error fetching active version {version_id} for agent {agent['agent_id']}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load agent's current configuration.")

@router.get("/agents/{agent_id}/tools", response_model=AgentToolsResponse, summary="Get Agent Tools", operation_id="get_agent_tools")
async def get_agent_tools(
    agent: dict = Depends(require_agent_ownership),
    version_service: VersionService = Depends(get_version_service)
):
    """Retrieves the complete tool configuration for the agent's active version."""
    logger.debug(f"Getting tools for agent {agent['agent_id']}")
    
    active_version = await _get_active_version_for_agent(agent, version_service)
    
    return AgentToolsResponse(
        agentpress_tools=active_version.agentpress_tools,
        configured_mcps=active_version.configured_mcps,
        custom_mcps=active_version.custom_mcps
    )

@router.put("/agents/{agent_id}/tools", summary="Update Agent Tools", operation_id="update_agent_tools")
async def update_agent_tools(
    update_request: AgentToolsUpdateRequest,
    agent: dict = Depends(require_agent_ownership),
    version_service: VersionService = Depends(get_version_service)
):
    """
    Updates the agent's tools by creating a new, activated version.
    This replaces the entire tool configuration for the agent.
    """
    agent_id = agent['agent_id']
    user_id = agent['account_id']
    logger.debug(f"Updating tools for agent {agent_id} by user {user_id}")

    try:
        # Get the current active version to use as a base for non-tool-related fields
        active_version = await _get_active_version_for_agent(agent, version_service)

        # Create a new version with the updated tools
        new_version = await version_service.create_version(
            agent_id=agent_id,
            user_id=user_id,
            # Carry over existing non-tool fields
            system_prompt=active_version.system_prompt,
            model=active_version.model,
            # Replace tool fields with the new data from the request
            agentpress_tools=update_request.agentpress_tools,
            configured_mcps=update_request.configured_mcps,
            custom_mcps=update_request.custom_mcps,
            change_description="Updated agent tools"
        )

        # Activate the new version to make the changes live
        await version_service.activate_version(agent_id, new_version.version_id, user_id)

        logger.info(f"Successfully updated tools for agent {agent_id} by creating and activating new version {new_version.version_id}")
        return {"success": True, "new_version_id": new_version.version_id}

    except Exception as e:
        logger.error(f"Error updating tools for agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update agent tools.")
