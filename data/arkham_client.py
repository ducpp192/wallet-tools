"""
Arkham Intelligence API client.

NOTE ON ENDPOINTS
-----------------
Arkham's API surface has changed between revisions and is not publicly
versioned. Every path this module uses is declared in `EP` below so it can be
corrected in one place. Run `python sand_radar.py --probe` to see which paths
answer for your key before trusting the radar output.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx

from utils.config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

_BASE = cfg.ARKHAM_BASE_URL

# Verify these against your account's docs; --probe reports which ones work.
EP = {
    "transfers":    "/transfers",
    "holders":      "/token/holders/{chain}/{address}",
    "balances":     "/balances/address/{address}",
    "address":      "/intelligence/address/{address}/all",
    "token_top":    "/token/top_flow/{chain}/{address}",
}


class ArkhamError(RuntimeError):
    pass


class ArkhamClient:
    """Thin async wrapper with retry/backoff and a shared connection pool."""

    def __init__(self, api_key: Optional[str] = None, base_url: str = _BASE):
        self.api_key = api_key if api_key is not None else cfg.ARKHAM_API_KEY
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ArkhamClient":
        if not self.api_key:
            log.warning("ARKHAM_API_KEY is empty — requests will likely 401")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"API-Key": self.api_key, "Accept": "application/json"},
            timeout=httpx.Timeout(cfg.ARKHAM_TIMEOUT),
            limits=httpx.Limits(max_connections=8),
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        assert self._client, "use ArkhamClient as an async context manager"
        delay = 1.0
        last_exc: Optional[Exception] = None

        for attempt in range(cfg.ARKHAM_MAX_RETRIES):
            try:
                r = await self._client.get(path, params=params)
                if r.status_code == 429:
                    retry_after = float(r.headers.get("Retry-After", delay))
                    log.warning("Arkham 429 on %s — sleeping %.1fs", path, retry_after)
                    await asyncio.sleep(retry_after)
                    delay *= 2
                    continue
                if r.status_code in (401, 403):
                    raise ArkhamError(f"{r.status_code} on {path}: check ARKHAM_API_KEY / plan tier")
                if r.status_code == 404:
                    raise ArkhamError(f"404 on {path}: endpoint path is wrong, fix data/arkham_client.py:EP")
                r.raise_for_status()
                return r.json()
            except ArkhamError:
                raise
            except Exception as e:                      # network / 5xx / parse
                last_exc = e
                log.debug("Arkham %s attempt %d failed: %s", path, attempt + 1, e)
                await asyncio.sleep(delay)
                delay *= 2

        raise ArkhamError(f"{path} failed after {cfg.ARKHAM_MAX_RETRIES} attempts: {last_exc}")

    # ── endpoints ────────────────────────────────────────────────────

    async def transfers(
        self,
        token: str,
        chains: str = "ethereum,polygon",
        *,
        since_secs: int = 3600,
        min_usd: float = 50_000,
        limit: int = 200,
        flow: Optional[str] = None,          # "in" | "out" | None (both)
        base: Optional[str] = None,          # entity or address to anchor on
    ) -> List[dict]:
        """Token transfers above `min_usd` in the last `since_secs`."""
        now = int(time.time() * 1000)
        params: Dict[str, Any] = {
            "tokens":   token,
            "chains":   chains,
            "timeGte":  now - since_secs * 1000,
            "timeLte":  now,
            "usdGte":   min_usd,
            "limit":    limit,
            "sortKey":  "time",
            "sortDir":  "desc",
        }
        if flow:
            params["flow"] = flow
        if base:
            params["base"] = base

        data = await self._get(EP["transfers"], params)
        if isinstance(data, dict):
            return data.get("transfers") or data.get("data") or []
        return data if isinstance(data, list) else []

    async def holders(self, token: str, chain: str = "ethereum", limit: int = 100) -> List[dict]:
        path = EP["holders"].format(chain=chain, address=token)
        data = await self._get(path, {"limit": limit})
        if isinstance(data, dict):
            return data.get("holders") or data.get("data") or []
        return data if isinstance(data, list) else []

    async def balances(self, address: str) -> dict:
        return await self._get(EP["balances"].format(address=address))

    async def address_intel(self, address: str) -> dict:
        return await self._get(EP["address"].format(address=address))

    async def probe(self, token: str, chain: str = "ethereum") -> Dict[str, str]:
        """Report which endpoints answer. Run this first."""
        results: Dict[str, str] = {}
        checks = [
            ("transfers", lambda: self.transfers(token, chain, since_secs=600, min_usd=1, limit=1)),
            ("holders",   lambda: self.holders(token, chain, limit=1)),
            ("balances",  lambda: self.balances(token)),
            ("address",   lambda: self.address_intel(token)),
        ]
        for name, call in checks:
            try:
                await call()
                results[name] = "OK"
            except ArkhamError as e:
                results[name] = f"FAIL {e}"
            except Exception as e:
                results[name] = f"FAIL {type(e).__name__}: {e}"
        return results
