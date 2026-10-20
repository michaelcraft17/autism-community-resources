#!/usr/bin/env python3
"""
England (and Wales) special schools and mainstream SEN units from GIAS -- the Department for Education's
"Get Information About Schools" register (Open Government Licence v3), one keyless CSV:

    https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata<YYYYMMDD>.csv

The filename date changes daily and the newest snapshots are sometimes still being written (on 2026-10-12
the 20261011/20261012 files were 39-48 MB against a full 64.7 MB), so a snapshot is checked before use:

    python3 tools/gias_fetch.py [latest]    newest complete snapshot from yesterday back 14 days (the default)
    python3 tools/gias_fetch.py 20261010    that date only (checks a and b)

A snapshot is accepted only if (a) it has >= 50,000 data rows, (b) its last record has as many columns as the
header, and (c, latest only) it has >= 99.5% of the rows of a complete snapshot at least 3 days older (also
downloaded; if none in the window can be read, a and b decide and a warning is printed). Rejected files are
deleted so the next run downloads them again. Dates that are not published yet (or removed) answer 403/404/410 and
are skipped; a 401/451, or a 403 from every date in the window that answered, is recorded as a refusal. A failed
download (after rc.get's retries) is counted with rc.note_failure and the next older date is tried; the third one
ends the run. The date used is printed and recorded as rc.STATUS["input"].

Sets (open establishments only; cp1252 CSV):
  core   all special schools / special post-16 institutions (EstablishmentTypeGroup "Special schools" or a
         type containing "special"), plus mainstream schools with an SEN unit or resourced provision whose
         SEN1-13 fields include ASD (autism)
  broad  mainstream schools with an SEN unit / resourced provision that does NOT list ASD (hearing, vision,
         physical, learning units, ...) -> new_resources_gias_broad.json, merged separately
Pupil referral units are alternative provision rather than SEN provision and are not included.

Coordinates are British National Grid (EPSG:27700), converted with pyproj. Head teacher fields
(HeadFirstName/HeadLastName) are never read. Entries are disability_scope "general" (special schools serve
every need); the services list says "Autism Support" where ASD is a listed need.

Writes:
    tools/gias_scratch/edubase_<date>.csv    raw downloads, kept and reused (gitignored)
    new_resources_gias.json                  core
    new_resources_gias_broad.json            broad
"""
import csv
import datetime
import os
import re
import sys
import urllib.error
import urllib.parse

from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import registry_common as rc  # noqa: E402

SCRATCH = os.path.join(rc.REPO, "tools", "gias_scratch")
URL = "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{}.csv"
SOURCE = "England GIAS (DfE Get Information About Schools) - official register of schools, Open Government Licence"
BNG = Transformer.from_crs(27700, 4326, always_xy=True)
UNIT_TYPES = {"Resourced provision", "SEN unit", "Resourced provision and SEN unit"}
MIN_ROWS = 50000      # (a)
DAYS = 14             # "latest" tries yesterday back this many days
REF_GAP = 3           # (c) compares with a snapshot at least this many days older ...
REF_SHARE = 0.995     # ... and needs at least this share of its rows
MAX_FAILURES = 3      # failed downloads before giving up


def sen_needs(r):
    return [r[f"SEN{i} (name)"].split(" - ")[0].strip() for i in range(1, 14)
            if r.get(f"SEN{i} (name)") and r[f"SEN{i} (name)"] != "Not Applicable"]


def build(rows):
    core, broad = [], []
    for r in rows:
        if not r["EstablishmentStatus (name)"].startswith("Open"):
            continue
        special = r["EstablishmentTypeGroup (name)"] == "Special schools" or "special" in r["TypeOfEstablishment (name)"].lower()
        unit = r["TypeOfResourcedProvision (name)"] in UNIT_TYPES
        if not (special or unit):
            continue
        needs = sen_needs(r)
        asd = "ASD" in needs
        if not r["Easting"] or not r["Northing"]:
            continue
        lng, lat = BNG.transform(float(r["Easting"]), float(r["Northing"]))
        if not rc.plausible("GB", lat, lng):
            continue
        addr = ", ".join(rc.clean(r[k]) for k in ("Street", "Locality", "Town", "Postcode") if rc.clean(r[k]))
        kind = r["TypeOfEstablishment (name)"]
        ages = f", ages {r['StatutoryLowAge']}-{r['StatutoryHighAge']}" if r["StatutoryLowAge"] and r["StatutoryHighAge"] else ""
        if special:
            desc = f"{kind}{ages}."
        else:
            prov = r["TypeOfResourcedProvision (name)"].lower()
            desc = f"Mainstream school ({kind}) with an {prov}{ages}." if prov == "sen unit" else \
                   f"Mainstream school ({kind}) with {prov}{ages}."
        if needs:
            desc += " Needs catered for: " + ", ".join(needs) + "."
        services = ["Special Education"] + (["Autism Support"] if asd else [])
        e = rc.entry(r["EstablishmentName"], SOURCE, "education", services, desc, address=addr,
                     phone=r["TelephoneNum"], website=rc.clean_url(r["SchoolWebsite"]), lat=lat, lng=lng,
                     external_id=f"gias:{r['URN']}", breadth="core" if (special or asd) else "broad", scope="general")
        (core if e["breadth"] == "core" else broad).append(e)
    return core, broad


