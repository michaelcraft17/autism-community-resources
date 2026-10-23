#!/usr/bin/env python3
"""
Refresh ONE registry source in the committed dataset (the data/ shards), or refuse loudly. The daily
"Registry refresh" workflow (.github/workflows/add-resources.yml) runs it; it also runs locally.

    python3 tools/refresh_source.py --check                 validate tools/refresh_sources.json against data/
    python3 tools/refresh_source.py --list                  the registry and the next 28 days of picks
    python3 tools/refresh_source.py --pick [NAME|scheduled] which source runs today ('' = scheduled)
    python3 tools/refresh_source.py --source NAME [--skip-fetch] [--dry-run] [--allow-drop] [--allow-change] [--force]
    python3 tools/refresh_source.py --record --picked NAME --push-result success|failure|skipped   rotation state

--source does, in order (the existing tools run as subprocesses):
  1. join_regions.py --force (refusing first if community_resources.json holds rows that are not in data/)
  2. the source's fetcher(s); raw downloads are deleted first so nothing stale is reused
  3. guards on the fetched rows, per (external_id prefix, source, breadth) group
  4. the source's old rows (by external_id prefix) are removed and merge_new_resources.py re-adds the fresh
     ones with its usual dedupe (+ dedupe_registry_vs_manual.py for charity registers); no other row is touched
  5. fresh rows go back into their old slots, so an unchanged source gives a zero diff
  6. split_by_region.py runs in tools/refresh_scratch/split/, and the result is checked before data/ is touched
  7. changed shards are copied into data/ (manifest last; restored from a backup if anything fails)
Exit codes: 0 ok (changed / unchanged / warming / none), 2 a guard tripped, 1 an error or refusal.
Nothing is committed here; the workflow commits data/ only when this exits 0 with status=changed.

Testing knob: REFRESH_TODAY=YYYY-MM-DD overrides today's date.
"""
import argparse
import datetime as dt
import filecmp
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import registry_common as rc  # noqa: E402

REGISTRY = os.path.join(TOOLS, "refresh_sources.json")
SCRATCH = os.path.join(TOOLS, "refresh_scratch")
STATE = os.path.join(SCRATCH, "state.json")
OUTCOME = os.path.join(SCRATCH, "outcome.json")
COMMIT_MSG = os.path.join(SCRATCH, "commit_message.txt")
SUMMARY_LOG = os.path.join(TOOLS, "logs", "refresh_summary.json")
FLAT = os.path.join(REPO, "community_resources.json")
DATA = os.path.join(REPO, "data")
README = os.path.join(REPO, "README.md")
INDEX = os.path.join(REPO, "index.html")
CACHE_GLOB = "tools/*_scratch/*cache*.jsonl"
CATCH_ALL = ("world/all.json", "us/national.json", "europe/other.json")
MOJIBAKE = ("�", "Ã", "â€")
FILL_FIELDS = ("address", "phone", "website")
FIELD_CLASS = {"coordinates": "coordinates", "placeless": "coordinates", "name": "name", "address": "address",
               "phone": "contact", "website": "contact", "description": "description", "services": "description",
               "type": "category", "breadth": "category", "disability_scope": "category"}
NON_SUBSTANTIVE = {"description"}
# The static "N+" figure in README.md and the three <meta> descriptions in index.html (each anchored, so the
# code comment and the unrelated "220,000 employees" text in index.html can never match).
COUNT_PATTERNS = [
    (README, re.compile(r"(over )(\d{1,3}(?:,\d{3})+)( of them)"), 1),
    (README, re.compile(r"(\*\*)(\d{1,3}(?:,\d{3})+)(\+ resources\*\*)"), 1),
    (INDEX, re.compile(r'(content=")(\d{1,3}(?:,\d{3})+)(\+ autism)'), 3),
]


class Fail(Exception):
    """code 2 = a guard tripped, 1 = an error or a refusal."""

    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.status = status or ("guard" if code == 2 else "failed")


def log(msg):
    print(f"[refresh] {msg}", flush=True)


def today():
    s = os.environ.get("REFRESH_TODAY")
    return dt.date.fromisoformat(s) if s else dt.datetime.now(dt.timezone.utc).date()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, **kw)
    os.replace(tmp, path)


def row_bytes(e):
    """Exactly how split_by_region.write_shard serialises a row."""
    return json.dumps(e, ensure_ascii=False, separators=(",", ":"))


def row_digest(e):
    return hashlib.blake2b(json.dumps(e, ensure_ascii=False, sort_keys=True).encode(), digest_size=16).digest()


def prefix_of(e):
    eid = e.get("external_id")
    if not isinstance(eid, str) or ":" not in eid:
        return None
    return eid.split(":", 1)[0]


def gkey(e):
    return (prefix_of(e), e.get("source"), e.get("breadth"))


def run(cmd, **kw):
    log("$ " + " ".join(os.path.relpath(c, REPO) if os.path.isabs(c) and c.startswith(REPO) else c for c in cmd[1:]))
    return subprocess.run(cmd, **kw)


# ── registry and state ────────────────────────────────────────────────────────────────────────────

def load_registry():
    reg = read_json(REGISTRY)
    sources = []
    for s in reg["sources"]:
        src = dict(reg["defaults"])
        src.update(s)
        src.setdefault("post_dedupe", False)
        src.setdefault("allow_placeless", False)
        src["prefixes"] = sorted({g["prefix"] for g in s["groups"]})
        keys = [(g["prefix"], g["source"], g["breadth"]) for g in s["groups"]]
        for g, k in zip(src["groups"], keys):
            g.setdefault("label", f"{g['prefix']} {g['breadth']}" if sum(x[0] == k[0] for x in keys) > 1 and
                         sum(x[0] == k[0] and x[2] == k[2] for x in keys) == 1 else g["prefix"])
        labels = [g["label"] for g in src["groups"]]
        if len(labels) != len(set(labels)):
            raise Fail(1, f"{src['name']}: group labels must be unique ({labels}); set 'label' on the groups")
        sources.append(src)
    return reg, sources


