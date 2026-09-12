"""VAD에 **무엇을 들려주느냐**를 잰다 - 다운믹스 대 센터 채널.

2026-09-12에 쓴 측정 도구를 그대로 옮겼다(`mfa_probe.py`와 같은 방식).
결론과 수치는 `checker/vad.py`의 `CENTER_MIN_RMS_RATIO` 위 주석,
`docs/HANDOFF.md` 6절, `docs/BACKLOG.md` 0-T절.

## 왜 필요했나

`vad._read_audio`가 `-ac 1`로 5.1을 한 채널에 섞고 있었다. 실측한 ffmpeg
다운믹스 계수는 FC(대사) 0.293 / FL·FR 0.207 / SL·SR 0.146 - 대사를 가장
많이 깎고 베드 4채널을 합쳐 올린다. 이게 얼마나 손해인지 **정답 경계를 아는
자료**로 재려면 음악이 깔린 한국어 방송 음성에 손 라벨이 있어야 하는데, 그런
공개 자료가 없다(`docs/HANDOFF.md` 8절). 그래서 만들었다.

## 방법

    beds   영상에서 **대사가 없는** 구간을 찾는다. 센터와 비센터를 따로 보고
           둘 다 말이 0인 창만 고른다. (메이드 인 코리아 E02: 센터 28.3%가
           말, 비센터 0.2% - 대사가 센터에 있다는 실측)
    build  Seoul Corpus(손보정 경계) 말소리를 FC에, 위에서 고른 **실제 방송
           베드**를 나머지 채널에 넣어 5.1을 만든다. 같은 파일을 다운믹스와
           센터 추출로 각각 16k 모노로 뽑아 폴더를 나눠 낸다.

정답 경계는 Seoul Corpus 라벨 그대로다 - 말소리를 시간 이동 없이 깔고 베드만
덮으므로 라벨을 손볼 일이 없다(규칙 11: 정답지를 재구성하지 않는다).

**SNR은 다운믹스 도메인에서 정의한다.** 말소리는 다운믹스 전, 베드는 다운믹스
후로 재면 10dB 넘게 어긋난다(2026-09-12에 실제로 틀렸던 자리 - 첫 판은 버렸다).

## 쓰는 법

    python tools/vad_input_probe.py beds <video.mkv>
    python tools/vad_input_probe.py build <video.mkv> <seoul_flac_dir> <out_dir>
    python tools/vad_sweep.py --corpus <out_dir>/dmix_snr10     # 그리고 center_snr10

Seoul Corpus 자료는 저장소 밖이다(openslr.org/113, label 57MB·sound 2.5GB).
`tools/seoul_corpus_to_json.py <TextGrid폴더> <flac폴더>`로 정답 JSON을 먼저 만든다.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from checker.media import _find
from checker.vad import (MIN_SILENCE_MS, MIN_SPEECH_MS, SAMPLE_RATE, THRESHOLD,
                         _probabilities, _spans, find_model)

RATE = 48000                      # 5.1 원본을 다루는 동안의 표본율
WINDOW_S = 60
STEP_S = 30
PANS = {"side": "pan=mono|c0=0.25*FL+0.25*FR+0.25*SL+0.25*SR",
        "center": "pan=mono|c0=FC"}


def ffmpeg_raw(args: list[str]) -> bytes:
    return subprocess.run([_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error"]
                          + args, capture_output=True, check=True).stdout


def read_group(video: Path, which: str) -> np.ndarray:
    raw = ffmpeg_raw(["-i", str(video), "-vn", "-af", PANS[which],
                      "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"])
    return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0


def scan(video: Path, which: str) -> list[tuple[float, float, int]]:
    audio = read_group(video, which)
    total_ms = int(len(audio) / SAMPLE_RATE * 1000)
    print(f"[{which}] {total_ms / 1000:.0f}s, Silero")
    spans = _spans(_probabilities(audio, find_model()), THRESHOLD, MIN_SPEECH_MS,
                   MIN_SILENCE_MS, 0, total_ms)
    speech_ms = sum(e - s for s, e in spans)
    print(f"[{which}] 말 구간 {len(spans)}개 / {speech_ms / 1000:.0f}s"
          f" = 전체의 {speech_ms / total_ms * 100:.1f}%")
    rows = []
    for start_s in range(0, int(total_ms / 1000) - WINDOW_S, STEP_S):
        a, b = start_s * 1000, (start_s + WINDOW_S) * 1000
        inside = sum(min(e, b) - max(s, a) for s, e in spans if s < b and e > a)
        seg = audio[int(a / 1000 * SAMPLE_RATE):int(b / 1000 * SAMPLE_RATE)]
        rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
        rows.append((inside / (b - a), rms, start_s))
    return rows


def beds(video: Path) -> int:
    side = {r[2]: r for r in scan(video, "side")}
    center = {r[2]: r for r in scan(video, "center")}
    quiet = [(start, side[start][1], center[start][1]) for start in sorted(side)
             if side[start][0] == 0 and center.get(start, (1,))[0] == 0]
    quiet.sort(key=lambda r: -(r[1] + r[2]))
    print()
    print(f"둘 다 말이 없는 창({WINDOW_S}초) {len(quiet)}개")
    print(f"  {'시작':>8} {'side RMS':>9} {'center RMS':>11}")
    for start_s, s_rms, c_rms in quiet[:15]:
        print(f"  {start_s:>6}s {s_rms:>9.4f} {c_rms:>11.4f}")
    return 0


def read_mono(path: Path) -> np.ndarray:
    raw = ffmpeg_raw(["-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
                      "-f", "s16le", "-"])
    return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0


def read_6ch(video: Path, start_s: float, length_s: float) -> np.ndarray:
    raw = ffmpeg_raw(["-ss", str(start_s), "-t", str(length_s), "-i", str(video),
                      "-vn", "-ar", str(RATE), "-f", "s16le", "-"])
    return np.frombuffer(raw, dtype=np.int16).astype("float32").reshape(-1, 6) / 32768.0


def write_wav(path: Path, data: np.ndarray, channels: int) -> None:
    pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    subprocess.run([_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error", "-y",
                    "-f", "s16le", "-ar", str(RATE), "-ac", str(channels), "-i", "-",
                    str(path)], input=pcm, check=True)


def downmix(six: np.ndarray, tmp: Path) -> np.ndarray:
    """ffmpeg `-ac 1`이 실제로 내는 다운믹스. 계수를 추측하지 않는다."""
    write_wav(tmp, six.reshape(-1), 6)
    raw = ffmpeg_raw(["-i", str(tmp), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"])
    return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0


def speech_rms(mono: np.ndarray, truth: dict) -> float:
    """라벨된 말소리 구간에서만 잰다 - 침묵을 넣으면 SNR이 왜곡된다."""
    parts = [mono[int(s["start"] * RATE):int(s["end"] * RATE)] for s in truth["segments"]
             if int(s["end"] * RATE) > int(s["start"] * RATE)]
    joined = np.concatenate(parts) if parts else mono
    return float(np.sqrt(np.mean(joined ** 2)))


def trim_truth(truth: dict, seconds: float) -> dict:
    """정답을 앞 `seconds`초로 자른다. 경계에 걸친 구간은 통째로 버린다."""
    out = {"segments": [x for x in truth["segments"] if x["end"] <= seconds],
           "exclude": [{"from": x["from"], "to": min(x["to"], seconds)}
                       for x in truth.get("exclude", []) if x["from"] < seconds]}
    for key in ("in_points", "out_points"):
        if key in truth:
            out[key] = [x for x in truth[key] if x <= seconds]
    return out


def tile(bed: np.ndarray, n: int) -> np.ndarray:
    if len(bed) >= n:
        return bed[:n]
    return np.tile(bed, (int(np.ceil(n / len(bed))), 1))[:n]


def build(a) -> int:
    bed_starts = [float(x) for x in a.beds.split(",")]
    snrs = [float(x) for x in a.snr.split(",")]
    clips = [p for p in sorted(a.flac.iterdir())
             if p.suffix.lower() in (".flac", ".wav") and p.with_suffix(".json").is_file()]
    clips = clips[:a.limit]
    if not clips:
        print("flac+json 짝을 찾지 못했습니다 - seoul_corpus_to_json.py를 먼저 돌립니다")
        return 1

    folders = {"clean": a.out / "clean"}
    for snr in snrs:
        folders[f"dmix_snr{snr:g}"] = a.out / f"dmix_snr{snr:g}"
        folders[f"center_snr{snr:g}"] = a.out / f"center_snr{snr:g}"
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    tmp6 = a.out / "_tmp6.wav"

    cache: dict[float, np.ndarray] = {}
    for i, clip in enumerate(clips):
        truth = json.loads(clip.with_suffix(".json").read_text(encoding="utf-8"))
        speech = read_mono(clip)
        if a.seconds:
            speech = speech[:int(a.seconds * RATE)]
            truth = trim_truth(truth, a.seconds)
        bed_start = bed_starts[i % len(bed_starts)]
        if bed_start not in cache:
            cache[bed_start] = read_6ch(a.video, bed_start, a.bed_seconds)
        bed = tile(cache[bed_start], len(speech))

        speech6 = np.zeros_like(bed)
        speech6[:, 2] = speech                       # FC
        s_rms = speech_rms(downmix(speech6, tmp6), truth)
        b_rms = float(np.sqrt(np.mean(downmix(bed, tmp6) ** 2)))

        truth_text = json.dumps(truth)
        write_wav(folders["clean"] / (clip.stem + ".wav"), speech, 1)
        (folders["clean"] / (clip.stem + ".json")).write_text(truth_text, encoding="utf-8")

        for snr in snrs:
            gain = s_rms / (10 ** (snr / 20.0) * b_rms) if b_rms > 0 else 0.0
            mix = bed * gain
            mix[:, 2] += speech
            peak = float(np.max(np.abs(mix)))
            if peak > 0.99:
                mix = mix * (0.99 / peak)
            write_wav(tmp6, mix.reshape(-1), 6)
            for name, args in ((f"dmix_snr{snr:g}", ["-ac", "1"]),
                               (f"center_snr{snr:g}", ["-af", "pan=mono|c0=FC"])):
                subprocess.run([_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error",
                                "-y", "-i", str(tmp6)] + args
                               + ["-ar", str(SAMPLE_RATE),
                                  str(folders[name] / (clip.stem + ".wav"))], check=True)
                (folders[name] / (clip.stem + ".json")).write_text(truth_text,
                                                                  encoding="utf-8")
        print(f"  [{i + 1}/{len(clips)}] {clip.stem} {len(speech) / RATE:.0f}s "
              f"bed@{bed_start:g}s 말 {s_rms:.4f} 베드 {b_rms:.4f}")
    if tmp6.exists():
        tmp6.unlink()
    print("다음: python tools/vad_sweep.py --corpus <위 폴더들>")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("beds", help="대사 없는 구간을 찾는다")
    b.add_argument("video", type=Path)
    c = sub.add_parser("build", help="합성 자료를 만든다")
    c.add_argument("video", type=Path)
    c.add_argument("flac", type=Path, help="Seoul flac + json 폴더")
    c.add_argument("out", type=Path)
    c.add_argument("--beds", default="480,3420,180")
    c.add_argument("--bed-seconds", type=float, default=60.0)
    c.add_argument("--snr", default="15,10,5,0")
    c.add_argument("--limit", type=int, default=15)
    c.add_argument("--seconds", type=float, default=180.0)
    a = ap.parse_args()
    return beds(a.video) if a.mode == "beds" else build(a)


if __name__ == "__main__":
    raise SystemExit(main())
