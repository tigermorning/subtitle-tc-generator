"""번역 심판 주입 오류 시험 — 시험 세트 만들기.

설계는 프로젝트 루트의 `TRANSLATION_CONSTRUCT_DESIGN.md` 6절. 정답지의 영어 원문(영어_SDH)과
한국어 번역을 시간으로 짝짓고, 짝 중 일부에 **오류를 하나씩 일부러 넣어** 심판(LLM)이
구분하는지 보는 시험 세트를 만든다. 이 파일은 세트 만들기까지다 — 심판 호출은 아직 없다.

원칙
- 규칙 기반이고 시드가 고정돼 같은 입력이면 같은 세트가 나온다.
- 한 셀에 오류 하나. 한 셀은 한 유형에만 쓴다(서로 다른 셀).
- 대사가 든 산출물은 `.work/judge_injection/`(git 제외)에만 둔다. `docs/evidence/`에는
  셀 번호·유형만 둔다(대사 없음).

용법: python tools/judge_injection/build_set.py [--seed N]
"""
import argparse
import bisect
import csv
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from checker.parsers import parse  # noqa: E402

CORPUS = ROOT / "학습한 TC 및 자막 모음"
OUT = ROOT / ".work" / "judge_injection"
VERSION = "v2"
EVIDENCE = ROOT / "docs" / "evidence"

# 시험에 쓰는 정답지 쌍(영어 원문 트랙 + 한국어 번역). 실제 폴더 이름(작품 제목)이 들어 있어
# 공개 저장소에는 두지 않고 비공개 저장소의 이 파일에서 읽는다. 여기에는 가명 키만 나온다.
SETS_FILE = ROOT / "rules" / "private" / "corpus" / "judge_injection_sets.yaml"


def load_sets() -> dict:
    import yaml
    if not SETS_FILE.is_file():
        sys.exit(f"시험 세트 목록이 없습니다: {SETS_FILE}\n"
                 "비공개 규정 저장소(rules/private)를 받았는지 확인하세요 — 작품 폴더 이름이 그 안에 있습니다.")
    data = yaml.safe_load(SETS_FILE.read_text(encoding="utf-8"))
    return {name: (v["en"], v["ko"]) for name, v in data["sets"].items()}


IOU_PAIR, IOU_INJECT, IOU_CONTROL = 0.5, 0.7, 0.8

# (코드, 기준, 난이도, 목표 n). 풀이 작은 유형부터 배정한다.
TYPES = [
    ("A3", "의미", "중간", 60), ("A4", "의미", "어려움", 60),
    ("D2", "유창성", "중간", 60), ("A2", "의미", "중간", 60), ("D1", "유창성", "쉬움", 60),
    ("C3", "말투", "중간", 60), ("A5", "의미", "중간", 60), ("A1", "의미", "쉬움", 60),
]
N_CONTROL = 300

PUNCT_TAIL = " .?!…\"'”’“‘~-"


def flat(text: str) -> str:
    """태그·줄바꿈을 걷어 한 줄로 만든다. 줄바꿈은 이 시험이 보는 것이 아니다(검사 T16)."""
    t = re.sub(r"<[^>]+>|\{[^}]*\}", "", text).replace("\n", " ")
    return re.sub(r"\s+", " ", t).strip()


def is_cue(text: str) -> bool:
    """효과음·화자 표시만 있는 셀([..]·(..))."""
    return bool(re.fullmatch(r"(\s*[\[\(][^\]\)]*[\]\)]\s*)+", flat(text)))


def split_tail(t: str):
    body = t.rstrip(PUNCT_TAIL)
    return body, t[len(body):]


def iou(a, b) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def mutual_pairs(ko, en):
    """시간 겹침(IoU)이 서로 가장 큰 한국어·영어 셀만 짝으로 한다."""
    def best(src, dst):
        starts = [d["start"] for d in dst]
        out = {}
        for i, s in enumerate(src):
            lo = bisect.bisect_left(starts, s["start"] - 3000)
            hi = bisect.bisect_right(starts, s["end"] + 3000)
            cand = [(iou((s["start"], s["end"]), (dst[j]["start"], dst[j]["end"])), j) for j in range(lo, hi)]
            if cand:
                out[i] = max(cand)
        return out
    bk, be = best(ko, en), best(en, ko)
    return [(i, j, v) for i, (v, j) in bk.items() if v >= IOU_PAIR and be.get(j, (0, -1))[1] == i]


