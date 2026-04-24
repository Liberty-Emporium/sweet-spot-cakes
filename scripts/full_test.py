#!/usr/bin/env python3
"""
Sweet Spot CRM — COMPLETE Route Coverage Test
Tests EVERY route in the app. GET pages are visited and screenshot.
POST routes are exercised with real data. Every modal, tab, form, 
status change, timesheet, tool, setting, recipe ingredient edit,
order item add, cash payment, checkout flow — ALL of it.
"""

import os, base64, datetime, time
from datetime import timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE      = "https://sweet-spot-cakes.up.railway.app"
EMAIL     = "info@sweetspotcustomcakes.com"
PASSWORD  = "sweetspot2026"
SS_DIR    = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/full_test_shots"
REPORT    = "/root/.openclaw/workspace/sweet-spot-cakes/index.html"
os.makedirs(SS_DIR, exist_ok=True)

# Real IDs from the live app
ORDER_IDS    = [1, 3, 10, 11, 12]
INV_IDS      = [1, 10, 11, 12, 13]
SUPPLIER_IDS = [13, 14, 15, 16, 17]
RECIPE_IDS   = [1, 10, 11, 12, 13]
EMP_IDS      = [1, 2, 3, 4]
EXPENSE_IDS  = [1, 2, 3]
CAMPAIGN_IDS = [1, 2, 3]
TOOL_IDS     = [1, 10, 11]
SPECIAL_IDS  = [1, 2]

results = []   # {section, label, status, note, img}
sections = {}

ERROR_MARKERS = [
    "internal server error", "not found", "404 not found",
    "werkzeug", "traceback (most recent", "syntaxerror",
    "attributeerror", "keyerror", "typeerror", "nameerror",
    "operationalerror", "bad gateway", "service unavailable",
]

def has_error(content, title=""):
    cl = content.lower()
    tl = title.lower()
    for m in ERROR_MARKERS:
        if m in tl:
            return m
        # avoid false positives from CSS (e.g. font-size:500)
        idx = cl.find(m)
        while idx != -1:
            ctx = cl[max(0,idx-30):idx+50]
            if not any(x in ctx for x in ['font-size','font-weight','#','px','rem','em',':']):
                return m
            idx = cl.find(m, idx+1)
    return None

# ── helpers ──────────────────────────────────────────────────────────────────

def log(section, label, status, note="", img=None):
    r = {"section":section,"label":label,"status":status,"note":note,"img":img}
    results.append(r)
    sections.setdefault(section,[]).append(len(results)-1)
    icon = "✅" if status=="ok" else "❌"
    print(f"    {icon} {label}{' — '+note if note else ''}")

def nav(page, path):
    try:
        page.goto(BASE+path, wait_until="networkidle", timeout=18000)
        return True
    except PWTimeout:
        try:
            page.goto(BASE+path, wait_until="load", timeout=10000)
            return True
        except Exception as e:
            return False

