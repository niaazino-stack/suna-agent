from typing import Optional
import json

from fastapi import APIRouter, HTTPException, Depends, Query, Request

# Core dependencies
from core.utils.auth_utils import (
    verify_and_get_user_id_from_jwt, 
    get_optional_user_id_from_jwt,
    require_agent_ownership
)
from core.utils.logger import logger
from core.utils.pagination import PaginationParams
from core.utils.core_tools_helper import ensure_core_tools_enabled
from core.ai_models import model_manager
from core.guest_session import guest_session_service

# Local dependencies
from .api_models import (
    AgentUpdateRequest, AgentResponse, AgentsResponse, 
    PaginationInfo, AgentCreateRequest, AgentIconGenerationRequest, AgentIconGenerationResponse
)
from . import core_utils as utils
from .core_utils import (_get_version_service, 
                       generate_agent_icon_and_colors as util_generate_icon)
from .config_helper import _get_default_agentpress_tools
from .agent_service import AgentService, AgentFilters
from .agent_loader import get_agent_loader
from .suna_config import SUNA_CONFIG

router = APIRouter(tags=["agents"])

@router.put("/agents/{agent_id}", response_model=AgentResponse, summary="Update Agent", operation_id="update_agent")
async def update_agent(
    agent_data: AgentUpdateRequest,
    agent: dict = Depends(require_agent_ownership)
):
    agent_id = agent['agent_id']
    user_id = agent['account_id']
    logger.debug(f"Updating agent {agent_id} for user: {user_id}")
    client = await utils.db.client
    
    try:
        # --- Check for restricted edits on default agents ---
        agent_metadata = agent.get('metadata', {})
        is_suna_agent = agent_metadata.get('is_suna_default', False)
        if is_suna_agent:
            logger.warning(f"Update attempt on Suna default agent {agent_id} by user {user_id}")
            restrictions = agent_metadata.get('restrictions', {})
            if (agent_data.name is not None and agent_data.name != agent.get('name') and not restrictions.get('name_editable')):
                raise HTTPException(status_code=403, detail="This agent's name cannot be modified.")
            if (agent_data.system_prompt is not None and not restrictions.get('system_prompt_editable')):
                raise HTTPException(status_code=403, detail="This agent's system prompt cannot be modified.")
            if (agent_data.agentpress_tools is not None and not restrictions.get('tools_editable')):
                raise HTTPException(status_code=403, detail="This agent's tools cannot be modified.")
            if ((agent_data.configured_mcps is not None or agent_data.custom_mcps is not None) and not restrictions.get('mcps_editable')):
                raise HTTPException(status_code=403, detail="This agent's integrations cannot be modified.")

        # --- Versioning Logic ---
        version_service = await _get_version_service()
        try:
            current_version_obj = await version_service.get_version_by_id(agent['current_version_id'], user_id)
            current_version_data = current_version_obj.to_dict()
        except Exception as e:
            logger.warning(f"Failed to get current version for agent {agent_id}, may need to create initial. Error: {e}")
            current_version_data = {}
        
        needs_new_version = False
        for field in ['system_prompt', 'model', 'configured_mcps', 'custom_mcps', 'agentpress_tools']:
            new_value = getattr(agent_data, field, None)
            if new_value is not None and new_value != current_version_data.get(field):
                logger.debug(f"Change detected in '{field}' for agent {agent_id}. New version required.")
                needs_new_version = True
                break

        update_data = {}
        if agent_data.name is not None: update_data["name"] = agent_data.name
        if agent_data.icon_name is not None: update_data["icon_name"] = agent_data.icon_name
        if agent_data.icon_color is not None: update_data["icon_color"] = agent_data.icon_color
        if agent_data.icon_background is not None: update_data["icon_background"] = agent_data.icon_background
        
        if agent_data.is_default:
            update_data["is_default"] = True
            await client.table('agents').update({"is_default": False}).eq("account_id", user_id).neq("agent_id", agent_id).execute()
        elif agent_data.is_default == False:
             update_data["is_default"] = False

        if needs_new_version:
            logger.debug(f"Creating new version for agent {agent_id} due to detected changes.")
            try:
                new_version = await version_service.create_version(
                    agent_id=agent_id, user_id=user_id,
                    system_prompt=agent_data.system_prompt if agent_data.system_prompt is not None else current_version_data.get('system_prompt'),
                    model=agent_data.model if agent_data.model is not None else current_version_data.get('model'),
                    configured_mcps=agent_data.configured_mcps if agent_data.configured_mcps is not None else current_version_data.get('configured_mcps'),
                    custom_mcps=agent_data.custom_mcps if agent_data.custom_mcps is not None else current_version_data.get('custom_mcps'),
                    agentpress_tools=ensure_core_tools_enabled(agent_data.agentpress_tools) if agent_data.agentpress_tools is not None else current_version_data.get('agentpress_tools'),
                    change_description="Configuration updated"
                )
                update_data['current_version_id'] = new_version.version_id
                update_data['version_count'] = new_version.version_number
                logger.info(f"Created new version {new_version.version_name} for agent {agent_id}")
            except Exception as e:
                logger.error(f"Error creating new agent version for {agent_id}: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Failed to create new agent version.")
        
        if update_data:
            logger.debug(f"Updating agent {agent_id} in database with data: {update_data}")
            await client.table('agents').update(update_data).eq("agent_id", agent_id).execute()

        loader = await get_agent_loader()
        agent_data_obj = await loader.load_agent(agent_id, user_id, load_config=True)
        return agent_data_obj.to_pydantic_model()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unhandled error updating agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred while updating the agent.")