def load_work(name: str, en_rel: str, ko_rel: str) -> dict:
    def cells(rel):
        return [dict(idx=e.index, start=e.start_ms, end=e.end_ms, text=flat(e.text))
                for e in parse(CORPUS / rel) if e.text.strip() and not is_cue(e.text)]
    en, ko = cells(en_rel), cells(ko_rel)
    return dict(name=name, en=en, ko=ko, pairs=mutual_pairs(ko, en), noun_stems=noun_stems(ko))


def noun_stems(ko) -> set:
    """어간(조사를 뗀 말)이 이 작품 자막에서 서로 다른 조사 둘 이상과 함께 나온 것 — 명사로 본다."""
    seen = {}
    for k in ko:
        for t in k["text"].split(" "):
            core = t.rstrip(",.?!…\"'”’")
            if particle_ok(core):
                seen.setdefault(core[:-1], set()).add(core[-1])
    return {s for s, ps in seen.items() if len(ps) >= 2}


# ---- 주입 함수: 변형 문자열을 돌려주고, 적용할 수 없으면 None ----------------------------
# 모든 함수는 (text, rng, ctx, en)을 받는다. en은 짝지은 영어 원문 셀이다.
# 유형마다 "의도한 오류만 생겼는가"가 기준이다(표본 점검, 설계 문서 6-3절):
#   A: 원문과 견줘 뜻이 틀리되 한국어는 문법에 맞아야 한다
#   C: 말투만 바뀌고 문법에는 맞아야 한다
#   D: 뜻은 그대로고 문법만 틀려야 한다

NUMWORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NUMWORDS.update(thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90, hundred=100, dozen=12,
                first=1, second=2, third=3, fourth=4, fifth=5, sixth=6, seventh=7, eighth=8, ninth=9, tenth=10)
TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}


def en_numbers(en: str) -> set:
    """영어 셀에 나온 수(숫자·영어 수사·서수·dozen·twenty-six 같은 합성어)."""
    nums = {int(x) for x in re.findall(r"\d+", en.replace(",", ""))}
    words = re.findall(r"[a-z]+", en.lower())
    for i, w in enumerate(words):
        if w in NUMWORDS:
            nums.add(NUMWORDS[w])
        if w in TENS and i + 1 < len(words) and 1 <= NUMWORDS.get(words[i + 1], 0) <= 9:
            nums.add(NUMWORDS[w] + NUMWORDS[words[i + 1]])
    return nums


