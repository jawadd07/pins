#!/usr/bin/env python3
"""Manage products.csv. Never rewrites scripts. Makes products.csv.bak before any change.
  python add_products.py                 add from keywords.txt  (category | keyword [| amazon product url or ASIN])
  python add_products.py --ideas         add ideas from Gemini free key (GEMINI_API_KEY)
  python add_products.py --setlinks links.txt   set exact product links:  product name | amazon url or ASIN"""
import argparse, csv, json, os, re, shutil, webbrowser
from urllib.parse import quote_plus
import requests, yaml

CSV = "products.csv"
COLS = ["name", "affiliate_url", "network", "category", "board", "keywords", "description", "image_url"]


def clean(s):
    return re.sub(r"\s+", " ", str(s).replace(",", " ").replace(";", " ").replace('"', "")).strip()


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
            "description": f"Popular {kw.lower()} pick worth a look", "image_url": ""}


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


def short_name(title):
    t = re.split(r"[,|(:\u2013\u2014]| - ", title)[0]
    words = clean(t).split()
    return " ".join(words[:7]).title() or clean(title)[:50].title()


def big_image(url):
    return re.sub(r"\._[^/]*_\.(jpg|png)$", r"._AC_SL1000_.\1", url) if "media-amazon" in url else url


def import_picks(path, rows, tag, cfg, limit):
    """picks.txt lines from the bookmarklet:  category | title | amazon url | image url   (skips ASINs already in products.csv)"""
    txt = open(path, encoding="utf-8").read().replace(" ## ", "\n")
    have_names = {r["name"].lower() for r in rows}
    have_asin = set(re.findall(r"/dp/([A-Z0-9]{10})", " ".join(r["affiliate_url"] for r in rows)))
    use_img = bool(cfg.get("use_amazon_images", False))
    new = []
    for ln in txt.splitlines():
        parts = [x.strip() for x in ln.split("|")]
        if len(parts) < 3 or parts[0].startswith("#"):
            continue
        cat, title, link = parts[0], parts[1], parts[2]
        img = parts[3] if len(parts) > 3 else ""
        if cat not in cfg.get("boards", {}):
            print("skip (category not in config boards):", cat)
            continue
        url = product_link(link, tag)
        m = re.search(r"/dp/([A-Z0-9]{10})", url or "")
        if not url or not m or m.group(1) in have_asin:
            continue
        name = short_name(title)
        if name.lower() in have_names:
            name = f"{name} {m.group(1)[-4:]}"
        r = make_row(cat, name, tag, url)
        r["name"] = name
        short_kw = " ".join(name.lower().split()[-2:])  # e.g. "papasan chair": broader photo search
        r["keywords"] = ";".join(dict.fromkeys([short_kw, name.lower(), cat.replace("-", " ")]))
        r["description"] = f"{name} is a popular pick with great reviews"[:120]
        r["image_url"] = big_image(img) if (use_img and img) else ""
        have_asin.add(m.group(1))
        have_names.add(name.lower())
        new.append(r)
        if len(new) >= limit:
            break
    return new


DS = r"(?:digistore24|checkout-ds24)\.com"


def ds24_parse(txt, aff_known):
    """digistore24 promo link / product url / bare product id -> (official promolink, affiliate id)"""
    txt = txt.strip()
    m = re.search(DS + r"/redir/(\d+)/([A-Za-z0-9_-]+)", txt)
    if m:
        return f"https://www.checkout-ds24.com/redir/{m.group(1)}/{m.group(2)}/pin", m.group(2)
    m = re.search(DS + r"/(?:product|redir)/(\d+)", txt) or re.fullmatch(r"(\d{4,8})", txt)
    if m and aff_known:
        return f"https://www.checkout-ds24.com/redir/{m.group(1)}/{aff_known}/pin", aff_known
    return None, aff_known


def import_digital(path, rows, cfg, limit):
    """digital.txt (ALL non-Amazon stores):  category | product name | affiliate link (or digistore24 product id) | network (optional)
    Takes up to `limit` products per run, the rest stay queued in the file."""
    aff = open("ds24_id.txt").read().strip() if os.path.exists("ds24_id.txt") else ""
    aff = aff or cfg.get("digistore_id", "")
    have = {r["name"].lower() for r in rows}
    new, remaining, done = [], [], []
    for raw in open(path, encoding="utf-8").read().splitlines():
        ln = raw.strip()
        parts = [x.strip() for x in ln.split("|")]
        if not ln or ln.startswith("#") or len(parts) < 3:
            remaining.append(raw)
            continue
        if len(new) >= limit:
            remaining.append(raw)
            continue
        cat, name, link = parts[0], clean(parts[1]), parts[2]
        net = parts[3].strip().lower() if len(parts) > 3 and parts[3].strip() else "digistore24"
        if cat not in cfg.get("boards", {}):
            print("kept (category not in config boards):", cat, "|", name)
            remaining.append(raw)
            continue
        if link.startswith("http") and not re.search(DS, link):  # any other store: keep affiliate link as is
            url = link
            if net == "digistore24":
                net = re.sub(r"^www\.", "", re.sub(r"https?://([^/]+)/.*", r"\1", link + "/"))
        else:
            url, aff = ds24_parse(link, aff)
        if not url:
            print("kept (need a full promo link first to learn your ID):", name)
            remaining.append(raw)
            continue
        done.append(raw)
        if name.lower() in have:
            continue
        have.add(name.lower())
        new.append({"name": name.title() if name.islower() else name, "affiliate_url": url, "network": net,
                    "category": cat, "board": "",
                    "keywords": ";".join(dict.fromkeys([name.lower(), cat.replace("-", " ")])),
                    "description": f"{name} - a popular pick", "image_url": ""})
    if aff:
        open("ds24_id.txt", "w").write(aff)
    return new, remaining, done


