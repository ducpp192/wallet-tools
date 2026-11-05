"""Chain definitions for the on-chain bytes32 scanner.

Only read-only JSON-RPC endpoints are used (eth_blockNumber,
eth_getBlockByNumber, eth_getTransactionReceipt / eth_getLogs).
"""

from __future__ import annotations

import os

CHAINS = {
    # ERC-20 universe
    "ethereum": {
        "name": "Ethereum",
        "chain_id": 1,
        "symbol": "ETH",
        "token_standard": "ERC-20",
        "rpcs": [
            "https://eth.llamarpc.com",
            "https://ethereum.publicnode.com",
            "https://rpc.ankr.com/eth",
            "https://cloudflare-eth.com",
            "https://eth-mainnet.public.blastapi.io",
        ],
        "explorer_tx": "https://etherscan.io/tx/{}",
    },
    # BEP-20 / "BSC-20" universe
    "bsc": {
        "name": "BSC",
        "chain_id": 56,
        "symbol": "BNB",
        "token_standard": "BEP-20",
        "rpcs": [
            "https://bsc-dataseed.binance.org",
            "https://bsc-dataseed1.defibit.io",
            "https://bsc-dataseed1.ninicoin.io",
            "https://bsc-rpc.publicnode.com",
            "https://rpc.ankr.com/bsc",
        ],
        "explorer_tx": "https://bscscan.com/tx/{}",
    },
}


def get_chain(key: str) -> dict:
    key = key.lower().strip()
    # friendly aliases
    aliases = {
        "eth": "ethereum",
        "erc20": "ethereum",
        "erc-20": "ethereum",
        "mainnet": "ethereum",
        "bnb": "bsc",
        "bep20": "bsc",
        "bep-20": "bsc",
        "bsc20": "bsc",
        "bsc-20": "bsc",
        "binance": "bsc",
    }
    key = aliases.get(key, key)
    if key not in CHAINS:
        raise KeyError(
            f"Unknown chain '{key}'. Available: {', '.join(CHAINS)} "
            f"(aliases: eth/erc20, bnb/bep20/bsc20)"
        )
    chain = dict(CHAINS[key])
    # Allow overriding RPCs from the environment, e.g.
    #   ETHEREUM_RPC="https://my-node:8545"  (comma-separated for several)
    #   BSC_RPC="https://..."
    env_val = os.getenv(f"{key.upper()}_RPC")
    if env_val:
        chain["rpcs"] = [u.strip() for u in env_val.split(",") if u.strip()]
    return chain


def all_chain_keys() -> list[str]:
    return list(CHAINS)
