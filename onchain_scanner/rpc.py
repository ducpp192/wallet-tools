"""Minimal, resilient JSON-RPC client for EVM chains (read-only).

Rotates across a list of public RPC endpoints, retrying on failure so a
single flaky node does not abort a scan.
"""

from __future__ import annotations

import itertools
import time
from typing import Any

import httpx


class RpcError(RuntimeError):
    pass


class EvmRpc:
    def __init__(self, rpcs: list[str], timeout: float = 20.0, max_retries: int = 4):
        if not rpcs:
            raise ValueError("No RPC endpoints provided")
        self._rpcs = list(rpcs)
        self._cycle = itertools.cycle(self._rpcs)
        self._timeout = timeout
        self._max_retries = max_retries
        self._id = 0
        self._client = httpx.Client(timeout=timeout, headers={"content-type": "application/json"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EvmRpc":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        last_err: Exception | None = None
        # try each endpoint up to max_retries total, with light backoff
        for attempt in range(self._max_retries):
            url = next(self._cycle)
            try:
                resp = self._client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data and data["error"]:
                    raise RpcError(f"{method}: {data['error']}")
                return data.get("result")
            except (httpx.HTTPError, RpcError, ValueError) as e:
                last_err = e
                time.sleep(min(2 ** attempt * 0.25, 4.0))
        raise RpcError(f"RPC '{method}' failed after {self._max_retries} tries: {last_err}")

    # ── convenience wrappers ──────────────────────────────────────
    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_block(self, number: int, full_tx: bool = True) -> dict:
        res = self.call("eth_getBlockByNumber", [hex(number), full_tx])
        if res is None:
            raise RpcError(f"Block {number} not found")
        return res

    def get_logs(self, from_block: int, to_block: int) -> list[dict]:
        return self.call(
            "eth_getLogs",
            [{"fromBlock": hex(from_block), "toBlock": hex(to_block)}],
        ) or []
