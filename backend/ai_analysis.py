import base64
import json
import re
import os
import anthropic

client = anthropic.Anthropic()

MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

PROMPT = """You are a retail shelf analyst. Carefully examine this store shelf photo and extract structured data for every visible SKU.

For each distinct product (SKU) visible on the shelf, extract:

MASTER DATA (from packaging design — fixed attributes of the product):
- name: product name as printed on pack (e.g. "Heineken Lager")
- brand: brand name (e.g. "Heineken")
- sku_code: barcode or SKU code if visible, else null
- pack_type: packaging format — one of: CAN, BOTTLE, CARTON, BAG, BOX, JAR, TUBE, POUCH, MULTIPACK, OTHER
- size_label: size as printed on pack (e.g. "500ml", "1L", "330ml", "6x330ml")
- size_ml: numeric volume in ml (e.g. 500, 1000, 330); for multipacks multiply unit size by count; null if not applicable
- unit_type: SINGLE, MULTIPACK, or BULK
- category: product category — e.g. BEER, SODA, WATER, JUICE, WINE, SPIRITS, DAIRY, SNACKS, COFFEE, OTHER
- placement: shelf environment — CHILLED, AMBIENT, or FROZEN

VARIABLE DATA (from this specific photo — changes per visit):
- price_per_unit: price as shown on shelf label in local currency (numeric, null if not visible)
- price_per_ltr: price per litre calculated from price_per_unit and size_ml (null if either is missing)
- num_facings: number of product columns/slots visible facing forward for this SKU
- unit_count: total visible units (facings × estimated depth)
- shelf_space_pct: estimated percentage of total visible shelf width occupied by this SKU
- confidence: your confidence in this detection (0.0–1.0)

Return ONLY a valid JSON object in this exact structure (no markdown, no explanation):
{
  "products": [
    {
      "name": "Heineken Lager",
      "brand": "Heineken",
      "sku_code": null,
      "pack_type": "CAN",
      "size_label": "500ml",
      "size_ml": 500,
      "unit_type": "SINGLE",
      "category": "BEER",
      "placement": "CHILLED",
      "price_per_unit": 1.89,
      "price_per_ltr": 3.78,
      "num_facings": 4,
      "unit_count": 12,
      "shelf_space_pct": 25.0,
      "confidence": 0.92
    }
  ],
  "total_shelf_units": 48,
  "shelf_environment": "CHILLED",
  "notes": "..."
}"""

DEFAULT_RESPONSE = {
    "products": [
        {
            "name": "Unknown Product",
            "brand": "Unknown",
            "sku_code": None,
            "pack_type": "OTHER",
            "size_label": None,
            "size_ml": None,
            "unit_type": "SINGLE",
            "category": "OTHER",
            "placement": "AMBIENT",
            "price_per_unit": None,
            "price_per_ltr": None,
            "num_facings": 0,
            "unit_count": 0,
            "shelf_space_pct": 100.0,
            "confidence": 0.0,
        }
    ],
    "total_shelf_units": 0,
    "shelf_environment": "AMBIENT",
    "notes": "Analysis failed or image could not be processed.",
}


def analyze_shelf_photo(image_path: str) -> dict:
    try:
        ext = os.path.splitext(image_path)[1].lower()
        media_type = MEDIA_TYPES.get(ext, "image/jpeg")

        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": PROMPT,
                        },
                    ],
                }
            ],
        )

        raw = message.content[0].text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        result = json.loads(raw)

        # Ensure all products have required fields
        for p in result.get("products", []):
            p.setdefault("name", "Unknown Product")
            p.setdefault("brand", "Unknown")
            p.setdefault("sku_code", None)
            p.setdefault("pack_type", "OTHER")
            p.setdefault("size_label", None)
            p.setdefault("size_ml", None)
            p.setdefault("unit_type", "SINGLE")
            p.setdefault("category", "OTHER")
            p.setdefault("placement", "AMBIENT")
            p.setdefault("price_per_unit", None)
            p.setdefault("price_per_ltr", None)
            p.setdefault("num_facings", 0)
            p.setdefault("unit_count", 0)
            p.setdefault("shelf_space_pct", 0.0)
            p.setdefault("confidence", 0.0)
            if not p["name"]:
                p["name"] = "Unknown Product"
            if not p["brand"]:
                p["brand"] = "Unknown"
            # Compute price_per_ltr if we have the data but AI didn't fill it
            if p["price_per_unit"] and p["size_ml"] and not p["price_per_ltr"]:
                p["price_per_ltr"] = round(p["price_per_unit"] / (p["size_ml"] / 1000), 4)

        return result

    except Exception as e:
        print(f"AI analysis error: {e}")
        fallback = json.loads(json.dumps(DEFAULT_RESPONSE))
        fallback["notes"] = f"Analysis error: {str(e)}"
        return fallback
