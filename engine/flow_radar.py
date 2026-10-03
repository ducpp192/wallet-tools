"""
Turn raw Arkham transfers into directional flow signals.

The core idea: a transfer's *counterparty type* carries more information than
its size. 400k SAND moving between two unlabelled wallets is noise; the same
400k landing on a CEX deposit address is sell pressure that has not hit the
book yet.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from utils.config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

# Counterparty buckets. Arkham labels entities; we fold them into classes.
CEX_TYPES = {"cex", "exchange"}
DEX_TYPES = {"dex", "defi"}
BRIDGE_TYPES = {"bridge"}
FUND_TYPES = {"fund", "vc", "institution", "market maker"}


def _side(entry: Optional[dict]) -> str:
    """Classify one side of a transfer into a counterparty class."""
    if not entry:
        return "unknown"
    etype = (entry.get("type") or entry.get("entityType") or "").lower()
    name = (entry.get("name") or entry.get("entityName") or "").lower()

    if etype in CEX_TYPES or any(k in name for k in ("binance", "upbit", "bithumb", "okx", "coinbase", "bybit")):
        return "cex"
    if etype in BRIDGE_TYPES or "bridge" in name or "layerzero" in name:
        return "bridge"
    if etype in DEX_TYPES or any(k in name for k in ("uniswap", "sushiswap", "pancake", "curve")):
        return "dex"
    if etype in FUND_TYPES:
        return "fund"
    if entry.get("isContract"):
        return "contract"
    return "unknown"


@dataclass
class FlowSnapshot:
    """Aggregated flow over one polling window."""
    window_secs: int = 0
    transfer_count: int = 0

    cex_in_usd: float = 0.0        # wallets -> exchange  (latent sell pressure)
    cex_out_usd: float = 0.0       # exchange -> wallets  (accumulation / withdrawal)
    dex_in_usd: float = 0.0
    dex_out_usd: float = 0.0
    bridge_usd: float = 0.0
    watchlist_usd: float = 0.0

    largest: List[dict] = field(default_factory=list)
    per_entity: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    watchlist_hits: List[dict] = field(default_factory=list)

    @property
    def cex_net_usd(self) -> float:
        """Positive = net flowing ONTO exchanges = bearish."""
        return self.cex_in_usd - self.cex_out_usd

    @property
    def cex_ratio(self) -> float:
        """in / out. >1 bearish, <1 bullish. Capped for display sanity."""
        if self.cex_out_usd <= 0:
            return 99.0 if self.cex_in_usd > 0 else 1.0
        return self.cex_in_usd / self.cex_out_usd


def aggregate(transfers: Iterable[dict], window_secs: int, watchlist: Optional[set] = None) -> FlowSnapshot:
    """Fold a list of Arkham transfers into a FlowSnapshot."""
    watchlist = {a.lower() for a in (watchlist or set())}
    snap = FlowSnapshot(window_secs=window_secs)
    scored: List[Tuple[float, dict]] = []

    for t in transfers:
        usd = float(t.get("historicalUSD") or t.get("unitValue") or t.get("usd") or 0)
        if usd <= 0:
            continue

        snap.transfer_count += 1
        frm = t.get("fromAddress") or t.get("from") or {}
        to = t.get("toAddress") or t.get("to") or {}
        s_from, s_to = _side(frm), _side(to)

        if s_to == "cex" and s_from != "cex":
            snap.cex_in_usd += usd
            name = (to.get("name") or to.get("entityName") or "cex").lower()
            snap.per_entity[f"→ {name}"] += usd
        elif s_from == "cex" and s_to != "cex":
            snap.cex_out_usd += usd
            name = (frm.get("name") or frm.get("entityName") or "cex").lower()
            snap.per_entity[f"← {name}"] += usd

        if s_to == "dex":
            snap.dex_in_usd += usd
        elif s_from == "dex":
            snap.dex_out_usd += usd

        if "bridge" in (s_from, s_to):
            snap.bridge_usd += usd

        for addr_entry in (frm, to):
            addr = (addr_entry.get("address") or "").lower()
            if addr and addr in watchlist:
                snap.watchlist_usd += usd
                snap.watchlist_hits.append({
                    "address": addr, "usd": usd,
                    "tx": t.get("txid") or t.get("transactionHash", ""),
                })
                break

        scored.append((usd, t))

    scored.sort(key=lambda x: x[0], reverse=True)
    snap.largest = [t for _, t in scored[:cfg.RADAR_TOP_TRANSFERS]]
    return snap


@dataclass
class Alert:
    level: str      # "INFO" | "WARN" | "CRIT"
    code: str
    message: str


def evaluate(snap: FlowSnapshot, baseline_cex_net: Optional[float] = None) -> List[Alert]:
    """Derive alerts from a snapshot. Thresholds live in utils/config.py."""
    alerts: List[Alert] = []

    if snap.cex_in_usd >= cfg.RADAR_CEX_IN_USD_WARN:
        lvl = "CRIT" if snap.cex_in_usd >= cfg.RADAR_CEX_IN_USD_CRIT else "WARN"
        alerts.append(Alert(
            lvl, "CEX_INFLOW",
            f"${snap.cex_in_usd:,.0f} moved ONTO exchanges in {snap.window_secs // 60}m "
            f"(in/out ratio {snap.cex_ratio:.2f}) — latent sell pressure",
        ))

    if snap.cex_out_usd >= cfg.RADAR_CEX_IN_USD_WARN and snap.cex_ratio < 0.5:
        alerts.append(Alert(
            "INFO", "CEX_OUTFLOW",
            f"${snap.cex_out_usd:,.0f} withdrawn from exchanges — accumulation signal",
        ))

    if snap.bridge_usd >= cfg.RADAR_BRIDGE_USD_WARN:
        alerts.append(Alert(
            "WARN", "BRIDGE_FLOW",
            f"${snap.bridge_usd:,.0f} through bridge contracts — SAND bridges on Base/BNB "
            f"are retired, so unexpected bridge activity deserves a manual look",
        ))

    if snap.watchlist_hits:
        total = snap.watchlist_usd
        alerts.append(Alert(
            "CRIT", "WATCHLIST",
            f"watchlist address active: ${total:,.0f} across {len(snap.watchlist_hits)} transfer(s)",
        ))

    if baseline_cex_net is not None and abs(baseline_cex_net) > 1:
        delta = snap.cex_net_usd - baseline_cex_net
        if abs(delta) >= abs(baseline_cex_net) * cfg.RADAR_FLOW_SPIKE_MULT:
            direction = "sell-side" if delta > 0 else "buy-side"
            alerts.append(Alert(
                "WARN", "FLOW_SPIKE",
                f"net CEX flow swung {direction} by ${abs(delta):,.0f} vs rolling baseline",
            ))

    return alerts
