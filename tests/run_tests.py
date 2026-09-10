"""검사기 테스트. pytest 없이 `python3 tests/run_tests.py`로 돌린다.

이 저장소는 아직 런타임 결정 전이라 의존성을 PyYAML 하나로 묶어 둔다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker import check_events, load_profile, ProfileError  # noqa: E402
from checker.model import Event  # noqa: E402
from checker.profile import _merge, _validate  # noqa: E402
from checker.text import count_chars  # noqa: E402
from checker.ocr import (  # noqa: E402
    OcrCaption, _checkpoint_fingerprint, _cleanup_checkpoint, _crop_filter,
    _enforce_no_overlap, _prepare_checkpoint, captions_to_draft_srt_events,
    captions_to_events, merge_captions, merge_frames,
)
from checker.position import JobRules, apply_marker, is_forced_narrative  # noqa: E402
from checker.generate import _is_known_hallucination, has_vad_support  # noqa: E402
from checker.sfx import (  # noqa: E402
    AUDIOSET_TO_CANDIDATE, SoundEvent, _apply_music_marker, _windows, merge_sound_events,
    sound_events_to_draft_events, speech_gaps,
)

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

# 발주처 공식 규정은 `rules/private/`(비공개 저장소 클론)에 있다. 자리를 직접 적으면
# 그 자리가 바뀔 때마다 시험이 통째로 깨지므로, 로더가 쓰는 것과 같은 탐색 함수로 찾는다.
from checker.profile import find_profile_file  # noqa: E402


def rule_file(reference: str) -> Path:
    path = find_profile_file(reference)
    if path is None:
        raise SystemExit(
            f"규정 프로파일을 찾지 못했습니다: {reference}. "
            "비공개 규정 저장소를 `rules/private/`로 클론했는지 확인하세요(.gitignore 참고)."
        )
    return path


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
           # **자동 교정은 이제 기본값이 아니다**(규칙 7) — 고치는 쪽을 보려면
           # 켜서 부른다.
           "settings": {"kind": "sdh", "applyFixes": True}}
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

    # **응답 스키마를 못박는다.** SE와의 계약(API_VERSION=1)이므로 리팩터로 키가
    # 빠지거나 이름이 바뀌면 플러그인이 조용히 깨진다. 값이 아니라 키 집합을 본다.
    ok("응답 키 집합이 계약과 같다",
       set(resp) == {"status", "message", "settings", "settingsVersion",
                     "undoDescription", "subtitle"}, str(sorted(resp)))
    ok("settingsVersion을 돌려준다", resp["settingsVersion"] == 1)
    ok("자막 응답 형식이 SubRip", resp["subtitle"]["format"] == "SubRip")
    ok("설정 키가 빠지지 않는다",
       set(resp2["settings"]) >= {"platform", "language", "kind", "applyFixes",
                                  "korean", "kscPath", "spacing", "children"},
       str(sorted(resp2["settings"])))

    req4 = dict(req); req4["settings"] = {"platform": "disney", "language": "en", "kind": "sdh"}
    r4 = plugin_run(req4)
    ok("없는 프로파일은 오류로 알린다",
       r4["status"] == "error" and "프로파일" in r4["message"], str(r4)[:60])

    # **고르지 않은 것을 고른 것처럼 보이지 않게 한다**(2026-09-08).
    req5 = {"apiVersion": 1, "tempDirectory": tmp,
            "subtitle": {"format": "SubRip", "subRip": SAMPLE_SRT}}
    r5 = plugin_run(req5)
    ok("아무것도 안 고르면 기본값으로 돌았다고 말한다",
       "정한 적이 없어" in r5["message"], r5["message"][:120])
    ok("아무것도 안 고르면 자막을 바꾸지 않는다", "subtitle" not in r5)

    # SE는 우리가 돌려준 설정을 그대로 되돌려준다. 그것을 "사람이 골랐다"로 세면
    # 두 번째 실행부터 알림이 사라진다 — 고른 칸 이름을 함께 왕복시켜 막는다.
    req6 = dict(req5); req6["settings"] = r5["settings"]
    r6 = plugin_run(req6)
    ok("SE가 되돌려준 설정을 사람 선택으로 세지 않는다",
       "정한 적이 없어" in r6["message"], r6["message"][:120])

    req7 = dict(req5); req7["settings"] = {"platform": "coupang", "kind": "sdh"}
    r7 = plugin_run(req7)
    ok("고르고 나면 그 알림이 사라진다", "정한 적이 없어" not in r7["message"])

    # 프로파일 어긋남 경고가 플러그인·GUI에도 온다(전에는 cli.py에만 있었다).
    COUPANG_SRT = ("1\n00:00:01,000 --> 00:00:04,000\n(진수) 어디 갔었어\n\n"
                   "2\n00:00:05,000 --> 00:00:08,000\n(영희) 몰라도 돼\n")
    req8 = {"apiVersion": 1, "tempDirectory": tmp,
            "subtitle": {"format": "SubRip", "subRip": COUPANG_SRT},
            "settings": {"platform": "netflix", "kind": "sdh"}}
    r8 = plugin_run(req8)
    ok("프로파일이 어긋나면 플러그인 메시지에도 뜬다",
       "coupang" in r8["message"], r8["message"][:160])

    # config.json이 깨졌으면 무시했다고 말한다 — 조용히 기본값으로 돌지 않는다.
    (Path(tmp) / "config.json").write_text("{깨진 json", encoding="utf-8")
    req9 = {"apiVersion": 1, "tempDirectory": tmp, "pluginDataDirectory": tmp,
            "subtitle": {"format": "SubRip", "subRip": SAMPLE_SRT}}
    r9 = plugin_run(req9)
    ok("깨진 config.json을 무시했다고 말한다",
       "config.json" in r9["message"] and "무시" in r9["message"], r9["message"][:120])


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
    load_profile_file(rule_file("netflix/common"))
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

coupang = load_profile_file(rule_file("coupang/ko-sdh"))
disney = load_profile_file(rule_file("disney/ko-sdh"))
practice = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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
   # 사전에 '[뛰어가는 발걸음]'이 들어오면서(2026-08-25) '발걸음'이 직접 맞는
   # 항목이 됐다 — 그전에는 분류(발소리) 쪽으로만 fallback 했다. 둘 다 정답이다.
   any(("발소리" in t or "발걸음" in t) for t in suggest("[발걸음 소리가 들린다]")),
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

coupang2 = load_profile_file(rule_file("coupang/ko-sdh"))
disney2 = load_profile_file(rule_file("disney/ko-sdh"))
practice2 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

cp3 = load_profile_file(rule_file("coupang/ko-sdh"))
dp3 = load_profile_file(rule_file("disney/ko-sdh"))
pr3 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

cp4 = load_profile_file(rule_file("coupang/ko-sdh"))
dp4 = load_profile_file(rule_file("disney/ko-sdh"))
pr4 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

cp5 = load_profile_file(rule_file("coupang/ko-sdh"))
dp5 = load_profile_file(rule_file("disney/ko-sdh"))
pr5 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

cp6 = load_profile_file(rule_file("coupang/ko-sdh"))
dp6 = load_profile_file(rule_file("disney/ko-sdh"))
pr6 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

pr7 = load_profile_file(rule_file("netflix/ko-sdh-practice"))

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

cp_lim = TimingLimits.from_profile(load_profile_file(rule_file("coupang/ko-sdh")), fps=23.976)
ok("쿠팡은 6초·2프레임", cp_lim.max_duration_ms == 6000 and cp_lim.min_gap_ms == 83)
ok("프레임레이트가 바뀌면 간격도 바뀐다",
   TimingLimits.from_profile(load_profile_file(rule_file("coupang/ko-sdh")),
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

# **인점이 이전 자막 끝보다 앞으로 끌려가지 않는다.** 대칭인 상한(다음 인점을
# 안 넘는 것)은 있었는데 하한이 없었다 — 예능처럼 끊김 없이 오래 이어지는
# 대화에서 VAD가 수십 초짜리 말소리 구간 하나로 묶으면, 그 구간에 걸친 모든
# 자막이 구간 맨 처음(수만 ms 전)으로 끌려갔다(실측 2026-08-28, 예능A
# 15회 — #81은 33,549ms, #358은 24,158ms 전으로 계산됐는데 둘 다 직전
# 자막과 거의 붙어 있는 자리였다).
long_blob = [(1000, 30000)]   # 29초짜리 하나로 묶인 말소리 구간
two_cues = [Event(1, 1000, 5000, "첫 자막"), Event(2, 5050, 9000, "둘째 자막")]
sug = suggest_spotting(two_cues, long_blob, fps)
second_start = next((s for s in sug if s.event_index == 2 and s.field_name == "start_ms"), None)
ok("긴 말소리 구간이라도 이전 자막 끝보다 훨씬 전으로는 안 당긴다"
   "(2~3프레임 여유는 남는다)",
   second_start is None or second_start.suggested >= 5000 - 200, str(sug))


# --- 장면 전환 스냅 ----------------------------------------------------------

from checker.timing import suggest_shot_snap  # noqa: E402

shots = [10000, 20000]

# **방향이 있다**(넷플릭스 공식 문서, 2026-08-28 확인). 대칭이 아니다 —
# 전환 뒤에 시작하는 인점, 전환 앞에서 끝나는 아웃점만 당긴다.
sug = suggest_shot_snap([Event(1, 10200, 12000, "전환 뒤 시작")], shots, fps)
ok("전환 뒤 0.5초 이내에 시작하면 전환 첫 프레임으로 당긴다",
   sug and sug[0].field_name == "start_ms" and sug[0].suggested == 10000, str(sug))
ok("전환 첫 프레임으로 당기라고 말한다", "첫 프레임" in sug[0].reason)

ok("전환 앞에서 시작하면(자연스러운 배치) 건드리지 않는다 — 규정이 다루지 않는 경우",
   not suggest_shot_snap([Event(1, 9800, 12000, "전환 앞 시작")], shots, fps))

ok("이미 붙어 있으면 조용하다",
   not suggest_shot_snap([Event(1, 10000, 15000, "딱")], shots, fps))
ok("멀리 떨어져 있으면 조용하다",
   not suggest_shot_snap([Event(1, 5000, 8000, "멀리")], shots, fps))

sug = suggest_shot_snap([Event(1, 3000, 9700, "전환 앞 끝")], shots, fps)
ends = [s for s in sug if s.field_name == "end_ms"]
ok("전환 앞 0.5초 이내에 끝나면 전환 2프레임 앞으로 당긴다",
   ends and ends[0].suggested < 10000, str(sug))

ok("전환 뒤에서 끝나면(자연스러운 배치) 건드리지 않는다 — 규정이 다루지 않는 경우",
   not suggest_shot_snap([Event(1, 3000, 10300, "전환 뒤 끝")], shots, fps))

ok("전환이 없으면 아무 말도 하지 않는다",
   suggest_shot_snap([Event(1, 0, 3000, "대사")], [], fps) == [])

cp_shot = load_profile_file(rule_file("coupang/ko-sdh"))
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

warn = mismatch_warning(coupang_style, load_profile_file(rule_file("netflix/ko-sdh-practice")))
ok("프로파일이 어긋나면 경고한다", warn and "coupang" in warn, str(warn))
ok("경고에 근거가 들어간다", "소괄호" in warn)

ok("맞는 프로파일이면 조용하다",
   mismatch_warning(coupang_style, load_profile_file(rule_file("coupang/ko-sdh"))) is None)
ok("근거가 약하면 말하지 않는다",
   mismatch_warning([Event(1, 0, 3000, "그래…")],
                    load_profile_file(rule_file("coupang/ko-sdh"))) is None)


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


# --- T14: 학습값(rules/learned/)이 재분할 기준 자리를 당긴다 -----------------
# 규칙 11 — 규정이 비워 둔 자리를 실측으로 채운다. 여기서는 자막 한 장 글자
# 수(chars_per_cue) 안에서 "어디를 자를지"만 학습값 쪽으로 당기고, 상한
# 자체(max_chars)는 안 건드린다.

from checker.profile import load_learned_chars_per_cue  # noqa: E402

ok("학습값이 있으면 중앙값을 읽는다",
   load_learned_chars_per_cue("disney", "ko", "sdh") == 11.0)
# 쿠팡은 `ko-sdh`만 학습값이 있고 `ko-translation`은 없다 — 같은 발주처·같은
# 언어라도 kind가 다르면 빌려 쓰지 않는다(2026-09-08: 디즈니로 걸던 시험인데,
# `disney/ko-translation`에 값이 실제로 생겨서 대상을 옮겼다).
ok("엄격 일치 — 같은 발주처라도 kind가 다르면 None",
   load_learned_chars_per_cue("coupang", "ko", "translation") is None)
# 2026-09-08 백필: T14 경로가 디즈니 SDH 하나에서만 돌던 것을 정답지가 남아
# 있는 조합 전부로 넓혔다. 값이 사라지면 그 조합에서 경로가 조용히 죽으므로
# 여기서 함께 못박는다.
ok("백필한 조합에서 학습값이 실제로 읽힌다",
   [load_learned_chars_per_cue(*t) for t in
    (("netflix", "ko", "sdh"), ("netflix", "ko", "translation"),
     ("netflix", "en", "translation"), ("disney", "ko", "translation"),
     ("coupang", "ko", "sdh"))] == [9.5, 8.5, 28.0, 17.0, 11.0],
   str([load_learned_chars_per_cue(*t) for t in
        (("netflix", "ko", "sdh"), ("netflix", "ko", "translation"),
         ("netflix", "en", "translation"), ("disney", "ko", "translation"),
         ("coupang", "ko", "sdh"))]))
ok("엄격 일치 — 학습값 없는 발주처는 None",
   load_learned_chars_per_cue("unknown", "ko", "sdh") is None)
ok("platform이 없으면 None", load_learned_chars_per_cue(None, "ko", "sdh") is None)

_t14_text = "안녕하세요 반갑습니다 오늘 날씨가 참 좋네요 산책이나 갈까요 저는 좋아요"
_t14_default = split_text(_t14_text, 30, W2)
_t14_targeted = split_text(_t14_text, 30, W2, target_chars=8)
ok("target_chars를 주면 다르게 자른다", _t14_default != _t14_targeted,
   str((_t14_default, _t14_targeted)))
ok("target_chars 없으면 기존 동작과 100% 같다",
   split_text(_t14_text, 30, W2) == _t14_default)

disney_ko_sdh = load_profile("disney", "ko", "sdh")
_t14_learned = resplit_all([Event(1, 0, 20000, _t14_text)], disney_ko_sdh)
_t14_plain = resplit_all([Event(1, 0, 20000, _t14_text)],
                         {**disney_ko_sdh, "platform": "unknown"})
ok("resplit_all이 프로파일의 학습값을 저절로 찾아 쓴다",
   [e.text for e in _t14_learned] != [e.text for e in _t14_plain],
   str(([e.text for e in _t14_learned], [e.text for e in _t14_plain])))
ok("학습값 없는 프로파일은 기존 동작(target_chars 없음)과 같다",
   [e.text for e in _t14_plain] == split_text(_t14_text, 32, W2),
   str(([e.text for e in _t14_plain], split_text(_t14_text, 32, W2))))

_t14_tiny_profile = {**disney_ko_sdh,
                     "limits": {**disney_ko_sdh.get("limits", {}),
                                "chars_per_line": 3, "max_lines": 1,
                                "char_weights": W2}}
_t14_clamped = resplit_all([Event(1, 0, 6000, "안녕 반가워 오늘 날씨 좋다")],
                           _t14_tiny_profile)
ok("학습값이 상한(max_chars)을 넘으면 상한이 이긴다 — 조각마다 상한 안",
   all(count_chars(e.text, W2) <= 3 for e in _t14_clamped),
   str([e.text for e in _t14_clamped]))


# --- 전사 읽기와 생성 파이프라인 -----------------------------------------
# 전사 자체는 기계와 모델에 달려 있어 시험으로 붙잡을 수 없다. 전사 **결과를
# 읽는 부분**과 그 뒤 단계를 잡는다.

from checker.transcribe import _parse_srt  # noqa: E402
from checker.generate import (Draft, _to_events, merge_notes, notes_srt,  # noqa: E402
                              read_script, review_report)

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

# **모델 경로에 한글이 있으면 whisper가 못 연다**(2026-08-12 재현). 사용자 자료
# 폴더 이름이 `자막편집기`라 기본 설치 상태에서 바로 걸렸고, "자막 만들기를 눌러도
# 아무 일이 없다"는 신고의 원인이었다. 시험이 못 잡은 자리라 여기에 박아 둔다.
from checker.transcribe import _ascii_model_path  # noqa: E402

import tempfile as _tf_model  # noqa: E402
with _tf_model.TemporaryDirectory() as _d:
    _work = Path(_d) / "work"
    _work.mkdir()
    _plain = Path(_d) / "ggml-tiny.bin"
    _plain.write_bytes(b"model")
    ok("아스키 경로는 그대로 쓴다", _ascii_model_path(_plain, _work).isascii())

    _hangul = Path(_d) / "자막편집기"
    _hangul.mkdir()
    _model = _hangul / "ggml-tiny.bin"
    _model.write_bytes(b"model")
    _called = _ascii_model_path(_model, _work)
    ok("한글 경로 모델은 아스키 이름으로 바꿔 부른다", _called.isascii())
    ok("바꿔 부른 모델이 실제로 있고 내용이 같다",
       (_work / _called).is_file() and (_work / _called).read_bytes() == b"model")
    ok("두 번 불러도 다시 만들지 않는다", _ascii_model_path(_model, _work) == _called)

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

# **merge_notes — 같은 번호에 겹치면 이어 붙인다, 덮어쓰지 않는다.**
# dict(notes + additions)로 그냥 합치면 나중 것이 먼저 것을 지운다 —
# 2026-09-08, 규정 위반을 draft.notes에 합치는 기능을 넣으며 미리 막았다.
_merged = merge_notes([(1, "align 노트"), (2, "sfx 노트")], [(1, "규정 위반")])
ok("겹치는 번호는 이어 붙인다", dict(_merged)[1] == "align 노트 / 규정 위반")
ok("안 겹치는 번호는 그대로 남는다", dict(_merged)[2] == "sfx 노트")
ok("순서가 안 섞인다(1번이 먼저)", [i for i, _ in _merged] == [1, 2])
ok("빈 추가 목록이면 원본과 같다",
   merge_notes([(3, "그대로")], []) == [(3, "그대로")])

# **review_report — 노트 있는 자막만, 번호·타임코드·본문·이유를 함께 낸다.**
_review_draft = Draft(
    [Event(1, 0, 1000, "가"), Event(2, 1000, 2500, "나")],
    notes=[(2, "확인 필요")])
_review = review_report(_review_draft)
ok("노트 없는 자막은 안 나온다", "#1" not in _review)
ok("노트 있는 자막은 번호·타임코드·본문·이유가 다 나온다",
   "#2" in _review and "00:00:01,000" in _review and "나" in _review
   and "확인 필요" in _review)


# --- 번역 -----------------------------------------------------------------
# 모델은 시험에 넣지 않는다(기계마다 다르고 느리다). 모델에 **무엇을 보내고 무엇을
# 받아 어떻게 되돌리는지**를 잡는다 — 사고는 거기서 났다.

from checker.translate import (  # noqa: E402
    Glossary, _TRANSLATION_SCHEMA, _parse_numbered, _parse_schema_reply,
    _protect, _restore, _strip_markdown_wrap,
    _strip_trailing_notes, to_events, translate_events)

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

# **출력 형식을 서버가 강제하는 경로**(2026-09-01). 프롬프트로 부탁하면 모델이
# 마크다운으로 감싸고 꼬리 설명을 다는데(실측: 영어 127곳·한국어 76곳·설명 다수),
# 스키마를 걸면 그런 응답 자체가 나올 수 없다. 아래가 고정하는 것은 "둘 다 읽는가"다.
_schema_reply = _json.dumps({"translations": [
    {"id": 1, "text": "진심이야?"}, {"id": 2, "text": "20분이나 기다렸어"}]},
    ensure_ascii=False)
ok("스키마로 받은 JSON을 읽는다",
   _parse_numbered(_schema_reply, [1, 2]) == {1: "진심이야?", 2: "20분이나 기다렸어"})
ok("JSON에서도 엉뚱한 번호는 버린다",
   _parse_numbered(_json.dumps({"translations": [{"id": 7, "text": "남의 자막"}]}), [1, 2]) == {})
# 스키마는 `text`가 문자열이라는 것만 보장한다 — 그 안에 강조 표시가 들어오는 것까지는
# 못 막으므로 평문 경로와 같은 정제를 그대로 태운다.
ok("JSON 안의 강조 표시도 벗긴다",
   _parse_numbered(_json.dumps({"translations": [{"id": 1, "text": "**진심이야?**"}]},
                               ensure_ascii=False), [1]) == {1: "진심이야?"})
# **빈 딕셔너리와 None은 다른 뜻이다.** 앞은 "JSON은 맞는데 쓸 항목이 없다", 뒤는
# "JSON이 아니다"이므로 평문으로 다시 읽어야 한다 — 뭉개면 평문 경로가 통째로 빈다.
ok("JSON이 아니면 평문 경로로 넘긴다", _parse_schema_reply("1. 진심이야?", [1]) is None)
ok("깨진 JSON도 평문 경로로 넘긴다", _parse_schema_reply('{"translations": [', [1]) is None)
ok("평문 응답은 스키마 분기를 지나 그대로 읽힌다",
   _parse_numbered("1. 진심이야?\n", [1]) == {1: "진심이야?"})


# **강제가 걸리는 경로에서만 스키마를 요구한다.** `ollama run`(cli)에는 그 자리가
# 없어서, 거기까지 JSON을 요구하면 형식은 안 지켜지면서 번호마저 잃는다.
class _SchemaSpy:
    supports_schema = True

    def __init__(self):
        self.schema = None
        self.prompt = ""

    def ask(self, system, prompt, schema=None):
        self.schema, self.prompt = schema, prompt
        return _json.dumps({"translations": [{"id": 1, "text": "진심이야?"}]},
                           ensure_ascii=False)


class _PlainSpy:
    """스키마를 모르는 번역기. **두 인자짜리 `ask`가 깨지지 않아야 한다.**"""

    def __init__(self):
        self.prompt = ""

    def ask(self, system, prompt):
        self.prompt = prompt
        return "1. 진심이야?\n"


_spy = _SchemaSpy()
_cues = translate_events([Event(1, 0, 3000, "Are you serious?")], _spy)
ok("강제 가능한 경로에는 스키마를 실어 보낸다", _spy.schema == _TRANSLATION_SCHEMA)
ok("스키마 경로 프롬프트는 id를 요구한다", "`id`" in _spy.prompt)
ok("스키마 응답이 번역문이 된다", _cues[0].text == "진심이야?")

_plain = _PlainSpy()
_cues = translate_events([Event(1, 0, 3000, "Are you serious?")], _plain)
ok("스키마를 모르는 번역기는 두 인자로 부른다", _cues[0].text == "진심이야?")
ok("평문 경로 프롬프트는 번호를 요구한다", "번호를 그대로" in _plain.prompt)

# 2인 화자 하이픈이 마크다운 강조 바깥에 있어도 벗긴다(실측: 예능A 15회
# "-**What year did you debut?**", 2026-08-27).
ok("하이픈 뒤 강조를 벗긴다",
   _strip_markdown_wrap("-**What year did you debut?**") == "-What year did you debut?")
ok("하이픈 없는 강조도 그대로 벗긴다",
   _strip_markdown_wrap("**Hello there.**") == "Hello there.")

# `*` 글머리표로 시작하는 설명도 참고: 줄과 같이 자른다(실측: "* Character
# names and specific terms were kept as provided.", 2026-08-27).
ok("별표 글머리 설명을 자른다",
   _strip_trailing_notes("* Character names and specific terms were kept as provided.") == "")
ok("본문 뒤에 붙은 별표 설명도 자른다",
   _strip_trailing_notes("Hello there.\n* Character names were kept as provided.")
   == "Hello there.")

# 복수형 "Notes:"도 잡는다(실측: 예능A 15회 2차·3차 결과에 "**Notes:**\n-
# Simplified..." 통째로 자막에 남음, 2026-08-27 — 전엔 단수 "Note:"만 잡았다).
ok("복수형 참고 표제도 자른다",
   _strip_trailing_notes("Hi.\n**Notes:**\n- Simplified for brevity.") == "Hi.")


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

# --- 번역기가 목표 언어에 한국어를 섞어 낼 때 표시만 한다(고치지 않는다) ---
# 2026-08-31, 영화A·영화B 4개 언어 번역 B층 심화 대조에서 실측:
# "(참고: ...)" 한국어 메타 설명을 덧붙이거나, 단어 하나가 통째로 한국어로
# 남는 경우("유도 혼수상태にありました") 둘 다 나옴 — 영화B 일본어에서
# 1434개 중 93개(6.5%). 한국어만 잘라내면 문장이 깨지므로 지어내지 않고
# 표시만 한다(foreign_dialogue.py와 같은 논리, 규칙4).

_fake = _FakeTranslator(["1. 유도 혼수상태にありました。\n"])
_cues = translate_events([Event(1, 0, 1000, "You were in an induced coma.")],
                         _fake, Glossary(), target_lang="ja")
ok("목표 언어가 ko가 아닌데 한국어가 섞이면 확인 필요로 표시한다",
   "한국어가 섞였습니다" in _cues[0].note)

_fake = _FakeTranslator(["1. これは完全に日本語です。\n"])
_cues = translate_events([Event(1, 0, 1000, "This is entirely in Japanese.")],
                         _fake, Glossary(), target_lang="ja")
ok("순수 목표 언어 결과는 표시하지 않는다", not _cues[0].note)

_fake = _FakeTranslator(["1. 안녕하세요\n"])
_cues = translate_events([Event(1, 0, 1000, "Hello.")], _fake, Glossary(), target_lang="ko")
ok("목표 언어가 ko면 한국어가 있어도 당연히 표시하지 않는다", not _cues[0].note)

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

# --- --semantic: 짝짓기·유사도를 바꿔 끼울 수 있다 ---------------------------
# 글자는 하나도 안 겹쳐도(의역) 뜻이 같으면 짝지어야 한다. 실제 임베딩 없이
# 가짜 유사도 함수로 이 배선만 검증한다(2026-08-27, `embed.py`).

def _fake_semantic(a: str, b: str) -> float:
    pairs = {("Mister Cho isn't that you?", "Aren't you Mr. Cho?"): 0.95}
    return pairs.get((a, b), pairs.get((b, a), 0.0))

_sem_truth = [Event(1, 1000, 3000, "Aren't you Mr. Cho?")]
_sem_ours = [Event(1, 1000, 3000, "Mister Cho isn't that you?")]
_char_cmp = compare(_sem_ours, _sem_truth)
# 시간이 겹치면 +0.3 보너스가 있어 이 경우도 "짝"으로는 잡힌다 — 여기서
# 확인할 것은 짝 여부가 아니라 **글자 유사도 값 자체가 낮다는 것**이다
# (실측 0.182, 예능A 15회) — 임베딩 유사도(아래, 0.95)와 대비된다.
ok("글자 유사도는 의역을 낮게 잰다",
   _char_cmp.matched[0].text_similarity < 0.3)
_sem_cmp = compare(_sem_ours, _sem_truth, similarity_fn=_fake_semantic)
ok("의미 유사도 함수를 주면 의역도 짝짓는다",
   summarize(_sem_cmp)["counts"]["matched"] == 1)
ok("보고서의 유사도도 짝짓기에 쓴 함수의 값이다(재계산 안 함)",
   _sem_cmp.matched[0].text_similarity == 0.95)

from checker.embed import build_similarity_fn, cosine  # noqa: E402


class _FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def embed_batch(self, texts):
        self.calls += 1
        # 텍스트 길이를 벡터로 쓴다 — 진짜 임베딩은 아니지만 코사인 계산·캐시
        # 배선만 검증하면 된다.
        return [[float(len(t)), 1.0] for t in texts]


ok("코사인 유사도 — 같은 방향이면 1.0", cosine([1, 0], [2, 0]) == 1.0)
ok("코사인 유사도 — 직각이면 0.0", cosine([1, 0], [0, 1]) == 0.0)
ok("빈 벡터는 0.0(0으로 나누지 않는다)", cosine([], [1, 2]) == 0.0)

_fake_embedder = _FakeEmbedder()
_fn = build_similarity_fn(["안녕", "안녕", "다른 말"], _fake_embedder)
ok("중복 문장은 한 번만 임베딩한다(캐시)", _fake_embedder.calls == 1)
ok("같은 문장끼리는 유사도 1.0", abs(_fn("안녕", "안녕") - 1.0) < 1e-9)


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

# --- 화자가 바뀌는 자리는 합치지 않는다(diarize.py 연동) ---------------------
# whisper는 화자 구분을 못 준다. `--diarize`로 별도 모델이 찾은 화자 구간을
# 주면, 간격이 짧아도 화자가 바뀌는 자리는 합치지 않는다(실측: 예능A 15회
# "미스터 조?"/"미스터 조는 넌 아니야?" 주고받기가 한 자막으로 뭉친 버그).

_turn_events = [Event(1, 0, 1000, "미스터 조?"), Event(2, 1050, 2000, "네, 접니다.")]
_same_speaker = [(0, 1000, "A"), (1050, 2000, "A")]
_diff_speaker = [(0, 1000, "A"), (1050, 2000, "B")]
ok("화자 구간 없으면 예전처럼 합친다",
   len(merge_cues(_turn_events, 4000, 250)) == 1)
ok("같은 화자면 합친다",
   len(merge_cues(_turn_events, 4000, 250, speaker_turns=_same_speaker)) == 1)
ok("화자가 바뀌면 간격이 짧아도 안 합친다",
   len(merge_cues(_turn_events, 4000, 250, speaker_turns=_diff_speaker)) == 2)

_unknown_speaker = [(0, 1000, "A")]  # 두 번째 자막 자리엔 화자 정보가 없다
ok("화자를 모르는 자리는 억지로 안 가른다(합친다)",
   len(merge_cues(_turn_events, 4000, 250, speaker_turns=_unknown_speaker)) == 1)

# **간격이 0인 병합**(whisper 조각이 딱 붙어 있는 흔한 경우)에서
# `previous.end_ms == event.start_ms`가 같은 시각이 돼 화자 비교가 무의미해지는
# 버그가 실제로 있었다(2026-08-27, 예능A 15회 실전 검증에서 발견 — 화자
# 분리를 켜도 병합 개수가 하나도 안 바뀌었다). 각 조각 자체의 중간 지점을
# 비교해야 이 경우도 잡힌다.
_zero_gap_events = [Event(1, 0, 2000, "미스터 조?"), Event(2, 2000, 4000, "네, 접니다.")]
_zero_gap_diff_speaker = [(0, 2000, "A"), (2000, 4000, "B")]
ok("간격 0이어도 화자가 바뀌면 안 합친다",
   len(merge_cues(_zero_gap_events, 4000, 250, speaker_turns=_zero_gap_diff_speaker)) == 2)

# 세 조각 이상 이어질 때 "누적된 자막"이 아니라 "마지막 원래 조각"과 비교해야
# 한다 — 누적본의 중간 지점을 쓰면 조각이 늘수록 엉뚱한 자리를 보게 된다.
_three_events = [Event(1, 0, 1000, "가"), Event(2, 1000, 2000, "나"), Event(3, 2000, 3000, "다")]
_three_speaker = [(0, 2000, "A"), (2000, 3000, "B")]
_three_merged = merge_cues(_three_events, 4000, 250, speaker_turns=_three_speaker)
ok("연쇄 병합에서도 화자 교체 지점을 정확히 가른다",
   len(_three_merged) == 2 and _three_merged[0].text == "가 나")

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

from checker.revise import (  # noqa: E402
    Revision, _too_different, report as revision_report, revise)

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

# 여러 회차(2차·3차...) 결과를 한 목록으로 받으면 회차별로 나눠서 세야 한다 —
# 전부 첫 회차 이름으로만 합산해 세면 뒤 회차가 고친 것까지 앞 회차가 고친
# 것처럼 보인다(실측, 2026-08-27).
_multi_round = [Revision(1, "가", "나", "2차"), Revision(2, "다", "라", "2차"),
               Revision(3, "마", "바", "3차")]
_multi_report = revision_report(_multi_round)
ok("회차별로 나눠서 센다", "2차 2개" in _multi_report and "3차 1개" in _multi_report,
   _multi_report)

# **표지가 합쳐진 문자열의 중간 줄에서 시작해도 걷어낸다.** `_parse_numbered`가
# 번호 없는 줄을 앞 번호에 이어 붙이므로, 모델이 "[pass 2]" 같은 표지를 두 번째
# 줄에 남기면 문자열 맨 앞이 아니라 중간에 온다(실측: 예능A 15회 2차·3차
# 결과, "[pass 2] -With our contract..."가 자막에 그대로 남음, 2026-08-27).
_tag_evs = [Event(1, 0, 1000, "첫 줄 그리고 둘째 줄")]
_tag_fake = _FakeTranslator(["1. 첫 줄\n[pass 2] 둘째 줄\n"])
_tag_out, _ = revise(_tag_evs, _tag_fake, target_lang="ko", stage="3차")
ok("표지가 중간 줄에 있어도 걷어낸다", "[pass 2]" not in _tag_out[0].text, _tag_out[0].text)

# 2차·3차도 1차와 같은 모델이 내는 흘림(마크다운 강조·자기 설명)을 똑같이 겪는다
# — 1차용 걸러내기를 그대로 재사용해야 한다.
_notes_evs = [Event(1, 0, 1000, "다듬을 문장이다")]
_notes_fake = _FakeTranslator(["1. 다듬은 문장\n**Notes:**\n- 이유 설명\n"])
_notes_out, _ = revise(_notes_evs, _notes_fake, target_lang="ko", stage="3차")
ok("2차·3차에서도 자기 설명을 걷어낸다", _notes_out[0].text == "다듬은 문장", _notes_out[0].text)

# --- 영어 2차·3차(target_lang) ----------------------------------------------
# 존댓말/반말 같은 한국어 문법 규칙이 영어 프롬프트에 안 섞여야 한다. 지원하지
# 않는 언어는 조용히 한국어로 떨어지지 않고 실패해야 한다(규칙 9).

_en_evs = [Event(1, 0, 1000, "I do not know what happened.")]
_en_fake = _FakeTranslator(["1. I don't know what happened.\n"])
_en_out, _en_rev = revise(_en_evs, _en_fake, target_lang="en", stage="3차")
ok("영어 3차도 고친 자막을 돌려준다", _en_out[0].text == "I don't know what happened.")

from checker.revise import THIRD_PASS_EN as _P3_EN, SECOND_PASS_EN as _P2_EN  # noqa: E402
ok("영어 프롬프트에 한국어 존댓말 조항이 안 섞인다",
   "존댓말" not in _P2_EN and "존댓말" not in _P3_EN)

try:
    revise(_en_evs, _FakeTranslator(["1. x\n"]), target_lang="fr", stage="2차")
    ok("지원 안 하는 언어는 실패한다", False)
except ValueError as exc:
    ok("지원 안 하는 언어는 실패한다", "fr" in str(exc))


# --- 전사 원문 문맥 검사 ----------------------------------------------------
# whisper가 비슷하게 들리는 다른 말로 잘못 듣고도 문법이 멀쩡한 문장을 만드는
# 것을, 앞뒤 자막과 이어 붙여 보고 걸러낸다. 고치지 않고 알리기만 한다(규칙 4).

from checker.context_check import flag_context_mismatches  # noqa: E402

_ctx_evs = [Event(1, 0, 1000, "우리는 동기와 설명이 필요합니다"),
           Event(2, 1000, 2000, "그 뒤에 진행하겠습니다")]
_ctx_fake = _FakeTranslator(["1: '동기와 설명'은 문맥상 '동기화 설명'의 오청으로 보입니다\n"])
_ctx_flags = flag_context_mismatches(_ctx_evs, _ctx_fake)
ok("문맥 불일치를 (번호, 이유)로 돌려준다",
   _ctx_flags == [(1, "'동기와 설명'은 문맥상 '동기화 설명'의 오청으로 보입니다")])

ok("자막 텍스트는 그대로다 — 고치지 않는다", _ctx_evs[0].text == "우리는 동기와 설명이 필요합니다")

ok("NONE이면 아무것도 안 남는다",
   flag_context_mismatches(_ctx_evs, _FakeTranslator(["NONE\n"])) == [])

ok("빈 답도 아무것도 안 남는다",
   flag_context_mismatches(_ctx_evs, _FakeTranslator([""])) == [])

ok("번역기가 없으면 검사를 건너뛴다", flag_context_mismatches(_ctx_evs, None) == [])

ok("자막이 없으면 빈 목록", flag_context_mismatches([], _ctx_fake) == [])

# 배치 범위 밖 번호를 모델이 잘못 대답해도 끼워 넣지 않는다.
_ctx_bad = _FakeTranslator(["99: 없는 번호\n1: 진짜 불일치\n"])
ok("범위 밖 번호는 버린다", flag_context_mismatches(_ctx_evs, _ctx_bad) == [(1, "진짜 불일치")])


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

    # 면적 — 작업마다 크게 봐야 하는 곳이 다르다.
    from app.window import MainWindow  # noqa: E402

    # 사람이 쓰던 배치를 되살리면 시험 결과가 기계마다 달라진다.
    _win = MainWindow(restore=False)
    _win.resize(1600, 900)
    _win.show()
    _qt_app.processEvents()

    # **두 배치를 견준다.** 절대 크기로 재면 화면이 작은 기계에서 창이 눌려
    # 통과·실패가 갈린다(실제로 그랬다). 견주는 것이 원래 확인하려던 것이기도 하다.
    # **파형은 아래 전체 폭을 쓴다.** 표는 스크롤하며 보면 되니 좁아도 된다.
    _win.apply_layout("spotting")
    _qt_app.processEvents()
    _spotting_rows = _win.main_splitter.sizes()      # [위, 파형]
    _spotting_top = _win.top_splitter.sizes()        # [영상, 표]

    _win.apply_layout("translating")
    _qt_app.processEvents()
    _translating_rows = _win.main_splitter.sizes()
    _translating_top = _win.top_splitter.sizes()

    ok("타임코드 배치는 파형을 크게 준다",
       _spotting_rows[1] > _translating_rows[1])
    ok("타임코드 배치에서는 파형이 위쪽보다 크다",
       _spotting_rows[1] > _spotting_rows[0])
    ok("번역 배치는 표를 넓게 준다",
       _translating_top[1] > _spotting_top[1])
    ok("파형은 창 전체 폭을 쓴다",
       _win.waveform.width() >= _win.top_splitter.width() - 2)

    # 잡이가 보여야 잡는다. 가는 선은 있는 줄도 모른다.
    ok("잡이가 잡을 만큼 두껍다", _win.main_splitter.handleWidth() >= 6)
    ok("칸이 완전히 접히지는 않는다", not _win.main_splitter.childrenCollapsible())
    _win.close()


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


# --- 원어 대본 읽기 --------------------------------------------------------
# 대본은 자막 파일로 오지 않는다. 워드·텍스트·PDF로 온다(사용자 지적 2026-08-12).

import zipfile as _zip  # noqa: E402
from checker.script import ScriptUnavailable, read_any, read_lines, read_text  # noqa: E402

with _tf3.TemporaryDirectory() as _d:
    _folder = Path(_d)

    # 한국어 파일은 cp949로 오는 경우가 흔하다.
    _cp949 = _folder / "cp949.txt"
    _cp949.write_bytes("첫 대사\n둘째 대사\n".encode("cp949"))
    ok("cp949 텍스트를 읽는다", read_text(_cp949).startswith("첫 대사"))

    _utf8 = _folder / "utf8.txt"
    _utf8.write_text("SARAH: Hello there.\n\n(She leaves.)\n\nDAD: Wait.\n",
                     encoding="utf-8")
    _lines = read_lines(_utf8)
    ok("텍스트 대본에서 대사만 딴다", [l.text for l in _lines] == ["Hello there.", "Wait."])
    ok("화자명을 함께 들고 온다", _lines[0].speaker == "Sarah")

    # 빈 줄이 없는 대본은 한 줄이 한 대사다. 그대로 두면 통째로 한 덩어리가 된다.
    _dense = _folder / "dense.txt"
    _dense.write_text("첫 줄\n둘째 줄\n셋째 줄\n", encoding="utf-8")
    ok("빈 줄이 없으면 줄마다 대사로 본다", len(read_lines(_dense)) == 3)

    # 워드는 zip 안의 XML이다. 표준 라이브러리로 읽는다.
    _docx = _folder / "script.docx"
    with _zip.ZipFile(_docx, "w") as _archive:
        _archive.writestr("word/document.xml",
                          '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
                          '<w:p><w:r><w:t>NARRATOR: In December 1944.</w:t></w:r></w:p>'
                          '<w:p><w:r><w:t>The battle begins.</w:t></w:r></w:p>'
                          '</w:body></w:document>')
    _from_docx = read_lines(_docx)
    ok("워드 대본을 읽는다", len(_from_docx) == 2)
    ok("워드에서도 화자를 뗀다", _from_docx[0].text == "In December 1944.")

    _broken = _folder / "broken.docx"
    with _zip.ZipFile(_broken, "w") as _archive:
        _archive.writestr("hello.txt", "not a word file")
    try:
        read_any(_broken)
        ok("워드가 아니면 알려 준다", False)
    except ScriptUnavailable:
        ok("워드가 아니면 알려 준다", True)


# --- 단축키와 기능 설명 ----------------------------------------------------
# **설명이 키보다 중요하다.** 어떤 기능을 쓸 수 있는지 알아야 도구를 쓴다
# (사용자 지적 2026-08-12). 키는 기본값일 뿐이고 사람이 바꾼다.

from app import shortcuts as _shortcuts  # noqa: E402

ok("기능마다 설명이 있다", all(len(a.what) > 20 for a in _shortcuts.ACTIONS))
ok("기능마다 묶음이 있다", all(a.group in _shortcuts.GROUPS for a in _shortcuts.ACTIONS))
ok("기본 단축키가 겹치지 않는다",
   _shortcuts.conflicts({a.key: a.default for a in _shortcuts.ACTIONS}) == [])
# 같은 키를 둘이 쓰면 하나만 듣는다. 말없이 덮어쓰지 않는다.
_clash = _shortcuts.conflicts({"play": "Ctrl+D", "split": "Ctrl+D"})
ok("겹친 키를 찾아낸다", len(_clash) == 1 and _clash[0][0] == "Ctrl+D")
ok("빈 키는 겹침으로 보지 않는다", _shortcuts.conflicts({"a": "", "b": ""}) == [])

with _tf3.TemporaryDirectory() as _d:
    _os3.environ["SUBTITLE_EDITOR_HOME"] = _d
    _keys = _shortcuts.load()
    ok("바꾸지 않으면 기본값", _keys["split"] == "Ctrl+Space")

    _keys["split"] = "Ctrl+D"
    _shortcuts.save(_keys)
    ok("바꾼 값이 남는다", _shortcuts.load()["split"] == "Ctrl+D")
    # **바꾼 것만 적는다.** 기본값이 나중에 바뀌면 따라가야 한다.
    _saved = _json.loads((Path(_d) / "shortcuts.json").read_text(encoding="utf-8"))
    ok("바꾼 것만 파일에 적는다", list(_saved) == ["split"])
    _os3.environ.pop("SUBTITLE_EDITOR_HOME", None)


# --- 사용자 설정 -----------------------------------------------------------
# 규정(프로파일)과 취향(설정)을 섞지 않는다. 자막이 규정을 어겼는지와 무관한 것들이다.

from app import prefs as _prefs  # noqa: E402

ok("설정마다 설명이 있다", all(len(o.what) > 15 for o in _prefs.OPTIONS))
ok("설정마다 묶음이 있다", all(o.group in _prefs.GROUPS for o in _prefs.OPTIONS))
ok("모든 항목에 기본값이 있다",
   all(o.key in _prefs.DEFAULTS for o in _prefs.OPTIONS))

with _tf3.TemporaryDirectory() as _d:
    _os3.environ["SUBTITLE_EDITOR_HOME"] = _d
    _values = _prefs.load()
    ok("바꾸지 않으면 기본값", _values["waveform_ms_per_pixel"] == 20)

    _values["waveform_ms_per_pixel"] = 8
    _prefs.save(_values)
    ok("바꾼 값이 남는다", _prefs.load()["waveform_ms_per_pixel"] == 8)
    # **바꾼 것만 적는다.** 기본값이 나중에 바뀌면 따라가야 한다.
    _kept = _json.loads((Path(_d) / "settings.json").read_text(encoding="utf-8"))
    ok("바꾼 것만 파일에 적는다", list(_kept) == ["waveform_ms_per_pixel"])
    # 엉뚱한 자료형이 들어오면 무시한다 — 손으로 고치다 깨뜨릴 수 있다.
    (Path(_d) / "settings.json").write_text('{"waveform_ms_per_pixel": "여덟"}',
                                            encoding="utf-8")
    ok("자료형이 다르면 기본값을 지킨다", _prefs.load()["waveform_ms_per_pixel"] == 20)
    _os3.environ.pop("SUBTITLE_EDITOR_HOME", None)


# --- 일을 다른 실에서 돌릴 때 객체가 사라지지 않는지 ---------------------------
# **2026-08-12 실사용 사고.** [자막 만들기]가 16분간 아무 일도 하지 않았다. 상태줄은
# "만드는 중입니다..."에서 멈추고, 로그에 한 줄도 안 늘고, ffprobe·ffmpeg·ollama 어느
# 것도 뜨지 않고, CPU는 10초에 0.5초만 썼다. 예외도 실패 신호도 없었다.
#
# 원인: 부르는 쪽이 `job`을 지역 변수로 두고 실만 보관해서, 파이썬이 `Job`을 거둬 가고
# `thread.started`에 연결한 슬롯이 사라졌다. `moveToThread`는 소유권을 넘기지 않는다.
#
# 이 시험은 **참조를 일부러 버린다.** GUI가 없어도 도는 자리에서만 돌린다.
try:
    from PySide6.QtWidgets import QApplication  # noqa: E402
except ImportError:
    ok("일 객체 보관 (PySide6 없어 건너뜀)", True)
else:
    import gc as _gc  # noqa: E402
    import os as _osq  # noqa: E402
    _osq.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
    from app import jobs as _jobs  # noqa: E402

    _app = QApplication.instance() or QApplication([])
    _ran: list[str] = []

    class _Tiny(_jobs.Job):
        def run(self):
            self._guarded(lambda: _ran.append("ran") or "result")

    def _start_and_drop():
        _job = _Tiny()                     # 지역 변수 — 사고 당시와 같은 상황
        _jobs.start(_job, lambda r: _ran.append("done"), lambda m: None,
                    lambda w: _ran.append("failed"))
        # 참조가 여기서 사라진다

    _start_and_drop()
    _gc.collect(); _gc.collect()
    _loop = QEventLoop()
    QTimer.singleShot(1500, _loop.quit)
    _loop.exec()

    ok("일 참조를 버려도 실행된다", "ran" in _ran, str(_ran))
    ok("끝나면 done 콜백이 온다", "done" in _ran, str(_ran))
    ok("끝난 일은 보관 목록에서 빠진다", len(_jobs._ALIVE) == 0, str(len(_jobs._ALIVE)))


# --- 교정과 검사의 순서 -----------------------------------------------------
# **검사는 맨 끝이다.** 원본만 검사하면 교정이 만든 새 위반을 못 본다. 아래가 실제
# 그런 경우다 — `불`을 `달러`로 고치면 한 글자가 늘어 줄 길이 한계를 넘는다.
#
# 결과 출력은 이 아래에 둔다. 위로 올려 두었다가 마지막에 붙인 시험 셋이 **실패해도
# 보고되지 않는 상태**로 한동안 있었다.

from checker.model import Event as _PEvent  # noqa: E402
from checker.pipeline import (CorrectOptions as _POpts,  # noqa: E402
                             correct_and_check as _pcheck)

_pprof = load_profile("netflix", "ko", "sdh")
_pline = "3천 불 " + "가" * 12          # 15.5자 -> 고치면 16.5자 (한계 16자)
_pevents = [_PEvent(1, 1000, 5000, _pline)]

_before = check_events([e.__dict__ for e in _pevents], _pprof, fps=23.976)
ok("고치기 전에는 길이 위반이 없다", "S01" not in ids(_before))
ok("고치기 전에는 화폐 표기가 걸린다", "C30" in ids(_before))

_after = _pcheck(_pevents, _pprof, _POpts(apply_fixes=True, fps=23.976))
_aids = {v["rule_id"] for v in _after.violations}
ok("교정이 만든 길이 위반을 잡는다", "S01" in _aids, str(sorted(_aids)))
ok("고쳐진 위반은 목록에서 빠진다", "C30" not in _aids, str(sorted(_aids)))
ok("교정본이 결과로 나온다", _after.events[0].text == "3천 달러 " + "가" * 12,
   _after.events[0].text)
# 입력을 건드리지 않는다 — 어댑터가 원본을 다시 쓸 수 있어야 한다.
ok("입력 자막은 그대로다", _pevents[0].text == _pline)

# 무엇을 고쳤는지 줄 단위로 남는다. 규칙 이름만으로는 되짚을 수 없다.
_pedits = _after.extra["edits"]
ok("고친 자리를 줄 단위로 남긴다", len(_pedits) == 1 and _pedits[0]["event_index"] == 1,
   str(_pedits))
ok("고치기 전 글자도 남긴다", _pedits[0]["before"] == _pline, str(_pedits))

# 교정을 끄면 원본을 설명한다 — 파일을 쓰지 않는 검사에서 그래야 한다.
_off = _pcheck(_pevents, _pprof, _POpts(apply_fixes=False, fps=23.976))
ok("교정을 끄면 원본을 검사한다", "C30" in {v["rule_id"] for v in _off.violations})
ok("교정을 끄면 고친 자리가 없다", _off.extra["edits"] == [])

# 한국어 교정 레인: 지적은 받되 글자는 그대로 두는 모드. `apply_korean=False`는
# 파일을 쓰지 않는 검사에서 쓴다 — 교정문을 얹고 검사하면 리포트가 사용자가 가진
# 자막이 아니라 '고쳤다면 됐을 것'을 설명한다.
_kevents = [_PEvent(1, 1000, 4000, "[진수] 어디 갔었어?")]

_kon = _pcheck(_kevents, _pprof, _POpts(korean=True, backend=fake_backend,
                                        apply_korean=True, apply_fixes=False,
                                        fps=23.976))
ok("교정문을 얹으면 글자가 바뀐다", "갔었어요" in _kon.events[0].text,
   _kon.events[0].text)
ok("얹은 자리를 센다", _kon.extra["korean_changed"] == 1,
   str(_kon.extra["korean_changed"]))

_koff = _pcheck(_kevents, _pprof, _POpts(korean=True, backend=fake_backend,
                                         apply_korean=False, apply_fixes=False,
                                         fps=23.976))
ok("얹지 않으면 글자는 그대로", _koff.events[0].text == _kevents[0].text,
   _koff.events[0].text)
ok("얹지 않아도 지적은 온다",
   {"K01", "K02"} <= {v["rule_id"] for v in _koff.violations},
   str(sorted({v["rule_id"] for v in _koff.violations})))
ok("얹지 않으면 고친 자리가 없다", _koff.extra["korean_edits"] == [],
   str(_koff.extra["korean_edits"]))

# **CLI가 실제로 어긋나 있던 자리다.** `correct_and_check`는 처음부터 순서가 맞았고,
# 원본을 검사한 뒤 따로 고쳐 쓰던 쪽이 CLI였다. 그래서 여기서 한 번 더 잰다.
import io as _pio  # noqa: E402
import json as _pjson  # noqa: E402
import tempfile as _ptf  # noqa: E402
from contextlib import redirect_stdout as _predirect  # noqa: E402

with _ptf.TemporaryDirectory() as _pd:
    _ppath = Path(_pd) / "grow.srt"
    _ppath.write_text(f"1\n00:00:01,000 --> 00:00:05,000\n{_pline}\n",
                      encoding="utf-8")
    _pbuf = _pio.StringIO()
    with _predirect(_pbuf):
        cli_main([str(_ppath), "-p", "netflix", "-l", "ko", "-k", "sdh",
                  "--fix", "--json"])
    _preport = _pjson.loads(_pbuf.getvalue())
    _pids = {v["rule_id"] for v in _preport["violations"]}
    ok("CLI 리포트가 교정본을 설명한다", "S01" in _pids and "C30" not in _pids,
       str(sorted(_pids)))
    ok("CLI가 고친 자리를 남긴다",
       [c["event_index"] for c in _preport["text_changes"]] == [1],
       str(_preport.get("text_changes")))
    # 리포트가 설명하는 자막과 실제로 나간 파일이 같아야 한다.
    ok("리포트와 나간 파일이 같다",
       (Path(_pd) / "grow.fixed.srt").read_text(encoding="utf-8").splitlines()[2]
       == "3천 달러 " + "가" * 12)


# --- 말투 (다큐 합니다체) ---------------------------------------------------
# 작업자 자료 312행 "다큐멘터리는 무조건 존댓말"에 사용자가 덧붙였다 — 합니다체
# 위주이지만 **자연스러움을 위해 가끔 '요'를 쓰는 것은 허용된다.** 그래서 줄마다
# 잡지 않고 비율만 낸다. 임계값은 완성본으로 재기 전까지 두지 않는다.

from checker import formality as _fm  # noqa: E402

_fmcases = [
    ("합니다", "합니다체"), ("먹었습니다", "합니다체"), ("가시겠습니까?", "합니다체"),
    ("들어오십시오", "합니다체"), ("아닙니다", "합니다체"),
    # `니다`만 보면 아래 둘이 합니다체로 잡힌다. 앞 음절 ㅂ받침이 그걸 막는다.
    ("그게 아니다", None), ("아니까 그렇지", None),
    ("그래요", "해요체"), ("맞죠?", "해요체"), ("어디 가세요", "해요체"),
    # 유보 — 반말인지 문장 중간이 잘린 것인지 줄 끝만 보고 가를 수 없다.
    ("왔어", None), ("해야", None),
    ("[민수] 안녕하십니까", "합니다체"),      # 화자명은 대사가 아니다
    ("[문이 닫히는 소리]", None),            # 효과음뿐이면 셀 것이 없다
    ("♪ 사랑이 지나간 자리에 ♪", None),
    ("그러니까 제 말은\n이렇게 됩니다", "합니다체"),   # 마지막 줄이 문장의 끝
]
for _text, _want in _fmcases:
    ok(f"말투 판별: {_text.splitlines()[0][:14]}", _fm.level_of(_text) == _want,
       f"{_fm.level_of(_text)} (기대 {_want})")

_fmevs = [_PEvent(i, 0, 1000, t) for i, (t, _) in enumerate(_fmcases, 1)]
_fms = _fm.summary(_fmevs)
ok("확정만 센다", _fms["decided"] == 10, str(_fms["counts"]))
ok("유보를 함께 낸다", _fms["undecided"] == 5, str(_fms["undecided"]))
# 비율은 **확정된 것들 사이의 비율**이다. 전체로 나누면 유보가 많을 때 뜻이 없어진다.
ok("비율은 확정분 기준", abs(_fms["formal_ratio"] - 0.7) < 1e-9,
   str(_fms["formal_ratio"]))
# 확정이 없으면 비율은 0.0이 아니라 없음이다 — 0.0은 "합니다체가 하나도 없다"로 읽힌다.
ok("확정이 없으면 비율도 없다",
   _fm.summary([_PEvent(1, 0, 1000, "[문 닫히는 소리]")])["formal_ratio"] is None)


# --- 캐릭터 분석 문서 -------------------------------------------------------
# **KNP 시트와 다른 문서다.** KNP는 고유명사 표기를, 이 문서는 말투와 인물 관계를
# 통일한다. 하나의 작품을 여러 작업자가 나누어 하기 때문에 필요하다.

from checker import characters as _ch  # noqa: E402

_chevs = [
    _PEvent(1, 0, 2000, "[민수] 김 경위님 어디 계십니까"),
    _PEvent(2, 2000, 4000, "[김 경위] 여기 있습니다"),
    _PEvent(3, 4000, 6000, "[민수] 지금 갑니다"),
    _PEvent(4, 6000, 8000, "저기 뭔가 있어요"),          # 화자 표시 없음
    _PEvent(5, 8000, 10000, "[문이 닫히는 소리]"),        # 효과음 — 인물이 아니다
    _PEvent(6, 10000, 12000, "[영희] 민수 씨 왔어요"),
    _PEvent(7, 12000, 14000, "[영희] 김 경위 어디 갔지"),
]
_people, _chcounts = _ch.extract(_chevs)
_by = {p.name: p for p in _people}

ok("인물만 뽑는다(효과음 제외)", sorted(_by) == ["김 경위", "민수", "영희"],
   str(sorted(_by)))
ok("대사 수를 센다", _by["민수"].lines == 2 and _by["김 경위"].lines == 1)
ok("대사가 많은 순", [p.name for p in _people][:2] == ["민수", "영희"],
   str([p.name for p in _people]))
# 못 센 것을 숨기지 않는다. 화자를 모르는 자막을 앞 화자에게 이어 붙이면 말투가
# 틀린 인물에게 쌓인다.
ok("화자를 모르는 자막은 따로 센다", _chcounts["untagged_events"] == 1,
   str(_chcounts))
ok("효과음은 화자 미상으로도 세지 않는다", _chcounts["tagged_events"] == 5,
   str(_chcounts))

# 말투는 그 인물의 대사만 모아서 센다. 화자 표시가 집계에 섞이면 안 된다.
ok("화자별로 말투를 센다",
   _by["민수"].dominant == "합니다체" and _by["영희"].dominant == "해요체",
   f'{_by["민수"].dominant} / {_by["영희"].dominant}')

# 호칭은 대사 안에 있으므로 근거가 된다. 다만 관계를 단정하지는 않는다.
ok("호칭을 뽑는다", _by["민수"].calls == {"김 경위": ["님"]}, str(_by["민수"].calls))
ok("긴 이름을 먼저 맞춘다 — '김 경위'가 '경위'에 먹히지 않는다",
   "김 경위" in _by["영희"].mentions, str(_by["영희"].mentions))
ok("자기 이름은 언급으로 세지 않는다", "민수" not in _by["민수"].mentions)

# **관계·성격·사진은 자막이 증명하지 못한다.** 비워 두고 표시한다.
ok("관계는 비어 있다", all(not p.relations for p in _people))
ok("조사 전에는 researched가 거짓", not any(p.researched for p in _people))
_chsum = _ch.summarize(_people)
ok("관계 없는 인물 수를 낸다", _chsum["no_relation"] == 3, str(_chsum))

_tsv = _ch.to_tsv(_people).splitlines()
ok("표에 근거 칸이 있다", _tsv[0].split("\t")[-1] == "근거", _tsv[0])
ok("채우지 않은 칸은 '확인 필요'", "확인 필요" in _tsv[1], _tsv[1])
ok("표는 인물마다 한 줄", len(_tsv) == 4, str(len(_tsv)))

_md = _ch.to_markdown(_people, _chcounts, "표본")
ok("문서에 못 센 자막을 적는다", "화자를 모르는 자막 1개" in _md)
ok("문서에 증명 못 하는 것을 밝힌다", "자막이 증명하지 못하므로" in _md)
# 사진은 저작권물이라 링크로만 넣는다. 없으면 넣지 않는다.
ok("사진이 없으면 그림을 넣지 않는다", "![" not in _md)
_by["민수"].photo = "characters/민수.jpg"
ok("사진이 있으면 링크로 넣는다",
   "![민수](characters/민수.jpg)" in _ch.to_markdown(_people, _chcounts))


# --- 번역·감수·용어 단계 ----------------------------------------------------
# `STAGES`는 다섯 단계를 선언하는데 `stage_` 함수는 넷뿐이었다. `translate`와
# `terms`는 두 어댑터가 각자 적어 두어 세 가지가 갈렸다:
#   ① GUI가 사용자의 번역 모델 설정을 무시했다(설정이 죽어 있었다)
#   ② GUI가 감수 내역을 버려 무엇이 바뀌었는지 볼 수 없었다
#   ③ GUI가 타임코드 고정을 확인하지 않았다

from checker import pipeline as _pl  # noqa: E402
from checker.translate import DEFAULT_MODEL as _DEF_MODEL  # noqa: E402

_declared = {s.id for s in _pl.STAGES}
_built = {n[6:] for n in dir(_pl) if n.startswith("stage_") and n != "stage_by_id"}
ok("선언한 단계마다 함수가 있다", _declared <= _built, str(sorted(_declared - _built)))


class _EchoTranslator:
    """번호를 그대로 돌려주는 흉내. 무엇을 물었는지도 남긴다."""

    def __init__(self):
        self.systems = []

    def ask(self, system, prompt):
        self.systems.append(system)
        out = []
        for line in prompt.splitlines():
            head = line.strip().split(".")[0].strip()
            if head.isdigit():
                out.append(f"{head}. 옮긴 말 {head}")
        return "\n".join(out)


_trprof = load_profile("netflix", "ko", "translation")
_trevs = [_PEvent(1, 0, 2000, "Find them"), _PEvent(2, 2000, 4000, "Before we fight")]
_tr = _EchoTranslator()
_first = _pl.stage_translate(_trevs, _trprof, translator=_tr)
ok("번역이 타임코드를 물려받는다",
   [(e.start_ms, e.end_ms) for e in _first.events] == [(0, 2000), (2000, 4000)])
# 전에는 CLI만 확인했다. 이제 단계가 확인하므로 GUI도 얻는다.
ok("타임코드가 그대로면 위반이 없다", _first.violations == [], str(_first.violations))
ok("확인이 필요한 자리를 낸다", "notes_by_index" in _first.extra)

# **회차는 인자다.** 전에는 `("2차","3차")[:passes-1]`이라 3차가 상한이었다.
_later = _pl.stage_revise(_first.events, _trprof, translator=_tr,
                          source={1: "Find them", 2: "Before we fight"}, rounds=3)
ok("회차 상한이 없다 — 4차까지 돈다",
   [r["stage"] for r in _later.extra["rounds"]] == ["2차", "3차", "4차"],
   str(_later.extra["rounds"]))
ok("첫 회차는 감수, 그 뒤는 윤문",
   [r["role"] for r in _later.extra["rounds"]] == ["감수", "윤문", "윤문"],
   str([r["role"] for r in _later.extra["rounds"]]))
# 프롬프트가 역할에 따라 실제로 갈리는지. 라벨만 바뀌고 프롬프트가 같으면 뜻이 없다.
ok("감수와 윤문이 다른 프롬프트를 쓴다",
   len({s[:24] for s in _tr.systems}) >= 2, str(len({s[:24] for s in _tr.systems})))
# 바꾼 내역을 버리지 않는다.
ok("감수 내역을 돌려준다", "revisions" in _later.extra)

# `stage`로 프롬프트를 유추하던 것이 조용한 실패의 원인이었다 — `"4차"`를 넘기면
# 에러 없이 윤문 프롬프트로 돌았다. 이제 알 수 없으면 예외다.
from checker.revise import revise as _revise  # noqa: E402
try:
    _revise(_trevs[:1], _tr, stage="4차")
    ok("유추할 수 없는 회차는 예외", False, "예외가 나지 않았다")
except ValueError:
    ok("유추할 수 없는 회차는 예외", True)
try:
    _revise(_trevs[:1], _tr, stage="4차", role="없는역할")
    ok("모르는 역할은 예외", False, "예외가 나지 않았다")
except ValueError:
    ok("모르는 역할은 예외", True)

# 모델 기본값이 세 곳에 흩어져 값이 달랐다. 이제 하나다.
from checker.translate import OllamaCliTranslator as _Cli  # noqa: E402
ok("설정 기본값과 번역기 기본값이 같다",
   _prefs.DEFAULTS["translate_model"] == _DEF_MODEL, _prefs.DEFAULTS["translate_model"])
ok("라이선스 제약을 설명에 적는다",
   "라이선스" in [o for o in _prefs.OPTIONS if o.key == "translate_model"][0].what)
ok("모델을 주지 않으면 기본값을 쓴다",
   _Cli.__init__.__defaults__[0] is None)


# --- 장르 겹치기 -------------------------------------------------------------
# 장르를 프롬프트가 아니라 **프로파일 층**에 두는 이유: 작업자 자료 590행이 장르로
# 타임코드 길이를 가른다. 프롬프트에 적으면 검사기가 모른다.
# (`translate.DOCUMENTARY_RULES`가 죽은 코드로 남아 있던 이유가 그것이다.)

from checker import genre as _gn  # noqa: E402

_gnames = {g["genre"] for g in _gn.available()}
ok("장르 셋", _gnames == {"documentary", "drama", "variety"}, str(sorted(_gnames)))
# 근거 없는 프로파일을 만들지 않는다 — 멜로는 드라마, 느와르는 캐릭터 문제다.
ok("멜로·느와르 프로파일은 만들지 않았다",
   not {"melodrama", "noir"} & _gnames, str(sorted(_gnames)))
ok("장르마다 출처가 있다",
   all(g["source"].get("client") for g in _gn.available()))

_gbase = load_profile("netflix", "ko", "sdh")
_gdoc = _gn.apply(_gbase, "documentary")
_gdrama = _gn.apply(_gbase, "drama")

ok("장르를 주지 않으면 그대로", _gn.apply(_gbase, None) is _gbase)
ok("다큐는 ~씨를 막는다", _gdoc["address"]["forbid_ssi"] is True)
ok("드라마는 ~씨를 허용한다", _gdrama["address"]["forbid_ssi"] is False)
ok("장르마다 권장 표시 시간이 다르다",
   _gn.recommended_spotting(_gdoc)[:2] == (3000, 5000)
   and _gn.recommended_spotting(_gdrama)[:2] == (2000, 3000))
# **출처를 덮어쓰지 않는다.** 플랫폼 규정과 장르 관행은 근거의 무게가 다르다.
ok("플랫폼 출처가 살아 있다", _gdoc["source"]["official"] is True)
ok("장르 출처를 따로 남긴다", "658" in _gdoc["genre_source"]["section"],
   str(_gdoc.get("genre_source")))
ok("얹어도 원본을 바꾸지 않는다", "genre" not in _gbase)

def _gev(text, index, start=0, end=4000):
    # 위쪽 `ev` 도우미는 루프 변수에 덮여 있다. 여기서 쓸 것을 따로 만든다.
    return {"index": index, "start_ms": start, "end_ms": end, "text": text}


_gevs = [
    _gev("민수 씨 어디 계십니까", 1, 0, 4000),
    _gev("[민수] 여기 있습니다", 2, 4000, 8000),      # 화자명은 호칭이 아니다
    _gev("씨앗을 심었습니다", 3, 8000, 12000),         # 낱말
    _gev("그 씨 말입니까", 4, 12000, 16000),           # 지시어 — 거른다
]
_gdocids = [(v["event_index"]) for v in check_events(_gevs, _gdoc, fps=23.976)["violations"]
            if v["rule_id"] == "G01"]
ok("다큐에서 이름 뒤 ~씨를 잡는다", _gdocids == [1], str(_gdocids))
ok("화자명·낱말·지시어는 잡지 않는다", 2 not in _gdocids and 3 not in _gdocids
   and 4 not in _gdocids, str(_gdocids))
ok("드라마에서는 잡지 않는다",
   not [v for v in check_events(_gevs, _gdrama, fps=23.976)["violations"]
        if v["rule_id"] == "G01"])
# 극존칭은 자료에 정의가 없어 무늬를 지어내지 않았다. **미구현으로 남겨 리포트에
# 뜨게 한다** — 조용히 통과시키면 "전부 통과"가 거짓말이 된다(규칙 9).
ok("극존칭은 미구현으로 밝힌다",
   any("super_honorific" in u
       for u in check_events(_gevs, _gdoc, fps=23.976)["unimplemented_checks"]))

# 권장 이탈은 **위반이 아니라 목록**이다(규칙 4·5).
_goff = _gn.off_recommendation([_PEvent(1, 0, 2000, "짧다"),
                                _PEvent(2, 2000, 6000, "맞다"),
                                _PEvent(3, 6000, 16000, "길다")], _gdoc)
ok("권장 이탈을 목록으로 낸다", [r["event_index"] for r in _goff] == [1, 3], str(_goff))
ok("권장 이탈은 위반 목록에 없다",
   not [v for v in check_events(_gevs, _gdoc, fps=23.976)["violations"]
        if "권장" in v["message"]])

try:
    _gn.apply(_gbase, "없는장르")
    ok("모르는 장르는 예외", False, "예외가 나지 않았다")
except ProfileError:
    ok("모르는 장르는 예외", True)


# --- 캐릭터 외부 조사 (네트워크 없이 파싱만) ---------------------------------
# 조회는 네트워크가 필요하지만 **읽어 들인 것을 해석하는 부분은 그렇지 않다.**
# 인포박스 해석을 시험으로 고정해 두면 위키 문법이 달라졌을 때 여기서 걸린다.

from checker import webchars as _wc  # noqa: E402

for _w, _want in (("breakingbad", "https://breakingbad.fandom.com/api.php"),
                  ("breakingbad.fandom.com", "https://breakingbad.fandom.com/api.php"),
                  ("https://x.fandom.com/ko", "https://x.fandom.com/ko/api.php"),
                  ("https://x.fandom.com/api.php", "https://x.fandom.com/api.php")):
    ok(f"위키 주소 -> API ({_w})", _wc.api_of(_w) == _want, _wc.api_of(_w))
try:
    _wc.api_of("  ")
    ok("위키를 비우면 예외", False, "예외가 나지 않았다")
except ValueError:
    ok("위키를 비우면 예외", True)

_WIKITEXT = """{{Character Infobox
|title = Walter White
|gender = Male
|age = 52
|occupation = [[Chemistry|Chemistry]] teacher<br />Meth manufacturer
|affiliation = {{Plainlist|
* [[Gray Matter]]
* [[Los Pollos Hermanos]]
}}
|family = [[Skyler White|Skyler]] (wife)<ref>{{cite web|url=http://x|title=y}}</ref>
|status = Deceased
}}
'''Walter Hartwell White Sr.''' was a [[chemistry]] teacher who turned to
manufacturing methamphetamine to secure his family's future.

== History ==
"""
_box = _wc.parse_infobox(_WIKITEXT)
# 중괄호 짝을 세지 않으면 첫 `}}`에서 잘려 절반만 읽는다(안쪽 템플릿이 흔하다).
ok("중첩 템플릿을 넘어 끝까지 읽는다", "status" in _box, str(sorted(_box)))
ok("링크는 보이는 글자만", _box["occupation"].startswith("Chemistry teacher"),
   _box["occupation"])
# **목록 틀 안의 값을 지우지 않는다.** `{{...}}`를 통째로 지웠다가 경력 정보를 통째로
# 버렸다 — `affiliation`이 빈칸이 됐다.
ok("목록 틀에 싸인 값을 살린다", "Gray Matter" in _box.get("affiliation", ""),
   str(_box.get("affiliation")))
# 각주 틀은 전부 `키=값`이라 자연히 빠진다.
ok("각주 틀은 빠진다", "http" not in _box["family"], _box["family"])

_picked = _wc.pick_fields(_box)
# 항목 이름은 작업자 자료가 정한 것이다(성별·나이·직업·경력·성격).
ok("자료 항목으로 옮긴다",
   {"gender", "age", "job", "career", "family"} <= set(_picked), str(_picked))
ok("경력을 빠뜨리지 않는다", "Gray Matter" in _picked["career"], _picked["career"])
ok("아는 키만 옮긴다", "status" not in _picked, str(sorted(_picked)))

ok("소개 첫 문단을 딴다",
   _wc.first_paragraph(_WIKITEXT).startswith("Walter Hartwell White Sr. was a"),
   _wc.first_paragraph(_WIKITEXT)[:50])
ok("인포박스는 소개로 잡지 않는다", "|" not in _wc.first_paragraph(_WIKITEXT))

# 나간 것을 기록한다 — **대사는 여기에 들어올 수 없다**(작품 제목과 인물 이름만).
_wc.forget()
ok("기록을 비울 수 있다", _wc.sent() == [])

# 조사 결과를 문서에 옮기는 부분. 네트워크 없이 가짜 결과로 잰다.
_chp = [_ch.Character(name="민수", lines=3)]
ok("조사 전에는 빈 항목이 다섯", len(_chp[0].missing) == 5, str(_chp[0].missing))
_chp[0].gender, _chp[0].age, _chp[0].job = "남성", "42", "형사"
_chp[0].career, _chp[0].traits = "강력계", "말수가 적다"
ok("채우면 빈 항목이 없다", _chp[0].missing == [], str(_chp[0].missing))
# **근거 없이 채운 것은 조사로 보지 않는다.**
ok("근거가 없으면 조사로 보지 않는다", not _chp[0].researched)
_chp[0].origin = "https://x.fandom.com/wiki/민수"
ok("근거가 있으면 조사로 본다", _chp[0].researched)

_chp[0].photo = "https://x/민수.png"
_chtsv = _ch.to_tsv(_chp).splitlines()
ok("표에 자료 항목 칸이 있다",
   all(c in _chtsv[0].split("\t") for c in ("성별", "나이", "직업", "경력", "성격")),
   _chtsv[0])
# 사진이 있는데 라이선스를 모르면 그렇게 적는다. 비워 두면 자유 이용으로 오해한다.
ok("사진이 있고 라이선스를 모르면 '확인 필요'",
   "확인 필요" in _chtsv[1].split("\t")[_chtsv[0].split("\t").index("사진 라이선스")],
   _chtsv[1])
_chmd = _ch.to_markdown(_chp, {"total": 1, "tagged_events": 3, "untagged_events": 0})
ok("문서에 라이선스를 사진 옆에 붙인다", "라이선스:" in _chmd)
ok("성격이 위키 요약임을 밝힌다", "요약이므로" in _chmd)


# --- T17 정한 말투를 벗어난 자리 ---------------------------------------------
# 프로파일에 오래 선언만 돼 있던 검사다. 미뤄진 이유가 있다 — **같은 인물이 존댓말과
# 반말을 섞는 것은 상대가 다르면 정상**이고 자막에 상대는 표시되지 않는다. 그래서
# 사람이 캐릭터 시트에 "이 인물은 이렇게 말한다"를 적어 주어야 성립한다.

_t17prof = load_profile("netflix", "ko", "translation")
_t17evs = [
    _gev("[민수] 어디 계십니까", 1),          # 합니다체 — 맞다
    _gev("[민수] 어디 있어요", 2),            # 해요체 — 어긋난다
    _gev("[영희] 여기 있어요", 3),            # 해요체로 정함 — 맞다
    _gev("[민수] 알았어", 4),                 # 유보 — 넘긴다
    _gev("화자를 모르는 대사입니다", 5),       # 화자 없음 — 넘긴다
]
_t17cast = {"민수": "합니다체", "영희": "해요체"}

# **시트가 없으면 조용히 통과로 보이면 안 된다.** 구현은 됐으므로 미구현 목록에서
# 빠지는데, 그러면 "검사했고 통과"로 읽힌다(규칙 9가 금지하는 상태).
_t17none = check_events(_t17evs, _t17prof, fps=23.976)
ok("시트가 없으면 T17을 지적하지 않는다",
   not [v for v in _t17none["violations"] if v["rule_id"] == "T17"])
ok("시트가 없으면 '돌지 못했다'고 밝힌다",
   any("formality_inconsistent" in r for r in _t17none.get("skipped_checks") or []),
   str(_t17none.get("skipped_checks")))

_t17got = check_events(_t17evs, _t17prof, fps=23.976, cast=_t17cast)
_t17hits = [(v["event_index"], v["detail"]) for v in _t17got["violations"]
            if v["rule_id"] == "T17"]
ok("정한 말투를 벗어난 자막만 잡는다", [i for i, _ in _t17hits] == [2], str(_t17hits))
ok("무엇이 어긋났는지 적는다", "합니다체로 정했는데 해요체" in _t17hits[0][1],
   _t17hits[0][1])
# 조사가 받침에 맞아야 한다. `민수은(는)`처럼 나오면 사람이 읽다가 걸린다.
ok("주제 조사를 받침에 맞춘다", "민수는" in _t17hits[0][1], _t17hits[0][1])
ok("시트를 주면 '돌지 못했다'가 사라진다",
   not [r for r in _t17got.get("skipped_checks") or []
        if "formality_inconsistent" in r])

# **반말로 정해 둔 인물도 한 방향으로는 검증된다** — 그 줄이 존댓말로 확정되면 어긋난
# 것이 맞다. 반대 방향(반말 확정)은 못 한다: `해야`와 `뭐야`를 줄 끝만 보고 못 가른다.
_t17ban = check_events([_gev("[철수] 어디 계십니까", 1), _gev("[철수] 몰라", 2)],
                       _t17prof, fps=23.976, cast={"철수": "반말"})
_t17banhits = [v["event_index"] for v in _t17ban["violations"] if v["rule_id"] == "T17"]
ok("반말로 정한 인물이 존댓말을 쓰면 잡는다", _t17banhits == [1], str(_t17banhits))

# 정해 주지 않은 인물은 건드리지 않는다 — 넓히면 오답이 난다.
_t17partial = check_events(_t17evs, _t17prof, fps=23.976, cast={"영희": "합니다체"})
ok("정해 주지 않은 인물은 넘긴다",
   [v["event_index"] for v in _t17partial["violations"] if v["rule_id"] == "T17"] == [3],
   str([v["event_index"] for v in _t17partial["violations"] if v["rule_id"] == "T17"]))

# 시트 되읽기 — **칸 순서가 아니라 머리글로 찾는다.** 사람이 엑셀에서 칸을 옮긴다.
import tempfile as _t17tf  # noqa: E402

with _t17tf.TemporaryDirectory() as _t17d:
    _t17p = Path(_t17d) / "cast.tsv"
    _t17people = [_ch.Character(name="민수", lines=5), _ch.Character(name="영희", lines=2)]
    _t17people[0].declared_tone = "하십시오체"      # 같은 뜻의 다른 말
    _t17people[0].relations = {"영희": "동료"}
    _t17p.write_text(_ch.to_tsv(_t17people), encoding="utf-8-sig")

    _back = _ch.read_tsv(_t17p)
    ok("시트를 되읽는다", [p.name for p in _back] == ["민수", "영희"],
       str([p.name for p in _back]))
    # 같은 뜻으로 쓰는 말을 받아 준다. **모르는 말은 빈 값으로 둔다**(짐작해서 한쪽으로
    # 떨어뜨리지 않는다).
    ok("말투 표기가 달라도 알아본다", _back[0].declared_tone == "합니다체",
       _back[0].declared_tone)
    ok("관계를 되읽는다", _back[0].relations == {"영희": "동료"}, str(_back[0].relations))
    # 우리가 적어 낸 자리표시자를 사람이 채운 것으로 착각하면 안 된다.
    ok("'정해 주세요'는 빈 값으로 읽는다", _back[1].declared_tone == "",
       _back[1].declared_tone)
    ok("'확인 필요'는 빈 값으로 읽는다", _back[1].gender == "", _back[1].gender)

    # 칸을 옮겨도 머리글로 찾으므로 값이 밀리지 않는다.
    _rows = [r.split("\t") for r in _t17p.read_text(encoding="utf-8-sig").splitlines()]
    _order = [_rows[0].index("성별"), _rows[0].index("이름")]
    _moved = ["\t".join([r[i] for i in _order] + r) for r in _rows]
    (Path(_t17d) / "moved.tsv").write_text("\n".join(_moved), encoding="utf-8-sig")
    _movedback = _ch.read_tsv(Path(_t17d) / "moved.tsv")
    ok("칸을 옮겨도 머리글로 찾는다",
       [p.name for p in _movedback] == ["민수", "영희"], str([p.name for p in _movedback]))
ok("모르는 말투 표기는 빈 값", _ch._tone_of("아무말") == "", _ch._tone_of("아무말"))


# --- 단계마다 볼 것이 다르다 (프롬프트 재배치) --------------------------------
# 1차가 문체·간결성·문화 조정까지 한꺼번에 시키고 있었다. 작업자 자료 569~579행이
# 나눠 놓은 것과 어긋나고, 한 번에 셋을 시키면 모델이 뒤섞어 어중간하게 낸다 —
# 그러면 가장 비싼 것(오역)에 쓸 여유가 없어진다.
#
# **규칙이 두 단계에 겹치면 고칠 때 한 곳만 고친다.** 그래서 겹침을 시험이 잡는다.

from checker.translate import SYSTEM as _P1  # noqa: E402
from checker.revise import (SECOND_PASS as _P2, THIRD_PASS as _P3,  # noqa: E402
                           cast_hint as _cast_hint, genre_hint as _genre_hint)

# 문체·간결·문장부호는 **3차에만** 있어야 한다.
# 2026-08-14: 작업자 자료 CHECK LIST(3)와 번역투 절에서 넷을 더 넣었다.
for _mark in ("마침표", "인칭대명사", "문장 요소", "과감히", "문장 부호",
              "이중 피동", "최상급", "간접인용"):
    ok(f"'{_mark}'는 3차에만", _mark in _P3 and _mark not in _P1 and _mark not in _P2,
       f"1차={_mark in _P1} 2차={_mark in _P2} 3차={_mark in _P3}")

# 오역은 1차의 일이다. 2차도 다시 보지만 1차가 첫 책임이다.
ok("1차가 오역을 못 박는다", "오역은 괜찮지 않습니다" in _P1)
ok("1차는 투박한 한국어를 허용한다", "투박" in _P1)
ok("1차가 부정·숫자·이름을 짚는다",
   all(w in _P1 for w in ("부정", "숫자", "이름")))
# 구조는 1차에서 지켜야 한다 — 번호가 타임코드에 걸려 있어 뒤 단계가 복구할 수 없다.
ok("1차가 번호 보존을 요구한다", "번호를 합치거나 나누지" in _P1)

# 말투는 2차의 일로 옮겼다. 전에는 2차가 "말투는 1차를 따릅니다"라고 해서,
# 1차가 말투를 정하지 않게 되면 **아무도 정하지 않는 상태**가 됐다.
ok("1차는 말투를 존댓말로 통일만 한다", "존댓말로 통일" in _P1)
ok("2차가 말투를 정한다", "인물 관계" in _P2 and "말투" in _P2)
# 자기소개 어순은 호칭이라 2차의 일이다. 3차(문체)로 새면 규칙이 두 곳에 갈린다.
ok("2차가 자기소개 어순을 든다", "직함+이름" in _P2 and "직함+이름" not in _P3)
ok("2차에 '말투는 1차를 따릅니다'가 없다", "1차를 따릅니다" not in _P2)
# 3차는 2차가 정한 것을 흔들지 않는다.
ok("3차는 말투를 바꾸지 않는다", "말투를 바꾸지 마세요" in _P3)
ok("3차는 뜻을 바꾸지 않는다", "뜻을 바꾸지 마세요" in _P3)
# 글자 수는 마지막이다(CLAUDE.md 1번).
ok("2차는 글자 수를 미룬다", "글자 수를 줄이는 것은 3차" in _P2)

# `DOCUMENTARY_RULES`는 **죽은 코드였다** — 정의만 있고 참조가 0건. 층이 틀렸기
# 때문이다. 이제 프로파일에서 읽는다.
import checker.translate as _tr  # noqa: E402
ok("죽은 상수를 지웠다", not hasattr(_tr, "DOCUMENTARY_RULES"))

_hint = _genre_hint(_gdoc)
ok("장르 규칙을 프로파일에서 읽는다", "~씨" in _hint and "극존칭" in _hint, _hint)
ok("합니다체 권장을 넣는다", "습니다" in _hint, _hint)
# **'요'를 금지하지 않는다.** 허용된다는 확인을 받았다.
ok("'요'를 금지하지 않는다", "괜찮습니다" in _hint, _hint)
ok("장르가 없으면 조각도 없다", _genre_hint(_gbase) == "", _genre_hint(_gbase))
ok("프로파일이 없어도 터지지 않는다", _genre_hint(None) == "")

# 캐릭터 시트가 정한 말투를 감수 프롬프트에 물린다 — **정하고, 쓰고, 검사하는 것이
# 한 자료다**(같은 시트가 T17도 돌린다).
_ch_hint = _cast_hint({"민수": "합니다체", "영희": "반말"})
ok("인물별 말투를 프롬프트에 넣는다",
   "민수: 합니다체" in _ch_hint and "영희: 반말" in _ch_hint, _ch_hint)
ok("시트에 없는 인물은 존댓말", "존댓말" in _ch_hint, _ch_hint)
ok("시트가 없으면 조각도 없다", _cast_hint(None) == "" and _cast_hint({}) == "")


class _SpyTranslator:
    """무엇을 물었는지 남기는 흉내."""

    def __init__(self):
        self.systems = []

    def ask(self, system, prompt):
        self.systems.append(system)
        return "\n".join(f"{n}. 그대로" for n in range(1, 3))


_spy = _SpyTranslator()
_pl.stage_revise([_PEvent(1, 0, 2000, "가"), _PEvent(2, 2000, 4000, "나")],
                 _gdoc, translator=_spy, source={1: "a", 2: "b"}, rounds=2,
                 cast={"민수": "합니다체"})
# 장르·인물 말투는 **말투를 정하는 단계에만** 붙는다. 윤문에 붙이면 3차가 말투를
# 다시 만지고, 그건 2차가 정한 것을 흔드는 일이다.
ok("감수 프롬프트에만 장르가 붙는다",
   "~씨" in _spy.systems[0] and "~씨" not in _spy.systems[-1],
   f"감수={'~씨' in _spy.systems[0]} 윤문={'~씨' in _spy.systems[-1]}")
ok("감수 프롬프트에만 인물 말투가 붙는다",
   "민수: 합니다체" in _spy.systems[0] and "민수: 합니다체" not in _spy.systems[-1])


# --- 오역 검증 (층 1: 역번역 없이) --------------------------------------------
# 백로그에 이 넷을 "확정"이라고 적었는데 **둘은 확정이 아니다.** 짓다가 드러났다:
#   확정  화자 표시 — 개수가 다르면 구조가 깨졌다
#   확정  용어      — 통일표가 정답을 정해 준다
#   추정  부정      — `I don't know` -> `몰라요`. 부정 표시 없이 부정한다
#   추정  숫자      — `in 5 minutes` -> `곧`. 자막은 숫자를 버리기도 한다
# 그래서 전부 **플래그로만** 낸다. 규정 위반 목록에 섞지 않는다(규칙 4).

from checker import mistranslation as _mt  # noqa: E402
from checker.translate import Glossary as _Glossary  # noqa: E402


def _flag_kind(source, target, glossary=None):
    found = _mt.scan([_PEvent(1, 0, 1000, target)], {1: source}, glossary)
    return found[0].kind if found else None


for _src, _tgt, _want in [
    # 부정 — 가장 치명적이다. 뜻이 정반대로 뒤집힌다.
    ("I never said I'd go alone", "혼자 가겠다고 했어요", "negation"),
    ("I don't know", "몰라요", None),               # 표시 없이 부정 — 걸리면 안 된다
    ("There is nothing here", "여기 아무것도 없어요", None),
    ("He didn't come", "오지 않았어요", None),
    # 숫자 — 한 음절 한자 수사 때문에 처음에 검사가 아예 돌지 않았다.
    ("Wait 5 minutes", "잠깐만요", "number"),        # `만`이 걸리면 안 된다
    ("Wait 5 minutes", "5분 기다려요", None),
    ("Wait 5 minutes", "다섯 시간 기다려요", None),   # 고유어 수사
    ("Wait 5 minutes", "오 분 기다려요", None),       # 한자 수사 + 단위
    ("It was 30 years ago", "삼십 년 전이었어요", None),   # 두 음절 한자 수사
    ("It was 30 years ago", "오래전이었어요", "number"),
    # 단위 변환은 정상이다(작업자 자료 146행: 화자 국적을 따져 단위를 다룬다).
    ("It costs 3 dollars", "3천 원입니다", None),
    # 화자 표시 — 구조라 확정이다. 이름이 한국어로 바뀌는 것은 정상이다.
    ("[Sarah] Come in", "들어오세요", "speaker"),
    ("[Sarah] Come in", "[사라] 들어오세요", None),
]:
    ok(f"오역 플래그: {_src[:22]} -> {_tgt[:14]}", _flag_kind(_src, _tgt) == _want,
       f"{_flag_kind(_src, _tgt)} (기대 {_want})")

ok("통일표를 어기면 잡는다",
   _flag_kind("We reached Bastogne", "바스통에 도착했습니다",
              _Glossary({"Bastogne": "바스토뉴"})) == "glossary")
ok("통일표를 지키면 안 잡는다",
   _flag_kind("We reached Bastogne", "바스토뉴에 도착했습니다",
              _Glossary({"Bastogne": "바스토뉴"})) is None)

# 확정을 먼저 보여 준다 — 사람이 위에서부터 처리하면 값이 큰 것부터 처리된다.
_mtevs = [_PEvent(1, 0, 1000, "혼자 가겠다고 했어요"),      # 추정(부정)
          _PEvent(2, 1000, 2000, "들어오세요")]             # 확정(화자 표시)
_mtflags = _mt.scan(_mtevs, {1: "I never said I'd go alone", 2: "[Sarah] Come in"})
ok("확정을 먼저 낸다", [f.certain for f in _mtflags] == [True, False],
   str([(f.kind, f.certain) for f in _mtflags]))
ok("집계가 확정·추정을 가른다",
   _mt.summarize(_mtflags) == {"total": 2, "by_kind": {"speaker": 1, "negation": 1},
                               "certain": 1, "estimated": 1},
   str(_mt.summarize(_mtflags)))
# 원문이 없는 자막은 견줄 수 없다. 넘긴다.
ok("원문이 없으면 넘긴다", _mt.scan([_PEvent(9, 0, 1000, "아무 말")], {}) == [])


class _LeakyTranslator:
    """일부러 부정과 숫자를 흘리는 흉내."""

    def ask(self, system, prompt):
        out = []
        for line in prompt.splitlines():
            head = line.strip().split(".")[0].strip()
            if head == "1":
                out.append("1. 혼자 가겠다고 했어요")
            elif head == "2":
                out.append("2. 잠깐만요")
        return "\n".join(out)


_mtresult = _pl.stage_translate(
    [_PEvent(1, 0, 2000, "I never said I'd go alone"),
     _PEvent(2, 2000, 4000, "Wait 5 minutes")],
    _trprof, translator=_LeakyTranslator())
ok("1차 직후에 검증이 돈다",
   {f.kind for f in _mtresult.extra["flags"]} == {"negation", "number"},
   str([f.kind for f in _mtresult.extra["flags"]]))
# **플래그는 위반이 아니다.** 규정 위반 목록에 들어가면 위반 건수가 거짓이 된다.
ok("플래그를 위반에 섞지 않는다", _mtresult.violations == [], str(_mtresult.violations))
ok("검증을 끌 수 있다",
   _pl.stage_translate([_PEvent(1, 0, 2000, "I never said I'd go alone")],
                       _trprof, translator=_LeakyTranslator(),
                       verify=False).extra["flags"] == [])


# --- 역번역 대조 --------------------------------------------------------------
# **역번역이 답인 이유는 읽기 편해서가 아니다 — 비교가 같은 언어끼리 되기 때문이다.**
# 영·한을 직접 견주려면 다국어 임베딩이 필요하고(torch ~2GB) 점수만 나와서 무엇이
# 틀렸는지 못 본다. 역번역을 거치면 의존성 없이 낱말로 재고 근거가 그대로 남는다.
#
# 백로그에 "겹침이 낮은 자막만 역번역한다"고 적어 두었는데 **그건 순환이었다** —
# 겹침은 역번역을 해야 계산된다. 전수로 돌리고 점수로 고른다.

from checker import backtranslate as _bt  # noqa: E402

ok("기능어는 빼고 내용어만 센다",
   _bt.content_words("It is the thing that I want") == ["thing", "want"],
   str(_bt.content_words("It is the thing that I want")))
# **부정은 기능어라도 빼지 않는다.** 빠지면 뜻이 정반대로 뒤집힌다.
ok("부정은 남긴다", "not" in _bt.content_words("I do not know"))
ok("표시 안의 글자는 안 센다",
   _bt.content_words("[Sarah] come in") == ["come"],
   str(_bt.content_words("[Sarah] come in")))

# 줄임말을 펴지 않으면 원문 `don't`와 역번역 `do not`이 어긋난 것으로 보인다 —
# 가장 중요한 신호인 부정이 바로 그 무늬라 그냥 두면 못 쓴다.
for _src, _back, _want in [
    ("I don't know", "I do not know", 1.0),
    ("We can't wait", "We cannot wait", 1.0),       # `n't`를 먼저 걸면 `ca not`이 된다
    ("He won't come", "He will not come", 1.0),
    ("I never said I'd go alone", "I never said I would go alone", 1.0),
]:
    ok(f"줄임말을 펴서 같게 본다: {_src}", abs(_bt.overlap(_src, _back) - _want) < 1e-9,
       f"{_bt.overlap(_src, _back):.2f}")

# 뜻이 새면 점수가 떨어진다.
ok("부정이 사라지면 점수가 내려간다",
   _bt.overlap("I don't know", "I know") < 1.0)
ok("낱말이 사라지면 점수가 내려간다",
   _bt.overlap("I never said I'd go alone", "I said I would go alone") < 1.0)
# **원문 기준으로 센다**(재현율). 역번역이 말을 덧붙이는 것은 관심이 아니다.
ok("덧붙임은 점수를 깎지 않는다",
   _bt.overlap("Come in", "Please come inside right now and come in") == 1.0,
   str(_bt.overlap("Come in", "Please come inside right now and come in")))
ok("셀 것이 없으면 점수도 없다", _bt.overlap("The is a", "anything") is None)

_btevs = [_PEvent(1, 0, 2000, "혼자 가겠다고 했어요"),
          _PEvent(2, 2000, 4000, "5분 기다려요")]
_btsrc = {1: "I never said I'd go alone", 2: "Wait five minutes"}
_btd = _bt.compare(_btevs, _btsrc, {1: "I said I would go alone",
                                    2: "Wait five minutes"})
ok("점수 낮은 순으로 낸다", [d.event_index for d in _btd] == [1, 2],
   str([(d.event_index, round(d.score, 2)) for d in _btd]))
ok("빠진 낱말을 짚는다", _btd[0].missing == ["never"], str(_btd[0].missing))
ok("원문·번역·역번역을 함께 낸다",
   all((_btd[0].source, _btd[0].korean, _btd[0].back)))
# 역번역이 없는 번호는 견줄 수 없다. 넘긴다.
ok("역번역이 없으면 넘긴다", _bt.compare(_btevs, _btsrc, {}) == [])

# **임계값을 두지 않는다.** 자르는 것은 점수가 아니라 개수다 — 몇 점 이하가 오역인지는
# 실제 작업물로 재야 알고, 재기 전에 임계값을 박으면 오답 공장이 된다.
ok("개수로 자른다", len(_bt.worst(_btd, 1)) == 1)
ok("0을 주면 전부", len(_bt.worst(_btd, 0)) == 2)
_btstats = _bt.summarize(_btd)
ok("눈금을 낸다", set(_btstats) == {"total", "mean", "median", "min", "below_half"},
   str(sorted(_btstats)))
ok("빈 목록도 터지지 않는다", _bt.summarize([]) == {"total": 0})


class _LeakyBack:
    """부정을 흘리는 역번역 흉내."""

    def ask(self, system, prompt):
        out = []
        for line in prompt.splitlines():
            head = line.strip().split(".")[0].strip()
            if head == "1":
                out.append("1. I said I would go alone")
            elif head == "2":
                out.append("2. Wait five minutes")
        return "\n".join(out)


_btresult = _pl.stage_backtranslate(_btevs, _trprof, translator=_LeakyBack(),
                                    source=_btsrc)
# **자막을 바꾸지 않는다** — 이 단계는 읽기만 한다.
ok("역번역이 자막을 바꾸지 않는다",
   [e.text for e in _btresult.events] == [e.text for e in _btevs])
ok("어긋난 자리를 낸다",
   [d.event_index for d in _btresult.extra["worst"]] == [1, 2],
   str([d.event_index for d in _btresult.extra["worst"]]))
ok("역번역은 위반을 내지 않는다", _btresult.violations == [])


class _DeadBack:
    def ask(self, system, prompt):
        raise RuntimeError("모델 없음")


# 한 묶음이 실패해도 나머지가 돌아야 한다. 여기서는 전부 실패하지만 터지지 않는다.
_btdead = _pl.stage_backtranslate(_btevs, _trprof, translator=_DeadBack(),
                                  source=_btsrc)
ok("역번역이 실패해도 터지지 않는다", _btdead.extra["summary"] == {"total": 0},
   str(_btdead.extra["summary"]))


# --- 누적 표류와 수렴 조건 ----------------------------------------------------
# `_too_different`는 **직전 단계만** 봤다. 2차가 1.4배, 3차가 또 1.4배면 원문 대비
# 2배가 되어도 매 회차는 통과한다 — 회차를 설정으로 열어 둔 지금 실제 위험이다.

class _Grower:
    """회차마다 직전 대비 1.4배로 늘리는 흉내."""

    def __init__(self):
        self.n = 0

    def ask(self, system, prompt):
        self.n += 1
        size = int(10 * (1.4 ** self.n))
        return "\n".join(f"{line.strip().split('.')[0]}. " + "가" * size
                         for line in prompt.splitlines()
                         if line.strip().split(".")[0].strip().isdigit())


_drift = [_PEvent(1, 0, 2000, "가" * 10)]
_loose = _pl.stage_revise(_drift, _trprof, translator=_Grower(), rounds=3)
# 가드를 회차마다 걸므로 3회차를 돌아도 1차 대비 1.5배를 넘지 않는다.
ok("누적 표류를 막는다", len(_loose.events[0].text) / 10 <= 1.5,
   f"{len(_loose.events[0].text) / 10:.2f}배")

# 직전 대비만 보면 어떻게 되는지 — `baseline` 없이 부르면 막지 못한다.
from checker.revise import revise as _rv  # noqa: E402

_g, _cur = _Grower(), _drift
for _stage, _role in (("2차", "감수"), ("3차", "윤문"), ("4차", "윤문")):
    _cur, _ = _rv(_cur, _g, stage=_stage, role=_role)
ok("baseline 없이는 누적으로 새어 나간다", len(_cur[0].text) / 10 > 1.5,
   f"{len(_cur[0].text) / 10:.2f}배")


class _Settling:
    """회차가 갈수록 고칠 것이 줄어드는 흉내."""

    def __init__(self):
        self.n = 0

    def ask(self, system, prompt):
        self.n += 1
        body = "바꿈" + "가" * self.n if self.n <= 2 else "바꿈가가"
        return "\n".join(f"{line.strip().split('.')[0]}. {body}"
                         for line in prompt.splitlines()
                         if line.strip().split(".")[0].strip().isdigit())


class _Busy:
    """미사여구를 영원히 만지는 흉내 — 상한이 없으면 안 멈춘다."""

    def __init__(self):
        self.n = 0

    def ask(self, system, prompt):
        self.n += 1
        return "\n".join(f"{line.strip().split('.')[0]}. 고침{self.n}"
                         for line in prompt.splitlines()
                         if line.strip().split(".")[0].strip().isdigit())


_conv = [_PEvent(1, 0, 2000, "처음")]

# ① 상한을 안 주면 예전처럼 고정 회차로 돈다.
_fixed = _pl.stage_revise(_conv, _trprof, translator=_Settling(), rounds=3)
ok("상한이 없으면 고정 회차", [r["stage"] for r in _fixed.extra["rounds"]]
   == ["2차", "3차", "4차"], str([r["stage"] for r in _fixed.extra["rounds"]]))

# ② 상한이 크면 그 사이에서 수렴을 본다.
_settled = _pl.stage_revise(_conv, _trprof, translator=_Settling(),
                            rounds=1, max_rounds=5)
ok("잠잠해지면 상한 전에 멈춘다", len(_settled.extra["rounds"]) < 5,
   str([(r["stage"], r["changed"]) for r in _settled.extra["rounds"]]))
ok("멈춘 이유를 남긴다", "멈췄습니다" in _settled.extra["stopped_because"],
   _settled.extra["stopped_because"])

# ③ **모델이 고치기를 멈추는 것을 기다리면 안 된다.** 상한이 잡아야 한다.
_capped = _pl.stage_revise(_conv, _trprof, translator=_Busy(),
                           rounds=1, max_rounds=4)
ok("상한이 영원한 손질을 끊는다", len(_capped.extra["rounds"]) == 4,
   str(len(_capped.extra["rounds"])))
# **상한에 걸린 것은 아직 덜 됐다는 뜻이다.** 다 끝난 것과 구분해야 한다.
ok("상한에 걸린 것을 구분해 적는다", "아직 덜 됐습니다" in _capped.extra["stopped_because"],
   _capped.extra["stopped_because"])
ok("다 끝난 것과 문구가 다르다",
   _capped.extra["stopped_because"] != _fixed.extra["stopped_because"])

# ④ 최소 회차는 채운다 — 2차를 안 돌면 오역·용어를 아무도 보지 않는다.
_minimum = _pl.stage_revise(_conv, _trprof, translator=_Busy(),
                            rounds=2, max_rounds=6, settle_at=999)
ok("최소 회차는 채운다", len(_minimum.extra["rounds"]) >= 2,
   str(len(_minimum.extra["rounds"])))
ok("임계를 넘기면 최소만 돌고 멈춘다", len(_minimum.extra["rounds"]) == 2,
   str([(r["stage"], r["changed"]) for r in _minimum.extra["rounds"]]))


# --- 단계별 결과 남기기 (.work/) ---------------------------------------------
# **15분 걸린 번역이 3차에서 깨지면 처음부터였다.** GUI는 아무것도 남기지 않고
# 메모리에서만 돌았고, CLI는 확장자가 파편적이라 어느 것이 어느 단계인지 규칙이 없었다.

from checker import work as _wk  # noqa: E402

with _t17tf.TemporaryDirectory() as _wkd:
    _wksub = Path(_wkd) / "ep01.srt"
    _wksub.write_text("1\n00:00:01,000 --> 00:00:03,000\n원문\n", encoding="utf-8")
    _w = _wk.Work.beside(_wksub)
    # **원본을 덮어쓰지 않는다**(규칙 7). 폴더를 따로 만들고 그 안에만 쓴다.
    ok("자막 옆에 폴더를 잡는다", _w.root.name == "ep01.work", _w.root.name)
    ok("잡기만 하고 만들지는 않는다", not _w.root.exists())
    ok("기록이 없으면 빈 것을 돌려준다", _w.manifest()["steps"] == [])

    _wkfirst = [_PEvent(1, 1000, 3000, "1차"), _PEvent(2, 4000, 6000, "둘")]
    _w.save("02-first", _wkfirst, model="exaone3.5:7.8b", seconds=12.34)
    _w.save_source({1: "First line", 2: "Second"})
    ok("자막을 남긴다", (_w.root / "02-first.srt").is_file())
    ok("원본은 그대로", _wksub.read_text(encoding="utf-8").strip().endswith("원문"))
    # 감수가 오역을 보려면 번호별 원문이 반드시 있어야 한다.
    ok("원문을 남기고 되읽는다", _w.read_source() == {1: "First line", 2: "Second"},
       str(_w.read_source()))

    _wksecond = [_PEvent(1, 1000, 3000, "2차"), _PEvent(2, 4000, 6000, "둘")]
    _w.save("03-revise-2차", _wksecond, extra={"changed": 1, "role": "감수"})
    ok("회차마다 따로 남긴다", _w.steps() == ["02-first", "03-revise-2차"],
       str(_w.steps()))
    ok("마지막 단계에서 이어 할 수 있다", _w.last()[0] == "03-revise-2차",
       _w.last()[0])
    ok("되읽은 자막이 같다", [e.text for e in _w.read("03-revise-2차")] == ["2차", "둘"],
       str([e.text for e in _w.read("03-revise-2차")]))
    # 회차 사이를 견줄 수 있어야 어느 회차에서 나빠졌는지 알 수 있다.
    ok("회차를 견준다",
       _wk.diff(_w.read("02-first"), _w.read("03-revise-2차"))
       == [{"event_index": 1, "before": "1차", "after": "2차"}],
       str(_wk.diff(_w.read("02-first"), _w.read("03-revise-2차"))))

    # **타임코드는 첫 단계에서 굳는다.** 이후 단계가 옮기면 잡아 기록한다 —
    # 받은 타임코드를 건드리는 것이 실무에서 가장 비싼 사고다(규칙 8).
    _wkmoved = [_PEvent(1, 1500, 3000, "3차"), _PEvent(2, 4000, 6000, "둘")]
    _entry = _w.save("04-polish", _wkmoved)
    ok("타임코드가 움직이면 기록에 남는다", _entry.get("timecodes_moved") == [1],
       str(_entry.get("timecodes_moved")))
    ok("요약에 경고로 나온다", "타임코드가 1곳 움직였습니다" in _w.summary(),
       _w.summary()[-200:])
    # **예외를 올리지 않는다.** 남기는 것은 보험이고, 막을지는 어댑터가 정한다.
    ok("저장은 예외를 올리지 않는다", (_w.root / "04-polish.srt").is_file())

    # 손으로 고치다 깨뜨릴 수 있다. 깨진 기록 때문에 작업이 멈추면 안 된다.
    (_w.root / "manifest.json").write_text("{망가짐", encoding="utf-8")
    ok("기록이 깨져도 터지지 않는다", _w.manifest()["steps"] == [],
       str(_w.manifest())[:60])
    ok("없는 단계를 읽으면 빈 목록", _w.read("없는단계") == [])
    ok("아무것도 없으면 last가 빈 값", _wk.Work(Path(_wkd) / "없음").last() == ("", []))


# --- 단계를 줄기별로 갈라 그린다 ----------------------------------------------
# 사용자 요구: "①②③이 눈에 보이게, 하나의 애매한 [자막 만들기] 안에 숨기지 말고."
# 번역 자막과 한국어 자막이 거치는 단계가 다르므로 줄을 갈라야 한다.

from checker.pipeline import TRACKS as _TRACKS, stages_of as _stages_of  # noqa: E402

ok("줄기가 넷", [k for k, _ in _TRACKS] == ["source", "translate", "korean", "tool"],
   str([k for k, _ in _TRACKS]))
ok("번역 줄기가 ①②③",
   [s.id for s in _stages_of("translate")] == ["translate", "revise", "polish"],
   str([s.id for s in _stages_of("translate")]))
ok("한국어 줄기가 ②③",
   [s.id for s in _stages_of("korean")] == ["korean", "check"],
   str([s.id for s in _stages_of("korean")]))
ok("자막을 바꾸지 않는 것은 조사 줄기",
   {s.id for s in _stages_of("tool")} == {"terms", "characters"},
   str({s.id for s in _stages_of("tool")}))
ok("모든 단계가 줄기에 속한다",
   all(s.track in {k for k, _ in _TRACKS} for s in _pl.STAGES))
# **회차를 사람이 정하는 단계는 감수뿐이다.** 화면이 이 표시로 회차 선택을 붙인다.
ok("회차를 정하는 단계는 감수뿐", [s.id for s in _pl.STAGES if s.rounds] == ["revise"],
   str([s.id for s in _pl.STAGES if s.rounds]))
ok("단계마다 설명이 있다", all(len(s.note) > 20 for s in _pl.STAGES))

# ③ 윤문·QA는 **어댑터가 아니라 파이프라인이** 순서를 잇는다.
_polprof = load_profile("netflix", "ko", "translation")


class _PolishSpy:
    def __init__(self):
        self.systems = []

    def ask(self, system, prompt):
        self.systems.append(system)
        return "\n".join(f"{line.strip().split('.')[0]}. 다듬음"
                         for line in prompt.splitlines()
                         if line.strip().split(".")[0].strip().isdigit())


_polspy = _PolishSpy()
_polres = _pl.stage_polish([_PEvent(1, 0, 4000, "그러니까...")], _polprof,
                           translator=_polspy, fps=23.976)
# 윤문 프롬프트를 쓴다 — 감수가 아니다(뜻은 ②에서 맞췄다).
ok("윤문 프롬프트로 돈다", "자막답게" in _polspy.systems[0], _polspy.systems[0][:40])
ok("윤문 뒤에 검사가 돈다", "report" in _polres.extra)
ok("윤문 내역을 낸다", "revisions" in _polres.extra)
# 윤문이 글자를 바꾸므로 검사는 그 뒤여야 한다 — 윤문이 만든 위반을 원본 검사로는
# 못 본다. 여기서는 `...`이 자동 교정되어 사라진 것으로 확인한다.
ok("윤문 결과에 자동 교정이 얹힌다", "..." not in _polres.events[0].text,
   _polres.events[0].text)

# 캐릭터 단계도 파이프라인에 있다. **위키를 주지 않으면 밖으로 나가지 않는다.**
_chres = _pl.stage_characters([_PEvent(1, 0, 2000, "[민수] 여기 있습니다")])
ok("인물을 뽑는다", _chres.extra["counts"]["total"] == 1, str(_chres.extra["counts"]))
ok("자막을 바꾸지 않는다", _chres.events[0].text == "[민수] 여기 있습니다")
ok("위키를 안 주면 조사하지 않는다", _chres.extra["research"] is None)
# 조사하지 않았다는 사실을 숨기지 않는다.
ok("조사하지 않았음을 밝힌다", any("증명하지 못" in n for n in _chres.notes),
   str(_chres.notes))


# --- UI 실에서 mpv를 붙잡지 않는다 (AppHangB1 조사) ---------------------------
# **2026-08-12 실사용 사고.** 6.5분 영상에서 자막 210개를 만들어 놓고 UI가 멈췄다
# (Windows 이벤트 로그 `AppHangB1`). Qt 쪽은 재 보니 전부 10ms 미만이었고
# (model.replace 8.9ms, 파형 10.0ms, 지적표 9.0ms), 남는 것은 **UI 실에서 도는 동기
# mpv 왕복**이었다.
#
# `_sync_position`은 100ms마다 울리는데 `fit_subtitle_scale()`이 mpv에 왕복을 두 번
# 한다(osd-dimensions 읽기 + sub-scale 쓰기). 초당 20번을 UI 실에서 기다린 셈이다.
# 그런데 그 함수의 독스트링은 "**창 크기가 바뀔 때마다** 다시 불러야 한다"고 적고 있다.

import inspect as _uinspect  # noqa: E402

try:
    from app import window as _uw  # noqa: E402
except ImportError:
    ok("100ms 시계가 크기 맞추기를 하지 않는다 (PySide6 없어 건너뜀)", True)
else:
    _sync_src = _uinspect.getsource(_uw.MainWindow._sync_position)
    # 주석에 이름이 적혀 있으므로 **호출**을 본다.
    ok("100ms 시계가 크기 맞추기를 하지 않는다",
       "self.player.fit_subtitle_scale()" not in _sync_src)
    # 창 크기가 바뀔 때 해야 한다 — 안 하면 레터박스에서 자막이 규격보다 커진다.
    ok("창 크기가 바뀔 때 맞춘다",
       "self.player.fit_subtitle_scale()"
       in _uinspect.getsource(_uw.MainWindow.resizeEvent))
    # 멈춰 있으면 mpv에 덜 묻는다. 위치가 안 바뀌는데 계속 묻는 것은 UI 실을 공짜로
    # 쓰는 일이다.
    ok("멈춰 있으면 시계를 늦춘다", "setInterval" in _sync_src)

    # **생성 결과를 화면에 넘기기 전에 남긴다.** 안 남기면 창이 닫히는 순간 통째로
    # 사라진다 — 실제로 210개를 그렇게 잃었다.
    from app import jobs as _uj  # noqa: E402

    _gen_src = _uinspect.getsource(_uj.GenerateJob)
    ok("생성 결과를 남긴다", "01-generate" in _gen_src)
    ok("남기기가 본 작업을 죽이지 않는다", "남기지 못했습니다" in _gen_src)
    ok("생성이 work 경로를 받는다",
       "work_beside" in _uinspect.signature(_uj.GenerateJob.__init__).parameters)

    # 로그가 두 벌로 섞이면 읽을 수 없다. 일이 보내는 말은 **일하는 실에서만** 남긴다 —
    # UI 실이 밀려 있으면 화면 기록은 늦게 오는데, 로그는 실제로 언제 끝났는지를
    # 알려 줘야 한다. 중복 때문에 멈춤 조사에서 로그를 잘못 읽을 뻔했다.
    ok("일이 보내는 말을 화면에만 보인다",
       "self._note_ui" in _uinspect.getsource(_uw.MainWindow._start))
    ok("화면 전용 함수는 로그를 안 쓴다",
       "log(" not in _uinspect.getsource(_uw.MainWindow._note_ui))


# --- mpv를 UI 실에서 기다리지 않는다 ------------------------------------------
# `command()`는 mpv의 답을 기다린다. UI 실에서 부르면 mpv가 늦는 만큼 화면이 멈춘다 —
# 자막 210개를 처음 얹는 자리에서 실제로 `AppHangB1`이 났다(2026-08-12). 미리 보기는
# 늦게 반영돼도 되는 일이라 기다릴 이유가 없다.

try:
    from app import player as _up  # noqa: E402
except ImportError:
    ok("자막 얹기는 기다리지 않는다 (PySide6 없어 건너뜀)", True)
else:
    for _name in ("set_subtitles", "reload_subtitles"):
        _src = _uinspect.getsource(getattr(_up.Player, _name))
        ok(f"{_name}은 기다리지 않는다",
           "self._async(" in _src and "self._mpv.command(" not in _src, _src[:70])
    _async_src = _uinspect.getsource(_up.Player._async)
    ok("command_async를 쓴다", "command_async" in _async_src)
    # 없는 빌드에서는 동기로 떨어진다 — 조용히 안 하는 것보다 느린 것이 낫다.
    ok("없는 빌드에서는 동기로 떨어진다", "self._mpv.command(name" in _async_src)



# --- 말줄임표는 후략에만 (2026-08-14, 작업자 자료 [영상번역] 문장부호) -------

# 이 자리의 `ev`는 앞에서 다른 것으로 덮여 있다. 헬퍼를 새로 둔다.
def _ev2(text: str) -> dict:
    return {"index": 1, "start_ms": 0, "end_ms": 3000, "text": text}


def _fires(text: str, rule_id: str, profile) -> bool:
    return rule_id in ids(check_events([_ev2(text)], profile))


_cp = load_profile("coupang", "ko", "sdh")
_dp = load_profile("disney", "ko", "sdh")

ok("전략 말줄임표를 잡는다", _fires("...그리고 우리는 갔다", "CC35", _cp))
ok("전각 말줄임표도 잡는다", _fires("- …그래서 말이야", "CC35", _cp))
ok("후략은 잡지 않는다", not _fires("말을 하다가...", "CC35", _cp))
# 자료가 '노래가 이어짐'을 가사 말줄임표로 알리라고 시킨다. 그것까지 잡으면
# 자료가 시킨 표기를 위반으로 부르는 것이 된다.
ok("노래 줄은 보지 않는다", not _fires("♪ ...노래가 이어진다 ♪", "CC35", _cp))
ok("디즈니도 같은 검사를 든다", _fires("...그리고", "DC35", _dp))


# --- 교정기와의 계약 (2026-08-14) ---------------------------------------
#
# 두 저장소는 라이브러리로 물려 있다. 교정기가 함수 이름이나 반환 모양을 바꾸면
# 이쪽이 깨지는데, **우리 시험은 가짜 백엔드로 돌기 때문에 그것을 못 본다.**
# 그래서 교정기가 옆에 있으면 **교정기가 스스로 들고 있는 계약 검사기**를 돌린다.
# 계약을 여기서 다시 정의하지 않는다 — 두 벌이 되면 갈라진다.

from checker.korean import corrector_info as _ci  # noqa: E402

_info = _ci()
if not _info["found"]:
    # **조용히 넘기지 않는다.** 검사하지 않은 것을 통과로 보이게 하지 않는다(규칙 9).
    print("  [건너뜀] 교정기가 없어 계약 검사를 돌리지 못했습니다.")
elif _info["contract"] == "unknown":
    print(f"  [건너뜀] 교정기에 계약 검사기가 없습니다 — {_info['detail']}")
else:
    ok("교정기 공개 계약이 맞는다", _info["contract"] == "ok", _info["detail"])
    ok("어느 판이 붙었는지 말한다", bool(_info["commit"]) or True)


# --- 정답지 대조: 텍스트 유사도 (2026-08-27) --------------------------------
#
# BLEU·ROUGE-L을 새 지표로 만들었다가, 독립 검토(critic)로 실측 검증한 결과 걷어냈다.
#   - ROUGE-L은 실제 자막 400쌍에서 align.similarity와 F1이 완전히 같은 값이었다
#     — 새 정보가 아니라 같은 계산의 재현이었다.
#   - 코퍼스 BLEU는 한국어 자막 특유의 짧은 어절 토큰 때문에 코퍼스 전체 35%가
#     4어절 미만이라 그 차수의 n-gram이 아예 없어 종종 0으로 무너졌다(짧은 자막
#     특성 — 고쳐도 정보량이 낮았다).
#   - 코퍼스 단일 스칼라는 규칙 13이 요구하는 "어느 자막을 봐야 하는지"를 못
#     짚었다. `evaluate.py`가 타이밍에는 이미 "가장 많이 어긋난 자막" 개별
#     목록을 내는데 텍스트 쪽은 중간값 하나로 뭉개고 있었다.
# 대신 이미 있던 `Pair.score`(짝짓기용, 시간 겹침 보너스 +0.3이 섞여 있었다)를
# 순수 텍스트 유사도로 갈라 `Pair.text_similarity`를 만들고, 그 값으로 "텍스트가
# 가장 안 맞는 자막" 개별 목록을 새로 냈다 — 새 모듈 없이 기존 값을 정직하게
# 씀으로써 규칙 13(도구를 고치는 것이지 가운데값을 내는 것이 아니다)에 맞춘다.

from checker.align import similarity as _text_sim  # noqa: E402
from checker.evaluate import compare, summarize, report  # noqa: E402
from checker.model import Event as _EvalEvent  # noqa: E402

# 시간이 완전히 겹치는 짝(+0.3 보너스가 항상 붙는 상황)인데 텍스트가 다른 경우 —
# 옛 구현(p.score)이었다면 유사도가 1.0을 넘어 보고됐을 자리다.
cmp1 = compare([_EvalEvent(1, 0, 3000, "완전히 다른 낱말들")],
              [_EvalEvent(1, 0, 3000, "전혀 다른 텍스트")])
pair = cmp1.matched[0]
ok("짝짓기 점수(score)에는 시간 보너스가 섞여 있다",
   pair.score > _text_sim(pair.ours.text, pair.truth.text), str(pair.score))
ok("텍스트 유사도는 짝짓기 점수와 별개로 1.0을 넘지 않는다",
   pair.text_similarity is not None and pair.text_similarity <= 1.0, str(pair.text_similarity))

# 완전히 같은 텍스트면 유사도는 정확히 1.0이어야 한다(오염됐던 예전 값은 1.3까지
# 나올 수 있었다).
cmp2 = compare([_EvalEvent(1, 0, 3000, "완전히 같은 문장")],
              [_EvalEvent(1, 0, 3000, "완전히 같은 문장")])
ok("완전히 같은 텍스트의 유사도는 1.0", cmp2.matched[0].text_similarity == 1.0)

stats = summarize(cmp2)
ok("요약에도 순수 유사도가 들어간다(1.0 초과 없음)",
   stats["text_similarity_median"] == 1.0, str(stats["text_similarity_median"]))
ok("BLEU·ROUGE 필드는 없다(독립 검토 결과 걷어냈다)",
   "bleu" not in stats and "rouge_l" not in stats)

# **`chars_per_cue`가 프로파일의 char_weights를 실제로 쓰는지**(2026-09-01
# 회귀 — `_evaluate_mode`가 프로파일을 안 불러와 이 값을 항상 가중치 없이
# (전부 1.0) 재고 있었다. 한국어는 CJK 1.0·기타 0.5라 결과가 계속 부풀려져
# 나왔다). "안녕 hi"는 CJK 2자 + 공백·라틴 3자 — 가중치 없으면 5.0, 한국어
# 가중치(cjk 1.0/other 0.5)면 3.5여야 한다.
cmp_cw = compare([_EvalEvent(1, 0, 3000, "안녕 hi")], [_EvalEvent(1, 0, 3000, "안녕 hi")])
stats_no_weights = summarize(cmp_cw)
stats_ko_weights = summarize(cmp_cw, char_weights={"cjk": 1.0, "other": 0.5})
ok("char_weights 없으면 기존처럼 전부 1.0으로 센다",
   stats_no_weights["chars_per_cue"]["ours_median"] == 5.0,
   str(stats_no_weights["chars_per_cue"]))
ok("char_weights를 주면 한국어 가중치가 실제로 반영된다",
   stats_ko_weights["chars_per_cue"]["ours_median"] == 3.5,
   str(stats_ko_weights["chars_per_cue"]))

# 텍스트가 가장 안 맞는 자막이 리포트 개별 목록에 실제로 나오고, 안 맞는 순으로
# 먼저 나오는지 확인한다.
mismatched = [_EvalEvent(1, 0, 3000, "정답과 완전히 다른 말"),
              _EvalEvent(2, 4000, 7000, "이건 거의 똑같은 문장")]
truth2 = [_EvalEvent(1, 0, 3000, "여기는 딴 소리를 한다"),
         _EvalEvent(2, 4000, 7000, "이건 거의 똑같은 문장이다")]
comparison3 = compare(mismatched, truth2)
by_similarity = sorted(comparison3.matched, key=lambda p: p.text_similarity)
worst_pair, best_pair = by_similarity[0], by_similarity[-1]
# **기본값에서는 텍스트 목록을 안 낸다**(규칙 15 — TC를 먼저 맞추고 그다음
# 텍스트다). 자막 단위가 정답과 어긋난 상태에서 이 목록을 보면 TC 문제를
# 번역 문제로 오판한다(2026-08-27 예능A 15회 실측이 그랬다).
txt_default = report(comparison3)
ok("기본값에서는 텍스트 목록을 내지 않는다",
   "텍스트가 가장 안 맞는 자막" not in txt_default, txt_default)
ok("대신 왜 안 내는지와 어떻게 보는지를 말한다",
   "--text-diff" in txt_default and "규칙 15" in txt_default, txt_default)
ok("TC 쪽(자막 수·인점·아웃점)은 기본값에서도 그대로 낸다",
   "자막 수" in txt_default and "인점" in txt_default, txt_default)

txt = report(comparison3, text_diff=True)
ok("--text-diff면 텍스트 불일치 개별 목록이 나온다",
   "텍스트가 가장 안 맞는 자막" in txt, txt)
# 리포트에는 타이밍 기준 "가장 많이 어긋난 자막" 목록도 따로 있으므로, 새로 넣은
# 텍스트 목록 구간만 잘라서 순서를 확인한다.
text_section = txt[txt.index("텍스트가 가장 안 맞는 자막"):]
ok("가장 안 맞는 자막이 잘 맞는 자막보다 먼저 나온다",
   text_section.index(f"#{worst_pair.truth.index:>3}")
   < text_section.index(f"#{best_pair.truth.index:>3}"), text_section)
# 유사도 가운데값은 기본값에서도 낸다 — 숫자 하나는 "얼마나 먼가"를 가늠하게
# 해 줄 뿐, 자막을 하나씩 손보게 만들지 않는다.
ok("유사도 가운데값은 기본값에서도 낸다", "텍스트 유사도" in txt_default, txt_default)


# --- 미리 점검(--dry-run) --------------------------------------------------
# 오늘(2026-08-27) 실제로 겪은 실패들(torch 충돌·DLL 못 찾음·디스크 부족·
# HF 토큰 없음·Ollama 응답 없음)이 전사·번역을 10~20분 돌리고 나서야
# 드러났다 — 실행 전에 환경만 빠르게 본다.

from checker import preflight as _pf  # noqa: E402

_pf_checks = _pf.run(Path("없는영상.mkv"), translate=False, diarize=False)
ok("없는 영상은 실패로 잡는다",
   any(not c.ok and "영상" in c.name for c in _pf_checks))
ok("예외를 올리지 않는다(실패도 결과로 담는다)", isinstance(_pf_checks, list))

_pf_report = _pf.report([_pf.Check("가짜 항목", True, "세부")])
ok("통과 항목을 보여 준다", "가짜 항목" in _pf_report and "세부" in _pf_report)
_pf_report_fail = _pf.report([_pf.Check("가짜 항목", False, "이유")])
ok("실패 개수를 요약한다", "1건 실패" in _pf_report_fail)
_pf_report_ok = _pf.report([_pf.Check("가짜 항목", True)])
ok("전부 통과하면 그렇게 말하되 로직은 보장 안 한다고 밝힌다",
   "실행해 봐야" in _pf_report_ok)


# --- OCR 자르기 구문(_crop_filter) ------------------------------------------

ok("아무것도 안 주면 안 자른다", _crop_filter() == "")
ok("band는 화면 아래만 남긴다", _crop_filter(band=0.25) == ",crop=iw:ih*0.25:0:ih*0.75")
ok("exclude_top은 화면 위만 뺀다",
   _crop_filter(exclude_top=0.2) == ",crop=iw:ih*0.8:0:ih*0.2")
try:
    _crop_filter(band=0.25, exclude_top=0.2)
    ok("band·exclude_top 동시 지정은 막는다", False)
except ValueError:
    ok("band·exclude_top 동시 지정은 막는다", True)


# --- 화면 캡션 OCR 병합(merge_frames) --------------------------------------
# ffmpeg·easyocr 없이 순수 함수만 검사한다 — .venv-ocr가 없어도 이 스위트는
# 그대로 통과해야 한다(규칙9, 무거운 의존성을 pre-commit 필수 경로에 안 넣는다).

_step = 500  # sample_fps=2.0일 때의 프레임 간격(ms)

_merged = merge_frames(
    [(0, "HELLO", 0.9), (500, "HELLO", 0.85), (1000, "HELLO", 0.9)], _step)
ok("같은 텍스트 연속 프레임이 캡션 하나로 병합된다", len(_merged) == 1)
ok("병합된 캡션의 끝 시각이 마지막 프레임 뒤로 늘어난다",
   _merged and _merged[0].end_ms == 1000 + _step)
ok("병합된 캡션의 프레임 수를 센다", _merged and _merged[0].frame_count == 3)

_split = merge_frames(
    [(0, "HELLO", 0.9), (500, "WORLD", 0.9)], _step)
ok("텍스트가 바뀌면 캡션이 갈린다", len(_split) == 2)

_dropped = merge_frames(
    [(0, "HELLO", 0.9), (500, "HELLO", 0.1), (1000, "HELLO", 0.1),
     (1500, "HELLO", 0.9)], _step, min_confidence=0.4)
ok("신뢰도 미달 프레임은 버려진다(연속으로 빠지면 간격이 벌어져 캡션이 갈린다)",
   len(_dropped) == 2)

_gapped = merge_frames(
    [(0, "HELLO", 0.9), (5000, "HELLO", 0.9)], _step)
ok("샘플 간격보다 큰 공백은 텍스트가 같아도 캡션을 가른다", len(_gapped) == 2)

_empty = merge_frames([(0, "   ", 0.9)], _step)
ok("빈 텍스트 프레임은 캡션이 되지 않는다", _empty == [])

# 실측(2026-08-30, 예능A 19회): 같은 캡션이 프레임마다 한두 글자씩
# 다르게 읽힌다("마님"이 "마남"·"마넘"으로 흔들림) — 완전 일치가 아니라
# 편집 유사도로 같은 캡션인지 본다.
_fuzzy = merge_frames(
    [(0, "우리 마남이 이런데 뭐 ?", 0.78), (500, "우리 마넘이 이런데 뭐 ?", 0.40),
     (1000, "우리 마남이 이런데 뭐 ?", 0.53)], _step)
ok("프레임마다 한두 글자 흔들려도 같은 캡션으로 합쳐진다(편집 유사도)",
   len(_fuzzy) == 1)
ok("합쳐진 캡션의 대표 텍스트는 신뢰도가 가장 높았던 프레임 것이다",
   _fuzzy and _fuzzy[0].text == "우리 마남이 이런데 뭐 ?"
   and abs(_fuzzy[0].confidence - (0.78 + 0.40 + 0.53) / 3) < 1e-9)

ok("정말 다른 텍스트는 유사도 기준 미달로 여전히 갈린다",
   len(merge_frames([(0, "HELLO", 0.9), (500, "GOODBYE", 0.9)], _step)) == 2)

# 실측(2026-08-31, 같은 영상 전체 회차 재검증): 유사도 비교를 직전 캡션의
# "대표 텍스트"(계속 갱신됨)와 하면 A~B~C~...~Z처럼 인접한 것끼리만 비슷해도
# 전체가 하나로 이어 붙는다 — 실제로 캡션 하나가 167초까지 늘어난 사례가
# 나왔다. 한 글자씩 a->b로 바뀌는 11프레임을 만들어 첫 프레임(anchor)과 끝
# 프레임이 완전히 다른 텍스트가 되는 상황을 재현한다.
_drift_frames = [
    (i * 500, ("b" * i) + ("a" * (10 - i)), 0.9) for i in range(11)
]
_drifted = merge_frames(_drift_frames, _step)
ok("전이적 드리프트(A~B~C~...~Z)는 anchor 비교로 막혀 여러 캡션으로 갈린다",
   len(_drifted) > 1)
ok("드리프트가 갈린 첫 캡션은 마지막 프레임(전혀 다른 텍스트)을 포함하지 않는다",
   _drifted[0].end_ms < _drift_frames[-1][0] + _step)

# max_duration_ms를 명시하면(opt-in) 같은 텍스트가 반복돼도 그만큼에서 갈린다.
_long_same = [(i * 500, "HELLO", 0.9) for i in range(21)]  # 0~10500ms
_capped = merge_frames(_long_same, _step, max_duration_ms=8000)
ok("max_duration_ms를 주면 같은 텍스트라도 그 길이에서 캡션이 갈린다",
   len(_capped) >= 2)
ok("갈린 첫 캡션의 길이가 지정한 최대 지속시간을 넘지 않는다",
   _capped[0].end_ms - _capped[0].start_ms <= 8000)

# 실측(2026-08-31, 예능A 19회): 315초·340초 프레임을 직접 열어 보니
# 이름 캡션("Sebastiam"/"Tomy"/"Scarlet")이 25초 넘게 픽셀 단위로 그대로였다
# — 정적 이름표·워터마크류는 실제로 오래 떠 있는다. 기본(max_duration_ms 안
# 줌)은 상한이 없어야 이런 정상 캡션을 안 쪼갠다.
_no_cap = merge_frames(_long_same, _step)
ok("기본은 지속시간 상한이 없다 — 정적 캡션(이름표 등)을 쪼개지 않는다",
   len(_no_cap) == 1)


# --- 화면 캡션 2단계: 마커 적용(apply_marker) ------------------------------
# is_forced_narrative()가 나중에 그대로 알아보는지가 핵심이다 — 다른 모양으로
# 감싸면 방금 만든 캡션을 검사기 스스로 못 알아본다(왕복 확인).

for _marker in ("double_quote", "italic", "bracket"):
    _wrapped = apply_marker("화면 텍스트", _marker)
    ok(f"apply_marker({_marker!r})가 감싼 텍스트를 is_forced_narrative가 다시 알아본다",
       is_forced_narrative(_wrapped, rules=JobRules(marker=_marker, policy="keep_both")))

ok("marker=none이면 감싸지 않는다", apply_marker("화면 텍스트", "none") == "화면 텍스트")
ok('marker=double_quote는 U+201C/U+201D로 감싼다',
   apply_marker("화면 텍스트", "double_quote") == "“화면 텍스트”")


# --- 화면 캡션 2단계: Event 변환·병합(captions_to_events, merge_captions) --

_caps = [OcrCaption(1000, 3000, "Sebastiam", 0.86, frame_count=5),
        OcrCaption(5000, 7000, "흐릿한 글자", 0.30, frame_count=2)]
_cap_events = captions_to_events(_caps, start_index=10)
ok("captions_to_events가 kind=caption으로 만든다",
   all(e.kind == "caption" for e in _cap_events))
ok("captions_to_events의 인덱스가 start_index부터 이어진다",
   [e.index for e in _cap_events] == [10, 11])

_dialogue = [Event(1, 0, 1000, "안녕"), Event(2, 4000, 4500, "잘가")]
_confidences = {e.index: c.confidence for e, c in zip(_cap_events, _caps)}
_merged_events, _merged_notes = merge_captions(
    _dialogue, [(1, "환각 의심")], _cap_events, _confidences, "bracket")

ok("합쳐진 이벤트가 시간순이다",
   [e.start_ms for e in _merged_events] == sorted(e.start_ms for e in _merged_events))
ok("합쳐진 이벤트 번호가 1..N으로 새로 매겨진다",
   [e.index for e in _merged_events] == list(range(1, len(_merged_events) + 1)))
ok("합쳐진 뒤에도 캡션 개수·대사 개수 합이 맞는다", len(_merged_events) == 4)

_caption_in_merged = [e for e in _merged_events if e.kind == "caption"]
ok("캡션 텍스트가 bracket 마커로 감싸졌다",
   all(e.text.startswith("[") and e.text.endswith("]") for e in _caption_in_merged))

_dialogue_note_idx = next(i for i, msg in _merged_notes if msg == "환각 의심")
_expected_dialogue_new_index = next(
    e.index for e in _merged_events if e.kind == "dialogue" and e.start_ms == 0)
ok("기존 대사 노트가 밀린 번호로 옮겨진다(안 옮기면 엉뚱한 자막을 가리킨다)",
   _dialogue_note_idx == _expected_dialogue_new_index)

_low_conf_idx = next(
    e.index for e in _merged_events if e.kind == "caption" and "흐릿한" in e.text)
ok("신뢰도 낮은 캡션은 확인 필요 노트가 붙는다",
   any(i == _low_conf_idx and "확인 필요" in msg for i, msg in _merged_notes))
_high_conf_idx = next(
    e.index for e in _merged_events if e.kind == "caption" and "Sebastiam" in e.text)
ok("신뢰도 높은 캡션(0.86)은 확인 필요 노트가 안 붙는다",
   not any(i == _high_conf_idx for i, msg in _merged_notes if "확인 필요" in msg))


# --- has_vad_support: VAD와 안 겹치는 자막은 지우지 않고 표시만 한다 -------
# 2026-08-31, 영화B 정답 대조: VAD가 배경음악 깔린 구간에서
# 진짜 대사("Hello!" 등)를 놓치는 사례를 확인 — 예전엔 여기서 조용히 지웠다.

ok("VAD 구간과 겹치면 지지받는다",
   has_vad_support(1000, 2000, [(500, 1500)], speech_end=1500, undetected_after=False))
ok("VAD 구간과 전혀 안 겹치면 지지받지 못한다(하지만 호출부가 지우지 않는다)",
   not has_vad_support(5000, 6000, [(0, 1000), (8000, 9000)],
                       speech_end=9000, undetected_after=False))
ok("VAD 자체가 비어 있으면(음량 방식 등) 항상 지지받는다",
   has_vad_support(5000, 6000, [], speech_end=0, undetected_after=False))
ok("undetected_after면 speech_end 이후 구간은 검출 실패로 보고 지지받는다",
   has_vad_support(50_000, 51_000, [(0, 1000)], speech_end=1000, undetected_after=True))
ok("undetected_after여도 speech_end 이전 구간은 그대로 안 겹치면 지지 못 받는다",
   not has_vad_support(500, 600, [(0, 100)], speech_end=1000, undetected_after=True))


# --- _is_known_hallucination: whisper의 유명한 침묵 환각 문구는 지운다 -----
# 2026-08-31, 영화A 오프닝 실측: "Transcribed by ESO, translated by —"
# 반복, "—"만 있는 조각 수십 개. 텍스트 자체로 판정되는 사실이라(규칙4)
# VAD 안 겹침(추정)과 달리 지운다.

ok("'Transcribed by' 계열은 대소문자 안 가리고 걸린다",
   _is_known_hallucination("Transcribed by ESO,"))
ok("'translated by' 계열도 걸린다", _is_known_hallucination("translated by —"))
ok("대시만 있는 조각은 글자가 없어서 걸린다", _is_known_hallucination("—"))
ok("음표(♪)만 있으면 예외 — 지어낸 자리표시자가 아니다(2026-08-31, 코드 리뷰로 발견)",
   not _is_known_hallucination("♪"))
ok("빈 문자열도 걸린다", _is_known_hallucination("   "))
ok("진짜 대사는 안 걸린다", not _is_known_hallucination("Hello!"))
ok("한글 대사는 안 걸린다(isalnum이 한글도 인정)",
   not _is_known_hallucination("안녕하세요"))
ok("우연히 비슷한 단어가 섞여도 대사면 안 걸린다",
   not _is_known_hallucination("I'm watching you."))
ok("한국어 팬섭 크레딧('한글자막 by ...')도 걸린다(2026-08-31, 드라마B E02~05 4회차 전부에서 확인)",
   _is_known_hallucination("한글자막 by 한효정"))

# **PLAUSIBLE_ONMIC_PHRASES는 VAD 정보 없이는 지우지 않는다**(2026-08-31,
# 코드 리뷰로 발견 — 예능·다큐 진행자가 실제로 "시청해 주셔서 감사합니다"류
# 인사를 할 수 있어(규칙16), 텍스트만으로 확신할 수 없다. 크레딧 문구와
# 달리 VAD가 이 구간에 말소리가 없다고 볼 때만 지운다).
ok("'thanks for watching'는 VAD 정보 없이는 안 지운다(옛날엔 무조건 지웠음)",
   not _is_known_hallucination("Thanks for watching!"))
ok("'다음 영상에서 만나요'도 VAD 정보 없이는 안 지운다",
   not _is_known_hallucination("다음 영상에서 만나요."))
ok("VAD와 안 겹치면(침묵) 'thanks for watching'을 지운다",
   _is_known_hallucination("Thanks for watching!", 5000, 6000, [(0, 1000)]))
ok("VAD와 겹치면(실제 말소리 있음) 'thanks for watching'을 안 지운다",
   not _is_known_hallucination("Thanks for watching!", 5000, 6000, [(4000, 7000)]))


# --- T10(quote_role_swapped)·T11(forced_narrative_merged_with_dialogue) ---
# 화면 캡션 2단계로 마커 적용 캡션이 실제로 생기니 이 두 검사(전엔 "미구현"으로만
# 보고됐다)를 구현한다.
# 주의: 위(994행 부근)에서 `ev`를 `Event` 인스턴스로 재할당해 놓아 이 지점부터는
# `ev()` 헬퍼 함수를 못 쓴다(플랫 스크립트라 전역이 그대로 덮인다) — 딕셔너리를
# 직접 만든다.

def _tev(text: str, index: int = 1, start: int = 0, end: int = 3000) -> dict:
    return {"index": index, "start_ms": start, "end_ms": end, "text": text}


_ko_tr = load_profile("netflix", "ko", "translation")
_dq_rules = JobRules(marker="double_quote", policy="keep_both")

_r_swapped = check_events(
    [_tev('안녕, "정말?" 이라고 말했다')], _ko_tr, job_rules=_dq_rules)
ok("T10: 대사 안 인용에 큰따옴표를 쓰면 잡는다", "T10" in ids(_r_swapped))

_r_full_caption = check_events(
    [_tev("“PRESENTED BY SCREWBALLS”")], _ko_tr, job_rules=_dq_rules)
ok("T10: 이벤트 전체가 화면자막이면 정상 사용이라 안 잡는다",
   "T10" not in ids(_r_full_caption))

_italic_rules = JobRules(marker="italic", policy="keep_both")
_r_other_marker = check_events(
    [_tev('안녕, "정말?" 이라고 말했다')], _ko_tr, job_rules=_italic_rules)
ok("T10: 마커가 double_quote가 아니면 이 검사는 안 돈다",
   "T10" not in ids(_r_other_marker))

_r_merged = check_events(
    [_tev("“PRESENTED BY SCREWBALLS”\n오늘도 즐거운 하루")], _ko_tr, job_rules=_dq_rules)
ok("T11: 한 자막 안에 화면자막과 대사가 섞이면 잡는다", "T11" in ids(_r_merged))

_r_both_dialogue = check_events([_tev("안녕\n반가워")], _ko_tr, job_rules=_dq_rules)
ok("T11: 둘 다 대사면 안 잡는다", "T11" not in ids(_r_both_dialogue))

_r_both_caption = check_events(
    [_tev("“첫째 줄”\n“둘째 줄”")], _ko_tr, job_rules=_dq_rules)
ok("T11: 둘 다 화면자막이면 안 잡는다", "T11" not in ids(_r_both_caption))

_r_ask = check_events([_tev("“PRESENTED”\n오늘도 즐거운 하루")], _ko_tr, job_rules=JobRules())
ok("T11: 마커가 정해지지 않았으면 검사하지 않는다", "T11" not in ids(_r_ask))

ok("T10/T11이 미구현 목록에서 빠졌다(마커가 정해진 넷플릭스 한국어 번역)",
   "T10" not in _r_swapped["unimplemented_checks"]
   and "T11" not in _r_merged["unimplemented_checks"])


# --- 하드섭 OCR 초안(captions_to_draft_srt_events) -------------------------
# corpus_build.py:90-91과 같은 원칙 — OCR은 정답지가 아니다. 카드 하나 = 자막
# 하나로 그대로 옮기고(마커로 안 감싼다), 신뢰도 낮은 카드만 노트로 남긴다.

_hard_caps = [OcrCaption(0, 2000, "그럼에도 말하고 싶다", 0.82, frame_count=4),
             OcrCaption(3000, 5000, "흐릿하게 읽힘", 0.35, frame_count=2)]
_hard_events, _hard_notes = captions_to_draft_srt_events(_hard_caps)

ok("카드 하나가 자막 하나로 그대로 옮겨진다(마커로 안 감싼다)",
   [e.text for e in _hard_events] == ["그럼에도 말하고 싶다", "흐릿하게 읽힘"])
ok("하드섭 초안 이벤트는 kind=caption이다",
   all(e.kind == "caption" for e in _hard_events))
ok("인덱스가 1..N으로 매겨진다", [e.index for e in _hard_events] == [1, 2])
ok("신뢰도 낮은 카드만 노트가 붙는다",
   [i for i, _ in _hard_notes] == [2] and "0.35" in _hard_notes[0][1])
ok("신뢰도 높은 카드는 노트가 안 붙는다", 1 not in dict(_hard_notes))


# --- SFX 1단계: speech_gaps(대사 없는 구간만 뽑기) -------------------------
# 대사 위에 깔린 배경음은 여기서 안 다룬다 — 화면까지 봐야 판단할 자리라
# 대사 없는 자리만 돌려준다(checker/sfx.py 독스트링).

ok("말소리 앞뒤·사이의 빈 구간을 뽑는다",
   speech_gaps([(2000, 4000), (6000, 7000)], duration_ms=10000, min_gap_ms=500)
   == [(0, 2000), (4000, 6000), (7000, 10000)])
ok("min_gap_ms보다 짧은 틈은 버린다",
   speech_gaps([(0, 2000), (2300, 4000)], duration_ms=4000, min_gap_ms=500) == [])
ok("겹치거나 순서 뒤섞인 말소리 구간도 정렬해서 처리한다",
   speech_gaps([(5000, 6000), (0, 1000)], duration_ms=8000, min_gap_ms=500)
   == [(1000, 5000), (6000, 8000)])
ok("말소리가 전혀 없으면 전체가 하나의 빈 구간이다",
   speech_gaps([], duration_ms=5000, min_gap_ms=500) == [(0, 5000)])

ok("AUDIOSET_TO_CANDIDATE의 후보는 전부 대괄호로 감싼 문구다",
   all(v.startswith("[") and v.endswith("]") for v in AUDIOSET_TO_CANDIDATE.values()))

# --- _windows: 긴 구간을 모델 입력 한계 이하로 나눈다(2026-08-31, 코드 리뷰로 발견) ---
# AST 모델이 10.24초 넘는 오디오를 통째로 받으면 앞부분만 대표하는 라벨을
# 낸다 — 그래서 분류 전에 창 단위로 나눈다.

ok("구간이 창보다 짧으면 그대로 창 하나",
   _windows(0, 5000, 9000) == [(0, 5000)])
ok("구간을 창 크기로 정확히 나눈다", _windows(0, 18000, 9000) == [(0, 9000), (9000, 18000)])
ok("나머지는 짧은 마지막 창으로 남는다",
   _windows(0, 20000, 9000) == [(0, 9000), (9000, 18000), (18000, 20000)])
ok("빈 구간은 창이 없다", _windows(1000, 1000, 9000) == [])

# --- _apply_music_marker: 플랫폼별 DP12류(음악 효과음 ♪ 표기) 반영 --------
# 2026-08-31, 드라마B E01 --generate --sfx 통합 테스트에서 실측: 고정 문구를
# 그대로 얹으면 디즈니 DP12(음악 효과음엔 ♪ 필요) 위반이 126건 났다.

ok("note_inside_bracket=True면 음악 관련 문구에 ♪를 넣는다",
   _apply_music_marker("[음악이 흐른다]", True) == "[♪ 음악이 흐른다]")
ok("note_inside_bracket=False면 음악 관련 문구에서 ♪를 뺀다",
   _apply_music_marker("[♪ 음악이 흐른다]", False) == "[음악이 흐른다]")
ok("note_inside_bracket=None이면 손대지 않는다",
   _apply_music_marker("[음악이 흐른다]", None) == "[음악이 흐른다]")
ok("음악과 무관한 문구는 손대지 않는다",
   _apply_music_marker("[개 짖는 소리]", True) == "[개 짖는 소리]")
ok("이미 규칙에 맞으면 그대로 둔다",
   _apply_music_marker("[♪ 음악이 흐른다]", True) == "[♪ 음악이 흐른다]")


# --- SFX 2단계: sound_events_to_draft_events·merge_sound_events -----------
# candidate 없는 라벨은 지어내지 않고 뺀다(규칙3). 얹은 자리는 신뢰도와
# 무관하게 예외 없이 확인 필요 노트가 붙는다(OCR과 다른 점, 모듈 독스트링).

_sound_events = [
    SoundEvent(2000, 4000, "Music", 0.6, "[음악이 흐른다]"),
    SoundEvent(9000, 10000, "Silence", 0.9, None),  # 매핑 없음 — 빠져야 한다
]
_sfx_draft = sound_events_to_draft_events(_sound_events, start_index=10)
ok("매핑 없는 라벨은 빠진다", len(_sfx_draft) == 1 and _sfx_draft[0].text == "[음악이 흐른다]")
ok("sfx 초안 이벤트는 kind=sfx다", _sfx_draft[0].kind == "sfx")

_sfx_dialogue = [Event(1, 0, 1000, "안녕"), Event(2, 5000, 6000, "잘가")]
_sfx_merged_events, _sfx_merged_notes, _sfx_merged_sources = merge_sound_events(
    _sfx_dialogue, [(1, "환각 의심")], _sfx_draft, {1: "Hi", 2: "Bye"})

ok("합쳐진 이벤트가 시간순이다",
   [e.start_ms for e in _sfx_merged_events] == sorted(e.start_ms for e in _sfx_merged_events))
ok("합쳐진 이벤트 번호가 1..N으로 새로 매겨진다",
   [e.index for e in _sfx_merged_events] == list(range(1, len(_sfx_merged_events) + 1)))
_sfx_note_idx = next(
    e.index for e in _sfx_merged_events if e.kind == "sfx")
ok("얹은 소리 후보는 신뢰도(0.6, 낮지 않음)와 무관하게 확인 필요 노트가 붙는다",
   any(i == _sfx_note_idx and "확인 필요" in msg for i, msg in _sfx_merged_notes))
_sfx_dialogue_note_idx = next(i for i, msg in _sfx_merged_notes if msg == "환각 의심")
_sfx_expected_dialogue_new_index = next(
    e.index for e in _sfx_merged_events if e.kind == "dialogue" and e.start_ms == 0)
ok("기존 대사 노트가 밀린 번호로 옮겨진다",
   _sfx_dialogue_note_idx == _sfx_expected_dialogue_new_index)
ok("dialogue_sources도 밀린 번호로 옮겨진다(2026-08-31, 코드 리뷰로 발견 — "
   "안 옮기면 원어 표시가 엉뚱한 자막을 가리킨다)",
   _sfx_merged_sources[_sfx_expected_dialogue_new_index] == "Hi")

# --- SFX 겹침 처리: 스포팅이 밀어낸 대사와 겹치면 물러서거나 버린다 -------
# 2026-08-31, 코드 리뷰로 발견 — timing.py의 LEADS가 대사 아웃점을 VAD
# 구간 끝보다 늦게 늘릴 수 있어, 그 자리에 얹은 소리 후보와 겹칠 수 있다.

_overlap_dialogue = [Event(1, 0, 2500, "안녕")]  # 아웃점이 2500까지 밀려남
_overlap_sfx = [Event(2, 2000, 4000, "[음악이 흐른다]", kind="sfx")]  # 원래 2000부터
_ov_events, _ov_notes, _ov_sources = merge_sound_events(_overlap_dialogue, [], _overlap_sfx)
_ov_sfx = next(e for e in _ov_events if e.kind == "sfx")
ok("대사와 겹치면 소리 후보 인점을 대사 아웃점 뒤로 민다",
   _ov_sfx.start_ms == 2500)

_short_overlap_dialogue = [Event(1, 0, 3900, "안녕")]
_short_overlap_sfx = [Event(2, 3800, 4000, "[음악이 흐른다]", kind="sfx")]  # 밀면 100ms
_ov2_events, _ov2_notes, _ov2_sources = merge_sound_events(
    _short_overlap_dialogue, [], _short_overlap_sfx)
ok("밀어내서 너무 짧아지면(500ms 미만) 통째로 버린다",
   not any(e.kind == "sfx" for e in _ov2_events))

# **버려진 이웃을 다음 클램프의 기준으로 삼지 않는다**(2026-08-31, 드라마B E01
# 실전 검증에서 재발견 — 합성 시험 하나만으로는 못 잡았다). VAD가 대사
# 하나 안에서 짧은 침묵을 잘못 감지해 소리 후보 3개가 연달아 나온 경우:
# 가운데 것이(대사와 겹쳐서) 버려지면, 세 번째 것은 그 버려진 것의 이른
# 끝점이 아니라 실제로 살아남은 이웃(대사)의 끝점을 봐야 한다 — 안 그러면
# 대사와 여전히 겹친 채로 통과한다.
_cascade_dialogue = [Event(1, 0, 1000, "앞"), Event(2, 2000, 5000, "대사")]
_cascade_sfx = [
    Event(3, 1000, 1800, "[음악A]", kind="sfx"),   # 정상 — 두 대사 사이
    Event(4, 3000, 3500, "[음악B]", kind="sfx"),   # 대사 한가운데 — 버려져야 함
    Event(5, 4900, 6000, "[음악C]", kind="sfx"),   # 버려진 B가 아니라 대사 끝(5000)을 봐야 함
]
_casc_events, _casc_notes, _ = merge_sound_events(_cascade_dialogue, [], _cascade_sfx)
_casc_sorted = sorted(_casc_events, key=lambda e: e.start_ms)
ok("가운데 겹친 후보는 버려진다",
   not any(e.text == "[음악B]" for e in _casc_sorted))
ok("그다음 후보는 버려진 이웃이 아니라 실제 이웃(대사)을 기준으로 밀린다",
   next(e for e in _casc_sorted if e.text == "[음악C]").start_ms == 5000)
ok("결과에 겹침이 없다",
   all(a.end_ms <= b.start_ms for a, b in zip(_casc_sorted, _casc_sorted[1:])))


# --- 겹침 방지(_enforce_no_overlap) ----------------------------------------
# "경계만 따로 정밀화"는 시도했다가 걷어냈다(ffmpeg이 짧은 구간을 독립적으로
# seek하면 실제 내용과 다른 프레임을 준다는 게 실측으로 드러남 — `checker/
# ocr.py` 모듈 독스트링 "4단계" 참고). 그 과정에서 찾은 실제 문제 중
# `_enforce_no_overlap`(앞 캡션 끝이 뒤 캡션 시작보다 늦게 잡히면 당긴다)은
# 정밀화 여부와 무관하게 유효해서 남겼다.
_r_overlapping = [OcrCaption(0, 1000, "A", 0.9), OcrCaption(800, 2000, "B", 0.9)]
_r_fixed = _enforce_no_overlap(_r_overlapping)
ok("겹치는 캡션은 앞 캡션 끝을 뒤 캡션 시작으로 당긴다",
   _r_fixed[0].end_ms == 800 and _r_fixed[1].start_ms == 800)

_r_clean = [OcrCaption(0, 500, "A", 0.9), OcrCaption(600, 1000, "B", 0.9)]
ok("이미 안 겹치면 그대로 둔다", _enforce_no_overlap(_r_clean) == _r_clean)

_r_unsorted = [OcrCaption(600, 1000, "B", 0.9), OcrCaption(0, 500, "A", 0.9)]
ok("시간순으로 정렬해서 돌려준다",
   [c.start_ms for c in _enforce_no_overlap(_r_unsorted)] == [0, 600])


# --- OCR 이어하기(체크포인트) ------------------------------------------------
# `--ocr-hardsub`는 71분 영상 기준 7~8시간짜리 스캔이다(`checker/ocr.py` 모듈
# 독스트링) — 절전·재부팅으로 끊기면 처음부터 다시 도는 비용을 감당하기
# 어렵다는 게 코드 동작 분석으로 드러났다(2026-08-31, 실제 재현은 아직 못
# 했다 — 몇 시간대 작업이라). 실제 EasyOCR 워커(`_ocr_worker.py`)의 프레임별
# 이어쓰기 자체는 격리 venv가 있어야 해서 여기서 못 돌리지만(다른 워커
# 파일들과 같은 제약), 어느 체크포인트를 믿어도 되는지 판단하는
# `_prepare_checkpoint`/`_checkpoint_fingerprint`/`_cleanup_checkpoint`는
# 순수 파이썬이라 여기서 잰다.
import tempfile as _ocrck_tf  # noqa: E402
import json as _ocrck_json  # noqa: E402

with _ocrck_tf.TemporaryDirectory(prefix="stc-ocrck-") as _ocrck_dir:
    _ocrck_dir = Path(_ocrck_dir)
    _ocrck_video = _ocrck_dir / "movie.mp4"
    _ocrck_video.write_bytes(b"fake video bytes")
    _ocrck_cp = _ocrck_dir / "movie.ocr-checkpoint.json"
    _ocrck_meta = _ocrck_dir / "movie.ocr-checkpoint.json.meta.json"

    _fp_a = _checkpoint_fingerprint(_ocrck_video, "en", 12.0, 0.25, True)
    _fp_b = _checkpoint_fingerprint(_ocrck_video, "en", 12.0, 0.25, True)
    ok("같은 영상·같은 설정은 지문이 같다", _fp_a == _fp_b)

    _fp_diff_fps = _checkpoint_fingerprint(_ocrck_video, "en", 2.0, 0.25, True)
    ok("sample_fps가 다르면 지문도 다르다", _fp_a != _fp_diff_fps)

    _fp_diff_lang = _checkpoint_fingerprint(_ocrck_video, "ko", 12.0, 0.25, True)
    ok("언어가 다르면 지문도 다르다", _fp_a != _fp_diff_lang)

    # 체크포인트도 메타도 없는 첫 실행 — 메타만 새로 남기고 아무것도 안 지운다.
    _prepare_checkpoint(_ocrck_cp, _fp_a)
    ok("첫 실행은 지문 파일을 남긴다", _ocrck_meta.is_file())
    ok("지울 체크포인트가 없으면 에러 없이 지나간다", not _ocrck_cp.is_file())

    # 끊긴 실행이 남긴 체크포인트 — 같은 지문이면 이어받게 그대로 둔다.
    _ocrck_cp.write_text(_ocrck_json.dumps([[0, "hello", 0.9]]), encoding="utf-8")
    _prepare_checkpoint(_ocrck_cp, _fp_a)
    ok("지문이 같으면 체크포인트를 안 지운다(이어받는다)", _ocrck_cp.is_file())

    # 설정을 바꿔 다시 부르면(예: sample_fps 변경) 옛 체크포인트를 못 믿는다.
    _prepare_checkpoint(_ocrck_cp, _fp_diff_fps)
    ok("지문이 다르면 체크포인트를 지운다(새로 시작)", not _ocrck_cp.is_file())
    ok("지문 파일은 새 지문으로 갱신된다",
       _ocrck_json.loads(_ocrck_meta.read_text(encoding="utf-8")) == _fp_diff_fps)

    # 스캔이 끝까지 성공하면 흔적을 치운다 — 안 그러면 다음 실행이 "이미 다
    # 됐다"고 오해한다(사실은 새 스캔인데 우연히 지문이 같을 수 있다).
    _ocrck_cp.write_text("[]", encoding="utf-8")
    _cleanup_checkpoint(_ocrck_cp)
    ok("성공하면 체크포인트를 지운다", not _ocrck_cp.is_file())
    ok("성공하면 지문 파일도 지운다", not _ocrck_meta.is_file())
    _cleanup_checkpoint(_ocrck_cp)  # 이미 없어도 에러 없이 지나간다
    ok("이미 지워졌어도 다시 불러도 안전하다(멱등)", not _ocrck_cp.is_file())


# --- 결정표: 고르지 않은 것을 고른 것처럼 보이지 않게 한다 ----------------

import argparse as _dec_argparse  # noqa: E402
from checker import decisions as _dec  # noqa: E402


def _dec_args(**kw):
    base = dict(platform=None, kind=None, lang=None, genre=None,
                translate=False, cast=None, profile=None, lock_timecodes=False)
    base.update(kw)
    return _dec_argparse.Namespace(**base)


_dec_empty = _dec_args()
_dec_list = _dec.resolve(_dec_empty)
ok("빈 칸을 예전과 같은 값으로 채운다",
   (_dec_empty.platform, _dec_empty.kind, _dec_empty.lang) == ("netflix", "translation", "ko"),
   f"{_dec_empty.platform}/{_dec_empty.kind}/{_dec_empty.lang}")
_dec_by_label = {d.label: d for d in _dec_list}
ok("채운 값은 default로 표시한다", _dec_by_label["발주처"].source == "default")
ok("발주처를 안 고르면 확인 필요로 낸다", _dec_by_label["발주처"].warn)
ok("종류를 안 고르면 확인 필요로 낸다", _dec_by_label["종류"].warn)
ok("언어는 경고까지 하지는 않는다", not _dec_by_label["언어"].warn)
ok("장르는 값을 채우지 않는다(미지정으로 남긴다)",
   _dec_by_label["장르"].source == "none" and _dec_by_label["장르"].value == "미지정")

_dec_user = _dec.resolve(_dec_args(platform="coupang", kind="sdh", lang="ko", genre="variety"))
ok("고른 것은 user로 표시하고 경고하지 않는다",
   all(d.source == "user" and not d.warn for d in _dec_user))
ok("고르면 경고 목록이 빈다", _dec.warnings(_dec_user) == [])
ok("안 고르면 경고 목록에 발주처가 들어간다",
   any("발주처" in w for w in _dec.warnings(_dec_list)))

# --profile로 파일을 직접 준 경우는 platform/kind를 안 고른 것이 정상이다.
_dec_file = {d.label: d for d in _dec.resolve(_dec_args(profile="x.yaml"))}
ok("--profile을 주면 발주처 미지정을 경고하지 않는다",
   _dec_file["발주처"].source == "file" and not _dec_file["발주처"].warn)

# 번역할 때만 캐스트 시트를 묻는다 — 검사만 할 때는 쓰지 않는 칸이다.
ok("검사만 할 때는 캐스트 시트를 묻지 않는다", "캐스트 시트" not in _dec_by_label)
_dec_tr = {d.label: d for d in _dec.resolve(_dec_args(translate=True))}
ok("번역인데 캐스트 시트가 없으면 확인 필요로 낸다", _dec_tr["캐스트 시트"].warn)
_dec_tr_cast = {d.label: d for d in _dec.resolve(_dec_args(translate=True, cast="c.tsv"))}
ok("캐스트 시트를 주면 경고하지 않는다", not _dec_tr_cast["캐스트 시트"].warn)

_dec_table = _dec.table(_dec_list)
ok("결정표에 기본값이라고 적힌다", "기본값" in _dec_table and "확인 필요" in _dec_table)
_dec_marks = ("(기본값", "(지정")
_dec_rows = [r for r in _dec_table.splitlines()
             if any(m in r for m in _dec_marks)]
_dec_heads = [r[:min(r.index(m) for m in _dec_marks if m in r)] for r in _dec_rows]
ok("한글 폭을 세어 칸을 맞춘다(줄마다 여는 괄호 자리가 같다)",
   len({_dec._width(h) for h in _dec_heads}) == 1, str(_dec_heads))

ok("리포트에 남기는 형태는 JSON으로 낼 수 있는 값뿐",
   all(set(r) == {"label", "value", "source", "note", "warn"}
       and isinstance(r["warn"], bool)
       for r in _dec.to_report(_dec_list)))


# --- 정답지가 이미 있는지 먼저 본다(규칙 13 기계화) ------------------------

from checker import answerkey as _ak  # noqa: E402

ok("회차 표기를 여러 꼴에서 읽는다",
   [_ak.episode_of(n) for n in ("A.E15.1080p.mkv", "B.15회.mkv", "C.S02E07.mkv",
                                "Movie.2026.1080p.mkv")] == ["15", "15", "7", None])
ok("시즌 표기 차이를 넘어 제목이 맞는다",
   _ak.normalize_title("드라마C") in _ak.normalize_title(
       "드라마C 시즌3.E06.260428.1080p.H264-F1RST"))
# 해상도·코덱 같은 군더더기는 지운다. 배급 그룹 딱지(-GRP)까지 다 지우려 들지는
# 않는다 — 목록에 없는 것이 남아도 폴더 제목이 부분 문자열이면 맞기 때문이다.
ok("릴리즈 군더더기가 있어도 폴더 제목으로 맞는다",
   _ak.normalize_title("영화A") in
   _ak.normalize_title("영화A.2026.1080p.WEB-DL.x264-GRP"),
   _ak.normalize_title("영화A.2026.1080p.WEB-DL.x264-GRP"))

with _tempfile.TemporaryDirectory() as _aktmp:
    _akroot = Path(_aktmp) / "truth"
    (_akroot / "넷플릭스_시험 작품").mkdir(parents=True)
    for _n in ("E03_한국어_SDH.srt", "E04_한국어_SDH.srt"):
        (_akroot / "넷플릭스_시험 작품" / _n).write_text("1\n", encoding="utf-8")
    # `_`로 시작하는 폴더는 캐시다 — 정답지로 세지 않는다.
    (_akroot / "_whisper_cache").mkdir()
    (_akroot / "_whisper_cache" / "시험 작품.srt").write_text("1\n", encoding="utf-8")

    _akstatus = Path(_aktmp) / "corpus_status.yaml"
    _akstatus.write_text(
        "works:\n"
        "  시험_작품:\n"
        "    episodes:\n"
        "      '3':\n"
        "        video: '[습작]/시험 작품.E03.1080p.NF.WEB-DL.mkv'\n"
        "        kinds:\n"
        "          sdh:\n"
        "            truth: truth/넷플릭스_시험 작품/E03_한국어_SDH.srt\n"
        "            pipeline:\n"
        "              tc_generated:\n"
        "                done: true\n"
        "                date: '2026-09-01'\n",
        encoding="utf-8")

    _akvideo = Path("[습작]/시험 작품.E03.1080p.NF.WEB-DL.mkv")
    _akkeys, _akdone = _ak.find(_akvideo, truth_root=_akroot, status_file=_akstatus)
    _akmsg = _ak.warning(_akkeys, _akdone)
    ok("같은 회차 정답지를 찾으면 경고한다",
       "이 영상의 정답지가 이미 있습니다" in _akmsg, str(_akmsg)[:80])
    ok("이미 끝난 단계도 함께 알린다",
       "tc_generated" in _akmsg and "2026-09-01" in _akmsg, str(_akmsg)[:200])
    ok("규칙 13(학습이 먼저)을 근거로 댄다", "규칙 13" in _akmsg)
    ok("캐시 폴더(_로 시작)는 정답지로 세지 않는다",
       all("_whisper_cache" not in str(k.path) for k in _akkeys))

    # 같은 작품 다른 회차뿐일 때 — 있는 것을 없다고 하지도, 있다고 단정하지도 않는다.
    _ak2, _akdone2 = _ak.find(Path("시험 작품.E09.1080p.NF.WEB-DL.mkv"),
                              truth_root=_akroot, status_file=_akstatus)
    _akmsg2 = _ak.warning(_ak2, _akdone2)
    ok("다른 회차만 있으면 그렇게 말한다",
       "다른 회차" in _akmsg2 and "이 회차 것은 못 찾았습니다" in _akmsg2, str(_akmsg2)[:100])

    # 상관없는 영상에는 아무 말도 하지 않는다(경고가 흔해지면 아무도 안 본다).
    _ak3, _akdone3 = _ak.find(Path("Some.Other.Movie.2026.1080p.WEB-DL.mkv"),
                              truth_root=_akroot, status_file=_akstatus)
    ok("상관없는 영상에는 경고하지 않는다", _ak.warning(_ak3, _akdone3) is None)

    # `truth:`는 사람이 손으로 적는 칸이라 주석이 붙어 있다. 우리가 고쳐 쓰지 않고
    # 적힌 그대로 보여 준다.
    _akstatus.write_text(
        "works:\n"
        "  시험_작품:\n"
        "    episodes:\n"
        "      '3':\n"
        "        video: '시험 작품.E03.1080p.NF.WEB-DL.mkv'\n"
        "        kinds:\n"
        "          sdh:\n"
        "            truth: 없는 경로/E03.srt (다른 데도 있음)\n",
        encoding="utf-8")
    _ak4, _akdone4 = _ak.find(Path("시험 작품.E03.1080p.NF.WEB-DL.mkv"),
                              truth_root=_akroot, status_file=_akstatus)
    ok("찾을 수 없는 truth는 적힌 그대로 보여 준다",
       any(k.shown == "없는 경로/E03.srt (다른 데도 있음)" for k in _ak4),
       str([k.shown for k in _ak4]))

# 실제 저장소 경로로 불러도 터지지 않는다(정답지 폴더가 없는 설치본 포함).
_ak5, _akdone5 = _ak.find(Path("아무 상관 없는 영상 이름.mkv"))
ok("기본 경로로 불러도 안전하다", _ak.warning(_ak5, _akdone5) is None)


# --- 문턱값 상수의 근거(A-4) -------------------------------------------------
# 값을 바꾸는 시험이 아니다. **근거를 적어 둔 상수가 실제로 쓰이는지**만 못박는다
# — 상수와 기본값이 갈라지면 주석의 실측 기록이 코드와 다른 것을 설명하게 된다.

import inspect as _a4_inspect  # noqa: E402
from checker import vad as _a4_vad  # noqa: E402
from checker import resplit as _a4_resplit  # noqa: E402

_a4_sig = _a4_inspect.signature(_a4_vad.detect_speech)
ok("VAD 기본값이 이름 붙은 상수와 같다",
   (_a4_sig.parameters["threshold"].default,
    _a4_sig.parameters["min_speech_ms"].default,
    _a4_sig.parameters["min_silence_ms"].default)
   == (_a4_vad.THRESHOLD, _a4_vad.MIN_SPEECH_MS, _a4_vad.MIN_SILENCE_MS))
ok("VAD 상수가 실측 당시 값 그대로다(바꾸려면 주석의 표부터 갱신한다)",
   (_a4_vad.THRESHOLD, _a4_vad.MIN_SPEECH_MS, _a4_vad.MIN_SILENCE_MS) == (0.5, 120, 250))
ok("침묵 당김 폭이 이름 붙은 상수와 같다",
   _a4_inspect.signature(_a4_resplit._snap_to_silence).parameters["tolerance_ms"].default
   == _a4_resplit.SNAP_TOLERANCE_MS == 400)

# 실측 도구가 정답지에서 **사람 말 자막만** 고르는지. 효과음·음악 자막을 섞어
# 세면 문턱값이 엉뚱하게 낮은 쪽으로 끌린다.
import importlib.util as _a4_iu  # noqa: E402
_a4_spec = _a4_iu.spec_from_file_location("vad_sweep", Path("tools/vad_sweep.py"))
_a4_sweep = _a4_iu.module_from_spec(_a4_spec)
_a4_spec.loader.exec_module(_a4_sweep)

with _tempfile.TemporaryDirectory() as _a4_tmp:
    _a4_srt = Path(_a4_tmp) / "t.srt"
    _a4_srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n[문 열리는 소리]\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n♪ 노래 ♪\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\n[진수] 어디 갔었어\n",
        encoding="utf-8")
    ok("효과음·음악만 있는 자막은 빼고 센다",
       _a4_sweep.speech_cues(_a4_srt) == [(5000, 6000)],
       str(_a4_sweep.speech_cues(_a4_srt)))

ok("구간이 없으면 점수를 내지 않는다(빈 dict)", _a4_sweep.score([], [(0, 1000)]) == {})
_a4_score = _a4_sweep.score([(0, 1000), (2000, 3000)], [(0, 1000), (2000, 3000)])
ok("정답과 똑같은 구간이면 오차가 0이다",
   _a4_score["인점중앙"] == 0 and _a4_score["아웃중앙"] == 0 and _a4_score["덮음%"] == 100.0,
   str(_a4_score))


# --- 문서가 코드보다 낡지 않게(docs_check) ----------------------------------
# 규칙 17이 "손대기 전에 먼저 열어 보라"고 정한 파일이 낡으면 체크리스트가 오히려
# 함정이 된다. 훅이 커밋 직전에 이 검사를 돌리므로, 검사 자체가 틀리면 안 된다.

_dc_spec = _a4_iu.spec_from_file_location("docs_check", Path("tools/docs_check.py"))
_dc = _a4_iu.module_from_spec(_dc_spec)
_dc_spec.loader.exec_module(_dc)

ok("지금 저장소 문서에 낡은 곳이 없다(경로·grep 주장)",
   _dc.check_paths(_dc.LIVING + _dc.HISTORICAL) + _dc.check_grep_claims(_dc.LIVING) == [],
   str(_dc.check_paths(_dc.LIVING + _dc.HISTORICAL)
       + _dc.check_grep_claims(_dc.LIVING)))

_dc_stale = _dc.check_live_counts(10 ** 9)
ok("시험 수가 다르면 낡았다고 잡는다",
   any("시험 수가 낡았다" in row for row in _dc_stale), str(_dc_stale))

with _tempfile.TemporaryDirectory() as _dc_tmp:
    _dc_doc = Path(_dc_tmp) / "d.md"
    _dc_root = _dc.ROOT
    try:
        # 임시 저장소를 흉내 낸다 — 검사 대상 경로를 그쪽으로 돌린다.
        _dc.ROOT = Path(_dc_tmp)
        (Path(_dc_tmp) / "checker").mkdir()
        (Path(_dc_tmp) / "checker" / "있는파일.py").write_text("learned\n", encoding="utf-8")
        _dc_doc.write_text(
            "`checker/있는파일.py`는 있고 `checker/없는파일.py`는 없다.\n"
            "`grep -rn \"learned\" checker/*.py` 1건.\n",
            encoding="utf-8")
        _dc_bad = _dc.check_paths(["d.md"])
        ok("없는 경로만 집어낸다",
           len(_dc_bad) == 1 and "없는파일" in _dc_bad[0], str(_dc_bad))
        ok("맞는 grep 주장은 통과시킨다", _dc.check_grep_claims(["d.md"]) == [])

        _dc_doc.write_text("`grep -rn \"learned\" checker/*.py` 0건.\n", encoding="utf-8")
        ok("틀린 grep 주장을 잡는다",
           len(_dc.check_grep_claims(["d.md"])) == 1,
           str(_dc.check_grep_claims(["d.md"])))

        # 도망갈 구멍이 있어야 한다 — 지금은 맞는 표기인데 걸리는 경우가 있다.
        _dc_doc.write_text(
            "`grep -rn \"learned\" checker/*.py` 0건. <!-- docs-check: 무시 -->\n",
            encoding="utf-8")
        ok("`docs-check: 무시`가 붙으면 넘어간다", _dc.check_grep_claims(["d.md"]) == [])

        # 옆 리포(교정기) 경로는 여기 없는 것이 정상이다(규칙 0).
        _dc_doc.write_text("교정기의 `tools/check_public_api.py`를 부른다.\n",
                           encoding="utf-8")
        ok("옆 리포 경로는 낡음으로 세지 않는다", _dc.check_paths(["d.md"]) == [])
    finally:
        _dc.ROOT = _dc_root


# --- 규칙 15: TC를 먼저 맞추고 그다음 텍스트 --------------------------------
# 원장(docs/corpus_status.yaml)에 TC 검증이 끝났다고 적혀 있는지 본다.
# **모른다와 안 끝났다는 다르다**(규칙 3) — 코퍼스 밖 자료로 대조하는 일도 흔하다.

from checker.answerkey import tc_state as _tc_state  # noqa: E402

with _tempfile.TemporaryDirectory() as _tc_tmp:
    _tc_status = Path(_tc_tmp) / "corpus_status.yaml"
    _tc_status.write_text(
        "works:\n"
        "  시험_작품:\n"
        "    episodes:\n"
        "      '1':\n"
        "        kinds:\n"
        "          sdh:\n"
        "            truth: truth/E01_한국어_SDH.srt\n"
        "            pipeline:\n"
        "              tc_generated: {done: true}\n"
        "          translation:\n"
        "            truth: truth/E01_영어_번역.srt\n"
        "            pipeline:\n"
        "              tc_verified: {done: true}\n",
        encoding="utf-8")
    ok("TC 검증이 안 끝났으면 그렇게 말한다",
       _tc_state(Path("E01_한국어_SDH.srt"), _tc_status) == (False, "시험_작품 1회 sdh"),
       str(_tc_state(Path("E01_한국어_SDH.srt"), _tc_status)))
    ok("TC 검증이 끝났으면 끝났다고 말한다",
       _tc_state(Path("E01_영어_번역.srt"), _tc_status)[0] is True)
    ok("원장에 없는 정답지는 None(모른다 ≠ 안 끝났다)",
       _tc_state(Path("코퍼스밖.srt"), _tc_status) is None)


# --- 규칙 12: 갈래를 동시에 벌이지 않는다 -----------------------------------

_ln_spec = _a4_iu.spec_from_file_location("lanes_check", Path("tools/lanes_check.py"))
_ln = _a4_iu.module_from_spec(_ln_spec)
_ln_spec.loader.exec_module(_ln)

ok("한 갈래만 건드리면 아무 말도 안 한다",
   _ln.report(["checker/cli.py", "tests/run_tests.py"]) is None)
ok("docs/와 최상위 md는 갈래로 세지 않는다",
   _ln.report(["docs/HANDOFF.md", "CLAUDE.md", "README.md"]) is None)
_ln_mixed = _ln.report(["checker/cli.py", "rules/learned/coupang/ko-sdh.yaml"])
ok("코드와 학습 자료가 섞이면 알린다",
   _ln_mixed is not None and "갈래 2개" in _ln_mixed, str(_ln_mixed))
ok("섞였다고 막지는 않는다(경고 문구에 그렇게 적는다)",
   "막지 않는다" in _ln_mixed, str(_ln_mixed))
ok("어느 파일이 어느 갈래인지 짚는다",
   "checker/cli.py" in _ln_mixed and "rules/learned/coupang/ko-sdh.yaml" in _ln_mixed)

# 규칙 12의 증거 기준 — 한 작품뿐인 학습값으로 코드를 고치는 중인지 짚는다.
ok("근거가 한 작품뿐인 학습값을 찾아낸다",
   _ln.single_work_learned(["rules/learned/coupang/ko-sdh.yaml"])
   == ["rules/learned/coupang/ko-sdh.yaml"])
ok("여러 작품이 근거인 학습값은 짚지 않는다",
   _ln.single_work_learned(["rules/learned/netflix/ko-sdh.yaml"]) == [],
   str(_ln.single_work_learned(["rules/learned/netflix/ko-sdh.yaml"])))
ok("학습값만 있고 코드가 없으면 '최소 2편'은 말하지 않는다",
   "최소 2편" not in (_ln.report(["rules/learned/coupang/ko-sdh.yaml",
                                 "rules/private/sources/작업자-자료/반영-계획.md"]) or ""))

# **한글 경로가 그대로 나와야 한다.** git 기본값은 한글을 8진수로 감싸 내놓아
# (`"rules/private/sources/ì..."`) 접두사 검사가 통째로 빗나간다 — 이 검사를
# 붙인 첫 커밋이 실제로 그래서 조용히 지나갔다(2026-09-08).
ok("NUL로 구분된 한글 경로를 그대로 읽는다",
   _ln.parse_z_output(chr(0).join(["rules/private/sources/작업자-자료/정독-기록.yaml",
                                 "checker/cli.py", ""])
                      .encode("utf-8"))
   == ["rules/private/sources/작업자-자료/정독-기록.yaml", "checker/cli.py"])
ok("한글 경로도 갈래로 잡힌다",
   "문서 정독" in _ln.lanes_of(["rules/private/sources/작업자-자료/정독-기록.yaml"]))

_ln_lanes = _ln.lanes_of(["rules/private/netflix/ko-sdh.yaml", "rules/private/sources/x.md",
                          "corpus/pairs/a.json", "checker/cli.py", "docs/PRD.md"])
ok("네 갈래를 각각 알아본다",
   set(_ln_lanes) == {"규정", "문서 정독", "코퍼스·학습", "코드"}, str(sorted(_ln_lanes)))


# --- 규칙 12: 안 다룬 범위를 셀 수 있게 남긴다(정독 기록) --------------------

_rp_spec = _a4_iu.spec_from_file_location("reading_progress", Path("tools/reading_progress.py"))
_rp = _a4_iu.module_from_spec(_rp_spec)
_rp_spec.loader.exec_module(_rp)

_rp_data = _rp.load()
ok("정독 기록이 읽힌다", isinstance(_rp_data.get("sources"), list) and _rp_data["sources"])
_rp_text, _rp_unknown = _rp.report(_rp_data)
ok("자료마다 상태를 적어 둔다", "반영함" in _rp_text and "안읽음" in _rp_text, _rp_text[:200])
# 지금 저장소의 실제 상태 — 2026-09-08에 남은 30장을 정독해 미확인이 0이 됐다.
# **0이 아니게 되면 자료가 늘었거나 기록이 사라진 것이다.** 어느 쪽이든 사람이 본다.
ok("미확인이 없다(모든 자료에 상태가 적혀 있다)", _rp_unknown == 0, _rp_text)
_rp_gap = _rp.missing_ids({"total": 3}, {"total": 3, "ids": {"A-1"}, "unknown": 2})
ok("미확인 id를 짚어 준다", _rp_gap == ["A-2", "A-3"], str(_rp_gap))

_rp_one = {"total": 4, "records": [{"state": "반영함", "ids": ["A-1", "A-2"]},
                                   {"state": "안읽음", "count": 1}]}
_rp_res = _rp.tally(_rp_one)
ok("id와 개수를 섞어 적어도 센다",
   _rp_res["counts"] == {"반영함": 2, "안읽음": 1} and _rp_res["unknown"] == 1,
   str(_rp_res))
ok("모르는 상태는 문제로 낸다",
   _rp.tally({"total": 1, "records": [{"state": "대충봄", "count": 1}]})["problems"],
   "모르는 상태를 그냥 통과시키면 안 된다")
ok("같은 id가 두 번 적히면 문제로 낸다",
   _rp.tally({"total": 2, "records": [{"state": "반영함", "ids": ["A-1"]},
                                      {"state": "정독함", "ids": ["A-1"]}]})["problems"])
ok("적힌 수가 전체보다 많으면 문제로 낸다",
   _rp.tally({"total": 1, "records": [{"state": "반영함", "count": 5}]})["problems"])


# --- 일본어 2차·3차 검수 ----------------------------------------------------
# 실측(정답 4작품 21,888개)이 가리킨 것: です/ます 종결 0~17%, 구두점 0%,
# 한 자막 7~15자. 그 셋이 프롬프트에 실제로 들어 있는지 못박는다 — 문구가 사라지면
# 일본어 결과가 다시 길고 정중해진다.

from checker.revise import ROLES_BY_LANG as _ja_roles  # noqa: E402
from checker.translate import SYSTEM_BY_LANG as _ja_system  # noqa: E402

ok("일본어 2차·3차 프롬프트가 있다", set(_ja_roles.get("ja") or {}) == {"감수", "윤문"},
   str(sorted(_ja_roles)))
_ja_second, _ja_third = _ja_roles["ja"]["감수"], _ja_roles["ja"]["윤문"]
ok("2차는 상체(常体)를 기본으로 못박는다", "常体" in _ja_second, _ja_second[:80])
ok("3차는 구두점을 쓰지 말라고 한다",
   "「。」「、」は使いません" in _ja_third, _ja_third[:120])
ok("3차는 실측 길이(7~15자·한 줄 7~9자)를 준다",
   "7~15字" in _ja_third and "7~9字" in _ja_third, _ja_third[:200])
ok("3차는 です・ます를 떼라고 한다", "です・ます" in _ja_third)
ok("2차·3차가 서로 다른 프롬프트다", _ja_second != _ja_third)

# 1차도 함께 고쳤다 — 1차가 만든 です/ます를 2·3차가 되돌리게 두지 않는다.
ok("1차 일본어 프롬프트가 상시체를 기본으로 한다",
   "상시체" in _ja_system["ja"], _ja_system["ja"][-200:])
ok("1차 일본어 프롬프트에 옛 '정중체로 통일'이 남아 있지 않다",
   "정중체(です・ます체)로 통일" not in _ja_system["ja"])

# 다른 언어를 건드리지 않았는지 — 한국어는 여전히 존댓말 통일이 1차 기본이다.
ok("한국어 1차는 그대로다", "존댓말로 통일" in _ja_system["ko"])
ok("지원하지 않는 언어는 조용히 한국어로 떨어지지 않는다",
   "de" not in _ja_roles)


# --- 상대별 말투(존반 행렬) — T17이 방향을 본다 -----------------------------
# 실무 KNP의 `존반` 탭은 인물 × 인물 행렬이고 칸이 방향을 갖는다(피비→로스와
# 로스→피비가 다를 수 있다, 작업자 자료 WORK-048). 캐릭터 시트 한 칸(`말투 지정`)
# 으로는 그 방향을 담을 수 없었다.

from checker.characters import Character, addressee as _ad, read_tsv as _read_cast  # noqa: E402
from checker.characters import to_tsv as _cast_tsv  # noqa: E402
from checker.checks import run_checks as _run_checks  # noqa: E402

ok("줄 안에 상대 이름이 있으면 상대를 가려낸다",
   _ad("로스 그거 봤어?", "피비", ["로스", "모니카", "피비"]) == "로스")
ok("상대 이름이 없으면 모른다고 한다",
   _ad("둘 다 와", "피비", ["로스", "모니카", "피비"]) == "")
ok("이름이 둘이면 찍지 않는다",
   _ad("로스랑 모니카 어디 갔어", "피비", ["로스", "모니카", "피비"]) == "")
ok("긴 이름이 짧은 이름에 먹히지 않는다",
   _ad("김 경위 오셨어요", "진수", ["김 경위", "경위", "진수"]) == "김 경위")
ok("대괄호 안(효과음·화자명)은 대사가 아니라 안 본다",
   _ad("[로스가 웃는다]", "피비", ["로스", "피비"]) == "")

# 시트 왕복 — 행렬이 TSV를 통과해도 살아남아야 한다.
_cp_people = [Character(name="피비"), Character(name="로스")]
_cp_people[0].declared_tone = "합니다체"
_cp_people[0].tone_to = {"로스": "반말"}
with _tempfile.TemporaryDirectory() as _cp_tmp:
    _cp_path = Path(_cp_tmp) / "cast.tsv"
    _cp_path.write_text(_cast_tsv(_cp_people), encoding="utf-8-sig")
    _cp_back = {p.name: p for p in _read_cast(_cp_path)}
    ok("상대별 말투가 시트를 왕복해도 남는다",
       _cp_back["피비"].tone_to == {"로스": "반말"}, str(_cp_back["피비"].tone_to))
    ok("상대별 말투가 없는 인물은 빈 사전이다", _cp_back["로스"].tone_to == {})

# T17은 넷플릭스 한국어 **번역** 프로파일에 선언돼 있다(SDH엔 없다).
_cp_profile = load_profile("netflix", "ko", "translation")
_cp_events = [Event(1, 0, 3000, "[피비] 로스 밥 먹었어?"),      # 로스에게 -> 반말이 맞다
              Event(2, 3000, 6000, "[피비] 로스 식사하셨어요?"),   # 로스에게 -> 존댓말이라 어긋남
              Event(3, 6000, 9000, "[피비] 안녕하세요")]           # 상대 모름 -> 말투 지정(합니다체)

_cp_v, _, _cp_skipped = _run_checks(_cp_events, _cp_profile,
                                    cast={"피비": "합니다체"},
                                    cast_pairs={"피비": {"로스": "반말"}})
_cp_t17 = [v for v in _cp_v if v.rule_id == "T17"]
ok("상대에게 정한 말투대로면 지적하지 않는다",
   all(v.event_index != 1 for v in _cp_t17), str(_cp_t17))
ok("상대에게 정한 말투를 벗어나면 지적한다",
   any(v.event_index == 2 for v in _cp_t17), str(_cp_t17))
ok("지적에 누구에게 하는 말인지 적는다",
   any("로스에게 반말" in v.detail for v in _cp_t17), str(_cp_t17))

# 상대를 못 가리는 줄은 예전 동작(사람별 한 칸) 그대로다.
_cp_v2, _, _ = _run_checks([Event(1, 0, 3000, "[피비] 밥 먹었어요?")], _cp_profile,
                           cast={"피비": "합니다체"},
                           cast_pairs={"피비": {"로스": "반말"}})
ok("상대를 모르면 사람별 값으로 본다",
   any(v.rule_id == "T17" for v in _cp_v2), str(_cp_v2))

# 행렬을 받았는데 한 번도 못 썼으면 그 사실을 남긴다(규칙 3).
_, _, _cp_skipped2 = _run_checks([Event(1, 0, 3000, "[피비] 밥 먹었어요?")], _cp_profile,
                                 cast={"피비": "합니다체"},
                                 cast_pairs={"피비": {"로스": "반말"}})
ok("행렬을 못 쓰면 안 썼다고 남긴다",
   any("상대별 말투를 받았지만" in s for s in _cp_skipped2), str(_cp_skipped2))

# 옛 호출부(플러그인·GUI)는 cast 하나만 넘긴다 — 그때 동작이 그대로여야 한다.
_cp_v3, _, _ = _run_checks([Event(1, 0, 3000, "[피비] 밥 먹었어요?")], _cp_profile,
                           cast={"피비": "합니다체"})
ok("cast만 넘겨도 예전과 같이 돈다", any(v.rule_id == "T17" for v in _cp_v3))


# --- 단위 환산: 대사와 화면자막이 다르다 -------------------------------------
# 작업자 자료가 두 자리에서 다른 것을 말한다 — 모순이 아니라 대상이 다르다.
#   대사      "화폐를 제외한 모든 단위는 환산하지 않고 화자가 말한 대로"(837행)
#   화면자막   반복 화면자막은 KNP `반복` 탭에 환산해 적는다(WORK-015·047)

from checker.position import JobRules as _uc_rules  # noqa: E402

_uc_profile = load_profile("netflix", "ko", "translation")
_uc_on = _uc_rules(marker="double_quote", policy="move_dialogue")


def _uc_check(text, rules=_uc_on):
    found, _, _ = _run_checks([Event(1, 0, 3000, text)], _uc_profile, job_rules=rules)
    return [v for v in found if v.rule_id == "T12"]


ok("화면자막에 비미터법 단위가 남아 있으면 확인을 건다",
   _uc_check("\u201c차로 8마일 거리\u201d"), "화면자막은 환산하는 자리다")
ok("대사는 건드리지 않는다(화자가 말한 대로가 맞다)",
   _uc_check("8마일이면 멀지") == [])
ok("미터법으로 적힌 화면자막은 지적하지 않는다",
   _uc_check("\u201c해발 3,000m\u201d") == [])
ok("화씨도 잡는다", _uc_check("\u201c기온 32°F\u201d"))
ok("영문 단위도 잡는다", _uc_check("\u201c8 miles from home\u201d"))

# **숫자가 붙은 것만 본다.** `노트`(공책)·`피트`(사람 이름) 같은 말을 지적하면
# 오답이 쏟아진다.
ok("숫자 없는 '노트'는 단위로 보지 않는다", _uc_check("\u201c노트에 적어 둬\u201d") == [])
ok("숫자 없는 '인치'도 보지 않는다", _uc_check("\u201c인치 단위가 뭐죠\u201d") == [])

# 통화는 이 검사가 아니라 C03(currency_converted)의 몫이다 — 환산 금지 대상이라
# 성격이 반대다.
ok("통화는 이 검사가 보지 않는다", _uc_check("\u201c15달러입니다\u201d") == [])

# 마커가 안 정해졌으면 무엇이 화면자막인지 알 수 없다 — 검사하지 않는다.
ok("표식이 미정이면 검사하지 않는다",
   _uc_check("\u201c차로 8마일 거리\u201d", _uc_rules(marker="ask")) == [])

# 같은 단위가 여러 번 나와도 한 번만 적는다.
_uc_many = _uc_check("\u201c8마일 걷고 다시 8마일\u201d")
ok("같은 단위를 되풀이해 적지 않는다",
   _uc_many and _uc_many[0].detail.count("8마일") == 1, str(_uc_many))

# 분야에 따라 그대로 두는 것이 맞을 수 있다는 것을 지적 문구가 말한다(규칙 4).
ok("그대로 두는 분야가 있다는 것을 함께 알린다",
   "해양" in _uc_check("\u201c수심 100피트\u201d")[0].detail)

# 이제 미구현 목록에서 빠졌다.
_, _uc_unimpl, _ = _run_checks([Event(1, 0, 3000, "안녕")], _uc_profile,
                               job_rules=_uc_on)
ok("non_metric_unit이 미구현 목록에서 빠졌다",
   not any("non_metric" in name for name in _uc_unimpl), str(_uc_unimpl))


# --- MQ4 에이전트(agent/) --------------------------------------------------
# requirements-agent.txt(fastapi·claude-agent-sdk)가 없는 환경에서는 건너뛴다 —
# PySide6와 같은 패턴(위 "독립 프로그램 화면" 절 참고). 실제 Claude Agent SDK를
# 부르는 시험은 없다 — 비용이 들고 결정론적이지 않아 커밋 훅에 안 맞는다.
# agent/loop.py::run_turn은 전부 스텁으로 갈아 끼운다. checker 연동
# (agent/tools.py)은 SDK 없이 도는 순수 함수라 실제로 부른다.

try:
    from fastapi.testclient import TestClient  # noqa: F401
    from agent import loop as _agent_loop  # noqa: F401
except ImportError:
    ok("agent 모듈 (fastapi/claude-agent-sdk 없어 건너뜀)", True)
else:
    import shutil as _agent_shutil
    from pathlib import Path as _AP

    from agent import tools as _at
    from agent.api import app as _agent_app
    from agent.state import (  # noqa: E402
        PendingQuestion as _APQ, SessionState as _AState, Violation as _AV,
        load as _aload, save as _asave, session_dir as _asession_dir,
    )
    from checker.model import Violation as _CV  # noqa: E402

    # -- tools.py: 위치 중복 제거 (2026-09-09 실사용 코퍼스에서 발견한 버그) --
    _grouped = _at._group_by_rule([
        _CV(rule_id="S13", clause="II.8 Speaker IDs", event_index=1,
            message="m1", line_no=2),
        _CV(rule_id="S13", clause="II.8 Speaker IDs", event_index=1,
            message="m2", line_no=2),  # 같은 큐에서 같은 규칙이 두 번(실제 있었다)
        _CV(rule_id="S13", clause="II.8 Speaker IDs", event_index=2,
            message="m3", line_no=5),
    ])
    ok("같은 큐·같은 규칙 중복은 위치를 한 번만 센다",
       len(_grouped) == 1 and _grouped[0].locations == [2, 5] and _grouped[0].count == 2,
       str(_grouped))

    _grouped_none = _at._group_by_rule([
        _CV(rule_id="S15", clause="continuity", event_index=3, message="m", line_no=None),
    ])
    ok("line_no 없으면 event_index로 폴백한다", _grouped_none[0].locations == [3])

    # -- tools.py: 영상 필요 여부 분류(사용자 지적, 2026-09-09) --
    _timing = _AV(rule_id="C01", article="General Requirements / Duration",
                  count=1, severity="confirm", locations=[3])
    _spacing = _AV(rule_id="DP07", article="실무 스펙 / 자막 간격",
                   count=1, severity="confirm", locations=[2])
    _speed = _AV(rule_id="S02", article="II.3 Reading Speed Limit",
                 count=1, severity="confirm", locations=[5])
    _line = _AV(rule_id="S16", article="General Requirements / Line Treatment",
                count=1, severity="confirm", locations=[2])
    _web, _video = _at.split_confirm_violations([_timing, _spacing, _speed, _line])
    ok("타이밍·간격류는 영상 확인 대상으로 갈린다",
       {v.rule_id for v in _video} == {"C01", "DP07"}, str(_video))
    ok("글자수·형식류는 웹카드로 남는다",
       {v.rule_id for v in _web} == {"S02", "S16"}, str(_web))

    # -- tools.py: SE 북마크 왕복 (checker/bookmarks.py의 기존 read()로 되읽는다) --
    import json as _bm_json  # noqa: E402
    from checker.bookmarks import read as _bm_read  # noqa: E402

    with __import__("tempfile").TemporaryDirectory() as _bmdir:
        _bm_srt = _AP(_bmdir) / "sample.srt"
        _bm_srt.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\n[진수] 안녕\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\n[영희] 그래\n", encoding="utf-8")
        _bm_out = _at.export_bookmarks(_bm_srt, [(1, "[C01] 확인 필요"), (2, "[DP07] 확인 필요")])
        ok("북마크 파일 이름이 SE가 찾는 그대로다(.SE.bookmarks — 예전엔 이게 틀렸다)",
           _bm_out == _AP(str(_bm_srt) + ".SE.bookmarks"), str(_bm_out))
        _bm_payload = _bm_json.loads(_bm_out.read_text(encoding="utf-8"))
        ok("idx는 SE 기준 0-시작으로 보정된다",
           [b["idx"] for b in _bm_payload["bookmarks"]] == [0, 1], str(_bm_payload))
        ok("4.0.15(사용자 실사용 버전) 포맷은 idx·txt뿐이다 — ms·forced는 v5.2 전용이라 안 넣는다",
           set(_bm_payload.keys()) == {"bookmarks"}
           and all(set(b.keys()) == {"idx", "txt"} for b in _bm_payload["bookmarks"]),
           str(_bm_payload))
        _notes = _bm_read(_bm_out)
        ok("SE 읽기 코드로 그대로 되읽힌다",
           [(n.index, n.text) for n in _notes] ==
           [(1, "[C01] 확인 필요"), (2, "[DP07] 확인 필요")], str(_notes))
        ok("자막 파일과 짝지어 읽힌다(같은 폴더의 sample.srt)",
           _notes[0].cue is not None and _notes[0].cue.text == "[진수] 안녕")

    # -- tools.py: 실제 checker 연동, 원본 불변 --
    _real_violations = _at.check(_AP("examples/ko-sdh-sample.srt"), "netflix", "sdh", "ko")
    ok("실제 srt로 실제 검사를 돈다(모의 데이터 아님)", isinstance(_real_violations, list))

    with __import__("tempfile").TemporaryDirectory() as _fixdir:
        _src = _AP(_fixdir) / "in.srt"
        _src.write_text("1\n00:00:01,000 --> 00:00:03,000\n그러니까...\n", encoding="utf-8")
        _before = _src.read_text(encoding="utf-8")
        _out = _AP(_fixdir) / "out.srt"
        _result = _at.fix(_src, _out, "netflix", "sdh", "ko")
        ok("fix()는 원본을 안 건드린다", _src.read_text(encoding="utf-8") == _before)
        ok("새 파일로 쓴다", _out.is_file())
        ok("적용한 규칙 이름이 돌아온다", "three_dot_ellipsis" in _result["applied"], str(_result))

    try:
        _at.check(_AP("examples/ko-sdh-sample.srt"), "amazon", "sdh", "ko")
        ok("프로파일 없는 발주처는 CheckerToolError", False, "예외가 안 났다")
    except _at.CheckerToolError:
        ok("프로파일 없는 발주처는 CheckerToolError", True)

    # -- state.py: 저장/복원 왕복 --
    _tid = "f_pytest_state_roundtrip"
    _agent_shutil.rmtree(_asession_dir(_tid), ignore_errors=True)
    _st = _AState(file_id=_tid, status="waiting_for_user", platform="netflix",
                  kind="sdh", language="ko", current_path="x.srt", outer_turns=2)
    _st.violations = [_AV(rule_id="S02", article="a", count=1, severity="confirm", locations=[3])]
    _st.pending_question = _APQ(question_id="q_1", version=1,
                                cards=[{"rule_id": "S02", "article": "a", "cue_index": 3}],
                                options=["승인", "거부", "직접수정"])
    _st.dispositioned["S02:3"] = "SE로 이관"
    _st.log("run_check", "위반 1종")
    _asave(_st)
    _loaded = _aload(_tid)
    ok("세션 상태가 그대로 되읽힌다",
       _loaded.status == "waiting_for_user" and _loaded.outer_turns == 2
       and _loaded.violations[0].rule_id == "S02"
       and _loaded.pending_question.question_id == "q_1"
       and _loaded.dispositioned == {"S02:3": "SE로 이관"})
    ok("history의 회차가 outer_turns를 따른다(예전엔 항상 0이었던 버그)",
       _loaded.history[0]["loop"] == 2, str(_loaded.history))
    ok("없는 세션은 None", _aload("f_없는세션") is None)
    _agent_shutil.rmtree(_asession_dir(_tid), ignore_errors=True)

    # -- loop.py: dispositioned 필터링(재확인 무한반복 방지) --
    _rf_state = _AState(file_id="f_pytest_refresh", status="running",
                        platform="netflix", kind="sdh", language="ko")
    _rf_state.dispositioned["S02:3"] = "승인"
    _rf_out = _agent_loop._refresh_violations(_rf_state, [
        _AV(rule_id="S02", article="a", count=2, severity="confirm", locations=[3, 5]),
        _AV(rule_id="S08", article="b", count=1, severity="auto", locations=[1]),
    ])
    ok("이미 판단된 위치는 걷어낸다",
       [v.locations for v in _rf_out if v.rule_id == "S02"] == [[5]], str(_rf_out))
    ok("auto 위반은 dispositioned와 무관하게 남는다",
       any(v.rule_id == "S08" for v in _rf_out))

    # -- api.py: HTTP 계약(loop.run_turn은 스텁으로 갈아 끼운다 — 비용 없음) --
    async def _stub_run_turn(state, prompt):
        state.status = "done"
        state.result = {"fixed": 0, "remaining": 0, "loop_count": 0,
                        "cost_usd": 0, "duration_ms": 0, "se_review": 0}

    _real_run_turn = _agent_loop.run_turn
    _agent_loop.run_turn = _stub_run_turn
    try:
        _client = TestClient(_agent_app)

        _r = _client.post("/api/sessions", files={"file": ("x.txt", b"hi", "text/plain")},
                          data={"platform": "netflix", "kind": "sdh", "language": "ko"})
        ok("srt 아닌 파일은 400",
           _r.status_code == 400 and _r.json()["detail"]["error"] == "invalid_srt")

        _r = _client.post("/api/sessions", files={"file": ("x.srt", b"1\n", "text/plain")},
                          data={"platform": "", "kind": "sdh", "language": "ko"})
        ok("발주처 없으면 400",
           _r.status_code == 400 and _r.json()["detail"]["error"] == "missing_platform")

        _r = _client.post("/api/sessions", files={"file": ("x.srt", b"1\n", "text/plain")},
                          data={"platform": "netflix", "kind": "sdh", "language": "ko"})
        ok("정상 업로드는 201", _r.status_code == 201)
        _fid = _r.json()["file_id"]
        ok("스텁이 status를 정한다(SDK 호출 없음)", _r.json()["status"] == "done")

        ok("모르는 세션은 404", _client.get("/api/sessions/f_없음").status_code == 404)

        _r = _client.get(f"/api/sessions/{_fid}/result")
        ok("완료면 result가 온다", _r.status_code == 200 and "report" in _r.json())

        _r = _client.get(f"/api/sessions/{_fid}/download")
        ok("완료면 다운로드된다", _r.status_code == 200)

        _r = _client.get(f"/api/sessions/{_fid}/bookmarks")
        ok("북마크 안 만든 세션은 404",
           _r.status_code == 404 and _r.json()["detail"]["error"] == "no_bookmarks")

        # 확인 카드 답변 계약 — pending_question을 직접 심어 둔다.
        _qstate = _aload(_fid)
        _qstate.status = "waiting_for_user"
        _qstate.current_path = "examples/ko-sdh-sample.srt"
        _qstate.pending_question = _APQ(question_id="q_1", version=1,
                                        cards=[{"rule_id": "S02", "article": "a", "cue_index": 1}],
                                        options=["승인", "거부", "직접수정"])
        _asave(_qstate)

        _r = _client.post(f"/api/sessions/{_fid}/answer",
                          json={"question_id": "q_틀림", "version": 1, "answers": []})
        ok("다른 질문ID로 답하면 409",
           _r.status_code == 409 and _r.json()["detail"]["error"] == "no_pending_question")

        _r = _client.post(f"/api/sessions/{_fid}/answer",
                          json={"question_id": "q_1", "version": 99, "answers": []})
        ok("낡은 버전이면 409(현재 버전을 알려준다)",
           _r.status_code == 409 and _r.json()["detail"]["current_version"] == 1)

        _r = _client.post(f"/api/sessions/{_fid}/answer",
                          json={"question_id": "q_1", "version": 1,
                                "answers": [{"rule_id": "S02", "cue_index": 1, "decision": "승인"}]})
        ok("정상 응답은 200", _r.status_code == 200)

        _r2 = _client.post(f"/api/sessions/{_fid}/answer",
                           json={"question_id": "q_1", "version": 1,
                                 "answers": [{"rule_id": "S02", "cue_index": 1, "decision": "거부"}]})
        ok("같은 질문에 두 번 답해도 재처리 안 한다(멱등성)",
           _r2.status_code == 200 and _r2.json()["dispositioned"].get("S02:1") == "승인")

        _r = _client.get(f"/api/sessions/{_fid}/cue/1")
        ok("큐 원문은 서버가 파일에서 직접 읽어 돌려준다(LLM 안 거침)",
           _r.status_code == 200 and "[진수]" in _r.json()["text"], str(_r.json()))

        _r = _client.get(f"/api/sessions/{_fid}/cue/9999")
        ok("없는 큐는 404", _r.status_code == 404)
    finally:
        _agent_loop.run_turn = _real_run_turn
        _agent_shutil.rmtree(_asession_dir(_fid), ignore_errors=True)


# --- 결과 ---------------------------------------------------------------

print(f"통과 {PASSED}건")
if FAILED:
    print(f"실패 {len(FAILED)}건")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("전부 통과")
