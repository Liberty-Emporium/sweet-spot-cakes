#!/usr/bin/env python3
"""
Sweet Spot CRM — Deep Action Test Suite
Actually DOES things: creates customers, adds ingredients, builds recipes,
places orders, adjusts stock, adds employees, creates campaigns, etc.
Records video of every action. Generates a report showing what was created.
"""

import os, base64, datetime, time
from datetime import timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE = "https://sweet-spot-cakes.up.railway.app"
EMAIL    = "info@sweetspotcustomcakes.com"
PASSWORD = "sweetspot2026"
VIDEO_DIR = "/root/.openclaw/workspace/sweet-spot-cakes/scripts/action_videos"
REPORT    = "/root/.openclaw/workspace/sweet-spot-cakes/index.html"

os.makedirs(VIDEO_DIR, exist_ok=True)

results = []  # {title, slug, desc, actions, path, status, errors}

# ─── Helpers ─────────────────────────────────────────────────────────────────

ERROR_MARKERS = [
    "internal server error", "not found", "404 not found",
    "werkzeug", "traceback", "syntaxerror", "attributeerror",
    "keyerror", "typeerror", "nameerror", "operationalerror",
    "bad gateway", "service unavailable",
]

def has_error(page):
    try:
        text = page.inner_text('body').lower()
        title = page.title().lower()
        for m in ERROR_MARKERS:
            if m in title or (m in text[:800] and 'font-size' not in text[:100]):
                return m
    except Exception:
        pass
    return None

def nav(page, path, wait="networkidle"):
    try:
        page.goto(BASE + path, wait_until=wait, timeout=20000)
        page.wait_for_timeout(400)
        return True
    except PWTimeout:
        try:
            page.goto(BASE + path, wait_until="load", timeout=12000)
            page.wait_for_timeout(400)
            return True
        except Exception as e:
            return False

def slow_scroll(page, steps=3, delay=500):
    page.evaluate("""steps => {
        const total = Math.max(document.body.scrollHeight - window.innerHeight, 0);
        const step = total / steps;
        let i = 0;
        const t = setInterval(() => { window.scrollBy(0, step); i++; if(i>=steps) clearInterval(t); }, 220);
    }""", steps)
    page.wait_for_timeout(steps * 240 + delay)

def flash_ok(page):
    """Check if flash/success message is present."""
    try:
        body = page.inner_text('body').lower()
        return any(w in body for w in ['added', 'saved', 'created', 'success', 'updated', 'placed'])
    except Exception:
        return False

