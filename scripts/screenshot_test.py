#!/usr/bin/env python3
"""
Sweet Spot CRM — Full Screenshot Test Suite
Logs in, visits every meaningful GET route, captures screenshots,
then generates a self-contained HTML report.
"""

import os, json, time, base64, datetime
from playwright.sync_api import sync_playwright

BASE_URL  = "https://sweet-spot-cakes.up.railway.app"
USERNAME  = "info@sweetspotcustomcakes.com"
PASSWORD  = "sweetspot2026"
OUT_DIR   = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/screenshots"
REPORT    = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/report.html"

os.makedirs(OUT_DIR, exist_ok=True)

# All meaningful GET routes to test (label, path)
ROUTES = [
    ("🏠 Dashboard",         "/dashboard"),
    ("📋 Orders",            "/orders"),
    ("➕ New Order",         "/orders/new"),
    ("📦 Inventory",         "/inventory"),
    ("🔧 Tools & Equipment", "/tools"),
    ("🍽️ Kitchen Display",   "/kitchen"),
    ("🏭 Suppliers",         "/suppliers"),
    ("👥 Employees",         "/employees"),
    ("📖 Recipes",           "/recipes"),
    ("👤 Customers",         "/customers"),
    ("📊 Reports",           "/reports"),
    ("💸 Expenses",          "/expenses"),
    ("📋 Prep Sheet",        "/prep-sheet"),
    ("⚙️ Settings",          "/settings"),
    ("🎂 Public Order Form", "/order"),
    ("🤝 Join Loyalty",      "/join"),
    ("📱 QR Code",           "/qr"),
    ("⭐ Loyalty & Specials","/loyalty"),
]

results = []

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    # ── Login ─────────────────────────────────────────────────────────────────
    print("🔐 Logging in...")
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.fill('input[name="email"]', USERNAME)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{BASE_URL}/dashboard", timeout=15000)
    print("  ✅ Logged in")

    # ── Screenshot each route ─────────────────────────────────────────────────
    for label, path in ROUTES:
        url = BASE_URL + path
        slug = path.strip("/").replace("/", "-") or "dashboard"
        img_path = f"{OUT_DIR}/{slug}.png"
        print(f"  📸 {label}  →  {path}")
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
            # Small pause to let any JS render
            page.wait_for_timeout(600)
            final_url = page.url
            title     = page.title()
            # Full-page screenshot
            page.screenshot(path=img_path, full_page=True)
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            results.append({
                "label": label, "path": path, "url": final_url,
                "title": title, "status": "ok", "img": b64,
                "redirected": final_url != url
            })
        except Exception as e:
            results.append({
                "label": label, "path": path, "url": url,
                "title": "", "status": "error", "img": None,
                "error": str(e)
            })
            print(f"    ❌ {e}")

    browser.close()

# ── Build HTML Report ─────────────────────────────────────────────────────────
ok_count  = sum(1 for r in results if r["status"] == "ok" and not r.get("redirected"))
red_count = sum(1 for r in results if r.get("redirected"))
err_count = sum(1 for r in results if r["status"] == "error")
ts        = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

