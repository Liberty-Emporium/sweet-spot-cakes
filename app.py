import os, json, sqlite3, secrets, hashlib, datetime, threading, time
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, jsonify, g)
import bcrypt
import stripe

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_DATA_DIR = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', os.path.dirname(__file__))
DB_PATH   = os.path.join(_DATA_DIR, 'sweetspot.db')
os.makedirs(_DATA_DIR, exist_ok=True)

_SK = os.environ.get('SECRET_KEY', '')
if not _SK:
    _KF = os.path.join(_DATA_DIR, '.secret_key')
    if os.path.exists(_KF):
        with open(_KF) as f: _SK = f.read().strip()
    if not _SK:
        _SK = secrets.token_hex(32)
        with open(_KF, 'w') as f: f.write(_SK)
app.secret_key = _SK

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PK      = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WH      = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

BAKERY_NAME    = os.environ.get('BAKERY_NAME', 'Sweet Spot Custom Cakes')
ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL', 'admin@sweetspotcakes.com')

# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS users (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        email     TEXT UNIQUE NOT NULL,
        password  TEXT NOT NULL,
        name      TEXT DEFAULT '',
        role      TEXT DEFAULT 'staff',  -- admin, manager, staff
        pin       TEXT DEFAULT '',       -- 4-digit clock-in PIN
        hourly_rate REAL DEFAULT 15.0,
        active    INTEGER DEFAULT 1,
        created   TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS employees (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        email       TEXT DEFAULT '',
        phone       TEXT DEFAULT '',
        role        TEXT DEFAULT 'Baker',
        hourly_rate REAL DEFAULT 15.0,
        pin         TEXT DEFAULT '',
        active      INTEGER DEFAULT 1,
        notes       TEXT DEFAULT '',
        created     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS timesheets (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        clock_in    TEXT NOT NULL,
        clock_out   TEXT,
        break_mins  INTEGER DEFAULT 0,
        notes       TEXT DEFAULT '',
        approved    INTEGER DEFAULT 0,
        created     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(employee_id) REFERENCES employees(id)
    );
    CREATE TABLE IF NOT EXISTS suppliers (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT NOT NULL,
        contact TEXT DEFAULT '',
        email   TEXT DEFAULT '',
        phone   TEXT DEFAULT '',
        address TEXT DEFAULT '',
        notes   TEXT DEFAULT '',
        active  INTEGER DEFAULT 1,
        created TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS ingredients (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        unit          TEXT DEFAULT 'lbs',
        quantity      REAL DEFAULT 0,
        reorder_level REAL DEFAULT 5,
        cost_per_unit REAL DEFAULT 0,
        supplier_id   INTEGER,
        location      TEXT DEFAULT '',
        notes         TEXT DEFAULT '',
        created       TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    );
    CREATE TABLE IF NOT EXISTS purchase_orders (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        supplier_id INTEGER NOT NULL,
        status      TEXT DEFAULT 'pending',  -- pending, ordered, received, cancelled
        total       REAL DEFAULT 0,
        notes       TEXT DEFAULT '',
        ordered_at  TEXT,
        received_at TEXT,
        created     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    );
    CREATE TABLE IF NOT EXISTS po_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        po_id       INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL,
        quantity    REAL NOT NULL,
        unit_cost   REAL NOT NULL,
        FOREIGN KEY(po_id) REFERENCES purchase_orders(id),
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
    );
    CREATE TABLE IF NOT EXISTS recipes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        category    TEXT DEFAULT 'Cake',
        description TEXT DEFAULT '',
        servings    INTEGER DEFAULT 1,
        prep_mins   INTEGER DEFAULT 60,
        bake_mins   INTEGER DEFAULT 45,
        base_price  REAL DEFAULT 0,
        active      INTEGER DEFAULT 1,
        image_url   TEXT DEFAULT '',
        created     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id     INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL,
        quantity      REAL NOT NULL,
        unit          TEXT DEFAULT '',
        FOREIGN KEY(recipe_id) REFERENCES recipes(id),
        FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
    );
    CREATE TABLE IF NOT EXISTS customers (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        name      TEXT NOT NULL,
        email     TEXT DEFAULT '',
        phone     TEXT DEFAULT '',
        address   TEXT DEFAULT '',
        birthday  TEXT DEFAULT '',
        notes     TEXT DEFAULT '',
        stripe_id TEXT DEFAULT '',
        created   TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS orders (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number    TEXT UNIQUE NOT NULL,
        customer_id     INTEGER,
        customer_name   TEXT NOT NULL,
        customer_email  TEXT DEFAULT '',
        customer_phone  TEXT DEFAULT '',
        type            TEXT DEFAULT 'custom',  -- custom, walkin, online
        status          TEXT DEFAULT 'pending', -- pending, confirmed, in_production, ready, delivered, cancelled
        pickup_date     TEXT,
        pickup_time     TEXT,
        special_notes   TEXT DEFAULT '',
        subtotal        REAL DEFAULT 0,
        tax             REAL DEFAULT 0,
        discount        REAL DEFAULT 0,
        total           REAL DEFAULT 0,
        deposit_paid    REAL DEFAULT 0,
        balance_due     REAL DEFAULT 0,
        stripe_pi       TEXT DEFAULT '',
        paid_in_full    INTEGER DEFAULT 0,
        created         TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id    INTEGER NOT NULL,
        recipe_id   INTEGER,
        name        TEXT NOT NULL,
        description TEXT DEFAULT '',
        quantity    INTEGER DEFAULT 1,
        unit_price  REAL NOT NULL,
        total       REAL NOT NULL,
        customizations TEXT DEFAULT '',
        FOREIGN KEY(order_id) REFERENCES orders(id),
        FOREIGN KEY(recipe_id) REFERENCES recipes(id)
    );
    CREATE TABLE IF NOT EXISTS receipts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id    INTEGER NOT NULL,
        amount      REAL NOT NULL,
        method      TEXT DEFAULT 'stripe', -- stripe, cash, card, check
        stripe_pi   TEXT DEFAULT '',
        notes       TEXT DEFAULT '',
        created     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(order_id) REFERENCES orders(id)
    );
    CREATE TABLE IF NOT EXISTS expenses (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        category    TEXT DEFAULT 'Supplies',
        description TEXT NOT NULL,
        amount      REAL NOT NULL,
        supplier_id INTEGER,
        receipt_url TEXT DEFAULT '',
        date        TEXT DEFAULT (date('now')),
        created     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    );
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    CREATE INDEX IF NOT EXISTS idx_ts_employee ON timesheets(employee_id);
    CREATE INDEX IF NOT EXISTS idx_oi_order ON order_items(order_id);
    ''')
    db.commit()

    # Seed admin user
    admin_pw = os.environ.get('ADMIN_PASSWORD', 'sweetspot2026')
    hashed = bcrypt.hashpw(admin_pw.encode(), bcrypt.gensalt()).decode()
    db.execute('''INSERT OR IGNORE INTO users(email,password,name,role)
                  VALUES(?,?,?,?)''', (ADMIN_EMAIL, hashed, 'Admin', 'admin'))
    db.commit()
    db.close()

init_db()

# ── Auth ──────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('role') not in ('admin', 'manager'):
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*a, **kw)
    return dec

def gen_order_number():
    now = datetime.datetime.now()
    return f"SS-{now.strftime('%y%m%d')}-{secrets.token_hex(2).upper()}"

def tax_rate():
    return float(os.environ.get('TAX_RATE', '0.07'))

# ── Health ────────────────────────────────────────────────────────────────────
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'app': BAKERY_NAME})

# ── Auth routes ───────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        pw    = request.form.get('password', '')
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email=? AND active=1', (email,)).fetchone()
        if not user or not bcrypt.checkpw(pw.encode(), user['password'].encode()):
            flash('Invalid email or password.', 'error')
            return render_template('login.html', bakery=BAKERY_NAME)
        session['user_id'] = user['id']
        session['name']    = user['name']
        session['role']    = user['role']
        session['email']   = user['email']
        session.permanent  = True
        return redirect(url_for('dashboard'))
    return render_template('login.html', bakery=BAKERY_NAME)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html', bakery=BAKERY_NAME)

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

    stats = {
        'orders_today':   db.execute("SELECT COUNT(*) FROM orders WHERE date(created)=?", (today,)).fetchone()[0],
        'orders_pending': db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'", ).fetchone()[0],
        'orders_ready':   db.execute("SELECT COUNT(*) FROM orders WHERE status='ready'").fetchone()[0],
        'revenue_week':   db.execute("SELECT COALESCE(SUM(amount),0) FROM receipts WHERE date(created)>=?", (week_ago,)).fetchone()[0],
        'low_stock':      db.execute("SELECT COUNT(*) FROM ingredients WHERE quantity<=reorder_level AND quantity>=0").fetchone()[0],
        'employees_in':   db.execute("SELECT COUNT(*) FROM timesheets WHERE clock_out IS NULL").fetchone()[0],
    }
    recent_orders = db.execute(
        "SELECT * FROM orders ORDER BY created DESC LIMIT 8"
    ).fetchall()
    upcoming = db.execute(
        "SELECT * FROM orders WHERE status NOT IN ('delivered','cancelled') AND pickup_date>=? ORDER BY pickup_date, pickup_time LIMIT 6",
        (today,)
    ).fetchall()
    low_stock_items = db.execute(
        "SELECT * FROM ingredients WHERE quantity<=reorder_level ORDER BY quantity ASC LIMIT 6"
    ).fetchall()
    return render_template('dashboard.html', stats=stats, recent_orders=recent_orders,
                           upcoming=upcoming, low_stock=low_stock_items,
                           bakery=BAKERY_NAME, user=session)

# ── Orders ────────────────────────────────────────────────────────────────────
@app.route('/orders')
@login_required
def orders():
    db = get_db()
    status = request.args.get('status', '')
    q = request.args.get('q', '')
    sql = "SELECT o.*, c.name as cname FROM orders o LEFT JOIN customers c ON o.customer_id=c.id WHERE 1=1"
    params = []
    if status: sql += " AND o.status=?"; params.append(status)
    if q:      sql += " AND (o.customer_name LIKE ? OR o.order_number LIKE ?)"; params += [f'%{q}%', f'%{q}%']
    sql += " ORDER BY o.created DESC LIMIT 100"
    all_orders = db.execute(sql, params).fetchall()
    return render_template('orders.html', orders=all_orders, status=status, q=q, bakery=BAKERY_NAME)

@app.route('/orders/new', methods=['GET', 'POST'])
@login_required
def new_order():
    db = get_db()
    if request.method == 'POST':
        cname  = request.form.get('customer_name', '').strip()
        cemail = request.form.get('customer_email', '').strip()
        cphone = request.form.get('customer_phone', '').strip()
        pickup_date = request.form.get('pickup_date', '')
        pickup_time = request.form.get('pickup_time', '')
        notes  = request.form.get('special_notes', '')
        otype  = request.form.get('type', 'custom')

        # Find or create customer
        cust = db.execute('SELECT id FROM customers WHERE email=? AND email!=?', (cemail, '')).fetchone()
        cust_id = None
        if cust:
            cust_id = cust['id']
        elif cemail:
            cur = db.execute('INSERT INTO customers(name,email,phone) VALUES(?,?,?)', (cname, cemail, cphone))
            cust_id = cur.lastrowid

        onum = gen_order_number()
        cur = db.execute('''INSERT INTO orders(order_number,customer_id,customer_name,customer_email,
                            customer_phone,type,pickup_date,pickup_time,special_notes)
                            VALUES(?,?,?,?,?,?,?,?,?)''',
                         (onum, cust_id, cname, cemail, cphone, otype, pickup_date, pickup_time, notes))
        db.commit()
        flash(f'Order {onum} created!', 'success')
        return redirect(url_for('order_detail', order_id=cur.lastrowid))
    recipes = db.execute("SELECT id,name,category,base_price FROM recipes WHERE active=1 ORDER BY name").fetchall()
    customers = db.execute("SELECT id,name,email,phone FROM customers ORDER BY name LIMIT 100").fetchall()
    return render_template('order_form.html', recipes=recipes, customers=customers, bakery=BAKERY_NAME)

@app.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: flash('Order not found.', 'error'); return redirect(url_for('orders'))
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    receipts = db.execute("SELECT * FROM receipts WHERE order_id=? ORDER BY created", (order_id,)).fetchall()
    return render_template('order_detail.html', order=order, items=items,
                           receipts=receipts, stripe_pk=STRIPE_PK, bakery=BAKERY_NAME)

@app.route('/orders/<int:order_id>/add-item', methods=['POST'])
@login_required
def order_add_item(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: return jsonify({'error': 'not found'}), 404
    name   = request.form.get('name', '').strip()
    qty    = int(request.form.get('quantity', 1))
    price  = float(request.form.get('unit_price', 0))
    custom = request.form.get('customizations', '')
    recipe_id = request.form.get('recipe_id') or None
    total  = qty * price
    db.execute('''INSERT INTO order_items(order_id,recipe_id,name,quantity,unit_price,total,customizations)
                  VALUES(?,?,?,?,?,?,?)''', (order_id, recipe_id, name, qty, price, total, custom))
    # Recalculate totals
    subtotal = db.execute("SELECT COALESCE(SUM(total),0) FROM order_items WHERE order_id=?", (order_id,)).fetchone()[0]
    tax = round(subtotal * tax_rate(), 2)
    discount = order['discount'] or 0
    grand = round(subtotal + tax - discount, 2)
    balance = round(grand - (order['deposit_paid'] or 0), 2)
    db.execute("UPDATE orders SET subtotal=?,tax=?,total=?,balance_due=? WHERE id=?",
               (subtotal, tax, grand, balance, order_id))
    db.commit()
    flash('Item added.', 'success')
    return redirect(url_for('order_detail', order_id=order_id))

@app.route('/orders/<int:order_id>/status', methods=['POST'])
@login_required
def order_status(order_id):
    db = get_db()
    new_status = request.form.get('status', '')
    valid = ['pending','confirmed','in_production','ready','delivered','cancelled']
    if new_status in valid:
        db.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
        db.commit()
    return redirect(url_for('order_detail', order_id=order_id))

# ── Stripe Checkout ───────────────────────────────────────────────────────────
@app.route('/orders/<int:order_id>/checkout', methods=['POST'])
@login_required
def order_checkout(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: return jsonify({'error': 'not found'}), 404
    if not stripe.api_key:
        flash('Stripe not configured. Add STRIPE_SECRET_KEY to Railway env vars.', 'error')
        return redirect(url_for('order_detail', order_id=order_id))
    amount_type = request.form.get('amount_type', 'balance')  # balance or deposit
    if amount_type == 'deposit':
        amount_cents = int((order['total'] * 0.5) * 100)
        label = '50% Deposit'
    else:
        amount_cents = int(order['balance_due'] * 100)
        label = 'Balance Due'
    if amount_cents <= 0:
        flash('Nothing to charge!', 'info')
        return redirect(url_for('order_detail', order_id=order_id))
    try:
        base = request.host_url.rstrip('/')
        session_obj = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {'name': f'{BAKERY_NAME} — Order {order["order_number"]} ({label})'},
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }],
            mode='payment',
            customer_email=order['customer_email'] or None,
            success_url=f'{base}/orders/{order_id}/payment-success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{base}/orders/{order_id}',
            metadata={'order_id': str(order_id), 'order_number': order['order_number']}
        )
        return redirect(session_obj.url)
    except Exception as e:
        flash(f'Stripe error: {e}', 'error')
        return redirect(url_for('order_detail', order_id=order_id))

@app.route('/orders/<int:order_id>/payment-success')
@login_required
def payment_success(order_id):
    db = get_db()
    sid = request.args.get('session_id', '')
    if sid and stripe.api_key:
        try:
            cs = stripe.checkout.Session.retrieve(sid)
            amount = cs.amount_total / 100
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            db.execute("INSERT INTO receipts(order_id,amount,method,stripe_pi,notes) VALUES(?,?,?,?,?)",
                       (order_id, amount, 'stripe', cs.payment_intent, f'Stripe checkout {sid[:12]}'))
            new_deposit = (order['deposit_paid'] or 0) + amount
            new_balance = max(0, (order['total'] or 0) - new_deposit)
            paid_full = 1 if new_balance <= 0.01 else 0
            db.execute("UPDATE orders SET deposit_paid=?,balance_due=?,paid_in_full=? WHERE id=?",
                       (new_deposit, new_balance, paid_full, order_id))
            db.commit()
            flash(f'Payment of ${amount:.2f} received! ✅', 'success')
        except Exception as e:
            flash(f'Payment recorded but verification failed: {e}', 'warning')
    return redirect(url_for('order_detail', order_id=order_id))

@app.route('/orders/<int:order_id>/cash-payment', methods=['POST'])
@login_required
def cash_payment(order_id):
    db = get_db()
    amount = float(request.form.get('amount', 0))
    method = request.form.get('method', 'cash')
    if amount > 0:
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        db.execute("INSERT INTO receipts(order_id,amount,method,notes) VALUES(?,?,?,?)",
                   (order_id, amount, method, request.form.get('notes', '')))
        new_deposit = (order['deposit_paid'] or 0) + amount
        new_balance = max(0, (order['total'] or 0) - new_deposit)
        paid_full = 1 if new_balance <= 0.01 else 0
        db.execute("UPDATE orders SET deposit_paid=?,balance_due=?,paid_in_full=? WHERE id=?",
                   (new_deposit, new_balance, paid_full, order_id))
        db.commit()
        flash(f'${amount:.2f} {method} payment recorded.', 'success')
    return redirect(url_for('order_detail', order_id=order_id))

# ── Inventory ─────────────────────────────────────────────────────────────────
@app.route('/inventory')
@login_required
def inventory():
    db = get_db()
    ingredients = db.execute('''
        SELECT i.*, s.name as supplier_name
        FROM ingredients i LEFT JOIN suppliers s ON i.supplier_id=s.id
        ORDER BY i.name
    ''').fetchall()
    return render_template('inventory.html', ingredients=ingredients, bakery=BAKERY_NAME)

@app.route('/inventory/add', methods=['POST'])
@login_required
def inventory_add():
    db = get_db()
    db.execute('''INSERT INTO ingredients(name,unit,quantity,reorder_level,cost_per_unit,supplier_id,notes)
                  VALUES(?,?,?,?,?,?,?)''',
               (request.form['name'].strip(), request.form.get('unit','lbs'),
                float(request.form.get('quantity',0)), float(request.form.get('reorder_level',5)),
                float(request.form.get('cost_per_unit',0)),
                request.form.get('supplier_id') or None, request.form.get('notes','')))
    db.commit()
    flash('Ingredient added.', 'success')
    return redirect(url_for('inventory'))

@app.route('/inventory/<int:item_id>/adjust', methods=['POST'])
@login_required
def inventory_adjust(item_id):
    db = get_db()
    delta = float(request.form.get('delta', 0))
    db.execute("UPDATE ingredients SET quantity=MAX(0,quantity+?) WHERE id=?", (delta, item_id))
    db.commit()
    return redirect(url_for('inventory'))

@app.route('/inventory/<int:item_id>/edit', methods=['POST'])
@login_required
def inventory_edit(item_id):
    db = get_db()
    db.execute('''UPDATE ingredients SET name=?,unit=?,quantity=?,reorder_level=?,
                  cost_per_unit=?,supplier_id=?,notes=? WHERE id=?''',
               (request.form['name'], request.form.get('unit','lbs'),
                float(request.form.get('quantity',0)), float(request.form.get('reorder_level',5)),
                float(request.form.get('cost_per_unit',0)),
                request.form.get('supplier_id') or None,
                request.form.get('notes',''), item_id))
    db.commit()
    flash('Updated.', 'success')
    return redirect(url_for('inventory'))

# ── Suppliers ─────────────────────────────────────────────────────────────────
@app.route('/suppliers')
@login_required
def suppliers():
    db = get_db()
    all_suppliers = db.execute("SELECT * FROM suppliers WHERE active=1 ORDER BY name").fetchall()
    return render_template('suppliers.html', suppliers=all_suppliers, bakery=BAKERY_NAME)

@app.route('/suppliers/add', methods=['POST'])
@login_required
def supplier_add():
    db = get_db()
    db.execute("INSERT INTO suppliers(name,contact,email,phone,address,notes) VALUES(?,?,?,?,?,?)",
               (request.form['name'], request.form.get('contact',''), request.form.get('email',''),
                request.form.get('phone',''), request.form.get('address',''), request.form.get('notes','')))
    db.commit()
    flash('Supplier added.', 'success')
    return redirect(url_for('suppliers'))

# ── Employees ─────────────────────────────────────────────────────────────────
@app.route('/employees')
@login_required
def employees():
    db = get_db()
    emps = db.execute('''
        SELECT e.*,
               (SELECT clock_in FROM timesheets WHERE employee_id=e.id AND clock_out IS NULL LIMIT 1) as clocked_in_at
        FROM employees e WHERE e.active=1 ORDER BY e.name
    ''').fetchall()
    return render_template('employees.html', employees=emps, bakery=BAKERY_NAME)

@app.route('/employees/add', methods=['POST'])
@login_required
def employee_add():
    db = get_db()
    db.execute("INSERT INTO employees(name,email,phone,role,hourly_rate,pin,notes) VALUES(?,?,?,?,?,?,?)",
               (request.form['name'], request.form.get('email',''), request.form.get('phone',''),
                request.form.get('role','Baker'), float(request.form.get('hourly_rate',15)),
                request.form.get('pin','0000'), request.form.get('notes','')))
    db.commit()
    flash('Employee added.', 'success')
    return redirect(url_for('employees'))

@app.route('/employees/<int:emp_id>/timesheets')
@login_required
def employee_timesheets(emp_id):
    db = get_db()
    emp = db.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    ts  = db.execute("SELECT * FROM timesheets WHERE employee_id=? ORDER BY clock_in DESC LIMIT 50", (emp_id,)).fetchall()
    total_hours = 0
    for t in ts:
        if t['clock_out']:
            ci = datetime.datetime.fromisoformat(t['clock_in'])
            co = datetime.datetime.fromisoformat(t['clock_out'])
            hrs = (co - ci).total_seconds() / 3600 - (t['break_mins'] or 0)/60
            total_hours += max(0, hrs)
    return render_template('timesheets.html', emp=emp, timesheets=ts,
                           total_hours=round(total_hours,2), bakery=BAKERY_NAME)

@app.route('/timesheets/clockin', methods=['POST'])
@login_required
def clock_in():
    db = get_db()
    emp_id = int(request.form.get('employee_id'))
    existing = db.execute("SELECT id FROM timesheets WHERE employee_id=? AND clock_out IS NULL", (emp_id,)).fetchone()
    if existing:
        flash('Already clocked in!', 'warning')
    else:
        db.execute("INSERT INTO timesheets(employee_id,clock_in) VALUES(?,datetime('now'))", (emp_id,))
        db.commit()
        emp = db.execute("SELECT name FROM employees WHERE id=?", (emp_id,)).fetchone()
        flash(f'{emp["name"]} clocked in ✅', 'success')
    return redirect(url_for('employees'))

@app.route('/timesheets/clockout', methods=['POST'])
@login_required
def clock_out():
    db = get_db()
    emp_id = int(request.form.get('employee_id'))
    ts = db.execute("SELECT id FROM timesheets WHERE employee_id=? AND clock_out IS NULL ORDER BY clock_in DESC LIMIT 1", (emp_id,)).fetchone()
    if ts:
        db.execute("UPDATE timesheets SET clock_out=datetime('now') WHERE id=?", (ts['id'],))
        db.commit()
        emp = db.execute("SELECT name FROM employees WHERE id=?", (emp_id,)).fetchone()
        flash(f'{emp["name"]} clocked out ✅', 'success')
    else:
        flash('Not clocked in.', 'warning')
    return redirect(url_for('employees'))

# ── Recipes ───────────────────────────────────────────────────────────────────
@app.route('/recipes')
@login_required
def recipes():
    db = get_db()
    all_recipes = db.execute("SELECT * FROM recipes WHERE active=1 ORDER BY category, name").fetchall()
    return render_template('recipes.html', recipes=all_recipes, bakery=BAKERY_NAME)

@app.route('/recipes/add', methods=['GET', 'POST'])
@login_required
def recipe_add():
    db = get_db()
    if request.method == 'POST':
        cur = db.execute('''INSERT INTO recipes(name,category,description,servings,prep_mins,bake_mins,base_price)
                            VALUES(?,?,?,?,?,?,?)''',
                         (request.form['name'], request.form.get('category','Cake'),
                          request.form.get('description',''), int(request.form.get('servings',1)),
                          int(request.form.get('prep_mins',60)), int(request.form.get('bake_mins',45)),
                          float(request.form.get('base_price',0))))
        db.commit()
        flash('Recipe added!', 'success')
        return redirect(url_for('recipe_detail', recipe_id=cur.lastrowid))
    ingredients = db.execute("SELECT id,name,unit FROM ingredients ORDER BY name").fetchall()
    return render_template('recipe_form.html', ingredients=ingredients, bakery=BAKERY_NAME)

@app.route('/recipes/<int:recipe_id>')
@login_required
def recipe_detail(recipe_id):
    db = get_db()
    recipe = db.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
    if not recipe: return redirect(url_for('recipes'))
    ingreds = db.execute('''
        SELECT ri.*, i.name as ing_name, i.cost_per_unit, i.unit as ing_unit
        FROM recipe_ingredients ri
        JOIN ingredients i ON ri.ingredient_id=i.id
        WHERE ri.recipe_id=?
    ''', (recipe_id,)).fetchall()
    cost = sum(r['quantity'] * r['cost_per_unit'] for r in ingreds)
    all_ingreds = db.execute("SELECT id,name,unit FROM ingredients ORDER BY name").fetchall()
    return render_template('recipe_detail.html', recipe=recipe, ingreds=ingreds,
                           cost=round(cost,2), all_ingreds=all_ingreds, bakery=BAKERY_NAME)

@app.route('/recipes/<int:recipe_id>/add-ingredient', methods=['POST'])
@login_required
def recipe_add_ingredient(recipe_id):
    db = get_db()
    db.execute("INSERT INTO recipe_ingredients(recipe_id,ingredient_id,quantity,unit) VALUES(?,?,?,?)",
               (recipe_id, int(request.form['ingredient_id']),
                float(request.form['quantity']), request.form.get('unit','')))
    db.commit()
    flash('Ingredient added to recipe.', 'success')
    return redirect(url_for('recipe_detail', recipe_id=recipe_id))

# ── Customers ─────────────────────────────────────────────────────────────────
@app.route('/customers')
@login_required
def customers():
    db = get_db()
    q = request.args.get('q', '')
    if q:
        custs = db.execute("SELECT * FROM customers WHERE name LIKE ? OR email LIKE ? OR phone LIKE ? ORDER BY name",
                           (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()
    else:
        custs = db.execute("SELECT * FROM customers ORDER BY name LIMIT 100").fetchall()
    return render_template('customers.html', customers=custs, q=q, bakery=BAKERY_NAME)

# ── Reports ───────────────────────────────────────────────────────────────────
@app.route('/reports')
@login_required
def reports():
    db = get_db()
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()

    revenue_month = db.execute("SELECT COALESCE(SUM(amount),0) FROM receipts WHERE date(created)>=?", (month_start,)).fetchone()[0]
    orders_month  = db.execute("SELECT COUNT(*) FROM orders WHERE date(created)>=?", (month_start,)).fetchone()[0]
    top_items     = db.execute('''SELECT name, SUM(quantity) as qty, SUM(total) as rev
                                  FROM order_items GROUP BY name ORDER BY rev DESC LIMIT 10''').fetchall()
    revenue_by_day = db.execute('''SELECT date(created) as day, SUM(amount) as total
                                   FROM receipts WHERE date(created)>=?
                                   GROUP BY day ORDER BY day''', (month_start,)).fetchall()
    employee_hours = db.execute('''
        SELECT e.name,
               ROUND(SUM(
                 CASE WHEN t.clock_out IS NOT NULL
                 THEN (julianday(t.clock_out)-julianday(t.clock_in))*24 - COALESCE(t.break_mins,0)/60.0
                 ELSE 0 END
               ),2) as hours,
               e.hourly_rate
        FROM employees e
        LEFT JOIN timesheets t ON t.employee_id=e.id AND date(t.clock_in)>=?
        WHERE e.active=1
        GROUP BY e.id ORDER BY hours DESC
    ''', (month_start,)).fetchall()
    return render_template('reports.html', revenue_month=revenue_month,
                           orders_month=orders_month, top_items=top_items,
                           revenue_by_day=revenue_by_day, employee_hours=employee_hours,
                           month=today.strftime('%B %Y'), bakery=BAKERY_NAME)

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route('/settings')
@admin_required
def settings():
    db = get_db()
    users = db.execute("SELECT id,name,email,role,active FROM users ORDER BY name").fetchall()
    return render_template('settings.html', users=users, bakery=BAKERY_NAME,
                           admin_email=ADMIN_EMAIL, stripe_configured=bool(stripe.api_key))

@app.route('/settings/add-user', methods=['POST'])
@admin_required
def add_user():
    db = get_db()
    email = request.form['email'].strip().lower()
    pw    = request.form['password']
    name  = request.form['name'].strip()
    role  = request.form.get('role', 'staff')
    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    try:
        db.execute("INSERT INTO users(email,password,name,role) VALUES(?,?,?,?)", (email, hashed, name, role))
        db.commit()
        flash(f'User {name} added.', 'success')
    except:
        flash('Email already exists.', 'error')
    return redirect(url_for('settings'))

# ── API (for AJAX) ────────────────────────────────────────────────────────────
@app.route('/api/ingredients')
@login_required
def api_ingredients():
    db = get_db()
    rows = db.execute("SELECT id,name,unit,quantity,cost_per_unit FROM ingredients ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/recipes')
@login_required
def api_recipes():
    db = get_db()
    rows = db.execute("SELECT id,name,category,base_price FROM recipes WHERE active=1 ORDER BY name").fetchall()
    return jsonify([dict(r) for r in rows])

# ── Cakely AI Agent API (Bearer token auth) ─────────────────────────────────
CAKELY_TOKEN = os.environ.get('CAKELY_API_TOKEN', 'cakely-sweet-spot-2026')

def cakely_auth():
    auth = request.headers.get('Authorization', '')
    return auth == f'Bearer {CAKELY_TOKEN}'

@app.route('/cakely/api/orders')
def cakely_orders():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    status = request.args.get('status', '')
    q = request.args.get('q', '')
    today = datetime.date.today().isoformat()
    sql = 'SELECT * FROM orders WHERE 1=1'
    params = []
    if status: sql += ' AND status=?'; params.append(status)
    if q: sql += ' AND (customer_name LIKE ? OR order_number LIKE ?)'; params += [f'%{q}%', f'%{q}%']
    sql += ' ORDER BY created DESC LIMIT 20'
    orders = [dict(r) for r in db.execute(sql, params).fetchall()]
    return jsonify({'ok': True, 'orders': orders, 'count': len(orders)})

@app.route('/cakely/api/orders/today')
def cakely_orders_today():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    today = datetime.date.today().isoformat()
    orders = [dict(r) for r in db.execute(
        "SELECT * FROM orders WHERE date(created)=? OR pickup_date=? ORDER BY pickup_time",
        (today, today)).fetchall()]
    pending = [dict(r) for r in db.execute(
        "SELECT * FROM orders WHERE status='pending' ORDER BY created DESC LIMIT 10").fetchall()]
    ready = [dict(r) for r in db.execute(
        "SELECT * FROM orders WHERE status='ready' ORDER BY pickup_date, pickup_time").fetchall()]
    return jsonify({'ok': True, 'today': orders, 'pending': pending, 'ready': ready,
                   'summary': f'{len(orders)} orders today, {len(pending)} pending, {len(ready)} ready for pickup'})

@app.route('/cakely/api/inventory/low')
def cakely_low_stock():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    items = [dict(r) for r in db.execute(
        'SELECT name, quantity, unit, reorder_level, cost_per_unit FROM ingredients WHERE quantity<=reorder_level ORDER BY quantity ASC'
    ).fetchall()]
    return jsonify({'ok': True, 'low_stock': items, 'count': len(items),
                   'summary': f'{len(items)} items at or below reorder level' if items else 'All stock levels OK ✅'})

@app.route('/cakely/api/inventory')
def cakely_inventory():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    items = [dict(r) for r in db.execute(
        'SELECT name, quantity, unit, reorder_level, cost_per_unit FROM ingredients ORDER BY name'
    ).fetchall()]
    return jsonify({'ok': True, 'inventory': items, 'count': len(items)})

@app.route('/cakely/api/customers')
def cakely_customers():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    q = request.args.get('q', '')
    if q:
        custs = [dict(r) for r in db.execute(
            'SELECT * FROM customers WHERE name LIKE ? OR email LIKE ? OR phone LIKE ? ORDER BY name LIMIT 10',
            (f'%{q}%', f'%{q}%', f'%{q}%')).fetchall()]
    else:
        custs = [dict(r) for r in db.execute('SELECT * FROM customers ORDER BY name LIMIT 20').fetchall()]
    return jsonify({'ok': True, 'customers': custs, 'count': len(custs)})

@app.route('/cakely/api/employees/status')
def cakely_employee_status():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    clocked_in = [dict(r) for r in db.execute(
        "SELECT e.name, e.role, t.clock_in FROM employees e "
        "JOIN timesheets t ON t.employee_id=e.id WHERE t.clock_out IS NULL ORDER BY e.name"
    ).fetchall()]
    clocked_out = [dict(r) for r in db.execute(
        "SELECT name, role FROM employees WHERE active=1 AND id NOT IN "
        "(SELECT employee_id FROM timesheets WHERE clock_out IS NULL)"
    ).fetchall()]
    return jsonify({'ok': True, 'clocked_in': clocked_in, 'clocked_out': clocked_out,
                   'summary': f'{len(clocked_in)} staff in, {len(clocked_out)} staff out'})

@app.route('/cakely/api/dashboard')
def cakely_dashboard():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    today = datetime.date.today().isoformat()
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    data = {
        'orders_today':   db.execute("SELECT COUNT(*) FROM orders WHERE date(created)=?", (today,)).fetchone()[0],
        'orders_pending': db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0],
        'orders_ready':   db.execute("SELECT COUNT(*) FROM orders WHERE status='ready'").fetchone()[0],
        'revenue_week':   round(db.execute("SELECT COALESCE(SUM(amount),0) FROM receipts WHERE date(created)>=?", (week_ago,)).fetchone()[0], 2),
        'low_stock_count':db.execute("SELECT COUNT(*) FROM ingredients WHERE quantity<=reorder_level").fetchone()[0],
        'staff_in':       db.execute("SELECT COUNT(*) FROM timesheets WHERE clock_out IS NULL").fetchone()[0],
        'pickups_today':  db.execute("SELECT COUNT(*) FROM orders WHERE pickup_date=? AND status NOT IN ('delivered','cancelled')", (today,)).fetchone()[0],
    }
    return jsonify({'ok': True, 'dashboard': data,
                   'summary': f"Today: {data['orders_today']} orders, {data['orders_ready']} ready for pickup, "
                              f"${data['revenue_week']:.2f} revenue this week, {data['low_stock_count']} low stock items"})

@app.route('/cakely/api/recipes')
def cakely_recipes():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    recipes = [dict(r) for r in db.execute(
        'SELECT name, category, base_price, servings, prep_mins, bake_mins, description FROM recipes WHERE active=1 ORDER BY name'
    ).fetchall()]
    return jsonify({'ok': True, 'recipes': recipes, 'count': len(recipes)})

@app.route('/cakely/api/memory')
def cakely_memory():
    """Returns Cakely brain files so the AI Widget can pull them."""
    IDENTITY = """# IDENTITY

- Name: Cakely \U0001f382
- Role: AI assistant for Sweet Spot Custom Cakes
- Bakery: Sweet Spot Custom Cakes \u2014 custom cakes, cupcakes, and baked goods
- App URL: Set BAKERY_URL in Railway env vars

## What Cakely Can Help With
- Looking up orders by customer name or order number
- Checking inventory levels and low stock alerts
- Finding customer information and history
- Checking today's pickups and pending orders
- Reporting on revenue and business stats
- Answering questions about recipes and pricing
- Checking which staff are clocked in

## What Cakely Cannot Do
- Create or modify orders directly (staff must do that in the app)
- Process payments
- Access systems outside Sweet Spot Custom Cakes"""

    SOUL = """# SOUL

## Personality
Warm, cheerful, and professional \u2014 like a friendly bakery manager who knows everything.
Proud of the bakery and genuinely helpful to all staff.

## Communication Style
- Short, clear answers with the key info upfront
- Use \U0001f382 \U0001f9c1 \u2728 emojis sparingly to keep it fun
- When you find data, present it in a readable way
- Always offer a next step or follow-up question

## Values
- Accuracy: only report real data from your actions
- Speed: get to the answer fast
- Warmth: this is a bakery \u2014 keep it sweet!"""

    MEMORY = f"""# MEMORY

## About Sweet Spot Custom Cakes
- A custom cake and bakery business
- Uses Sweet Spot Cakes app for order management
- Staff can clock in/out, manage orders, track inventory, and view reports

## Cakely API Token
- Token: {CAKELY_TOKEN}
- Use Bearer auth: Authorization: Bearer {CAKELY_TOKEN}

## Available Actions
- get_dashboard: overall bakery stats (orders, revenue, staff, low stock)
- get_todays_orders: all orders for today + pending + ready for pickup
- lookup_order: search orders by customer name or order number
- get_low_stock: ingredients at or below reorder level
- get_inventory: full inventory list
- lookup_customer: search customer by name/email/phone
- get_employee_status: who is clocked in/out right now
- get_recipes: all active recipes with pricing"""

    return jsonify({'ok': True, 'identity_md': IDENTITY, 'soul_md': SOUL, 'memory_md': MEMORY})


@app.route('/api/customers/search')
@login_required
def api_customers_search():
    db = get_db()
    q = request.args.get('q', '')
    rows = db.execute("SELECT id,name,email,phone FROM customers WHERE name LIKE ? OR email LIKE ? LIMIT 10",
                      (f'%{q}%', f'%{q}%')).fetchall()
    return jsonify([dict(r) for r in rows])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
