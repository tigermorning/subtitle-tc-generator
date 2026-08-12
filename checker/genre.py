"""장르를 프로파일 위에 얹는다.

**왜 프롬프트가 아니라 프로파일인가.** 장르는 번역 말투만 바꾸는 것이 아니다.
작업자 자료 590행이 장르로 **타임코드 길이**를 가른다("정통 다큐는 3~5초, 드라마는
2~3초, 예능/리얼다큐는 2초 이하"). 프롬프트에 아무리 적어도 검사기는 그것을 모른다.

`translate.DOCUMENTARY_RULES`가 죽은 코드로 남아 있던 이유가 이것이다 — 정의만 있고
참조가 0건이었다. 층이 틀렸으니 쓸 자리가 없었다.

**장르는 플랫폼 밑에 두지 않는다.** 다큐멘터리는 넷플릭스에도 쿠팡에도 있다. 플랫폼
밑에 두면 같은 규칙을 플랫폼 수만큼 적어야 한다. 그래서 `rules/genre/`에 조각으로
두고 `_merge`로 얹는다 — 프로파일 상속(`extends`)이 쓰는 것과 같은 병합이다.

## 만들지 않은 장르

- **멜로** — 일반 대화체이므로 드라마가 그대로 맞는다(사용자 확인). 빈 프로파일을
  늘리면 상속만 복잡해지고 얻는 것이 없다.
- **느와르** — 거친 표현·욕설은 이미 **플랫폼 규정**이 정한다
  (`censorship.allowed: false` = 검열 금지 = 동등 강도로 옮긴다). 장르가 아니라
  **캐릭터**가 그 인물이 그렇게 말하는지를 정한다 → `characters.py`.
"""

from __future__ import annotations

from pathlib import Path

from .profile import RULES_ROOT, ProfileError, _merge, _read

GENRE_ROOT = RULES_ROOT / "genre"


def available() -> list[dict]:
    """쓸 수 있는 장르 목록. `{"genre": ..., "label": ..., "source": ...}`."""
    out = []
    for path in sorted(GENRE_ROOT.glob("*.yaml")):
        data = _read(path)
        out.append({"genre": data.get("genre") or path.stem,
                    "label": data.get("label", ""),
                    "source": data.get("source") or {}})
    return out


def load(name: str) -> dict:
    """장르 조각을 읽는다. **완전한 프로파일이 아니므로 `_check_usable`을 걸지 않는다.**"""
    path = GENRE_ROOT / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(g["genre"] for g in available()) or "없음"
        raise ProfileError(f"모르는 장르입니다: {name} (있는 것: {known})")
    return _read(path)


def apply(profile: dict, name: str | None) -> dict:
    """프로파일에 장르를 얹은 새 사전을 돌려준다. `name`이 없으면 그대로 돌려준다.

    **출처를 덮어쓰지 않는다.** 플랫폼 규정과 장르 관행은 근거의 무게가 다르므로
    (규칙 5) 장르 출처는 `genre_source`로 따로 남긴다 — 얹었다는 사실이 리포트에서
    사라지면 어느 기준으로 잰 것인지 알 수 없다.
    """
    if not name:
        return profile
    overlay = dict(load(name))
    genre_source = overlay.pop("source", None)
    overlay.pop("schema_version", None)
    overlay.pop("label", None)
    merged = _merge(profile, overlay)
    merged["genre"] = overlay.get("genre") or name
    if genre_source:
        merged["genre_source"] = genre_source
    return merged


def recommended_spotting(profile: dict) -> tuple[int | None, int | None, str]:
    """장르가 권장하는 표시 시간. `(최소, 최대, 설명)`.

    **권장이지 규정이 아니다.** 플랫폼이 정한 `limits`는 그대로 두고, 이 범위를
    벗어난 것은 위반이 아니라 숫자로 낸다(규칙 4·5).
    """
    spotting = profile.get("spotting") or {}
    span = spotting.get("recommended_ms") or [None, None]
    low = span[0] if len(span) > 0 else None
    high = span[1] if len(span) > 1 else None
    return low, high, spotting.get("recommended_note", "")


def off_recommendation(events, profile: dict) -> list[dict]:
    """권장 표시 시간을 벗어난 자막. 지적이 아니라 목록이다."""
    low, high, note = recommended_spotting(profile)
    if low is None and high is None:
        return []
    out = []
    for ev in events:
        span = ev.end_ms - ev.start_ms
        if low is not None and span < low:
            out.append({"event_index": ev.index, "duration_ms": span,
                        "reason": f"권장보다 짧습니다({span}ms < {low}ms)", "note": note})
        elif high is not None and span > high:
            out.append({"event_index": ev.index, "duration_ms": span,
                        "reason": f"권장보다 깁니다({span}ms > {high}ms)", "note": note})
    return out
