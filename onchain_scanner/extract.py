"""Extract 32-byte words from EVM transactions and event logs.

A transaction's `input` is parsed as a 4-byte selector followed by 32-byte
ABI words. Event logs contribute their indexed `topics` (each 32 bytes) and
their `data` payload (also split into 32-byte words). Every word is yielded
with provenance so the classifier and store can record where it came from.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Found:
    chain: str
    block: int
    tx_hash: str
    source: str          # "calldata" | "log_topic" | "log_data"
    position: int        # word index within its source
    selector: str | None # function selector for calldata, else event sig topic0
    contract: str | None # tx `to` (calldata) or log `address`
    hex64: str           # normalized 64-hex word (no 0x)


def _strip(hexstr: str) -> str:
    return hexstr[2:] if hexstr.startswith(("0x", "0X")) else hexstr


def _words(payload: str) -> list[str]:
    """Split a hex payload into 32-byte (64 hex char) words, dropping a trailing
    partial word."""
    h = _strip(payload)
    return [h[i : i + 64] for i in range(0, len(h) - len(h) % 64, 64)]


def from_transaction(chain: str, block: int, tx: dict) -> list[Found]:
    out: list[Found] = []
    inp = _strip(tx.get("input") or "")
    tx_hash = (tx.get("hash") or "").lower()
    to = (tx.get("to") or None)
    if to:
        to = to.lower()

    if len(inp) >= 8:
        selector = "0x" + inp[:8]
        body = inp[8:]
    else:
        selector = None
        body = inp

    for i, w in enumerate(_words(body)):
        out.append(
            Found(chain, block, tx_hash, "calldata", i, selector, to, w.lower())
        )
    return out


def from_log(chain: str, block: int, tx_hash: str, log: dict) -> list[Found]:
    out: list[Found] = []
    addr = (log.get("address") or None)
    if addr:
        addr = addr.lower()
    topics = log.get("topics") or []
    topic0 = topics[0].lower() if topics else None

    # indexed topics: topic0 is the event signature; topics[1:] are values
    for i, t in enumerate(topics):
        tn = _strip(t)
        if len(tn) == 64:
            out.append(
                Found(chain, block, tx_hash.lower(), "log_topic", i, topic0, addr, tn.lower())
            )

    for i, w in enumerate(_words(log.get("data") or "")):
        out.append(
            Found(chain, block, tx_hash.lower(), "log_data", i, topic0, addr, w.lower())
        )
    return out
