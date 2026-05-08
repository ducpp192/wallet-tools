#!/usr/bin/env python3
"""
main.py — Token Holdings & LP Checker
Dashboard at http://localhost:5012
Tab 1: Token Holdings  (Blockscout v2, 5 chains)
Tab 2: LP Check        (DexScreener, 5 chains)
"""
import asyncio
import sys
import time
import uuid
from typing import Dict, List, Any

# ── auto-install ────────────────────────────────────────────────
_missing = []
for _pkg, _spec in [("aiohttp", "aiohttp>=3.9.0"), ("httpx", "httpx>=0.27.0")]:
    try:
        __import__(_pkg)
    except ImportError:
        _missing.append(_spec)
if _missing:
    import subprocess
    print(f"Installing: {_missing}")
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + _missing + ["-q"])

from aiohttp import web
import httpx

# ── Chain configs ────────────────────────────────────────────────
BLOCKSCOUT = {
    "base":      "https://base.blockscout.com",
    "avax":      "https://avalanche.blockscout.com",
    "bsc":       "https://bsc.blockscout.com",
    "sonic":     "https://sonic.blockscout.com",
    "ethereum":  "https://eth.blockscout.com",
}

CHAIN_LABELS = {
    "base": "Base", "avax": "Avalanche", "bsc": "BSC",
    "sonic": "Sonic", "ethereum": "Ethereum",
}

EXPLORERS = {
    "base":     "https://basescan.org/token/{contract}?a={wallet}",
    "avax":     "https://snowscan.xyz/token/{contract}?a={wallet}",
    "bsc":      "https://bscscan.com/token/{contract}?a={wallet}",
    "sonic":    "https://sonicscan.org/token/{contract}?a={wallet}",
    "ethereum": "https://etherscan.io/token/{contract}?a={wallet}",
}

# ── Job store ────────────────────────────────────────────────────
jobs: Dict[str, dict] = {}  # job_id -> {status, progress, total, results, error}

def new_job() -> str:
    jid = str(uuid.uuid4())
    jobs[jid] = {"status": "running", "progress": 0, "total": 0, "results": [], "error": None}
    return jid

def _job(jid: str) -> dict:
    return jobs.get(jid, {})


# ════════════════════════════════════════════════════════════════
# Holdings scanner
# ════════════════════════════════════════════════════════════════

def _make_holding_row(wallet: str, network: str, name: str, symbol: str,
                      contract: str, decimals: int, raw_val: str) -> dict | None:
    """Tạo row từ raw values, trả None nếu balance = 0."""
    try:
        balance = float(raw_val) / (10 ** decimals)
    except Exception:
        balance = 0.0
    if balance <= 0:
        return None
    explorer = EXPLORERS.get(network, "").format(contract=contract, wallet=wallet)
    return {
        "wallet":       wallet,
        "network":      network,
        "token_name":   name,
        "token_symbol": symbol,
        "contract":     contract,
        "balance":      round(balance, 6),
        "price_usd":    0.0,
        "value_usd":    0.0,
        "explorer":     explorer,
    }


async def _fetch_holdings_avax_glacier(
    client: httpx.AsyncClient,
    wallet: str,
    sem: asyncio.Semaphore,
) -> List[dict]:
    """Dùng Glacier API (Avalanche Foundation) — chính thức, free, không cần key."""
    GLACIER = "https://glacier-api.avax.network/v1/chains/43114/addresses"
    url = f"{GLACIER}/{wallet}/balances:listErc20?pageSize=100"
    results = []

    async with sem:
        while url:
            try:
                r = await client.get(url, timeout=20,
                                     headers={"Accept": "application/json"})
                if r.status_code in (400, 404, 422):
                    break
                r.raise_for_status()
                data = r.json()
            except Exception:
                break

            for tok in data.get("erc20TokenBalances", []):
                contract = tok.get("address", "") or ""
                name     = tok.get("name", "") or ""
                symbol   = tok.get("symbol", "") or ""
                decimals = int(tok.get("decimals") or 18)
                raw_val  = str(tok.get("balance", "0") or "0")
                row = _make_holding_row(wallet, "avax", name, symbol,
                                        contract, decimals, raw_val)
                if row:
                    results.append(row)

            next_token = data.get("nextPageToken")
            if next_token:
                url = f"{GLACIER}/{wallet}/balances:listErc20?pageSize=100&pageToken={next_token}"
            else:
                url = None

    return results


async def _fetch_holdings_for_wallet(
    client: httpx.AsyncClient,
    wallet: str,
    network: str,
    sem: asyncio.Semaphore,
) -> List[dict]:
    # Avalanche dùng Glacier API riêng (avalanche.blockscout.com không ổn định)
    if network == "avax":
        return await _fetch_holdings_avax_glacier(client, wallet, sem)

    base_url = BLOCKSCOUT[network]
    url = f"{base_url}/api/v2/addresses/{wallet}/tokens?type=ERC-20"
    results = []

    async with sem:
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
                token = item.get("token", {})
                name     = token.get("name", "") or ""
                symbol   = token.get("symbol", "") or ""

                _addr = (
                    token.get("address_hash")
                    or token.get("address")
                    or item.get("token_contract_address_hash")
                    or ""
                )
                if isinstance(_addr, dict):
                    contract = _addr.get("hash", "") or ""
                else:
                    contract = str(_addr) if _addr else ""

                decimals = int(token.get("decimals") or 18)
                raw_val  = item.get("value", "0") or "0"
                row = _make_holding_row(wallet, network, name, symbol,
                                        contract, decimals, raw_val)
                if row:
                    results.append(row)

            next_params = data.get("next_page_params")
            if next_params:
                qs = "&".join(f"{k}={v}" for k, v in next_params.items())
                url = f"{base_url}/api/v2/addresses/{wallet}/tokens?type=ERC-20&{qs}"
            else:
                url = None

    return results


