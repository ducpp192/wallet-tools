"""CLI entry point:  python -m onchain_scanner ...

Examples
--------
  # Scan the last 5 blocks on BSC (BEP-20 / "BSC-20"), calldata + logs:
  python -m onchain_scanner --chain bsc --last 5

  # Scan an explicit Ethereum (ERC-20) block range into a chosen DB + CSV:
  python -m onchain_scanner --chain eth --from 19000000 --to 19000002 \
      --db out/eth.db --csv out/eth.csv

  # Only words touching specific token contracts, calldata only:
  python -m onchain_scanner --chain bsc --last 10 --no-logs \
      --contract 0x55d398326f99059fF775485246999027B3197955
"""

from __future__ import annotations

import argparse
import sys
import time

from .chains import all_chain_keys, get_chain
from .rpc import EvmRpc
from .scanner import Scanner
from .store import Store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="onchain_scanner",
        description="Index & classify 32-byte (0x + 64 hex) values in "
                    "ERC-20 (Ethereum) and BEP-20 (BSC) on-chain data.",
    )
    p.add_argument("--chain", required=True,
                   help="ethereum|eth|erc20  or  bsc|bnb|bep20|bsc20")
    rng = p.add_mutually_exclusive_group(required=True)
    rng.add_argument("--last", type=int, metavar="N",
                     help="scan the most recent N blocks")
    rng.add_argument("--from", dest="from_block", type=int, metavar="BLOCK",
                     help="start block (use with --to)")
    p.add_argument("--to", dest="to_block", type=int, metavar="BLOCK",
                   help="end block (inclusive; default = latest)")
    p.add_argument("--db", default="onchain_scanner_out/hits.db",
                   help="SQLite output path")
    p.add_argument("--csv", default=None, help="optional CSV export path")
    p.add_argument("--no-calldata", action="store_true",
                   help="skip transaction calldata")
    p.add_argument("--no-logs", action="store_true",
                   help="skip event logs")
    p.add_argument("--contract", action="append", default=[], metavar="ADDR",
                   help="restrict to these contract addresses (repeatable)")
    p.add_argument("--rpc", action="append", default=[], metavar="URL",
                   help="override RPC endpoint(s) for this chain (repeatable); "
                        "also settable via ETHEREUM_RPC / BSC_RPC env vars")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        chain = get_chain(args.chain)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.no_calldata and args.no_logs:
        print("error: nothing to scan (both --no-calldata and --no-logs set)",
              file=sys.stderr)
        return 2

    store = Store(args.db)
    rpc = EvmRpc(args.rpc) if args.rpc else None
    scanner = Scanner(
        args.chain,
        store,
        include_calldata=not args.no_calldata,
        include_logs=not args.no_logs,
        only_contracts=frozenset(args.contract) if args.contract else None,
        rpc=rpc,
    )

    try:
        latest = scanner.latest_block()
        if args.last is not None:
            end = latest
            start = max(0, latest - args.last + 1)
        else:
            start = args.from_block
            end = args.to_block if args.to_block is not None else latest
        if start > end:
            print(f"error: start block {start} > end block {end}", file=sys.stderr)
            return 2

        n_blocks = end - start + 1
        print(f"Chain : {chain['name']} ({chain['token_standard']}), latest block {latest}")
        print(f"Range : {start} .. {end}  ({n_blocks} block{'s' if n_blocks != 1 else ''})")
        print(f"Source: {'calldata ' if not args.no_calldata else ''}"
              f"{'logs' if not args.no_logs else ''}".strip())
        if scanner.only:
            print(f"Filter: {len(scanner.only)} contract(s)")
        print("-" * 60)

        t0 = time.time()

        def progress(block: int, total: int) -> None:
            done = block - start + 1
            print(f"  block {block}  ({done}/{n_blocks})  hits so far: {total}",
                  end="\r", flush=True)

        total = scanner.scan_range(start, end, progress=progress)
        dt = time.time() - t0
        print()  # end the \r line
        print("-" * 60)
        print(f"Done: {total} bytes32 words from {n_blocks} blocks in {dt:.1f}s")
        print(f"DB  : {args.db}")

        print("\nBreakdown by category:")
        for cat, cnt in store.counts_by_category():
            print(f"  {cat:16s} {cnt:>10,}")

        if args.csv:
            n = store.export_csv(args.csv)
            print(f"\nCSV : {args.csv}  ({n:,} rows)")

    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        scanner.close()
        store.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
