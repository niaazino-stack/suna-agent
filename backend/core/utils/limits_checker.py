"""
This module provides functions to check resource limits for users.

In this simplified version, all limits are effectively disabled to allow for unrestricted development and usage.
"""

from typing import Dict, Any
from core.utils.logger import logger

async def check_agent_run_limit(client, account_id: str) -> Dict[str, Any]:
    """Always allows starting a new agent run."""
    logger.debug(f"Checking agent run limit for account {account_id} (limit disabled)")
    return {
        'can_start': True,
        'running_count': 0,
        'running_thread_ids': [],
        'limit': 999999
    }

async def check_agent_count_limit(client, account_id: str) -> Dict[str, Any]:
    """Always allows creating a new agent."""
    logger.debug(f"Checking agent count limit for account {account_id} (limit disabled)")
    return {
        'can_create': True,
        'current_count': 0,
        'limit': 999999,
        'tier_name': 'unlimited'
    }

async def check_project_count_limit(client, account_id: str) -> Dict[str, Any]:
    """Always allows creating a new project."""
    logger.debug(f"Checking project count limit for account {account_id} (limit disabled)")
    return {
        'can_create': True,
        'current_count': 0,
        'limit': 999999,
        'tier_name': 'unlimited'
    }

async def check_trigger_limit(client, account_id: str, agent_id: str = None, trigger_type: str = None) -> Dict[str, Any]:
    """Always allows creating a new trigger."""
    logger.debug(f"Checking trigger limit for account {account_id} (limit disabled)")
    return {
        'can_create': True,
        'current_count': 0,
        'limit': 999999,
        'tier_name': 'unlimited'
    }

async def check_custom_worker_limit(client, account_id: str) -> Dict[str, Any]:
    """Always allows creating a new custom worker (MCP)."""
    logger.debug(f"Checking custom worker limit for account {account_id} (limit disabled)")
    return {
        'can_create': True,
        'current_count': 0,
        'limit': 999999,
        'tier_name': 'unlimited'
    }

async def check_thread_limit(client, account_id: str) -> Dict[str, Any]:
    """Always allows creating a new thread."""
    logger.debug(f"Checking thread limit for account {account_id} (limit disabled)")
    return {
        'can_create': True,
        'current_count': 0,
        'limit': 999999,
        'tier_name': 'unlimited'
    }
