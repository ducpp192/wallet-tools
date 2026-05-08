#!/usr/bin/env python3
"""
lp_server.py — Backend cho lp-checker.html  (port 5014)

Endpoints:
  GET  /        → serve lp-checker.html
  GET  /ping    → {"ok": true}
  POST /lp      → on-chain LP pools cho 1 token (Multicall3)
  POST /pairs   → DexScreener pairs (enrich price/vol)
  POST /balance → Blockscout v2 wallet holdings
"""
import asyncio, os, sys, time
from pathlib import Path
from typing import Dict, List

_missing = []
for _pkg, _spec in [
    ("aiohttp",     "aiohttp>=3.9.0"),
    ("httpx",       "httpx>=0.27.0"),
]:
    try:
        __import__(_pkg)
    except ImportError:
        _missing.append(_spec)
if _missing:
    import subprocess
    print(f"[*] Installing: {_missing}")
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + _missing + ["-q"])

from aiohttp import web
import httpx

HERE = Path(__file__).parent

# ── RPC config ───────────────────────────────────────────────────
RPC_CFG: Dict[str, dict] = {
    "base": {
        "rpc":       "https://mainnet.base.org",
        "weth":      "0x4200000000000000000000000000000000000006",
        "symbol":    "WETH",
        "cg":        "ethereum",
        "factories": [
            ("Uniswap V2",    "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"),
            ("Aerodrome V2",  "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"),
            ("SushiSwap",     "0x71524B4f93c58fcbF659783284E38825f0622859"),
            ("BaseSwap",      "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"),
        ],
    },
    "avalanche": {
        "rpc":       "https://api.avax.network/ext/bc/C/rpc",
        "weth":      "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        "symbol":    "WAVAX",
        "cg":        "avalanche-2",
        "factories": [
            ("Trader Joe",  "0x9Ad6C38BE94206cA50bb0d90783181662f0Cfa10"),
            ("Pangolin",    "0xefa94DE7a4656D787667C749f7E1223D71E9FD88"),
        ],
    },
    "bsc": {
        "rpc":       "https://bsc-dataseed.binance.org",
        "weth":      "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "symbol":    "WBNB",
        "cg":        "binancecoin",
        "factories": [
            ("PancakeSwap", "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"),
            ("ApeSwap",     "0x0841BD0B734E4F5853f0dD8d7Ea041c241fb0Da6"),
        ],
    },
    "sonic": {
        "rpc":       "https://rpc.soniclabs.com",
        "weth":      "0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38",
        "symbol":    "wS",
        "cg":        "sonic-3",
        "factories": [],  # thêm factory address Sonic vào đây khi có
    },
    "ethereum": {
        "rpc":       "https://cloudflare-eth.com",
        "weth":      "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "symbol":    "WETH",
        "cg":        "ethereum",
        "factories": [
            ("Uniswap V2",  "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"),
            ("SushiSwap",   "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"),
        ],
    },
}

BLOCKSCOUT: Dict[str, str] = {
    "base":      "https://base.blockscout.com",
    "avalanche": "https://avalanche.blockscout.com",
    "bsc":       "https://bsc.blockscout.com",
    "sonic":     "https://sonic.blockscout.com",
    "ethereum":  "https://eth.blockscout.com",
}

MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ── Price cache ──────────────────────────────────────────────────
_price_cache: dict = {"ts": 0.0, "data": {}}


async def _native_prices(client: httpx.AsyncClient) -> Dict[str, float]:
    now = time.monotonic()
    if now - _price_cache["ts"] < 60 and _price_cache["data"]:
        return _price_cache["data"]
    try:
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=ethereum,avalanche-2,binancecoin,sonic-3&vs_currencies=usd",
            timeout=8,
        )
        d = r.json()
        prices = {
            "ethereum":    float((d.get("ethereum")    or {}).get("usd") or 3000),
            "avalanche-2": float((d.get("avalanche-2") or {}).get("usd") or 30),
            "binancecoin": float((d.get("binancecoin") or {}).get("usd") or 600),
            "sonic-3":     float((d.get("sonic-3")     or {}).get("usd") or 0.5),
        }
    except Exception:
        prices = {"ethereum": 3000, "avalanche-2": 30, "binancecoin": 600, "sonic-3": 0.5}
    _price_cache["data"] = prices
    _price_cache["ts"]   = now
    return prices


