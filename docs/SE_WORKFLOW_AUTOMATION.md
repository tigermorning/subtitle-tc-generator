# SE 단축키 기능 → 자동화 대응표

출처: SubtitleEdit `src/ui/Logic/ShortcutsMain.cs`에 등록된 단축 기능 전체(약 200개)를
훑어 **작업자가 실제로 반복하는 것**만 묶었다.

목표를 사용자가 이렇게 정했다:

> 단축키 자체보다 그 단축키가 **동작시키는 기능**이 중요하다. 가장 좋은 것은
> 사용자가 단축키를 쓸 일이 거의 없는 것이다. 지금까지는 사람이 일일이 수동으로
> 해야 했으므로 단축키가 중요했지만, 자동화가 되면 그럴 필요가 없다.

그래서 이 표의 판정 기준은 "SE에 있느냐"가 아니라 **"사람이 손으로 해야 하느냐"**다.

---

## 1. 타임코드 미세 조정 — 자동화 대상 1순위

SE 기능: `MoveStartOneFrameBack/Forward`(+`KeepGapPrev`), `MoveEndOneFrame*`(+`KeepGapNext`),
`ExtendSelectedLinesToNextShotChangeOrNextSubtitle`, `ExtendSelectedLinesToPreviousShotChange`,
`ExtendPreviousEndToSelectedStart`, `ExtendNextStartToSelectedEnd`, `ApplyDurationLimits`,
`ApplyMinGap`, `BridgeGaps`, `EvenlyDistributeLines`, `RecalculateDurationSelectedLines`,
`AdjustAllTimes`, `AdjustDurations`

**사람이 하는 일**: 프레임 단위로 시작·끝을 밀고, 샷 체인지에 붙이고, 갭을 메우고,
길이를 규정 안으로 넣는 것. 자막 하나마다 반복된다.

**자동화 가능성**: 높다. 전부 **규칙으로 정해지는 계산**이다 —
"최소 표시 시간 미달이면 늘린다", "샷 체인지 ±N프레임 안이면 붙인다", "갭이 기준보다
좁으면 벌린다", "CPS 초과면 표시 시간을 늘린다".

**지금 우리**: 위반을 **찾기만** 한다(C01 표시 시간, `gap_too_short`, 읽기 속도).
고치지는 않는다.

**다음 할 일**: 타임코드 수렴 파이프라인. 규칙끼리 충돌하므로(늘리면 갭이 좁아지고,
갭을 벌리면 CPS가 올라간다) **순서와 우선순위를 정해 수렴시키고 남은 위반을 보고**해야 한다.
샷 체인지 목록은 SE가 뽑아 주거나(`GenerateImportShotChanges`) 우리가 ffmpeg로 뽑는다.

---

## 2. 자르기·붙이기 — 자동화 대상 2순위

SE 기능: `MergeSelectedLines`, `GeneralMergeSelectedLinesAndUnbreak(Cjk)`, `MergeShortLines`,
`MergeContinuationLines`, `MergeWithLineAfter/Before(AndAutoBreak|KeepBreaks|AsDialog)`,
`MoveTextFromCursorToNextAndGoToNext`, `MoveLastWordToNextSubtitle`,
`MoveFirstWordFromNextLineUpCurrentSubtitle`, `FetchFirstWordFromNextSubtitle`,
`MoveLastWordFromFirstLineDownCurrentSubtitle`

**사람이 하는 일**: 내용과 글자 수에 맞춰 자막을 쪼개고 합치면서 TC를 세분화하는 것.
사용자가 말한 ②단계이고, 시간을 제일 많이 먹는다.

**자동화 가능성**: 중간. 어디서 끊을지는 **의미 단위**를 알아야 하는데, 그 판정을
우리가 이미 시작했다(`checker/korean_break.py`).

**지금 우리**: 나쁜 줄바꿈을 **지적**한다(T16·S16). 다시 끊어 주지는 않는다.

**다음 할 일**: `--resplit`. 글자 수를 넘는 자막을 의미 단위로 다시 끊고, 그에 맞춰
TC를 글자 비율로 나눈다. 짧은 자막은 병합 후보로 제안한다(`too_short_to_stand_alone`이
이미 찾는다). **자동 적용이 아니라 제안 → 확인**이 기본이어야 한다.

