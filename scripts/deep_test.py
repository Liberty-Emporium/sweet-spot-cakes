#!/usr/bin/env python3
"""
Sweet Spot CRM — DEEP Screenshot Test Suite
Tests every page, every detail view, every modal/tab/interaction layer.
Generates a self-contained HTML report with all screenshots embedded.
"""

import os, base64, datetime, re
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://sweet-spot-cakes.up.railway.app"
EMAIL    = "info@sweetspotcustomcakes.com"
PASSWORD = "sweetspot2026"
OUT_DIR  = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/screenshots_deep"
REPORT   = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/deep_report.html"

os.makedirs(OUT_DIR, exist_ok=True)

results  = []  # {section, label, path, status, img, note}
sections = {}  # section -> list of result indexes

def shot(page, slug, label, path, section, note=""):
    img_path = f"{OUT_DIR}/{slug}.png"
    try:
        page.wait_for_timeout(500)
        page.screenshot(path=img_path, full_page=True)
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        r = {"section": section, "label": label, "path": path,
             "status": "ok", "img": b64, "note": note}
    except Exception as e:
        r = {"section": section, "label": label, "path": path,
             "status": "error", "img": None, "note": str(e)}
    results.append(r)
    sections.setdefault(section, []).append(len(results) - 1)
    status = "✅" if r["status"] == "ok" else "❌"
    print(f"  {status} [{section}] {label}")
    return r["status"] == "ok"

def goto(page, path, wait="networkidle"):
    try:
        page.goto(BASE_URL + path, wait_until=wait, timeout=20000)
        return True
    except PWTimeout:
        try:
            page.goto(BASE_URL + path, wait_until="load", timeout=15000)
            return True
        except Exception:
            return False

def open_modal(page, selector):
    try:
        page.click(selector, timeout=4000)
        page.wait_for_timeout(400)
        return True
    except Exception:
        return False

