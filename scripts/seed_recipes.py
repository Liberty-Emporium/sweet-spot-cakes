#!/usr/bin/env python3
"""
seed_recipes.py — High-End Bakery Recipe Seeder for Sweet Spot Custom Cakes
============================================================================
Inserts 14 premium recipes with full ingredient quantities and tool links.
Run locally against a dev DB or pipe to Railway via stdin.

Usage:
    python3 scripts/seed_recipes.py /path/to/sweetspot.db
    python3 scripts/seed_recipes.py  (auto-detects local dev DB)
"""

import sys
import os
import sqlite3

# ── Locate DB ──────────────────────────────────────────────────────────────────
if len(sys.argv) > 1:
    DB_PATH = sys.argv[1]
else:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(_base, 'sweetspot.db')
    if not os.path.exists(DB_PATH):
        _vol = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '')
        DB_PATH = os.path.join(_vol, 'sweetspot.db') if _vol else DB_PATH

print(f"Using DB: {DB_PATH}")
if not os.path.exists(DB_PATH):
    print("❌ DB not found. Run the app once to create it, then re-run this script.")
    sys.exit(1)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
db = con.cursor()

# ── Build lookup maps ─────────────────────────────────────────────────────────
ingr_map = {r['name']: r['id'] for r in db.execute('SELECT id, name FROM ingredients').fetchall()}
tool_map = {r['name']: r['id'] for r in db.execute('SELECT id, name FROM tools WHERE active=1').fetchall()}

def ingr(name):
    if name not in ingr_map:
        print(f"  ⚠️  Ingredient not found: {name}")
        return None
    return ingr_map[name]

def tool(name):
    if name not in tool_map:
        print(f"  ⚠️  Tool not found: {name}")
        return None
    return tool_map[name]

def add_recipe(name, category, description, servings, prep_mins, bake_mins, base_price,
               ingredients, tools):
    """
    ingredients: list of (ingredient_name, quantity, unit)
    tools:       list of tool_names
    """
    existing = db.execute('SELECT id FROM recipes WHERE name=?', (name,)).fetchone()
    if existing:
        print(f"  ⏩ Recipe already exists: {name}")
        return existing['id']

    db.execute(
        '''INSERT INTO recipes(name, category, description, servings, prep_mins, bake_mins, base_price, active)
           VALUES(?,?,?,?,?,?,?,1)''',
        (name, category, description, servings, prep_mins, bake_mins, base_price)
    )
    recipe_id = db.lastrowid
    con.commit()

    # Link ingredients
    linked_i = 0
    for iname, qty, unit in ingredients:
        iid = ingr(iname)
        if iid:
            db.execute(
                'INSERT INTO recipe_ingredients(recipe_id, ingredient_id, quantity, unit) VALUES(?,?,?,?)',
                (recipe_id, iid, qty, unit)
            )
            linked_i += 1
    con.commit()

    # Link tools
    linked_t = 0
    for tname in tools:
        tid = tool(tname)
        if tid:
            existing_rt = db.execute(
                'SELECT id FROM recipe_tools WHERE recipe_id=? AND tool_id=?', (recipe_id, tid)
            ).fetchone()
            if not existing_rt:
                db.execute('INSERT INTO recipe_tools(recipe_id, tool_id) VALUES(?,?)', (recipe_id, tid))
                linked_t += 1
    con.commit()

    print(f"  ✅ {name}  ({linked_i} ingredients, {linked_t} tools)")
    return recipe_id


# ══════════════════════════════════════════════════════════════════════════════
# RECIPES
# ══════════════════════════════════════════════════════════════════════════════
print("\n🎂 Seeding high-end bakery recipes...\n")

