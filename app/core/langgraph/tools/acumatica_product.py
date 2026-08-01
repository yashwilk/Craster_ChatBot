"""Product catalog lookup tool — queries Acumatica's "Products Simple" GI."""

import time
from typing import Optional

from langchain_core.tools import tool

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import acumatica_tool_calls_total, acumatica_tool_duration_seconds
from app.services.acumatica import acumatica_client, build_odata_string_filter, rows_to_compact_json

# --- Adjust these to match your Products Simple GI's actual OData field names ---
ITEM_ID_FIELD = "InventoryID"
DESCRIPTION_FIELD = "Description"
CATEGORY_FIELD = "ItemClass"
PRICE_FIELD = "DefaultPrice"
AVAILABLE_QTY_FIELD = "QtyAvailable"
# ----------------------------------------------------------------------------


@tool
async def search_products(query: str, category: Optional[str] = None, max_results: int = 10) -> str:
    """Search the Craster product catalog (Acumatica "Products Simple" GI).

    Use this whenever the user asks about specific products, specs,
    pricing, categories, or availability. Never guess product details —
    always look them up with this tool first.

    Args:
        query: Free-text product name, keyword, or description to search for.
        category: Optional product category / item class to filter by.
        max_results: Maximum number of matching products to return (default 10).

    Returns:
        str: A JSON array of matching product rows, or a message if none found.
    """
    tool_name = "search_products"
    start = time.monotonic()
    try:
        filters = [build_odata_string_filter(DESCRIPTION_FIELD, query)]
        if category:
            escaped = category.replace("'", "''")
            filters.append(f"{CATEGORY_FIELD} eq '{escaped}'")
        odata_filter = " and ".join(filters)

        rows = await acumatica_client.query_gi(
            gi_name=settings.ACUMATICA_PRODUCTS_GI,
            odata_filter=odata_filter,
            top=max_results,
        )
        acumatica_tool_calls_total.labels(tool=tool_name, status="success").inc()
        logger.info("acumatica_products_search", query=query, category=category, result_count=len(rows))
        return rows_to_compact_json(rows, max_rows=max_results)
    except Exception as e:
        acumatica_tool_calls_total.labels(tool=tool_name, status="error").inc()
        logger.exception("acumatica_products_search_failed", query=query, error=str(e))
        return f"Product lookup failed: {e}"
    finally:
        acumatica_tool_duration_seconds.labels(tool=tool_name).observe(time.monotonic() - start)
