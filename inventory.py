"""Inventory parsing and validation."""

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


def _row_dict(headers: list[str], values: list[str]) -> dict[str, str]:
    padded = values + [""] * (len(headers) - len(values))
    return {
        header: (padded[index] or "").strip()
        for index, header in enumerate(headers)
    }


def parse_inventory_rows(values: list[list[str]]) -> list[dict]:
    if not values:
        raise InventoryError("inventory sheet is empty")

    headers = [header.strip() for header in values[0]]
    missing_columns = set(COLUMNS) - set(headers)
    if missing_columns:
        raise InventoryError(
            "inventory missing columns: " + ", ".join(sorted(missing_columns))
        )

    items: list[dict] = []
    item_id_lines: dict[str, list[int]] = {}
    identity_lines: dict[tuple[str, str, str], list[int]] = {}

    for line_number, raw_row in enumerate(values[1:], start=2):
        row = _row_dict(headers, raw_row)
        for column in COLUMNS:
            if not (row.get(column) or "").strip():
                raise InventoryError(
                    f"inventory line {line_number}: missing value for '{column}'"
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


def get_item(items: list[dict], item_id: str) -> dict | None:
    for item in items:
        if item["item_id"] == item_id:
            return item
    return None