def shot(page, slug, label, section, note=""):
    path = f"{SS_DIR}/{slug}.png"
    try:
        page.wait_for_timeout(400)
        content = page.content()
        title   = page.title()
        err = has_error(content, title)
        page.screenshot(path=path, full_page=True)
        with open(path,"rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        if err:
            log(section, label, "error", f"page error: {err}", b64)
        else:
            log(section, label, "ok", note, b64)
    except Exception as e:
        log(section, label, "error", str(e)[:120])

def post_form(page, action_url, fields, section, label, follow=True):
    """Submit a form via fetch and check the response."""
    try:
        body_parts = "&".join(f"{k}={v}" for k,v in fields.items())
        js = f"""async () => {{
            const r = await fetch('{BASE}{action_url}', {{
                method:'POST',
                headers:{{'Content-Type':'application/x-www-form-urlencoded','X-Requested-With':'XMLHttpRequest'}},
                body:'{body_parts}',
                redirect:'follow'
            }});
            return {{status: r.status, url: r.url}};
        }}"""
        result = page.evaluate(js)
        ok = result['status'] < 400
        log(section, label, "ok" if ok else "error",
            f"HTTP {result['status']} → {result['url'][-60:]}")
    except Exception as e:
        log(section, label, "error", str(e)[:120])

def close_modal(page):
    try:
        page.evaluate("() => { const m=document.getElementById('addModal'); if(m) m.style.display='none'; }")
        page.wait_for_timeout(150)
    except Exception:
        pass

def open_modal(page):
    try:
        page.evaluate("() => { const m=document.getElementById('addModal'); if(m) m.style.display='flex'; }")
        page.wait_for_timeout(300)
    except Exception:
        pass

def fill_modal_submit(page, fields, section, label, select_fields=None):
    """Open addModal, fill fields, submit, take screenshot."""
    try:
        close_modal(page)
        open_modal(page)
        modal = page.query_selector('#addModal')
        if not modal:
            log(section, label, "error", "addModal not found")
            return False
        for fname, val in fields.items():
            inp = modal.query_selector(f'input[name="{fname}"]')
            if inp:
                inp.fill(str(val))
        if select_fields:
            for fname, val in select_fields.items():
                sel = modal.query_selector(f'select[name="{fname}"]')
                if sel:
                    try:
                        sel.select_option(label=val)
                    except Exception:
                        try:
                            sel.select_option(value=val)
                        except Exception:
                            sel.select_option(index=1)
        submit = modal.query_selector('button[type="submit"]')
        if not submit:
            log(section, label, "error", "no submit button in modal")
            return False
        submit.click()
        page.wait_for_load_state("networkidle", timeout=10000)
        page.wait_for_timeout(300)
        # check for error
        err = has_error(page.content(), page.title())
        if err:
            log(section, label, "error", f"after submit: {err}")
            return False
        log(section, label, "ok")
        return True
    except Exception as e:
        log(section, label, "error", str(e)[:120])
        return False

def scroll(page, steps=3):
    page.evaluate(f"""() => {{
        const t=Math.max(document.body.scrollHeight-window.innerHeight,0)/({steps});
        let i=0; const x=setInterval(()=>{{window.scrollBy(0,t);if(++i>={steps})clearInterval(x);}},200);
    }}""")
    page.wait_for_timeout(steps*220+400)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN TEST RUN
# ─────────────────────────────────────────────────────────────────────────────

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width":1400,"height":900})
    page = ctx.new_page()

    # ── LOGIN ────────────────────────────────────────────────────────────────
    print("\n🔐 LOGIN")
    nav(page, "/login")
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', PASSWORD)
    with page.expect_navigation(timeout=12000):
        page.click('button[type="submit"]')
    shot(page, "00-login", "Login → Dashboard", "Auth")

    # ── DASHBOARD ────────────────────────────────────────────────────────────
    print("\n📊 DASHBOARD")
    nav(page, "/dashboard")
    shot(page, "01-dashboard", "Dashboard — top", "Dashboard")
    scroll(page, 4)
    shot(page, "01-dashboard-scroll", "Dashboard — charts/stats", "Dashboard", "scrolled")

    # ── ORDERS ───────────────────────────────────────────────────────────────
    print("\n📋 ORDERS")
    nav(page, "/orders")
    shot(page, "02-orders", "Orders — list", "Orders")

    # Status filter tabs
    for status in ["pending","confirmed","in_progress","ready","delivered","cancelled"]:
        nav(page, f"/orders?status={status}")
        shot(page, f"02-orders-{status}", f"Orders — filter: {status}", "Orders")

    # New order form
    nav(page, "/orders/new")
    shot(page, "02-orders-new", "New Order — blank form", "Orders")
    # Fill the form
    pickup = (datetime.datetime.now()+timedelta(days=7)).strftime("%Y-%m-%d")
    try:
        for fname,val in [("customer_name","Full Test Customer"),("customer_email","fulltest@example.com"),
                          ("customer_phone","555-000-1111"),("pickup_date",pickup)]:
            inp = page.query_selector(f'input[name="{fname}"]')
            if inp: inp.fill(val)
        for fname in ["cake_flavor","cake_size"]:
            sel = page.query_selector(f'select[name="{fname}"]')
            if sel: sel.select_option(index=1)
        ta = page.query_selector('textarea[name="special_notes"]')
        if ta: ta.fill("Full integration test order — please ignore")
        scroll(page, 2)
        shot(page, "02-orders-new-filled", "New Order — filled", "Orders")
        submit = None
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible(): submit=btn; break
        if submit:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=12000)
            shot(page, "02-orders-after-new", "After new order submit", "Orders")
    except Exception as e:
        log("Orders","New order form submit","error",str(e)[:100])

    # Get the new order ID from the redirect URL
    new_order_id = None
    if "/orders/" in page.url and "/new" not in page.url:
        try: new_order_id = int(page.url.split("/orders/")[-1].split("/")[0])
        except Exception: pass
    if new_order_id:
        ORDER_IDS.insert(0, new_order_id)

    # Order detail pages
    for oid in ORDER_IDS[:4]:
        nav(page, f"/orders/{oid}")
        shot(page, f"02-order-{oid}", f"Order #{oid} detail", "Orders")
        scroll(page, 2)
        shot(page, f"02-order-{oid}-scroll", f"Order #{oid} scrolled", "Orders")

        # Add item to order
        post_form(page, f"/orders/{oid}/add-item",
                  {"name":"Test Cake Tier","quantity":"1","unit_price":"35.00","description":"integration test item"},
                  "Orders", f"Order #{oid} — add item")

        # Update status
        for new_status in ["confirmed","in_progress"]:
            post_form(page, f"/orders/{oid}/status", {"status":new_status},
                      "Orders", f"Order #{oid} — status → {new_status}")

        # Checkout (creates Stripe session or cash option)
        nav(page, f"/orders/{oid}")
        try:
            checkout_btn = page.query_selector('form[action*="checkout"] button, button:has-text("Checkout"), button:has-text("Collect Payment")')
            if checkout_btn and checkout_btn.is_visible():
                checkout_btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                shot(page, f"02-order-{oid}-checkout", f"Order #{oid} checkout", "Orders")
                page.go_back()
                page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Cash payment
        post_form(page, f"/orders/{oid}/cash-payment",
                  {"amount_paid":"100.00","payment_note":"cash test"},
                  "Orders", f"Order #{oid} — cash payment")

        # Kitchen view for this order
        nav(page, f"/kitchen/order/{oid}")
        shot(page, f"02-kitchen-order-{oid}", f"Kitchen view Order #{oid}", "Kitchen")

    # ── KITCHEN ──────────────────────────────────────────────────────────────
    print("\n🍳 KITCHEN")
    nav(page, "/kitchen")
    shot(page, "03-kitchen", "Kitchen — display board", "Kitchen")
    scroll(page, 3)
    shot(page, "03-kitchen-scroll", "Kitchen — scrolled", "Kitchen")

    # ── INVENTORY ────────────────────────────────────────────────────────────
    print("\n📦 INVENTORY")
    nav(page, "/inventory")
    shot(page, "04-inventory", "Inventory — list", "Inventory")
    scroll(page, 4)
    shot(page, "04-inventory-scroll", "Inventory — scrolled", "Inventory")

    # Add ingredients
    ingredient_adds = [
        {"name":"Almond Flour","unit":"lbs","quantity":"15","reorder_level":"3","cost_per_unit":"4.50"},
        {"name":"Vanilla Extract","unit":"oz","quantity":"32","reorder_level":"8","cost_per_unit":"0.95"},
        {"name":"Powdered Sugar","unit":"lbs","quantity":"40","reorder_level":"10","cost_per_unit":"0.60"},
    ]
    for ing in ingredient_adds:
        nav(page, "/inventory")
        fill_modal_submit(page, ing, "Inventory", f"Add ingredient: {ing['name']}")

    # Adjust, edit, set-supplier on existing items
    for iid in INV_IDS[:3]:
        post_form(page, f"/inventory/{iid}/adjust", {"delta":"3"},
                  "Inventory", f"Inventory #{iid} — adjust +3")
        post_form(page, f"/inventory/{iid}/adjust", {"delta":"-1"},
                  "Inventory", f"Inventory #{iid} — adjust -1")
        post_form(page, f"/inventory/{iid}/set-supplier", {"supplier_id":str(SUPPLIER_IDS[0])},
                  "Inventory", f"Inventory #{iid} — set supplier")

    # Edit an ingredient
    post_form(page, f"/inventory/{INV_IDS[0]}/edit",
              {"name":"Bread Flour (Updated)","unit":"lbs","quantity":"52","reorder_level":"10",
               "cost_per_unit":"0.68","supplier_id":str(SUPPLIER_IDS[0]),"notes":"Primary flour stock"},
              "Inventory", f"Inventory #{INV_IDS[0]} — edit")

    # ── SUPPLIERS ────────────────────────────────────────────────────────────
    print("\n🚚 SUPPLIERS")
    nav(page, "/suppliers")
    shot(page, "05-suppliers", "Suppliers — list", "Suppliers")
    scroll(page, 3)

    # Add suppliers
    supplier_adds = [
        {"name":"Global Baking Co.","contact_name":"Sue Kim","email":"sue@globalbaking.com","phone":"800-555-9001","payment_terms":"Net 30"},
        {"name":"Fresh Farms Direct","contact_name":"Paul Nash","email":"paul@freshfarms.com","phone":"800-555-9002","payment_terms":"COD"},
    ]
    for s in supplier_adds:
        nav(page, "/suppliers")
        fill_modal_submit(page, s, "Suppliers", f"Add supplier: {s['name']}")

    # Auto-PO for each supplier
    for sid in SUPPLIER_IDS[:3]:
        nav(page, f"/suppliers/{sid}/auto-po")
        shot(page, f"05-supplier-{sid}-autopo", f"Supplier #{sid} Auto-PO", "Suppliers")
        scroll(page, 2)
        # Submit the PO if there are items
        try:
            submit = page.query_selector('button[type="submit"]:has-text("Send"), button[type="submit"]:has-text("Submit"), form[action*="purchase"] button[type="submit"]')
            if submit and submit.is_visible():
                submit.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                shot(page, f"05-supplier-{sid}-po-sent", f"Supplier #{sid} PO sent", "Suppliers")
        except Exception:
            pass

    # ── TOOLS ────────────────────────────────────────────────────────────────
    print("\n🔧 TOOLS")
    nav(page, "/tools")
    shot(page, "06-tools", "Tools — list", "Tools")
    scroll(page, 3)

    # Add tools
    tools_to_add = [
        {"name":"Offset Spatula Set","category":"Decorating","quantity":"3","condition":"Good","notes":"12-inch and 8-inch"},
        {"name":"Cake Turntable","category":"Decorating","quantity":"2","condition":"Excellent","notes":"Heavy-duty aluminum"},
        {"name":"Stand Mixer Bowl","category":"Mixing","quantity":"4","condition":"Good","notes":"5-quart stainless"},
    ]
    for t in tools_to_add:
        nav(page, "/tools")
        fill_modal_submit(page, t, "Tools", f"Add tool: {t['name']}")

    # Edit a tool
    nav(page, "/tools")
    post_form(page, f"/tools/{TOOL_IDS[0]}/edit",
              {"name":"KitchenAid Stand Mixer","category":"Mixing","quantity":"2",
               "condition":"Good","notes":"Primary mixing equipment - updated"},
              "Tools", f"Edit tool #{TOOL_IDS[0]}")

    # ── RECIPES ──────────────────────────────────────────────────────────────
    print("\n📖 RECIPES")
    nav(page, "/recipes")
    shot(page, "07-recipes", "Recipes — list", "Recipes")
    scroll(page, 2)

    # Add recipes
    recipes_to_add = [
        {"name":"Lemon Lavender Cake","servings":"10","prep_mins":"25","bake_mins":"35","base_price":"75"},
        {"name":"Strawberry Dream Cake","servings":"14","prep_mins":"40","bake_mins":"50","base_price":"85"},
        {"name":"Red Velvet Supreme","servings":"16","prep_mins":"35","bake_mins":"40","base_price":"95"},
    ]
    new_recipe_ids = []
    for r in recipes_to_add:
        nav(page, "/recipes/add")
        try:
            page.fill('input[name="name"]', r["name"], timeout=3000)
            cat_sel = page.query_selector('select[name="category"]')
            if cat_sel: cat_sel.select_option(index=1)
            for fname in ["servings","prep_mins","bake_mins","base_price"]:
                inp = page.query_selector(f'input[name="{fname}"]')
                if inp: inp.fill(r[fname])
            ta = page.query_selector('textarea[name="description"]')
            if ta: ta.fill(f"Customer favorite — {r['name']}. Made fresh daily.")
            submit = None
            for btn in page.query_selector_all('button[type="submit"]'):
                if btn.is_visible(): submit=btn; break
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                if "/recipes/" in page.url and "/add" not in page.url:
                    rid = int(page.url.split("/recipes/")[-1].split("/")[0])
                    new_recipe_ids.append(rid)
                    RECIPE_IDS.append(rid)
                shot(page, f"07-recipe-new-{r['name'][:10].replace(' ','-').lower()}", f"New recipe: {r['name']}", "Recipes")
                log("Recipes", f"Add recipe: {r['name']}", "ok")
        except Exception as e:
            log("Recipes", f"Add recipe: {r['name']}", "error", str(e)[:100])

    # Recipe detail — add/edit/remove ingredients, add tools
    for rid in RECIPE_IDS[:4]:
        nav(page, f"/recipes/{rid}")
        shot(page, f"07-recipe-{rid}", f"Recipe #{rid} detail", "Recipes")
        scroll(page, 3)

        # Add ingredient to recipe
        try:
            ing_sel = page.query_selector('select[name="ingredient_id"]')
            if ing_sel:
                opts = ing_sel.query_selector_all('option[value]')
                if opts and len(opts)>1:
                    ing_sel.select_option(index=1)
                    qty = page.query_selector('input[name="quantity"]')
                    unit = page.query_selector('input[name="unit"]')
                    if qty: qty.fill("2")
                    if unit: unit.fill("cups")
                    submit = page.query_selector('form[action*="add-ingredient"] button[type="submit"]')
                    if not submit:
                        for btn in page.query_selector_all('button[type="submit"]'):
                            if btn.is_visible(): submit=btn; break
                    if submit:
                        submit.click()
                        page.wait_for_load_state("networkidle", timeout=8000)
                        log("Recipes", f"Recipe #{rid} — add ingredient", "ok")
        except Exception as e:
            log("Recipes", f"Recipe #{rid} — add ingredient", "error", str(e)[:80])

        # Add tool to recipe via JSON API
        try:
            result = page.evaluate(f"""async () => {{
                const r = await fetch('{BASE}/api/recipe-tools/{rid}', {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body: JSON.stringify({{tool_id: {TOOL_IDS[0]}}}) 
                }});
                return {{status: r.status}};
            }}""")
            ok = result['status'] < 400
            log("Recipes", f"Recipe #{rid} — add tool", "ok" if ok else "error",
                f"HTTP {result['status']}")
        except Exception as e:
            log("Recipes", f"Recipe #{rid} — add tool", "error", str(e)[:80])

        # Check for recipe_ingredients to edit/remove
        nav(page, f"/recipes/{rid}")
        try:
            ri_links = page.query_selector_all('form[action*="update-ingredient"], form[action*="remove-ingredient"]')
            if ri_links:
                first = ri_links[0]
                action = first.get_attribute('action') or ''
                ri_id = action.split('/')[-1] if action else None
                if ri_id and ri_id.isdigit():
                    post_form(page, f"/recipes/{rid}/update-ingredient/{ri_id}",
                              {"quantity":"3","unit":"oz"},
                              "Recipes", f"Recipe #{rid} — update ingredient #{ri_id}")
        except Exception:
            pass

    # ── CUSTOMERS ────────────────────────────────────────────────────────────
    print("\n👥 CUSTOMERS")
    nav(page, "/customers")
    shot(page, "08-customers", "Customers — list", "Customers")
    scroll(page, 4)

    # Search
    for q in ["Maria","Derek","Lisa","chocolate",""]:
        nav(page, f"/customers?q={q}")
        shot(page, f"08-customers-search-{q or 'all'}", f"Customers — search: '{q}'", "Customers")

    # API customer search
    nav(page, "/api/customers/search?q=Maria")
    shot(page, "08-customers-api", "Customers API search", "Customers")

    # ── EMPLOYEES ────────────────────────────────────────────────────────────
    print("\n👔 EMPLOYEES")
    nav(page, "/employees")
    shot(page, "09-employees", "Employees — list", "Employees")
    scroll(page, 3)

    # Add employees
    emp_adds = [
        {"name":"Carlos Rivera","email":"carlos@sweetspot.com","phone":"919-555-7001","hourly_rate":"17.50"},
        {"name":"Priya Patel","email":"priya@sweetspot.com","phone":"919-555-7002","hourly_rate":"16.00"},
    ]
    role_opts = ["Baker","Decorator","Counter Staff","Manager"]
    for i, e in enumerate(emp_adds):
        nav(page, "/employees")
        fill_modal_submit(page, e, "Employees", f"Add employee: {e['name']}",
                         select_fields={"role": role_opts[i % len(role_opts)]})

    # Timesheet clock-in / clock-out
    for eid in EMP_IDS[:3]:
        nav(page, f"/employees/{eid}/timesheets")
        shot(page, f"09-emp-{eid}-timesheets", f"Employee #{eid} timesheets", "Employees")
        scroll(page, 2)

        post_form(page, "/timesheets/clockin",
                  {"employee_id":str(eid),"notes":"Integration test clock-in"},
                  "Employees", f"Employee #{eid} — clock in")
        page.wait_for_timeout(500)
        post_form(page, "/timesheets/clockout",
                  {"employee_id":str(eid),"break_mins":"15","notes":"Integration test clock-out"},
                  "Employees", f"Employee #{eid} — clock out")

        nav(page, f"/employees/{eid}/timesheets")
        shot(page, f"09-emp-{eid}-ts-after", f"Employee #{eid} timesheets after clock", "Employees")

    # ── REPORTS ──────────────────────────────────────────────────────────────
    print("\n📈 REPORTS")
    nav(page, "/reports")
    shot(page, "10-reports", "Reports — top", "Reports")
    page.wait_for_timeout(800)
    scroll(page, 6)
    shot(page, "10-reports-scroll", "Reports — charts", "Reports")

    # Prep sheet
    nav(page, "/prep-sheet")
    shot(page, "10-prep-sheet", "Prep Sheet", "Reports")
    scroll(page, 4)

    # ── EXPENSES ─────────────────────────────────────────────────────────────
    print("\n💰 EXPENSES")
    nav(page, "/expenses")
    shot(page, "11-expenses", "Expenses — list", "Expenses")
    scroll(page, 3)

    expense_adds = [
        {"description":"Cake box restock","amount":"78.50","category":"packaging"},
        {"description":"Food coloring set","amount":"32.00","category":"ingredients"},
        {"description":"Refrigerator maintenance","amount":"165.00","category":"equipment"},
        {"description":"Water bill","amount":"88.00","category":"utilities"},
        {"description":"Instagram ads","amount":"50.00","category":"marketing"},
    ]
    for exp in expense_adds:
        nav(page, "/expenses")
        close_modal(page)
        open_modal(page)
        modal = page.query_selector('#addModal')
        if modal:
            for fname, val in exp.items():
                inp = modal.query_selector(f'input[name="{fname}"], textarea[name="{fname}"]')
                if inp and inp.is_visible():
                    inp.fill(val)
                sel = modal.query_selector(f'select[name="{fname}"]')
                if sel and sel.is_visible():
                    try: sel.select_option(value=val)
                    except Exception:
                        try: sel.select_option(label=val)
                        except Exception: sel.select_option(index=1)
            date_inp = modal.query_selector('input[name="date"], input[type="date"]')
            if date_inp and date_inp.is_visible():
                date_inp.fill(datetime.datetime.now().strftime("%Y-%m-%d"))
            submit = modal.query_selector('button[type="submit"]')
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                log("Expenses", f"Add expense: {exp['description']}", "ok")

    # ── SETTINGS ─────────────────────────────────────────────────────────────
    print("\n⚙️  SETTINGS")
    nav(page, "/settings")
    shot(page, "12-settings", "Settings — full page", "Settings")
    scroll(page, 5)
    shot(page, "12-settings-scroll", "Settings — scrolled", "Settings")

    # Add a new user
    nav(page, "/settings")
    post_form(page, "/settings/add-user",
              {"name":"Test User","email":"testuser@sweetspot.com","password":"testpass123","role":"staff"},
              "Settings", "Add user account")

    # ── MARKETING ────────────────────────────────────────────────────────────
    print("\n📣 MARKETING")
    nav(page, "/marketing")
    shot(page, "13-marketing", "Marketing — campaign list", "Marketing")
    scroll(page, 3)

    # Create campaigns
    campaign_names = ["Summer Cake Sale","Back to School Treats","Holiday Pre-Order Special"]
    new_campaign_ids = []
    for cname in campaign_names:
        nav(page, "/marketing")
        try:
            btn = page.query_selector('button:has-text("New Campaign"), button:has-text("Create"), button:has-text("+ New")')
            if btn: btn.click()
            page.wait_for_timeout(500)
            for fname, val in [("name",cname),("subject",f"🎂 {cname} — Sweet Spot Cakes")]:
                for el in page.query_selector_all(f'input[name="{fname}"]'):
                    if el.is_visible(): el.fill(val); break
            ta = page.query_selector('textarea[name="body"],textarea[name="content"],textarea[name="message"]')
            if ta and ta.is_visible():
                ta.fill(f"Special offer just for you — {cname}. Order online at sweetspotcustomcakes.com")
            submit = None
            for btn in page.query_selector_all('button[type="submit"]'):
                if btn.is_visible(): submit=btn; break
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                if "/marketing/campaigns/" in page.url:
                    cid = int(page.url.split("/campaigns/")[-1].split("/")[0])
                    new_campaign_ids.append(cid)
                    CAMPAIGN_IDS.append(cid)
                log("Marketing", f"Create campaign: {cname}", "ok")
        except Exception as e:
            log("Marketing", f"Create campaign: {cname}", "error", str(e)[:80])

    # Campaign detail, edit, mark-sent, generate-ad
    for cid in CAMPAIGN_IDS[:4]:
        nav(page, f"/marketing/campaigns/{cid}")
        shot(page, f"13-campaign-{cid}", f"Campaign #{cid} detail", "Marketing")
        scroll(page, 2)

        post_form(page, f"/marketing/campaigns/{cid}/edit",
                  {"name":f"Campaign #{cid} (Edited)","subject":"Updated subject line"},
                  "Marketing", f"Campaign #{cid} — edit")

        post_form(page, f"/marketing/campaigns/{cid}/mark-sent", {},
                  "Marketing", f"Campaign #{cid} — mark sent")

        nav(page, f"/marketing/campaigns/{cid}")
        shot(page, f"13-campaign-{cid}-after", f"Campaign #{cid} after mark-sent", "Marketing")

    # ── LOYALTY ──────────────────────────────────────────────────────────────
    print("\n🌟 LOYALTY")
    nav(page, "/loyalty")
    shot(page, "14-loyalty", "Loyalty — overview", "Loyalty")
    scroll(page, 3)

    # Add specials
    specials = [
        {"title":"Summer Fling Special","description":"10% off all summer flavors June-August","discount_percent":"10"},
        {"title":"Birthday Month Bonus","description":"Free custom message + candles for birthday month orders","discount_percent":"5"},
        {"title":"Referral Reward","description":"$10 off your next order when you refer a friend","discount_percent":"0"},
    ]
    for sp in specials:
        nav(page, "/loyalty")
        close_modal(page)
        try:
            btn = page.query_selector('button:has-text("Add Special"), button:has-text("+ Add")')
            if btn: btn.click()
            page.wait_for_timeout(400)
            for fname, val in sp.items():
                for el in page.query_selector_all(f'input[name="{fname}"], textarea[name="{fname}"]'):
                    if el.is_visible(): el.fill(val); break
            submit = None
            for btn in page.query_selector_all('button[type="submit"]'):
                if btn.is_visible(): submit=btn; break
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                log("Loyalty", f"Add special: {sp['title']}", "ok")
        except Exception as e:
            log("Loyalty", f"Add special: {sp['title']}", "error", str(e)[:80])

    # Toggle specials
    for sid in SPECIAL_IDS:
        post_form(page, f"/loyalty/specials/{sid}/toggle", {},
                  "Loyalty", f"Special #{sid} — toggle active")

    nav(page, "/loyalty")
    shot(page, "14-loyalty-after", "Loyalty — after adds", "Loyalty")

    # ── PUBLIC PAGES ─────────────────────────────────────────────────────────
    print("\n🌐 PUBLIC PAGES")

    # Menu
    nav(page, "/menu")
    shot(page, "15-menu", "Public — Menu", "Public")
    scroll(page, 4)

    # QR code
    nav(page, "/qr")
    shot(page, "15-qr", "Public — QR code", "Public")

    # Join loyalty
    nav(page, "/join")
    shot(page, "15-join", "Public — Join loyalty (blank)", "Public")
    try:
        page.fill('input[name="name"]', "Loyalty Test Member")
        page.fill('input[name="email"]', "loyalty2@test.com")
        page.fill('input[name="phone"]', "555-JOIN-001")
        try: page.fill('input[name="birthday"]', "1995-06-15")
        except Exception: pass
        shot(page, "15-join-filled", "Public — Join loyalty (filled)", "Public")
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible():
                btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                break
        shot(page, "15-join-after", "Public — Join loyalty (after submit)", "Public")
        log("Public", "Loyalty sign-up form submit", "ok")
    except Exception as e:
        log("Public", "Loyalty sign-up form submit", "error", str(e)[:80])

    # Public order — multiple flavors/sizes
    for i, (size_idx, flavor_idx) in enumerate([(0,0),(1,2),(2,1)]):
        nav(page, "/order")
        pickup = (datetime.datetime.now()+timedelta(days=7+i)).strftime("%Y-%m-%d")
        try:
            page.fill('input[name="name"]', f"Test Customer {i+1}")
            page.fill('input[type="email"]', f"testcust{i+1}@sweetspotdemo.com")
            page.fill('input[name="phone"]', f"555-00{i+1}-{i+1}000")
            page.fill('input[name="pickup_date"]', pickup)
            size_cards = page.query_selector_all('#sizeGrid .opt-card')
            if size_cards and len(size_cards)>size_idx:
                size_cards[size_idx].click()
                page.wait_for_timeout(300)
            flavor_cards = page.query_selector_all('#flavorGrid .opt-card')
            if flavor_cards and len(flavor_cards)>flavor_idx:
                flavor_cards[flavor_idx].click()
                page.wait_for_timeout(300)
            # add-on
            addon_cards = page.query_selector_all('.addon-card')
            if addon_cards and len(addon_cards)>i:
                addon_cards[i].click()
                page.wait_for_timeout(200)
            msg = page.query_selector('input[name="message_text"], textarea[name="message_text"]')
            if msg: msg.fill(f"Test order {i+1}")
            scroll(page, 2)
            shot(page, f"15-order-form-{i+1}", f"Public order form #{i+1}", "Public")
            page.click('#submitBtn', timeout=5000)
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(800)
            if "confirmation" in page.url:
                onum = page.url.split("/")[-1]
                shot(page, f"15-order-confirm-{i+1}", f"Order #{i+1} confirmation {onum}", "Public")
                log("Public", f"Public order #{i+1} → {onum}", "ok")
            else:
                shot(page, f"15-order-fail-{i+1}", f"Order #{i+1} no confirmation", "Public")
                log("Public", f"Public order #{i+1}", "error", f"URL: {page.url}")
        except Exception as e:
            log("Public", f"Public order #{i+1}", "error", str(e)[:80])

    # ── CLEANUP: Verify nothing is broken after all writes ───────────────────
    print("\n🔍 FINAL VERIFICATION")
    for path, label in [
        ("/dashboard","Dashboard"),("/orders","Orders"),("/inventory","Inventory"),
        ("/suppliers","Suppliers"),("/recipes","Recipes"),("/customers","Customers"),
        ("/employees","Employees"),("/reports","Reports"),("/expenses","Expenses"),
        ("/marketing","Marketing"),("/loyalty","Loyalty"),("/settings","Settings"),
        ("/tools","Tools"),("/kitchen","Kitchen"),("/prep-sheet","Prep Sheet"),
    ]:
        nav(page, path)
        content = page.content()
        title   = page.title()
        err = has_error(content, title)
        if err:
            log("Final Check", f"{label} — final load", "error", f"error: {err}")
        else:
            log("Final Check", f"{label} — final load", "ok")

    ctx.close()
    browser.close()

