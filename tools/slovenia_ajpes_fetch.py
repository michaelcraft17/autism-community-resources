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

Genuinely tiny yield for a country of ~2.1M: exactly one organization
found, a sole-practitioner support center. The autocomplete endpoint
returns only the registered name string, not address/registration
details, and AJPES's full results page renders those client-side via
a separate call not yet identified -- rather than invest further
discovery effort for one entry, this ships as a placeless (country-
level) resource, consistent with how thin/partial sources elsewhere
in this project (e.g. the Autism-Europe PDF) are handled.

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

# Hand-verified against the live ajax.asp endpoint (see docstring); only one
# real hit found across all prefix variants tried.
ENTRIES = [
    {
        "name": "Avtizmu Naj Ambulanta - Center za pomoč osebam z avtizmom in njihovim družinam",
        "description": "Registered support center for people with autism and their families "
                        "(sole practitioner: Ana Bezenšek), based in Slovenia.",
    },
]


def main():
    resources = []
    for e in ENTRIES:
        resources.append({
            "name": e["name"],
            "type": "general_support",
            "source": SOURCE,
            "services": ["Information & Support"],
            "description": e["description"],
            "address": "Slovenia",
            "placeless": True,
        })

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(resources)} entries to {OUT_PATH}")


if __name__ == "__main__":
    main()
