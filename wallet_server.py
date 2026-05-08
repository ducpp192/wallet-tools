#!/usr/bin/env python3
"""
wallet_server.py — BIP44 Wallet Generator
Dashboard at http://localhost:5013
"""
import json
import sys

# ── auto-install ────────────────────────────────────────────────
_missing = []
for _pkg, _spec in [("aiohttp", "aiohttp>=3.9.0"), ("eth_account", "eth-account>=0.10.0")]:
    try:
        __import__(_pkg)
    except ImportError:
        _missing.append(_spec)
if _missing:
    import subprocess
    print(f"Installing: {_missing}")
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + _missing + ["-q"])

# ── imports ─────────────────────────────────────────────────────
from aiohttp import web
from eth_account import Account

Account.enable_unaudited_hdwallet_features()

# ── HTML ────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wallet Generator</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0d0d0d;color:#e0e0e0;font-family:'Segoe UI',monospace;font-size:14px}
  header{background:#111;border-bottom:1px solid #222;padding:14px 24px;display:flex;align-items:center;gap:12px}
  header h1{font-size:18px;color:#00c8ff}
  .container{max-width:1200px;margin:0 auto;padding:20px}
  .card{background:#141414;border:1px solid #222;border-radius:8px;padding:20px;margin-bottom:20px}
  .card h2{font-size:15px;color:#aaa;margin-bottom:14px;text-transform:uppercase;letter-spacing:.05em}
  textarea{width:100%;background:#0d0d0d;border:1px solid #333;color:#e0e0e0;border-radius:6px;
           padding:10px;font-size:13px;resize:vertical;min-height:100px;outline:none;font-family:monospace}
  textarea:focus{border-color:#00c8ff}
  .row{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}
  label{display:block;color:#888;margin-bottom:6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
  input[type=number]{background:#0d0d0d;border:1px solid #333;color:#e0e0e0;border-radius:6px;
                     padding:8px 12px;font-size:14px;width:140px;outline:none}
  input[type=number]:focus{border-color:#00c8ff}
  .btn{padding:9px 22px;border:none;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600;
       transition:.15s;white-space:nowrap}
  .btn-primary{background:#00c8ff;color:#000}
  .btn-primary:hover{background:#00b0e0}
  .btn-green{background:#00c853;color:#000}
  .btn-green:hover{background:#00b048}
  .btn:disabled{opacity:.45;cursor:not-allowed}
  .warning{background:#1a0f00;border:1px solid #ff6600;border-radius:6px;padding:12px 16px;
           color:#ff9944;font-size:12px;margin-bottom:16px;line-height:1.5}
  #status{font-size:13px;color:#888;margin-top:10px;min-height:18px}
  #status.ok{color:#00c853} #status.err{color:#ff3d3d}
  .tbl-wrap{overflow-x:auto;margin-top:6px}
  table{width:100%;border-collapse:collapse;font-size:12px}
  thead tr{background:#1a1a1a}
  th{padding:8px 10px;text-align:left;color:#888;font-weight:600;border-bottom:1px solid #222;white-space:nowrap}
  td{padding:7px 10px;border-bottom:1px solid #191919;font-family:monospace;word-break:break-all}
  tr:hover td{background:#181818}
  .phrase-row td{background:#111;color:#777;font-size:11px;padding:4px 10px}
  .idx{color:#555;width:50px}
  .pidx{color:#555;width:60px}
  .path{color:#666;font-size:11px}
  .addr{color:#00c8ff}
  .pk{color:#ffaa00;font-size:11px}
  #export-btn{display:none}
  .summary{color:#888;font-size:12px;margin-bottom:10px}
  .hint{color:#555;font-size:11px;margin-top:6px}
</style>
</head>
<body>
<header>
  <h1>&#128273; Wallet Generator</h1>
  <span style="color:#555;font-size:12px">BIP44 &middot; ETH-compatible &middot; m/44'/60'/0'/0/i</span>
</header>
<div class="container">

  <div class="warning">
    &#9888;&#65039; <strong>SECURITY WARNING:</strong> Never share your seed phrase or private keys with anyone.
    Use this tool only on an offline or trusted machine.
  </div>

  <div class="card">
    <h2>Input</h2>
    <div style="margin-bottom:14px">
      <label>Seed Phrase(s)</label>
      <textarea id="mnemonic" placeholder="Nhập 1 hoặc nhiều seed phrase&#10;&#10;Hỗ trợ các định dạng:&#10;• 1 phrase/dòng: word1 word2 ... word12&#10;• Mỗi từ 1 dòng (tự động ghép 12 từ thành 1 phrase)&#10;• Nhiều phrase dán liền (tự động tách)" rows="6"></textarea>
      <div class="hint">Hỗ trợ: 1 phrase/dòng, mỗi từ 1 dòng (tự nhóm 12), hoặc nhiều phrase liền nhau.</div>
    </div>
    <div class="row">
      <div>
        <label>Số wallet / phrase (1&ndash;20)</label>
        <input type="number" id="count" value="1" min="1" max="20">
      </div>
      <button class="btn btn-primary" id="gen-btn" onclick="generate()">&#9889; Generate</button>
      <button class="btn btn-green" id="export-btn" onclick="exportCsv()">&#8595; Export CSV</button>
    </div>
    <div id="status"></div>
  </div>

  <div class="card" id="result-card" style="display:none">
    <h2>Results</h2>
    <div class="summary" id="summary"></div>
    <div class="tbl-wrap">
      <table>
        <thead><tr>
          <th class="pidx">Phrase#</th>
          <th class="idx">Idx</th>
          <th>Derivation Path</th>
          <th>Address</th>
          <th>Private Key</th>
        </tr></thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </div>

</div>
<script>
var _wallets = [];

function parsePhrases(raw) {
  var lines = raw.split('\n').map(function(l){ return l.trim(); }).filter(Boolean);
  // Detect: each line is a single BIP39 word (one word per line)
  var allSingleWords = lines.length > 1 && lines.every(function(l){
    return /^[a-zA-Z]{2,10}$/.test(l);
  });
  if (allSingleWords) {
    var chunk = (lines.length % 24 === 0) ? 24 : 12;
    if (lines.length % chunk !== 0) chunk = 12;
    var phrases = [];
    for (var i = 0; i < lines.length; i += chunk)
      phrases.push(lines.slice(i, i + chunk).join(' '));
    return phrases;
  }
  // Normal: each line is a complete phrase (12 or 24 words)
  var phrases = [];
  for (var i = 0; i < lines.length; i++) {
    var words = lines[i].split(/\s+/).filter(Boolean);
    if (words.length === 12 || words.length === 24) {
      phrases.push(lines[i]);
    } else if (words.length > 24) {
      // All phrases squashed on one line — split by 12
      var chunk2 = (words.length % 24 === 0) ? 24 : 12;
      if (words.length % chunk2 === 0) {
        for (var j = 0; j < words.length; j += chunk2)
          phrases.push(words.slice(j, j + chunk2).join(' '));
      }
    }
    // skip lines that don't parse
  }
  return phrases;
}

async function generate() {
  var raw = document.getElementById('mnemonic').value.trim();
  var cnt = Math.max(1, Math.min(20, parseInt(document.getElementById('count').value) || 1));
  var btn = document.getElementById('gen-btn');

  if (!raw) { setStatus('Please enter a seed phrase.', 'err'); return; }
  var phrases = parsePhrases(raw);
  if (!phrases.length) {
    setStatus('No valid 12/24-word phrases found. Check input format.', 'err'); return;
  }

  btn.disabled = true;
  setStatus('Generating ' + cnt + ' wallet(s) × ' + phrases.length + ' phrase(s)...', '');

  try {
    var r = await fetch('/generate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({mnemonics: phrases, count: cnt})
    });
    var data = await r.json();
    if (!data.ok) throw new Error(data.error || 'Server error');
    _wallets = data.wallets;
    renderTable(_wallets, data.phrase_count);
    setStatus('Done — ' + _wallets.length + ' wallets từ ' + data.phrase_count + ' phrase(s).', 'ok');
    document.getElementById('export-btn').style.display = '';
  } catch(e) {
    setStatus('Error: ' + e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function renderTable(wallets, phraseCount) {
  var rows = [];
  var lastP = -1;
  wallets.forEach(function(w) {
    if (w.phrase_idx !== lastP) {
      lastP = w.phrase_idx;
      rows.push('<tr class="phrase-row"><td colspan="5">Phrase #' + (w.phrase_idx+1) + ' &nbsp;—&nbsp; ' +
                w.mnemonic_preview + '</td></tr>');
    }
    rows.push('<tr><td class="pidx">' + (w.phrase_idx+1) + '</td>' +
              '<td class="idx">' + w.index + '</td>' +
              '<td class="path">' + w.path + '</td>' +
              '<td class="addr">' + w.address + '</td>' +
              '<td class="pk">' + w.private_key + '</td></tr>');
  });
  document.getElementById('tbody').innerHTML = rows.join('');
  document.getElementById('summary').textContent =
    wallets.length + ' wallets từ ' + phraseCount + ' seed phrase(s)';
  document.getElementById('result-card').style.display = '';
}

function exportCsv() {
  if (!_wallets.length) return;
  var header = 'phrase_idx,index,path,address,private_key\n';
  var rows = _wallets.map(function(w) {
    return (w.phrase_idx+1) + ',' + w.index + ',"' + w.path + '","' + w.address + '","' + w.private_key + '"';
  }).join('\n');
  var blob = new Blob([header + rows], {type:'text/csv'});
  var url  = URL.createObjectURL(blob);
  var a    = document.createElement('a');
  a.href = url;
  a.download = 'wallets_' + Date.now() + '.csv';
  a.click();
  URL.revokeObjectURL(url);
}

function setStatus(msg, cls) {
  var el = document.getElementById('status');
  el.textContent = msg;
  el.className = cls;
}
</script>
</body>
</html>
"""


# ── API handlers ────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=HTML, content_type="text/html")


async def handle_generate(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    # Support both legacy single mnemonic and new batch mnemonics array
    mnemonics_raw = body.get("mnemonics") or []
    if not mnemonics_raw and body.get("mnemonic"):
        mnemonics_raw = [body["mnemonic"]]

    count = max(1, min(20, int(body.get("count") or 1)))

    if not mnemonics_raw:
        return web.json_response({"ok": False, "error": "mnemonic required"}, status=400)

    wallets = []
    skipped = []
    for p_idx, mn in enumerate(mnemonics_raw):
        mn = " ".join(mn.strip().split())  # normalize whitespace
        words = mn.split()
        if len(words) not in (12, 24):
            skipped.append(p_idx)
            continue
        preview = " ".join(words[:3]) + " ... " + words[-1]
        for i in range(count):
            path = f"m/44'/60'/0'/0/{i}"
            acc  = Account.from_mnemonic(mn, account_path=path)
            wallets.append({
                "phrase_idx":      p_idx,
                "mnemonic_preview": preview,
                "index":           i,
                "path":            path,
                "address":         acc.address,
                "private_key":     acc.key.hex(),
            })

    return web.json_response({
        "ok":           True,
        "wallets":      wallets,
        "phrase_count": len(mnemonics_raw) - len(skipped),
        "skipped":      len(skipped),
    })


# ── App ─────────────────────────────────────────────────────────

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/",          handle_index)
    app.router.add_post("/generate", handle_generate)
    return app


if __name__ == "__main__":
    PORT = 5013
    print("=" * 55)
    print("  Wallet Generator")
    print(f"  Dashboard : http://localhost:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 55)
    web.run_app(build_app(), host="0.0.0.0", port=PORT, access_log=None)