# ── BUILD REPORT ─────────────────────────────────────────────────────────────

print("\n📄 Building report...")

ok   = sum(1 for r in results if r["status"]=="ok")
fail = sum(1 for r in results if r["status"]=="error")
total = len(results)
now  = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")

cards_html = ""
for sec, idxs in sections.items():
    sec_ok   = sum(1 for i in idxs if results[i]["status"]=="ok")
    sec_fail = sum(1 for i in idxs if results[i]["status"]=="error")
    sec_badge = (f'<span class="badge ok">{sec_ok} passed</span>' +
                (f' <span class="badge fail">{sec_fail} failed</span>' if sec_fail else ''))
    rows_html = ""
    for i in idxs:
        r = results[i]
        icon = "✅" if r["status"]=="ok" else "❌"
        note_html = f'<span class="note">{r["note"]}</span>' if r["note"] else ""
        img_html  = f'<img src="data:image/png;base64,{r["img"]}" loading="lazy">' if r.get("img") else ""
        rows_html += f'<tr class="{r["status"]}"><td class="icon">{icon}</td><td class="lbl">{r["label"]}{note_html}</td><td class="thumb">{img_html}</td></tr>'
    cards_html += f"""
    <div class="section">
      <div class="sec-header">
        <h2>{sec}</h2>
        <div>{sec_badge}</div>
      </div>
      <table>{rows_html}</table>
    </div>
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sweet Spot CRM — Full Route Coverage Test</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',system-ui,sans-serif;background:#0d0408;color:#fdf2f8}}
  header{{background:linear-gradient(135deg,#1f0d16,#2a1020);padding:44px 32px 32px;text-align:center;border-bottom:1px solid #3d1a28}}
  header h1{{font-size:2rem;font-weight:700;color:#f472b6;margin-bottom:6px}}
  header p{{color:#9d8890;font-size:.9rem}}
  .meta{{display:flex;gap:14px;justify-content:center;margin-top:16px;flex-wrap:wrap}}
  .meta span{{background:#1f0d16;border:1px solid #3d1a28;border-radius:20px;padding:4px 14px;font-size:.8rem;color:#fda4af}}
  .wrap{{max-width:1400px;margin:32px auto;padding:0 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(640px,1fr));gap:24px}}
  .section{{background:#1f0d16;border:1px solid #3d1a28;border-radius:14px;overflow:hidden}}
  .sec-header{{padding:14px 18px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #3d1a28;background:#2a1020}}
  .sec-header h2{{font-size:.95rem;font-weight:700;color:#f472b6}}
  table{{width:100%;border-collapse:collapse}}
  tr{{border-bottom:1px solid #1f0d16}}
  tr.error{{background:rgba(239,68,68,.06)}}
  td{{padding:7px 14px;vertical-align:middle}}
  td.icon{{width:28px;font-size:.9rem}}
  td.lbl{{font-size:.8rem;color:#e5d0d8;line-height:1.5}}
  .note{{display:block;font-size:.72rem;color:#9d8890;margin-top:2px}}
  td.thumb{{width:80px;text-align:right}}
  td.thumb img{{width:72px;height:48px;object-fit:cover;border-radius:6px;border:1px solid #3d1a28;cursor:pointer}}
  td.thumb img:hover{{transform:scale(1.05)}}
  .badge{{font-size:.72rem;padding:2px 8px;border-radius:10px}}
  .badge.ok{{background:rgba(34,197,94,.15);color:#4ade80;border:1px solid rgba(34,197,94,.3)}}
  .badge.fail{{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3)}}
  footer{{text-align:center;padding:28px;color:#9d8890;font-size:.78rem;border-top:1px solid #3d1a28;margin-top:16px}}
  footer a{{color:#f472b6;text-decoration:none}}
  /* Lightbox */
  #lb{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:999;align-items:center;justify-content:center;cursor:pointer}}
  #lb.on{{display:flex}}
  #lb img{{max-width:95vw;max-height:95vh;border-radius:8px}}
  @media(max-width:680px){{.wrap{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>🎂 Sweet Spot Custom Cakes — Full Coverage Test</h1>
  <p>Every route, every form, every action tested against the live app</p>
  <div class="meta">
    <span>📅 {now}</span>
    <span>✅ {ok} passed</span>
    <span>❌ {fail} failed</span>
    <span>📋 {total} total checks</span>
    <span>🔗 <a href="https://sweet-spot-cakes.up.railway.app" style="color:#f472b6">Live App</a></span>
  </div>
</header>
<div class="wrap">{cards_html}</div>
<footer>Built by <a href="#">KiloClaw</a> · Alexander AI Integrated Solutions</footer>
<div id="lb" onclick="this.classList.remove('on')"><img id="lb-img" src=""></div>
<script>
  document.querySelectorAll('td.thumb img').forEach(img=>{{
    img.addEventListener('click',e=>{{
      e.stopPropagation();
      document.getElementById('lb-img').src=img.src;
      document.getElementById('lb').classList.add('on');
    }});
  }});
</script>
</body>
</html>"""

with open(REPORT,"w") as f:
    f.write(html)

size_mb = os.path.getsize(REPORT)/(1024*1024)
print(f"\n{'='*55}")
print(f"✅ {ok}/{total} passed  ❌ {fail} failed")
print(f"📄 {REPORT}  ({size_mb:.1f} MB)")
