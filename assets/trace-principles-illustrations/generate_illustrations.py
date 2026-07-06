from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parent
W, H = 1920, 1080

BLACK = (18, 18, 18)
ORANGE = (230, 112, 32)
RED = (204, 48, 42)
BLUE = (50, 98, 180)
LIGHT = (245, 245, 245)


FONT_PATHS = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


FONT_SM = font(32)
FONT_MD = font(42)
FONT_LG = font(52)


def canvas(seed: int) -> tuple[Image.Image, ImageDraw.ImageDraw, random.Random]:
    rng = random.Random(seed)
    im = Image.new("RGB", (W, H), "white")
    return im, ImageDraw.Draw(im), rng


def jitter(rng: random.Random, value: float, amount: float) -> float:
    return value + rng.uniform(-amount, amount)


def line(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    pts: list[tuple[float, float]],
    fill=BLACK,
    width: int = 4,
    wobble: float = 3.0,
    repeats: int = 1,
) -> None:
    for _ in range(repeats):
        noisy = [(jitter(rng, x, wobble), jitter(rng, y, wobble)) for x, y in pts]
        d.line(noisy, fill=fill, width=width, joint="curve")


def rect(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    xy: tuple[int, int, int, int],
    fill=None,
    outline=BLACK,
    width: int = 4,
    wobble: float = 4.0,
) -> None:
    x1, y1, x2, y2 = xy
    if fill is not None:
        d.rectangle(xy, fill=fill)
    line(d, rng, [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)], outline, width, wobble, 2)


def ellipse(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    xy: tuple[int, int, int, int],
    fill=None,
    outline=BLACK,
    width: int = 4,
    wobble: float = 3.0,
) -> None:
    for i in range(2):
        off = rng.uniform(-wobble, wobble)
        d.ellipse(
            (xy[0] + off, xy[1] - off, xy[2] - off, xy[3] + off),
            fill=fill if i == 0 else None,
            outline=outline,
            width=width,
        )


def arrow(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    start: tuple[int, int],
    end: tuple[int, int],
    fill=ORANGE,
    width: int = 5,
    bend: float = 0.0,
) -> None:
    sx, sy = start
    ex, ey = end
    mx = (sx + ex) / 2
    my = (sy + ey) / 2 + bend
    pts = []
    for t in [i / 22 for i in range(23)]:
        x = (1 - t) ** 2 * sx + 2 * (1 - t) * t * mx + t**2 * ex
        y = (1 - t) ** 2 * sy + 2 * (1 - t) * t * my + t**2 * ey
        pts.append((x, y))
    line(d, rng, pts, fill=fill, width=width, wobble=2.5, repeats=1)
    ang = math.atan2(ey - my, ex - mx)
    head = 28
    a1 = ang + math.pi * 0.84
    a2 = ang - math.pi * 0.84
    line(d, rng, [(ex, ey), (ex + math.cos(a1) * head, ey + math.sin(a1) * head)], fill, width, 1.5)
    line(d, rng, [(ex, ey), (ex + math.cos(a2) * head, ey + math.sin(a2) * head)], fill, width, 1.5)


def label(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    text: str,
    pos: tuple[int, int],
    fill=BLACK,
    size: str = "md",
    box: bool = False,
) -> None:
    f = {"sm": FONT_SM, "md": FONT_MD, "lg": FONT_LG}[size]
    x, y = pos
    if box:
        bbox = d.textbbox((x, y), text, font=f)
        rect(d, rng, (bbox[0] - 14, bbox[1] - 8, bbox[2] + 14, bbox[3] + 10), outline=fill, width=3, wobble=2)
    d.text((x, y), text, fill=fill, font=f)


def blob_points(cx: int, cy: int, rx: int, ry: int, rng: random.Random, n: int = 28) -> list[tuple[float, float]]:
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rjx = rx * rng.uniform(0.88, 1.08)
        rjy = ry * rng.uniform(0.88, 1.08)
        pts.append((cx + math.cos(a) * rjx, cy + math.sin(a) * rjy))
    return pts


