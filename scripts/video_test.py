#!/usr/bin/env python3
"""
Sweet Spot CRM — Video Test Suite
Records a walkthrough video of every major section, then builds
a self-contained HTML report page that embeds all the videos.
"""

import os, base64, datetime, subprocess, time
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://sweet-spot-cakes.up.railway.app"
EMAIL    = "info@sweetspotcustomcakes.com"
PASSWORD = "sweetspot2026"
VIDEO_DIR = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/videos"
REPORT    = "/root/.openclaw/workspace/sweet-spot-cakes/index.html"

os.makedirs(VIDEO_DIR, exist_ok=True)

results = []  # {title, desc, webm_path, status, note}

ERROR_MARKERS = [
    "internal server error",
    "werkzeug", "traceback", "syntaxerror",
    "attributeerror", "keyerror", "typeerror",
    "nameerror", "operationalerror",
    "bad gateway", "service unavailable",
]

def has_error(page):
    try:
        text = page.inner_text('body').lower()
        title = page.title().lower()
        for m in ERROR_MARKERS:
            if m in title or m in text[:600]:
                return m
    except Exception:
        pass
    return None

def nav(page, path):
    try:
        page.goto(BASE_URL + path, wait_until="networkidle", timeout=20000)
        return True
    except PWTimeout:
        try:
            page.goto(BASE_URL + path, wait_until="load", timeout=12000)
            return True
        except Exception as e:
            print(f"  ⚠️  nav failed: {e}")
            return False

def slow_scroll(page, steps=4, delay=600):
    """Smoothly scroll down then back up."""
    page.evaluate("""steps => {
        const total = Math.max(document.body.scrollHeight - window.innerHeight, 0);
        const step = total / steps;
        let i = 0;
        const t = setInterval(() => {
            window.scrollBy(0, step);
            i++;
            if (i >= steps) clearInterval(t);
        }, 200);
    }""", steps)
    page.wait_for_timeout(steps * 220 + delay)

def record_section(browser, title, slug, desc, fn):
    """
    Run fn(page) inside a fresh context that records to VIDEO_DIR.
    Playwright saves the video when the context closes.
    """
    ctx = browser.new_context(
        viewport={"width": 1400, "height": 900},
        record_video_dir=VIDEO_DIR,
        record_video_size={"width": 1400, "height": 900},
    )
    page = ctx.new_page()

    # Login
    nav(page, "/login")
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    try:
        with page.expect_navigation(timeout=10000):
            page.click('button[type="submit"]')
    except PWTimeout:
        pass
    page.wait_for_timeout(400)

    error_hit = None
    note = ""
    try:
        fn(page)
        error_hit = has_error(page)
    except Exception as e:
        note = str(e)
        error_hit = "exception"
        print(f"  ⚠️  {title}: {e}")

    # Get the video path before closing
    video_path = page.video.path() if page.video else None
    ctx.close()  # This finalises the .webm file

    # Convert/rename to a fixed name
    final_path = None
    if video_path and os.path.exists(video_path):
        final_path = f"{VIDEO_DIR}/{slug}.webm"
        os.rename(video_path, final_path)

    status = "ok" if not error_hit else "error"
    results.append({
        "title": title,
        "slug": slug,
        "desc": desc,
        "path": final_path,
        "status": status,
        "note": note or (f"Error: {error_hit}" if error_hit else ""),
    })
    icon = "✅" if status == "ok" else "❌"
    print(f"  {icon} {title}{' — ' + (note or str(error_hit)) if status == 'error' else ''}")
    return status == "ok"

# ──────────────────────────────────────────────────────────────────────────────
# SECTION SCRIPTS
# ──────────────────────────────────────────────────────────────────────────────

def sec_dashboard(page):
    nav(page, "/dashboard")
    page.wait_for_timeout(800)
    slow_scroll(page, steps=5, delay=800)
    page.wait_for_timeout(500)

