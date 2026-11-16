#!/usr/bin/env python3
"""KDP low-content book factory.  make: interior PDF + cover PDF + listing text per book.  link: add your published book to Pinterest.
KDP has no upload API: you upload the files yourself (about 5 minutes per book)."""
import argparse, csv, json, os, random, re, shutil
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader

OUT, STATE = Path("kdp_out"), Path("kdp_state.json")
W6, H9 = 6 * inch, 9 * inch
M = 0.6 * inch
THEMES = [("#2F4858", "#33658A", "#F6AE2D"), ("#5B3A29", "#B5651D", "#F4E3C1"), ("#2D6A4F", "#52B788", "#D8F3DC"),
          ("#6D2E46", "#C06C84", "#FDE2E4"), ("#1D3557", "#457B9D", "#F1FAEE"), ("#4A3F6B", "#8F7FBF", "#F3E8FF")]

# kind, title, subtitle, theme, prompts/headers (each book gets its own wording)
BOOKS = [
    ("gratitude", "Five Minute Gratitude Journal", "Simple Daily Prompts for a Calmer Mind", 0,
     ["Today I am grateful for", "One small win today", "Someone who made my day easier"]),
    ("habit", "Weekly Habit Tracker", "Build Routines That Last, One Week at a Time", 1, ["Weekly goal", "My focus this week", "Next week I will"]),
    ("budget", "Monthly Budget Planner", "Track Income, Bills and Savings in One Place", 2, []),
    ("meal", "Weekly Meal Planner and Grocery List", "Plan Your Week, Shop Smarter, Waste Less", 3, []),
    ("workout", "Workout Log Book", "Track Sets, Reps and Progress", 4, []),
    ("reading", "Book Review Journal", "Log What You Read, Rate It and Remember It", 5, []),
    ("sleep", "Sleep and Mood Tracker", "Understand Your Rest and Your Days", 0, []),
    ("gratitude", "Gratitude Journal for Students", "Daily Prompts for Focus and Confidence", 4, ["Today at school or study I am thankful for", "I felt proud when", "Tomorrow I want to"]),
    ("budget", "Savings Goals Planner", "Set a Target, Track Progress, Reach It", 1, []),
    ("habit", "Self Care Habit Tracker", "Small Daily Habits for a Healthier You", 3, ["This week I take care of myself by", "I need more of", "I need less of"]),
]
KEYS = {"gratitude": ["gratitude journal", "daily gratitude prompts", "mindfulness journal", "thankful journal", "positive thinking journal", "self care journal", "journal for women"],
        "habit": ["habit tracker", "weekly habit planner", "routine tracker", "goal tracker", "self improvement planner", "daily habits log", "productivity tracker"],
        "budget": ["budget planner", "monthly budget book", "bill tracker", "savings tracker", "finance planner", "expense tracker notebook", "money planner"],
        "meal": ["meal planner", "weekly meal planner notebook", "grocery list pad", "menu planner", "meal prep planner", "family meal planner", "food planner"],
        "workout": ["workout log book", "gym log", "fitness journal", "exercise tracker", "strength training log", "weightlifting journal", "fitness planner"],
        "reading": ["book review journal", "reading log", "book journal", "reading tracker", "book lovers gift", "book notebook", "reading planner"],
        "sleep": ["sleep tracker", "mood tracker journal", "sleep diary", "wellness journal", "daily mood log", "sleep log book", "self care tracker"]}
DESC = {"gratitude": "A simple daily gratitude journal with guided prompts and space to write.", "habit": "A weekly habit tracker with room for goals and notes.",
        "budget": "A clean budget planner with income, bills and savings pages.", "meal": "A weekly meal planner with a grocery list on every page.",
        "workout": "A workout log with room for exercises, sets, reps and notes.", "reading": "A reading journal with space for ratings and notes on each book.",
        "sleep": "A sleep and mood tracker with a weekly layout."}


