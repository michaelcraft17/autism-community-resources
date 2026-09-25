#!/usr/bin/env python3
"""
Brazil: IPEA "Mapa das OSCs" full base (round-3 research, A1).

Source: https://mapaosc.ipea.gov.br/base-dados -- the whole civil-society-
organization registry (every non-profit legal form in Brazil), semicolon-
separated, UTF-8, ~1.1M rows. Already has full address + lat/lon (comma as
decimal separator, fixed here), so no separate geocoding step needed.

The download filename is dated -- re-resolve from the base-dados page if this
404s: `curl -s https://mapaosc.ipea.gov.br/base-dados | grep -oE 'href="[^"]*\\.csv"'`.

Filters: name-regex match on autis/asperger (autism) or a broader disability
term list, `situacao_cadastral` == "Ativa" and `removida_do_mosc` == "não".
Category via CNAE (primary activity code), per tools/category_map.py's
BRAZIL_CNAE table, with a keyword override from the org's own name.
"""
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from category_map import classify, brazil_cnae_type

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = "/tmp/brazil_scratch/mosc.csv"
OUT_AUTISM = os.path.join(REPO, "new_resources_brazil_autism.json")
OUT_DISABILITY = os.path.join(REPO, "new_resources_brazil_disability.json")

AUTISM_RE = re.compile(r"autis|asperger", re.IGNORECASE)
DISABILITY_RE = re.compile(
    r"deficien|excepcion|apae\b|s[íi]ndrome de down|paralisia cerebral|"
    r"\bsurdo|\bcego|pestalozzi|intelectual|tdah|dislexia",
    re.IGNORECASE,
)
# Known false positives (none expected for these terms specifically, but keep
# the pattern consistent with the rest of the project's discipline).


def to_float(s):
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def build_entry(row, disability_scope):
    name = row["tx_razao_social_osc"].strip()
    trade_name = (row.get("tx_nome_fantasia_osc") or "").strip()
    lat = to_float(row.get("latitude"))
    lng = to_float(row.get("longitude"))
    cnae = (row.get("cnae") or "").strip()
    entry_type = classify(name, None, code_type=brazil_cnae_type(cnae))

    # municipio_nome has occasional genuine bad bytes upstream (a source data
    #-quality issue, not fixable by re-decoding); the address field's own
    # embedded city name is intact for the same rows, so prefer that for any
    # human-facing text.
    address = row.get("tx_endereco_completo") or ""
    addr_parts = [p.strip() for p in address.split(",") if p.strip()]
    # Brazilian format tail: "..., Bairro, City, UF[, CEP]" -- if the last
    # segment is a CEP (postal code, mostly digits), the city is 3rd-from-end,
    # not 2nd (which would be the UF state code).
    if len(addr_parts) >= 3 and re.match(r"^\d{5,9}$", addr_parts[-1]):
        city_display = addr_parts[-3]
    elif len(addr_parts) >= 2:
        city_display = addr_parts[-2]
    else:
        city_display = row.get("municipio_nome", "")
    uf = row.get("UF_Sigla", "")

    entry = {
        "name": trade_name if trade_name and len(trade_name) > 3 else name,
        "address": address or f"{city_display}, {uf}",
        "phone": "",
        "website": "",
        "type": entry_type,
        "source": "Brazil IPEA Mapa das OSCs (civil-society-organization registry) - official government open data",
        "services": [],
        "description": f"Registered Brazilian civil-society organization (CNAE {cnae}), {city_display}, {uf}",
        "external_id": row["cnpj"],
    }
    if lat is not None and lng is not None:
        entry["coordinates"] = {"lat": lat, "lng": lng}
    else:
        entry["placeless"] = True
    if disability_scope:
        entry["disability_scope"] = disability_scope
    return entry


def main():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: {CSV_PATH} not found. Download the CSV first (see docstring).")
        sys.exit(1)

    autism_out, disability_out = [], []
    seen_cnpj = set()
    total = 0
    with open(CSV_PATH, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            total += 1
            if row.get("situacao_cadastral") != "Ativa":
                continue
            if (row.get("removida_do_mosc") or "").strip().lower() == "sim":
                continue
            name = row.get("tx_razao_social_osc") or ""
            cnpj = row.get("cnpj")
            if cnpj in seen_cnpj:
                continue
            is_autism = bool(AUTISM_RE.search(name))
            is_disability = bool(DISABILITY_RE.search(name)) and not is_autism
            if not (is_autism or is_disability):
                continue
            seen_cnpj.add(cnpj)
            if is_autism:
                autism_out.append(build_entry(row, disability_scope=None))
            else:
                disability_out.append(build_entry(row, disability_scope="general"))

    print(f"Scanned {total} rows.")
    print(f"Autism-named, active: {len(autism_out)}")
    print(f"Disability-named, active: {len(disability_out)}")

    with open(OUT_AUTISM, "w", encoding="utf-8") as f:
        json.dump(autism_out, f, ensure_ascii=False)
    with open(OUT_DISABILITY, "w", encoding="utf-8") as f:
        json.dump(disability_out, f, ensure_ascii=False)
    print(f"Wrote {OUT_AUTISM} and {OUT_DISABILITY}")


if __name__ == "__main__":
    main()