cards = ""
for r in results:
    if r["status"] == "error":
        badge = '<span style="background:#ef4444;color:#fff;padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:700">❌ ERROR</span>'
        img_html = f'<div style="background:#1e1e1e;border-radius:10px;padding:40px;text-align:center;color:#ef4444;font-size:.9rem">{r.get("error","Unknown error")}</div>'
    elif r.get("redirected"):
        badge = '<span style="background:#f59e0b;color:#000;padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:700">↪ REDIRECT</span>'
        img_html = f'<img src="data:image/png;base64,{r["img"]}" style="width:100%;border-radius:10px;display:block">'
    else:
        badge = '<span style="background:#22c55e;color:#fff;padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:700">✅ PASS</span>'
        img_html = f'<img src="data:image/png;base64,{r["img"]}" style="width:100%;border-radius:10px;display:block">'

    cards += f"""
    <div style="background:#1a1a2e;border:1px solid #2d2d4e;border-radius:14px;overflow:hidden;break-inside:avoid;margin-bottom:28px">
      <div style="padding:16px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #2d2d4e;background:#16213e">
        <div style="flex:1">
          <div style="font-size:1.05rem;font-weight:800;color:#f8fafc">{r["label"]}</div>
          <div style="font-size:.78rem;color:#94a3b8;margin-top:2px;font-family:monospace">{r["path"]}</div>
        </div>
        {badge}
      </div>
      <div style="padding:14px">
        {img_html}
      </div>
    </div>
    """

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sweet Spot CRM — Test Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f0f23; color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  .hero {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); padding: 60px 40px 50px; text-align: center; border-bottom: 1px solid #2d2d4e; }}
  .hero h1 {{ font-size: 2.4rem; font-weight: 900; background: linear-gradient(90deg, #f472b6, #a78bfa, #38bdf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 10px; }}
  .hero p {{ color: #94a3b8; font-size: 1rem; }}
  .stats {{ display: flex; justify-content: center; gap: 24px; margin-top: 28px; flex-wrap: wrap; }}
  .stat {{ background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1); border-radius: 12px; padding: 16px 28px; text-align: center; min-width: 120px; }}
  .stat .num {{ font-size: 2rem; font-weight: 900; }}
  .stat .lbl {{ font-size: .75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: .08em; margin-top: 2px; }}
  .green {{ color: #22c55e; }} .yellow {{ color: #f59e0b; }} .red {{ color: #ef4444; }} .blue {{ color: #38bdf8; }}
  .grid {{ max-width: 1300px; margin: 40px auto; padding: 0 28px; columns: 2; column-gap: 24px; }}
  @media (max-width: 900px) {{ .grid {{ columns: 1; }} }}
  .footer {{ text-align: center; padding: 40px; color: #475569; font-size: .8rem; border-top: 1px solid #1e293b; margin-top: 20px; }}
  img {{ cursor: pointer; transition: transform .2s; }}
  img:hover {{ transform: scale(1.01); }}
  /* Lightbox */
  #lb {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:9999; align-items:center; justify-content:center; padding:20px; }}
  #lb img {{ max-width:95vw; max-height:92vh; border-radius:10px; box-shadow:0 0 60px rgba(0,0,0,.8); }}
  #lb-close {{ position:fixed; top:18px; right:24px; font-size:2rem; color:#fff; cursor:pointer; background:none; border:none; z-index:10000; }}
</style>
</head>
<body>

<div id="lb" onclick="closeLB()">
  <button id="lb-close" onclick="closeLB()">✕</button>
  <img id="lb-img" src="">
</div>

<div class="hero">
  <div style="font-size:2.5rem;margin-bottom:12px">🎂</div>
  <h1>Sweet Spot CRM — Full System Test</h1>
  <p>Automated screenshot test of every page · Generated {ts}</p>
  <div style="margin-top:8px"><a href="https://sweet-spot-cakes.up.railway.app" target="_blank" style="color:#38bdf8;font-size:.88rem;text-decoration:none">🔗 sweet-spot-cakes.up.railway.app</a></div>
  <div class="stats">
    <div class="stat"><div class="num blue">{len(results)}</div><div class="lbl">Pages Tested</div></div>
    <div class="stat"><div class="num green">{ok_count}</div><div class="lbl">Passed</div></div>
    <div class="stat"><div class="num yellow">{red_count}</div><div class="lbl">Redirects</div></div>
    <div class="stat"><div class="num red">{err_count}</div><div class="lbl">Errors</div></div>
  </div>
</div>

<div class="grid">
{cards}
</div>

<div class="footer">
  Generated by Echo · Alexander AI Integrated Solutions · {ts}
</div>

<script>
function closeLB() {{ document.getElementById('lb').style.display='none'; }}
document.querySelectorAll('.grid img').forEach(function(img) {{
  img.addEventListener('click', function() {{
    document.getElementById('lb-img').src = this.src;
    document.getElementById('lb').style.display = 'flex';
  }});
}});
document.addEventListener('keydown', function(e) {{ if(e.key==='Escape') closeLB(); }});
</script>
</body>
</html>"""

with open(REPORT, "w") as f:
    f.write(html)

print(f"\n✅ Done! {ok_count} passed, {red_count} redirects, {err_count} errors")
print(f"📄 Report: {REPORT}")
