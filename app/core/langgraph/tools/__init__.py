"""LangGraph tool registry — the agent picks up whatever is listed here."""

from langchain_core.tools.base import BaseTool

from .acumatica_product import search_products
from .acumatica_sales import search_sales
from .ask_human import ask_human
from .duckduckgo_search import duckduckgo_search_tool

tools: list[BaseTool] = [
    duckduckgo_search_tool,
    ask_human,
    search_products,
    search_sales,
]
