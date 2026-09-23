# 규정 프로파일 스키마 v1

플랫폼별 자막 규정을 **데이터로** 정의한다. 코드에 값을 박지 않는 이유는 규정이 자주 개정되기 때문이다(넷플릭스 한국어 2025-07-07, 영어 2025-12-19 개정 확인). 규정이 바뀌면 이 디렉터리의 YAML만 고치고 코드는 건드리지 않는다.

> **이 디렉터리에는 코드를 넣지 않는다.** 순수 데이터만 유지해야 나중에 `git subtree split`으로 별도 저장소로 떼낼 수 있다.

## 1. 파일 배치

```
rules/private/
  <platform>/
    common.yaml            kind: common     — SDH·번역 공통 기술 요건
    <lang>-translation.yaml  kind: translation
    <lang>-sdh.yaml          kind: sdh
  sources/                 사람이 읽는 근거 문서(원문 정리). YAML은 여기서 파생된다.
```

## 2. 필수 헤더

모든 파일 맨 위에 온다.

```yaml
schema_version: 1
platform: netflix          # netflix | disney | coupang
language: ko               # ISO 639-1. common 은 language: null 가능
kind: sdh                  # sdh | translation | common
extends: common.yaml       # 같은 플랫폼 디렉터리 기준 상대 경로. common 자신은 생략
status: complete           # complete | partial | unavailable
source:
  official: true           # 플랫폼/정부 공식 문서인가. false면 client를 함께 적어야 한다
  url: "..."
  section: "Korean TTSG Section II"
  revision: "2025-07-07"   # 원문 change log의 최신일
  verified: "2026-08-11"   # 우리가 원문을 확인한 날
```

**`status: unavailable`인 프로파일, 그리고 `official: false`이면서 `source.client`도 없는 프로파일은 로더가 검사에 쓰지 않는다.** 블로그·2차 자료 수치가 조용히 룰이 되는 것을 막는다 — 발주처가 지정한 실무 기준은 `source.client`를 적으면 쓸 수 있다.

## 3. SDH ↔ 번역 자막 섞임 방지 (핵심)

두 종류는 읽기 속도·표기 방식이 다르다. 사람 기억이 아니라 **스키마가 막는다.**

| 키 | common | translation | sdh |
|---|---|---|---|
| `limits.*` | ✅ 기본값 | ✅ 덮어쓰기 | ✅ 덮어쓰기 |
| `text.*` | ✅ | ✅ | ✅ |
| `speaker_id` | ❌ | **❌ 금지** | ✅ 필수 |
| `sound_effect` | ❌ | **❌ 금지** | ✅ 필수 |
| `music` | ❌ | ✅ (가사 표기만) | ✅ (♪·곡 제목 식별자) |
| `forced_narrative` | ❌ | ✅ | ✅ |
| `censorship` | ❌ | ✅ | ✅ |

**로더 계약**
1. `kind`가 없으면 로드 실패. 기본값을 주지 않는다 — 조용히 한쪽으로 떨어지면 그게 곧 섞임이다.
2. `kind: translation`인데 `speaker_id`·`sound_effect` 키가 있으면 **로드 실패**(경고 아님).
   **`extends`로 상속받아 새어 들어오는 것도 막힌다** — `_validate()`는 파일 하나를
   병합 전에만 보므로, `common.yaml`(kind: common은 검사 대상이 아니다)에 `speaker_id`를
   통째로 두면 번역이 상속으로 그대로 받아도 로더가 못 잡는다(2026-09-21, 디즈니·쿠팡
   `common.yaml`이 실제로 그랬다 — `ko-translation.yaml`을 로드하면 `speaker_id`가
   병합돼 들어와 있었다). **화자명 괄호 모양만은 SDH·번역 둘 다 필요하다**
   (`colon_speaker_prefix`·`space_between_markers`처럼 common 규칙이 두 kind 모두에서
   돈다) — 그 값은 `speaker_id`가 아니라 `markers.speaker_enclosure`에 common
   레벨로 둔다. `checker/profile.py`의 `speaker_enclosure(profile)`이 이 키를 먼저
   보고, 없으면 `speaker_id.enclosure`(SDH 자신이 적어 둔 값)로 내려간다. SDH 전용
   나머지 필드(화자 번호 초기화·언어 표기 등)는 `ko-sdh.yaml`에만 둔다 — 새 플랫폼을
   추가할 때 `speaker_id`를 `common.yaml`에 두고 싶어지면 이 문단을 먼저 본다.
