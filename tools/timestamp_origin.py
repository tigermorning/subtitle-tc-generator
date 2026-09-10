"""라벨 JSON의 start/end가 **말소리 경계인지** 가린다.

## 왜 필요한가

이 판별이 데이터셋 채택 여부를 통째로 가른다. `checker/vad.py`의 문턱값을
정답과 견줘 고르려면(`tools/vad_sweep.py`), 그 정답이 **사람이 소리를 듣고 찍은
말의 시작·끝**이어야 한다. 아니면 엉뚱한 기준에 맞춰 튜닝하게 된다.

## 실제로 이 도구가 잡아낸 것 (2026-09-10)

AI Hub 71699(한국어 텍스트-비디오-사운드)를 이걸로 봤다. 결론은 "사람이냐
기계냐" 이전이었다 — **애초에 말소리 경계가 아니었다.** 구간이 클립을 빈틈없이
덮고(첫 구간 30/30이 정확히 0.000), 구간 사이 간격의 95%가 정확히 10ms였다.
전사 텍스트를 문장 단위로 자른 **분할점**이지 말이 시작·끝난 자리가 아니다.
ffmpeg `silencedetect`로 대 보니 실제 무음과 1~2초까지 어긋났다.

그래서 지문 목록에 C(이어붙임)와 C2(전체 덮음)가 있다. **처음엔 없었고, 그래서
한 번 놓쳤다** — 처음 판은 `end[i] == start[i+1]`(간격 0)만 봤는데 이 자료는
간격이 0이 아니라 10ms로 **일정**했다. 0인지가 아니라 한 값에 쏠렸는지를 본다.

## 무엇을 보나

    A. 양자화     값 mod 10ms / 20ms(whisper hop) / 프레임격자의 쏠림
    B. 자릿수     .0 / .5 쏠림 = 사람의 러프 입력, 균등 = 기계
    C. 이어붙임   구간 사이 간격이 한 값에 쏠렸는가 (쏠리면 침묵이 안 적힌 것이다)
    C2. 전체 덮음 첫 구간이 0에서 시작하는가 (덮으면 발화 경계가 아니라 분할점)
    D. 상한       특정 길이에 봉우리 = 윈도우 상한에 잘린 자국

**C가 결정한다.** 여기 걸리면 A·B(사람이냐 기계냐)는 물어볼 필요가 없다. C2는
참고만 한다 — 짧게 잘린 클립은 사람이 찍어도 0에서 시작할 수 있다.

짝이 되는 도구가 `tools/vad_sweep.py`다. 그쪽이 "이 문턱값이 정답과 얼마나
가까운가"를 재고, 이쪽은 그 전에 **"이걸 정답으로 써도 되는가"**를 묻는다.

이 스크립트는 **고르지 않는다.** 숫자를 내놓고 사람이 정한다(규칙 11의 승격 경로).

    python tools/timestamp_origin.py <라벨JSON들이_있는_폴더>
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path

# whisper는 16kHz/hop 320 = 20ms 격자로 단어 시각을 낸다. 10ms는 대부분의
# VAD 프레임. 23.976/25/29.97fps는 사람이 SE에서 찍었을 때의 격자다.
GRIDS_MS = {
    "10ms (일반 VAD 프레임)": 10.0,
    "20ms (whisper hop)": 20.0,
    "1000/23.976fps": 1000.0 / 23.976,
    "1000/25fps": 40.0,
    "1000/29.97fps": 1001.0 / 30.0,
}

# Windows 기본 콘솔은 cp949라 한글·기호가 섞이면 여기서 터진다(규칙 10).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def collect(obj, out: list) -> None:
    """중첩 구조 어디에 있든 start/end 짝을 긁어 온다.

    AI Hub는 데이터셋마다 키 배치가 다르다(71699는 `video.term[]` 아래 있었다).
    구조를 미리 못 박으면 포맷이 조금만 달라도 0건이 나오고, 그걸 "타임코드 없음"
    으로 오독하게 된다.
    """
    if isinstance(obj, dict):
        s, e = obj.get("start"), obj.get("end")
        if _num(s) is not None and _num(e) is not None:
            out.append((_num(s), _num(e)))
        for v in obj.values():
            collect(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect(v, out)


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip()
        try:
            return float(t)
        except ValueError:
            pass
        # "00:01:23.456" / "00:01:23,456" 꼴도 받는다
        parts = t.replace(",", ".").split(":")
        if len(parts) == 3:
            try:
                h, m, sec = parts
                return int(h) * 3600 + int(m) * 60 + float(sec)
            except ValueError:
                return None
    return None


def grid_fit(ms_values: list[float], grid: float) -> float:
    """격자에서 벗어난 거리의 **중앙값을 격자폭으로 나눈 값**(0~0.5).

    완전히 붙어 있으면 0에 가깝고, 무관하면 0.25(균등분포의 기대값)에 가깝다.
    비율로 재야 격자폭이 다른 것끼리 견줄 수 있다.
    """
    offs = []
    for v in ms_values:
        r = v % grid
        offs.append(min(r, grid - r))
    return st.median(offs) / grid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path, help="라벨 JSON이 든 폴더(재귀 탐색)")
    ap.add_argument("--limit", type=int, default=2000, help="읽을 JSON 파일 수 상한")
    args = ap.parse_args()

    files = sorted(args.root.rglob("*.json"))[: args.limit]
    if not files:
        print(f"JSON을 못 찾았다: {args.root}", file=sys.stderr)
        return 1

    pairs: list[tuple[float, float]] = []
    per_file: list[list[tuple[float, float]]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  건너뜀 {f.name}: {exc}", file=sys.stderr)
            continue
        got: list[tuple[float, float]] = []
        collect(data, got)
        if got:
            per_file.append(got)
            pairs.extend(got)

    if not pairs:
        print("start/end 짝이 하나도 없다. 키 이름이 다를 수 있다 — JSON 하나를 직접 열어 확인할 것.")
        return 1

    # 초 단위인지 밀리초 단위인지 스스로 가린다. 초로 들어온 값을 ms로 잘못 읽으면
    # 격자 판정이 통째로 무의미해진다.
    span = max(max(e for _, e in pairs), 1e-9)
    unit_ms = 1.0 if span > 10000 else 1000.0
    marks_ms = [v * unit_ms for pair in pairs for v in pair]

    print(f"파일 {len(per_file)}개 / 구간 {len(pairs)}개 / 시각값 {len(marks_ms)}개")
    print(f"단위 판정: {'밀리초' if unit_ms == 1.0 else '초'} (최대 end={span:.3f})")

    print("")
    print("C. 이어붙임 — 구간 사이 간격이 한 값에 쏠렸는가")
    gaps: list[float] = []
    for got in per_file:
        seq = sorted(got)
        for (_, e), (s2, _) in zip(seq, seq[1:]):
            gaps.append(round((s2 - e) * unit_ms, 4))
    glued = 0.0
    if gaps:
        mode, hits = Counter(gaps).most_common(1)[0]
        glued = hits / len(gaps)
        print(f"   최빈 간격 {mode:+.4f}ms — {hits}/{len(gaps)} = {glued:.1%}")
        if glued > 0.30:
            print("   >>> 이어붙인 분할이다. 사이의 침묵이 기록되지 않았다는 뜻이다.")

    print("")
    print("C2. 클립을 빈틈없이 덮는가 (덮으면 발화 경계가 아니라 분할점이다)")
    at_zero = sum(1 for got in per_file if abs(min(s for s, _ in got)) < 1e-9)
    covered = at_zero / len(per_file)
    print(f"   첫 구간이 정확히 0에서 시작: {at_zero}/{len(per_file)} = {covered:.1%}")
    # **이 값만으로 판정하지 않는다.** 짧게 잘린 클립은 사람이 찍어도 0에서 시작할
    # 수 있다(합성 시험본이 실제로 100%가 나와 거짓양성을 냈다). C가 결정한다.

    print("")
    print("A. 양자화 — 0에 가까울수록 그 격자에 붙어 있다 (무관하면 0.25)")
    on_grid = False
    for name, g in GRIDS_MS.items():
        fit = grid_fit(marks_ms, g)
        flag = ""
        if fit < 0.02:
            flag = "  <<< 강하게 붙음"
            if g in (10.0, 20.0):
                on_grid = True
        elif fit < 0.08:
            flag = "  <  약하게 붙음"
        print(f"   {name:24s} {fit:.4f}{flag}")

    print("")
    print("B. 소수 자릿수 분포")
    dec = Counter()
    for v in marks_ms:
        s = f"{v / 1000:.6f}".rstrip("0")
        dec[max(0, len(s.split(".")[1]))] += 1
    for k in sorted(dec):
        print(f"   소수 {k}자리: {dec[k]:>7} ({dec[k] / len(marks_ms) * 100:5.1f}%)")

    print("")
    print("D. 구간 길이 상한 봉우리 (상위 5개)")
    durs = Counter(round((e - s) * unit_ms / 1000, 2) for s, e in pairs)
    for d, k in durs.most_common(5):
        print(f"   {d:>7.2f}s : {k}")

    print("")
    print("---- 읽는 법 ----")
    if glued > 0.30:
        print("**말소리 경계가 아니다.** 구간이 일정 간격으로 이어 붙어 있다 = 텍스트를")
        print("문장 단위로 나눈 분할점이지 말이 시작·끝난 자리가 아니다.")
        print("vad_sweep의 정답으로 쓰지 않는다. (AI Hub 71699가 정확히 이 경우였다)")
    elif on_grid:
        print("기계 산출 의심. 10/20ms 격자에 붙어 있다.")
        print("이 경우도 vad_sweep의 정답으로 쓰지 않는다 — 기계로 기계를 채점하게 된다.")
    else:
        print("자동 지문이 안 보인다. 사람 확정 가능성 있음.")
        print("다만 이것만으로 확정하지 말고, 클립 3~5개를 ffmpeg silencedetect로 대 보고")
        print("경계가 실제 무음과 맞는지 확인한다(규칙 4 — 추정과 확실한 근거를 가른다).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
