"""Podcast Afterparty - reusable episode artwork template (Pillow).

Builds an episode cover (3000x3000 RGB JPEG) and a YouTube thumbnail (1280x720 JPEG)
from a JSON brand config. The design is fixed; everything brand- or episode-specific
lives in the config. Background is procedural and abstract (dark base + glow + halftone
dots). No people are generated: the photo must come from the client's OWN images.

Usage:
  python3 artwork_template.py brand.json [OUTDIR]
  python3 artwork_template.py --example > brand.json     # print an example config

Config keys (colours are "#RRGGBB"; paths are relative to the config file):
  show_name        e.g. "MY SHOW" (use | to split onto two lines, second line in accent)
  title            episode title (use | to force line breaks)
  guest            guest name label (optional, "" to hide)
  colours          {background, title_box, title_text, glow, accent, label_text}
  fonts            {title, label}  .ttf paths (heavy condensed caps work best for title)
  logo             square logo / channel avatar (optional)
  photo            {src, box: [x0,y0,x1,y1]} crop of the client's own image
  out_cover, out_thumb   output file names
"""
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
import json, math, os, random, sys

EXAMPLE = {
    "show_name": "MY PODCAST|SHOW",
    "title": "YOUR EPISODE|TITLE|HERE",
    "guest": "GUEST NAME",
    "colours": {"background": "#121213", "title_box": "#FDC905", "title_text": "#121213",
                "glow": "#FE8306", "accent": "#FFB601", "label_text": "#FFFFFF"},
    "fonts": {"title": "fonts/Anton-Regular.ttf", "label": "fonts/Poppins-SemiBold.ttf"},
    "logo": "Reference/logo.png",
    "photo": {"src": "Reference/guest-photo.jpg", "box": [0, 0, 1280, 720]},
    "out_cover": "Episode - cover 3000x3000.jpg",
    "out_thumb": "Episode - YouTube thumbnail 1280x720.jpg",
}


def rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def load(path):
    cfg = json.load(open(path, encoding="utf-8"))
    base = os.path.dirname(os.path.abspath(path))
    rel = lambda p: p if not p or os.path.isabs(p) else os.path.join(base, p)
    c = {k: rgb(v) for k, v in {**EXAMPLE["colours"], **cfg.get("colours", {})}.items()}
    f = {**EXAMPLE["fonts"], **cfg.get("fonts", {})}
    return {
        "show_name": cfg.get("show_name", ""), "title": cfg["title"], "guest": cfg.get("guest", ""),
        "c": c, "title_font": rel(f["title"]), "label_font": rel(f["label"]),
        "logo": rel(cfg.get("logo") or ""),
        "photo_src": rel(cfg["photo"]["src"]), "photo_box": tuple(cfg["photo"]["box"]),
        "out_cover": cfg.get("out_cover", EXAMPLE["out_cover"]), "out_thumb": cfg.get("out_thumb", EXAMPLE["out_thumb"]),
    }


