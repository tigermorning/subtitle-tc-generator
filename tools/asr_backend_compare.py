"""전사 백엔드 후보를 **같은 TC 창에 넣어** whisper와 견준다.

## 왜 이 방식인가

"저 모델이 whisper보다 낫지 않냐"는 질문은 계속 온다(2026-09-10에는
Qwen3-ASR-1.7B였다). 그때마다 맨손으로 재려 하면 두 가지를 헷갈리게 된다 —
**TC가 달라서 생긴 차이**와 **받아 적은 글자가 달라서 생긴 차이**다.

그래서 이 도구는 TC를 whisper 것으로 **고정**하고, 그 창(window) 안의 오디오만
후보 모델에 다시 넣어 텍스트만 갈아 끼운다. 두 결과의 타임코드가 완전히 같으니
`checker --against`로 정답지와 대조할 때 달라지는 변수가 ASR 텍스트 하나뿐이다.

**둘 다 정답지를 기준으로만 잰다. 서로 비교하지 않는다**(CLAUDE.md 규칙 13 —
"이 값이 저 값보다 나은가"를 묻지 않고 "정답과 어디가 다른가"만 묻는다).

## 이 설계가 못 재는 것 (결과에 반드시 같이 적는다)

- **창 경계를 whisper가 정했으므로 whisper에 유리하다.** 후보 모델은 창 밖
  문맥을 못 본다.
- **반복 환각을 못 잰다.** 창 단위로 도니 문맥 이월 자체가 불가능하다 —
  후보 쪽 "반복 0건"은 실력이 아니라 창 나눔이 만든 착시다.
- **TC 품질을 못 잰다.** TC는 양쪽 다 whisper 것이다. 후보 모델이 TC를 스스로
  내는지(Qwen3-ASR은 안 낸다 — 별도 forced aligner 필요)는 이 도구 밖에서
  따로 확인한다.

## 쓰는 법

    # ① whisper 기준선 — 프로젝트 자체 전사 함수를 그대로 부른다
    python tools/asr_backend_compare.py baseline VIDEO.mkv --language ko --out whisper.srt

    # ② 후보 모델을 그 창에 넣는다 (16kHz 모노 wav가 필요하다)
    ffmpeg -i VIDEO.mkv -map 0:1 -ac 1 -ar 16000 -c:a pcm_s16le audio.wav
    python tools/asr_backend_compare.py alt audio.wav --windows whisper.srt \\
        --language ko --out qwen.srt

    # ③ 둘 다 정답지에 대고 잰다
    python -m checker.cli whisper.srt --against 정답.srt -p disney -k sdh
    python -m checker.cli qwen.srt   --against 정답.srt -p disney -k sdh

①은 이미 뽑아 둔 전사가 있으면 건너뛴다 — `학습한 TC 및 자막 모음/
_whisper_cache/`의 srt가 그대로 창이 된다. 그러면 GPU 몇 분이면 끝난다.

`alt`가 내는 `<out>.json`에는 창마다 **모델이 판정한 언어**가 함께 남는다.
언어 힌트를 무시하는 모델이 있어서다(2026-09-10 실측: Qwen3-ASR에
`--language ko`를 줘도 778창 중 205창을 한국어 아님으로 판정했다). 그 json으로
"같은 언어로 판정한 창만" 추려 다시 재면 언어 판정 문제와 전사 품질 문제를
가를 수 있다.

## 실제 결과

2026-09-10에 Qwen3-ASR-1.7B를 이걸로 재고 기각했다. 숫자와 기각 사유는
`docs/HANDOFF.md` 5절 "전사 백엔드 교체 검토"에 있다 — **다시 검토하기 전에
거기부터 읽는다**(규칙 17).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SR = 16000
"""후보 모델에 넣는 표본율. whisper 계열과 같은 16kHz 모노로 맞춘다."""


def parse_srt(text: str) -> list[tuple[int, int, str]]:
    """srt 본문에서 (시작ms, 끝ms, 텍스트)를 뽑는다.

    `checker/align.py`의 파서를 쓰지 않는다 — 저쪽은 자막 파일을 검사용 모델로
    올리는 물건이고 여기서는 **창 목록**만 필요하다. 시간이 없는 블록은 버린다.
    """
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        m = re.search(r"(\d+):(\d\d):(\d\d)[,.](\d\d\d)\s*-->\s*"
                      r"(\d+):(\d\d):(\d\d)[,.](\d\d\d)", lines[idx])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
        end = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
        body = " ".join(lines[idx + 1:]).strip()
        if body:
            out.append((start, end, body))
    return out


def ms_to_srt(ms: int) -> str:
    ms = max(0, ms)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"


def write_srt(path: Path, cues: list[tuple[int, int, str]]) -> int:
    """빈 텍스트는 버리고 번호를 다시 매겨 쓴다."""
    kept = [(s, e, t) for s, e, t in cues if t.strip()]
    path.write_text(
        "\n".join(f"{n}\n{ms_to_srt(s)} --> {ms_to_srt(e)}\n{t}\n"
                  for n, (s, e, t) in enumerate(kept, 1)),
        encoding="utf-8")
    return len(kept)


def load_wav(path: Path):
    """16kHz 모노 16bit wav만 받는다.

    soundfile·librosa를 안 쓴다 — 이 도구 하나 때문에 의존성을 늘리지 않는다.
    표준 라이브러리 `wave`로 충분하고, 형식이 다르면 조용히 리샘플하는 대신
    **여기서 막는다**(잘못된 표본율로 잰 결과가 나중에 근거로 쓰이면 더 나쁘다).
    """
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SR, 1, 2):
            raise SystemExit(
                f"{path.name}: 16000Hz 모노 16bit wav가 필요합니다 "
                f"(지금 {w.getframerate()}Hz, {w.getnchannels()}채널, "
                f"{w.getsampwidth() * 8}bit). ffmpeg으로 다시 뽑으세요:\n"
                f"  ffmpeg -i VIDEO -map 0:1 -ac 1 -ar 16000 -c:a pcm_s16le out.wav")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def cmd_baseline(args: argparse.Namespace) -> None:
    """프로젝트 자체 전사 함수로 기준선을 뽑는다.

    직접 faster-whisper를 부르지 않는다 — `condition_on_previous_text=False`나
    `hallucination_silence_threshold` 같은 설정이 실제 파이프라인과 어긋나면
    비교 자체가 무의미해진다. `checker/transcribe.py`가 유일한 출처다.
    """
    from checker.transcribe import _faster_whisper_transcribe

    t0 = time.time()
    segments = _faster_whisper_transcribe(
        args.video, args.language, not args.cpu, lambda m: print(m, flush=True))
    if segments is None:
        raise SystemExit("faster-whisper를 못 불러왔습니다 — 위 메시지를 보세요.")
    n = write_srt(args.out, [(s.start_ms, s.end_ms, s.text) for s in segments])
    print(f"{args.out} 자막 {n}개, {time.time() - t0:.0f}초", flush=True)


def cmd_alt(args: argparse.Namespace) -> None:
    """후보 모델을 whisper 창에 넣어 텍스트만 갈아 끼운다."""
    import numpy as np
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    windows = parse_srt(args.windows.read_text(encoding="utf-8-sig"))
    if args.limit_ms:
        windows = [w for w in windows if w[1] <= args.limit_ms]
    audio = load_wav(args.wav)
    print(f"창 {len(windows)}개, 오디오 {len(audio) / SR / 60:.1f}분", flush=True)

    t0 = time.time()
    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForMultimodalLM.from_pretrained(
        args.model, dtype=torch.float16, device_map="cpu" if args.cpu else "cuda")
    model.eval()
    print(f"모델 적재 {time.time() - t0:.1f}초", flush=True)

    texts: list[str] = []
    langs: list[str] = []
    t0 = time.time()
    for i in range(0, len(windows), args.batch):
        clips = []
        for start, end, _ in windows[i:i + args.batch]:
            a = max(0, int((start - args.pad_ms) / 1000 * SR))
            b = min(len(audio), int((end + args.pad_ms) / 1000 * SR))
            clip = audio[a:b]
            if len(clip) < SR // 10:  # 0.1초보다 짧으면 모델이 거부한다
                clip = np.pad(clip, (0, SR // 10 - len(clip)))
            clips.append(clip)
        inputs = processor.apply_transcription_request(
            audio=clips, language=args.language).to(model.device, model.dtype)
        with torch.inference_mode():
            out_ids = model.generate(**inputs, max_new_tokens=args.max_new_tokens,
                                     do_sample=False)
        for decoded in processor.batch_decode(
                out_ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True):
            lang, body = split_language_tag(decoded)
            langs.append(lang)
            texts.append(re.sub(r"\s+", " ", body).strip())
        done = min(i + args.batch, len(windows))
        rate = (time.time() - t0) / done
        print(f"  {done}/{len(windows)}  ({rate:.2f}초/창, "
              f"남은 {rate * (len(windows) - done) / 60:.1f}분)", flush=True)

    n = write_srt(args.out, [(s, e, t) for (s, e, _), t in zip(windows, texts)])
    args.out.with_suffix(".json").write_text(
        json.dumps([{"start": w[0], "end": w[1], "lang": l, "text": t}
                    for w, l, t in zip(windows, langs, texts)],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("판정 언어:", Counter(langs).most_common(8), flush=True)
    print(f"{args.out} 자막 {n}개, {time.time() - t0:.0f}초", flush=True)


def split_language_tag(decoded: str) -> tuple[str, str]:
    """`language Korean<asr_text>…` 꼴에서 판정 언어와 본문을 가른다.

    Qwen3-ASR의 출력 형식이다. 형식이 다른 모델이면 통째로 본문으로 본다 —
    **조용히 앞부분을 잘라내지 않는다**(잘못 자르면 전사가 짧아진 것을
    모델 탓으로 오해하게 된다).
    """
    m = re.match(r"\s*language\s+(\S+?)<asr_text>(.*)", decoded, re.S)
    return (m.group(1), m.group(2)) if m else ("?", decoded)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="whisper 기준선 srt를 뽑는다")
    b.add_argument("video", type=Path)
    b.add_argument("--language", default="auto")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--cpu", action="store_true")
    b.set_defaults(func=cmd_baseline)

    a = sub.add_parser("alt", help="후보 모델을 whisper 창에 넣는다")
    a.add_argument("wav", type=Path, help="16kHz 모노 16bit wav")
    a.add_argument("--windows", type=Path, required=True, help="whisper 전사 srt")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B-hf")
    a.add_argument("--language", default=None,
                   help="언어 힌트. 모델이 무시할 수 있다 — 결과 json의 판정 언어를 볼 것")
    a.add_argument("--limit-ms", type=int, default=0, help="0이면 전체")
    a.add_argument("--pad-ms", type=int, default=0,
                   help="창 앞뒤 여유. 0이 아니면 창이 겹쳐 말이 두 번 나올 수 있다")
    a.add_argument("--batch", type=int, default=8)
    a.add_argument("--max-new-tokens", type=int, default=192)
    a.add_argument("--cpu", action="store_true")
    a.set_defaults(func=cmd_alt)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