3. `forced_narrative`는 번역·SDH 둘 다 쓸 수 있다 — 대사와 화면 자막(On-screen Text)이
   겹칠 때 지울지 병기할지는 SDH 쪽에도 있는 문제라서다(`coupang/ko-sdh.yaml`·
   `disney/ko-sdh.yaml`·`netflix/ko-sdh-practice.yaml` 실측). 막아야 할 것은 SDH
   전용 키(`speaker_id`·`sound_effect`, 계약 2)가 번역 쪽으로 새는 것이지 그 반대가
   아니다. (2026-08-11 초판은 이 항목을 "sdh에 있으면 로드 실패"로 반대로 적었다 —
   `checker/profile.py`의 `TRANSLATION_ONLY_KEYS = ()`가 그 제약을 뺀 이유와 함께 적혀
   있다. 실제 프로파일이 이미 이 키를 쓰고 있어 문서를 코드에 맞춰 고친다.)
4. `extends`는 `kind: common`이거나 **같은 kind**인 파일만 가리킬 수 있다(예: `ko-sdh-practice.yaml`이 `ko-sdh.yaml`을 상속). sdh가 translation을 상속하는 것은 금지.
5. 병합은 **키 단위 얕은 덮어쓰기**. 리스트는 덮어쓰기(병합 아님) — 상위 값이 부분적으로 살아남아 생기는 유령 규칙을 막는다. **예외**: `rules` 목록은 이어 붙이되 같은 `id`는 개별(child) 쪽이 이긴다 — 공통 규칙과 개별 규칙을 둘 다 살리기 위해서다.
6. 상속본은 `disable_rules`로 상위 규칙 id를 끌 수 있다:
   ```yaml
   disable_rules: [C05, S12]   # 부모(common·상위 kind)의 규칙 id만 적는다
   ```
   발주처가 신경 안 쓰는 규칙을 계속 위반으로 띄우면 리포트가 노이즈가 되고 진짜
   지적이 묻힌다(`checker/profile.py`의 `_resolve`). **아직 이 저장소 어느 프로파일도
   실사용하지 않는다** — 넷플릭스·디즈니·쿠팡은 지금까지 상위 규칙을 끌 필요가
   없었다. 에이전시별 예외 프로파일을 만들 때 쓰라고 남겨 둔 자리다.

## 4. 값 규약

- **글자 수**: `chars_per_line`은 `char_weights`와 함께 읽는다. 한국어는 CJK와 그 외(라틴·공백·문장부호)에 서로 다른 가중치를 준다 — 값은 프로파일의 `char_weights`에 있다.
- **읽기 속도**: `reading_speed_cps.adult` / `.children`. 아동물은 별도 프로파일이 아니라 같은 파일 안의 분기다(넷플릭스가 그렇게 정의한다).
- **시간**: 밀리초 정수. 프레임 값은 쓰지 않는다(프레임레이트 의존).
- **규칙 id**: 넷플릭스는 `common.yaml`에 `C##`, `S##`(SDH)·`T##`(번역)을 kind별로 완전히
  가른다. **디즈니·쿠팡은 다른 방식이다** — 접두어가 kind가 아니라 "번역 전용이냐
  아니냐"로 갈린다(실측, `rules/private/*/*.yaml`):
  - 넷플릭스: `C##`(공통) / `S##`(SDH) / `T##`(번역). 영어 프로파일은
    `ES##`(영어 SDH) / `ET##`(영어 번역) / `TP##`(템플릿)
  - 디즈니: `DP##`는 **common.yaml과 ko-sdh.yaml 양쪽에 걸쳐 쓰는 한 이름공간**이다
    (스펙·화자명처럼 SDH가 쓰는 값 대부분이 `common.yaml`에 있어서). `common.yaml`
    안의 "작업 표기" 상용구 규칙(콜론 화자 표기·화폐 표기 등, 넷플릭스 C11~C33에
    대응)만 따로 `DC##`를 쓴다. `DT##`는 `ko-translation.yaml` 전용
  - 쿠팡: 같은 구조 — `CP##`(common.yaml + ko-sdh.yaml 공유) / `CC##`(common.yaml
    안의 상용구만) / `CT##`(ko-translation.yaml 전용)

  즉 "`P`가 SDH 전용"이 아니다 — `P`는 "이 발주처가 번역에서도 상속해 쓰는 값이냐"의
  반대말에 가깝다. 새 플랫폼을 넷플릭스처럼(kind별 완전 분리) 만들지, 디즈니·쿠팡처럼
  (번역 전용만 따로) 만들지는 그 발주처가 `common.yaml`에 화자명 같은 SDH성 값을
  얼마나 두는지에 달려 있다 — 정하면 이 목록에 추가한다. `clause`에 원문 조항 번호를
  넣는다. 위반 리포트가 조항을 인용할 수 있어야 한다 — 그게 이 프로젝트의 존재 이유다.
