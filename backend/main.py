import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.database import get_db, init_db
from backend.ai_analysis import analyze_shelf_photo

UPLOADS_DIR = "/home/user/shelf-photo-app/uploads"
FRONTEND_DIR = "/home/user/shelf-photo-app/frontend"

app = FastAPI(title="ShelfTracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    await init_db()


@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


class LocationCreate(BaseModel):
    name: str
    store_name: str = ""
    address: str = ""


class ProductCreate(BaseModel):
    name: str
    brand: str = ""


@app.post("/api/locations")
async def create_location(body: LocationCreate):
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO locations (name, store_name, address) VALUES (?, ?, ?)",
            (body.name, body.store_name, body.address),
        )
        await db.commit()
        row = await (await db.execute(
            "SELECT * FROM locations WHERE id = ?", (cursor.lastrowid,)
        )).fetchone()
        return dict(row)


@app.get("/api/locations")
async def list_locations():
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM locations")).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/photos/upload")
async def upload_photo(
    file: UploadFile = File(...),
    location_id: int = Form(...),
    captured_at: str = Form(...),
):
    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOADS_DIR, filename)

    contents = await file.read()
    with open(file_path, "wb") as f:
        f.write(contents)

    analysis = analyze_shelf_photo(file_path)
    analysis_json = json.dumps(analysis)
    created_at = datetime.now(timezone.utc).isoformat()

    async with get_db() as db:
        cursor = await db.execute(
            """INSERT INTO shelf_photos (location_id, captured_at, file_path, analysis_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (location_id, captured_at, file_path, analysis_json, created_at),
        )
        photo_id = cursor.lastrowid
        await db.commit()

        product_results = []
        for p in analysis.get("products", []):
            name            = p.get("name") or "Unknown Product"
            brand           = p.get("brand") or "Unknown"
            sku_code        = p.get("sku_code")
            pack_type       = p.get("pack_type") or "OTHER"
            size_label      = p.get("size_label")
            size_ml         = p.get("size_ml")
            unit_type       = p.get("unit_type") or "SINGLE"
            category        = p.get("category") or "OTHER"
            placement       = p.get("placement") or "AMBIENT"
            unit_count      = int(p.get("unit_count") or 0)
            num_facings     = int(p.get("num_facings") or 0)
            shelf_space_pct = float(p.get("shelf_space_pct") or 0.0)
            price_per_unit  = p.get("price_per_unit")
            price_per_ltr   = p.get("price_per_ltr")
            confidence      = float(p.get("confidence") or 0.0)

            existing = await (await db.execute(
                "SELECT id FROM products WHERE LOWER(name) = LOWER(?) AND LOWER(brand) = LOWER(?)",
                (name, brand),
            )).fetchone()

            if existing:
                product_id = existing["id"]
                # Update master data in case it's more complete this time
                await db.execute(
                    """UPDATE products SET sku_code=COALESCE(?,sku_code), pack_type=COALESCE(?,pack_type),
                       size_label=COALESCE(?,size_label), size_ml=COALESCE(?,size_ml),
                       unit_type=COALESCE(?,unit_type), category=COALESCE(?,category),
                       placement=COALESCE(?,placement)
                       WHERE id=?""",
                    (sku_code, pack_type, size_label, size_ml, unit_type, category, placement, product_id),
                )
            else:
                pc = await db.execute(
                    """INSERT INTO products
                       (name, brand, sku_code, pack_type, size_label, size_ml, unit_type, category, placement, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, brand, sku_code, pack_type, size_label, size_ml, unit_type, category, placement, created_at),
                )
                product_id = pc.lastrowid

            await db.execute(
                """INSERT INTO photo_products
                   (photo_id, product_id, unit_count, num_facings, shelf_space_pct, price_per_unit, price_per_ltr, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (photo_id, product_id, unit_count, num_facings, shelf_space_pct, price_per_unit, price_per_ltr, confidence),
            )

            product_results.append({
                "product_id": product_id,
                "name": name, "brand": brand,
                "pack_type": pack_type, "size_label": size_label,
                "category": category, "placement": placement,
                "price_per_unit": price_per_unit, "price_per_ltr": price_per_ltr,
                "num_facings": num_facings, "unit_count": unit_count,
                "shelf_space_pct": shelf_space_pct, "confidence": confidence,
            })

        await db.commit()

        return {
            "photo_id": photo_id,
            "analysis": analysis,
            "products": product_results,
        }


@app.get("/api/photos")
async def list_photos(location_id: Optional[int] = None):
    async with get_db() as db:
        if location_id is not None:
            rows = await (await db.execute(
                """SELECT sp.*, l.name AS location_name
                   FROM shelf_photos sp
                   LEFT JOIN locations l ON sp.location_id = l.id
                   WHERE sp.location_id = ?
                   ORDER BY sp.captured_at DESC""",
                (location_id,),
            )).fetchall()
        else:
            rows = await (await db.execute(
                """SELECT sp.*, l.name AS location_name
                   FROM shelf_photos sp
                   LEFT JOIN locations l ON sp.location_id = l.id
                   ORDER BY sp.captured_at DESC"""
            )).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/photos/{photo_id}")
async def get_photo(photo_id: int):
    async with get_db() as db:
        photo = await (await db.execute(
            "SELECT * FROM shelf_photos WHERE id = ?", (photo_id,)
        )).fetchone()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        products = await (await db.execute(
            """SELECT pp.*, p.name, p.brand, p.sku_code, p.pack_type, p.size_label,
                      p.size_ml, p.unit_type, p.category, p.placement
               FROM photo_products pp
               JOIN products p ON pp.product_id = p.id
               WHERE pp.photo_id = ?
               ORDER BY pp.shelf_space_pct DESC""",
            (photo_id,),
        )).fetchall()

        return {"photo": dict(photo), "products": [dict(r) for r in products]}


@app.post("/api/products")
async def upsert_product(body: ProductCreate):
    created_at = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        existing = await (await db.execute(
            "SELECT id FROM products WHERE LOWER(name) = LOWER(?) AND LOWER(brand) = LOWER(?)",
            (body.name, body.brand),
        )).fetchone()

        if existing:
            row = await (await db.execute(
                "SELECT * FROM products WHERE id = ?", (existing["id"],)
            )).fetchone()
        else:
            cursor = await db.execute(
                "INSERT INTO products (name, brand, created_at) VALUES (?, ?, ?)",
                (body.name, body.brand, created_at),
            )
            await db.commit()
            row = await (await db.execute(
                "SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)
            )).fetchone()

        return dict(row)


@app.get("/api/products")
async def list_products():
    async with get_db() as db:
        rows = await (await db.execute("SELECT * FROM products ORDER BY name")).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/analysis/sales")
async def sales_analysis(
    location_id: int,
    start: Optional[str] = None,
    end: Optional[str] = None,
):
    async with get_db() as db:
        if start and end:
            photos = await (await db.execute(
                """SELECT * FROM shelf_photos
                   WHERE location_id = ? AND captured_at >= ? AND captured_at <= ?
                   ORDER BY captured_at ASC""",
                (location_id, start, end),
            )).fetchall()
        elif start:
            photos = await (await db.execute(
                """SELECT * FROM shelf_photos
                   WHERE location_id = ? AND captured_at >= ?
                   ORDER BY captured_at ASC""",
                (location_id, start),
            )).fetchall()
        elif end:
            photos = await (await db.execute(
                """SELECT * FROM shelf_photos
                   WHERE location_id = ? AND captured_at <= ?
                   ORDER BY captured_at ASC""",
                (location_id, end),
            )).fetchall()
        else:
            photos = await (await db.execute(
                """SELECT * FROM shelf_photos
                   WHERE location_id = ?
                   ORDER BY captured_at ASC""",
                (location_id,),
            )).fetchall()

        photos = [dict(p) for p in photos]

        for i in range(len(photos) - 1):
            earlier = photos[i]
            later = photos[i + 1]

            earlier_products = await (await db.execute(
                "SELECT product_id, unit_count, price_per_unit FROM photo_products WHERE photo_id = ?",
                (earlier["id"],),
            )).fetchall()
            later_products = await (await db.execute(
                "SELECT product_id, unit_count, price_per_unit FROM photo_products WHERE photo_id = ?",
                (later["id"],),
            )).fetchall()

            earlier_map = {r["product_id"]: dict(r) for r in earlier_products}
            later_map = {r["product_id"]: dict(r) for r in later_products}
            all_product_ids = set(earlier_map.keys()) | set(later_map.keys())

            for pid in all_product_ids:
                e_count = earlier_map[pid]["unit_count"] if pid in earlier_map else 0
                l_count = later_map[pid]["unit_count"] if pid in later_map else 0
                # Use the price from the earlier photo; fall back to later
                price_per_unit = (
                    earlier_map[pid].get("price_per_unit")
                    if pid in earlier_map
                    else later_map[pid].get("price_per_unit")
                ) or 0.0

                if l_count < e_count:
                    units_sold = e_count - l_count
                    replenishment_detected = 0
                else:
                    units_sold = 0
                    replenishment_detected = 1 if l_count > e_count else 0

                revenue_estimate = units_sold * price_per_unit

                await db.execute(
                    """DELETE FROM sales_estimates
                       WHERE location_id = ? AND product_id = ? AND period_start = ? AND period_end = ?""",
                    (location_id, pid, earlier["captured_at"], later["captured_at"]),
                )
                await db.execute(
                    """INSERT INTO sales_estimates
                       (location_id, product_id, period_start, period_end, units_sold,
                        replenishment_detected, price_per_unit, revenue_estimate)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (location_id, pid, earlier["captured_at"], later["captured_at"],
                     units_sold, replenishment_detected, price_per_unit, revenue_estimate),
                )

        await db.commit()

        query_args = [location_id]
        filter_clause = "WHERE se.location_id = ?"
        if start:
            filter_clause += " AND se.period_start >= ?"
            query_args.append(start)
        if end:
            filter_clause += " AND se.period_end <= ?"
            query_args.append(end)

        rows = await (await db.execute(
            f"""SELECT se.*, p.name AS product_name, p.brand,
                       p.pack_type, p.size_label, p.category, p.placement
               FROM sales_estimates se
               JOIN products p ON se.product_id = p.id
               {filter_clause}
               ORDER BY se.period_start""",
            query_args,
        )).fetchall()

        return [dict(r) for r in rows]