async def run_holdings_job(jid: str, wallets: List[str], networks: List[str]) -> None:
    job = jobs[jid]
    total_tasks = len(wallets) * len(networks)
    job["total"] = total_tasks
    done = 0
    all_results: List[dict] = []

    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    sem = asyncio.Semaphore(10)

    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for wallet in wallets:
            wallet = wallet.strip()
            if not wallet:
                continue
            for net in networks:
                tasks.append((wallet, net))

        async def _one(wallet, net):
            nonlocal done
            rows = await _fetch_holdings_for_wallet(client, wallet, net, sem)
            all_results.extend(rows)
            done += 1
            job["progress"] = done

        await asyncio.gather(*[_one(w, n) for w, n in tasks])

    job["results"] = all_results
    job["status"]  = "done"


# ════════════════════════════════════════════════════════════════
# LP Checker — Direct RPC (query factory contracts on-chain)
# ════════════════════════════════════════════════════════════════

# Chain config: rpc + WETH address + V2 factory list
# factories: list of (dex_name, factory_address)
RPC_CFG: Dict[str, dict] = {
    "base": {
        "rpc":     "https://mainnet.base.org",
        "weth":    "0x4200000000000000000000000000000000000006",
        "symbol":  "WETH",
        "cg":      "ethereum",
        "explorer": "https://basescan.org/address/{pair}",
        "factories": [
            ("uniswap-v2",   "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"),
            ("aerodrome-v2", "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"),
            ("sushiswap",    "0x71524B4f93c58fcbF659783284E38825f0622859"),
            ("baseswap",     "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB"),
        ],
    },
    "avax": {
        "rpc":     "https://api.avax.network/ext/bc/C/rpc",
        "weth":    "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        "symbol":  "WAVAX",
        "cg":      "avalanche-2",
        "explorer": "https://snowscan.xyz/address/{pair}",
        "factories": [
            ("traderjoe",  "0x9Ad6C38BE94206cA50bb0d90783181662f0Cfa10"),
            ("pangolin",   "0xefa94DE7a4656D787667C749f7E1223D71E9FD88"),
        ],
    },
    "bsc": {
        "rpc":     "https://bsc-dataseed.binance.org",
        "weth":    "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "symbol":  "WBNB",
        "cg":      "binancecoin",
        "explorer": "https://bscscan.com/address/{pair}",
        "factories": [
            ("pancakeswap-v2", "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"),
            ("apeswap",        "0x0841BD0B734E4F5853f0dD8d7Ea041c241fb0Da6"),
        ],
    },
    "sonic": {
        "rpc":     "https://rpc.soniclabs.com",
        "weth":    "0x039e2fB66102314Ce7b64Ce5Ce3E5183bc94aD38",
        "symbol":  "wS",
        "cg":      "sonic-3",
        "explorer": "https://sonicscan.org/address/{pair}",
        "factories": [
            # ⚠️  BRO VERIFY 2 ĐỊA CHỈ NÀY TRÊN sonicscan.org TRƯỚC KHI DÙNG
            ("shadow",  "SHADOW_FACTORY_REPLACE_ME"),
            ("swapx",   "SWAPX_FACTORY_REPLACE_ME"),
        ],
    },
    "ethereum": {
        "rpc":     "https://cloudflare-eth.com",
        "weth":    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "symbol":  "WETH",
        "cg":      "ethereum",
        "explorer": "https://etherscan.io/address/{pair}",
        "factories": [
            ("uniswap-v2",  "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"),
            ("sushiswap",   "0xC0AEe478e3658e2610c5F7A4A2E1777cE9e4f2Ac"),
        ],
    },
}

# keep for handle_lp_start validation
CHAIN_SLUG = {k: k for k in RPC_CFG}

# Multicall3 — same address on all major EVM chains
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"

# ── ABI helpers ──────────────────────────────────────────────────

_SEL_GET_PAIR  = "e6a43905"   # getPair(address,address)
_SEL_RESERVES  = "0902f1ac"   # getReserves()
_SEL_TOKEN0    = "0dfe1681"   # token0()

def _enc_get_pair(token: str, weth: str) -> str:
    return "0x" + _SEL_GET_PAIR + token[2:].lower().zfill(64) + weth[2:].lower().zfill(64)

def _dec_addr(result: str) -> str:
    if not result or len(result) < 42:
        return ""
    a = "0x" + result[-40:]
    return "" if int(a, 16) == 0 else a

