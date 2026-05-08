"""
Scoring rubric (from config defaults):
  Pump (buy_ratio >= 0.70)   → +3 ; only imbalance adds on top
  Vol spike (>2x avg_vol_1m) → +1 (non-pump path)
  Momentum positive 1m/5m    → +1 (non-pump path)
  Breakout (near 20-bar high)→ +1 (non-pump path)
  Order imbalance ≥ 2.0      → +1
  Weak volume                → -1 (non-pump path)
  Order bear ≤ 0.5           → -1
  Dump (sell_ratio ≥ 0.80)   → -2 ; vol spike partially offsets (+1)
"""
import time
from typing import Dict, List, Tuple

from models.token_state import TokenState
from engine.pump_detector import compute_metrics, compute_momentum
from utils.config import Config, cfg as _cfg


def _score(state: TokenState, cfg: Config) -> Tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []

    if state.price <= 0:
        return 0, []

    highs = list(state._kline_highs)
    max_high = max(highs) if highs else 0.0

    # ── PUMP path ────────────────────────────────────────────
    if state.pump_detected:
        score += 3
        reasons.append(f"buy_ratio:{state.buy_ratio:.2f}")
        if state.trade_freq >= 1.0:
            reasons.append(f"freq:{state.trade_freq:.1f}/s")

        # Imbalance still applies
        if state.imbalance >= cfg.IMBALANCE_BULL:
            score += 1
            reasons.append(f"imb_bull:{state.imbalance:.2f}")
        elif state.imbalance <= cfg.IMBALANCE_BEAR:
            score -= 1
            reasons.append(f"imb_bear:{state.imbalance:.2f}")

        # Informational notes (no score change)
        if state.momentum_1m != 0 or state.momentum_5m != 0:
            reasons.append(f"momentum:1m={state.momentum_1m:+.2f}%,5m={state.momentum_5m:+.2f}%")
        if max_high > 0 and state.price >= max_high * 0.999:
            reasons.append(f"breakout:{state.price:.6g}>{max_high:.6g}")
        if abs(state.momentum_1m) >= 0.01:
            reasons.append(f"price{state.momentum_1m:+.2f}%")

    # ── DUMP path ─────────────────────────────────────────────
    elif state.dump_detected:
        score -= 2
        sell_ratio = round(1.0 - state.buy_ratio, 2)
        reasons.append(f"sell_ratio:{sell_ratio:.2f}")

        # Vol spike partially offsets dump
        if state.avg_volume_1m > 0 and state.recent_volume > cfg.VOLUME_SPIKE_MULT * state.avg_volume_1m:
            score += 1
            reasons.append(f"vol_spike:{state.recent_volume:.0f}>{cfg.VOLUME_SPIKE_MULT:.1f}x{state.avg_volume_1m:.0f}")

        if abs(state.momentum_1m) >= 0.01:
            reasons.append(f"price{state.momentum_1m:+.2f}%")

        # vol_ok confirmation note
        if state.avg_volume_1m > 0:
            min_vol = state.avg_volume_1m * 0.8
            if state.recent_volume >= min_vol:
                reasons.append(f"vol_ok:{state.recent_volume:.0f}>={min_vol:.0f}")

    # ── NORMAL path ───────────────────────────────────────────
    else:
        # Volume
        if state.avg_volume_1m > 0:
            if state.recent_volume > cfg.VOLUME_SPIKE_MULT * state.avg_volume_1m:
                score += 1
                reasons.append(
                    f"vol_spike:{state.recent_volume:.0f}>"
                    f"{cfg.VOLUME_SPIKE_MULT:.1f}x{state.avg_volume_1m:.0f}"
                )
            elif state.momentum_1m > 0 and state.recent_volume < cfg.WEAK_VOL_MULT * state.avg_volume_1m:
                score -= 1
                reasons.append(
                    f"weak_vol:{state.recent_volume:.0f}"
                    f"<0.5x{state.avg_volume_1m:.0f}"
                )

        # Momentum
        if state.momentum_1m > 0 or state.momentum_5m > 0:
            score += 1
            reasons.append(f"momentum:1m={state.momentum_1m:+.2f}%,5m={state.momentum_5m:+.2f}%")

        # Breakout
        if max_high > 0 and state.price >= max_high * 0.999:
            score += 1
            reasons.append(f"breakout:{state.price:.6g}>{max_high:.6g}")

        # Imbalance
        if state.imbalance >= cfg.IMBALANCE_BULL:
            score += 1
            reasons.append(f"imb_bull:{state.imbalance:.2f}")
        elif state.imbalance <= cfg.IMBALANCE_BEAR:
            score -= 1
            reasons.append(f"imb_bear:{state.imbalance:.2f}")

        if abs(state.momentum_1m) >= 0.01:
            reasons.append(f"price{state.momentum_1m:+.2f}%")

    return score, reasons


def run_scoring_pass(
    states: Dict[str, TokenState],
    config: Config = None,
) -> List[TokenState]:
    """Score every token in-place. Returns list of BUY tokens sorted by score."""
    if config is None:
        config = _cfg

    for state in states.values():
        if state.price <= 0:
            continue
        compute_metrics(state, config)
        compute_momentum(state)
        score, reasons = _score(state, config)
        state.score = score
        state.reasons = reasons
        if score >= config.SCORE_BUY:
            state.signal = "BUY"
        elif score <= config.SCORE_SELL:
            state.signal = "SELL"
        else:
            state.signal = "IGNORE"

    return sorted(
        [s for s in states.values() if s.signal == "BUY"],
        key=lambda s: -s.score,
    )


def build_signal_output(state: TokenState) -> dict:
    return {
        "symbol":              state.symbol,
        "signal":              state.signal,
        "score":               state.score,
        "price":               state.price,
        "market_cap":          state.market_cap,
        "volume_24h":          state.volume_24h,
        "momentum_1m_pct":     round(state.momentum_1m, 4),
        "momentum_5m_pct":     round(state.momentum_5m, 4),
        "price_1h_ago":        state.price_1h_ago,
        "price_change_1h_pct": round(state.price_change_1h_pct, 4),
        "imbalance":           round(state.imbalance, 4),
        "spread_pct":          round(state.spread_pct, 4),
        "buy_ratio":           round(state.buy_ratio, 4),
        "trade_freq":          round(state.trade_freq, 3),
        "recent_volume":       round(state.recent_volume, 4),
        "avg_volume_1m":       round(state.avg_volume_1m, 4),
        "pump_detected":       state.pump_detected,
        "dump_detected":       state.dump_detected,
        "reasons":             state.reasons[:6],
        "timestamp":           time.time(),
    }
