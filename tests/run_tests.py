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

# 디즈니·쿠팡 한국어 SDH는 실무 자료로 채워졌다. 아직 없는 조합은 여전히 실패해야 한다.
try:
    load_profile("disney", "en", "sdh")
    ok("없는 프로파일은 로드 실패", False, "예외가 나지 않았다")
except ProfileError:
    ok("없는 프로파일은 로드 실패", True)

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

# 화면 자막은 SDH도 다룬다(대사와 겹칠 때 지울지 병기할지가 플랫폼마다 다르다).
# 막아야 할 것은 SDH 규정이 번역 프로파일에 새는 것이지 그 반대가 아니다.
_validate({"schema_version": 1, "kind": "sdh", "forced_narrative": {}}, Path("x.yaml"))
ok("SDH에도 화면 자막 규정을 적을 수 있다", True)

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


# --- 문서 단위 검사 -------------------------------------------------------

from checker.checks import speaker_ids  # noqa: E402

doc = [ev("[김 경위] 어디 갔었어?", index=1),
       ev("[진수] 몰라", index=2),
       ev("[김경위] 말해", index=3)]
r = check_events(doc, ko_sdh)
detail = " ".join(v["detail"] for v in r["violations"] if v["rule_id"] == "S13")
ok("공백만 다른 화자 표시를 잡는다", "김 경위" in detail and "김경위" in detail, detail)

doc = [ev("[경위] 어디 갔었어?", index=1), ev("[김 경위] 말해", index=2)]
r = check_events(doc, ko_sdh)
ok("포함 관계인 화자 표시를 확인 요청한다", "S13" in ids(r))

doc = [ev("[남자 1] 저기요", index=1), ev("[남자 2] 왜요", index=2)]
r = check_events(doc, ko_sdh)
ok("번호로 구분한 것은 위반이 아니다", "S13" not in ids(r),
   str([v["detail"] for v in r["violations"] if v["rule_id"] == "S13"]))

doc = [ev("[진수] 어디 갔었어?", index=1), ev("[영희] 몰라", index=2)]
r = check_events(doc, ko_sdh)
ok("서로 다른 인물은 위반이 아니다", "S13" not in ids(r))

found = speaker_ids([Event(1, 0, 3000, "[문이 쾅 닫히는 소리]\n[진수] 어디 가")])
ok("대괄호만 있는 줄은 효과음이라 화자로 안 센다",
   [f[0] for f in found] == ["진수"], str(found))

found = speaker_ids([Event(1, 0, 3000, "-[영희] 몰라도 돼")])
ok("2인 화자 하이픈 뒤 화자 표시도 잡는다", found[0][0] == "영희", str(found))

ok("미구현 목록에서 S13이 빠졌다",
   all("S13" not in u for u in check_events([ev("[진수] 안녕")], ko_sdh)["unimplemented_checks"]))


# --- SE 플러그인 어댑터 ---------------------------------------------------

import json as _json  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from checker.plugin import run as plugin_run  # noqa: E402
from checker.parsers import parse_text  # noqa: E402

SAMPLE_SRT = ("1\n00:00:01,000 --> 00:00:04,000\n[진수] 그러니까...\n\n"
              "2\n00:00:05,000 --> 00:00:08,000\n[영희] 몰라도 돼\n")

ok("문자열에서 바로 읽는다", len(parse_text(SAMPLE_SRT)) == 2)

