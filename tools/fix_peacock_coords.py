import json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
fixed = 0
for d in data:
    if d["name"] == "Georgina Peacock, M.D":
        d["coordinates"] = {"lat": 33.781177759541, "lng": -84.323095065058}
        fixed += 1
print("fixed:", fixed)

tmp = f"{REPO}/community_resources.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_resources.json")
print("total entries:", len(data))