---

## 3. 줄바꿈 — 부분 자동화 완료

SE 기능: `AutoBreak`, `GeneralUnbreakNoSpaceCjk`

**SE의 한계**: `Utilities.AutoBreakLinePrivate`이 CJK면 어절 분리 경로를 아예 타지 않는다.
한국어 자동 줄바꿈이 글자 수 절단이다.

**지금 우리**: 의존명사·보조 용언·관형사·관형형으로 나쁜 자리를 잡는다. 실사용 자막
1,926개로 오탐을 42→5건으로 줄였다.

**다음 할 일**: 지적에서 **제안**으로. "여기서 끊으세요"까지 내놓는다.

---

## 4. 검수 이동 — 우리가 이미 대체한다

SE 기능: `GoToNextError`, `GoToPreviousError`, `ListErrors`, `FindDoubleWords`,
`FindDoubleLines`, `FixCommonErrors`, `RemoveTextForHearingImpaired`

**사람이 하는 일**: 오류를 하나씩 찾아 다니며 고치는 것.

**지금 우리**: 리포트가 **한 번에 전부** 준다 — 조항 인용, 문제 줄, 규칙별 집계까지.
자동 교정 가능한 것은 `--fix`가 한 번에 처리한다. **오류 사이를 이동할 이유가 없어진다.**

SE의 `FixCommonErrors`는 영어권 규칙이고 한국어 사전이 0개다. 우리는 국립국어원 사전·
규범으로 판정한다. 대체가 아니라 없던 것이 생긴 것이다.

---

## 5. 재생·탐색 — 자동화 대상 아님

SE 기능: `Play`, `Pause`, `PlaySelectedLines(WithLoop)`, `PlayFromJustBeforeText`,
`GoToNextShotChange`, `PlaybackSpeedFaster/Slower`, 파형 조작 전반

**판정**: 사람이 영상을 보고 판단하는 일이다. 자동화 대상이 아니고, **SE가 잘한다.**
우리가 다시 만들 이유가 없다 — SE 안에서 쓰거나 SE와 나란히 쓰면 된다.

---

## 6. 일괄 처리 — 우리가 더 낫다

SE 기능: `BatchConvert`, `MultipleReplace`, `ChangeCasing`, `Renumber`, `RemoveBlankLines`

**지금 우리**: 폴더 통째로 검사·교정하고 종료 코드로 통과 여부를 낸다. 납품 전 게이트로
쓸 수 있다. SE의 일괄 변환은 포맷 변환이 주고 규정 검사는 못 한다.

---

## 자동화 최종 그림

사용자가 말한 목표를 단계로 옮기면 이렇다.

```
지금        영상 → SE로 TC 분할 → 손으로 자르기 → 부산대 → SE → 사전 검색 → SE
1단계(완료)  ...                                  → 우리 도구 한 번 → SE
2단계        영상 + 대본 → 자동 TC 제안 + 자동 자르기 제안 → 사람은 확인만
3단계        영상 → 받아쓰기 → 규정 맞춘 초벌 자막 → 사람은 다듬기만
```

2단계에서 사람이 하는 일은 **판단**이고, 손으로 하는 일은 **확인·수정**만 남는다.
단축키가 필요 없어지는 지점이 여기다.

3단계는 Whisper 받아쓰기가 붙어야 하고, 그것은 미디어를 다루므로 SE 플러그인이나
별도 처리 경로가 필요하다.

---

## 우선순위 (사용자 목표 기준)

| 순위 | 항목 | 근거 |
|---|---|---|
| 1 | 타임코드 수렴 파이프라인 | 반복 횟수가 제일 많고 전부 규칙으로 정해진다 |
| 2 | 다시 끊기(`--resplit`) 제안 | 시간을 제일 많이 먹는 단계 |
| 3 | 줄바꿈 제안(지적 → 제안) | 재료가 이미 있다 |
| 4 | 샷 체인지 연동 | 1번의 정확도를 좌우한다 |
| 5 | 받아쓰기 검수 | 제일 비싸고 제일 크다 |
