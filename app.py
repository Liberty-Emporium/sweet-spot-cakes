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

# ── Square config ────────────────────────────────────────────────────
SQUARE_ACCESS_TOKEN  = os.environ.get('SQUARE_ACCESS_TOKEN', '')
SQUARE_LOCATION_ID   = os.environ.get('SQUARE_LOCATION_ID', '')
SQUARE_ENV           = os.environ.get('SQUARE_ENV', 'sandbox')  # 'sandbox' or 'production'
SQUARE_BASE_URL      = 'https://connect.squareup.com' if SQUARE_ENV == 'production' else 'https://connect.squareupsandbox.com'

BAKERY_NAME    = os.environ.get('BAKERY_NAME', 'Sweet Spot Custom Cakes')
ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL', 'info@sweetspotcustomcakes.com')

# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA synchronous=NORMAL')
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA busy_timeout=5000')
    return g.db

# ── Rate limiting (simple in-memory) ─────────────────────────────────────────
import time as _time
_rl_store: dict = {}
_rl_lock = threading.Lock()

def _rate_limit(key: str, max_req: int = 10, window: int = 60) -> bool:
    """Return True if request should be blocked."""
    now = _time.time()
    with _rl_lock:
        hits = [t for t in _rl_store.get(key, []) if now - t < window]
        if len(hits) >= max_req:
            return True
        hits.append(now)
        _rl_store[key] = hits
    return False

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
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
    CREATE TABLE IF NOT EXISTS order_photos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id    INTEGER NOT NULL,
        filename    TEXT NOT NULL,
        caption     TEXT DEFAULT '',
        created     TEXT DEFAULT (datetime('now')),
        FOREIGN KEY(order_id) REFERENCES orders(id)
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
    CREATE TABLE IF NOT EXISTS specials (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        description TEXT DEFAULT '',
        discount    TEXT DEFAULT '',
        valid_from  TEXT DEFAULT (date('now')),
        valid_until TEXT DEFAULT '',
        active      INTEGER DEFAULT 1,
        created     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS campaigns (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        audience    TEXT DEFAULT 'all',  -- all, birthday, new, top_customers
        subject     TEXT DEFAULT '',
        message     TEXT DEFAULT '',
        ad_copy     TEXT DEFAULT '',
        status      TEXT DEFAULT 'draft', -- draft, sent, scheduled
        sent_count  INTEGER DEFAULT 0,
        created     TEXT DEFAULT (datetime('now')),
        sent_at     TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS loyalty_members (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER UNIQUE NOT NULL,
        joined_at   TEXT DEFAULT (datetime('now')),
        points      INTEGER DEFAULT 0,
        tier        TEXT DEFAULT 'member',
        source      TEXT DEFAULT 'qr',
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS tools (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        category    TEXT DEFAULT 'Equipment',
        quantity    INTEGER DEFAULT 1,
        unit        TEXT DEFAULT 'each',
        location    TEXT DEFAULT '',
        notes       TEXT DEFAULT '',
        active      INTEGER DEFAULT 1,
        created     TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS recipe_tools (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL,
        tool_id   INTEGER NOT NULL,
        notes     TEXT DEFAULT '',
        FOREIGN KEY(recipe_id) REFERENCES recipes(id),
        FOREIGN KEY(tool_id)   REFERENCES tools(id)
    );
    ''')
    db.commit()

    # Seed admin user
    admin_pw = os.environ.get('ADMIN_PASSWORD', 'sweetspot2026')
    hashed = bcrypt.hashpw(admin_pw.encode(), bcrypt.gensalt()).decode()
    db.execute('''INSERT OR IGNORE INTO users(email,password,name,role)
                  VALUES(?,?,?,?)''', (ADMIN_EMAIL, hashed, 'Admin', 'admin'))
    db.commit()

    # ── Seed high-end bakery ingredients ──────────────────────────────────────
    INGREDIENTS_SEED = [
        # (name, unit, qty, reorder, cost, notes)
        # Flours & Starches
        ('Cake Flour (High-Protein)',    'lbs',  25, 10, 2.40,  'Store airtight, cool dry place'),
        ('All-Purpose Flour',            'lbs',  30, 10, 1.80,  'King Arthur preferred'),
        ('Bread Flour',                  'lbs',  15,  8, 2.10,  'For laminated doughs'),
        ('Almond Flour',                 'lbs',  10,  5, 8.50,  'Blanched, fine grind'),
        ('Hazelnut Flour',               'lbs',   5,  3, 9.20,  'For financiers & dacquoise'),
        ('Cornstarch',                   'lbs',   8,  4, 1.60,  'Pie fillings & pastry cream'),
        ('Tapioca Starch',               'lbs',   4,  2, 3.10,  'Gluten-free thickener'),
        # Sugars & Sweeteners
        ('Granulated Sugar',             'lbs',  40, 15, 0.90,  ''),
        ('Powdered Sugar (10X)',         'lbs',  25, 10, 1.20,  'Sift before use'),
        ('Light Brown Sugar',            'lbs',  15,  8, 1.30,  'Keep sealed'),
        ('Dark Brown Sugar',             'lbs',  10,  5, 1.40,  'Keep sealed'),
        ('Demerara Sugar',               'lbs',   5,  3, 2.80,  'Finishing sugar for tops'),
        ('Turbinado Sugar',              'lbs',   5,  3, 2.60,  'Sanding & garnish'),
        ('Honey (Wildflower)',           'lbs',   6,  3, 7.50,  'Raw, local sourced'),
        ('Maple Syrup (Grade A Dark)',   'cups', 12,  6, 5.20,  'Refrigerate after open'),
        ('Glucose Syrup',               'lbs',   8,  4, 4.10,  'Anti-crystallization'),
        ('Invert Sugar (Trimoline)',     'lbs',   4,  2, 6.80,  'Keeps cakes moist longer'),
        # Dairy & Eggs
        ('Unsalted Butter (European)',   'lbs',  30, 15, 5.80,  '84% butterfat preferred'),
        ('Heavy Cream (36%)',            'gallons', 5, 2, 6.40, 'Refrigerate, FIFO'),
        ('Cream Cheese',                 'lbs',  10,  5, 4.20,  'Full fat Philadelphia or equiv'),
        ('Whole Milk',                   'gallons', 3, 2, 4.10, 'Refrigerate'),
        ('Buttermilk',                   'gallons', 2, 1, 4.80, 'Refrigerate'),
        ('Sour Cream',                   'lbs',   6,  3, 3.60,  'Full fat'),
        ('Mascarpone',                   'lbs',   4,  2, 9.20,  'Tiramisu & mousse cakes'),
        ('Eggs (Large AA)',              'dozen', 12,  6, 4.50, 'Room temp before use'),
        ('Egg Whites (Pasteurized)',     'lbs',   4,  2, 5.10,  'Meringues & macarons'),
        # Chocolate & Cocoa
        ('Valrhona Dark Chocolate 70%', 'lbs',   8,  4, 18.50, 'Couverture, temper for decor'),
        ('Valrhona Milk Chocolate 40%', 'lbs',   6,  3, 16.80, 'Couverture'),
        ('Valrhona White Chocolate',    'lbs',   5,  3, 17.20, 'Couverture'),
        ('Dutch-Process Cocoa Powder',  'lbs',   6,  3,  8.40, 'Droste or Cacao Barry'),
        ('Natural Cocoa Powder',        'lbs',   4,  2,  7.20, 'For red velvet'),
        ('Black Cocoa Powder',          'lbs',   3,  2, 12.00, 'Ultra-dark Oreo flavor'),
        # Leaveners & Salt
        ('Baking Powder (alum-free)',   'lbs',   3,  2,  4.20, 'Test freshness monthly'),
        ('Baking Soda',                 'lbs',   3,  2,  1.80, ''),
        ('Fine Sea Salt',               'lbs',   5,  3,  3.20, ''),
        ('Fleur de Sel',                'oz',   12,  4, 12.00, 'Finishing salt only'),
        ('Cream of Tartar',             'lbs',   2,  1,  6.40, 'Stabilizes egg whites'),
        # Extracts, Flavors & Spices
        ('Pure Vanilla Extract',        'oz',   16,  6, 14.00, 'Nielsen-Massey or Rodelle'),
        ('Vanilla Bean Paste',          'oz',   12,  4, 18.00, 'Seeds visible in frosting'),
        ('Whole Vanilla Beans',         'each', 24,  8, 2.80,  'Madagascar Bourbon'),
        ('Almond Extract',              'oz',    8,  3, 9.50,  ''),
        ('Rose Water',                  'oz',    8,  3, 4.20,  'Middle Eastern brand'),
        ('Orange Blossom Water',        'oz',    6,  2, 4.60,  ''),
        ('Espresso Powder',             'oz',    8,  4, 8.80,  'Enhances chocolate'),
        ('Cinnamon (Ceylon)',           'oz',   12,  4, 7.20,  'True cinnamon'),
        ('Cardamom (Ground)',           'oz',    6,  3, 9.40,  ''),
        ('Fleur de Sel Caramel Sauce',  'oz',   24,  8, 6.50,  'House-made or Fran\'s'),
        # Nuts & Fruits
        ('Blanched Almonds',            'lbs',   5,  3, 8.20,  'Whole & sliced'),
        ('Pistachios (Raw, Shelled)',   'lbs',   4,  2, 14.50, 'Bright green color'),
        ('Hazelnuts (Roasted)',         'lbs',   4,  2, 11.20, 'Skin-off preferred'),
        ('Pecans (Halves)',             'lbs',   4,  2, 10.80, ''),
        ('Dried Cherries',              'lbs',   3,  2,  9.20, 'Montmorency tart'),
        ('Freeze-Dried Raspberries',    'oz',   12,  4, 16.00, 'Powder for buttercream'),
        ('Freeze-Dried Strawberries',   'oz',   12,  4, 14.00, 'Powder for buttercream'),
        # Specialty & Décor
        ('Edible Gold Dust',            'each',  5,  2, 22.00, 'CK Products'),
        ('Edible Silver Dust',          'each',  5,  2, 18.00, 'CK Products'),
        ('Food Coloring Gel Set',       'each',  3,  1, 32.00, 'Americolor soft gel'),
        ('Fondant (White, Premium)',    'lbs',  20,  8,  5.20, 'Satin Ice or Fondarific'),
        ('Gum Paste',                   'lbs',   6,  3,  6.80, 'For sugar flowers'),
        ('Isomalt',                     'lbs',   4,  2, 12.00, 'Sugar showpiece work'),
        ('Luster Dust (Assorted)',      'each',  8,  3, 11.00, 'For metallic finishes'),
        ('Parchment Paper (half-sheet)','boxes', 4,  2,  9.50, ''),
        ('Piping Bags (16-inch)',        'boxes', 6,  3,  8.00, 'Disposable heavy duty'),
        ('Acetate Sheets',              'each', 50, 20,  0.40, 'Entremet collars & glazing'),
    ]
    existing_ingr = {r['name'] for r in db.execute('SELECT name FROM ingredients').fetchall()}
    for name, unit, qty, reorder, cost, notes in INGREDIENTS_SEED:
        if name not in existing_ingr:
            db.execute(
                'INSERT INTO ingredients(name,unit,quantity,reorder_level,cost_per_unit,notes) VALUES(?,?,?,?,?,?)',
                (name, unit, qty, reorder, cost, notes)
            )
    db.commit()

    # ── Seed baker tools & equipment ──────────────────────────────────────────
    TOOLS_SEED = [
        # (name, category, qty, unit, location, notes)
        # Pans & Molds
        ('Round Cake Pan 6"',           'Pans & Molds',   12, 'each', 'Pan Rack A', '2" deep, anodized aluminum'),
        ('Round Cake Pan 8"',           'Pans & Molds',   12, 'each', 'Pan Rack A', '2" deep, anodized aluminum'),
        ('Round Cake Pan 10"',          'Pans & Molds',    8, 'each', 'Pan Rack A', '2" deep'),
        ('Round Cake Pan 12"',          'Pans & Molds',    6, 'each', 'Pan Rack A', 'For tiered cakes'),
        ('Half Sheet Pan (18x13")',      'Pans & Molds',   20, 'each', 'Pan Rack B', 'Aluminum, commercial'),
        ('Quarter Sheet Pan (9x13")',    'Pans & Molds',   10, 'each', 'Pan Rack B', ''),
        ('Bundt Pan (Nordic Ware)',      'Pans & Molds',    4, 'each', 'Pan Rack C', 'Heritage & anniversary'),
        ('Springform Pan 9"',           'Pans & Molds',    6, 'each', 'Pan Rack C', 'Cheesecake & tarts'),
        ('Tart Pan 9" (removable)',     'Pans & Molds',    6, 'each', 'Pan Rack C', 'Fluted edge'),
        ('Loaf Pan 9x5"',               'Pans & Molds',    8, 'each', 'Pan Rack B', ''),
        ('Silicone Sphere Mold',        'Pans & Molds',    4, 'each', 'Mold Shelf',  '6-cavity, entremet bombs'),
        ('Silicone Half-Sphere Mold',   'Pans & Molds',    4, 'each', 'Mold Shelf',  '8-cavity'),
        ('Entremet Ring 6"',            'Pans & Molds',    8, 'each', 'Mold Shelf',  'Stainless, adjustable'),
        ('Entremet Ring 8"',            'Pans & Molds',    8, 'each', 'Mold Shelf',  'Stainless, adjustable'),
        ('Cupcake/Muffin Tin (24-cup)', 'Pans & Molds',    6, 'each', 'Pan Rack B', 'Commercial aluminum'),
        # Mixing & Prep
        ('KitchenAid 7qt Commercial Mixer','Mixing & Prep', 2,'each', 'Prep Counter', 'Bowl-lift, 1 hp'),
        ('Hobart 20qt Floor Mixer',     'Mixing & Prep',   1, 'each', 'Mixer Station','For large batches'),
        ('Stainless Mixing Bowl Set',   'Mixing & Prep',   6, 'set',  'Shelf', '3qt, 5qt, 8qt, 12qt'),
        ('Rubber Spatula (High-Temp)',  'Mixing & Prep',  12, 'each', 'Utensil Bin', 'Heat-safe to 800°F'),
        ('Bench Scraper',               'Mixing & Prep',   8, 'each', 'Utensil Bin', 'Stainless, flat'),
        ('Bowl Scraper (Flexible)',     'Mixing & Prep',   8, 'each', 'Utensil Bin', ''),
        ('Hand Whisk (12")',            'Mixing & Prep',   8, 'each', 'Utensil Bin', 'Balloon style'),
        ('Digital Kitchen Scale',       'Mixing & Prep',   4, 'each', 'Prep Counter', '0.1g precision, 11 lb cap'),
        # Decorating
        ('Turntable (Ateco Heavy)',     'Decorating',      4, 'each', 'Cake Decor Station', 'Cast iron base'),
        ('Offset Spatula (9")',         'Decorating',      8, 'each', 'Utensil Bin',  'Frosting & spreading'),
        ('Offset Spatula (4")',         'Decorating',      8, 'each', 'Utensil Bin',  'Detail work'),
        ('Straight Spatula (12")',      'Decorating',      6, 'each', 'Utensil Bin',  ''),
        ('Cake Smoother / Icing Comb',  'Decorating',      6, 'each', 'Decor Shelf',  'Acrylic, various textures'),
        ('Piping Tips Set (Ateco)',     'Decorating',      4, 'set',  'Tip Box',      '55-piece set'),
        ('Coupler Set',                 'Decorating',      8, 'set',  'Tip Box',      'Standard & large'),
        ('Fondant Smoother',            'Decorating',      6, 'each', 'Decor Shelf',  'Double-sided'),
        ('Rolling Pin (French)',        'Decorating',      4, 'each', 'Decor Shelf',  'For fondant & pastry'),
        ('Fondant Mat (Non-stick)',     'Decorating',      4, 'each', 'Decor Shelf',  '24x24 inch'),
        ('Flower Nail Set',             'Decorating',      2, 'set',  'Decor Shelf',  'Buttercream flowers'),
        ('Petal Veiner & Cutter Set',  'Decorating',      2, 'set',  'Decor Shelf',  'Gum paste flowers'),
        ('Airbrush Kit (Iwata)',        'Decorating',      2, 'each', 'Decor Station', 'Gravity feed, compressor incl'),
        ('Cake Board (10" round)',      'Decorating',     50, 'each', 'Supply Shelf', 'Gold foil'),
        ('Cake Board (12" round)',      'Decorating',     30, 'each', 'Supply Shelf', 'Gold foil'),
        ('Cake Drum (14" round)',       'Decorating',     20, 'each', 'Supply Shelf', '1/2" thick'),
        # Baking & Heating
        ('Convection Oven (Full-Size)', 'Baking & Heating', 2,'each', 'Oven Bay',    'Commercial, 5-rack'),
        ('Deck Oven',                   'Baking & Heating', 1,'each', 'Oven Bay',    '2-deck, steam injection'),
        ('Instant-Read Thermometer',   'Baking & Heating', 6,'each', 'Utensil Bin', 'Thermapen or equiv'),
        ('Candy/Sugar Thermometer',    'Baking & Heating', 4,'each', 'Utensil Bin', '100–400°F range'),
        ('Oven Thermometer',           'Baking & Heating', 6,'each', 'Oven Bay',    'Verify oven accuracy'),
        ('Bain-Marie / Double Boiler', 'Baking & Heating', 3,'each', 'Range Station','Chocolate & curd work'),
        ('Kitchen Torch (Bernzomatic)','Baking & Heating', 3,'each', 'Burner Shelf', 'Brûlée & meringue'),
        # Cutting & Measuring
        ('Chef Knife (10", Wüsthof)',  'Cutting',          4, 'each', 'Knife Block', 'Keep razor sharp'),
        ('Serrated Bread Knife (10")', 'Cutting',          4, 'each', 'Knife Block', 'Cake leveling & slicing'),
        ('Cake Leveler / Slicer',      'Cutting',          3, 'each', 'Tool Shelf',  'Adjustable height wire'),
        ('Pastry Cutter (Fluted)',     'Cutting',          4, 'each', 'Tool Shelf',  'For lattice & tart dough'),
        ('Cookie Cutter Set',          'Cutting',          4, 'set',  'Tool Shelf',  'Assorted shapes & sizes'),
        ('Measuring Cup Set (Dry)',    'Measuring',         4, 'set',  'Prep Counter','Stainless'),
        ('Measuring Spoon Set',        'Measuring',         6, 'set',  'Prep Counter','1/8 tsp – 1 tbsp'),
        # Cooling & Storage
        ('Wire Cooling Rack (half-sheet)', 'Cooling',      10,'each', 'Rack Wall',   ''),
        ('Cake Carrier (Tall)',         'Cooling',          6, 'each', 'Storage',     'Lockable, 18" tall'),
        ('Sheet Pan Rack (20-shelf)',   'Cooling',          2, 'each', 'Walk-In',     'On wheels'),
        ('Proofing Box / Cabinet',      'Cooling',          1, 'each', 'Kitchen',     'Humidity & temp control'),
    ]
    existing_tools = {r['name'] for r in db.execute('SELECT name FROM tools').fetchall()}
    for name, category, qty, unit, location, notes in TOOLS_SEED:
        if name not in existing_tools:
            db.execute(
                'INSERT INTO tools(name,category,quantity,unit,location,notes) VALUES(?,?,?,?,?,?)',
                (name, category, qty, unit, location, notes)
            )
    db.commit()

    # ── Seed high-end recipes ──────────────────────────────────────────
    ingr_map = {r['name']: r['id'] for r in db.execute('SELECT id, name FROM ingredients').fetchall()}
    tool_map = {r['name']: r['id'] for r in db.execute('SELECT id, name FROM tools WHERE active=1').fetchall()}
    existing_recipes = {r['name'] for r in db.execute('SELECT name FROM recipes').fetchall()}

    def _seed_recipe(name, category, description, servings, prep_mins, bake_mins, base_price, ingredients, tools_list):
        if name in existing_recipes:
            return
        cur2 = db.execute(
            'INSERT INTO recipes(name,category,description,servings,prep_mins,bake_mins,base_price,active) VALUES(?,?,?,?,?,?,?,1)',
            (name, category, description, servings, prep_mins, bake_mins, base_price)
        )
        rid = cur2.lastrowid
        for iname, qty, unit in ingredients:
            iid = ingr_map.get(iname)
            if iid:
                db.execute('INSERT INTO recipe_ingredients(recipe_id,ingredient_id,quantity,unit) VALUES(?,?,?,?)', (rid, iid, qty, unit))
        for tname in tools_list:
            tid = tool_map.get(tname)
            if tid:
                existing_rt = db.execute('SELECT id FROM recipe_tools WHERE recipe_id=? AND tool_id=?', (rid, tid)).fetchone()
                if not existing_rt:
                    db.execute('INSERT INTO recipe_tools(recipe_id,tool_id) VALUES(?,?)', (rid, tid))
        db.commit()

    RECIPE_SEED = [
        {
            'name': 'Classic French Vanilla Layer Cake',
            'category': 'Cake',
            'description': 'Four light genoise layers soaked in vanilla syrup, filled and frosted with silky French buttercream. Finished with vanilla bean flecks and a smooth ganache drip.',
            'servings': 16, 'prep_mins': 90, 'bake_mins': 30, 'base_price': 98.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 3.0, 'cups'), ('Granulated Sugar', 2.0, 'cups'),
                ('Unsalted Butter (European)', 1.0, 'cups'), ('Eggs (Large AA)', 4.0, 'each'),
                ('Whole Milk', 1.0, 'cups'), ('Baking Powder (alum-free)', 2.5, 'tsp'),
                ('Fine Sea Salt', 0.5, 'tsp'), ('Vanilla Bean Paste', 2.0, 'tbsp'),
                ('Pure Vanilla Extract', 1.0, 'tsp'), ('Heavy Cream (36%)', 2.0, 'cups'),
                ('Powdered Sugar (10X)', 3.0, 'cups'),
            ],
            'tools': ['Round Cake Pan 8"','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Rubber Spatula (High-Temp)','Offset Spatula (9")','Turntable (Ateco Heavy)',
                      'Cake Smoother / Icing Comb','Serrated Bread Knife (10")','Instant-Read Thermometer',
                      'Wire Cooling Rack (half-sheet)','Cake Board (10" round)','Piping Tips Set (Ateco)'],
        },
        {
            'name': 'Dark Chocolate Espresso Entremet',
            'category': 'Entremet',
            'description': 'Modern mirror-glaze entremet: hazelnut dacquoise base, espresso cremeux insert, Valrhona 70% chocolate mousse, and a glossy dark mirror glaze.',
            'servings': 12, 'prep_mins': 180, 'bake_mins': 20, 'base_price': 145.00,
            'ingredients': [
                ('Valrhona Dark Chocolate 70%', 1.5, 'lbs'), ('Hazelnut Flour', 1.0, 'cups'),
                ('Powdered Sugar (10X)', 0.75, 'cups'), ('Egg Whites (Pasteurized)', 0.5, 'cups'),
                ('Heavy Cream (36%)', 3.0, 'cups'), ('Granulated Sugar', 1.0, 'cups'),
                ('Espresso Powder', 2.0, 'tbsp'), ('Glucose Syrup', 0.5, 'cups'),
                ('Unsalted Butter (European)', 0.25, 'cups'), ('Eggs (Large AA)', 3.0, 'each'),
                ('Dutch-Process Cocoa Powder', 0.25, 'cups'), ('Fleur de Sel', 0.5, 'tsp'),
            ],
            'tools': ['Entremet Ring 8"','Silicone Half-Sphere Mold','KitchenAid 7qt Commercial Mixer',
                      'Bain-Marie / Double Boiler','Digital Kitchen Scale','Instant-Read Thermometer',
                      'Candy/Sugar Thermometer','Acetate Sheets','Offset Spatula (4")','Wire Cooling Rack (half-sheet)',
                      'Half Sheet Pan (18x13")'],
        },
        {
            'name': 'Lemon Lavender Chiffon Cake',
            'category': 'Cake',
            'description': 'Ultra-light chiffon layers with fresh lemon curd filling, whipped mascarpone cream, and edible lavender petals. Elegant and floral.',
            'servings': 14, 'prep_mins': 75, 'bake_mins': 35, 'base_price': 105.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 2.5, 'cups'), ('Granulated Sugar', 1.75, 'cups'),
                ('Eggs (Large AA)', 6.0, 'each'), ('Whole Milk', 0.75, 'cups'),
                ('Baking Powder (alum-free)', 1.5, 'tsp'), ('Fine Sea Salt', 0.5, 'tsp'),
                ('Cream of Tartar', 0.5, 'tsp'), ('Mascarpone', 1.0, 'lbs'),
                ('Heavy Cream (36%)', 2.0, 'cups'), ('Powdered Sugar (10X)', 1.5, 'cups'),
                ('Pure Vanilla Extract', 1.0, 'tsp'), ('Edible Gold Dust', 1.0, 'each'),
            ],
            'tools': ['Round Cake Pan 8"','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Rubber Spatula (High-Temp)','Hand Whisk (12")','Offset Spatula (9")','Turntable (Ateco Heavy)',
                      'Cake Smoother / Icing Comb','Instant-Read Thermometer','Wire Cooling Rack (half-sheet)',
                      'Cake Board (10" round)'],
        },
        {
            'name': 'Salted Caramel Praline Cake',
            'category': 'Cake',
            'description': 'Brown butter vanilla cake with house-made salted caramel buttercream, crunchy hazelnut praline, and a dramatic caramel drip. Rich and indulgent.',
            'servings': 16, 'prep_mins': 120, 'bake_mins': 32, 'base_price': 125.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 3.0, 'cups'), ('Dark Brown Sugar', 2.0, 'cups'),
                ('Unsalted Butter (European)', 1.25, 'cups'), ('Eggs (Large AA)', 4.0, 'each'),
                ('Buttermilk', 1.0, 'cups'), ('Baking Soda', 1.5, 'tsp'),
                ('Fine Sea Salt', 0.75, 'tsp'), ('Fleur de Sel Caramel Sauce', 8.0, 'oz'),
                ('Hazelnuts (Roasted)', 1.0, 'cups'), ('Granulated Sugar', 1.0, 'cups'),
                ('Heavy Cream (36%)', 1.5, 'cups'), ('Fleur de Sel', 1.0, 'tsp'),
                ('Invert Sugar (Trimoline)', 2.0, 'tbsp'),
            ],
            'tools': ['Round Cake Pan 8"','Round Cake Pan 6"','KitchenAid 7qt Commercial Mixer',
                      'Digital Kitchen Scale','Candy/Sugar Thermometer','Bain-Marie / Double Boiler',
                      'Offset Spatula (9")','Turntable (Ateco Heavy)','Cake Smoother / Icing Comb',
                      'Kitchen Torch (Bernzomatic)','Cake Board (10" round)','Wire Cooling Rack (half-sheet)'],
        },
        {
            'name': 'Raspberry Rose Macaron Tower',
            'category': 'Pastry',
            'description': 'French-style macarons with almond shells, raspberry-rose ganache filling, and fresh raspberry jam. Hand-assembled into a towering display.',
            'servings': 40, 'prep_mins': 240, 'bake_mins': 14, 'base_price': 185.00,
            'ingredients': [
                ('Almond Flour', 2.0, 'cups'), ('Powdered Sugar (10X)', 2.0, 'cups'),
                ('Egg Whites (Pasteurized)', 0.75, 'cups'), ('Granulated Sugar', 0.75, 'cups'),
                ('Cream of Tartar', 0.25, 'tsp'), ('Valrhona White Chocolate', 0.5, 'lbs'),
                ('Heavy Cream (36%)', 0.75, 'cups'), ('Freeze-Dried Raspberries', 2.0, 'oz'),
                ('Rose Water', 1.0, 'tbsp'), ('Food Coloring Gel Set', 1.0, 'each'),
            ],
            'tools': ['Half Sheet Pan (18x13")','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Piping Tips Set (Ateco)','Piping Bags (16-inch)','Measuring Spoon Set',
                      'Rubber Spatula (High-Temp)','Instant-Read Thermometer','Wire Cooling Rack (half-sheet)',
                      'Stainless Mixing Bowl Set'],
        },
        {
            'name': 'Gateau Opera',
            'category': 'Entremet',
            'description': 'Classic Parisian opera cake: almond joconde sponge soaked in espresso syrup, layered with coffee buttercream and dark chocolate ganache, finished with a perfect chocolate glaze.',
            'servings': 14, 'prep_mins': 200, 'bake_mins': 12, 'base_price': 135.00,
            'ingredients': [
                ('Almond Flour', 1.5, 'cups'), ('Powdered Sugar (10X)', 1.5, 'cups'),
                ('Eggs (Large AA)', 6.0, 'each'), ('Egg Whites (Pasteurized)', 0.5, 'cups'),
                ('Cake Flour (High-Protein)', 0.5, 'cups'), ('Unsalted Butter (European)', 0.25, 'cups'),
                ('Valrhona Dark Chocolate 70%', 1.0, 'lbs'), ('Heavy Cream (36%)', 1.5, 'cups'),
                ('Espresso Powder', 3.0, 'tbsp'), ('Granulated Sugar', 1.0, 'cups'),
                ('Glucose Syrup', 2.0, 'tbsp'), ('Fine Sea Salt', 0.25, 'tsp'),
            ],
            'tools': ['Half Sheet Pan (18x13")','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Bain-Marie / Double Boiler','Offset Spatula (4")','Offset Spatula (9")',
                      'Bench Scraper','Instant-Read Thermometer','Acetate Sheets',
                      'Serrated Bread Knife (10")','Rubber Spatula (High-Temp)'],
        },
        {
            'name': 'Strawberry Champagne Celebration Cake',
            'category': 'Celebration',
            'description': 'Light champagne chiffon layers with fresh strawberry compote, champagne Italian meringue buttercream, and a sugar-shard crown.',
            'servings': 20, 'prep_mins': 150, 'bake_mins': 28, 'base_price': 165.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 3.5, 'cups'), ('Granulated Sugar', 2.5, 'cups'),
                ('Eggs (Large AA)', 5.0, 'each'), ('Egg Whites (Pasteurized)', 0.75, 'cups'),
                ('Unsalted Butter (European)', 1.0, 'cups'), ('Heavy Cream (36%)', 2.0, 'cups'),
                ('Baking Powder (alum-free)', 2.5, 'tsp'), ('Fine Sea Salt', 0.5, 'tsp'),
                ('Pure Vanilla Extract', 2.0, 'tsp'), ('Freeze-Dried Strawberries', 2.0, 'oz'),
                ('Cream of Tartar', 0.5, 'tsp'), ('Powdered Sugar (10X)', 2.0, 'cups'),
                ('Edible Gold Dust', 2.0, 'each'), ('Isomalt', 0.5, 'lbs'),
            ],
            'tools': ['Round Cake Pan 10"','Round Cake Pan 8"','Round Cake Pan 6"',
                      'KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale','Candy/Sugar Thermometer',
                      'Turntable (Ateco Heavy)','Cake Smoother / Icing Comb','Offset Spatula (9")',
                      'Offset Spatula (4")','Kitchen Torch (Bernzomatic)','Cake Board (12" round)',
                      'Cake Drum (14" round)','Piping Tips Set (Ateco)','Piping Bags (16-inch)',
                      'Airbrush Kit (Iwata)'],
        },
        {
            'name': 'Valrhona Chocolate Lava Cakes',
            'category': 'Dessert',
            'description': 'Individual molten chocolate cakes with a Valrhona 70% dark chocolate center that flows when cut. Served with crème anglaise and edible gold dust.',
            'servings': 8, 'prep_mins': 30, 'bake_mins': 12, 'base_price': 52.00,
            'ingredients': [
                ('Valrhona Dark Chocolate 70%', 0.5, 'lbs'), ('Unsalted Butter (European)', 0.5, 'cups'),
                ('Eggs (Large AA)', 4.0, 'each'), ('Granulated Sugar', 0.5, 'cups'),
                ('Cake Flour (High-Protein)', 0.25, 'cups'), ('Fine Sea Salt', 0.25, 'tsp'),
                ('Fleur de Sel', 0.5, 'tsp'), ('Pure Vanilla Extract', 1.0, 'tsp'),
                ('Edible Gold Dust', 1.0, 'each'), ('Heavy Cream (36%)', 1.0, 'cups'),
                ('Whole Vanilla Beans', 1.0, 'each'),
            ],
            'tools': ['Bain-Marie / Double Boiler','Digital Kitchen Scale','Springform Pan 9"',
                      'Rubber Spatula (High-Temp)','Hand Whisk (12")','Instant-Read Thermometer',
                      'Oven Thermometer','Stainless Mixing Bowl Set','Measuring Spoon Set'],
        },
        {
            'name': 'Pistachio Raspberry Wedding Tiers',
            'category': 'Wedding',
            'description': 'Three-tier wedding cake: pistachio sponge with fresh raspberry jam, whipped white chocolate ganache, and fondant-finished tiers with handcrafted sugar roses. Serves 60.',
            'servings': 60, 'prep_mins': 480, 'bake_mins': 40, 'base_price': 495.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 6.0, 'cups'), ('Pistachios (Raw, Shelled)', 2.0, 'cups'),
                ('Granulated Sugar', 5.0, 'cups'), ('Unsalted Butter (European)', 3.0, 'cups'),
                ('Eggs (Large AA)', 10.0, 'each'), ('Whole Milk', 2.0, 'cups'),
                ('Baking Powder (alum-free)', 3.0, 'tsp'), ('Fine Sea Salt', 1.0, 'tsp'),
                ('Almond Extract', 1.0, 'tsp'), ('Valrhona White Chocolate', 2.0, 'lbs'),
                ('Heavy Cream (36%)', 4.0, 'cups'), ('Freeze-Dried Raspberries', 3.0, 'oz'),
                ('Fondant (White, Premium)', 10.0, 'lbs'), ('Gum Paste', 2.0, 'lbs'),
                ('Food Coloring Gel Set', 1.0, 'each'), ('Luster Dust (Assorted)', 2.0, 'each'),
                ('Edible Gold Dust', 2.0, 'each'),
            ],
            'tools': ['Round Cake Pan 6"','Round Cake Pan 8"','Round Cake Pan 10"','Round Cake Pan 12"',
                      'KitchenAid 7qt Commercial Mixer','Hobart 20qt Floor Mixer','Digital Kitchen Scale',
                      'Turntable (Ateco Heavy)','Cake Smoother / Icing Comb','Fondant Smoother',
                      'Rolling Pin (French)','Fondant Mat (Non-stick)','Flower Nail Set',
                      'Petal Veiner & Cutter Set','Offset Spatula (9")','Offset Spatula (4")',
                      'Cake Board (10" round)','Cake Board (12" round)','Cake Drum (14" round)',
                      'Serrated Bread Knife (10")','Airbrush Kit (Iwata)'],
        },
        {
            'name': 'Black Forest Gateau',
            'category': 'Cake',
            'description': 'Black cocoa sponge with Morello cherry compote, kirsch syrup, and clouds of freshly whipped cream. Chocolate shavings and glazed cherries on top.',
            'servings': 14, 'prep_mins': 90, 'bake_mins': 30, 'base_price': 98.00,
            'ingredients': [
                ('Black Cocoa Powder', 0.75, 'cups'), ('Cake Flour (High-Protein)', 2.0, 'cups'),
                ('Granulated Sugar', 2.0, 'cups'), ('Eggs (Large AA)', 4.0, 'each'),
                ('Unsalted Butter (European)', 0.75, 'cups'), ('Buttermilk', 1.0, 'cups'),
                ('Baking Soda', 1.5, 'tsp'), ('Baking Powder (alum-free)', 0.5, 'tsp'),
                ('Fine Sea Salt', 0.5, 'tsp'), ('Heavy Cream (36%)', 3.0, 'cups'),
                ('Dried Cherries', 1.0, 'cups'), ('Valrhona Dark Chocolate 70%', 0.5, 'lbs'),
                ('Pure Vanilla Extract', 1.0, 'tsp'), ('Powdered Sugar (10X)', 0.5, 'cups'),
            ],
            'tools': ['Round Cake Pan 8"','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Turntable (Ateco Heavy)','Cake Smoother / Icing Comb','Offset Spatula (9")',
                      'Bench Scraper','Serrated Bread Knife (10")','Cake Leveler / Slicer',
                      'Wire Cooling Rack (half-sheet)','Piping Tips Set (Ateco)','Piping Bags (16-inch)',
                      'Cake Board (10" round)'],
        },
        {
            'name': 'Earl Grey & Honey Chiffon Cake',
            'category': 'Cake',
            'description': 'Earl Grey-infused chiffon layers with whipped honey mascarpone, fresh orange curd, and a candied citrus crown.',
            'servings': 12, 'prep_mins': 80, 'bake_mins': 35, 'base_price': 110.00,
            'ingredients': [
                ('Cake Flour (High-Protein)', 2.0, 'cups'), ('Granulated Sugar', 1.5, 'cups'),
                ('Eggs (Large AA)', 5.0, 'each'), ('Cream of Tartar', 0.5, 'tsp'),
                ('Whole Milk', 0.75, 'cups'), ('Honey (Wildflower)', 0.5, 'cups'),
                ('Mascarpone', 0.75, 'lbs'), ('Heavy Cream (36%)', 1.5, 'cups'),
                ('Orange Blossom Water', 1.0, 'tbsp'), ('Fine Sea Salt', 0.25, 'tsp'),
                ('Baking Powder (alum-free)', 1.5, 'tsp'), ('Turbinado Sugar', 0.25, 'cups'),
            ],
            'tools': ['Round Cake Pan 8"','KitchenAid 7qt Commercial Mixer','Digital Kitchen Scale',
                      'Rubber Spatula (High-Temp)','Hand Whisk (12")','Turntable (Ateco Heavy)',
                      'Offset Spatula (9")','Cake Smoother / Icing Comb','Wire Cooling Rack (half-sheet)',
                      'Cake Board (10" round)','Kitchen Torch (Bernzomatic)'],
        },
        {
            'name': 'Classic Tarte Tatin',
            'category': 'Pastry',
            'description': 'Upside-down caramelized apple tart in buttery rough puff pastry. Amber Demerara caramel, salted butter, and perfectly softened apples. Served warm with crème fraiche.',
            'servings': 8, 'prep_mins': 60, 'bake_mins': 40, 'base_price': 48.00,
            'ingredients': [
                ('All-Purpose Flour', 2.0, 'cups'), ('Unsalted Butter (European)', 1.0, 'cups'),
                ('Granulated Sugar', 1.0, 'cups'), ('Demerara Sugar', 0.5, 'cups'),
                ('Fine Sea Salt', 0.5, 'tsp'), ('Fleur de Sel', 0.5, 'tsp'),
                ('Cream of Tartar', 0.25, 'tsp'), ('Heavy Cream (36%)', 0.25, 'cups'),
                ('Whole Vanilla Beans', 1.0, 'each'),
            ],
            'tools': ['Tart Pan 9" (removable)','Candy/Sugar Thermometer','Digital Kitchen Scale',
                      'Rolling Pin (French)','Bench Scraper','Pastry Cutter (Fluted)',
                      'Bain-Marie / Double Boiler','Instant-Read Thermometer','Oven Thermometer',
                      'Half Sheet Pan (18x13")'],
        },
        {
            'name': 'Beurre Croissants (Laminated)',
            'category': 'Viennoiserie',
            'description': 'Classic laminated croissants with 27 buttery layers. 84% fat European butter locked into a yeasted dough through four double turns. Golden, shattering exterior with honeycomb crumb.',
            'servings': 12, 'prep_mins': 720, 'bake_mins': 20, 'base_price': 28.00,
            'ingredients': [
                ('Bread Flour', 4.0, 'cups'), ('Granulated Sugar', 0.25, 'cups'),
                ('Fine Sea Salt', 1.5, 'tsp'), ('Unsalted Butter (European)', 2.5, 'cups'),
                ('Whole Milk', 1.25, 'cups'), ('Eggs (Large AA)', 2.0, 'each'),
            ],
            'tools': ['Rolling Pin (French)','Bench Scraper','Digital Kitchen Scale',
                      'Proofing Box / Cabinet','Half Sheet Pan (18x13")','Instant-Read Thermometer',
                      'Oven Thermometer','Pastry Cutter (Fluted)','Measuring Cup Set (Dry)',
                      'Measuring Spoon Set'],
        },
        {
            'name': 'Creme Brulee Tart',
            'category': 'Pastry',
            'description': 'Crisp pate sucree shell filled with silky vanilla creme brulee custard, torched Demerara sugar crust, finished with edible gold dust and seasonal berries.',
            'servings': 10, 'prep_mins': 60, 'bake_mins': 45, 'base_price': 58.00,
            'ingredients': [
                ('All-Purpose Flour', 1.5, 'cups'), ('Powdered Sugar (10X)', 0.5, 'cups'),
                ('Unsalted Butter (European)', 0.5, 'cups'), ('Eggs (Large AA)', 3.0, 'each'),
                ('Heavy Cream (36%)', 2.5, 'cups'), ('Granulated Sugar', 0.5, 'cups'),
                ('Demerara Sugar', 0.5, 'cups'), ('Whole Vanilla Beans', 2.0, 'each'),
                ('Fine Sea Salt', 0.25, 'tsp'), ('Edible Gold Dust', 1.0, 'each'),
            ],
            'tools': ['Tart Pan 9" (removable)','Digital Kitchen Scale','Rolling Pin (French)',
                      'Bench Scraper','Pastry Cutter (Fluted)','Bain-Marie / Double Boiler',
                      'Instant-Read Thermometer','Kitchen Torch (Bernzomatic)','Candy/Sugar Thermometer',
                      'Wire Cooling Rack (half-sheet)','Measuring Spoon Set'],
        },
    ]

    for r in RECIPE_SEED:
        _seed_recipe(
            r['name'], r['category'], r['description'], r['servings'],
            r['prep_mins'], r['bake_mins'], r['base_price'],
            r['ingredients'], r['tools']
        )

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
@app.after_request
def security_headers(resp):
    resp.headers['X-Frame-Options'] = 'SAMEORIGIN'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-XSS-Protection'] = '1; mode=block'
    resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    resp.headers['Permissions-Policy'] = 'geolocation=(), microphone=()'
    return resp

@app.route('/robots.txt')
def robots_txt():
    return app.response_class(
        "User-agent: *\nAllow: /\nDisallow: /dashboard\nDisallow: /admin\nSitemap: https://sweet-spot-cakes.up.railway.app/sitemap.xml\n",
        mimetype='text/plain'
    )

@app.route('/sitemap.xml')
def sitemap_xml():
    pages = ['/', '/order', '/join', '/menu']
    urls = ''.join(f'<url><loc>https://sweet-spot-cakes.up.railway.app{p}</loc></url>' for p in pages)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return app.response_class(xml, mimetype='application/xml')

@app.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr or 'unknown'
    if request.method == 'POST' and _rate_limit(f'login:{ip}', max_req=10, window=60):
        flash('Too many login attempts. Please wait a minute.', 'error')
        return render_template('login.html'), 429
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
    notify   = request.args.get('notify', '')
    photos   = db.execute('SELECT * FROM order_photos WHERE order_id=? ORDER BY created', (order_id,)).fetchall()
    return render_template('order_detail.html', order=order, items=items,
                           receipts=receipts, notify=notify, photos=photos,
                           stripe_pk=STRIPE_PK, bakery=BAKERY_NAME)

@app.route('/orders/<int:order_id>/upload-photo', methods=['POST'])
@login_required
def order_upload_photo(order_id):
    db = get_db()
    url     = request.form.get('photo_url', '').strip()
    caption = request.form.get('caption', '').strip()
    if not url:
        flash('Please provide a photo URL.', 'error')
        return redirect(url_for('order_detail', order_id=order_id))
    db.execute('INSERT INTO order_photos(order_id, filename, caption) VALUES(?,?,?)',
               (order_id, url, caption))
    db.commit()
    flash('Reference photo added.', 'success')
    return redirect(url_for('order_detail', order_id=order_id))

@app.route('/orders/<int:order_id>/delete-photo/<int:photo_id>', methods=['POST'])
@login_required
def order_delete_photo(order_id, photo_id):
    db = get_db()
    db.execute('DELETE FROM order_photos WHERE id=? AND order_id=?', (photo_id, order_id))
    db.commit()
    return redirect(url_for('order_detail', order_id=order_id))

@app.route('/orders/<int:order_id>/add-item', methods=['POST'])
@login_required
def order_add_item(order_id):
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order: return jsonify({'error': 'not found'}), 404
    name   = request.form.get('name', '').strip()
    try:
        qty = int(request.form.get('quantity') or 1)
    except (ValueError, TypeError):
        qty = 1
    try:
        price = float(request.form.get('unit_price') or 0)
    except (ValueError, TypeError):
        price = 0
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
    amount_type = request.form.get('amount_type', 'balance')  # balance, deposit, or custom
    if amount_type == 'custom':
        try:
            custom_amount = float(request.form.get('custom_amount', 0))
        except (ValueError, TypeError):
            custom_amount = order['balance_due'] or 0
        amount_cents = int(custom_amount * 100)
        label = f'Custom Amount (${custom_amount:.2f})'
    elif amount_type == 'deposit':
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
    try:
        amount = float(request.form.get('amount') or 0)
    except (ValueError, TypeError):
        amount = 0
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

# ── Register (POS screen) ────────────────────────────────────────────────
from flask import Response as _Response

@app.route('/orders/<int:order_id>/register')
@login_required
def order_register(order_id):
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('orders'))
    receipts = db.execute('SELECT * FROM receipts WHERE order_id=? ORDER BY created', (order_id,)).fetchall()
    return render_template('register.html',
                           order=order,
                           receipts=receipts,
                           bakery=BAKERY_NAME,
                           stripe_configured=bool(stripe.api_key),
                           square_configured=bool(SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID))

# ── Square Checkout ──────────────────────────────────────────────────
@app.route('/orders/<int:order_id>/square-demo')
@login_required
def square_demo(order_id):
    """Simulated Square checkout page for demo/testing."""
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('orders'))
    amount = float(request.args.get('amount', order['balance_due'] or 0))
    return render_template('square_demo.html',
                           order=order,
                           amount=amount,
                           bakery=BAKERY_NAME)

@app.route('/orders/<int:order_id>/square-demo-confirm', methods=['POST'])
@login_required
def square_demo_confirm(order_id):
    """Records demo Square payment as if it went through."""
    db = get_db()
    amount = float(request.form.get('amount', 0))
    if amount > 0:
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        db.execute('INSERT INTO receipts(order_id,amount,method,notes) VALUES(?,?,?,?)',
                   (order_id, amount, 'square', 'Square DEMO payment'))
        new_deposit = (order['deposit_paid'] or 0) + amount
        new_balance = max(0, (order['total'] or 0) - new_deposit)
        paid_full = 1 if new_balance <= 0.01 else 0
        db.execute('UPDATE orders SET deposit_paid=?,balance_due=?,paid_in_full=? WHERE id=?',
                   (new_deposit, new_balance, paid_full, order_id))
        db.commit()
        flash(f'⬛ Square DEMO payment of ${amount:.2f} recorded! ✅', 'success')
    return redirect(url_for('order_register', order_id=order_id))

@app.route('/orders/<int:order_id>/square-checkout', methods=['POST'])
@login_required
def square_checkout(order_id):
    import urllib.request as _ureq
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': 'not found'}), 404
    if not SQUARE_ACCESS_TOKEN or not SQUARE_LOCATION_ID:
        flash('Square not configured. Add SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID to Railway env vars.', 'error')
        return redirect(url_for('order_register', order_id=order_id))
    try:
        custom_amount = float(request.form.get('custom_amount') or order['balance_due'] or 0)
        if custom_amount <= 0:
            flash('Nothing to charge!', 'info')
            return redirect(url_for('order_register', order_id=order_id))
        amount_cents = int(custom_amount * 100)
        base = request.host_url.rstrip('/')
        idempotency_key = secrets.token_hex(16)
        payload = json.dumps({
            'idempotency_key': idempotency_key,
            'order': {
                'location_id': SQUARE_LOCATION_ID,
                'reference_id': order['order_number'],
                'customer_id': None,
                'line_items': [{
                    'name': f'{BAKERY_NAME} — Order {order["order_number"]}',
                    'quantity': '1',
                    'base_price_money': {'amount': amount_cents, 'currency': 'USD'}
                }]
            },
            'checkout_options': {
                'redirect_url': f'{base}/orders/{order_id}/square-success',
                'merchant_support_email': ADMIN_EMAIL,
                'allow_tipping': False,
            },
            'pre_populated_data': {
                'buyer_email': order['customer_email'] or ''
            }
        }).encode()
        req = _ureq.Request(
            f'{SQUARE_BASE_URL}/v2/online-checkout/payment-links',
            data=payload,
            headers={
                'Authorization': f'Bearer {SQUARE_ACCESS_TOKEN}',
                'Content-Type': 'application/json',
                'Square-Version': '2024-01-18'
            }
        )
        with _ureq.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        url = data.get('payment_link', {}).get('url')
        if not url:
            raise ValueError(f'No URL in Square response: {data}')
        # Store pending amount in session for success handler
        session['sq_pending'] = {'order_id': order_id, 'amount': custom_amount, 'idempotency_key': idempotency_key}
        return redirect(url)
    except Exception as e:
        flash(f'Square error: {e}', 'error')
        return redirect(url_for('order_register', order_id=order_id))

@app.route('/orders/<int:order_id>/square-success')
@login_required
def square_success(order_id):
    db = get_db()
    pending = session.pop('sq_pending', {})
    amount = pending.get('amount', 0)
    if amount > 0 and pending.get('order_id') == order_id:
        order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        db.execute('INSERT INTO receipts(order_id,amount,method,notes) VALUES(?,?,?,?)',
                   (order_id, amount, 'square', f'Square checkout'))
        new_deposit = (order['deposit_paid'] or 0) + amount
        new_balance = max(0, (order['total'] or 0) - new_deposit)
        paid_full = 1 if new_balance <= 0.01 else 0
        db.execute('UPDATE orders SET deposit_paid=?,balance_due=?,paid_in_full=? WHERE id=?',
                   (new_deposit, new_balance, paid_full, order_id))
        db.commit()
        flash(f'Square payment of ${amount:.2f} received! ✅', 'success')
    else:
        flash('Square payment received — please verify amount manually.', 'warning')
    return redirect(url_for('order_register', order_id=order_id))

# ── Inventory ──────────────────────────────────────────────────────────────

# ── Order Delete (admin only) ──────────────────────────────────────────────
@app.route('/orders/<int:order_id>/delete', methods=['POST'])
@login_required
def order_delete(order_id):
    if session.get('role') != 'admin':
        flash('Admin access required to delete orders.', 'error')
        return redirect(url_for('order_detail', order_id=order_id))
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('orders'))
    order_number = order['order_number']
    db.execute('DELETE FROM receipts WHERE order_id=?', (order_id,))
    db.execute('DELETE FROM order_items WHERE order_id=?', (order_id,))
    db.execute('DELETE FROM orders WHERE id=?', (order_id,))
    db.commit()
    flash(f'Order {order_number} has been deleted.', 'success')
    return redirect(url_for('orders'))

@app.route('/inventory')
@login_required
def inventory():
    db = get_db()
    ingredients = db.execute('''
        SELECT i.*, s.name as supplier_name
        FROM ingredients i LEFT JOIN suppliers s ON i.supplier_id=s.id
        ORDER BY i.name
    ''').fetchall()
    suppliers = db.execute('SELECT id, name FROM suppliers WHERE active=1 ORDER BY name').fetchall()
    return render_template('inventory.html', ingredients=ingredients, suppliers=suppliers, bakery=BAKERY_NAME)

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

@app.route('/inventory/<int:item_id>/delete', methods=['POST'])
@login_required
def inventory_delete(item_id):
    db = get_db()
    item = db.execute('SELECT name FROM ingredients WHERE id=?', (item_id,)).fetchone()
    if not item:
        flash('Ingredient not found.', 'error')
        return redirect(url_for('inventory'))
    db.execute('DELETE FROM recipe_ingredients WHERE ingredient_id=?', (item_id,))
    db.execute('DELETE FROM ingredients WHERE id=?', (item_id,))
    db.commit()
    flash(f'"{item["name"]}" deleted from inventory.', 'success')
    return redirect(url_for('inventory'))

@app.route('/inventory/<int:item_id>/set-supplier', methods=['POST'])
@login_required
def inventory_set_supplier(item_id):
    db = get_db()
    supplier_id = request.form.get('supplier_id') or None
    db.execute('UPDATE ingredients SET supplier_id=? WHERE id=?', (supplier_id, item_id))
    db.commit()
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


# ── Tools & Equipment ─────────────────────────────────────────────────────────
@app.route('/tools')
@login_required
def tools_list():
    db = get_db()
    _ensure_kitchen_tables(db)
    q = request.args.get('q', '').strip()
    cat = request.args.get('cat', '')
    sql = 'SELECT * FROM tools WHERE active=1'
    params = []
    if q:   sql += ' AND name LIKE ?'; params.append(f'%{q}%')
    if cat: sql += ' AND category=?';  params.append(cat)
    sql += ' ORDER BY category, name'
    all_tools = db.execute(sql, params).fetchall()
    categories = [r['category'] for r in db.execute('SELECT DISTINCT category FROM tools WHERE active=1 ORDER BY category').fetchall()]
    return render_template('tools.html', tools=all_tools, categories=categories, q=q, cat=cat, bakery=BAKERY_NAME)

@app.route('/tools/add', methods=['POST'])
@login_required
def tools_add():
    db = get_db()
    db.execute('INSERT INTO tools(name,category,quantity,unit,location,notes) VALUES(?,?,?,?,?,?)',
               (request.form['name'], request.form.get('category','Equipment'),
                float(request.form.get('quantity', 1)), request.form.get('unit','each'),
                request.form.get('location',''), request.form.get('notes','')))
    db.commit()
    flash('Tool added!', 'success')
    return redirect(url_for('tools_list'))

@app.route('/tools/<int:tool_id>/edit', methods=['POST'])
@login_required
def tools_edit(tool_id):
    db = get_db()
    db.execute('UPDATE tools SET name=?,category=?,quantity=?,unit=?,location=?,notes=? WHERE id=?',
               (request.form['name'], request.form.get('category','Equipment'),
                float(request.form.get('quantity', 1)), request.form.get('unit','each'),
                request.form.get('location',''), request.form.get('notes',''), tool_id))
    db.commit()
    flash('Tool updated!', 'success')
    return redirect(url_for('tools_list'))

@app.route('/tools/<int:tool_id>/delete', methods=['POST'])
@login_required
def tools_delete(tool_id):
    db = get_db()
    db.execute('UPDATE tools SET active=0 WHERE id=?', (tool_id,))
    db.commit()
    flash('Tool removed.', 'success')
    return redirect(url_for('tools_list'))

# ── Kitchen Production View ───────────────────────────────────────────────────
def _run_migrations(db):
    """Safe schema migrations for all tables — ALTER TABLE ADD COLUMN is idempotent via try/except."""
    migrations = {
        'orders': [
            ('type',         "TEXT DEFAULT 'custom'"),
            ('special_notes', "TEXT DEFAULT ''"),
            ('deposit_paid',  'REAL DEFAULT 0'),
            ('balance_due',   'REAL DEFAULT 0'),
            ('stripe_pi',     "TEXT DEFAULT ''"),
            ('paid_in_full',  'INTEGER DEFAULT 0'),
            ('discount',      'REAL DEFAULT 0'),
        ],
        'order_items': [
            ('customizations', "TEXT DEFAULT ''"),
            ('description',    "TEXT DEFAULT ''"),
        ],
        'recipes': [
            ('prep_mins',   'INTEGER DEFAULT 60'),
            ('bake_mins',   'INTEGER DEFAULT 45'),
            ('image_url',   "TEXT DEFAULT ''"),
            ('description', "TEXT DEFAULT ''"),
            ('active',      'INTEGER DEFAULT 1'),
        ],
        'ingredients': [
            ('location',      "TEXT DEFAULT ''"),
            ('notes',         "TEXT DEFAULT ''"),
            ('supplier_id',   'INTEGER'),
            ('reorder_level', 'REAL DEFAULT 5'),
            ('cost_per_unit', 'REAL DEFAULT 0'),
        ],
        'tools': [
            ('location', "TEXT DEFAULT ''"),
            ('notes',    "TEXT DEFAULT ''"),
            ('quantity', 'INTEGER DEFAULT 1'),
            ('unit',     "TEXT DEFAULT 'each'"),
            ('active',   'INTEGER DEFAULT 1'),
            ('category', "TEXT DEFAULT 'Equipment'"),
            ('created',  "TEXT DEFAULT (datetime('now'))"),
        ],
        'customers': [
            ('birthday',  "TEXT DEFAULT ''"),
            ('stripe_id', "TEXT DEFAULT ''"),
            ('address',   "TEXT DEFAULT ''"),
        ],
        'users': [
            ('pin',         "TEXT DEFAULT ''"),
            ('hourly_rate', 'REAL DEFAULT 15.0'),
        ],
        'employees': [
            ('pin',         "TEXT DEFAULT ''"),
            ('hourly_rate', 'REAL DEFAULT 15.0'),
            ('notes',       "TEXT DEFAULT ''"),
        ],
        'suppliers': [
            ('contact', "TEXT DEFAULT ''"),
            ('email',   "TEXT DEFAULT ''"),
            ('phone',   "TEXT DEFAULT ''"),
            ('address', "TEXT DEFAULT ''"),
            ('notes',   "TEXT DEFAULT ''"),
            ('active',  'INTEGER DEFAULT 1'),
            ('created', "TEXT DEFAULT (datetime('now'))"),
        ],
        'purchase_orders': [
            ('status',      "TEXT DEFAULT 'pending'"),
            ('total',       'REAL DEFAULT 0'),
            ('notes',       "TEXT DEFAULT ''"),
            ('ordered_at',  'TEXT'),
            ('received_at', 'TEXT'),
            ('created',     "TEXT DEFAULT (datetime('now'))"),
        ],
    }
    for table, cols in migrations.items():
        for col, defn in cols:
            try:
                db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {defn}')
            except Exception:
                pass  # column already exists — fine
    db.commit()

def _ensure_kitchen_tables(db):
    """Ensure tools/recipe_tools/purchase_orders/po_items/suppliers tables exist and all columns are present."""
    # Suppliers table
    db.execute('''
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
        )''')
    # Purchase orders
    db.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            status      TEXT DEFAULT 'pending',
            total       REAL DEFAULT 0,
            notes       TEXT DEFAULT '',
            ordered_at  TEXT,
            received_at TEXT,
            created     TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
        )''')
    # PO line items
    db.execute('''
        CREATE TABLE IF NOT EXISTS po_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id         INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL,
            quantity      REAL NOT NULL,
            unit_cost     REAL NOT NULL,
            FOREIGN KEY(po_id) REFERENCES purchase_orders(id),
            FOREIGN KEY(ingredient_id) REFERENCES ingredients(id)
        )''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, category TEXT DEFAULT 'Equipment',
            quantity INTEGER DEFAULT 1, unit TEXT DEFAULT 'each',
            location TEXT DEFAULT '', notes TEXT DEFAULT '',
            active INTEGER DEFAULT 1, created TEXT DEFAULT (datetime('now'))
        )''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS recipe_tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL, tool_id INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            FOREIGN KEY(recipe_id) REFERENCES recipes(id),
            FOREIGN KEY(tool_id) REFERENCES tools(id)
        )''')
    _run_migrations(db)
    db.commit()

@app.route('/kitchen')
@login_required
def kitchen():
    """Baker production view: all active orders with recipes, ingredients & tools."""
    db = get_db()
    _ensure_kitchen_tables(db)
    statuses = ['pending', 'confirmed', 'in_production']
    placeholders = ','.join('?' * len(statuses))
    orders = db.execute(
        f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY pickup_date ASC, pickup_time ASC",
        statuses
    ).fetchall()

    production_orders = []
    for order in orders:
        items = db.execute(
            'SELECT oi.*, r.prep_mins, r.bake_mins, r.description as rdesc '
            'FROM order_items oi LEFT JOIN recipes r ON oi.recipe_id=r.id '
            'WHERE oi.order_id=?', (order['id'],)
        ).fetchall()

        enriched_items = []
        for item in items:
            ingredients, tools = [], []
            if item['recipe_id']:
                ingredients = db.execute(
                    'SELECT ri.quantity, ri.unit, i.name, i.location, i.quantity as stock '
                    'FROM recipe_ingredients ri '
                    'JOIN ingredients i ON ri.ingredient_id=i.id '
                    'WHERE ri.recipe_id=? ORDER BY i.name',
                    (item['recipe_id'],)
                ).fetchall()
                tools = db.execute(
                    'SELECT t.name, t.category, t.location, t.notes '
                    'FROM recipe_tools rt '
                    'JOIN tools t ON rt.tool_id=t.id '
                    'WHERE rt.recipe_id=? AND t.active=1 ORDER BY t.category, t.name',
                    (item['recipe_id'],)
                ).fetchall()
            enriched_items.append({'item': item, 'ingredients': ingredients, 'tools': tools})

        production_orders.append({'order': order, 'order_items': enriched_items})

    return render_template('kitchen.html', production_orders=production_orders, bakery=BAKERY_NAME)

@app.route('/kitchen/order/<int:order_id>')
@login_required
def kitchen_order(order_id):
    """Single order production sheet — full consolidated ingredient + tool list."""
    db = get_db()
    _ensure_kitchen_tables(db)
    order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('kitchen'))

    items = db.execute(
        'SELECT oi.*, r.prep_mins, r.bake_mins, r.description as rdesc '
        'FROM order_items oi LEFT JOIN recipes r ON oi.recipe_id=r.id '
        'WHERE oi.order_id=?', (order_id,)
    ).fetchall()

    enriched_items = []
    all_ingredients = {}
    all_tools = {}

    for item in items:
        qty_mult = item['quantity'] or 1
        ingredients, tools = [], []
        if item['recipe_id']:
            raw_ingr = db.execute(
                'SELECT ri.quantity, ri.unit, i.name, i.location, i.quantity as stock '
                'FROM recipe_ingredients ri '
                'JOIN ingredients i ON ri.ingredient_id=i.id '
                'WHERE ri.recipe_id=? ORDER BY i.name',
                (item['recipe_id'],)
            ).fetchall()
            raw_tools = db.execute(
                'SELECT t.name, t.category, t.location, t.notes '
                'FROM recipe_tools rt '
                'JOIN tools t ON rt.tool_id=t.id '
                'WHERE rt.recipe_id=? AND t.active=1 ORDER BY t.category, t.name',
                (item['recipe_id'],)
            ).fetchall()
            for ri in raw_ingr:
                needed = round(ri['quantity'] * qty_mult, 3)
                if ri['name'] in all_ingredients:
                    all_ingredients[ri['name']]['needed'] += needed
                else:
                    all_ingredients[ri['name']] = {
                        'needed': needed, 'unit': ri['unit'],
                        'location': ri['location'], 'stock': ri['stock']
                    }
            for t in raw_tools:
                all_tools[t['name']] = {'category': t['category'], 'location': t['location'], 'notes': t['notes']}
            ingredients = raw_ingr
            tools = raw_tools
        enriched_items.append({'item': item, 'ingredients': ingredients, 'tools': tools})

    return render_template('kitchen_order.html',
                           order=order, items=enriched_items,
                           all_ingredients=all_ingredients,
                           all_tools=all_tools,
                           bakery=BAKERY_NAME)

@app.route('/api/tools')
@login_required
def api_tools():
    db = get_db()
    _ensure_kitchen_tables(db)
    tools = db.execute('SELECT id, name, category FROM tools WHERE active=1 ORDER BY category, name').fetchall()
    return jsonify([dict(t) for t in tools])

@app.route('/api/recipe-tools/<int:recipe_id>', methods=['GET'])
@login_required
def api_recipe_tools_get(recipe_id):
    db = get_db()
    tools = db.execute(
        'SELECT rt.id, t.id as tool_id, t.name, t.category FROM recipe_tools rt '
        'JOIN tools t ON rt.tool_id=t.id WHERE rt.recipe_id=?', (recipe_id,)
    ).fetchall()
    return jsonify([dict(t) for t in tools])

@app.route('/api/recipe-tools/<int:recipe_id>', methods=['POST'])
@login_required
def api_recipe_tools_add(recipe_id):
    db = get_db()
    data = request.get_json()
    tool_id = data.get('tool_id')
    if not tool_id:
        return jsonify({'error': 'tool_id required'}), 400
    existing = db.execute('SELECT id FROM recipe_tools WHERE recipe_id=? AND tool_id=?', (recipe_id, tool_id)).fetchone()
    if existing:
        return jsonify({'ok': True, 'message': 'Already linked'})
    db.execute('INSERT INTO recipe_tools(recipe_id, tool_id) VALUES(?,?)', (recipe_id, tool_id))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/recipe-tools/remove/<int:rt_id>', methods=['POST'])
@login_required
def api_recipe_tools_remove(rt_id):
    db = get_db()
    db.execute('DELETE FROM recipe_tools WHERE id=?', (rt_id,))
    db.commit()
    return jsonify({'ok': True})


# ── Suppliers ─────────────────────────────────────────────────────────────────
@app.route('/suppliers')
@login_required
def suppliers():
    db = get_db()
    all_suppliers = db.execute("SELECT * FROM suppliers WHERE active=1 ORDER BY name").fetchall()

    # For each supplier: linked inventory items + purchase order history
    supplier_data = []
    for s in all_suppliers:
        # Inventory items linked to this supplier
        items = db.execute(
            '''SELECT name, unit, quantity, reorder_level, cost_per_unit
               FROM ingredients WHERE supplier_id=? ORDER BY name''',
            (s['id'],)
        ).fetchall()

        # Purchase order history with line items
        pos = db.execute(
            '''SELECT po.id, po.status, po.total, po.ordered_at, po.received_at, po.notes
               FROM purchase_orders po
               WHERE po.supplier_id=?
               ORDER BY po.created DESC LIMIT 10''',
            (s['id'],)
        ).fetchall()

        po_list = []
        for po in pos:
            po_items = db.execute(
                '''SELECT i.name, pi.quantity, pi.unit_cost, i.unit
                   FROM po_items pi JOIN ingredients i ON i.id=pi.ingredient_id
                   WHERE pi.po_id=?''',
                (po['id'],)
            ).fetchall()
            po_list.append({'po': po, 'items': po_items})

        # Total spent with this supplier
        # Use PO history if available, otherwise estimate from inventory value (qty * cost)
        po_total = db.execute(
            '''SELECT COALESCE(SUM(total),0) FROM purchase_orders
               WHERE supplier_id=? AND status=\"received\"''',
            (s['id'],)
        ).fetchone()[0]
        inv_total = db.execute(
            '''SELECT COALESCE(SUM(quantity * cost_per_unit),0)
               FROM ingredients WHERE supplier_id=? AND cost_per_unit > 0''',
            (s['id'],)
        ).fetchone()[0]
        total_spent = po_total if po_total > 0 else inv_total

        supplier_data.append({
            'supplier': dict(s),
            'inv_items': [dict(r) for r in items],
            'po_orders': [{'po': dict(p['po']), 'items': [dict(i) for i in p['items']]} for p in po_list],
            'total_spent': total_spent
        })

    # All ingredients for the "add PO" form
    all_ingredients = [dict(r) for r in db.execute('SELECT id, name, unit, cost_per_unit FROM ingredients ORDER BY name').fetchall()]

    return render_template('suppliers.html', supplier_data=supplier_data,
                           all_ingredients=all_ingredients, bakery=BAKERY_NAME)

@app.route('/suppliers/<int:supplier_id>/auto-po')
@login_required
def supplier_auto_po(supplier_id):
    """Show a pre-filled purchase order for all low-stock items from this supplier."""
    db = get_db()
    supplier = db.execute('SELECT * FROM suppliers WHERE id=? AND active=1', (supplier_id,)).fetchone()
    if not supplier:
        flash('Supplier not found.', 'error')
        return redirect(url_for('suppliers'))

    # Items linked to this supplier that are at or below reorder level
    rows = db.execute(
        '''SELECT i.id, i.name, i.unit, i.quantity, i.reorder_level,
                  i.cost_per_unit,
                  (SELECT pi.unit_cost FROM po_items pi
                   JOIN purchase_orders po ON po.id = pi.po_id
                   WHERE pi.ingredient_id = i.id
                   ORDER BY po.created DESC LIMIT 1) AS last_price
           FROM ingredients i
           WHERE i.supplier_id = ?
             AND i.reorder_level > 0
             AND i.quantity <= i.reorder_level
           ORDER BY i.name''',
        (supplier_id,)
    ).fetchall()

    low_items = [dict(r) for r in rows]
    return render_template('auto_po.html', supplier=dict(supplier),
                           low_items=low_items, bakery=BAKERY_NAME)


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

@app.route('/suppliers/<int:supplier_id>/purchase', methods=['POST'])
@login_required
def supplier_purchase(supplier_id):
    """Log a purchase/delivery from a supplier."""
    db = get_db()
    notes      = request.form.get('notes', '')
    status     = request.form.get('status', 'received')
    ing_ids    = request.form.getlist('ingredient_id')
    quantities = request.form.getlist('qty')
    unit_costs = request.form.getlist('unit_cost')

    if not ing_ids:
        flash('Add at least one item.', 'error')
        return redirect(url_for('suppliers'))

    total = 0.0
    line_items = []
    for ing_id, qty, uc in zip(ing_ids, quantities, unit_costs):
        try:
            qty    = float(qty)
            uc     = float(uc)
            if qty <= 0: continue
            total += qty * uc
            line_items.append((int(ing_id), qty, uc))
        except (ValueError, TypeError):
            continue

    if not line_items:
        flash('No valid items.', 'error')
        return redirect(url_for('suppliers'))

    now = datetime.date.today().isoformat()
    cur = db.execute(
        '''INSERT INTO purchase_orders(supplier_id, status, total, notes, ordered_at, received_at)
           VALUES (?,?,?,?,?,?)''',
        (supplier_id, status, total, notes, now, now if status == 'received' else None)
    )
    po_id = cur.lastrowid

    for ing_id, qty, uc in line_items:
        db.execute('INSERT INTO po_items(po_id, ingredient_id, quantity, unit_cost) VALUES(?,?,?,?)',
                   (po_id, ing_id, qty, uc))
        if status == 'received':
            # Update inventory quantity and cost_per_unit
            db.execute('UPDATE ingredients SET quantity=quantity+?, cost_per_unit=? WHERE id=?',
                       (qty, uc, ing_id))

    db.commit()
    flash(f'Purchase logged! Total: ${total:.2f}', 'success')
    return redirect(url_for('suppliers'))


@app.route('/suppliers/<int:supplier_id>/delete', methods=['POST'])
@login_required
def supplier_delete(supplier_id):
    db = get_db()
    supplier = db.execute('SELECT name FROM suppliers WHERE id=?', (supplier_id,)).fetchone()
    if not supplier:
        flash('Supplier not found.', 'error')
        return redirect(url_for('suppliers'))
    # Soft delete — keeps referential integrity with ingredients
    db.execute('UPDATE suppliers SET active=0 WHERE id=?', (supplier_id,))
    db.commit()
    flash(f'Supplier "{supplier["name"]}" deleted.', 'success')
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

@app.route('/recipes/<int:recipe_id>/update-ingredient/<int:ri_id>', methods=['POST'])
@login_required
def recipe_update_ingredient(recipe_id, ri_id):
    try:
        qty = float(request.form.get('quantity') or 0)
    except (ValueError, TypeError):
        qty = 0
    if qty > 0:
        db = get_db()
        db.execute('UPDATE recipe_ingredients SET quantity=? WHERE id=? AND recipe_id=?',
                   (qty, ri_id, recipe_id))
        db.commit()
    return redirect(url_for('recipe_detail', recipe_id=recipe_id))

@app.route('/recipes/<int:recipe_id>/remove-ingredient/<int:ri_id>', methods=['POST'])
@login_required
def recipe_remove_ingredient(recipe_id, ri_id):
    db = get_db()
    db.execute('DELETE FROM recipe_ingredients WHERE id=? AND recipe_id=?', (ri_id, recipe_id))
    db.commit()
    flash('Ingredient removed.', 'success')
    return redirect(url_for('recipe_detail', recipe_id=recipe_id))

@app.route('/recipes/<int:recipe_id>/delete', methods=['POST'])
@login_required
def recipe_delete(recipe_id):
    if session.get('role') != 'admin':
        flash('Admin access required.', 'error')
        return redirect(url_for('recipe_detail', recipe_id=recipe_id))
    db = get_db()
    db.execute('DELETE FROM recipe_ingredients WHERE recipe_id=?', (recipe_id,))
    db.execute('DELETE FROM recipe_tools WHERE recipe_id=?', (recipe_id,))
    db.execute('DELETE FROM recipes WHERE id=?', (recipe_id,))
    db.commit()
    flash('Recipe deleted.', 'success')
    return redirect(url_for('recipes'))

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

    expenses_month = db.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date >= ?",
        (month_start,)).fetchone()[0]

    payroll_month = sum(
        (row['hours'] or 0) * (row['hourly_rate'] or 0)
        for row in employee_hours
    )

    profit_month = revenue_month - expenses_month - payroll_month

    expense_by_cat = db.execute('''
        SELECT category, SUM(amount) as total
        FROM expenses WHERE date >= ?
        GROUP BY category ORDER BY total DESC
    ''', (month_start,)).fetchall()

    return render_template('reports.html', revenue_month=revenue_month,
                           orders_month=orders_month, top_items=top_items,
                           revenue_by_day=revenue_by_day, employee_hours=employee_hours,
                           expenses_month=expenses_month, payroll_month=payroll_month,
                           profit_month=profit_month, expense_by_cat=expense_by_cat,
                           month=today.strftime('%B %Y'), bakery=BAKERY_NAME)