def xiaohei(
    d: ImageDraw.ImageDraw,
    rng: random.Random,
    cx: int,
    cy: int,
    scale: float = 1.0,
    arms: str = "down",
) -> None:
    rx = int(42 * scale)
    ry = int(58 * scale)
    pts = blob_points(cx, cy, rx, ry, rng)
    d.polygon(pts, fill=BLACK)
    d.line(pts + [pts[0]], fill=BLACK, width=max(2, int(3 * scale)))
    eye_r = max(5, int(7 * scale))
    d.ellipse((cx - int(16 * scale) - eye_r, cy - int(14 * scale) - eye_r, cx - int(16 * scale) + eye_r, cy - int(14 * scale) + eye_r), fill="white")
    d.ellipse((cx + int(15 * scale) - eye_r, cy - int(12 * scale) - eye_r, cx + int(15 * scale) + eye_r, cy - int(12 * scale) + eye_r), fill="white")
    leg_y = cy + ry - 2
    line(d, rng, [(cx - int(18 * scale), leg_y), (cx - int(28 * scale), leg_y + int(34 * scale))], width=max(3, int(4 * scale)), wobble=2)
    line(d, rng, [(cx + int(18 * scale), leg_y), (cx + int(27 * scale), leg_y + int(34 * scale))], width=max(3, int(4 * scale)), wobble=2)
    if arms == "measure":
        line(d, rng, [(cx - rx, cy), (cx - rx - int(56 * scale), cy - int(28 * scale))], width=4, wobble=2)
        line(d, rng, [(cx + rx, cy), (cx + rx + int(72 * scale), cy - int(10 * scale))], width=4, wobble=2)
    elif arms == "crank":
        line(d, rng, [(cx - rx, cy - 8), (cx - rx - int(52 * scale), cy + int(18 * scale))], width=4, wobble=2)
        line(d, rng, [(cx + rx, cy - 6), (cx + rx + int(48 * scale), cy - int(36 * scale))], width=4, wobble=2)
    elif arms == "carry":
        line(d, rng, [(cx - rx, cy - 8), (cx - rx - int(54 * scale), cy - int(50 * scale))], width=4, wobble=2)
        line(d, rng, [(cx + rx, cy - 10), (cx + rx + int(56 * scale), cy - int(48 * scale))], width=4, wobble=2)
    elif arms == "stamp":
        line(d, rng, [(cx + rx, cy - 10), (cx + rx + int(55 * scale), cy - int(50 * scale))], width=4, wobble=2)
        line(d, rng, [(cx - rx, cy - 4), (cx - rx - int(44 * scale), cy + int(18 * scale))], width=4, wobble=2)


def terminal_card(d: ImageDraw.ImageDraw, rng: random.Random, x: int, y: int, txt: str) -> None:
    rect(d, rng, (x, y, x + 210, y + 86), outline=BLACK, width=4, wobble=3)
    d.text((x + 22, y + 20), "$ " + txt, font=FONT_SM, fill=BLACK)
    line(d, rng, [(x + 20, y + 58), (x + 166, y + 58)], fill=BLUE, width=3, wobble=2)


def file_page(d: ImageDraw.ImageDraw, rng: random.Random, x: int, y: int, w: int = 120, h: int = 150, txt: str = "") -> None:
    rect(d, rng, (x, y, x + w, y + h), outline=BLACK, width=3, wobble=3)
    line(d, rng, [(x + 24, y + 44), (x + w - 24, y + 44)], width=3, wobble=2)
    line(d, rng, [(x + 24, y + 74), (x + w - 34, y + 74)], width=3, wobble=2)
    if txt:
        d.text((x + 20, y + h - 50), txt, font=FONT_SM, fill=BLACK)