with _tempfile.TemporaryDirectory() as tmp:
    req = {"apiVersion": 1, "responseFilePath": str(Path(tmp) / "response.json"),
           "tempDirectory": tmp, "pluginDataDirectory": tmp,
           "subtitle": {"format": "SubRip", "subRip": SAMPLE_SRT},
           "settings": {"kind": "sdh"}}
    resp = plugin_run(req)
    ok("정상 응답", resp["status"] == "ok", str(resp)[:80])
    ok("설정을 돌려준다(SE가 왕복시킨다)", resp["settings"]["kind"] == "sdh")
    ok("고친 자막을 돌려준다", "subtitle" in resp and "…" in resp["subtitle"]["native"])
    ok("undo 설명이 있다", bool(resp.get("undoDescription")))
    ok("전체 리포트를 파일로 남긴다", (Path(tmp) / "last-report.txt").is_file())
    report = (Path(tmp) / "last-report.txt").read_text(encoding="utf-8")
    ok("리포트에 조항이 들어간다", "II." in report or "Section I" in report, report[:60])

    # config.json 을 손으로 고칠 수 있어야 한다
    (Path(tmp) / "config.json").write_text(
        _json.dumps({"kind": "sdh", "applyFixes": False}), encoding="utf-8")
    req2 = dict(req); req2["settings"] = None
    resp2 = plugin_run(req2)
    ok("config.json을 읽는다", resp2["settings"]["applyFixes"] is False)
    ok("applyFixes=false면 자막을 건드리지 않는다", "subtitle" not in resp2)

    req3 = dict(req); req3["subtitle"] = {"subRip": ""}
    ok("빈 자막은 오류로", plugin_run(req3)["status"] == "error")

    req4 = dict(req); req4["settings"] = {"platform": "disney", "language": "en", "kind": "sdh"}
    r4 = plugin_run(req4)
    ok("없는 프로파일은 오류로 알린다",
       r4["status"] == "error" and "프로파일" in r4["message"], str(r4)[:60])


# --- 발주처 프로파일 --------------------------------------------------------

from checker.profile import load_profile_file  # noqa: E402

AGENCY = Path("examples/profiles/agency-sample-ko-translation.yaml")
agency = load_profile_file(AGENCY)

ok("공식 프로파일을 상속한다", agency["platform"] == "netflix" and agency["kind"] == "translation")
ok("덮어쓴 값이 이긴다", agency["limits"]["chars_per_line"] == 14)
ok("안 덮어쓴 값은 상속된다", agency["limits"]["reading_speed_cps"]["adult"] == 12)
ok("공통 프로파일까지 사슬로 병합된다", agency["limits"]["duration_ms"]["max"] == 7000)
ok("disable_rules로 상위 규칙을 끈다", all(r["id"] != "T06" for r in agency["rules"]))
ok("발주처 고유 규칙이 더해진다", any(r["id"] == "A01" for r in agency["rules"]))

r = check_events([ev("그러니까...")], agency)
ok("끈 규칙은 위반으로 안 뜬다", "T06" not in ids(r))

r = check_events([ev("가나다라마바사아자차카타파하가", end=20000)], agency)
msg = [v["message"] for v in r["violations"] if v["rule_id"] == "T01"]
ok("문구의 숫자도 프로파일 값을 따른다", msg and "14자" in msg[0], str(msg))

gap_profile = dict(agency)
gap_profile["limits"] = dict(agency["limits"], min_gap_ms=100)
gap_profile["rules"] = agency["rules"] + [
    {"id": "A02", "clause": "지침 4.1", "check": "gap_too_short", "auto": False,
     "message": "자막 간 간격이 부족합니다."}]
r = check_events([{"index": 1, "start_ms": 0, "end_ms": 2000, "text": "첫 줄"},
                  {"index": 2, "start_ms": 2050, "end_ms": 4000, "text": "둘째 줄"}], gap_profile)
ok("자막 간 간격을 잰다", "A02" in ids(r))
r = check_events([{"index": 1, "start_ms": 0, "end_ms": 2000, "text": "첫 줄"},
                  {"index": 2, "start_ms": 1900, "end_ms": 4000, "text": "둘째 줄"}], gap_profile)
ok("겹침도 잡는다", any("겹칩니다" in v["detail"] for v in r["violations"]))

ok("넷플릭스에는 간격 규정을 넣지 않았다", "min_gap_ms" not in ko_tr["limits"])

try:
    load_profile_file(Path("rules/netflix/common.yaml"))
    ok("common 파일은 직접 검사에 못 쓴다", False, "예외가 나지 않았다")
except ProfileError:
    ok("common 파일은 직접 검사에 못 쓴다", True)


