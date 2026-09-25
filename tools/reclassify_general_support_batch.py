"""
One-off follow-up to classify_categories.py: several fetchers (Switzerland Zefix,
Germany ZER, UK CCEW, UK CCNI) hard-defaulted every entry to "general_support"
instead of classifying per-entry. That passes classify_categories.py's
VALID_TYPES membership check (general_support IS a valid type), so the original
script found nothing to fix -- but it's a placeholder pattern in spirit, same as
a missing category. This re-runs real classification on just those batches.

Usage:
    python3 tools/reclassify_general_support_batch.py           # apply
    python3 tools/reclassify_general_support_batch.py --dry-run
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify_categories import classify_one, VALID_TYPES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "community_resources.json"
LOG_DIR = ROOT / "tools" / "logs"

SOURCE_MARKERS = ["Zefix", "Zuwendungsempf", "Charity Commission", "CCNI"]


def main():
    dry_run = "--dry-run" in sys.argv
    LOG_DIR.mkdir(exist_ok=True)

    data = json.load(open(DATA_FILE, encoding="utf-8"))
    targets = [
        (i, d) for i, d in enumerate(data)
        if d.get("type") == "general_support"
        and any(m.lower() in (d.get("source") or "").lower() for m in SOURCE_MARKERS)
    ]
    print(f"{len(targets)} general_support entries from suspect sources to re-check")

    changes = []
    unchanged = []
    errors = []

    for n, (i, d) in enumerate(targets, 1):
        try:
            result = classify_one(d.get("name", ""), d.get("description", ""), d.get("services", []))
        except Exception as e:
            print(f"  [{n}/{len(targets)}] ERROR on {d.get('name')!r}: {e}")
            errors.append({"name": d.get("name"), "error": str(e)})
            continue

        if result == "uncertain" or result == "general_support":
            unchanged.append({"name": d.get("name"), "result": result})
        else:
            changes.append({"name": d.get("name"), "old_type": "general_support", "new_type": result})
            print(f"  [{n}/{len(targets)}] {d.get('name')!r}: general_support -> {result}")
            if not dry_run:
                data[i]["type"] = result

        if n % 50 == 0:
            print(f"  ... {n}/{len(targets)} done, {len(changes)} changed so far")

    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"reclassify_general_support_{ts}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Reclassify general_support batch run: {ts}\ndry_run={dry_run}\n")
        f.write(f"Changed ({len(changes)}):\n")
        for c in changes:
            f.write(f"  {c['name']!r}: general_support -> {c['new_type']}\n")
        f.write(f"\nConfirmed general_support / uncertain ({len(unchanged)}):\n")
        for u in unchanged:
            f.write(f"  {u['name']!r}: {u['result']}\n")
        if errors:
            f.write(f"\nErrors ({len(errors)}):\n")
            for e in errors:
                f.write(f"  {e}\n")

    print(f"\n{len(changes)} changed, {len(unchanged)} confirmed/uncertain, {len(errors)} errors")
    print(f"Log: {log_path}")

    if not dry_run and changes:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Wrote {DATA_FILE}")
    elif dry_run:
        print("Dry run -- community_resources.json not modified")


if __name__ == "__main__":
    main()