# ── Multicall3 ABI helpers ───────────────────────────────────────

_SEL_GET_PAIR = "e6a43905"
_SEL_RESERVES = "0902f1ac"
_SEL_TOKEN0   = "0dfe1681"


def _enc_get_pair(token: str, weth: str) -> str:
    return "0x" + _SEL_GET_PAIR + token[2:].lower().zfill(64) + weth[2:].lower().zfill(64)


def _dec_addr_bytes(b: bytes) -> str:
    if len(b) < 32:
        return ""
    a = "0x" + b[-20:].hex()
    return "" if int(a, 16) == 0 else a


def _dec_reserves_bytes(b: bytes):
    if len(b) < 64:
        return 0, 0
    return int.from_bytes(b[0:32], "big"), int.from_bytes(b[32:64], "big")


def _mc3_encode(calls: list) -> str:
    sel = bytes.fromhex("82ad56cb")
    n = len(calls)
    blobs = []
    for target, allow_fail, calldata in calls:
        cd  = bytes.fromhex(calldata[2:] if calldata.startswith("0x") else calldata)
        pad = ((len(cd) + 31) // 32) * 32
        blobs.append(
            bytes.fromhex(target[2:].lower().zfill(64))
            + (b"\x00" * 31 + (b"\x01" if allow_fail else b"\x00"))
            + (96).to_bytes(32, "big")
            + len(cd).to_bytes(32, "big")
            + cd + b"\x00" * (pad - len(cd))
        )
    offsets, structs, cur = b"", b"", n * 32
    for b_ in blobs:
        offsets += cur.to_bytes(32, "big")
        structs += b_
        cur += len(b_)
    return "0x" + (sel + (32).to_bytes(32, "big") + n.to_bytes(32, "big") + offsets + structs).hex()


def _mc3_decode(result_hex: str, n: int) -> list:
    if not result_hex or result_hex in ("0x", ""):
        return [(False, b"")] * n
    try:
        raw      = bytes.fromhex(result_hex[2:])
        outer    = int.from_bytes(raw[0:32], "big")
        arr_len  = int.from_bytes(raw[outer: outer+32], "big")
        base     = outer + 32
        results  = []
        for i in range(min(n, arr_len)):
            so  = int.from_bytes(raw[base+i*32: base+i*32+32], "big")
            s   = base + so
            ok  = bool(int.from_bytes(raw[s: s+32], "big"))
            bdo = int.from_bytes(raw[s+32: s+64], "big")
            bdp = s + bdo
            bdl = int.from_bytes(raw[bdp: bdp+32], "big")
            results.append((ok, raw[bdp+32: bdp+32+bdl]))
        while len(results) < n:
            results.append((False, b""))
        return results
    except Exception:
        return [(False, b"")] * n


async def _mc3_rpc(client: httpx.AsyncClient, rpc: str, calls: list) -> list:
    if not calls:
        return []
    payload = _mc3_encode(calls)
    try:
        r = await client.post(rpc, json={
            "jsonrpc": "2.0", "method": "eth_call",
            "params":  [{"to": MULTICALL3, "data": payload}, "latest"], "id": 1,
        }, timeout=25)
        hex_result = r.json().get("result", "0x")
    except Exception:
        hex_result = "0x"
    return _mc3_decode(hex_result, len(calls))


# ── LP scan — single token, all factories via Multicall3 ─────────

async def scan_token_lp(
    client: httpx.AsyncClient,
    token: str,
    networks: List[str],
    native_prices: Dict[str, float],
) -> List[dict]:
    pools = []

    for net in networks:
        cfg = RPC_CFG.get(net)
        if not cfg or not cfg["factories"]:
            continue

        rpc      = cfg["rpc"]
        weth     = cfg["weth"]
        weth_sym = cfg["symbol"]
        nprice   = native_prices.get(cfg["cg"], 1.0)

        valid_factories = [
            (name, addr) for name, addr in cfg["factories"]
            if addr.startswith("0x") and len(addr) == 42
        ]
        if not valid_factories:
            continue

        # Step 1: getPair for all factories in one Multicall3 call
        gp_calls = [(addr, True, _enc_get_pair(token, weth)) for _, addr in valid_factories]
        gp_res   = await _mc3_rpc(client, rpc, gp_calls)

        found = []  # (dex_name, pair_address)
        for (dex_name, _), (ok, data) in zip(valid_factories, gp_res):
            if ok and len(data) >= 32:
                pair = _dec_addr_bytes(data)
                if pair:
                    found.append((dex_name, pair))

        if not found:
            continue

        # Step 2: getReserves + token0 for all found pairs in one call
        rv_calls = [(pair, True, "0x" + _SEL_RESERVES) for _, pair in found]
        t0_calls = [(pair, True, "0x" + _SEL_TOKEN0)   for _, pair in found]
        combo    = await _mc3_rpc(client, rpc, rv_calls + t0_calls)

        mid       = len(found)
        rv_dec    = combo[:mid]
        t0_dec    = combo[mid:]

        for (dex_name, pair_addr), (rv_ok, rv_data), (t0_ok, t0_data) in zip(found, rv_dec, t0_dec):
            r0, r1   = _dec_reserves_bytes(rv_data) if rv_ok else (0, 0)
            token0   = _dec_addr_bytes(t0_data).lower() if t0_ok and len(t0_data) >= 32 else ""
            weth_raw = r0 if token0 == weth.lower() else r1
            weth_amt = weth_raw / 1e18
            weth_usd = round(weth_amt * nprice, 4)
            liq_usd  = round(weth_usd * 2, 4)

            pools.append({
                "network":      net,
                "dex":          dex_name,
                "pair_address": pair_addr,
                "weth_symbol":  weth_sym,
                "weth_amt":     round(weth_amt, 8),
                "weth_usd":     weth_usd,
                "liq_usd":      liq_usd,
            })

    return pools


# ── Blockscout holdings ──────────────────────────────────────────

async def fetch_blockscout_holdings(
    client: httpx.AsyncClient,
    wallet: str,
    networks: List[str],
    native_prices: Dict[str, float],
) -> List[dict]:
    assets = []

    for net in networks:
        base_url = BLOCKSCOUT.get(net)
        if not base_url:
            continue

        url = f"{base_url}/api/v2/addresses/{wallet}/tokens?type=ERC-20"
        while url:
            try:
                r = await client.get(url, timeout=15)
                if r.status_code in (400, 404, 422):
                    break
                r.raise_for_status()
                data = r.json()
            except Exception:
                break

            for item in data.get("items", []):
                token = item.get("token") or {}

                _a = (
                    token.get("address_hash")
                    or token.get("address")
                    or item.get("token_contract_address_hash")
                    or ""
                )
                contract = (_a.get("hash", "") if isinstance(_a, dict) else str(_a)).strip()

                decimals = int(token.get("decimals") or 18)
                raw_val  = item.get("value", "0") or "0"
                try:
                    balance = float(raw_val) / 10 ** decimals
                except Exception:
                    balance = 0.0
                if balance <= 0:
                    continue

                assets.append({
                    "network":      net,
                    "token_name":   token.get("name")   or "",
                    "token_symbol": token.get("symbol") or "",
                    "contract":     contract,
                    "balance":      round(balance, 6),
                    "price_usd":    0.0,
                    "value_usd":    0.0,
                    "token_type":   "ERC-20",
                    "thumbnail":    token.get("icon_url") or "",
                })

            nxt = data.get("next_page_params")
            if nxt:
                qs  = "&".join(f"{k}={v}" for k, v in nxt.items())
                url = f"{base_url}/api/v2/addresses/{wallet}/tokens?type=ERC-20&{qs}"
            else:
                url = None

    # Enrich ERC-20 prices via DexScreener (batch 30)
    contracts = [a["contract"] for a in assets if a["contract"]]
    price_map: Dict[str, float] = {}
    for i in range(0, len(contracts), 30):
        batch = contracts[i: i + 30]
        try:
            r2 = await client.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{','.join(batch)}",
                timeout=12,
            )
            for pair in (r2.json().get("pairs") or []):
                bt  = pair.get("baseToken") or {}
                ba  = (bt.get("address") or "").lower()
                p   = float(pair.get("priceUsd") or 0)
                if ba and p and ba not in price_map:
                    price_map[ba] = p
        except Exception:
            pass

    for a in assets:
        p = price_map.get(a["contract"].lower(), 0.0)
        a["price_usd"]  = p
        a["value_usd"]  = round(a["balance"] * p, 4)

    return assets


