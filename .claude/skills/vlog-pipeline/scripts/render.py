"""按时间线渲染样片或精剪。

用法：
  python3 render.py <时间线.json> <输出.mp4> --draft [--label "样片 v1 · 占位版"]
      样片：没录的出镜和没做的画面用占位卡，烧进参考字幕和版本标签，用来对节奏
  python3 render.py <时间线.json> <输出.mp4>
      精剪：要求口播已录好、每段都对齐了（align_vo.py）；无字幕、无标签，含口播和现场原声
  加 --keep 保留中间文件（默认渲染完删掉）

画质做法（来自已验证的成片）：
  - 每个镜头先单独渲染成接近无损的中间片（crf 10），最后只压缩一次，避免二次压缩掉画质
  - 需要放大的素材（比如微信压过的 720p）先轻降噪去块，用 lanczos 放大，再自适应锐化（cas）
  - 不用 AI 超分：人脸会被"脑补"得不像本人
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageEnhance  # noqa: E402
from common import ffmpeg, font  # noqa: E402
from timeline import Timeline  # noqa: E402

DENOISE = {"light": "hqdn3d=1.5:1.5:3:3", "strong": "hqdn3d=2.5:2.5:4:4"}
GRADE = {"light": "curves=all='0/0 0.25/0.21 0.5/0.5 0.75/0.8 1/1',eq=saturation=1.08"}
YELLOW = (255, 214, 10)


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


class Renderer:
    def __init__(self, tl, draft, work):
        self.tl, self.draft, self.work = tl, draft, work
        self.W, self.H, self.fps = tl.W, tl.H, tl.fps

    # ---------- 占位卡 ----------
    def wrap(self, text, fnt, max_w):
        lines, cur = [], ""
        for ch in text:
            if cur and fnt.getlength(cur + ch) > max_w and ch not in "，。？！；、":
                lines.append(cur)
                cur = ""
            cur += ch
        return lines + ([cur] if cur else [])

    def pill(self, d, cx, cy, text, fnt, bg, fg):
        tw = fnt.getlength(text)
        box = (cx - tw / 2 - 30, cy - fnt.size / 2 - 16, cx + tw / 2 + 30, cy + fnt.size / 2 + 22)
        d.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=bg)
        d.text((cx - tw / 2, cy - fnt.size / 2), text, font=fnt, fill=fg)

    def placeholder_png(self, title, note, path, still=None):
        W, H = self.W, self.H
        if still:
            im = Image.open(still).convert("RGB").resize((W, H))
            im = ImageEnhance.Brightness(im).enhance(0.6)
        else:
            im = Image.new("RGB", (W, H), (22, 22, 24))
        d = ImageDraw.Draw(im)
        self.pill(d, W / 2, H * 0.3, f"占位 · {title}", font(46), YELLOW, (0, 0, 0))
        f = font(38, "medium")
        for i, line in enumerate(self.wrap(note or "", f, W * 0.8)):
            d.text((W / 2, H * 0.3 + 110 + i * 56), line, font=f, fill=(255, 255, 255), anchor="mm")
        im.save(path)
        return path

    # ---------- 单个镜头 ----------
    def layout(self, sh, inf):
        """返回 filter_complex 片段：输入 [v0]，输出 [v1]。"""
        W, H = self.W, self.H
        w, h = (inf["w"], inf["h"]) if inf else (W, H)
        mode = sh.get("layout", "auto")
        if mode == "auto":
            mode = "fill" if abs(w / h - W / H) < 0.15 else "band"
        up = max(W / w, H / h) if mode == "fill" else W / w
        auto = up > 1.15
        dn = sh.get("denoise", "auto")
        dn = DENOISE.get("light" if dn == "auto" and auto else dn, "")
        sharpen = sh.get("sharpen", "auto")
        sharpen = (0.5 if auto else 0) if sharpen == "auto" else sharpen
        cas = f",cas={sharpen}" if sharpen else ""
        pre = f"{dn}," if dn else ""
        if mode == "fill":
            return (f"[v0]{pre}scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}{cas}[v1]")
        # band：横屏素材放中间，背景是同一画面放大、模糊、压暗
        cy = sh.get("cy", H // 2)
        return (f"[v0]{pre}split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"gblur=sigma=40,eq=brightness=-0.18[bg];[b]scale={W}:-2:flags=lanczos{cas}[fg];"
                f"[bg][fg]overlay=(W-w)/2:{cy}-h/2[v1]")

    def shot_video(self, s, sh, out):
        tl, fps = self.tl, self.fps
        dur, kind = sh["_dur"], sh["_type"]
        frames = max(1, round(dur * fps))
        inputs, speed, inf = [], 1, None
        if kind == "talk" and tl.has_vo(s):
            tempo = s.get("tempo", 1)
            t_in = s["vo"][0] + (sh["_start"] - s["_start"]) * tempo
            inputs, speed, inf = ["-ss", f"{t_in:.4f}", "-i", tl.voice], tempo, tl.info(tl.voice)
        elif kind == "clip":
            src = tl.abs(sh["src"])
            speed, inf = sh.get("_speed", 1), tl.info(src)
            inputs = ["-ss", f"{sh.get('in', 0):.4f}", "-i", src]
        elif kind in ("image", "follow"):
            src = tl.abs(sh["src"]) if kind == "image" else tl.follow
            if not src:
                sys.exit("时间线里没写 follow（结尾关注动效）的路径")
            inf = tl.info(src)
            inputs = (["-loop", "1"] if kind == "image" else []) + ["-i", src]
        else:  # placeholder，或还没录的出镜
            if kind == "talk":
                png = self.placeholder_png("出镜待录", sh.get("note", s.get("text", "")),
                                           os.path.join(self.work, f"ph-{id(sh)}.png"), tl.talk_still)
            else:
                png = self.placeholder_png(sh.get("title", "画面待做"), sh.get("note", ""),
                                           os.path.join(self.work, f"ph-{id(sh)}.png"))
            inputs, inf = ["-loop", "1", "-i", png], {"w": self.W, "h": self.H}
        chain = [f"[0:v]setpts=(PTS-STARTPTS)/{speed}[v0]" if speed != 1 else "[0:v]null[v0]", self.layout(sh, inf)]
        last = "v1"
        if tl.grade in GRADE:
            chain.append(f"[{last}]{GRADE[tl.grade]}[g]")
            last = "g"
        for k, (x, y, w, h) in enumerate(sh.get("blur", [])):
            r = max(1, min(12, min(w, h) // 4))
            chain.append(f"[{last}]split[m{k}][c{k}];[c{k}]crop={w}:{h}:{x}:{y},boxblur={r}:2[b{k}];[m{k}][b{k}]overlay={x}:{y}[o{k}]")
            last = f"o{k}"
        chain.append(f"[{last}]fps={fps},setsar=1,tpad=stop_mode=clone:stop_duration=30,format=yuv420p[v]")
        ffmpeg(*inputs, "-filter_complex", ";".join(chain), "-map", "[v]", "-frames:v", str(frames), "-r", str(fps),
               "-c:v", "libx264", "-crf", "10", "-preset", "fast", "-an", out)

    def shot_audio(self, sh, out):
        """镜头自带的声音（现场原声、环境声），音量按 audio 字段，默认静音。"""
        dur, vol = sh["_dur"], sh.get("audio", 0)
        src = self.tl.abs(sh.get("src")) if sh["_type"] == "clip" else None
        inf = self.tl.info(src) if src else None
        if vol and inf and inf["has_audio"]:
            speed = sh.get("_speed", 1)
            tempo = []
            while speed > 2:
                tempo.append("atempo=2")
                speed /= 2
            while speed < 0.5:
                tempo.append("atempo=0.5")
                speed /= 0.5
            if abs(speed - 1) > 1e-3:
                tempo.append(f"atempo={speed:.4f}")
            af = ",".join(tempo + [f"volume={vol}", "aformat=sample_rates=48000:channel_layouts=stereo",
                                   "afade=t=in:d=0.02", "apad", f"atrim=0:{dur:.4f}",
                                   f"afade=t=out:st={max(0, dur - 0.04):.4f}:d=0.04"])
            ffmpeg("-ss", f"{sh.get('in', 0):.4f}", "-i", src, "-map", "0:a:0", "-af", af, "-c:a", "pcm_s16le", out)
        else:
            ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur:.4f}", "-c:a", "pcm_s16le", out)

    # ---------- 口播 ----------
    def voice_track(self, out):
        """从实录里按段截口播，句间留白已在 vo 入出点里定好；可单段变速（不变调）。"""
        tl = self.tl
        parts = []
        for s in tl.segments:
            p = os.path.join(self.work, f"vo-{s['_i']:02d}.wav")
            dur = s["_dur"]
            if tl.has_vo(s):
                a, tempo = s["vo"][0], s.get("tempo", 1)
                spoken = s["_speech"] / tempo
                af = (f"atrim={a:.4f}:{a + s['_speech']:.4f},asetpts=PTS-STARTPTS,"
                      + (f"atempo={tempo}," if tempo != 1 else "")
                      + f"afade=t=in:d=0.03,afade=t=out:st={max(0, spoken - 0.06):.4f}:d=0.06,"
                      f"aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={dur:.4f},atrim=0:{dur:.4f}")
                ffmpeg("-i", tl.voice, "-map", "0:a:0", "-af", af, "-c:a", "pcm_s16le", p)
            else:
                ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur:.4f}", "-c:a", "pcm_s16le", p)
            parts.append(p)
        return concat(parts, out, self.work, "vo")

    # ---------- 样片的参考字幕和标签 ----------
    def caption_png(self, text, path):
        im = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f = font(60)
        lines = self.wrap(text.rstrip("，。；"), f, self.W * 0.83)
        top = self.H * 0.745 - 78 * len(lines) / 2
        for i, line in enumerate(lines):
            d.text((self.W / 2, top + i * 78), line, font=f, fill=(255, 255, 255), anchor="mt", stroke_width=5, stroke_fill=(0, 0, 0))
        im.save(path)

    def label_png(self, text, path):
        im = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        f = font(28, "medium")
        tw = f.getlength(text)
        d.rounded_rectangle((36, 36, 72 + tw, 88), radius=26, fill=(0, 0, 0, 150))
        d.text((54, 44), text, font=f, fill=(255, 255, 255, 230))
        im.save(path)

    def overlays(self, video, label, out):
        inputs, chain, last, n = ["-i", video], [], "0:v", 1
        if label:
            p = os.path.join(self.work, "label.png")
            self.label_png(label, p)
            inputs += ["-i", p]
            chain.append(f"[{last}][{n}:v]overlay=0:0[l{n}]")
            last, n = f"l{n}", n + 1
        for s in self.tl.segments:
            for ci, (c, a, b) in enumerate(self.tl.clause_windows(s)):
                p = os.path.join(self.work, f"cap-{s['_i']}-{ci}.png")
                self.caption_png(c, p)
                inputs += ["-i", p]
                chain.append(f"[{last}][{n}:v]overlay=0:0:enable='between(t,{a:.3f},{b - 0.001:.3f})'[l{n}]")
                last, n = f"l{n}", n + 1
        if not chain:
            return video
        ffmpeg(*inputs, "-filter_complex", ";".join(chain), "-map", f"[{last}]", "-c:v", "libx264", "-crf", "10",
               "-preset", "fast", out)
        return out

    def run(self, out, label):
        tl = self.tl
        vids, auds = [], []
        for s in tl.segments:
            for k, sh in enumerate(s["shots"]):
                v = os.path.join(self.work, f"s{s['_i']:02d}-{k}.mp4")
                a = os.path.join(self.work, f"s{s['_i']:02d}-{k}.wav")
                self.shot_video(s, sh, v)
                self.shot_audio(sh, a)
                vids.append(v)
                auds.append(a)
                print(f"  {s['name']} {k + 1}/{len(s['shots'])}", flush=True)
        video = concat(vids, os.path.join(self.work, "video.mp4"), self.work, "v")
        ambient = concat(auds, os.path.join(self.work, "ambient.wav"), self.work, "a")
        if self.draft:
            video = self.overlays(video, label, os.path.join(self.work, "video-cap.mp4"))
        if tl.voice:
            vo = self.voice_track(os.path.join(self.work, "vo.wav"))
            af = ("[1:a]highpass=f=70,afftdn=nr=8[vo];[vo][2:a]amix=inputs=2:normalize=0:duration=first,"
                  "loudnorm=I=-16:TP=-1.5:LRA=11[a]")
            ins = ["-i", video, "-i", vo, "-i", ambient]
        else:
            af = "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[a]"
            ins = ["-i", video, "-i", ambient]
        ffmpeg(*ins, "-filter_complex", af, "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-crf", "16",
               "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-t", f"{tl.total:.4f}", "-movflags", "+faststart", out)
        return out


def concat(parts, out, work, tag):
    lst = os.path.join(work, f"concat-{tag}.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out)
    return out


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] != "--label"]
    if len(pos) < 2:
        sys.exit(__doc__)
    tl = Timeline(pos[0])
    draft = "--draft" in sys.argv
    print(tl.report())
    if not draft:
        missing = [s["name"] for s in tl.segments if not s.get("live") and not tl.has_vo(s)]
        if missing:
            sys.exit(f"精剪需要实录口播：时间线里写 voice，并用 align_vo.py 给这些段对齐 vo：{'、'.join(missing)}。只想看节奏就加 --draft")
        ph = [s["name"] for s in tl.segments for sh in s["shots"] if sh["_type"] == "placeholder"]
        if ph:
            print(f"⚠ 精剪里还有占位画面：{'、'.join(ph)}。交付前换成真画面，或在文件名里写明「占位」")
    if any(w.startswith("找不到") for w in tl.warnings):
        sys.exit("有素材找不到，先修好路径")
    work = tempfile.mkdtemp(prefix="vlog-render-")
    try:
        out = Renderer(tl, draft, work).run(os.path.abspath(pos[1]), arg("--label", "样片 · 占位版 · 字幕仅供参考" if draft else ""))
        print("输出", out, f"{tl.total:.2f}s")
    finally:
        if "--keep" in sys.argv:
            print("中间文件在", work)
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
