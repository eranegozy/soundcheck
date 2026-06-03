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


def _format_lines(lines: list[int]) -> str:
    return ", ".join(str(n) for n in lines)


def _validate_uniqueness(
    item_id_lines: dict[str, list[int]],
    identity_lines: dict[tuple[str, str, str], list[int]],
) -> None:
    errors: list[str] = []

    for item_id, lines in sorted(item_id_lines.items()):
        if len(lines) > 1:
            errors.append(
                f"Duplicate item_id '{item_id}' on lines {_format_lines(lines)}"
            )

    for (brand, model, number), lines in sorted(identity_lines.items()):
        if len(lines) > 1:
            errors.append(
                "Duplicate brand, model, and number "
                f"({brand} {model} {number}) on lines {_format_lines(lines)}. "
                "Items with the same brand and model must use different numbers."
            )

    if errors:
        raise InventoryError("\n\n".join(errors))


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
    item_id_lines: dict[str, list[int]] = {}
    identity_lines: dict[tuple[str, str, str], list[int]] = {}

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

            item_id = row["item_id"].strip()
            brand = row["brand"].strip()
            model = row["model"].strip()
            number = row["number"].strip()
            image = row["image"].strip()

            item_id_lines.setdefault(item_id, []).append(line_number)
            identity_lines.setdefault((brand, model, number), []).append(line_number)

            items.append(
                {
                    "item_id": item_id,
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

    _validate_uniqueness(item_id_lines, identity_lines)
    return items


def get_item(data_dir: Path, item_id: str) -> dict | None:
    for item in load_inventory(data_dir):
        if item["item_id"] == item_id:
            return item
    return None
