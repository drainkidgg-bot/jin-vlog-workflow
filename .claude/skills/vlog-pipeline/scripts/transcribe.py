"""转写原声或口播，带时间戳（可选逐字时间）。

用法：<venv>/bin/python transcribe.py <音视频>... [--prompt "专有名词，逗号分开"] [--words] [--out <目录>]
  --prompt  素材里会出现的人名、产品名、英文词，能明显减少听错
  --words   同时输出逐字时间（对齐实录口播时要用）
  --out     结果放哪，默认和素材同目录；每个文件出 <名>.json 和 <名>.txt

准备环境（只做一次，放临时目录就行）：
  python3 -m venv <临时目录>/whisper-venv
  Apple 芯片的 Mac：<临时目录>/whisper-venv/bin/pip install mlx-whisper
  其他电脑：         <临时目录>/whisper-venv/bin/pip install faster-whisper
模型用 large-v3-turbo。不要换成 large-v3：嘈杂的现场素材上它会"幻听"出没说过的话。
"""
import json
import os
import subprocess
import sys
import tempfile


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map", "0:a:0", "-ac", "1", "-ar", "16000", dst], check=True)


def transcribe(wav, prompt, words):
    try:
        import mlx_whisper
        r = mlx_whisper.transcribe(wav, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="zh",
                                   initial_prompt=prompt or None, word_timestamps=words)
        return [dict(start=s["start"], end=s["end"], text=s["text"].strip(),
                     words=[dict(word=w["word"], start=w["start"], end=w["end"]) for w in s.get("words", [])])
                for s in r["segments"]]
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("没装转写模型。按本文件开头的说明建 venv 装 mlx-whisper（Apple 芯片）或 faster-whisper，再用 venv 里的 python 跑。")
    model = WhisperModel("large-v3-turbo", compute_type="int8")
    segs, _ = model.transcribe(wav, language="zh", initial_prompt=prompt or None, word_timestamps=words, vad_filter=False)
    return [dict(start=s.start, end=s.end, text=s.text.strip(),
                 words=[dict(word=w.word, start=w.start, end=w.end) for w in (s.words or [])]) for s in segs]


def main():
    files = [a for i, a in enumerate(sys.argv[1:], 1)
             if not a.startswith("--") and sys.argv[i - 1] not in ("--prompt", "--out")]
    if not files:
        sys.exit(__doc__)
    prompt, words, out_dir = arg("--prompt", ""), "--words" in sys.argv, arg("--out")
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        d = out_dir or os.path.dirname(os.path.abspath(f))
        os.makedirs(d, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a.wav")
            try:
                to_wav(f, wav)
            except subprocess.CalledProcessError:
                print(f"== {base}：没有音轨，跳过")
                continue
            segs = transcribe(wav, prompt, words)
        json.dump(dict(source=os.path.abspath(f), segments=segs), open(os.path.join(d, base + ".json"), "w"), ensure_ascii=False, indent=1)
        lines = [f"{s['start']:7.2f}–{s['end']:7.2f}  {s['text']}" for s in segs]
        open(os.path.join(d, base + ".txt"), "w").write("\n".join(lines) + "\n")
        print(f"== {base}")
        print("\n".join(lines) if lines else "（没有识别到说话）")


if __name__ == "__main__":
    main()