def draw_agent_attribution() -> None:
    im, d, rng = canvas(101)
    rect(d, rng, (700, 220, 1320, 760), outline=BLACK, width=5, wobble=6)
    label(d, rng, "项目工作区", (900, 275), fill=BLUE, size="md")
    rect(d, rng, (910, 425, 1100, 610), outline=BLACK, width=4, wobble=4)
    label(d, rng, "cwd 门槛", (925, 495), fill=BLACK, size="sm")
    xiaohei(d, rng, 830, 565, 1.2, arms="measure")
    line(d, rng, [(770, 500), (934, 510)], fill=ORANGE, width=4, wobble=2)
    ellipse(d, rng, (682, 490, 750, 558), outline=BLACK, width=4)
    line(d, rng, [(725, 545), (782, 610)], width=5, wobble=2)
    label(d, rng, "看进程站在哪里", (665, 675), fill=BLUE, size="sm")

    terminal_card(d, rng, 190, 200, "claude")
    terminal_card(d, rng, 230, 455, "codex")
    terminal_card(d, rng, 180, 700, "openclaw")
    arrow(d, rng, (410, 250), (700, 360), bend=30)
    arrow(d, rng, (455, 505), (700, 520), bend=-20)
    arrow(d, rng, (405, 745), (700, 650), bend=-40)
    label(d, rng, "agent 进程", (245, 120), fill=BLACK, size="md")
    label(d, rng, "cwd 在里面", (1135, 470), fill=ORANGE, size="md")

    rect(d, rng, (1385, 350, 1660, 465), outline=BLACK, width=4, wobble=4)
    label(d, rng, "归属候选", (1430, 382), fill=BLACK, size="md")
    arrow(d, rng, (1320, 520), (1385, 415), bend=-15)
    rect(d, rng, (1405, 590, 1658, 700), outline=RED, width=4, wobble=4)
    label(d, rng, "没人活跃", (1445, 612), fill=RED, size="sm")
    label(d, rng, "human 兜底", (1445, 650), fill=RED, size="sm")
    im.save(OUT_DIR / "01-agent-attribution.png")


