import json, re, os, time
import requests

SCRATCH = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\01dd4fda-bed2-4ee1-8d82-7a492c36c3ab\scratchpad"
PARSED = os.path.join(SCRATCH, "ndrn_parsed.json")
OUT = os.path.join(SCRATCH, "ndrn_pa.jsonl")

def geocode(street, city, state, zip5):
    try:
        r = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/address",
            params={"street": street, "city": city, "state": state, "zip": zip5,
                    "benchmark": "Public_AR_Current", "format": "json"},
            timeout=20,
        )
        r.raise_for_status()
        matches = r.json().get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            return {"lat": coords["y"], "lng": coords["x"]}
    except Exception as ex:
        print(f"  geocode error for {street}, {city}, {state}: {ex}")
    return None

def parse_addr_parts(address):
    # address like "street..., city, ST ZIP" possibly with extra comma segments (Office Location:/Mailing Address:)
    parts = [p.strip() for p in address.split(",")]
    # last part should be "ST ZIP" or "ST ZIP-XXXX"
    last = parts[-1]
    m = re.match(r"([A-Z]{2})\s+(\d{5})", last)
    if not m:
        return None
    state, zip5 = m.group(1), m.group(2)
    city = parts[-2] if len(parts) >= 2 else ""
    street = parts[-3] if len(parts) >= 3 else ""
    return street, city, state, zip5

def main():
    data = json.load(open(PARSED, encoding="utf-8"))

    # Fix known mojibake / verify against org's own site
    for d in data:
        if d["location_slug"] == "puerto-rico" and "Impedimentos" in d["name"]:
            d["name"] = "Oficina de Protección y Defensa de las Personas con Impedimentos"
            d["address"] = "Centro Gubernamental Minillas, Roberto Sánchez Vilella, Torre Sur, Piso 2, Oficina 203, Ave. De Diego, Parada 22, Santurce, PR 00912"
            d["phone"] = "(787) 665-2120"

    written = 0
    skipped_no_geo = []
    with open(OUT, "w", encoding="utf-8") as f:
        for d in data:
            addr_parts = parse_addr_parts(d["address"])
            services = ["Legal Advocacy", "Disability Rights", "Protection & Advocacy"]
            is_cap = "client assistance" in d["name"].lower()
            if is_cap:
                services = ["Client Assistance Program", "Vocational Rehabilitation Advocacy", "Disability Rights"]
                desc = f"{d['name']} is the federally designated Client Assistance Program (CAP) providing free advocacy for individuals seeking vocational rehabilitation services."
            else:
                desc = f"{d['name']} is the federally mandated Protection & Advocacy (P&A) system providing free legal advocacy for people with disabilities."

            coords = None
            if addr_parts:
                street, city, state, zip5 = addr_parts
                coords = geocode(street, city, state, zip5)
                time.sleep(0.3)
            else:
                skipped_no_geo.append(d["name"])

            entry = {
                "name": d["name"],
                "address": d["address"],
                "phone": d["phone"],
                "website": d["website"],
                "type": "advocacy",
                "source": "ndrn-protection-advocacy",
                "services": services,
                "description": desc,
                "coordinates": coords,
                "suggested": {
                    "free_services": True,
                    "telehealth": False,
                    "in_home": False,
                    "accepts_medicaid": False,
                    "early_intervention": False,
                    "bilingual": False,
                    "wheelchair_accessible": False,
                },
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} entries to {OUT}")
    if skipped_no_geo:
        print(f"Could not parse address for geocoding ({len(skipped_no_geo)}): {skipped_no_geo}")

if __name__ == "__main__":
    main()
