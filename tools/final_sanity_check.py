import json, re

REPO = "C:/Users/Lenovo/autism-community-resources"
data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
new_sources = {"ndrn-protection-advocacy", "aucd-ucedd", "autism-care-network"}
specialty_services = {"Developmental-Behavioral Pediatrics", "Neurodevelopmental Disabilities",
                       "Child & Adolescent Psychiatry", "Pediatric Neurology"}

new = [d for d in data if d.get("source") in new_sources or
       (d.get("source") == "npi-registry" and d.get("services") and d["services"][0] in specialty_services)]
print("total new entries:", len(new))

# Rough bounding boxes: continental US + AK + HI + common territories
def plausible(lat, lng):
    boxes = [
        (24, 50, -125, -66),   # continental US
        (51, 72, -180, -129),  # Alaska
        (18, 23, -161, -154),  # Hawaii
        (17, 19, -68, -64),    # PR/VI
        (13, 21, 144, 146),    # Guam/N.Mariana
        (-15, -13, -171, -169),# American Samoa
    ]
    return any(a <= lat <= b and c <= lng <= d for a, b, c, d in boxes)

bad = [d for d in new if not d.get("coordinates") or
       not plausible(d["coordinates"]["lat"], d["coordinates"]["lng"])]
print("still-implausible coords:", len(bad))
for d in bad:
    print(" -", d["name"], "|", d["address"], "|", d.get("coordinates"))

# duplicate check within new entries + against rest of file
seen = {}
dupes = 0
for d in data:
    key = (re.sub(r"[^a-z0-9]", "", d["name"].lower()), re.sub(r"[^a-z0-9]", "", d["address"].split(",")[0].lower()))
    if key in seen:
        dupes += 1
    seen[key] = seen.get(key, 0) + 1
print("exact name+street duplicates in full dataset:", dupes)