def snapshot_path(date):
    return os.path.join(SCRATCH, f"edubase_{date}.csv")


def problem(path):
    """(data rows, None) for a snapshot that passes checks a and b, else (rows, reason)."""
    n, width, last = 0, None, None
    try:
        with open(path, encoding="cp1252", newline="") as f:
            for row in csv.reader(f):
                if not row:
                    continue
                if width is None:
                    width = len(row)
                else:
                    n, last = n + 1, row
    except (csv.Error, UnicodeDecodeError) as e:
        return n, f"unreadable ({e})"
    if n < MIN_ROWS:
        return n, f"only {n} rows"
    if len(last) != width:
        return n, f"last record has {len(last)} of {width} columns"
    return n, None


class Finder:
    """Snapshots of the "latest" window: downloads once, remembers row counts, deletes partial files."""

    def __init__(self):
        self.rows = {}        # date -> rows of a snapshot that passed a and b, or None
        self.answers = {}     # date -> "403" / "404" / "410" / "failed" / "partial" / "ok"
        self.failures = 0

    def complete(self, date):
        if date not in self.rows:
            self.rows[date] = self._load(date)
        return self.rows[date]

    def _load(self, date):
        try:
            path = rc.download(URL.format(date), snapshot_path(date), probe=True)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):   # not published (yet), or removed
                self.answers[date] = str(e.code)
                return None
            if e.code in (401, 451):
                host = urllib.parse.urlsplit(URL).netloc
                rc.note_refusal(host, e.code, URL.format(date))
                sys.exit(f"GIAS: {host} refused {date} with HTTP {e.code}")
            self._failed(date, e)
            return None
        except Exception as e:  # noqa: BLE001
            self._failed(date, e)
            return None
        n, why = problem(path)
        if why:
            self.reject(date, why)
            return None
        self.answers[date] = "ok"
        return n

    def _failed(self, date, e):
        self.answers[date] = "failed"
        self.failures += 1
        rc.note_failure("gias_download", f"{date}: {e!r}")
        print(f"  {date}: download failed ({e!r})")
        if self.failures >= MAX_FAILURES:
            sys.exit(f"GIAS: {self.failures} failed downloads -- giving up")

    def reject(self, date, why):
        self.rows[date], self.answers[date] = None, "partial"
        print(f"  {date}: rejected, {why}; deleted")
        if os.path.exists(snapshot_path(date)):
            os.remove(snapshot_path(date))


def latest(today=None):
    """Newest snapshot from yesterday back DAYS days that passes checks a, b and c; returns its date."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    window = [(today - datetime.timedelta(days=k)).strftime("%Y%m%d") for k in range(1, DAYS + 1)]
    fd = Finder()
    for i, date in enumerate(window):
        n = fd.complete(date)
        if n is None:
            continue
        ref = next((d for d in window[i + REF_GAP:] if fd.complete(d) is not None), None)   # dates are a day apart
        if ref is None:
            msg = f"GIAS {date}: no complete snapshot {REF_GAP}+ days older in the window; accepted on checks a and b only"
            print("WARNING:", msg)
            rc.STATUS.setdefault("warnings", []).append(msg)
            return date
        if n < REF_SHARE * fd.rows[ref]:
            fd.reject(date, f"{n} rows vs {fd.rows[ref]} in {ref}")
            continue
        print(f"  {date}: {n} rows, {fd.rows[ref]} in {ref}")
        return date
    seen = set(fd.answers.values())
    if "403" in seen and seen <= {"403", "failed"}:   # every date that answered said 403
        rc.note_refusal(urllib.parse.urlsplit(URL).netloc, 403, f"every snapshot {window[-1]}-{window[0]} that answered said 403")
    sys.exit(f"GIAS: no complete snapshot from {window[0]} back to {window[-1]} "
             f"({', '.join(f'{d} {a}' for d, a in fd.answers.items())})")


def explicit(date):
    """The given date's snapshot, checked for a and b only."""
    path = rc.download(URL.format(date), snapshot_path(date))
    _, why = problem(path)
    if why:
        os.remove(path)
        sys.exit(f"{date}: {why} -- partial snapshot, deleted; pick another date or run with 'latest'")
    return date


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "latest"
    if arg == "latest":
        date = latest()
    elif re.fullmatch(r"\d{8}", arg):
        date = explicit(arg)
    else:
        sys.exit("usage: gias_fetch.py [latest | YYYYMMDD]")
    print(f"GIAS: using snapshot {date}")
    rc.STATUS["input"] = f"GIAS {date}"
    with open(snapshot_path(date), encoding="cp1252", newline="") as f:
        rows = list(csv.DictReader(f))
    core, broad = build(rows)
    print(f"GIAS {date}: {len(rows)} rows -> core {len(core)}, broad {len(broad)}")
    out = rc.finalize(os.path.join(rc.REPO, "new_resources_gias.json"), core)
    rc.finalize(os.path.join(rc.REPO, "new_resources_gias_broad.json"), broad)
    rc.spot_check(out, 10, fields=("name", "address", "services"))


if __name__ == "__main__":
    main()
