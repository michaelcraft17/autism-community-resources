import csv, json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

def norm(addr):
    return " ".join((addr or "").strip().upper().split())

names = {}
with open(f"{REPO}/facility_names_filled.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        name = (row.get("facility_name") or "").strip()
        if name:
            names[norm(row["address"])] = name

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
applied = 0
for r in data:
    key = norm(r.get("address"))
    if key in names:
        r["facility_name"] = names[key]
        applied += 1

tmp = f"{REPO}/community_resources.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_resources.json")

print(f"Applied facility_name to {applied} records across {len(names)} named addresses.")
print("Now run tools/regen_community_data_js.py to rebuild community_data.js.")