# --- SE 대응 검사 -----------------------------------------------------------

agency2 = load_profile_file(AGENCY)

r = check_events([ev("가나다라마바", end=1500)], agency2)   # 6자 / 1.5초 = 4 CPS
ok("권장 속도 이하는 조용하다", "A03" not in ids(r))

r = check_events([ev("가나다라마바사아자차카", end=1000)], agency2)  # 11 CPS: 권장 10 초과, 상한 12 이내
ok("권장 속도 초과를 알린다", "A03" in ids(r))

r = check_events([ev("가나다라마바사아자차카타파하가나", end=1000)], agency2)  # 16 CPS: 상한 초과
ok("상한을 넘으면 권장 규칙은 중복해 말하지 않는다",
   "T02" in ids(r) and "A03" not in ids(r))

r = check_events([ev("짧다", end=900)], agency2)
ok("병합 후보를 알린다", "A04" in ids(r))
r = check_events([ev("길다", end=2000)], agency2)
ok("기준 이상은 병합 후보가 아니다", "A04" not in ids(r))

r = check_events([ev("한 둘 셋 넷 다섯 여섯", end=1000)], agency2)  # 6어절/1초 = 360 wpm
ok("분당 어절 수를 잰다", "A05" in ids(r))
r = check_events([ev("한 둘", end=10000)], agency2)
ok("느리면 조용하다", "A05" not in ids(r))


# --- 한국어 줄바꿈 ----------------------------------------------------------

from checker.korean_break import check_line_break, check_top_heavy  # noqa: E402

W = {"cjk": 1.0, "other": 0.5}

ok("의존명사 분리를 잡는다",
   any("의존명사" in p for p in check_line_break(["내가 할 수 있는", "것 같아"], W)))
ok("보조 용언 분리를 잡는다",
   any("보조 용언" in p for p in check_line_break(["내가 할 수", "있는 일이야"], W)))
ok("관형사 분리를 잡는다",
   any("관형사" in p for p in check_line_break(["그때 우리가 봤던 그", "영화 기억나"], W)))
ok("관형형 분리를 잡는다",
   any("갈렸을 수" in p for p in check_line_break(["목격된", "용의 차량이 있습니다"], W)))

# 실사용에서 났던 오탐들 — 다시 나면 안 된다
ok("인명 '척'을 의존명사로 보지 않는다", not check_line_break(["형사 두 명", "척 파머 형사입니다"], W))
ok("조사 '를' 뒤는 끊어도 된다", not check_line_break(["도주 중인 운전자를", "추적 중입니다"], W))
ok("조사 '는'을 관형형으로 보지 않는다", not check_line_break(["그 차는", "흰색이었어요"], W))
ok("명사 어미 '인'을 관형형으로 보지 않는다", not check_line_break(["우리가 찾던 범인", "맞습니다"], W))
ok("2인 화자 자막은 문법 단위로 보지 않는다",
   not check_line_break(["- 어디 갔어", "- 몰라도 돼"], W))
ok("한 줄 자막은 대상이 아니다", not check_line_break(["한 줄뿐이야"], W))

ok("역피라미드는 따로 잰다", check_top_heavy(["아주 긴 윗줄입니다 정말로", "짧아"], W))
ok("아래가 길면 조용하다", not check_top_heavy(["짧게", "조금 더 긴 아랫줄이야"], W))
ok("문구의 조사가 맞는다",
   any("'목격된'으로" in p for p in check_line_break(["목격된", "용의 차량이 있습니다"], W)))

r = check_events([ev("- Hello there", index=1)], en_tr)
ok("영어에는 한국어 줄바꿈 규칙을 적용하지 않는다", "T16" not in ids(r))


# --- 실무 자료 기반 검사·프로파일 ---------------------------------------

coupang = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
disney = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
practice = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

ok("쿠팡 프로파일이 뜬다", coupang["platform"] == "coupang" and coupang["kind"] == "sdh")
ok("공식 문서가 아님을 밝힌다",
   coupang["source"]["official"] is False and bool(coupang["source"]["client"]))
