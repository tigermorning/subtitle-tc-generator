"""고르지 않은 것을 고른 것처럼 보이게 두지 않는다.

## 왜 필요한가

`--generate`가 찍던 `프로파일: netflix ko translation` 한 줄은 **사람이 고른
것인지 기본값이 채운 것인지 구분되지 않았다.** 규칙 1의 ⓪(발주처 확인이 모든
작업에 앞선다)는 도구 안에서 조용히 넷플릭스로 채워지고 있었고, 그 사실이
화면에도 리포트에도 남지 않았다.

`preflight.py`와 층이 다르다. 저기는 **환경**(ffmpeg·모델·디스크·토큰)이
준비됐는지 보고, 여기는 **결정**(어느 발주처·어느 종류·어느 장르·인물 관계를
아는지)이 실제로 내려졌는지 본다. 환경이 다 갖춰져도 발주처를 안 고르면
결과물은 처음부터 다른 기준으로 만들어진다 — 10분 걸려 만든 뒤에야 드러난다.

## 채우되, 채웠다고 말한다

기본값을 없애면 예전 명령이 전부 깨진다. 그래서 **값은 그대로 채우고 출처를
남긴다** — 규칙 11이 `rules/learned/`에 `origin: learned`를 지우지 않고 남기는
것과 같은 이유다. 어디서 온 값인지가 남아야 나중에 근거를 댈 수 있다.

    user      사람이 명령줄에서 골랐다
    default   고르지 않아 기계가 채웠다        <- 이것을 눈에 띄게 한다
    file      --profile로 프로파일 파일을 줬다
    none      고르지 않았고 채우지도 않았다(장르·캐스트 시트)

## 여기서 하지 않는 것

**막지 않는다.** 기본값으로 도는 것 자체가 위반은 아니고(규칙 4 — 추정으로
자동 교정하지 않듯, 추정으로 실행을 막지도 않는다), `detect.py`처럼 값을
바꿔치기하지도 않는다. 말하는 것까지가 이 모듈의 일이다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 고르지 않았을 때 채우는 값. **바꾸지 말 것** — 예전 명령이 이 값으로 돌던
# 결과와 달라지면, 도구가 조용히 다른 답을 내는 셈이 된다.
PLATFORM_FALLBACK = "netflix"
KIND_FALLBACK = "translation"
LANG_FALLBACK = "ko"


@dataclass
class Decision:
    label: str
    value: str
    source: str          # user | default | file | none
    note: str = ""
    warn: bool = False    # 결정표에서 "확인 필요"로 표시하고 경고로도 낸다


_SOURCE_LABEL = {
    "user": "지정함",
    "default": "기본값 — 지정 안 함",
    "file": "--profile 파일",
    "none": "지정 안 함",
}


def resolve(args) -> list[Decision]:
    """`args`의 빈 칸을 채우고, 무엇을 채웠는지 목록으로 돌려준다.

    **`args`를 고친다** — `platform`/`kind`/`lang`이 `None`이면 기본값을 넣는다.
    파서의 `default=`를 여기로 옮긴 것이라, 부르지 않으면 뒤 단계가 `None`을 본다.
    """
    out: list[Decision] = []
    from_file = bool(getattr(args, "profile", None))

    if args.platform is None:
        args.platform = PLATFORM_FALLBACK
        platform = Decision("발주처", args.platform, "file" if from_file else "default",
                            "규칙 1 ⓪ — 발주처 확인이 가장 먼저입니다. -p로 지정하세요."
                            if not from_file else "", warn=not from_file)
    else:
        platform = Decision("발주처", args.platform, "user")
    out.append(platform)

    if args.kind is None:
        args.kind = KIND_FALLBACK
        # 번역 프로파일로 SDH 파일을 돌리면 효과음 규칙이 아예 없어 **조용히 다
        # 통과한다**(`detect.mismatch_warning`의 같은 지적). 기본값이 둘 중 더
        # 느슨한 쪽이라 특히 눈에 띄어야 한다.
        kind = Decision("종류", args.kind, "file" if from_file else "default",
                        "SDH 파일이면 효과음 규칙이 통째로 빠집니다. -k sdh로 지정하세요."
                        if not from_file else "", warn=not from_file)
    else:
        kind = Decision("종류", args.kind, "user")
    out.append(kind)

    if args.lang is None:
        args.lang = LANG_FALLBACK
        # 언어는 경고하지 않는다 — 이 도구의 납품물은 한국어 자막이고(규칙 2),
        # 발주처처럼 "고르지 않으면 답이 뒤집히는" 자리가 아니다.
        out.append(Decision("언어", args.lang, "default"))
    else:
        out.append(Decision("언어", args.lang, "user"))

    genre = getattr(args, "genre", None)
    if genre:
        out.append(Decision("장르", genre, "user"))
    else:
        # 값을 채우지 않는다 — 장르는 권장이지 규정이 아니라(genre.py) 채울
        # 기본값 자체가 없다. 다만 **결정이 안 된 사실**은 보이게 둔다.
        out.append(Decision("장르", "미지정", "none",
                            "장르 관행(병합 간격·표시 시간 권장값)을 얹지 않습니다."))

    if getattr(args, "translate", False):
        if getattr(args, "cast", None):
            out.append(Decision("캐스트 시트", str(args.cast), "user"))
        else:
            # 규칙 16 — 자막 작업은 배경지식이 필수다. 시트가 없으면
            # `translate.py`가 "관계를 모르면 존댓말로 통일"로 채운다.
            out.append(Decision("캐스트 시트", "없음", "none",
                                "인물 관계를 모른 채 존댓말로 통일해 번역합니다"
                                " (--characters로 만들어 --cast로 줍니다).",
                                warn=True))

    if getattr(args, "lock_timecodes", False):
        out.append(Decision("타임코드", "고정", "user",
                            "받은 타임코드를 그대로 둡니다(나누기·수렴·스포팅 안 함)."))

    return out


def _width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글은 두 칸이라 `len()`으로 맞추면 어긋난다."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def table(decisions: list[Decision]) -> str:
    """사람이 읽는 결정표. `--dry-run`과 `--generate` 앞머리에서 쓴다."""
    lines = ["결정표 — 이 실행이 무엇을 기준으로 삼는지"]
    label_w = max(_width(d.label) for d in decisions)
    value_w = max(_width(d.value) for d in decisions)
    for d in decisions:
        mark = "  <- 확인 필요" if d.warn else ""
        lines.append(f"  {_pad(d.label, label_w)}  {_pad(d.value, value_w)}  "
                     f"({_SOURCE_LABEL.get(d.source, d.source)}){mark}")
        if d.note:
            lines.append(f"  {' ' * label_w}  {d.note}")
    return "\n".join(lines)


def warnings(decisions: list[Decision]) -> list[str]:
    """짧은 경고 문구만 추린다 — 결정표를 안 찍는 경로(그냥 `--check`)용."""
    return [f"{d.label}를 지정하지 않아 {d.value}로 진행합니다. {d.note}".strip()
            for d in decisions if d.warn]


def to_report(decisions: list[Decision]) -> list[dict]:
    """리포트(JSON·텍스트)에 남길 형태. 화면에서 흘러가도 파일에는 남는다."""
    return [{"label": d.label, "value": d.value, "source": d.source,
             "note": d.note, "warn": d.warn} for d in decisions]
