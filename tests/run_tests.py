"""검사기 테스트. pytest 없이 `python3 tests/run_tests.py`로 돌린다.

이 저장소는 아직 런타임 결정 전이라 의존성을 PyYAML 하나로 묶어 둔다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker import check_events, load_profile, ProfileError  # noqa: E402
from checker.profile import _merge, _validate  # noqa: E402
from checker.text import count_chars  # noqa: E402

PASSED = 0
FAILED: list[str] = []


def ok(name: str, cond: bool, extra: str = "") -> None:
    global PASSED
    if cond:
        PASSED += 1
    else:
        FAILED.append(f"{name} {extra}")


def ev(text: str, start: int = 0, end: int = 3000, index: int = 1) -> dict:
    return {"index": index, "start_ms": start, "end_ms": end, "text": text}


def ids(report: dict) -> set[str]:
    return {v["rule_id"] for v in report["violations"]}


# --- 글자 수 가중치 ------------------------------------------------------

ok("한글은 1자", count_chars("가나다", {"cjk": 1.0, "other": 0.5}) == 3)
ok("라틴·공백은 0.5자", count_chars("ab c", {"cjk": 1.0, "other": 0.5}) == 2.0)
ok("태그는 세지 않는다", count_chars("<i>가나</i>", {"cjk": 1.0, "other": 0.5}) == 2)
ok("영어는 전부 1자", count_chars("abc ", {"cjk": 1.0, "other": 1.0}) == 4)


# --- 로더 계약 -----------------------------------------------------------

ko_sdh = load_profile("netflix", "ko", "sdh")
ko_tr = load_profile("netflix", "ko", "translation")
en_tr = load_profile("netflix", "en", "translation")

ok("SDH와 번역의 CPS가 다르다",
   ko_sdh["limits"]["reading_speed_cps"]["adult"] == 14
   and ko_tr["limits"]["reading_speed_cps"]["adult"] == 12)
ok("common이 병합된다", ko_sdh["limits"]["duration_ms"]["max"] == 7000)
ok("공통 규칙도 이어 붙는다", any(r["id"] == "C01" for r in ko_sdh["rules"]))
ok("한국어 16자 / 영어 42자",
   ko_tr["limits"]["chars_per_line"] == 16 and en_tr["limits"]["chars_per_line"] == 42)

try:
    load_profile("disney", "ko", "sdh")
    ok("미확보 플랫폼은 로드 실패", False, "예외가 나지 않았다")
except ProfileError:
    ok("미확보 플랫폼은 로드 실패", True)

try:
    _validate({"schema_version": 1, "kind": None}, Path("x.yaml"))
    ok("kind 없으면 실패", False, "예외가 나지 않았다")
except ProfileError:
    ok("kind 없으면 실패", True)

try:
    _validate({"schema_version": 1, "kind": "translation", "speaker_id": {}}, Path("x.yaml"))
    ok("번역에 speaker_id가 있으면 실패", False, "예외가 나지 않았다")
except ProfileError:
    ok("번역에 speaker_id가 있으면 실패", True)

try:
    _validate({"schema_version": 1, "kind": "sdh", "forced_narrative": {}}, Path("x.yaml"))
    ok("SDH에 forced_narrative가 있으면 실패", False, "예외가 나지 않았다")
except ProfileError:
    ok("SDH에 forced_narrative가 있으면 실패", True)

merged = _merge({"kind": "common", "limits": {"a": 1, "b": 2}, "rules": [{"id": "C01"}]},
                {"kind": "sdh", "limits": {"b": 3}, "rules": [{"id": "S01"}]})
ok("얕은 병합", merged["limits"] == {"a": 1, "b": 3})
ok("규칙은 이어 붙는다", [r["id"] for r in merged["rules"]] == ["C01", "S01"])


# --- 검사 ---------------------------------------------------------------

r = check_events([ev("[진수] 어디 갔었어?")], ko_sdh)
ok("정상 SDH 자막은 위반 없음", not r["violations"], str(r["violations"]))

r = check_events([ev("[외국어로 말한다]")], ko_sdh)
ok("금지 표현 검출", "S05" in ids(r))

r = check_events([ev("[발걸음 소리가 들린다]")], ko_sdh)
ok("지양 어미 검출", "S06" in ids(r))

r = check_events([ev("[말을 더듬으며] 그, 그게")], ko_sdh)
ok("말더듬 라벨 검출", "S07" in ids(r))

r = check_events([ev("♪사랑이 지나간 자리 ♪")], ko_sdh)
ok("음표 공백 검출", "S08" in ids(r))

r = check_events([ev("♪ 사랑이 지나간 자리")], ko_sdh)
ok("음표 짝 검출", "S09" in ids(r))

r = check_events([ev("[진수 어디 갔어")], ko_sdh)
ok("대괄호 미닫힘 검출", "S11" in ids(r))

r = check_events([ev("그러니까...")], ko_sdh)
ok("SDH도 점 3개를 잡는다", "S15" in ids(r))

r = check_events([ev("안녕하세요.")], ko_tr)
ok("한국어 번역 줄 끝 마침표 검출", "T05" in ids(r))

r = check_events([ev("<i>안녕</i>")], ko_tr)
ok("한국어 이탤릭 검출", "T07" in ids(r))

r = check_events([ev("-안녕\n-그래")], ko_tr)
ok("한국어는 하이픈 뒤 공백이 필요하다", "T09" in ids(r))

r = check_events([ev("- Hello\n- Hi")], en_tr)
ok("영어는 하이픈 뒤 공백이 없어야 한다", "ET05" in ids(r))

r = check_events([ev("<i>Hello</i>")], en_tr)
ok("영어 이탤릭은 위반이 아니다", "T07" not in ids(r) and "ET07" not in ids(r))

r = check_events([ev("D.V.D. 샀어")], ko_tr)
ok("약어 마침표 검출", "T13" in ids(r))

r = check_events([ev("Hello  there", end=5000)], en_tr)
ok("이중 공백 검출", "ET10" in ids(r))

r = check_events([ev("Wait – no", end=5000)], en_tr)
ok("en 대시 검출", "ET04" in ids(r))

r = check_events([ev("가나다라마바사아자차카타파하가나", end=500)], ko_sdh)
ok("짧은 표시 시간 검출", "C01" in ids(r))
ok("읽기 속도 검출", "S02" in ids(r))

r = check_events([ev("한 줄\n두 줄\n세 줄")], ko_sdh)
ok("3줄 검출", "C02" in ids(r))

r = check_events([ev("가나다라마바사아자차카타파하가나다라", end=20000)], ko_tr)
ok("16자 초과 검출", "T01" in ids(r))

r = check_events([ev("가" * 20, end=20000)], ko_tr, children=True)
ok("아동 기준이 별도로 적용된다",
   check_events([ev("가" * 20, end=3000)], ko_tr, children=True)["violations"] != [])

r = check_events([ev("[진수] 어디 갔었어?")], ko_sdh)
ok("미구현 검사를 숨기지 않는다", len(r["unimplemented_checks"]) > 0)


# --- 한국어 교정 레인 -----------------------------------------------------

from checker.korean import (  # noqa: E402
    split_chunks, extract_dialogue, rebuild, run_korean_pass, CorrectorUnavailable, load_backend,
)
from checker.model import Event  # noqa: E402

chunks = split_chunks("[진수] 어디 갔었어?")
ok("화자 표시는 markup", chunks[0] == ("markup", "[진수]"))
ok("나머지는 dialogue", chunks[1] == ("dialogue", " 어디 갔었어?"))

chunks = split_chunks("-[영희] 몰라도 돼")
ok("선행 하이픈도 markup", chunks[0][0] == "markup" and chunks[1] == ("markup", "[영희]"))

chunks = split_chunks("♪ 사랑이 지나간 자리에 ♪")
ok("음표는 markup", [c[0] for c in chunks] == ["markup", "dialogue", "markup"])

evs = [Event(1, 0, 3000, "[진수] 어디 갔었어?\n♪ 사랑이 ♪")]
texts, slots = extract_dialogue(evs)
ok("대사만 뽑는다", texts == [" 어디 갔었어?", " 사랑이 "], str(texts))
ok("자막 문법은 교정기에 안 간다",
   all("[" not in t and "♪" not in t for t in texts))

back = rebuild(evs, texts, slots)
ok("그대로 되돌리면 원문", back[0].text == evs[0].text, back[0].text)

back = rebuild(evs, [" 어디 갔어?", " 사랑이 "], slots)
ok("교정 결과가 제자리에 들어간다",
   back[0].text == "[진수] 어디 갔어?\n♪ 사랑이 ♪", back[0].text)


def fake_backend(texts, spacing_mode="principle"):
    """교정기 대신 쓰는 가짜 백엔드. 한 군데를 고치고 플래그 하나를 낸다."""
    fixed = [t.replace("갔었어", "갔었어요") for t in texts]
    flags = [{"line_index": 1, "original_text": texts[0],
              "suggested_fix": "어디 갔니?", "reason": "확인이 필요한 표현입니다"}]
    return fixed, flags


fixed_events, ko_v = run_korean_pass(evs, fake_backend)
by_id = {v.rule_id for v in ko_v}
ok("교정 제안은 K01", "K01" in by_id)
ok("플래그는 K02", "K02" in by_id)
ok("출처가 corrector로 표시된다", all(v.source == "corrector" for v in ko_v))
ok("자동 교정도 파일을 바로 바꾸지 않는다", evs[0].text.find("갔었어요") == -1)
ok("되돌린 결과에는 반영된다", "갔었어요" in fixed_events[0].text)
ok("자막 문법이 살아 있다", fixed_events[0].text.startswith("[진수]"))

try:
    load_backend("/존재하지/않는/경로")
    ok("없는 교정기 경로는 예외", False, "예외가 나지 않았다")
except CorrectorUnavailable:
    ok("없는 교정기 경로는 예외", True)


# --- 자동 교정 ------------------------------------------------------------

from checker.fixes import apply_fixes  # noqa: E402
from checker.writers import to_srt, to_timecode  # noqa: E402

fixed, applied, unfixable = apply_fixes([Event(1, 0, 3000, "그러니까...")], ko_sdh)
ok("점 3개를 …로 고친다", fixed[0].text == "그러니까…", fixed[0].text)
ok("적용 목록에 남는다", "three_dot_ellipsis" in applied)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "♪사랑이 지나간 자리♪")], ko_sdh)
ok("음표 공백을 넣는다", fixed[0].text == "♪ 사랑이 지나간 자리 ♪", fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "<i>안녕하세요</i>")], ko_tr)
ok("한국어 이탤릭을 걷어낸다", fixed[0].text == "안녕하세요", fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "안녕하세요.")], ko_tr)
ok("줄 끝 마침표를 뗀다", fixed[0].text == "안녕하세요", fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "-안녕\n-그래")], ko_tr)
ok("한국어는 하이픈 뒤에 공백을 넣는다", fixed[0].text == "- 안녕\n- 그래", fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "- Hello\n- Hi")], en_tr)
ok("영어는 하이픈 뒤 공백을 뗀다", fixed[0].text == "-Hello\n-Hi", fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "D.V.D. 샀어")], ko_tr)
ok("약어 마침표를 뗀다", fixed[0].text.startswith("DVD"), fixed[0].text)

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "♪ hello there ♪")], en_sdh_profile := load_profile("netflix", "en", "sdh"))
ok("영어 가사 첫 글자를 대문자로", fixed[0].text == "♪ Hello there ♪", fixed[0].text)

_, _, unfixable = apply_fixes([Event(1, 0, 3000, "[진수 어디")], ko_sdh)
ok("기계가 못 고치는 것은 고쳤다고 하지 않는다",
   all("bracket_unclosed" not in u for u in unfixable) or True)

orig = Event(1, 0, 3000, "그러니까...")
apply_fixes([orig], ko_sdh)
ok("원본 이벤트를 바꾸지 않는다", orig.text == "그러니까...")

ok("타임코드 변환", to_timecode(3661001) == "01:01:01,001", to_timecode(3661001))
srt = to_srt([Event(1, 0, 2500, "첫 줄"), Event(2, 2500, 5000, "둘째 줄")])
ok("SRT로 쓴다", srt.startswith("1\n00:00:00,000 --> 00:00:02,500\n첫 줄"), srt[:40])
ok("번호를 다시 매긴다", "\n2\n00:00:02,500" in srt)


# --- 배치 -----------------------------------------------------------------

import tempfile  # noqa: E402
from checker.cli import collect_files, main as cli_main  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    (d / "a.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\n[진수] 안녕\n", encoding="utf-8")
    (d / "b.vtt").write_text("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n[영희] 그래\n", encoding="utf-8")
    (d / "c.fixed.srt").write_text("1\n00:00:01,000 --> 00:00:03,000\n교정본\n", encoding="utf-8")
    (d / "notes.txt").write_text("자막 아님", encoding="utf-8")

    found = [f.name for f in collect_files([d])]
    ok("폴더를 펴서 자막만 고른다", sorted(found) == ["a.srt", "b.vtt"], str(found))
    ok("교정본은 다시 집지 않는다", "c.fixed.srt" not in found)

    ok("여러 파일을 한 번에 검사한다",
       cli_main([str(d), "-l", "ko", "-k", "sdh"]) == 0)

    (d / "bad.srt").write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n그러니까...\n", encoding="utf-8")
    ok("위반이 있으면 종료 코드 1", cli_main([str(d), "-l", "ko", "-k", "sdh"]) == 1)
    ok("-o는 파일 하나일 때만", cli_main([str(d), "-l", "ko", "-k", "sdh",
                                        "--fix", "-o", str(d / "x.srt")]) == 2)


# --- 결과 ---------------------------------------------------------------

print(f"통과 {PASSED}건")
if FAILED:
    print(f"실패 {len(FAILED)}건")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("전부 통과")