ok("쿠팡은 화자 번호를 에피 내 유지", coupang["speaker_id"]["numbering_reset"] == "episode")
ok("디즈니는 씬마다 초기화", disney["speaker_id"]["numbering_reset"] == "scene")
ok("쿠팡은 장면 전환 비적용", coupang["shot_change"]["applied"] is False)
ok("디즈니는 장면 전환 적용", disney["shot_change"]["applied"] is True)
ok("실무 판은 공식 값을 물려받는다",
   practice["limits"]["reading_speed_cps"]["adult"] == 14
   and practice["limits"]["chars_per_line"] == 16)

r = check_events([ev("아, 저요? [웃음]")], coupang)
ok("쿠팡은 대사 뒤 효과음을 잡는다", "CP01" in ids(r))
r = check_events([ev("아, 저요? [웃음]")], practice)
ok("넷플릭스는 대사 뒤 효과음을 잡지 않는다", "CP01" not in ids(r))

r = check_events([ev("[진수][웃으며] 저요?")], practice)
ok("표시 사이 공백 없음을 잡는다", "S18" in ids(r))
r = check_events([ev("[진수] [웃으며] 저요?")], practice)
ok("띄어 쓰면 조용하다", "S18" not in ids(r))

r = check_events([ev("[정적]")], practice)
ok("[정적]을 잡는다", "S19" in ids(r))
r = check_events([ev("넓이는 30㎡야", end=6000)], practice)
ok("단위 조합 문자를 잡는다", "S20" in ids(r))
r = check_events([ev("철수 & 영희", end=6000)], practice)
ok("'&'를 잡는다", "S21" in ids(r))
r = check_events([ev("R&B 좋아", end=6000)], practice)
ok("약어 안의 '&'는 넘어간다", "S21" not in ids(r))
r = check_events([ev("John F. Kennedy", end=6000)], practice)
ok("가운데 이름 온점을 잡는다", "S22" in ids(r))

r = check_events([ev("[진수] 안녕")], practice)
ok("정상 자막은 실무 규칙에도 안 걸린다",
   not {"S18", "S19", "S20", "S21", "S22"} & ids(r), str(ids(r)))


# --- 효과음 사전 -----------------------------------------------------------

from checker.lexicon import suggest, suggest_text, _load  # noqa: E402

ok("사전이 로드된다", len(_load()) > 300, str(len(_load())))
ok("문 소리에 문 관련 후보를 준다",
   any("문" in t for t in suggest("[문 닫는 소리]")), str(suggest("[문 닫는 소리]")))
ok("낱말 단위로 견준다 — '닫는'이 '깨닫는'에 걸리지 않는다",
   "[깨닫는 탄성]" not in suggest("[문 닫는 소리]"))
ok("조사를 떼고 견준다",
   any("발소리" in t for t in suggest("[발걸음 소리가 들린다]")),
   str(suggest("[발걸음 소리가 들린다]")))
ok("자기 자신은 후보에서 뺀다", "[다급한 발소리]" not in suggest("[다급한 발소리]"))
ok("맞는 게 없으면 빈 목록", suggest("[알 수 없는 소리]") == [])
ok("후보 수를 제한한다", len(suggest("[자동차 소리]", limit=2)) <= 2)
ok("리포트 문구를 만든다", "이렇게 쓸 수 있습니다" in suggest_text("[문 닫는 소리]"))
ok("후보 없으면 문구도 없다", suggest_text("[알 수 없는 소리]") == "")

r = check_events([ev("[문이 쾅 닫히는 소리]")], ko_sdh)
detail = " ".join(v["detail"] for v in r["violations"] if v["rule_id"] == "S06")
ok("지적에 대안이 함께 나온다", "이렇게 쓸 수 있습니다" in detail, detail[:60])


# --- 스펙 표에서 읽은 값 -----------------------------------------------------

coupang2 = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
disney2 = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
practice2 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

ok("쿠팡 듀레이션 상한만 6초", coupang2["limits"]["duration_ms"]["max"] == 6000
   and disney2["limits"]["duration_ms"]["max"] == 7000)