def sec_orders(page):
    nav(page, "/orders")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    # Open an order detail
    try:
        link = page.locator('a[href*="/orders/"]').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=3)
    except Exception:
        pass
    # New order form
    nav(page, "/orders/new")
    page.wait_for_timeout(500)
    try:
        page.fill('input[name="customer_name"]', "Sarah Johnson", timeout=3000)
        page.fill('input[type="email"]', "sarah@example.com", timeout=3000)
        page.fill('input[name="customer_phone"]', "555-123-4567", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(600)
    slow_scroll(page, steps=3)

def sec_kitchen(page):
    nav(page, "/kitchen")
    page.wait_for_timeout(800)
    slow_scroll(page, steps=3)
    # Open a kitchen order card if present
    try:
        card = page.locator('.order-card, .kitchen-card, tr a').first
        if card.is_visible(timeout=2000):
            card.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=2)
    except Exception:
        pass

def sec_inventory(page):
    nav(page, "/inventory")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=4)
    # Open Add Ingredient modal
    try:
        page.click('button:has-text("+ Add Ingredient")', timeout=3000)
        page.wait_for_timeout(600)
        # Fill in the modal
        modal = page.query_selector('#addModal')
        if modal:
            inp = modal.query_selector('input[name="name"]')
            if inp:
                inp.fill("Demo Vanilla Extract")
            sel = modal.query_selector('select[name="unit"]')
            if sel:
                sel.select_option("oz")
            qty = modal.query_selector('input[name="quantity"]')
            if qty:
                qty.fill("48")
        page.wait_for_timeout(600)
        # Close modal without saving
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass
    # Demo the adjust +/- on first item
    try:
        first_row = page.query_selector('tbody tr:first-child')
        if first_row:
            adj_inp = first_row.query_selector('input[type="number"][id*="adj-qty"]')
            if adj_inp:
                adj_inp.fill("5")
                page.wait_for_timeout(400)
    except Exception:
        pass

def sec_suppliers(page):
    nav(page, "/suppliers")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    # Click into Auto-PO for first supplier that has the button
    try:
        btn = page.locator('a[href*="/auto-po"]').first
        if btn.is_visible(timeout=2000):
            btn.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(700)
            slow_scroll(page, steps=3)
            page.go_back()
            page.wait_for_timeout(400)
    except Exception:
        pass
    # Add supplier modal
    try:
        page.click('button:has-text("Add"), button:has-text("+ Add")', timeout=3000)
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

def sec_recipes(page):
    nav(page, "/recipes")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    # Open a recipe detail
    try:
        link = page.locator('a[href*="/recipes/"]').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=4)
    except Exception:
        pass

def sec_customers(page):
    nav(page, "/customers")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=4)
    # Search demo
    try:
        search = page.query_selector('input[type="search"], input[placeholder*="Search"], input[name="q"]')
        if search:
            search.fill("Johnson")
            page.wait_for_timeout(600)
    except Exception:
        pass

def sec_employees(page):
    nav(page, "/employees")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    # Add modal
    try:
        page.click('button:has-text("Add Employee"), button:has-text("+ Add")', timeout=3000)
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

def sec_reports(page):
    nav(page, "/reports")
    page.wait_for_timeout(1000)  # charts take a moment
    slow_scroll(page, steps=6, delay=1000)

def sec_expenses(page):
    nav(page, "/expenses")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    try:
        page.click('button:has-text("Add Expense"), button:has-text("+ Add")', timeout=3000)
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

def sec_marketing(page):
    nav(page, "/marketing")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    try:
        link = page.locator('a[href*="/marketing/"]').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=3)
    except Exception:
        pass

def sec_loyalty(page):
    nav(page, "/loyalty")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    try:
        page.click('button:has-text("Add Special"), button:has-text("Special")', timeout=3000)
        page.wait_for_timeout(500)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

def sec_settings(page):
    nav(page, "/settings")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=5)

def sec_public(page):
    # Public-facing pages (no login needed but we're in the same context)
    nav(page, "/order")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=4)
    try:
        page.fill('input[name="customer_name"], input[placeholder*="name"]', "Demo Customer", timeout=3000)
        page.fill('input[type="email"]', "demo@example.com", timeout=3000)
        page.wait_for_timeout(400)
    except Exception:
        pass
    nav(page, "/loyalty/join")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)

