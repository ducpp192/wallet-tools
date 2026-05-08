"""
Wallet Holdings Scraper - dùng Blockscout API (FREE, không cần API key)
Hỗ trợ: Base, Avalanche
"""
import asyncio, aiohttp, csv, json, sys, os
from datetime import datetime

# ============================================================
# CONFIG - chỉnh ở đây
# ============================================================
INPUT_FILE  = "wallets.txt"   # file chứa danh sách ví
OUTPUT_CSV  = f"holdings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
NETWORKS    = ["base", "avalanche"]  # bỏ bớt nếu chỉ cần 1 network
MAX_WORKERS = 5               # scan bao nhiêu ví song song
DELAY       = 0.15            # giây giữa mỗi request

BLOCKSCOUT = {
    "base":      "https://base.blockscout.com",
    "avalanche": "https://avalanche.blockscout.com",
}
EXPLORER = {
    "base":      "https://basescan.org/token/{contract}?a={addr}",
    "avalanche": "https://snowtrace.io/token/{contract}?a={addr}",
}
# ============================================================

all_results = []
stats = {"wallets": 0, "found": 0, "empty": 0, "errors": 0}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

async def fetch_all_tokens(session, addr, network):
    """Lấy toàn bộ tokens - Blockscout cursor pagination"""
    base_url  = BLOCKSCOUT[network]
    all_items = []
    # First request: không có cursor params
    next_params = {}
    page_num = 1

    while True:
        # Build URL với cursor params nếu có
        qs = "type=ERC-20"
        for k, v in next_params.items():
            qs += f"&{k}={v}"
        url = f"{base_url}/api/v2/addresses/{addr}/tokens?{qs}"

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as r:
                if r.status != 200:
                    log(f"  [{network}] HTTP {r.status}")
                    break
                data = json.loads(await r.text())
        except Exception as e:
            log(f"  [{network}] Error: {e}")
            break

        items = data.get("items", [])
        all_items.extend(items)

        next_params = data.get("next_page_params") or {}
        if not next_params:
            break  # Hết trang

        page_num += 1
        await asyncio.sleep(DELAY)

    return all_items

async def scan_wallet(session, addr, semaphore):
    async with semaphore:
        log(f"Scanning: {addr}")
        wallet_results = []

        for network in NETWORKS:
            try:
                items = await fetch_all_tokens(session, addr, network)
                await asyncio.sleep(DELAY)

                if not items:
                    log(f"  [{network}] No tokens")
                    continue

                count = 0
                for item in items:
                    tok = item.get("token", {})
                    if not tok:
                        continue

                    name     = tok.get("name", "")
                    symbol   = tok.get("symbol", "")
                    contract = tok.get("address_hash", "") or tok.get("address", "")
                    decimals = int(tok.get("decimals") or 18)
                    price    = tok.get("exchange_rate") or "0"

                    # Balance từ item
                    raw_val = item.get("value", "0") or "0"
                    try:
                        balance = float(raw_val) / (10 ** decimals)
                    except Exception:
                        balance = 0

                    if balance <= 0:
                        continue

                    try:
                        price_usd = float(price) if price else 0
                    except Exception:
                        price_usd = 0

                    value_usd = balance * price_usd
                    explorer  = EXPLORER[network].format(contract=contract, addr=addr)

                    wallet_results.append({
                        "wallet":       addr,
                        "network":      network,
                        "token_name":   name,
                        "token_symbol": symbol,
                        "contract":     contract,
                        "balance":      f"{balance:.6f}",
                        "price_usd":    f"{price_usd:.8f}",
                        "value_usd":    f"{value_usd:.4f}",
                        "explorer":     explorer,
                    })
                    count += 1

                log(f"  [{network}] {count} tokens with balance > 0")

            except Exception as e:
                log(f"  [{network}] Error: {e}")
                stats["errors"] += 1

        stats["wallets"] += 1
        if wallet_results:
            stats["found"] += len(wallet_results)
            all_results.extend(wallet_results)
            log(f"  ✓ Total: {len(wallet_results)} holdings\n")
        else:
            stats["empty"] += 1
            log(f"  — Empty wallet\n")

def save_csv():
    print("\n" + "="*55)
    if not all_results:
        log("Không có holdings nào!")
        return

    fieldnames = ["wallet","network","token_name","token_symbol","contract","balance","price_usd","value_usd","explorer"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_results)

    print(f"  File     : {OUTPUT_CSV}")
    print(f"  Wallets  : {stats['wallets']}")
    print(f"  Holdings : {stats['found']}")
    print(f"  Empty    : {stats['empty']}")
    print(f"  Errors   : {stats['errors']}")
    print("="*55)

async def main():
    # ---- Đọc danh sách ví ----
    if len(sys.argv) > 1:
        wallets_raw = sys.argv[1:]
    elif os.path.exists(INPUT_FILE):
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            wallets_raw = f.readlines()
    else:
        print(f"Usage:")
        print(f"  python basescan_holdings.py 0xABC... 0xDEF...")
        print(f"  hoặc tạo file '{INPUT_FILE}' với mỗi dòng 1 địa chỉ")
        return

    wallets = list(dict.fromkeys(
        w.strip() for w in wallets_raw
        if w.strip().startswith("0x") and len(w.strip()) == 42
    ))

    if not wallets:
        print("Không tìm thấy địa chỉ ví hợp lệ!")
        return

    print("="*55)
    print(f"  Blockscout Holdings Scraper (NO API KEY)")
    print(f"  Networks : {', '.join(NETWORKS)}")
    print(f"  Wallets  : {len(wallets)}")
    print(f"  Output   : {OUTPUT_CSV}")
    print("="*55 + "\n")

    semaphore = asyncio.Semaphore(MAX_WORKERS)
    headers   = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        tasks = [scan_wallet(session, w, semaphore) for w in wallets]
        await asyncio.gather(*tasks)

    save_csv()

if __name__ == "__main__":
    asyncio.run(main())