@app.get("/api/analysis/share-of-shelf")
async def share_of_shelf(
    location_id: Optional[int] = None,
    photo_id: Optional[int] = None,
):
    async with get_db() as db:
        if photo_id is None and location_id is not None:
            latest = await (await db.execute(
                """SELECT id FROM shelf_photos WHERE location_id = ?
                   ORDER BY captured_at DESC LIMIT 1""",
                (location_id,),
            )).fetchone()
            if not latest:
                raise HTTPException(status_code=404, detail="No photos found for this location")
            photo_id = latest["id"]

        if photo_id is None:
            raise HTTPException(status_code=400, detail="photo_id or location_id required")

        photo = await (await db.execute(
            """SELECT sp.*, l.name AS location_name
               FROM shelf_photos sp
               LEFT JOIN locations l ON sp.location_id = l.id
               WHERE sp.id = ?""",
            (photo_id,),
        )).fetchone()
        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        rows = await (await db.execute(
            """SELECT pp.shelf_space_pct, pp.unit_count, pp.num_facings,
                      pp.price_per_unit, pp.price_per_ltr,
                      p.name, p.brand, p.pack_type, p.size_label, p.category, p.placement
               FROM photo_products pp
               JOIN products p ON pp.product_id = p.id
               WHERE pp.photo_id = ?
               ORDER BY pp.shelf_space_pct DESC""",
            (photo_id,),
        )).fetchall()
        items = [dict(r) for r in rows]
        total_units = sum(item["unit_count"] for item in items)

        return {
            "photo_id": photo_id,
            "captured_at": photo["captured_at"],
            "location_name": photo["location_name"],
            "products": items,
            "total_units": total_units,
        }
