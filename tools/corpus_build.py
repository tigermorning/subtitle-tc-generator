"""정답 자막에서 학습 자료를 만든다 — 영상 하나에서 언어 쌍과 통계와 지적을 뽑는다.

**왜 필요한가.** 생성기를 고치려면 사람이 만든 자막이 필요하다. 상용 릴리스의 mkv에는
공식 자막이 트랙으로 들어 있고, 그 타임코드는 그 파일에 대해 정답이다. 그것을 모아
① 스포팅 값을 실측으로 정하고 ② 원어-한국어 쌍을 번역 학습 자료로 쓴다.

**타임코드만 정답으로 둔다.** 글자는 사람이 쓴 것이라 틀린 자리가 있을 수 있다. 그래서
버리지 않고 **지적으로 남긴다**(`flags.jsonl`). 규칙 3과 같은 판단이다 — 어느 쪽도 정답으로
두지 않고 어긋난 자리를 표시한다.

**판본을 섞지 않는다.** 같은 작품이라도 23.976과 24.000 판은 끝에서 9초 어긋난다. 그래서
자막은 **그 파일에서 뽑은 것만** 쓰고, 사이드카 파일을 받을 때는 fps를 함께 적어 둔다.

    python tools/corpus_build.py --video 영화.mkv --out .tmp/corpus --pivot eng --target kor

나오는 것:

    pairs.jsonl   원어-한국어 쌍. 자막이 합쳐진 자리는 n:m 묶음 하나로 낸다
    stats.json    실측 값 — 노출 시간·간격·줄당 글자·CPS·합쳐진 비율
    flags.jsonl   사람 자막에서 눈에 걸린 자리. 버리지 않고 표시만 한다
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker.model import Event
from checker.parsers import parse
# 내부 이름을 쓴다. 이 도구가 남으면 media.py에서 공개로 올린다.
from checker.media import _find, _as_tool_path  # noqa: E402

TAG = re.compile(r"</?[a-zA-Z][^>]*>")
# `{\an8}` 같은 배치 지시. **글자가 아니다.** 이것을 세면 줄당 글자 수가 부풀고,
# 부푼 값으로 사람 자막을 "16자 초과"라고 지적하게 된다(실제로 그랬다).
OVERRIDE = re.compile(r"\{[^}]*\}")
SPEAKER = re.compile(r"^[\[(][^\])]{0,20}[\])]\s*")
DASH = re.compile(r"^-\s*")
AN = re.compile(r"\{\\an(\d)\}")


def bare(text: str) -> str:
    """태그·배치 지시·화자 표시·대화 하이픈을 뗀 글자. 길이를 잴 때만 쓴다."""
    out = OVERRIDE.sub("", TAG.sub("", text))
    return "\n".join(DASH.sub("", SPEAKER.sub("", ln).strip()).strip()
                     for ln in out.split("\n")).strip()


@dataclass
class Track:
    index: int
    lang: str
    title: str
    codec: str


def probe_tracks(video: Path) -> list[Track]:
    out = subprocess.run(
        [_find("ffprobe"), "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index,codec_name:stream_tags=language,title",
         "-of", "json", _as_tool_path(video)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    data = json.loads(out.stdout or "{}")
    tracks = []
    for s in data.get("streams", []):
        tags = s.get("tags") or {}
        tracks.append(Track(int(s["index"]), tags.get("language", ""),
                            tags.get("title", ""), s.get("codec_name", "")))
    return tracks


def extract(video: Path, track: Track, dest: Path) -> Path | None:
    """텍스트 트랙만 뽑는다. PGS/VobSub은 그림이라 OCR이 필요하고, OCR을 거친 것은
    타임코드도 글자도 근사값이 되므로 **정답 자료로 쓰지 않는다.**"""
    if track.codec not in {"subrip", "ass", "ssa", "mov_text", "webvtt"}:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [_find("ffmpeg"), "-v", "error", "-y", "-i", _as_tool_path(video),
         "-map", f"0:{track.index}", "-c:s", "srt", _as_tool_path(dest)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return dest if dest.is_file() and dest.stat().st_size > 0 else (r and None)


def group(src: list[Event], tgt: list[Event]) -> list[dict]:
    """시간이 겹치는 것끼리 묶는다. 한국어가 영어 둘을 합치는 일이 흔하므로 1:1을
    강요하지 않는다 — 겹침이 이어지는 동안 한 묶음으로 본다."""
    pairs, i, j = [], 0, 0
    while i < len(src) or j < len(tgt):
        a, b = [], []
        if i < len(src) and (j >= len(tgt) or src[i].start_ms <= tgt[j].start_ms):
            a.append(src[i]); i += 1
        else:
            b.append(tgt[j]); j += 1
        grew = True
        while grew:
            grew = False
            lo = min([e.start_ms for e in a + b])
            hi = max([e.end_ms for e in a + b])
            while i < len(src) and src[i].start_ms < hi and src[i].end_ms > lo:
                a.append(src[i]); i += 1; grew = True
            while j < len(tgt) and tgt[j].start_ms < hi and tgt[j].end_ms > lo:
                b.append(tgt[j]); j += 1; grew = True
        pairs.append({
            "start_ms": min([e.start_ms for e in a + b]),
            "end_ms": max([e.end_ms for e in a + b]),
            "source": "\n".join(e.text for e in a),
            "target": "\n".join(e.text for e in b),
            "n_source": len(a), "n_target": len(b),
        })
    return pairs


def flags_for(events: list[Event], lang: str) -> list[dict]:
    """사람 자막에서 눈에 걸린 자리. **고치지 않고 남긴다.**

    수치는 넷플릭스 한국어 기준을 잣대로 쓴다(줄당 16자·최대 두 줄·최소 노출
    0.833초·최대 7초). 발주처가 다르면 잣대가 달라지므로 **위반이 아니라 지적**이다.
    """
    out = []
    for k, e in enumerate(events):
        t = bare(e.text)
        lines = [ln for ln in t.split("\n") if ln.strip()]
        why = []
        if not t:
            why.append("빈 자막")
        if e.duration_ms < 833:
            why.append(f"노출 {e.duration_ms}ms — 0.833초 미만")
        if e.duration_ms > 7000:
            why.append(f"노출 {e.duration_ms}ms — 7초 초과")
        if len(lines) > 2:
            why.append(f"{len(lines)}줄 — 두 줄 초과")
        if lang == "kor":
            over = [len(ln) for ln in lines if len(ln) > 16]
            if over:
                why.append(f"줄당 {max(over)}자 — 16자 초과")
        if t and e.duration_ms:
            cps = len(t.replace("\n", "")) / (e.duration_ms / 1000)
            if cps > 20:
                why.append(f"{cps:.1f}자/초 — 읽기 속도 초과")
        # **프레임 간격은 지적하지 않는다.** 넷플릭스는 2020-07-24에 그 규정을 삭제했다.
        # 이 릴리스의 원어 트랙은 자막을 붙여 놓는데(간격 중앙값 1ms), 그것을 위반으로
        # 세면 사람 자막의 61%가 지적된다 — 오류가 아니라 잣대가 다른 것이다.
        if k + 1 < len(events):
            gap = events[k + 1].start_ms - e.end_ms
            if gap < 0:
                why.append(f"다음 자막과 {-gap}ms 겹침")
        if why:
            out.append({"index": e.index, "start_ms": e.start_ms,
                        "text": e.text, "why": why})
    return out


def profile_evidence(events: list[Event]) -> dict:
    """프로파일 값을 **자료에서 읽는다.** 추측해서 만들지 않기 위해서다(규칙 9).

    화면자막 표식과 겹침 처리는 작업 시작 전에 정해야 하는 값인데, 사람이 만든
    납품본에는 그 답이 이미 들어 있다 — 작은따옴표로 감쌌는지 이탤릭인지, 대사와
    겹칠 때 위로 올렸는지(`{\\an8}`).
    """
    an, marker = {}, {"작은따옴표": 0, "큰따옴표": 0, "대괄호": 0, "이탤릭만": 0}
    for e in events:
        for m in AN.finditer(e.text):
            an[f"an{m[1]}"] = an.get(f"an{m[1]}", 0) + 1
        t = bare(e.text)
        italic = "<i>" in e.text
        if t.startswith("'") and t.rstrip().endswith("'"):
            marker["작은따옴표"] += 1
        elif t.startswith('"') and t.rstrip().endswith('"'):
            marker["큰따옴표"] += 1
        elif t.startswith("[") and t.rstrip().endswith("]"):
            marker["대괄호"] += 1
        elif italic:
            marker["이탤릭만"] += 1
    return {"배치 지시": an, "감싼 방식": marker}


def stats_for(events: list[Event], lang: str) -> dict:
    import statistics as st
    dur = [e.duration_ms for e in events]
    chars, cps, lines, gaps = [], [], [], []
    for k, e in enumerate(events):
        t = bare(e.text)
        ls = [ln for ln in t.split("\n") if ln.strip()]
        if ls:
            chars.append(max(len(ln) for ln in ls))
            lines.append(len(ls))
        if t and e.duration_ms:
            cps.append(len(t.replace("\n", "")) / (e.duration_ms / 1000))
        if k + 1 < len(events):
            gaps.append(events[k + 1].start_ms - e.end_ms)
    def q(v, p):
        return round(st.quantiles(v, n=100)[p - 1], 1) if len(v) > 2 else None
    return {
        "lang": lang, "cues": len(events),
        "duration_ms": {"중앙값": st.median(dur), "5%": q(dur, 5), "95%": q(dur, 95),
                        "최소": min(dur), "최대": max(dur)},
        "chars_per_line": {"중앙값": st.median(chars), "95%": q(chars, 95),
                           "최대": max(chars)} if chars else {},
        "cps": {"중앙값": round(st.median(cps), 1), "95%": q(cps, 95)} if cps else {},
        "lines": {"한 줄": lines.count(1), "두 줄": lines.count(2),
                  "세 줄 이상": sum(1 for v in lines if v > 2)},
        "gap_ms": {"중앙값": st.median(gaps), "5%": q(gaps, 5)} if gaps else {},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pivot", default="eng", help="원어 트랙 언어 코드")
    ap.add_argument("--target", default="kor", help="목표 트랙 언어 코드")
    ap.add_argument("--all-langs", action="store_true",
                    help="다른 언어 트랙도 전부 뽑아 둔다(쌍은 만들지 않는다)")
    a = ap.parse_args()

    if not a.video.is_file():
        print(f"영상을 찾지 못했습니다: {a.video}", file=sys.stderr)
        return 1
    a.out.mkdir(parents=True, exist_ok=True)
    srt_dir = a.out / "srt"

    tracks = probe_tracks(a.video)
    text_tracks = [t for t in tracks if t.codec in
                   {"subrip", "ass", "ssa", "mov_text", "webvtt"}]
    image_tracks = [t for t in tracks if t not in text_tracks]
    print(f"자막 트랙 {len(tracks)}개 — 텍스트 {len(text_tracks)}, "
          f"그림 {len(image_tracks)}(건너뜁니다)")
    if not text_tracks:
        print("텍스트 자막 트랙이 없습니다. 이 파일은 정답 자료로 쓸 수 없습니다.",
              file=sys.stderr)
        return 1

    def pick(lang: str) -> Track | None:
        same = [t for t in text_tracks if t.lang == lang]
        if not same:
            return None
        plain = [t for t in same if "sdh" not in t.title.lower()
                 and "hi" not in t.title.lower().split()]
        return (plain or same)[0]

    wanted = [t for t in (pick(a.pivot), pick(a.target)) if t]
    if a.all_langs:
        wanted = text_tracks
    got: dict[str, Path] = {}
    for t in wanted:
        name = f"{t.lang or 'und'}_{t.index}.srt"
        if extract(a.video, t, srt_dir / name):
            got[f"{t.lang}:{t.index}"] = srt_dir / name

    src_t, tgt_t = pick(a.pivot), pick(a.target)
    if not (src_t and tgt_t):
        print(f"쌍을 만들 트랙이 없습니다 (원어 {a.pivot} / 목표 {a.target}). "
              f"뽑기만 했습니다.", file=sys.stderr)
        return 0

    src = parse(srt_dir / f"{src_t.lang or 'und'}_{src_t.index}.srt")
    tgt = parse(srt_dir / f"{tgt_t.lang or 'und'}_{tgt_t.index}.srt")
    pairs = group(src, tgt)
    both = [p for p in pairs if p["n_source"] and p["n_target"]]

    meta = {"video": a.video.name, "pivot": a.pivot, "target": a.target}
    with (a.out / "pairs.jsonl").open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps({**meta, **p}, ensure_ascii=False) + "\n")
    with (a.out / "flags.jsonl").open("w", encoding="utf-8") as f:
        for lang, evs in ((a.pivot, src), (a.target, tgt)):
            for row in flags_for(evs, lang):
                f.write(json.dumps({**meta, "lang": lang, **row},
                                   ensure_ascii=False) + "\n")
    merged = sum(1 for p in both if p["n_source"] > 1 or p["n_target"] > 1)
    stats = {
        **meta,
        "tracks": {"텍스트": len(text_tracks), "그림": len(image_tracks)},
        "pairs": {"전체": len(pairs), "양쪽 다 있음": len(both),
                  "원어만": sum(1 for p in pairs if not p["n_target"]),
                  "목표만": sum(1 for p in pairs if not p["n_source"]),
                  "합쳐진 묶음": merged},
        "source": stats_for(src, a.pivot),
        "target": stats_for(tgt, a.target),
        "프로파일 근거": profile_evidence(tgt),
        "화면자막 후보": [
            {"start_ms": p["start_ms"], "text": p["target"]}
            for p in pairs if not p["n_source"] and p["n_target"]
        ][:200],
    }
    (a.out / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"쌍 {len(both)}개 (합쳐진 묶음 {merged}개) -> {a.out/'pairs.jsonl'}")
    print(f"통계 -> {a.out/'stats.json'}")
    print(f"지적 -> {a.out/'flags.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