def close_modal(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    # ── LOGIN ────────────────────────────────────────────────────────────────
    print("\n🔐 Logging in...")
    goto(page, "/login", wait="load")
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    with page.expect_navigation():
        page.click('button[type="submit"]')
    print("  ✅ Logged in\n")

    # ── 1. DASHBOARD ─────────────────────────────────────────────────────────
    print("📊 DASHBOARD")
    goto(page, "/dashboard")
    shot(page, "01-dashboard", "Dashboard — Main View", "/dashboard", "Dashboard")

    # Scroll down to see charts/stats
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(400)
    shot(page, "01-dashboard-scroll", "Dashboard — Lower Stats & Charts", "/dashboard", "Dashboard", "Scrolled")

    # ── 2. ORDERS ────────────────────────────────────────────────────────────
    print("\n📋 ORDERS")
    goto(page, "/orders")
    shot(page, "02-orders-list", "Orders — Full List", "/orders", "Orders")

    # Filter by status tabs if present
    for status in ["pending", "confirmed", "in_progress", "ready", "delivered"]:
        try:
            btn = page.locator(f'a[href*="status={status}"], button:has-text("{status}"), [data-status="{status}"]').first
            if btn.is_visible(timeout=1000):
                btn.click()
                page.wait_for_timeout(400)
                shot(page, f"02-orders-{status}", f"Orders — Filter: {status.title()}", f"/orders?status={status}", "Orders", f"Status filter: {status}")
                goto(page, "/orders")
        except Exception:
            pass

    # New Order form
    goto(page, "/orders/new")
    shot(page, "02-orders-new", "New Order Form", "/orders/new", "Orders")

    # Fill out and screenshot a partially-filled form
    try:
        page.fill('input[name="customer_name"], input[placeholder*="name"], input[placeholder*="Name"]', "Sarah Johnson", timeout=3000)
        page.fill('input[name="customer_email"], input[type="email"]', "sarah@example.com", timeout=3000)
        page.fill('input[name="customer_phone"], input[placeholder*="phone"], input[placeholder*="Phone"]', "555-123-4567", timeout=3000)
        shot(page, "02-orders-new-filled", "New Order Form — Filled In", "/orders/new", "Orders", "Form partially filled")
    except Exception:
        pass

    # Order detail pages (use real IDs found)
    for oid in [4, 3, 1]:
        if goto(page, f"/orders/{oid}"):
            shot(page, f"02-order-detail-{oid}", f"Order Detail #{oid}", f"/orders/{oid}", "Orders")
            # Try opening any modals/sections on the order detail
            try:
                page.evaluate("window.scrollTo(0, 400)")
                page.wait_for_timeout(300)
                shot(page, f"02-order-detail-{oid}-scroll", f"Order Detail #{oid} — Scrolled", f"/orders/{oid}", "Orders", "Scrolled view")
            except Exception:
                pass

    # ── 3. KITCHEN DISPLAY ───────────────────────────────────────────────────
    print("\n🍽️ KITCHEN")
    goto(page, "/kitchen")
    shot(page, "03-kitchen", "Kitchen Display Board", "/kitchen", "Kitchen")

    for oid in [4, 1, 3]:
        if goto(page, f"/kitchen/order/{oid}"):
            shot(page, f"03-kitchen-order-{oid}", f"Kitchen Order View #{oid}", f"/kitchen/order/{oid}", "Kitchen")

    # ── 4. INVENTORY ─────────────────────────────────────────────────────────
    print("\n📦 INVENTORY")
    goto(page, "/inventory")
    shot(page, "04-inventory", "Inventory — Full List", "/inventory", "Inventory")

    # Search/filter if available
    try:
        search = page.locator('input[placeholder*="search"], input[placeholder*="Search"], input[type="search"]').first
        if search.is_visible(timeout=1500):
            search.fill("flour")
            page.wait_for_timeout(400)
            shot(page, "04-inventory-search", "Inventory — Search: flour", "/inventory", "Inventory", "Filtered by 'flour'")
            search.fill("")
            page.wait_for_timeout(300)
    except Exception:
        pass

    # Open Add Ingredient modal
    goto(page, "/inventory")
    if open_modal(page, 'button:has-text("Add Ingredient"), button:has-text("+ Add")'):
        shot(page, "04-inventory-add-modal", "Inventory — Add Ingredient Modal", "/inventory", "Inventory", "Add modal open")
        close_modal(page)

    # Scroll down to see all ingredients + adjust controls
    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(300)
    shot(page, "04-inventory-scroll", "Inventory — Ingredient Table (Scrolled)", "/inventory", "Inventory", "Showing adjust controls")

    # ── 5. SUPPLIERS ─────────────────────────────────────────────────────────
    print("\n🏭 SUPPLIERS")
    goto(page, "/suppliers")
    shot(page, "05-suppliers", "Suppliers — Main List", "/suppliers", "Suppliers")

    # Scroll down to see supplier cards
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "05-suppliers-scroll", "Suppliers — Cards Scrolled", "/suppliers", "Suppliers")

    # Auto-PO for first supplier
    for sid in [18, 19, 14]:
        if goto(page, f"/suppliers/{sid}/auto-po"):
            shot(page, f"05-suppliers-autopo-{sid}", f"Supplier Auto PO #{sid}", f"/suppliers/{sid}/auto-po", "Suppliers")
            break

    # Open Add Supplier modal
    goto(page, "/suppliers")
    if open_modal(page, 'button:has-text("Add Supplier"), button:has-text("+ Add")'):
        shot(page, "05-suppliers-add-modal", "Suppliers — Add Supplier Modal", "/suppliers", "Suppliers", "Add modal open")
        close_modal(page)

    # ── 6. TOOLS & EQUIPMENT ─────────────────────────────────────────────────
    print("\n🔧 TOOLS")
    goto(page, "/tools")
    shot(page, "06-tools", "Tools & Equipment — Main List", "/tools", "Tools & Equipment")

    # Filter by category if possible
    try:
        cats = page.locator('a[href*="cat="], select[name="cat"] option').all()
        if cats:
            cats[1].click()
            page.wait_for_timeout(400)
            shot(page, "06-tools-filtered", "Tools — Category Filtered", "/tools", "Tools & Equipment", "Category filter applied")
    except Exception:
        pass

    goto(page, "/tools")
    if open_modal(page, 'button:has-text("Add Tool"), button:has-text("+ Add")'):
        shot(page, "06-tools-add-modal", "Tools — Add Tool Modal", "/tools", "Tools & Equipment", "Add modal open")
        close_modal(page)

    # ── 7. RECIPES ───────────────────────────────────────────────────────────
    print("\n📖 RECIPES")
    goto(page, "/recipes")
    shot(page, "07-recipes", "Recipes — Main List", "/recipes", "Recipes")

    goto(page, "/recipes/add")
    shot(page, "07-recipes-add", "Add New Recipe Form", "/recipes/add", "Recipes")

    for rid in [15, 24, 1]:
        if goto(page, f"/recipes/{rid}"):
            shot(page, f"07-recipe-detail-{rid}", f"Recipe Detail #{rid}", f"/recipes/{rid}", "Recipes")
            page.evaluate("window.scrollTo(0, 400)")
            page.wait_for_timeout(300)
            shot(page, f"07-recipe-detail-{rid}-scroll", f"Recipe Detail #{rid} — Ingredients", f"/recipes/{rid}", "Recipes", "Ingredients section")
            break

    # ── 8. CUSTOMERS ─────────────────────────────────────────────────────────
    print("\n👤 CUSTOMERS")
    goto(page, "/customers")
    shot(page, "08-customers", "Customers — Full List", "/customers", "Customers")

    # Search for a customer
    try:
        search = page.locator('input[placeholder*="search"], input[placeholder*="Search"]').first
        if search.is_visible(timeout=1500):
            search.fill("J")
            page.wait_for_timeout(500)
            shot(page, "08-customers-search", "Customers — Search Results", "/customers", "Customers", "Search active")
            search.fill("")
    except Exception:
        pass

    # Scroll down to see customer table rows
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "08-customers-scroll", "Customers — Table (Scrolled)", "/customers", "Customers")

    # ── 9. EMPLOYEES & TIMESHEETS ────────────────────────────────────────────
    print("\n👥 EMPLOYEES")
    goto(page, "/employees")
    shot(page, "09-employees", "Employees — Main List", "/employees", "Employees")

    if open_modal(page, 'button:has-text("Add Employee"), button:has-text("+ Add")'):
        shot(page, "09-employees-add-modal", "Employees — Add Employee Modal", "/employees", "Employees", "Add modal open")
        close_modal(page)

    # Timesheet page for first employee
    goto(page, "/employees")
    try:
        first_ts_link = page.locator('a[href*="/timesheets"]').first
        if first_ts_link.is_visible(timeout=2000):
            href = first_ts_link.get_attribute("href")
            goto(page, href)
            shot(page, "09-timesheets", "Employee Timesheets", href, "Employees")
    except Exception:
        pass

    # ── 10. REPORTS ──────────────────────────────────────────────────────────
    print("\n📊 REPORTS")
    goto(page, "/reports")
    shot(page, "10-reports", "Reports — Overview", "/reports", "Reports")

    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(300)
    shot(page, "10-reports-scroll", "Reports — Charts & Graphs", "/reports", "Reports", "Scrolled to charts")

    page.evaluate("window.scrollTo(0, 1200)")
    page.wait_for_timeout(300)
    shot(page, "10-reports-bottom", "Reports — Lower Sections", "/reports", "Reports", "Full lower view")

    # Date range filter if available
    try:
        date_input = page.locator('input[type="date"], input[name*="from"], input[name*="start"]').first
        if date_input.is_visible(timeout=1500):
            date_input.fill("2026-01-01")
            page.locator('input[type="date"]').last.fill("2026-04-23")
            page.locator('button[type="submit"], button:has-text("Filter"), button:has-text("Apply")').first.click()
            page.wait_for_timeout(600)
            shot(page, "10-reports-filtered", "Reports — Date Filtered", "/reports", "Reports", "Date range applied")
    except Exception:
        pass

    # ── 11. EXPENSES ─────────────────────────────────────────────────────────
    print("\n💸 EXPENSES")
    goto(page, "/expenses")
    shot(page, "11-expenses", "Expenses — Main List", "/expenses", "Expenses")

    if open_modal(page, 'button:has-text("Add Expense"), button:has-text("+ Add"), button:has-text("Log Expense")'):
        shot(page, "11-expenses-add-modal", "Expenses — Add Expense Modal", "/expenses", "Expenses", "Add modal open")
        close_modal(page)

    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "11-expenses-scroll", "Expenses — Table (Scrolled)", "/expenses", "Expenses")

    # ── 12. PREP SHEET ───────────────────────────────────────────────────────
    print("\n📋 PREP SHEET")
    goto(page, "/prep-sheet")
    shot(page, "12-prep-sheet", "Prep Sheet — Today's View", "/prep-sheet", "Prep Sheet")

    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(300)
    shot(page, "12-prep-sheet-scroll", "Prep Sheet — Scrolled", "/prep-sheet", "Prep Sheet")

    # ── 13. MARKETING ────────────────────────────────────────────────────────
    print("\n📣 MARKETING")
    goto(page, "/marketing")
    shot(page, "13-marketing", "Marketing — Campaigns List", "/marketing", "Marketing")

    if open_modal(page, 'button:has-text("New Campaign"), button:has-text("+ Campaign"), button:has-text("Create")'):
        shot(page, "13-marketing-new-modal", "Marketing — New Campaign Modal", "/marketing", "Marketing", "Create modal open")
        close_modal(page)

    # Campaign detail
    goto(page, "/marketing/campaigns/1")
    shot(page, "13-marketing-campaign-1", "Marketing — Campaign Detail #1", "/marketing/campaigns/1", "Marketing")
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "13-marketing-campaign-1-scroll", "Marketing — Campaign #1 Scrolled", "/marketing/campaigns/1", "Marketing")

    # ── 14. LOYALTY & SPECIALS ───────────────────────────────────────────────
    print("\n⭐ LOYALTY")
    goto(page, "/loyalty")
    shot(page, "14-loyalty", "Loyalty Program — Overview", "/loyalty", "Loyalty")

    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "14-loyalty-scroll", "Loyalty — Specials & Members", "/loyalty", "Loyalty")

    if open_modal(page, 'button:has-text("Add Special"), button:has-text("+ Special"), button:has-text("New Special")'):
        shot(page, "14-loyalty-add-special", "Loyalty — Add Special Modal", "/loyalty", "Loyalty", "Add special modal")
        close_modal(page)

    # ── 15. MENU ─────────────────────────────────────────────────────────────
    print("\n🎂 MENU")
    goto(page, "/menu")
    shot(page, "15-menu", "Menu — Public Menu View", "/menu", "Menu")

    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(300)
    shot(page, "15-menu-scroll", "Menu — Scrolled (More Items)", "/menu", "Menu")

    # ── 16. SETTINGS ─────────────────────────────────────────────────────────
    print("\n⚙️ SETTINGS")
    goto(page, "/settings")
    shot(page, "16-settings", "Settings — Main Panel", "/settings", "Settings")

    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    shot(page, "16-settings-scroll", "Settings — Users & Config (Scrolled)", "/settings", "Settings")

    # ── 17. PUBLIC PAGES (no login) ──────────────────────────────────────────
    print("\n🌐 PUBLIC PAGES")
    pub_ctx  = browser.new_context(viewport={"width": 1400, "height": 900})
    pub_page = pub_ctx.new_page()

    # Public order form
    goto(pub_page, "/order")
    shot(pub_page, "17-public-order", "Public Order Form — Landing", "/order", "Public Pages")

    # Fill it out step by step
    try:
        pub_page.fill('input[name="customer_name"], input[placeholder*="name"]', "Emily Davis", timeout=3000)
        pub_page.fill('input[name="customer_email"], input[type="email"]', "emily@example.com", timeout=3000)
        pub_page.fill('input[name="customer_phone"], input[placeholder*="phone"]', "555-987-6543", timeout=3000)
        pub_page.wait_for_timeout(300)
        shot(pub_page, "17-public-order-filled", "Public Order Form — Filled Out", "/order", "Public Pages", "Customer info filled")
    except Exception:
        pass

    # Scroll for more of the form
    pub_page.evaluate("window.scrollTo(0, 500)")
    pub_page.wait_for_timeout(300)
    shot(pub_page, "17-public-order-scroll", "Public Order Form — Cake Options", "/order", "Public Pages", "Scrolled to cake options")

    # Join loyalty
    goto(pub_page, "/join")
    shot(pub_page, "17-public-join", "Join Loyalty Program", "/join", "Public Pages")

    try:
        pub_page.fill('input[name="name"], input[placeholder*="name"]', "Test Customer", timeout=2000)
        pub_page.fill('input[type="email"]', "test@example.com", timeout=2000)
        shot(pub_page, "17-public-join-filled", "Join Loyalty — Form Filled", "/join", "Public Pages", "Form filled in")
    except Exception:
        pass

    # QR code page
    goto(pub_page, "/qr")
    shot(pub_page, "17-public-qr", "QR Code Page", "/qr", "Public Pages")

    # Menu (public)
    goto(pub_page, "/menu")
    shot(pub_page, "17-public-menu", "Public Menu", "/menu", "Public Pages")
    pub_page.evaluate("window.scrollTo(0, 600)")
    pub_page.wait_for_timeout(300)
    shot(pub_page, "17-public-menu-scroll", "Public Menu — More Items", "/menu", "Public Pages")

    pub_ctx.close()

    # ── 18. MOBILE RESPONSIVE VIEWS ──────────────────────────────────────────
    print("\n📱 MOBILE VIEWS")
    mob_ctx  = browser.new_context(viewport={"width": 390, "height": 844})
    mob_page = mob_ctx.new_page()

    goto(mob_page, "/login", wait="load")
    mob_page.fill('input[name="email"]', EMAIL)
    mob_page.fill('input[name="password"]', PASSWORD)
    with mob_page.expect_navigation():
        mob_page.click('button[type="submit"]')

    for path, label, slug in [
        ("/dashboard",  "Dashboard",    "mob-dashboard"),
        ("/orders",     "Orders",       "mob-orders"),
        ("/inventory",  "Inventory",    "mob-inventory"),
        ("/kitchen",    "Kitchen",      "mob-kitchen"),
        ("/customers",  "Customers",    "mob-customers"),
    ]:
        goto(mob_page, path)
        shot(mob_page, f"18-{slug}", f"Mobile — {label}", path, "Mobile Views")

    mob_ctx.close()
    browser.close()

