#!/usr/bin/env python3
"""
test_mc3.py — Kiểm tra Multicall3 batch getPair trên Base
Chạy: python test_mc3.py
"""
import asyncio, json, httpx

RPC      = "https://mainnet.base.org"
MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"
FACTORY_UV2 = "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6"   # Uniswap v2 on Base
WETH    = "0x4200000000000000000000000000000000000006"

# Dùng 10 token đầu từ danh sách 500 token Base của bro
TOKENS = [
    "0xcD09cAF2901d81c53aFd5De8bf74f10fb199a8bc",
    "0xb8D98a102b0079B69FFbc760C8d857A31653e56e",
    "0x5Efc4446E1D772428adBD6053a0421Ca7B3Ed85A",
    "0x4ed4e862860bed51a9570b96d89af5e1b0efefed",   # DEGEN — known to have LP
    "0x0578d8A44db98B23BF096A382e016e29a5Ce0ffe",   # HIGHER — known to have LP
    "0x2Da56AcB9Ea78330f947bD57C54119Debda7AF71",
    "0x3C281A39944a2319aA653D81Cfd93Ca10983D234",
    "0x7d89e05C0B93B24B5Cb23A073E60D008FEd1aCe7",
    "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",   # DAI — well known
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # USDC — should have LP
]

_SEL_GET_PAIR = "e6a43905"

def _enc_get_pair(token, weth):
    return "0x" + _SEL_GET_PAIR + token[2:].lower().zfill(64) + weth[2:].lower().zfill(64)

def _mc3_encode(calls):
    sel = bytes.fromhex("82ad56cb")
    n = len(calls)
    struct_blobs = []
    for target, allow_fail, calldata in calls:
        cd = bytes.fromhex(calldata[2:] if calldata.startswith("0x") else calldata)
        pad = ((len(cd) + 31) // 32) * 32
        blob = (
            bytes.fromhex(target[2:].lower().zfill(64)) +
            (b"\x00" * 31 + (b"\x01" if allow_fail else b"\x00")) +
            (96).to_bytes(32, "big") +
            len(cd).to_bytes(32, "big") +
            cd + b"\x00" * (pad - len(cd))
        )
        struct_blobs.append(blob)
    offsets = b""
    structs = b""
    cur = n * 32
    for blob in struct_blobs:
        offsets += cur.to_bytes(32, "big")
        structs += blob
        cur += len(blob)
    array_body = n.to_bytes(32, "big") + offsets + structs
    args = (32).to_bytes(32, "big") + array_body
    return "0x" + (sel + args).hex()

def _mc3_decode(result_hex, n):
    if not result_hex or result_hex in ("0x", ""):
        return [(False, b"")] * n
    try:
        raw = bytes.fromhex(result_hex[2:])
        outer_off = int.from_bytes(raw[0:32], "big")
        arr_len   = int.from_bytes(raw[outer_off: outer_off+32], "big")
        base      = outer_off + 32
        results   = []
        for i in range(min(n, arr_len)):
            soff    = int.from_bytes(raw[base+i*32: base+i*32+32], "big")
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
    except Exception as e:
        print(f"decode error: {e}")
        return [(False, b"")] * n

def _dec_addr_bytes(b):
    if len(b) < 32:
        return ""
    a = "0x" + b[-20:].hex()
    return "" if int(a, 16) == 0 else a

async def main():
    calls = [(FACTORY_UV2, True, _enc_get_pair(tok, WETH)) for tok in TOKENS]
    payload = _mc3_encode(calls)
    print(f"Payload size: {len(payload)//2} bytes, {len(calls)} calls")

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(RPC, json={
            "jsonrpc": "2.0", "method": "eth_call",
            "params": [{"to": MULTICALL3, "data": payload}, "latest"], "id": 1,
        })
        resp = r.json()

    result_hex = resp.get("result", "0x")
    print(f"Response status: {r.status_code}")
    if "error" in resp:
        print(f"RPC error: {resp['error']}")
        return

    decoded = _mc3_decode(result_hex, len(calls))
    print(f"\nDecoded {len(decoded)} results:\n")
    found = 0
    for i, (tok, (ok, data)) in enumerate(zip(TOKENS, decoded)):
        addr = _dec_addr_bytes(data) if ok and len(data) >= 32 else ""
        status = f"PAIR: {addr}" if addr else ("null (no LP)" if ok else "FAILED")
        print(f"  [{i}] {tok[:18]}... -> {status}")
        if addr:
            found += 1

    print(f"\nFound {found}/{len(TOKENS)} pairs on Uniswap V2 (Base)")

asyncio.run(main())
