"""抽帧拼成一张联系表，每格标时间，用来"看"素材、挑入点、挑封面帧。

用法：
  python3 contact_sheet.py <视频> <输出.jpg> [--every 1] [--width 240] [--cols 8] [--crop W:H:X:Y]
  python3 contact_sheet.py <视频> <输出.jpg> --at 0.8,10.4,17.2 [--full <目录>]
    --every  每隔几秒一帧（默认按时长自动取，约 40 格）
    --at     只取这些时间点（挑封面、挑入点时用）
    --full   同时把这些时间点的原尺寸帧存成 PNG（封面底图候选）
    --crop   先裁再缩，看局部（比如人脸、屏幕上的字）
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw  # noqa: E402
from common import ffmpeg, font, video_info  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and not sys.argv[i - 1].startswith("--")]
    if len(pos) < 2:
        sys.exit(__doc__)
    src, out = pos[0], pos[1]
    info = video_info(src)
    if not info:
        sys.exit(f"读不出来：{src}")
    width, cols, crop = int(arg("--width", 240)), int(arg("--cols", 8)), arg("--crop")
    if arg("--at"):
        times = [float(x) for x in arg("--at").split(",")]
    else:
        every = float(arg("--every", 0) or max(0.5, round(info["dur"] / 40 * 2) / 2))
        times, t = [], 0.0
        while t < info["dur"] - 0.05:
            times.append(round(t, 2))
            t += every
    vf = (f"crop={crop}," if crop else "") + f"scale={width}:-2"
    tiles = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"{i:04d}.jpg")
            ffmpeg("-ss", f"{t}", "-i", src, "-frames:v", "1", "-vf", vf, "-q:v", "3", p)
            if os.path.exists(p):
                tiles.append((t, Image.open(p).convert("RGB")))
            if arg("--full"):
                os.makedirs(arg("--full"), exist_ok=True)
                name = os.path.splitext(os.path.basename(src))[0]
                ffmpeg("-ss", f"{t}", "-i", src, "-frames:v", "1", os.path.join(arg("--full"), f"{name}-{t:.2f}s.png"))
    if not tiles:
        sys.exit("一帧都没取到")
    w, h = tiles[0][1].size
    label_h = 28
    cols = min(cols, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + label_h)), "white")
    d = ImageDraw.Draw(sheet)
    f = font(20, "medium")
    for i, (t, im) in enumerate(tiles):
        x, y = (i % cols) * w, (i // cols) * (h + label_h)
        sheet.paste(im, (x, y + label_h))
        d.text((x + 6, y + 3), f"{t:.1f}s", font=f, fill="black")
    sheet.save(out, quality=88)
    print(out, f"{len(tiles)} 格", sheet.size)


if __name__ == "__main__":
    main()
