"""QR sticker helpers for admin print page."""

import re

import segno


def qr_svg_for_url(url: str) -> str:
    svg = segno.make(url, error="m").svg_inline(border=0, scale=3)
    svg = re.sub(r'\s(width|height)="[^"]*"', "", svg, count=2)
    return svg.replace("<svg ", '<svg class="sticker-qr-svg" ', 1)


def sticker_payload(item: dict, detail_url: str) -> dict:
    components = item.get("components") or []
    return {
        "item_id": item["item_id"],
        "display_name": item["display_name"],
        "location": item["location_label"],
        "components": components,
        "components_text": "; ".join(components) if components else "—",
        "detail_url": detail_url,
        "qr_svg": qr_svg_for_url(detail_url),
    }
