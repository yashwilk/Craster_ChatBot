"""Sales/order lookup tool — queries Acumatica's "Sales Simple" GI."""

import time
from typing import Optional

from langchain_core.tools import tool

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import acumatica_tool_calls_total, acumatica_tool_duration_seconds
from app.services.acumatica import acumatica_client, build_odata_string_filter, rows_to_compact_json

# --- Adjust these to match your Sales Simple GI's actual OData field names ---
ORDER_NBR_FIELD = "OrderNbr"
CUSTOMER_FIELD = "CustomerName"
STATUS_FIELD = "Status"
ORDER_TOTAL_FIELD = "OrderTotal"
ORDER_DATE_FIELD = "OrderDate"
# ------------------------------------------------------------------------


@tool
async def search_sales(
    customer: Optional[str] = None,
    order_number: Optional[str] = None,
    status: Optional[str] = None,
    max_results: int = 10,
) -> str:
    """Search Craster sales orders/quotes (Acumatica "Sales Simple" GI).

    Use this whenever the user asks about order status, quote history,
    a customer's past orders, or sales totals. Never guess figures — always
    look them up with this tool first. Do not expose data for a customer
    other than the one the requester is asking about without confirming
    intent with `ask_human` first if it's ambiguous.

    Args:
        customer: Customer name (or partial name) to filter by.
        order_number: Exact order/quote number to look up.
        status: Order status to filter by (e.g. "Open", "Completed").
        max_results: Maximum number of matching orders to return (default 10).

    Returns:
        str: A JSON array of matching order rows, or a message if none found.
    """
    tool_name = "search_sales"
    start = time.monotonic()
    try:
        filters = []
        if customer:
            filters.append(build_odata_string_filter(CUSTOMER_FIELD, customer))
        if order_number:
            escaped = order_number.replace("'", "''")
            filters.append(f"{ORDER_NBR_FIELD} eq '{escaped}'")
        if status:
            escaped = status.replace("'", "''")
            filters.append(f"{STATUS_FIELD} eq '{escaped}'")

        if not filters:
            return "Please provide at least a customer name, order number, or status to search sales records."

        odata_filter = " and ".join(filters)
        rows = await acumatica_client.query_gi(
            gi_name=settings.ACUMATICA_SALES_GI,
            odata_filter=odata_filter,
            top=max_results,
        )
        acumatica_tool_calls_total.labels(tool=tool_name, status="success").inc()
        logger.info(
            "acumatica_sales_search",
            customer=customer,
            order_number=order_number,
            status=status,
            result_count=len(rows),
        )
        return rows_to_compact_json(rows, max_rows=max_results)
    except Exception as e:
        acumatica_tool_calls_total.labels(tool=tool_name, status="error").inc()
        logger.exception("acumatica_sales_search_failed", error=str(e))
        return f"Sales lookup failed: {e}"
    finally:
        acumatica_tool_duration_seconds.labels(tool=tool_name).observe(time.monotonic() - start)
