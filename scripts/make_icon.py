"""生成应用桌面图标：packaging/app_icon.ico（多分辨率）+ 预览 PNG。

设计语言与 R7 前端一致（Claude 式现代风）：
- 赤陶（terracotta）垂直渐变圆角方块
- 米白文档页 + 柔和投影
- 黏土色四角星芒（AI 研究写作意象）+ 三行文字线

用法：python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "packaging"

# ---- 调色板（与 frontend/src/styles/global.css 的 @theme 保持同源）----
GRAD_TOP = (226, 142, 104)     # #E28E68
GRAD_BOTTOM = (192, 88, 47)    # #C0582F
SHEET = (251, 247, 238)        # #FBF7EE 米白纸面
SPARK = (199, 91, 50)          # #C75B32 星芒（黏土深）
LINE = (222, 197, 168)         # #DEC5A8 文字线（暖沙）
SHADOW = (74, 26, 10, 96)      # 投影

SS = 2048  # 超采样画布，缩小抗锯齿


def lerp(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient_tile(size: int, radius: int) -> Image.Image:
    """垂直渐变 + 左上柔光的圆角方块底板。"""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        row = lerp(GRAD_TOP, GRAD_BOTTOM, y / (size - 1))
        for x in range(size):
            px[x, y] = row
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255
    )
    tile.paste(grad, (0, 0), mask)

    # 左上柔光：径向白色高光，叠在渐变上再被同一 mask 裁切
    glow = Image.new("L", (size, size), 0)
    gd = ImageDraw.Draw(glow)
    cx, cy, r = int(size * 0.28), int(size * 0.18), int(size * 0.75)
    for i in range(r, 0, -4):
        alpha = int(30 * (i / r) ** 2)
        gd.ellipse([cx - i, cy - i, cx + i, cy + i], fill=alpha)
    glow = glow.filter(ImageFilter.GaussianBlur(size // 60))
    white = Image.new("RGBA", (size, size), (255, 245, 235, 255))
    tile.paste(white, (0, 0), Image.composite(glow, Image.new("L", (size, size), 0), mask))
    return tile


def sparkle(cx: float, cy: float, radius: float, samples: int = 60,
            waist: float = 0.16) -> list[tuple[float, float]]:
    """四角星芒：N/E/S/W 四个尖角，相邻尖角间用二次贝塞尔凹边相连。

    控制点放在对角线方向、距中心 waist·R 处 —— 值越小腰部收得越紧。
    """
    tips = [(cx, cy - radius), (cx + radius, cy),
            (cx, cy + radius), (cx - radius, cy)]
    pts: list[tuple[float, float]] = []
    for i in range(4):
        p0 = tips[i]
        p2 = tips[(i + 1) % 4]
        # 控制点位于两尖角夹角的对角方向近中心处：i=0 右上(+,-)、1 右下(+,+)、
        # 2 左下(-,+)、3 左上(-,-)
        diag_x = 1 if i in (0, 1) else -1
        diag_y = -1 if i in (0, 3) else 1
        ctrl = (cx + diag_x * radius * waist, cy + diag_y * radius * waist)
        for j in range(samples):
            t = j / samples
            u = 1 - t
            pts.append((u * u * p0[0] + 2 * u * t * ctrl[0] + t * t * p2[0],
                        u * u * p0[1] + 2 * u * t * ctrl[1] + t * t * p2[1]))
    return pts


def glyph_layer(size: int) -> Image.Image:
    """文档页（含投影）+ 星芒 + 文字线，坐标按 1024 设计稿等比换算。"""
    k = size / 1024.0
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    sheet_box = [round(v * k) for v in (302, 292, 722, 772)]
    sheet_radius = round(46 * k)
    line_h = round(26 * k)
    line_xs = round(366 * k)
    line_ws = [round(w * k) for w in (300, 300, 178)]
    line_ys = [round(y * k) for y in (560, 622, 684)]
    big_spark = ((618 * k, 400 * k), 80 * k)
    small_spark = ((486 * k, 352 * k), 30 * k)

    # 柔和投影
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(sheet_box, radius=sheet_radius, fill=SHADOW)
    shadow = shadow.filter(ImageFilter.GaussianBlur(18 * k))
    layer.alpha_composite(shadow, (0, round(14 * k)))

    draw = ImageDraw.Draw(layer)
    # 纸面
    draw.rounded_rectangle(sheet_box, radius=sheet_radius, fill=SHEET)
    # 文字线
    for w, y in zip(line_ws, line_ys, strict=True):
        draw.rounded_rectangle(
            [line_xs, y, line_xs + w, y + line_h], radius=line_h // 2, fill=LINE
        )
    # 星芒（大 + 小）
    draw.polygon(sparkle(*big_spark[0], big_spark[1]), fill=SPARK)
    draw.polygon(sparkle(*small_spark[0], small_spark[1]), fill=SPARK)
    return layer


def render(master_size: int = SS) -> Image.Image:
    radius = round(master_size * 0.226)
    icon = gradient_tile(master_size, radius)
    icon.alpha_composite(glyph_layer(master_size))
    return icon.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    master = render()

    # 多分辨率 ICO（LANCZOS 逐级缩放后交给 PIL 打包）
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    frames = [master.resize(s, Image.LANCZOS) for s in sizes]
    master.resize((256, 256), Image.LANCZOS).save(
        OUT_DIR / "app_icon.ico",
        format="ICO",
        sizes=sizes,
        append_images=frames,
    )
    # 预览图（README / 人工校对用）
    master.resize((512, 512), Image.LANCZOS).save(OUT_DIR / "icon_preview.png")
    print(f"[OK] {OUT_DIR / 'app_icon.ico'}")
    print(f"[OK] {OUT_DIR / 'icon_preview.png'}")


if __name__ == "__main__":
    main()
