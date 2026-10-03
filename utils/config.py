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


    # ── Arkham / SAND flow radar ──────────────────────────────
    ARKHAM_API_KEY:   str   = os.getenv("ARKHAM_API_KEY", "")
    ARKHAM_BASE_URL:  str   = os.getenv("ARKHAM_BASE_URL", "https://api.arkm.com")
    ARKHAM_TIMEOUT:   float = 25.0
    ARKHAM_MAX_RETRIES: int = 4

    # SAND token contracts. Base/BNB contracts from before the Aug-2026 bridge
    # exploit are permanently retired — do NOT add them back.
    SAND_TOKEN_ETH: str = os.getenv(
        "SAND_TOKEN_ETH", "0x3845badAde8e6dFF049820680d1F14bD3903a5d0"
    )
    SAND_TOKEN_POLYGON: str = os.getenv(
        "SAND_TOKEN_POLYGON", "0xBbba073C31bF03b8ACf7c28EF0738DeCF3695683"
    )

    # Addresses worth a hard alert whenever they move: exploiter wallets,
    # compensation treasury, team/vesting. Fill from the official post-mortem.
    SAND_WATCHLIST: tuple = tuple(
        a.strip() for a in os.getenv("SAND_WATCHLIST", "").split(",") if a.strip()
    )

    RADAR_INTERVAL:        float = 180     # seconds between polls
    RADAR_WINDOW_SECS:     int   = 3600    # lookback per poll
    RADAR_MIN_USD:         float = 50_000  # ignore dust
    RADAR_TOP_TRANSFERS:   int   = 5
    RADAR_BASELINE_WINDOW: int   = 12      # polls kept for the rolling baseline

    RADAR_CEX_IN_USD_WARN:  float = 500_000
    RADAR_CEX_IN_USD_CRIT:  float = 2_000_000
    RADAR_BRIDGE_USD_WARN:  float = 100_000
    RADAR_FLOW_SPIKE_MULT:  float = 3.0


cfg = Config()