QUERIES = {"gratitude": ["woman writing in journal", "person journaling with coffee", "woman smiling morning window", "hands writing notebook"],
           "habit": ["woman morning routine", "person stretching morning", "woman planning notebook desk", "person doing yoga at home"],
           "budget": ["couple budgeting laptop", "person counting money", "woman using calculator desk", "saving coins jar"],
           "meal": ["woman cooking healthy food", "family cooking kitchen", "meal prep containers", "woman chopping vegetables"],
           "workout": ["woman workout gym", "man lifting weights", "woman running outdoors", "person yoga mat"],
           "reading": ["woman reading book cozy", "person reading by window", "reading book with tea", "woman reading on sofa"],
           "sleep": ["woman sleeping bed", "person stretching in bed morning", "cozy bedroom night", "woman relaxing bedroom"]}
FW, FH = 1838, 2775  # front cover at 300 dpi (6.125 x 9.25 in incl. bleed)


def get_photo(b):
    """real photo from Pexels (free, commercial use ok). returns (front, dimmed back) PIL images or (None, None)"""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        print("  !!! NO PHOTO: PEXELS_API_KEY missing. Copy keys.bat into this folder, then delete kdp_out and kdp_state.json and run again.")
        return None, None
    try:
        import io, requests
        from PIL import Image, ImageFilter
        qs = QUERIES[b[0]]
        q = qs[sum(map(ord, b[1])) % len(qs)]
        used_f = Path("kdp_photos_used.txt")
        used = set(used_f.read_text().split()) if used_f.exists() else set()
        r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key},
                         params={"query": q, "orientation": "portrait", "per_page": 30}, timeout=60)
        r.raise_for_status()
        ph = [p for p in r.json().get("photos", []) if p["width"] >= 1600 and p["height"] >= 2400 and str(p["id"]) not in used]
        if not ph:
            return None, None
        pick = random.Random(sum(map(ord, b[1]))).choice(ph[:8])
        url = pick["src"]["original"] + f"?auto=compress&cs=tinysrgb&fit=crop&w={FW}&h={FH}"
        img = Image.open(io.BytesIO(requests.get(url, timeout=120).content)).convert("RGB").resize((FW, FH))
        used_f.write_text("\n".join(list(used) + [str(pick["id"])]))
        print("  photo OK:", q)
        back = Image.blend(img.filter(ImageFilter.GaussianBlur(8)), Image.new("RGB", img.size, (0, 0, 0)), 0.55)
        return img, back
    except Exception as e:
        print("  !!! PHOTO FAILED, plain cover:", str(e)[:90])
        return None, None


