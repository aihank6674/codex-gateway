"""
HTML template for the codex-gateway real-time monitoring dashboard.
Auto-refreshes every 2 seconds via JavaScript fetch.
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>codex-gateway Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:'Inter',system-ui,sans-serif;background:#0f1117;color:#e4e4e7;min-height:100vh}
  .header{background:linear-gradient(135deg,#1a1b26 0%,#24283b 100%);padding:28px 32px;border-bottom:1px solid #2a2d3a}
  .header h1{font-size:22px;font-weight:700;display:flex;align-items:center;gap:10px}
  .header h1 span.icon{font-size:26px}
  .header .sub{color:#7a7f93;font-size:13px;margin-top:4px}
  .status-dot{width:9px;height:9px;border-radius:50%;background:#22c55e;display:inline-block;margin-right:6px;box-shadow:0 0 8px #22c55e88;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;padding:24px 32px}
  .card{background:#1a1b26;border:1px solid #2a2d3a;border-radius:12px;padding:20px;transition:border-color .2s}
  .card:hover{border-color:#3b3f54}
  .card .label{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:#7a7f93;font-weight:600}
  .card .value{font-size:28px;font-weight:700;margin-top:6px;background:linear-gradient(135deg,#7c3aed,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .card .detail{font-size:12px;color:#52566a;margin-top:4px}
  .section{padding:0 32px 24px}
  .section h2{font-size:15px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px;color:#a0a3b5}
  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{text-align:left;padding:10px 14px;background:#1a1b26;color:#7a7f93;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.8px;border-bottom:1px solid #2a2d3a;position:sticky;top:0}
  tbody tr{border-bottom:1px solid #1e2030;transition:background .15s}
  tbody tr:hover{background:#1e2030}
  tbody td{padding:10px 14px}
  .badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600}
  .badge-cloud{background:#7c3aed22;color:#a78bfa;border:1px solid #7c3aed44}
  .badge-local{background:#06b6d422;color:#67e8f9;border:1px solid #06b6d444}
  .badge-stream{background:#22c55e22;color:#86efac;border:1px solid #22c55e44}
  .badge-block{background:#f59e0b22;color:#fcd34d;border:1px solid #f59e0b44}
  .model-bar{display:flex;align-items:center;gap:10px;margin-bottom:8px}
  .model-bar .name{min-width:180px;font-size:13px;font-weight:500}
  .model-bar .bar-bg{flex:1;height:22px;background:#1e2030;border-radius:6px;overflow:hidden}
  .model-bar .bar-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#7c3aed,#06b6d4);transition:width .5s ease;display:flex;align-items:center;justify-content:flex-end;padding-right:8px;font-size:11px;font-weight:600;min-width:32px}
  .table-wrap{background:#1a1b26;border:1px solid #2a2d3a;border-radius:12px;overflow:hidden;max-height:420px;overflow-y:auto}
  .table-wrap::-webkit-scrollbar{width:6px}
  .table-wrap::-webkit-scrollbar-track{background:#1a1b26}
  .table-wrap::-webkit-scrollbar-thumb{background:#3b3f54;border-radius:3px}
  .empty{text-align:center;padding:40px;color:#52566a;font-size:14px}
  .footer{text-align:center;padding:20px;color:#3b3f54;font-size:11px}
</style>
</head>
<body>
<div class="header">
  <h1><span class="icon">🚀</span> codex-gateway <span style="font-weight:400;color:#52566a;font-size:16px">Dashboard</span></h1>
  <div class="sub"><span class="status-dot"></span>Live — Auto-refreshing every 2s</div>
</div>

<div class="grid" id="cards">
  <div class="card"><div class="label">Uptime</div><div class="value" id="uptime">—</div></div>
  <div class="card"><div class="label">Total Requests</div><div class="value" id="total">0</div></div>
  <div class="card"><div class="label">Active Backends</div><div class="value" id="backends">—</div></div>
  <div class="card"><div class="label">Models Routed</div><div class="value" id="models_count">0</div></div>
</div>

<div class="section">
  <h2>📊 Model Distribution</h2>
  <div id="model-bars" style="background:#1a1b26;border:1px solid #2a2d3a;border-radius:12px;padding:16px"></div>
</div>

<div class="section">
  <h2>📋 Recent Requests</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Time</th><th>Client Selection</th><th>Backend</th><th>Target Model</th><th>Mode</th></tr></thead>
      <tbody id="req-body"><tr><td colspan="5" class="empty">Waiting for requests…</td></tr></tbody>
    </table>
  </div>
</div>

<div class="footer">codex-gateway — Local API Gateway Proxy</div>

<script>
async function refresh() {
  try {
    const r = await fetch('/v1/stats');
    const d = await r.json();
    document.getElementById('uptime').textContent = d.uptime;
    document.getElementById('total').textContent = d.total_requests;
    const bk = Object.keys(d.requests_by_backend);
    document.getElementById('backends').textContent = bk.length || '—';
    const mk = Object.keys(d.requests_by_model);
    document.getElementById('models_count').textContent = mk.length;

    // Model bars
    const maxV = Math.max(...Object.values(d.requests_by_model), 1);
    const barsHtml = mk.length ? mk.map(m => {
      const c = d.requests_by_model[m];
      const pct = Math.max((c / maxV) * 100, 8);
      return `<div class="model-bar"><span class="name">${m}</span><div class="bar-bg"><div class="bar-fill" style="width:${pct}%">${c}</div></div></div>`;
    }).join('') : '<div class="empty">No model data yet</div>';
    document.getElementById('model-bars').innerHTML = barsHtml;

    // Recent table
    if (d.recent_requests.length) {
      document.getElementById('req-body').innerHTML = d.recent_requests.map(r => {
        const bClass = r.target_backend.toLowerCase().includes('deepseek') ? 'badge-cloud' : 'badge-local';
        const mClass = r.stream ? 'badge-stream' : 'badge-block';
        return `<tr>
          <td style="color:#7a7f93;font-variant-numeric:tabular-nums">${r.time}</td>
          <td>${r.client_model}</td>
          <td><span class="badge ${bClass}">${r.target_backend.toUpperCase()}</span></td>
          <td style="font-weight:500">${r.target_model}</td>
          <td><span class="badge ${mClass}">${r.stream ? '⚡ Stream' : '📦 Block'}</span></td>
        </tr>`;
      }).join('');
    }
  } catch(e) { /* silently retry */ }
}
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>"""
