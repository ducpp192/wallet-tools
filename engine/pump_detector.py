"""
Processes raw trade ticks into per-token metrics:
  buy_ratio, trade_freq, recent_volume, avg_volume_1m,
  pump_detected, dump_detected, momentum_1m, momentum_5m.
"""
from models.token_state import TokenState
from utils.config import Config


def update_trade(state: TokenState, price: float, qty: float,
                 is_buy: bool, ts: float) -> None:
    """Record a WebSocket trade tick."""
    state.price = price
    state._recent_trades.append((is_buy, qty))
    state._trade_timestamps.append(ts)

    # 1-minute volume bucket
    if state._bucket_start == 0.0:
        state._bucket_start = ts
    if ts - state._bucket_start >= 60.0:
        state._volume_buckets.append(state._current_bucket_vol)
        state._current_bucket_vol = 0.0
        state._bucket_start = ts
    state._current_bucket_vol += qty

    # Price snapshot for momentum
    state._price_snapshots.append((ts, price))


def compute_metrics(state: TokenState, cfg: Config) -> None:
    """Recompute all derived metrics from rolling buffers."""
    trades = list(state._recent_trades)
    if not trades:
        return

    # buy_ratio
    buys = sum(1 for is_buy, _ in trades if is_buy)
    state.buy_ratio = round(buys / len(trades), 4)

    # trade_freq (trades per second over the recorded window)
    ts_list = list(state._trade_timestamps)
    if len(ts_list) >= 2:
        window = ts_list[-1] - ts_list[0]
        state.trade_freq = round(len(ts_list) / window, 3) if window > 0 else float(len(ts_list))
    else:
        state.trade_freq = 0.0

    # recent_volume (sum of qty in last 50 trades)
    state.recent_volume = round(sum(qty for _, qty in trades), 4)

    # avg_volume_1m (rolling average of completed 1-min buckets)
    buckets = list(state._volume_buckets)
    if buckets:
        state.avg_volume_1m = round(sum(buckets) / len(buckets), 4)

    # pump / dump flags
    state.pump_detected = state.buy_ratio >= cfg.PUMP_BUY_RATIO
    state.dump_detected = (1.0 - state.buy_ratio) >= cfg.DUMP_SELL_RATIO


def compute_momentum(state: TokenState) -> None:
    """Compute momentum_1m and momentum_5m from price snapshots."""
    snaps = list(state._price_snapshots)
    if not snaps or state.price <= 0:
        return

    now_ts = snaps[-1][0]

    def price_n_secs_ago(secs: float) -> float:
        target = now_ts - secs
        result = 0.0
        for ts, px in snaps:
            if ts <= target:
                result = px
        return result

    p1m = price_n_secs_ago(60)
    p5m = price_n_secs_ago(300)

    if p1m > 0:
        state.momentum_1m = round((state.price - p1m) / p1m * 100, 4)
    if p5m > 0:
        state.momentum_5m = round((state.price - p5m) / p5m * 100, 4)
