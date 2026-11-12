"""SE4를 번역 칸이 있는 상태로 연다(번역 자막 + 원문 자막 + 영상).

사용: python se_open_pair.py TRANSLATION.srt ORIGINAL.srt VIDEO
SE4 설정 `Settings.xml`의 최근 파일 맨 앞에 OriginalFileName 을 단 항목을 넣고, SE4를 인자 없이 연다
(설정 StartLoadLastFile=True 라 마지막 파일을 원문과 함께 연다). 2026-11-12 확인: 창 제목이
«번역.srt + 원문.srt - Subtitle Edit 4.0.16»으로 열렸다.
"""
import os, subprocess, sys, time
import xml.etree.ElementTree as ET
from pathlib import Path

tr, orig, video = (str(Path(p).resolve()) for p in sys.argv[1:4])
se_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Subtitle Edit 4"
settings = se_dir / "Settings.xml"
subprocess.run(["powershell", "-NoProfile", "-Command",
                f"Get-Process SubtitleEdit -EA SilentlyContinue | ? {{ $_.Path -like '{se_dir}*' }} | "
                "% { $_.CloseMainWindow() | Out-Null; $_.WaitForExit(15000) | Out-Null }"])
left = subprocess.run(["powershell", "-NoProfile", "-Command",
                       f"@(Get-Process SubtitleEdit -EA SilentlyContinue | ? {{ $_.Path -like '{se_dir}*' }}).Count"],
                      capture_output=True, text=True).stdout.strip()
if left not in ("", "0"):
    # SE는 번역+원문을 열기만 해도 «변경됨(*)»으로 표시해 닫을 때 저장을 묻는다.
    # 사용자 지정(2026-11-12): «저장 안 함으로 닫으면 된다» → 저장하지 않고 닫는다
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    f"Get-Process SubtitleEdit -EA SilentlyContinue | ? {{ $_.Path -like '{se_dir}*' }} | Stop-Process"])
    time.sleep(2)
tree = ET.parse(settings)
names = tree.getroot().find("RecentFiles/FileNames")
for e in list(names):
    if e.text == tr:
        names.remove(e)
e = ET.Element("FileName", {"VideoFileName": video, "OriginalFileName": orig, "AudioTrack": "-1",
                            "FirstVisibleIndex": "0", "FirstSelectedIndex": "0"})
e.text = tr
names.insert(0, e)
tree.write(settings, encoding="utf-8", xml_declaration=True)
subprocess.Popen([str(se_dir / "SubtitleEdit.exe")])
time.sleep(10)
out = subprocess.run(["powershell", "-NoProfile", "-Command",
                      "Get-Process SubtitleEdit -EA SilentlyContinue | % MainWindowTitle"], capture_output=True, text=True)
print("SE 창:", out.stdout.strip())
