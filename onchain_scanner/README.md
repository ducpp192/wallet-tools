# onchain_scanner — bytes32 indexer & classifier

Scan on-chain data on **ERC-20 (Ethereum)** and **BEP-20 / "BSC-20" (BSC)**,
find every value shaped like `0x` + 64 hex characters (a 32-byte EVM word) in
transaction **calldata** and **event logs**, classify each one, and write the
results to **SQLite** (+ optional CSV) for analysis.

> This is a read-only data-analysis tool. It only calls read JSON-RPC methods
> (`eth_blockNumber`, `eth_getBlockByNumber`, `eth_getLogs`). It does **not**
> derive private keys and does **not** query balances.

## Install

```bash
pip install -r requirements.txt   # needs httpx (already listed)
```

## Usage

```bash
# Last 5 blocks on BSC (BEP-20 / BSC-20), calldata + logs:
python -m onchain_scanner --chain bsc --last 5

# Explicit Ethereum (ERC-20) block range, custom DB + CSV export:
python -m onchain_scanner --chain eth --from 19000000 --to 19000002 \
    --db out/eth.db --csv out/eth.csv

# Only words touching a specific token contract, calldata only:
python -m onchain_scanner --chain bsc --last 10 --no-logs \
    --contract 0x55d398326f99059fF775485246999027B3197955
```

Chain aliases: `ethereum` = `eth`/`erc20`; `bsc` = `bnb`/`bep20`/`bsc20`.

### Custom RPC endpoints

The built-in public RPCs may be rate-limited or blocked by your network. Point
the scanner at your own node / provider:

```bash
python -m onchain_scanner --chain eth --last 3 --rpc https://your-node:8545
# or via environment variable (comma-separated for several):
ETHEREUM_RPC="https://node-a,https://node-b" python -m onchain_scanner --chain eth --last 3
BSC_RPC="https://your-bsc-node" python -m onchain_scanner --chain bsc --last 3
```

## Categories

Each 32-byte word is labelled:

| category         | meaning |
|------------------|---------|
| `zero`           | all-zero word |
| `bool`           | ABI bool (`0`/`1`) |
| `address`        | left-padded 20-byte address |
| `uint256_small`  | integer fitting in ≤ 8 bytes (amount / id / nonce) |
| `uint256`        | larger integer (9–31 significant bytes) |
| `timestamp`      | small int inside a plausible unix-time window |
| `selector_word`  | 4-byte function selector, zero-padded |
| `bytes32_string` | short ASCII string (right zero-padded) |
| `tx_hash`        | matches a tx hash in the same block |
| `block_hash`     | matches the block hash |
| `opaque_hash`    | high-entropy 32 bytes — hash / merkle root / salt / commit / storage slot |

## Output schema (`bytes32_hits`)

`chain, block, tx_hash, source (calldata|log_topic|log_data), position,
selector, contract, word, category, note, value_dec`

Example queries:

```sql
-- all opaque 32-byte digests seen on BSC, newest first
SELECT block, tx_hash, contract, word FROM bytes32_hits
WHERE chain='bsc' AND category='opaque_hash' ORDER BY block DESC;

-- most common function selectors carrying bytes32 args
SELECT selector, COUNT(*) FROM bytes32_hits
WHERE source='calldata' GROUP BY selector ORDER BY 2 DESC LIMIT 20;
```

## Offline self-test

```bash
python -m onchain_scanner.selftest
```
