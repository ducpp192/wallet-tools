# 🚀 Crypto Scanner — Pump/Dump Signal Engine + Wallet Tools

A real-time cryptocurrency signal scanner built with **Python + aiohttp**, featuring pump/dump detection, order book imbalance analysis, and multi-chain wallet utilities.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

---

## ✨ Features

### 📡 Signal Scanner (port 5012)
- Real-time **BUY/SELL signal engine** scanning mid-cap tokens on Binance
- **Pump/dump detection** via volume spike, price momentum, order book imbalance
- **WebSocket live feed** from Binance trade stream
- **CoinMarketCap integration** for mid-cap universe filtering
- Web dashboard showing live signals with score, price change, volume

### 🔍 Wallet Tools
- **`wallet_server.py`** (port 5013) — BIP44 HD wallet generator & holdings viewer
- **`sweep_server.py`** (port 5015) — Multi-chain asset scanner (ETH, Base, BSC, Arbitrum)
- **`basescan_holdings.py`** — Scan token holdings for any wallet on Base chain
- **`lp_server.py`** — LP pool checker (Uniswap v2/v3, Aerodrome, SushiSwap)
- **`onchain_scanner/`** — index & classify 32-byte (`0x`+64hex) words in ERC-20 (Ethereum) & BEP-20/BSC calldata and event logs → SQLite/CSV (read-only data analysis; see `onchain_scanner/README.md`)

---

## 🏗️ Project Structure

```
crypto-scanner/
├── main.py                 # Entry point — starts all servers
├── dashboard.py            # Web dashboard (port 5012)
├── wallet_server.py        # Wallet generator & viewer (port 5013)
├── sweep_server.py         # Multi-chain asset sweeper (port 5015)
├── lp_server.py            # LP pool checker
├── basescan_holdings.py    # Base chain wallet scanner
│
├── data/
│   ├── cmc_client.py       # CoinMarketCap API client
│   ├── binance_rest.py     # Binance REST (klines, tickers, orderbook)
│   └── binance_ws.py       # Binance WebSocket trade stream
│
├── engine/
│   ├── signal_engine.py    # Weighted signal scoring (0–100)
│   ├── pump_detector.py    # Pump/dump pattern detection
│   └── imbalance.py        # Order book imbalance analysis
│
├── models/
│   └── token_state.py      # Per-token runtime state
│
└── utils/
    ├── config.py           # Config loader (reads .env)
    └── logger.py           # Logging setup
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API keys
```bash
cp .env.example .env
# Edit .env and add your CoinMarketCap API key
```

`.env` file:
```env
CMC_API_KEY=your_coinmarketcap_api_key_here
```

Get a free API key at: https://coinmarketcap.com/api/

### 3. Run
```bash
python main.py
```

- Dashboard: http://localhost:5012
- Wallet tools: http://localhost:5013
- Sweep scanner: http://localhost:5015

---

## ⚙️ How It Works

1. **CMC Client** fetches mid-cap token list (market cap $1M–$500M) every 5 minutes
2. **Binance REST** enriches each token with klines, orderbook, funding rate
3. **Binance WS** streams live trades for real-time buy/sell pressure
4. **Signal Engine** scores each token 0–100:
   - Volume spike vs 20-period average
   - Price momentum (1m, 5m)
   - Order book imbalance (bid/ask ratio)
   - Trade flow (buy ratio from live ticks)
5. **Dashboard** displays ranked signals via web UI

---

## 🔗 Supported Chains (Wallet Tools)

| Chain | Explorer |
|-------|----------|
| Ethereum | Etherscan |
| Base | Basescan |
| BSC | BscScan |
| Arbitrum | Arbiscan |

---

## 📄 License

MIT — free to use, modify, and share.
