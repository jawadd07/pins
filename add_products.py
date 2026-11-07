#!/usr/bin/env python3
"""Manage products.csv. Never rewrites scripts. Makes products.csv.bak before any change.
  python add_products.py                 add from keywords.txt  (category | keyword [| amazon product url or ASIN])
  python add_products.py --ideas         add ideas from Gemini free key (GEMINI_API_KEY)
  python add_products.py --setlinks links.txt   set exact product links:  product name | amazon url or ASIN"""
import argparse, csv, json, os, re, shutil
from urllib.parse import quote_plus
import requests, yaml

CSV = "products.csv"
COLS = ["name", "affiliate_url", "network", "category", "board", "keywords", "description", "image_url"]


def clean(s):
    return re.sub(r"\s+", " ", str(s).replace(",", " ").replace(";", " ")).strip()


def read_rows():
    with open(CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    shutil.copy(CSV, CSV + ".bak")
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def find_tag(rows, cfg):
    for r in rows:
        m = re.search(r"tag=([A-Za-z0-9_-]+)", r.get("affiliate_url", ""))
        if m:
            return m.group(1)
    return cfg.get("amazon_tag", "")


def product_link(txt, tag):
    """amazon product url / ASIN -> clean tagged /dp/ link. amzn.to short links kept as is."""
    txt = txt.strip()
    if re.search(r"amzn\.to|a\.co/", txt):
        return txt
    m = re.search(r"(?:/dp/|/gp/product/|/product/)([A-Z0-9]{10})", txt) or re.fullmatch(r"([A-Z0-9]{10})", txt)
    return f"https://www.amazon.com/dp/{m.group(1)}?tag={tag}" if m else None


def make_row(cat, kw, tag, link=None):
    kw = clean(kw)
    url = (product_link(link, tag) if link else None) or f"https://www.amazon.com/s?k={quote_plus(kw)}&tag={tag}"
    return {"name": kw.title(), "affiliate_url": url, "network": "amazon", "category": cat, "board": "",
            "keywords": ";".join(dict.fromkeys([kw.lower(), cat.replace("-", " ")])),
            "description": f"Popular {kw.lower()} pick worth a look for your home", "image_url": ""}


def from_file(path):
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = [x.strip() for x in ln.split("|")]
        if len(parts) == 1:
            out.append(("home-decor", parts[0], None))
        else:
            out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else None))
    return out


def from_gemini(cfg, cats, n):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("set GEMINI_API_KEY first (free: aistudio.google.com)")
    model = cfg.get("text", {}).get("gemini_model", "gemini-2.0-flash")
    out = []
    for c in cats:
        prompt = (f"List {n} specific, popular products people buy on Amazon US in the Pinterest category "
                  f"'{c.replace('-', ' ')}' (home, decor, kitchen, wellness). Current trends welcome. "
                  'Return ONLY a JSON list of short product search phrases like ["rattan pendant light"].')
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          params={"key": key}, timeout=120,
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseMimeType": "application/json"}})
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        out += [(c, k, None) for k in json.loads(txt)[:n]]
    return out


def set_links(path, rows, tag):
    byname = {r["name"].lower(): r for r in rows}
    n = 0
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "|" not in ln:
            continue
        name, _, link = [x.strip() for x in ln.partition("|")]
        if not link or "PASTE" in link.upper():
            continue
        url = product_link(link, tag)
        if not url:
            print("bad link, skipped:", name)
            continue
        r = byname.get(name.lower())
        if not r:
            print("name not in products.csv:", name)
            continue
        if r["affiliate_url"] != url:
            r["affiliate_url"] = url
            n += 1
            print("link set:", name)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ideas", action="store_true")
    ap.add_argument("--file", default="keywords.txt")
    ap.add_argument("--setlinks", metavar="FILE")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--config", default="config.yaml")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    rows = read_rows()
    tag = find_tag(rows, cfg)
    if not tag:
        raise SystemExit("no Amazon tag found. add amazon_tag: yourtag-20 to config.yaml")
    if a.setlinks:
        if set_links(a.setlinks, rows, tag):
            write_rows(rows)
        else:
            print("no link changes")
        raise SystemExit
    cats = list(cfg.get("boards", {}).keys())
    cand = from_gemini(cfg, cats, 3) if a.ideas else from_file(a.file)
    have = {r["name"].lower() for r in rows}
    new = []
    for cat, kw, link in cand:
        if cat not in cfg.get("boards", {}):
            print("skip (category not in config boards):", cat, "|", kw)
            continue
        r = make_row(cat, kw, tag, link)
        if r["name"].lower() in have:
            continue
        have.add(r["name"].lower())
        new.append(r)
        if len(new) >= a.max:
            break
    if not new:
        print("no new products to add")
    else:
        shutil.copy(CSV, CSV + ".bak")
        with open(CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            for r in new:
                w.writerow(r)
        print("added", len(new), "products:", ", ".join(r["name"] for r in new))
