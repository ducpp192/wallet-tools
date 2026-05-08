import asyncio
import time
import httpx
from typing import Dict

from models.token_state import TokenState
from engine.imbalance import calc_imbalance, calc_spread_pct
from utils.logger import get_logger

log = get_logger(__name__)

_BASE = "https://api.binance.com/api/v3"


async def _enrich(client: httpx.AsyncClient, state: TokenState) -> None:
    sym = state.symbol

    # ── 24hr ticker ──────────────────────────────────────────
    try:
        r = await client.get(f"{_BASE}/ticker/24hr", params={"symbol": sym}, timeout=10)
        r.raise_for_status()
        t = r.json()
        state.price    = float(t.get("lastPrice", 0) or 0)
        state.high_24h = float(t.get("highPrice",  0) or 0)
        state.low_24h  = float(t.get("lowPrice",   0) or 0)
        state.last_rest_update = time.time()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 404):
            log.debug("Symbol not on Binance: %s", sym)
        return
    except Exception as e:
        log.debug("REST ticker %s: %s", sym, e)
        return

    # ── Order book ───────────────────────────────────────────
    try:
        r = await client.get(f"{_BASE}/depth", params={"symbol": sym, "limit": 10}, timeout=10)
        r.raise_for_status()
        ob = r.json()
        state.imbalance  = calc_imbalance(ob.get("bids", []), ob.get("asks", []))
        state.spread_pct = calc_spread_pct(ob.get("bids", []), ob.get("asks", []))
    except Exception as e:
        log.debug("REST depth %s: %s", sym, e)

    # ── 1-min klines (breakout detection) ────────────────────
    try:
        r = await client.get(
            f"{_BASE}/klines",
            params={"symbol": sym, "interval": "1m", "limit": 22},
            timeout=10,
        )
        r.raise_for_status()
        klines = r.json()
        state._kline_highs.clear()
        for k in klines[-21:-1]:          # last 20 completed candles
            state._kline_highs.append(float(k[2]))
    except Exception as e:
        log.debug("REST klines %s: %s", sym, e)

    # ── 1-hour kline for price_1h_ago ────────────────────────
    try:
        r = await client.get(
            f"{_BASE}/klines",
            params={"symbol": sym, "interval": "1h", "limit": 2},
            timeout=10,
        )
        r.raise_for_status()
        ks = r.json()
        if ks:
            state.price_1h_ago = float(ks[0][4])   # close of prev 1h candle
            if state.price > 0 and state.price_1h_ago > 0:
                state.price_change_1h_pct = round(
                    (state.price - state.price_1h_ago) / state.price_1h_ago * 100, 4
                )
    except Exception as e:
        log.debug("REST 1h kline %s: %s", sym, e)


async def rest_loop(states: Dict[str, TokenState], interval: float = 30) -> None:
    """Continuously refresh all tokens via Binance REST, then sleep."""
    while True:
        syms = list(states.keys())
        if syms:
            try:
                limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
                async with httpx.AsyncClient(limits=limits) as client:
                    sem = asyncio.Semaphore(10)

                    async def _safe(state: TokenState) -> None:
                        async with sem:
                            await _enrich(client, state)

                    await asyncio.gather(*[_safe(states[s]) for s in syms if s in states])
            except Exception as e:
                log.warning("REST loop error: %s", e)

        await asyncio.sleep(interval)