def wrap(c, text, font, size, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if c.stringWidth(t, font, size) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def hdr(c, text, th, w, h):
    c.setFillColor(HexColor(th[0])); c.setFont("Helvetica-Bold", 13); c.drawString(M, h - M + 4, text)
    c.setStrokeColor(HexColor(th[1])); c.setLineWidth(1.5); c.line(M, h - M - 4, w - M, h - M - 4)


def lines(c, x, y, wd, n, gap=0.3 * inch, col="#BBBBBB"):
    c.setStrokeColor(HexColor(col)); c.setLineWidth(0.5)
    for i in range(n):
        c.line(x, y - i * gap, x + wd, y - i * gap)
    return y - n * gap


def table(c, x, y, cols, rows, rh, head, th):
    tw = sum(cols)
    c.setFillColor(HexColor(th[2])); c.rect(x, y - rh, tw, rh, fill=1, stroke=0)
    c.setFillColor(HexColor(th[0])); c.setFont("Helvetica-Bold", 8)
    cx = x
    for wd, t in zip(cols, head):
        c.drawString(cx + 3, y - rh + 5, t); cx += wd
    c.setStrokeColor(HexColor("#999999")); c.setLineWidth(0.5)
    for r in range(rows + 1):
        c.line(x, y - rh * (r + 1), x + tw, y - rh * (r + 1))
    cx = x
    for wd in cols + [0]:
        c.line(cx, y, cx, y - rh * (rows + 1)); cx += wd
    return y - rh * (rows + 1)


def page(c, kind, b, th, i, w, h):
    title, pr = b[1], b[4]
    iw = w - 2 * M
    c.setFillColor(HexColor("#222222"))
    if kind == "gratitude":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Date: ______________________")
        y = h - M - 50
        for p in pr:
            c.setFont("Helvetica-Bold", 10); c.setFillColor(HexColor(th[1])); c.drawString(M, y, p)
            y = lines(c, M, y - 22, iw, 4) - 14
    elif kind == "habit":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Week of: ______________")
        y = table(c, M, h - M - 36, [iw - 7 * 0.4 * inch] + [0.4 * inch] * 7, 12, 0.3 * inch, ["Habit", "M", "T", "W", "T", "F", "S", "S"], th) - 22
        for p in pr:
            c.setFont("Helvetica-Bold", 9); c.setFillColor(HexColor(th[1])); c.drawString(M, y, p + ":")
            y = lines(c, M, y - 16, iw, 2, 0.26 * inch) - 8
    elif kind == "budget":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Month: ______________")
        y = table(c, M, h - M - 34, [iw * .55, iw * .225, iw * .225], 4, 0.26 * inch, ["Income source", "Expected", "Actual"], th) - 14
        y = table(c, M, y, [iw * .4, iw * .2, iw * .25, iw * .15], 10, 0.26 * inch, ["Bill / expense", "Due", "Amount", "Paid"], th) - 14
        c.setFont("Helvetica-Bold", 9); c.setFillColor(HexColor(th[1])); c.drawString(M, y, "Savings goal / notes")
        lines(c, M, y - 18, iw, 3, 0.26 * inch)
    elif kind == "meal":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Week of: ______________")
        y = table(c, M, h - M - 34, [iw * .16] + [iw * .28] * 3, 7, 0.46 * inch, ["Day", "Breakfast", "Lunch", "Dinner"], th) - 8
        for d, yy in zip("MTWTFSS", range(7)):
            c.setFillColor(HexColor(th[0])); c.setFont("Helvetica-Bold", 9)
            c.drawString(M + 4, h - M - 34 - 0.26 * inch * 0 - 0.46 * inch * (yy + 1) - 0.46 * inch / 2 + 6, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][yy])
        c.setFont("Helvetica-Bold", 9); c.setFillColor(HexColor(th[1])); c.drawString(M, y - 12, "Grocery list")
        lines(c, M, y - 30, iw, 4, 0.24 * inch)
    elif kind == "workout":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Date: ____________   Focus: ____________________")
        table(c, M, h - M - 36, [iw * .32] + [iw * .12] * 4 + [iw * .2], 14, 0.4 * inch, ["Exercise", "Set 1", "Set 2", "Set 3", "Set 4", "Notes"], th)
    elif kind == "reading":
        hdr(c, title, th, w, h)
        y = h - M - 30
        for _ in range(4):
            c.setFont("Helvetica", 9); c.setFillColor(HexColor("#222222"))
            c.drawString(M, y, "Title: " + "_" * 44); c.drawString(M, y - 16, "Author: " + "_" * 30)
            c.drawString(M, y - 32, "Started: ________   Finished: ________   Rating:  \u2606 \u2606 \u2606 \u2606 \u2606".replace("\u2606", "*"))
            y = lines(c, M, y - 52, iw, 2, 0.24 * inch) - 22
    elif kind == "sleep":
        hdr(c, title, th, w, h); c.setFont("Helvetica", 9); c.drawString(M, h - M - 22, "Week of: ______________")
        y = table(c, M, h - M - 36, [iw * .16, iw * .17, iw * .17, iw * .14, iw * .16, iw * .2], 7, 0.5 * inch, ["Day", "Bedtime", "Wake up", "Hours", "Quality 1-5", "Mood"], th) - 18
        c.setFont("Helvetica-Bold", 9); c.setFillColor(HexColor(th[1])); c.drawString(M, y, "What helped or hurt my sleep this week")
        lines(c, M, y - 20, iw, 5, 0.26 * inch)
    c.setFillColor(HexColor("#888888")); c.setFont("Helvetica", 8); c.drawCentredString(w / 2, M / 2, str(i))


def interior(path, b, pages):
    th = [HexColor(x) and x for x in THEMES[b[3]]]
    c = canvas.Canvas(str(path), pagesize=(W6, H9))
    c.setFillColor(HexColor(th[0])); c.setFont("Helvetica-Bold", 22)
    for j, ln in enumerate(wrap(c, b[1], "Helvetica-Bold", 22, W6 - 2 * M)):
        c.drawCentredString(W6 / 2, H9 * .62 - j * 30, ln)
    c.setFont("Helvetica", 11); c.setFillColor(HexColor("#444444")); c.drawCentredString(W6 / 2, H9 * .45, "This book belongs to: ______________________")
    c.showPage()
    c.showPage()  # blank back of title page
    for i in range(1, pages - 1):
        page(c, b[0], b, th, i, W6, H9); c.showPage()
    c.save()