def draw_event_filter() -> None:
    im, d, rng = canvas(202)
    for i, txt in enumerate([".git", "tmp", "node", ".trace", "写一半", "重复"]):
        x = 170 + (i % 3) * 150 + rng.randint(-18, 18)
        y = 230 + (i // 3) * 155 + rng.randint(-20, 20)
        file_page(d, rng, x, y, 92, 112, txt)
    label(d, rng, "watchdog 事件", (175, 145), fill=BLACK, size="md")
    arrow(d, rng, (610, 430), (780, 480), bend=-45)

    rect(d, rng, (770, 280, 1235, 735), outline=BLACK, width=5, wobble=7)
    ellipse(d, rng, (870, 365, 1135, 620), outline=BLACK, width=5, wobble=5)
    line(d, rng, [(870, 445), (1135, 445)], fill=BLACK, width=4, wobble=3, repeats=2)
    line(d, rng, [(870, 540), (1135, 540)], fill=BLACK, width=4, wobble=3, repeats=2)
    for x in [940, 1010, 1080]:
        line(d, rng, [(x, 365), (x, 620)], fill=BLACK, width=3, wobble=3)
    xiaohei(d, rng, 960, 705, 1.05, arms="crank")
    ellipse(d, rng, (1185, 375, 1275, 465), outline=ORANGE, width=5)
    line(d, rng, [(1230, 420), (1310, 375)], fill=ORANGE, width=5, wobble=2)
    label(d, rng, "忽略目录", (805, 245), fill=RED, size="sm")
    label(d, rng, "500ms 去重", (1010, 245), fill=RED, size="sm")
    label(d, rng, "等写完", (1065, 650), fill=BLUE, size="sm")

    file_page(d, rng, 1485, 405, 145, 175, "变化")
    arrow(d, rng, (1240, 510), (1485, 500), bend=25)
    label(d, rng, "干净变化", (1470, 610), fill=ORANGE, size="md")
    for x, y in [(760, 770), (830, 815), (1165, 805), (1265, 760)]:
        d.line((x, y, x + 28, y + 25), fill=RED, width=4)
        d.line((x + 25, y, x, y + 25), fill=RED, width=4)
    im.save(OUT_DIR / "02-event-filtering.png")


def draw_batcher() -> None:
    im, d, rng = canvas(303)
    label(d, rng, "零散变化", (190, 165), fill=BLACK, size="md")
    for i in range(7):
        file_page(d, rng, 160 + i * 62, 300 + (i % 3) * 80, 72, 86)
    arrow(d, rng, (620, 430), (760, 430), bend=-20)

    rect(d, rng, (760, 240, 1285, 740), outline=BLACK, width=5, wobble=6)
    xiaohei(d, rng, 1000, 515, 1.25, arms="carry")
    line(d, rng, [(850, 360), (1150, 360)], fill=ORANGE, width=6, wobble=3)
    for idx, (x, name, color) in enumerate([(820, "Claude", RED), (990, "Codex", BLUE), (1160, "human", BLACK)]):
        ellipse(d, rng, (x - 55, 300, x + 55, 420), outline=color, width=4)
        line(d, rng, [(x - 35, 315), (x + 35, 405)], fill=color, width=3, wobble=2)
        line(d, rng, [(x + 35, 315), (x - 35, 405)], fill=color, width=3, wobble=2)
        d.text((x - 48, 435), name, font=FONT_SM, fill=color)
        d.text((x - 42, 470), "2秒", font=FONT_SM, fill=ORANGE)
    label(d, rng, "独立 timer", (790, 205), fill=BLUE, size="md")
    label(d, rng, "互不推迟", (1080, 205), fill=BLUE, size="md")
    label(d, rng, "同文件取最后一次", (835, 665), fill=RED, size="sm")

    rect(d, rng, (1450, 355, 1690, 550), outline=BLACK, width=4, wobble=5)
    label(d, rng, "一批 commit", (1478, 420), fill=ORANGE, size="md")
    arrow(d, rng, (1285, 450), (1450, 450), bend=0)
    for x, y in [(1505, 575), (1580, 590), (1650, 570)]:
        ellipse(d, rng, (x - 12, y - 12, x + 12, y + 12), fill=BLACK, outline=BLACK, width=2)
    im.save(OUT_DIR / "03-agent-batching.png")


def draw_repository() -> None:
    im, d, rng = canvas(404)
    label(d, rng, "文件字节", (190, 165), fill=BLACK, size="md")
    file_page(d, rng, 175, 300, 120, 150, ".py")
    file_page(d, rng, 315, 250, 120, 150, ".docx")
    file_page(d, rng, 300, 470, 120, 150, ".png")
    arrow(d, rng, (500, 420), (665, 420), bend=-35)

    rect(d, rng, (650, 250, 1015, 665), outline=BLACK, width=5, wobble=5)
    label(d, rng, "SHA-256", (750, 290), fill=BLUE, size="md")
    for y, txt in [(360, "1a/2b..."), (455, "ef/91..."), (550, "9c/aa...")]:
        rect(d, rng, (705, y, 960, y + 62), outline=BLACK, width=3, wobble=3)
        d.text((735, y + 13), txt, font=FONT_SM, fill=BLACK)
    xiaohei(d, rng, 1070, 615, 1.15, arms="stamp")
    rect(d, rng, (1095, 470, 1240, 535), outline=RED, width=4, wobble=3)
    label(d, rng, "盖 commit", (1085, 400), fill=RED, size="sm")

    arrow(d, rng, (1015, 420), (1275, 405), bend=-20)
    rect(d, rng, (1275, 250, 1640, 560), outline=BLACK, width=5, wobble=6)
    label(d, rng, "SQLite 台账", (1360, 290), fill=BLACK, size="md")
    line(d, rng, [(1315, 370), (1600, 370)], width=3, wobble=2)
    line(d, rng, [(1315, 430), (1600, 430)], width=3, wobble=2)
    label(d, rng, "agent / time", (1325, 382), fill=BLUE, size="sm")
    label(d, rng, "完整 manifest", (1325, 442), fill=ORANGE, size="sm")

    rect(d, rng, (1160, 690, 1525, 835), outline=ORANGE, width=4, wobble=5)
    label(d, rng, "checkout 读清单", (1205, 715), fill=ORANGE, size="md")
    label(d, rng, "多余文件删除", (1235, 770), fill=RED, size="sm")
    arrow(d, rng, (1445, 560), (1360, 690), bend=35)
    ellipse(d, rng, (1535, 740, 1620, 825), outline=RED, width=4)
    line(d, rng, [(1555, 760), (1600, 805)], fill=RED, width=5, wobble=2)
    line(d, rng, [(1600, 760), (1555, 805)], fill=RED, width=5, wobble=2)
    im.save(OUT_DIR / "04-blob-manifest.png")


def main() -> None:
    draw_agent_attribution()
    draw_event_filter()
    draw_batcher()
    draw_repository()
    print(f"generated 4 images in {OUT_DIR}")


if __name__ == "__main__":
    main()