@router.delete("/agents/{agent_id}", summary="Delete Agent", operation_id="delete_agent")
async def delete_agent(agent_id: str, agent: dict = Depends(require_agent_ownership)):
    user_id = agent['account_id']
    logger.debug(f"Deleting agent: {agent_id} for user: {user_id}")
    
    try:
        if agent['is_default']:
            raise HTTPException(status_code=400, detail="Cannot delete the default agent.")
        if agent.get('metadata', {}).get('is_suna_default', False):
            raise HTTPException(status_code=400, detail="Cannot delete this protected system agent.")

        # --- Cleanup related triggers ---
        try:
            from core.triggers.trigger_service import get_trigger_service
            trigger_service = get_trigger_service(utils.db)
            await trigger_service.delete_triggers_for_agent(agent_id)
            logger.info(f"Cleaned up triggers for agent {agent_id}")
        except Exception as e:
            logger.warning(f"Failed to clean up all triggers for agent {agent_id}: {e}", exc_info=True)

        # --- Delete the agent ---
        client = await utils.db.client
        delete_result = await client.table('agents').delete().eq('agent_id', agent_id).execute()
        if not delete_result.data:
            logger.warning(f"Deletion of agent {agent_id} affected no rows, it might have been already deleted.")
            raise HTTPException(status_code=404, detail="Unable to delete agent, it may have been already deleted.")
        
        logger.info(f"Successfully deleted agent: {agent_id}")
        return {"message": "Agent deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during agent deletion for {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred during agent deletion.")

