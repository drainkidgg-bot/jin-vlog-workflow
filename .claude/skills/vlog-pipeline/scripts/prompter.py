"""提词版视频：放在手机或电脑上，对着它一条连录出镜口播。

用法：python3 prompter.py <时间线.json> <输出.mp4> [--countdown 3]

格式（已验证）：
  - 整段话一起显示，正在念的小段高亮，其余变暗
  - 顶部写第几段、段名，以及这段画面是"出镜 · 看镜头"还是"画外音"
  - 底部预告下一段
  - 现场原声段显示「现场原声 · 不用念」，停留原声的时长
  - 节奏按时间线里的 cps（真人口播约每秒 5 字），不按机器配音
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw  # noqa: E402
from common import ffmpeg, font  # noqa: E402
from timeline import Timeline  # noqa: E402

WHITE, DIM, GREY, YELLOW = (255, 255, 255), (95, 95, 100), (140, 140, 145), (255, 214, 10)


def wrap_runs(runs, fnt, max_w):
    """runs: [(文字, 颜色)] → 按宽度折行。英文词不拆开。"""
    import re
    lines, cur, cur_w = [], [], 0
    for text, color in runs:
        for tk in re.findall(r"[A-Za-z]+|\s|.", text):
            w = fnt.getlength(tk)
            if cur and cur_w + w > max_w and tk not in "，。？！；、":
                lines.append(cur)
                cur, cur_w = [], 0
                if tk == " ":
                    continue
            cur.append((tk, color))
            cur_w += w
    return lines + ([cur] if cur else [])


def draw_lines(d, W, lines, fnt, cy, line_h):
    top = cy - line_h * len(lines) / 2
    for i, ln in enumerate(lines):
        x = (W - sum(fnt.getlength(t) for t, _ in ln)) / 2
        for t, c in ln:
            d.text((x, top + i * line_h), t, font=fnt, fill=c)
            x += fnt.getlength(t)


def frame(tl, si, ci, path, countdown=None):
    W, H = tl.W, tl.H
    im = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(im)
    s = tl.segments[si]
    n = len(tl.segments)
    if s.get("live"):
        live = "不用念" if "原声" in s["name"] else "现场原声 · 不用念"
        head, hc = f"{si + 1}/{n} · {s['name']} · {live}", YELLOW
    elif any(sh["_type"] == "talk" for sh in s["shots"]):
        head, hc = f"{si + 1}/{n} · {s['name']} · 出镜 · 看镜头", YELLOW
    else:
        head, hc = f"{si + 1}/{n} · {s['name']} · 画外音", GREY
    d.text((W / 2, 150), head, font=font(38, "medium"), fill=hc, anchor="mm")
    if countdown is not None:
        d.text((W / 2, 420), str(countdown), font=font(160), fill=WHITE, anchor="mm")
    if s.get("live"):
        runs = [(s.get("text") or s.get("note", "（原声）"), GREY)]
    else:
        runs = [(c, DIM if countdown is not None else (WHITE if j == ci else DIM)) for j, (c, _) in enumerate(s["_clauses"])]
    f = font(76)
    draw_lines(d, W, wrap_runs(runs, f, W * 0.87), f, H * 0.45, 112)
    if si + 1 < n:
        nxt = tl.segments[si + 1]
        d.text((W / 2, H * 0.76), "下一句", font=font(32, "medium"), fill=(110, 110, 115), anchor="mm")
        txt = "（现场原声，不用念）" if nxt.get("live") else nxt.get("text", "")
        f2 = font(44, "medium")
        draw_lines(d, W, wrap_runs([(txt, GREY)], f2, W * 0.83), f2, H * 0.83, 62)
    im.save(path)


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--countdown"]
    if len(pos) < 2:
        sys.exit(__doc__)
    tl = Timeline(pos[0])
    if tl.voice:
        print("提示：时间线已经有实录口播，提词版仍按估时（cps）排，只用于重录")
        tl.voice = None
        tl._compute()
    cd = int(sys.argv[sys.argv.index("--countdown") + 1]) if "--countdown" in sys.argv else 3
    with tempfile.TemporaryDirectory() as work:
        states = []
        for k in range(cd, 0, -1):
            p = os.path.join(work, f"cd{k}.png")
            frame(tl, 0, 0, p, countdown=k)
            states.append((p, 1.0))
        for s in tl.segments:
            wins = tl.clause_windows(s) if not s.get("live") else [("", s["_start"], s["_start"] + s["_dur"])]
            for ci, (_, a, b) in enumerate(wins):
                p = os.path.join(work, f"p{s['_i']:02d}-{ci:02d}.png")
                frame(tl, s["_i"], ci, p)
                states.append((p, b - a))
        lst = os.path.join(work, "list.txt")
        with open(lst, "w") as f:
            for p, dur in states:
                f.write(f"file '{p}'\nduration {dur:.3f}\n")
            f.write(f"file '{states[-1][0]}'\n")
        total = tl.total + cd
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
               "-vf", f"fps={tl.fps},format=yuv420p", "-c:v", "libx264", "-crf", "20", "-c:a", "aac",
               "-t", f"{total:.3f}", "-movflags", "+faststart", os.path.abspath(pos[1]))
    print("输出", pos[1], f"{total:.1f}s（前 {cd} 秒倒计时，正文 0:0{cd} 对应成片 0:00）")


if __name__ == "__main__":
    main()