- **`auto`**: `true`면 자동 교정, `false`면 확인 플래그만. 근거가 간접적인 규칙은 반드시 `false`.

## 5. SubtitleEdit 환경설정과의 대응

작업자가 SE에서 맞추던 값들이다. 발주처가 요구하는 틀은 결국 이 값들의 묶음이므로
프로파일이 같은 것을 담아야 한다.

| SE 설정 | 프로파일 키 | 상태 |
|---|---|---|
| Single line max length | `limits.chars_per_line` | 있음 |
| Max number of lines | `limits.max_lines` | 있음 |
| Min duration (ms) | `limits.duration_ms.min` | 있음 |
| Max duration (ms) | `limits.duration_ms.max` | 있음 |
| Max chars/sec | `limits.reading_speed_cps.adult` | 있음 |
| Optimal chars/sec | `limits.optimal_cps` | 있음 |
| CPS line length strategy | `limits.char_weights` | 있음 |
| Min gap between lines (ms) | `limits.min_gap_ms` | 있음 |
| Max words per minute | `limits.words_per_minute` | 있음 |
| Single line max pixel width | `limits.pixel_width` | 있음(검사는 미구현 — 폰트 정보가 필요하다) |
| Merge lines shorter than (ms) | `limits.merge_shorter_than_ms` | 있음 |
| Dialog style | `dual_speaker.marker` | 있음 |
| Continuation style | `continuity.*` | 있음(부분) |

**자막 간 간격 주의**:

- 넷플릭스 규정은 **살아 있다** — Subtitle Timing Guidelines §5, 최소 2프레임(모든 프레임레이트).
- General Requirements 변경 이력 2020-07-24 "Timing and frame gap sections removed"는
  그 문서에서 빼 사흘 뒤(2020-07-27) 별도 문서로 옮긴 것이다. 예전엔 이걸 "삭제"로 잘못 적었다.
- 프레임 규정은 `limits.min_gap_frames`로 넣는다. `min_gap_ms`로 굳히면 다른 프레임레이트에서 틀린다.
- 같은 절의 "24fps에서 3~11프레임 간격은 2프레임으로 닫는다"는 아직 미구현이다.

값을 담되 검사가 없는 항목은 리포트의 `미구현 검사`로 드러난다. 숨기지 않는다.

## 6. 미확보 플랫폼

디즈니+·쿠팡플레이는 공식 문서는 구하지 못했지만, 작업자 실무 자료(`source.client`)로
채운 완성된 프로파일(`status: complete`)이 있다 — `official: false`일 뿐 미확보가
아니다. 공식 문서 자체가 아예 없는 항목은 각 플랫폼 디렉터리의 `UNAVAILABLE.yaml`에
확보 경로와 미확인 항목을 따로 적어 둔다. **웹에 도는 수치를 채워 넣지 말 것.**

## 7. 장르 오버레이 — 다른 계약이다 (2026-09-21 추가)

`rules/genre/*.yaml`(`documentary.yaml`·`drama.yaml`·`variety.yaml`)은 이 문서가
지금까지 설명한 플랫폼 프로파일과 **다른, 더 가벼운 계약**을 쓴다. 헷갈리지
않도록 따로 적는다 — 지금까지는 이 파일에 아예 없어서, 존재를 모르고 손대는
사고가 났었다(`docs/AGENT_INCIDENTS.md`, `rules/genre/variety.yaml`을 안 보고
같은 결론을 다시 만든 사고).

- **왜 플랫폼 밑에 안 두나**: 다큐멘터리는 넷플릭스에도 쿠팡에도 있다. 플랫폼
  밑에 두면 같은 규칙을 플랫폼 수만큼 적어야 한다(`checker/genre.py` 상단 주석).
- **적용 방식**: `checker/genre.py`의 `apply()`가 `profile.py`의 **같은 `_merge()`**로
  장르 조각을 이미 로드된 플랫폼 프로파일 위에 얹는다 — `extends`가 쓰는 병합
  엔진을 그대로 재사용한다(리스트는 대체, `rules`만 id 기준으로 이어 붙임. 계약 5).
  `--genre <이름>`을 줘야 얹힌다 — 안 주면 프로파일은 플랫폼 것 그대로다.
