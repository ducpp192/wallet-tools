#!/usr/bin/env python3
"""
sweep_server.py — Multi-chain Sweeper (EVM + Sui + TON)
Dashboard: http://localhost:5015
"""
import asyncio, sys, time, uuid, base64, hashlib
from typing import Dict, List

_missing = []
for _pkg, _spec in [
    ("aiohttp",     "aiohttp>=3.9.0"),
    ("httpx",       "httpx>=0.27.0"),
    ("eth_account", "eth-account>=0.10.0"),
    ("nacl",        "pynacl>=1.5.0"),
    ("tonsdk",      "tonsdk>=0.0.16"),
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
from eth_account import Account
from eth_utils import to_checksum_address
from nacl.signing import SigningKey as _NaClSigningKey
from tonsdk.contract.wallet import WalletV4ContractR2 as _TonWalletV4R2
from tonsdk.utils import bytes_to_b64str as _ton_to_b64

# ── Chain config ─────────────────────────────────────────────────
GAS_LIMIT = 21_000

CHAINS = {
    "base": {
        "name": "Base", "chain_id": 8453, "symbol": "ETH", "tx_type": 2,
        "color": "#0052ff",
        "rpcs": [
            "https://mainnet.base.org",
            "https://base.llamarpc.com",
            "https://base-rpc.publicnode.com",
            "https://base-mainnet.public.blastapi.io",
            "https://rpc.ankr.com/base",
        ],
        "explorer": "https://basescan.org/tx/{}",
    },
    "bsc": {
        "name": "BSC", "chain_id": 56, "symbol": "BNB", "tx_type": 0,
        "color": "#f0b90b",
        "rpcs": [
            "https://bsc-dataseed.binance.org",
            "https://bsc-dataseed1.defibit.io",
            "https://bsc-dataseed1.ninicoin.io",
            "https://bsc-rpc.publicnode.com",
            "https://rpc.ankr.com/bsc",
        ],
        "explorer": "https://bscscan.com/tx/{}",
    },
    "ethereum": {
        "name": "Ethereum", "chain_id": 1, "symbol": "ETH", "tx_type": 2,
        "color": "#627eea",
        "rpcs": [
            "https://eth.llamarpc.com",
            "https://ethereum.publicnode.com",
            "https://rpc.ankr.com/eth",
            "https://cloudflare-eth.com",
            "https://eth-mainnet.public.blastapi.io",
        ],
        "explorer": "https://etherscan.io/tx/{}",
    },
    "avalanche": {
        "name": "Avalanche", "chain_id": 43114, "symbol": "AVAX", "tx_type": 2,
        "color": "#e84142",
        "rpcs": [
            "https://api.avax.network/ext/bc/C/rpc",
            "https://avalanche.public-rpc.com",
            "https://avax.meowrpc.com",
            "https://rpc.ankr.com/avalanche",
            "https://avalanche-c-chain-rpc.publicnode.com",
        ],
        "explorer": "https://snowscan.xyz/tx/{}",
    },
    "sonic": {
        "name": "Sonic", "chain_id": 146, "symbol": "S", "tx_type": 2,
        "color": "#00e5b0",
        "rpcs": [
            "https://rpc.soniclabs.com",
            "https://sonic.drpc.org",
            "https://sonic-rpc.publicnode.com",
            "https://rpc.ankr.com/sonic",
        ],
        "explorer": "https://sonicscan.org/tx/{}",
    },
    "pulse": {
        "name": "PulseChain", "chain_id": 369, "symbol": "PLS", "tx_type": 2,
        "color": "#b44aff",
        "rpcs": [
            "https://rpc.pulsechain.com",
            "https://pulsechain.publicnode.com",
            "https://rpc-pulsechain.g4mm4.io",
            "https://pulsechain.drpc.org",
        ],
        "explorer": "https://scan.pulsechain.com/tx/{}",
    },
    "arbitrum": {
        "name": "Arbitrum", "chain_id": 42161, "symbol": "ETH", "tx_type": 2,
        "color": "#28a0f0",
        "rpcs": [
            "https://arb1.arbitrum.io/rpc",
            "https://arbitrum.llamarpc.com",
            "https://arbitrum-one-rpc.publicnode.com",
            "https://rpc.ankr.com/arbitrum",
            "https://arbitrum-mainnet.public.blastapi.io",
        ],
        "explorer": "https://arbiscan.io/tx/{}",
    },
    "sui": {
        "name": "Sui", "chain_id": None, "symbol": "SUI", "tx_type": -1,
        "color": "#4da2ff",
        "rpcs": [
            "https://fullnode.mainnet.sui.io",
            "https://sui-rpc.publicnode.com",
            "https://sui.drpc.org",
            "https://rpc.ankr.com/sui",
        ],
        "explorer": "https://suiscan.xyz/mainnet/tx/{}",
    },
    "ton": {
        "name": "TON", "chain_id": None, "symbol": "TON", "tx_type": -3,
        "color": "#0088cc",
        "rpcs": [
            "https://toncenter.com/api/v2",
            "https://ton.access.orbs.network/route/v1/mainnet/toncenter",
        ],
        # tonapi.io — dùng để check balance (rate limit cao hơn toncenter)
        "tonapi": "https://tonapi.io/v2",
        "explorer": "https://tonscan.org/tx/{}",
    },
}

# ── Sui constants ─────────────────────────────────────────────────
SUI_GAS_BUDGET_MIST = 20_000_000   # 0.02 SUI per tx
SUI_TOKEN_TYPES = [
    "0x549e8b69270defbfafd4f94e17ec44cdbdd99820b33bda2278dea3b9a32d3f55::cert::CERT",
    "0xa99b8952d4f7d947ea77fe0ecdcc9e5fc0bcab2841d6e2a5aa00c3044e5544b5::navx::NAVX",
    "0x356a26eb9e012a68958082340d4c4116e7f55615cf27affcff209cf0ae544f59::wal::WAL",
    "0x5145494a5f5100e645e4b0aa950fa6b68f614e8c59e17bc5ded3495123a79178::ns::NS",
    "0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC",
    "0x8b4d553839b219c3fd47608a0cc3d5fcc572cb25d41b7df3833208586a8d2470::hawal::HAWAL",
    "0xdeeb7a4662eec9f2f3def03fb937a663dddaa2e215b8078a284d026b7946c270::deep::DEEP",
]

# ── bech32m decoder (inline — for suiprivkey1... format) ─────────
_B32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_B32M_CONST  = 0x2bc830a3

def _b32m_polymod(vals):
    GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for v in vals:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= GEN[i] if (b >> i) & 1 else 0
    return chk

def _b32m_hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]

def _b32m_decode(s: str):
    s = s.lower()
    pos = s.rfind('1')
    if pos < 1 or len(s) - pos - 1 < 6:
        return None, None
    hrp   = s[:pos]
    data5 = []
    for c in s[pos + 1:]:
        d = _B32_CHARSET.find(c)
        if d < 0:
            return None, None
        data5.append(d)
    if _b32m_polymod(_b32m_hrp_expand(hrp) + data5) != _B32M_CONST:
        return None, None
    # Remove 6-char checksum, convert 5-bit → 8-bit
    data5 = data5[:-6]
    acc = bits = 0
    out = []
    for v in data5:
        acc = (acc << 5) | v
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    return hrp, bytes(out)

# ── Sui key / address helpers ─────────────────────────────────────

def _slip10_derive_ed25519(seed: bytes, path: str) -> bytes:
    """SLIP-0010 Ed25519 derivation — all segments must be hardened."""
    import hmac as _hmac
    h   = _hmac.new(b"ed25519 seed", seed, hashlib.sha512).digest()
    key, cc = h[:32], h[32:]
    for seg in path.split('/'):
        if seg == 'm':
            continue
        idx  = int(seg.rstrip("'")) | (0x80000000 if seg.endswith("'") else 0)
        data = b'\x00' + key + idx.to_bytes(4, 'big')
        h    = _hmac.new(cc, data, hashlib.sha512).digest()
        key, cc = h[:32], h[32:]
    return key

def _sui_key_from_mnemonic(phrase: str, passphrase: str = "") -> bytes:
    """BIP39 seed → SLIP-0010 Ed25519 → Sui private key (path m/44'/784'/0'/0'/0')."""
    import unicodedata
    mn   = unicodedata.normalize('NFKD', phrase.strip())
    salt = unicodedata.normalize('NFKD', 'mnemonic' + passphrase)
    seed = hashlib.pbkdf2_hmac('sha512', mn.encode(), salt.encode(), 2048)
    return _slip10_derive_ed25519(seed, "m/44'/784'/0'/0'/0'")

