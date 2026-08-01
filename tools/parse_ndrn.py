import re, json, os

SCRATCH = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\01dd4fda-bed2-4ee1-8d82-7a492c36c3ab\scratchpad"
html = open(os.path.join(SCRATCH, "ndrn_raw.html"), encoding="utf-8").read()

# split into <li ... member_agency ...> blocks, keeping the opening tag (with class attr) for each
starts = list(re.finditer(r'<li class="(blog-item[^"]*)"', html))
items = []
for i, m in enumerate(starts):
    end = starts[i + 1].start() if i + 1 < len(starts) else len(html)
    items.append(m.group(1) + html[m.end():end])

def strip_tags(s):
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&amp;', '&').strip()
    return s

out = []
for it in items:
    name_m = re.search(r'<h3>(.*?)</h3>', it)
    if not name_m:
        continue
    name = strip_tags(name_m.group(1)).strip()

    addr_m = re.search(r'Address</div><div class="details-data"><address>(.*?)</address>', it, re.S)
    address_raw = strip_tags(addr_m.group(1)) if addr_m else ""
    address = " ".join(line.strip() for line in address_raw.splitlines() if line.strip())
    address = re.sub(r',\s*,', ',', address)
    # ensure commas between components (join lines with ', ' instead of raw concatenation)
    if addr_m:
        lines = [l.strip() for l in strip_tags(addr_m.group(1)).splitlines() if l.strip()]
        address = ", ".join(lines)

    phone_m = re.search(r'Phone</div><div class="details-data">(.*?)</div>', it, re.S)
    phone_raw = strip_tags(phone_m.group(1)) if phone_m else ""
    phone_first = phone_raw.splitlines()[0].strip() if phone_raw else ""

    website_m = re.search(r'Website</div><div class="details-data"><a href="([^"]+)"', it)
    website = website_m.group(1) if website_m else ""

    loc_m = re.search(r'agency_location-([a-z\-]+)', it)
    location_slug = loc_m.group(1) if loc_m else ""

    out.append({
        "name": name,
        "address": address,
        "phone": phone_first,
        "website": website,
        "location_slug": location_slug,
    })

print(f"Parsed {len(out)} agencies")
tmp = os.path.join(SCRATCH, "ndrn_parsed.json.tmp")
final = os.path.join(SCRATCH, "ndrn_parsed.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, final)

for o in out:
    print(o["location_slug"], "|", o["name"], "|", o["address"], "|", o["phone"], "|", o["website"])
