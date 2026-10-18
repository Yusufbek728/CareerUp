"""CareerUp ad: 1080x1920, 30fps, 16s. Frames via Pillow, audio via numpy, mux via ffmpeg.

python ad/make_ad.py uz frames 1.5 4.5 8 12 15   -> PNG previews into ad/preview/
python ad/make_ad.py uz render                   -> ad/careerup_ad_uz.mp4   (languages: ru, en, uz)
"""
import math
import subprocess
import sys
import wave
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
LOGO = ROOT.parent / "static" / "mainapp" / "logo.png"

W, H, FPS, DUR = 1080, 1920, 30, 16.0
BG_TOP, BG_BOT = (10, 22, 42), (5, 11, 22)
PRIMARY, ACCENT = (118, 169, 255), (132, 242, 212)
TEXT, MUTED, DARK = (237, 244, 255), (168, 183, 207), (7, 17, 31)


TX = {
    "ru": dict(
        hook=("Устал искать", "работу вслепую?"), tags=("Вакансии", "Стажировки", "Резюме"), why="Почему CareerUp",
        features=(("Быстрый подбор", "Находите возможности по", "вашим навыкам и целям."),
                  ("Умные фильтры", "Лучшие вакансии по опыту,", "формату работы и зарплате."),
                  ("Надёжная сеть", "Надёжные работодатели и", "кандидаты на одной платформе.")),
        jobs_h=("Найди своё.", "Прямо сейчас."),
        chips=((("Полный день", False), ("Удалённо", False)), (("Гибкий график", False), ("Офис", False)),
               (("Стажировка", True), ("12 недель", False))),
        badge="Новые каждый день", cta=("Найди свой", "следующий шаг."), button="Найти вакансии  →"),
    "en": dict(
        hook=("Tired of searching", "for a job blindly?"), tags=("Jobs", "Internships", "Resumes"), why="Why CareerUp",
        features=(("Fast matching", "Find opportunities that match", "your skills and goals."),
                  ("Smart filters", "The best jobs by experience,", "work model and salary."),
                  ("Trusted network", "Trusted employers and", "candidates on one platform.")),
        jobs_h=("Find yours.", "Right now."),
        chips=((("Full time", False), ("Remote", False)), (("Flexible hours", False), ("Office", False)),
               (("Internship", True), ("12 weeks", False))),
        badge="New every day", cta=("Find your", "next step."), button="Find jobs  →"),
    "uz": dict(
        hook=("Ish qidirib", "charchadingizmi?"), tags=("Ishlar", "Amaliyotlar", "Rezyumelar"), why="Nega CareerUp",
        features=(("Tez moslashtirish", "Ko'nikma va maqsadlaringizga", "mos imkoniyatlarni toping."),
                  ("Aqlli filtrlar", "Tajriba, ish turi va maosh", "bo'yicha eng yaxshi ishlar."),
                  ("Ishonchli tarmoq", "Ishonchli ish beruvchilar va", "nomzodlar bir platformada.")),
        jobs_h=("O'zingnikini toping.", "Hoziroq."),
        chips=((("To'liq vaqt", False), ("Masofaviy ish", False)), (("Moslashuvchan jadval", False), ("Ofis", False)),
               (("Amaliyot", True), ("12 hafta", False))),
        badge="Har kuni yangi", cta=("Keyingi qadamingizni", "toping."), button="Ishlarni topish  →"),
}
L = TX["ru"]


# ---------- helpers ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ph(t, a, b):
    return clamp((t - a) / (b - a))


def out_cubic(x):
    return 1 - (1 - x) ** 3


def out_back(x, s=1.9):
    x -= 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


@lru_cache(maxsize=None)
def font(size, weight="b"):
    name = {"b": "segoeuib.ttf", "k": "seguibl.ttf", "r": "segoeui.ttf"}[weight]
    return ImageFont.truetype(f"C:/Windows/Fonts/{name}", size)


@lru_cache(maxsize=None)
def text_img(text, size, color, weight="b"):
    f = font(size, weight)
    l, t, r, b = f.getbbox(text)
    while r - l > 960 and size > 20:  # keep inside safe margins for longer translations
        size -= 4
        f = font(size, weight)
        l, t, r, b = f.getbbox(text)
    pad = 12
    img = Image.new("RGBA", (r - l + pad * 2, b - t + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=f, fill=color + (255,))
    return img


def put(base, img, cx, cy, a=1.0, s=1.0, dx=0, dy=0):
    if a <= 0.01:
        return
    if s != 1.0:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    if a < 0.999:
        alpha = img.getchannel("A").point(lambda v: int(v * a))
        img = img.copy()
        img.putalpha(alpha)
    base.paste(img, (int(cx - img.width / 2 + dx), int(cy - img.height / 2 + dy)), img)


@lru_cache(maxsize=None)
def glow(color, size, strength):
    y, x = np.mgrid[0:size, 0:size]
    r = np.hypot(x - size / 2, y - size / 2) / (size / 2)
    a = (np.clip(1 - r, 0, 1) ** 2.2 * 255 * strength).astype(np.uint8)
    arr = np.zeros((size, size, 4), np.uint8)
    arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3] = color[0], color[1], color[2], a
    return Image.fromarray(arr, "RGBA")


