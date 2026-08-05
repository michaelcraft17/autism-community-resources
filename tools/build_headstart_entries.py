import csv, json, os

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/HS_Service_Locations.csv"
DST = f"{SP}/head_start.jsonl"

# Well-established: 1 = Head Start, 2 = Early Head Start (the two dominant, universally
# documented program tiers). Codes 3-6 are smaller specialized variants (migrant/seasonal,
# American Indian/Alaska Native, etc.) whose exact code->label mapping isn't published in
# the dataset itself, so we describe them generically rather than assert an unverified guess.
PROGRAM_TYPE_LABEL = {
    "1": "Head Start",
    "2": "Early Head Start",
}

def clean_phone(*candidates):
    for c in candidates:
        c = (c or "").strip()
        if c:
            return c
    return ""

def build_address(row):
    parts = [row["address_line_one"].strip()]
    if row["address_line_two"].strip():
        parts[0] = parts[0] + " " + row["address_line_two"].strip()
    zip5 = row["zip"].strip()
    return f"{parts[0]}, {row['city'].strip()}, {row['state'].strip()} {zip5}"

if __name__ == "__main__":
    rows = list(csv.DictReader(open(SRC, encoding="utf-8-sig")))
    print(f"Total rows: {len(rows)}")

    kept = 0
    skipped_status = 0
    out_lines = []
    for row in rows:
        if row["status"] != "Open":
            skipped_status += 1
            continue

        program_label = PROGRAM_TYPE_LABEL.get(row["program_type"], "Head Start program")
        name = row["service_location_name"].strip()
        recipient = row["recipient_name"].replace("_", " ").strip()

        entry = {
            "name": name,
            "address": build_address(row),
            "phone": clean_phone(row["service_location_phone_number"], row["registration_phone_number"]),
            "website": "",
            "type": "education",
            "source": "head-start",
            "services": [program_label],
            "description": f"{program_label} location operated by {recipient.title()}"
                            + (f", {row['county'].strip()}" if row["county"].strip() else "")
                            + (f". Funded slots: {row['funded_slots']}." if row["funded_slots"].strip() else "."),
            "coordinates": {"lat": float(row["latitude"]), "lng": float(row["longitude"])},
            "suggested": {
                "free_services": True,
                "telehealth": False,
                "in_home": False,
                "accepts_medicaid": False,
                "early_intervention": True,
                "bilingual": False,
                "wheelchair_accessible": False,
            },
        }
        out_lines.append(json.dumps(entry, ensure_ascii=False))
        kept += 1

    tmp = DST + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out_lines) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DST)

    print(f"kept (status=Open): {kept}")
    print(f"skipped (Closed/Not Reported): {skipped_status}")
    print(f"wrote: {DST}")
