import httpx
from typing import Dict
from utils.config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

_CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"


async def fetch_universe() -> Dict[str, dict]:
    """
    Fetch token list from CoinMarketCap, apply market-cap/volume filters.
    Returns  {  "BTCUSDT": {"market_cap": ..., "volume_24h": ..., "volume_change_24h": ...}, ... }
    """
    params = {
        "start":    1,
        "limit":    500,
        "sort":     "volume_24h",
        "sort_dir": "desc",
        "convert":  "USD",
    }
    headers = {
        "X-CMC_PRO_API_KEY": cfg.CMC_API_KEY,
        "Accept":            "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(_CMC_URL, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.error("CMC fetch failed: %s", e)
        return {}

    universe: Dict[str, dict] = {}
    for coin in data.get("data", []):
        symbol = coin.get("symbol", "").upper()
        if not symbol:
            continue

        quote             = coin.get("quote", {}).get("USD", {})
        market_cap        = float(quote.get("market_cap")       or 0)
        volume_24h        = float(quote.get("volume_24h")       or 0)
        volume_change_24h = float(quote.get("volume_change_24h") or 0)
        price_change_24h  = float(quote.get("percent_change_24h") or 0)

        if market_cap < cfg.MARKET_CAP_MIN or market_cap > cfg.MARKET_CAP_MAX:
            continue
        if volume_24h < cfg.VOLUME_24H_MIN:
            continue
        if price_change_24h > cfg.PRICE_SKIP_THRESHOLD * 100:
            log.debug("Skip %s: already +%.1f%%", symbol, price_change_24h)
            continue

        binance_sym = symbol + "USDT"
        universe[binance_sym] = {
            "market_cap":        market_cap,
            "volume_24h":        volume_24h,
            "volume_change_24h": volume_change_24h,
        }

        if len(universe) >= cfg.MAX_TOKENS:
            break

    log.info("CMC universe: %d tokens", len(universe))
    return universe