@lru_cache(maxsize=None)
def background():
    g = np.zeros((H, W, 3), np.uint8)
    k = np.linspace(0, 1, H)[:, None]
    for i in range(3):
        g[..., i] = (BG_TOP[i] * (1 - k) + BG_BOT[i] * k).astype(np.uint8)
    return Image.fromarray(g, "RGB").convert("RGBA")


@lru_cache(maxsize=None)
def logo(height):
    im = Image.open(LOGO).convert("RGB")
    arr = np.asarray(im).astype(np.float32)
    alpha = np.clip((arr.max(axis=2) - 12) * 2.0, 0, 255).astype(np.uint8)
    rgba = Image.fromarray(np.dstack([arr.astype(np.uint8), alpha]), "RGBA")
    rgba = rgba.crop(rgba.getchannel("A").point(lambda v: 255 if v > 25 else 0).getbbox())
    return rgba.resize((int(rgba.width * height / rgba.height), height), Image.LANCZOS)


def rrect(w, h, r, fill, outline=None, width=2):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=fill, outline=outline, width=width)
    return img


def draw_bg(t):
    base = background().copy()
    a = glow(PRIMARY, 1300, 0.55)
    b = glow(ACCENT, 1100, 0.35)
    base.paste(a, (int(-250 + 140 * math.sin(t * 0.5)), int(-150 + 100 * math.cos(t * 0.4))), a)
    base.paste(b, (int(330 - 120 * math.cos(t * 0.45)), int(1000 + 110 * math.sin(t * 0.35))), b)
    return base


def fade(t, a, b, c, d):
    """0 -> 1 on [a,b], hold, 1 -> 0 on [c,d]"""
    return ph(t, a, b) * (1 - ph(t, c, d))


# ---------- scenes ----------
def scene_hook(base, t):
    g = fade(t, 0.0, 0.25, 2.65, 3.1)
    if g <= 0:
        return
    for i, (txt, col, y) in enumerate(((L["hook"][0], TEXT, 790), (L["hook"][1], PRIMARY, 940))):
        p = out_cubic(ph(t, 0.15 + i * 0.35, 0.75 + i * 0.35))
        put(base, text_img(txt, 104, col, "k"), W / 2, y, a=p * g, dy=(1 - p) * 70)
    bar = out_cubic(ph(t, 1.0, 1.6))
    bw = int(520 * bar)
    if bw > 2:
        put(base, rrect(bw, 14, 7, ACCENT + (255,)), W / 2, 1060, a=g)


def scene_logo(base, t):
    g = fade(t, 2.9, 3.2, 5.8, 6.2)
    if g <= 0:
        return
    s = out_back(ph(t, 3.0, 3.7))
    # pulse ring
    rp = ph(t, 3.2, 4.4)
    if 0 < rp < 1:
        d = int(380 + 600 * out_cubic(rp))
        ring = Image.new("RGBA", (d, d), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((2, 2, d - 3, d - 3), outline=PRIMARY + (255,), width=5)
        put(base, ring, W / 2, 760, a=(1 - rp) * 0.7 * g)
    put(base, glow(PRIMARY, 900, 0.5), W / 2, 760, a=g * ph(t, 3.0, 3.6))
    put(base, logo(430), W / 2, 760, a=g, s=max(s, 0.01))
    p = out_cubic(ph(t, 3.7, 4.3))
    put(base, text_img("CareerUp", 170, TEXT, "k"), W / 2, 1110, a=p * g, dy=(1 - p) * 50)
    for i, (w, x) in enumerate(zip(L["tags"], (-355, 0, 340))):
        p = out_cubic(ph(t, 4.3 + i * 0.2, 4.8 + i * 0.2))
        put(base, text_img(w, 56, ACCENT if i == 1 else MUTED, "b"), W / 2, 1255, a=p * g, dx=x, dy=(1 - p) * 30)


def icon(kind):
    img = Image.new("RGBA", (130, 130), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, 129, 129), fill=PRIMARY + (46,), outline=PRIMARY + (140,), width=3)
    c = ACCENT + (255,)
    if kind == 0:  # bolt
        d.polygon([(72, 24), (38, 74), (62, 74), (54, 106), (92, 54), (68, 54)], fill=c)
    elif kind == 1:  # target
        for r, w in ((36, 6), (22, 6)):
            d.ellipse((65 - r, 65 - r, 65 + r, 65 + r), outline=c, width=w)
        d.ellipse((57, 57, 73, 73), fill=c)
    else:  # two linked people
        for cx in (50, 80):
            d.ellipse((cx - 13, 38, cx + 13, 64), fill=c)
            d.pieslice((cx - 24, 70, cx + 24, 118), 180, 360, fill=c)
    return img


