# 규정 프로파일 스키마 v1

플랫폼별 자막 규정을 **데이터로** 정의한다. 코드에 값을 박지 않는 이유는 규정이 자주 개정되기 때문이다(넷플릭스 한국어 2025-07-07, 영어 2025-12-19 개정 확인). 규정이 바뀌면 이 디렉터리의 YAML만 고치고 코드는 건드리지 않는다.

> **이 디렉터리에는 코드를 넣지 않는다.** 순수 데이터만 유지해야 나중에 `git subtree split`으로 별도 저장소로 떼낼 수 있다.

## 1. 파일 배치

```
rules/
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
  official: true           # 플랫폼/정부 공식 문서인가. false면 룰로 쓰지 않는다
  url: "..."
  section: "Korean TTSG Section II"
  revision: "2025-07-07"   # 원문 change log의 최신일
  verified: "2026-08-11"   # 우리가 원문을 확인한 날
```

**`official: false`이거나 `status: unavailable`인 프로파일은 로더가 검사에 쓰지 않는다.** 블로그·2차 자료 수치가 조용히 룰이 되는 것을 막는다.

## 3. SDH ↔ 번역 자막 섞임 방지 (핵심)

두 종류는 읽기 속도·표기 방식이 다르다. 사람 기억이 아니라 **스키마가 막는다.**

| 키 | common | translation | sdh |
|---|---|---|---|
| `limits.*` | ✅ 기본값 | ✅ 덮어쓰기 | ✅ 덮어쓰기 |
| `text.*` | ✅ | ✅ | ✅ |
| `speaker_id` | ❌ | **❌ 금지** | ✅ 필수 |
| `sound_effect` | ❌ | **❌ 금지** | ✅ 필수 |
| `music` | ❌ | ✅ (가사 표기만) | ✅ (♪·곡 제목 식별자) |
| `forced_narrative` | ❌ | ✅ | ❌ |
| `censorship` | ❌ | ✅ | ✅ |

**로더 계약**
1. `kind`가 없으면 로드 실패. 기본값을 주지 않는다 — 조용히 한쪽으로 떨어지면 그게 곧 섞임이다.
2. `kind: translation`인데 `speaker_id`·`sound_effect` 키가 있으면 **로드 실패**(경고 아님).
3. `kind: sdh`인데 `forced_narrative`가 있으면 로드 실패.
4. `extends`는 `kind: common`인 파일만 가리킬 수 있다. sdh가 translation을 상속하는 것은 금지.
5. 병합은 **키 단위 얕은 덮어쓰기**. 리스트는 덮어쓰기(병합 아님) — 상위 값이 부분적으로 살아남아 생기는 유령 규칙을 막는다.

## 4. 값 규약

- **글자 수**: `chars_per_line`은 `char_weights`와 함께 읽는다. 한국어는 CJK 1자, 그 외(라틴·공백·문장부호) 0.5자.
- **읽기 속도**: `reading_speed_cps.adult` / `.children`. 아동물은 별도 프로파일이 아니라 같은 파일 안의 분기다(넷플릭스가 그렇게 정의한다).
- **시간**: 밀리초 정수. 프레임 값은 쓰지 않는다(프레임레이트 의존).
- **규칙 id**: `rules[].id`는 `T##`(번역) / `S##`(SDH). `clause`에 원문 조항 번호를 넣는다. 위반 리포트가 조항을 인용할 수 있어야 한다 — 그게 이 프로젝트의 존재 이유다.
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

**자막 간 간격 주의**: 넷플릭스는 이 규정을 삭제했다(General Requirements change log
2020-07-24 "Timing and frame gap sections removed"). 그래서 넷플릭스 프로파일에는
`min_gap_ms`를 넣지 않는다. SubtitleEdit의 2프레임 갭 검사는 옛 판본을 따르고 있다 —
근거 없는 지적을 그대로 옮기지 않는다. 발주처가 요구하면 그때 프로파일에 넣는다.

값을 담되 검사가 없는 항목은 리포트의 `미구현 검사`로 드러난다. 숨기지 않는다.

## 6. 미확보 플랫폼

디즈니+·쿠팡플레이는 공식 문서를 구하지 못했다. 값을 추측해 채우지 않고 `status: unavailable`로 남긴다. 로더가 이를 만나면 "이 플랫폼은 규정 미확보"라고 사용자에게 알리고 검사를 건너뛴다. **웹에 도는 수치를 채워 넣지 말 것.**