def sync_links_file(path, rows):
    """make sure every product has a line in links.txt"""
    have = set()
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            if ln.strip() and not ln.startswith("#") and "|" in ln:
                have.add(ln.split("|")[0].strip().lower())
    missing = [r["name"] for r in rows if r["name"].lower() not in have]
    if missing:
        with open(path, "a", encoding="utf-8") as f:
            for n in missing:
                f.write(f"{n} | PASTE LINK HERE\n")
    return len(missing)


def open_searches(path, limit):
    """open Amazon search tabs (sorted by reviews, no tag) for products still waiting for a link"""
    todo = []
    for ln in open(path, encoding="utf-8"):
        if ln.strip() and not ln.startswith("#") and "|" in ln:
            parts = [x.strip() for x in ln.split("|")]
            if len(parts) < 2 or "PASTE" in parts[1].upper() or not parts[1]:
                todo.append(parts[0])
    for n in todo[:limit]:
        webbrowser.open(f"https://www.amazon.com/s?k={quote_plus(n)}&s=review-rank")
    print(f"opened {min(len(todo), limit)} tabs, {max(0, len(todo) - limit)} products still waiting")
    return todo


def set_links(path, rows, tag):
    """line:  product name | amazon url or ASIN | optional exact photo url"""
    byname = {r["name"].lower(): r for r in rows}
    n = 0
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if not ln or ln.startswith("#") or "|" not in ln:
            continue
        parts = [x.strip() for x in ln.split("|")]
        name, link = parts[0], parts[1]
        photo = parts[2] if len(parts) > 2 else ""
        r = byname.get(name.lower())
        if not r:
            print("name not in products.csv:", name)
            continue
        if link and "PASTE" not in link.upper():
            url = product_link(link, tag)
            if not url:
                print("bad link, skipped:", name)
            elif r["affiliate_url"] != url:
                r["affiliate_url"] = url
                n += 1
                print("link set:", name)
        if photo.startswith("http") and r.get("image_url") != photo:
            r["image_url"] = photo
            n += 1
            print("photo set:", name)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ideas", action="store_true")
    ap.add_argument("--file", default="keywords.txt")
    ap.add_argument("--setlinks", metavar="FILE")
    ap.add_argument("--import", dest="imp", metavar="FILE", help="import picks.txt made by the bookmarklet")
    ap.add_argument("--digital", metavar="FILE", help="import digistore24 products from digital.txt")
    ap.add_argument("--openlinks", action="store_true", help="open Amazon search tabs for products without exact link")
    ap.add_argument("--max", type=int, default=5)
    ap.add_argument("--config", default="config.yaml")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    rows = read_rows()
    tag = find_tag(rows, cfg)
    if not tag:
        raise SystemExit("no Amazon tag found. add amazon_tag: yourtag-20 to config.yaml")
    if a.digital:
        if not os.path.exists(a.digital) or not open(a.digital, encoding="utf-8").read().strip():
            print("digital.txt empty, nothing to import")
            raise SystemExit
        new, remaining, done = import_digital(a.digital, rows, cfg, a.max)
        if new:
            shutil.copy(CSV, CSV + ".bak")
            with open(CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                for r in new:
                    w.writerow(r)
            with open("digital_done.txt", "a", encoding="utf-8") as f:
                f.write("\n".join(done) + "\n")
            open(a.digital, "w", encoding="utf-8").write("\n".join(remaining) + ("\n" if remaining else ""))
            print("digital imported", len(new), ":", ", ".join(r["name"] for r in new), "| still queued:",
                  sum(1 for x in remaining if x.strip() and not x.startswith("#")))
        else:
            print("no new digital products")
        raise SystemExit
    if a.imp:
        if not os.path.exists(a.imp) or not open(a.imp, encoding="utf-8").read().strip():
            print("picks.txt empty, nothing to import")
            raise SystemExit
        new = import_picks(a.imp, rows, tag, cfg, a.max)
        if new:
            shutil.copy(CSV, CSV + ".bak")
            with open(CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                for r in new:
                    w.writerow(r)
            with open("picks_done.txt", "a", encoding="utf-8") as f:
                f.write(open(a.imp, encoding="utf-8").read() + "\n")
            open(a.imp, "w", encoding="utf-8").close()
            print("imported", len(new), "products:", ", ".join(r["name"] for r in new))
        else:
            print("no new products in picks.txt")
        raise SystemExit
    if a.openlinks:
        sync_links_file("links.txt", rows)
        open_searches("links.txt", 5)
        raise SystemExit
    if a.setlinks:
        if set_links(a.setlinks, rows, tag):
            write_rows(rows)
        else:
            print("no link changes")
        raise SystemExit
    cats = list(cfg.get("boards", {}).keys())
    cand = from_gemini(cfg, cats, 3) if a.ideas else from_file(a.file)
    if os.path.exists("keywords_bank.txt"):  # built-in list: runs automatically when keywords.txt is used up
        cand += from_file("keywords_bank.txt")
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
        sync_links_file("links.txt", read_rows())
