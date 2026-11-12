"""영상 한 구간의 TC를 처음부터 끝까지 만든다(사람 음성만, SE 파형 기준).

사용: python run_tc.py VIDEO START_SEC DUR_SEC OUTDIR FPS GAP_FRAMES KIND [SCRIPT.txt REF.srt MAX_CHARS]
  KIND = sdh(장면전환 앞뒤 0.5초 적용) | translation(장면전환 안 씀)
  REF.srt 는 영상 시각 기준(예: ffmpeg -i 영상 -map 0:s:0 ref.srt 로 뽑은 영상 안 자막 트랙)
순서(사용자 지정 2026-11-12):
 1) 구간 자르기(clip.mp4) 2) 사람 음성만 추출(5.1이면 센터 → Kim_Vocal_2 → Silero VAD)
 3) clip_음성만.mp4 를 SE4로 열어 **SE가 파형을 받게 한 뒤**
 4) 그 SE 파형 파일로 인점·아웃점(wave_tc.py) 5) SE를 닫고 결과로 다시 연다
"""
import os, subprocess, sys, time, shutil, glob
from pathlib import Path

if len(sys.argv) < 8 or sys.argv[7] not in ("sdh", "translation"):
    sys.exit("사용: run_tc.py VIDEO START DUR OUTDIR FPS GAP_FRAMES KIND  (GAP_FRAMES: 발주처 요청 0 또는 2, KIND: sdh|translation)")
video, start, dur, out, fps, gap, kind = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5], sys.argv[6], sys.argv[7]
# 선택: 대본이 있으면 SCRIPT.txt REF.srt(시각 있는 참고 자막) MAX_CHARS(한 자막 최대 글자: 영어 84, 한국어 32)
script, ref, max_chars = (sys.argv[8], sys.argv[9], sys.argv[10]) if len(sys.argv) > 10 else (None, None, None)
HERE = Path(__file__).resolve().parent
SE_DIR = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Subtitle Edit 4"
MODEL = Path.home() / "models" / "Kim_Vocal_2.onnx"
PY = sys.executable
out.mkdir(parents=True, exist_ok=True)
run = lambda *a: subprocess.run([str(x) for x in a], check=True)

layout = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                         "stream=channel_layout", "-of", "csv=p=0", video], capture_output=True, text=True).stdout.strip()
pan = ",pan=stereo|c0=FC|c1=FC" if layout.startswith(("5.1", "7.1")) else ""
print("소리 배치", layout, "→ 센터만" if pan else "→ 전체")
run("ffmpeg", "-v", "error", "-y", "-i", video, "-ss", start, "-t", dur, "-map", "0:a:0",
    "-af", "aresample=async=1:first_pts=0" + pan, "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out / "src.wav")
if not (os.environ.get("REUSE") and (out / "voice_sep.wav").exists()):
    run(PY, HERE / "separate_onnx.py", MODEL, out / "src.wav", out / "voice_sep.wav")
run(PY, HERE / "vad_mask.py", out / "voice_sep.wav", out / "voice_only.wav")
if not (os.environ.get("REUSE") and (out / "clip.mp4").exists()):
  run("ffmpeg", "-v", "error", "-y", "-ss", start, "-i", video, "-t", dur, "-map", "0:v:0", "-map", "0:a:0",
    "-vf", "scale=-2:720", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
    "-c:a", "aac", "-ac", "2", out / "clip.mp4")
run("ffmpeg", "-v", "error", "-y", "-i", out / "clip.mp4", "-i", out / "voice_only.wav", "-map", "0:v", "-map", "1:a",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out / "clip_음성만.mp4")


def se_close():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-Process SubtitleEdit -EA SilentlyContinue | ? {{ $_.Path -like '{SE_DIR}*' }} | "
                    "% { $_.CloseMainWindow() | Out-Null; $_.WaitForExit(15000) | Out-Null }"])


srt = out / "clip_음성만.srt"
import json


