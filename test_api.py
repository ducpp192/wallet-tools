#!/usr/bin/env python3
"""
test_api.py — Kiểm tra raw JSON từ Blockscout API
Chạy: python test_api.py
"""
import asyncio
import json
import httpx

WALLET  = "0x457e800eE4ee8a774B1aBae2fe290cAce5946954"
NETWORK = "base"
BASE_URL = "https://base.blockscout.com"

async def main():
    url = f"{BASE_URL}/api/v2/addresses/{WALLET}/tokens?type=ERC-20"
    print(f"URL: {url}\n")

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        print(f"Status: {r.status_code}\n")
        data = r.json()

    items = data.get("items", [])
    print(f"Total items: {len(items)}\n")

    if not items:
        print("No items returned!")
        return

    # In raw JSON của item đầu tiên
    print("=== RAW item[0] ===")
    print(json.dumps(items[0], indent=2))
    print()

    # Phân tích các keys
    item0 = items[0]
    tok   = item0.get("token", {})
    print("=== Keys at item level ===")
    print(list(item0.keys()))
    print()
    print("=== Keys inside token ===")
    print(list(tok.keys()))
    print()
    print("=== token.address value ===")
    print(repr(tok.get("address")))

asyncio.run(main())
