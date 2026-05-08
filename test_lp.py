#!/usr/bin/env python3
"""
test_lp.py — Kiểm tra DexScreener batch API
Chạy: python test_lp.py
Paste vài địa chỉ token vào ADDRS bên dưới
"""
import asyncio, json, httpx

# ← Paste địa chỉ token thật từ danh sách 500 token của bro vào đây
ADDRS = [
    "0xcD09cAF2901d81c53aFd5De8bf74f10fb199a8bc",
    "0xb8D98a102b0079B69FFbc760C8d857A31653e56e",
    "0x5Efc4446E1D772428adBD6053a0421Ca7B3Ed85A",
]

NETWORKS_SELECTED = ["base", "avax", "bsc", "sonic", "ethereum"]

_DS_TO_NET = {
    "base": "base", "avalanche": "avax", "bsc": "bsc",
    "sonic": "sonic", "soniclabs": "sonic", "ethereum": "ethereum",
}

async def main():
    addr_str = ",".join(ADDRS[:30])
    url = f"https://api.dexscreener.com/latest/dex/tokens/{addr_str}"
    print(f"URL: {url}\n")

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(url)
        print(f"Status: {r.status_code}")
        data = r.json()

    pairs = data.get("pairs") or []
    print(f"Total pairs returned: {len(pairs)}\n")

    if not pairs:
        print("DexScreener returned 0 pairs for these addresses.")
        print("Raw response:")
        print(json.dumps(data, indent=2)[:2000])
        return

    # In chi tiết từng pair
    for i, p in enumerate(pairs):
        chain  = p.get("chainId", "?")
        net    = _DS_TO_NET.get(chain.lower(), chain)
        base   = (p.get("baseToken")  or {})
        quote  = (p.get("quoteToken") or {})
        liq    = p.get("liquidity") or {}
        print(f"[{i}] chain={chain} net={net} | "
              f"{base.get('symbol','?')}/{quote.get('symbol','?')} | "
              f"dex={p.get('dexId','?')} | "
              f"liq.usd={liq.get('usd')} liq.base={liq.get('base')} liq.quote={liq.get('quote')} | "
              f"filtered_out={net not in NETWORKS_SELECTED}")

asyncio.run(main())