- **필수 헤더가 다르다**: §2가 요구하는 `platform`/`language`/`kind`/`status`가
  **없다.** 대신 `genre`(장르 이름)·`label`(표시용 이름)·`source`만 있다.
  `schema_version: 1` 태그는 붙어 있지만 `genre.apply()`가 병합 직전에
  `overlay.pop("schema_version", None)`으로 버린다 — **읽지도 검증하지도
  않는다.** 플랫폼 스키마와 같은 버전 번호를 쓰는 것처럼 보이지만 실제로는
  아무 계약도 안 걸려 있으니, 새 장르 파일을 만들 때 이 태그를 보고 §2 헤더가
  필요하다고 착각하지 않는다.
- **`rules[].id`는 `G##`을 쓴다.** 플랫폼 규칙(T##/S##/C##/...)과 이름 공간이
  겹치지 않아야 한다 — 장르 규칙은 항상 플랫폼 규칙 뒤에 이어 붙기 때문에
  겹치면 어느 쪽이 이겼는지 알기 어렵다.
- **`load_profile()`을 안 거친다.** `_check_usable`(status: complete·source 출처
  확인)이 안 걸리므로 장르 파일은 `status`·`source.official` 없이도 로드된다.
  대신 `genre.load()`는 완전한 검사 프로파일이 아니라 **얹을 조각**이라는 전제로
  설계됐다(`checker/genre.py`: "완전한 프로파일이 아니므로 `_check_usable`을
  걸지 않는다").

## 작업마다 정해지는 것 (2026-08-11 추가)

두 가지는 프로파일이 정하지 않고 **작업 시작 전에 사람이 고른다.** 업체마다 다르고
같은 업체도 작업마다 달라지기 때문이다(작업자 자료 `작업 기본 원칙` [영상번역]
673·677·678행).

```yaml
forced_narrative:
  marker: ask        # double_quote | italic | bracket | none | ask
collision:
  policy: ask        # move_dialogue | dialogue_only | keep_both | ask
  move_to: top_center  # move_dialogue일 때 말자막이 갈 자리
```

`ask`이면 **위치 검사도 교정도 하지 않는다.** 대신 무엇을 정해야 하는지 리포트에
적는다. 어디로 옮길지 모르는 채로 옮기면 납품물이 틀어진다.

명령줄은 `--fn-marker`, `--collision`, `--collision-move-to`로 받고, SE 플러그인은
같은 것을 드롭다운으로 받는다.

**`collision.policy`는 확정됐다 — 미확보가 아니다.** 사용자가 준 구글독스 원본
(작업 기본 원칙.docx 안 이미지 WORK-030)을 2026-08-14 전수 정독해서 값을 뽑았다
(`rules/private/sources/작업자-자료/이미지-정독.md` 207~236행). 넷플릭스·디즈니는
`dialogue_only`(화면자막 삭제), 쿠팡은 `keep_both`(병기) — 이미
`coupang/common.yaml`·`disney/common.yaml`·`netflix/ko-sdh-practice.yaml`에
들어가 있다. 다시 찾을 필요 없다.

**`forced_narrative.marker`만 `ask`로 남는다 — 이것도 미확보가 아니라 확인된
부재다.** 같은 자료(작업 기본 원칙 본문 671~678행)가 "회사마다 다른 이름으로
불림"·"화면 자막은 상단, 말 자막은 하단에 동시에 따라고 하는 업체도 있긴 함"이라고
**업체·작업마다 다르다는 것 자체를 명시**한다. 마커는 플랫폼 규정이 아니라 매 작업
지시서에서 오는 값이라, 어떤 자료를 더 읽어도 나오지 않는다. "자료를 못 읽었다"고
말하지 말 것 — 읽었고, 없다는 게 결론이다.

## kind: common으로 공통부를 뺀다

SDH와 번역 자막은 **화자명·어조 표기가 같다**(작업자 지적 2026-08-11). 그래서
플랫폼마다 `common.yaml`에 종류를 가리지 않는 부분(스펙·화자명·문장부호·줄바꿈·
위치)을 두고, `ko-sdh.yaml`과 `ko-translation.yaml`이 각각 그것을 상속한다.

번역 프로파일이 SDH 프로파일을 직접 상속하지는 **못한다**(계약 4). 그러면 효과음·
음 소거 규칙까지 딸려 와 두 규정이 섞인다.