def _norm_sui_type(coin_type: str) -> str:
    """Normalize Sui coin type by zero-padding the address portion."""
    if "::" not in coin_type:
        return coin_type
    idx  = coin_type.index("::")
    addr = coin_type[:idx]
    rest = coin_type[idx:]
    if addr.startswith("0x"):
        addr = "0x" + addr[2:].zfill(64)
    return addr + rest

def _parse_sui_key(raw: str) -> bytes:
    """Return 32-byte ed25519 seed from mnemonic / suiprivkey1 / hex / base64."""
    raw = " ".join(raw.strip().split())  # collapse internal newlines
    # 12/15/18/21/24 words → BIP39 mnemonic
    words = raw.split()
    if len(words) in (12, 15, 18, 21, 24):
        return _sui_key_from_mnemonic(raw)
    if raw.lower().startswith("suiprivkey1"):
        hrp, data = _b32m_decode(raw)
        if data is None or len(data) < 33:
            raise ValueError("Invalid suiprivkey bech32m")
        if data[0] != 0:
            raise ValueError(f"Only ed25519 keys supported (scheme={data[0]})")
        return data[1:33]
    if raw.startswith("0x"):
        h = raw[2:]
        if len(h) != 64:
            raise ValueError(f"Expected 64 hex after 0x, got {len(h)}")
        return bytes.fromhex(h)
    if len(raw) == 64:
        return bytes.fromhex(raw)
    # Try base64
    try:
        dec = base64.b64decode(raw + "=" * (-len(raw) % 4))
        if len(dec) == 33:
            return dec[1:]
        if len(dec) == 32:
            return dec
    except Exception:
        pass
    raise ValueError(f"Unrecognized Sui key format")

def _sui_address(pk_bytes: bytes) -> str:
    sk  = _NaClSigningKey(pk_bytes)
    pub = bytes(sk.verify_key)
    return "0x" + hashlib.blake2b(bytes([0x00]) + pub, digest_size=32).digest().hex()

def _is_sui_address(s: str) -> bool:
    s = s.strip()
    return s.startswith("0x") and len(s) == 66 and all(
        c in "0123456789abcdefABCDEF" for c in s[2:]
    )

# ── Sui RPC helpers ───────────────────────────────────────────────

async def _sui_rpc(client: httpx.AsyncClient, method: str, params: list, retries: int = 3):
    rpcs     = CHAINS["sui"]["rpcs"]
    last_exc = None
    for attempt in range(retries):
        url = rpcs[attempt % len(rpcs)]
        try:
            r    = await client.post(url, json={
                "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
            }, timeout=20)
            body = r.json()
            if "error" in body:
                last_exc = RuntimeError(str(body["error"]))
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            return body.get("result")
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.5 * (attempt + 1))
    raise last_exc or RuntimeError("Sui RPC failed")

async def _sui_get_all_coins(client, addr: str, coin_type: str) -> list:
    coins  = []
    cursor = None
    for _ in range(200):   # max 10 000 coin objects
        result = await _sui_rpc(client, "suix_getCoins", [addr, coin_type, cursor, 50])
        if not result or "data" not in result:
            break
        coins.extend(result["data"])
        if not result.get("hasNextPage"):
            break
        cursor = result.get("nextCursor")
    return coins

async def _sui_sign_execute(client, pk_bytes: bytes, tx_b64: str) -> str:
    tx_bytes   = base64.b64decode(tx_b64)
    intent_msg = bytes([0, 0, 0]) + tx_bytes          # TransactionData intent
    digest     = hashlib.blake2b(intent_msg, digest_size=32).digest()
    sk         = _NaClSigningKey(pk_bytes)
    sig_bytes  = sk.sign(digest).signature             # 64 bytes
    pub_bytes  = bytes(sk.verify_key)                  # 32 bytes
    full_sig   = bytes([0x00]) + sig_bytes + pub_bytes # flag=ed25519
    sig_b64    = base64.b64encode(full_sig).decode()
    result = await _sui_rpc(client, "sui_executeTransactionBlock", [
        tx_b64, [sig_b64],
        {"showEffects": True},
        "WaitForLocalExecution",
    ])
    if result:
        effects = result.get("effects") or {}
        status  = effects.get("status") or {}
        if isinstance(status, dict) and status.get("status") == "failure":
            raise RuntimeError(status.get("error", "tx failed"))
        return result.get("digest", "")
    return ""

# ── Sui sweep ────────────────────────────────────────────────────

async def _sweep_sui_wallet(
    client:        httpx.AsyncClient,
    raw_key:       str,
    recipient_sui: str,
    min_sui:       float,
    dry_run:       bool,
    sem:           asyncio.Semaphore,
) -> dict:
    row = {"chain": "Sui", "chain_key": "sui", "address": "?",
           "status": "error", "amount_swept": 0.0, "tx_hash": "", "note": ""}
    try:
        pk_bytes       = _parse_sui_key(raw_key)
        addr           = _sui_address(pk_bytes)
        row["address"] = addr
    except Exception as e:
        row["note"] = f"invalid key: {e}"
        return row

    async with sem:
        try:
            balances = await _sui_rpc(client, "suix_getAllBalances", [addr])
            if not balances:
                row["status"] = "skip"
                row["note"]   = "no coins"
                return row

            # Build normalized balance map
            bal_map = {_norm_sui_type(b["coinType"]): int(b["totalBalance"]) for b in balances}

            # Locate SUI entry (endswith ::sui::SUI)
            sui_entry     = next((b for b in balances if b["coinType"].endswith("::sui::SUI")), None)
            sui_coin_type = sui_entry["coinType"] if sui_entry else "0x2::sui::SUI"
            sui_balance   = int(sui_entry["totalBalance"]) if sui_entry else 0

            # Tokens with non-zero balance
            tokens_to_sweep = []
            for raw_type in SUI_TOKEN_TYPES:
                bal = bal_map.get(_norm_sui_type(raw_type), 0)
                if bal > 0:
                    tokens_to_sweep.append({"type": raw_type, "name": raw_type.split("::")[-1], "bal": bal})

            if dry_run:
                tok_notes = [f"{t['name']}:{t['bal']}" for t in tokens_to_sweep]
                row["status"]       = "dry_run"
                row["amount_swept"] = round(sui_balance / 1e9, 9)
                row["note"]         = f"SUI:{sui_balance/1e9:.4f}" + (
                    " | " + ", ".join(tok_notes) if tok_notes else "")
                return row

            if sui_balance == 0 and not tokens_to_sweep:
                row["status"] = "skip"
                row["note"]   = "all balances zero"
                return row

            tx_notes    = []
            last_digest = ""

            # ── Sweep tokens first (SUI pays gas) ─────────────────
            for tok in tokens_to_sweep:
                if sui_balance < SUI_GAS_BUDGET_MIST:
                    tx_notes.append(f"{tok['name']}: no SUI gas")
                    continue
                try:
                    coins    = await _sui_get_all_coins(client, addr, tok["type"])
                    if not coins:
                        continue
                    coin_ids = [c["coinObjectId"] for c in coins]
                    total    = str(sum(int(c["balance"]) for c in coins))

                    sui_coins = await _sui_get_all_coins(client, addr, sui_coin_type)
                    if not sui_coins:
                        tx_notes.append(f"{tok['name']}: no SUI gas coin")
                        continue

                    tx_data = await _sui_rpc(client, "unsafe_pay", [
                        addr, coin_ids, [recipient_sui], [total],
                        sui_coins[0]["coinObjectId"], str(SUI_GAS_BUDGET_MIST),
                    ])
                    if tx_data and "txBytes" in tx_data:
                        d = await _sui_sign_execute(client, pk_bytes, tx_data["txBytes"])
                        last_digest  = d or last_digest
                        sui_balance -= SUI_GAS_BUDGET_MIST
                        tx_notes.append(f"{tok['name']}: ok")
                    else:
                        tx_notes.append(f"{tok['name']}: no txBytes")
                except Exception as e:
                    tx_notes.append(f"{tok['name']}: {str(e)[:60]}")

            # ── Sweep SUI last ─────────────────────────────────────
            min_mist = int(min_sui * 1e9)
            if sui_balance >= max(min_mist, SUI_GAS_BUDGET_MIST):
                try:
                    sui_coins = await _sui_get_all_coins(client, addr, sui_coin_type)
                    if sui_coins:
                        coin_ids = [c["coinObjectId"] for c in sui_coins]
                        tx_data  = await _sui_rpc(client, "unsafe_payAllSui", [
                            addr, coin_ids, recipient_sui, str(SUI_GAS_BUDGET_MIST),
                        ])
                        if tx_data and "txBytes" in tx_data:
                            d = await _sui_sign_execute(client, pk_bytes, tx_data["txBytes"])
                            last_digest         = d or last_digest
                            row["amount_swept"] = round(
                                max(0, sui_balance - SUI_GAS_BUDGET_MIST) / 1e9, 9)
                            tx_notes.append("SUI: ok")
                        else:
                            tx_notes.append("SUI: no txBytes")
                except Exception as e:
                    tx_notes.append(f"SUI: {str(e)[:60]}")
            elif sui_balance > 0:
                tx_notes.append(f"SUI:{sui_balance/1e9:.6f} below min")

            if last_digest or any(n.endswith(": ok") for n in tx_notes):
                row["status"]  = "sent"
                row["tx_hash"] = last_digest
                row["note"]    = ", ".join(tx_notes) if tx_notes else "ok"
            elif tx_notes:
                row["status"] = "skip"
                row["note"]   = ", ".join(tx_notes)
            else:
                row["status"] = "skip"
                row["note"]   = "nothing swept"

        except Exception as e:
            row["status"] = "error"
            row["note"]   = str(e)[:300]

    return row

