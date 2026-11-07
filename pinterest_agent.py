#!/usr/bin/env python3
"""Pinterest affiliate pipeline: products.csv -> text -> images -> landing pages -> drip schedule -> bulk CSV / API post."""
import argparse, csv, hashlib, json, os, random, re, sqlite3, textwrap, time
from datetime import datetime, timedelta
from pathlib import Path
import requests, yaml
from PIL import Image, ImageDraw, ImageFont

CFG, OUT = {}, Path("site")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def db():
    c = sqlite3.connect("state.db")
    c.execute("""create table if not exists pins(id integer primary key, slug text, variant int,
        title text, descr text, link text, board text, image text, media_url text,
        sched text, status text default 'new', h text unique)""")
    return c


# ---------- text ----------
ANGLES = [
    ("{n}: Easy Upgrade Idea", "Looking for {k}? {n} makes it simple and affordable. Save this pin for later and check the details."),
    ("Best {k} Ideas: {n}", "Our top pick for {k}: {n}. Practical, easy to use, great for everyday life. Tap to see more."),
    ("{k} Made Easy With {n}", "Struggling with {k}? Here is a simple fix: {n}. Pin it now so you can find it later."),
    ("Budget-Friendly {k}: {n}", "Want {k} without overspending? {n} is worth a look. Save for your next shopping list."),
    ("Gift Idea: {n}", "Need a useful gift? {n} is a great idea for anyone who cares about {k}. Save it for later."),
    ("Before You Buy: {n}", "Researching {k}? Take a look at {n} and see if it fits your needs. Save this pin to compare later."),
]


def gen_text(p, n, dry, start=0):
    prov = CFG.get("text", {}).get("provider", "template")
    kws = [k.strip() for k in p.get("keywords", "").split(";") if k.strip()]
    if dry or prov == "template":
        out = []
        for i in range(n):
            t, d = ANGLES[(start + i) % len(ANGLES)]
            k = kws[i % len(kws)] if kws else p.get("category", "your home")
            out.append({"title": t.format(n=p["name"], k=k.title()), "description": d.format(n=p["name"], k=k),
                        "overlay": f"{k} idea", "image_prompt":
                        f"{p['name']}, {k}, lifestyle photo, bright natural light, vertical composition, no text"})
        return out
    prompt = f"""Write {n} DIFFERENT Pinterest pin variants for this product.
Product: {p['name']}
Niche/category: {p.get('category','')}
Keywords: {p.get('keywords','')}
Notes: {p.get('description','')}
Rules: title <=90 chars, main keyword first, no clickbait lies. description 300-450 chars, natural,
2-3 keywords, max 3 hashtags, no prices/claims you cannot verify. overlay = <=6 word hook for image.
image_prompt = photo scene for AI image gen, vertical, lifestyle, NO text/logos in image.
Each variant uses a different angle (problem, idea, list, budget, gift, before/after).
Return ONLY a JSON list of objects with keys: title, description, overlay, image_prompt."""
    if prov == "gemini":  # free tier, key from aistudio.google.com
        m = CFG["text"].get("gemini_model", "gemini-2.0-flash")
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                          params={"key": os.environ["GEMINI_API_KEY"]}, timeout=120,
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseMimeType": "application/json"}})
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    elif prov == "claude":  # paid
        import anthropic
        r = anthropic.Anthropic().messages.create(
            model=CFG["claude_model"], max_tokens=3000, messages=[{"role": "user", "content": prompt}])
        txt = r.content[0].text
    else:
        raise SystemExit("text.provider must be template | gemini | claude")
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)[:n]


# ---------- image ----------
def fetch(url, path):
    path.write_bytes(requests.get(url, timeout=120).content)


def gen_base(p, v, tmp, dry):
    prov = CFG["image"]["provider"]
    if dry:
        Image.new("RGB", (1000, 1500), (random.randint(40, 200),) * 3).save(tmp)
    elif prov == "fal":
        r = requests.post(CFG["image"]["fal_endpoint"], headers={"Authorization": f"Key {os.environ['FAL_KEY']}"},
                          json={"prompt": v["image_prompt"], "image_size": {"width": 1000, "height": 1500},
                                "num_images": 1}, timeout=240)
        r.raise_for_status()
        fetch(r.json()["images"][0]["url"], tmp)
    elif prov == "design":  # free, offline, unlimited: designed text pin
        draw_design(p, v, tmp)
    elif prov == "pollinations":  # free, no key, rate limited -> slow + retry
        from urllib.parse import quote
        time.sleep(CFG["image"].get("delay", 15))
        last = None
        for attempt in range(5):
            try:
                u = (f"https://image.pollinations.ai/prompt/{quote(v['image_prompt'])}"
                     f"?width=1000&height=1500&model=flux&nologo=true&seed={random.randint(1, 10**6)}")
                r = requests.get(u, timeout=180)
                ct = r.headers.get("content-type", "")
                if r.ok and ct.startswith("image/"):
                    tmp.write_bytes(r.content)
                    Image.open(tmp).verify()
                    return
                last = f"{r.status_code} {ct} {r.text[:80]}"
            except Exception as e:
                last = str(e)
            print(f"  image retry {attempt + 1}/5: {last}")
            time.sleep(30)
        raise RuntimeError("pollinations failed: " + str(last))
    elif prov == "product":  # use product's own image_url
        fetch(p["image_url"], tmp)
    else:
        raise SystemExit("image.provider must be design | pollinations | fal | product")


