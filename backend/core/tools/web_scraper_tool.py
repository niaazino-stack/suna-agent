"""
This module provides a web scraping tool that conforms to the new plugin architecture.

It is responsible for fetching the content of web pages.
"""

import httpx
from pydantic import BaseModel, Field
from typing import Type, List
import asyncio

from core.tools.base import ToolBase
from core.utils.config import config
from core.utils.logger import logger

# --- Pydantic Schemas for Input ---

class WebScraperInput(BaseModel):
    urls: List[str] = Field(..., description="A list of URLs to scrape.")
    include_html: bool = Field(False, description="Whether to include the raw HTML in the output.")

# --- Tool Implementation ---

class WebScraperTool(ToolBase):
    """A tool for scraping web pages using the Firecrawl API."""

    name = "web_scraper"
    description = "Extracts the content from a list of web pages."
    schema = WebScraperInput

    def __init__(self):
        self.firecrawl_api_key = config.FIRECRAWL_API_KEY
        self.firecrawl_url = config.FIRECRAWL_URL
        if not self.firecrawl_api_key:
            logger.warning("FIRECRAWL_API_KEY is not configured. The WebScraperTool will not be available.")

    async def execute(self, urls: List[str], include_html: bool = False) -> dict:
        if not self.firecrawl_api_key:
            return {"error": "Firecrawl API key not configured."}

        if not urls:
            return {"error": "At least one URL is required."}

        tasks = [self._scrape_single_url(url, include_html) for url in urls]
        results = await asyncio.gather(*tasks)
        return {"status": "success", "scraped_content": results}

    async def _scrape_single_url(self, url: str, include_html: bool) -> dict:
        """Helper to scrape a single URL."""
        headers = {
            "Authorization": f"Bearer {self.firecrawl_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"url": url, "formats": ["markdown"]}
        if include_html:
            payload["formats"].append("html")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.firecrawl_url}/v1/scrape", json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                data = response.json()
                return {
                    "url": url,
                    "title": data.get("data", {}).get("metadata", {}).get("title", ""),
                    "content": data.get("data", {}).get("markdown", ""),
                    "html": data.get("data", {}).get("html", "") if include_html else None
                }
        except Exception as e:
            logger.error(f"Error scraping URL {url}: {e}", exc_info=True)
            return {"url": url, "error": str(e)}
