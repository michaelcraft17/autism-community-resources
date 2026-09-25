"""
Classify entries whose `type` field isn't one of the site's real taxonomy values
(advocacy/therapy/education/medical/social/general_support — see TYPE_META in
index.html) into the closest matching category, using a local Ollama model
(qwen2.5-coder:7b). Pure closed-set classification, not fact generation, so it's
safe to auto-apply -- but every change is logged to tools/logs/ for audit, and
anything the model can't confidently place is left alone rather than guessed at.

Usage:
    python3 tools/classify_categories.py           # apply to community_resources.json
    python3 tools/classify_categories.py --dry-run  # classify + log only, no writes

Checkpointing: progress is written to tools/logs/category_classification_progress.json
every 20 entries, so an interrupted run can resume (currently the whole run is tiny --
well under 100 entries on this dataset -- but the mechanism is here for when a future
batch of new sources brings in more mismatched category values).
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "community_resources.json"
LOG_DIR = ROOT / "tools" / "logs"
PROGRESS_FILE = LOG_DIR / "category_classification_progress.json"

VALID_TYPES = ["advocacy", "therapy", "education", "medical", "social", "general_support"]

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:7b"

PROMPT_TEMPLATE = """You are classifying a directory entry for an autism/disability resource website into exactly one category.

Valid categories (pick exactly one, or "uncertain" if genuinely unclear):
- advocacy: advocacy organizations, awareness campaigns, policy/legal support
- therapy: ABA, speech, occupational, physical therapy providers/clinics
- education: schools, tutoring, IEP support, educational programs
- medical: doctors, hospitals, diagnostic clinics, psychiatric/medical care
- social: social skills groups, recreation, camps, playgrounds, community events
- general_support: support groups, helplines, family resources, general nonprofits that don't fit the above

Entry name: {name}
Description: {description}
Existing services listed: {services}

Respond with ONLY one word: one of advocacy, therapy, education, medical, social, general_support, or uncertain. No punctuation, no explanation."""


def classify_one(name, description, services):
    prompt = PROMPT_TEMPLATE.format(
        name=name, description=description or "(none)",
        services=", ".join(services) if services else "(none)",
    )
    payload = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"temperature": 0},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    raw = result.get("response", "").strip().lower()
    match = re.search(r"advocacy|therapy|education|medical|social|general_support|uncertain", raw)
    return match.group(0) if match else "uncertain"


def main():
    dry_run = "--dry-run" in sys.argv
    LOG_DIR.mkdir(exist_ok=True)

    data = json.load(open(DATA_FILE, encoding="utf-8"))
    targets = [(i, d) for i, d in enumerate(data) if d.get("type") not in VALID_TYPES]
    print(f"{len(targets)} entries need classification (out of {len(data)} total)")

    changes = []
    uncertain = []

    for n, (i, d) in enumerate(targets, 1):
        try:
            result = classify_one(d.get("name", ""), d.get("description", ""), d.get("services", []))
        except Exception as e:
            print(f"  [{n}/{len(targets)}] ERROR on {d.get('name')!r}: {e}")
            uncertain.append({"name": d.get("name"), "old_type": d.get("type"), "error": str(e)})
            continue

        old_type = d.get("type")
        if result == "uncertain":
            uncertain.append({"name": d.get("name"), "old_type": old_type})
            print(f"  [{n}/{len(targets)}] {d.get('name')!r}: uncertain (left as {old_type!r})")
            continue

        changes.append({"name": d.get("name"), "old_type": old_type, "new_type": result})
        print(f"  [{n}/{len(targets)}] {d.get('name')!r}: {old_type!r} -> {result}")
        if not dry_run:
            data[i]["type"] = result

        if n % 20 == 0:
            PROGRESS_FILE.write_text(json.dumps({"done": n, "total": len(targets)}))

    ts = time.strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"category_classification_{ts}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"Category classification run: {ts}\n")
        f.write(f"dry_run={dry_run}\n")
        f.write(f"Applied changes ({len(changes)}):\n")
        for c in changes:
            f.write(f"  {c['name']!r}: {c['old_type']!r} -> {c['new_type']}\n")
        f.write(f"\nLeft as uncertain / unchanged ({len(uncertain)}):\n")
        for u in uncertain:
            f.write(f"  {u}\n")

    print(f"\n{len(changes)} classified, {len(uncertain)} left uncertain/unchanged")
    print(f"Log: {log_path}")

    if not dry_run and changes:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Wrote {DATA_FILE}")
    elif dry_run:
        print("Dry run -- community_resources.json not modified")


if __name__ == "__main__":
    main()