def background(w, h, c, seed=7):
    random.seed(seed)
    base = Image.new("RGB", (w, h), c["background"])
    glow = Image.new("L", (w, h), 0)
    g = ImageDraw.Draw(glow)
    r = int(max(w, h) * 0.55)
    for cx, cy, a in [(w * 0.92, h * 0.08, 120), (w * 0.05, h * 0.98, 80)]:
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=a)
    glow = glow.filter(ImageFilter.GaussianBlur(max(w, h) * 0.18))
    base = Image.composite(Image.new("RGB", (w, h), c["glow"]), base, glow.point(lambda v: int(v * 0.45)))
    dots = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(dots)
    step = max(12, int(min(w, h) / 45))
    diag = math.hypot(w, h)
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            ox = x + (step // 2 if (y // step) % 2 else 0)
            t = max(1 - math.hypot(w - ox, y) / (diag * 0.42), 1 - math.hypot(ox, h - y) / (diag * 0.35), 0)
            rad = step * 0.42 * t
            if rad > 0.6:
                d.ellipse([ox - rad, y - rad, ox + rad, y + rad], fill=70)
    base = Image.composite(Image.new("RGB", (w, h), c["glow"]), base, dots)
    noise = Image.effect_noise((w, h), 10).convert("RGB")
    return Image.blend(base, ImageChops.multiply(base, noise.point(lambda v: 200 + v // 5)), 0.15)


def fit_lines(draw, text, font_path, box_w, box_h, max_lines=4, leading=1.02):
    forced = [l.strip() for l in text.split("|")] if "|" in text else None
    for size in range(int(box_h), 10, -4):
        f = ImageFont.truetype(font_path, size)
        if forced:
            lines = forced
        else:
            lines, cur = [], ""
            for wd in text.split():
                test = (cur + " " + wd).strip()
                if draw.textlength(test, font=f) <= box_w or not cur:
                    cur = test
                else:
                    lines.append(cur); cur = wd
            lines.append(cur)
        lh = int(size * leading)
        if len(lines) <= max_lines and lh * len(lines) <= box_h and all(draw.textlength(l, font=f) <= box_w for l in lines):
            return f, lines, lh
    raise ValueError("Title does not fit the box - shorten it")


def title_box(img, rect, ep, pad_frac=0.07):
    x0, y0, x1, y1 = rect
    dr = ImageDraw.Draw(img)
    dr.rectangle(rect, fill=ep["c"]["title_box"])
    pad = int((x1 - x0) * pad_frac)
    f, lines, lh = fit_lines(dr, ep["title"].upper(), ep["title_font"], x1 - x0 - 2 * pad, y1 - y0 - 2 * pad)
    y = y0 + (y1 - y0 - lh * len(lines)) // 2
    for l in lines:
        bb = dr.textbbox((0, 0), l, font=f)
        dr.text((x0 + pad - bb[0], y - int(f.size * 0.08)), l, font=f, fill=ep["c"]["title_text"])
        y += lh


def photo_layer(src, box, target_h, top_fade=False):
    face = Image.open(src).convert("RGB").crop(box)
    s = target_h / face.height
    face = face.resize((round(face.width * s), target_h), Image.LANCZOS)
    mask = Image.new("L", face.size, 255)
    md = ImageDraw.Draw(mask)
    fade = int(face.width * 0.28)
    for x in range(fade):
        md.line([(x, 0), (x, face.height)], fill=int(255 * (x / fade) ** 1.6))
    if top_fade:
        tf = int(face.height * 0.15)
        top = Image.new("L", face.size, 255)
        td = ImageDraw.Draw(top)
        for y in range(tf):
            td.line([(0, y), (face.width, y)], fill=int(255 * (y / tf) ** 1.4))
        mask = ImageChops.multiply(mask, top)
    return face, mask, s


def build(ep, outdir="."):
    os.makedirs(outdir, exist_ok=True)
    c = ep["c"]
    # YouTube thumbnail 1280x720
    W, H = 1280, 720
    th = background(W, H, c)
    face, mask, _ = photo_layer(ep["photo_src"], ep["photo_box"], H)
    th.paste(face, (W - face.width, 0), mask)
    title_box(th, (40, 70, 600, 650), ep)
    th.save(os.path.join(outdir, ep["out_thumb"]), "JPEG", quality=92, subsampling=0)
    # Podcast cover 3000x3000
    C, m = 3000, 150  # 5% safe margin
    cv = background(C, C, c, seed=11)
    face, mask, s = photo_layer(ep["photo_src"], ep["photo_box"], 2000, top_fade=True)
    cv.paste(face, (C - face.width, C - face.height), mask)
    tx = m
    if ep["logo"] and os.path.exists(ep["logo"]):
        logo = Image.open(ep["logo"]).convert("RGBA").resize((560, 560), Image.LANCZOS)
        cmask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(cmask).ellipse([4, 4, 556, 556], fill=255)
        cv.paste(logo, (m, m), ImageChops.multiply(cmask, logo.getchannel("A")))
        tx = m + 620
    dr = ImageDraw.Draw(cv)
    if ep["show_name"]:
        parts = [p.strip() for p in ep["show_name"].upper().split("|")][:2]
        size = 190
        while size > 60:
            lf = ImageFont.truetype(ep["title_font"], size)
            if all(dr.textlength(p, font=lf) <= C - m - tx for p in parts): break
            size -= 10
        for i, p in enumerate(parts):
            dr.text((tx, m + 70 + i * int(size * 1.15)), p, font=lf, fill=c["label_text"] if i == 0 else c["accent"])
    title_box(cv, (m, 1000, 1350, 2400), ep)
    if ep["guest"]:
        gf = ImageFont.truetype(ep["label_font"], 120)
        gw = dr.textlength(ep["guest"], font=gf)
        dr.rectangle([m, 2450, m + gw + 120, 2650], fill=c["background"])
        dr.text((m + 60, 2470), ep["guest"], font=gf, fill=c["label_text"])
    cv.convert("RGB").save(os.path.join(outdir, ep["out_cover"]), "JPEG", quality=92, subsampling=0)
    return s  # cover photo upscale factor (>2 means it may look soft)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__); sys.exit(0)
    if sys.argv[1] == "--example":
        print(json.dumps(EXAMPLE, indent=2)); sys.exit(0)
    out = sys.argv[2] if len(sys.argv) > 2 else "."
    print("cover photo upscale x%.2f" % build(load(sys.argv[1]), out))