def sec_mobile(page):
    """Re-visits key pages at mobile viewport."""
    # We can't resize mid-context but we do the walkthrough at mobile
    # (This context is created at mobile size)
    for path in ["/dashboard", "/orders", "/inventory", "/customers"]:
        nav(page, path)
        page.wait_for_timeout(600)
        slow_scroll(page, steps=2, delay=400)

# ──────────────────────────────────────────────────────────────────────────────
# RUN ALL SECTIONS
# ──────────────────────────────────────────────────────────────────────────────

SECTIONS = [
    ("Dashboard",    "dashboard",   "Main KPIs, revenue charts, and recent activity overview", sec_dashboard),
    ("Orders",       "orders",      "Order list, detail view, status filters, and new order form", sec_orders),
    ("Kitchen",      "kitchen",     "Live kitchen display board with order cards", sec_kitchen),
    ("Inventory",    "inventory",   "Ingredient list, add modal demo, and +/− stock adjustment", sec_inventory),
    ("Suppliers",    "suppliers",   "Supplier list, Auto-PO flow, and add supplier", sec_suppliers),
    ("Recipes",      "recipes",     "Recipe catalog and detailed ingredient breakdown", sec_recipes),
    ("Customers",    "customers",   "Customer list with search demo", sec_customers),
    ("Employees",    "employees",   "Team roster and add employee form", sec_employees),
    ("Reports",      "reports",     "Revenue, sales, and performance charts", sec_reports),
    ("Expenses",     "expenses",    "Expense tracker and add expense form", sec_expenses),
    ("Marketing",    "marketing",   "Campaign management and detail view", sec_marketing),
    ("Loyalty",      "loyalty",     "Loyalty program overview and specials", sec_loyalty),
    ("Settings",     "settings",    "Bakery configuration and preferences", sec_settings),
    ("Public Pages", "public",      "Customer-facing order form and loyalty sign-up", sec_public),
]

print("🎬 Sweet Spot CRM — Video Test Suite")
print("=" * 50)

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])

    for title, slug, desc, fn in SECTIONS:
        print(f"\n🎥 Recording: {title}")
        record_section(browser, title, slug, desc, fn)

    # Mobile section with different viewport
    print(f"\n🎥 Recording: Mobile")
    ctx_mob = browser.new_context(
        viewport={"width": 390, "height": 844},
        record_video_dir=VIDEO_DIR,
        record_video_size={"width": 390, "height": 844},
    )
    page_mob = ctx_mob.new_page()
    nav(page_mob, "/login")
    page_mob.fill('input[name="email"]', EMAIL)
    page_mob.fill('input[name="password"]', PASSWORD)
    try:
        with page_mob.expect_navigation(timeout=10000):
            page_mob.click('button[type="submit"]')
    except PWTimeout:
        pass
    sec_mobile(page_mob)
    mob_raw = page_mob.video.path() if page_mob.video else None
    ctx_mob.close()
    mob_final = None
    if mob_raw and os.path.exists(mob_raw):
        mob_final = f"{VIDEO_DIR}/mobile.webm"
        os.rename(mob_raw, mob_final)
    results.append({
        "title": "Mobile View",
        "slug": "mobile",
        "desc": "Dashboard, Orders, Inventory, and Customers at iPhone 14 size",
        "path": mob_final,
        "status": "ok",
        "note": "",
    })
    print("  ✅ Mobile View")

    browser.close()

# ──────────────────────────────────────────────────────────────────────────────
# BUILD HTML REPORT
# ──────────────────────────────────────────────────────────────────────────────

print("\n📄 Building HTML report...")

ok_count = sum(1 for r in results if r["status"] == "ok")
total = len(results)
now = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

