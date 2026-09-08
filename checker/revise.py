"""1차 번역을 다시 본다 — 작업자가 하는 2차·3차 작업.

작업자 자료(`작업 기본 원칙` 569~579행)가 단계를 이렇게 나눈다.

    1차   오역 없이 빠르게. 맥락 생각 말고            (`translate.py`가 하는 일)
    2차   올바른 한국어로. **전문 용어 조사**, 맥락 안에서 문장의 역할 바로잡기
    3차   영상 없이 줄글로 읽으며 말투·흐름 윤문

    (ex.) 1차 그들과 싸우기 전에 그들을 발견해야 한다
          2차 놈들과 싸우기 전에 우선 찾아야 한다
          3차 우선 찾아야 싸우든 말든 하지

**한 번에 다 시키지 않는 이유가 여기 있다.** 사람도 나눠서 한다. 한 번에 "잘
번역해라"라고 하면 모델은 세 가지를 뒤섞어 어중간하게 낸다. 1차는 정확도, 2차는
용어와 맥락, 3차는 말맛 — 볼 것이 다르다.

**바꾼 것은 전부 남긴다.** 2차가 1차보다 늘 나은 것은 아니다. 무엇을 왜 바꿨는지
보여야 사람이 되돌릴 수 있다.

이 단계는 로컬 모델로 돈다. 대본이 밖으로 나가지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event
from .translate import _parse_numbered, _strip_markdown_wrap, _strip_trailing_notes

# **2차는 뜻과 맥락과 말투다.** 문체 규칙은 여기 없다 — 3차로 옮겼다.
#
# 전에는 이 프롬프트가 마침표·인칭대명사·문장요소 규칙을 1차와 **똑같이** 적고 있었다.
# 규칙이 두 곳에 있으면 고칠 때 한 곳만 고친다. 규칙은 한 단계에만 둔다.
#
# 말투도 바뀌었다. 전에는 "말투는 1차를 따릅니다. 흔들지 마세요"였는데, 1차가 말투를
# 정하지 않게 되었으므로(존댓말로 통일) **말투를 정하는 것이 2차의 일이다.**
SECOND_PASS_KO = (
    "당신은 영상 번역 감수자입니다. 1차 번역을 **2차 번역**으로 다듬습니다.\n"
    "1차는 뜻만 맞춰 놓은 초벌입니다. 투박한 것이 정상이고, 그것을 여기서 고칩니다.\n"
    "\n"
    "볼 것은 넷입니다.\n"
    "  1. 오역 — 원문의 뜻과 다른 것. **가장 먼저 봅니다.**\n"
    "  2. 용어 — 주어진 고정 표기를 쓰지 않은 것\n"
    "  3. 맥락 — 앞뒤 자막과 이어지지 않거나 지시 대상이 틀린 것\n"
    "  4. 말투 — 인물 관계에 맞는 존댓말/반말. 1차는 전부 존댓말로 두었습니다\n"
    "\n"
    "규칙:\n"
    "- 올바른 한국어로 씁니다. 어색한 번역투를 우리말 어순으로 풀어 주세요.\n"
    "- 말투는 **인물 관계**로 정합니다. 나이나 성별만으로 정하지 마세요.\n"
    "  관계를 알 수 없으면 존댓말을 씁니다.\n"
    "- 한번 정한 말투를 자막마다 바꾸지 마세요.\n"
    "- 한국 문화로 과하게 옮기지 않습니다(미국인이 한국식으로 말하면 어색합니다).\n"
    "- **자기소개는 '직함+이름'입니다.** '이름+직함'은 높임법이라 자기를 소개할 때 "
    "쓸 수 없습니다 — '존슨 형사입니다'(x), '형사 존슨입니다'(어색), "
    "'LA경찰서 존슨입니다'·'강력팀 존슨입니다'(o).\n"
    "- 글자 수를 줄이는 것은 3차에서 합니다. 여기서는 **뜻이 맞는 것**이 먼저입니다.\n"
    "- **고칠 곳이 없으면 1차를 그대로 씁니다.** 바꾸기 위해 바꾸지 마세요.\n"
    "- 번호를 그대로 붙여 같은 개수로 냅니다. 설명하지 마세요."
)

# **3차가 자막다움을 담당한다.** 1차에 있던 문체·간결·문장부호 조항이 여기로 왔다.
# 이 단계는 원문을 보지 않는다 — 한국어만 소리 내어 읽는다(작업자 자료: "영상 없이
# 줄글로 읽으며").
#
# 번역투 종결어미·한정사/빈도부사 생략·현재진행형 세 항목은 `표기_맞춤법_번역.txt`
# 766~773행("번역투|오역|윤문" 절)에서 옮겼다(2026-08-27, 사용자 확인 후 반영).
# 같은 절의 이중 피동·사동, 사물 주어 금지, 최상급 비문, 직접인용→간접인용,
# 인칭대명사 제거는 이미 아래에 있었다. 단어별 뜻풀이 목록("원문 의미 살리기",
# 781~820행)은 여기 넣지 않았다 — 프롬프트에 넣기엔 개별 단어 지식이라
# 커지기만 하고 그 단어가 안 나오는 대사엔 쓸모가 없다. 대신
# `rules/lexicon/en-ko-word-sense.yaml`로 따로 뺐다.
THIRD_PASS_KO = (
    "당신은 영상 번역가입니다. 자막을 소리 내어 읽으며 **자막답게** 다듬습니다.\n"
    "뜻과 용어는 2차에서 맞췄습니다. **여기서 뜻을 바꾸면 그것이 사고입니다.**\n"
    "\n"
    "- 주어와 서술어가 호응하는지, 입에 붙는지 봅니다.\n"
    "- 자막은 짧을수록 좋습니다. **불필요한 말은 과감히 뺍니다.**\n"
    "- 문장 요소를 덜어냅니다: '수', '있', '것', '의', '들', 보조 용언, 극존칭 '-시-'.\n"
    "  **넣을지 뺄지 헷갈리면 빼는 것이 맞습니다.**\n"
    "- **이중 피동·이중 사동을 쓰지 않습니다.** 조여지다→조이다, 적응되다→적응하다, "
    "믿겨지다→믿어지다, 순화시키다→순화하다.\n"
    "- '~전제하에서', '~ 말이죠', '~다는 것을요' 같은 번역투 종결·연결 표현을 피합니다.\n"
    "- 한정사(some, just 같은)·빈도부사는 뜻이 문맥에 이미 드러나 있으면 억지로 "
    "옮기지 않아도 됩니다.\n"
    "- 현재진행형을 기계적으로 '~하고 있다'로 옮기지 말고, 자연스러운 현재형으로 "
    "풉니다.\n"
    "- **행위의 주체는 사람입니다.** 사물을 주어로 세우지 마세요 — "
    "'A에서 B로 안전하게 보내 줍니다'가 아니라 'A에서 B로 안전하게 갈 수 있습니다'.\n"
    "- **'가장 ~한 것 중 하나'는 비문입니다**(한국어의 최상급은 하나뿐). "
    "최상급을 빼고 '매우 ~한'으로 씁니다. '문제는/관건은 ~냐이다'도 비문입니다.\n"
    "- 직접인용은 특별한 경우가 아니면 **간접인용**으로 바꿉니다 — "
    "'\\'무대를 마련하다\\'라는 표현'이 아니라 '무대를 마련한다는 표현'.\n"
    "- **인칭대명사를 쓰지 않습니다.** '그', '그녀', '그들'은 이름이나 호칭으로 "
    "바꾸거나 뺍니다.\n"
    "- **마침표를 쓰지 않습니다.** 문장 끝 쉼표도 쓰지 않습니다.\n"
    "- 문장 부호를 최소화합니다(쉼표·말줄임표·괄호).\n"
    "- 구어입니다. 문어체로 늘이지 마세요.\n"
    "- 뜻을 바꾸지 마세요. 용어를 바꾸지 마세요. 말투를 바꾸지 마세요.\n"
    "- 고칠 곳이 없으면 그대로 씁니다.\n"
    "- 번호를 그대로 붙여 같은 개수로 냅니다. 설명하지 마세요."
)

# **영어는 한국어 규칙을 번역해서 쓰지 않는다.** 존댓말/반말, 이중 피동,
# 인칭대명사 회피 같은 조항은 한국어 문법 범주라 영어에 그대로 옮기면 없는
# 문제에 억지 답을 강요하게 된다(규칙 9 — 자료 없이 만들지 않는다). 대신
# 실제로 영어 자막이 쓰는 압축 관행을 조사해서 넣었다:
#
#   Netflix 공식 English Timed Text Style Guide, Section I.1 —
#     "When editing for reading speed, favor text reduction, deletion
#      and condensing." (2026-08-27 확인, 이미 en-translation.yaml의 근거와
#      같은 문서)
#   Suratno & Wijaya(2018), "Text Reduction: Strategies Adopted in Audio
#     Visual Subtitle Translation" — Antonini(2005)·Díaz-Cintas & Remael
#     (2007)의 축소 전략 셋(제거·순화·압축)을 실제 자막 209건으로 검증한
#     연구. 여기 3차 규칙의 구체 기법(주저·미완성 문장 제거, 동사구
#     단순화, 능동태 선호, 겹문장 쪼개기)은 이 논문의 분류를 그대로 따랐다.
SECOND_PASS_EN = (
    "You are a subtitle editor. You refine a first-pass translation into a "
    "**second pass**.\n"
    "The first pass only got the meaning right — rough phrasing is expected, "
    "and you fix that here.\n"
    "\n"
    "You check four things.\n"
    "  1. Mistranslation — anything that says something the source didn't. "
    "**Check this first.**\n"
    "  2. Terminology — fixed terms not used as given.\n"
    "  3. Context — references that don't connect to neighboring lines, or "
    "wrong referents.\n"
    "  4. Register — formality appropriate to the relationship between "
    "speakers. If the relationship is unclear, default to a neutral, "
    "professionally polite register (not stiff, not overly casual).\n"
    "\n"
    "Rules:\n"
    "- Write natural English word order, not a literal transplant of the "
    "source sentence structure.\n"
    "- Keep register consistent for a given character once established — "
    "don't flip a formal speaker casual mid-scene without reason.\n"
    "- Don't overlay source-culture conventions onto English speech that "
    "wouldn't naturally use them.\n"
    "- Shortening for reading speed happens in the third pass. Here, "
    "**correctness comes first.**\n"
    "- **If there is nothing to fix, keep the first pass as-is.** Don't "
    "change things just to change them.\n"
    "- Keep the same numbering, same count. No explanations."
)

THIRD_PASS_EN = (
    "You are a subtitle editor. You read the lines aloud and polish them to "
    "**read like a subtitle**.\n"
    "Meaning and terminology were already fixed in the second pass. "
    "**Changing meaning here is a mistake.**\n"
    "\n"
    "- Check that it sounds like natural spoken English, not written prose.\n"
    "- Shorter is better. **Cut aggressively** using these techniques "
    "(Antonini 2005; Díaz-Cintas & Remael 2007):\n"
    "  - Elimination: hesitations (\"um\", \"like\", \"you know\"), false "
    "starts, abandoned/unfinished clauses, redundant restatement, and "
    "formulaic filler (\"you know what?\", \"I mean\") that carries no "
    "content — cut these unless they characterize the speaker.\n"
    "  - Simplify verbal phrases: drop padding modal/aspect constructions. "
    "\"I'm going to have to fight\" -> \"I have to fight\".\n"
    "  - Split long compound or multi-clause sentences into short simple "
    "ones when that reads faster.\n"
    "  - Prefer active voice — it's shorter and reads faster than passive, "
    "unless passive is what a native speaker would actually say.\n"
    "  - Use contractions for natural rhythm (\"don't\", \"I'm\", \"can't\") "
    "unless the beat calls for the full form as emphasis.\n"
    "- Avoid comma overuse and complex punctuation (colons, semicolons) — "
    "subtitles read at a glance, not like a printed page.\n"
    "- Don't change meaning. Don't change terminology. Don't change the "
    "register the second pass set.\n"
    "- If there is nothing to cut, keep it as-is.\n"
    "- Keep the same numbering, same count. No explanations."
)


@dataclass
class Revision:
    index: int
    before: str
    after: str
    stage: str          # 2차 | 3차

    @property
    def changed(self) -> bool:
        return self.before.strip() != self.after.strip()


# 하위 호환: 옛 이름이 한국어 프롬프트를 가리킨다.
SECOND_PASS = SECOND_PASS_KO
THIRD_PASS = THIRD_PASS_KO

# 일본어 2차·3차. **실측으로 만들었다**(2026-09-08, 정답 자막 4작품 21,888개 —
# 넷플릭스 예능B(예능 8화) 13,323 / 디즈니 드라마C(드라마 5화) 4,399 /
# 디즈니 다큐A 심판의 날(다큐 5화) 2,558 / 블루레이 영화B(영화) 1,608).
# 발주처 넷·장르 넷에서 같은 방향이 나왔다(규칙 12 — 최소 2편).
#
#     항목                   예능   드라마   다큐   영화
#     한 자막 글자수 중앙값     9      9      15     7
#     한 줄 글자수 중앙값       7      8       9     7    (95%는 11~17)
#     한 줄짜리 비율          63%    81%     45%    84%
#     です/ます 종결           9%    17%      0%     1%
#     「。」「、」 포함          0%     0%      0%     0%
#     어절 사이 공백           8%    15%     14%    22%
#
# **왜 필요했나.** 이 파일은 한국어·영어뿐이었고, 우리 일본어 1차 결과는 정답보다
# 압도적으로 길었다(2026-08-31 실측, 영화B: 중앙값 24자 대 정답 13자, 81%가
# 30% 이상 김). 예: 우리 "距離 800メートルです" 대 정답 "距離 800メートル".
# 길이만의 문제가 아니라 **문체가 다르다** — 정답은 です/ます를 거의 안 쓰고
# 구두점을 아예 안 쓴다.
#
# 실측과 일반 관행을 섞지 않는다. 위 표는 실측이고, 아래 프롬프트의 "인칭대명사·
# 지시어를 덜어낸다"는 일본어 자막의 일반 관행이다(어느 언어에 어떤 문법 범주가
# 있는지와 같은 층 — `translate.py`의 `_base_rules` 주석 참고).
SECOND_PASS_JA = (
    "あなたは映像翻訳のチェッカーです。一次翻訳を**二次翻訳**に整えます。\n"
    "一次は意味だけ合わせた下訳です。ぎこちないのが普通で、それをここで直します。\n"
    "\n"
    "見るのは四つです。\n"
    "  1. 誤訳 — 原文にないことを言っている箇所。**まずこれを見ます。**\n"
    "  2. 用語 — 指定された訳語どおりに使われていないもの。\n"
    "  3. 文脈 — 前後の台詞とつながらない指示語・照応。\n"
    "  4. 文体 — 話者の関係に合った丁寧さ。\n"
    "\n"
    "規則:\n"
    "- **基本は常体(だ・である、体言止め)です。** 実際の字幕では敬体(です・ます)は"
    "ごく一部にしか現れません。話者がはっきり丁寧に話す場面だけ敬体にします。\n"
    "- 一度決めた話者の文体は場面の途中で理由なく変えません。\n"
    "- 原文の語順をそのまま移さず、自然な日本語の語順にします。\n"
    "- 読む速さのための短縮は三次で行います。ここでは**正しさが先**です。\n"
    "- **直すところがなければ一次のまま残します。** 変えるために変えないでください。\n"
    "- 番号と行数はそのまま。説明は書かないでください。"
)

THIRD_PASS_JA = (
    "あなたは映像翻訳のチェッカーです。声に出して読み、**字幕として読める形**に"
    "整えます。\n"
    "意味と用語は二次で直っています。**ここで意味を変えるのは誤りです。**\n"
    "\n"
    "- **短いほどよい。思い切って削ります。** 実際の字幕は一画面7~15字、"
    "一行7~9字が中心です(一行は長くても16字程度)。\n"
    "- 削り方:\n"
    "  - 文末の「です・ます」を落として体言止めにする。"
    "「距離 800メートルです」→「距離 800メートル」\n"
    "  - 言わなくても通じる助詞を省く。「私は行きます」→「行く」\n"
    "  - 人称代名詞(私・あなた・彼)と指示語は、なくても分かるなら消す。\n"
    "  - 言いよどみ・繰り返し・相づちは、人物を特徴づけていない限り消す。\n"
    "- **句読点「。」「、」は使いません。** 区切りが要るところは全角スペースを"
    "入れます。「?」「!」は感情を示すときだけ使います。\n"
    "- 一画面はできるだけ一行にまとめます。二行になるときは意味の切れ目で折ります。\n"
    "- 意味を変えない。用語を変えない。二次が決めた文体を変えない。\n"
    "- 削るところがなければそのまま残します。\n"
    "- 番号と行数はそのまま。説明は書かないでください。"
)


ROLES_BY_LANG: dict[str, dict[str, str]] = {
    "ko": {"감수": SECOND_PASS_KO, "윤문": THIRD_PASS_KO},
    "en": {"감수": SECOND_PASS_EN, "윤문": THIRD_PASS_EN},
    "ja": {"감수": SECOND_PASS_JA, "윤문": THIRD_PASS_JA},
}
# 하위 호환: `target_lang`을 안 주는 옛 호출부는 여전히 한국어를 본다.
ROLES = ROLES_BY_LANG["ko"]


def genre_hint(profile: dict | None) -> str:
    """장르가 정한 것을 프롬프트 한 조각으로. **프로파일에서 읽는다.**

    전에는 `translate.DOCUMENTARY_RULES`라는 상수가 있었는데 **아무도 부르지 않는 죽은
    코드였다.** 층이 틀렸기 때문이다 — 장르는 검사 기준도 바꾸므로 프로파일에 있어야
    하고(`checker/genre.py`), 프롬프트는 거기서 읽어 오는 것이 맞다.
    """
    if not profile:
        return ""
    lines = []
    prefer = (profile.get("formality") or {}).get("prefer")
    if prefer == "합니다체":
        # **'요'를 금지하지 않는다.** 사용자 확인: 다큐는 합니다체 위주이지만 자연스러움을
        # 위해 가끔 '요'를 쓰는 것은 허용된다.
        lines.append("- 종결어미는 '-습니다/-ㅂ니다'를 위주로 씁니다. 자연스러움을 "
                     "위해 '-요'를 가끔 쓰는 것은 괜찮습니다.")
    address = profile.get("address") or {}
    if address.get("forbid_ssi"):
        lines.append("- 호칭 '~씨'를 쓰지 않습니다(작업자 자료: 다큐·리얼리티).")
    if address.get("forbid_super_honorific"):
        lines.append("- 극존칭을 쓰지 않습니다.")
    if not lines:
        return ""
    label = profile.get("genre") or "작품"
    return f"\n\n[{label} 규칙]\n" + "\n".join(lines)


def cast_hint(cast: dict[str, str] | None) -> str:
    """캐릭터 시트가 정한 말투를 프롬프트 한 조각으로.

    **여기가 캐릭터 시트의 값이 나오는 자리다.** 하나의 작품을 여러 작업자가 나누어
    하기 때문에 말투가 사람마다 갈리는데, 시트를 물려 주면 모델이 같은 기준으로 쓴다.
    같은 시트가 `T17` 검사도 돌린다 — 정하고, 쓰고, 검사하는 것이 한 자료다.
    """
    if not cast:
        return ""
    rows = "\n".join(f"  {name}: {tone}" for name, tone in cast.items())
    return ("\n\n[인물별로 정한 말투 — 이대로 씁니다]\n" + rows
            + "\n  여기 없는 인물은 존댓말을 씁니다.")


def revise(events: list[Event], translator, source: dict[int, str] | None = None,
           glossary=None, stage: str = "2차", role: str = "",
           profile: dict | None = None, cast: dict[str, str] | None = None,
           baseline: dict[int, str] | None = None,
           batch: int = 8, context: int = 2, target_lang: str = "ko",
           progress=None) -> tuple[list[Event], list[Revision]]:
    """자막을 다시 본다. (고친 자막, 바뀐 내역)

    `source`는 자막 번호별 원문이다. 감수에서는 원문이 있어야 오역을 볼 수 있다 —
    없으면 원어만 보고 다듬는 윤문처럼 돈다.

    `role`이 프롬프트를 고른다(`감수` 또는 `윤문`). `stage`는 사람에게 보이는
    이름일 뿐이다. `target_lang`이 **어느 언어의** 2차·3차인지 고른다 —
    `translate.py`의 `target_lang`과 같은 신호다. 지원하지 않는 언어는 조용히
    한국어로 떨어지지 않고 실패한다(규칙 9 — 그 언어의 2차·3차 쟁점을 조사해서
    `ROLES_BY_LANG`에 넣어야 한다, 추측해서 채우지 않는다).

    `baseline`은 **1차 번역**이다(번호별). 회차를 여러 번 돌 때 누적 표류를 막는 데
    쓴다 — 직전 단계만 보면 매 회차 1.4배씩 늘어 원문 대비 2배가 되어도 통과한다.

    **전에는 `role`이 없고 `stage`로 프롬프트를 유추했다.** `stage == "2차"`가 아니면
    무조건 윤문 프롬프트를 썼기 때문에 `"4차"`를 넘기면 **에러도 없이** 윤문으로
    돌았다. 회차를 설정으로 열려면 그 조용한 실패를 먼저 막아야 한다 — 유추할 수
    없는 이름이 오면 예외를 올린다.
    """
    say = progress or (lambda _m: None)
    if not role:
        role = {"2차": "감수", "3차": "윤문"}.get(stage, "")
        if not role:
            raise ValueError(
                f"'{stage}'가 감수인지 윤문인지 알 수 없습니다. role을 주세요.")
    if target_lang not in ROLES_BY_LANG:
        raise ValueError(
            f"목표 언어 '{target_lang}'의 2차·3차 프롬프트가 없습니다. "
            f"지원 언어: {', '.join(ROLES_BY_LANG)}. 새 언어는 그 언어의 실제 자막 "
            "압축·문체 관행을 조사해서 ROLES_BY_LANG에 넣어야 합니다.")
    roles = ROLES_BY_LANG[target_lang]
    if role not in roles:
        raise ValueError(f"모르는 역할입니다: {role} (쓸 수 있는 것: {', '.join(roles)})")
    system = roles[role]
    # 장르와 인물별 말투는 **말투를 정하는 단계**에만, 그것도 한국어일 때만 붙인다.
    # 존댓말/반말·'~씨' 금지 같은 조항은 한국어 문법 범주라 다른 언어 프롬프트에
    # 섞으면 없는 문제에 억지 답을 강요하게 된다.
    if role == "감수" and target_lang == "ko":
        system += genre_hint(profile) + cast_hint(cast)
    source = source or {}
    revisions: list[Revision] = []
    out: list[Event] = []

    for start in range(0, len(events), batch):
        chunk = events[start:start + batch]
        say(f"{stage} {start + 1}~{start + len(chunk)} / {len(events)}")

        before = ""
        if context and start:
            recent = events[max(0, start - context):start]
            before_label = "Previous lines (for reference only):" if target_lang != "ko" \
                else "앞 자막(참고만 하세요):"
            before = (before_label + "\n"
                      + "\n".join(f"  {e.text}" for e in recent) + "\n\n")

        src_label, p1_label = ("[source]", "[pass 1]") if target_lang != "ko" \
            else ("[원문]", "[1차]")
        lines = []
        for event in chunk:
            original = source.get(event.index)
            if original and role == "감수":
                lines.append(f"{event.index}. {src_label} {original}\n   {p1_label} {event.text}")
            else:
                lines.append(f"{event.index}. {event.text}")

        instruction = (f"Refine the following subtitles into the {stage} pass.\n\n"
                       if target_lang != "ko" else f"다음 자막을 {stage} 번역으로 다듬으세요.\n\n")
        prompt = (f"{before}{glossary.hint() if glossary else ''}\n"
                  f"{instruction}" + "\n".join(lines))
        reply = translator.ask(system, prompt)
        got = _parse_numbered(reply, [e.index for e in chunk])

        for event in chunk:
            text = (got.get(event.index) or "").strip()
            # 모델이 형식을 흘리면(`[2차]`·`[pass 2]` 같은 표지) 걷어낸다. **줄마다
            # 본다** — `_parse_numbered`가 번호 없는 줄을 앞 번호에 이어 붙이므로,
            # 표지가 합쳐진 문자열의 **중간 줄**에서 시작할 수 있다. `^`만 보면
            # (문자열 전체의 맨 앞만) 그 경우를 놓친다(실측: 예능A 15회,
            # "[pass 2] -With our contract..."가 자막에 그대로 남음, 2026-08-27).
            text = "\n".join(re.sub(r"^\[[^\]]{1,6}\]\s*", "", line)
                            for line in text.split("\n"))
            # 1차와 같은 흘림(마크다운 강조로 통째로 감싸기, "참고:"/"**Notes:**"
            # 자기 설명 덧붙이기)이 2차·3차에서도 그대로 난다 — 같은 종류의 모델이
            # 하는 같은 실수다. 1차에서 이미 만든 걸러내기를 그대로 쓴다.
            text = _strip_trailing_notes(_strip_markdown_wrap(text))
            # **누적 표류를 함께 막는다.** 직전 단계만 보면 2차가 1.4배, 3차가 또
            # 1.4배로 늘어 원문 대비 2배가 되어도 매 회차는 통과한다. 회차를 설정으로
            # 열어 둔 지금 이것이 실제 위험이다.
            origin = (baseline or {}).get(event.index)
            drifted = _too_different(event.text, text) or (
                bool(origin) and _too_different(origin, text))
            if not text or drifted:
                # **의심스러우면 직전을 지킨다.** 다음 회차가 늘 나은 것은 아니다.
                # 1차로 되돌리지는 않는다 — 중간 회차가 제대로 고친 것을 버릴 이유가 없다.
                out.append(Event(event.index, event.start_ms, event.end_ms, event.text))
                continue
            out.append(Event(event.index, event.start_ms, event.end_ms, text))
            revision = Revision(event.index, event.text, text, stage)
            if revision.changed:
                revisions.append(revision)

    return out, revisions


def _too_different(before: str, after: str, limit: float = 1.5) -> bool:
    """길이가 너무 달라지면 다듬은 것이 아니라 다시 쓴 것이다.

    모델이 설명을 덧붙이거나 두 자막을 합쳐 버리는 사고를 막는다.

    한계를 1.5배로 둔다. 2.5배 -> 1.8배로 조였다가 1.77배짜리 덧붙임을 또
    통과시켰다 —
    **한국어를 한국어로 다듬는 단계**라 길이가 크게 늘 이유가 없다(원어에서 옮기는
    1차와 다르다). 자막은 화면에 맞춰 길이가 정해져 있어 조금만 늘어도 못 쓴다.
    실제 다듬기는 1.2~1.3배를 넘지 않았다(`진짜야?` -> `진심이야?` 1.25배).
    """
    if not before.strip():
        return False
    ratio = len(after) / max(len(before), 1)
    return ratio > limit or ratio < 1 / limit


def report(revisions: list[Revision], show: int = 20) -> str:
    """무엇을 왜 바꿨는지. 사람이 되돌릴 수 있어야 한다.

    **회차별로 나눠서 센다.** `stage_revise`는 여러 회차(2차·3차...)의 결과를
    한 목록에 모아서 준다 — 전부 `revisions[0].stage`(맨 처음 회차) 이름으로만
    세면, 뒤 회차가 고친 것까지 앞 회차가 고친 것처럼 보인다(실측: 예능A
    15회, "2차에서 1207개를 고쳤습니다"라고 나왔는데 실은 2차+3차 합산값이었다
    — 2차 대상 자막이 1114개뿐이라 1207개는 애초에 2차 혼자 낼 수 없는
    숫자다, 2026-08-27).
    """
    if not revisions:
        return "바꾼 자막이 없습니다."
    by_stage: dict[str, int] = {}
    for r in revisions:
        by_stage[r.stage] = by_stage.get(r.stage, 0) + 1
    summary = ", ".join(f"{stage} {n}개" for stage, n in by_stage.items())
    lines = [f"고쳤습니다 — {summary} (합계 {len(revisions)}개)"]
    for revision in revisions[:show]:
        lines.append(f"  #{revision.index}")
        lines.append(f"    전: {revision.before}")
        lines.append(f"    후: {revision.after}")
    if len(revisions) > show:
        lines.append(f"  … 외 {len(revisions) - show}개")
    return "\n".join(lines)
