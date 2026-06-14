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

PROMPT = (
    'Analyze this store shelf photo. Identify all visible products, estimate unit counts and shelf space percentage for each product. '
    'Return ONLY valid JSON in this exact format: '
    '{"products": [{"name": "...", "brand": "...", "unit_count": 5, "shelf_space_pct": 30.0, "confidence": 0.85}], '
    '"total_shelf_units": 20, "notes": "..."}'
)

DEFAULT_RESPONSE = {
    "products": [
        {
            "name": "Unknown Product",
            "brand": "Unknown",
            "unit_count": 0,
            "shelf_space_pct": 100.0,
            "confidence": 0.0,
        }
    ],
    "total_shelf_units": 0,
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
            if not p.get("name"):
                p["name"] = "Unknown Product"
            if not p.get("brand"):
                p["brand"] = "Unknown"

        return result

    except Exception as e:
        print(f"AI analysis error: {e}")
        fallback = json.loads(json.dumps(DEFAULT_RESPONSE))
        fallback["notes"] = f"Analysis error: {str(e)}"
        return fallback