# ── Expenses ─────────────────────────────────────────────────────────────────
EXPENSE_CATEGORIES = ['Supplies', 'Ingredients', 'Equipment', 'Packaging', 'Marketing',
                       'Utilities', 'Rent', 'Labor', 'Insurance', 'Other']

@app.route('/expenses')
@login_required
def expenses():
    db  = get_db()
    now = datetime.date.today()
    month = request.args.get('month', now.strftime('%Y-%m'))
    month_start = month + '-01'
    try:
        month_end = (datetime.date.fromisoformat(month_start).replace(day=28)
                     + datetime.timedelta(days=4)).replace(day=1).isoformat()
    except Exception:
        month_end = (now.replace(day=28) + datetime.timedelta(days=4)).replace(day=1).isoformat()

    rows = db.execute('''
        SELECT e.id, e.category, e.description, e.amount, e.date,
               s.name as supplier_name
        FROM expenses e
        LEFT JOIN suppliers s ON s.id = e.supplier_id
        WHERE e.date >= ? AND e.date < ?
        ORDER BY e.date DESC, e.id DESC
    ''', (month_start, month_end)).fetchall()

    total = sum(r['amount'] for r in rows)
    by_category = sorted(
        {cat: sum(r['amount'] for r in rows if r['category'] == cat)
         for cat in {r['category'] for r in rows}}.items(),
        key=lambda x: x[1], reverse=True
    )
    suppliers = db.execute("SELECT id, name FROM suppliers WHERE active=1 ORDER BY name").fetchall()
    return render_template('expenses.html', expenses=rows, total=total,
                           by_category=by_category, month=month,
                           suppliers=suppliers, categories=EXPENSE_CATEGORIES,
                           now=now.isoformat(), bakery=BAKERY_NAME)