def get_source(name):
    _, sources = load_registry()
    for s in sources:
        if s["name"] == name:
            return s
    raise Fail(1, f"unknown source {name!r}; known: {', '.join(s['name'] for s in sources)}")


def load_state():
    try:
        st = read_json(STATE)
        st.setdefault("sources", {})
        return st
    except (OSError, ValueError):
        return {"sources": {}}


def save_state(st):
    write_json(STATE, st, indent=1, sort_keys=True)


def days_overdue(src, st, day):
    """None when not due (or cooling down after a failure); a source never refreshed counts as most overdue."""
    s = st["sources"].get(src["name"], {})
    cd = s.get("cooldown_until")
    if cd and day < dt.date.fromisoformat(cd):
        return None
    last = s.get("last_success")
    if not last:
        return 10 ** 6
    over = (day - (dt.date.fromisoformat(last) + dt.timedelta(days=src["every_days"]))).days
    return over if over >= 0 else None


def choose(sources, st, day):
    best = None
    for i, src in enumerate(sources):
        over = days_overdue(src, st, day)
        if over is not None and (best is None or over > best[0]):
            best = (over, i, src["name"])
    return best[2] if best else "none"


# ── reporting ─────────────────────────────────────────────────────────────────────────────────────

def gh_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def step_summary(line):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_url():
    if os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return None


def fmt_dur(s):
    s = int(round(s))
    return f"{s // 60}m{s % 60:02d}s"


# ── data helpers ──────────────────────────────────────────────────────────────────────────────────

def scan_shards(data_dir, is_source, digests=False):
    """Per shard: (rows, source rows); optionally a Counter of row digests over all shards."""
    man = read_json(os.path.join(data_dir, "manifest.json"))
    info, dig, total = {}, Counter(), 0
    for it in man["files"]:
        rows = read_json(os.path.join(data_dir, it["file"]))
        if len(rows) != it["count"]:
            raise Fail(1, f"{data_dir}/{it['file']}: manifest says {it['count']} rows, found {len(rows)}")
        info[it["file"]] = (len(rows), sum(1 for e in rows if is_source(e)))
        total += len(rows)
        if digests:
            dig.update(row_digest(e) for e in rows)
    if total != man["total"]:
        raise Fail(1, f"{data_dir}/manifest.json total {man['total']} != shard rows {total}")
    return man, info, dig


def flat_matches_data():
    """True when community_resources.json is absent or holds exactly the rows in data/ (as a multiset)."""
    if not os.path.exists(FLAT):
        return True, 0
    _, _, dig = scan_shards(DATA, lambda e: False, digests=True)
    flat = Counter(row_digest(e) for e in read_json(FLAT))
    diff = sum(((flat - dig) + (dig - flat)).values())
    return diff == 0, diff


def schema_problem(e, src):
    if not isinstance(e.get("name"), str) or not e["name"].strip():
        return "missing name"
    if e.get("type") not in rc.VALID_TYPES:
        return f"bad type {e.get('type')!r}"
    if not isinstance(e.get("services"), list):
        return "services is not a list"
    if not isinstance(e.get("description"), str):
        return "description is not a string"
    if e.get("breadth") not in ("core", "broad"):
        return f"bad breadth {e.get('breadth')!r}"
    if "disability_scope" in e and e["disability_scope"] not in ("general", "neurodevelopmental"):
        return f"bad disability_scope {e.get('disability_scope')!r}"
    c = e.get("coordinates")
    if c:
        if not isinstance(c, dict) or not rc.plausible(src["country"], c.get("lat"), c.get("lng")):
            return f"coordinates outside {src['country']}"
    elif not (e.get("placeless") and src["allow_placeless"]):
        return "no coordinates"
    return None


def has_mojibake(e):
    text = " ".join(str(e.get(k) or "") for k in ("name", "address", "description"))
    return any(m in text for m in MOJIBAKE)


