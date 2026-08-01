import json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

REMOVE_NAMES_ADDRS = {
    ("Kelton Thomas, M.D", "MONTEREALE 24, BUILDING 121, AVIANO, AE 33170"),
    ("Meagan Freeman, DO", "LANDSTUHL REGIONAL MEDICAL CENTER, APO, AE 09180"),
    ("Scott Guthrie, M.D", "52D MEDICAL GROUP, APO, AE 09126"),
    ("Jessica Stanfield, MD", "UNIT 3690 BOX MDG, APO, AE 09126"),
    ("Ann Etim, M.D", "NMRTC OKINAWA, FPO, AP 96362"),
    ("Razvan Adam, MD", "PSC 41, APO, AE 09464"),
    ("Shonda Janke, M.D", "LANDSTUHL REGIONAL MEDICAL CENTER, APO, NY 09180"),
    ("John Bell, MD", "PATCH ARMY HEALTH CLINIC STUTTGART, APO, AE 09107"),
    ("Ayesha Quraishy, M.D", "B-82 KDA SCHEME I -A, KARACHI, SINDH 75350"),
}

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
print(f"Before: {len(data)}")

kept = []
removed = 0
for d in data:
    key = (d["name"], d["address"])
    if key in REMOVE_NAMES_ADDRS:
        removed += 1
        print(f"  removing: {d['name']} | {d['address']}")
        continue
    if d["name"] == "Willough Jenkins, MD" and "CALIFORNIA" in d["address"]:
        d["address"] = d["address"].replace("CALIFORNIA", "CA")
        print(f"  normalized: {d['name']} -> {d['address']}")
    kept.append(d)

print(f"Removed: {removed}")
print(f"After: {len(kept)}")

tmp = f"{REPO}/community_resources.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(kept, f, indent=2, ensure_ascii=False)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_resources.json")
print("Wrote community_resources.json")
