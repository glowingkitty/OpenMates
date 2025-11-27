# backend/shared/providers/firecrawl/__init__.py
#
# Firecrawl API provider package.
# Provides web scraping functionality using the Firecrawl API.

from .firecrawl_scrape import scrape_url, check_firecrawl_health

__all__ = ["scrape_url", "check_firecrawl_health"]