# ── HTTP handlers ─────────────────────────────────────────────────

async def handle_index(req: web.Request) -> web.Response:
    html_path = HERE / "lp-checker.html"
    if html_path.exists():
        return web.Response(
            text=html_path.read_text(encoding="utf-8"),
            content_type="text/html",
            charset="utf-8",
        )
    return web.Response(text="lp-checker.html not found", status=404)


async def handle_ping(req: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": "1.0"})


async def handle_lp(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    token    = (body.get("token") or "").strip()
    networks = body.get("networks") or ["base", "avalanche"]
    eth_price = float(body.get("eth_price")  or 0)
    avax_price = float(body.get("avax_price") or 0)

    if not token or not token.startswith("0x"):
        return web.json_response({"ok": False, "error": "Invalid token"}, status=400)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20)) as client:
        # Use caller-supplied prices to avoid extra API call
        np = await _native_prices(client)
        if eth_price > 0:
            np["ethereum"] = eth_price
        if avax_price > 0:
            np["avalanche-2"] = avax_price

        pools = await scan_token_lp(client, token, networks, np)

    return web.json_response({"ok": True, "pools": pools})


async def handle_pairs(req: web.Request) -> web.Response:
    """DexScreener enrichment — optional, best-effort."""
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    address = (body.get("address") or "").strip()
    if not address:
        return web.json_response({"ok": True, "pairs": []})

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{address}",
                timeout=12,
            )
            pairs = r.json().get("pairs") or []
    except Exception:
        pairs = []

    return web.json_response({"ok": True, "pairs": pairs})


