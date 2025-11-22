"""
Core API module for the Super Agent.

This module aggregates all the core API routers into a single router instance.
It also exports the essential `initialize` and `cleanup` functions for the application lifecycle.
"""

from fastapi import APIRouter

# Import core application modules
from .core_utils import initialize, cleanup

# Import feature-specific routers
from .versioning.api import router as agent_versioning_router
from .agent_runs import router as agent_runs_router
from .agent_crud import router as agent_crud_router
from .agent_tools import router as agent_tools_router
from .agent_json import router as agent_json_router
from .agent_setup import router as agent_setup_router
from .threads import router as threads_router
from .tools_api import router as tools_api_router
from .limits_api import router as limits_api_router
from .feedback import router as feedback_router

# The main router for the core API
router = APIRouter()

# --- Router Inclusions ---
# The order of inclusion can be important if there are overlapping path operations.
# Grouping them by functionality.

# Agent Management
router.include_router(agent_crud_router, prefix="/agents", tags=["Agents"])
router.include_router(agent_setup_router, prefix="/agents", tags=["Agents"])
router.include_router(agent_json_router, prefix="/agents", tags=["Agents"])
router.include_router(agent_versioning_router, prefix="/agents", tags=["Agents"])

# Agent Execution & Interaction
router.include_router(agent_runs_router, prefix="/runs", tags=["Agent Runs"])
router.include_router(threads_router, prefix="/threads", tags=["Threads"])

# Tools & Capabilities
router.include_router(agent_tools_router, prefix="/agents", tags=["Agent Tools"])
router.include_router(tools_api_router, prefix="/tools", tags=["Tools"])

# System & User Feedback
router.include_router(limits_api_router, prefix="/limits", tags=["System"])
router.include_router(feedback_router, prefix="/feedback", tags=["User Feedback"])


# Re-export the initialize and cleanup functions for use in the main `api.py`
__all__ = ['router', 'initialize', 'cleanup']