def _dec_addr_bytes(b: bytes) -> str:
    if len(b) < 32:
        return ""
    a = "0x" + b[-20:].hex()
    return "" if int(a, 16) == 0 else a

def _dec_reserves(result: str):
    if not result or len(result) < 130:
        return 0, 0
    d = result[2:]
    return int(d[:64], 16), int(d[64:128], 16)

def _dec_reserves_bytes(b: bytes):
    if len(b) < 64:
        return 0, 0
    return int.from_bytes(b[0:32], "big"), int.from_bytes(b[32:64], "big")


def _mc3_encode(calls: list) -> str:
    """Encode Multicall3.aggregate3((address,bool,bytes)[]) → 0x hex string.
    calls = [(target_hex, allow_failure_bool, calldata_hex), ...]
    """
    sel = bytes.fromhex("82ad56cb")
    n = len(calls)

    # Each struct: address(32) + bool(32) + offset_to_bytes(32) + len(32) + data(padded)
    # But ABI encodes the array with an outer offset pointer first
    struct_blobs = []
    for target, allow_fail, calldata in calls:
        cd = bytes.fromhex(calldata[2:] if calldata.startswith("0x") else calldata)
        pad = ((len(cd) + 31) // 32) * 32
        blob = (
            bytes.fromhex(target[2:].lower().zfill(64)) +          # address
            (b"\x00" * 31 + (b"\x01" if allow_fail else b"\x00")) + # bool
            (96).to_bytes(32, "big") +                               # offset to bytes = 3*32
            len(cd).to_bytes(32, "big") +                            # bytes length
            cd + b"\x00" * (pad - len(cd))                           # bytes data
        )
        struct_blobs.append(blob)

    # Build array: length + offsets + structs
    offsets = b""
    structs = b""
    cur = n * 32   # start of struct data after offset table
    for blob in struct_blobs:
        offsets += cur.to_bytes(32, "big")
        structs += blob
        cur += len(blob)

    array_body = n.to_bytes(32, "big") + offsets + structs
    # outer: pointer to array (= 32)
    args = (32).to_bytes(32, "big") + array_body
    return "0x" + (sel + args).hex()


def _mc3_decode(result_hex: str, n: int) -> list:
    """Returns list of (success: bool, return_data: bytes), length = n."""
    if not result_hex or result_hex in ("0x", ""):
        return [(False, b"")] * n
    try:
        raw = bytes.fromhex(result_hex[2:])
        outer_off = int.from_bytes(raw[0:32], "big")
        arr_len   = int.from_bytes(raw[outer_off: outer_off + 32], "big")
        base      = outer_off + 32
        results   = []
        for i in range(min(n, arr_len)):
            soff    = int.from_bytes(raw[base + i*32: base + i*32 + 32], "big")
            s       = base + soff
            success = bool(int.from_bytes(raw[s: s+32], "big"))
            bd_off  = int.from_bytes(raw[s+32: s+64], "big")
            bd_pos  = s + bd_off
            bd_len  = int.from_bytes(raw[bd_pos: bd_pos+32], "big")
            bd      = raw[bd_pos+32: bd_pos+32+bd_len]
            results.append((success, bd))
        while len(results) < n:
            results.append((False, b""))
        return results
    except Exception:
        return [(False, b"")] * n


async def _mc3_call(client: httpx.AsyncClient, rpc: str,
                    calls: list, sem: asyncio.Semaphore) -> list:
    """Single Multicall3 RPC call; returns decoded [(success, bytes), ...]."""
    payload = _mc3_encode(calls)
    async with sem:
        try:
            r = await client.post(rpc, json={
                "jsonrpc": "2.0", "method": "eth_call",
                "params": [{"to": MULTICALL3, "data": payload}, "latest"], "id": 1,
            }, timeout=30)
            result_hex = r.json().get("result", "0x")
        except Exception:
            result_hex = "0x"
    return _mc3_decode(result_hex, len(calls))


async def _get_native_prices(client: httpx.AsyncClient) -> Dict[str, float]:
    """CoinGecko prices cho native tokens."""
    try:
        r = await client.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=ethereum,avalanche-2,binancecoin,sonic-3&vs_currencies=usd",
            timeout=10,
        )
        d = r.json()
        return {
            "ethereum":    float((d.get("ethereum")    or {}).get("usd") or 3000),
            "avalanche-2": float((d.get("avalanche-2") or {}).get("usd") or 30),
            "binancecoin": float((d.get("binancecoin") or {}).get("usd") or 600),
            "sonic-3":     float((d.get("sonic-3")     or {}).get("usd") or 0.5),
        }
    except Exception:
        return {"ethereum": 3000, "avalanche-2": 30, "binancecoin": 600, "sonic-3": 0.5}


_MC3_BATCH = 500   # max calls per Multicall3 invocation


