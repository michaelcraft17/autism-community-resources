import json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
fixed = 0
for d in data:
    if d["name"] == "Jaime Ley, M.D" and d["address"] == "PO BOX 6998, SAN DIEGO, CA 92166":
        d["coordinates"] = {"lat": 32.7174202, "lng": -117.1627720}
        fixed += 1
print("fixed:", fixed)

tmp = f"{REPO}/community_resources.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_resources.json")
print("total entries:", len(data))
