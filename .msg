chore: 저장소 이름을 '자막 및 TC 생성기'로 바꾼다

편집기가 아니라 **생성기**다. 영상 하나에서 전사 -> 대조 -> 번역 -> 재분할 ->
스포팅까지 만들어 내는 것이 이 도구가 하는 일이고, 이름이 그것을 가리지 않아야 한다.

GitHub 저장소를 `subtitle-editor` -> `subtitle-tc-generator`로 바꿨다. 아직 아무
곳에도 배포하지 않았으므로 주소가 바뀌어도 영향이 없다(사용자 확인).

- `README.md`·`CLAUDE.md` 제목 변경
- **`README.md`의 낡은 줄을 고쳤다** — "아직 코드는 없다. 규정 데이터와 설계 문서만
  있다"가 남아 있었다. `app/`·`checker/` 7,700줄이 있는 지금은 사실이 아니고, 실제로
  이 줄 때문에 다른 세션이 이 프로젝트를 코드 없는 저장소로 오해했다.
- **`checker/webterms.py`의 USER_AGENT** — 옛 GitHub 주소가 박혀 있었다. 이건 웹
  서버로 실제로 나가는 값이라 틀리면 안 된다.
- `plugin/se4/Runner.cs` — 저장소 추측 경로에 새 이름을 **추가**했다. 옛 이름도 계속
  본다. 이미 `subtitle-editor`로 받아 둔 사람이 깨지면 안 된다.
- `docs/SE_PLUGIN.md` 조회 순서 표 갱신

로컬 폴더 이름은 그대로 뒀다(`내 문서\subtitle-editor`). 바꾸려면 이 커밋의 추측
경로가 이미 새 이름을 보고 있으므로 그때 폴더만 옮기면 된다.

교정기와의 관계도 README에 한 줄로 적었다 — 자막 지식은 이 저장소가, 한국어 규범
지식은 `korean-subtitle-corrector`가 갖는다.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