@lru_cache(maxsize=None)
def feature_card(i, title, l1, l2):
    card = rrect(920, 290, 44, (255, 255, 255, 16), (255, 255, 255, 46), 2)
    card.paste(icon(i), (46, 80), icon(i))
    for img, y in ((text_img(title, 68, TEXT, "k"), 55), (text_img(l1, 38, MUTED, "r"), 150), (text_img(l2, 38, MUTED, "r"), 200)):
        card.paste(img, (210 - 12, y - 12), img)
    return card


def scene_features(base, t):
    g = fade(t, 5.9, 6.3, 10.0, 10.5)
    if g <= 0:
        return
    p = out_cubic(ph(t, 6.0, 6.6))
    put(base, text_img(L["why"], 84, ACCENT, "k"), W / 2, 400, a=p * g, dy=(1 - p) * 40)
    for i, f in enumerate(L["features"]):
        p = out_cubic(ph(t, 6.5 + i * 0.7, 7.2 + i * 0.7))
        put(base, feature_card(i, *f), W / 2, 700 + i * 350, a=p * g, dx=(1 - p) * (-260 if i % 2 == 0 else 260))


@lru_cache(maxsize=None)
def chip(text, hot):
    f = font(34, "b")
    w = int(f.getlength(text)) + 50
    col = ACCENT if hot else PRIMARY
    img = rrect(w, 60, 30, col + (40,), col + (170,), 2)
    ImageDraw.Draw(img).text((25, 8), text, font=f, fill=col + (255,))
    return img


