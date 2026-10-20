#!/usr/bin/env python3
"""
Norway: active special schools (skolekategori 12 "Spesialskole") from Udir's NSR (Nasjonalt skoleregister), keyless:

    https://data-nsr.udir.no/v4/enheter/skolekategori/12      list of units (orgnr, ErAktiv)
    https://data-nsr.udir.no/v4/enhet/<orgnr>                 detail: Beliggenhetsadresse, Koordinat, Internettadresse

Coordinates are in the detail record; a unit without one is geocoded with Kartverket and dropped if that fails too
(rc counts transient Kartverket failures in rc.STATUS). external_id "no-org:<orgnr>" (same key the Brreg fetcher uses,
which skips these organisation numbers, so run this first). Writes new_resources_nsr.json.
Any failed list or detail request (after rc.get's retries) stops the run, as do a detail answer without Navn and an
empty active list, so a partial file is never written. The active count is recorded as rc.STATUS["input"].
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SOURCE = "Norway Udir NSR (Nasjonalt skoleregister) - official school register"


def main():
    lst = rc.get_json("https://data-nsr.udir.no/v4/enheter/skolekategori/12", timeout=120)["EnhetListe"]
    active = [u["Organisasjonsnummer"] for u in lst if u.get("ErAktiv")]
    print(f"{len(lst)} special-school units, {len(active)} active")
    if not active:
        sys.exit("NSR: no active special-school units in the list -- the API changed? nothing written")
    rc.STATUS["input"] = f"NSR {len(active)} active units"
    entries = []
    kv = rc.Kartverket(os.path.join(rc.REPO, "tools", "nsr_scratch", "kartverket_cache.jsonl"))
    for org in active:
        d = rc.get_json(f"https://data-nsr.udir.no/v4/enhet/{org}", timeout=60, delay=0.2)
        if not isinstance(d, dict) or "Navn" not in d:   # an error body, not a unit record
            sys.exit(f"NSR {org}: detail answer is not a unit record ({str(d)[:200]!r}) -- nothing written")
        k = d.get("Koordinat") or {}
        a = d.get("Beliggenhetsadresse") or {}
        lat, lng = k.get("Breddegrad"), k.get("Lengdegrad")
        if not rc.plausible("NO", lat, lng):   # no NSR coordinate: official Kartverket address geocoder
            hit = kv.address(a.get("Adresse"), a.get("Postnummer"), (d.get("Kommune") or {}).get("Kommunenummer"))
            if not hit:
                print("  no coordinates:", d.get("Navn"))
                continue
            lat, lng = hit
        addr = ", ".join(x for x in (rc.clean(a.get("Adresse")), f"{rc.clean(a.get('Postnummer'))} {rc.clean(a.get('Poststed')).title()}".strip()) if x)
        owner = "private" if d.get("ErPrivatskole") else "public"
        pupils = f" {d['Elevtall']} pupils." if d.get("Elevtall") else ""
        stage = "primary and lower-secondary" if d.get("ErGrunnskole") or d.get("SkoletrinnGSFra") else "upper-secondary" if d.get("ErVideregaaendeSkole") else ""
        entries.append(rc.entry(d["Navn"], SOURCE, "education", ["Special Education"],
                                f"Special school (spesialskole), {owner}{', ' + stage if stage else ''}, {rc.clean((d.get('Kommune') or {}).get('Navn'))}.{pupils}".replace(", .", "."),
                                address=addr, website=rc.clean_url(d.get("Internettadresse")), lat=lat, lng=lng,
                                external_id=f"no-org:{org}", scope="general"))
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_nsr.json"), entries)
    rc.spot_check(out, 6, fields=("name", "address", "description"))


if __name__ == "__main__":
    main()
