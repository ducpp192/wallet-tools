"""
crypto-pump-scanner — Web Dashboard (port 5011)

Serves a real-time HTML dashboard + JSON API.
Import and call dashboard_task() from main.py.
"""

import json
import time
from typing import Dict

from aiohttp import web

from models.token_state import TokenState
from engine.signal_engine import run_scoring_pass, build_signal_output
from utils.config import cfg
from utils.logger import get_logger

log = get_logger(__name__)

DASHBOARD_PORT = 5012

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crypto Pump Scanner</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',monospace;font-size:13px}
  header{background:#161b22;border-bottom:1px solid #30363d;padding:14px 24px;display:flex;align-items:center;gap:12px}
  header h1{font-size:17px;font-weight:700;letter-spacing:.03em}
  .dot{width:8px;height:8px;border-radius:50%;background:#3fb950;display:inline-block;animation:pulse 1.5s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .badge{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700}
  .live{background:#da3633;color:#fff}
  .updated{color:#8b949e;font-size:12px;margin-left:auto}

  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;padding:16px 24px 8px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px}
  .card .label{color:#8b949e;font-size:10px;text-transform:uppercase;letter-spacing:.05em}
  .card .value{font-size:22px;font-weight:700;margin-top:3px}
  .card .sub{font-size:11px;color:#8b949e;margin-top:2px}
  .green{color:#3fb950}.red{color:#f85149}.yellow{color:#d29922}.blue{color:#58a6ff}.purple{color:#d2a0ff}

  .section{padding:0 24px 20px}
  .section h2{font-size:12px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;
              margin-bottom:8px;padding-top:16px;display:flex;align-items:center;gap:8px}
  .cnt{background:#21262d;border-radius:10px;padding:1px 8px;font-size:11px;color:#8b949e}
  table{width:100%;border-collapse:collapse}
  th{color:#8b949e;font-size:10px;text-transform:uppercase;padding:5px 8px;
     border-bottom:1px solid #21262d;text-align:left;white-space:nowrap}
  td{padding:6px 8px;border-bottom:1px solid #21262d;font-size:12px;vertical-align:top}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:#161b22}
  .tag{padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700;white-space:nowrap}
  .buy{background:#1a2a1a;color:#3fb950}.sell{background:#2a1a1a;color:#f85149}
  .pump{background:#2d1f00;color:#d29922}.dump{background:#2a1a2a;color:#d2a0ff}
  .neutral{background:#1a1f2e;color:#58a6ff}
  .bar-wrap{width:80px;background:#21262d;border-radius:3px;height:6px;display:inline-block;vertical-align:middle}
  .bar{height:6px;border-radius:3px}
  .bar-buy{background:#3fb950}.bar-sell{background:#f85149}
  .empty{color:#8b949e;font-style:italic;text-align:center;padding:20px}
  .score-pos{color:#3fb950;font-weight:700}.score-neg{color:#f85149;font-weight:700}
  .divider{border:none;border-top:1px solid #21262d;margin:0 24px 4px}

  /* All-tokens mini table */
  .mini td,.mini th{padding:4px 8px}
  .filter-tabs{display:flex;gap:4px;margin-left:auto}
  .ftab{padding:2px 10px;border-radius:6px;font-size:11px;border:1px solid #30363d;
        background:#161b22;color:#8b949e;cursor:pointer;transition:all .15s}
  .ftab:hover{background:#21262d;color:#e6edf3}
  .ftab.active{background:#1f6feb;border-color:#1f6feb;color:#fff}
</style>
</head>
<body>
<header>
  <span class="dot"></span>
  <h1>Crypto Pump Scanner</h1>
  <span class="badge live">LIVE</span>
  <span class="updated" id="updatedAt">—</span>
</header>

<div class="stats">
  <div class="card"><div class="label">Tracking</div><div class="value blue" id="cnt">0</div><div class="sub">tokens</div></div>
  <div class="card"><div class="label">BUY Signals</div><div class="value green" id="buyCount">0</div><div class="sub">score ≥ 3</div></div>
  <div class="card"><div class="label">SELL Signals</div><div class="value red" id="sellCount">0</div><div class="sub">score ≤ -1</div></div>
  <div class="card"><div class="label">Pump Alerts</div><div class="value yellow" id="pumpCount">0</div><div class="sub">active</div></div>
  <div class="card"><div class="label">Avg Buy Ratio</div><div class="value" id="avgBuy">—</div><div class="sub">market sentiment</div></div>
  <div class="card"><div class="label">Refreshed</div><div class="value" id="scanAge">—</div><div class="sub">ago</div></div>
</div>

<!-- BUY signals -->
<div class="section">
  <h2><span class="green">▲ BUY Signals</span> <span class="cnt" id="buyBadge">0</span></h2>
  <table id="buyTable">
    <thead><tr>
      <th>Symbol</th><th>Score</th><th>Price</th><th>Mom 1m</th><th>Mom 5m</th>
      <th>Buy Ratio</th><th>Imbalance</th><th>Market Cap</th><th>Vol 24h</th><th>Vol Chg 24h</th><th>Flag</th><th>Reasons</th>
    </tr></thead>
    <tbody id="buyBody"><tr><td colspan="12" class="empty">Waiting for signals…</td></tr></tbody>
  </table>
</div>

<hr class="divider">

<!-- SELL signals -->
<div class="section">
  <h2><span class="red">▼ SELL Signals</span> <span class="cnt" id="sellBadge">0</span></h2>
  <table id="sellTable">
    <thead><tr>
      <th>Symbol</th><th>Score</th><th>Price</th><th>Mom 1m</th><th>Mom 5m</th>
      <th>Buy Ratio</th><th>Imbalance</th><th>Market Cap</th><th>Vol 24h</th><th>Vol Chg 24h</th><th>Flag</th><th>Reasons</th>
    </tr></thead>
    <tbody id="sellBody"><tr><td colspan="12" class="empty">No SELL signals</td></tr></tbody>
  </table>
</div>

<hr class="divider">

<!-- All tokens -->
<div class="section">
  <h2>
    All Tokens
    <span class="cnt" id="allBadge">0</span>
    <div class="filter-tabs" style="margin-left:auto">
      <span class="ftab active" id="f-all" onclick="setFilter('all')">All</span>
      <span class="ftab" id="f-buy" onclick="setFilter('buy')">BUY</span>
      <span class="ftab" id="f-sell" onclick="setFilter('sell')">SELL</span>
      <span class="ftab" id="f-pump" onclick="setFilter('pump')">PUMP</span>
    </div>
  </h2>
  <table class="mini">
    <thead><tr>
      <th>Symbol</th><th>Signal</th><th>Score</th><th>Price</th>
      <th>Mom 1m</th><th>Mom 5m</th><th>Buy Ratio</th><th>Imbalance</th><th>Market Cap</th><th>Vol 24h</th><th>Vol Chg 24h</th>
    </tr></thead>
    <tbody id="allBody"><tr><td colspan="11" class="empty">Loading…</td></tr></tbody>
  </table>
</div>

<script>
let allTokens = [];
let currentFilter = 'all';
let lastDataTs = 0;

function setFilter(f) {
  currentFilter = f;
  ['all','buy','sell','pump'].forEach(x => {
    document.getElementById('f-'+x).className = 'ftab' + (x===f?' active':'');
  });
  renderAll();
}

function fmtPrice(p) {
  if (p >= 1) return '$' + p.toFixed(4);
  if (p >= 0.01) return '$' + p.toFixed(5);
  return '$' + p.toFixed(8);
}
function fmtMom(m) {
  const c = m > 0 ? 'green' : m < 0 ? 'red' : '';
  return `<span class="${c}">${m >= 0 ? '+' : ''}${m.toFixed(2)}%</span>`;
}
function fmtVol(v) {
  if (v >= 1e9) return '$' + (v/1e9).toFixed(1) + 'B';
  if (v >= 1e6) return '$' + (v/1e6).toFixed(1) + 'M';
  return '$' + (v/1e3).toFixed(0) + 'K';
}
function buyBar(ratio) {
  const pct = Math.round(ratio * 100);
  return `<div class="bar-wrap"><div class="bar bar-buy" style="width:${pct}%"></div></div> ${pct}%`;
}
function flagTag(t) {
  if (t.pump_detected) return '<span class="tag pump">PUMP</span>';
  if (t.dump_detected) return '<span class="tag dump">DUMP</span>';
  return '<span class="tag neutral">—</span>';
}
function signalTag(s) {
  if (s === 'BUY')  return '<span class="tag buy">BUY</span>';
  if (s === 'SELL') return '<span class="tag sell">SELL</span>';
  return '<span class="tag neutral">—</span>';
}
function scoreSpan(s) {
  return `<span class="${s>0?'score-pos':s<0?'score-neg':''}">${s>0?'+':''}${s}</span>`;
}
function fmtCap(v) {
  if (!v) return '—';
  if (v >= 1e9) return '$' + (v/1e9).toFixed(2) + 'B';
  if (v >= 1e6) return '$' + (v/1e6).toFixed(1) + 'M';
  return '$' + (v/1e3).toFixed(0) + 'K';
}
function fmtVolChg(v) {
  if (v == null) return '—';
  const sign = v >= 0 ? '+' : '';
  const cls  = v >= 100 ? 'yellow' : v >= 30 ? 'green' : v < 0 ? 'red' : '';
  return `<span class="${cls}">${sign}${v.toFixed(1)}%</span>`;
}
function signalRow(t) {
  return `<tr>
    <td><b>${t.symbol}</b></td>
    <td>${scoreSpan(t.score)}</td>
    <td>${fmtPrice(t.price)}</td>
    <td>${fmtMom(t.momentum_1m)}</td>
    <td>${fmtMom(t.momentum_5m)}</td>
    <td>${buyBar(t.buy_ratio)}</td>
    <td>${t.imbalance.toFixed(2)}</td>
    <td style="color:#8b949e">${fmtCap(t.market_cap)}</td>
    <td style="color:#8b949e">${fmtVol(t.volume_24h)}</td>
    <td>${fmtVolChg(t.volume_change_24h)}</td>
    <td>${flagTag(t)}</td>
    <td style="color:#8b949e;max-width:240px;white-space:normal">${(t.reasons||[]).slice(0,3).join(' · ')}</td>
  </tr>`;
}
function miniRow(t) {
  return `<tr>
    <td><b>${t.symbol}</b></td>
    <td>${signalTag(t.signal)}</td>
    <td>${scoreSpan(t.score)}</td>
    <td>${fmtPrice(t.price)}</td>
    <td>${fmtMom(t.momentum_1m)}</td>
    <td>${fmtMom(t.momentum_5m)}</td>
    <td>${buyBar(t.buy_ratio)}</td>
    <td>${t.imbalance.toFixed(2)}</td>
    <td style="color:#8b949e">${fmtCap(t.market_cap)}</td>
    <td style="color:#8b949e">${fmtVol(t.volume_24h)}</td>
    <td>${fmtVolChg(t.volume_change_24h)}</td>
  </tr>`;
}

function renderAll() {
  let filtered = allTokens;
  if (currentFilter === 'buy')  filtered = allTokens.filter(t => t.signal === 'BUY');
  if (currentFilter === 'sell') filtered = allTokens.filter(t => t.signal === 'SELL');
  if (currentFilter === 'pump') filtered = allTokens.filter(t => t.pump_detected);
  document.getElementById('allBody').innerHTML = filtered.length
    ? filtered.map(miniRow).join('')
    : '<tr><td colspan="11" class="empty">No tokens match filter</td></tr>';
}

async function refresh() {
  try {
    const d = await fetch('/api/state').then(r => r.json());

    // Stats cards
    document.getElementById('cnt').textContent      = d.tokens_count || 0;
    document.getElementById('buyCount').textContent  = d.buy_count  || 0;
    document.getElementById('sellCount').textContent = d.sell_count || 0;
    document.getElementById('pumpCount').textContent = d.pump_count || 0;

    const avgBuy = d.avg_buy_ratio != null ? (d.avg_buy_ratio * 100).toFixed(1) + '%' : '—';
    document.getElementById('avgBuy').textContent = avgBuy;
    document.getElementById('avgBuy').className = 'value ' + (d.avg_buy_ratio > 0.55 ? 'green' : d.avg_buy_ratio < 0.45 ? 'red' : 'yellow');

    const ageS = d.data_age_secs != null ? d.data_age_secs.toFixed(0) + 's' : '—';
    document.getElementById('scanAge').textContent = ageS;

    // BUY table
    const buys = (d.all_tokens || []).filter(t => t.signal === 'BUY');
    document.getElementById('buyBadge').textContent = buys.length;
    document.getElementById('buyBody').innerHTML = buys.length
      ? buys.map(signalRow).join('')
      : '<tr><td colspan="12" class="empty">No BUY signals right now</td></tr>';

    // SELL table
    const sells = (d.all_tokens || []).filter(t => t.signal === 'SELL');
    document.getElementById('sellBadge').textContent = sells.length;
    document.getElementById('sellBody').innerHTML = sells.length
      ? sells.map(signalRow).join('')
      : '<tr><td colspan="12" class="empty">No SELL signals</td></tr>';

    // All tokens
    allTokens = d.all_tokens || [];
    document.getElementById('allBadge').textContent = allTokens.length;
    renderAll();

    document.getElementById('updatedAt').textContent = new Date().toLocaleTimeString();
    lastDataTs = Date.now();
  } catch(e) { console.error('refresh error', e); }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text=_HTML, content_type="text/html")


async def handle_state(request: web.Request) -> web.Response:
    states: Dict[str, TokenState] = request.app["states"]
    config = request.app["config"]

    now = time.time()
    all_tokens = []
    buy_count = sell_count = pump_count = 0
    buy_ratios = []

    # Score all tokens
    try:
        top = run_scoring_pass(states, config)
    except Exception:
        top = []

    # Build full list sorted by score
    scored_list = []
    for state in states.values():
        if state.price <= 0:
            continue
        age = now - state.last_rest_update if state.last_rest_update else 9999
        scored_list.append({
            "symbol":        state.symbol,
            "signal":        state.signal,
            "score":         state.score,
            "price":         state.price,
            "momentum_1m":   round(state.momentum_1m, 4),
            "momentum_5m":   round(state.momentum_5m, 4),
            "imbalance":     round(state.imbalance, 4),
            "buy_ratio":     round(state.buy_ratio, 4),
            "trade_freq":    round(state.trade_freq, 3),
            "pump_detected": state.pump_detected,
            "dump_detected": state.dump_detected,
            "reasons":       state.reasons[:5],
            "volume_24h":        state.volume_24h,
            "volume_change_24h": round(state.volume_change_24h, 2),
            "market_cap":        state.market_cap,
            "data_age":          round(age, 0),
        })
        if state.signal == "BUY":
            buy_count += 1
        elif state.signal == "SELL":
            sell_count += 1
        if state.pump_detected:
            pump_count += 1
        if state.buy_ratio > 0:
            buy_ratios.append(state.buy_ratio)

    # Sort by score desc
    scored_list.sort(key=lambda x: -x["score"])

    avg_buy = round(sum(buy_ratios) / len(buy_ratios), 4) if buy_ratios else None

    # Data freshness (age of most recently updated token)
    ages = [s["data_age"] for s in scored_list if s["data_age"] < 9000]
    data_age = round(min(ages), 0) if ages else None

    payload = {
        "tokens_count":  len(states),
        "buy_count":     buy_count,
        "sell_count":    sell_count,
        "pump_count":    pump_count,
        "avg_buy_ratio": avg_buy,
        "data_age_secs": data_age,
        "all_tokens":    scored_list,
        "server_ts":     now,
    }
    return web.Response(
        text=json.dumps(payload),
        content_type="application/json",
    )


async def dashboard_task(states: Dict[str, TokenState], port: int = DASHBOARD_PORT) -> None:
    """Async task: run the aiohttp web dashboard."""
    app = web.Application()
    app["states"] = states
    app["config"] = cfg

    app.router.add_get("/",          handle_root)
    app.router.add_get("/api/state", handle_state)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port, reuse_address=True)
    await site.start()
    log.info("Dashboard running at http://localhost:%d", port)

    try:
        while True:
            import asyncio
            await asyncio.sleep(3600)  # keep alive
    except Exception:
        await runner.cleanup()