# ── TON helpers ───────────────────────────────────────────────────

def _ton_key_from_mnemonic(phrase: str):
    """BIP39 → SLIP-0010 Ed25519 at m/44'/607'/0' → (priv64, pub32)."""
    import unicodedata
    mn    = unicodedata.normalize('NFKD', phrase.strip())
    salt  = unicodedata.normalize('NFKD', 'mnemonic')
    seed  = hashlib.pbkdf2_hmac('sha512', mn.encode(), salt.encode(), 2048)
    p32   = _slip10_derive_ed25519(seed, "m/44'/607'/0'")
    sk    = _NaClSigningKey(p32)
    pub32 = bytes(sk.verify_key)
    return p32 + pub32, pub32   # (priv64, pub32)

def _is_ton_address(s: str) -> bool:
    s = s.strip()
    if ':' in s:
        wc, h = s.split(':', 1)
        return wc.lstrip('-').isdigit() and len(h) == 64
    return len(s) == 48

# Semaphore riêng cho TON:
#   - tonapi.io: ~10 req/s free → semaphore=5, delay=0.12s
#   - toncenter fallback: 1 req/s → semaphore=1, delay=1.1s
_ton_sem_tonapi    = asyncio.Semaphore(5)
_ton_sem_toncenter = asyncio.Semaphore(1)