def cover(path, b, pages):
    th = [HexColor(x) for x in THEMES[b[3]]]
    spine, bleed = pages * 0.002252 * inch, 0.125 * inch
    CW, CH = 2 * W6 + spine + 2 * bleed, H9 + 2 * bleed
    c = canvas.Canvas(str(path), pagesize=(CW, CH))
    c.setFillColor(th[0]); c.rect(0, 0, CW, CH, fill=1, stroke=0)
    fx = bleed + W6 + spine  # front panel x
    photo, back = get_photo(b)
    if photo:
        c.drawImage(ImageReader(photo), fx, 0, W6 + bleed, CH)
        c.drawImage(ImageReader(back), 0, 0, bleed + W6, CH)
    else:
        c.setFillColor(th[1]); c.setFillAlpha(0.35); c.circle(fx + W6 * .8, CH * .85, W6 * .45, fill=1, stroke=0); c.circle(fx + W6 * .1, CH * .15, W6 * .35, fill=1, stroke=0)
        c.setFillAlpha(1)
    # title panel on front
    size = 36
    while size > 20 and len(wrap(c, b[1], "Helvetica-Bold", size, W6 - 1.6 * inch)) > 3:
        size -= 3
    tl = wrap(c, b[1], "Helvetica-Bold", size, W6 - 1.6 * inch)
    sl = wrap(c, b[2], "Times-Italic", 15, W6 - 1.6 * inch)
    ph = len(tl) * size * 1.18 + len(sl) * 20 + 62
    px, pw, top = fx + 0.45 * inch, W6 - 0.9 * inch, CH * 0.80
    c.setFillColor(white); c.setFillAlpha(0.92 if photo else 1); c.roundRect(px, top - ph, pw, ph, 10, fill=1, stroke=0); c.setFillAlpha(1)
    c.setStrokeColor(th[2]); c.setLineWidth(2); c.roundRect(px + 6, top - ph + 6, pw - 12, ph - 12, 7, fill=0, stroke=1)
    cx, y = px + pw / 2, top - 26 - size * 0.8
    c.setFillColor(th[0]); c.setFont("Helvetica-Bold", size)
    for ln in tl:
        c.drawCentredString(cx, y, ln); y -= size * 1.18
    c.setStrokeColor(th[2]); c.setLineWidth(2.5); c.line(cx - 0.45 * inch, y + size * 0.55, cx + 0.45 * inch, y + size * 0.55)
    y -= 12
    c.setFillColor(th[1]); c.setFont("Times-Italic", 15)
    for ln in sl:
        c.drawCentredString(cx, y, ln); y -= 20
    c.setFillColor(th[0]); c.roundRect(fx + W6 / 2 - 1.05 * inch, bleed + 0.55 * inch, 2.1 * inch, 0.4 * inch, 10, fill=1, stroke=0)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 11); c.drawCentredString(fx + W6 / 2, bleed + 0.68 * inch, b[0].upper() + " BOOK")
    # spine
    c.setFillColor(th[0]); c.rect(bleed + W6, 0, spine, CH, fill=1, stroke=0)
    if pages >= 79:  # spine text only allowed from 79 pages
        c.saveState(); c.translate(bleed + W6 + spine / 2, CH / 2); c.rotate(-90); c.setFillColor(white); c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(0, -4, b[1][:45]); c.restoreState()
    # back
    c.setFillColor(white); c.setFont("Helvetica-Bold", 15)
    ty = CH * .74
    for ln in wrap(c, b[1], "Helvetica-Bold", 15, W6 - inch):
        c.drawCentredString(bleed + W6 / 2, ty, ln); ty -= 21
    c.setFillColor(th[2]); c.setFont("Helvetica", 11)
    for ln in wrap(c, DESC[b[0]], "Helvetica", 11, W6 - 1.2 * inch):
        ty -= 8; c.drawCentredString(bleed + W6 / 2, ty, ln); ty -= 8
    c.setFillColor(white); c.rect(bleed + W6 - 0.25 * inch - 2 * inch, bleed + 0.25 * inch, 2 * inch, 1.2 * inch, fill=1, stroke=0)  # barcode space
    c.save()
    try:
        import fitz
        pg = fitz.open(str(path))[0]
        pg.get_pixmap(dpi=110, clip=fitz.Rect(fx, 0, fx + W6 + bleed, CH)).save(str(path.with_name("cover_front.png")))
    except Exception as e:
        print("  (front cover png skipped:", str(e)[:60], ")")


