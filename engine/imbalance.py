from typing import List


def calc_imbalance(bids: List, asks: List, levels: int = 5) -> float:
    """bid_vol / ask_vol for top N levels. Returns 1.0 on zero ask."""
    bid_vol = sum(float(qty) for _, qty in bids[:levels])
    ask_vol = sum(float(qty) for _, qty in asks[:levels])
    if ask_vol == 0:
        return 0.0
    return round(bid_vol / ask_vol, 4)


def calc_spread_pct(bids: List, asks: List) -> float:
    if not bids or not asks:
        return 0.0
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    mid = (best_bid + best_ask) / 2
    if mid == 0:
        return 0.0
    return round((best_ask - best_bid) / mid * 100, 4)
