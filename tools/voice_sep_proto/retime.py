"""텍스트 단위로 자막을 정하고, 인점·아웃점은 음성 트랙 파형에서 다시 잡는다. 시제품.

사용: python retime.py VOICE.wav OFFSET_SEC OUT.srt UNITS.json
출력: OUT.srt(참고용), OUT.voice.json(음성 시작·끝 -> rules_frames.py 입력)
- 텍스트: 방송 화면 글자(fix7/text.srt, 화면 직접 읽기)를 기준으로 삼았다. whisper 전사는 오인식이 많다
  (E01에서 여러 곳, 세지 않음). 화면 글자와 음성이 다른 곳은 사람이 확인한다
- 끊는 자리: 화면 글자의 뜻 단위(자막 하나 = 화면 자막 하나)
- 인점: UNITS.json에 적은 값(근거 표시). 자동 재탐색은 쓰지 않는다
  1차 음성 TC(cues.json) 인점, 없으면 파형을 20ms 간격으로 찍어 읽은 값
- 음성 끝: 다음 자막 인점 30ms 전까지에서 최고치 -25dB(최소 -38dBFS) 이상이 이어진 마지막 지점. 0.35초 넘게 조용하면 끝
- TC 규칙(작업 기본 원칙 600~604행): 인점 = 음성 시작 3프레임 전, 아웃점 = 음성 끝 7프레임 뒤, 최소 길이 우선
- 규칙(간격 메우기·최소 간격·겹침·장면전환)은 rules_frames.py가 OUT.voice.json을 읽어 건다. 여기서 쓰는 OUT.srt는 참고용
"""
import json
import sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

path, OFFSET, out_srt = sys.argv[1], float(sys.argv[2]), sys.argv[3]
FRAME = 1001 / 30000
MIN_DUR = 5 / 6

# UNITS.json: [[인점(영상 기준 초), 텍스트, 근거], ...]. 줄바꿈은 화면 그대로. 인점은 탐색하지 않고 이 값을 쓴다.
# 근거 "1차" = voice_tc.py가 잡은 인점(정답 인점과 대조해 ±25ms 확인된 방식),
#      "파형" = 음성 트랙 포락선을 20ms 간격으로 찍어 끊김 직후 상승을 직접 읽은 값,
#      "불확실" = 앞말과 끊김이 뚜렷하지 않아 사람 확인이 필요한 값
# (자동 재탐색은 앞말이 이어지는 곳에서 창 시작점을 인점으로 잡아 버려 쓰지 않는다: E01 130.040초 사례)
# 텍스트는 방송사 자막이라 공개 저장소에 두지 않는다. UNITS.json은 작업 폴더에만 있다.
UNITS = [tuple(u) for u in json.load(open(sys.argv[4], encoding="utf-8"))]

sr0, x = wavfile.read(path)
a = resample_poly(x.astype(np.float32).mean(1) / 32768, 160, 441)
SR, HOP = 16000, 80
hop_t = HOP / SR
n = len(a) // HOP
env = 10 * np.log10(np.convolve((a[: n * HOP] ** 2).reshape(n, HOP).mean(1), np.ones(2) / 2, "same") + 1e-10)


END_DROP, END_MIN = 25, -38     # 그 자막 최고치 -25dB(최소 -38dBFS) 이상이 20ms 이어지는 곳을 말로 본다
END_BREAK = 0.35                # 말 뒤 이만큼 조용하면 말이 끝난 것. 그 뒤 소리는 효과음이 샌 것이다(181.5초 총소리)


def offset(on, limit):
    """음성 끝. 1차(voice_tc.py) 끝점과 중앙값 5ms 차이(41건)"""
    i0, i1 = max(int(on / hop_t), 0), min(int(limit / hop_t), n)
    thr = max(env[i0:i1].max() - END_DROP, END_MIN)
    last, quiet = None, 0
    for k in range(i0 + 3, i1):
        if env[k - 3:k + 1].mean() >= thr:
            last, quiet = k, 0
        elif last is not None:
            quiet += 1
            if quiet * hop_t > END_BREAK:
                break
    return (last + 1) * hop_t if last is not None else limit


# 작업자 자료 「작업 기본 원칙」 600~604행(TC 따기):
#   인점은 보이스 시작 전 0.1초 이내(2~3프레임), 아웃점은 보이스 끝난 후 0.2~0.3초 이내(6~9프레임),
#   음성이 겹치면 다음 말소리의 인점 우선, 아웃점 규칙보다 Minimum Duration이 우선
LEAD_IN, LAG_OUT = 3 * FRAME, 7 * FRAME

rows = [[t - OFFSET, text] for t, text, _ in UNITS]
cues = []
for i, (on, text) in enumerate(rows):
    limit = rows[i + 1][0] - 0.03 if i + 1 < len(rows) else min(on + 7, n * hop_t)
    limit = min(limit, on + 7)
    cues.append({"vin": on, "vout": offset(on, limit), "text": text})

snap_in = lambda t: np.floor((t + OFFSET) / FRAME + 1e-6) * FRAME
snap_out = lambda t: np.ceil((t + OFFSET) / FRAME - 1e-6) * FRAME
for i, c in enumerate(cues):
    c["in"], c["out"] = snap_in(max(c["vin"] - LEAD_IN, 0)), snap_out(c["vout"] + LAG_OUT)
    # 겹침(다음 인점 우선)·간격은 tc_rules_nf.py가 정리한다
    if c["out"] - c["in"] < MIN_DUR:
        nxt = snap_in(max(cues[i + 1]["vin"] - LEAD_IN, 0)) if i + 1 < len(cues) else 1e9
        c["out"] = min(c["in"] + np.ceil(MIN_DUR / FRAME - 1e-6) * FRAME, nxt - 2 * FRAME)


def fmt(t):
    ms = int(round(t * 1000))
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


json.dump([{"voice_in": round(c["vin"] + OFFSET, 4), "voice_out": round(c["vout"] + OFFSET, 4), "text": c["text"],
            "basis": u[2]} for c, u in zip(cues, UNITS)],
          open(out_srt.rsplit(".", 1)[0] + ".voice.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(out_srt, "w", encoding="utf-8") as f:
    for i, c in enumerate(cues, 1):
        f.write(f"{i}\n{fmt(c['in'])} --> {fmt(c['out'])}\n{c['text']}\n\n")
print(f"자막 {len(cues)}, 불확실 {sum(1 for u in UNITS if u[2] == '불확실')}: {[u[0] for u in UNITS if u[2] == '불확실']}")
