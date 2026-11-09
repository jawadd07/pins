"""Pinterest agent doctor: looks at THIS folder, fixes the safe problems by itself, and prints a report.
Put this file and doctor.bat into your pinterest-agent folder and double-click doctor.bat."""
import csv
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
OK, FIX, WARN, BAD = [], [], [], []


def ok(m): OK.append(m)
def fix(m): FIX.append(m)
def warn(m): WARN.append(m)
def bad(m): BAD.append(m)


def read(p):
    return Path(p).read_text(encoding="utf-8", errors="replace") if Path(p).exists() else ""


def run(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


# ---- files
for f in ("auto.bat", "run.bat", "add_products.py", "pinterest_agent.py", "config.yaml", "products.csv", "keywords_bank.txt", "requirements.txt"):
    (ok if (HERE / f).exists() else bad)(f"{f} " + ("is there" if (HERE / f).exists() else "is MISSING: copy it back from your zip"))
for f in ("links.txt", "picks.txt", "digital.txt"):
    if not (HERE / f).exists():
        (HERE / f).write_text("", encoding="utf-8"); fix(f"{f} was missing: made an empty one")
if (HERE / "reset.bat").exists():
    warn("reset.bat exists. NEVER run it: it deletes docs and state.db (all your pins).")

# ---- keys
keys = read("keys.bat")
m = re.search(r"PEXELS_API_KEY=(\S+)", keys)
if m and len(m.group(1)) > 10:
    ok("keys.bat has a Pexels key")
else:
    bad("keys.bat has NO Pexels key (set PEXELS_API_KEY=...). Pins that need a photo will fail. Your old keys.bat or pexels.com/api has it.")

# ---- config.yaml (simple reader, no extra package needed)
cfg = read("config.yaml")
def cval(k):
    m = re.search(r"^\s*" + re.escape(k) + r":\s*[\"']?([^\"'#\n]*)", cfg, re.M)
    return m.group(1).strip() if m else ""
for k in ("media_base_url", "landing_base_url"):
    v = cval(k)
    (ok if v.startswith("https://") else bad)(f"config.yaml {k}: {v or 'EMPTY'}")
cfg_tag = cval("amazon_tag")
pm = cval("publish_mode") or "now"
ok(f"publish_mode: {pm} (now = no dates, pins post as soon as the CSV is uploaded)")
if "own_publish" in cfg and pm == "now":
    ok("own_publish line is there but publish_mode now wins: nothing to do")

# ---- products.csv
rows = []
if (HERE / "products.csv").exists():
    try:
        with open("products.csv", newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            fields, rows = rd.fieldnames or [], list(rd)
        need = ["name", "affiliate_url", "network", "category"]
        miss = [c for c in need if c not in fields]
        (bad if miss else ok)(f"products.csv columns: " + (f"MISSING {miss}" if miss else "ok"))
        names = [r.get("name", "") for r in rows]
        empty = [r for r in rows if not r.get("name") or not r.get("affiliate_url")]
        if empty:
            fix(f"products.csv: removed {len(empty)} rows with no name or link")
        seen, clean, dup = set(), [], 0
        for r in rows:
            k = (r.get("name") or "").lower()
            if not r.get("name") or not r.get("affiliate_url"):
                continue
            if k in seen:
                dup += 1; continue
            seen.add(k); clean.append(r)
        if dup:
            fix(f"products.csv: removed {dup} duplicate product rows")
        if empty or dup:
            Path("products.csv.bak").write_bytes(Path("products.csv").read_bytes())
            with open("products.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(clean)
            rows = clean
        by = {}
        for r in rows:
            by[r.get("network") or "amazon"] = by.get(r.get("network") or "amazon", 0) + 1
        ok("products by network: " + ", ".join(f"{k} {v}" for k, v in by.items()))
        own = by.get("own", 0)
        if own:
            warn(f"products.csv has {own} 'own' products (packs from the OLD Asset Packer). Run asset_packer\\clean_old_agent.bat once, they are not needed here.")
        tags = {m.group(1) for r in rows for m in [re.search(r"tag=([A-Za-z0-9_-]+)", r.get("affiliate_url", ""))] if m}
        (ok if (tags or cfg_tag) else warn)(f"Amazon store tag in use: {', '.join(sorted(tags)) or cfg_tag}" if (tags or cfg_tag) else "no Amazon tag found in config.yaml or products.csv: new Amazon products would earn nothing")
        amz = [r for r in rows if (r.get("network") or "amazon") == "amazon"]
        notag = [r for r in amz if "tag=" not in r.get("affiliate_url", "")]
        (warn if notag else ok)(f"{len(notag)} Amazon links without your tag (they would earn nothing)" if notag else "all Amazon links carry a tag")
        miss_img = [r for r in rows if r.get("image_url") and not r["image_url"].startswith("http") and not Path(r["image_url"]).exists()]
        if miss_img:
            warn(f"{len(miss_img)} products have an image_url file that does not exist: their pins fall back to a stock photo")
    except Exception as e:
        bad(f"products.csv cannot be read: {e}")

# ---- stray files from the old tool
sp = HERE / "pinterest.py"
if sp.exists() and "def add_packs" in read(sp):
    sp.unlink(); fix("removed pinterest.py (a file of the Asset Packer that was in the wrong folder)")

# ---- state.db
if (HERE / "state.db").exists():
    try:
        con = sqlite3.connect("state.db")
        n = con.execute("select count(*) from pins").fetchone()[0]
        st = dict(con.execute("select status, count(*) from pins group by status").fetchall())
        ok(f"state.db: {n} pins {st}")
        slugs = {re.sub(r"[^a-z0-9]+", "-", (r.get("name") or "").lower()).strip("-")[:60] for r in rows}
        orph = [s for (s,) in con.execute("select distinct slug from pins").fetchall() if s not in slugs]
        if orph:
            warn(f"state.db has pins of {len(orph)} products that are not in products.csv any more (harmless; they only fill the database)")
        con.close()
    except Exception as e:
        bad(f"state.db is damaged: {e}")
else:
    warn("state.db does not exist yet (normal before the first run)")

# ---- exports
ex = HERE / "exports"
ex.mkdir(exist_ok=True)
(ex / "uploaded").mkdir(exist_ok=True)
pend = list(ex.glob("*.csv"))
dated = 0
for c in pend:
    try:
        r = list(csv.reader(open(c, newline="", encoding="utf-8")))
        if r and "Publish date" in r[0]:
            i = r[0].index("Publish date"); dated += sum(1 for x in r[1:] if len(x) > i and x[i])
    except Exception:
        pass
ok(f"exports: {len(pend)} CSV waiting for upload" + (f", {dated} pins in them still have a publish date (run auto.bat once: it removes the dates)" if dated and pm == "now" else ""))

# ---- git
if (HERE / ".git").exists():
    lock = HERE / ".git" / "index.lock"
    if lock.exists():
        busy = False
        if os.name == "nt":
            busy = "git.exe" in run(["tasklist", "/FI", "IMAGENAME eq git.exe"])[1]
        if busy:
            warn("git.lock exists and git.exe is running: close VS Code / other black windows, then run doctor.bat again")
        else:
            lock.unlink(); fix("removed the stale .git\\index.lock (that was the 'Unable to create index.lock' error)")
    code, url = run(["git", "remote", "get-url", "origin"])
    if code == 0:
        ok(f"git remote origin: {url}")
        code, out = run(["git", "ls-remote", "--heads", "origin"], 40)
        (ok if code == 0 else bad)("GitHub reachable, push should work" if code == 0 else f"cannot reach GitHub: {out[-150:]}")
    else:
        bad("git has no remote 'origin'. run.bat adds it on the next run (https://github.com/jawadd07/pins.git).")
    code, out = run(["git", "status", "-sb"])
    first = out.splitlines()[0] if out else ""
    (warn if "ahead" in first else ok)("git: " + (first or "clean"))
else:
    warn("no .git folder here: run.bat will make one and push (first push can be refused if the GitHub repo already has pins: then ask for help)")

# ---- the site
base = cval("landing_base_url")
if base:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/", timeout=20) as r:
            ok(f"your GitHub Pages site answers ({r.status})")
    except Exception as e:
        warn(f"GitHub Pages did not answer ({str(e)[:60]}). If you just pushed, wait 2 minutes.")
d = HERE / (cval("out_dir") or "docs")
pages = list((d / "pages").glob("*.html")) if (d / "pages").exists() else []
(ok if pages or not rows else warn)(f"{d.name}\\pages: {len(pages)} landing pages")
if rows and pages:
    slugs = {re.sub(r"[^a-z0-9]+", "-", (r.get("name") or "").lower()).strip("-")[:60] for r in rows}
    stale = [p for p in pages if p.stem not in slugs]
    if stale:
        warn(f"{len(stale)} landing pages belong to products that are not in products.csv. The next run.bat pushes their removal only if you delete them. Names: " + ", ".join(p.stem for p in stale[:4]))

# ---- python
vp = HERE / ".venv" / "Scripts" / "python.exe"
(ok if vp.exists() or os.name != "nt" else warn)(".venv exists" if vp.exists() else "no .venv yet: auto.bat makes it on the first run")

# ---- report
def show(title, lst):
    if lst:
        print(f"\n{title}")
        for x in lst:
            print("  - " + x)

print("=" * 64 + "\nPINTEREST AGENT DOCTOR\n" + "=" * 64)
show("FIXED BY ME", FIX)
show("PROBLEMS (you must do something)", BAD)
show("WARNINGS", WARN)
show("OK", OK)
print("\n" + "-" * 64)
print("RESULT: " + ("PROBLEMS FOUND: read the PROBLEMS list" if BAD else "healthy" + (" (see the warnings)" if WARN else "")))
print("""
HOW TO RUN THE AGENT
  auto.bat   Amazon + Digistore: adds 5 new Amazon products, imports links.txt / picks.txt / digital.txt,
             makes the pins and landing pages, pushes to GitHub. Run it 2 times a week.
  run.bat    only makes pins for products that already exist and pushes (auto.bat calls it itself).
  After it says DONE: wait 2 minutes, then upload the newest CSV from exports in Pinterest
  (Settings > Import content > Upload .csv), and move it to exports\\uploaded.
  Never run reset.bat.""")
