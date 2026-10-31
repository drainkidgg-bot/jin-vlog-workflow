"""结尾关注动效：圆形头像弹出，下面的红色「+」被点击后转成对勾，再浮出「关注我」和一句口号。
每个账号做一次，以后每条视频直接接在最后。

用法：python3 follow_card.py --avatar <头像.jpg> --slogan "一起把相机玩明白" --out <输出>
  [--title 关注我] [--bg black|green|alpha] [--dur 4] [--notext]
    --bg black  黑底 mp4，组件在画面正中，单独接在片尾（默认）
    --bg green  绿幕 mp4，在剪映里用「色度抠图」叠到画面上
    --bg alpha  透明背景 ProRes 4444 .mov，剪映里直接叠
    --notext    只出头像和按钮，文案每条在剪映里自己加
头像用平台上的同一张方图，整张切成圆，和账号头像保持一致。
规格：1080×1920，30fps，无声。节奏：0–0.5 秒头像弹出，1.2 秒点击，1.7 秒浮出文案，停到结尾。
"""
import math
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw  # noqa: E402
from common import font as _font  # noqa: E402

W, H, FPS = 1080, 1920, 30
SS = 2                    # 超采样，边缘更顺
RH = 800                  # 组件区域高度
RED = (254, 44, 85)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def font(size, w="semibold"):
    return _font(size * SS, w)


def clamp(x):
    return max(0.0, min(1.0, x))


def seg(t, a, b):
    return clamp((t - a) / (b - a))


def out_cubic(x):
    return 1 - (1 - x) ** 3


def in_out(x):
    return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def out_back(x, s=1.9):
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def in_back(x, s=1.7):
    return (s + 1) * x ** 3 - s * x ** 2


def lerp(a, b, x):
    return a + (b - a) * x


def S(*v):
    return [x * SS for x in v]


def layer():
    return Image.new("RGBA", (W * SS, RH * SS), (0, 0, 0, 0))


def put(base, lay, alpha=1.0):
    if alpha < 1:
        lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
    base.alpha_composite(lay)


def circle(d, cx, cy, r, **kw):
    d.ellipse(S(cx - r, cy - r, cx + r, cy + r), **kw)


def text_c(d, cx, cy, s, f, fill):
    b = d.textbbox((0, 0), s, font=f)
    d.text((cx * SS - (b[2] - b[0]) / 2 - b[0], cy * SS - (b[3] - b[1]) / 2 - b[1]), s, font=f, fill=fill)


def stroke(d, pts, width, fill):
    if len(pts) < 2:
        return
    d.line([c * SS for p in pts for c in p], fill=fill, width=int(width * SS), joint="curve")
    for x, y in (pts[0], pts[-1]):
        circle(d, x, y, width / 2, fill=fill)


def poly_progress(pts, p):
    """折线按长度取前 p 比例，用来"描"出对勾。"""
    segs = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total, out, acc = sum(segs), [pts[0]], 0
    for i, L in enumerate(segs):
        if acc + L <= p * total:
            out.append(pts[i + 1])
            acc += L
        else:
            k = (p * total - acc) / L
            out.append((lerp(pts[i][0], pts[i + 1][0], k), lerp(pts[i][1], pts[i + 1][1], k)))
            break
    return out


