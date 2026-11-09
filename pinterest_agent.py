#!/usr/bin/env python3
"""Pinterest affiliate pipeline: products.csv -> text -> images -> landing pages -> drip schedule -> bulk CSV / API post."""
import argparse, csv, hashlib, html, json, os, random, re, shutil, sqlite3, textwrap, time
from datetime import datetime, timedelta
from pathlib import Path
import requests, yaml
from PIL import Image, ImageDraw, ImageFont

CFG, OUT = {}, Path("site")
EXACT = {"on": False}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


NOW = "0000-00-00T00:00:00"   # marker: no publish date, Pinterest posts the pin as soon as the CSV is uploaded


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
    ("Small Space Hack: {n}", "Short on room? {n} fits {k} ideas without the clutter. Save this pin for your next home refresh."),
    ("Cozy Home Find: {n}", "Add a cozy touch with {n}. A simple way to upgrade {k}. Pin it and come back when you are ready."),
    ("Weekend Refresh: {n}", "Planning a weekend refresh? {n} is an easy win for {k}. Save it to your board."),
    ("Style Inspo: {n}", "Style inspiration for {k}: {n}. Tap to see the details and save for later."),
]



STYLE = {"fashion", "jewelry", "beauty", "gifts", "party"}
UTIL = {"organization", "fitness", "pets", "crochet", "planners", "weddings", "languages"}
DESIGN = {"design"}
ANGLES_DESIGN = [
    ("{n}: Editable Vector Set", "Looking for {k}? {n} is a ready to use vector set for your next project. Save this pin and check the details."),
    ("Licensed Vectors For Designers: {n}", "Need {k} for your designs? {n} comes with a commercial licence. Save it for later."),
    ("Vector Pack: {n}", "A clean vector pack for {k}. {n} opens in Illustrator, Affinity and Inkscape. Pin it for your next project."),
    ("Save This For Your Next Project", "Working on a logo, sticker or print? {n} has {k} shapes ready to edit. Tap to see the pack."),
    ("Instant Download: {n}", "Download {n} right after purchase. Editable EPS files for {k}. Save this pin."),
    ("Graphic Design Resource: {n}", "A handy resource for {k}: {n}. Scale it to any size without losing quality."),
    ("Silhouette And Vector Ideas: {n}", "Ideas for {k}? {n} is a set of clean vectors you can recolor and reuse. Save for later."),
    ("Craft And Print Ready: {n}", "Use {n} for stickers, prints, signs and more. {k} vectors with a commercial licence."),
    ("Build Your Asset Library: {n}", "Add {k} to your asset library with {n}. Save this pin to find it again."),
    ("Popular Vector Pack: {n}", "{n} is a popular pick for {k}. Open the pack to see what is inside."),
]
ANGLES_STYLE = [
    ("Style Inspo: {n}", "Looking for {k}? {n} is an easy way to add style. Save this pin for later."),
    ("Trending Now: {n}", "Searches for {k} keep climbing. See {n} and save it for your next look."),
    ("Gift Idea: {n}", "Need a gift idea? {n} fits anyone into {k}. Save it for later."),
    ("Easy Upgrade: {n}", "Upgrade your look with {k}. {n} is a simple pick. Pin it for later."),
    ("Wishlist Find: {n}", "Adding {k} to your wishlist? Take a look at {n} and save it."),
    ("Must-Have: {n}", "A must-have for {k} fans: {n}. Tap to see the details."),
    ("Everyday Pick: {n}", "Easy to wear or use every day. {n} is a great {k} find. Save for later."),
    ("Budget Style Find: {n}", "Want {k} without overspending? {n} is worth a look. Save it."),
    ("Pin For Later: {n}", "Planning your {k} shopping list? Save {n} for later."),
    ("Popular Pick: {n}", "{n} keeps showing up in {k} searches. Save this pin to compare later."),
]
ANGLES_UTIL = [
    ("Easy Win: {n}", "Want better {k}? {n} makes it simple. Save this pin for later."),
    ("Life Hack: {n}", "A simple {k} hack: {n}. Pin it so you can find it again."),
    ("Worth It: {n}", "Is {n} worth it for {k}? Take a look and save it to compare."),
    ("Beginner Friendly: {n}", "New to {k}? {n} is an easy place to start. Save for later."),
    ("Save Time With {n}", "Make {k} easier with {n}. Save this pin for your next shopping list."),
    ("Smart Pick: {n}", "A smart pick for {k}: {n}. Tap to see more and save it."),
    ("Budget Find: {n}", "Looking for {k} on a budget? {n} is worth a look."),
    ("Daily Routine Upgrade: {n}", "Upgrade your routine with {n}. Great for {k}. Pin it for later."),
    ("Top Pick: {n}", "Our top pick for {k}: {n}. Save this pin so you do not lose it."),
    ("Gift Idea: {n}", "Need a useful gift? {n} is great for anyone into {k}. Save it."),
]


