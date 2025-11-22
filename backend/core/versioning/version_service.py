import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from uuid import uuid4

from core.services.supabase import DBConnection
from core.utils.logger import logger

# --- Data Models and Custom Exceptions ---

@dataclass
class AgentVersion:
    """Represents a snapshot of an agent's configuration."""
    version_id: str
    agent_id: str
    version_number: int
    version_name: str
    system_prompt: str
    model: Optional[str] = None
    configured_mcps: List[Dict[str, Any]] = field(default_factory=list)
    custom_mcps: List[Dict[str, Any]] = field(default_factory=list)
    agentpress_tools: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = ""
    change_description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the dataclass to a dictionary."""
        return {
            'version_id': self.version_id,
            'agent_id': self.agent_id,
            'version_number': self.version_number,
            'version_name': self.version_name,
            'system_prompt': self.system_prompt,
            'model': self.model,
            'configured_mcps': self.configured_mcps,
            'custom_mcps': self.custom_mcps,
            'agentpress_tools': self.agentpress_tools,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'change_description': self.change_description,
        }

class VersionServiceError(Exception): pass
class VersionNotFoundError(VersionServiceError): pass
class AgentNotFoundError(VersionServiceError): pass
class UnauthorizedError(VersionServiceError): pass

# --- Version Service Class ---

class VersionService:
    """Manages the lifecycle of agent versions."""
    def __init__(self):
        self.db = DBConnection()

    async def _get_client(self):
        return await self.db.client

    async def _user_owns_agent(self, agent_id: str, user_id: str) -> bool:
        """Checks if a user is the owner of an agent."""
        if user_id == "system":
            return True  # Allow system-level access
        
        client = await self._get_client()
        result = await client.table('agents').select('agent_id').eq('agent_id', agent_id).eq('account_id', user_id).maybe_single().execute()
        return result.data is not None

    def _version_from_db_row(self, row: Dict[str, Any]) -> AgentVersion:
        """Constructs an AgentVersion object from a database row."""
        config = row.get('config', {})
        tools = config.get('tools', {})
        return AgentVersion(
            version_id=row['version_id'],
            agent_id=row['agent_id'],
            version_number=row['version_number'],
            version_name=row['version_name'],
            system_prompt=config.get('system_prompt', ''),
            model=config.get('model'),
            configured_mcps=tools.get('mcp', []),
            custom_mcps=tools.get('custom_mcp', []),
            agentpress_tools=tools.get('agentpress', {}),
            is_active=row.get('is_active', False),
            created_at=datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')),
            created_by=row['created_by'],
            change_description=row.get('change_description'),
        )

    async def create_version(
        self, agent_id: str, user_id: str, system_prompt: str,
        configured_mcps: List, custom_mcps: List, agentpress_tools: Dict,
        model: Optional[str] = None, version_name: Optional[str] = None, change_description: Optional[str] = None
    ) -> AgentVersion:
        logger.debug(f"Creating new version for agent {agent_id} by user {user_id}")
        if not await self._user_owns_agent(agent_id, user_id):
            raise UnauthorizedError("You do not have permission to create versions for this agent.")

        client = await self._get_client()
        
        # Get the next version number
        max_version_result = await client.table('agent_versions').select('version_number').eq('agent_id', agent_id).order('version_number', desc=True).limit(1).execute()
        version_number = (max_version_result.data[0]['version_number'] + 1) if max_version_result.data else 1
        
        version = AgentVersion(
            version_id=str(uuid4()), agent_id=agent_id, version_number=version_number,
            version_name=version_name or f"v{version_number}", system_prompt=system_prompt,
            model=model, configured_mcps=configured_mcps, custom_mcps=custom_mcps,
            agentpress_tools=agentpress_tools, created_by=user_id, change_description=change_description
        )

        version_config = {
            'system_prompt': version.system_prompt, 'model': version.model,
            'tools': {'agentpress': version.agentpress_tools, 'mcp': version.configured_mcps, 'custom_mcp': version.custom_mcps}
        }

        db_data = {
            'version_id': version.version_id, 'agent_id': version.agent_id,
            'version_number': version.version_number, 'version_name': version.version_name,
            'is_active': False,  # New versions are not active by default
            'created_by': version.created_by, 'change_description': version.change_description,
            'config': version_config
        }
        
        result = await client.table('agent_versions').insert(db_data).execute()
        if not result.data:
            raise VersionServiceError("Failed to save the new version.")
        
        # The new version is not activated automatically, so we don't update agent's current_version_id here.
        logger.info(f"Successfully created version {version.version_name} for agent {agent_id}")
        return version

    async def get_version_by_id(self, version_id: str, user_id: str) -> AgentVersion:
        logger.debug(f"Fetching version by ID: {version_id}")
        client = await self._get_client()
        result = await client.table('agent_versions').select('*').eq('version_id', version_id).single().execute()
        
        if not result.data:
            raise VersionNotFoundError(f"Version {version_id} not found.")
            
        version = self._version_from_db_row(result.data)
        if not await self._user_owns_agent(version.agent_id, user_id):
            raise UnauthorizedError("You do not have permission to view this version.")
            
        return version

    async def get_all_versions(self, agent_id: str, user_id: str) -> List[AgentVersion]:
        logger.debug(f"Fetching all versions for agent {agent_id}")
        if not await self._user_owns_agent(agent_id, user_id):
            raise UnauthorizedError("You do not have permission to list versions for this agent.")

        client = await self._get_client()
        result = await client.table('agent_versions').select('*').eq('agent_id', agent_id).order('version_number', desc=True).execute()
        return [self._version_from_db_row(row) for row in result.data]

    async def activate_version(self, agent_id: str, version_id: str, user_id: str):
        logger.debug(f"Activating version {version_id} for agent {agent_id}")
        if not await self._user_owns_agent(agent_id, user_id):
            raise UnauthorizedError("You do not have permission to activate versions for this agent.")

        client = await self._get_client()
        
        # First, ensure the version to be activated exists and belongs to the agent
        version_res = await client.table('agent_versions').select('version_id').eq('agent_id', agent_id).eq('version_id', version_id).maybe_single().execute()
        if not version_res.data:
            raise VersionNotFoundError("Version to activate not found for this agent.")

        # Update the agent's main record to point to the new active version
        update_res = await client.table('agents').update({'current_version_id': version_id}).eq('agent_id', agent_id).execute()
        if not update_res.data:
            raise AgentNotFoundError("Failed to update the active version for the agent.")

        logger.info(f"Successfully activated version {version_id} for agent {agent_id}")

    async def update_version_details(
        self, agent_id: str, version_id: str, user_id: str,
        version_name: Optional[str] = None, change_description: Optional[str] = None
    ) -> AgentVersion:
        logger.debug(f"Updating details for version {version_id}")
        if not await self._user_owns_agent(agent_id, user_id):
            raise UnauthorizedError("You do not have permission to update this version.")

        if version_name is None and change_description is None:
            raise ValueError("No details provided to update.")

        client = await self._get_client()
        update_data = {'updated_at': datetime.now(timezone.utc).isoformat()}
        if version_name is not None: update_data['version_name'] = version_name
        if change_description is not None: update_data['change_description'] = change_description
        
        result = await client.table('agent_versions').update(update_data).eq('version_id', version_id).eq('agent_id', agent_id).execute()
        if not result.data:
            raise VersionNotFoundError("Version not found or failed to update.")

        return self._version_from_db_row(result.data[0])

# --- Singleton Instance --- 

_version_service_instance = None

async def get_version_service() -> VersionService:
    """Provides a singleton instance of the VersionService."""
    global _version_service_instance
    if _version_service_instance is None:
        _version_service_instance = VersionService()
    return _version_service_instance
