import json, os, time
import requests

SP = "C:/Users/Lenovo/AppData/Local/Temp/claude/C--Users-Lenovo/01dd4fda-bed2-4ee1-8d82-7a492c36c3ab/scratchpad"
SEARCH_OUT = f"{SP}/propublica_search_results.jsonl"
DETAIL_OUT = f"{SP}/propublica_details.jsonl"

def already_done(path, key="ein"):
    done = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                done.add(d[key])
            except (json.JSONDecodeError, KeyError):
                continue
    return done

def fetch_search_pages():
    seen_eins = already_done(SEARCH_OUT)
    out = open(SEARCH_OUT, "a", encoding="utf-8")
    page = 0
    while True:
        resp = requests.get(
            "https://projects.propublica.org/nonprofits/api/v2/search.json",
            params={"q": "autism", "page": page}, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        orgs = data["organizations"]
        if not orgs:
            break
        new = 0
        for org in orgs:
            if org["ein"] not in seen_eins:
                out.write(json.dumps(org, ensure_ascii=False) + "\n")
                seen_eins.add(org["ein"])
                new += 1
        out.flush()
        os.fsync(out.fileno())
        print(f"  search page {page}/{data['num_pages']}: {new} new", flush=True)
        page += 1
        if page >= data["num_pages"]:
            break
        time.sleep(0.3)
    out.close()
    print(f"Total unique orgs found: {len(seen_eins)}", flush=True)
    return seen_eins

def fetch_details(eins):
    done = already_done(DETAIL_OUT, key="ein_looked_up")
    todo = [e for e in eins if e not in done]
    print(f"Detail fetch: {len(todo)} remaining of {len(eins)}", flush=True)
    out = open(DETAIL_OUT, "a", encoding="utf-8")
    for i, ein in enumerate(todo):
        try:
            resp = requests.get(
                f"https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json",
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                data["ein_looked_up"] = ein
                out.write(json.dumps(data, ensure_ascii=False) + "\n")
            else:
                out.write(json.dumps({"ein_looked_up": ein, "error": resp.status_code}, ensure_ascii=False) + "\n")
        except Exception as ex:
            out.write(json.dumps({"ein_looked_up": ein, "error": str(ex)}, ensure_ascii=False) + "\n")
        out.flush()
        os.fsync(out.fileno())
        if (i + 1) % 100 == 0:
            print(f"  detail: {i+1}/{len(todo)}", flush=True)
        time.sleep(0.15)
    out.close()

if __name__ == "__main__":
    eins = fetch_search_pages()
    fetch_details(eins)
    print("DONE.", flush=True)
