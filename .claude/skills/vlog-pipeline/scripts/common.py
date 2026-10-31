"""各脚本共用的小工具：找中文字体、跑 ffmpeg、读素材信息。"""
import glob
import json
import os
import subprocess
import sys

from PIL import ImageFont

# 中文字体，按顺序找第一个存在的：(路径通配, 各字重在 ttc 里的序号)
_FONT_CANDIDATES = [
    ("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/PingFang.ttc",
     {"regular": 3, "medium": 7, "semibold": 11, "light": 15}),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", {"regular": 0, "medium": 0, "semibold": 1, "light": 0}),
    ("/System/Library/Fonts/STHeiti Medium.ttc", {"regular": 0, "medium": 0, "semibold": 0, "light": 0}),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-*.ttc", {"regular": 0, "medium": 0, "semibold": 0, "light": 0}),
    ("C:/Windows/Fonts/msyh.ttc", {"regular": 0, "medium": 0, "semibold": 1, "light": 0}),
]
_font_path = None
_font_idx = None


def font(size, weight="semibold"):
    """中文字体。weight: regular / medium / semibold / light。"""
    global _font_path, _font_idx
    if _font_path is None:
        for pattern, idx in _FONT_CANDIDATES:
            hits = sorted(glob.glob(pattern))
            if hits:
                _font_path, _font_idx = hits[0], idx
                break
        else:
            sys.exit("找不到中文字体，请在 common.py 的 _FONT_CANDIDATES 里加一个")
    return ImageFont.truetype(_font_path, int(size), index=_font_idx.get(weight, 0))


def run(cmd, **kw):
    """跑命令，失败就抛错。cmd 是列表。"""
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def ffmpeg(*args):
    run(["ffmpeg", "-v", "error", "-y", *args])


def probe(path):
    """ffprobe 的 JSON 结果。"""
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True)
    if out.returncode:
        return None
    return json.loads(out.stdout)


def video_info(path):
    """返回 dict：dur, w, h（已按旋转换算成显示尺寸）, fps, hdr, has_audio, codec。不是视频返回 None。"""
    p = probe(path)
    if not p:
        return None
    v = next((s for s in p["streams"] if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    if not v:
        return None
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    if "rotate" in v.get("tags", {}):
        rot = int(v["tags"]["rotate"])
    if abs(rot) % 180 == 90:
        w, h = h, w
    num, _, den = v.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0
    dur = float(p["format"].get("duration") or v.get("duration") or 0)
    return dict(
        dur=dur, w=w, h=h, fps=fps, codec=v.get("codec_name"),
        hdr=v.get("color_transfer") in ("arib-std-b67", "smpte2084"),
        has_audio=any(s.get("codec_type") == "audio" for s in p["streams"]),
        image=dur == 0 or v.get("codec_name") in ("png", "mjpeg", "webp", "bmp", "tiff"),
        created=p["format"].get("tags", {}).get("com.apple.quicktime.creationdate") or p["format"].get("tags", {}).get("creation_time", ""),
    )


def fmt_time(t):
    """秒 → 0:12.3"""
    return f"{int(t // 60)}:{t % 60:04.1f}"
