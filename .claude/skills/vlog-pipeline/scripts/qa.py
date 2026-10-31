"""成片体检：规格、响度、黑帧、定格、剪接点附近的"跳帧"。给 vlog-video-qa 子代理和交付前自查用。

用法：python3 qa.py <成片.mp4> [<时间线.json>] [--sheet <输出目录>]
  带时间线时，会对照每个镜头的起止，指出可疑的位置属于哪一段
  --sheet  在每个剪接点前后各抽两帧拼图（cut-XX.jpg），用眼睛确认没有带进上一个镜头的几帧
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw  # noqa: E402
from common import ffmpeg, fmt_time, font, video_info  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def stderr_of(*args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", *args, "-f", "null", "-"], capture_output=True, text=True).stderr


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--sheet"]
    if not pos:
        sys.exit(__doc__)
    video = pos[0]
    tl = None
    if len(pos) > 1:
        from timeline import Timeline
        tl = Timeline(pos[1])
    inf = video_info(video)
    out = [f"## 成片体检：{os.path.basename(video)}", ""]

    # 规格
    spec = f"{inf['w']}×{inf['h']}，{inf['fps']:.2f}fps，{inf['dur']:.2f}s，{'有' if inf['has_audio'] else '没有'}音轨"
    issues = []
    if (inf["w"], inf["h"]) != ((tl.W, tl.H) if tl else (1080, 1920)):
        issues.append("尺寸不对")
    if tl and abs(inf["dur"] - tl.total) > 0.1:
        issues.append(f"时长和时间线差 {inf['dur'] - tl.total:+.2f}s")
    if not inf["has_audio"]:
        issues.append("没有音轨（交付要含口播和现场原声）")
    out.append(f"- 规格：{spec}" + (f"  ⚠ {'；'.join(issues)}" if issues else ""))

    # 响度
    e = stderr_of("-i", video, "-map", "0:a:0", "-af", "ebur128=peak=true") if inf["has_audio"] else ""
    m_i = re.findall(r"I:\s+(-?[\d.]+) LUFS", e)
    m_p = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", e)
    if m_i and float(m_i[-1]) < -60:
        out.append("- 响度：几乎无声（还没录口播的样片是正常的；精剪出现这个说明口播没进来）")
    elif m_i:
        li, tp = float(m_i[-1]), float(m_p[-1]) if m_p else 0
        flag = "  ⚠ 目标约 -16 LUFS" if abs(li + 16) > 1.5 else ""
        flag += "  ⚠ 峰值过高，可能破音" if tp > -1 else ""
        out.append(f"- 响度：{li:.1f} LUFS，峰值 {tp:.1f} dBTP{flag}")

    def where(t):
        if not tl:
            return ""
        for s in tl.segments:
            for sh in s["shots"]:
                if sh["_start"] - 1e-3 <= t < sh["_start"] + sh["_dur"]:
                    ok = {"follow": "，结尾动效，正常", "placeholder": "，占位卡"}.get(sh["_type"], "")
                    return f"「{s['name']}{ok}」"
        return ""

    # 黑帧
    blacks = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", stderr_of("-i", video, "-vf", "blackdetect=d=0.1:pix_th=0.08", "-an"))
    out.append("- 黑帧：" + ("没有" if not blacks else "；".join(f"{fmt_time(float(a))}–{fmt_time(float(b))}{where(float(a))}" for a, b in blacks)))

    # 定格（超过 1 秒画面不动；结尾动效最后定格是正常的）
    fr = stderr_of("-i", video, "-vf", "freezedetect=n=0.002:d=1", "-an")
    fs = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", fr)]
    fe = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", fr)] + [inf["dur"]] * len(fs)
    out.append("- 定格 ≥1s：" + ("没有" if not fs else "；".join(f"{fmt_time(a)}–{fmt_time(b)}{where(a)}" for a, b in zip(fs, fe))))

    # 剪接点附近的跳帧：镜头切换应该正好落在剪接点上，剪接点前后 0.05–0.5 秒内又切一次，多半是素材没剪干净
    if tl:
        cuts = sorted({round(sh["_start"], 3) for s in tl.segments for sh in s["shots"]} - {0})
        sc = stderr_of("-i", video, "-vf", "select='gt(scene,0.3)',showinfo", "-an")
        scenes = [float(x) for x in re.findall(r"pts_time:([\d.]+)", sc)]
        odd, inner = [], []
        for t in scenes:
            near = min(cuts, key=lambda c: abs(c - t)) if cuts else None
            if near is None or abs(t - near) <= 0.05:
                continue
            if abs(t - near) < 0.5:
                odd.append(f"{fmt_time(t)}（剪接点 {fmt_time(near)} {'后' if t > near else '前'} {abs(t - near):.2f}s）{where(t)}")
            else:
                inner.append(f"{fmt_time(t)}{where(t)}")
        out.append("- 剪接点附近的异常切换（多半是素材没剪干净）：" + ("没有" if not odd else "；".join(odd)))
        out.append("- 镜头中间的切换（素材自带剪接或大动作，确认是想要的）：" + ("没有" if not inner else "；".join(inner)))

        if arg("--sheet"):
            d = arg("--sheet")
            os.makedirs(d, exist_ok=True)
            fps = tl.fps
            for k, c in enumerate(cuts):
                tiles = []
                for off in (-2, -1, 0, 1):
                    t = max(0, c + off / fps + 0.001)
                    p = os.path.join(d, f"_f{k}{off}.jpg")
                    ffmpeg("-ss", f"{t:.4f}", "-i", video, "-frames:v", "1", "-vf", "scale=270:-2", p)
                    tiles.append((off, Image.open(p).convert("RGB")))
                    os.remove(p)
                w, h = tiles[0][1].size
                sheet = Image.new("RGB", (w * 4, h + 30), "white")
                dr = ImageDraw.Draw(sheet)
                for i, (off, im) in enumerate(tiles):
                    sheet.paste(im, (i * w, 30))
                    dr.text((i * w + 6, 4), f"{fmt_time(c)} {'+' if off >= 0 else ''}{off}帧", font=font(18, "medium"), fill="black")
                sheet.save(os.path.join(d, f"cut-{k:02d}.jpg"), quality=85)
            out.append(f"- 剪接点拼图：{d}/cut-XX.jpg（每张是剪接点前两帧、后两帧）")
    print("\n".join(out))


if __name__ == "__main__":
    main()
