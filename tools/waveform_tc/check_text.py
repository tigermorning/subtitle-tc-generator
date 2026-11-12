"""자막 글자가 실제 대사와 맞는지 전수조사한다(받아쓰기와 나란히 놓고 비교).

사용: python check_text.py CLIP.srt ASR.srt [OUT.tsv]
- ASR.srt 는 같은 구간 분리 음성을 ffmpeg whisper 필터로 받아쓴 것(시각은 구간 기준).
- 받아쓰기는 글자 검사에만 쓴다. TC(인점·아웃점)는 바꾸지 않는다.
- 자막마다 시간이 겹치는 받아쓰기 글자를 모아 유사도를 내고, 낮은 것을 «확인 필요»로 표시한다.
"""
import re, sys, difflib


def read(p):
    t = open(p, encoding="utf-8-sig").read()
    f = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    out = []
    for b in re.findall(r"(\d+)\n(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)\n(.*?)(?:\n\n|\Z)", t, re.S):
        out.append((int(b[0]), f(*b[1:5]), f(*b[5:9]), re.sub(r"<[^>]+>", "", b[9]).replace("\n", " ").strip()))
    return out


norm = lambda s: re.sub(r"[^a-z0-9' ]", "", s.lower().replace("’", "'")).split()
cues, asr = read(sys.argv[1]), read(sys.argv[2])
rows = []
for n, a, b, txt in cues:
    heard = " ".join(x[3] for x in asr if x[1] < b + 0.3 and x[2] > a - 0.3)
    r = difflib.SequenceMatcher(None, norm(txt), norm(heard)).ratio()
    rows.append((n, a, b, txt, heard, r))
bad = [x for x in rows if x[5] < 0.6]
print(f"자막 {len(rows)}개, 받아쓰기와 많이 다름(유사도 0.6 미만) {len(bad)}개")
for n, a, b, txt, heard, r in bad:
    print(f"  #{n} {a:7.2f}-{b:7.2f} {r:.2f} | 자막: {txt} | 받아쓰기: {heard}")
if len(sys.argv) > 3:
    with open(sys.argv[3], "w", encoding="utf-8") as f:
        f.write("번호\t인점\t아웃점\t유사도\t자막\t받아쓰기\n")
        for n, a, b, txt, heard, r in rows:
            f.write(f"{n}\t{a:.3f}\t{b:.3f}\t{r:.2f}\t{txt}\t{heard}\n")
