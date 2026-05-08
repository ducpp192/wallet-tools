import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # API
    CMC_API_KEY: str = os.getenv("CMC_API_KEY", "")

    # Universe filter
    MARKET_CAP_MIN:        float = 50_000_000
    MARKET_CAP_MAX:        float = 500_000_000
    VOLUME_24H_MIN:        float = 5_000_000
    MAX_TOKENS:            int   = 40
    PRICE_SKIP_THRESHOLD:  float = 0.10   # skip if already up >10% in 24h

    # Signal scoring thresholds
    PUMP_BUY_RATIO:   float = 0.70
    DUMP_SELL_RATIO:  float = 0.80
    VOLUME_SPIKE_MULT: float = 2.0
    WEAK_VOL_MULT:    float = 0.5
    IMBALANCE_BULL:   float = 2.0
    IMBALANCE_BEAR:   float = 0.5
    SCORE_BUY:        int   = 3
    SCORE_SELL:       int   = -1

    # Cooldown between repeat signals for same token
    SIGNAL_COOLDOWN_SECS: float = 120

    # Console
    TOP_SIGNALS: int = 5

    # Refresh intervals (seconds)
    CMC_REFRESH_INTERVAL:  float = 300
    REST_REFRESH_INTERVAL: float = 30
    SIGNAL_INTERVAL:       float = 5
    CONSOLE_INTERVAL:      float = 10

    # WebSocket
    WS_MAX_STREAMS:    int   = 200
    WS_RECONNECT_DELAY: float = 5


cfg = Config()
