"""
Suggest parser mappings for unknown or unmapped armoury items.

Outputs ready-to-paste lines for:
- ArmouryParser.ITEM_ID_MAPPING
- ArmouryParser.ITEM_CATEGORIES

This script does not modify parser.py automatically.
"""

import argparse
import os
import sqlite3
import sys

import requests
from dotenv import load_dotenv

# Allow running as a standalone script from the scripts/ directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.armoury.parser import ArmouryParser


def fetch_torn_items(api_key):
    response = requests.get(
        "https://api.torn.com/torn/",
        params={"selections": "items", "key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"Torn API error: {data['error']}")
    return data.get("items", {})


def infer_category(item_name, torn_type):
    # Keep existing parser behavior as highest priority.
    current = ArmouryParser.get_item_category(item_name)
    if current != "Unknown":
        return current
    return ArmouryParser.get_category_from_api_type(torn_type)


def load_candidates(db_path, include_known_category=False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if include_known_category:
        where_clause = "item_id = 0 OR item_category = 'Unknown'"
    else:
        where_clause = "item_category = 'Unknown'"

    rows = cur.execute(
        f"""
        SELECT item_name,
               COUNT(*) as usage_count,
               SUM(CASE WHEN item_id = 0 THEN 1 ELSE 0 END) as missing_id_count
        FROM armoury_news
        WHERE {where_clause}
          AND item_name IS NOT NULL
          AND item_name != ''
        GROUP BY item_name
        ORDER BY usage_count DESC, item_name ASC
        """
    ).fetchall()

    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Suggest ITEM_ID_MAPPING and ITEM_CATEGORIES entries for unknown armoury items."
    )
    parser.add_argument(
        "--db",
        default="data/tornintel.db",
        help="Path to SQLite database (default: data/tornintel.db)",
    )
    parser.add_argument(
        "--include-known-category",
        action="store_true",
        help="Include items with known category but missing item_id=0",
    )
    args = parser.parse_args()

    load_dotenv()
    keys = [k.strip() for k in os.getenv("TORN_API_KEYS", "").split(",") if k.strip()]
    if not keys:
        raise RuntimeError("No TORN_API_KEYS configured")

    items = fetch_torn_items(keys[0])
    name_to_info = {v.get("name", "").lower(): (int(i), v.get("type", "Unknown")) for i, v in items.items()}

    candidates = load_candidates(args.db, include_known_category=args.include_known_category)

    suggestions = []
    unresolved = []

    for row in candidates:
        item_name = row["item_name"]
        key = item_name.lower()
        usage_count = row["usage_count"]
        missing_id_count = row["missing_id_count"]

        item_id, torn_type = name_to_info.get(key, (0, "Unknown"))
        suggested_category = infer_category(item_name, torn_type)

        current_id = ArmouryParser.get_item_id(item_name)
        current_category = ArmouryParser.get_item_category(item_name)

        if item_id == 0:
            unresolved.append((item_name, usage_count, missing_id_count, "Not found in torn/items"))
            continue

        needs_id = current_id == 0
        needs_category = current_category == "Unknown" and suggested_category != "Unknown"

        if not needs_id and not needs_category:
            continue

        suggestions.append(
            {
                "item_name": item_name,
                "key": key,
                "item_id": item_id,
                "torn_type": torn_type,
                "suggested_category": suggested_category,
                "usage_count": usage_count,
                "missing_id_count": missing_id_count,
                "needs_id": needs_id,
                "needs_category": needs_category,
            }
        )

    print(f"Candidates scanned: {len(candidates)}")
    print(f"Suggestions: {len(suggestions)}")
    print(f"Unresolved: {len(unresolved)}")

    if suggestions:
        print("\n# Suggested ITEM_ID_MAPPING entries")
        for s in suggestions:
            if s["needs_id"]:
                print(f'"{s["key"]}": {s["item_id"]},  # {s["item_name"]} (usage={s["usage_count"]}, type={s["torn_type"]})')

        print("\n# Suggested ITEM_CATEGORIES entries")
        for s in suggestions:
            if s["needs_category"]:
                print(f'"{s["key"]}": "{s["suggested_category"]}",  # {s["item_name"]} (usage={s["usage_count"]}, type={s["torn_type"]})')

        print("\n# Suggested verification SQL")
        print("SELECT item_name, item_id, item_category, COUNT(*) AS cnt")
        print("FROM armoury_news")
        print("WHERE item_name IN (")
        for s in suggestions:
            print(f"  '{s['item_name']}',")
        print(")")
        print("GROUP BY item_name, item_id, item_category")
        print("ORDER BY item_name;")

    if unresolved:
        print("\n# Unresolved items")
        for name, usage, missing_id, reason in unresolved:
            print(f"{name} | usage={usage} | missing_id_rows={missing_id} | {reason}")


if __name__ == "__main__":
    main()
