# 인계: PE-A-Frame으로 말소리 구간 찾기 실험 (2026-11-13, 아이펠 PC → GPU PC)

## 목표
Meta의 `facebook/pe-a-frame-small`(글로 묘사한 소리가 언제 나는지 40ms마다 점수를 내는 모델)이
TC 인·아웃 잡기에 도움이 되는지 본다. 토이스토리5 05-08분 한 장면으로 기존 파형 TC와 비교한다.

## 지금까지 한 일
- 모델 카드 원문·설정 파일 3개·transformers 5.22.2 소스(`models/pe_audio/`)를 읽었다. 확인한 사실은 `tools/pea_frame_probe.py` 머리말에 있다.
  - 48kHz 모노, 1프레임 = 1920샘플 = 40ms, 위치 한도 10000프레임(약 400초).
  - 점수는 `sigmoid(out.logits_audio_text[0, 0])`(학습된 scale·bias 포함). 모델 카드의 `spans`·`threshold`는 transformers에 없다.
- `tools/pea_frame_probe.py` 작성: 점수 → 임계값 0.1~0.7로 구간 자르기 → SRT 인·아웃과 차이(ms), ±42ms·±125ms 비율, 자막별 표, 그림 저장.
  비교 로직만 가짜 점수로 점검했다(실제 모델은 한 번도 못 돌림).
- Colab 노트북판: 프로젝트 폴더 `experiments/pea_frame_compare/pea_frame_compare.ipynb`(저장소 밖, 이 PC에만 있음). GPU PC에서는 위 스크립트를 쓰면 된다.

## 결정과 이유
- 아이펠 PC에서는 못 돌림: Windows 응용 프로그램 제어 정책이 pip로 받은 torch DLL을 막음(`WinError 4551`, `torch_global_deps.dll`). 보안 설정은 바꾸지 않는다.
- 임계값은 고정값 목록으로 훑는다(기존 TC에 맞춰 고르면 숫자가 실제보다 좋게 나옴).
- 앞뒤 자막과 50ms 안으로 붙은 경계는 채점에서 뺀다(말소리 검출로는 나눌 수 없음).

## 열린 문제
- **정답 TC가 아직 없다.** 사용자가 05-08분을 SE에서 고쳐 저장해 주기로 함. 그전 결과는 '기존 파형 TC와의 일치도'이지 정확도가 아니다.
- 40ms 단위라 프레임 단위 정확도는 기대하기 어렵다(? 추정, 결과로 확인).

## 다음 첫 행동 (GPU PC)
1. `git pull` (이 문서와 스크립트가 들어 있음).
2. D: 드라이브 연결 확인 — 입력이 `D:\자막TC생성기\습작 SDH+번역\토이스토리5\파형TC_05-08분\`의 `voice_only.wav`(30MB), `clip_음성만.srt`.
3. 별도 가상환경에 설치 후 실행:
   ```
   python -m venv .venv-pea
   .venv-pea\Scripts\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
   .venv-pea\Scripts\pip install "transformers>=5.22" soundfile numpy matplotlib
   .venv-pea\Scripts\python tools\pea_frame_probe.py --wav "D:\자막TC생성기\습작 SDH+번역\토이스토리5\파형TC_05-08분\voice_only.wav" --srt "D:\자막TC생성기\습작 SDH+번역\토이스토리5\파형TC_05-08분\clip_음성만.srt" --out "D:\자막TC생성기\습작 SDH+번역\토이스토리5\파형TC_05-08분\pea_out"
   ```
   CUDA 버전(cu124)은 그 PC의 `nvidia-smi`를 보고 맞춘다. 첫 줄 `장치: cuda …`를 확인.
4. 결과(`summary.json`, `per_cue.txt`, `plot.png`)를 사용자에게 보고. 원음(`src.wav`, 음악 섞임)으로도 한 번 돌려 음악 구간에서 말소리를 가르는지 본다.

## 건드린 파일·상태
- 새 파일: `tools/pea_frame_probe.py`, `docs/HANDOFF-pea-frame.md`.
- 저장소 밖: `C:\Users\Aiffel\.venvs\pea`(이 PC, DLL이 막혀 못 쓰는 환경 — 사용자 허락 후 지움).

## 확인한 것과 못 한 것
- 확인: 설정·소스의 입출력, 비교 로직(가짜 점수, 붙은 경계 제외 동작).
- 못 함: 실제 모델 실행, 처리 단계(`PeAudioProcessor`)에 `sampling_rate` 인자를 넘겨도 되는지(소스의 `__call__` 인자 목록 미확인 — 오류 나면 인자를 빼 본다).
