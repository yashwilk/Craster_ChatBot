"""Shared Acumatica ERP client.

Handles cookie-session login against Acumatica's REST endpoint and querying
Generic Inquiries (GIs) via their OData feed. The session cookie is cached
(Valkey/Redis if configured, else in-process) so we don't re-login on every
tool call — Acumatica sessions are relatively expensive to establish.

Two GIs are used by this project:
  * Products Simple GI  -> catalog lookups (search_products tool)
  * Sales Simple GI      -> order/sales lookups (search_sales tool)

Both go through this one client so auth, caching, retries, and error
handling live in exactly one place.
"""

import json
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.cache import cache_service
from app.core.config import settings
from app.core.logging import logger

_SESSION_CACHE_KEY = "acumatica:session_cookie"


class AcumaticaError(Exception):
    """Raised when Acumatica returns an unrecoverable error."""


class AcumaticaClient:
    """Thin async client over Acumatica's login + OData GI endpoints."""

    def __init__(self) -> None:
        if not settings.ACUMATICA_BASE_URL:
            logger.warning("acumatica_base_url_not_configured")
        self._base_url = settings.ACUMATICA_BASE_URL

    async def _login(self) -> str:
        """POST to /entity/auth/login and return the Set-Cookie session header."""
        payload = {
            "name": settings.ACUMATICA_USERNAME,
            "password": settings.ACUMATICA_PASSWORD,
        }
        if settings.ACUMATICA_TENANT:
            payload["company"] = settings.ACUMATICA_TENANT
        if settings.ACUMATICA_BRANCH:
            payload["branch"] = settings.ACUMATICA_BRANCH

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self._base_url}/entity/auth/login", json=payload)
            resp.raise_for_status()
            cookie_header = "; ".join(f"{k}={v}" for k, v in resp.cookies.items())
            if not cookie_header:
                raise AcumaticaError("acumatica login succeeded but returned no session cookie")
            await cache_service.set(_SESSION_CACHE_KEY, cookie_header, ttl=settings.ACUMATICA_SESSION_TTL_SECONDS)
            logger.info("acumatica_login_success")
            return cookie_header

    async def _get_session_cookie(self, force_refresh: bool = False) -> str:
        """Return a cached session cookie, logging in if absent or forced."""
        if not force_refresh:
            cached = await cache_service.get(_SESSION_CACHE_KEY)
            if cached:
                return cached
        return await self._login()

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def query_gi(
        self,
        gi_name: str,
        odata_filter: Optional[str] = None,
        select: Optional[str] = None,
        top: int = 20,
    ) -> list[dict[str, Any]]:
        """Query a Generic Inquiry's OData feed with an optional $filter/$select/$top.

        Args:
            gi_name: The GI's OData entity name (as published in Acumatica).
            odata_filter: A raw OData $filter expression, e.g.
                "substringof('table', ItemDescription)".
            select: Comma-separated field list to limit the response payload.
            top: Max rows to return.

        Returns:
            List of result rows as plain dicts.

        Raises:
            AcumaticaError: On a non-recoverable HTTP or configuration error.
        """
        if not self._base_url:
            raise AcumaticaError(
                "Acumatica is not configured (ACUMATICA_BASE_URL missing). "
                "Set it in your environment to enable catalog/sales lookups."
            )

        params: dict[str, Any] = {"$top": top}
        if odata_filter:
            params["$filter"] = odata_filter
        if select:
            params["$select"] = select

        cookie = await self._get_session_cookie()
        url = f"{self._base_url}/odata/{gi_name}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params, headers={"Cookie": cookie})

            # Session expired — refresh once and retry.
            if resp.status_code == 401:
                logger.info("acumatica_session_expired_refreshing")
                cookie = await self._get_session_cookie(force_refresh=True)
                resp = await client.get(url, params=params, headers={"Cookie": cookie})

            if resp.status_code != 200:
                logger.error(
                    "acumatica_gi_query_failed", gi_name=gi_name, status=resp.status_code, body=resp.text[:500]
                )
                raise AcumaticaError(f"Acumatica GI '{gi_name}' query failed with status {resp.status_code}")

            data = resp.json()
            rows = data.get("value", data if isinstance(data, list) else [])
            return rows


def build_odata_string_filter(field: str, value: str) -> str:
    """Build a case-insensitive 'contains' OData filter for a text field."""
    escaped = value.replace("'", "''")
    return f"substringof('{escaped}', {field})"


def rows_to_compact_json(rows: list[dict[str, Any]], max_rows: int = 15) -> str:
    """Serialize GI rows to compact JSON for LLM consumption, capped at max_rows."""
    if not rows:
        return "No matching records found."
    return json.dumps(rows[:max_rows], default=str)


acumatica_client = AcumaticaClient()