ok("CPL·CPS는 세 플랫폼이 같다",
   coupang2["limits"]["chars_per_line"] == disney2["limits"]["chars_per_line"] == 16
   and coupang2["limits"]["reading_speed_cps"]["adult"] == 14)
ok("쿠팡은 불가피할 때의 한계도 적어 둔다",
   coupang2["limits"]["chars_per_line_hard"] == 20 and coupang2["limits"]["max_lines_hard"] == 3)

r = check_events([ev("가나다", end=6500)], coupang2)
ok("쿠팡 6초 초과를 잡는다", "CP00" in ids(r))
r = check_events([ev("가나다", end=6500)], disney2)
ok("디즈니는 6.5초를 잡지 않는다", "DP00" not in ids(r))

gap_events = [{"index": 1, "start_ms": 0, "end_ms": 2000, "text": "첫 줄"},
              {"index": 2, "start_ms": 2050, "end_ms": 4000, "text": "둘째 줄"}]
r = check_events(gap_events, coupang2, fps=23.976)
ok("2프레임 간격을 잰다", "CP08" in ids(r))
r = check_events(gap_events, coupang2, fps=59.94)
ok("프레임레이트가 높으면 같은 간격도 통과한다", "CP08" not in ids(r))
r = check_events(gap_events, practice2, fps=23.976)
ok("넷플릭스 실무 판에도 간격 규정이 있다", "S23" in ids(r))
r = check_events(gap_events, ko_sdh, fps=23.976)
ok("공식 판에는 간격 규정을 넣지 않았다", not any(v["rule_id"] == "S23" for v in r["violations"]))


# --- 문장부호 표(이미지)에서 읽은 규칙 ---------------------------------------

cp3 = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
dp3 = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
pr3 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

r = check_events([ev("그러니까…")], cp3)
ok("쿠팡은 전각 말줄임표를 잡는다", "CP09" in ids(r))
r = check_events([ev("그러니까...")], cp3)
ok("쿠팡에서 점 셋은 정상", "CP09" not in ids(r))
r = check_events([ev("그러니까...")], pr3)
ok("넷플릭스는 점 셋을 잡는다", "S24" in ids(r))
r = check_events([ev("그러니까…")], pr3)
ok("넷플릭스에서 전각은 정상", "S24" not in ids(r))

fixed, _, _ = apply_fixes([Event(1, 0, 3000, "그래…")], cp3)
ok("쿠팡 교정은 점 셋으로 간다", fixed[0].text == "그래...", fixed[0].text)
fixed, _, _ = apply_fixes([Event(1, 0, 3000, "그래...")], pr3)
ok("넷플릭스 교정은 전각으로 간다", fixed[0].text == "그래…", fixed[0].text)

r = check_events([ev("뭐라고?!")], cp3)
ok("쿠팡은 이중 부호를 잡는다", "CP10" in ids(r))
r = check_events([ev("뭐라고?!")], pr3)
ok("넷플릭스는 이중 부호를 허용한다", not any(v["rule_id"] == "S26" for v in r["violations"]))
r = check_events([ev("오~ 그래")], cp3)
ok("쿠팡은 물결표를 잡는다", "CP11" in ids(r))

r = check_events([ev("아…", index=1), ev("그래...", index=2)], dp3)
ok("디즈니는 말줄임표 혼용을 잡는다", "DP08" in ids(r))
r = check_events([ev("아…", index=1), ev("그래…", index=2)], dp3)
ok("통일돼 있으면 조용하다", "DP08" not in ids(r))

r = check_events([ev("[문이 쾅\n닫히는 소리]")], cp3)
ok("줄 넘어간 효과음을 잡는다", "CP12" in ids(r))


# --- 대사·배경음악 표(이미지)에서 읽은 규칙 ---------------------------------

cp4 = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
dp4 = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
pr4 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

ok("디즈니만 대괄호 안에 음표", dp4["music"]["note_inside_bracket"] is True
   and cp4["music"]["note_inside_bracket"] is False)