def se_waveform():
    """SE4를 clip_음성만.mp4 로 열어 파형을 받게 하고 se_waveform.wav 로 복사한다."""
    srt.write_text("1\n00:00:00,000 --> 00:00:00,500\n(파형 받는 중)\n\n", encoding="utf-8")
    se_close()
    before = set(glob.glob(str(SE_DIR / "Waveforms" / "*.wav")))
    subprocess.Popen([str(SE_DIR / "SubtitleEdit.exe"), str(srt)])
    for _ in range(180):  # SE가 파형을 받을 때까지 최대 3분
        time.sleep(1)
        new = set(glob.glob(str(SE_DIR / "Waveforms" / "*.wav"))) - before
        if new:
            wf = max(new, key=os.path.getmtime); time.sleep(2)
            shutil.copyfile(wf, out / "se_waveform.wav"); print("SE 파형", wf); return
        if _ == 30:
            # 소리가 전과 같으면 SE가 저장해 둔 파형을 다시 쓰고 새 파일을 만들지 않는다 →
            # 길이(초당 150점)가 이 구간과 맞는 가장 최근 파형을 쓴다
            import wave as _w
            cands = []
            for f in glob.glob(str(SE_DIR / "Waveforms" / "*.wav")):
                try:
                    with _w.open(f) as w:
                        if abs(w.getnframes() / w.getframerate() - float(dur)) < 0.5:
                            cands.append(f)
                except Exception:
                    pass
            if cands:
                wf = max(cands, key=os.path.getmtime)
                shutil.copyfile(wf, out / "se_waveform.wav"); print("SE 파형(저장된 것 재사용)", wf); return
    sys.exit("SE가 파형을 만들지 않았습니다(설정 WaveformAutoGenWhenOpeningVideo 확인)")


extra = []
if kind == "sdh":
    sys.path.insert(0, str(HERE.parents[1]))
    from checker.media import detect_shot_changes
    shots = detect_shot_changes(out / "clip.mp4")
    json.dump(shots, open(out / "shots.json", "w"))
    print("장면전환", len(shots), "개")
    extra = [out / "shots.json"]
os.environ["WAVE_TC_VAD_SRC"] = str(out / "voice_sep.wav")
os.environ.pop("WAVE_TC_KEEP", None)
for pass_no in (1, 2):
    se_waveform()
    run(PY, HERE / "wave_tc.py", out / "se_waveform.wav", out / "wave_only.srt", 0, fps, gap, *extra)
    if not script:
        shutil.copyfile(out / "wave_only.srt", srt); break
    # 대본 넣기: 대본 줄 시각은 시각 있는 참고 자막(영상 안 자막 트랙 등)에서 얻는다. 글자 수가 넘치면 쉼에서 나눈다
    run(PY, HERE / "fill_script.py", out / "wave_only.srt.json", out / "se_waveform.wav", script, ref,
        start, fps, gap, max_chars, srt)
    missing = json.load(open(str(srt) + ".unplaced.json", encoding="utf-8"))
    if pass_no == 2 or not missing:
        break
    # 2차: 대본 줄이 있는데 VAD가 놓친 자리(외침·아이·기계 목소리, 2026-11-12)를 대본 시각 ±0.3초 되살리고 다시 한다
    print("대본 자리를 못 찾은 줄", len(missing), "개 — 그 자리 소리를 되살려 다시 잡습니다")
    keep = out / "keep_script.json"
    json.dump([m[:2] for m in missing], open(keep, "w", encoding="utf-8"))
    run(PY, HERE / "vad_mask.py", out / "voice_sep.wav", out / "voice_only.wav", 0.5, 0.3, keep)
    run("ffmpeg", "-v", "error", "-y", "-i", out / "clip.mp4", "-i", out / "voice_only.wav", "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out / "clip_음성만.mp4")
    os.environ["WAVE_TC_KEEP"] = str(keep)
# 원본 영상 시각판
import re
def _shift(m):
    v = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000 + float(start)
    return f"{int(v // 3600):02d}:{int(v % 3600 // 60):02d}:{int(v % 60):02d},{int(round((v - int(v)) * 1000)) % 1000:03d}"
(out / "wave_tc_원본시각.srt").write_text(re.sub(r"(\d+):(\d+):(\d+),(\d+)", _shift, srt.read_text(encoding="utf-8")), encoding="utf-8")
shutil.copyfile(srt, out / "clip.srt")
se_close()
subprocess.Popen([str(SE_DIR / "SubtitleEdit.exe"), str(srt)])
print("완료:", srt)