def has_batchim(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 != 0


def particle_ok(core: str) -> bool:
    """어절 끝이 받침과 맞는 조사 모양인가(이·은·을은 받침 뒤, 가·는·를은 받침 없는 글자 뒤)."""
    if len(core) < 3 or core[-1] not in "이가은는을를":
        return False
    prev = core[-2]
    if not (0xAC00 <= ord(prev) <= 0xD7A3):
        return False
    return has_batchim(prev) == (core[-1] in "이은을")


def a1(text, rng, ctx, en):
    """같은 작품의 다른 셀 번역으로 통째 교체(길이 ±30%). 문법은 온전하고 뜻만 완전히 다르다."""
    n = len(text.replace(" ", ""))
    pool = [k["text"] for k in ctx["ko"] if k["text"] != text and 0.7 * n <= len(k["text"].replace(" ", "")) <= 1.3 * n]
    return rng.choice(pool) if pool else None


CONNECT = ("고", "며", "면", "서", "지만", "는데", "은데", "니까", "면서", "려고", "도록", "다가", "자")
NOT_CONNECT = ("에서", "로서", "에게서", "한테서")


def a2(text, rng, ctx, en):
    """누락. 남은 말이 문장으로 성립하는 세 방법만 쓴다(어절을 무작위로 빼면 한국어는 거의 비문이 된다 — 1라운드 표본 4/20).
    (가) 두 화자 셀에서 한 화자의 말을 뺀다 (나) 문장이 둘 이상이면 한 문장을 뺀다
    (다) 앞쪽 종속절(…고·며·면·지만·는데 등으로 끝나는 어절까지)을 뺀다."""
    opts = []
    if text.startswith("- ") and " - " in text:
        parts = text[2:].split(" - ")
        if len(parts) == 2 and all(p.strip() for p in parts):
            opts.append("- " + rng.choice(parts).strip())
    sents = re.split(r"(?<=[.?!]) ", text)
    if len(sents) >= 2:
        k = rng.randrange(len(sents))
        kept = " ".join(sents[:k] + sents[k + 1:])
        # 뺀 문장이 2어절 이상이고 남은 말에 없는 내용일 때만(반복되는 감탄문을 빼면 정보가 줄지 않는다)
        if len(sents[k].split(" ")) >= 2 and sents[k].strip(" .?!") not in kept:
            opts.append(kept)
    toks = text.split(" ")
    if "-" not in toks:
        # 첫 어절만 빼는 것('하지만' 같은 접속어)은 뜻이 줄지 않으므로 2어절 이상 뺄 때만 쓴다
        for i in range(1, max(1, len(toks) - 3)):
            core = toks[i].rstrip(",")
            if len(core) >= 2 and core.endswith(CONNECT) and not core.endswith(NOT_CONNECT):
                opts.append(" ".join(toks[i + 1:]))
                break
    return rng.choice(opts) if opts else None


NUM = re.compile(r"(?<![\d,.:])\d+(?![\d,.:])")


def a3(text, rng, ctx, en):
    """숫자 변경. 바뀌는 수는 영어 원문에도 있는 수여야 한다(원문에서 확인할 수 없는 오류는 시험이 안 된다)."""
    src = en_numbers(en)
    ms = [m for m in NUM.finditer(text) if int(m.group()) in src]
    if not ms:
        return None
    m = rng.choice(ms)
    n = int(m.group())
    if n < 10:
        choices = [d for d in range(1, 10) if d != n and d not in src]
        if not choices:
            return None
        new = rng.choice(choices)
    else:
        new = None
        for _ in range(10):
            d = rng.randint(1, max(1, n // 5))
            cand = n + d if rng.random() < 0.5 else n - d
            if cand > 0 and cand != n and len(str(cand)) == len(str(n)) and cand not in src:
                new = cand
                break
        if new is None:
            return None
    return text[:m.start()] + str(new) + text[m.end():]


PARTICLES = "이가은는도만에께"


def a4(text, rng, ctx, en):
    """부정 뒤집기: '안'·'못' 어절 삭제, 또는 있다↔없다 맞바꾸기."""
    toks = text.split(" ")
    opts = []
    for i, t in enumerate(toks):
        if t in ("안", "못"):
            opts.append(("del", i))
        if i > 0 and t[:1] in ("있", "없") and not t.startswith("없이") and toks[i - 1][-1:] in PARTICLES:
            opts.append(("swap", i))
    if not opts:
        return None
    kind, i = rng.choice(opts)
    if kind == "del":
        return " ".join(toks[:i] + toks[i + 1:])
    toks[i] = ("없" if toks[i][0] == "있" else "있") + toks[i][1:]
    return " ".join(toks)


FINAL_END = ("요", "니다", "죠", "어", "아", "야", "지", "네", "다", "까", "냐")   # 문장을 끝맺는 어미('자'·'니'는 연결 어미와 겹쳐 뺀다)
CONJ_START = ("하지만", "그러나", "그리고", "그래서", "그런데", "그렇지만")


def a5(text, rng, ctx, en):
    """추가: 다른 셀의 짧은 완결 문장(2~5어절, 숫자 없음)을 뒤에 붙인다. 문법은 온전하고 원문에 없는 말이 늘어난다.
    이음새가 깨지지 않게 원본도 문장을 끝맺는 어미로 끝나야 하고, 붙는 문장은 접속어로 시작하지 않는다."""
    if not split_tail(text)[0].endswith(FINAL_END) or len(text.split(" ")) < 3:
        return None
    shorts = [k["text"] for k in ctx["ko"] if k["text"] != text and 2 <= len(k["text"].split(" ")) <= 5
              and split_tail(k["text"])[0].endswith(FINAL_END) and not k["text"].startswith(CONJ_START + ("-",))
              and not NUM.search(k["text"])]
    return text + " " + rng.choice(shorts) if shorts else None


PRON_FIRST = ("나", "내", "너", "네", "넌", "난", "저", "제", "우리", "그", "이", "걔", "쟤")
# 주어 조사(이·가·은·는)로 끝나는 듯 보이지만 주어가 아닌 어절: 부사(…없이·같이)와 부사어 뒤의 '는'(…에는·로는)
NOT_SUBJECT = ("없이", "같이", "많이", "높이", "깊이", "길이", "가까이", "일찍이", "에는", "에서는", "로는", "으로는", "에도")


def c3(text, rng, ctx, en):
    """인칭대명사: 문장 앞쪽의 **주어** 명사구(…이/가/은/는)를 '그는/그가'로 바꾼다. 작업 기본 원칙 640행이 금지한다.
    목적어(을/를)·부사·시간 표현은 바꾸지 않는다(1라운드 표본에서 목적어까지 바뀌어 문장이 깨졌다)."""
    toks = text.split(" ")
    if len(toks) < 5 or toks[0] == "-" or any(toks[0].startswith(p) for p in PRON_FIRST):
        return None
    # 앞 두 어절 안에서만 찾는다(셋째 어절부터는 안긴 절의 주어나 수식어가 섞인다).
    # 어간이 말뭉치에서 서로 다른 조사 둘 이상과 함께 쓰인 명사여야 한다 — '버티는'(수식어 는)·'십자가'(명사 끝 가)를 거른다.
    for k in range(min(2, len(toks) - 2)):
        core = toks[k].rstrip(",")
        if (core[-1:] in "이가은는" and particle_ok(core) and not core.endswith(NOT_SUBJECT)
                and core[:-1] in ctx["noun_stems"]):
            pron = "그는" if core[-1] in "은는" else "그가"
            return " ".join([pron] + toks[k + 1:])
    return None


def d1(text, rng, ctx, en):
    """어절 순서를 섞는다(원래 순서와 60% 이상 달라지게)."""
    body, tail = split_tail(text)
    toks = body.split(" ")
    # 문장 안쪽에 ?!.가 있는 셀은 섞으면 문장 끝 부호가 가운데로 가서 다른 오류가 섞인다
    if len(toks) < 6 or "-" in toks or re.search(r"[?!.]", body):
        return None
    for _ in range(30):
        perm = toks[:]
        rng.shuffle(perm)
        if sum(a != b for a, b in zip(perm, toks)) >= 0.6 * len(toks):
            return " ".join(perm) + tail
    return None


SWAP_FORM = {"이": "가", "가": "이", "은": "는", "는": "은", "을": "를", "를": "을"}


def d2(text, rng, ctx, en):
    """조사 이형태 오류: 받침과 맞게 쓴 조사를 짝 이형태로 바꾼다(사람가·브라운는). 뜻은 그대로고 맞춤법만 틀린다."""
    toks = text.split(" ")
    opts = []
    for i, t in enumerate(toks):
        core = t.rstrip(",.?!…\"'”’")
        if particle_ok(core):
            opts.append((i, core, t[len(core):]))
    if not opts:
        return None
    i, core, trail = rng.choice(opts)
    toks[i] = core[:-1] + SWAP_FORM[core[-1]] + trail
    return " ".join(toks)


FUNCS = dict(A1=a1, A2=a2, A3=a3, A4=a4, A5=a5, C3=c3, D1=d1, D2=d2)


def make_row(w, i, j, v, code, crit, level, var):
    ko = w["ko"]
    return dict(work=w["name"], srt_index=ko[i]["idx"], en_index=w["en"][j]["idx"], iou=round(v, 3), type=code,
                criterion=crit, difficulty=level, en=w["en"][j]["text"], ko_orig=ko[i]["text"], ko=var,
                prev2=[k["text"] for k in ko[max(0, i - 2):i]], next1=[k["text"] for k in ko[i + 1:i + 2]])


def build(seed: int):
    works = {n: load_work(n, *paths) for n, paths in load_sets().items()}
    pool, control_pool = [], []
    for w in works.values():
        for i, j, v in w["pairs"]:
            if v >= IOU_INJECT:
                pool.append((w["name"], i, j, v))
            if v >= IOU_CONTROL:
                control_pool.append((w["name"], i, j, v))
    used, rows, report = set(), [], {}
    for code, crit, level, n_target in TYPES:
        rng = random.Random(f"{seed}-{code}")
        cands = pool[:]
        rng.shuffle(cands)
        fn, got, applicable = FUNCS[code], 0, 0
        for work, i, j, v in cands:
            if (work, i) in used:
                continue
            w = works[work]
            k = w["ko"][i]
            var = fn(k["text"], rng, w, w["en"][j]["text"])
            if var is None or var == k["text"]:
                continue
            applicable += 1
            if got < n_target:
                used.add((work, i))
                rows.append(make_row(w, i, j, v, code, crit, level, var))
                got += 1
        report[code] = dict(target=n_target, built=got, applicable_in_pool=applicable)
    rng = random.Random(f"{seed}-O")
    rng.shuffle(control_pool)
    built = 0
    for work, i, j, v in control_pool:
        if (work, i) in used or built >= N_CONTROL:
            continue
        used.add((work, i))
        w = works[work]
        rows.append(make_row(w, i, j, v, "O", "대조", "-", w["ko"][i]["text"]))
        built += 1
    report["O"] = dict(target=N_CONTROL, built=built, applicable_in_pool=len(control_pool))
    for n, r in enumerate(rows, 1):
        r["uid"] = n
    return works, rows, report, len(pool)


def self_check(rows):
    """변형이 의도한 만큼만 바뀌었는지 기계로 확인한다. (uid, 이유) 목록을 돌려준다."""
    bad, seen = [], set()
    for r in rows:
        t, o, v = r["type"], r["ko_orig"], r["ko"]
        key = (r["work"], r["srt_index"])
        if key in seen:
            bad.append((r["uid"], "같은 셀을 두 번 씀"))
        seen.add(key)
        if t == "O":
            if v != o:
                bad.append((r["uid"], "대조군이 변형됨"))
            continue
        if v == o:
            bad.append((r["uid"], "변형이 원본과 같음"))
        if t == "A2" and not (v.strip(" -") and len(v) < len(o)):
            bad.append((r["uid"], "A2가 줄지 않았거나 비어 있음"))
        if t == "A5" and not (v.startswith(o + " ") and split_tail(o)[0].endswith(FINAL_END)):
            bad.append((r["uid"], "A5가 원본 뒤에 붙인 꼴이 아니거나 원본이 문장 끝 어미로 끝나지 않음"))
        if t == "C3" and not (v.startswith(("그는 ", "그가 ")) and not o.startswith(("그는", "그가"))):
            bad.append((r["uid"], "C3가 '그는/그가'로 시작하지 않음"))
        if t == "A3" and re.sub(r"\d+", "#", v) != re.sub(r"\d+", "#", o):
            bad.append((r["uid"], "A3가 숫자 밖도 바뀜"))
        if t == "D1" and sorted(split_tail(v)[0].split(" ")) != sorted(split_tail(o)[0].split(" ")):
            bad.append((r["uid"], "D1이 어절 집합을 바꿈"))
        if t == "D2" and not (len(v) == len(o) and sum(a != b for a, b in zip(v, o)) == 1):
            bad.append((r["uid"], "D2가 한 글자만 바뀌지 않음"))
    return bad


def write_outputs(rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"set_{VERSION}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with open(EVIDENCE / f"judge_injection_set_{VERSION}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uid", "work", "srt_index", "en_index", "iou", "type", "criterion", "difficulty"])
        for r in rows:
            w.writerow([r["uid"], r["work"], r["srt_index"], r["en_index"], r["iou"], r["type"], r["criterion"], r["difficulty"]])
    # 사람이 읽어 점검할 표본: 유형마다 20개(무작위, 시드 고정)
    lines = ["# 변형 표본 점검 (유형별 20개)", "", "대사가 들어 있다. git에 올리지 않는다(`.work/`).", ""]
    for code, crit, level, _ in TYPES:
        sel = [r for r in rows if r["type"] == code]
        random.Random(f"sample-check-{code}").shuffle(sel)
        lines += [f"## {code} ({crit}, {level}) — 전체 {len(sel)}개 중 {min(20, len(sel))}개", ""]
        for r in sel[:20]:
            lines.append(f"- #{r['uid']} ({r['work']} {r['srt_index']})")
            if code.startswith("A"):
                lines.append(f"  - 원문: {r['en']}")
            lines.append(f"  - 원본: {r['ko_orig']}")
            lines.append(f"  - 변형: {r['ko']}")
        lines.append("")
    (OUT / f"sample_check_{VERSION}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20261017)
    args = ap.parse_args()
    works, rows, report, n_pool = build(args.seed)
    print(f"시드 {args.seed}, 작품 {len(works)}개, 짝(IoU>={IOU_PAIR}) "
          f"{sum(len(w['pairs']) for w in works.values())}개, 주입 풀(IoU>={IOU_INJECT}) {n_pool}개")
    for code, r in report.items():
        print(f"  {code}: 목표 {r['target']:>3} 만듦 {r['built']:>3} (풀에서 적용 가능 {r['applicable_in_pool']})")
    bad = self_check(rows)
    print(f"기계 점검: 셀 {len(rows)}개, 이상 {len(bad)}건")
    for uid, why in bad[:10]:
        print("  -", uid, why)
    write_outputs(rows)
    print(f"저장: {OUT / f'set_{VERSION}.jsonl'}, {OUT / f'sample_check_{VERSION}.md'}, {EVIDENCE / f'judge_injection_set_{VERSION}.csv'}")


if __name__ == "__main__":
    main()