# ── 1. Classic French Vanilla Layer Cake ─────────────────────────────────────
add_recipe(
    name='Classic French Vanilla Layer Cake',
    category='Cake',
    description='Four light genoise layers soaked in vanilla syrup, filled and frosted with silky French buttercream. Finished with vanilla bean flecks and a smooth ganache drip.',
    servings=16,
    prep_mins=90,
    bake_mins=30,
    base_price=145.00,
    ingredients=[
        ('Cake Flour (High-Protein)',  3.0,  'cups'),
        ('Granulated Sugar',           2.0,  'cups'),
        ('Unsalted Butter (European)', 1.0,  'cups'),
        ('Eggs (Large AA)',            4.0,  'each'),
        ('Whole Milk',                 1.0,  'cups'),
        ('Baking Powder (alum-free)',  2.5,  'tsp'),
        ('Fine Sea Salt',              0.5,  'tsp'),
        ('Vanilla Bean Paste',         2.0,  'tbsp'),
        ('Pure Vanilla Extract',       1.0,  'tsp'),
        ('Heavy Cream (36%)',          2.0,  'cups'),
        ('Powdered Sugar (10X)',       3.0,  'cups'),
    ],
    tools=[
        'Round Cake Pan 8"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Rubber Spatula (High-Temp)',
        'Offset Spatula (9")',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Serrated Bread Knife (10")',
        'Instant-Read Thermometer',
        'Wire Cooling Rack (half-sheet)',
        'Cake Board (10" round)',
        'Piping Tips Set (Ateco)',
    ]
)

# ── 2. Dark Chocolate Espresso Entremet ──────────────────────────────────────
add_recipe(
    name='Dark Chocolate Espresso Entremet',
    category='Entremet',
    description='Modern mirror-glaze entremet: hazelnut dacquoise base, espresso cremeux insert, Valrhona 70% chocolate mousse, and a glossy dark mirror glaze. A showstopper for any occasion.',
    servings=12,
    prep_mins=180,
    bake_mins=20,
    base_price=220.00,
    ingredients=[
        ('Valrhona Dark Chocolate 70%', 1.5,  'lbs'),
        ('Hazelnut Flour',              1.0,  'cups'),
        ('Powdered Sugar (10X)',        0.75, 'cups'),
        ('Egg Whites (Pasteurized)',    0.5,  'cups'),
        ('Heavy Cream (36%)',           3.0,  'cups'),
        ('Granulated Sugar',            1.0,  'cups'),
        ('Espresso Powder',             2.0,  'tbsp'),
        ('Glucose Syrup',               0.5,  'cups'),
        ('Gelatin Sheets',              8.0,  'each'),
        ('Unsalted Butter (European)',  0.25, 'cups'),
        ('Eggs (Large AA)',             3.0,  'each'),
        ('Dutch-Process Cocoa Powder',  0.25, 'cups'),
        ('Fleur de Sel',                0.5,  'tsp'),
    ],
    tools=[
        'Entremet Ring 8"',
        'Silicone Half-Sphere Mold',
        'KitchenAid 7qt Commercial Mixer',
        'Bain-Marie / Double Boiler',
        'Digital Kitchen Scale',
        'Instant-Read Thermometer',
        'Candy/Sugar Thermometer',
        'Acetate Sheets',
        'Offset Spatula (4")',
        'Wire Cooling Rack (half-sheet)',
        'Half Sheet Pan (18x13")',
    ]
)

# ── 3. Lemon Lavender Chiffon Cake ───────────────────────────────────────────
add_recipe(
    name='Lemon Lavender Chiffon Cake',
    category='Cake',
    description='Ultra-light chiffon cake layers with fresh lemon curd filling, whipped mascarpone cream, and edible lavender petals. Elegant, floral, and perfect for spring weddings.',
    servings=14,
    prep_mins=75,
    bake_mins=35,
    base_price=165.00,
    ingredients=[
        ('Cake Flour (High-Protein)',  2.5,  'cups'),
        ('Granulated Sugar',           1.75, 'cups'),
        ('Eggs (Large AA)',            6.0,  'each'),
        ('Whole Milk',                 0.75, 'cups'),
        ('Baking Powder (alum-free)',  1.5,  'tsp'),
        ('Fine Sea Salt',              0.5,  'tsp'),
        ('Cream of Tartar',            0.5,  'tsp'),
        ('Mascarpone',                 1.0,  'lbs'),
        ('Heavy Cream (36%)',          2.0,  'cups'),
        ('Powdered Sugar (10X)',       1.5,  'cups'),
        ('Pure Vanilla Extract',       1.0,  'tsp'),
        ('Edible Gold Dust',           1.0,  'each'),
    ],
    tools=[
        'Round Cake Pan 8"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Rubber Spatula (High-Temp)',
        'Hand Whisk (12")',
        'Offset Spatula (9")',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Instant-Read Thermometer',
        'Wire Cooling Rack (half-sheet)',
        'Cake Board (10" round)',
    ]
)

# ── 4. Salted Caramel Praline Cake ───────────────────────────────────────────
add_recipe(
    name='Salted Caramel Praline Cake',
    category='Cake',
    description='Brown butter vanilla cake layers with house-made salted caramel buttercream, crunchy hazelnut praline, and a dramatic caramel drip. Rich, indulgent, unforgettable.',
    servings=16,
    prep_mins=120,
    bake_mins=32,
    base_price=195.00,
    ingredients=[
        ('Cake Flour (High-Protein)',  3.0,  'cups'),
        ('Dark Brown Sugar',           2.0,  'cups'),
        ('Unsalted Butter (European)', 1.25, 'cups'),
        ('Eggs (Large AA)',            4.0,  'each'),
        ('Buttermilk',                 1.0,  'cups'),
        ('Baking Soda',                1.5,  'tsp'),
        ('Fine Sea Salt',              0.75, 'tsp'),
        ('Fleur de Sel Caramel Sauce', 8.0,  'oz'),
        ('Hazelnuts (Roasted)',        1.0,  'cups'),
        ('Granulated Sugar',           1.0,  'cups'),
        ('Heavy Cream (36%)',          1.5,  'cups'),
        ('Fleur de Sel',               1.0,  'tsp'),
        ('Invert Sugar (Trimoline)',   2.0,  'tbsp'),
    ],
    tools=[
        'Round Cake Pan 8"',
        'Round Cake Pan 6"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Candy/Sugar Thermometer',
        'Bain-Marie / Double Boiler',
        'Offset Spatula (9")',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Kitchen Torch (Bernzomatic)',
        'Cake Board (10" round)',
        'Wire Cooling Rack (half-sheet)',
    ]
)

# ── 5. Raspberry Rose Macaron Tower ──────────────────────────────────────────
add_recipe(
    name='Raspberry Rose Macaron Tower',
    category='Pastry',
    description='French-style macarons with almond shells, raspberry-rose ganache filling, and fresh raspberry jam center. Hand-assembled into a towering croquembouche-style display.',
    servings=40,
    prep_mins=240,
    bake_mins=14,
    base_price=280.00,
    ingredients=[
        ('Almond Flour',               2.0,  'cups'),
        ('Powdered Sugar (10X)',        2.0,  'cups'),
        ('Egg Whites (Pasteurized)',    0.75, 'cups'),
        ('Granulated Sugar',           0.75, 'cups'),
        ('Cream of Tartar',            0.25, 'tsp'),
        ('Valrhona White Chocolate',   0.5,  'lbs'),
        ('Heavy Cream (36%)',          0.75, 'cups'),
        ('Freeze-Dried Raspberries',   2.0,  'oz'),
        ('Rose Water',                 1.0,  'tbsp'),
        ('Food Coloring Gel Set',      1.0,  'each'),
    ],
    tools=[
        'Half Sheet Pan (18x13")',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Piping Tips Set (Ateco)',
        'Piping Bags (16-inch)',
        'Measuring Spoon Set',
        'Rubber Spatula (High-Temp)',
        'Instant-Read Thermometer',
        'Wire Cooling Rack (half-sheet)',
        'Stainless Mixing Bowl Set',
    ]
)

# ── 6. Opera Cake (Gâteau Opéra) ─────────────────────────────────────────────
add_recipe(
    name='Gâteau Opéra',
    category='Entremet',
    description='Classic Parisian opera cake: almond joconde sponge soaked in espresso syrup, layered with coffee buttercream and dark chocolate ganache, finished with a perfect chocolate glaze. Six precision layers.',
    servings=14,
    prep_mins=200,
    bake_mins=12,
    base_price=210.00,
    ingredients=[
        ('Almond Flour',               1.5,  'cups'),
        ('Powdered Sugar (10X)',        1.5,  'cups'),
        ('Eggs (Large AA)',             6.0,  'each'),
        ('Egg Whites (Pasteurized)',    0.5,  'cups'),
        ('Cake Flour (High-Protein)',   0.5,  'cups'),
        ('Unsalted Butter (European)', 0.25, 'cups'),
        ('Valrhona Dark Chocolate 70%', 1.0, 'lbs'),
        ('Heavy Cream (36%)',           1.5,  'cups'),
        ('Espresso Powder',             3.0,  'tbsp'),
        ('Granulated Sugar',            1.0,  'cups'),
        ('Glucose Syrup',               2.0,  'tbsp'),
        ('Fine Sea Salt',               0.25, 'tsp'),
    ],
    tools=[
        'Half Sheet Pan (18x13")',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Bain-Marie / Double Boiler',
        'Offset Spatula (4")',
        'Offset Spatula (9")',
        'Bench Scraper',
        'Instant-Read Thermometer',
        'Acetate Sheets',
        'Serrated Bread Knife (10")',
        'Rubber Spatula (High-Temp)',
    ]
)

# ── 7. Strawberry Champagne Celebration Cake ─────────────────────────────────
add_recipe(
    name='Strawberry Champagne Celebration Cake',
    category='Celebration',
    description='Light champagne chiffon layers with fresh strawberry compote filling, champagne Italian meringue buttercream, and a sugar-shard crown. The ultimate celebration centerpiece.',
    servings=20,
    prep_mins=150,
    bake_mins=28,
    base_price=295.00,
    ingredients=[
        ('Cake Flour (High-Protein)',   3.5,  'cups'),
        ('Granulated Sugar',            2.5,  'cups'),
        ('Eggs (Large AA)',             5.0,  'each'),
        ('Egg Whites (Pasteurized)',    0.75, 'cups'),
        ('Unsalted Butter (European)',  1.0,  'cups'),
        ('Heavy Cream (36%)',           2.0,  'cups'),
        ('Baking Powder (alum-free)',   2.5,  'tsp'),
        ('Fine Sea Salt',               0.5,  'tsp'),
        ('Pure Vanilla Extract',        2.0,  'tsp'),
        ('Freeze-Dried Strawberries',   2.0,  'oz'),
        ('Cream of Tartar',             0.5,  'tsp'),
        ('Powdered Sugar (10X)',        2.0,  'cups'),
        ('Edible Gold Dust',            2.0,  'each'),
        ('Isomalt',                     0.5,  'lbs'),
    ],
    tools=[
        'Round Cake Pan 10"',
        'Round Cake Pan 8"',
        'Round Cake Pan 6"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Candy/Sugar Thermometer',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Offset Spatula (9")',
        'Offset Spatula (4")',
        'Kitchen Torch (Bernzomatic)',
        'Cake Board (12" round)',
        'Cake Drum (14" round)',
        'Piping Tips Set (Ateco)',
        'Piping Bags (16-inch)',
        'Airbrush Kit (Iwata)',
    ]
)

# ── 8. Valrhona Chocolate Lava Cakes ─────────────────────────────────────────
add_recipe(
    name='Valrhona Chocolate Lava Cakes',
    category='Dessert',
    description='Individual molten chocolate cakes with a Valrhona 70% dark chocolate center that flows when cut. Served with crème anglaise and edible gold dust. Pure luxury.',
    servings=8,
    prep_mins=30,
    bake_mins=12,
    base_price=85.00,
    ingredients=[
        ('Valrhona Dark Chocolate 70%', 0.5,  'lbs'),
        ('Unsalted Butter (European)',  0.5,  'cups'),
        ('Eggs (Large AA)',             4.0,  'each'),
        ('Granulated Sugar',            0.5,  'cups'),
        ('Cake Flour (High-Protein)',   0.25, 'cups'),
        ('Fine Sea Salt',               0.25, 'tsp'),
        ('Fleur de Sel',                0.5,  'tsp'),
        ('Pure Vanilla Extract',        1.0,  'tsp'),
        ('Edible Gold Dust',            1.0,  'each'),
        ('Heavy Cream (36%)',           1.0,  'cups'),
        ('Whole Vanilla Beans',         1.0,  'each'),
    ],
    tools=[
        'Bain-Marie / Double Boiler',
        'Digital Kitchen Scale',
        'Springform Pan 9"',
        'Rubber Spatula (High-Temp)',
        'Hand Whisk (12")',
        'Instant-Read Thermometer',
        'Oven Thermometer',
        'Stainless Mixing Bowl Set',
        'Measuring Spoon Set',
    ]
)

# ── 9. Pistachio Raspberry Wedding Tiers ─────────────────────────────────────
add_recipe(
    name='Pistachio Raspberry Wedding Tiers',
    category='Wedding',
    description='Three-tier wedding cake: pistachio sponge with fresh raspberry jam, whipped white chocolate ganache, and fondant-finished tiers decorated with handcrafted sugar roses. Serves 60.',
    servings=60,
    prep_mins=480,
    bake_mins=40,
    base_price=850.00,
    ingredients=[
        ('Cake Flour (High-Protein)',   6.0,  'cups'),
        ('Pistachios (Raw, Shelled)',   2.0,  'cups'),
        ('Granulated Sugar',            5.0,  'cups'),
        ('Unsalted Butter (European)',  3.0,  'cups'),
        ('Eggs (Large AA)',            10.0,  'each'),
        ('Whole Milk',                  2.0,  'cups'),
        ('Baking Powder (alum-free)',   3.0,  'tsp'),
        ('Fine Sea Salt',               1.0,  'tsp'),
        ('Almond Extract',              1.0,  'tsp'),
        ('Valrhona White Chocolate',    2.0,  'lbs'),
        ('Heavy Cream (36%)',           4.0,  'cups'),
        ('Freeze-Dried Raspberries',    3.0,  'oz'),
        ('Fondant (White, Premium)',   10.0,  'lbs'),
        ('Gum Paste',                   2.0,  'lbs'),
        ('Food Coloring Gel Set',       1.0,  'each'),
        ('Luster Dust (Assorted)',      2.0,  'each'),
        ('Edible Gold Dust',            2.0,  'each'),
    ],
    tools=[
        'Round Cake Pan 6"',
        'Round Cake Pan 8"',
        'Round Cake Pan 10"',
        'Round Cake Pan 12"',
        'KitchenAid 7qt Commercial Mixer',
        'Hobart 20qt Floor Mixer',
        'Digital Kitchen Scale',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Fondant Smoother',
        'Rolling Pin (French)',
        'Fondant Mat (Non-stick)',
        'Flower Nail Set',
        'Petal Veiner & Cutter Set',
        'Offset Spatula (9")',
        'Offset Spatula (4")',
        'Cake Board (10" round)',
        'Cake Board (12" round)',
        'Cake Drum (14" round)',
        'Serrated Bread Knife (10")',
        'Airbrush Kit (Iwata)',
    ]
)

# ── 10. Black Forest Gateau ───────────────────────────────────────────────────
add_recipe(
    name='Black Forest Gateau',
    category='Cake',
    description='German-inspired schwarzwälder kirschtorte: light black cocoa sponge, Morello cherry compote, house-made kirsch syrup, and clouds of freshly whipped cream. Chocolate shavings and glazed cherries on top.',
    servings=14,
    prep_mins=90,
    bake_mins=30,
    base_price=155.00,
    ingredients=[
        ('Black Cocoa Powder',          0.75, 'cups'),
        ('Cake Flour (High-Protein)',   2.0,  'cups'),
        ('Granulated Sugar',            2.0,  'cups'),
        ('Eggs (Large AA)',             4.0,  'each'),
        ('Unsalted Butter (European)', 0.75, 'cups'),
        ('Buttermilk',                  1.0,  'cups'),
        ('Baking Soda',                 1.5,  'tsp'),
        ('Baking Powder (alum-free)',   0.5,  'tsp'),
        ('Fine Sea Salt',               0.5,  'tsp'),
        ('Heavy Cream (36%)',           3.0,  'cups'),
        ('Dried Cherries',              1.0,  'cups'),
        ('Valrhona Dark Chocolate 70%', 0.5,  'lbs'),
        ('Pure Vanilla Extract',        1.0,  'tsp'),
        ('Powdered Sugar (10X)',        0.5,  'cups'),
    ],
    tools=[
        'Round Cake Pan 8"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Turntable (Ateco Heavy)',
        'Cake Smoother / Icing Comb',
        'Offset Spatula (9")',
        'Bench Scraper',
        'Serrated Bread Knife (10")',
        'Cake Leveler / Slicer',
        'Wire Cooling Rack (half-sheet)',
        'Piping Tips Set (Ateco)',
        'Piping Bags (16-inch)',
        'Cake Board (10" round)',
    ]
)

# ── 11. Earl Grey & Honey Chiffon ────────────────────────────────────────────
add_recipe(
    name='Earl Grey & Honey Chiffon Cake',
    category='Cake',
    description='Delicate Earl Grey-infused chiffon layers with whipped honey mascarpone, fresh orange curd, and a candied citrus crown. Elevated afternoon tea flavor in a stunning format.',
    servings=12,
    prep_mins=80,
    bake_mins=35,
    base_price=175.00,
    ingredients=[
        ('Cake Flour (High-Protein)',   2.0,  'cups'),
        ('Granulated Sugar',            1.5,  'cups'),
        ('Eggs (Large AA)',             5.0,  'each'),
        ('Cream of Tartar',             0.5,  'tsp'),
        ('Whole Milk',                  0.75, 'cups'),
        ('Honey (Wildflower)',          0.5,  'cups'),
        ('Mascarpone',                  0.75, 'lbs'),
        ('Heavy Cream (36%)',           1.5,  'cups'),
        ('Orange Blossom Water',        1.0,  'tbsp'),
        ('Fine Sea Salt',               0.25, 'tsp'),
        ('Baking Powder (alum-free)',   1.5,  'tsp'),
        ('Turbinado Sugar',             0.25, 'cups'),
    ],
    tools=[
        'Round Cake Pan 8"',
        'KitchenAid 7qt Commercial Mixer',
        'Digital Kitchen Scale',
        'Rubber Spatula (High-Temp)',
        'Hand Whisk (12")',
        'Turntable (Ateco Heavy)',
        'Offset Spatula (9")',
        'Cake Smoother / Icing Comb',
        'Wire Cooling Rack (half-sheet)',
        'Cake Board (10" round)',
        'Kitchen Torch (Bernzomatic)',
    ]
)

# ── 12. Tarte Tatin aux Pommes ────────────────────────────────────────────────
add_recipe(
    name='Classic Tarte Tatin',
    category='Pastry',
    description='Upside-down caramelized apple tart in a buttery, flaky rough puff pastry shell. Amber Demerara caramel, salted butter, and perfectly softened Granny Smith apples. Served warm with crème fraîche.',
    servings=8,
    prep_mins=60,
    bake_mins=40,
    base_price=80.00,
    ingredients=[
        ('All-Purpose Flour',          2.0,  'cups'),
        ('Unsalted Butter (European)', 1.0,  'cups'),
        ('Granulated Sugar',           1.0,  'cups'),
        ('Demerara Sugar',             0.5,  'cups'),
        ('Fine Sea Salt',              0.5,  'tsp'),
        ('Fleur de Sel',               0.5,  'tsp'),
        ('Cream of Tartar',            0.25, 'tsp'),
        ('Heavy Cream (36%)',          0.25, 'cups'),
        ('Whole Vanilla Beans',        1.0,  'each'),
    ],
    tools=[
        'Tart Pan 9" (removable)',
        'Candy/Sugar Thermometer',
        'Digital Kitchen Scale',
        'Rolling Pin (French)',
        'Bench Scraper',
        'Pastry Cutter (Fluted)',
        'Bain-Marie / Double Boiler',
        'Instant-Read Thermometer',
        'Oven Thermometer',
        'Half Sheet Pan (18x13")',
    ]
)

# ── 13. Croissant au Beurre (Laminated) ──────────────────────────────────────
add_recipe(
    name='Beurre Croissants (Laminated)',
    category='Viennoiserie',
    description='Classic laminated croissants with 27 buttery layers. 84% fat European butter locked into a yeasted détrempe through four double turns. Golden, shattering exterior with a honeycomb crumb.',
    servings=12,
    prep_mins=720,
    bake_mins=20,
    base_price=48.00,
    ingredients=[
        ('Bread Flour',                4.0,  'cups'),
        ('Granulated Sugar',           0.25, 'cups'),
        ('Fine Sea Salt',              1.5,  'tsp'),
        ('Unsalted Butter (European)', 2.5,  'cups'),
        ('Whole Milk',                 1.25, 'cups'),
        ('Eggs (Large AA)',            2.0,  'each'),
    ],
    tools=[
        'Rolling Pin (French)',
        'Bench Scraper',
        'Digital Kitchen Scale',
        'Proofing Box / Cabinet',
        'Half Sheet Pan (18x13")',
        'Instant-Read Thermometer',
        'Oven Thermometer',
        'Pastry Cutter (Fluted)',
        'Measuring Cup Set (Dry)',
        'Measuring Spoon Set',
    ]
)

# ── 14. Crème Brûlée Tart ─────────────────────────────────────────────────────
add_recipe(
    name='Crème Brûlée Tart',
    category='Pastry',
    description='Crisp pâte sucrée shell filled with silky vanilla crème brûlée custard, torched Demerara sugar crust, and finished with edible gold dust and seasonal berries.',
    servings=10,
    prep_mins=60,
    bake_mins=45,
    base_price=95.00,
    ingredients=[
        ('All-Purpose Flour',          1.5,  'cups'),
        ('Powdered Sugar (10X)',        0.5,  'cups'),
        ('Unsalted Butter (European)', 0.5,  'cups'),
        ('Eggs (Large AA)',             3.0,  'each'),
        ('Heavy Cream (36%)',           2.5,  'cups'),
        ('Granulated Sugar',           0.5,  'cups'),
        ('Demerara Sugar',             0.5,  'cups'),
        ('Whole Vanilla Beans',        2.0,  'each'),
        ('Fine Sea Salt',              0.25, 'tsp'),
        ('Edible Gold Dust',           1.0,  'each'),
    ],
    tools=[
        'Tart Pan 9" (removable)',
        'Digital Kitchen Scale',
        'Rolling Pin (French)',
        'Bench Scraper',
        'Pastry Cutter (Fluted)',
        'Bain-Marie / Double Boiler',
        'Instant-Read Thermometer',
        'Kitchen Torch (Bernzomatic)',
        'Candy/Sugar Thermometer',
        'Wire Cooling Rack (half-sheet)',
        'Measuring Spoon Set',
    ]
)

# ── Done ──────────────────────────────────────────────────────────────────────
total = db.execute('SELECT COUNT(*) FROM recipes').fetchone()[0]
total_ri = db.execute('SELECT COUNT(*) FROM recipe_ingredients').fetchone()[0]
total_rt = db.execute('SELECT COUNT(*) FROM recipe_tools').fetchone()[0]

print(f"\n🎂 Done! {total} recipes total — {total_ri} ingredient links, {total_rt} tool links")
con.close()
