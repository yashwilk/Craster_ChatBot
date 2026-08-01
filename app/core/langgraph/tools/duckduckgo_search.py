"""General web search tool (for anything outside Craster's own data)."""

from langchain_community.tools import DuckDuckGoSearchResults

duckduckgo_search_tool = DuckDuckGoSearchResults(num_results=10, handle_tool_error=True)
