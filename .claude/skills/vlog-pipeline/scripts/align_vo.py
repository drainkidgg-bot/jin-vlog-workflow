"""把实录口播逐段对上时间线：找出每段话在录音里的起止，写进时间线的 vo。

用法：
  1. 先转写实录（要逐字时间）：<venv>/bin/python transcribe.py <实录.MOV> --words --prompt "专有名词" --out <目录>
  2. python3 align_vo.py <时间线.json> <实录.json> [--pad 0.1] [--noise -35] [--write]
       --pad    每段前后留多少静音（秒）。默认 0.1，两段之间合起来约 0.2 秒，是已验证的节奏
       --noise  静音检测的门限（dB），录音底噪大就调高，比如 -30
       --write  把结果写回时间线（同时写 voice）。不加只打印，先看一遍

对齐方法：转写的逐字时间给出大致位置，再吸附到附近的静音边界上，避免切到字。
打印结果里要看三样：
  - 每段的「实际说的」和稿子差在哪：录的时候改了词，以实录为准改时间线的 text（字幕要跟实录一致）
  - 「没对上的录音」：开头的语气词、重录的句子、NG。同一句录了几遍，一般用最后一遍，手动改 vo
  - 覆盖率低于 70% 的段：多半对错了位置，要人工核对
"""
import difflib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeline import Timeline, save_json  # noqa: E402


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def norm(s):
    return re.sub(r"[^\w]", "", s or "").lower().replace("_", "")


def silences(path, noise, min_d=0.15):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-map", "0:a:0", "-af", f"silencedetect=noise={noise}dB:d={min_d}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends + [1e9] * (len(starts) - len(ends))))


def main():
    pos = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("--") and sys.argv[i - 1] not in ("--pad", "--noise")]
    if len(pos) < 2:
        sys.exit(__doc__)
    tl = Timeline(pos[0])
    tr = json.load(open(pos[1], encoding="utf-8"))
    pad, noise = float(arg("--pad", 0.1)), float(arg("--noise", -35))
    voice = tl.voice or tr["source"]

    # 录音的逐字流：每个字带起止时间
    chars = []
    for seg in tr["segments"]:
        for w in seg.get("words", []):
            n = norm(w["word"])
            for k, ch in enumerate(n):
                span = (w["end"] - w["start"]) / max(1, len(n))
                chars.append((ch, w["start"] + span * k, w["start"] + span * (k + 1)))
    if not chars:
        sys.exit("转写里没有逐字时间，转写时加 --words")
    stream = "".join(c for c, _, _ in chars)

    # 稿子的字流，记下每个字属于哪一段
    segs = [s for s in tl.segments if not s.get("live")]
    script, owner = "", []
    for k, s in enumerate(segs):
        n = norm(s.get("text"))
        script += n
        owner += [k] * len(n)

    hit = {}  # 段 → 对上的录音字下标
    for blk in difflib.SequenceMatcher(None, script, stream, autojunk=False).get_matching_blocks():
        for j in range(blk.size):
            hit.setdefault(owner[blk.a + j], []).append(blk.b + j)

    sil = silences(voice, noise)
    used, rows, prev_end_idx = set(), [], -1
    for k, s in enumerate(segs):
        idx = sorted(i for i in hit.get(k, []) if i > prev_end_idx)
        total = len(norm(s.get("text")))
        if not idx:
            rows.append((s, None, None, 0, ""))
            continue
        i0, i1 = idx[0], idx[-1]
        prev_end_idx = i1
        used.update(range(i0, i1 + 1))
        a0, b0 = chars[i0][1], chars[i1][2]
        lo = chars[i0 - 1][2] if i0 > 0 else 0          # 不能切进上一个字
        hi = chars[i1 + 1][1] if i1 + 1 < len(chars) else 1e9
        a = next((max(e - pad, st) for st, e in sil if a0 - 0.4 <= e <= a0 + 0.15), a0 - pad)
        b = next((min(st + pad, e) for st, e in sil if b0 - 0.15 <= st <= b0 + 0.4), b0 + pad)
        a, b = max(a, lo, 0), min(b, hi)
        said = "".join(c for c, _, _ in chars[i0:i1 + 1])
        rows.append((s, round(a, 2), round(b, 2), len(idx) / max(1, total), said))

    print("| 段 | 入 | 出 | 覆盖 | 稿子 | 实际说的（归一化，无标点） |\n|---|---|---|---|---|---|")
    for s, a, b, cov, said in rows:
        flag = " ⚠" if cov < 0.7 else ""
        a_s = "—" if a is None else f"{a:.2f}"
        b_s = "—" if b is None else f"{b:.2f}"
        print(f"| {s['name']} | {a_s} | {b_s} | {cov:.0%}{flag} | {s.get('text', '')} | {said} |")

    # 没归到任何段的录音
    gaps, cur = [], []
    for i, c in enumerate(chars):
        if i in used:
            if cur:
                gaps.append(cur)
            cur = []
        else:
            cur.append(c)
    if cur:
        gaps.append(cur)
    if gaps:
        print("\n没对上的录音（语气词、重录、NG，自己判断要不要用）：")
        for g in gaps:
            print(f"  {g[0][1]:6.2f}–{g[-1][2]:6.2f}  {''.join(c for c, _, _ in g)}")

    if "--write" in sys.argv:
        rel = os.path.relpath(voice, tl.root) if voice.startswith(tl.root) else voice
        tl.data["voice"] = tl.data.get("voice") or rel
        for s, a, b, _, _ in rows:
            if a is not None:
                s["vo"] = [a, b]
        save_json(tl.data, tl.path)
        print(f"\n已写回 {tl.path}。再跑 timeline.py 看新的总长。")


if __name__ == "__main__":
    main()