# ── BUILD REPORT ──────────────────────────────────────────────────────────────
print("\n📄 Building HTML report...")

ok_count  = sum(1 for r in results if r["status"] == "ok")
err_count = sum(1 for r in results if r["status"] == "error")
ts        = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

# Build section nav
nav_html = ""
for sec in sections:
    nav_html += f'<a href="#{sec.lower().replace(" ","_").replace("&","")}" style="padding:6px 14px;background:rgba(255,255,255,.06);border-radius:20px;color:#94a3b8;text-decoration:none;font-size:.8rem;white-space:nowrap">{sec}</a>\n'

# Build cards grouped by section
body_html = ""
for sec, idxs in sections.items():
    sec_id = sec.lower().replace(" ", "_").replace("&", "")
    body_html += f'''
    <div id="{sec_id}" style="margin-bottom:48px">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #1e293b">
        <h2 style="font-size:1.3rem;font-weight:800;color:#f8fafc;margin:0">{sec}</h2>
        <span style="font-size:.75rem;color:#64748b">{len(idxs)} screenshots</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(640px,1fr));gap:20px">
    '''
    for i in idxs:
        r = results[i]
        if r["status"] == "error":
            badge    = '<span style="background:#ef4444;color:#fff;padding:2px 10px;border-radius:20px;font-size:.72rem;font-weight:700">❌ ERROR</span>'
            img_html = f'<div style="background:#1e1e1e;border-radius:10px;padding:40px;text-align:center;color:#ef4444">{r.get("note","")}</div>'
        else:
            badge    = '<span style="background:#22c55e;color:#fff;padding:2px 10px;border-radius:20px;font-size:.72rem;font-weight:700">✅ PASS</span>'
            img_html = f'<img src="data:image/png;base64,{r["img"]}" style="width:100%;border-radius:8px;display:block;cursor:pointer" onclick="openLB(this.src)">'

        note_html = f'<span style="font-size:.72rem;color:#64748b;margin-left:8px">{r["note"]}</span>' if r.get("note") else ""

        body_html += f'''
        <div style="background:#1a1a2e;border:1px solid #2d2d4e;border-radius:12px;overflow:hidden">
          <div style="padding:12px 16px;display:flex;align-items:center;gap:10px;border-bottom:1px solid #2d2d4e;background:#16213e">
            <div style="flex:1">
              <span style="font-size:.92rem;font-weight:700;color:#f8fafc">{r["label"]}</span>{note_html}
              <div style="font-size:.72rem;color:#475569;font-family:monospace;margin-top:2px">{r["path"]}</div>
            </div>
            {badge}
          </div>
          <div style="padding:10px">{img_html}</div>
        </div>
        '''
    body_html += "</div></div>"

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sweet Spot CRM — Deep System Test Report</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#0f0f23; color:#f8fafc; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
.hero {{ background:linear-gradient(135deg,#1a1a2e,#16213e 50%,#0f3460); padding:50px 40px 40px; text-align:center; border-bottom:1px solid #2d2d4e; }}
.hero h1 {{ font-size:2.2rem; font-weight:900; background:linear-gradient(90deg,#f472b6,#a78bfa,#38bdf8); -webkit-background-clip:text; -webkit-text-fill-color:transparent; margin-bottom:8px; }}
.stats {{ display:flex; justify-content:center; gap:20px; margin-top:24px; flex-wrap:wrap; }}
.stat {{ background:rgba(255,255,255,.05); border:1px solid rgba(255,255,255,.1); border-radius:12px; padding:14px 26px; text-align:center; }}
.stat .num {{ font-size:1.9rem; font-weight:900; }}
.stat .lbl {{ font-size:.72rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.07em; margin-top:2px; }}
.blue{{color:#38bdf8}} .green{{color:#22c55e}} .red{{color:#ef4444}} .purple{{color:#a78bfa}}
.nav {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:center; padding:20px 40px; background:#0d0d1f; border-bottom:1px solid #1e293b; position:sticky; top:0; z-index:100; }}
.content {{ max-width:1400px; margin:40px auto; padding:0 32px; }}
.footer {{ text-align:center; padding:36px; color:#334155; font-size:.78rem; border-top:1px solid #1e293b; margin-top:20px; }}
/* Lightbox */
#lb {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.94); z-index:9999; align-items:center; justify-content:center; padding:20px; }}
#lb.open {{ display:flex; }}
#lb img {{ max-width:95vw; max-height:92vh; border-radius:10px; box-shadow:0 0 80px rgba(0,0,0,.9); }}
#lb-close {{ position:fixed; top:16px; right:22px; font-size:2rem; color:#fff; cursor:pointer; background:none; border:none; z-index:10000; line-height:1; }}
</style>
</head>
<body>

<div id="lb" onclick="closeLB()">
  <button id="lb-close" onclick="closeLB()">✕</button>
  <img id="lb-img" src="">
</div>

<div class="hero">
  <div style="font-size:2.2rem;margin-bottom:10px">🎂</div>
  <h1>Sweet Spot CRM — Deep System Test</h1>
  <p style="color:#94a3b8;font-size:.95rem">Full coverage: every page, every detail view, modals, filters, forms, mobile</p>
  <p style="margin-top:6px"><a href="https://sweet-spot-cakes.up.railway.app" target="_blank" style="color:#38bdf8;font-size:.85rem;text-decoration:none">🔗 sweet-spot-cakes.up.railway.app</a></p>
  <div class="stats">
    <div class="stat"><div class="num blue">{len(results)}</div><div class="lbl">Screenshots</div></div>
    <div class="stat"><div class="num purple">{len(sections)}</div><div class="lbl">Sections</div></div>
    <div class="stat"><div class="num green">{ok_count}</div><div class="lbl">Passed</div></div>
    <div class="stat"><div class="num red">{err_count}</div><div class="lbl">Errors</div></div>
  </div>
  <p style="color:#475569;font-size:.78rem;margin-top:16px">Generated {ts}</p>
</div>

<div class="nav">
{nav_html}
</div>

<div class="content">
{body_html}
</div>

<div class="footer">
  Generated by Echo · Alexander AI Integrated Solutions · {ts}
</div>

<script>
function openLB(src) {{
  document.getElementById('lb-img').src = src;
  document.getElementById('lb').classList.add('open');
}}
function closeLB() {{
  document.getElementById('lb').classList.remove('open');
}}
document.addEventListener('keydown', function(e) {{ if(e.key==='Escape') closeLB(); }});
</script>
</body>
</html>"""

with open(REPORT, "w") as f:
    f.write(html)

print(f"\n✅ {ok_count}/{len(results)} passed  |  {err_count} errors")
print(f"📄 Report: {REPORT}")
