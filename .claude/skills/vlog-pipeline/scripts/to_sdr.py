"""把 iPhone 拍的 HDR（HLG / PQ）视频转成 SDR，同时缩到 1080p。不转的话，后面剪出来颜色会发灰、发白。

用法：python3 to_sdr.py <视频>... --out <目录>
  不是 HDR 的文件跳过，后面直接用原件。

macOS 用系统自带的 avconvert（和"照片"导出同一套色调映射），效果最稳。
别的系统需要 ffmpeg 带 zscale 滤镜（libzimg）才能转；没有就提示手动处理。
"""
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import video_info  # noqa: E402


def has_filter(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines() if len(line.split()) > 1)


def convert(src, dst):
    if shutil.which("avconvert"):
        subprocess.run(["avconvert", "-s", os.path.abspath(src), "-p", "Preset1920x1080", "-o", os.path.abspath(dst), "--replace"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif has_filter("zscale"):
        vf = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,"
              "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,scale='if(gt(iw,ih),-2,1080)':'if(gt(iw,ih),1080,-2)'")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf, "-c:v", "libx264", "-crf", "12",
                        "-preset", "fast", "-c:a", "copy", dst])
    else:
        sys.exit("这台机器没有 avconvert，ffmpeg 也没有 zscale，转不了 HDR。可以在手机相册里导出时选「兼容性最佳」，或装带 libzimg 的 ffmpeg。")
    # avconvert 失败时不一定报错，所以以文件为准
    info = video_info(dst) if os.path.exists(dst) else None
    if not info:
        print(f"失败：{src}（没有生成可读的文件，检查路径里有没有特殊字符）")
        return False
    print(f"{os.path.basename(src)} → {dst}  {info['w']}×{info['h']} HDR={info['hdr']}")
    return True


def main():
    if "--out" not in sys.argv:
        sys.exit(__doc__)
    i = sys.argv.index("--out")
    out_dir, srcs = sys.argv[i + 1], sys.argv[1:i] + sys.argv[i + 2:]
    os.makedirs(out_dir, exist_ok=True)
    for src in srcs:
        info = video_info(src)
        if not info or info["image"]:
            continue
        if not info["hdr"]:
            print(f"{os.path.basename(src)} 不是 HDR，跳过")
            continue
        convert(src, os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".mov"))


if __name__ == "__main__":
    main()
