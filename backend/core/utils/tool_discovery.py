"""
This module implements the modern, plugin-based tool discovery system.

It works by scanning the `core/tools` directory, dynamically importing Python modules,
and registering any classes that inherit from the `ToolBase` abstract base class.
This creates a simple, elegant, and highly extensible plugin architecture.
"""

import importlib
import inspect
import pkgutil
from typing import Dict, List, Any, Optional

# Local imports
from core.tools.base import ToolBase
from core.utils.logger import logger
import core.tools

# --- Tool Cache ---
# This cache will store instantiated tool objects, keyed by their names.
_TOOL_INSTANCE_CACHE: Dict[str, ToolBase] = {}
_METADATA_CACHE: List[Dict[str, Any]] = []

def _discover_and_register_tools():
    """
    Scans the `core.tools` package, discovers all `ToolBase` subclasses,
    instantiates them, and populates the cache.
    """
    if _TOOL_INSTANCE_CACHE: # Caching check
        return

    logger.info("Initializing tool discovery...")
    
    # Dynamically import all modules in the `core.tools` package
    for module_info in pkgutil.walk_packages(core.tools.__path__, core.tools.__name__ + '.'):
        if module_info.name.endswith('.base'): # Don't import the base class module itself
            continue
        try:
            module = importlib.import_module(module_info.name)
            # Inspect the module for ToolBase subclasses
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, ToolBase) and obj is not ToolBase and not inspect.isabstract(obj):
                    try:
                        # Instantiate the tool
                        tool_instance = obj()
                        tool_name = tool_instance.name

                        if tool_name in _TOOL_INSTANCE_CACHE:
                            logger.warning(f"Duplicate tool name '{tool_name}' found. Overwriting.")
                        
                        _TOOL_INSTANCE_CACHE[tool_name] = tool_instance
                        logger.debug(f"Discovered and registered tool: '{tool_name}'")
                    except Exception as e:
                        logger.error(f"Failed to instantiate tool {obj.__name__}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Failed to import or inspect module {module_info.name}: {e}", exc_info=True)

    # Populate the metadata cache after all tools are registered
    _METADATA_CACHE.extend([tool.get_metadata() for tool in _TOOL_INSTANCE_CACHE.values()])
    logger.info(f"Tool discovery complete. {_TOOL_INSTANCE_CACHE.__len__()} tools registered.")

def get_all_tools() -> Dict[str, ToolBase]:
    """Returns a dictionary of all discovered tool instances."""
    _discover_and_register_tools()
    return _TOOL_INSTANCE_CACHE

def get_tools_metadata() -> List[Dict[str, Any]]:
    """Returns the metadata for all discovered tools."""
    _discover_and_register_tools()
    return _METADATA_CACHE

def get_tool(tool_name: str) -> Optional[ToolBase]:
    """Retrieves a single tool instance by its name."""
    _discover_and_register_tools()
    return _TOOL_INSTANCE_CACHE.get(tool_name)

# It can be beneficial to warm up the cache at application startup.
def warm_up_tools_cache():
    """Pre-loads and caches all tool classes. Call at startup."""
    logger.info("Warming up tools cache...")
    get_all_tools()
    logger.info("Tools cache is warm.")