class Card:
    def __init__(self, avatar, title, slogan, notext):
        im = Image.open(avatar).convert("RGB")
        side = min(im.size)
        l, t = (im.width - side) // 2, (im.height - side) // 2
        self.avatar = im.crop((l, t, l + side, t + side))
        self.title, self.slogan, self.notext = title, slogan, notext

    def paste_avatar(self, base, cx, cy, r):
        size = max(2, int(2 * r * SS))
        a = self.avatar.resize((size, size), Image.LANCZOS).convert("RGBA")
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).ellipse((0, 0, size - 1, size - 1), fill=255)
        a.putalpha(m)
        lay = layer()
        lay.paste(a, (int(cx * SS - a.width / 2), int(cy * SS - a.height / 2)))
        put(base, lay)

    def ripple(self, base, cx, cy, t, t0):
        p = seg(t, t0, t0 + .5)
        if 0 < p < 1:
            lay = layer()
            circle(ImageDraw.Draw(lay), cx, cy, lerp(20, 95, out_cubic(p)), outline=(255, 255, 255, int(220 * (1 - p))), width=int(4 * SS))
            put(base, lay)
        q = seg(t, t0 - .15, t0 + .2)   # 手指按下的触点
        if 0 < q < 1:
            lay = layer()
            k = math.sin(q * math.pi)
            circle(ImageDraw.Draw(lay), cx, cy, lerp(26, 18, k), fill=(255, 255, 255, int(150 * k)))
            put(base, lay)

    def draw(self, t):
        base = layer()
        cx, cy, r = 540, 230, 104
        s = out_back(seg(t, 0, .45))
        if s > 0:
            lay = layer()
            circle(ImageDraw.Draw(lay), cx, cy, (r + 6) * s, fill=(255, 255, 255, 255))
            put(base, lay)
            self.paste_avatar(base, cx, cy, r * s)
        # 红色加号徽标：弹出 → 按下 → 转成白底红勾 → 收起
        bx, by, br = cx, cy + r, 32
        k = out_back(seg(t, .35, .7)) * (1 - in_back(seg(t, 2.5, 2.85))) * (1 - .15 * math.sin(math.pi * seg(t, 1.15, 1.35)))
        morph = in_out(seg(t, 1.3, 1.6))
        if k > 0.01:
            lay = layer()
            d = ImageDraw.Draw(lay)
            circle(d, bx, by, br * k + 3, fill=(255, 255, 255, int(255 * morph)))
            circle(d, bx, by, br * k, fill=tuple(int(lerp(a, 255, morph)) for a in RED) + (255,))
            if morph < 1:   # 加号旋转缩小
                ang, L = math.radians(90 * morph), 13 * k * (1 - morph)
                for a0 in (0, math.pi / 2):
                    dx, dy = L * math.cos(a0 + ang), L * math.sin(a0 + ang)
                    stroke(d, [(bx - dx, by - dy), (bx + dx, by + dy)], 5.5 * k, (255, 255, 255, 255))
            cp = out_cubic(seg(t, 1.45, 1.8))
            if cp > 0:
                s30 = 30 * k
                pts = [(bx - .42 * s30, by + .02 * s30), (bx - .12 * s30, by + .32 * s30), (bx + .45 * s30, by - .3 * s30)]
                stroke(d, poly_progress(pts, cp), 6 * k, RED + (255,))
            put(base, lay)
        self.ripple(base, bx, by, t, 1.2)
        if not self.notext:
            p = out_cubic(seg(t, 1.7, 2.15))
            if p > 0:
                lay = layer()
                d = ImageDraw.Draw(lay)
                off = (1 - p) * 24
                text_c(d, 540, 430 + off, self.title, font(60), (255, 255, 255, 255))
                if self.slogan:
                    text_c(d, 540, 506 + off, self.slogan, font(38, "regular"), (255, 255, 255, 225))
                put(base, lay, p)
        return base


def main():
    if not arg("--avatar") or not arg("--out"):
        sys.exit(__doc__)
    card = Card(arg("--avatar"), arg("--title", "关注我"), arg("--slogan", ""), "--notext" in sys.argv)
    bg, dur, out = arg("--bg", "black"), float(arg("--dur", 4)), arg("--out")
    # 黑底版把头像到文案整体放在画面正中；叠加版放在画面下半部
    ry = 637 if bg == "black" else 980
    if bg == "alpha":
        enc = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16"]
        fill = (0, 0, 0, 0)
    else:
        enc = ["-c:v", "libx264", "-crf", "14", "-preset", "slow", "-pix_fmt", "yuv420p"]
        fill = (0, 0, 0, 255) if bg == "black" else (0, 177, 64, 255)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS),
                          "-i", "-", *enc, "-r", str(FPS), out], stdin=subprocess.PIPE)
    for i in range(int(dur * FPS)):
        fr = Image.new("RGBA", (W, H), fill)
        fr.alpha_composite(card.draw(i / FPS).resize((W, RH), Image.LANCZOS), (0, ry))
        p.stdin.write(fr.tobytes())
    p.stdin.close()
    if p.wait():
        sys.exit("ffmpeg 出错")
    print(out)


if __name__ == "__main__":
    main()
