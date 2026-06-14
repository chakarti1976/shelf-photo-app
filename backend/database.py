import aiosqlite
from contextlib import asynccontextmanager

DB_PATH = "/home/user/shelf-photo-app/shelf_tracker.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                store_name TEXT,
                address TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shelf_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_id INTEGER,
                captured_at TEXT,
                file_path TEXT,
                analysis_json TEXT,
                created_at TEXT,
                FOREIGN KEY (location_id) REFERENCES locations(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                brand TEXT,
                sku_code TEXT,
                pack_type TEXT,
                size_label TEXT,
                size_ml REAL,
                unit_type TEXT,
                category TEXT,
                placement TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS photo_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_id INTEGER,
                product_id INTEGER,
                unit_count INTEGER,
                num_facings INTEGER,
                shelf_space_pct REAL,
                price_per_unit REAL,
                price_per_ltr REAL,
                confidence REAL,
                FOREIGN KEY (photo_id) REFERENCES shelf_photos(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sales_estimates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                location_id INTEGER,
                product_id INTEGER,
                period_start TEXT,
                period_end TEXT,
                units_sold INTEGER,
                replenishment_detected INTEGER DEFAULT 0,
                price_per_unit REAL,
                revenue_estimate REAL,
                FOREIGN KEY (location_id) REFERENCES locations(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        # Add new columns to existing tables if upgrading from old schema
        for col, definition in [
            ("sku_code",    "TEXT"),
            ("pack_type",   "TEXT"),
            ("size_label",  "TEXT"),
            ("size_ml",     "REAL"),
            ("unit_type",   "TEXT"),
            ("category",    "TEXT"),
            ("placement",   "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE products ADD COLUMN {col} {definition}")
            except Exception:
                pass
        for col, definition in [
            ("num_facings",    "INTEGER"),
            ("price_per_unit", "REAL"),
            ("price_per_ltr",  "REAL"),
        ]:
            try:
                await db.execute(f"ALTER TABLE photo_products ADD COLUMN {col} {definition}")
            except Exception:
                pass
        for col, definition in [
            ("price_per_unit", "REAL"),
        ]:
            try:
                await db.execute(f"ALTER TABLE sales_estimates ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await db.commit()


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
