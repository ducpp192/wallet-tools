"""
Subscribes to Binance combined trade streams.
Streams are split into batches of WS_MAX_STREAMS per connection.
Reconnects automatically on drop. Restarts when token list changes.
"""
import asyncio
import json
from typing import Dict, List, Set

import websockets

from models.token_state import TokenState
from engine.pump_detector import update_trade
from utils.config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

_WS_BASE = "wss://stream.binance.com:9443/stream"


def _url(symbols: List[str]) -> str:
    streams = "/".join(s.lower() + "@trade" for s in symbols)
    return f"{_WS_BASE}?streams={streams}"


async def _stream(url: str, states: Dict[str, TokenState]) -> None:
    """Single connection — reconnects on error indefinitely."""
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
                log.info("WS connected (%d streams)", url.count("@trade"))
                async for raw in ws:
                    try:
                        msg  = json.loads(raw)
                        data = msg.get("data", {})
                        if data.get("e") != "trade":
                            continue
                        symbol = data["s"]
                        state  = states.get(symbol)
                        if state is None:
                            continue
                        price  = float(data["p"])
                        qty    = float(data["q"])
                        ts     = data["T"] / 1000.0
                        is_buy = not data.get("m", True)   # m=False → buyer initiated
                        update_trade(state, price, qty, is_buy, ts)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("WS disconnected (%s), retry in %ds", e, cfg.WS_RECONNECT_DELAY)
            await asyncio.sleep(cfg.WS_RECONNECT_DELAY)


async def ws_loop(states: Dict[str, TokenState]) -> None:
    """
    Manages WS connections. Restarts all connections whenever the
    set of tracked symbols changes (i.e. after each CMC refresh).
    """
    tasks: List[asyncio.Task] = []
    known: Set[str] = set()

    while True:
        current = set(states.keys())

        if current != known and current:
            # Cancel old connections
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            tasks.clear()

            known = current
            syms  = list(current)
            batch_size = cfg.WS_MAX_STREAMS
            batches = [syms[i:i + batch_size] for i in range(0, len(syms), batch_size)]

            for batch in batches:
                tasks.append(asyncio.create_task(_stream(_url(batch), states)))

            log.info("WS: %d connections for %d symbols", len(tasks), len(syms))

        await asyncio.sleep(10)   # poll for symbol changes every 10s
