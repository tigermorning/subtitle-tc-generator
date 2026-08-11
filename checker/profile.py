"""규정 프로파일 로더. `rules/SCHEMA.md`의 로더 계약을 여기서 강제한다.

계약을 코드로 옮긴 이유: SDH와 번역 자막이 섞이는 것을 사람 기억이 아니라 기계가
막아야 하기 때문이다. 위반은 경고가 아니라 **로드 실패**다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# 실행 파일로 묶이면 규정 파일이 임시 폴더에 풀린다. 저장소에서 돌 때와 자리가
# 다르므로 둘 다 본다 — 못 찾으면 검사가 통째로 안 돈다.
_BUNDLED = Path(getattr(sys, "_MEIPASS", "")) / "rules" if getattr(sys, "_MEIPASS", "") else None
RULES_ROOT = (_BUNDLED if _BUNDLED and _BUNDLED.is_dir()
              else Path(__file__).resolve().parent.parent / "rules")

KINDS = ("sdh", "translation", "common")

# SDH 전용 키. 번역 자막 프로파일에 나타나면 두 규정이 섞인 것이다.
SDH_ONLY_KEYS = ("speaker_id", "sound_effect")

# 번역 전용 키는 두지 않는다.
#
# 처음에는 `forced_narrative`를 번역 전용으로 막았다. 넷플릭스 공식 가이드에서
# 화면 자막(On-screen Text)이 Section I(번역)에만 있었기 때문이다. 그런데 실무
# 자료를 반영하다 SDH 프로파일이 로드 실패했다 — **SDH 작업도 화면 자막을 다룬다.**
# 대사와 겹칠 때 지울지 병기할지가 플랫폼마다 다르고, 그것을 적을 자리가 필요하다.
#
# 막아야 할 것은 "SDH 규정이 번역 프로파일에 새는 것"이지 그 반대가 아니다.
# 화자 표시·효과음이 번역 자막에 있으면 확실히 잘못이지만, 화면 자막은 양쪽 다 쓴다.
TRANSLATION_ONLY_KEYS = ()


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
    if kind == "sdh" and TRANSLATION_ONLY_KEYS:
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


def available_profiles() -> list[dict]:
    """쓸 수 있는 프로파일 목록. 미확보 플랫폼은 나오지 않는다.

    파일 이름을 함께 준다 — `en-translation`과 `en-template`은 platform·language·kind가
    같아서 그 셋만으로는 구분되지 않는다(실제로 목록에 같은 줄이 두 번 나왔다).
    """
    found = []
    for path in sorted(RULES_ROOT.glob("*/*.yaml")):
        try:
            data = _read(path)
        except ProfileError:
            continue
        if data.get("kind") in ("sdh", "translation") and data.get("status") == "complete":
            src = data.get("source") or {}
            found.append({
                "name": path.stem,
                "path": path,
                "platform": data["platform"],
                "language": data["language"],
                "kind": data["kind"],
                "section": src.get("section", ""),
                "revision": src.get("revision", ""),
            })
    return found