def listing(path, b, pages):
    k = KEYS[b[0]]
    path.write_text(f"""TITLE: {b[1]}
SUBTITLE: {b[2]}
AUTHOR: (your name or a pen name)
LANGUAGE: English
TRIM SIZE: 6 x 9 in | INTERIOR: black and white, white paper | PAGES: {pages} | COVER: matte
DESCRIPTION:
{b[1]}: {b[2]}.
{DESC[b[0]]}
- Easy 6 x 9 inch size, fits a bag or desk
- {pages} pages with a clean, simple layout
- Make it part of your daily or weekly routine
KEYWORDS (7 boxes):
{chr(10).join('- ' + x for x in k)}
CATEGORIES: choose 2 that fit (search for: planners, journals, {b[0]}).
PRICE: you set it. Royalty is 60% of the list price minus printing cost. Use KDP's price calculator.
AI DISCLOSURE: when KDP asks "AI-generated content", answer honestly. Layout and page text here were produced with AI assistance, so choose YES.
UPLOAD: kdp.amazon.com > Create > Paperback > fill the info above > upload interior.pdf and cover.pdf (Upload a cover you created) > Preview > Publish.
""", encoding="utf-8")


def cmd_make(a):
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    todo = [b for b in BOOKS if slug(b[1]) not in st][:min(a.count, 3)]
    if not todo:
        print("all books in the bank are made. ask Claude for more themes."); return
    for b in todo:
        d = OUT / slug(b[1]); d.mkdir(parents=True, exist_ok=True)
        pages = a.pages
        interior(d / "interior.pdf", b, pages); cover(d / "cover.pdf", b, pages); listing(d / "listing.txt", b, pages)
        st[slug(b[1])] = {"title": b[1], "subtitle": b[2], "kind": b[0], "pages": pages}
        print("made:", d)
    STATE.write_text(json.dumps(st, indent=1))
    print("Upload each folder to KDP (see listing.txt). Max 3 new titles per day on KDP. After publishing, put the book link in kdp_links.txt and run:  python kdp_agent.py link")


def cmd_link(a):
    from add_products import COLS, find_tag, make_row, read_rows, product_link
    import yaml
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    rows = read_rows(); tag = find_tag(rows, cfg); have = {r["name"].lower() for r in rows}; new = []
    for ln in open(a.links, encoding="utf-8").read().splitlines():
        if ln.startswith("#") or "|" not in ln:
            continue
        s, _, url = [x.strip() for x in ln.partition("|")]
        if s not in st:
            print("unknown book id:", s); continue
        link = product_link(url, tag)
        if not link:
            print("bad link:", s); continue
        r = make_row("planners", st[s]["title"], tag, link)
        r["name"], r["description"] = st[s]["title"], st[s]["subtitle"]
        r["keywords"] = ";".join(KEYS[st[s]["kind"]][:2] + ["planners"])
        r["image_url"] = str(OUT / s / "cover_front.png")
        if r["name"].lower() not in have:
            new.append(r); have.add(r["name"].lower())
    if new:
        shutil.copy("products.csv", "products.csv.bak")
        with open("products.csv", "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            for r in new:
                w.writerow(r)
        open(a.links, "w", encoding="utf-8").write("# book-id | amazon link\n")
        print("added to pins:", ", ".join(r["name"] for r in new), "| now run auto.bat")
    else:
        print("nothing new")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "link"])
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--pages", type=int, default=110)
    ap.add_argument("--links", default="kdp_links.txt")
    a = ap.parse_args()
    {"make": cmd_make, "link": cmd_link}[a.cmd](a)