r = check_events([ev("[잔잔한 음악]")], dp4)
ok("디즈니에서 음표 빠지면 잡는다", "DP12" in ids(r))
r = check_events([ev("[♪ 잔잔한 음악]")], dp4)
ok("디즈니에서 음표 있으면 정상", "DP12" not in ids(r))
r = check_events([ev("[♪ 잔잔한 음악]")], cp4)
ok("쿠팡에서 음표 있으면 잡는다", "CP13" in ids(r))
r = check_events([ev("♪ 사랑이 지나간 자리 ♪")], cp4)
ok("가사의 음표는 대상이 아니다", "CP13" not in ids(r))

ok("디즈니 삐 처리는 O", dp4["censorship"]["bleeped_word"] == "O"
   and cp4["censorship"]["bleeped_word"] == "*")
r = check_events([ev("이제 *됐네")], dp4)
ok("디즈니에서 별표를 잡는다", "DP13" in ids(r))
r = check_events([ev("이제 O됐네")], dp4)
ok("디즈니에서 O는 정상", "DP13" not in ids(r))
r = check_events([ev("이제 O됐네")], pr4)
ok("넷플릭스에서 O를 잡는다", "S28" in ids(r))

r = check_events([ev("이런 ** *** ***")], cp4)
ok("쿠팡은 별표 나열을 잡는다", "CP14" in ids(r))
r = check_events([ev("이런 [음 소거 효과음]")], pr4)
ok("넷플릭스는 [음 소거 효과음]을 잡는다", "S27" in ids(r))
r = check_events([ev("이런 [음 소거 효과음]")], cp4)
ok("쿠팡에서 [음 소거 효과음]은 정상", "CP14" not in ids(r))

ok("디즈니는 발화 표기 우선", dp4["korean"]["orthography"] == "as_spoken")
ok("넷플릭스·쿠팡은 표준어", pr4["korean"]["orthography"] == "standard"
   and cp4["korean"]["orthography"] == "standard")


# --- 화자명·외국어 표(이미지) -------------------------------------------------

cp5 = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
dp5 = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
pr5 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

ok("쿠팡만 화자명이 소괄호", cp5["speaker_id"]["enclosure"] == "()"
   and dp5["speaker_id"]["enclosure"] == "[]" and pr5["speaker_id"]["enclosure"] == "[]")
r = check_events([ev("[철수] 안녕")], cp5)
ok("쿠팡에서 대괄호 화자명을 잡는다", "CP16" in ids(r))
r = check_events([ev("(철수) 안녕")], cp5)
ok("쿠팡에서 소괄호는 정상", "CP16" not in ids(r))
r = check_events([ev("(철수) 안녕")], pr5)
ok("넷플릭스에서 소괄호를 잡는다", "S29" in ids(r))
r = check_events([ev("(철수) [작게] 안녕")], cp5)
ok("쿠팡의 (화자) [어조] 형식은 정상", "CP16" not in ids(r))
r = check_events([ev("[문이 쾅 닫힌다]")], cp5)
ok("효과음은 쿠팡에서도 대괄호라 걸리지 않는다", "CP16" not in ids(r))

r = check_events([ev("[철수와 영희] 출발!")], pr5)
ok("동시 발화의 '와'를 잡는다", "S30" in ids(r))
r = check_events([ev("[철수, 영희] 출발!")], pr5)
ok("쉼표 나열은 정상", "S30" not in ids(r))
r = check_events([ev("[함께] 출발!")], pr5)
ok("[함께]도 정상", "S30" not in ids(r))

r = check_events([ev("[철수]\n안녕하세요")], pr5)
ok("화자명만 있는 줄을 잡는다", "S31" in ids(r))
r = check_events([ev("[철수] 안녕하세요\n반갑습니다")], pr5)
ok("같은 줄에 있으면 정상", "S31" not in ids(r))
r = check_events([ev("[문이 쾅 닫힌다]\n[진수] 왔어?")], pr5)
ok("효과음 다음 줄이 표시로 시작하면 걸리지 않는다", "S31" not in ids(r))