async def _scan_factory_mc3(
    client: httpx.AsyncClient,
    rpc: str,
    factory: str,
    dex_name: str,
    chain: str,
    weth: str,
    weth_sym: str,
    native_price: float,
    explorer_tpl: str,
    tokens: List[str],
    sem: asyncio.Semaphore,
) -> List[dict]:
    if not factory.startswith("0x") or len(factory) != 42:
        return []

    # ── Step 1: getPair for ALL tokens via Multicall3 ────────────
    get_pair_calls = [
        (factory, True, _enc_get_pair(tok, weth))
        for tok in tokens
    ]

    # Send in batches of _MC3_BATCH to stay within gas/size limits
    pair_decoded: list = []
    for i in range(0, len(get_pair_calls), _MC3_BATCH):
        batch = get_pair_calls[i: i + _MC3_BATCH]
        decoded = await _mc3_call(client, rpc, batch, sem)
        pair_decoded.extend(decoded)

    # Extract valid pair addresses
    found: List[tuple] = []
    for tok, (ok, data) in zip(tokens, pair_decoded):
        if ok and len(data) >= 32:
            addr = _dec_addr_bytes(data)
            if addr:
                found.append((tok, addr))

    if not found:
        return []

    # ── Step 2: getReserves + token0 for found pairs ─────────────
    rv_calls = [(pair, True, "0x" + _SEL_RESERVES) for _, pair in found]
    t0_calls = [(pair, True, "0x" + _SEL_TOKEN0)   for _, pair in found]
    combined = rv_calls + t0_calls

    combo_decoded: list = []
    for i in range(0, len(combined), _MC3_BATCH):
        batch = combined[i: i + _MC3_BATCH]
        decoded = await _mc3_call(client, rpc, batch, sem)
        combo_decoded.extend(decoded)

    mid = len(found)
    rv_decoded = combo_decoded[:mid]
    t0_decoded = combo_decoded[mid:]

    rows = []
    for (token, pair_addr), (rv_ok, rv_data), (t0_ok, t0_data) in zip(found, rv_decoded, t0_decoded):
        r0, r1 = _dec_reserves_bytes(rv_data) if rv_ok else (0, 0)
        token0 = _dec_addr_bytes(t0_data).lower() if t0_ok and len(t0_data) >= 32 else ""

        weth_raw = r0 if token0 == weth.lower() else r1
        weth_amt = weth_raw / 1e18
        weth_usd = round(weth_amt * native_price, 6)
        liq_usd  = round(weth_usd * 2, 4)

        rows.append({
            "address":      token,
            "name":         token[:10] + "...",
            "symbol":       "",
            "network":      chain,
            "dex":          dex_name,
            "pair_address": pair_addr,
            "weth_amt":     round(weth_amt, 8),
            "weth_usd":     weth_usd,
            "weth_symbol":  weth_sym,
            "liq_usd":      liq_usd,
            "price_usd":    0.0,
            "vol_24h":      0.0,
            "dexscreener":  explorer_tpl.format(pair=pair_addr),
        })
    return rows


async def run_lp_job(jid: str, addresses: List[str], networks: List[str]) -> None:
    job   = jobs[jid]
    addrs = [a.strip() for a in addresses if a.strip()]
    nets  = [n for n in networks if n in RPC_CFG]

    total = sum(len(RPC_CFG[n]["factories"]) for n in nets)
    job["total"]    = max(total, 1)
    job["progress"] = 0
    all_results: List[dict] = []

    # Low concurrency — each call is already a mega-batch
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    sem    = asyncio.Semaphore(5)

    async with httpx.AsyncClient(limits=limits) as client:
        native_prices = await _get_native_prices(client)

        for net in nets:
            cfg    = RPC_CFG[net]
            nprice = native_prices.get(cfg["cg"], 1.0)

            for dex_name, factory in cfg["factories"]:
                rows = await _scan_factory_mc3(
                    client, cfg["rpc"], factory, dex_name, net,
                    cfg["weth"], cfg["symbol"], nprice,
                    cfg["explorer"], addrs, sem,
                )
                all_results.extend(rows)
                job["progress"] += 1

    # Deduplicate same token+pair
    seen, unique = set(), []
    for r in all_results:
        k = (r["address"].lower(), r["pair_address"].lower())
        if k not in seen:
            seen.add(k)
            unique.append(r)

    unique.sort(key=lambda r: -r["liq_usd"])

    for idx, row in enumerate(unique, 1):
        row["no"] = idx

    job["results"] = unique
    job["status"]  = "done"


# ════════════════════════════════════════════════════════════════
# HTTP handlers
# ════════════════════════════════════════════════════════════════

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html")


async def handle_holdings_start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    raw_wallets = body.get("wallets", "")
    wallets = [w.strip() for w in raw_wallets.replace(",", "\n").splitlines() if w.strip()]
    networks = [n for n in body.get("networks", []) if n in BLOCKSCOUT]

    if not wallets:
        return web.json_response({"ok": False, "error": "No wallets provided"}, status=400)
    if not networks:
        return web.json_response({"ok": False, "error": "No networks selected"}, status=400)

    jid = new_job()
    asyncio.create_task(run_holdings_job(jid, wallets, networks))
    return web.json_response({"ok": True, "job_id": jid})