def haversine_m(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(min(1.0, math.sqrt(h)))


def floor_for(old_n, g, src, allow_drop):
    if allow_drop:
        return 0
    if not old_n:
        return g["min_rows"]
    return max(g["min_rows"], old_n - max(math.ceil(old_n * src["max_drop_pct"] / 100), 3))


# ── count copy ────────────────────────────────────────────────────────────────────────────────────

def plan_count_copy(total, warnings):
    """{path: new_text} when the rounded static figure must change, {} when it already matches.
    A pattern that no longer matches exactly (copy reworded) is a warning, never a failed refresh."""
    figure = f"{total // 10000 * 10000:,}"
    texts, found = {}, []
    for path, pat, n in COUNT_PATTERNS:
        texts.setdefault(path, open(path, encoding="utf-8").read())
        hits = pat.findall(texts[path])
        if len(hits) != n:
            warnings.append(f"count copy: expected {n} match(es) of {pat.pattern!r} in {os.path.basename(path)}, "
                            f"found {len(hits)}; static count left as is")
            return {}, None
        found += [h[1] for h in hits]
    if len(set(found)) != 1:
        warnings.append(f"count copy: the static figures disagree ({sorted(set(found))}); left as is")
        return {}, None
    if found[0] == figure:
        return {}, None
    new = dict(texts)
    for path, pat, _ in COUNT_PATTERNS:
        new[path] = pat.sub(lambda m: m.group(1) + figure + m.group(3), new[path])
    for path in texts:   # only the matched lines may differ
        a, b = texts[path].split("\n"), new[path].split("\n")
        changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        expect = sum(n for p, _, n in COUNT_PATTERNS if p == path)
        if len(a) != len(b) or len(changed) != expect:
            warnings.append(f"count copy: unexpected edit shape in {os.path.basename(path)}; left as is")
            return {}, None
    return {p: t for p, t in new.items() if t != texts[p]}, {"from": found[0], "to": figure}


# ── the refresh ───────────────────────────────────────────────────────────────────────────────────

class Refresh:
    def __init__(self, src, args):
        self.src, self.args = src, args
        self.prefixes = set(src["prefixes"])
        self.groups = {(g["prefix"], g["source"], g["breadth"]): g for g in src["groups"]}
        self.warnings = []
        self.o = {"source": src["name"], "label": src["label"], "date": today().isoformat(), "dry_run": bool(args.dry_run),
                  "status": "failed", "message": "", "warnings": self.warnings, "run_url": run_url()}
        self.joined = False
        self.t0 = time.monotonic()

    def is_source(self, e):
        return prefix_of(e) in self.prefixes

    def glabel(self, k):
        g = self.groups.get(k)
        return g["label"] if g else f"{k[0]}/{k[2]} ({str(k[1])[:40]})"

    # 1 ─ join
    def join(self):
        if not self.args.force:
            ok, diff = flat_matches_data()
            if not ok:
                raise Fail(1, f"community_resources.json differs from data/ in {diff} rows (unsplit local work?). Run "
                              "tools/split_by_region.py to keep it, or pass --force to discard it.")
        r = run([sys.executable, os.path.join(TOOLS, "join_regions.py"), "--force"], cwd=REPO)
        if r.returncode:
            raise Fail(1, "join_regions.py failed")
        self.joined = True
        self.d0 = read_json(FLAT)
        self.old_man, self.old_info, _ = scan_shards(DATA, self.is_source)
        self.old = [e for e in self.d0 if self.is_source(e)]
        unknown = Counter(gkey(e) for e in self.old if gkey(e) not in self.groups)
        if unknown:
            raise Fail(1, "rows with this source's prefixes but an unregistered (source, breadth): "
                          + "; ".join(f"{self.glabel(k)} x{n}" for k, n in unknown.items())
                          + " -- update tools/refresh_sources.json")
        ids = [e["external_id"] for e in self.old]
        if len(ids) != len(set(ids)):
            raise Fail(1, "duplicate external_ids among the source's current rows")
        self.old_by_id = {e["external_id"]: e for e in self.old}
        self.old_groups = defaultdict(list)
        for e in self.old:
            self.old_groups[gkey(e)].append(e)
        self.o["total_before"] = len(self.d0)
        log(f"{self.src['name']}: {len(self.old)} current rows in {len(self.old_groups)} group(s); dataset {len(self.d0):,}")

    def drop_outputs(self):
        """A fetch that can't be merged (refused, crashed, partial) must not leave outputs for a later --skip-fetch."""
        for out in self.src["outputs"]:
            path = os.path.join(REPO, out)
            if os.path.exists(path):
                os.remove(path)

    # 2 ─ fetch
    def fetch(self):
        src = self.src
        os.makedirs(SCRATCH, exist_ok=True)
        for pat in src["raw"]:
            for p in glob.glob(os.path.join(REPO, pat)):
                os.remove(p)
        for out in src["outputs"]:
            if os.path.exists(os.path.join(REPO, out)):
                os.remove(os.path.join(REPO, out))
        prior = os.path.join(SCRATCH, "prior_rows.json")
        write_json(prior, {e["external_id"]: {"address": e.get("address", ""), "coordinates": e.get("coordinates")}
                           for e in self.old})
        deadline = time.monotonic() + src["timeout_minutes"] * 60
        budget = int(src["nominatim_max_new"])
        official = int(src["official_geocoder_max_new"])
        agg = {"nominatim_new": 0, "official_new": 0, "budget_skipped": 0, "prior_reused": 0, "refused": [], "transient": Counter(),
               "transient_examples": [], "input": []}
        t0 = time.monotonic()
        for i, cmd in enumerate(src["commands"]):
            sf = os.path.join(SCRATCH, f"status_{i}.json")
            if os.path.exists(sf):
                os.remove(sf)
            env = dict(os.environ, NOMINATIM_MAX_NEW=str(max(0, budget - agg["nominatim_new"])),
                       OFFICIAL_GEOCODER_MAX_NEW=str(max(0, official - agg["official_new"])), RC_PRIOR_ROWS=prior,
                       RC_STATUS_FILE=sf, PYTHONUNBUFFERED="1")
            left = deadline - time.monotonic()
            if left <= 0:
                raise Fail(1, f"fetch time limit ({src['timeout_minutes']} min) reached before {cmd[0]}")
            try:
                r = run([sys.executable, *[os.path.join(REPO, c) if j == 0 else c for j, c in enumerate(cmd)]],
                        cwd=REPO, env=env, timeout=left)
            except subprocess.TimeoutExpired:
                self.drop_outputs()
                raise Fail(1, f"{cmd[0]} hit the {src['timeout_minutes']}-minute fetch limit") from None
            st = None
            if os.path.exists(sf):
                st = read_json(sf)
                for k in ("nominatim_new", "official_new", "budget_skipped", "prior_reused"):
                    agg[k] += st.get(k, 0)
                agg["refused"] += st.get("refused", [])
                agg["transient"].update(st.get("transient", {}))
                agg["transient_examples"] += st.get("transient_examples", [])
                if st.get("input"):
                    agg["input"].append(st["input"])
                self.warnings.extend(f"{os.path.basename(cmd[0])}: {w}" for w in st.get("warnings", []))
            else:
                self.warnings.append(f"{cmd[0]} wrote no status file")
            if agg["refused"] or r.returncode:
                self.drop_outputs()
            if agg["refused"]:
                hosts = ", ".join(sorted({f"{x['host']} ({x['code']})" for x in agg["refused"]}))
                raise Fail(1, f"refused by {hosts}: a block, WAF, CAPTCHA or rate-limit ban is reported, not worked "
                              "around. Nothing was merged.", status="refused")
            if r.returncode:
                raise Fail(1, f"{cmd[0]} exited with code {r.returncode}")
        for ex in agg["transient_examples"][:10]:   # the log is the only place a CI failure can be read
            print(f"[refresh] transient failure: {ex}", flush=True)
        self.o.update(fetch_s=round(time.monotonic() - t0), nominatim_new=agg["nominatim_new"],
                      official_new=agg["official_new"],
                      prior_reused=agg["prior_reused"], transient=dict(agg["transient"]),
                      transient_examples=agg["transient_examples"][:10], input=agg["input"])
        return agg

    # 3 ─ load + pre-merge guards
    def load_outputs(self):
        rows = []
        for out in self.src["outputs"]:
            path = os.path.join(REPO, out)
            if not os.path.exists(path):
                raise Fail(2, f"{out} was not written")
            part = read_json(path)
            if not isinstance(part, list):
                raise Fail(2, f"{out} is not a JSON list")
            rows += part
        self.fetched = rows
        self.o["fetched"] = len(rows)
        return rows

    def premerge_guards(self):
        a, src, problems = self.args, self.src, []
        new_groups, seen, schema_bad = defaultdict(list), set(), Counter()
        for e in self.fetched:
            k = gkey(e)
            if k not in self.groups:
                problems.append(f"fetched row in an unregistered group {self.glabel(k)}: {e.get('name')!r}")
                if len(problems) > 20:
                    break
                continue
            eid = e["external_id"]
            if eid in seen:
                problems.append(f"duplicate external_id across the outputs: {eid}")
            seen.add(eid)
            p = schema_problem(e, src)
            if p:
                schema_bad[p] += 1
                if sum(schema_bad.values()) <= 5:
                    log(f"  bad row ({p}): {e.get('name')!r} {eid} {e.get('coordinates')}")
            new_groups[k].append(e)
        for p, n in schema_bad.items():
            problems.append(f"{n} row(s): {p}")
        for k, g in self.groups.items():
            old, new = self.old_groups.get(k, []), new_groups.get(k, [])
            lo = floor_for(len(old), g, src, a.allow_drop)
            if len(new) < lo:
                problems.append(f"{g['label']}: fetched {len(new)} rows, needs >= {lo} (now {len(old)}, min_rows "
                                f"{g['min_rows']}, max drop {src['max_drop_pct']}%)")
            if not a.allow_change and len(old) >= 10 and len(new) > len(old) * (1 + src["max_growth_pct"] / 100) + 3:
                problems.append(f"{g['label']}: fetched {len(new)} rows, more than +{src['max_growth_pct']}% over {len(old)} "
                                "(a broken filter?)")
            if not a.allow_change and len(old) >= 20 and new:
                for f in FILL_FIELDS:
                    ro = sum(1 for e in old if e.get(f)) / len(old)
                    rn = sum(1 for e in new if e.get(f)) / len(new)
                    if (ro - rn) * 100 > src["max_fill_drop_pts"]:
                        problems.append(f"{g['label']}: '{f}' filled in {rn:.0%} of fetched rows vs {ro:.0%} now")
                mo, mn = sum(map(has_mojibake, old)), sum(map(has_mojibake, new))
                if mn > mo + 2:
                    problems.append(f"{g['label']}: {mn} rows with mojibake (U+FFFD/Ã/â€) vs {mo} now -- an encoding change?")
        if not self.fetched:
            problems.append("no rows fetched")
        if problems:
            raise Fail(2, "pre-merge guards: " + " | ".join(problems[:25]))
        self.o["groups"] = [{"group": g["label"], "before": len(self.old_groups.get(k, [])), "fetched": len(new_groups.get(k, []))}
                            for k, g in self.groups.items()]

    # 4 ─ merge
    def merge(self):
        base = [e for e in self.d0 if not self.is_source(e)]
        write_json(FLAT, base)
        r = run([sys.executable, os.path.join(TOOLS, "merge_new_resources.py"),
                 *[os.path.join(REPO, o) for o in self.src["outputs"]]], cwd=REPO)
        if r.returncode:
            raise Fail(1, "merge_new_resources.py failed")
        if self.src["post_dedupe"]:
            r = run([sys.executable, os.path.join(TOOLS, "dedupe_registry_vs_manual.py"), *self.src["prefixes"]], cwd=REPO)
            if r.returncode:
                raise Fail(1, "dedupe_registry_vs_manual.py failed")
        merged = read_json(FLAT)
        non_src = [e for e in merged if not self.is_source(e)]
        if len(non_src) != len(base) or any(x != y for x, y in zip(non_src, base)):
            raise Fail(1, "the merge changed rows of other sources; refusing")
        self.base = base
        self.fresh = [e for e in merged if self.is_source(e)]
        ids = [e["external_id"] for e in self.fresh]
        if len(ids) != len(set(ids)):
            raise Fail(1, "duplicate external_ids after the merge")

    # 5 ─ post-merge checks, reorder, diff
    def reconcile(self):
        a, src = self.args, self.src
        fresh_groups = defaultdict(list)
        for e in self.fresh:
            fresh_groups[gkey(e)].append(e)
        problems = []
        for k, g in self.groups.items():
            old_n, kept = len(self.old_groups.get(k, [])), len(fresh_groups.get(k, []))
            lo = floor_for(old_n, g, src, a.allow_drop)
            if kept < lo:
                problems.append(f"{g['label']}: {kept} rows survive the merge, needs >= {lo} (now {old_n})")
        if problems:
            raise Fail(2, "post-merge guards: " + " | ".join(problems))

        fresh_by_id = {e["external_id"]: e for e in self.fresh}
        O, S = set(self.old_by_id), set(fresh_by_id)
        F = {e.get("external_id") for e in self.fetched}
        result = []
        for e in self.d0:
            if self.is_source(e):
                f = fresh_by_id.get(e["external_id"])
                if f is not None:
                    result.append(f)
            else:
                result.append(e)
        result += [e for e in self.fresh if e["external_id"] not in O]
        if len(result) != len(self.base) + len(self.fresh):
            raise Fail(1, "reorder lost or duplicated rows")
        self.result = result

        added, removed = S - O, O - S
        changed, by_field, shift = [], Counter(), 0.0
        subst = Counter()
        for i in O & S:
            old, new = self.old_by_id[i], fresh_by_id[i]
            if row_bytes(old) == row_bytes(new):
                continue
            changed.append(i)
            classes = {FIELD_CLASS.get(f, "other") for f in set(old) | set(new) if old.get(f) != new.get(f)} or {"key order"}
            by_field.update(classes)
            if classes - NON_SUBSTANTIVE:
                subst[gkey(new)] += 1
            if old.get("coordinates") and new.get("coordinates"):
                shift = max(shift, haversine_m(old["coordinates"], new["coordinates"]))
        dropped = self.explain_drops((O & F) - S) if (O & F) - S else []
        rekeyed = self.rekeyed(removed, added, fresh_by_id)
        for k, g in self.groups.items():
            old_n = len(self.old_groups.get(k, []))
            if not a.allow_change and old_n >= 20 and subst[k] * 100 / old_n > src["max_changed_pct"]:
                problems.append(f"{g['label']}: {subst[k]} of {old_n} rows changed name/address/location/contact/category "
                                f"(> {src['max_changed_pct']}%) -- a parser change? (--allow-change to accept)")
            # ids replaced by new ids (a re-keyed layer, or another set of rows of about the same size); a pure drop
            # is the row-count floors' job
            old_ids = {e["external_id"] for e in self.old_groups.get(k, [])}
            new_ids = {e["external_id"] for e in fresh_groups.get(k, [])}
            replaced = min(len(old_ids - new_ids), len(new_ids - old_ids))
            if not a.allow_change and old_n >= 20 and replaced * 100 / old_n > src["max_changed_pct"]:
                problems.append(f"{g['label']}: {replaced} of {old_n} ids replaced by new ids (> {src['max_changed_pct']}%) -- "
                                "re-keyed ids or a different row set? (--allow-change to accept)")
        if problems:
            raise Fail(2, "change guard: " + " | ".join(problems))
        for row in self.o.get("groups", []):
            k = next(k for k, g in self.groups.items() if g["label"] == row["group"])
            ids_old = {e["external_id"] for e in self.old_groups.get(k, [])}
            ids_new = {e["external_id"] for e in fresh_groups.get(k, [])}
            row.update(after=len(ids_new), added=len(ids_new - ids_old), removed=len(ids_old - ids_new),
                       changed=sum(1 for i in changed if i in ids_new))
        self.counts = (len(added), len(removed), len(changed))
        self.o.update(added=len(added), removed=len(removed), changed=len(changed),
                      removed_upstream=len(O - F), dropped_by_merge=dropped, rekeyed=rekeyed,
                      changed_by_field=dict(by_field), max_coord_shift_m=round(shift, 1),
                      removed_ids=sorted(removed)[:200], added_ids=sorted(added)[:200], total_after=len(result))
        log(f"diff: +{len(added)} added, -{len(removed)} removed ({len(O - F)} gone upstream, {len(dropped)} skipped by "
            f"the merge, {rekeyed} re-keyed), ~{len(changed)} changed {dict(by_field)}")

    def explain_drops(self, ids):
        """Why the merge/dedupe skipped fetched rows that are in the dataset today (rename, move, hand edit)."""
        import merge_new_resources as mn
        holders, triples = defaultdict(set), {}
        for e in self.base:
            holders[(mn.norm_name(e.get("name")), mn.norm_city(e.get("address")))].add(e.get("source"))
            triples[(e.get("name") or "", e.get("address") or "", e.get("source") or "")] = e.get("source")
        out = []
        for e in self.fetched:
            if e.get("external_id") not in ids:
                continue
            h = holders.get((mn.norm_name(e.get("name")), mn.norm_city(e.get("address"))))
            t = (e.get("name") or "", e.get("address") or "", e.get("source") or "")
            if h:
                why = "name+city held by " + "; ".join(sorted(str(s)[:60] for s in h))
            elif t in triples:
                why = "same name|address|source as an existing row"
            elif self.src["post_dedupe"]:
                why = "dedupe_registry_vs_manual: same website as an id-less row"
            else:
                why = "duplicate among the fetched rows"
            out.append({"id": e["external_id"], "name": e.get("name"), "why": why})
        return out[:200]

    def rekeyed(self, removed, added, fresh_by_id):
        import merge_new_resources as mn
        pool = defaultdict(list)
        for i in added:
            e = fresh_by_id[i]
            pool[(gkey(e), mn.norm_name(e.get("name")))].append(e)
        n = 0
        for i in removed:
            e = self.old_by_id[i]
            for f in pool.get((gkey(e), mn.norm_name(e.get("name"))), []):
                if e.get("coordinates") and f.get("coordinates") and haversine_m(e["coordinates"], f["coordinates"]) < 100:
                    n += 1
                    break
        return n

    # 6 ─ split in scratch + shard guards
    def split(self):
        a, src = self.args, self.src
        sdir = os.path.join(SCRATCH, "split")
        shutil.rmtree(sdir, ignore_errors=True)
        write_json(os.path.join(sdir, "community_resources.json"), self.result)
        r = run([sys.executable, os.path.join(TOOLS, "split_by_region.py")], cwd=sdir, capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-4000:], r.stderr[-4000:])
            raise Fail(1, "split_by_region.py failed")
        self.sdata = os.path.join(sdir, "data")
        new_man, new_info, _ = scan_shards(self.sdata, self.is_source)
        if new_man["total"] != len(self.result):
            raise Fail(1, f"split wrote {new_man['total']} rows, expected {len(self.result)}")
        problems = []
        max_bytes = (a.max_shard_mb if a.max_shard_mb is not None else src["max_shard_mb"]) * 1024 * 1024
        for f in new_info:
            size = os.path.getsize(os.path.join(self.sdata, f))
            if size > max_bytes:
                problems.append(f"shard {f} is {size / 1048576:.1f} MB (> {max_bytes / 1048576:.0f} MB)")
        before, after = self.old_man["total"], new_man["total"]
        max_total = a.max_total_drop_pct if a.max_total_drop_pct is not None else src["max_total_drop_pct"]
        if (before - after) * 100 / before > max_total:
            problems.append(f"dataset total would drop {before:,} -> {after:,} (> {max_total}%)")
        old_files, new_files = set(self.old_info), set(new_info)
        changed = {f for f in old_files & new_files
                   if not filecmp.cmp(os.path.join(DATA, f), os.path.join(self.sdata, f), shallow=False)}
        added, removed = new_files - old_files, old_files - new_files
        allowed = {f for f, (_, s) in self.old_info.items() if s} | {f for f, (_, s) in new_info.items() if s}
        stray = (changed | added | removed) - allowed
        if stray:
            problems.append(f"shards without any of this source's rows would change: {sorted(stray)}")
        for f in CATCH_ALL:
            o, n = self.old_info.get(f, (0, 0))[1], new_info.get(f, (0, 0))[1]
            if n > o:
                problems.append(f"{n - o} of this source's rows would land in the catch-all shard {f} (misrouted?)")
        man_changed = not filecmp.cmp(os.path.join(DATA, "manifest.json"), os.path.join(self.sdata, "manifest.json"), shallow=False)
        if problems:
            raise Fail(2, "shard guards: " + " | ".join(problems))
        files_differ = bool(changed or added or removed or man_changed)
        if files_differ != (self.counts != (0, 0, 0)):
            raise Fail(1, f"internal inconsistency: diff counts {self.counts} but shard files differ={files_differ}")
        self.shard_changes = (changed, added, removed, man_changed)
        self.o["shards_changed"] = sorted(changed | added | removed)
        log(f"split: {len(changed)} shard(s) changed, {len(added)} added, {len(removed)} removed; total {before:,} -> {after:,}")

    # 7+8 ─ count copy, then an atomic copy into data/
    def apply(self):
        changed, added, removed, man_changed = self.shard_changes
        edits, bump = plan_count_copy(len(self.result), self.warnings)
        self.o["count_copy"] = bump
        if self.args.dry_run:
            log("dry run: data/ left untouched")
            return
        backup = os.path.join(SCRATCH, "backup")
        shutil.rmtree(backup, ignore_errors=True)
        for f in sorted(changed | removed) + ["manifest.json"]:
            os.makedirs(os.path.dirname(os.path.join(backup, f)), exist_ok=True)
            shutil.copy2(os.path.join(DATA, f), os.path.join(backup, f))
        for path in edits:
            shutil.copy2(path, os.path.join(backup, "_copy_" + os.path.basename(path)))
        try:
            for f in sorted(changed | added):
                os.makedirs(os.path.dirname(os.path.join(DATA, f)), exist_ok=True)
                shutil.copyfile(os.path.join(self.sdata, f), os.path.join(DATA, f))
            for f in sorted(removed):
                os.remove(os.path.join(DATA, f))
            shutil.copyfile(os.path.join(self.sdata, "manifest.json"), os.path.join(DATA, "manifest.json"))
            for f in sorted(changed | added) + ["manifest.json"]:
                if not filecmp.cmp(os.path.join(DATA, f), os.path.join(self.sdata, f), shallow=False):
                    raise OSError(f"data/{f} does not match the checked split output")
            if any(os.path.exists(os.path.join(DATA, f)) for f in removed):
                raise OSError("a removed shard is still in data/")
            for path, text in edits.items():
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    f.write(text)
                os.replace(path + ".tmp", path)
        except BaseException as e:  # noqa: BLE001 -- restore on any error or interruption, then report
            for f in added:
                if os.path.exists(os.path.join(DATA, f)):
                    os.remove(os.path.join(DATA, f))
            for f in sorted(changed | removed) + ["manifest.json"]:
                shutil.copyfile(os.path.join(backup, f), os.path.join(DATA, f))
            for path in edits:
                shutil.copyfile(os.path.join(backup, "_copy_" + os.path.basename(path)), path)
            if not isinstance(e, Exception):
                raise
            raise Fail(1, f"copying into data/ failed ({e}); data/ restored from the backup") from None
        if bump:
            log(f"static count copy: {bump['from']}+ -> {bump['to']}+ (README.md, index.html)")
        shutil.rmtree(backup, ignore_errors=True)

    def commit_message(self):
        o = self.o
        lines = [f"Refresh {o['label']}: +{o['added']} added, -{o['removed']} removed, ~{o['changed']} changed", "",
                 f"Source: {o['source']}" + (f" ({'; '.join(o['input'])})" if o.get("input") else ""),
                 f"Fetched {o.get('fetched', 0):,} rows; dataset {o['total_before']:,} -> {o['total_after']:,} entries."]
        for g in o.get("groups", []):
            lines.append(f"  {g['group']}: {g['before']} -> {g['after']} (+{g['added']} -{g['removed']} ~{g['changed']})")
        lines.append(f"Removed: {o['removed_upstream']} gone upstream, {len(o['dropped_by_merge'])} skipped by the merge "
                     f"dedupe, {o['rekeyed']} re-keyed.")
        if o["changed_by_field"]:
            lines.append("Changed fields: " + ", ".join(f"{k} {v}" for k, v in sorted(o["changed_by_field"].items())))
        if o.get("count_copy"):
            lines.append(f"Static count copy: {o['count_copy']['from']}+ -> {o['count_copy']['to']}+")
        if self.warnings:
            lines.append("Warnings: " + "; ".join(self.warnings))
        if o.get("run_url"):
            lines.append(f"Run: {o['run_url']}")
        return "\n".join(lines) + "\n"

    def execute(self):
        a = self.args
        state = load_state().get("sources", {}).get(self.src["name"], {})
        try:
            self.join()
            if not a.skip_fetch:
                agg = self.fetch()
            else:
                agg = None
                self.o["input"] = ["outputs reused (--skip-fetch)"]
                first = os.path.join(SCRATCH, "outcome_first.json")   # written by refresh_commit.sh before a re-apply
                if os.path.exists(first) and read_json(first).get("source") == self.src["name"]:
                    self.o["input"] = read_json(first).get("input", []) + ["re-applied after a push race"]
            self.load_outputs()
            prev = state.get("last_input")
            if agg and prev and agg["input"] and agg["input"] != prev:
                self.warnings.append(f"input changed since the last successful refresh: {'; '.join(prev)} -> "
                                     f"{'; '.join(agg['input'])} (an older year or file would mean a fallback)")
            if agg:
                if agg["budget_skipped"]:
                    tries = state.get("warm_attempts", 0) + 1
                    if tries >= self.src["max_warm_attempts"]:
                        self.drop_outputs()
                        raise Fail(1, f"still geocoding after {tries} runs ({agg['budget_skipped']} lookups left over "
                                      f"the per-run budgets: {self.src['nominatim_max_new']} Nominatim, "
                                      f"{self.src['official_geocoder_max_new']} Kartverket/Maa-amet)")
                    self.drop_outputs()
                    self.o.update(status="warming", message=f"{agg['nominatim_new']} new Nominatim and "
                                  f"{agg['official_new']} Kartverket/Maa-amet lookups, "
                                  f"{agg['budget_skipped']} left for the next run (attempt {tries}); nothing merged")
                    return 0
                n_tr = sum(agg["transient"].values())
                tol = max(self.src["transient_min"], math.ceil(len(self.fetched) * self.src["transient_pct"] / 100))
                if n_tr > tol:
                    self.drop_outputs()
                    raise Fail(1, f"{n_tr} transient fetch failures (> {tol} tolerated) {dict(agg['transient'])}: the "
                                  "output may be partial, so nothing was merged; it is retried after a cooldown",
                               status="transient")
                if n_tr:
                    self.warnings.append(f"{n_tr} transient failure(s) tolerated: {dict(agg['transient'])}")
            self.premerge_guards()
            self.merge()
            self.reconcile()
            self.split()
            unchanged = self.counts == (0, 0, 0)
            if not unchanged:
                self.apply()
            self.o["status"] = "unchanged" if unchanged else "changed"
            return 0
        except Fail as f:
            self.o.update(status=f.status, message=str(f))
            return f.code
        except Exception as e:  # noqa: BLE001
            self.o.update(status="failed", message=f"{type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            if self.joined:   # leave community_resources.json equal to join(data/)
                subprocess.run([sys.executable, os.path.join(TOOLS, "join_regions.py"), "--force"], cwd=REPO,
                               stdout=subprocess.DEVNULL)
            shutil.rmtree(os.path.join(SCRATCH, "split"), ignore_errors=True)

    def report(self, code):
        o = self.o
        o["exit_code"] = code
        o["duration_s"] = round(time.monotonic() - self.t0)
        write_json(OUTCOME, o, indent=1)
        write_json(SUMMARY_LOG, o, indent=1)
        if o["status"] == "changed":
            with open(COMMIT_MSG, "w", encoding="utf-8") as f:
                f.write(self.commit_message())
        st = o["status"]
        tag = " (dry run)" if o["dry_run"] else ""
        if st in ("changed", "unchanged"):
            detail = (f"+{o['added']} −{o['removed']} ~{o['changed']} · total {o['total_before']:,} → {o['total_after']:,}"
                      + (f" · count copy {o['count_copy']['from']}+ → {o['count_copy']['to']}+" if o.get("count_copy") else ""))
        else:
            detail = o["message"]
        if o.get("input"):
            detail += " · input: " + "; ".join(o["input"])
        line = f"**Registry refresh** · `{o['source']}`{tag} · **{st}** · {detail} · {fmt_dur(o['duration_s'])}"
        if self.warnings:
            line += " · ⚠ " + "; ".join(self.warnings)
        step_summary(line)
        if os.environ.get("GITHUB_ACTIONS"):   # an annotation on the run page (also readable through the API)
            kind = "notice" if code == 0 else "error"
            print(f"::{kind} title=Registry refresh {o['source']}{tag}::" + line.replace("**", "").replace("\n", " "), flush=True)
        gh_output(status=st, dry_run=str(o["dry_run"]).lower(), count_bump=str(bool(o.get("count_copy"))).lower())
        log(f"{st}: {detail}")
        if self.warnings:
            log("warnings: " + "; ".join(self.warnings))


# ── commands ──────────────────────────────────────────────────────────────────────────────────────

def cmd_check():
    import split_by_region as sbr
    reg, sources = load_registry()
    problems, warnings = [], []
    names, owner = set(), {}
    need = {"name", "label", "country", "every_days", "commands", "outputs", "groups", "raw", "caches"}
    for s in sources:
        n = s.get("name")
        miss = need - set(s)
        if miss:
            problems.append(f"{n}: missing {sorted(miss)}")
            continue
        if n in names:
            problems.append(f"duplicate source name {n}")
        names.add(n)
        if not isinstance(s["every_days"], int) or s["every_days"] < 1:
            problems.append(f"{n}: every_days must be a positive integer")
        if s["country"] not in rc.BBOX:
            problems.append(f"{n}: no bounding box for country {s['country']} in registry_common.BBOX")
        for cmd in s["commands"]:
            if not cmd or not os.path.exists(os.path.join(REPO, cmd[0])):
                problems.append(f"{n}: command {cmd} does not name an existing script")
        for o in s["outputs"]:
            if not fnmatch.fnmatch(o, "new_resources_*.json") or "/" in o:
                problems.append(f"{n}: output {o} must be a new_resources_*.json file in the repo root")
        for g in s["groups"]:
            if not {"prefix", "source", "breadth", "min_rows"} <= set(g):
                problems.append(f"{n}: group {g} needs prefix, source, breadth, min_rows")
                continue
            if sbr.forced_shard(g["source"]) is None:
                problems.append(f"{n}: source {g['source']!r} has no NEW_SOURCE_SHARDS rule in split_by_region.py")
        for p in s["prefixes"]:
            if p in owner and owner[p] != n:
                problems.append(f"prefix {p} is registered by both {owner[p]} and {n}")
            owner[p] = n
        protected = s["caches"] + ["tools/refresh_scratch/state.json"] + s["outputs"]
        for pat in s["raw"]:
            if not fnmatch.fnmatch(pat, "tools/*_scratch/*"):
                problems.append(f"{n}: raw glob {pat} must stay inside a tools/<x>_scratch/ dir")
            if "cache" in pat or any(fnmatch.fnmatch(p, pat) for p in protected):
                problems.append(f"{n}: raw glob {pat} would delete a cache, the rotation state or an output")
        for c in s["caches"]:
            if not fnmatch.fnmatch(c, CACHE_GLOB):
                problems.append(f"{n}: cache {c} is not covered by the persisted glob {CACHE_GLOB}")
    # every row carrying a registered prefix must belong to one of that source's groups
    by_src = {s["name"]: s for s in sources if "groups" in s}
    known = {(g["prefix"], g["source"], g["breadth"]): s["name"] for s in by_src.values() for g in s["groups"]}
    counts, stray = Counter(), Counter()
    man = read_json(os.path.join(DATA, "manifest.json"))
    for it in man["files"]:
        for e in read_json(os.path.join(DATA, it["file"])):
            p = prefix_of(e)
            if p in owner:
                k = gkey(e)
                if k in known:
                    counts[k] += 1
                else:
                    stray[k] += 1
    for k, c in stray.items():
        problems.append(f"{c} row(s) carry prefix {k[0]} (registered by {owner[k[0]]}) but source/breadth "
                        f"{k[1]!r}/{k[2]} is not one of its groups -- a refresh would delete them")
    for k, n in known.items():
        if not counts[k]:
            warnings.append(f"{n}: group {k[0]}/{k[2]} has no rows in data/ yet")
    for w in warnings:
        log("warning: " + w)
    if problems:
        for p in problems:
            log("PROBLEM: " + p)
        raise Fail(1, f"{len(problems)} problem(s) in {os.path.relpath(REGISTRY, REPO)}")
    log(f"registry OK: {len(sources)} sources, {len(known)} groups, {sum(counts.values()):,} rows in data/")
    return 0


def cmd_list():
    _, sources = load_registry()
    st = load_state()
    day = today()
    print(f"{'name':<11} {'every':>5}  {'last ok':<10}  groups")
    for s in sources:
        last = st["sources"].get(s["name"], {}).get("last_success", "-")
        print(f"{s['name']:<11} {s['every_days']:>4}d  {last:<10}  " + ", ".join(g["label"] for g in s["groups"]))
    print("\nNext 28 days, if every run succeeds:")
    sim = json.loads(json.dumps(st))
    for d in range(28):
        dd = day + dt.timedelta(days=d)
        n = choose(sources, sim, dd)
        if n != "none":
            sim["sources"].setdefault(n, {}).update(last_success=dd.isoformat())
            sim["sources"][n].pop("cooldown_until", None)
        print(f"  {dd.isoformat()}  {n}")
    return 0


def cmd_pick(arg):
    for p in (OUTCOME, COMMIT_MSG):
        if os.path.exists(p):
            os.remove(p)
    _, sources = load_registry()
    arg = (arg or "").strip()
    if arg and arg != "scheduled":
        name = get_source(arg)["name"]
    else:
        name = choose(sources, load_state(), today())
    print(name)
    gh_output(source=name)
    if name == "none":
        write_json(OUTCOME, {"source": "none", "status": "none", "date": today().isoformat()}, indent=1)
        step_summary(f"**Registry refresh** · nothing due on {today().isoformat()}")
    return 0


def cmd_record(push_result, dry_run, picked=None):
    """Update the rotation state after a run. A picked source with no outcome (the refresh step was killed,
    e.g. by its time limit) counts as a failure, so a source that always times out cannot block the rotation."""
    if dry_run:
        log("dry run: rotation state unchanged")
        return 0
    o = read_json(OUTCOME) if os.path.exists(OUTCOME) else {}
    if picked and picked != "none" and o.get("source") != picked:
        o = {"source": picked, "status": "failed", "message": "the refresh step did not finish"}
    if not o or o.get("status") == "none":
        log("nothing to record")
        return 0
    if o.get("dry_run"):
        log("dry run: rotation state unchanged")
        return 0
    src = get_source(o["source"])
    st = load_state()
    s = st["sources"].setdefault(src["name"], {})
    day = today()
    status = o["status"]
    if status == "changed" and push_result != "success":
        status = "failed"
        o["message"] = f"commit/push step {push_result}"
    s.update(last_attempt=day.isoformat(), last_status=status)
    if status in ("changed", "unchanged"):
        s.update(last_success=day.isoformat(), fails=0, warm_attempts=0)
        if o.get("input") and "outputs reused (--skip-fetch)" not in o["input"]:
            s["last_input"] = o["input"]
        s.pop("cooldown_until", None)
    elif status == "warming":
        s["warm_attempts"] = s.get("warm_attempts", 0) + 1
    else:
        s["fails"] = s.get("fails", 0) + 1
        s["warm_attempts"] = 0
        wait = min(2 ** (s["fails"] - 1), src["every_days"])
        s["cooldown_until"] = (day + dt.timedelta(days=wait)).isoformat()
    save_state(st)
    log(f"recorded {src['name']}: {status} ({json.dumps(s, sort_keys=True)})")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--list", action="store_true")
    g.add_argument("--pick", nargs="?", const="scheduled", metavar="NAME")
    g.add_argument("--source", metavar="NAME")
    g.add_argument("--record", action="store_true")
    ap.add_argument("--skip-fetch", action="store_true", help="reuse the new_resources_*.json files already on disk")
    ap.add_argument("--dry-run", action="store_true", help="run every step and guard but leave data/ untouched")
    ap.add_argument("--allow-drop", action="store_true", help="relax the row-count floors (min_rows, max drop, survivors)")
    ap.add_argument("--allow-change", action="store_true",
                    help="relax the growth, fill-rate, mojibake, changed-rows and replaced-ids guards")
    ap.add_argument("--force", action="store_true", help="overwrite a community_resources.json that differs from data/")
    ap.add_argument("--max-shard-mb", type=float)
    ap.add_argument("--max-total-drop-pct", type=float)
    ap.add_argument("--push-result", default="skipped", help="--record: outcome of the commit/push step")
    ap.add_argument("--picked", help="--record: the source the pick step chose")
    a = ap.parse_args()
    try:
        if a.check:
            return cmd_check()
        if a.list:
            return cmd_list()
        if a.pick is not None:
            return cmd_pick(a.pick)
        if a.record:
            return cmd_record(a.push_result, a.dry_run, a.picked)
        r = Refresh(get_source(a.source.strip()), a)
        code = r.execute()
        r.report(code)
        return code
    except Fail as f:
        log(f"FAILED: {f}")
        step_summary(f"**Registry refresh** · **failed** · {f}")
        return f.code


if __name__ == "__main__":
    sys.exit(main())