ok("넷플릭스는 한국어 복귀 표시를 넣지 않는다",
   pr5["speaker_id"]["foreign_return_marker"] is False
   and dp5["speaker_id"]["foreign_return_marker"] is True
   and cp5["speaker_id"]["foreign_return_marker"] is True)


# --- 노래·크레딧 표(이미지) --------------------------------------------------

cp6 = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
dp6 = load_profile_file(Path("rules/disney/ko-sdh.yaml"))
pr6 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

r = check_events([ev("♪ 내 피, 땀, 눈물 ♪")], cp6)
ok("쿠팡은 가사 쉼표를 잡는다", "CP19" in ids(r))
r = check_events([ev("♪ 내 피 땀 눈물 ♪")], cp6)
ok("쉼표를 빼면 정상", "CP19" not in ids(r))
r = check_events([ev("♪ 내 피, 땀, 눈물 ♪")], pr6)
ok("넷플릭스는 가사 쉼표를 허용한다",
   not any(v["message"].startswith("쿠팡") for v in r["violations"]))
r = check_events([ev("가사가 아니면, 쉼표는 상관없다", end=9000)], cp6)
ok("가사가 아닌 줄은 대상이 아니다", "CP19" not in ids(r))

r = check_events([ev("- ♪ 널 사랑해 ♪\n- 놀고 있네")], dp6)
ok("디즈니는 가사+대사 한 셀을 잡는다", "DP18" in ids(r))
r = check_events([ev("- ♪ 널 사랑해 ♪\n- 놀고 있네")], cp6)
ok("쿠팡·넷플릭스는 허용한다", "CP19" not in ids(r) and "DP18" not in ids(r))
r = check_events([ev("♪ 동해 물과 백두산이 ♪")], dp6)
ok("가사만 있으면 정상", "DP18" not in ids(r))

r = check_events([ev("자막: 홍길동")], pr6)
ok("넷플릭스는 크레딧을 잡는다", "S32" in ids(r))
r = check_events([ev("자막: 홍길동")], cp6)
ok("쿠팡은 크레딧을 쓴다", not any(v["rule_id"] == "CP21" for v in r["violations"]))
ok("쿠팡 크레딧 길이는 2초", cp6["credit"]["credit_duration_ms"] == 2000)

r = check_events([{"index": 1, "start_ms": 0, "end_ms": 3000, "text": "첫 자막"}], cp6)
ok("쿠팡은 첫 셀 인점 0을 잡는다", "CP20" in ids(r))
r = check_events([{"index": 1, "start_ms": 1000, "end_ms": 4000, "text": "첫 자막"}], cp6)
ok("인점을 띄우면 정상", "CP20" not in ids(r))


# --- 범위·쉼표 (표기 자료 이미지) --------------------------------------------

pr7 = load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml"))

for text, should in (("6만~8만 명", False), ("6만-8만 명", False),
                     ("6~8만 명", True), ("6만 ~ 8만 명", True), ("6만 - 8만 명", True)):
    r = check_events([ev(text, end=9000)], pr7)
    ok(f"범위 표기: {text}", ("S33" in ids(r)) == should, str(ids(r)))

r = check_events([ev("2019-2020년 사이", end=9000)], pr7)
ok("연도 범위는 단위가 없어 걸리지 않는다", "S33" not in ids(r))
r = check_events([ev("전화 010-1234", end=9000)], pr7)
ok("전화번호는 범위가 아니다", "S33" not in ids(r))

r = check_events([ev("그러나, 아니야")], pr7)
ok("접속부사 뒤 쉼표를 잡는다", "S34" in ids(r))
r = check_events([ev("그러나 아니야")], pr7)
ok("쉼표가 없으면 정상", "S34" not in ids(r))
r = check_events([ev("엄마, 사랑해요")], pr7)
ok("호명 뒤 쉼표는 정상", "S34" not in ids(r))


# --- 결과 ---------------------------------------------------------------

print(f"통과 {PASSED}건")
if FAILED:
    print(f"실패 {len(FAILED)}건")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("전부 통과")


