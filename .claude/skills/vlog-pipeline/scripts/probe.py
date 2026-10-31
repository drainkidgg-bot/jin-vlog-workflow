"""素材体检：列出每个视频、照片的时长、尺寸、帧率、HDR、音量，标出要先处理的问题。

用法：python3 probe.py <文件或目录>... [--loudness]
  --loudness  顺便量每段的平均音量（长素材会慢一些）
输出一张 Markdown 表，贴进素材盘点。
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fmt_time, video_info  # noqa: E402

EXTS = {".mov", ".mp4", ".m4v", ".mkv", ".avi", ".webm", ".jpg", ".jpeg", ".png", ".heic", ".webp"}


def mean_volume(path):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    return float(m.group(1)) if m else None


def files(args):
    for a in args:
        if os.path.isdir(a):
            for root, _, names in os.walk(a):
                for n in sorted(names):
                    if os.path.splitext(n)[1].lower() in EXTS:
                        yield os.path.join(root, n)
        else:
            yield a


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    loud = "--loudness" in sys.argv
    rows = ["| 文件 | 时长 | 尺寸 | 帧率 | 音量 | 注意 |", "|---|---|---|---|---|---|"]
    for f in files(args):
        info = video_info(f)
        if not info:
            rows.append(f"| {os.path.basename(f)} | — | — | — | — | 读不出来，可能不是视频或图片 |")
            continue
        notes = []
        short = min(info["w"], info["h"])
        if info["image"]:
            notes.append("照片")
        else:
            if short < 1080:
                notes.append(f"{short}p，低于 1080（微信转发会压到 720p，要原片请对方用原文件或 AirDrop 发）")
            if info["hdr"]:
                notes.append("HDR，先转 SDR（to_sdr.py）")
            if info["w"] > info["h"]:
                notes.append("横屏")
            if not info["has_audio"]:
                notes.append("没有音轨")
        vol = ""
        if loud and info["has_audio"] and not info["image"]:
            mv = mean_volume(f)
            vol = f"{mv:.0f} dB" if mv is not None else ""
            if mv is not None and mv < -45:
                notes.append("几乎没声音")
        dur = "—" if info["image"] else fmt_time(info["dur"])
        fps = "—" if info["image"] else f"{info['fps']:.0f}"
        rows.append(f"| {os.path.basename(f)} | {dur} | {info['w']}×{info['h']} | {fps} | {vol} | {'；'.join(notes)} |")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