@lru_cache(maxsize=None)
def job_card(letter, title, chips):
    card = rrect(920, 240, 40, (255, 255, 255, 18), (255, 255, 255, 50), 2)
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((40, 50, 180, 190), 34, fill=PRIMARY + (255,))
    lt = text_img(letter, 88, DARK, "k")
    card.paste(lt, (110 - lt.width // 2, 120 - lt.height // 2), lt)
    tt = text_img(title, 56, TEXT, "k")
    card.paste(tt, (214 - 12, 50 - 12), tt)
    x = 214
    for label, hot in chips:
        c = chip(label, hot)
        card.paste(c, (x, 140), c)
        x += c.width + 16
    return card


JOB_TITLES = (("F", "Frontend Developer"), ("M", "Marketing Manager"), ("Q", "QA Testing Intern"))


@lru_cache(maxsize=None)
def new_badge():
    label = text_img(L["badge"], 38, DARK, "b")
    badge = rrect(label.width + 70, 80, 40, ACCENT + (255,))
    badge.paste(label, ((badge.width - label.width) // 2, (80 - label.height) // 2), label)
    return badge


def scene_jobs(base, t):
    g = fade(t, 10.3, 10.7, 13.1, 13.6)
    if g <= 0:
        return
    for i, txt in enumerate(L["jobs_h"]):
        p = out_cubic(ph(t, 10.4 + i * 0.25, 11.0 + i * 0.25))
        put(base, text_img(txt, 104, TEXT if i == 0 else ACCENT, "k"), W / 2, 430 + i * 130, a=p * g, dy=(1 - p) * 50)
    for i, ((letter, title), chips) in enumerate(zip(JOB_TITLES, L["chips"])):
        p = out_cubic(ph(t, 11.0 + i * 0.4, 11.7 + i * 0.4))
        put(base, job_card(letter, title, chips), W / 2, 880 + i * 290, a=p * g, dy=(1 - p) * 140)
    pulse = 1 + 0.04 * math.sin((t - 12.0) * 7)
    if t > 12.0:
        put(base, new_badge(), W / 2, 1660, a=g * ph(t, 12.0, 12.4), s=pulse)


def scene_cta(base, t):
    g = fade(t, 13.3, 13.7, 15.6, 16.0)
    if g <= 0:
        return
    s = out_back(ph(t, 13.4, 14.0))
    put(base, glow(PRIMARY, 900, 0.45), W / 2, 560, a=g)
    put(base, logo(300), W / 2, 560, a=g, s=max(s, 0.01))
    for i, (txt, col) in enumerate(((L["cta"][0], TEXT), (L["cta"][1], PRIMARY))):
        p = out_cubic(ph(t, 13.9 + i * 0.25, 14.5 + i * 0.25))
        put(base, text_img(txt, 108, col, "k"), W / 2, 880 + i * 130, a=p * g, dy=(1 - p) * 50)
    p = out_back(ph(t, 14.6, 15.2))
    pulse = 1 + 0.035 * math.sin((t - 15.0) * 6) if t > 15.0 else 1
    btn = rrect(760, 150, 75, ACCENT + (255,))
    lab = text_img(L["button"], 58, DARK, "k")
    btn.paste(lab, (380 - lab.width // 2, 75 - lab.height // 2), lab)
    put(base, glow(ACCENT, 1000, 0.35), W / 2, 1290, a=g * ph(t, 14.6, 15.2))
    put(base, btn, W / 2, 1290, a=g, s=max(p, 0.01) * pulse)
    put(base, text_img("CareerUp", 66, MUTED, "b"), W / 2, 1520, a=g * ph(t, 15.0, 15.4))


def frame(t):
    base = draw_bg(t)
    for sc in (scene_hook, scene_logo, scene_features, scene_jobs, scene_cta):
        sc(base, t)
    return base.convert("RGB")


# ---------- audio ----------
def make_audio(path, sr=44100):
    n = int(DUR * sr)
    t = np.arange(n) / sr
    out = np.zeros(n)
    chords = ((220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66))
    for i, ch in enumerate(chords):
        s, e = int(i * 4 * sr), int((i + 1) * 4 * sr)
        tt = t[s:e] - t[s]
        env = np.minimum(tt / 0.8, 1) * np.minimum((4 - tt) / 0.8, 1)
        for f in ch:
            out[s:e] += env * (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * 2 * f * tt)) * 0.05
    rng = np.random.default_rng(7)
    for beat in np.arange(3.0, DUR - 0.6, 0.5):  # kick
        s = int(beat * sr)
        tt = np.arange(int(0.3 * sr)) / sr
        k = np.sin(2 * np.pi * (45 * tt + 75 * (1 - np.exp(-tt * 30)) / 30 * 1)) * np.exp(-tt * 14) * 0.32
        out[s:s + len(k)] += k[: n - s]
    for beat in np.arange(3.25, DUR - 0.6, 0.5):  # hat
        s = int(beat * sr)
        tt = np.arange(int(0.05 * sr)) / sr
        h = rng.standard_normal(len(tt)) * np.exp(-tt * 90) * 0.035
        out[s:s + len(h)] += h[: n - s]
    for at in (0.0, 3.0, 6.0, 10.4, 13.4):  # whooshes
        s = int(at * sr)
        L = int(0.7 * sr)
        tt = np.linspace(0, 1, L)
        w = np.convolve(rng.standard_normal(L), np.ones(24) / 24, mode="same") * np.sin(np.pi * tt) ** 2 * 0.22
        out[s:s + L] += w[: n - s]
    s = int(14.6 * sr)  # button ding
    tt = np.arange(int(1.2 * sr)) / sr
    ding = (np.sin(2 * np.pi * 1318.5 * tt) + 0.5 * np.sin(2 * np.pi * 1975 * tt)) * np.exp(-tt * 4) * 0.12
    out[s:s + len(ding)] += ding[: n - s]
    out *= np.clip((DUR - t) / 0.7, 0, 1)
    out = out / max(1e-6, np.abs(out).max()) * 0.85
    pcm = (np.repeat(out[:, None], 2, axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# ---------- main ----------
def render():
    wav = ROOT / "audio.wav"
    make_audio(wav)
    mp4 = ROOT / f"careerup_ad_{LANG}.mp4"
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(wav), "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(mp4)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total = int(DUR * FPS)
    for i in range(total):
        p.stdin.write(frame(i / FPS).tobytes())
        if i % 60 == 0:
            print(f"{i}/{total}", flush=True)
    p.stdin.close()
    p.wait()
    print("done", mp4)


if __name__ == "__main__":
    # usage: make_ad.py <ru|en|uz> frames t1 t2 ... | make_ad.py <ru|en|uz> render
    LANG = sys.argv[1]
    L = TX[LANG]
    if sys.argv[2] == "frames":
        out = ROOT / "preview"
        out.mkdir(exist_ok=True)
        for s in sys.argv[3:]:
            frame(float(s)).save(out / f"{LANG}_t{float(s):05.2f}.png")
            print("saved", s)
    else:
        render()