async def handle_lp_start(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    raw_addrs = body.get("addresses", "")
    addresses = [a.strip() for a in raw_addrs.replace(",", "\n").splitlines() if a.strip()]
    networks  = [n for n in body.get("networks", []) if n in CHAIN_SLUG]

    if not addresses:
        return web.json_response({"ok": False, "error": "No addresses provided"}, status=400)
    if not networks:
        return web.json_response({"ok": False, "error": "No networks selected"}, status=400)

    jid = new_job()
    asyncio.create_task(run_lp_job(jid, addresses, networks))
    return web.json_response({"ok": True, "job_id": jid})


async def handle_job_status(request: web.Request) -> web.Response:
    jid = request.match_info["job_id"]
    job = _job(jid)
    if not job:
        return web.json_response({"ok": False, "error": "Job not found"}, status=404)
    return web.json_response({
        "ok":       True,
        "status":   job["status"],
        "progress": job["progress"],
        "total":    job["total"],
        "count":    len(job["results"]),
        "error":    job["error"],
    })


async def handle_job_results(request: web.Request) -> web.Response:
    jid = request.match_info["job_id"]
    job = _job(jid)
    if not job:
        return web.json_response({"ok": False, "error": "Job not found"}, status=404)
    return web.json_response({"ok": True, "results": job["results"]})


async def handle_debug_holdings(request: web.Request) -> web.Response:
    """GET /debug/holdings?wallet=0x...&network=avax  — trả raw JSON từ API"""
    wallet  = request.rel_url.query.get("wallet", "").strip()
    network = request.rel_url.query.get("network", "base").strip()
    if not wallet:
        return web.json_response({"error": "?wallet=0x... required"})
    if network not in BLOCKSCOUT and network != "avax":
        return web.json_response({"error": f"unknown network {network}"})

    async with httpx.AsyncClient(timeout=20) as client:
        if network == "avax":
            url = f"https://glacier-api.avax.network/v1/chains/43114/addresses/{wallet}/balances:listErc20?pageSize=10"
            try:
                r    = await client.get(url, headers={"Accept": "application/json"})
                data = r.json()
            except Exception as e:
                return web.json_response({"error": str(e)})
            items = data.get("erc20TokenBalances", [])
            return web.json_response({
                "url": url, "status": r.status_code,
                "total_items": len(items),
                "sample": items[:3],
            })
        else:
            url = f"{BLOCKSCOUT[network]}/api/v2/addresses/{wallet}/tokens?type=ERC-20"
            try:
                r    = await client.get(url)
                data = r.json()
            except Exception as e:
                return web.json_response({"error": str(e)})
            items = data.get("items", [])
            sample = []
            for item in items[:3]:
                tok = item.get("token", {})
                sample.append({
                    "raw_token_keys": list(tok.keys()),
                    "raw_address_field": tok.get("address"),
                    "name": tok.get("name"),
                    "symbol": tok.get("symbol"),
                })
            return web.json_response({"url": url, "total_items": len(items), "sample": sample})


# ════════════════════════════════════════════════════════════════
# HTML Dashboard
# ════════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Token Scanner</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0d;color:#e0e0e0;font-family:'Segoe UI',sans-serif;font-size:14px}
header{background:#111;border-bottom:1px solid #222;padding:12px 24px;display:flex;align-items:center;gap:16px}
header h1{font-size:17px;color:#00c8ff;white-space:nowrap}
.tabs{display:flex;gap:2px;background:#0d0d0d;border-bottom:1px solid #222;padding:0 24px}
.tab{padding:10px 20px;cursor:pointer;color:#888;border-bottom:2px solid transparent;font-size:13px;transition:.15s}
.tab.active{color:#00c8ff;border-bottom-color:#00c8ff}
.tab:hover:not(.active){color:#ccc}
.panel{display:none;padding:20px 24px}
.panel.active{display:block}
.card{background:#141414;border:1px solid #222;border-radius:8px;padding:18px;margin-bottom:16px}
.card h3{font-size:13px;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}
textarea,input[type=text]{width:100%;background:#0d0d0d;border:1px solid #333;color:#e0e0e0;
  border-radius:6px;padding:9px 12px;font-size:13px;font-family:monospace;outline:none;resize:vertical}
textarea:focus,input[type=text]:focus{border-color:#00c8ff}
.chains{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px}
.chain-cb{display:flex;align-items:center;gap:6px;cursor:pointer;
  background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;padding:6px 12px;user-select:none}
.chain-cb input{accent-color:#00c8ff;cursor:pointer}
.chain-cb:hover{border-color:#444}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:12px}
.btn{padding:8px 20px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;transition:.15s}
.btn-blue{background:#00c8ff;color:#000}.btn-blue:hover{background:#00b0e0}
.btn-green{background:#00c853;color:#000}.btn-green:hover{background:#00b048}
.btn-red{background:#e53935;color:#fff}.btn-red:hover{background:#c62828}
.btn:disabled{opacity:.4;cursor:not-allowed}
.progress-bar{height:4px;background:#1a1a1a;border-radius:4px;overflow:hidden;margin-top:10px}
.progress-fill{height:100%;background:#00c8ff;border-radius:4px;transition:width .3s}
.status-line{font-size:12px;color:#888;margin-top:6px}
.status-line.ok{color:#00c853}.status-line.err{color:#ff3d3d}
.tbl-wrap{overflow-x:auto;margin-top:8px;max-height:520px;overflow-y:auto}
table{width:100%;border-collapse:collapse;font-size:12px}
thead{position:sticky;top:0;z-index:1}
thead tr{background:#1a1a1a}
th{padding:7px 10px;text-align:left;color:#777;font-weight:600;border-bottom:1px solid #222;white-space:nowrap}
td{padding:6px 10px;border-bottom:1px solid #191919;font-family:monospace}
tr:hover td{background:#181818}
td a{color:#00c8ff;text-decoration:none}td a:hover{text-decoration:underline}
.badge{display:inline-block;padding:1px 7px;border-radius:4px;font-size:10px;font-weight:700}
.badge-base{background:#1a3a6a;color:#6ab0ff}
.badge-avax{background:#3a1a1a;color:#ff6060}
.badge-bsc{background:#2a2400;color:#f0c000}
.badge-sonic{background:#1a2a1a;color:#60c060}
.badge-ethereum{background:#1a1a3a;color:#9090ff}
.result-count{color:#888;font-size:12px;margin-top:6px}
</style>
</head>
<body>

<header>
  <h1>&#127880; Token Scanner</h1>
  <span style="color:#555;font-size:12px">Holdings &amp; LP Checker</span>
</header>

<div class="tabs">
  <div class="tab active" onclick="switchTab('holdings')">&#128202; Token Holdings</div>
  <div class="tab" onclick="switchTab('lp')">&#128199; LP Check</div>
</div>

<!-- ═══ TAB 1: Holdings ═══ -->
<div class="panel active" id="tab-holdings">

  <div class="card">
    <h3>Wallet Addresses</h3>
    <textarea id="h-wallets" rows="5" placeholder="One wallet address per line (or comma-separated)"></textarea>
    <h3 style="margin-top:14px">Networks</h3>
    <div class="chains" id="h-chains">
      <label class="chain-cb"><input type="checkbox" value="base" checked> Base</label>
      <label class="chain-cb"><input type="checkbox" value="avax" checked> Avalanche</label>
      <label class="chain-cb"><input type="checkbox" value="bsc" checked> BSC</label>
      <label class="chain-cb"><input type="checkbox" value="sonic" checked> Sonic</label>
      <label class="chain-cb"><input type="checkbox" value="ethereum" checked> Ethereum</label>
    </div>
    <div class="row">
      <button class="btn btn-blue" id="h-start-btn" onclick="startHoldings()">&#9889; Scan</button>
      <button class="btn btn-red" id="h-stop-btn" onclick="stopJob('h')" style="display:none">&#9632; Stop</button>
      <button class="btn btn-green" id="h-export-btn" onclick="exportHoldings()" style="display:none">&#8595; Export CSV</button>
    </div>
    <div class="progress-bar" id="h-pbar" style="display:none"><div class="progress-fill" id="h-pfill" style="width:0%"></div></div>
    <div class="status-line" id="h-status"></div>
  </div>

  <div class="card" id="h-result-card" style="display:none">
    <h3>Results <span class="result-count" id="h-count"></span></h3>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>Wallet</th><th>Network</th><th>Token</th><th>Symbol</th>
          <th>Contract</th><th>Balance</th><th>Price USD</th><th>Value USD</th><th>Explorer</th>
        </tr></thead>
        <tbody id="h-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ═══ TAB 2: LP Check ═══ -->
<div class="panel" id="tab-lp">

  <div class="card">
    <h3>Token Contract Addresses</h3>
    <textarea id="lp-addrs" rows="5" placeholder="One contract address per line (or comma-separated)"></textarea>
    <h3 style="margin-top:14px">Networks</h3>
    <div class="chains" id="lp-chains">
      <label class="chain-cb"><input type="checkbox" value="base" checked> Base</label>
      <label class="chain-cb"><input type="checkbox" value="avax" checked> Avalanche</label>
      <label class="chain-cb"><input type="checkbox" value="bsc" checked> BSC</label>
      <label class="chain-cb"><input type="checkbox" value="sonic" checked> Sonic</label>
      <label class="chain-cb"><input type="checkbox" value="ethereum" checked> Ethereum</label>
    </div>
    <div class="row">
      <button class="btn btn-blue" id="lp-start-btn" onclick="startLP()">&#9889; Check LP</button>
      <button class="btn btn-red" id="lp-stop-btn" onclick="stopJob('lp')" style="display:none">&#9632; Stop</button>
      <button class="btn btn-green" id="lp-export-btn" onclick="exportLP()" style="display:none">&#8595; Export CSV</button>
    </div>
    <div class="progress-bar" id="lp-pbar" style="display:none"><div class="progress-fill" id="lp-pfill" style="width:0%"></div></div>
    <div class="status-line" id="lp-status"></div>
  </div>

  <div class="card" id="lp-result-card" style="display:none">
    <h3>Results <span class="result-count" id="lp-count"></span></h3>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>Address</th><th>Name</th><th>Symbol</th><th>Network</th>
          <th>DEX</th><th>Pair</th><th>WETH Amt</th><th>WETH USD</th><th>Native</th>
          <th>Liq USD</th><th>Price USD</th><th>Vol 24h</th><th>DexScreener</th>
        </tr></thead>
        <tbody id="lp-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
var _hResults = [];
var _lpResults = [];
var _hTimer = null;
var _lpTimer = null;
var _hJobId = null;
var _lpJobId = null;
var _hStopped = false;
var _lpStopped = false;

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(function(t,i){ t.classList.toggle('active', i === (name==='holdings'?0:1)); });
  document.getElementById('tab-holdings').classList.toggle('active', name==='holdings');
  document.getElementById('tab-lp').classList.toggle('active', name==='lp');
}

function getChecked(containerId) {
  var boxes = document.querySelectorAll('#' + containerId + ' input[type=checkbox]:checked');
  return Array.from(boxes).map(function(b){ return b.value; });
}

// ── Holdings ──────────────────────────────────────────────────

async function startHoldings() {
  var wallets  = document.getElementById('h-wallets').value.trim();
  var networks = getChecked('h-chains');
  if (!wallets) { setStatus('h', 'Enter at least one wallet address.', 'err'); return; }
  if (!networks.length) { setStatus('h', 'Select at least one network.', 'err'); return; }

  _hStopped = false;
  _hResults = [];
  document.getElementById('h-start-btn').disabled = true;
  document.getElementById('h-stop-btn').style.display = '';
  document.getElementById('h-export-btn').style.display = 'none';
  document.getElementById('h-pbar').style.display = '';
  document.getElementById('h-pfill').style.width = '0%';
  document.getElementById('h-result-card').style.display = 'none';
  setStatus('h', 'Starting scan...', '');

  try {
    var r = await fetch('/api/holdings/start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({wallets: wallets, networks: networks})
    });
    var d = await r.json();
    if (!d.ok) throw new Error(d.error);
    _hJobId = d.job_id;
    _hTimer = setInterval(function(){ pollJob('h'); }, 1200);
  } catch(e) {
    setStatus('h', 'Error: ' + e.message, 'err');
    document.getElementById('h-start-btn').disabled = false;
    document.getElementById('h-stop-btn').style.display = 'none';
  }
}

async function pollJob(prefix) {
  var jobId = prefix === 'h' ? _hJobId : _lpJobId;
  if (!jobId) return;
  try {
    var r = await fetch('/api/job/' + jobId);
    var d = await r.json();
    if (!d.ok) return;

    var pct = d.total > 0 ? Math.round(d.progress / d.total * 100) : 0;
    document.getElementById(prefix + '-pfill').style.width = pct + '%';
    setStatus(prefix, 'Progress: ' + d.progress + ' / ' + d.total + ' (' + d.count + ' results)', '');

    if (d.status === 'done' || (prefix==='h' ? _hStopped : _lpStopped)) {
      clearInterval(prefix === 'h' ? _hTimer : _lpTimer);
      var res = await fetch('/api/job/' + jobId + '/results');
      var rd  = await res.json();
      if (prefix === 'h') {
        _hResults = rd.results;
        renderHoldings(_hResults);
        setStatus('h', 'Done — ' + _hResults.length + ' token holdings found.', 'ok');
        document.getElementById('h-export-btn').style.display = _hResults.length ? '' : 'none';
      } else {
        _lpResults = rd.results;
        renderLP(_lpResults);
        setStatus('lp', 'Done — ' + _lpResults.length + ' LP pairs found.', 'ok');
        document.getElementById('lp-export-btn').style.display = _lpResults.length ? '' : 'none';
      }
      document.getElementById(prefix + '-start-btn').disabled = false;
      document.getElementById(prefix + '-stop-btn').style.display = 'none';
    }
  } catch(e) {}
}

function stopJob(prefix) {
  if (prefix === 'h') _hStopped = true; else _lpStopped = true;
}

function renderHoldings(rows) {
  var BADGE = {base:'badge-base',avax:'badge-avax',bsc:'badge-bsc',sonic:'badge-sonic',ethereum:'badge-ethereum'};
  var tbody = document.getElementById('h-tbody');
  tbody.innerHTML = rows.map(function(r) {
    var badge = '<span class="badge ' + (BADGE[r.network]||'') + '">' + r.network + '</span>';
    return '<tr><td>' + short(r.wallet) + '</td><td>' + badge + '</td><td>' + esc(r.token_name) +
      '</td><td>' + esc(r.token_symbol) + '</td><td>' + short(r.contract) + '</td><td>' +
      r.balance + '</td><td>' + (r.price_usd||0) + '</td><td>' + (r.value_usd||0) +
      '</td><td>' + (r.explorer ? '<a href="'+esc(r.explorer)+'" target="_blank">View</a>' : '') +
      '</td></tr>';
  }).join('');
  document.getElementById('h-count').textContent = '— ' + rows.length + ' rows';
  document.getElementById('h-result-card').style.display = '';
}

function renderLP(rows) {
  var BADGE = {base:'badge-base',avax:'badge-avax',bsc:'badge-bsc',sonic:'badge-sonic',ethereum:'badge-ethereum'};
  var tbody = document.getElementById('lp-tbody');
  tbody.innerHTML = rows.map(function(r) {
    var badge = '<span class="badge ' + (BADGE[r.network]||'') + '">' + r.network + '</span>';
    return '<tr><td>' + (r.no||'') + '</td><td>' + short(r.address) + '</td><td>' + esc(r.name) +
      '</td><td>' + esc(r.symbol) + '</td><td>' + badge + '</td><td>' + esc(r.dex) +
      '</td><td>' + short(r.pair_address) + '</td><td>' + r.weth_amt + '</td><td>' + r.weth_usd +
      '</td><td>' + esc(r.weth_symbol) + '</td><td>$' + r.liq_usd + '</td><td>$' + r.price_usd +
      '</td><td>$' + r.vol_24h + '</td><td>' +
      (r.dexscreener ? '<a href="'+esc(r.dexscreener)+'" target="_blank">DS</a>' : '') +
      '</td></tr>';
  }).join('');
  document.getElementById('lp-count').textContent = '— ' + rows.length + ' rows';
  document.getElementById('lp-result-card').style.display = '';
}

// ── LP ───────────────────────────────────────────────────────

async function startLP() {
  var addrs    = document.getElementById('lp-addrs').value.trim();
  var networks = getChecked('lp-chains');
  if (!addrs) { setStatus('lp', 'Enter at least one contract address.', 'err'); return; }
  if (!networks.length) { setStatus('lp', 'Select at least one network.', 'err'); return; }

  _lpStopped = false;
  _lpResults = [];
  document.getElementById('lp-start-btn').disabled = true;
  document.getElementById('lp-stop-btn').style.display = '';
  document.getElementById('lp-export-btn').style.display = 'none';
  document.getElementById('lp-pbar').style.display = '';
  document.getElementById('lp-pfill').style.width = '0%';
  document.getElementById('lp-result-card').style.display = 'none';
  setStatus('lp', 'Starting LP check...', '');

  try {
    var r = await fetch('/api/lp/start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({addresses: addrs, networks: networks})
    });
    var d = await r.json();
    if (!d.ok) throw new Error(d.error);
    _lpJobId = d.job_id;
    _lpTimer = setInterval(function(){ pollJob('lp'); }, 1200);
  } catch(e) {
    setStatus('lp', 'Error: ' + e.message, 'err');
    document.getElementById('lp-start-btn').disabled = false;
    document.getElementById('lp-stop-btn').style.display = 'none';
  }
}

// ── CSV Export ────────────────────────────────────────────────

function exportHoldings() {
  if (!_hResults.length) return;
  var header = 'wallet,network,token_name,token_symbol,contract,balance,price_usd,value_usd,explorer\n';
  var rows = _hResults.map(function(r) {
    return '"'+r.wallet+'","'+r.network+'","'+esc2(r.token_name)+'","'+esc2(r.token_symbol)+
      '","'+r.contract+'",'+r.balance+','+r.price_usd+','+r.value_usd+',"'+esc2(r.explorer)+'"';
  }).join('\n');
  downloadCsv(header+rows, 'holdings_'+Date.now()+'.csv');
}

function exportLP() {
  if (!_lpResults.length) return;
  var header = 'no,address,name,symbol,network,dex,pair_address,weth_amt,weth_usd,weth_symbol,liq_usd,price_usd,vol_24h,dexscreener\n';
  var rows = _lpResults.map(function(r) {
    return '"'+(r.no||'')+'","'+r.address+'","'+esc2(r.name)+'","'+esc2(r.symbol)+
      '","'+r.network+'","'+esc2(r.dex)+'","'+r.pair_address+'","'+r.weth_amt+
      '","'+r.weth_usd+'","'+r.weth_symbol+'","'+r.liq_usd+'","'+r.price_usd+
      '","'+r.vol_24h+'","'+esc2(r.dexscreener)+'"';
  }).join('\n');
  downloadCsv(header+rows, 'lp_check_'+Date.now()+'.csv');
}

function downloadCsv(content, filename) {
  var blob = new Blob([content], {type:'text/csv'});
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ── Helpers ───────────────────────────────────────────────────

function setStatus(prefix, msg, cls) {
  var el = document.getElementById(prefix + '-status');
  el.textContent = msg; el.className = 'status-line' + (cls ? ' '+cls : '');
}

function short(s) {
  if (!s || s.length <= 16) return s;
  return s.slice(0,8)+'...'+s.slice(-6);
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function esc2(s) {
  if (!s) return '';
  return String(s).replace(/"/g,'""');
}
</script>
</body>
</html>
"""


# ════════════════════════════════════════════════════════════════
# App wiring
# ════════════════════════════════════════════════════════════════

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/",                       handle_index)
    app.router.add_post("/api/holdings/start",    handle_holdings_start)
    app.router.add_post("/api/lp/start",          handle_lp_start)
    app.router.add_get("/api/job/{job_id}",       handle_job_status)
    app.router.add_get("/api/job/{job_id}/results", handle_job_results)
    app.router.add_get("/debug/holdings",           handle_debug_holdings)
    return app


if __name__ == "__main__":
    PORT = 5012
    print("=" * 60)
    print("  Token Scanner — Holdings & LP Checker")
    print(f"  Dashboard : http://localhost:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    web.run_app(build_app(), host="0.0.0.0", port=PORT, access_log=None)
