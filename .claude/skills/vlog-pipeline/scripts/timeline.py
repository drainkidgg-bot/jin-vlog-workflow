"""时间线：一条 vlog 的口播、分段和画面都写在 outputs/<条>/时间线.json 里，
分镜脚本、口播稿、提词版、样片、精剪都从这一份生成。格式见 vlog-script 的 references/时间线格式.md。

用法：
  python3 timeline.py <时间线.json>                       列出每段的起止、时长和警告
  python3 timeline.py <时间线.json> --docs <目录> [--tag v1]  写出 分镜脚本-<tag>.md 和 口播-<tag>.txt
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import fmt_time, video_info  # noqa: E402

# 英文词按读音折算成几个"字"，没列的按 1.5
EN_WEIGHT = {"AI": 2, "App": 1, "iPhone": 2, "OK": 2, "vlog": 2, "Wi": 1, "Fi": 1}
TAIL = 0.35        # 估时：每段说完留的气口
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".heic")


def project_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".claude")) or os.path.exists(os.path.join(d, "CLAUDE.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.getcwd()
        d = parent


def clauses(text):
    """按 ，。？！；… 切成小段，标点留在段尾。"""
    parts = re.findall(r"[^，。？！；…]+[，。？！；…]*", text or "")
    return [p.strip() for p in parts if p.strip()]


def speak_time(c, cps):
    """估一小段要念多久：中文按字，数字按 0.8 字，英文按词表。"""
    w = len(re.findall(r"[一-鿿]", c)) + 0.8 * len(re.findall(r"\d", c))
    for word in re.findall(r"[A-Za-z]+", c):
        w += EN_WEIGHT.get(word, 1.5)
    pause = 0.3 if c[-1] in "。？！…" else 0.15 if c[-1] in "，；" else 0
    return w / cps + pause


class Timeline:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.root = project_root(os.path.dirname(self.path))
        self.data = json.load(open(self.path, encoding="utf-8"))
        d = self.data
        self.W, self.H = d.get("size", [1080, 1920])
        self.fps = d.get("fps", 30)
        self.cps = d.get("cps", 5.0)
        self.voice = self.abs(d.get("voice"))
        self.follow = self.abs(d.get("follow"))
        self.talk_still = self.abs(d.get("talk_still"))
        self.grade = d.get("grade", "none")
        self.segments = d["segments"]
        self.warnings = []
        self._src_info = {}
        self._compute()

    # ---------- 路径和素材 ----------
    def abs(self, p):
        if not p:
            return None
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def info(self, path):
        if path not in self._src_info:
            self._src_info[path] = video_info(path) if path and os.path.exists(path) else None
        return self._src_info[path]

    def q(self, t):
        """对齐到整帧，避免累积误差让口型跑偏。"""
        return round(t * self.fps) / self.fps

    # ---------- 计算时长 ----------
    def has_vo(self, s):
        return bool(self.voice and s.get("vo") and not s.get("live"))

    def _compute(self):
        t = 0.0
        for i, s in enumerate(self.segments):
            s["_i"] = i
            tempo = s.get("tempo", 1)
            s["_clauses"] = [(c, speak_time(c, self.cps)) for c in clauses(s.get("text", ""))]
            if s.get("live"):
                fixed = sum(self.q(sh["dur"]) for sh in s["shots"] if sh.get("dur"))
                dur = s.get("fixed") or fixed
                if not dur:
                    self.warnings.append(f"「{s['name']}」是现场原声段，要给片段写 dur 或给段写 fixed")
            elif self.has_vo(s):
                a, b = s["vo"]
                s["_speech"] = self.q(b - a)
                dur = s.get("fixed") or s["_speech"] / tempo
            else:
                dur = s.get("fixed") or sum(d for _, d in s["_clauses"]) + TAIL
            s["_dur"] = self.q(dur)
            s["_start"] = self.q(t)
            t += s["_dur"]
            self._layout_shots(s)
        self.total = self.q(t)

    def shot_type(self, sh):
        if sh.get("type"):
            return sh["type"]
        src = sh.get("src", "")
        return "image" if src.lower().endswith(IMAGE_EXTS) else "clip"

    def _layout_shots(self, s):
        shots = s["shots"]
        fixed = [self.q(sh["dur"]) if sh.get("dur") else None for sh in shots]
        free = [i for i, d in enumerate(fixed) if d is None]
        rest = s["_dur"] - sum(d for d in fixed if d)
        if free:
            each = self.q(rest / len(free))
            for k, i in enumerate(free):
                fixed[i] = each if k < len(free) - 1 else self.q(rest - each * (len(free) - 1))
        elif abs(rest) > 0.01:
            fixed[-1] = self.q(fixed[-1] + rest)
        t = s["_start"]
        for sh, d in zip(shots, fixed):
            if d < 1 / self.fps - 1e-6:
                self.warnings.append(f"「{s['name']}」的画面「{sh.get('note', sh.get('src', ''))}」时长不够（{d:.2f}s），减少固定时长的画面")
                d = 1 / self.fps
            sh["_dur"], sh["_start"] = d, t
            t = self.q(t + d)
            kind = self.shot_type(sh)
            sh["_type"] = kind
            if kind in ("clip", "image"):
                path = self.abs(sh["src"])
                inf = self.info(path)
                if not inf:
                    self.warnings.append(f"找不到或读不出素材：{sh['src']}")
                    continue
                if kind == "clip":
                    speed = sh.get("speed", 1)
                    if speed == "fit":
                        speed = max(0.1, (inf["dur"] - sh.get("in", 0)) / d)
                    sh["_speed"] = speed
                    over = sh.get("in", 0) + d * speed - inf["dur"]
                    if over > 0.05:
                        self.warnings.append(f"「{s['name']}」{os.path.basename(path)} 超出素材末尾 {over:.1f}s，会定格最后一帧")

    # ---------- 输出 ----------
    def clause_windows(self, s):
        """每个小段在全片里的起止。有实录时按估时比例分配到实际时长里。"""
        cl = s["_clauses"]
        if not cl:
            return []
        est = sum(d for _, d in cl)
        speak = s["_dur"] if not self.has_vo(s) else min(s["_dur"], s["_speech"] / s.get("tempo", 1))
        scale = speak / est if self.has_vo(s) else 1
        t, out = s["_start"], []
        for i, (c, d) in enumerate(cl):
            end = s["_start"] + s["_dur"] if i == len(cl) - 1 else t + d * scale
            out.append((c, t, end))
            t += d * scale
        return out

    def vis_desc(self, sh):
        k = sh["_type"]
        note = sh.get("note", "")
        if k == "clip":
            sp = sh.get("_speed", 1)
            extra = f"，{sp:g} 倍速" if sp != 1 and sh.get("speed") != "fit" else ""
            return f"{note}（{os.path.basename(sh['src'])} {sh.get('in', 0):.1f}s 起{extra}）"
        if k == "image":
            return f"{note}（{os.path.basename(sh['src'])}）"
        if k == "talk":
            label = note if note.startswith("出镜") else "出镜" + ("：" + note if note else "")
            return label + ("" if self.voice else "【待录】")
        if k == "follow":
            return "结尾关注动效"
        return f"【占位】{note}"

    def sound_desc(self, s):
        if s.get("live"):
            return "现场原声"
        on_cam = any(sh["_type"] == "talk" for sh in s["shots"])
        return "口播（出镜）" if on_cam else "口播"

    def write_docs(self, out_dir, tag):
        title = self.data.get("title", "")
        rows = ["| 时间 | 段 | 画面 | 声音 | 字幕 |", "|---|---|---|---|---|"]
        for s in self.segments:
            vis = "<br>".join(f"{fmt_time(sh['_start'])} {self.vis_desc(sh)}" for sh in s["shots"])
            rows.append(f"| {fmt_time(s['_start'])}–{fmt_time(s['_start'] + s['_dur'])} | {s['name']} | {vis} "
                        f"| {self.sound_desc(s)} | {s.get('text', '')} |")
        basis = "按实录口播" if self.voice else f"按每秒约 {self.cps:g} 字估时，录完口播后会按实录重排"
        notes = self.data.get("notes", "")
        with open(os.path.join(out_dir, f"分镜脚本-{tag}.md"), "w", encoding="utf-8") as f:
            f.write(f"# {title} · 分镜脚本 {tag}\n\n总长 {self.total:.1f} 秒，{basis}。{notes}\n\n" + "\n".join(rows) + "\n")
        with open(os.path.join(out_dir, f"口播-{tag}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(s["text"] for s in self.segments if s.get("text") and not s.get("live")) + "\n")
        return [os.path.join(out_dir, f"分镜脚本-{tag}.md"), os.path.join(out_dir, f"口播-{tag}.txt")]

    def report(self):
        lines = []
        for s in self.segments:
            src = "实录" if self.has_vo(s) else ("原声" if s.get("live") else "估时")
            lines.append(f"{s['_i'] + 1:>2} {s['name']:<8} {fmt_time(s['_start'])}–{fmt_time(s['_start'] + s['_dur'])}  "
                         f"{s['_dur']:5.2f}s [{src}]  {s.get('text', '')}")
            for sh in s["shots"]:
                lines.append(f"      {fmt_time(sh['_start'])} {sh['_dur']:5.2f}s  {self.vis_desc(sh)}")
        lines.append(f"总长 {self.total:.2f}s")
        lines += [f"⚠ {w}" for w in self.warnings]
        return "\n".join(lines)


def save_json(data, path):
    """写回时间线，去掉计算出来的 _ 开头字段。"""
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(data), f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tl = Timeline(sys.argv[1])
    print(tl.report())
    if "--docs" in sys.argv:
        out = sys.argv[sys.argv.index("--docs") + 1]
        tag = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else "v1"
        os.makedirs(out, exist_ok=True)
        for p in tl.write_docs(out, tag):
            print("写出", p)
