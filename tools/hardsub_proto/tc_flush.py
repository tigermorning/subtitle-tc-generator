"""최소 보정판(v7): 방송 글자 프레임(픽셀) TC를 기준으로 삼고, 이어진 자막만 딱 붙인다. 시제품.

사용: python tc_flush.py TEXT.srt PIXEL.srt AUDIO.srt OUT.srt REPORT.txt [FPS]
  TEXT.srt   번호별 최종 텍스트. `[읽기 실패]`로 시작하는 자막은 뺀다(제작진 크레딧·광고 띠 등)
  PIXEL.srt  픽셀 신호로 잡은 인점·아웃점(프레임 정확)
  AUDIO.srt  audio_snap.py 결과(인점만 글자 뒤 150ms 안의 큰 음성 시작으로 당겨진 것)
규칙은 둘뿐이다.
  1) 인점 = AUDIO.srt의 인점, 아웃점 = PIXEL.srt의 아웃점
  2) 방송에서 바로 이어진 쌍(아웃 프레임과 다음 인 프레임 간격이 1프레임 이내)은 앞 자막 아웃점 = 다음 자막 인점
간격 메우기·장면전환 맞추기는 하지 않는다. 사용자 SE 파란 선 5건에서 그 보정들이 정답에서 멀어졌다.
"""
import re, sys

text_srt, pix_srt, aud_srt, out_srt, report = sys.argv[1:6]
FPS = float(sys.argv[6]) if len(sys.argv) > 6 else 30000 / 1001
FR = 1000.0 / FPS


def parse(ts):
    h, m, s, ms = map(int, re.findall(r"\d+", ts))
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def fmt(ms):
    ms = int(ms // 10 * 10)      # SE 미리보기(ASS 10ms 반올림)에서도 그 프레임에 뜨도록 10ms 내림
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


def load(path):
    r = {}
    for b in open(path, encoding="utf-8").read().strip().split("\n\n"):
        L = b.split("\n")
        a, e = [parse(x) for x in L[1].split(" --> ")]
        r[int(L[0])] = (a, e, "\n".join(L[2:]))
    return r


text, pix, aud = load(text_srt), load(pix_srt), load(aud_srt)
keep = [n for n in sorted(text) if not text[n][2].startswith("[읽기 실패]")]
cue = {n: [aud[n][0], pix[n][1]] for n in keep}       # [인, 아웃]
flushed, shifted, log = 0, 0, []
for n in keep:
    if aud[n][0] != pix[n][0]:
        shifted += 1
        log.append(f"#{n} in {fmt(pix[n][0])} -> {fmt(aud[n][0])}  글자 뒤 {aud[n][0] - pix[n][0]}ms의 큰 음성 시작")
for n in keep:
    m = n + 1
    if m in cue and pix[m][0] - pix[n][1] <= FR + 10 and cue[m][0] > cue[n][0]:
        cue[n][1] = cue[m][0]
        flushed += 1
bad = sum(1 for n in keep if cue[n][1] <= cue[n][0])
overlap = sum(1 for n, m in zip(keep, keep[1:]) if cue[m][0] < cue[n][1])
print(f"cues {len(keep)}, 인점 당김 {shifted}, 딱 붙임 {flushed}, 길이 역전 {bad}, 겹침 {overlap}")
with open(out_srt, "w", encoding="utf-8") as f:
    for k, n in enumerate(keep, 1):
        f.write(f"{k}\n{fmt(cue[n][0])} --> {fmt(cue[n][1])}\n{text[n][2]}\n\n")
with open(report, "w", encoding="utf-8") as f:
    f.write(f"# 조정 기록 (원 번호 기준). 인점 당김 {shifted}, 딱 붙임 {flushed}\n")
    f.write("\n".join(log) + "\n")
print("wrote", out_srt)
