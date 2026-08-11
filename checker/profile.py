"""규정 프로파일 로더. `rules/SCHEMA.md`의 로더 계약을 여기서 강제한다.

계약을 코드로 옮긴 이유: SDH와 번역 자막이 섞이는 것을 사람 기억이 아니라 기계가
막아야 하기 때문이다. 위반은 경고가 아니라 **로드 실패**다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RULES_ROOT = Path(__file__).resolve().parent.parent / "rules"

KINDS = ("sdh", "translation", "common")

# 종류 전용 키. 반대쪽에 나타나면 프로파일이 섞인 것이다.
SDH_ONLY_KEYS = ("speaker_id", "sound_effect")
TRANSLATION_ONLY_KEYS = ("forced_narrative",)


class ProfileError(Exception):
    """프로파일이 계약을 어겼다. 부분적으로라도 로드하지 않는다."""


def _read(path: Path) -> dict:
    if not path.is_file():
        raise ProfileError(f"프로파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProfileError(f"프로파일이 매핑이 아닙니다: {path}")
    return data


def _validate(data: dict, path: Path) -> None:
    kind = data.get("kind")
    # 계약 1: kind 없으면 실패. 기본값을 주지 않는다 — 조용히 한쪽으로 떨어지는 것이 곧 섞임이다.
    if kind not in KINDS:
        raise ProfileError(f"{path.name}: kind가 {KINDS} 중 하나여야 합니다(현재: {kind!r})")

    # 계약 2·3: 전용 키가 반대쪽에 있으면 실패.
    if kind == "translation":
        bad = [k for k in SDH_ONLY_KEYS if k in data]
        if bad:
            raise ProfileError(f"{path.name}: 번역 프로파일에 SDH 전용 키가 있습니다: {bad}")
    if kind == "sdh":
        bad = [k for k in TRANSLATION_ONLY_KEYS if k in data]
        if bad:
            raise ProfileError(f"{path.name}: SDH 프로파일에 번역 전용 키가 있습니다: {bad}")

    if data.get("schema_version") != 1:
        raise ProfileError(f"{path.name}: 지원하지 않는 schema_version입니다")


def _resolve(path: Path, seen: list[Path] | None = None) -> dict:
    """프로파일 하나를 읽고 `extends` 사슬을 위에서부터 병합한다.

    사슬을 허용하는 이유: 규정은 **절대적 정답이 아니라 발주처가 요구하는 틀**이다.
    같은 넷플릭스 작업이라도 에이전시가 자기 기준을 얹는 경우가 있다(말줄임표를
    `...`로 쓰라거나, 한 줄 글자 수를 더 조인다거나). 그럴 때 공식 프로파일을
    베끼지 않고 **상속해서 덮어쓰게** 한다 — 공식 값이 개정되면 상속본도 따라간다.
    """
    seen = seen or []
    if path in seen:
        chain = " -> ".join(p.name for p in seen + [path])
        raise ProfileError(f"extends가 순환합니다: {chain}")

    data = _read(path)
    _validate(data, path)

    parent_ref = data.get("extends")
    if not parent_ref:
        return data

    parent_path = (path.parent / parent_ref).resolve()
    if not parent_path.is_file():
        # 다른 디렉터리의 공식 프로파일을 가리킬 수 있게 rules/ 기준으로도 찾는다.
        parent_path = (RULES_ROOT / parent_ref).resolve()
    parent = _resolve(parent_path, seen + [path])

    # 계약 4: 상속은 kind: common 이거나 **같은 종류**여야 한다.
    # sdh가 translation을 상속하는 순간 두 규정이 섞인다.
    if parent.get("kind") not in ("common", data.get("kind")):
        raise ProfileError(
            f"{path.name}: extends는 kind: common 이거나 같은 kind여야 합니다"
            f"(현재 {parent.get('kind')!r} <- {data.get('kind')!r})"
        )

    merged = _merge(parent, data)

    # 상속본이 상위 규칙을 끌 수 있어야 한다. 발주처가 안 보는 규칙을 위반으로
    # 계속 띄우면 리포트가 노이즈가 되고, 진짜 지적이 묻힌다.
    disabled = set(data.get("disable_rules") or [])
    if disabled:
        merged["rules"] = [r for r in merged["rules"] if r["id"] not in disabled]
    return merged


def load_profile(platform: str, language: str, kind: str) -> dict:
    """플랫폼·언어·종류로 프로파일을 읽어 `extends`를 병합해 돌려준다."""
    if kind not in ("sdh", "translation"):
        raise ProfileError("kind는 sdh 또는 translation이어야 합니다")

    path = RULES_ROOT / platform / f"{language}-{kind}.yaml"
    if not path.is_file():
        raise ProfileError(
            f"{platform}/{language} {kind} 프로파일이 없습니다. "
            f"공식 규정을 확보하지 못한 플랫폼일 수 있습니다({platform}/UNAVAILABLE.yaml 참고)."
        )
    return _check_usable(_resolve(path), path)


def load_profile_file(path: Path) -> dict:
    """파일 경로로 프로파일을 읽는다. 에이전시·발주처 전용 프로파일용."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ProfileError(f"프로파일 파일이 없습니다: {path}")
    return _check_usable(_resolve(path), path)


def _check_usable(data: dict, path: Path) -> dict:
    if data.get("kind") not in ("sdh", "translation"):
        raise ProfileError(f"{path.name}: 검사에 쓰려면 kind가 sdh 또는 translation이어야 합니다")
    if data.get("status") != "complete":
        raise ProfileError(f"{path.name}: status가 complete가 아닙니다({data.get('status')!r})")
    # 2차 자료로 채운 프로파일이 조용히 검사에 쓰이는 것을 막는다. 다만 발주처가
    # 지정한 사내 기준은 "공식 문서"가 없을 수 있어 `source.client`로 대신 밝힌다.
    src = data.get("source") or {}
    if not src.get("official") and not src.get("client"):
        raise ProfileError(
            f"{path.name}: 출처가 없는 프로파일은 검사에 쓰지 않습니다"
            " (공식 문서면 source.official, 발주처 지정이면 source.client를 적으세요)"
        )
    return data


def _merge(parent: dict, child: dict) -> dict:
    """계약 5: 키 단위 얕은 덮어쓰기. 리스트는 합치지 않고 통째로 대체한다.

    리스트를 병합하면 상위 값이 부분적으로 살아남아 프로파일에 적혀 있지 않은
    유령 규칙이 생긴다. 한 단계 아래 매핑까지만 병합하고 그 아래는 대체한다.
    """
    merged = dict(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            sub = dict(merged[key])
            sub.update(value)
            merged[key] = sub
        else:
            merged[key] = value

    # 규칙은 공통 + 개별을 이어 붙인다(같은 id면 개별이 이긴다).
    child_ids = {r["id"] for r in child.get("rules", [])}
    merged["rules"] = [r for r in parent.get("rules", []) if r["id"] not in child_ids] + child.get(
        "rules", []
    )
    return merged


def available_profiles() -> list[tuple[str, str, str]]:
    """(platform, language, kind) 목록. 미확보 플랫폼은 나오지 않는다."""
    found = []
    for path in sorted(RULES_ROOT.glob("*/*.yaml")):
        try:
            data = _read(path)
        except ProfileError:
            continue
        if data.get("kind") in ("sdh", "translation") and data.get("status") == "complete":
            found.append((data["platform"], data["language"], data["kind"]))
    return found