async def handle_balance(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    wallet   = (body.get("wallet") or "").strip()
    networks = body.get("networks") or ["base", "avalanche"]
    provider = body.get("provider") or "blockscout"

    if not wallet:
        return web.json_response({"ok": False, "error": "No wallet"}, status=400)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20)) as client:
        np = await _native_prices(client)
        # Only Blockscout implemented (free, no key required)
        # Other providers (Covalent / Moralis / Ankr) → fall back to Blockscout
        assets = await fetch_blockscout_holdings(client, wallet, networks, np)

    return web.json_response({"ok": True, "assets": assets})


# ── CORS middleware (allow file:// origin for local use) ──────────

@web.middleware
async def cors_middleware(req: web.Request, handler):
    resp = await handler(req)
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


async def handle_options(req: web.Request) -> web.Response:
    return web.Response(status=204, headers={
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    })


# ── App ───────────────────────────────────────────────────────────

app = web.Application(middlewares=[cors_middleware])
app.router.add_get( "/",        handle_index)
app.router.add_get( "/ping",    handle_ping)
app.router.add_post("/lp",      handle_lp)
app.router.add_post("/pairs",   handle_pairs)
app.router.add_post("/balance", handle_balance)
app.router.add_route("OPTIONS", "/{path_info:.*}", handle_options)

if __name__ == "__main__":
    print("=" * 56)
    print("  LP Server — backend for lp-checker.html")
    print("  Dashboard: http://localhost:5014")
    print("=" * 56)
    web.run_app(app, host="127.0.0.1", port=5014, print=None)
