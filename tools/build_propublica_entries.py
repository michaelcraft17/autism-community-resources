import json, os

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SRC = f"{SP}/propublica_details.jsonl"
DST = f"{SP}/propublica_autism.jsonl"

# B = Educational Institutions and Related Activities (NTEE major group) -> education.
# Everything else in this "autism" keyword search (G health/disease-disorder, H medical
# research, P human services, T philanthropy, etc.) defaults to advocacy - these are
# nonprofit support/awareness/service orgs, not literal social/recreation clubs, matching
# how ASAN/CPIR were classified earlier in this dataset.
def classify_type(ntee_code):
    if ntee_code and ntee_code.startswith("B"):
        return "education"
    return "advocacy"

NTEE_LABELS = {
    "G84": "Autism",
    "P82": "Developmentally Disabled Centers, Services",
    "P80": "Services to Promote the Independence of Specific Populations",
    "P20": "Human Service Organizations",
    "P01": "Alliance/Advocacy Organizations (Human Services)",
    "B28": "Special Education",
    "B01": "Alliance/Advocacy Organizations (Education)",
    "H84": "Autism Medical Research",
}

if __name__ == "__main__":
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    print(f"Total rows: {len(rows)}")

    kept = 0
    skipped_error = 0
    skipped_status = 0
    skipped_no_address = 0
    out_lines = []
    for row in rows:
        if "error" in row or "organization" not in row:
            skipped_error += 1
            continue
        org = row["organization"]

        if org.get("exempt_organization_status_code") not in (1, 2):
            skipped_status += 1
            continue

        street = (org.get("address") or "").strip()
        city = (org.get("city") or "").strip()
        state = (org.get("state") or "").strip()
        zipcode = (org.get("zipcode") or "").strip().split("-")[0]
        if not street or not city or not state:
            skipped_no_address += 1
            continue

        name = (org.get("name") or "").strip()
        ntee = org.get("ntee_code")
        ntee_label = NTEE_LABELS.get(ntee)

        entry = {
            "name": name,
            "address": f"{street}, {city}, {state} {zipcode}".strip(),
            "phone": "",
            "website": "",
            "type": classify_type(ntee),
            "source": "propublica-irs-autism",
            "services": [ntee_label] if ntee_label else ["Nonprofit autism/disability support organization"],
            "description": f"IRS-registered 501(c)(3) nonprofit"
                            + (f", NTEE classification: {ntee_label} ({ntee})" if ntee_label else
                               (f", NTEE code {ntee}" if ntee else ""))
                            + f". EIN {org.get('ein')}.",
            "coordinates": None,
            "suggested": {
                "free_services": False,
                "telehealth": False,
                "in_home": False,
                "accepts_medicaid": False,
                "early_intervention": False,
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

    print(f"kept: {kept}")
    print(f"skipped (API error): {skipped_error}")
    print(f"skipped (inactive/unknown status): {skipped_status}")
    print(f"skipped (no address): {skipped_no_address}")
    print(f"wrote: {DST}")
