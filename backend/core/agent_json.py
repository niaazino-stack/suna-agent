"""
This module handles the import and export of agent configurations as JSON.

It has been refactored to remove legacy limit checks and to use the standard,
ownership-based authorization model for exports.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from fastapi import APIRouter, HTTPException, Depends

# Core dependencies
from core.utils.auth_utils import verify_and_get_user_id_from_jwt, require_agent_ownership
from core.utils.logger import logger
from core.templates.template_service import MCPRequirementValue

# Local dependencies
from .api_models import JsonAnalysisRequest, JsonAnalysisResponse, JsonImportRequestModel, JsonImportResponse
from . import core_utils as utils
from .config_helper import extract_agent_config
from .versioning.version_service import VersionService

router = APIRouter(tags=["agent-json"])

class JsonImportError(Exception):
    pass

class JsonImportService:
    """Service class to handle the logic of importing agents from JSON."""
    def __init__(self, db_connection):
        self._db = db_connection

    async def import_agent(self, request: JsonImportRequestModel, user_id: str) -> dict:
        """Main method to import an agent, creating the agent and its first version."""
        logger.debug(f"Importing agent from JSON for user {user_id}")
        json_data = request.json_data

        # Basic validation of the incoming JSON structure
        if not all(k in json_data for k in ['tools', 'system_prompt']):
            raise JsonImportError("Invalid JSON structure: missing 'tools' or 'system_prompt'.")

        # In a more complete implementation, this is where you would handle
        # mapping required credentials (MCPs) to the user's existing credentials.
        # For this refactoring, we assume the user has the necessary credentials.

        # Create the agent record in the database
        agent_id = await self._create_agent_record(json_data, request.instance_name, user_id)

        # Create the first version for the newly created agent
        await self._create_initial_version(agent_id, user_id, json_data)

        logger.info(f"Successfully imported agent {agent_id} from JSON for user {user_id}")
        return {
            'status': 'success',
            'instance_id': agent_id,
            'name': request.instance_name or json_data.get('name', 'Imported Agent')
        }

    async def _create_agent_record(self, json_data: dict, instance_name: Optional[str], user_id: str) -> str:
        """Creates the agent entry in the 'agents' table."""
        client = await self._db.client
        agent_name = instance_name or json_data.get('name', 'Imported Agent')

        insert_data = {
            "account_id": user_id,
            "name": agent_name,
            "description": json_data.get('description', ''),
            "icon_name": json_data.get('icon_name', 'brain'),
            "is_default": False,
            "metadata": {
                "imported_from_json": True,
                "import_date": datetime.now(timezone.utc).isoformat()
            }
        }
        
        result = await client.table('agents').insert(insert_data).execute()
        if not result.data:
            raise JsonImportError("Database failure: Could not create agent record.")
        
        return result.data[0]['agent_id']

    async def _create_initial_version(self, agent_id: str, user_id: str, json_data: dict):
        """Creates the first version of the agent based on the imported JSON data."""
        try:
            version_service = VersionService()
            tools_config = json_data.get('tools', {})

            new_version = await version_service.create_version(
                agent_id=agent_id,
                user_id=user_id,
                system_prompt=json_data.get('system_prompt', ''),
                agentpress_tools=tools_config.get('agentpress', {}),
                configured_mcps=tools_config.get('mcp', []),
                custom_mcps=tools_config.get('custom_mcp', []),
                change_description="Initial version from JSON import"
            )
            
            # Activate the newly created version
            await version_service.activate_version(agent_id, new_version.version_id, user_id)

        except Exception as e:
            logger.error(f"Failed to create initial version for imported agent {agent_id}: {e}", exc_info=True)
            # Attempt to roll back the agent creation if versioning fails
            client = await self._db.client
            await client.table('agents').delete().eq('agent_id', agent_id).execute()
            raise JsonImportError(f"Failed to create initial configuration: {e}")

# --- API Endpoints ---

@router.post("/agents/import", response_model=JsonImportResponse, summary="Import Agent from JSON", operation_id="import_agent_json")
async def import_agent_from_json(
    request: JsonImportRequestModel,
    user_id: str = Depends(verify_and_get_user_id_from_jwt)
):
    """Imports an agent from a JSON configuration."""
    logger.debug(f"Initiating agent import from JSON for user: {user_id}")
    
    try:
        import_service = JsonImportService(utils.db)
        result = await import_service.import_agent(request, user_id)
        return JsonImportResponse(**result)
        
    except Exception as e:
        logger.error(f"Error during JSON agent import: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to import agent: {str(e)}")

@router.get("/agents/{agent_id}/export", summary="Export Agent as JSON", operation_id="export_agent_json")
async def export_agent(
    agent: dict = Depends(require_agent_ownership)
):
    """Exports the active configuration of an agent as JSON."""
    agent_id = agent['agent_id']
    user_id = agent['account_id']
    logger.debug(f"Exporting agent {agent_id} for user: {user_id}")
    
    try:
        # Fetch the active version configuration
        version_id = agent.get('current_version_id')
        version_data = None
        if version_id:
            version_service = VersionService()
            version_obj = await version_service.get_version_by_id(version_id, user_id)
            version_data = version_obj.to_dict()

        # Use the config helper to get a unified config
        config = extract_agent_config(agent, version_data)

        # Construct the export data structure
        export_data = {
            "name": config.get('name', ''),
            "description": config.get('description', ''),
            "system_prompt": config.get('system_prompt', ''),
            "tools": {
                'agentpress': config.get('agentpress_tools', {}),
                'mcp': config.get('configured_mcps', []),
                'custom_mcp': config.get('custom_mcps', [])
            },
            "metadata": agent.get('metadata', {}),
            "exported_at": datetime.now(timezone.utc).isoformat()
        }

        # Remove sensitive or irrelevant metadata before exporting
        for key in ['is_suna_default', 'installation_date', 'imported_from_json', 'import_date']:
            export_data["metadata"].pop(key, None)

        logger.info(f"Successfully exported agent {agent_id}")
        return export_data
        
    except Exception as e:
        logger.error(f"Error exporting agent {agent_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export agent configuration.")
