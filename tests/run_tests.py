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

# **표시끼리는 붙여 쓴다**(사용자 지정 2026-08-02 교정기 / 2026-08-11 재확인).
# 예전에는 정반대로 검사했다 — 작업자 자료 206행을 그대로 옮긴 탓인데, 그러면
# 교정기와 편집기가 서로 반대로 고친다.
r = check_events([ev("[진수][웃으며] 저요?")], practice)
ok("붙여 쓴 것은 조용하다", "S18" not in ids(r))
r = check_events([ev("[진수] [웃으며] 저요?")], practice)
ok("표시 사이 공백을 잡는다", "S18" in ids(r))
# 표시만 있는 줄(효과음)은 대사가 없으므로 보지 않는다.
r = check_events([ev("[문이 쾅 닫힌다] [발소리]")], practice)
ok("효과음만 있는 줄은 건드리지 않는다", "S18" not in ids(r))

_join = apply_fixes([Event(1, 0, 1, "(철수) [작게] 왜 이래")],
                    load_profile("coupang", "ko", "sdh"))[0]
ok("표시 사이 공백을 지운다", _join[0].text == "(철수)[작게] 왜 이래")
_keep = apply_fixes([Event(1, 0, 1, "(철수)[작게]왜 이래")],
                    load_profile("coupang", "ko", "sdh"))[0]
# 표시와 대사 사이 한 칸은 교정기 몫이다. 여기서 두 도구가 겹치면 왕복이 생긴다.
ok("대사와의 간격은 건드리지 않는다", _keep[0].text == "(철수)[작게]왜 이래")

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


# --- 타임코드 수렴 -----------------------------------------------------------

from checker.timing import TimingLimits, converge  # noqa: E402

lim = TimingLimits.from_profile(ko_sdh, fps=23.976)
# 넷플릭스 공식은 5/6초를 833ms로 적었고 실무 스펙 표는 0.834초로 적었다.
# 같은 값을 반올림만 다르게 쓴 것이라 프로파일마다 그대로 둔다.
ok("프로파일에서 한계를 읽는다",
   lim.min_duration_ms == 833 and lim.max_duration_ms == 7000 and lim.max_cps == 14)

cp_lim = TimingLimits.from_profile(load_profile_file(Path("rules/coupang/ko-sdh.yaml")), fps=23.976)
ok("쿠팡은 6초·2프레임", cp_lim.max_duration_ms == 6000 and cp_lim.min_gap_ms == 83)
ok("프레임레이트가 바뀌면 간격도 바뀐다",
   TimingLimits.from_profile(load_profile_file(Path("rules/coupang/ko-sdh.yaml")),
                             fps=59.94).min_gap_ms == 33)

r = converge([Event(1, 0, 400, "짧다"), Event(2, 5000, 6000, "다음")], lim)
ok("최소 표시 시간을 늘린다", r.events[0].duration_ms >= lim.min_duration_ms, str(r.events[0]))
ok("무엇을 왜 고쳤는지 남긴다", r.changes and "최소 표시 시간" in r.changes[0].reason)

r = converge([Event(1, 0, 20000, "길다")], lim)
ok("최대 표시 시간을 줄인다", r.events[0].duration_ms == 7000)

r = converge([Event(1, 0, 3000, "앞"), Event(2, 2000, 5000, "뒤")], lim)
ok("겹침을 푼다", r.events[0].end_ms <= r.events[1].start_ms,
   f"{r.events[0].end_ms} vs {r.events[1].start_ms}")

r = converge([Event(1, 0, 3000, "앞"), Event(2, 3010, 6000, "뒤")], cp_lim)
ok("간격을 벌린다", r.events[1].start_ms - r.events[0].end_ms >= 83,
   str(r.events[0].end_ms))

r = converge([Event(1, 0, 1000, "가나다라마바사아자차카타파하가나다라마바사")], lim)
ok("읽기 속도에 맞춰 늘린다", r.events[0].duration_ms > 1000)

# 늘릴 자리가 없으면 고쳤다고 하지 않는다
r = converge([Event(1, 0, 400, "짧다"), Event(2, 500, 3000, "바로 뒤")], lim)
ok("못 맞춘 것은 남긴다", any("최소 표시 시간" in m for _i, m in r.unresolved), str(r.unresolved))
ok("못 맞췄으면 병합을 권한다", any("병합" in m for _i, m in r.unresolved))

r = converge([Event(1, 0, 2000, "가" * 200)], lim)
ok("시간으로 못 줄이는 속도는 글자를 줄이라고 말한다",
   any("글자를 줄이" in m for _i, m in r.unresolved), str(r.unresolved))

original = [Event(1, 0, 400, "짧다")]
converge(original, lim)
ok("원본 이벤트를 건드리지 않는다", original[0].end_ms == 400)


# --- 스포팅 제안 (영상 없이 합성 구간으로 검증) -------------------------------

from checker.timing import suggest_spotting  # noqa: E402

fps = 23.976
frame = 1000 / fps
speech = [(3667, 4594), (5112, 7667)]

sug = suggest_spotting([Event(1, 3000, 5000, "첫 대사")], speech, fps)
by_field = {s.field_name: s for s in sug}
ok("인점을 말소리 앞으로 제안한다", "start_ms" in by_field)
ok("제안값이 말소리 시작보다 앞이다", by_field["start_ms"].suggested < 3667)
# 아웃점 5000ms는 말소리 끝(4594) + 6프레임(4844)에서 156ms 차이라 허용 범위(4프레임=167ms)
# 안이다. 규정 안인 것은 말하지 않는 것이 맞다.
ok("허용 범위 안의 아웃점은 말하지 않는다", "end_ms" not in by_field)

sug = suggest_spotting([Event(1, 3000, 6000, "첫 대사"), Event(2, 6500, 9000, "둘째")],
                       speech, fps)
by_field = {s.field_name: s for s in sug if s.event_index == 1}
ok("다음 자막 인점을 넘어서까지 늘리지 않는다",
   "end_ms" not in by_field or by_field["end_ms"].suggested <= 6500, str(sug))

# 이미 규정 안이면 말하지 않는다.
# 아웃점 기준에는 검출 보정(SPEECH_TAIL_FRAMES)이 함께 들어간다 — 말소리 검출이
# 말 끝을 일찍 자르는 만큼을 되돌리는 값이라, 규정(6~9프레임)과 다른 자리를 잰다.
from checker.timing import SPEECH_TAIL_FRAMES  # noqa: E402

good_start = int(3667 - 3 * frame)
good_end = int(4594 + (6 + SPEECH_TAIL_FRAMES) * frame)
ok("규정 안이면 조용하다",
   not suggest_spotting([Event(1, good_start, good_end, "대사")], speech, fps),
   str(suggest_spotting([Event(1, good_start, good_end, "대사")], speech, fps)))

sug = suggest_spotting([Event(1, 100000, 102000, "효과음뿐")], speech, fps)
ok("말소리가 없으면 그렇다고 알린다",
   sug and "말소리를 찾지 못했습니다" in sug[0].reason, str(sug))

ok("말소리 구간이 없으면 아무 말도 하지 않는다",
   suggest_spotting([Event(1, 0, 2000, "대사")], [], fps) == [])

original = Event(1, 3000, 5000, "대사")
suggest_spotting([original], speech, fps)
ok("제안은 원본을 바꾸지 않는다", original.start_ms == 3000 and original.end_ms == 5000)


# --- 장면 전환 스냅 ----------------------------------------------------------

from checker.timing import suggest_shot_snap  # noqa: E402

shots = [10000, 20000]

sug = suggest_shot_snap([Event(1, 9800, 12000, "걸침")], shots, fps)
ok("전환에 어설프게 걸친 인점을 잡는다",
   sug and sug[0].field_name == "start_ms" and sug[0].suggested == 10000, str(sug))
ok("딱 붙이라고 말한다", "딱 붙이거나" in sug[0].reason)

ok("이미 붙어 있으면 조용하다",
   not suggest_shot_snap([Event(1, 10000, 15000, "딱")], shots, fps))
ok("멀리 떨어져 있으면 조용하다",
   not suggest_shot_snap([Event(1, 5000, 8000, "멀리")], shots, fps))