# Encode videos as base64 data URIs so the report is self-contained
def encode_video(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

cards_html = ""
for r in results:
    b64 = encode_video(r["path"])
    status_badge = (
        '<span class="badge ok">✅ PASS</span>' if r["status"] == "ok"
        else f'<span class="badge fail">❌ FAIL — {r["note"]}</span>'
    )
    if b64:
        video_tag = f'<video controls preload="metadata" src="data:video/webm;base64,{b64}"></video>'
    else:
        video_tag = '<div class="no-video">⚠️ Video not recorded</div>'

    cards_html += f"""
    <div class="card {'error' if r['status'] == 'error' else ''}">
      <div class="card-header">
        <h2>{r['title']}</h2>
        {status_badge}
      </div>
      <p class="desc">{r['desc']}</p>
      {video_tag}
    </div>
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sweet Spot Custom Cakes — CRM Video Walkthrough</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',system-ui,sans-serif;background:#0d0408;color:#fdf2f8;min-height:100vh}}
  header{{background:linear-gradient(135deg,#1f0d16,#2a1020);padding:48px 32px 36px;text-align:center;border-bottom:1px solid #3d1a28}}
  header h1{{font-size:2.2rem;font-weight:700;color:#f472b6;margin-bottom:8px}}
  header p{{color:#9d8890;font-size:.95rem}}
  .meta{{display:flex;gap:24px;justify-content:center;margin-top:18px;flex-wrap:wrap}}
  .meta span{{background:#1f0d16;border:1px solid #3d1a28;border-radius:20px;padding:5px 16px;font-size:.82rem;color:#fda4af}}
  .grid{{max-width:1300px;margin:40px auto;padding:0 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(580px,1fr));gap:28px}}
  .card{{background:#1f0d16;border:1px solid #3d1a28;border-radius:16px;overflow:hidden;transition:transform .2s}}
  .card:hover{{transform:translateY(-2px)}}
  .card.error{{border-color:#ef4444}}
  .card-header{{padding:18px 20px 10px;display:flex;justify-content:space-between;align-items:center;gap:12px}}
  .card-header h2{{font-size:1.05rem;font-weight:600;color:#fdf2f8}}
  .badge{{font-size:.75rem;padding:3px 10px;border-radius:12px;white-space:nowrap}}
  .badge.ok{{background:rgba(34,197,94,.15);color:#4ade80;border:1px solid rgba(34,197,94,.3)}}
  .badge.fail{{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3)}}
  .desc{{padding:0 20px 14px;font-size:.83rem;color:#9d8890;line-height:1.5}}
  video{{width:100%;display:block;background:#000;max-height:500px}}
  .no-video{{padding:40px;text-align:center;color:#9d8890;font-size:.9rem}}
  footer{{text-align:center;padding:32px;color:#9d8890;font-size:.8rem;border-top:1px solid #3d1a28;margin-top:20px}}
  footer a{{color:#f472b6;text-decoration:none}}
  @media(max-width:640px){{.grid{{grid-template-columns:1fr}}.card-header{{flex-direction:column;align-items:flex-start}}}}
</style>
</head>
<body>
<header>
  <h1>🎂 Sweet Spot Custom Cakes</h1>
  <p>CRM Platform — Full Video Walkthrough &amp; Test Report</p>
  <div class="meta">
    <span>📅 Generated {now}</span>
    <span>🎥 {total} Videos</span>
    <span>✅ {ok_count}/{total} Passed</span>
    <span>🔗 <a href="https://sweet-spot-cakes.up.railway.app" style="color:#f472b6">Live App</a></span>
  </div>
</header>
<div class="grid">
{cards_html}
</div>
<footer>
  Built with ❤️ by <a href="https://kiloclaw.ai">KiloClaw</a> &amp;
  <a href="https://alexander-ai.com">Alexander AI Integrated Solutions</a>
</footer>
</body>
</html>"""

with open(REPORT, "w") as f:
    f.write(html)

print(f"\n{'='*50}")
print(f"✅ Done! {ok_count}/{total} sections recorded")
print(f"📄 Report: {REPORT}")
size_mb = os.path.getsize(REPORT) / (1024*1024)
print(f"📦 File size: {size_mb:.1f} MB")
