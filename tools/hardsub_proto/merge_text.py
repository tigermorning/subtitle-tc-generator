"""화면을 직접 읽은 결과(read.tsv)를 자막 파일에 합친다. 시제품.

사용: python merge_text.py PIXEL.srt READ.tsv AUDIO.srt OUT_TEXT.srt OUT_AUDIO_READ.srt
  PIXEL.srt   hardsub_tc.py 결과. 번호와 글자 프레임 TC의 기준
  READ.tsv    번호<TAB>분류<TAB>텍스트. 분류는 D(대사) / N(자막 없음) / X(자막 아님). 두 줄은 `|`로 잇는다
  AUDIO.srt   audio_snap.py 결과(인점 보정)
  OUT_TEXT.srt        PIXEL의 TC + 읽은 텍스트. N·X는 `[읽기 실패] 이유`로 적는다. tc_flush.py 입력
  OUT_AUDIO_READ.srt  AUDIO의 TC + 읽은 텍스트. tc_rules_nf.py 입력(번호는 PIXEL 기준 그대로)
빠진 번호·남는 번호·알 수 없는 분류가 있으면 아무것도 쓰지 않고 멈춘다(조용히 넘어가지 않는다).
"""
import re, sys
from collections import Counter

pixel, tsv, audio, out_text, out_audio = sys.argv[1:6]


def load_srt(path):
    r = {}
    for b in open(path, encoding="utf-8").read().strip().split("\n\n"):
        L = b.split("\n")
        r[int(L[0])] = (L[1], "\n".join(L[2:]))
    return r


pix, aud = load_srt(pixel), load_srt(audio)
rows = {}
for line in open(tsv, encoding="utf-8").read().splitlines():
    if not line.strip():
        continue
    cols = line.split("\t")
    if len(cols) < 2 or not cols[0].isdigit():
        sys.exit(f"read.tsv 형식이 아닙니다: {line[:60]!r}")
    n = int(cols[0])
    if n in rows:
        sys.exit(f"read.tsv에 번호 {n}이 두 번 있습니다")
    rows[n] = (cols[1], cols[2] if len(cols) > 2 else "")

missing = sorted(set(pix) - set(rows))
extra = sorted(set(rows) - set(pix))
bad = sorted(n for n, (c, _) in rows.items() if c not in ("D", "N", "X"))
if missing or extra or bad or set(aud) != set(pix):
    sys.exit(f"합치기를 멈춥니다 — 아직 안 읽은 번호 {len(missing)}개 {missing[:10]}, "
             f"PIXEL에 없는 번호 {len(extra)}개 {extra[:10]}, 알 수 없는 분류 {len(bad)}개 {bad[:10]}, "
             f"AUDIO와 PIXEL 번호 불일치 {set(aud) != set(pix)}")


def text_of(n):
    cls, t = rows[n]
    if cls == "D":
        if not t.strip():
            sys.exit(f"번호 {n}: 분류 D인데 텍스트가 비어 있습니다")
        return t.replace("|", "\n")
    return f"[읽기 실패] {t}".rstrip()


for path, times in ((out_text, pix), (out_audio, aud)):
    with open(path, "w", encoding="utf-8") as f:
        for n in sorted(pix):
            f.write(f"{n}\n{times[n][0]}\n{text_of(n)}\n\n")
print(f"{len(pix)}구간 합침 — {dict(Counter(c for c, _ in rows.values()))}")
print("wrote", out_text, out_audio)