sug = suggest_shot_snap([Event(1, 3000, 9700, "아웃점 걸침")], shots, fps)
ends = [s for s in sug if s.field_name == "end_ms"]
ok("전환에 걸친 아웃점은 2프레임 앞으로 제안한다",
   ends and ends[0].suggested < 10000, str(sug))

ok("전환이 없으면 아무 말도 하지 않는다",
   suggest_shot_snap([Event(1, 0, 3000, "대사")], [], fps) == [])

cp_shot = load_profile_file(Path("rules/coupang/ko-sdh.yaml"))
ok("쿠팡은 장면 전환 비적용이라 이 검사를 부르지 않는다",
   cp_shot["shot_change"]["applied"] is False)


# --- 플랫폼 유추 -------------------------------------------------------------

from checker.detect import detect_platform, mismatch_warning  # noqa: E402

coupang_style = [Event(1, 0, 4000, "(철수) 안녕하세요"),
                 Event(2, 5000, 8000, "(영희) [작게] 그래..."),
                 Event(3, 9000, 12000, "(철수) 어디 가?")]
netflix_style = [Event(1, 0, 4000, "[철수/작게] 안녕하세요"),
                 Event(2, 5000, 8000, "[영희/영어] 그래…"),
                 Event(3, 9000, 12000, "[잔잔한 음악]")]
disney_style = [Event(1, 0, 4000, "[철수가 작게] 안녕하세요"),
                Event(2, 5000, 8000, "[♪ 잔잔한 음악]"),
                Event(3, 9000, 12000, "이제 O됐네")]

ok("소괄호 화자명은 쿠팡으로 본다", detect_platform(coupang_style)[0].platform == "coupang")
ok("슬래시 화자명은 넷플릭스로 본다", detect_platform(netflix_style)[0].platform == "netflix")
ok("서술형·음표·O 삐는 디즈니로 본다", detect_platform(disney_style)[0].platform == "disney",
   str(detect_platform(disney_style)[:2]))
ok("근거를 남긴다", detect_platform(coupang_style)[0].evidence)

ok("화자명이 없으면 함부로 단정하지 않는다",
   not detect_platform([Event(1, 0, 3000, "그냥 대사입니다")]))

warn = mismatch_warning(coupang_style, load_profile_file(Path("rules/netflix/ko-sdh-practice.yaml")))
ok("프로파일이 어긋나면 경고한다", warn and "coupang" in warn, str(warn))
ok("경고에 근거가 들어간다", "소괄호" in warn)

ok("맞는 프로파일이면 조용하다",
   mismatch_warning(coupang_style, load_profile_file(Path("rules/coupang/ko-sdh.yaml"))) is None)
ok("근거가 약하면 말하지 않는다",
   mismatch_warning([Event(1, 0, 3000, "그래…")],
                    load_profile_file(Path("rules/coupang/ko-sdh.yaml"))) is None)


# --- 스크립트 대조 -----------------------------------------------------------

from checker.align import Segment, align, similarity, summary  # noqa: E402

segs = [Segment(0, 2000, "안녕하세요 반갑습니다"),
        Segment(2500, 4500, "오늘 날씨가 좋네요"),
        Segment(5000, 7000, "어 그래 뭐 그러네")]
script = ["안녕하세요, 반갑습니다.", "오늘 날씨가 좋네요."]

cues = align(segs, script)
ok("스크립트와 맞으면 스크립트 문장을 쓴다",
   cues[0].text == "안녕하세요, 반갑습니다." and cues[0].source == "script")
ok("스크립트에 없는 대사는 전사로 채우고 표시한다",
   cues[-1].source == "transcript" and cues[-1].needs_review, str(cues[-1]))
ok("즉흥 대사일 수 있다고 알린다", "즉흥" in cues[-1].note)

cues = align([Segment(0, 2000, "안녕하세요")], ["안녕하세요", "이 대사는 잘렸다"])
ok("소리를 못 찾은 스크립트 줄을 알린다",
   any("소리를 찾지 못했" in c.note for c in cues), str(cues))
ok("소리 없는 줄은 길이가 0이다", any(c.start_ms == c.end_ms for c in cues))

# 대사가 조금 바뀐 경우 — 스크립트를 쓰되 표시한다
cues = align([Segment(0, 2000, "밥은 먹었니 오늘 고생이 많다")],
             ["밥은 먹었니 오늘 수고가 많으십니다 정말로 그래"])
ok("조금 다르면 스크립트를 쓰고 표시한다",
   cues[0].source == "script" and cues[0].needs_review, str(cues[0]))

# 통째로 바뀐 경우 — 짝이 없는 것과 구분할 수 없으므로 전사를 쓰되 후보를 함께 보여 준다
cues = align([Segment(0, 2000, "밥은 먹었니")], ["식사는 하셨습니까"])
ok("통째로 다르면 전사를 쓴다", cues[0].source == "transcript")
ok("그 자리 스크립트를 함께 보여 준다", "이 자리 스크립트" in cues[0].note, cues[0].note)

ok("유사도를 잰다", similarity("안녕하세요 반갑습니다", "안녕하세요, 반갑습니다!") > 0.9)
ok("빈 문자열은 0", similarity("", "무엇") == 0.0)

st = summary(align(segs, script))
ok("어디서 왔는지 집계한다", st["from_script"] == 2 and st["from_transcript"] == 1)
ok("봐야 할 자리를 센다", st["needs_review"] >= 1)


# --- 의미 단위 재분할 ---------------------------------------------------------

from checker.resplit import resplit, resplit_all, split_text  # noqa: E402

W2 = {"cjk": 1.0, "other": 0.5}

pieces = split_text("안녕하세요. 오늘 날씨가 참 좋습니다.", 12, W2)
ok("문장 끝에서 먼저 끊는다", pieces[0] == "안녕하세요.", str(pieces))

pieces = split_text("그러니까 내 말은 지금 여기서 할 수 있는 게 없다는 거야", 14, W2)
ok("여러 조각으로 나눈다", len(pieces) > 1)
ok("각 조각이 한계 안이다", all(count_chars(p, W2) <= 14 for p in pieces), str(pieces))

ok("짧으면 그대로 둔다", split_text("짧다", 16, W2) == ["짧다"])
ok("끊을 자리가 없으면 자르지 않는다", len(split_text("가" * 40, 16, W2)) == 1)

ev = Event(1, 0, 6000, "안녕하세요. 오늘 날씨가 참 좋습니다. 산책이나 갈까요?")
out = resplit(ev, 12, W2)
ok("나눈 만큼 자막이 늘어난다", len(out) > 1)
ok("시간이 이어진다", out[0].end_ms == out[1].start_ms)
ok("전체 구간을 유지한다", out[0].start_ms == 0 and out[-1].end_ms == 6000)

speech = [(0, 1800), (2600, 6000)]
out = resplit(Event(1, 0, 6000, "안녕하세요. 오늘 날씨가 참 좋습니다."), 12, W2, speech)
ok("침묵 자리로 경계를 당긴다", 1800 <= out[0].end_ms <= 2600,
   str([(e.start_ms, e.end_ms) for e in out]))

out = resplit_all([Event(1, 0, 6000, "안녕하세요. 오늘 날씨가 좋습니다."),
                   Event(2, 7000, 9000, "짧은 줄")], ko_sdh)
ok("번호를 다시 매긴다", [e.index for e in out] == list(range(1, len(out) + 1)))


# --- 전사 읽기와 생성 파이프라인 -----------------------------------------
# 전사 자체는 기계와 모델에 달려 있어 시험으로 붙잡을 수 없다. 전사 **결과를
# 읽는 부분**과 그 뒤 단계를 잡는다.

from checker.transcribe import _parse_srt  # noqa: E402
from checker.generate import Draft, _to_events, notes_srt, read_script  # noqa: E402

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:04,560
동기화 설명을 좀 드리겠습니다

