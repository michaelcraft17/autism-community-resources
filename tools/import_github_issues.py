#!/usr/bin/env python3
"""
Pulls community-submitted resources from GitHub issues into the harvest pipeline.

The site's "Suggest a Resource" button (index.html, SuggestModal) opens a prefilled
GitHub issue instead of posting anywhere -- there's no backend on a static GitHub
Pages site, so GitHub's own issue tracker doubles as the intake queue. This script
is the other half: it pulls open issues labeled `resource-suggestion`, parses the
`**Field:** value` markdown lines the form generates back into the resource-JSON
shape used by community_resources.json, and writes them to
new_resources_submissions.json -- the same gitignored scratch-file convention every
other source in this project uses (see new_resources_*.json in .gitignore).

This script deliberately does NOT geocode, merge, or close/label issues -- same
manual-review discipline as every other source in HANDOFF.md's data pipeline.
A submission is a claim from an anonymous visitor, not a verified official source;
it should get at least a quick look (does the org exist, is the website real)
before merging, the same way an LLM-narrated result would.

Human workflow to actually process a batch of submissions:
    1. python3 tools/import_github_issues.py
       -- review new_resources_submissions.json by hand; spot-check a few
          website/org names actually resolve to something real.
    2. Geocode the entries that lack `coordinates` (this script never guesses
       one) -- e.g. adapt tools/geocode_fill_missing.py, or add coordinates by
       hand for a small batch. Entries covering a whole country/region with no
       single address can instead be marked `"placeless": true`.
    3. python3 tools/merge_new_resources.py
    4. node gen_community_data.js
    5. Test locally (python3 -m http.server 8765), then commit.
    6. Manually close each imported issue on GitHub (`gh issue close <n>
       --comment "Added, thanks!"` or similar) so it doesn't get re-imported.

Requires the `gh` CLI, already authenticated (same tool this project's workflow
already uses elsewhere).
"""
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(REPO, "new_resources_submissions.json")

# Maps the human-readable **Type:** label the form writes back to the internal
# type key used throughout community_resources.json (see TYPE_META in index.html).
LABEL_TO_TYPE = {
    "advocacy": "advocacy",
    "therapy": "therapy",
    "education": "education",
    "medical": "medical",
    "social": "social",
    "general support": "general_support",
}

FIELD_RE = re.compile(r"^\*\*([^:*]+):\*\*\s*(.*)$")


def parse_body(body):
    fields = {}
    for line in (body or "").splitlines():
        m = FIELD_RE.match(line.strip())
        if m:
            fields[m.group(1).strip().lower()] = m.group(2).strip()
    return fields


def to_resource(fields, issue_number):
    name = fields.get("name", "").strip()
    country = fields.get("country", "").strip()
    description = fields.get("description", "").strip()
    missing = [k for k, v in (("Name", name), ("Country", country), ("Description", description)) if not v]
    if missing:
        return None, missing

    address = fields.get("address/city", "").strip()
    if address and country and country.lower() not in address.lower():
        address = f"{address}, {country}"
    elif not address:
        address = country

    type_label = fields.get("type", "").strip().lower()
    rtype = LABEL_TO_TYPE.get(type_label, "general_support")

    website = fields.get("website", "").strip()
    phone = fields.get("phone", "").strip()

    resource = {
        "name": name,
        "type": rtype,
        "source": f"Community submission (GitHub issue #{issue_number})",
        "services": ["Community submission -- unverified, review before merging"],
        "description": description,
        "address": address,
    }
    if website:
        resource["website"] = website
    if phone:
        resource["phone"] = phone
    return resource, []


def main():
    try:
        raw = subprocess.run(
            ["gh", "issue", "list", "--label", "resource-suggestion", "--state", "open",
             "--json", "number,title,body", "--limit", "200"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        print("gh CLI not found -- install/authenticate it first (same tool used elsewhere in this project).")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"gh issue list failed: {e.stderr}")
        sys.exit(1)

    issues = json.loads(raw.stdout)
    print(f"Open resource-suggestion issues found: {len(issues)}")

    resources = []
    flagged = []
    for issue in issues:
        fields = parse_body(issue.get("body", ""))
        resource, missing = to_resource(fields, issue["number"])
        if resource is None:
            flagged.append((issue["number"], issue.get("title", ""), missing))
        else:
            resources.append(resource)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resources, f, indent=2, ensure_ascii=False)

    print(f"Parsed cleanly: {len(resources)} -> {OUT_PATH}")
    if flagged:
        print(f"Flagged, NOT written (missing required fields), review by hand:")
        for number, title, missing in flagged:
            print(f"  #{number} \"{title}\" -- missing: {', '.join(missing)}")
    print("\nNone of these were geocoded, merged, or closed. See this script's docstring for the next steps.")


if __name__ == "__main__":
    main()