async def _ton_get_balance(client: httpx.AsyncClient, addr: str) -> int:
    """Trả về balance nanoTON.
    Dùng tonapi.io trước (rate limit cao), fallback toncenter nếu lỗi.
    'uninitialized' = ví chưa gửi tx nhưng vẫn CÓ balance → KHÔNG trả 0.
    """
    # ── Thử tonapi.io trước ──────────────────────────────────────
    tonapi = CHAINS["ton"]["tonapi"]
    for attempt in range(3):
        try:
            async with _ton_sem_tonapi:
                await asyncio.sleep(0.12)
                r = await client.get(
                    f"{tonapi}/accounts/{addr}",
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
            if r.status_code == 429:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code == 404:
                return 0   # account không tồn tại
            if r.status_code == 200:
                data   = r.json()
                status = data.get("status", "")
                if status == "nonexist":
                    return 0
                bal = data.get("balance", 0)
                return int(bal) if bal else 0
        except Exception:
            await asyncio.sleep(1.0 * (attempt + 1))

    # ── Fallback: toncenter v2 ────────────────────────────────────
    for rpc in CHAINS["ton"]["rpcs"]:
        for attempt in range(2):
            try:
                async with _ton_sem_toncenter:
                    await asyncio.sleep(1.1)
                    r = await client.get(
                        f"{rpc}/getAddressInformation",
                        params={"address": addr},
                        timeout=20,
                    )
                if r.status_code == 429:
                    await asyncio.sleep(3.0 * (attempt + 1))
                    continue
                body = r.json()
                if not body.get("ok"):
                    break
                info  = body["result"]
                state = info.get("state", "")
                bal   = info.get("balance", "0") or "0"
                bal_i = int(bal) if str(bal).lstrip("-").isdigit() else 0
                if state == "nonexist" or bal_i < 0:
                    return 0
                return bal_i
            except Exception:
                await asyncio.sleep(2.0 * (attempt + 1))

    raise RuntimeError("TON balance unavailable (all endpoints failed)")

async def _ton_api_post(client: httpx.AsyncClient, path: str, data: dict):
    """POST lên toncenter — chỉ dùng để send tx."""
    rpcs = CHAINS["ton"]["rpcs"]
    last_exc = None
    for attempt in range(len(rpcs) * 2):
        url = rpcs[attempt % len(rpcs)] + "/" + path.lstrip("/")
        try:
            async with _ton_sem_toncenter:
                await asyncio.sleep(1.1)
                r = await client.post(url, json=data, timeout=20)
            if r.status_code == 429:
                await asyncio.sleep(3.0 * (attempt + 1))
                last_exc = RuntimeError("TON API 429 rate-limited")
                continue
            body = r.json()
            if body.get("ok"):
                return body["result"]
            raise RuntimeError(str(body.get("error", "TON API error")))
        except RuntimeError:
            raise
        except Exception as e:
            last_exc = e
            await asyncio.sleep(2.0 * (attempt + 1))
    raise last_exc or RuntimeError("TON send failed after retries")

async def _ton_get_seqno(client: httpx.AsyncClient, addr: str) -> int:
    """Lấy seqno. Raise RuntimeError nếu không lấy được (để caller skip thay vì gửi sai seqno)."""

    # ── tonapi.io: GET /v2/accounts/{addr}/methods/seqno ──────────
    tonapi = CHAINS["ton"]["tonapi"]
    try:
        async with _ton_sem_tonapi:
            await asyncio.sleep(0.12)
            r = await client.get(
                f"{tonapi}/accounts/{addr}/methods/seqno",
                headers={"Accept": "application/json"},
                timeout=15,
            )
        if r.status_code == 200:
            data  = r.json()
            # tonapi trả về decoded (nếu có) hoặc raw stack
            dec   = data.get("decoded") or {}
            if "seqno" in dec:
                return int(dec["seqno"])
            raw = data.get("stack", [])
            if raw:
                val = raw[0].get("num") or raw[0].get("value", "0")
                return int(val, 16) if isinstance(val, str) and val.startswith("0x") else int(val, 16) if val else 0
        if r.status_code == 404:
            return 0   # ví uninitialized → seqno = 0 là đúng
    except Exception:
        pass

    # ── Fallback: toncenter runGetMethod ─────────────────────────
    for rpc in CHAINS["ton"]["rpcs"]:
        try:
            async with _ton_sem_toncenter:
                await asyncio.sleep(1.1)
                r = await client.post(
                    f"{rpc}/runGetMethod",
                    json={"address": addr, "method": "seqno", "stack": []},
                    timeout=20,
                )
            if r.status_code == 429:
                await asyncio.sleep(3.0)
                continue
            body = r.json()
            if body.get("ok"):
                stack = body["result"].get("stack", [])
                return int(stack[0][1], 16) if stack else 0
        except Exception:
            continue

    raise RuntimeError("seqno unavailable — all TON endpoints failed")

# ── TON sweep ────────────────────────────────────────────────────

async def _sweep_ton_wallet(
    client:        httpx.AsyncClient,
    raw_phrase:    str,
    recipient_ton: str,
    min_ton:       float,
    dry_run:       bool,
    sem:           asyncio.Semaphore,
) -> dict:
    row = {"chain": "TON", "chain_key": "ton", "address": "?",
           "status": "error", "amount_swept": 0.0, "tx_hash": "", "note": ""}
    try:
        # Accept both "w1 w2...w12" (one line) and accidental multi-line input
        phrase = " ".join(raw_phrase.strip().split())   # collapse any internal newlines
        words  = phrase.split()
        if len(words) not in (12, 15, 18, 21, 24):
            raise ValueError(
                f"TON mnemonic must be 12 or 24 words (got {len(words)}). "
                "Use one phrase per line with words separated by spaces."
            )
        priv64, pub32 = _ton_key_from_mnemonic(phrase)
        wallet  = _TonWalletV4R2(public_key=pub32, private_key=priv64)
        address = wallet.address.to_string(True, True, False, False)  # non-bounceable UQ...
        row["address"] = address
    except Exception as e:
        row["note"] = f"invalid: {e}"
        return row

    # TON dùng _ton_sem riêng bên trong API calls, không cần sem chung
    try:
        balance_nano = await _ton_get_balance(client, address)
        min_nano     = int(min_ton * 1e9)
        GAS_NANO     = 5_000_000    # 0.005 TON — gas thực tế ~0.003-0.005 TON

        if dry_run:
            row["status"]       = "dry_run"
            row["amount_swept"] = round(balance_nano / 1e9, 9)
            row["note"]         = f"TON:{balance_nano/1e9:.4f}"
            return row

        if balance_nano < max(min_nano, GAS_NANO):
            row["status"] = "skip"
            row["note"]   = f"{balance_nano/1e9:.6f} TON below min"
            return row

        # seqno raises RuntimeError nếu không lấy được → safe: không gửi sai seqno
        seqno    = await _ton_get_seqno(client, address)
        # send_mode=128 gửi toàn bộ balance còn lại sau phí, send_amt chỉ là placeholder
        send_amt = balance_nano - GAS_NANO

        transfer = wallet.create_transfer_message(
            to_addr=recipient_ton,
            amount=send_amt,
            seqno=seqno,
            send_mode=128,   # send all remaining balance, fees deducted by node
        )
        boc = _ton_to_b64(transfer["message"].to_boc(False))

        # Gửi qua tonapi.io trước (nhanh hơn), fallback toncenter
        tx_hash = ""
        try:
            async with _ton_sem_tonapi:
                await asyncio.sleep(0.12)
                r2 = await client.post(
                    f"{CHAINS['ton']['tonapi']}/blockchain/message",
                    json={"boc": boc},
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    timeout=20,
                )
            if r2.status_code in (200, 201, 202):
                d2 = r2.json()
                tx_hash = d2.get("message_hash", d2.get("hash", "ok"))
            else:
                raise RuntimeError(f"tonapi send {r2.status_code}: {r2.text[:200]}")
        except Exception:
            # Fallback toncenter
            result  = await _ton_api_post(client, "sendBocReturnHash", {"boc": boc})
            tx_hash = result.get("hash", "") if isinstance(result, dict) else str(result)

        row["status"]       = "sent"
        row["amount_swept"] = round(send_amt / 1e9, 9)
        row["tx_hash"]      = tx_hash
        row["note"]         = f"seqno={seqno} send_mode=128"

    except Exception as e:
        row["status"] = "error"
        row["note"]   = str(e)[:300]

    return row

# ── Job store ────────────────────────────────────────────────────
jobs: Dict[str, dict] = {}


def _new_job(dry_run: bool = False, chain_keys: list = None,
             recipient_sui: str = "", recipient_ton: str = "") -> str:
    jid = str(uuid.uuid4())
    ck  = chain_keys or list(CHAINS.keys())
    jobs[jid] = {
        "status":        "running",
        "progress":      0,
        "total":         0,
        "cancel":        False,
        "dry_run":       dry_run,
        "chains":        ck,
        "recipient_sui": recipient_sui,
        "recipient_ton": recipient_ton,
        "results":       [],
        "stats":         {
            "sent": 0, "simulated": 0, "skip": 0, "errors": 0,
            "totals": {k: 0.0 for k in ck},
        },
        "error": None,
    }
    return jid


# ── RPC helpers ──────────────────────────────────────────────────

async def _rpc(
    client: httpx.AsyncClient,
    method: str,
    params: list,
    chain_key: str = "base",
    retries: int = 3,
):
    rpcs     = CHAINS[chain_key]["rpcs"]
    last_exc = None
    for attempt in range(retries):
        rpc_url = rpcs[attempt % len(rpcs)]
        try:
            r = await client.post(rpc_url, json={
                "jsonrpc": "2.0", "method": method,
                "params": params, "id": 1,
            }, timeout=15)
            body = r.json()
            if "error" in body:
                last_exc = RuntimeError(str(body["error"]))
                await asyncio.sleep(0.3 * (attempt + 1))
                continue
            return body.get("result")
        except Exception as e:
            last_exc = e
            await asyncio.sleep(0.3 * (attempt + 1))
    raise last_exc or RuntimeError("RPC failed")


# ── Key helpers ──────────────────────────────────────────────────

def _norm_key(raw: str) -> str:
    k = raw.strip().replace(" ", "")
    if k.lower().startswith("0x"):
        k = k[2:]
    if len(k) != 64:
        raise ValueError(f"bad length {len(k)}, expected 64 hex chars")
    return "0x" + k.lower()


def _is_address(s: str) -> bool:
    try:
        s = s.strip()
        if not s.startswith("0x") or len(s) != 42:
            return False
        int(s[2:], 16)
        return True
    except Exception:
        return False


def _checksum(addr: str) -> str:
    return to_checksum_address(addr.strip())


# ── Core sweep logic ─────────────────────────────────────────────

async def _sweep_wallet(
    client:    httpx.AsyncClient,
    raw_key:   str,
    recipient: str,
    min_wei:   int,
    gas_mult:  float,
    dry_run:   bool,
    sem:       asyncio.Semaphore,
    chain_key: str,
) -> dict:
    chain = CHAINS[chain_key]
    row   = {
        "chain":         chain["name"],
        "chain_key":     chain_key,
        "address":       "?",
        "status":        "error",
        "amount_swept":  0.0,
        "tx_hash":       "",
        "note":          "",
    }

    try:
        pk      = _norm_key(raw_key)
        account = Account.from_key(pk)
        addr    = account.address
        row["address"] = addr
    except Exception as e:
        row["note"] = f"invalid key: {e}"
        return row

    async with sem:
        try:
            # Fetch balance + gas sequentially (same block height)
            bal_hex = await _rpc(client, "eth_getBalance", [addr, "latest"], chain_key)
            gp_hex  = await _rpc(client, "eth_gasPrice",   [],               chain_key)
            balance   = int(bal_hex, 16) if bal_hex else 0
            gas_price = int(gp_hex,  16) if gp_hex  else 1_000_000_000
            sym       = chain["symbol"]

            if chain["tx_type"] == 0:
                # ── BSC legacy (type 0) ──────────────────────────────
                gas_price_final = int(gas_price * gas_mult)
                gas_budget      = (GAS_LIMIT + 500) * gas_price_final
                send_value      = balance - gas_budget

                if send_value < min_wei:
                    row["status"] = "skip"
                    row["note"]   = f"balance {balance/1e18:.8f} {sym} — too low after gas"
                    return row

                if dry_run:
                    row["status"]        = "dry_run"
                    row["amount_swept"]  = round(send_value / 1e18, 9)
                    row["note"]          = f"gasPrice={gas_price_final/1e9:.4f} gwei"
                    return row

                nc_hex = await _rpc(client, "eth_getTransactionCount", [addr, "latest"], chain_key)
                nonce  = int(nc_hex, 16) if nc_hex else 0

                tx = {
                    "chainId":  chain["chain_id"],
                    "nonce":    nonce,
                    "to":       _checksum(recipient),
                    "value":    send_value,
                    "gas":      GAS_LIMIT,
                    "gasPrice": gas_price_final,
                }
                note_str = f"gasPrice={gas_price_final/1e9:.4f} gwei"

            else:
                # ── EIP-1559 (type 2): Base / Ethereum / Avalanche ──
                priority_fee = 1_000_000                        # 0.001 gwei tip
                max_fee_gas  = int(gas_price * gas_mult) + priority_fee
                gas_budget   = (GAS_LIMIT + 500) * max_fee_gas  # +500 buffer
                send_value   = balance - gas_budget

                if send_value < min_wei:
                    row["status"] = "skip"
                    row["note"]   = f"balance {balance/1e18:.8f} {sym} — too low after gas"
                    return row

                if dry_run:
                    row["status"]        = "dry_run"
                    row["amount_swept"]  = round(send_value / 1e18, 9)
                    row["note"]          = f"gasPrice={gas_price/1e9:.4f} gwei maxFee={max_fee_gas/1e9:.4f} gwei"
                    return row

                nc_hex = await _rpc(client, "eth_getTransactionCount", [addr, "latest"], chain_key)
                nonce  = int(nc_hex, 16) if nc_hex else 0

                tx = {
                    "type":                 2,
                    "chainId":              chain["chain_id"],
                    "nonce":                nonce,
                    "to":                   _checksum(recipient),
                    "value":                send_value,
                    "gas":                  GAS_LIMIT,
                    "maxFeePerGas":         max_fee_gas,
                    "maxPriorityFeePerGas": priority_fee,
                }
                note_str = f"maxFee={max_fee_gas/1e9:.4f} gwei"

            signed    = account.sign_transaction(tx)
            raw_bytes = getattr(signed, "raw_transaction", None) \
                     or getattr(signed, "rawTransaction", b"")
            raw_hex   = "0x" + raw_bytes.hex()

            tx_hash = await _rpc(client, "eth_sendRawTransaction", [raw_hex], chain_key)

            row["status"]        = "sent"
            row["amount_swept"]  = round(send_value / 1e18, 9)
            row["tx_hash"]       = tx_hash or ""
            row["note"]          = note_str

        except Exception as e:
            row["status"] = "error"
            row["note"]   = str(e)[:300]

    return row


# ── Job runner ───────────────────────────────────────────────────

async def run_sweep_job(
    jid:          str,
    private_keys: List[str],
    recipient:    str,
    concurrency:  int,
    min_eth:      float,
    gas_mult:     float,
    dry_run:      bool,
    chain_keys:   List[str],
) -> None:
    job           = jobs[jid]
    recipient_sui = job.get("recipient_sui", "")
    recipient_ton = job.get("recipient_ton", "")
    min_wei       = int(min_eth * 1e18)
    tasks         = [(pk, ck) for pk in private_keys for ck in chain_keys]
    job["total"]  = len(tasks)

    limits = httpx.Limits(
        max_connections=concurrency + 20,
        max_keepalive_connections=concurrency,
    )
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(limits=limits) as client:

        async def _do(pk: str, chain_key: str) -> None:
            if job["cancel"]:
                return
            if chain_key == "sui":
                row = await _sweep_sui_wallet(
                    client, pk, recipient_sui, min_eth, dry_run, sem
                )
            elif chain_key == "ton":
                row = await _sweep_ton_wallet(
                    client, pk, recipient_ton, min_eth, dry_run, sem
                )
            else:
                row = await _sweep_wallet(
                    client, pk, recipient, min_wei, gas_mult, dry_run, sem, chain_key
                )
            job["results"].append(row)
            job["progress"] = len(job["results"])
            s  = row["status"]
            st = job["stats"]
            if s == "sent":
                st["sent"] += 1
                st["totals"][chain_key] = round(
                    st["totals"].get(chain_key, 0.0) + row["amount_swept"], 9
                )
            elif s == "dry_run":
                st["simulated"] += 1
                st["totals"][chain_key] = round(
                    st["totals"].get(chain_key, 0.0) + row["amount_swept"], 9
                )
            elif s == "skip":
                st["skip"] += 1
            else:
                st["errors"] += 1

        await asyncio.gather(*[_do(pk, ck) for pk, ck in tasks])

    job["status"] = "cancelled" if job["cancel"] else "done"


# ── HTTP handlers ─────────────────────────────────────────────────

async def handle_index(req: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html")


async def handle_sweep_start(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    raw_keys      = body.get("keys", "")
    recipient     = (body.get("recipient")     or "").strip()
    recipient_sui = (body.get("recipient_sui") or "").strip()
    concurrency   = max(1, min(int(body.get("concurrency", 30)), 200))
    min_eth       = float(body.get("min_eth", 0.000001))
    gas_mult      = float(body.get("gas_mult", 1.5))
    dry_run       = bool(body.get("dry_run", False))
    chain_keys    = [k for k in body.get("chains", ["base"]) if k in CHAINS]

    keys = [k.strip() for k in raw_keys.replace(",", "\n").splitlines() if k.strip()]

    # ── Mnemonic grouping ────────────────────────────────────────
    # Case 1: each word on its own line (wallet export format)
    #   → "abandon\nabandon\n...abandon\nabout" (12 lines per phrase)
    # Case 2: all phrases pasted on one line separated by spaces
    #   → "w1 w2...w12 w1 w2...w12" (all 4764 words in one entry)
    # Detect either case and regroup into 12-word phrases.
    def _looks_bip39(word: str) -> bool:
        w = word.strip()
        return 2 <= len(w) <= 12 and w.replace('-', '').isalpha()

    if keys and len(keys[0].split()) == 1 and _looks_bip39(keys[0]):
        # Every entry is likely a single BIP39 word — sample first word only
        if len(keys) % 12 == 0:
            keys = [" ".join(keys[i:i+12]) for i in range(0, len(keys), 12)]
        elif len(keys) % 24 == 0:
            keys = [" ".join(keys[i:i+24]) for i in range(0, len(keys), 24)]
    elif len(keys) == 1:
        words = keys[0].split()
        if len(words) > 24 and _looks_bip39(words[0]):
            # All mnemonics pasted as a single long string
            chunk = 24 if len(words) % 24 == 0 else 12
            if len(words) % chunk == 0:
                keys = [" ".join(words[i:i+chunk]) for i in range(0, len(words), chunk)]

    if not keys:
        return web.json_response({"ok": False, "error": "No private keys provided"}, status=400)
    if not chain_keys:
        return web.json_response({"ok": False, "error": "Select at least one chain"}, status=400)

    recipient_ton = (body.get("recipient_ton") or "").strip()
    evm_chains    = [k for k in chain_keys if k not in ("sui", "ton")]
    has_sui       = "sui" in chain_keys
    has_ton       = "ton" in chain_keys
    if evm_chains and not _is_address(recipient):
        return web.json_response({"ok": False, "error": "Invalid EVM recipient address"}, status=400)
    if has_sui and not _is_sui_address(recipient_sui):
        return web.json_response(
            {"ok": False, "error": "Invalid Sui recipient (need 0x + 64 hex chars)"},
            status=400,
        )
    if has_ton and not _is_ton_address(recipient_ton):
        return web.json_response(
            {"ok": False, "error": "Invalid TON recipient address (EQ.../UQ... or 0:hex)"},
            status=400,
        )

    jid = _new_job(dry_run=dry_run, chain_keys=chain_keys,
                   recipient_sui=recipient_sui, recipient_ton=recipient_ton)
    asyncio.create_task(
        run_sweep_job(jid, keys, recipient, concurrency, min_eth, gas_mult, dry_run, chain_keys)
    )
    return web.json_response({"ok": True, "job_id": jid})


async def handle_sweep_cancel(req: web.Request) -> web.Response:
    jid = req.match_info["job_id"]
    job = jobs.get(jid)
    if not job:
        return web.json_response({"ok": False, "error": "Not found"}, status=404)
    job["cancel"] = True
    return web.json_response({"ok": True})


async def handle_job_status(req: web.Request) -> web.Response:
    jid = req.match_info["job_id"]
    job = jobs.get(jid)
    if not job:
        return web.json_response({"ok": False, "error": "Not found"}, status=404)
    return web.json_response({
        "ok":       True,
        "status":   job["status"],
        "progress": job["progress"],
        "total":    job["total"],
        "dry_run":  job["dry_run"],
        "chains":   job["chains"],
        "stats":    job["stats"],
        "error":    job["error"],
    })


async def handle_job_results(req: web.Request) -> web.Response:
    jid    = req.match_info["job_id"]
    offset = int(req.rel_url.query.get("offset", 0))
    limit  = int(req.rel_url.query.get("limit", 200))
    job    = jobs.get(jid)
    if not job:
        return web.json_response({"ok": False, "error": "Not found"}, status=404)
    page = job["results"][offset: offset + limit]
    return web.json_response({"ok": True, "results": page, "total": len(job["results"])})


# ── HTML dashboard ────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Multi-chain Sweeper</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0d;color:#e0e0e0;font-family:'Segoe UI',sans-serif;font-size:14px}
header{background:#111;border-bottom:1px solid #222;padding:12px 24px;display:flex;align-items:center;gap:16px}
header h1{font-size:17px;color:#ff6b00;white-space:nowrap}
.main{padding:20px 24px;max-width:1200px;margin:0 auto}
.card{background:#141414;border:1px solid #222;border-radius:8px;padding:18px;margin-bottom:16px}
.card h3{font-size:12px;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}
textarea,input[type=text],input[type=number]{
  width:100%;background:#0d0d0d;border:1px solid #333;color:#e0e0e0;
  border-radius:6px;padding:9px 12px;font-size:13px;font-family:monospace;outline:none}
textarea:focus,input:focus{border-color:#ff6b00}
textarea{resize:vertical}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:10px}
.col{flex:1;min-width:140px}
label.lbl{font-size:12px;color:#888;display:block;margin-bottom:5px}
.btn{padding:8px 22px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:700;transition:.15s}
.btn-orange{background:#ff6b00;color:#000}.btn-orange:hover{background:#e05e00}
.btn-red{background:#c62828;color:#fff}.btn-red:hover{background:#b71c1c}
.btn-green{background:#00c853;color:#000}.btn-green:hover{background:#00b048}
.btn:disabled{opacity:.35;cursor:not-allowed}
.warning{background:#1a0e00;border:1px solid #8b4500;border-radius:6px;padding:12px 16px;
  color:#ffaa44;font-size:13px;margin-bottom:16px;line-height:1.6}
.warning b{color:#ff8800}
.progress-bar{height:5px;background:#1a1a1a;border-radius:4px;overflow:hidden;margin-top:12px}
.progress-fill{height:100%;background:#ff6b00;border-radius:4px;transition:width .3s}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}
.stat-box{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;padding:12px;text-align:center}
.stat-val{font-size:22px;font-weight:700;color:#ff6b00;font-family:monospace}
.stat-lbl{font-size:11px;color:#666;margin-top:3px}
.stat-val.green{color:#00c853}
.stat-val.red{color:#e53935}
.stat-val.blue{color:#00c8ff}
.chain-totals-row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 4px}
.chain-total-box{background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;padding:10px 16px;text-align:center;min-width:140px}
.chain-total-val{font-size:15px;font-weight:700;font-family:monospace}
.chain-total-name{font-size:10px;color:#555;margin-top:3px;text-transform:uppercase;letter-spacing:.06em}
.status-line{font-size:12px;color:#888;margin-top:8px}
.tbl-wrap{overflow:auto;max-height:480px;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
thead{position:sticky;top:0;z-index:1}
thead tr{background:#1c1c1c}
th{padding:7px 10px;text-align:left;color:#777;font-weight:700;border-bottom:1px solid #222;white-space:nowrap}
td{padding:5px 10px;border-bottom:1px solid #191919;font-family:monospace}
tr:hover td{background:#181818}
.copy-addr{cursor:pointer;color:#aaa;font-family:monospace;font-size:11px;word-break:break-all}
.copy-addr:hover{color:#00c8ff;text-decoration:underline}
.copy-addr.copied{color:#00c853}
td a{color:#ff6b00;text-decoration:none}td a:hover{text-decoration:underline}
.badge{display:inline-block;padding:1px 8px;border-radius:4px;font-size:10px;font-weight:700}
.bg-sent{background:#003320;color:#00e676}
.bg-skip{background:#1a1a00;color:#888}
.bg-dry{background:#001a2e;color:#00c8ff}
.bg-err{background:#2a0000;color:#ff5252}
.bg-invalid{background:#1a0020;color:#ce93d8}
.bg-cancel{background:#111;color:#555}
.dry-banner{background:#001a2e;border:1px solid #00c8ff;border-radius:6px;padding:10px 16px;
  color:#00c8ff;font-size:13px;font-weight:700;margin-bottom:10px;display:none;text-align:center;letter-spacing:.04em}
.real-banner{background:#1a0000;border:1px solid #ff1744;border-radius:6px;padding:10px 16px;
  color:#ff5252;font-size:13px;font-weight:700;margin-bottom:10px;display:none;text-align:center;letter-spacing:.04em}
.checkbox-row{display:flex;align-items:center;gap:8px;margin-top:12px;cursor:pointer;
  background:#111;border:2px solid #333;border-radius:6px;padding:10px 14px;transition:.2s}
.checkbox-row:hover{border-color:#555}
.checkbox-row input{accent-color:#ff6b00;cursor:pointer;width:16px;height:16px}
.mode-badge{display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;margin-left:8px}
.mode-sim{background:#001a2e;color:#00c8ff;border:1px solid #00c8ff55}
.mode-real{background:#1a0000;color:#ff5252;border:1px solid #ff174455}
/* chain selector */
.chain-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.chain-btn{
  display:flex;align-items:center;gap:7px;
  padding:8px 16px;border-radius:20px;
  border:2px solid #2a2a2a;background:#111;
  color:#555;cursor:pointer;font-size:13px;font-weight:600;
  transition:.15s;
}
.chain-btn:hover{border-color:#444;color:#888}
.chain-dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex-shrink:0}
.chain-btn[data-chain="base"].active    {border-color:#0052ff;color:#4d8aff;background:#00062a}
.chain-btn[data-chain="bsc"].active     {border-color:#f0b90b;color:#f0b90b;background:#1a1400}
.chain-btn[data-chain="ethereum"].active{border-color:#627eea;color:#8fa4f0;background:#07092a}
.chain-btn[data-chain="avalanche"].active{border-color:#e84142;color:#f07070;background:#1a0505}
.chain-btn[data-chain="sonic"].active    {border-color:#00e5b0;color:#00e5b0;background:#001a13}
.chain-btn[data-chain="pulse"].active    {border-color:#b44aff;color:#c97aff;background:#12012a}
.chain-btn[data-chain="arbitrum"].active {border-color:#28a0f0;color:#5bbef5;background:#001a2e}
.chain-btn[data-chain="sui"].active      {border-color:#4da2ff;color:#7dc0ff;background:#00112a}
.chain-btn[data-chain="ton"].active      {border-color:#0088cc;color:#33aaee;background:#001520}
.chain-note{font-size:11px;color:#555;margin-top:8px}
</style>
</head>
<body>
<header>
  <h1>&#9889; Multi-chain Sweeper</h1>
  <span style="color:#555;font-size:12px">Base &bull; BSC &bull; Ethereum &bull; Avalanche</span>
</header>

<div class="main">

  <div class="warning">
    <b>&#9888; Security warning:</b> Private keys are processed locally in Python — never run this on a remote/shared server.
    Use <b>Dry Run</b> first to verify amounts before sending real transactions.
  </div>

  <!-- Chain selector -->
  <div class="card">
    <h3>Select Chains</h3>
    <div class="chain-row">
      <button class="chain-btn active" id="chain-base"      data-chain="base"      onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#0052ff"></span>Base (ETH)
      </button>
      <button class="chain-btn"       id="chain-bsc"       data-chain="bsc"       onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#f0b90b"></span>BSC (BNB)
      </button>
      <button class="chain-btn"       id="chain-ethereum"  data-chain="ethereum"  onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#627eea"></span>Ethereum (ETH)
      </button>
      <button class="chain-btn"       id="chain-avalanche" data-chain="avalanche" onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#e84142"></span>Avalanche (AVAX)
      </button>
      <button class="chain-btn"       id="chain-sonic"     data-chain="sonic"     onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#00e5b0"></span>Sonic (S)
      </button>
      <button class="chain-btn"       id="chain-pulse"     data-chain="pulse"     onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#b44aff"></span>PulseChain (PLS)
      </button>
      <button class="chain-btn"       id="chain-arbitrum"  data-chain="arbitrum"  onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#28a0f0"></span>Arbitrum (ETH)
      </button>
      <button class="chain-btn"       id="chain-sui"       data-chain="sui"       onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#4da2ff"></span>Sui (SUI + tokens)
      </button>
      <button class="chain-btn"       id="chain-ton"       data-chain="ton"       onclick="toggleChain(this)">
        <span class="chain-dot" style="background:#0088cc"></span>TON
      </button>
    </div>
    <div class="chain-note" id="chain-note">1 chain selected</div>
  </div>

  <!-- Config card -->
  <div class="card">
    <h3>Configuration</h3>

    <label class="lbl">Recipient address — EVM chains (Base / BSC / Ethereum / Avalanche / Sonic / PulseChain)</label>
    <input type="text" id="recipient" placeholder="0x... (40 hex chars)" style="max-width:520px">

    <div id="sui-recipient-wrap" style="display:none;margin-top:10px">
      <label class="lbl" style="color:#4da2ff">Sui Recipient Address</label>
      <input type="text" id="recipient_sui" placeholder="0x... (64 hex chars — Sui address)" style="max-width:580px;border-color:#1a3a6e">
      <div style="font-size:11px;color:#4da2ff55;margin-top:4px">Sweeps: SUI + CERT + NAVX + WAL + NS + USDC + HAWAL + DEEP</div>
    </div>

    <div id="ton-recipient-wrap" style="display:none;margin-top:10px">
      <label class="lbl" style="color:#33aaee">TON Recipient Address</label>
      <input type="text" id="recipient_ton" placeholder="EQ... or UQ... (48 chars) or 0:hexstring" style="max-width:580px;border-color:#003350">
      <div style="font-size:11px;color:#0088cc55;margin-top:4px">Input: 12-word seed phrase per line &bull; Wallet V4R2 &bull; send_mode=128</div>
    </div>

    <div class="row" style="margin-top:14px">
      <div class="col">
        <label class="lbl">Concurrency (wallets in parallel)</label>
        <input type="number" id="concurrency" value="30" min="1" max="200">
      </div>
      <div class="col">
        <label class="lbl">Gas multiplier (safety buffer)</label>
        <input type="number" id="gas_mult" value="1.5" min="1.1" max="5" step="0.1">
      </div>
      <div class="col">
        <label class="lbl">Min balance to sweep (skip below)</label>
        <input type="number" id="min_eth" value="0.000001" min="0" step="0.000001">
      </div>
    </div>

    <label class="checkbox-row" id="dry-toggle" onclick="toggleDryMode()">
      <input type="checkbox" id="dry_run" onclick="event.stopPropagation();toggleDryMode()">
      <span id="dry-label" style="font-size:13px;color:#888">Dry Run (simulate — no real transactions sent)</span>
      <span class="mode-badge mode-real" id="mode-badge">&#9889; REAL MODE</span>
    </label>
  </div>

  <!-- Keys card -->
  <div class="card">
    <h3>Private Keys</h3>
    <textarea id="keys" rows="10" placeholder="EVM chains: one private key per line (hex, 0x optional)&#10;TON / Sui: one seed phrase per line — 12 words separated by spaces&#10;  e.g.: abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about&#10;Also supports: each word on its own line (auto-grouped into 12-word phrases)"></textarea>
    <div class="row" style="margin-top:12px">
      <button class="btn btn-orange" id="btn-start" onclick="startSweep()">&#9889; Start Sweep</button>
      <button class="btn btn-red"    id="btn-stop"  onclick="cancelJob()" disabled>&#9632; Stop</button>
      <button class="btn btn-green"  id="btn-csv"   onclick="exportCSV()" disabled>&#8595; Export CSV</button>
      <span id="key-count" style="color:#555;font-size:12px"></span>
    </div>
  </div>

  <!-- Progress + stats -->
  <div class="card" id="progress-card" style="display:none">
    <h3 id="progress-title">Sweeping...</h3>
    <div id="dry-banner"  class="dry-banner">&#128268; SIMULATION MODE &#8212; Kh&#244;ng c&#243; transaction th&#7853;t n&#224;o &#273;&#432;&#7907;c g&#7917;i</div>
    <div id="real-banner" class="real-banner">&#9889; REAL MODE &#8212; &#272;ang g&#7917;i transactions th&#7853;t!</div>
    <div class="stats-grid">
      <div class="stat-box"><div class="stat-val green" id="stat-sent">0</div><div class="stat-lbl" id="lbl-sent">Sent (real)</div></div>
      <div class="stat-box"><div class="stat-val blue"  id="stat-sim">0</div><div class="stat-lbl">Simulated</div></div>
      <div class="stat-box"><div class="stat-val"       id="stat-skip">0</div><div class="stat-lbl">Skipped</div></div>
      <div class="stat-box"><div class="stat-val red"   id="stat-err">0</div><div class="stat-lbl">Errors</div></div>
    </div>
    <div class="chain-totals-row" id="chain-totals"></div>
    <div class="progress-bar"><div class="progress-fill" id="prog-fill" style="width:0%"></div></div>
    <div class="status-line" id="status-line">Starting...</div>
  </div>

  <!-- Results table -->
  <div class="card" id="results-card" style="display:none">
    <h3>Results <span id="results-count" style="color:#555;font-size:11px;font-weight:normal"></span></h3>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th>#</th>
          <th>Chain</th>
          <th>Wallet Address</th>
          <th>Status</th>
          <th>Amount Swept</th>
          <th>TX Hash</th>
          <th>Note</th>
        </tr></thead>
        <tbody id="tbl-body"></tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:11px;color:#555" id="tbl-note"></div>
  </div>

</div>

<script>
const CHAIN_INFO = {
  base:      {name:'Base',      symbol:'ETH',  color:'#4d8aff', explorer:'https://basescan.org/tx/{}'},
  bsc:       {name:'BSC',       symbol:'BNB',  color:'#f0b90b', explorer:'https://bscscan.com/tx/{}'},
  ethereum:  {name:'Ethereum',  symbol:'ETH',  color:'#8fa4f0', explorer:'https://etherscan.io/tx/{}'},
  avalanche: {name:'Avalanche', symbol:'AVAX', color:'#f07070', explorer:'https://snowscan.xyz/tx/{}'},
  sonic:     {name:'Sonic',     symbol:'S',    color:'#00e5b0', explorer:'https://sonicscan.org/tx/{}'},
  pulse:     {name:'PulseChain',symbol:'PLS',  color:'#c97aff', explorer:'https://scan.pulsechain.com/tx/{}'},
  arbitrum:  {name:'Arbitrum',  symbol:'ETH',  color:'#5bbef5', explorer:'https://arbiscan.io/tx/{}'},
  sui:       {name:'Sui',       symbol:'SUI',  color:'#7dc0ff', explorer:'https://suiscan.xyz/mainnet/tx/{}'},
  ton:       {name:'TON',       symbol:'TON',  color:'#33aaee', explorer:'https://tonscan.org/tx/{}'},
};

let currentJob   = null;
let pollTimer    = null;
let allResults   = [];
let loadedOffset = 0;
const MAX_DISPLAY = 5000;

function getSelectedChains() {
  return [...document.querySelectorAll('.chain-btn.active')].map(b => b.dataset.chain);
}

function toggleChain(btn) {
  btn.classList.toggle('active');
  const sel = getSelectedChains();
  document.getElementById('sui-recipient-wrap').style.display = sel.includes('sui') ? '' : 'none';
  document.getElementById('ton-recipient-wrap').style.display = sel.includes('ton') ? '' : 'none';
  updateChainNote();
}

function updateChainNote() {
  const sel = getSelectedChains();
  const kn  = document.getElementById('keys').value.split('\n').filter(l => l.trim()).length;
  const tot = kn * sel.length;
  document.getElementById('chain-note').textContent =
    sel.length === 0 ? '⚠️ Select at least one chain' :
    `${sel.length} chain${sel.length > 1 ? 's' : ''} selected${kn ? ' — ' + tot.toLocaleString() + ' total sweeps' : ''}`;
}

function toggleDryMode() {
  const cb    = document.getElementById('dry_run');
  const badge = document.getElementById('mode-badge');
  const lbl   = document.getElementById('dry-label');
  const toggle= document.getElementById('dry-toggle');
  if (cb.checked) {
    badge.className   = 'mode-badge mode-sim';
    badge.textContent = '\u{1F4A4} SIMULATION';
    lbl.style.color   = '#00c8ff';
    toggle.style.borderColor = '#00c8ff44';
  } else {
    badge.className   = 'mode-badge mode-real';
    badge.textContent = '⚡ REAL MODE';
    lbl.style.color   = '#ff5252';
    toggle.style.borderColor = '#ff174488';
  }
}

document.getElementById('keys').addEventListener('input', () => {
  const n = document.getElementById('keys').value.split('\n').filter(l => l.trim()).length;
  document.getElementById('key-count').textContent = n ? `${n.toLocaleString()} keys` : '';
  updateChainNote();
});

function initChainTotals(chains, isDry) {
  const container = document.getElementById('chain-totals');
  container.innerHTML = chains.map(ck => {
    const ci = CHAIN_INFO[ck] || {name: ck, symbol: '?', color: '#888'};
    return `<div class="chain-total-box">
      <div class="chain-total-val" id="ctot-${ck}" style="color:${ci.color}">0.000000 ${ci.symbol}</div>
      <div class="chain-total-name">${ci.name}${isDry ? ' (sim)' : ''}</div>
    </div>`;
  }).join('');
}

function updateChainTotals(totals) {
  for (const [ck, val] of Object.entries(totals)) {
    const el = document.getElementById(`ctot-${ck}`);
    if (!el) continue;
    const ci = CHAIN_INFO[ck] || {symbol: '?'};
    el.textContent = `${parseFloat(val).toFixed(6)} ${ci.symbol}`;
  }
}

async function startSweep() {
  const keys       = document.getElementById('keys').value;
  const recipient  = document.getElementById('recipient').value.trim();
  const concurrency= parseInt(document.getElementById('concurrency').value) || 30;
  const gas_mult   = parseFloat(document.getElementById('gas_mult').value) || 1.5;
  const min_eth    = parseFloat(document.getElementById('min_eth').value) || 0;
  const dry_run    = document.getElementById('dry_run').checked;
  const chains     = getSelectedChains();

  const recipient_sui = document.getElementById('recipient_sui').value.trim();
  const recipient_ton = document.getElementById('recipient_ton').value.trim();
  if (!chains.length) { alert('Select at least one chain'); return; }
  const evmChains = chains.filter(c => !['sui','ton'].includes(c));
  const hasSui    = chains.includes('sui');
  const hasTon    = chains.includes('ton');
  if (evmChains.length && (!recipient.startsWith('0x') || recipient.length !== 42)) {
    alert('Please enter a valid EVM recipient address (0x + 40 hex chars)');
    return;
  }
  if (hasSui && (!recipient_sui.startsWith('0x') || recipient_sui.length !== 66)) {
    alert('Please enter a valid Sui recipient address (0x + 64 hex chars)');
    return;
  }
  if (hasTon && recipient_ton.length < 48) {
    alert('Please enter a valid TON recipient address (EQ.../UQ... or 0:hex)');
    return;
  }
  const keyList = keys.split('\n').filter(l => l.trim());
  if (!keyList.length) { alert('Please enter at least one private key'); return; }

  const totalOps = keyList.length * chains.length;
  const confirmed = dry_run || confirm(
    `REAL SWEEP\n\nWallets: ${keyList.length.toLocaleString()}\nChains: ${chains.join(', ')}\nTotal txs: ${totalOps.toLocaleString()}\nRecipient: ${recipient}\n\nThis will send REAL transactions. Continue?`
  );
  if (!confirmed) return;

  // Reset UI
  allResults = []; loadedOffset = 0;
  document.getElementById('tbl-body').innerHTML = '';
  document.getElementById('results-card').style.display  = 'none';
  document.getElementById('progress-card').style.display = 'block';
  document.getElementById('dry-banner').style.display    = dry_run ? 'block' : 'none';
  document.getElementById('real-banner').style.display   = dry_run ? 'none'  : 'block';
  document.getElementById('btn-start').disabled = true;
  document.getElementById('btn-stop').disabled  = false;
  document.getElementById('btn-csv').disabled   = true;
  setStats(0, 0, 0, 0);
  initChainTotals(chains, dry_run);

  const r = await fetch('/api/sweep/start', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({keys, recipient, recipient_sui, recipient_ton, concurrency, gas_mult, min_eth, dry_run, chains}),
  });
  const d = await r.json();
  if (!d.ok) { alert('Error: ' + d.error); resetBtn(); return; }

  currentJob = d.job_id;
  pollTimer  = setInterval(poll, 1000);
}

async function cancelJob() {
  if (!currentJob) return;
  await fetch(`/api/sweep/${currentJob}/cancel`, {method:'POST'});
  document.getElementById('btn-stop').disabled = true;
}

async function poll() {
  if (!currentJob) return;
  const r = await fetch(`/api/job/${currentJob}`);
  const d = await r.json();
  if (!d.ok) return;

  const {progress, total, status, stats, dry_run: isDry} = d;
  const pct = total ? Math.round(progress / total * 100) : 0;
  document.getElementById('prog-fill').style.width    = pct + '%';
  document.getElementById('status-line').textContent  =
    `${status === 'running' ? 'Processing' : status} — ${progress.toLocaleString()} / ${total.toLocaleString()} (${pct}%)`;
  document.getElementById('progress-title').textContent =
    status === 'done'      ? (isDry ? 'Simulation complete' : 'SWEEP COMPLETE') :
    status === 'cancelled' ? 'Cancelled' :
    (isDry ? 'Simulating...' : 'Sweeping (REAL)...');

  setStats(stats.sent, stats.simulated, stats.skip, stats.errors);
  updateChainTotals(stats.totals || {});

  await loadResults();

  if (status === 'done' || status === 'cancelled') {
    clearInterval(pollTimer);
    await loadResults(true);
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-stop').disabled  = true;
    document.getElementById('btn-csv').disabled   = false;
  }
}

async function loadResults(final = false) {
  if (!currentJob) return;
  const limit = 200;
  while (true) {
    const r = await fetch(`/api/job/${currentJob}/results?offset=${loadedOffset}&limit=${limit}`);
    const d = await r.json();
    if (!d.ok || !d.results.length) break;
    d.results.forEach(row => {
      allResults.push(row);
      if (allResults.length <= MAX_DISPLAY) appendRow(allResults.length, row);
    });
    loadedOffset += d.results.length;
    document.getElementById('results-card').style.display = 'block';
    document.getElementById('results-count').textContent  =
      `(${allResults.length.toLocaleString()} rows${allResults.length >= MAX_DISPLAY ? ' — showing first ' + MAX_DISPLAY : ''})`;
    if (d.results.length < limit) break;
    if (!final) break;
  }
}

function appendRow(idx, row) {
  const tbody = document.getElementById('tbl-body');
  const s     = row.status;
  const badge = s === 'sent'     ? '<span class="badge bg-sent">SENT</span>'   :
                s === 'skip'     ? '<span class="badge bg-skip">SKIP</span>'   :
                s === 'dry_run'  ? '<span class="badge bg-dry">DRY</span>'    :
                s === 'error'    ? '<span class="badge bg-err">ERR</span>'    :
                s === 'cancelled'? '<span class="badge bg-cancel">CANCEL</span>' :
                                   '<span class="badge bg-invalid">KEY?</span>';

  const ci = CHAIN_INFO[row.chain_key] || {name: row.chain || '?', symbol: '?', color: '#888', explorer: null};
  const chainCell = `<span style="color:${ci.color};font-weight:700">${ci.name}</span>`;

  const amtStr  = row.amount_swept > 0 ? `${row.amount_swept.toFixed(9)} ${ci.symbol}` : '-';

  let txLink = '-';
  if (row.tx_hash && ci.explorer) {
    const url = ci.explorer.replace('{}', row.tx_hash);
    txLink = `<a href="${url}" target="_blank">${row.tx_hash.slice(0,14)}...</a>`;
  }

  // Address cell: full address, click to copy
  const addrFull = row.address !== '?' ? row.address : '?';
  const addrCell = addrFull === '?' ? '?' :
    `<span class="copy-addr" onclick="copyAddr(this,'${addrFull}')" title="Click to copy">${addrFull}</span>`;

  const tr = document.createElement('tr');
  tr.innerHTML =
    `<td>${idx}</td><td>${chainCell}</td><td>${addrCell}</td>` +
    `<td>${badge}</td><td>${amtStr}</td><td>${txLink}</td>` +
    `<td style="color:#555;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${row.note}">${row.note}</td>`;
  tbody.appendChild(tr);
}

function setStats(sent, sim, skip, errs) {
  document.getElementById('stat-sent').textContent = sent.toLocaleString();
  document.getElementById('stat-sim').textContent  = sim.toLocaleString();
  document.getElementById('stat-skip').textContent = skip.toLocaleString();
  document.getElementById('stat-err').textContent  = errs.toLocaleString();
}

function resetBtn() {
  document.getElementById('btn-start').disabled = false;
  document.getElementById('btn-stop').disabled  = true;
}

function exportCSV() {
  const header = ['no','chain','address','status','amount_swept','symbol','tx_hash','note'];
  const rows   = allResults.map((r, i) => {
    const ci = CHAIN_INFO[r.chain_key] || {symbol: '?'};
    return [
      i + 1, r.chain || '', r.address, r.status,
      r.amount_swept, ci.symbol, r.tx_hash,
      `"${(r.note || '').replace(/"/g, '""')}"`,
    ].join(',');
  });
  const blob = new Blob([header.join(',') + '\n' + rows.join('\n')], {type:'text/csv'});
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), {
    href: url, download: `sweep_${Date.now()}.csv`
  });
  a.click(); URL.revokeObjectURL(url);
}

function copyAddr(el, addr) {
  navigator.clipboard.writeText(addr).then(function() {
    el.classList.add('copied');
    var orig = el.textContent;
    el.textContent = 'Copied!';
    setTimeout(function() {
      el.classList.remove('copied');
      el.textContent = addr;
    }, 1200);
  }).catch(function() {
    // Fallback nếu clipboard API không có (HTTP)
    var ta = document.createElement('textarea');
    ta.value = addr; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    el.classList.add('copied');
    setTimeout(function() { el.classList.remove('copied'); }, 1200);
  });
}
</script>
</body>
</html>
"""


# ── App setup ────────────────────────────────────────────────────

app = web.Application()
app.router.add_get("/",                           handle_index)
app.router.add_post("/api/sweep/start",           handle_sweep_start)
app.router.add_post("/api/sweep/{job_id}/cancel", handle_sweep_cancel)
app.router.add_get("/api/job/{job_id}",           handle_job_status)
app.router.add_get("/api/job/{job_id}/results",   handle_job_results)

if __name__ == "__main__":
    print("=" * 60)
    print("  Multi-chain Sweeper — EVM (7 chains) + Sui + TON")
    print("  Dashboard: http://localhost:5015")
    print("=" * 60)
    web.run_app(app, host="127.0.0.1", port=5015, print=None)
