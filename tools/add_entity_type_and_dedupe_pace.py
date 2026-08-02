import json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))

for r in data:
    if r.get("source") == "npi-registry":
        r["entity_type"] = "organization" if "ABA / Behavioral Therapy" in (r.get("services") or []) else "individual"
    else:
        r["entity_type"] = "organization"

n_org = sum(1 for r in data if r["entity_type"] == "organization")
n_ind = sum(1 for r in data if r["entity_type"] == "individual")
print("organization:", n_org, " individual:", n_ind, " total:", len(data))

keep = None
drop_idx = None
for i, r in enumerate(data):
    if r["name"] == "PACE School" and "PRUNERIDGE" in r["address"].upper():
        drop_idx = i
    if r["name"] == "Pacific Autism Center for Education (PACE) - Pruneridge Campus":
        keep = r

assert keep is not None and drop_idx is not None
keep["description"] = keep["description"].rstrip(".") + ". WASC-accredited."
removed = data.pop(drop_idx)
print("removed:", removed["name"], removed["address"])

tmp = f"{REPO}/community_resources.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_resources.json")
print("saved. total records now:", len(data))