def font(sz):
    for f in ["DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"]:
        try:
            return ImageFont.truetype(f, sz)
        except OSError:
            pass
    return ImageFont.load_default()


PALETTES = [  # top, bottom, text, accent
    ((200, 85, 61), (242, 208, 164), (255, 255, 255), (255, 240, 225)),
    ((79, 109, 91), (220, 229, 214), (255, 255, 255), (240, 247, 236)),
    ((31, 42, 68), (224, 182, 107), (255, 255, 255), (255, 236, 200)),
    ((232, 180, 184), (255, 241, 230), (74, 40, 50), (120, 60, 75)),
    ((92, 60, 110), (232, 200, 225), (255, 255, 255), (250, 232, 247)),
    ((40, 100, 110), (200, 232, 228), (255, 255, 255), (232, 250, 247)),
]


def draw_design(p, v, tmp):
    rnd = random.Random(hash(p["name"]) % 10**6 + len(v["overlay"]))
    top, bot, tc, ac = rnd.choice(PALETTES)
    im = Image.new("RGB", (1000, 1500))
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(1500):
        t = y / 1499
        d.line([(0, y), (1000, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    for _ in range(5):  # soft decor circles
        r = rnd.randint(120, 320)
        x, y = rnd.randint(-100, 1100), rnd.randint(-100, 1600)
        d.ellipse((x - r, y - r, x + r, y + r), fill=ac + (45,))
    cat = (p.get("category") or "ideas").replace("-", " ").upper()
    f_small = font(40)
    w = d.textlength(cat, font=f_small) + 70
    d.rounded_rectangle((500 - w / 2, 150, 500 + w / 2, 225), radius=38, outline=tc, width=4)
    d.text((500, 188), cat, font=f_small, fill=tc, anchor="mm")
    head = textwrap.wrap(v["overlay"].upper(), 13)[:4]
    sz = 118
    while sz > 60 and max(d.textlength(l, font=font(sz)) for l in head) > 860:
        sz -= 6
    y = 470
    for ln in head:
        d.text((500, y), ln, font=font(sz), fill=tc, anchor="mm")
        y += int(sz * 1.2)
    d.line([(380, y + 10), (620, y + 10)], fill=tc, width=6)
    y += 90
    for ln in textwrap.wrap(p["name"], 24)[:3]:
        d.text((500, y), ln, font=font(58), fill=ac, anchor="mm")
        y += 75
    d.rounded_rectangle((250, 1230, 750, 1330), radius=50, fill=tc)
    d.text((500, 1280), "SAVE FOR LATER", font=font(44), fill=top, anchor="mm")
    im.save(tmp)


def make_image(p, v, out, dry):
    tmp = out.with_name(out.stem + "_base.png")
    gen_base(p, v, tmp, dry)
    im = Image.open(tmp).convert("RGB")
    w, h = im.size  # crop to 2:3
    tw = int(h * 2 / 3)
    if tw <= w:
        im = im.crop(((w - tw) // 2, 0, (w - tw) // 2 + tw, h))
    else:
        th = int(w * 3 / 2)
        im = im.crop((0, (h - th) // 2, w, (h - th) // 2 + th))
    im = im.resize((1000, 1500))
    if CFG["image"].get("overlay_text", True) and CFG["image"]["provider"] != "design":
        d = ImageDraw.Draw(im, "RGBA")
        lines = textwrap.wrap(v["overlay"].upper(), 16)[:3]
        f = font(88)
        bh = 120 * len(lines) + 60
        d.rectangle((0, 1500 - bh - 80, 1000, 1500 - 80), fill=(0, 0, 0, 170))
        y = 1500 - bh - 50
        for ln in lines:
            d.text((500, y), ln, font=f, fill="white", anchor="mt")
            y += 120
    im.save(out, quality=90)
    tmp.unlink(missing_ok=True)


# ---------- landing page ----------
PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><style>body{{font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.6}}
a.b{{display:inline-block;background:#e60023;color:#fff;padding:14px 28px;border-radius:999px;text-decoration:none;font-weight:700}}
small{{color:#666}}</style></head><body><h1>{name}</h1><p>{desc}</p>
<p><a class="b" rel="sponsored nofollow noopener" href="{url}">Check it out</a></p>
<p><small>{disc}</small></p></body></html>"""


def write_page(p, slug):
    pg = OUT / "pages" / f"{slug}.html"
    pg.write_text(PAGE.format(name=p["name"], desc=p.get("description", ""), url=p["affiliate_url"],
                              disc=CFG["landing_disclosure"]), encoding="utf-8")


# ---------- schedule ----------
def schedule(con):
    rows = con.execute("select id,variant from pins where sched is null").fetchall()
    random.shuffle(rows)
    rows.sort(key=lambda r: r[1])  # spread variants of same product across days
    s = CFG["schedule"]
    start = datetime.fromisoformat(s["start_date"]) if s.get("start_date") else \
        (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    h0, h1 = s["hours"]
    day = 0
    while rows:
        d = start + timedelta(days=day)
        quota = s["ramp"][min(day // 7, len(s["ramp"]) - 1)]
        used = con.execute("select count(*) from pins where substr(sched,1,10)=?", (d.strftime("%Y-%m-%d"),)).fetchone()[0]
        take = rows[:max(0, quota - used)]
        rows = rows[len(take):]
        mins = sorted(random.sample(range(h0 * 60, h1 * 60), len(take)))
        for (pid, _), m in zip(take, mins):
            t = d.replace(hour=m // 60, minute=m % 60).isoformat(timespec="seconds")
            con.execute("update pins set sched=? where id=?", (t, pid))
        day += 1
    con.commit()


# ---------- export ----------
def export(con):
    lim = (datetime.now() + timedelta(days=29)).isoformat(timespec="seconds")
    rows = con.execute("select id,title,descr,link,board,media_url,sched from pins where status='new' and sched<=? order by sched",
                       (lim,)).fetchall()
    for i in range(0, len(rows), 200):  # Pinterest limit 200/file
        chunk = rows[i:i + 200]
        Path("exports").mkdir(exist_ok=True)
        f = Path("exports") / f"pinterest_bulk_{datetime.now():%Y%m%d}_{i // 200 + 1}.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date", "Keywords"])
            for _, t, d, l, b, m, s in chunk:
                w.writerow([t, m, b, "", d, l, s, ""])
        con.executemany("update pins set status='exported' where id=?", [(r[0],) for r in chunk])
        print("wrote", f, len(chunk), "pins")
    con.commit()


# ---------- commands ----------
def read_products():
    with open(CFG["products_file"], newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("name") and r.get("affiliate_url")]


def cmd_run(a):
    con = db()
    base = CFG["landing_base_url"].rstrip("/")
    media = CFG["media_base_url"].rstrip("/")
    for p in read_products():
        slug = slugify(p["name"])
        have = con.execute("select count(*) from pins where slug=?", (slug,)).fetchone()[0]
        need = CFG["variants_per_product"] - have
        if need <= 0:
            continue
        print("product:", p["name"], "| new variants:", need)
        variants = gen_text(p, need, a.dry, have)
        write_page(p, slug)
        for i, v in enumerate(variants, start=have):
            img = OUT / "images" / f"{slug}-v{i}.jpg"
            try:
                make_image(p, v, img, a.dry)
            except Exception as e:
                print("  image failed, rerun later:", e)
                img.with_name(img.stem + "_base.png").unlink(missing_ok=True)
                break
            link = f"{base}/pages/{slug}.html?v={i}" if base else p["affiliate_url"]
            desc = f"{v['description'].strip()} {CFG['pin_disclosure']}"[:500]
            title = v["title"][:100]
            board = p.get("board") or CFG["boards"].get(p.get("category", ""), CFG["default_board"])
            h = hashlib.sha1((link + title).encode()).hexdigest()
            try:
                con.execute("insert into pins(slug,variant,title,descr,link,board,image,media_url,h) values(?,?,?,?,?,?,?,?,?)",
                            (slug, i, title, desc, link, board, str(img), f"{media}/images/{img.name}", h))
            except sqlite3.IntegrityError:
                print("  dup skip", title)
        con.commit()
    schedule(con)
    export(con)
    print("done. push 'docs/' to GitHub, then upload bulk CSV in Pinterest.")


def cmd_post_due(a):
    """Only after Pinterest API access approved. Run via cron every 15 min."""
    con = db()
    tok = os.environ["PINTEREST_TOKEN"]
    now = datetime.now().isoformat(timespec="seconds")
    for pid, t, d, l, b, m in con.execute(
            "select id,title,descr,link,board,media_url from pins where status in('new','exported') and sched<=?", (now,)).fetchall():
        bid = CFG.get("board_ids", {}).get(b)
        if not bid:
            print("no board_id for", b); continue
        r = requests.post("https://api.pinterest.com/v5/pins", headers={"Authorization": f"Bearer {tok}"},
                          json={"board_id": bid, "title": t, "description": d, "link": l,
                                "media_source": {"source_type": "image_url", "url": m}}, timeout=60)
        print(pid, r.status_code, r.text[:120])
        if r.ok:
            con.execute("update pins set status='posted' where id=?", (pid,)); con.commit()


def cmd_stats(a):
    for s, c in db().execute("select status,count(*) from pins group by status"):
        print(s, c)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "post-due", "stats"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--dry", action="store_true", help="no API calls, grey placeholder images")
    a = ap.parse_args()
    CFG.update(yaml.safe_load(open(a.config, encoding="utf-8")))
    OUT = Path(CFG.get("out_dir", "site"))
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    {"run": cmd_run, "post-due": cmd_post_due, "stats": cmd_stats}[a.cmd](a)