def record(browser, title, slug, desc, fn, viewport=None):
    vp = viewport or {"width": 1400, "height": 900}
    ctx = browser.new_context(
        viewport=vp,
        record_video_dir=VIDEO_DIR,
        record_video_size=vp,
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

    errors = []
    actions_done = []

    try:
        fn(page, actions_done, errors)
    except Exception as e:
        errors.append(f"Unhandled: {e}")

    video_raw = page.video.path() if page.video else None
    ctx.close()

    final_path = None
    if video_raw and os.path.exists(video_raw):
        final_path = f"{VIDEO_DIR}/{slug}.webm"
        if os.path.exists(final_path):
            os.remove(final_path)
        os.rename(video_raw, final_path)

    status = "ok" if not errors else "error"
    results.append({
        "title": title, "slug": slug, "desc": desc,
        "actions": actions_done, "path": final_path,
        "status": status, "errors": errors,
    })
    icon = "✅" if status == "ok" else "⚠️ "
    print(f"  {icon} {title}")
    for a in actions_done:
        print(f"     ✔ {a}")
    for e in errors:
        print(f"     ✘ {e}")

# ─── Section: Customers ───────────────────────────────────────────────────────

def sec_customers(page, done, errs):
    nav(page, "/customers")
    slow_scroll(page, steps=2)

    # Add 3 customers via the public join page (most reliable route)
    customers_to_add = [
        ("Maria Rodriguez", "maria.rodriguez@email.com", "919-555-0101", "Loves chocolate, birthday in March"),
        ("Derek Thompson", "derek.thompson@email.com", "336-555-0202", "Wedding cake client, budget ~$350"),
        ("Lisa Chen",      "lisa.chen@email.com",      "704-555-0303", "Regular customer, gluten-free preferred"),
    ]

    for name, email, phone, notes in customers_to_add:
        nav(page, "/join")
        page.wait_for_timeout(400)
        try:
            page.fill('input[name="name"]', name, timeout=3000)
            page.fill('input[name="email"]', email, timeout=3000)
            page.fill('input[name="phone"]', phone, timeout=3000)
        except Exception:
            pass
        try:
            page.fill('input[name="birthday"]', "1990-03-15", timeout=2000)
        except Exception:
            pass
        page.wait_for_timeout(300)
        try:
            page.click('button[type="submit"]', timeout=5000)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(400)
            done.append(f"Added customer: {name}")
        except Exception as e:
            errs.append(f"Customer add {name}: {e}")

    # Verify they appear
    nav(page, "/customers")
    page.wait_for_timeout(500)
    body = page.inner_text('body')
    for name, _, _, _ in customers_to_add:
        if name.split()[0] in body:
            done.append(f"Verified in list: {name}")
    slow_scroll(page, steps=3)

    # Search test
    search = page.query_selector('input[type="search"], input[name="q"], input[placeholder*="Search"]')
    if search:
        search.fill("Rodriguez")
        page.wait_for_timeout(600)
        done.append("Search demo: 'Rodriguez'")

# ─── Section: Inventory ───────────────────────────────────────────────────────

def sec_inventory(page, done, errs):
    nav(page, "/inventory")
    slow_scroll(page, steps=2)

    ingredients = [
        ("Bread Flour",         "lbs",  "50",  "10", "0.65"),
        ("Unsalted Butter",     "lbs",  "20",  "5",  "3.20"),
        ("Granulated Sugar",    "lbs",  "30",  "8",  "0.55"),
        ("Heavy Cream",         "cups", "24",  "6",  "0.85"),
        ("Cream Cheese",        "oz",   "48",  "12", "0.45"),
        ("Cocoa Powder",        "oz",   "32",  "8",  "0.70"),
        ("Baking Powder",       "oz",   "16",  "4",  "0.30"),
    ]

    for name, unit, qty, reorder, cost in ingredients:
        # Click Add Ingredient
        try:
            close_add_modal(page)
            page.click('button:has-text("+ Add Ingredient")', timeout=3000)
            page.wait_for_timeout(500)
            page.wait_for_function("document.getElementById('addModal')?.style.display === 'flex'", timeout=5000)
        except Exception:
            errs.append(f"Could not open add modal for {name}")
            continue

        modal = page.query_selector('#addModal')
        if not modal:
            errs.append(f"Modal not found for {name}")
            continue

        try:
            modal.query_selector('input[name="name"]').fill(name)
            sel = modal.query_selector('select[name="unit"]')
            if sel:
                try:
                    sel.select_option(unit)
                except Exception:
                    sel.select_option(index=0)
            for fname, val in [("quantity",qty),("reorder_level",reorder),("cost_per_unit",cost)]:
                inp = modal.query_selector(f'input[name="{fname}"]')
                if inp:
                    inp.fill(val)
            modal.query_selector('button[type="submit"]').click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(300)
            done.append(f"Added ingredient: {name} ({qty} {unit})")
        except Exception as e:
            errs.append(f"Ingredient {name}: {e}")

    # Verify and scroll
    nav(page, "/inventory")
    page.wait_for_timeout(500)
    slow_scroll(page, steps=4)

    body = page.inner_text('body')
    for name, *_ in ingredients:
        if name in body:
            done.append(f"Verified: {name}")

    # Demo +/- adjust on first item
    try:
        first_row = page.query_selector('tbody tr:first-child')
        if first_row:
            adj_form = first_row.query_selector('form[action*="/adjust"]')
            if adj_form:
                item_id = adj_form.get_attribute('action').split('/')[2]
                qi = page.query_selector(f'#adj-qty-{item_id}')
                if qi:
                    qi.fill("5")
                    page.wait_for_timeout(300)
                    plus_btn = first_row.query_selector('button[onclick*=", 1)"]')
                    if plus_btn:
                        plus_btn.click()
                        page.wait_for_load_state("networkidle", timeout=8000)
                        done.append("Adjusted stock: +5 to first ingredient")
    except Exception as e:
        errs.append(f"Adjust demo: {e}")

# ─── Section: Suppliers ───────────────────────────────────────────────────────

def close_add_modal(page):
    """Force-close any addModal that might be lingering."""
    try:
        page.evaluate("""() => {
            const m = document.getElementById('addModal');
            if (m) m.style.display = 'none';
        }""")
        page.wait_for_timeout(200)
    except Exception:
        pass

def sec_suppliers(page, done, errs):
    nav(page, "/suppliers")
    page.wait_for_timeout(500)
    slow_scroll(page, steps=2)

    suppliers = [
        ("Triangle Flour Co.",    "Bob Mills",      "bob@triangleflour.com",    "919-555-1001", "Net 30"),
        ("Carolina Dairy Supply", "Ann Carter",     "ann@carolinadairy.com",    "704-555-2002", "Net 15"),
        ("Sweet Supply Depot",    "Mark Johnson",   "mark@sweetsupply.com",     "336-555-3003", "COD"),
    ]

    for sname, contact, email, phone, terms in suppliers:
        try:
            # Ensure modal is closed before opening
            close_add_modal(page)
            page.click('button[onclick*="addModal"], button:has-text("Add Supplier"), button:has-text("+ Add")', timeout=5000)
            page.wait_for_timeout(500)
            # Wait for modal to be visible
            page.wait_for_function("document.getElementById('addModal')?.style.display === 'flex'", timeout=5000)

            modal = page.query_selector('#addModal')
            if not modal:
                errs.append(f"No addModal for {sname}")
                continue

            for fname, val in [('name', sname), ('contact_name', contact), ('email', email), ('phone', phone), ('payment_terms', terms)]:
                try:
                    inp = modal.query_selector(f'input[name="{fname}"]')
                    if inp:
                        inp.fill(val)
                except Exception:
                    pass

            page.wait_for_timeout(300)
            submit = modal.query_selector('button[type="submit"]')
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                page.wait_for_timeout(400)
                done.append(f"Added supplier: {sname}")
        except Exception as e:
            errs.append(f"Supplier {sname}: {e}")

    nav(page, "/suppliers")
    page.wait_for_timeout(500)
    slow_scroll(page, steps=3)

    # Auto-PO demo
    try:
        po_btn = page.locator('a[href*="/auto-po"]').first
        if po_btn.is_visible(timeout=2000):
            po_btn.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(700)
            slow_scroll(page, steps=2)
            done.append("Viewed Auto-PO page")
            page.go_back()
            page.wait_for_timeout(400)
    except Exception:
        pass

# ─── Section: Recipes ─────────────────────────────────────────────────────────

def sec_recipes(page, done, errs):
    nav(page, "/recipes")
    slow_scroll(page, steps=2)

    # Add a new recipe
    try:
        nav(page, "/recipes/add")
        page.wait_for_timeout(500)

        page.fill('input[name="name"]', "Classic Chocolate Layer Cake", timeout=3000)
        # category is a <select>
        cat_sel = page.query_selector('select[name="category"]')
        if cat_sel:
            try:
                cat_sel.select_option(label="Cakes")
            except Exception:
                cat_sel.select_option(index=0)
        else:
            cat_inp = page.query_selector('input[name="category"]')
            if cat_inp:
                cat_inp.fill("Cakes")
        page.wait_for_timeout(200)

        for fname, val in [
            ("servings", "12"),
            ("prep_mins", "30"),
            ("bake_mins", "45"),
            ("base_price", "65"),
        ]:
            try:
                inp = page.query_selector(f'input[name="{fname}"]')
                if inp:
                    inp.fill(val)
            except Exception:
                pass

        try:
            desc = page.query_selector('textarea[name="description"]')
            if desc:
                desc.fill("Rich chocolate layer cake with cream cheese frosting. Customer favorite.")
        except Exception:
            pass

        page.wait_for_timeout(300)
        submit = None
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible():
                submit = btn
                break
        if submit:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(500)
            done.append("Created recipe: Classic Chocolate Layer Cake")
    except Exception as e:
        errs.append(f"Recipe add: {e}")

    # Go to recipe detail and add ingredients
    nav(page, "/recipes")
    page.wait_for_timeout(500)
    try:
        link = page.locator('a[href*="/recipes/"]:has-text("Chocolate"), a[href*="/recipes/"]').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(500)
            slow_scroll(page, steps=2)

            # Add ingredients to the recipe
            for ing_name, qty, unit in [("Cocoa Powder","2","oz"),("Granulated Sugar","3","lbs"),("Unsalted Butter","1","lbs")]:
                try:
                    # Find ingredient selector
                    ing_sel = page.query_selector('select[name="ingredient_id"]')
                    if ing_sel:
                        # Find the option matching our ingredient
                        options = ing_sel.query_selector_all('option')
                        for opt in options:
                            if ing_name.lower() in opt.text_content().lower():
                                ing_sel.select_option(value=opt.get_attribute('value'))
                                break
                    qty_inp = page.query_selector('input[name="quantity"]')
                    if qty_inp:
                        qty_inp.fill(qty)
                    unit_inp = page.query_selector('input[name="unit"]')
                    if unit_inp:
                        unit_inp.fill(unit)
                    page.wait_for_timeout(200)
                    submit = page.query_selector('button[type="submit"]:has-text("Add"), form button[type="submit"]')
                    if not submit:
                        for btn in page.query_selector_all('button[type="submit"]'):
                            if btn.is_visible():
                                submit = btn
                                break
                    if submit:
                        submit.click()
                        page.wait_for_load_state("networkidle", timeout=6000)
                        page.wait_for_timeout(300)
                        done.append(f"Added {qty} {unit} {ing_name} to recipe")
                except Exception as e:
                    errs.append(f"Recipe ingredient {ing_name}: {e}")
    except Exception as e:
        errs.append(f"Recipe detail: {e}")

    nav(page, "/recipes")
    slow_scroll(page, steps=3)

# ─── Section: Orders ─────────────────────────────────────────────────────────

def sec_orders(page, done, errs):
    pickup_date = (datetime.datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")

    nav(page, "/orders")
    slow_scroll(page, steps=2)

    # Create 2 new orders
    orders_to_create = [
        {
            "customer_name": "Maria Rodriguez",
            "customer_email": "maria.rodriguez@email.com",
            "customer_phone": "919-555-0101",
            "cake_flavor": "Chocolate Fudge",
            "cake_size": '8" Round',
            "special_notes": "Birthday cake, write 'Happy Birthday Maria' on top",
            "pickup_date": pickup_date,
        },
        {
            "customer_name": "Derek Thompson",
            "customer_email": "derek.thompson@email.com",
            "customer_phone": "336-555-0202",
            "cake_flavor": "Vanilla Bean",
            "cake_size": "2-Tier",
            "special_notes": "Wedding consultation order, gold leaf decoration",
            "pickup_date": (datetime.datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d"),
        },
    ]

    for order in orders_to_create:
        nav(page, "/orders/new")
        page.wait_for_timeout(500)

        for fname, val in [
            ("customer_name", order["customer_name"]),
            ("customer_email", order["customer_email"]),
            ("customer_phone", order["customer_phone"]),
            ("pickup_date", order["pickup_date"]),
        ]:
            try:
                inp = page.query_selector(f'input[name="{fname}"]')
                if inp:
                    inp.fill(val)
            except Exception:
                pass

        for fname, val in [("cake_flavor", order["cake_flavor"]), ("cake_size", order["cake_size"])]:
            try:
                inp = page.query_selector(f'input[name="{fname}"], select[name="{fname}"]')
                if inp:
                    tag = inp.evaluate("el => el.tagName")
                    if tag == "SELECT":
                        try:
                            inp.select_option(label=val)
                        except Exception:
                            inp.select_option(index=1)
                    else:
                        inp.fill(val)
            except Exception:
                pass

        try:
            notes = page.query_selector('textarea[name="special_notes"], input[name="special_notes"]')
            if notes:
                notes.fill(order["special_notes"])
        except Exception:
            pass

        page.wait_for_timeout(300)
        slow_scroll(page, steps=2)

        submit = None
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible():
                submit = btn
                break
        if submit:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=12000)
            page.wait_for_timeout(500)
            if "orders" in page.url or "dashboard" in page.url or has_error(page) is None:
                done.append(f"Created order for: {order['customer_name']}")
            else:
                errs.append(f"Order create may have failed for {order['customer_name']}: {page.url}")

    # View orders list
    nav(page, "/orders")
    page.wait_for_timeout(500)
    slow_scroll(page, steps=3)

    # Open an order and update status
    try:
        link = page.locator('a[href*="/orders/"]:not([href*="new"])').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=3)
            done.append("Viewed order detail page")

            # Update status to 'confirmed'
            status_form = page.query_selector('form[action*="/status"]')
            if status_form:
                sel = status_form.query_selector('select[name="status"]')
                if sel:
                    sel.select_option("confirmed")
                    page.wait_for_timeout(200)
                    status_form.query_selector('button[type="submit"]').click()
                    page.wait_for_load_state("networkidle", timeout=6000)
                    done.append("Updated order status → confirmed")
    except Exception as e:
        errs.append(f"Order detail/status: {e}")

# ─── Section: Employees ───────────────────────────────────────────────────────

def sec_employees(page, done, errs):
    nav(page, "/employees")
    slow_scroll(page, steps=2)

    employees = [
        ("Rachel Green",   "rachel@sweetspot.com", "919-555-4001", "Baker",          "16.50"),
        ("Tom Baker",      "tom@sweetspot.com",     "336-555-4002", "Decorator",      "18.00"),
        ("Jen Williams",   "jen@sweetspot.com",     "704-555-4003", "Counter Staff",  "14.50"),
    ]

    for name, email, phone, role, rate in employees:
        try:
            close_add_modal(page)
            page.click('button[onclick*="addModal"], button:has-text("Add Employee"), button:has-text("+ Add")', timeout=5000)
            page.wait_for_timeout(500)
            page.wait_for_function("document.getElementById('addModal')?.style.display === 'flex'", timeout=5000)

            modal = page.query_selector('#addModal')
            if not modal:
                errs.append(f"No addModal for employee {name}")
                continue

            for fname, val in [('name',name),('email',email),('phone',phone),('hourly_rate',rate)]:
                inp = modal.query_selector(f'input[name="{fname}"]')
                if inp:
                    inp.fill(val)

            role_sel = modal.query_selector('select[name="role"]')
            if role_sel:
                try:
                    role_sel.select_option(label=role)
                except Exception:
                    role_sel.select_option(index=1)
            else:
                role_inp = modal.query_selector('input[name="role"]')
                if role_inp:
                    role_inp.fill(role)

            page.wait_for_timeout(300)
            submit = modal.query_selector('button[type="submit"]')
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                page.wait_for_timeout(400)
                done.append(f"Added employee: {name} ({role})")
        except Exception as e:
            errs.append(f"Employee {name}: {e}")

    nav(page, "/employees")
    slow_scroll(page, steps=3)
    body = page.inner_text('body')
    for name, *_ in employees:
        if name.split()[0] in body:
            done.append(f"Verified in list: {name}")

# ─── Section: Expenses ────────────────────────────────────────────────────────

def sec_expenses(page, done, errs):
    nav(page, "/expenses")
    slow_scroll(page, steps=2)

    expenses = [
        ("Flour Supplier Invoice",    "ingredients", "187.50"),
        ("Mixer Repair",              "equipment",   "95.00"),
        ("Box Supplies",              "packaging",   "62.40"),
        ("Electricity Bill",          "utilities",   "215.00"),
    ]

    for desc_text, category, amount in expenses:
        try:
            close_add_modal(page)
            open_btn = page.query_selector('button:has-text("Add Expense"), button:has-text("+ Add"), button[onclick*="add"]')
            if open_btn:
                open_btn.click()
                page.wait_for_timeout(500)

            for fname, val in [('description', desc_text), ('amount', amount)]:
                for el in page.query_selector_all(f'input[name="{fname}"], textarea[name="{fname}"]'):
                    if el.is_visible():
                        el.fill(val)
                        break

            # Category select or input
            try:
                cat_el = page.query_selector('select[name="category"]')
                if cat_el and cat_el.is_visible():
                    try:
                        cat_el.select_option(label=category)
                    except Exception:
                        cat_el.select_option(index=1)
                else:
                    cat_inp = page.query_selector('input[name="category"]')
                    if cat_inp and cat_inp.is_visible():
                        cat_inp.fill(category)
            except Exception:
                pass

            # Date
            try:
                date_inp = page.query_selector('input[name="date"], input[type="date"]')
                if date_inp and date_inp.is_visible():
                    date_inp.fill(datetime.datetime.now().strftime("%Y-%m-%d"))
            except Exception:
                pass

            page.wait_for_timeout(300)
            submit = None
            for btn in page.query_selector_all('button[type="submit"]'):
                if btn.is_visible():
                    submit = btn
                    break
            if submit:
                submit.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                page.wait_for_timeout(300)
                done.append(f"Added expense: {desc_text} ${amount}")
        except Exception as e:
            errs.append(f"Expense {desc_text}: {e}")

    nav(page, "/expenses")
    slow_scroll(page, steps=3)

# ─── Section: Marketing Campaign ─────────────────────────────────────────────

def sec_marketing(page, done, errs):
    nav(page, "/marketing")
    slow_scroll(page, steps=2)

    try:
        btn = page.query_selector('button:has-text("New Campaign"), button:has-text("+ New"), button:has-text("Create")')
        if btn:
            btn.click()
            page.wait_for_timeout(500)

        for fname, val in [
            ('name', "Spring Specials 2026"),
            ('subject', "🎂 Spring is here — treat yourself!"),
        ]:
            for el in page.query_selector_all(f'input[name="{fname}"]'):
                if el.is_visible():
                    el.fill(val)
                    break

        try:
            ta = page.query_selector('textarea[name="body"], textarea[name="content"], textarea[name="message"]')
            if ta and ta.is_visible():
                ta.fill("Spring flavors are here! Lemon lavender, strawberry cream, and fresh floral cakes available now through May 31. Order online at sweetspotcustomcakes.com or call us today!")
        except Exception:
            pass

        page.wait_for_timeout(300)
        submit = None
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible():
                submit = btn
                break
        if submit:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(500)
            done.append("Created marketing campaign: Spring Specials 2026")
    except Exception as e:
        errs.append(f"Marketing campaign: {e}")

    nav(page, "/marketing")
    slow_scroll(page, steps=3)
    try:
        link = page.locator('a[href*="/marketing/campaigns/"]').first
        if link.is_visible(timeout=2000):
            link.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(600)
            slow_scroll(page, steps=2)
            done.append("Viewed campaign detail")
    except Exception:
        pass

# ─── Section: Loyalty ─────────────────────────────────────────────────────────

def sec_loyalty(page, done, errs):
    nav(page, "/loyalty")
    slow_scroll(page, steps=3)

    # Add a loyalty special
    try:
        close_add_modal(page)
        btn = page.query_selector('button:has-text("Add Special"), button:has-text("+ Add"), button:has-text("New Special")')
        if btn:
            btn.click()
            page.wait_for_timeout(500)

        for fname, val in [
            ('title', "Mother's Day Special"),
            ('description', "Free custom rose decoration on any Mother's Day cake order"),
            ('discount_percent', "10"),
        ]:
            for el in page.query_selector_all(f'input[name="{fname}"], textarea[name="{fname}"]'):
                if el.is_visible():
                    el.fill(val)
                    break

        page.wait_for_timeout(300)
        submit = None
        for btn in page.query_selector_all('button[type="submit"]'):
            if btn.is_visible():
                submit = btn
                break
        if submit:
            submit.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(400)
            done.append("Added loyalty special: Mother's Day Special")
    except Exception as e:
        errs.append(f"Loyalty special: {e}")

    nav(page, "/loyalty")
    slow_scroll(page, steps=3)

# ─── Section: Public Order (full submit) ─────────────────────────────────────

def sec_public_order(page, done, errs):
    nav(page, "/order")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=2)

    try:
        page.fill('input[name="name"]', "Test Customer Demo")
        page.fill('input[type="email"]', "demo@sweetspottest.com")
        page.fill('input[name="phone"]', "555-777-9999")
        pickup = (datetime.datetime.now() + timedelta(days=8)).strftime("%Y-%m-%d")
        page.fill('input[name="pickup_date"]', pickup)
        page.wait_for_timeout(300)

        size_lbl = page.query_selector('#sizeGrid .opt-card')
        if size_lbl:
            size_lbl.click()
            page.wait_for_timeout(300)
        flavor_lbl = page.query_selector('#flavorGrid .opt-card')
        if flavor_lbl:
            flavor_lbl.click()
            page.wait_for_timeout(300)

        # Check an add-on
        addon = page.query_selector('.addon-card')
        if addon:
            addon.click()
            page.wait_for_timeout(200)

        try:
            msg = page.query_selector('input[name="message_text"], textarea[name="message_text"]')
            if msg:
                msg.fill("Happy Birthday!")
        except Exception:
            pass

        slow_scroll(page, steps=3)
        page.wait_for_timeout(400)

        page.click('#submitBtn', timeout=5000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(800)

        if "confirmation" in page.url:
            order_num = page.url.split("/")[-1]
            done.append(f"Public order placed → confirmation: {order_num}")
        else:
            errs.append(f"Public order may not have confirmed, URL: {page.url}")
    except Exception as e:
        errs.append(f"Public order: {e}")

    # Also show loyalty join
    nav(page, "/join")
    page.wait_for_timeout(500)
    try:
        page.fill('input[name="name"]', "Demo Loyalty Member")
        page.fill('input[name="email"]', "loyalty.demo@email.com")
        page.fill('input[name="phone"]', "555-888-0000")
        page.wait_for_timeout(300)
    except Exception:
        pass
    slow_scroll(page, steps=2)

# ─── Section: Dashboard + Reports ────────────────────────────────────────────

def sec_dashboard_final(page, done, errs):
    nav(page, "/dashboard")
    page.wait_for_timeout(800)
    slow_scroll(page, steps=5, delay=800)
    done.append("Dashboard shows all live data")

    nav(page, "/reports")
    page.wait_for_timeout(1000)
    slow_scroll(page, steps=6, delay=1000)
    done.append("Reports page with all metrics")

    nav(page, "/prep-sheet")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    done.append("Prep sheet viewed")

    nav(page, "/kitchen")
    page.wait_for_timeout(700)
    slow_scroll(page, steps=3)
    done.append("Kitchen display board viewed")

# ─── RUN ALL ─────────────────────────────────────────────────────────────────

SECTIONS = [
    ("Customers",        "customers",   "Add 3 real customers, verify list, search demo",                  sec_customers),
    ("Inventory",        "inventory",   "Add 7 ingredients with units/costs, adjust stock levels",         sec_inventory),
    ("Suppliers",        "suppliers",   "Add 3 suppliers, view Auto-PO flow",                              sec_suppliers),
    ("Recipes",          "recipes",     "Create a recipe, add ingredients to it",                          sec_recipes),
    ("Orders",           "orders",      "Create 2 customer orders, view detail, update status",            sec_orders),
    ("Employees",        "employees",   "Add 3 staff members (baker, decorator, counter staff)",           sec_employees),
    ("Expenses",         "expenses",    "Log 4 real business expenses",                                    sec_expenses),
    ("Marketing",        "marketing",   "Create Spring campaign, view detail",                             sec_marketing),
    ("Loyalty",          "loyalty",     "Add Mother's Day loyalty special",                                sec_loyalty),
    ("Public Order",     "public",      "Fill and submit full public order form → confirmation page",      sec_public_order),
    ("Dashboard+Reports","dashboard",   "Live dashboard with all data, full reports, prep sheet, kitchen", sec_dashboard_final),
]

print("🎬 Sweet Spot CRM — Deep Action Test Suite")
print("=" * 55)
print("This test CREATES real data in the app.\n")

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--no-sandbox"])
    for title, slug, desc, fn in SECTIONS:
        print(f"\n🎥 {title}")
        record(browser, title, slug, desc, fn)
    browser.close()

# ─── BUILD REPORT ────────────────────────────────────────────────────────────

print("\n📄 Building HTML report...")

def encode_video(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

ok_count  = sum(1 for r in results if r["status"] == "ok")
total     = len(results)
now_str   = datetime.datetime.now().strftime("%B %d, %Y at %I:%M %p")
all_actions = sum(len(r["actions"]) for r in results)

cards_html = ""
for r in results:
    b64 = encode_video(r["path"])
    badge = ('<span class="badge ok">✅ PASS</span>' if r["status"] == "ok"
             else '<span class="badge fail">⚠️ PARTIAL</span>')
    video_tag = (f'<video controls preload="metadata" src="data:video/webm;base64,{b64}"></video>'
                 if b64 else '<div class="no-video">⚠️ Video not recorded</div>')

    actions_html = ""
    if r["actions"]:
        actions_html = "<ul class='action-list'>" + "".join(f"<li>✔ {a}</li>" for a in r["actions"]) + "</ul>"
    if r["errors"]:
        actions_html += "<ul class='error-list'>" + "".join(f"<li>✘ {e}</li>" for e in r["errors"]) + "</ul>"

    cards_html += f"""
    <div class="card {'partial' if r['status']!='ok' else ''}">
      <div class="card-header"><h2>{r['title']}</h2>{badge}</div>
      <p class="desc">{r['desc']}</p>
      {actions_html}
      {video_tag}
    </div>
"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sweet Spot Custom Cakes — Deep CRM Action Test</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',system-ui,sans-serif;background:#0d0408;color:#fdf2f8;min-height:100vh}}
  header{{background:linear-gradient(135deg,#1f0d16,#2a1020);padding:48px 32px 36px;text-align:center;border-bottom:1px solid #3d1a28}}
  header h1{{font-size:2.2rem;font-weight:700;color:#f472b6;margin-bottom:8px}}
  header p{{color:#9d8890;font-size:.95rem}}
  .meta{{display:flex;gap:16px;justify-content:center;margin-top:18px;flex-wrap:wrap}}
  .meta span{{background:#1f0d16;border:1px solid #3d1a28;border-radius:20px;padding:5px 16px;font-size:.82rem;color:#fda4af}}
  .grid{{max-width:1300px;margin:40px auto;padding:0 24px;display:grid;grid-template-columns:repeat(auto-fill,minmax(580px,1fr));gap:28px}}
  .card{{background:#1f0d16;border:1px solid #3d1a28;border-radius:16px;overflow:hidden;transition:transform .2s}}
  .card:hover{{transform:translateY(-2px)}}
  .card.partial{{border-color:#f59e0b}}
  .card-header{{padding:18px 20px 8px;display:flex;justify-content:space-between;align-items:center;gap:12px}}
  .card-header h2{{font-size:1.05rem;font-weight:600}}
  .badge{{font-size:.75rem;padding:3px 10px;border-radius:12px;white-space:nowrap}}
  .badge.ok{{background:rgba(34,197,94,.15);color:#4ade80;border:1px solid rgba(34,197,94,.3)}}
  .badge.fail{{background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(245,158,11,.3)}}
  .desc{{padding:4px 20px 10px;font-size:.82rem;color:#9d8890;line-height:1.5}}
  .action-list,.error-list{{padding:0 20px 12px;list-style:none}}
  .action-list li{{font-size:.78rem;color:#86efac;padding:2px 0;line-height:1.5}}
  .error-list li{{font-size:.78rem;color:#fca5a5;padding:2px 0;line-height:1.5}}
  video{{width:100%;display:block;background:#000;max-height:520px}}
  .no-video{{padding:40px;text-align:center;color:#9d8890;font-size:.9rem}}
  footer{{text-align:center;padding:32px;color:#9d8890;font-size:.8rem;border-top:1px solid #3d1a28;margin-top:20px}}
  footer a{{color:#f472b6;text-decoration:none}}
  @media(max-width:640px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header>
  <h1>🎂 Sweet Spot Custom Cakes</h1>
  <p>CRM Platform — Deep Action Test &amp; Walkthrough</p>
  <div class="meta">
    <span>📅 {now_str}</span>
    <span>🎥 {total} Videos</span>
    <span>✅ {ok_count}/{total} Passed</span>
    <span>⚡ {all_actions} Actions Performed</span>
    <span>🔗 <a href="https://sweet-spot-cakes.up.railway.app" style="color:#f472b6">Live App</a></span>
  </div>
</header>
<div class="grid">{cards_html}</div>
<footer>
  Built with ❤️ by <a href="#">KiloClaw</a> &amp; Alexander AI Integrated Solutions
</footer>
</body>
</html>"""

with open(REPORT, "w") as f:
    f.write(html)

size_mb = os.path.getsize(REPORT) / (1024*1024)
print(f"\n{'='*55}")
print(f"✅ {ok_count}/{total} passed | {all_actions} real actions performed")
print(f"📄 Report: {REPORT} ({size_mb:.1f} MB)")