@app.route('/expenses/add', methods=['POST'])
@login_required
def expenses_add():
    db = get_db()
    category    = request.form.get('category', 'Supplies')
    description = request.form.get('description', '').strip()
    amount      = float(request.form.get('amount', 0))
    date        = request.form.get('date') or datetime.date.today().isoformat()
    supplier_id = request.form.get('supplier_id') or None
    if not description or amount <= 0:
        flash('Description and a positive amount are required.', 'error')
        return redirect('/expenses')
    db.execute(
        'INSERT INTO expenses(category,description,amount,date,supplier_id) VALUES(?,?,?,?,?)',
        (category, description, amount, date, supplier_id)
    )
    db.commit()
    flash('Expense logged.', 'success')
    return redirect('/expenses')

@app.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def expenses_delete(expense_id):
    db = get_db()
    db.execute('DELETE FROM expenses WHERE id=?', (expense_id,))
    db.commit()
    flash('Expense deleted.', 'success')
    return redirect(request.referrer or '/expenses')

# ── Prep Sheet ────────────────────────────────────────────────────────────────
@app.route('/prep-sheet')
@login_required
def prep_sheet():
    db    = get_db()
    today = datetime.date.today()
    tomorrow  = today + datetime.timedelta(days=1)
    day_after = today + datetime.timedelta(days=2)
    window_end = (today + datetime.timedelta(days=3)).isoformat()

    orders = db.execute('''
        SELECT o.id, o.order_number, o.customer_name, o.pickup_date, o.pickup_time,
               o.special_notes, o.status,
               o.total, o.balance_due, o.paid_in_full
        FROM orders o
        WHERE o.pickup_date >= ? AND o.pickup_date < ?
          AND o.status NOT IN ('cancelled','delivered')
        ORDER BY o.pickup_date, o.pickup_time
    ''', (today.isoformat(), window_end)).fetchall()

    # Build combined ingredient pull list from recipe-linked order items
    ingredient_needs = {}
    for o in orders:
        items = db.execute('''
            SELECT oi.quantity, oi.recipe_id
            FROM order_items oi
            WHERE oi.order_id=? AND oi.recipe_id IS NOT NULL
        ''', (o['id'],)).fetchall()
        for item in items:
            qty     = item['quantity'] or 1
            ingredients = db.execute('''
                SELECT i.name, ri.quantity, ri.unit
                FROM recipe_ingredients ri
                JOIN inventory i ON i.id = ri.inventory_id
                WHERE ri.recipe_id=?
            ''', (item['recipe_id'],)).fetchall()
            for ing in ingredients:
                key = ing['name']
                needed = (ing['quantity'] or 0) * qty
                if key not in ingredient_needs:
                    stock_row = db.execute(
                        'SELECT quantity FROM inventory WHERE name=?', (key,)
                    ).fetchone()
                    ingredient_needs[key] = {
                        'needed': 0,
                        'unit': ing['unit'] or '',
                        'stock': stock_row['quantity'] if stock_row else 0
                    }
                ingredient_needs[key]['needed'] += needed

    ingredient_needs = sorted(ingredient_needs.items(), key=lambda x: x[0])
    return render_template('prep_sheet.html',
                           orders=orders,
                           ingredient_needs=ingredient_needs,
                           today=today.isoformat(),
                           tomorrow=tomorrow.isoformat(),
                           day_after=day_after.isoformat(),
                           bakery=BAKERY_NAME)

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

