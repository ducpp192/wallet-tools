from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
from typing import List, Deque, Tuple


@dataclass
class TokenState:
    symbol: str

    # ── CMC data ──────────────────────────────────────────────
    market_cap:        float = 0.0
    volume_24h:        float = 0.0
    volume_change_24h: float = 0.0

    # ── Binance REST data ─────────────────────────────────────
    price:    float = 0.0
    high_24h: float = 0.0
    low_24h:  float = 0.0

    price_1h_ago:        float = 0.0
    price_change_1h_pct: float = 0.0

    # orderbook
    imbalance:  float = 1.0   # bid_vol / ask_vol
    spread_pct: float = 0.0

    # ── WebSocket-derived metrics ─────────────────────────────
    buy_ratio:     float = 0.5
    trade_freq:    float = 0.0   # trades/sec
    recent_volume: float = 0.0   # sum qty of last 50 trades
    avg_volume_1m: float = 0.0   # rolling avg of per-minute volumes

    # ── Momentum (computed each scoring pass) ─────────────────
    momentum_1m: float = 0.0   # % change vs 60s ago
    momentum_5m: float = 0.0   # % change vs 300s ago

    # ── Detection flags ───────────────────────────────────────
    pump_detected: bool = False
    dump_detected: bool = False

    # ── Signal output ─────────────────────────────────────────
    signal:  str       = "IGNORE"
    score:   int       = 0
    reasons: List[str] = field(default_factory=list)

    # ── Timestamps ────────────────────────────────────────────
    last_rest_update: float = 0.0
    last_signal_time: float = 0.0   # cooldown tracker

    # ── Internal rolling state (not serialised) ───────────────
    # (timestamp, price) snapshots for momentum
    _price_snapshots: Deque[Tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=400), repr=False
    )
    # (is_buy: bool, qty: float) last 50 trades
    _recent_trades: Deque[Tuple[bool, float]] = field(
        default_factory=lambda: deque(maxlen=50), repr=False
    )
    # timestamps of recent trades (for freq calc)
    _trade_timestamps: Deque[float] = field(
        default_factory=lambda: deque(maxlen=50), repr=False
    )
    # completed 1-minute volume buckets (base-asset qty)
    _volume_buckets: Deque[float] = field(
        default_factory=lambda: deque(maxlen=19), repr=False
    )
    _current_bucket_vol: float = 0.0
    _bucket_start:       float = 0.0

    # last 20 1-min candle highs for breakout detection
    _kline_highs: Deque[float] = field(
        default_factory=lambda: deque(maxlen=20), repr=False
    )
