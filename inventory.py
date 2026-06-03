"""Load inventory from CSV files."""

import csv
from pathlib import Path

COLUMNS = (
    "item_id",
    "brand",
    "model",
    "number",
    "serial",
    "category",
    "location",
    "components",
    "image",
)


class InventoryError(Exception):
    """Raised when inventory data is invalid or missing."""


def display_name(brand: str, model: str, number: str) -> str:
    parts = [brand.strip(), model.strip()]
    if number.strip():
        parts.append(number.strip())
    return " ".join(parts)


def parse_components(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(";") if part.strip()]


def load_inventory(data_dir: Path) -> list[dict]:
    csv_path = data_dir / "inventory.csv"
    if not csv_path.is_file():
        raise InventoryError(f"inventory file not found: {csv_path}")

    items: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        missing_columns = set(COLUMNS) - set(fieldnames)
        if missing_columns:
            raise InventoryError(
                "inventory.csv missing columns: "
                + ", ".join(sorted(missing_columns))
            )

        for line_number, row in enumerate(reader, start=2):
            for column in COLUMNS:
                if not (row.get(column) or "").strip():
                    raise InventoryError(
                        f"inventory.csv line {line_number}: "
                        f"missing value for '{column}'"
                    )

            brand = row["brand"].strip()
            model = row["model"].strip()
            number = row["number"].strip()
            image = row["image"].strip()

            items.append(
                {
                    "item_id": row["item_id"].strip(),
                    "brand": brand,
                    "model": model,
                    "number": number,
                    "serial": row["serial"].strip(),
                    "category": row["category"].strip(),
                    "location": row["location"].strip(),
                    "components": parse_components(row["components"]),
                    "image": image,
                    "display_name": display_name(brand, model, number),
                    "image_url": f"/images/{image}",
                }
            )

    return items