# ── Public Order (no login required) ──────────────────────────────────────────────
@app.route('/order', methods=['GET', 'POST'])
def public_order():
    if request.method == 'POST':
        db = get_db()
        # Customer info
        cname       = request.form.get('name', '').strip()
        cemail      = request.form.get('email', '').strip().lower()
        cphone      = request.form.get('phone', '').strip()
        pickup_date = request.form.get('pickup_date', '').strip()
        pickup_time = request.form.get('pickup_time', '').strip()
        # Cake details
        size        = request.form.get('size', '').strip()
        flavor      = request.form.get('flavor', '').strip()
        addons      = request.form.getlist('addons')
        message_txt = request.form.get('message_text', '').strip()
        occasion    = request.form.get('occasion', '').strip()
        notes       = request.form.get('special_notes', '').strip()

        if not cname or not pickup_date:
            flash('Please fill in your name and pickup date.', 'error')
            return redirect(url_for('public_order'))

        # Build description
        details = []
        if size:        details.append(f'Size: {size}')
        if flavor:      details.append(f'Flavor: {flavor}')
        if occasion:    details.append(f'Occasion: {occasion}')
        if addons:      details.append(f'Add-ons: {", ".join(addons)}')
        if message_txt: details.append(f'Message on cake: "{message_txt}"')
        if notes:       details.append(f'Notes: {notes}')
        full_notes = '\n'.join(details)

        # Find or create customer
        cust_id = None
        if cemail:
            existing = db.execute('SELECT id FROM customers WHERE email=?', (cemail,)).fetchone()
            if existing:
                cust_id = existing['id']
                if cphone:
                    db.execute('UPDATE customers SET phone=? WHERE id=?', (cphone, cust_id))
            else:
                cur = db.execute('INSERT INTO customers(name,email,phone,notes) VALUES(?,?,?,?)',
                                 (cname, cemail, cphone, 'Online order'))
                cust_id = cur.lastrowid

        # Calculate base price from size selection
        size_prices = {
            '6" Round (serves 8-10)': 45,
            '8" Round (serves 12-16)': 65,
            '10" Round (serves 20-24)': 90,
            '12" Round (serves 28-35)': 120,
            '2-Tier (serves 30-40)': 175,
            '3-Tier (serves 60-80)': 275,
            'Sheet Cake (serves 24-48)': 95,
        }
        addon_prices = {
            'Fondant Decorations': 25,
            'Fresh Flowers': 20,
            'Gold/Silver Leaf': 30,
            'Photo Print Topper': 15,
            'Extra Frosting Layer': 10,
            'Gluten-Free Option': 15,
            'Vegan Option': 15,
        }
        base = float(size_prices.get(size, 0))
        addon_total = sum(float(addon_prices.get(a, 0)) for a in addons)
        subtotal = base + addon_total
        tax_amt  = round(subtotal * tax_rate(), 2)
        total    = round(subtotal + tax_amt, 2)

        onum = gen_order_number()
        cur = db.execute(
            '''INSERT INTO orders(order_number,customer_id,customer_name,customer_email,
               customer_phone,type,status,pickup_date,pickup_time,special_notes,
               subtotal,tax,total,balance_due)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (onum, cust_id, cname, cemail, cphone, 'online', 'pending',
             pickup_date, pickup_time, full_notes,
             subtotal, tax_amt, total, total)
        )
        order_id = cur.lastrowid

        # Add order item
        item_name = f'{size} — {flavor}' if size and flavor else (size or flavor or 'Custom Cake')
        if addons:
            item_name += f' + {", ".join(addons)}'
        db.execute(
            'INSERT INTO order_items(order_id,name,description,quantity,unit_price,total,customizations) VALUES(?,?,?,?,?,?,?)',
            (order_id, item_name, full_notes, 1, subtotal, subtotal, full_notes)
        )
        db.commit()
        return redirect(url_for('order_confirmation', order_number=onum))

    return render_template('public_order.html', bakery=BAKERY_NAME,
                           cake_sizes=CAKE_SIZES, flavors=FLAVORS, add_ons=ADD_ONS)


@app.route('/order/confirmation/<order_number>')
def order_confirmation(order_number):
    db = get_db()
    order = db.execute('SELECT * FROM orders WHERE order_number=?', (order_number,)).fetchone()
    return render_template('order_confirmation.html', order=order, bakery=BAKERY_NAME)


# ── Loyalty / QR Signup ────────────────────────────────────────────────────────────
@app.route('/join', methods=['GET', 'POST'])
def join():
    """Public QR signup page — no login required."""
    success = False
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        email    = request.form.get('email', '').strip().lower()
        phone    = request.form.get('phone', '').strip()
        birthday = request.form.get('birthday', '').strip()
        if name:
            db = get_db()
            # Check if already a customer by email or phone
            existing = None
            if email:
                existing = db.execute('SELECT id FROM customers WHERE email=?', (email,)).fetchone()
            if not existing and phone:
                existing = db.execute('SELECT id FROM customers WHERE phone=?', (phone,)).fetchone()
            if existing:
                cust_id = existing['id']
                # Update birthday if provided
                if birthday:
                    db.execute('UPDATE customers SET birthday=? WHERE id=?', (birthday, cust_id))
            else:
                cur = db.execute('INSERT INTO customers(name,email,phone,birthday,notes) VALUES(?,?,?,?,?)',
                                 (name, email, phone, birthday, 'QR loyalty signup'))
                cust_id = cur.lastrowid
            # Add to loyalty if not already there
            db.execute('INSERT OR IGNORE INTO loyalty_members(customer_id,source) VALUES(?,?)',
                       (cust_id, 'qr'))
            db.commit()
            success = True
    # Get active specials to show on signup page
    db = get_db()
    specials = db.execute("SELECT * FROM specials WHERE active=1 ORDER BY created DESC LIMIT 3").fetchall()
    return render_template('join.html', success=success, specials=specials, bakery=BAKERY_NAME)


@app.route('/qr')
def qr_code():
    """Generate a QR code image for the /join page."""
    import urllib.parse
    base = request.host_url.rstrip('/')
    join_url = f'{base}/join'
    # Use Google Charts QR API (no install needed)
    encoded = urllib.parse.quote(join_url)
    qr_url = f'https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={encoded}&bgcolor=fff&color=6b0029'
    return render_template('qr.html', qr_url=qr_url, join_url=join_url, bakery=BAKERY_NAME)


@app.route('/loyalty')
@login_required
def loyalty():
    db = get_db()
    members = db.execute('''
        SELECT c.*, lm.joined_at, lm.points, lm.tier, lm.source,
               (SELECT COUNT(*) FROM orders WHERE customer_id=c.id) as order_count
        FROM loyalty_members lm
        JOIN customers c ON c.id=lm.customer_id
        ORDER BY lm.joined_at DESC
    ''').fetchall()
    specials = db.execute("SELECT * FROM specials ORDER BY created DESC").fetchall()
    today = datetime.date.today()
    # Find birthdays this month
    month = str(today.month).zfill(2)
    birthdays = db.execute(
        "SELECT c.name, c.email, c.phone, c.birthday FROM customers c "
        "JOIN loyalty_members lm ON lm.customer_id=c.id "
        "WHERE c.birthday LIKE ?",(f'%-{month}-%',)
    ).fetchall()
    return render_template('loyalty.html', members=members, specials=specials,
                           birthdays=birthdays, bakery=BAKERY_NAME,
                           total=len(members))


@app.route('/loyalty/specials/add', methods=['POST'])
@login_required
def special_add():
    db = get_db()
    db.execute('INSERT INTO specials(title,description,discount,valid_from,valid_until) VALUES(?,?,?,?,?)',
               (request.form['title'], request.form.get('description',''),
                request.form.get('discount',''), request.form.get('valid_from', datetime.date.today().isoformat()),
                request.form.get('valid_until','')))
    db.commit()
    flash('Special added! ✨', 'success')
    return redirect(url_for('loyalty'))


@app.route('/loyalty/specials/<int:special_id>/toggle', methods=['POST'])
@login_required
def special_toggle(special_id):
    db = get_db()
    s = db.execute('SELECT active FROM specials WHERE id=?', (special_id,)).fetchone()
    if s:
        db.execute('UPDATE specials SET active=? WHERE id=?', (0 if s['active'] else 1, special_id))
        db.commit()
    return redirect(url_for('loyalty'))


# ── Public Menu ─────────────────────────────────────────────────────────────────

# Cake size/flavor/tier pricing (can be overridden by env or DB later)
CAKE_SIZES = [
    {'label': '6" Round (serves 8-10)',    'price': 38,  'emoji': '🎂'},
    {'label': '8" Round (serves 12-16)',   'price': 52,  'emoji': '🎂'},
    {'label': '10" Round (serves 20-24)',  'price': 72,  'emoji': '🎂'},
    {'label': '12" Round (serves 28-35)', 'price': 98,  'emoji': '🎂'},
    {'label': '2-Tier (serves 30-40)',    'price': 145, 'emoji': '✨'},
    {'label': '3-Tier (serves 60-80)',    'price': 235, 'emoji': '✨'},
    {'label': 'Sheet Cake (serves 24-48)','price': 75,  'emoji': '🎂'},
]

FLAVORS = [
    {'name': 'Classic Vanilla',        'desc': 'Light, fluffy vanilla sponge with silky vanilla buttercream',              'emoji': '🧁', 'popular': True},
    {'name': 'Rich Chocolate',         'desc': 'Deep, fudgy chocolate cake with chocolate ganache frosting',               'emoji': '🍫', 'popular': True},
    {'name': 'Strawberry Dream',       'desc': 'Fresh strawberry cake with whipped cream and strawberry compote',          'emoji': '🍓', 'popular': True},
    {'name': 'Red Velvet',             'desc': 'Velvety red cake with tangy cream cheese frosting',                        'emoji': '❤️', 'popular': True},
    {'name': 'Lemon Blueberry',        'desc': 'Bright lemon sponge with fresh blueberry jam and lemon curd frosting',    'emoji': '🍋', 'popular': False},
    {'name': 'Funfetti Celebration',   'desc': 'Vanilla cake packed with rainbow sprinkles inside and out',               'emoji': '🎈', 'popular': False},
    {'name': 'Carrot Cake',            'desc': 'Warmly spiced carrot cake with decadent cream cheese frosting',           'emoji': '🥕', 'popular': False},
    {'name': 'Cookies & Cream',        'desc': 'Chocolate cake layered with Oreo cream and cookies & cream frosting',     'emoji': '🍪', 'popular': False},
    {'name': 'Caramel Pecan',          'desc': 'Butter pecan cake drizzled with homemade caramel and praline crunch',    'emoji': '🥜', 'popular': False},
    {'name': 'Marble',                 'desc': 'Swirled vanilla and chocolate sponge with vanilla or chocolate frosting', 'emoji': '🌀', 'popular': False},
]

ADD_ONS = [
    {'name': 'Custom Message',          'price': 0,  'desc': 'Personalized text piped on your cake'},
    {'name': 'Fondant Decorations',     'price': 20, 'desc': 'Custom fondant figures, flowers, or toppers'},
    {'name': 'Fresh Flowers',           'price': 15, 'desc': 'Real edible flowers or silk florals'},
    {'name': 'Gold/Silver Leaf',        'price': 20, 'desc': 'Luxurious metallic leaf accent details'},
    {'name': 'Photo Print Topper',      'price': 12, 'desc': 'Edible photo printed on frosting sheet'},
    {'name': 'Extra Frosting Layer',    'price': 8,  'desc': 'Double the frosting — because why not?'},
    {'name': 'Gluten-Free Option',      'price': 10, 'desc': 'Gluten-free flour blend at no compromise in taste'},
    {'name': 'Vegan Option',            'price': 10, 'desc': '100% plant-based ingredients'},
]


@app.route('/menu')
def menu():
    db = get_db()
    # Get actual recipes from DB too
    db_recipes = db.execute(
        "SELECT * FROM recipes WHERE active=1 ORDER BY category, name"
    ).fetchall()
    return render_template('menu.html', bakery=BAKERY_NAME,
                           cake_sizes=CAKE_SIZES, flavors=FLAVORS,
                           add_ons=ADD_ONS, db_recipes=db_recipes)


# ── Marketing & Ads ─────────────────────────────────────────────────────────────────
@app.route('/marketing')
@login_required
def marketing():
    db = get_db()
    campaigns = db.execute('SELECT * FROM campaigns ORDER BY created DESC').fetchall()

    # Audience counts
    total_members = db.execute('SELECT COUNT(*) FROM loyalty_members').fetchone()[0]
    month = str(datetime.date.today().month).zfill(2)
    birthday_count = db.execute(
        "SELECT COUNT(*) FROM customers c JOIN loyalty_members lm ON lm.customer_id=c.id WHERE c.birthday LIKE ?",
        (f'%-{month}-%',)).fetchone()[0]
    new_count = db.execute(
        "SELECT COUNT(*) FROM loyalty_members WHERE date(joined_at) >= date('now','-30 days')").fetchone()[0]
    top_count = db.execute(
        """SELECT COUNT(*) FROM loyalty_members lm
           JOIN (SELECT customer_id, COUNT(*) as cnt FROM orders GROUP BY customer_id HAVING cnt>=2) t
           ON t.customer_id=lm.customer_id""").fetchone()[0]
    email_count = db.execute(
        "SELECT COUNT(*) FROM loyalty_members lm JOIN customers c ON c.id=lm.customer_id WHERE c.email != ''"
    ).fetchone()[0]

    audiences = [
        {'key': 'all',          'label': 'All VIP Members',        'count': total_members,  'icon': '⭐'},
        {'key': 'birthday',     'label': 'Birthdays This Month',   'count': birthday_count, 'icon': '🎂'},
        {'key': 'new',          'label': 'New Members (30 days)',  'count': new_count,      'icon': '🌱'},
        {'key': 'top_customers','label': 'Top Customers (2+ orders)', 'count': top_count,  'icon': '🏆'},
    ]
    return render_template('marketing.html', campaigns=campaigns, audiences=audiences,
                           email_count=email_count, total=total_members, bakery=BAKERY_NAME)


@app.route('/marketing/campaigns/new', methods=['POST'])
@login_required
def campaign_new():
    db = get_db()
    cur = db.execute(
        'INSERT INTO campaigns(name,audience,subject,message,ad_copy) VALUES(?,?,?,?,?)',
        (request.form['name'].strip(),
         request.form.get('audience', 'all'),
         request.form.get('subject', '').strip(),
         request.form.get('message', '').strip(),
         request.form.get('ad_copy', '').strip()))
    db.commit()
    flash('Campaign created! ✨', 'success')
    return redirect(url_for('campaign_detail', campaign_id=cur.lastrowid))


@app.route('/marketing/campaigns/<int:campaign_id>')
@login_required
def campaign_detail(campaign_id):
    db = get_db()
    campaign = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
    if not campaign: return redirect(url_for('marketing'))

    # Build audience list
    audience = campaign['audience']
    if audience == 'birthday':
        month = str(datetime.date.today().month).zfill(2)
        members = db.execute(
            "SELECT c.* FROM customers c JOIN loyalty_members lm ON lm.customer_id=c.id WHERE c.birthday LIKE ? AND c.email != ''",
            (f'%-{month}-%',)).fetchall()
    elif audience == 'new':
        members = db.execute(
            "SELECT c.* FROM customers c JOIN loyalty_members lm ON lm.customer_id=c.id WHERE date(lm.joined_at) >= date('now','-30 days') AND c.email != ''"
        ).fetchall()
    elif audience == 'top_customers':
        members = db.execute(
            """SELECT c.* FROM customers c
               JOIN loyalty_members lm ON lm.customer_id=c.id
               JOIN (SELECT customer_id, COUNT(*) as cnt FROM orders GROUP BY customer_id HAVING cnt>=2) t
               ON t.customer_id=c.id WHERE c.email != ''""").fetchall()
    else:  # all
        members = db.execute(
            "SELECT c.* FROM customers c JOIN loyalty_members lm ON lm.customer_id=c.id WHERE c.email != '' ORDER BY c.name"
        ).fetchall()

    return render_template('campaign_detail.html', campaign=campaign, members=members,
                           bakery=BAKERY_NAME)


@app.route('/marketing/campaigns/<int:campaign_id>/edit', methods=['POST'])
@login_required
def campaign_edit(campaign_id):
    db = get_db()
    db.execute('UPDATE campaigns SET name=?,audience=?,subject=?,message=?,ad_copy=? WHERE id=?',
               (request.form['name'], request.form.get('audience','all'),
                request.form.get('subject',''), request.form.get('message',''),
                request.form.get('ad_copy',''), campaign_id))
    db.commit()
    flash('Campaign updated!', 'success')
    return redirect(url_for('campaign_detail', campaign_id=campaign_id))


@app.route('/marketing/campaigns/<int:campaign_id>/generate-ad', methods=['POST'])
@login_required
def campaign_generate_ad(campaign_id):
    """Use AI to generate ad copy for the campaign."""
    db = get_db()
    campaign = db.execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
    if not campaign: return jsonify({'error': 'not found'}), 404

    openrouter_key = os.environ.get('OPENROUTER_API_KEY', '')
    if not openrouter_key:
        return jsonify({'error': 'OPENROUTER_API_KEY not set in Railway env vars'}), 400

    import urllib.request as _ur
    audience_labels = {
        'all': 'all VIP loyalty members',
        'birthday': 'customers with birthdays this month',
        'new': 'new members who joined in the last 30 days',
        'top_customers': 'top customers with 2 or more orders',
    }
    audience_label = audience_labels.get(campaign['audience'], campaign['audience'])
    prompt = f"""You are a marketing copywriter for a custom cake bakery called {BAKERY_NAME}.

Write 3 SHORT, punchy marketing messages for {audience_label}.
The campaign is: "{campaign['name']}"
{('The offer/special: ' + campaign['subject']) if campaign['subject'] else ''}

Write:
1. A text message (SMS) version — max 160 chars, casual and warm
2. An email subject line — catchy, under 50 chars
3. A social media post — 2-3 sentences with emojis, friendly and fun

Format:
SMS: [text]
EMAIL SUBJECT: [text]
SOCIAL: [text]"""

    try:
        payload = json.dumps({'model': 'openai/gpt-4o-mini',
                              'messages': [{'role': 'user', 'content': prompt}],
                              'max_tokens': 300}).encode()
        req = _ur.Request('https://openrouter.ai/api/v1/chat/completions', data=payload,
                          headers={'Authorization': f'Bearer {openrouter_key}',
                                   'Content-Type': 'application/json'})
        with _ur.urlopen(req, timeout=20) as r:
            result = json.loads(r.read())
        ad_copy = result['choices'][0]['message']['content']
        db.execute('UPDATE campaigns SET ad_copy=? WHERE id=?', (ad_copy, campaign_id))
        db.commit()
        return jsonify({'ok': True, 'ad_copy': ad_copy})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/marketing/campaigns/<int:campaign_id>/mark-sent', methods=['POST'])
@login_required
def campaign_mark_sent(campaign_id):
    db = get_db()
    count = int(request.form.get('count', 0))
    db.execute("UPDATE campaigns SET status='sent', sent_count=?, sent_at=datetime('now') WHERE id=?",
               (count, campaign_id))
    db.commit()
    flash(f'Campaign marked as sent to {count} members! ✅', 'success')
    return redirect(url_for('campaign_detail', campaign_id=campaign_id))


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

# ── Cakely WRITE actions ──────────────────────────────────────────────────────
@app.route('/cakely/api/recipes/add', methods=['POST'])
def cakely_add_recipe():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    name        = data.get('name', '').strip()
    category    = data.get('category', 'Cake')
    description = data.get('description', '')
    servings    = int(data.get('servings', 12))
    prep_mins   = int(data.get('prep_mins', 60))
    bake_mins   = int(data.get('bake_mins', 30))
    base_price  = float(data.get('base_price', 0))
    if not name:
        return jsonify({'error': 'name is required'}), 400
    cur = db.execute(
        'INSERT INTO recipes(name,category,description,servings,prep_mins,bake_mins,base_price) VALUES(?,?,?,?,?,?,?)',
        (name, category, description, servings, prep_mins, bake_mins, base_price)
    )
    db.commit()
    return jsonify({'ok': True, 'id': cur.lastrowid, 'message': f'Recipe "{name}" added successfully!'})

@app.route('/cakely/api/inventory/add', methods=['POST'])
def cakely_add_ingredient():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    name          = data.get('name', '').strip()
    unit          = data.get('unit', 'each')
    quantity      = float(data.get('quantity', 0))
    reorder_level = float(data.get('reorder_level', 5))
    cost_per_unit = float(data.get('cost_per_unit', 0))
    if not name:
        return jsonify({'error': 'name is required'}), 400
    cur = db.execute(
        'INSERT INTO ingredients(name,unit,quantity,reorder_level,cost_per_unit) VALUES(?,?,?,?,?)',
        (name, unit, quantity, reorder_level, cost_per_unit)
    )
    db.commit()
    return jsonify({'ok': True, 'id': cur.lastrowid, 'message': f'Ingredient "{name}" added to inventory!'})

@app.route('/cakely/api/inventory/update', methods=['POST'])
def cakely_update_inventory():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    name  = data.get('name', '').strip()
    delta = float(data.get('delta', 0))  # positive = add, negative = remove
    item = db.execute('SELECT * FROM ingredients WHERE name LIKE ?', (f'%{name}%',)).fetchone()
    if not item:
        return jsonify({'error': f'Ingredient "{name}" not found'}), 404
    new_qty = max(0, item['quantity'] + delta)
    db.execute('UPDATE ingredients SET quantity=? WHERE id=?', (new_qty, item['id']))
    db.commit()
    return jsonify({'ok': True, 'name': item['name'], 'old_qty': item['quantity'],
                   'new_qty': new_qty, 'unit': item['unit'],
                   'message': f'{item["name"]} updated: {item["quantity"]} → {new_qty} {item["unit"]}'})

@app.route('/cakely/api/customers/add', methods=['POST'])
def cakely_add_customer():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    name  = data.get('name', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    notes = data.get('notes', '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    cur = db.execute('INSERT INTO customers(name,email,phone,notes) VALUES(?,?,?,?)',
                     (name, email, phone, notes))
    db.commit()
    return jsonify({'ok': True, 'id': cur.lastrowid, 'message': f'Customer "{name}" added!'})

@app.route('/cakely/api/orders/add', methods=['POST'])
def cakely_add_order():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    cname       = data.get('customer_name', '').strip()
    cemail      = data.get('customer_email', '').strip()
    cphone      = data.get('customer_phone', '').strip()
    pickup_date = data.get('pickup_date', '')
    pickup_time = data.get('pickup_time', '')
    notes       = data.get('special_notes', '')
    otype       = data.get('type', 'custom')
    if not cname:
        return jsonify({'error': 'customer_name is required'}), 400
    # Find or create customer
    cust = db.execute('SELECT id FROM customers WHERE email=? AND email!=""', (cemail,)).fetchone() if cemail else None
    cust_id = cust['id'] if cust else None
    if not cust_id and cemail:
        cur = db.execute('INSERT INTO customers(name,email,phone) VALUES(?,?,?)', (cname, cemail, cphone))
        cust_id = cur.lastrowid
    onum = gen_order_number()
    cur = db.execute(
        'INSERT INTO orders(order_number,customer_id,customer_name,customer_email,customer_phone,type,pickup_date,pickup_time,special_notes) VALUES(?,?,?,?,?,?,?,?,?)',
        (onum, cust_id, cname, cemail, cphone, otype, pickup_date, pickup_time, notes)
    )
    db.commit()
    return jsonify({'ok': True, 'order_number': onum, 'order_id': cur.lastrowid,
                   'message': f'Order {onum} created for {cname}! Pickup: {pickup_date} {pickup_time}'})

@app.route('/cakely/api/orders/update-status', methods=['POST'])
def cakely_update_order_status():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    data = request.get_json() or {}
    q      = data.get('order_number', data.get('q', '')).strip()
    status = data.get('status', '').strip().lower()
    valid  = ['pending','confirmed','in_production','ready','delivered','cancelled']
    if status not in valid:
        return jsonify({'error': f'status must be one of: {valid}'}), 400
    order = db.execute('SELECT * FROM orders WHERE order_number=? OR customer_name LIKE ?',
                       (q, f'%{q}%')).fetchone()
    if not order:
        return jsonify({'error': f'Order not found for: {q}'}), 404
    db.execute('UPDATE orders SET status=? WHERE id=?', (status, order['id']))
    db.commit()
    return jsonify({'ok': True, 'order_number': order['order_number'],
                   'customer': order['customer_name'], 'new_status': status,
                   'message': f'Order {order["order_number"]} ({order["customer_name"]}) → {status}'})


@app.route('/cakely/api/suppliers', methods=['GET'])
def cakely_suppliers():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    db = get_db()
    rows = db.execute("SELECT id,name,contact,email,phone,address,notes FROM suppliers WHERE active=1 ORDER BY name").fetchall()
    return jsonify({'suppliers': [dict(r) for r in rows]})

@app.route('/cakely/api/suppliers/add', methods=['POST'])
def cakely_supplier_add():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(force=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    db = get_db()
    db.execute(
        "INSERT INTO suppliers(name,contact,email,phone,address,notes) VALUES(?,?,?,?,?,?)",
        (name, data.get('contact',''), data.get('email',''),
         data.get('phone',''), data.get('address',''), data.get('notes',''))
    )
    db.commit()
    supplier_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return jsonify({'ok': True, 'supplier_id': supplier_id, 'name': name,
                    'message': f'Supplier "{name}" added successfully.'})

@app.route('/cakely/api/suppliers/update', methods=['POST'])
def cakely_supplier_update():
    if not cakely_auth(): return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(force=True) or {}
    supplier_id = data.get('supplier_id')
    if not supplier_id:
        return jsonify({'error': 'supplier_id is required'}), 400
    db = get_db()
    supplier = db.execute('SELECT * FROM suppliers WHERE id=?', (supplier_id,)).fetchone()
    if not supplier:
        return jsonify({'error': 'Supplier not found'}), 404
    fields = ['name','contact','email','phone','address','notes']
    for f in fields:
        if f in data:
            db.execute(f'UPDATE suppliers SET {f}=? WHERE id=?', (data[f], supplier_id))
    db.commit()
    return jsonify({'ok': True, 'supplier_id': supplier_id, 'message': 'Supplier updated.'})

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
- get_recipes: all active recipes with pricing
- get_suppliers: list all active suppliers
- add_supplier: add a new supplier (name required; optional: contact, email, phone, address, notes)
- update_supplier: update supplier fields by supplier_id"""

    return jsonify({'ok': True, 'identity_md': IDENTITY, 'soul_md': SOUL, 'memory_md': MEMORY})


@app.route('/api/customers/search')
@login_required
def api_customers_search():
    db = get_db()
    q = request.args.get('q', '')
    rows = db.execute("SELECT id,name,email,phone FROM customers WHERE name LIKE ? OR email LIKE ? LIMIT 10",
                      (f'%{q}%', f'%{q}%')).fetchall()
    return jsonify([dict(r) for r in rows])

# Run migrations on startup to patch any live DBs missing columns
# (defined after _run_migrations so the function exists at this point)
with app.app_context():
    _mig_db = sqlite3.connect(DB_PATH)
    _mig_db.row_factory = sqlite3.Row
    _run_migrations(_mig_db)
    _mig_db.close()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

