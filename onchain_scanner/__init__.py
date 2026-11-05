"""onchain_scanner — index & classify 32-byte (0x + 64 hex) values on-chain.

Scans transaction calldata and event logs on ERC-20 (Ethereum) and
BEP-20 / BSC chains, extracts every 32-byte word of the form `0x<64 hex>`,
and classifies each one (tx hash, address word, uint256 amount, bytes32
string, opaque hash/root/salt, zero, ...). Results go to SQLite + CSV for
on-chain data analysis.

This tool does NOT derive private keys and does NOT look up balances.
"""

__version__ = "0.1.0"