def gen_text(p, n, dry, start=0):
    prov = CFG.get("text", {}).get("provider", "template")
    kws = [k.strip() for k in p.get("keywords", "").split(";") if k.strip()]
    if dry or prov == "template":
        out = []
        cat = p.get("category", "")
        angles = ANGLES_DESIGN if cat in DESIGN else ANGLES_STYLE if cat in STYLE else ANGLES_UTIL if cat in UTIL else ANGLES
        for i in range(n):
            t, d = angles[(start + i) % len(angles)]
            k = kws[i % len(kws)] if kws else p.get("category", "your home")
            if cat in DESIGN:      # vector packs: a hook that says what it is, not "... idea"
                hooks = [f"{k} vector pack", f"{k} vectors", "editable eps vectors", f"{k} design set", "commercial use vectors", f"{k} clipart bundle", "vector art bundle", "instant download"]
                overlay = hooks[(start + i) % len(hooks)]
            else:
                overlay = f"{k} idea"
            out.append({"title": t.format(n=p["name"], k=k.title()), "description": d.format(n=p["name"], k=k),
                        "overlay": overlay, "image_prompt":
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
    EXACT["on"] = False
    if p.get("image_url") and not dry:  # exact product photo wins
        try:
            if os.path.exists(p["image_url"]):  # local file, e.g. a KDP book cover
                shutil.copy(p["image_url"], tmp)
            else:
                fetch(p["image_url"], tmp)
            Image.open(tmp).verify()
            EXACT["on"] = True
            return
        except Exception as e:
            print("  image_url failed, using", prov, "|", str(e)[:60])
    if dry:
        Image.new("RGB", (1000, 1500), (random.randint(40, 200),) * 3).save(tmp)
    elif prov == "fal":
        r = requests.post(CFG["image"]["fal_endpoint"], headers={"Authorization": f"Key {os.environ['FAL_KEY']}"},
                          json={"prompt": v["image_prompt"], "image_size": {"width": 1000, "height": 1500},
                                "num_images": 1}, timeout=240)
        r.raise_for_status()
        fetch(r.json()["images"][0]["url"], tmp)
    elif prov == "pexels":  # free real photos, free key: pexels.com/api
        key = os.environ["PEXELS_API_KEY"]
        kw0 = (p.get("keywords", "").split(";")[0] or p["name"]).strip()
        cat = p.get("category", "")
        cat_q = {"crochet": "crochet yarn", "planners": "planner notebook desk", "weddings": "wedding planning",
                 "languages": "language learning books", "design": "graphic design desk"}.get(cat, (cat or "home").replace("-", " "))
        allp, q = [], ""
        for q in dict.fromkeys([p.get("photo_query") or p["name"], kw0, cat_q]):  # name -> keyword -> category
            r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                             params={"query": q, "orientation": "portrait", "per_page": 30}, timeout=60)
            r.raise_for_status()
            allp = r.json().get("photos", [])
            if len(allp) >= 5:
                break
        used = set(open("used_photos.txt").read().split()) if os.path.exists("used_photos.txt") else set()
        photos = [x for x in allp if str(x["id"]) not in used] or allp
        if not photos:
            raise RuntimeError("no pexels photo for " + q)
        ph = random.choice(photos[:15])
        fetch(ph["src"]["large2x"], tmp)
        with open("used_photos.txt", "a") as uf:
            uf.write(str(ph["id"]) + "\n")
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
        raise SystemExit("image.provider must be design | pexels | pollinations | fal | product")


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


def compose_product(tmp, v, out):
    """exact product photo on a designed pin: 6 palettes x 3 layouts, so 8 pins of one photo look different"""
    photo = Image.open(tmp).convert("RGB")
    rnd = random.Random(sum(map(ord, out.name)))
    top, bot, tc, ac = PALETTES[rnd.randrange(len(PALETTES))]
    im = Image.new("RGB", (1000, 1500))
    d = ImageDraw.Draw(im, "RGBA")
    for y in range(1500):
        t = y / 1499
        d.line([(0, y), (1000, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    lay = rnd.randrange(3)
    card_y, card_h = [(520, 800), (120, 800), (300, 900)][lay]
    d.rounded_rectangle((70, card_y, 930, card_y + card_h), radius=36, fill=(255, 255, 255, 255))
    sc = min(800 / photo.width, (card_h - 50) / photo.height)
    ph = photo.resize((max(1, int(photo.width * sc)), max(1, int(photo.height * sc))))
    im.paste(ph, (500 - ph.width // 2, card_y + (card_h - ph.height) // 2))
    head = textwrap.wrap(v["overlay"].upper(), 14)[:3]
    sz = 100 if lay != 2 else 76
    while sz > 50 and max(d.textlength(l, font=font(sz)) for l in head) > 860:
        sz -= 6
    y = [170, card_y + card_h + 50, 100][lay]
    r, g, b = im.getpixel((500, min(1499, y + 40)))
    hc = (30, 30, 45) if 0.299 * r + 0.587 * g + 0.114 * b > 150 else (255, 255, 255)  # readable on light or dark
    for ln in head:
        d.text((500, y), ln, font=font(sz), fill=hc, anchor="mt")
        y += int(sz * 1.2)
    d.rounded_rectangle((300, 1385, 700, 1465), radius=40, fill=tc)
    d.text((500, 1425), "SAVE FOR LATER", font=font(36), fill=top, anchor="mm")
    im.save(out, quality=90)


def make_image(p, v, out, dry):
    tmp = out.with_name(out.stem + "_base.png")
    gen_base(p, v, tmp, dry)
    if EXACT["on"]:
        compose_product(tmp, v, out)
        tmp.unlink(missing_ok=True)
        return
    im = Image.open(tmp).convert("RGB")
    w, h = im.size  # crop to 2:3
    tw = int(h * 2 / 3)
    if tw <= w:
        im = im.crop(((w - tw) // 2, 0, (w - tw) // 2 + tw, h))
    else:
        th = int(w * 3 / 2)
        im = im.crop((0, (h - th) // 2, w, (h - th) // 2 + th))
    im = im.resize((1000, 1500))
    if CFG["image"].get("overlay_text", True) and (CFG["image"]["provider"] != "design" or p.get("image_url")):
        d = ImageDraw.Draw(im, "RGBA")
        lines = textwrap.wrap(v["overlay"].upper(), 16)[:3]
        f = font(88)
        bh = 120 * len(lines) + 60
        lay = sum(map(ord, out.name)) % 3  # 3 layouts so pins of one photo look different
        y0 = [1500 - bh - 80, 80, (1500 - bh) // 2][lay]
        d.rectangle((0, y0, 1000, y0 + bh), fill=(0, 0, 0, 150))
        y = y0 + 30
        for ln in lines:
            d.text((500, y), ln, font=f, fill="white", anchor="mt")
            y += 120
    im.save(out, quality=90)
    tmp.unlink(missing_ok=True)


# ---------- landing page ----------
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title><meta name="description" content="{desc}">
<style>body{{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px 16px;line-height:1.6;color:#222}}
a.home{{color:#e60023;text-decoration:none;font-size:14px}}img{{width:100%;border-radius:16px;margin:16px 0}}
a.b{{display:inline-block;background:#e60023;color:#fff;padding:14px 28px;border-radius:999px;text-decoration:none;font-weight:700}}
small{{color:#666;display:block;margin-top:24px}}</style></head><body>
<a class="home" href="../index.html">&larr; All picks</a><h1>{name}</h1>{img}<p>{desc}</p>
<p><a class="b" rel="sponsored nofollow noopener" href="{url}">Check it out</a></p>
<small>{disc}</small></body></html>"""


def write_page(p, slug):
    pg = OUT / "pages" / f"{slug}.html"
    net = p.get("network", "amazon")
    if net in ("own", "gumroad"):  # my own products: no affiliate wording
        disc = CFG.get("landing_disclosure_own", "These are digital products made and sold by me.")
    else:
        disc = CFG["landing_disclosure"] if net == "amazon" else CFG.get(
            "landing_disclosure_generic", "Disclosure: this page contains affiliate links. I may earn a commission at no extra cost to you.")
    img = f'<img src="../images/{slug}-v0.jpg" alt="{html.escape(p["name"])}">' if (OUT / "images" / f"{slug}-v0.jpg").exists() else ""
    pg.write_text(PAGE.format(name=html.escape(p["name"]), desc=html.escape(p.get("description", "")), url=html.escape(p["affiliate_url"]),
                              disc=html.escape(disc), img=img), encoding="utf-8")


SITE_CSS = """body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;color:#222;background:#fafafa;line-height:1.6}
header{background:#fff;padding:32px 16px;text-align:center;border-bottom:1px solid #eee}header h1{margin:0 0 8px}
main{max-width:1000px;margin:0 auto;padding:16px}h2{margin-top:40px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:16px}
.card{background:#fff;border-radius:14px;overflow:hidden;text-decoration:none;color:#222;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.card img{width:100%;aspect-ratio:2/3;object-fit:cover;display:block}.card span{display:block;padding:10px 12px;font-weight:600;font-size:14px}
footer{max-width:1000px;margin:40px auto;padding:16px;color:#666;font-size:13px}a{color:#e60023}"""


def write_site(prods):
    """home page + privacy page, rebuilt every run so the site grows with the pins"""
    groups = {}
    for p in prods:
        groups.setdefault(p.get("category", ""), []).append(p)
    order = [c for c in CFG.get("boards", {}) if c in groups] + [c for c in groups if c not in CFG.get("boards", {})]
    amazon = any(p.get("network", "amazon") == "amazon" for p in prods)
    disc = CFG.get("landing_disclosure_generic", "Disclosure: this site contains affiliate links. I may earn a commission at no extra cost to you.")
    if amazon:
        disc += " As an Amazon Associate I earn from qualifying purchases."
    secs = []
    for c in order:
        title = html.escape(CFG.get("boards", {}).get(c, c.replace("-", " ").title()))
        cards = []
        for p in groups[c]:
            slug = slugify(p["name"])
            im = f'<img loading="lazy" src="images/{slug}-v0.jpg" alt="{html.escape(p["name"])}">' if (OUT / "images" / f"{slug}-v0.jpg").exists() else ""
            cards.append(f'<a class="card" href="pages/{slug}.html">{im}<span>{html.escape(p["name"])}</span></a>')
        secs.append(f"<h2>{title}</h2><div class=\"grid\">{''.join(cards)}</div>")
    home = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><!-- Awin --><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Style and Home Picks</title><meta name="description" content="Style, home decor, kitchen, gift and lifestyle picks gathered from my Pinterest boards.">
<style>{SITE_CSS}</style></head><body>
<header><h1>Style and Home Picks</h1><p>Ideas for your home, wardrobe and gifts, shared on <a href="https://www.pinterest.com/jawadd_07/">Pinterest</a>.<br>Each page links to a product I think is worth a look.</p></header>
<main><p><small>{html.escape(disc)}</small></p>{''.join(secs)}</main>
<footer><p>{html.escape(disc)}</p><p><a href="privacy.html">Privacy</a></p></footer></body></html>"""
    (OUT / "index.html").write_text(home, encoding="utf-8")
    priv = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Privacy</title><style>{SITE_CSS}</style></head><body><main><p><a href="index.html">&larr; Home</a></p><h1>Privacy and disclosure</h1>
<p>This site does not ask for or store personal information and does not run its own accounts or comments.</p>
<p>Product links lead to other websites (for example Amazon or Digistore24). Those sites have their own cookies and privacy policies.</p>
<p>{html.escape(disc)}</p></main></body></html>"""
    (OUT / "privacy.html").write_text(priv, encoding="utf-8")


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
            off = s.get("audience_utc_offset", -5)  # hours in audience tz (US Eastern=-5); Pinterest reads CSV as UTC
            t = (d.replace(hour=m // 60, minute=m % 60) - timedelta(hours=off)).isoformat(timespec="seconds")
            con.execute("update pins set sched=? where id=?", (t, pid))
        day += 1
    con.commit()


# ---------- export ----------
def export(con):
    lim = (datetime.now() + timedelta(days=29)).isoformat(timespec="seconds")
    rows = con.execute("select id,title,descr,link,board,media_url,sched from pins where status='new' and sched<=? order by sched",
                       (lim,)).fetchall()
    for i in range(0, len(rows), 100):  # Pinterest limit 100/file
        chunk = rows[i:i + 100]
        Path("exports").mkdir(exist_ok=True)
        f = Path("exports") / f"pinterest_bulk_{datetime.now():%Y%m%d_%H%M}_{i // 100 + 1}.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date", "Keywords"])
            for _, t, d, l, b, m, s in chunk:
                w.writerow([t, m, b, "", d, l, "" if s == NOW else s, ""])
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
        write_page(p, slug)  # always refresh page so link edits reach old pins
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
            own = p.get("network") in ("own", "gumroad")
            desc = (v["description"].strip() if own else f"{v['description'].strip()} {CFG['pin_disclosure']}")[:500]   # own products: no "#ad affiliate" text
            title = v["title"][:100]
            board = p.get("board") or CFG["boards"].get(p.get("category", ""), CFG["default_board"])
            h = hashlib.sha1((link + title).encode()).hexdigest()
            try:
                now = p.get("network") in ("own", "gumroad") and CFG.get("own_publish", "now") == "now"   # my own products: post immediately
                con.execute("insert into pins(slug,variant,title,descr,link,board,image,media_url,sched,h) values(?,?,?,?,?,?,?,?,?,?)",
                            (slug, i, title, desc, link, board, str(img), f"{media}/images/{img.name}", NOW if now else None, h))
            except sqlite3.IntegrityError:
                print("  dup skip", title)
        con.commit()
    prods = read_products()
    for p in prods:
        write_page(p, slugify(p["name"]))  # again, now images exist
    write_site(prods)
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


def cmd_reschedule(a):
    """re-time pins that are not posted yet (use with new ramp). Old scheduled pins on Pinterest must be deleted by hand first."""
    con = db()
    q = "update pins set sched=NULL, status='new' where status in ('new','exported')"
    if a.after:
        con.execute(q + " and sched>=?", (a.after,))
    else:
        con.execute(q)
    con.commit()
    schedule(con)
    export(con)


def cmd_stats(a):
    for s, c in db().execute("select status,count(*) from pins group by status"):
        print(s, c)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "post-due", "stats", "reschedule"])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--after", default="", help="reschedule: only pins dated on/after YYYY-MM-DD")
    ap.add_argument("--dry", action="store_true", help="no API calls, grey placeholder images")
    a = ap.parse_args()
    CFG.update(yaml.safe_load(open(a.config, encoding="utf-8")))
    OUT = Path(CFG.get("out_dir", "site"))
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(parents=True, exist_ok=True)
    {"run": cmd_run, "post-due": cmd_post_due, "stats": cmd_stats, "reschedule": cmd_reschedule}[a.cmd](a)
