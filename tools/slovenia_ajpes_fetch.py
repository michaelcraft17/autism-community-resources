#!/usr/bin/env python3
"""
Slovenian autism-related organizations from AJPES (Agencija Republike
Slovenije za javnopravne evidence in storitve / Agency for Public
Legal Records and Related Services)'s ePRS business register:

    https://www.ajpes.si/prs/ajax.asp?method=getNaziv&term=<prefix>&s=1

Free, no API key. Discovered by driving the register's own search
form (https://www.ajpes.si/prs/) once with Playwright and watching
its network requests -- the same one-time discovery technique used in
tools/belgium_kbo_fetch.py. This specific endpoint is a *prefix*
autocomplete (matches only the start of the registered company name),
not a substring/full-text search, which matters for a heavily-declined
language like Slovenian: querying the dictionary form "avtizem"
(autism) returns nothing, because the one real match in the registry
is named starting with "AVTIZMU..." (a declined form). "avti"/"avtiz"
as a shorter prefix catches it; other case-declined roots
(avtist/avtistič/avtistov/avtistk) were tried and returned nothing
further.

Genuinely tiny yield for autism specifically in a country of ~2.1M: exactly
one organization found, a sole-practitioner support center. The autocomplete
endpoint returns only the registered name string, not address/registration
details, and AJPES's full results page renders those client-side via
a separate call not yet identified -- rather than invest further
discovery effort for one entry, this ships as a placeless (country-
level) resource, consistent with how thin/partial sources elsewhere
in this project (e.g. the Autism-Europe PDF) are handled.

Disability-master pass: re-queried the same live endpoint with Slovenian
general-disability term prefixes ("invalid"/"invalidsko" -- disability/
disabled-person, the standard modern term; "down" -- Down syndrome). The
endpoint caps each response at 10 results and is a prefix match (see
docstring above), so several prefix variants were tried by hand
(invalid/invalidsko/invalidov) to sample past the cap; "invalidsko" alone
returned the same 10 as "invalid" plus one extra, suggesting this is close
to the full set for that root. Real, clearly disability-related hits
across "invalid"/"invalidsko"/"down": Ilco Slovenija's 5 regional ostomy-
patient chapters (Ljubljana/Maribor/Novo Mesto/Posavje/Koroška), 2 general
physical-disability advocacy societies (Bohinj, Brežice), 1 national
society ("Kengurujček"), 4 "invalidsko podjetje" sheltered-employment
companies (a real, legally-defined Slovenian company category for firms
that employ a quota of workers with disabilities -- DESERTA/JASPIS/LUMIA/
Posočje), and the national Down Syndrome Slovenia society. Excluded as
coincidental name matches with no corroborating disability connection,
same discipline as this project's other name-collision exclusions: "INVAL
ČIŠČENJE PROSTOROV" (a cleaning company), "GLUHICOM" (manufacturing/trade,
"gluh"=deaf appears to be unrelated wordplay/surname), "SLEPA PEGA"
("blind spot", a visual-stimuli-transfer tech company), "SINDROM PLUS"/
"SINDROM investicije" (catering and investment companies, "sindrom"
coincidental), and three "gibalno" ("movement")-prefixed entries (two
movement-therapy practices, one movement-arts society) too ambiguous to
confirm as disability-specific rather than general fitness/arts.

Usage:
    python3 tools/slovenia_ajpes_fetch.py

Writes:
    new_resources_slovenia.json   final resource-schema output (repo root)
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_slovenia.json")

SOURCE = "Slovenia AJPES ePRS business register - official national entity registry"

# Hand-verified against the live ajax.asp endpoint (see docstring).
ENTRIES = [
    {
        "name": "Avtizmu Naj Ambulanta - Center za pomoč osebam z avtizmom in njihovim družinam",
        "description": "Registered support center for people with autism and their families "
                        "(sole practitioner: Ana Bezenšek), based in Slovenia.",
        "scope": None,
    },
    {
        "name": "Invalid Društvo gibalno oviranih in oseb z invalidnostjo Bohinj",
        "description": "Registered society for people with physical disabilities and "
                        "disabilities generally, Bohinj, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalid Združenje gibalno oviranih in oseb z invalidnostjo Brežice",
        "description": "Registered association for people with physical disabilities and "
                        "disabilities generally, Brežice, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Ilco Ljubljana",
        "description": "Regional chapter of Ilco Slovenija, a national support society for "
                        "ostomy patients (a recognized disability/chronic-illness category), "
                        "Ljubljana, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Ilco Maribor",
        "description": "Regional chapter of Ilco Slovenija, a national support society for "
                        "ostomy patients, Maribor, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Ilco Novo Mesto",
        "description": "Regional chapter of Ilco Slovenija, a national support society for "
                        "ostomy patients, Novo Mesto, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Ilco Posavje",
        "description": "Regional chapter of Ilco Slovenija, a national support society for "
                        "ostomy patients, Posavje region, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Ilco za Koroško",
        "description": "Regional chapter of Ilco Slovenija, a national support society for "
                        "ostomy patients, Koroška region, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko društvo Kengurujček Slovenije",
        "description": "National disability-support society, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko podjetje DESERTA, družba za zaposlovanje invalidov",
        "description": "\"Invalidsko podjetje\" -- a legally-defined Slovenian company "
                        "category for firms that employ a quota of workers with "
                        "disabilities, wholesale trade sector, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko podjetje JASPIS",
        "description": "\"Invalidsko podjetje\" providing training, education, and "
                        "employment for people with disabilities, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko podjetje LUMIA, družba za rehabilitacijo, usposabljanje in zaposlovanje",
        "description": "\"Invalidsko podjetje\" providing rehabilitation, training, and "
                        "employment for people with disabilities, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Invalidsko podjetje Posočje",
        "description": "\"Invalidsko podjetje\" -- a legally-defined Slovenian company "
                        "category for firms that employ a quota of workers with "
                        "disabilities, Posočje region, Slovenia.",
        "scope": "general",
    },
    {
        "name": "Downov sindrom Slovenija, društvo za kakovostno življenje ljudi z Downovim sindromom",
        "description": "National Down Syndrome society, Slovenia.",
        "scope": "neurodevelopmental",
    },
]


def main():
    resources = []
    for e in ENTRIES:
        entry = {
            "name": e["name"],
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": e["description"],
            "address": "Slovenia",
            "placeless": True,
            "breadth": "core",
        }
        if e.get("scope"):
            entry["disability_scope"] = e["scope"]
        resources.append(entry)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(resources)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
