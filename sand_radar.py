#!/usr/bin/env python3
"""
SAND flow radar — polls Arkham for SAND movement and raises flow alerts.

Usage
-----
    python sand_radar.py --probe          # check API key + endpoint paths first
    python sand_radar.py                  # run the radar loop
    python sand_radar.py --once           # single pass, useful in cron
    python sand_radar.py --min-usd 25000 --interval 120

Output goes to stdout and, per poll, one JSON line to data/sand_radar.jsonl so
you can replay history or chart it later.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from collections import deque
from dataclasses import asdict
from typing import Deque, Optional

from data.arkham_client import ArkhamClient, ArkhamError
from engine.flow_radar import aggregate, evaluate
from utils.config import cfg
from utils.logger import get_logger

log = get_logger("sand_radar")

HIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sand_radar.jsonl")

_stop = asyncio.Event()


def _fmt_usd(v: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:,.2f}{unit}"
    return f"${v:,.0f}"


def _render(snap, alerts, price_note: str = "") -> str:
    bar = "─" * 66
    lines = [
        bar,
        f" SAND FLOW RADAR  ·  {time.strftime('%Y-%m-%d %H:%M:%S')}  ·  window {snap.window_secs // 60}m",
        bar,
        f" transfers tracked : {snap.transfer_count}",
        f" CEX inflow        : {_fmt_usd(snap.cex_in_usd):>12}   (wallets → exchange, sell pressure)",
        f" CEX outflow       : {_fmt_usd(snap.cex_out_usd):>12}   (exchange → wallets, accumulation)",
        f" CEX net           : {_fmt_usd(snap.cex_net_usd):>12}   ratio {snap.cex_ratio:.2f}"
        f"  {'BEARISH' if snap.cex_net_usd > 0 else 'BULLISH'}",
        f" DEX in / out      : {_fmt_usd(snap.dex_in_usd)} / {_fmt_usd(snap.dex_out_usd)}",
        f" bridge flow       : {_fmt_usd(snap.bridge_usd)}",
    ]
    if price_note:
        lines.append(f" price             : {price_note}")

    if snap.per_entity:
        lines.append("")
        lines.append(" top counterparties:")
        ranked = sorted(snap.per_entity.items(), key=lambda kv: kv[1], reverse=True)
        for name, usd in ranked[:6]:
            lines.append(f"   {name:<34} {_fmt_usd(usd):>12}")

    if snap.largest:
        lines.append("")
        lines.append(" largest transfers:")
        for t in snap.largest:
            usd = float(t.get("historicalUSD") or t.get("unitValue") or t.get("usd") or 0)
            frm = (t.get("fromAddress") or {}).get("name") or (t.get("fromAddress") or {}).get("address", "?")
            to = (t.get("toAddress") or {}).get("name") or (t.get("toAddress") or {}).get("address", "?")
            lines.append(f"   {_fmt_usd(usd):>10}  {str(frm)[:22]:<22} → {str(to)[:22]}")

    if alerts:
        lines.append("")
        for a in alerts:
            mark = {"CRIT": "!!", "WARN": " !", "INFO": "  "}.get(a.level, "  ")
            lines.append(f" {mark} [{a.level}] {a.code}: {a.message}")
    else:
        lines.append("")
        lines.append("    no alerts — flow within normal bounds")

    lines.append(bar)
    return "\n".join(lines)


def _persist(snap, alerts) -> None:
    try:
        os.makedirs(os.path.dirname(HIST_PATH), exist_ok=True)
        row = {
            "ts": int(time.time()),
            "transfers": snap.transfer_count,
            "cex_in_usd": round(snap.cex_in_usd, 2),
            "cex_out_usd": round(snap.cex_out_usd, 2),
            "cex_net_usd": round(snap.cex_net_usd, 2),
            "dex_in_usd": round(snap.dex_in_usd, 2),
            "dex_out_usd": round(snap.dex_out_usd, 2),
            "bridge_usd": round(snap.bridge_usd, 2),
            "alerts": [asdict(a) for a in alerts],
        }
        with open(HIST_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("could not append history: %s", e)


async def run(args: argparse.Namespace) -> int:
    watchlist = set(cfg.SAND_WATCHLIST)
    baselines: Deque[float] = deque(maxlen=cfg.RADAR_BASELINE_WINDOW)

    async with ArkhamClient() as ark:
        if args.probe:
            print("probing Arkham endpoints for SAND …\n")
            results = await ark.probe(cfg.SAND_TOKEN_ETH, "ethereum")
            width = max(len(k) for k in results)
            for name, status in results.items():
                print(f"  {name:<{width}}  {status}")
            ok = sum(1 for v in results.values() if v == "OK")
            print(f"\n{ok}/{len(results)} endpoints reachable.")
            if ok == 0:
                print("Fix ARKHAM_API_KEY in .env, or correct EP paths in data/arkham_client.py.")
                return 1
            return 0

        while not _stop.is_set():
            try:
                transfers = await ark.transfers(
                    cfg.SAND_TOKEN_ETH,
                    chains=args.chains,
                    since_secs=args.window,
                    min_usd=args.min_usd,
                    limit=args.limit,
                )
                snap = aggregate(transfers, args.window, watchlist)
                baseline = sum(baselines) / len(baselines) if baselines else None
                alerts = evaluate(snap, baseline)
                baselines.append(snap.cex_net_usd)

                print(_render(snap, alerts))
                _persist(snap, alerts)

            except ArkhamError as e:
                log.error("Arkham: %s", e)
                if args.once:
                    return 1
            except Exception as e:
                log.exception("radar pass failed: %s", e)

            if args.once:
                return 0

            try:
                await asyncio.wait_for(_stop.wait(), timeout=args.interval)
            except asyncio.TimeoutError:
                pass

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="SAND flow radar (Arkham)")
    p.add_argument("--probe", action="store_true", help="test API key and endpoint paths, then exit")
    p.add_argument("--once", action="store_true", help="single pass then exit")
    p.add_argument("--interval", type=float, default=cfg.RADAR_INTERVAL, help="seconds between polls")
    p.add_argument("--window", type=int, default=cfg.RADAR_WINDOW_SECS, help="lookback window in seconds")
    p.add_argument("--min-usd", type=float, default=cfg.RADAR_MIN_USD, help="ignore transfers below this USD value")
    p.add_argument("--limit", type=int, default=200, help="max transfers per poll")
    p.add_argument("--chains", default="ethereum,polygon", help="comma-separated chains")
    args = p.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop.set)
        except NotImplementedError:
            pass                                    # Windows
    try:
        return loop.run_until_complete(run(args))
    except KeyboardInterrupt:
        return 0
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
