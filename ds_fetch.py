#!/usr/bin/env python3
"""Digistore24 auto-finder: asks the Digistore24 API for marketplace offers, keeps the popular/safe ones that fit your boards,
adds the NEXT few (never the same twice) to products.csv with your affiliate link.   Needs DS24_API_KEY (read-only) in keys.bat.
  python ds_fetch.py            add up to ds_per_run new products
  python ds_fetch.py --probe    print what the API returns (to debug) and save ds_debug.json (contains no key)"""
import argparse, csv, json, os, re, sys
import requests, yaml
import add_products as AP

API = "https://www.digistore24.com/api/call/listMarketplaceEntries"
BLOCK = re.compile(r"weight.?loss|lose weight|fat burn|diabet|blood.?sugar|keto|supplement|cure|tinnitus|prostate|cbd|detox|libido|"
                   r"erect|forex|crypto|bitcoin|trading|casino|betting|adult|dating|make money|passive income|get rich|income|"
                   r"manifest|miracle|wealth|millionaire|hack|loan|gambl|medical|pain relief|anti.?aging|hair loss|cancer|"
                   r"depress|anxiety|\bmlm\b", re.I)
DEFAULT_MAP = {   # board key (must exist in config boards) -> words in headline/category
    "languages": ["language", "english", "spanish", "french", "german", "italian", "arabic", "vocabulary", "pronunciation", "grammar", "fluent"],
    "crochet": ["crochet", "knit", "amigurumi", "macrame", "embroider", "sewing", "quilt"],
    "planners": ["planner", "printable", "journal", "template", "habit", "productivity", "bullet journal", "worksheet"],
    "weddings": ["wedding", "bride", "bridal"],
    "fitness": ["yoga", "pilates", "workout", "stretch", "mobility", "home gym", "calisthenic"],
    "pets": ["dog", "puppy", "cat ", "kitten", "pet "],
    "organization": ["declutter", "organiz", "cleaning", "minimalis"],
    "kitchen": ["recipe", "cookbook", "baking", "meal prep"],
}


def find_entries(o):
    """the API wraps the list in changing keys -> find the list of dicts that carry main_product_id"""
    best = []
    def walk(x):
        nonlocal best
        if isinstance(x, list):
            if x and all(isinstance(i, dict) for i in x) and any("main_product_id" in i or "id" in i for i in x):
                if len(x) > len(best):
                    best = x
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    walk(o)
    return best


def fnum(v, d=0.0):
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return d


def pick_board(e, cmap, boards):
    text = (str(e.get("headline", "")) + " " + str(e.get("product_category", ""))).lower() + " "
    for b, words in cmap.items():
        if b in boards and any(w in text for w in words):
            return b
    return None


def choose(entries, cfg, seen, have_names):
    ds = cfg.get("ds_auto", {}) or {}
    cmap = ds.get("board_words") or DEFAULT_MAP
    boards = cfg.get("boards", {})
    min_stars = float(ds.get("min_stars", 2))
    max_cancel = float(ds.get("max_cancel_rate", 25))
    need_stats = bool(ds.get("need_valid_stats", True))
    out = []
    for e in entries:
        pid = str(e.get("main_product_id") or e.get("product_id") or "")
        name = AP.clean(re.sub(r"<[^>]+>", "", str(e.get("headline", ""))))
        if not pid.isdigit() or not name or pid in seen or name.lower() in have_names:
            continue
        if str(e.get("language", "en")).lower() != "en":
            continue
        if str(e.get("approval_status", "approved")).lower() in ("rejected", "pending", "new"):
            continue
        if BLOCK.search(name + " " + str(e.get("product_category", ""))) or BLOCK.search(re.sub(r"<[^>]+>", " ", str(e.get("description", "")))[:600]):
            continue
        if need_stats and str(e.get("stats_is_valid", "Y")).upper() != "Y":
            continue
        if fnum(e.get("stats_stars")) < min_stars or fnum(e.get("stats_cancel_rate")) > max_cancel:
            continue
        b = pick_board(e, cmap, boards)
        if not b:
            continue
        score = fnum(e.get("stats_stars")) * 10 + fnum(e.get("stats_affiliate_profit_visitor")) * 5 + min(fnum(e.get("stats_count_orders")), 500) / 100
        out.append((score, pid, name, b, e))
    out.sort(key=lambda t: -t[0])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    ds = cfg.get("ds_auto", {}) or {}
    if os.environ.get("DS24_FAKE"):                       # offline test
        data = json.load(open(os.environ["DS24_FAKE"], encoding="utf-8"))
    else:
        key = os.environ.get("DS24_API_KEY", "").strip()
        if not key:
            print("DS24_API_KEY nahi mila (keys.bat mein 'set DS24_API_KEY=...'). Digistore auto-find skip, digital.txt wala manual raasta chalta rahega.")
            return 0
        try:
            r = requests.get(API, headers={"X-DS-API-KEY": key, "Accept": "application/json"}, timeout=60)
            data = r.json()
        except Exception as ex:
            print("Digistore API call fail:", str(ex)[:200])
            return 0
    if isinstance(data, dict) and data.get("result") not in (None, "success"):
        print("Digistore API ne mana kiya:", str(data.get("message") or data)[:300])
        return 0
    entries = find_entries(data)
    if a.probe or not entries:
        json.dump(data, open("ds_debug.json", "w", encoding="utf-8"), indent=1)
        print(f"{len(entries)} entries mile. Pehli entry ke keys:", sorted(entries[0].keys()) if entries else "-")
        print("Poora jawab ds_debug.json mein (isme API key nahi hai).")
        if not entries:
            return 0
        if a.probe:
            return 0
    aff = open("ds24_id.txt").read().strip() if os.path.exists("ds24_id.txt") else cfg.get("digistore_id", "")
    if not aff:
        print("ds24_id.txt khali: apna Digistore24 ID daalo.")
        return 0
    seen = set(open("ds_seen.txt").read().split()) if os.path.exists("ds_seen.txt") else set()
    rows = AP.read_rows()
    have = {r["name"].lower() for r in rows}
    picks = choose(entries, cfg, seen, have)
    limit = a.max or int(ds.get("per_run", 5))
    new = []
    for score, pid, name, b, e in picks[:limit]:
        new.append({"name": name, "affiliate_url": f"https://www.checkout-ds24.com/redir/{pid}/{aff}/pin", "network": "digistore24",
                    "category": b, "board": "", "keywords": ";".join(dict.fromkeys([name.lower(), b.replace("-", " ")])),
                    "description": f"{name} - a popular pick"[:120], "image_url": ""})
        seen.add(pid)
    print(f"{len(entries)} offers dekhe, filter ke baad {len(picks)} theek, {len(new)} naye add:")
    for n in new:
        print("  +", n["category"], "|", n["name"])
    if new:
        AP.write_rows(rows + new)
        open("ds_seen.txt", "w").write("\n".join(sorted(seen)))
    elif not picks:
        print("Koi naya theek offer nahi mila (filter strict hai: config.yaml mein ds_auto dekho).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