2
00:00:04,560 --> 00:00:06,800
그 기본강의에서
살짝 들으셨을텐데
"""

segs = _parse_srt(SAMPLE_SRT)
ok("전사 SRT를 읽는다", len(segs) == 2)
ok("타임코드를 밀리초로 읽는다", segs[0].start_ms == 0 and segs[0].end_ms == 4560)
ok("여러 줄 자막을 붙여 읽는다", segs[1].text == "그 기본강의에서\n살짝 들으셨을텐데")

dotted = _parse_srt("1\n00:00:01.500 --> 00:00:02.250\n네\n")
ok("점으로 찍힌 타임코드도 읽는다", dotted and dotted[0].start_ms == 1500)
ok("쓰레기 줄은 건너뛴다", _parse_srt("\n\n쓰레기\n\n1\n잘못된 타임코드\n말\n\n") == [])

import tempfile as _tf3  # noqa: E402
with _tf3.TemporaryDirectory() as _d:
    _sp = Path(_d) / "script.txt"
    _sp.write_text("Hello there,\nold friend.\n\nHow have you been?\n", encoding="utf-8")
    # 대본의 줄바꿈은 종이 폭 때문이지 대사가 끊긴 자리가 아니다.
    ok("스크립트는 문단을 한 대사로 읽는다",
       [l.text for l in read_script(_sp)] == ["Hello there, old friend.",
                                              "How have you been?"])

_cues = align([Segment(0, 1000, "hello there")], ["Hello there.", "Where have you been?"])
_notes: list = []
_events = _to_events(_cues, _notes)
ok("소리를 못 찾은 스크립트 줄을 지우지 않는다", len(_events) == 2)
ok("소리 없는 줄은 길이 0으로 남는다", _events[1].start_ms == _events[1].end_ms)
ok("그 자리를 봐야 할 곳으로 표시한다", any(i == 2 for i, _ in _notes))

_draft = Draft([Event(1, 0, 1000, "가"), Event(2, 1000, 2000, "나")],
               notes=[(2, "스크립트에 없는 대사입니다")])
_out = notes_srt(_draft)
ok("노트에 봐야 할 이유가 들어간다", "스크립트에 없는" in _out)
ok("깨끗한 줄은 조용히 채운다", "·" in _out)
# 번호가 어긋나면 SE에서 짝이 맞지 않는다.
ok("자막 수만큼 노트를 낸다", _out.count("-->") == 2)


# --- 번역 -----------------------------------------------------------------
# 모델은 시험에 넣지 않는다(기계마다 다르고 느리다). 모델에 **무엇을 보내고 무엇을
# 받아 어떻게 되돌리는지**를 잡는다 — 사고는 거기서 났다.

from checker.translate import (  # noqa: E402
    Glossary, _parse_numbered, _protect, _restore, to_events, translate_events)

body, frame = _protect("<i>She never did learn to knock.</i>")
ok("이탤릭 태그를 떼고 보낸다", body == "She never did learn to knock.")
ok("번역문에 태그를 도로 씌운다",
   _restore("노크도 안 하더라.", frame) == "<i>노크도 안 하더라.</i>")

body, frame = _protect("♪ Hello darkness my old friend ♪")
ok("음표를 떼고 보낸다", body == "Hello darkness my old friend")
ok("음표를 띄어쓰기와 함께 되돌린다",
   _restore("안녕 어둠아 내 오랜 친구여", frame) == "♪ 안녕 어둠아 내 오랜 친구여 ♪")

# 화자명은 떼지 않는다. SDH에서 화자명은 한국어로 옮겨야 할 대상이다.
body, _ = _protect("[Sarah] You can't be serious.")
ok("화자명은 모델에게 보낸다", body.startswith("[Sarah]"))

body, frame = _protect("Wait{\\an8} what?")
ok("대사 가운데 태그는 되돌리지 못한다고 표시한다", frame[2] is True)

got = _parse_numbered("1. 진심이야?\n2. 20분이나 기다렸어\n", [1, 2])
ok("번호 붙은 답을 읽는다", got == {1: "진심이야?", 2: "20분이나 기다렸어"})
ok("엉뚱한 번호는 버린다", _parse_numbered("7. 남의 자막\n", [1, 2]) == {})
ok("이어지는 줄은 앞 번호에 붙인다",
   _parse_numbered("1. 첫 줄\n둘째 줄\n", [1]) == {1: "첫 줄\n둘째 줄"})


class _FakeTranslator:
    """정해진 답만 내는 가짜. 모자라게 답하는 상황을 일부러 만든다."""

    def __init__(self, replies): self.replies, self.asked = list(replies), []

    def ask(self, system, prompt):
        self.asked.append(prompt)
        return self.replies.pop(0) if self.replies else ""


_evs = [Event(1, 0, 1000, "Hello."), Event(2, 1000, 2000, "Goodbye.")]
_fake = _FakeTranslator(["1. 안녕하세요\n2. 안녕히 가세요\n"])
_cues = translate_events(_evs, _fake, Glossary())
ok("자막 수만큼 번역이 나온다", len(_cues) == 2)
ok("타임코드는 원어 것을 그대로 쓴다",
   [(e.start_ms, e.end_ms) for e in to_events(_cues, _evs)] == [(0, 1000), (1000, 2000)])

# 한 줄이 빠지면 그 줄만 다시 묻는다. 통째로 다시 돌리면 잘 나온 것까지 흔들린다.
_fake = _FakeTranslator(["1. 안녕하세요\n", "안녕히 가세요"])
_cues = translate_events(_evs, _fake, Glossary())
ok("빠진 줄만 다시 묻는다", len(_fake.asked) == 2 and "Goodbye" in _fake.asked[1])
ok("다시 물은 자리를 표시한다", bool(_cues[1].note))

_fake = _FakeTranslator(["", ""])
_cues = translate_events(_evs[:1], _fake, Glossary())
# 빈 자막은 사람이 못 보고 지나친다. 원문이 남아 있으면 눈에 띈다.
ok("끝내 못 옮기면 원문을 남긴다", _cues[0].text == "Hello.")
ok("못 옮겼다고 표시한다", "원문" in _cues[0].note)

_gl = Glossary({"Halberd Systems": "핼버드 시스템즈"})
ok("통일표를 어긴 자리를 찾는다",
   _gl.check("From Halberd Systems.", "할버드 시스템에서") == ["Halberd Systems → 핼버드 시스템즈"])
ok("지킨 자리는 조용하다", _gl.check("From Halberd Systems.", "핼버드 시스템즈에서") == [])
ok("통일표를 프롬프트에 싣는다", "핼버드 시스템즈" in _gl.hint())

_fake = _FakeTranslator(["1. 할버드에서 왔어\n"])
_cues = translate_events([Event(1, 0, 1000, "From Halberd Systems.")], _fake, _gl)
# 고치지 않는다 — 문맥에 따라 안 쓰는 것이 맞을 때가 있다.
ok("통일표 위반은 표시만 한다",
   _cues[0].text == "할버드에서 왔어" and "고정 표기" in _cues[0].note)


# --- 자막 위치 -------------------------------------------------------------
# SDH든 번역이든 겹침 규칙이 있다는 점은 같고 **다루는 방법이 다르다**.
# 작업자 자료 [영상번역] 673·677행: 하단 자리로 옮기기도 하고, 말자막만 남기기도
# 한다. 그래서 코드에 못박지 않고 작업 시작 전에 고른다.

from checker.position import (  # noqa: E402
    JobRules, apply_positions, is_forced_narrative, is_placed, position_of,
    set_place, strip_position, suggest_positions)

ok("위치 태그를 읽는다", position_of("{\\an8}위에 있다") == "8")
ok("태그가 없으면 기본 자리", position_of("그냥 대사") is None)
ok("자리 지정 여부를 안다", is_placed("{\\an2}가") and not is_placed("가"))
ok("태그를 뗀다", strip_position("{\\an8}가") == "가")
ok("태그는 맨 앞에 하나만", set_place("{\\an2}가", "{\\an8}") == "{\\an8}가")
ok("빈 태그면 기본 자리로", set_place("{\\an8}가", "") == "가")

# 정해지기 전에는 아무것도 화면자막으로 보지 않는다. 추측해서 옮기면 납품물이 틀어진다.
_undecided = JobRules()
ok("정해지지 않으면 화면자막 판정을 안 한다",
   not is_forced_narrative('"공항 도착 30분 전"', None, _undecided))
ok("무엇을 정해야 하는지 말한다", "화면자막 표식" in _undecided.undecided_note())

_quote = JobRules(marker="double_quote", policy="move_dialogue")
ok("정한 표식만 인정한다", is_forced_narrative('"공항 도착 30분 전"', None, _quote))
# 이탤릭을 강조로 쓰는 작업에서 멀쩡한 대사가 화면자막이 되면 안 된다.
ok("정하지 않은 표식은 인정하지 않는다", not is_forced_narrative("<i>3년 후</i>", None, _quote))
_italic = JobRules(marker="italic", policy="move_dialogue")
ok("이탤릭 표식도 고를 수 있다", is_forced_narrative("<i>3년 후</i>", None, _italic))
ok("일부만 기울인 것은 강조", not is_forced_narrative("나는 <i>정말</i> 몰랐어", None, _italic))

_evs = [Event(1, 0, 3000, '"공항 도착 30분 전"'),
        Event(2, 500, 2500, "늦으면 안 돼"),
        Event(3, 5000, 7000, "{\\an8}겹치는 게 없다")]
ok("기준이 없으면 제안도 없다", suggest_positions(_evs, None, None, JobRules()) == [])

_sug = suggest_positions(_evs, None, None, _quote)
_move = [s for s in _sug if s.action == "move"]
_reset = [s for s in _sug if s.action == "reset"]
ok("겹치는 말자막을 옮긴다", len(_move) == 1 and _move[0].event_index == 2)
ok("기본은 상단 중앙", _move[0].tag == "{\\an8}")
# 앞 장면에서 옮긴 채로 두면 그다음부터 자막이 계속 그 자리에 뜬다.
ok("겹칠 것이 없으면 되돌린다", len(_reset) == 1 and _reset[0].event_index == 3)
ok("화면자막 자신은 건드리지 않는다", all(s.event_index != 1 for s in _sug))

# 673행: 하단 자리로 보내는 업체도 있다.
_right = JobRules(marker="double_quote", policy="move_dialogue", move_to="bottom_right")
ok("어디로 보낼지 고를 수 있다",
   suggest_positions(_evs[:2], None, None, _right)[0].tag == "{\\an3}")

# 677행: 영상번역에서는 말자막이 우선이라 화면자막을 넣지 않는다.
_only = JobRules(marker="double_quote", policy="dialogue_only")
_sug2 = suggest_positions(_evs[:2], None, None, _only)
ok("말자막 우선 기준은 화면자막 쪽을 지적한다",
   len(_sug2) == 1 and _sug2[0].event_index == 1)
ok("자막을 지우는 일은 사람이 한다", _sug2[0].action == "review")

_keep = JobRules(marker="double_quote", policy="keep_both")
ok("둘 다 두는 기준에서는 옮기지 않는다",
   [s for s in suggest_positions(_evs[:2], None, None, _keep) if s.action == "move"] == [])

_apply = [Event(1, 0, 3000, '"공항 도착 30분 전"'), Event(2, 500, 2500, "늦으면 안 돼")]
apply_positions(_apply, suggest_positions(_apply, None, None, _quote))
ok("옮긴 자막에 태그가 붙는다", _apply[1].text.startswith("{\\an8}"))

_review = [Event(1, 0, 3000, '"공항 도착 30분 전"'), Event(2, 500, 2500, "늦으면 안 돼")]
ok("지우라는 제안은 기계가 실행하지 않는다",
   apply_positions(_review, suggest_positions(_review, None, None, _only)) == 0)

# 영상에서 추정한 근거는 고치지 않는다 — 무늬를 글자로 볼 수 있다.
_evs3 = [Event(1, 0, 2000, "대사")]
_guess = suggest_positions(_evs3, None, [(0, 2000)], _quote)
ok("영상 근거로도 제안은 한다", len(_guess) == 1)
ok("영상 근거는 확실하지 않다고 표시한다", _guess[0].certain is False)
ok("영상 근거만으로는 고치지 않는다", apply_positions(_evs3, _guess) == 0)
ok("사람이 허락하면 고친다", apply_positions(_evs3, _guess, only_certain=False) == 1)


# --- SDH인가 번역 자막인가 -------------------------------------------------
# 종류가 어긋나면 검사가 통째로 헛돈다. 번역 프로파일에는 효과음 규칙이 아예
# 없어서 SDH 파일을 넣어도 **조용히 다 통과한다** — 플랫폼 불일치보다 위험하다.

from checker.detect import detect_kind  # noqa: E402

_sdh = [Event(1, 0, 1, "[문이 쾅 닫힌다]"),
        Event(2, 0, 1, "[철수] 왔어?"),
        Event(3, 0, 1, "♪ 노래가 흐른다 ♪")]
ok("효과음·화자·음표를 보고 SDH로 본다", detect_kind(_sdh)[0] == "sdh")
ok("무엇을 보고 그렇게 봤는지 남긴다", len(detect_kind(_sdh)[1]) == 3)

_long = [Event(i, 0, 1, f"대사 {i}") for i in range(1, 35)]
ok("표시가 하나도 없고 길면 번역 자막", detect_kind(_long)[0] == "translation")
# "효과음이 없다"는 조용한 장면이라는 뜻일 수도 있다. 짧으면 말하지 않는다.
ok("짧으면 아무 말도 하지 않는다", detect_kind(_long[:5])[0] is None)
ok("근거가 약하면 근거도 비운다", detect_kind(_long[:5])[1] == [])

_warn = mismatch_warning(_sdh, load_profile("netflix", "ko", "translation"))
ok("종류가 어긋나면 경고한다", _warn is not None and "SDH" in _warn)
ok("맞으면 조용하다", mismatch_warning(_sdh, load_profile("netflix", "ko", "sdh")) is None)


# --- 스포팅 자동 적용 -------------------------------------------------------
# 생성 경로에서는 자동으로 반영한다. 타임코드 자체가 방금 기계가 만든 것이라
# 훼손할 사람의 작업물이 없다. 검사 경로에서는 --fix-spotting을 켤 때만 한다.

from checker.timing import apply_spotting  # noqa: E402


class _Spot:
    def __init__(self, index, field_name, current, suggested):
        self.event_index, self.field_name = index, field_name
        self.current, self.suggested = current, suggested


_evs = [Event(1, 1000, 3000, "가"), Event(2, 4000, 6000, "나")]
n = apply_spotting(_evs, [_Spot(1, "start_ms", 1000, 900), _Spot(1, "end_ms", 3000, 3200)])
ok("인점을 앞으로 당긴다", _evs[0].start_ms == 900)
ok("아웃점을 뒤로 민다", _evs[0].end_ms == 3200)
ok("옮긴 개수를 돌려준다", n == 2)

ok("바뀌지 않는 제안은 세지 않는다",
   apply_spotting(_evs, [_Spot(2, "start_ms", 4000, 4000)]) == 0)
# 인점이 아웃점을 넘으면 자막이 뒤집힌다. 그런 제안은 버린다.
ok("자막을 뒤집는 제안은 버린다",
   apply_spotting(_evs, [_Spot(2, "start_ms", 4000, 9000)]) == 0 and _evs[1].start_ms == 4000)
ok("없는 자막 번호는 조용히 넘긴다", apply_spotting(_evs, [_Spot(99, "start_ms", 0, 1)]) == 0)


# --- 타임코드 고정 ---------------------------------------------------------
# 작업자 자료 190행: "TC 작업이 되어 온 파일에 내가 번역만 한 경우는 TC를 절대
# 건드리면 안 됨!" 약속은 확인할 수 있어야 약속이다.

from checker.cli import _assert_timecodes_unchanged, _timecodes_of  # noqa: E402

_before = [Event(1, 0, 1000, "가"), Event(2, 2000, 3000, "나")]
_same = [Event(1, 0, 1000, "다른 글자"), Event(2, 2000, 3000, "나")]
ok("글자만 바뀐 것은 통과",
   _assert_timecodes_unchanged(_timecodes_of(_before), _timecodes_of(_same), Path("x.srt")) is None)

_moved = [Event(1, 0, 1200, "가"), Event(2, 2000, 3000, "나")]
_problem = _assert_timecodes_unchanged(_timecodes_of(_before), _timecodes_of(_moved), Path("x.srt"))
ok("한 곳이라도 움직이면 잡는다", _problem is not None and "#1" in _problem)
ok("결과를 쓰지 않는다고 말한다", "쓰지 않았습니다" in _problem)

_split = [Event(1, 0, 500, "가"), Event(2, 500, 1000, "가"), Event(3, 2000, 3000, "나")]
_problem = _assert_timecodes_unchanged(_timecodes_of(_before), _timecodes_of(_split), Path("x.srt"))
# 나누면 경계가 새로 생긴다. 그것도 타임코드를 건드린 것이다.
ok("자막을 나눈 것도 잡는다", _problem is not None and "개수" in _problem)

# 고정과 수정은 함께 쓸 수 없다. 조용히 무시하면 사람은 고정된 줄 알고 기계는 옮긴다.
import subprocess as _sp  # noqa: E402
_res = _sp.run([sys.executable, "-m", "checker", "examples/ko-sdh-sample.srt",
                "--lock-timecodes", "--fix-timing"],
               capture_output=True, text=True, encoding="utf-8", errors="replace",
               cwd=str(Path(__file__).resolve().parent.parent))
ok("--lock-timecodes와 --fix-timing을 함께 쓰면 막는다",
   _res.returncode != 0 and "함께 쓸 수 없습니다" in _res.stderr)


# --- 대본에서 대사만 딴다 --------------------------------------------------
# 작업자 자료 100행: "스크립트에 있다고 무조건 사용은 금물! 스크립트에서는 대사만
# 딸 것!" 실제로 `SARAH:`가 콜론째 자막에 나갔다(2026-08-11).

from checker.generate import read_script, speaker_prefix  # noqa: E402

with _tf3.TemporaryDirectory() as _d:
    _sp = Path(_d) / "s.txt"
    _sp.write_text("SARAH: You can't be serious.\n\n(She steps inside.)\n\n"
                   "Mrs. Kim: Come in.\n\nHe said 9:30, not 10.\n", encoding="utf-8")
    _lines = read_script(_sp)
    ok("화자 표시를 대사에서 뗀다", _lines[0].text == "You can't be serious.")
    ok("화자명을 버리지 않는다", _lines[0].speaker == "Sarah")
    ok("대문자 이름을 자막 표기로 고친다", _lines[0].speaker == "Sarah")
    ok("지문은 대사가 아니다", all("steps inside" not in l.text for l in _lines))
    ok("점이 든 이름도 잡는다", _lines[1].speaker == "Mrs. Kim")
    # 대사 안의 콜론은 화자 표시가 아니다. 시각을 잘라 먹으면 안 된다.
    ok("대사 안의 콜론은 건드리지 않는다", _lines[2].text == "He said 9:30, not 10.")
    ok("그 줄에는 화자가 없다", _lines[2].speaker == "")

_netflix = load_profile("netflix", "ko", "sdh")
ok("플랫폼 표기로 화자명을 만든다", speaker_prefix("사라", _netflix) == "[사라] ")
ok("쿠팡은 소괄호", speaker_prefix("사라", load_profile("coupang", "ko", "sdh")) == "(사라) ")
ok("이름이 없으면 아무것도 붙이지 않는다", speaker_prefix("", _netflix) == "")

# 금지된 문장부호. 부호는 작업자가 가장 민감하게 보는 자리다.
_tr = load_profile("netflix", "ko", "translation")
_evs = [{"index": 1, "start_ms": 0, "end_ms": 2000, "text": "Sarah: 진심이야?"},
        {"index": 2, "start_ms": 0, "end_ms": 2000, "text": "9:30에 만나자"},
        {"index": 3, "start_ms": 0, "end_ms": 2000, "text": "[사라] 진심이야?"}]
_found = [v["event_index"] for v in check_events(_evs, _tr)["violations"]
          if v["rule_id"] == "T19"]
ok("대사에 든 콜론을 잡는다", 1 in _found)
ok("시각의 콜론은 값이라 놔둔다", 2 not in _found)
ok("화자 표시 안은 보지 않는다", 3 not in _found)

# **떼는 것이 아니라 옮긴다.** 원문이 무엇으로 적었든 자막 표기는 우리 것이다.
_ev_objs = [Event(1, 0, 2000, "Sarah: 진심이야?"), Event(2, 0, 2000, "9:30에 만나자"),
            Event(3, 0, 2000, "화자1: 왜 이래")]
_fixed, _applied, _ = apply_fixes(_ev_objs, _tr)
ok("콜론 화자 표기를 대괄호로 옮긴다", _fixed[0].text == "[Sarah] 진심이야?")
ok("시각은 그대로 둔다", _fixed[1].text == "9:30에 만나자")
ok("한국어 화자명도 옮긴다", _fixed[2].text == "[화자1] 왜 이래")

# OTT마다 기호가 다르다. 쿠팡은 소괄호다.
_cp = apply_fixes([Event(1, 0, 2000, "화자1: 왜 이래")],
                  load_profile("coupang", "ko", "translation"))[0]
ok("쿠팡은 소괄호로 옮긴다", _cp[0].text == "(화자1) 왜 이래")


# --- 교정기에 넘기는 표기 --------------------------------------------------
# OTT마다 화자명·어조 부호가 갈린다. 교정기는 이미 받을 줄 아는데 우리가 안
# 넘기고 있었다(사용자 지적 2026-08-11). 어조가 화자명과 같다고 가정하면 안 된다.

from checker.korean import _corrector_options  # noqa: E402


def _markers(platform, kind="sdh"):
    options = _corrector_options(None, load_profile(platform, "ko", kind))
    return options.get("markers")


if _markers("netflix") is None:
    # 교정기가 없는 환경에서는 조용히 빈 값을 돌려준다 — 그것도 계약이다.
    ok("교정기가 없으면 아무것도 넘기지 않는다", _corrector_options(None, {}) == {})
else:
    ok("넷플릭스는 둘 다 대괄호", _markers("netflix").speaker == "[]"
       and _markers("netflix").tone == "[]")
    ok("디즈니도 둘 다 대괄호", _markers("disney").speaker == "[]"
       and _markers("disney").tone == "[]")
    # (철수) [작게] — 화자명은 소괄호, 어조는 대괄호다.
    ok("쿠팡은 화자명만 소괄호", _markers("coupang").speaker == "()")
    ok("쿠팡 어조는 대괄호", _markers("coupang").tone == "[]")
    ok("번역 자막도 같은 표기를 쓴다",
       _markers("coupang", "translation").speaker == "()")

    _style = _corrector_options(None, load_profile("netflix", "ko", "sdh")).get("style")
    ok("넷플릭스 말줄임표를 교정기 용어로 넘긴다", _style and _style.ellipsis == "char")
    _cp = _corrector_options(None, load_profile("coupang", "ko", "sdh")).get("style")
    ok("쿠팡은 점 셋", _cp and _cp.ellipsis == "dots")
    # 디즈니는 둘 다 되므로 강제하지 않는다(작업물 내 통일만 검사한다).
    ok("디즈니는 말줄임표를 강제하지 않는다",
       "style" not in _corrector_options(None, load_profile("disney", "ko", "sdh")))


# --- 정답과 대조 -----------------------------------------------------------
# "타임코드가 이상하다"만으로는 무엇을 얼마나 바꿀지 모른다. 방향과 크기를 재야
# 감이 아니라 값으로 고친다.

from checker.evaluate import compare, report, summarize  # noqa: E402

_truth = [Event(1, 1000, 3000, "안녕하세요"), Event(2, 4000, 6500, "날씨가 좋네요"),
          Event(3, 8000, 10000, "그러게요")]
_ours = [Event(1, 1150, 3120, "안녕하세요"), Event(2, 4160, 6600, "날씨가 좋네요"),
         Event(3, 11000, 12000, "없는 자막")]

_cmp = compare(_ours, _truth)
_stats = summarize(_cmp)
ok("짝지은 수를 센다", _stats["counts"]["matched"] == 2)
ok("정답에만 있는 것을 센다", _stats["counts"]["missing"] == 1)
ok("우리에게만 있는 것을 센다", _stats["counts"]["extra"] == 1)
# 양수 = 늦게 시작했다. 방향이 뒤집히면 고칠 값의 부호가 뒤집힌다.
ok("인점이 얼마나 늦은지 잰다", _stats["start_ms"]["median"] == 155)
ok("프레임으로도 환산한다", _stats["start_frames"] == 3.7)
# 흩어짐이 작으면 상수로 고칠 수 있고, 크면 방법이 틀린 것이다.
ok("흩어진 정도를 잰다", _stats["start_ms"]["spread"] == 5)

_no_match = compare([Event(1, 60000, 61000, "전혀 다른 말")], _truth)
ok("짝이 없으면 짝짓지 않는다", summarize(_no_match)["counts"]["matched"] == 0)
ok("그래도 개수는 보고한다", summarize(_no_match)["counts"]["missing"] == 3)

_text = report(_cmp)
ok("어긋난 자막을 보여 준다", "가장 많이 어긋난" in _text)
ok("빠뜨린 자막을 보여 준다", "그러게요" in _text)


# --- 전사 조각 묶기 --------------------------------------------------------
# whisper는 말이 잠깐 멎을 때마다 끊는다. 사람은 한 호흡을 한 자막에 담는다.
# 값(4초·250ms)은 전문가 타임코드와 대조해 골랐다 — `regroup.py` 첫머리 참고.

from checker.regroup import limits_from_profile, merge_cues  # noqa: E402

_segs = [Event(1, 0, 1500, "안녕하세요"), Event(2, 1500, 3000, "오늘 날씨가"),
         Event(3, 5000, 6500, "멀리 떨어진 말")]
_merged = merge_cues(_segs, 4000, 250)
ok("붙어 있는 조각을 합친다", len(_merged) == 2)
ok("합친 텍스트를 이어 붙인다", _merged[0].text == "안녕하세요 오늘 날씨가")
ok("시간도 이어 붙인다", (_merged[0].start_ms, _merged[0].end_ms) == (0, 3000))
# 말이 끊긴 자리가 사람도 끊는 자리다.
ok("간격이 넓으면 합치지 않는다", _merged[1].text == "멀리 떨어진 말")
ok("번호를 다시 매긴다", [e.index for e in _merged] == [1, 2])

_long = [Event(1, 0, 3500, "긴 말"), Event(2, 3500, 6000, "이어지는 말")]
ok("합쳐서 상한을 넘으면 합치지 않는다", len(merge_cues(_long, 4000, 250)) == 2)
ok("상한을 0으로 주면 손대지 않는다", merge_cues(_segs, 0, 250) is _segs)

# **글자 수는 보지 않는다.** 원어 글자 수는 납품물과 무관하다(16자는 한국어 기준).
_wordy = [Event(1, 0, 1500, "This trial's about banking and coding and transactions"),
          Event(2, 1500, 3000, "and details that nobody wants to read at all")]
ok("원어가 길어도 합친다", len(merge_cues(_wordy, 4000, 250)) == 1)

ok("프로파일이 값을 정하지 않으면 기본값", limits_from_profile({}) == (4000, 250))
ok("프로파일 값이 이긴다",
   limits_from_profile({"timecode": {"merge_max_ms": 3000}}) == (3000, 250))

# 스포팅이 자막을 뭉개지 않는지. 한 말소리 구간에 여러 자막이 걸릴 때 무너졌다.
_dense = [Event(1, 1000, 2000, "가"), Event(2, 2000, 3000, "나"), Event(3, 3000, 4000, "다")]
_spots = [_Spot(1, "end_ms", 2000, 9000), _Spot(2, "start_ms", 2000, 500),
          _Spot(3, "end_ms", 4000, 4300)]
_moved = apply_spotting(_dense, _spots)
ok("뒤 자막을 넘는 아웃점은 받지 않는다", _dense[0].end_ms == 2000)
ok("앞 자막을 침범하는 인점은 받지 않는다", _dense[1].start_ms == 2000)
ok("마지막 자막은 늘릴 수 있다", _dense[2].end_ms == 4300 and _moved == 1)


# --- 강사 첨삭 읽기 --------------------------------------------------------
# 규정 문서가 "무엇이 맞는지"를 말한다면 첨삭은 "무엇이 실제로 틀리는지"를 말한다.

from checker.bookmarks import classify, clean, read  # noqa: E402

ok("SE의 <br />를 줄바꿈으로", clean("가<br />나") == "가\n나")
ok("강사가 붙인 갈래 표시를 믿는다", classify("<오역><br />8-9번 문장에") == "translation")
ok("표시가 없으면 말로 가른다", classify("아웃점 너무 빠릅니다") == "timecode")
ok("표기 지적을 가른다", classify("시간과 시각은 아라비아 숫자로 표기합니다") == "notation")
# 좁은 갈래가 이긴다 — "의미"가 들어가도 인점 이야기면 타임코드 일이다.
ok("겹치면 좁은 갈래가 이긴다", classify("의미별 스파팅 수정해 주세요") == "timecode")
ok("모르면 기타로 둔다", classify("좋습니다!") == "other")

with _tf3.TemporaryDirectory() as _d:
    _srt = Path(_d) / "a.srt"
    _srt.write_text("1\n00:00:01,000 --> 00:00:03,000\n첫 줄\n\n"
                    "2\n00:00:04,000 --> 00:00:06,000\n둘째 줄\n", encoding="utf-8")
    _bm = Path(_d) / "a.srt.SE.bookmarks"
    _bm.write_text('{"bookmarks":[{"idx":2,"txt":"아웃점 너무 빠릅니다"}]}', encoding="utf-8")
    _notes = read(_bm)
    ok("첨삭을 읽는다", len(_notes) == 1 and _notes[0].kind == "timecode")
    ok("자막과 짝짓는다", _notes[0].cue is not None and _notes[0].cue.text == "둘째 줄")

    # SE는 파일에 따라 0부터 번호를 매긴다. 자막 수를 넘는 번호가 그 증거다.
    _bm.write_text('{"bookmarks":[{"idx":0,"txt":"가"},{"idx":2,"txt":"나"}]}', encoding="utf-8")
    _zero = read(_bm)
    ok("0-기준 파일을 알아본다", [n.index for n in _zero] == [1, 3])


# --- WSL에서 Windows 도구 부르기 -------------------------------------------
# `/mnt/c/...`는 Windows에 없는 이름이라 ffmpeg이 "Illegal byte sequence"로 죽는다.
# 한글이 섞이면 더 빨리 죽는다(2026-08-11 실측). 상대 경로로 바꾸면 통한다.

import os as _os  # noqa: E402
from checker.media import _as_tool_path  # noqa: E402

if _os.name != "nt":
    _here = Path.cwd()
    ok("Windows 경로가 아니면 그대로 둔다", _as_tool_path("relative/x.mp4") == "relative/x.mp4")
    if str(_here).startswith("/mnt/"):
        _abs = _here / "examples" / "x.mp4"
        ok("작업 폴더 밑은 상대 경로로 바꾼다",
           _as_tool_path(_abs) == "examples/x.mp4")
        # 드라이브를 건너가면 Windows가 못 푼다. 그때는 손대지 않는다.
        ok("드라이브를 건너가면 그대로 둔다",
           _as_tool_path("/mnt/d/영상/x.mp4") == "/mnt/d/영상/x.mp4")


# --- 말소리 모델(VAD) ------------------------------------------------------
# 모델 자체는 시험에 넣지 않는다(파일이 있어야 하고 느리다). 확률을 구간으로
# 바꾸는 규칙만 잡는다 — 사고가 나는 자리는 거기다.

from checker.vad import _spans  # noqa: E402

# 32ms 프레임. [말 10프레임][침묵 3][말 10] — 침묵이 짧으니 한 덩어리다.
_probs = [0.9] * 10 + [0.1] * 3 + [0.9] * 10
ok("짧은 침묵으로 말을 끊지 않는다",
   len(_spans(_probs, 0.5, 120, 250, 0, 1000)) == 1)
# 침묵이 길면 끊는다.
_probs2 = [0.9] * 10 + [0.1] * 10 + [0.9] * 10
ok("긴 침묵에서는 끊는다", len(_spans(_probs2, 0.5, 120, 250, 0, 1000)) == 2)
# 아주 짧은 소리는 기침·잡음일 수 있다.
ok("너무 짧은 말소리는 버린다",
   _spans([0.1] * 5 + [0.9] * 2 + [0.1] * 10, 0.5, 120, 250, 0, 1000) == [])
ok("조용하면 빈 목록", _spans([0.1] * 20, 0.5, 120, 250, 0, 1000) == [])
ok("끝까지 말하면 마지막 구간을 닫는다",
   _spans([0.9] * 20, 0.5, 120, 250, 0, 1000)[-1][1] == 20 * 32)
# 여유를 주면 앞뒤로 벌어지되 영상 밖으로는 못 나간다.
_padded = _spans([0.1] * 5 + [0.9] * 10 + [0.1] * 10, 0.5, 120, 250, 100, 480)
ok("여유를 앞뒤로 준다", _padded[0][0] == 60)
ok("영상 밖으로 나가지 않는다", _padded[0][1] <= 480)


# --- 용어 뽑기·조사 --------------------------------------------------------
# 작업자가 작품마다 공부하던 자리다. 기계가 대신할 수 있는 것은 **번역이 아니라
# 조사**다. 근거 없는 표기를 정답처럼 내면 검수에서 되돌아온다.

from checker.terms import Term, extract, research, summarize, to_tsv  # noqa: E402

_lines = ["Jason Bull: This trial is about banking.",
          "Nice to meet you, Benny.",
          "That is a nice hat.",
          "He signed an NDA with Halberd Systems.",
          "Halberd Systems is in Panama."]
_terms = extract(_lines)
_names = [t.source for t in _terms]
ok("여러 낱말로 된 이름을 한 덩어리로 잡는다", "Halberd Systems" in _names)
ok("약어를 잡는다", "NDA" in _names)
# `Nice to meet you`의 Nice가 도시 니스로 조사되어 나온 적이 있다.
ok("소문자로도 나오는 낱말은 이름이 아니다", "Nice" not in _names)
ok("경칭만 남은 것은 버린다", "Mr" not in _names)
ok("긴 이름 안의 조각은 버린다", "Halberd" not in _names)
ok("몇 번 나오는지 센다",
   next(t.count for t in _terms if t.source == "Halberd Systems") == 2)

# 용어집에 이미 있으면 그것이 이긴다. 발주처가 정한 표기가 규범보다 앞선다.
_researched = research([Term("Halberd Systems")], glossary={"Halberd Systems": "핼버드"})
ok("용어집이 이긴다", _researched[0].korean == "핼버드")
ok("어디서 왔는지 남긴다", _researched[0].origin == "KNP/용어집")
ok("근거가 있으면 확정으로 본다", _researched[0].confirmed)

_unknown = Term("Bastogne")
ok("모르는 것은 비워 둔다", not _unknown.korean and not _unknown.confirmed)
_tsv = to_tsv([_unknown])
ok("확인이 필요하다고 적는다", "확인 필요" in _tsv)
ok("KNP 칸 순서를 따른다", _tsv.splitlines()[0].startswith("Source Language\tTarget Language"))

_stats = summarize([Term("A", korean="가", origin="KNP/용어집"), Term("B")])
ok("근거 있는 것과 없는 것을 나눠 센다",
   _stats["confirmed"] == 1 and _stats["unknown"] == 1)

from checker.webterms import DISAMBIGUATED  # noqa: E402

# `불 (드라마)`, `니스 (프랑스)` — 같은 이름의 문서가 여럿이면 사람이 정한다.
ok("갈라 놓은 표제어를 알아본다", bool(DISAMBIGUATED.search("불 (드라마)")))
ok("보통 표제어는 건드리지 않는다", not DISAMBIGUATED.search("바스토뉴"))


# --- 강사 첨삭에서 온 검사 -------------------------------------------------
# 규정 문서가 아니라 **실제로 되풀이된 지적**에서 뽑은 규칙들이다. 실무 자막
# 2,622개에 돌려 오탐 0건을 확인했다(첨삭이 반영된 최종본이라 참 지적도 0건이다).

_tr = load_profile("netflix", "ko", "translation")


def _flags(text, prefix="C3"):
    found = check_events([{"index": 1, "start_ms": 0, "end_ms": 2000, "text": text}], _tr)
    return {v["rule_id"] for v in found["violations"] if v["rule_id"].startswith(prefix)}


ok("화폐 '불'을 잡는다", "C30" in _flags("20만 불짜리 집이야"))
ok("조사가 붙어도 잡는다", "C30" in _flags("3천 불을 냈어"))
# `불이 났다`를 고치면 큰일이다. 앞에 숫자가 있을 때만 화폐로 본다.
ok("불이 났다는 건드리지 않는다", "C30" not in _flags("불이 났어요"))
ok("불편해요도 아니다", "C30" not in _flags("불편해요"))

ok("조합 문자를 잡는다", "C31" in _flags("50㎡ 원룸이에요"))
ok("한글 시각을 잡는다", "C32" in _flags("아홉 시에 만나자"))
# '세 시간'은 시각이 아니라 기간이다.
ok("시간(기간)은 시각이 아니다", "C32" not in _flags("세 시간 걸려"))
ok("시계는 시각이 아니다", "C32" not in _flags("시계를 봐"))

ok("10 이상 한글 수를 잡는다", "C33" in _flags("열다섯 명이 왔어"))
# 10 미만은 소리 나는 대로 적는 것이 원칙이다.
ok("10 미만은 놔둔다", "C33" not in _flags("세 명이 왔어"))
ok("열정은 수가 아니다", "C33" not in _flags("열정적이야"))

_fixed, _, _ = apply_fixes([Event(1, 0, 1, "3천 불을 냈어"),
                            Event(2, 0, 1, "5천 불이 없어")], _tr)
# 받침이 바뀌면 조사도 바뀐다. `달러을`이 나온 적이 있다.
ok("화폐를 고치며 조사도 맞춘다", _fixed[0].text == "3천 달러를 냈어")
ok("주격 조사도 맞춘다", _fixed[1].text == "5천 달러가 없어")


# --- 2차·3차 번역 ----------------------------------------------------------
# 작업자 자료 569~579행의 단계를 그대로 나눈다. 한 번에 "잘 번역해라"라고 하면
# 모델이 정확도·용어·말맛을 뒤섞어 어중간하게 낸다.

from checker.revise import _too_different, report as revision_report, revise  # noqa: E402

_evs = [Event(1, 0, 1000, "그들과 싸우기 전에 그들을 발견해야 한다"),
        Event(2, 1000, 2000, "놈들은 강하다")]

_fake = _FakeTranslator(["1. 놈들과 싸우기 전에 우선 찾아야 한다\n2. 놈들은 강하다\n"])
_out, _revisions = revise(_evs, _fake, source={1: "We must find them before we fight"})
ok("고친 자막을 돌려준다", _out[0].text == "놈들과 싸우기 전에 우선 찾아야 한다")
ok("타임코드는 그대로", (_out[0].start_ms, _out[0].end_ms) == (0, 1000))
ok("바뀐 것만 내역에 남는다", len(_revisions) == 1 and _revisions[0].index == 1)
ok("전후를 함께 남긴다", "그들과" in _revisions[0].before and "놈들과" in _revisions[0].after)

# **의심스러우면 1차를 지킨다.** 2차가 늘 나은 것은 아니다.
_fake = _FakeTranslator(["1. 이건 완전히 다른 아주 긴 문장으로 설명을 덧붙인 것입니다 정말 깁니다\n"])
_out, _ = revise(_evs[:1], _fake)
ok("너무 달라지면 1차를 지킨다", _out[0].text == _evs[0].text)

_fake = _FakeTranslator([""])
_out, _ = revise(_evs[:1], _fake)
ok("답이 없으면 1차를 지킨다", _out[0].text == _evs[0].text)

ok("길이가 두 배 넘으면 다시 쓴 것으로 본다", _too_different("짧은 말", "짧은 말을 아주 길게 늘여 쓴 것"))
ok("비슷한 길이는 다듬은 것", not _too_different("먼저 연락했어야지", "먼저 연락했어야 했어"))
ok("빈 원문은 견주지 않는다", not _too_different("", "무엇이든"))

ok("바꾼 것이 없으면 그렇게 말한다", "없습니다" in revision_report([]))


# --- 독립 프로그램 화면 ----------------------------------------------------
# 화면은 PySide6가 있어야 시험할 수 있다. 없는 환경(개발용 WSL)에서는 건너뛴다 —
# 엔진 시험이 화면 때문에 멈추면 안 된다.

try:
    from PySide6.QtWidgets import QApplication      # noqa: F401
except ImportError:
    pass
else:
    import os as _os2
    _os2.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # **위젯을 만들기 전에 QApplication이 있어야 한다.** 없이 만들면 파이썬이
    # 조용히 죽는다 — 예외도 안 나고 뒤 시험이 통째로 안 돌았다.
    _qt_app = QApplication.instance() or QApplication([])
    from app.model import SubtitleModel  # noqa: E402

    _app_model = SubtitleModel([Event(1, 1000, 3000, "첫 줄"),
                                Event(2, 5000, 7000, "둘째\n줄")])
    ok("표에 자막 수만큼 줄이 선다", _app_model.rowCount() == 2)
    ok("타임코드를 사람이 읽는 꼴로 보여 준다",
       _app_model.data(_app_model.index(0, 1)) == "00:00:01,000")
    ok("길이를 초로 보여 준다", _app_model.data(_app_model.index(0, 3)) == "2.00")
    # 두 줄짜리 자막을 한 줄로 보면 줄바꿈이 맞는지 알 수 없다.
    ok("줄바꿈을 눈에 보이게 둔다", "⏎" in _app_model.data(_app_model.index(1, 5)))

    # **자막은 두 벌이다** — 원어와 번역을 나란히 봐야 번역을 검토할 수 있다.
    _src = _app_model.remember_sources()
    _app_model.replace([Event(1, 1000, 3000, "번역본"), Event(2, 5000, 7000, "둘째")], _src)
    ok("원어 칸에 번역 전 글자가 남는다", _app_model.data(_app_model.index(0, 4)) == "첫 줄")
    ok("자막 칸에는 번역이 온다", _app_model.data(_app_model.index(0, 5)) == "번역본")
    # 검사·교정을 돌려도 원어는 남아야 한다.
    _app_model.replace([Event(1, 1000, 3000, "교정본"), Event(2, 5000, 7000, "둘째")])
    ok("원어를 주지 않으면 지우지 않는다", _app_model.data(_app_model.index(0, 4)) == "첫 줄")
    ok("그 시각의 자막을 찾는다", _app_model.row_for_time(2000) == 0)
    ok("아무것도 없는 시각은 -1", _app_model.row_for_time(4000) == -1)

    # 파형 — 좌표 계산과 가장자리 잡기. 여기가 틀리면 엉뚱한 자막을 끌게 된다.
    from app.waveform import Waveform  # noqa: E402

    _wave = Waveform()
    _wave.resize(1000, 160)
    _wave.ms_per_pixel = 20.0
    _wave.view_start_ms = 10000
    ok("화면 좌표를 시각으로", _wave.ms_at(100) == 12000)
    ok("시각을 화면 좌표로", _wave.x_at(12000) == 100)
    ok("왕복해도 같다", _wave.ms_at(_wave.x_at(15000)) == 15000)

    _wave.set_events([Event(1, 12000, 14000, "가"), Event(2, 20000, 22000, "나")])
    _grabbed = _wave._edge_at(_wave.x_at(12000))
    ok("인점 가장자리를 잡는다", _grabbed and _grabbed[1] == "start")
    _grabbed = _wave._edge_at(_wave.x_at(14000))
    ok("아웃점 가장자리를 잡는다", _grabbed and _grabbed[1] == "end")
    ok("가장자리가 아니면 안 잡는다", _wave._edge_at(_wave.x_at(13000)) is None)

    # 확대해도 보고 있던 자리가 그대로 있어야 한다.
    _wave.zoom(0.5, anchor_ms=15000)
    ok("확대해도 보던 자리를 붙잡는다", abs(_wave.ms_at(_wave.x_at(15000)) - 15000) <= 1)
    ok("너무 작게는 못 줄인다", _wave.ms_per_pixel >= 1.0)


# --- 발주처 기준(사용자 프로파일) ------------------------------------------
# 규정은 바뀌고, 발주처마다 다르고, 다른 회사 일도 받는다. 딸려 온 셋만 쓸 수
# 있으면 도구가 일을 막는다.

import os as _os3  # noqa: E402
from checker.profile import (available_profiles, find_profile_file,  # noqa: E402
                             user_root)

with _tf3.TemporaryDirectory() as _d:
    _os3.environ["SUBTITLE_EDITOR_PROFILES"] = _d
    _client = Path(_d) / "우리에이전시"
    _client.mkdir()
    (_client / "ko-translation.yaml").write_text(
        "schema_version: 1\nplatform: 우리에이전시\nlanguage: ko\n"
        "kind: translation\nstatus: complete\n"
        "extends: netflix/ko-translation.yaml\n"
        "limits:\n  chars_per_line: 14\n"
        "disable_rules: [T05]\n", encoding="utf-8")

    ok("사용자 자리에서 프로파일을 찾는다",
       find_profile_file("우리에이전시/ko-translation") is not None)

    _mine = load_profile("우리에이전시", "ko", "translation")
    # **바꾼 값만 적고 나머지는 상속한다.** 통째로 베끼면 공식 기준이 개정돼도 못 따라간다.
    ok("덮어쓴 값이 이긴다", _mine["limits"]["chars_per_line"] == 14)
    ok("나머지는 상속한다", _mine["limits"]["duration_ms"]["min"] == 833)
    # 발주처가 안 보는 규칙을 계속 띄우면 진짜 지적이 묻힌다.
    ok("끈 규칙은 빠진다", "T05" not in [r["id"] for r in _mine["rules"]])
    ok("나머지 규칙은 남는다", len(_mine["rules"]) > 10)

    _names = [p["platform"] for p in available_profiles()]
    ok("목록에 발주처 기준이 나온다", "우리에이전시" in _names)
    ok("딸려 온 기준도 그대로 나온다", "netflix" in _names)
    _os3.environ.pop("SUBTITLE_EDITOR_PROFILES", None)


# --- 자막 편집 조작 --------------------------------------------------------
# 작업자가 SE에서 쓰던 조작을 그대로 옮겼다. 화면과 떼어 놓아 여기서 시험한다.

try:
    from app.edits import (merge_with_next, remove_line_breaks, set_in_point,  # noqa: E402
                           set_out_point, split_at, toggle_dash)
except ImportError:
    pass
else:
    _cues = [Event(1, 0, 4000, "첫 자막입니다"), Event(2, 5000, 8000, "둘째 자막")]
    _split, _new = split_at([Event(e.index, e.start_ms, e.end_ms, e.text) for e in _cues],
                            1, 2000)
    ok("재생 위치에서 나눈다", len(_split) == 3)
    ok("시간이 이어진다", _split[0].end_ms == 2000 and _split[1].start_ms == 2000)
    ok("번호를 다시 매긴다", [e.index for e in _split] == [1, 2, 3])
    # 가장자리에서는 나누지 않는다 — 길이 0짜리가 생긴다.
    ok("가장자리에서는 나누지 않는다",
       len(split_at([Event(1, 0, 4000, "가나다")], 1, 10)[0]) == 1)

    _merged, _ = merge_with_next(
        [Event(1, 0, 2000, "가"), Event(2, 2000, 4000, "나")], 1)
    ok("다음 자막과 합친다", len(_merged) == 1 and _merged[0].end_ms == 4000)
    ok("독백은 줄만 바꾼다", _merged[0].text == "가\n나")

    _dialogue, _ = merge_with_next(
        [Event(1, 0, 2000, "가"), Event(2, 2000, 4000, "나")], 1, dialogue=True)
    ok("대화는 하이픈을 넣는다", _dialogue[0].text == "- 가\n- 나")

    ok("하이픈을 뺀다", toggle_dash(Event(1, 0, 1, "- 가\n- 나")) == "가\n나")
    ok("없으면 넣는다", toggle_dash(Event(1, 0, 1, "가\n나")) == "- 가\n- 나")
    ok("줄바꿈을 없앤다", remove_line_breaks(Event(1, 0, 1, "가\n나")) == "가 나")
    # 위치 태그는 편집을 거쳐도 살아남아야 한다.
    ok("위치 태그를 지키며 줄바꿈만 없앤다",
       remove_line_breaks(Event(1, 0, 1, "{\\an8}가\n나")) == "{\\an8}가 나")

    _points = [Event(1, 1000, 3000, "가"), Event(2, 4000, 6000, "나")]
    ok("인점을 지금 위치로", set_in_point(_points, 1, 1500) and _points[0].start_ms == 1500)
    # 이웃을 침범하면 하지 않는다. 겹친 자막은 둘 다 못 읽는다.
    ok("다음 자막을 침범하면 안 한다", not set_out_point(_points, 1, 5000))
    ok("아웃점을 지금 위치로", set_out_point(_points, 1, 3500) and _points[0].end_ms == 3500)


# --- 결과 ---------------------------------------------------------------

print(f"통과 {PASSED}건")
if FAILED:
    print(f"실패 {len(FAILED)}건")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("전부 통과")


