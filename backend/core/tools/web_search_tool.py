"""
This module provides a web search tool that conforms to the new plugin architecture.
"""

from tavily import AsyncTavilyClient
from pydantic import BaseModel, Field
from typing import Type, List, Union
import asyncio

from core.tools.base import ToolBase
from core.utils.config import config
from core.utils.logger import logger

# --- Pydantic Schemas for Input ---

class WebSearchInput(BaseModel):
    query: Union[str, List[str]] = Field(..., description="A single search query or a list of queries to execute concurrently.")
    num_results: int = Field(10, description="The number of search results to return per query.")

# --- Tool Implementation ---

class WebSearchTool(ToolBase):
    """A tool for performing web searches using the Tavily API."""

    name = "web_search"
    description = "Search the web for up-to-date information. Supports single or multiple queries for concurrent searching."
    schema = WebSearchInput

    def __init__(self):
        self.tavily_api_key = config.TAVILY_API_KEY
        if not self.tavily_api_key:
            logger.warning("TAVILY_API_KEY is not configured. The WebSearchTool will not be available.")
            self.tavily_client = None
        else:
            self.tavily_client = AsyncTavilyClient(api_key=self.tavily_api_key)

    async def execute(self, query: Union[str, List[str]], num_results: int = 10) -> dict:
        if not self.tavily_client:
            return {"error": "Tavily API key not configured."}

        is_batch = isinstance(query, list)

        try:
            if is_batch:
                if not query:
                    return {"error": "At least one search query is required for batch search."}
                tasks = [self._execute_single_search(q, num_results) for q in query]
                results = await asyncio.gather(*tasks)
                return {"status": "success", "results": results}
            else:
                return await self._execute_single_search(query, num_results)

        except Exception as e:
            logger.error(f"Error performing web search: {e}", exc_info=True)
            return {"error": f"An unexpected error occurred: {e}"}

    async def _execute_single_search(self, query: str, num_results: int) -> dict:
        """Helper to run a single search query."""
        try:
            search_response = await self.tavily_client.search(
                query=query,
                max_results=num_results,
                include_images=True,
                include_answer=True,
                search_depth="advanced"
            )
            return search_response
        except Exception as e:
            logger.error(f"Error during single search for query '{query}': {e}")
            return {"query": query, "error": str(e)}
