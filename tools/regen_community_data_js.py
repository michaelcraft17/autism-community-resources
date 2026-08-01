import json, os

REPO = "C:/Users/Lenovo/autism-community-resources"

data = json.load(open(f"{REPO}/community_resources.json", encoding="utf-8"))
js = "window.communityData = " + json.dumps(data, ensure_ascii=False) + ";\n"

tmp = f"{REPO}/community_data.js.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(js)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, f"{REPO}/community_data.js")
print(f"Wrote community_data.js: {len(data)} entries, {os.path.getsize(f'{REPO}/community_data.js')} bytes")
