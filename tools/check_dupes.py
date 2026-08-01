import json, re
from collections import defaultdict

REPO = "C:/Users/Lenovo/autism-community-resources"
data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))

groups = defaultdict(list)
for d in data:
    key = (re.sub(r"[^a-z0-9]", "", d["name"].lower()), re.sub(r"[^a-z0-9]", "", d["address"].split(",")[0].lower()))
    groups[key].append(d)

for key, items in groups.items():
    if len(items) > 1:
        print("=== DUPLICATE GROUP ===")
        for d in items:
            print(" -", d["name"], "|", d["address"], "|", d["source"], "|", d.get("npi_number", ""))