@router.get("/agents", response_model=AgentsResponse, summary="List Agents", operation_id="list_agents")
async def get_agents(
    request: Request,
    user_id: Optional[str] = Depends(get_optional_user_id_from_jwt),
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None, sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc", has_default: Optional[bool] = None,
    has_mcp_tools: Optional[bool] = None, has_agentpress_tools: Optional[bool] = None,
    tools: Optional[str] = None, content_type: Optional[str] = None
):
    try:
        if not user_id:
            guest_session_id = request.headers.get('X-Guest-Session')
            if not guest_session_id:
                raise HTTPException(status_code=401, detail="Authentication required")
            session = await guest_session_service.get_or_create_session(request, guest_session_id)
            user_id = session['session_id']
            logger.info(f"Guest user {user_id} fetching agents.")

        filters = AgentFilters(
            search=search, has_default=has_default, has_mcp_tools=has_mcp_tools,
            has_agentpress_tools=has_agentpress_tools, content_type=content_type,
            tools=[tool.strip() for tool in tools.split(',') if tool.strip()] if tools else [],
            sort_by=sort_by, sort_order=sort_order
        )
        
        agent_service = AgentService(await utils.db.client)
        paginated_result = await agent_service.get_agents_paginated(
            user_id=user_id, 
            pagination_params=PaginationParams(page=page, page_size=limit),
            filters=filters
        )
        
        return AgentsResponse(
            agents=[AgentResponse(**agent) for agent in paginated_result.data],
            pagination=PaginationInfo(**paginated_result.pagination.dict())
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agents for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch agents.")

@router.get("/agents/{agent_id}", response_model=AgentResponse, summary="Get Agent", operation_id="get_agent")
async def get_agent(agent: dict = Depends(require_agent_ownership)):
    """Get a single agent with its full configuration."""
    agent_id = agent['agent_id']
    user_id = agent['account_id']
    logger.debug(f"Fetching agent {agent_id} for user: {user_id}")
    try:
        loader = await get_agent_loader()
        agent_data = await loader.load_agent(agent_id, user_id, load_config=True)
        return agent_data.to_pydantic_model()
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error fetching agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch agent.")

@router.post("/agents", response_model=AgentResponse, summary="Create Agent", operation_id="create_agent")
async def create_agent(
    agent_data: AgentCreateRequest,
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    logger.debug(f"Creating new agent '{agent_data.name}' for user: {user_id}")
    client = await utils.db.client
    
    try:
        if agent_data.is_default:
            await client.table('agents').update({"is_default": False}).eq("account_id", user_id).execute()
        
        insert_data = {
            "account_id": user_id,
            "name": agent_data.name,
            "icon_name": agent_data.icon_name or "bot",
            "icon_color": agent_data.icon_color or "#000000",
            "icon_background": agent_data.icon_background or "#F3F4F6",
            "is_default": agent_data.is_default or False,
            "version_count": 1
        }
        new_agent_result = await client.table('agents').insert(insert_data).execute()
        if not new_agent_result.data:
            raise HTTPException(status_code=500, detail="Failed to create agent record.")
        agent = new_agent_result.data[0]
        
        try:
            version_service = await _get_version_service()
            default_model = await model_manager.get_default_model_for_user(client, user_id)
            
            version = await version_service.create_version(
                agent_id=agent['agent_id'], user_id=user_id,
                system_prompt=SUNA_CONFIG["system_prompt"], # Default prompt
                model=default_model,
                configured_mcps=agent_data.configured_mcps or [],
                custom_mcps=agent_data.custom_mcps or [],
                agentpress_tools=ensure_core_tools_enabled(_get_default_agentpress_tools()),
                version_name="v1", change_description="Initial version"
            )
            await client.table('agents').update({'current_version_id': version.version_id}).eq('agent_id', agent['agent_id']).execute()

        except Exception as e:
            logger.critical(f"Failed to create initial version for agent {agent['agent_id']}. Rolling back agent creation. Error: {e}", exc_info=True)
            await client.table('agents').delete().eq('agent_id', agent['agent_id']).execute()
            raise HTTPException(status_code=500, detail="Failed to create agent's initial configuration.")

        logger.info(f"Successfully created agent {agent['agent_id']} with v1 for user: {user_id}")
        
        loader = await get_agent_loader()
        created_agent_data = await loader.load_agent(agent['agent_id'], user_id, load_config=True)
        return created_agent_data.to_pydantic_model()
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating agent for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred while creating the agent.")

@router.post("/agents/generate-icon", response_model=AgentIconGenerationResponse, summary="Generate Agent Icon", operation_id="generate_agent_icon")
async def generate_agent_icon(
    request: AgentIconGenerationRequest,
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    """Generate an appropriate icon and colors for an agent based on its name."""
    logger.debug(f"Generating icon for agent name: '{request.name}' for user {user_id}")
    try:
        result = await util_generate_icon(name=request.name)
        return AgentIconGenerationResponse(**result)
    except Exception as e:
        logger.error(f"Error generating agent icon: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate agent icon.")
