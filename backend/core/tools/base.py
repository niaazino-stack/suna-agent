"""
This module defines the foundational abstract base class for all agent tools.

By inheriting from `ToolBase`, developers can create new tools that the system
can automatically discover and integrate. This forms the core of the plugin
architecture for extending agent capabilities.
"""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Type, Dict, Any

class ToolBase(ABC):
    """
    Abstract Base Class for all tools.
    
    All tools must inherit from this class and implement the required methods.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """A unique, programmatic name for the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A human-readable description of what the tool does. Used by the LLM."""
        pass

    @property
    @abstractmethod
    def schema(self) -> Type[BaseModel]:
        """
The Pydantic model defining the input schema for the tool."""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        """
        The main logic of the tool.
        
        It receives the parsed input according to the schema and must return a
        dictionary representing the structured output.
        """
        pass

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns the full metadata dictionary for the tool, used for discovery.
        This method is already implemented and should not be overridden.
        """
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema.model_json_schema()
        }
