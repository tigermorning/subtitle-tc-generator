"""이 영상의 정답지가 이미 있는지 먼저 본다.

## 왜 필요한가

`CLAUDE.md` 규칙 13은 "정답지가 있는 영상은 정답지 학습(A)부터, 예외 없이"라고
정해 놨다. 그런데 규칙이 글로만 있으면 지켜지지 않는다 — 실제로 두 번 어겼다.

    2026-08-28~29   정답지 있는 회차의 초안을 3차 윤문까지 입혀 "완성본"으로
                    전달함. 정답지 자체가 이미 완성본이라 값어치가 0이었다
                    (`docs/AGENT_INCIDENTS.md` 5번)
    2026-08-30      `[습작] SDH+번역/`의 새 영상을 "정답지 없다"고 단정하고
                    whisper로 5회차를 통째로 생성함. mkv 안에 디즈니 정식 한국어
                    SDH 트랙이 이미 있었다(규칙 17 다섯 번째 사고)

두 번째 사고는 `media.list_subtitle_streams`(영상 **안**의 자막 트랙을 센다)로
막았다. 이 파일은 남은 절반이다 — 영상 **밖**에, 우리가 이미 추출해 둔 정답지가
있는 경우. 규칙 9의 pre-commit 훅과 같은 방식이다: 기억에 맡기지 않고 기계가 알린다.

## 어디를 보나

    rules/private/corpus/corpus_status.yaml   `video:` 경로가 그대로 적혀 있다. 가장 확실한 근거 —
                              `truth:`(정답지 경로)와 이미 끝난 단계까지 함께 안다
    학습한 TC 및 자막 모음/    `<플랫폼>_<제목>/E<회차>_<언어>_<종류>.srt`.
                              제목·회차를 파일 이름에서 맞춰 본다

## 무엇을 하지 않나

**막지 않는다.** 제목 맞추기는 파일 이름에서 하는 **추정**이고, 추정으로 실행을
막으면 이름만 비슷한 다른 작품에서 일을 못 하게 된다(규칙 4 — 추정은 알리기만
한다). `--generate`를 계속 돌릴지는 사람이 정한다.

**정답지를 열어 보지 않는다.** 있다는 사실만 알린다. 내용을 읽어 초안에 섞으면
그것은 학습이 아니라 복제다(규칙 13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRUTH_ROOT = REPO_ROOT / "학습한 TC 및 자막 모음"
def _status_file() -> Path:
    """원장이 놓인 자리. **비공개 쪽이 먼저다.**

    원장에는 작품 제목·릴리즈 파일명·로컬 절대 경로가 그대로 적힌다. 저장소가
    공개라 그대로 둘 수 없어 비공개 저장소(`rules/private/corpus/`)로 옮겼다
    (`.gitignore` 참고). 없으면 옛 자리를 본다 — 없어도 이 기능은 **막지 않는다**
    (아래 "무엇을 하지 않나").
    """
    private = REPO_ROOT / "rules" / "private" / "corpus" / "corpus_status.yaml"
    return private if private.is_file() else REPO_ROOT / "docs" / "corpus_status.yaml"


STATUS_FILE = _status_file()

# 릴리즈 파일 이름의 군더더기. 제목만 남기려고 자르는 자리다.
_JUNK = re.compile(
    r"\b(1080p|720p|2160p|480p|web-?dl|webrip|bluray|bdrip|hdtv|x264|x265|h264|h265"
    r"|hevc|aac\d?\.?\d?|ddp?\+?\d?\.?\d?|atmos|nf|dsnp|amzn|atvp|hmax|repack|proper)\b",
    re.I)
# 회차 표기. `E15`, `15회`, `S02E15`, `.19회.` 등.
_EPISODE = re.compile(r"(?:s\d{1,2})?e(\d{1,3})\b|(\d{1,3})\s*회", re.I)


def normalize_title(text: str) -> str:
    """제목 비교용으로 납작하게 만든다.

    **`시즌`/`season`도 지운다.** 정답지 폴더는 `드라마C`인데 영상 이름은
    `드라마C 시즌3`처럼 오는 일이 실제로 있다 — 양쪽에서 똑같이 지우면 맞는다.
    """
    text = _JUNK.sub(" ", text)
    text = re.sub(r"(시즌|season)", " ", text, flags=re.I)
    return re.sub(r"[^0-9a-z가-힣]+", "", text.lower())


def episode_of(name: str) -> str | None:
    """파일 이름에서 회차 번호를 뽑는다. 없으면 `None`(영화 등)."""
    m = _EPISODE.search(_JUNK.sub(" ", name))
    if not m:
        return None
    return str(int(m.group(1) or m.group(2)))


@dataclass(frozen=True)
class AnswerKey:
    path: Path
    source: str            # "corpus_status" | "folder"
    episode: str | None = None
    detail: str = ""
    label: str = ""        # 화면에 낼 이름. 비면 파일 이름을 쓴다

    @property
    def shown(self) -> str:
        return self.label or self.path.name


def _truth_path(raw: str) -> tuple[Path, str]:
    """`corpus_status.yaml`의 `truth:` 값에서 경로를 꺼낸다.

    **사람이 손으로 적는 칸이라 주석이 붙어 있다** — 예: `.../E06_영어_번역.srt
    (Viki_.../E06_영어_번역.srt도 있음)`. 괄호를 무조건 떼면 괄호가 든 진짜 파일
    이름을 망가뜨리므로, **파일이 실제로 있는 쪽**을 고른다.
    """
    text = str(raw).strip()
    full = REPO_ROOT / text
    if full.is_file() or " (" not in text:
        return full, ""
    head = text.split(" (", 1)[0].strip()
    trimmed = REPO_ROOT / head
    if trimmed.is_file():
        return trimmed, ""
    # 둘 다 못 찾았다. 적힌 그대로 보여 준다 — 우리가 고쳐 쓰지 않는다(규칙 13).
    return full, text


def _from_status(video: Path, status_file: Path) -> tuple[list[AnswerKey], list[str]]:
    """`corpus_status.yaml`에서 **같은 영상 파일**을 찾는다. 이름이 같아야 한다."""
    try:
        import yaml
    except ImportError:  # 규정 파일을 읽을 때와 같은 의존성이라 실제로는 늘 있다
        return [], []
    try:
        data = yaml.safe_load(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return [], []
    if not isinstance(data, dict):
        return [], []

    found: list[AnswerKey] = []
    done: list[str] = []
    target = video.name.lower()
    for work, wdata in (data.get("works") or {}).items():
        for ep, edata in ((wdata or {}).get("episodes") or {}).items():
            recorded = (edata or {}).get("video")
            if not recorded or Path(str(recorded)).name.lower() != target:
                continue
            for kind, kdata in ((edata or {}).get("kinds") or {}).items():
                truth = (kdata or {}).get("truth")
                if truth:
                    path, label = _truth_path(truth)
                    found.append(AnswerKey(
                        path, "corpus_status", str(ep),
                        f"{work} {ep}회 {kind}", label))
                # 이미 끝난 단계를 다시 돌리지 않게 함께 알린다(규칙 17 2번).
                for stage, sdata in ((kdata or {}).get("pipeline") or {}).items():
                    if isinstance(sdata, dict) and sdata.get("done"):
                        done.append(f"{work} {ep}회 {kind}: {stage} "
                                    f"({sdata.get('date', '날짜 미상')})")
    return found, done


def _from_folder(video: Path, root: Path) -> list[AnswerKey]:
    """`학습한 TC 및 자막 모음/`에서 제목이 맞는 폴더를 찾는다."""
    if not root.is_dir():
        return []

    stem = normalize_title(video.stem)
    want_ep = episode_of(video.name)
    out: list[AnswerKey] = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or folder.name.startswith("_"):
            continue
        # `넷플릭스_예능A` -> 앞의 플랫폼 딱지를 뗀다.
        title = folder.name.split("_", 1)[-1]
        flat = normalize_title(title)
        if not flat or flat not in stem:
            continue
        for path in sorted(folder.glob("*.srt")):
            ep = episode_of(path.name)
            # 회차를 양쪽에서 알아냈는데 다르면 다른 회차다 — 그래도 같은 작품이라
            # 뒤에서 "이 작품 정답지가 있다"고는 말한다(`detail`에 남긴다).
            out.append(AnswerKey(path, "folder", ep,
                                 "같은 회차" if ep and ep == want_ep else "다른 회차"))
    return out


def find(video: Path, truth_root: Path | None = None,
         status_file: Path | None = None) -> tuple[list[AnswerKey], list[str]]:
    """`(찾은 정답지, 이미 끝난 단계)`. 못 찾으면 둘 다 빈 목록."""
    status_file = STATUS_FILE if status_file is None else status_file
    truth_root = TRUTH_ROOT if truth_root is None else truth_root

    keys, done = ([], [])
    if status_file.is_file():
        keys, done = _from_status(video, status_file)
    seen = {k.path for k in keys}
    keys += [k for k in _from_folder(video, truth_root) if k.path not in seen]
    return keys, done


def tc_state(truth: Path, status_file: Path | None = None) -> tuple[bool, str] | None:
    """이 정답지의 TC 검증(`tc_verified`)이 원장에 기록됐는지.

    `(끝났는가, 라벨)`. 원장에서 이 정답지를 못 찾으면 `None` — **모른다와 안
    끝났다는 다르다**(규칙 3). 코퍼스 밖 자료로 대조하는 일도 흔하다.

    규칙 15("TC를 먼저 100% 맞춘 뒤에 자막 텍스트")를 확인하는 자리에서 쓴다.
    """
    status_file = STATUS_FILE if status_file is None else status_file
    if not status_file.is_file():
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        data = yaml.safe_load(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None

    want = truth.name.lower()
    for work, wdata in (data.get("works") or {}).items():
        for ep, edata in ((wdata or {}).get("episodes") or {}).items():
            for kind, kdata in ((edata or {}).get("kinds") or {}).items():
                raw = (kdata or {}).get("truth")
                if not raw:
                    continue
                path, _ = _truth_path(raw)
                if path.name.lower() != want:
                    continue
                stage = ((kdata or {}).get("pipeline") or {}).get("tc_verified") or {}
                return bool(stage.get("done")), f"{work} {ep}회 {kind}"
    return None


def warning(keys: list[AnswerKey], done: list[str]) -> str | None:
    """사람에게 낼 경고. 찾은 게 없으면 `None`."""
    if not keys and not done:
        return None

    lines: list[str] = []
    same = [k for k in keys if k.source == "corpus_status" or k.detail == "같은 회차"]
    other = [k for k in keys if k not in same]

    if same:
        lines.append(f"경고: 이 영상의 정답지가 이미 있습니다({len(same)}개).")
        for k in same[:6]:
            lines.append(f"      - {k.shown}" + (f"  ({k.detail})" if k.detail else ""))
        if len(same) > 6:
            lines.append(f"      … 외 {len(same) - 6}개")
    elif other:
        lines.append(f"경고: 같은 작품의 정답지가 이미 있습니다"
                     f"(다른 회차 {len(other)}개). 이 회차 것은 못 찾았습니다.")
        for k in other[:4]:
            lines.append(f"      - {k.shown}")

    if done:
        lines.append("      이미 끝난 단계가 기록돼 있습니다:")
        for row in done[:6]:
            lines.append(f"      - {row}")

    lines.append("      정답지가 있는 영상은 **정답지 학습(A)이 먼저입니다**"
                 "(규칙 13) — `정답지-학습` 스킬로 먼저 확인하세요.")
    lines.append("      whisper로 초안을 만드는 것은 도구를 고치려고 대조할 때"
                 "(`--against`)만 필요합니다. 완성본을 만드는 일이 아닙니다.")
    return "\n".join(lines)
