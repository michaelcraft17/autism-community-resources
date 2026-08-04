import json, os

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
src = f"{SP}/sibshops.jsonl"
dst = f"{SP}/sibshops_clean.jsonl"

kept = 0
dropped_defunct = 0
dropped_malformed = 0
noted_restricted = 0

out_lines = []
for line in open(src, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    name = d.get("name", "")

    if "DEFUNCT" in name.upper():
        dropped_defunct += 1
        continue

    # malformed: name field holds a raw address (parsing bug), address field empty
    if len(name) > 25 and "," in name and any(ch.isdigit() for ch in name[:6]) and not d.get("address"):
        dropped_malformed += 1
        continue

    access = d.get("access", "")
    if access and "general community" not in access.lower():
        note = f" Access note: {access}."
        if note.strip() not in d.get("description", ""):
            d["description"] = (d.get("description") or "").rstrip() + note
        noted_restricted += 1

    d.pop("contact_name", None)
    d.pop("email", None)

    out_lines.append(json.dumps(d, ensure_ascii=False))
    kept += 1

tmp = dst + ".tmp"
with open(tmp, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(out_lines) + "\n")
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, dst)

print("kept:", kept)
print("dropped_defunct:", dropped_defunct)
print("dropped_malformed:", dropped_malformed)
print("noted_restricted:", noted_restricted)
print("wrote:", dst)
