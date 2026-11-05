"""Scan a block range on an EVM chain, extract & classify every bytes32 word."""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from .chains import get_chain
from .classify import classify
from .extract import from_log, from_transaction
from .rpc import EvmRpc
from .store import Store


class Scanner:
    def __init__(
        self,
        chain_key: str,
        store: Store,
        *,
        include_calldata: bool = True,
        include_logs: bool = True,
        only_contracts: frozenset[str] | None = None,
        rpc: EvmRpc | None = None,
    ):
        self.chain_key = chain_key
        self.chain = get_chain(chain_key)
        self.store = store
        self.include_calldata = include_calldata
        self.include_logs = include_logs
        self.only = frozenset(a.lower() for a in only_contracts) if only_contracts else None
        self.rpc = rpc or EvmRpc(self.chain["rpcs"])

    def latest_block(self) -> int:
        return self.rpc.block_number()

    def _keep(self, contract: str | None) -> bool:
        if self.only is None:
            return True
        return contract is not None and contract in self.only

    def scan_block(self, number: int) -> int:
        """Scan one block; return number of bytes32 hits stored."""
        block = self.rpc.get_block(number, full_tx=True)
        block_hash = (block.get("hash") or "")[2:].lower() or None
        txs = block.get("transactions") or []
        known_tx = frozenset(
            (t.get("hash") or "")[2:].lower() for t in txs if t.get("hash")
        )

        founds = []
        if self.include_calldata:
            for tx in txs:
                if self._keep((tx.get("to") or "").lower() or None):
                    founds.extend(from_transaction(self.chain_key, number, tx))

        if self.include_logs:
            logs = self.rpc.get_logs(number, number)
            for log in logs:
                addr = (log.get("address") or "").lower() or None
                if self._keep(addr):
                    founds.extend(
                        from_log(
                            self.chain_key,
                            number,
                            log.get("transactionHash") or "",
                            log,
                        )
                    )

        rows = []
        for f in founds:
            c = classify(
                f.hex64,
                known_tx_hashes=known_tx,
                block_hash=block_hash,
            )
            row = asdict(f)
            row["word"] = row.pop("hex64")   # store column is `word`
            row["category"] = c.category
            row["note"] = c.note
            row["value_dec"] = c.value_dec
            rows.append(row)

        self.store.add_many(rows)
        return len(rows)

    def scan_range(
        self,
        start: int,
        end: int,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        total = 0
        for n in range(start, end + 1):
            total += self.scan_block(n)
            if progress:
                progress(n, total)
        return total

    def close(self) -> None:
        self.rpc.close()
