"""원어 자막을 한국어 초벌로 옮긴다 — 이 컴퓨터 안에서.

**밖으로 보내지 않는다.** 방송 전 영상과 대본은 유출되면 계약이 깨지는 물건이다.
번역 API에 붙이면 편하지만 작업자가 쓸 수 없다. 그래서 로컬 모델만 부른다.

**자막 번역은 문장 번역이 아니다.** 이 모듈이 신경 쓰는 것:

    한 자막 = 한 화면      자막을 합치거나 쪼개지 않는다. 타임코드가 붙어 있다.
    앞뒤 맥락              한 줄만 떼어 주면 대명사와 존댓말이 무너진다.
    표기 통일              같은 인물·지명이 자막마다 달라지면 안 된다.
    태그 보존              [화자명], 이탤릭, 음표는 번역 대상이 아니다.

**글자 수는 여기서 맞추지 않는다.** 번역이 끝난 **뒤** 한국어에 대해 재분할한다
(`resplit.py`). 원어 기준으로 끊어 놓으면 한국어가 거기에 갇힌다.

**초벌이다.** 기계가 낸 것을 사람이 고친다. 그래서 확신 없는 자리를 감추지 않고
표시한다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .model import Event

# 번역하지 않고 그대로 넘길 것들. 화자명·효과음·음표는 표기 규정의 영역이라
# 모델이 손대면 규정이 무너진다.
KEEP = re.compile(r"(\{\\[^}]*\}|</?[a-zA-Z][^>]*>|♪+)")


class TranslatorUnavailable(RuntimeError):
    pass


@dataclass
class Glossary:
    """표기 통일표. 발주처가 주면 그대로 따르고, 없으면 비워 둔다."""
    terms: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile: dict) -> "Glossary":
        consistency = profile.get("consistency") or {}
        return cls(dict(consistency.get("glossary") or {}))

    def merge_terms(self, terms: dict) -> "Glossary":
        self.terms.update({k: v for k, v in (terms or {}).items() if k and v})
        return self

    def merge_knp(self, path) -> int:
        """KNP 시트를 먹는다. 작업자가 어차피 만드는 표다."""
        from .knp import read_terms

        before = len(self.terms)
        self.merge_terms(read_terms(path))
        return len(self.terms) - before

    def merge_file(self, path) -> "Glossary":
        """`원어<탭 또는 =>한국어` 한 줄에 하나. 주석은 #."""
        from pathlib import Path
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = re.split(r"\t|=>|\s*=\s*", line, maxsplit=1)
            if len(parts) == 2 and parts[0].strip():
                self.terms[parts[0].strip()] = parts[1].strip()
        return self

    def hint(self) -> str:
        if not self.terms:
            return ""
        pairs = ", ".join(f"{k} → {v}" for k, v in list(self.terms.items())[:40])
        return f"\n고정 표기(반드시 이대로): {pairs}"

    def check(self, source: str, target: str) -> list[str]:
        """통일표를 어긴 자리를 돌려준다. 고치지는 않는다 — 문맥에 따라 안 쓰는
        것이 맞을 때가 있어 기계가 단정할 수 없다."""
        missed = []
        for src, dst in self.terms.items():
            if re.search(re.escape(src), source, re.IGNORECASE) and dst not in target:
                missed.append(f"{src} → {dst}")
        return missed


# **번역 모델 기본값은 여기 하나뿐이다.** 세 곳에 흩어져 있었고 값이 달랐다 —
# 두 백엔드 클래스는 qwen, 설정 화면과 CLI 도움말은 exaone. 그래서 GUI가 설정을
# 읽지 않던 동안 사용자는 exaone으로 도는 줄 알고 qwen으로 돌렸다.
#
# exaone3.5는 한국어가 낫지만(실측) **상업 이용에 제약이 있는 라이선스**다.
# qwen2.5는 Apache 2.0이다. 바꿔 쓸 수 있게 설정에 열어 둔다.
DEFAULT_MODEL = "exaone3.5:7.8b"
OPEN_LICENCE_MODEL = "qwen2.5:7b-instruct"


class OllamaTranslator:
    """Ollama에 붙는다. 모델은 이 컴퓨터에서 돈다.

    WSL에서 돌 때는 Windows 쪽 Ollama를 봐야 한다 — GPU가 거기 붙어 있다.
    `OLLAMA_HOST`가 있으면 그것을 쓰고, 없으면 WSL 게이트웨이(=Windows 호스트)를
    먼저 보고 안 되면 localhost를 본다.
    """

    def __init__(self, model: str | None = None, host: str | None = None,
                 timeout: int = 300):
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.host = host or self._find_host()

    @staticmethod
    def _candidates() -> list[str]:
        hosts = []
        env = os.environ.get("OLLAMA_HOST")
        if env:
            hosts.append(env if env.startswith("http") else f"http://{env}")
        try:  # WSL -> Windows 호스트
            out = subprocess.run(["ip", "route", "show", "default"],
                                 capture_output=True, text=True, timeout=5).stdout
            gateway = out.split()[2] if len(out.split()) > 2 else ""
            if gateway:
                hosts.append(f"http://{gateway}:11434")
        except Exception:
            pass
        hosts.append("http://127.0.0.1:11434")
        return hosts

    @classmethod
    def _find_host(cls) -> str:
        for host in cls._candidates():
            try:
                with urllib.request.urlopen(f"{host}/api/tags", timeout=3):
                    return host
            except Exception:
                continue
        raise TranslatorUnavailable(
            "Ollama를 찾지 못했습니다. Windows에서 Ollama를 설치·실행한 뒤 모델을 "
            "받으세요:\n"
            "  winget install Ollama.Ollama\n"
            "  ollama pull qwen2.5:7b-instruct\n"
            "다른 자리에 있으면 OLLAMA_HOST로 알려 주세요(예: 172.27.112.1:11434).")

    def available_models(self) -> list[str]:
        with urllib.request.urlopen(f"{self.host}/api/tags", timeout=10) as res:
            return [m["name"] for m in json.load(res).get("models", [])]

    def ask(self, system: str, prompt: str) -> str:
        body = json.dumps({
            "model": self.model, "system": system, "prompt": prompt,
            "stream": False,
            # 자막 번역은 창작이 아니다. 낮게 잡아 흔들림을 줄인다.
            "options": {"temperature": 0.2, "top_p": 0.9, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return json.load(res).get("response", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if "not found" in detail:
                raise TranslatorUnavailable(
                    f"모델 {self.model}이(가) 없습니다. 받으세요: "
                    f"ollama pull {self.model}") from exc
            raise TranslatorUnavailable(f"Ollama 오류: {detail}") from exc
        except urllib.error.URLError as exc:
            raise TranslatorUnavailable(f"Ollama에 닿지 못했습니다: {exc.reason}") from exc


class OllamaCliTranslator:
    """`ollama` 명령을 직접 부른다.

    **왜 HTTP가 아니라 명령인가**: WSL에서 작업할 때 Windows 쪽 Ollama는
    127.0.0.1에만 붙어 있어 WSL에서 포트로 닿지 않는다(실측). 뚫으려면 Ollama를
    `0.0.0.0`에 열어야 하는데, 그건 같은 망의 다른 컴퓨터에도 열어 주는 일이다.
    작업자의 미공개 대본이 도는 자리에서 할 짓이 아니다.

    명령으로 부르면 아무 포트도 열지 않는다. Windows에서 그냥 쓰는 사람은
    `OllamaTranslator`(HTTP)가 그대로 된다.
    """

    WINDOWS_PATHS = (
        "/mnt/c/Users/{user}/AppData/Local/Programs/Ollama/ollama.exe",
        "/mnt/c/Program Files/Ollama/ollama.exe",
    )

    def __init__(self, model: str | None = None, exe: str | None = None,
                 timeout: int = 600):
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.exe = exe or self._find_exe()

    @classmethod
    def _find_exe(cls) -> str:
        import shutil
        for name in ("ollama", "ollama.exe"):
            found = shutil.which(name)
            if found:
                return found
        user = os.environ.get("WSL_USER") or os.environ.get("USER") or ""
        for pattern in cls.WINDOWS_PATHS:
            for candidate in ({pattern.format(user=user)}
                              | set(_windows_user_paths(pattern))):
                if os.path.isfile(candidate):
                    return candidate
        raise TranslatorUnavailable(
            "ollama 명령을 찾지 못했습니다. 설치하세요:\n"
            "  winget install Ollama.Ollama\n"
            f"  ollama pull qwen2.5:7b-instruct")

    def available_models(self) -> list[str]:
        out = subprocess.run([self.exe, "list"], capture_output=True, text=True,
                             timeout=60).stdout
        return [l.split()[0] for l in out.replace("\r", "").splitlines()[1:] if l.strip()]

    def ask(self, system: str, prompt: str) -> str:
        # 시스템 지시를 프롬프트 앞에 붙인다. `ollama run`에는 시스템 지시를 따로
        # 주는 자리가 없다.
        result = subprocess.run(
            [self.exe, "run", self.model],
            input=f"{system}\n\n{prompt}\n", capture_output=True, text=True,
            timeout=self.timeout, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            detail = (result.stderr or "").replace("\r", "").strip()[:200]
            if "not found" in detail:
                raise TranslatorUnavailable(
                    f"모델 {self.model}이(가) 없습니다. 받으세요: "
                    f"ollama pull {self.model}")
            raise TranslatorUnavailable(f"Ollama 오류: {detail}")
        return (result.stdout or "").replace("\r", "").strip()


def _windows_user_paths(pattern: str) -> list[str]:
    """WSL에서 Windows 사용자 폴더를 훑는다. 사용자 이름이 리눅스 쪽과 다를 수 있다."""
    import glob
    return glob.glob(pattern.replace("{user}", "*"))


# ---------------------------------------------------------------- 서버 챙기기
#
# **왜 프로그램이 직접 챙기나.** Ollama는 설치할 때 Windows 시작 폴더에 바로가기를
# 넣지만, 사용자가 트레이에서 닫으면 그대로 없어진다. 그 상태로 번역을 누르면
# "Ollama를 찾지 못했습니다"만 뜬다 — 고칠 방법을 알아도 번거롭고, 모르면 막힌다.
#
# 그래서 **없으면 띄운다.** 다만 두 자리에서 성격을 다르게 한다.
#
#   프로그램 시작    띄우고 기다리지 않는다. 시작이 느려지면 안 된다
#   번역 직전        준비될 때까지 잠깐 기다린다. 어차피 몇 분 걸리는 일이다

# 트레이 앱이 서버를 관리한다. `ollama.exe serve`를 직접 띄우면 트레이 없이 서버만
# 남아, 사용자가 그것을 끌 방법이 없다. Windows 시작 바로가기도 이 파일을 가리킨다.
_APP_EXE_NAMES = ("ollama app.exe", "ollama.exe")


def server_running(timeout: float = 1.5) -> bool:
    """서버가 응답하는가. **빨리 답한다** — 시작 경로에서 부르므로 오래 끌면 안 된다."""
    for host in OllamaTranslator._candidates():
        try:
            with urllib.request.urlopen(f"{host}/api/tags", timeout=timeout):
                return True
        except Exception:
            continue
    return False


def find_app() -> str | None:
    """트레이 앱(없으면 ollama.exe) 자리. 못 찾으면 None — 예외를 올리지 않는다."""
    import shutil

    for name in _APP_EXE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    user = os.environ.get("WSL_USER") or os.environ.get("USER") or ""
    for pattern in OllamaCliTranslator.WINDOWS_PATHS:
        for candidate in ({pattern.format(user=user)} | set(_windows_user_paths(pattern))):
            path = Path(candidate)
            if not path.is_file():
                continue
            # 같은 폴더의 트레이 앱을 먼저 쓴다.
            app = path.with_name("ollama app.exe")
            return str(app if app.is_file() else path)
    return None


def ensure_server(progress=None, wait_seconds: float = 0.0) -> bool:
    """서버가 없으면 띄운다. 이미 돌고 있으면 아무것도 하지 않는다.

    `wait_seconds`가 0이면 띄우기만 하고 바로 돌아온다(시작 경로). 값을 주면 그만큼
    응답을 기다린다(번역 직전).

    **어떤 경우에도 예외를 올리지 않는다.** 번역은 선택 기능이고, Ollama가 없다고
    프로그램이 못 뜨면 안 된다. 못 띄웠으면 거짓을 돌려주고 이유는 `progress`로 알린다.
    """
    say = progress or (lambda _m: None)
    if server_running():
        return True

    exe = find_app()
    if not exe:
        say("Ollama를 찾지 못해 번역 서버를 띄우지 못했습니다(번역만 안 됩니다).")
        return False

    try:
        # 창을 띄우지 않고, 우리 프로그램이 끝나도 살아 있게 떼어 놓는다.
        flags = 0
        for name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
            flags |= getattr(subprocess, name, 0)
        subprocess.Popen([exe], creationflags=flags, close_fds=True)
        say(f"번역 서버(Ollama)를 띄웠습니다: {Path(exe).name}")
    except Exception as exc:
        say(f"번역 서버를 띄우지 못했습니다({type(exc).__name__}). 번역만 안 됩니다.")
        return False

    if wait_seconds <= 0:
        return False        # 띄웠지만 아직 준비됐다고 말할 수는 없다

    # 모델을 올리는 것이 아니라 서버가 뜨는 것만 기다린다 — 보통 1~3초다.
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if server_running():
            say("번역 서버가 준비됐습니다.")
            return True
        time.sleep(0.5)
    say(f"번역 서버가 {wait_seconds:.0f}초 안에 준비되지 않았습니다.")
    return False


def make_translator(model: str | None = None, prefer_cli: bool | None = None):
    """쓸 수 있는 백엔드를 고른다. WSL이면 명령, 아니면 HTTP를 먼저 본다."""
    if prefer_cli is None:
        prefer_cli = "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False
    kwargs = {"model": model} if model else {}
    order = ([OllamaCliTranslator, OllamaTranslator] if prefer_cli
             else [OllamaTranslator, OllamaCliTranslator])
    problems = []
    for cls in order:
        try:
            return cls(**kwargs)
        except TranslatorUnavailable as exc:
            problems.append(str(exc))
    raise TranslatorUnavailable(problems[0])


# 작업자 자료(`작업 기본 원칙` [영상번역])에 적힌 규칙을 그대로 옮겼다. 번역기에게
# "잘 번역해라"라고 하면 소설처럼 쓴다 — 자막 번역은 규칙이 있는 글쓰기다.
SYSTEM = (
    "당신은 영상 번역가입니다. 영어 대사를 한국어 자막으로 옮깁니다.\n"
    "- 자막은 한 줄에 하나입니다. 번호를 합치거나 나누지 마세요.\n"
    "- 구어입니다. 문어체로 늘이지 말고 대사처럼 짧게 씁니다.\n"
    "- **마침표를 쓰지 않습니다.** 문장 끝에 쉼표도 쓰지 않습니다.\n"
    "- 문장 부호를 최소화합니다(쉼표·말줄임표·괄호).\n"
    "- 문장 요소를 최소화합니다. '수', '있', '것', 보조 용언, 극존칭 '-시-'를 덜어냅니다.\n"
    "- **인칭대명사를 쓰지 않습니다.** '그', '그녀', '그들'은 이름이나 호칭으로 바꾸거나 뺍니다.\n"
    "- 원문의 단어에 매달리지 말고 **의미**를 옮깁니다. 불필요한 말은 과감히 뺍니다.\n"
    "- 인물 관계에 맞는 말투를 유지합니다(존댓말/반말을 자막마다 바꾸지 마세요).\n"
    "  관계를 알 수 없으면 존댓말을 씁니다.\n"
    "- 한국 문화로 과하게 옮기지 않습니다(미국인이 한국식으로 말하면 어색합니다).\n"
    "- 대괄호 안의 화자명·효과음, 음표, 태그는 그대로 둡니다.\n"
    "- 설명을 덧붙이지 말고 번역만 냅니다."
)

# 다큐·리얼리티에는 더 붙는다. 드라마와 규칙이 다르다(작업자 자료).
DOCUMENTARY_RULES = (
    "\n- 다큐·리얼리티입니다. 호칭 '~씨'와 극존칭을 쓰지 않습니다."
)


@dataclass
class TranslatedCue:
    index: int
    source: str
    text: str
    note: str = ""


def _protect(text: str) -> tuple[str, tuple[str, str, bool]]:
    """태그를 **떼어 놓는다**. 모델에게는 맨 대사만 보여 준다.

    처음에는 자리표(`\\x01 0 \\x02`)로 바꿔 넣었는데, 모델이 그걸 대괄호로 바꿔
    버려 이탤릭이 통째로 날아갔다(exaone3.5 실측: `<i>She never…</i>` ->
    `[그녀는…]`). 자리표는 모델에게 낯선 기호이고 낯선 기호는 손을 탄다.

    그래서 태그는 보내지 않는다. 앞뒤에 붙어 있던 것을 기억했다가 번역문에 도로
    씌운다. 대사 한가운데 있던 태그는 되돌리지 않고 **표시한다** — 한국어 어순이
    달라 어디에 넣을지 기계가 알 수 없다.

    화자명 `[사라]`는 떼지 않는다. SDH에서 화자명은 한국어로 옮겨야 하는 대상이다.
    """
    head, tail, inner = "", "", False
    body = text
    while True:
        m = re.match(r"^\s*(\{\\[^}]*\}|</?[a-zA-Z][^>]*>|♪+)\s*", body)
        if not m:
            break
        head += m.group(1)
        body = body[m.end():]
    while True:
        m = re.search(r"\s*(\{\\[^}]*\}|</?[a-zA-Z][^>]*>|♪+)\s*$", body)
        if not m:
            break
        tail = m.group(1) + tail
        body = body[:m.start()]
    if KEEP.search(body):
        inner = True
        body = KEEP.sub(" ", body)
    return re.sub(r"\s+", " ", body).strip(), (head, tail, inner)


def _restore(text: str, frame: tuple[str, str, bool]) -> str:
    head, tail, _inner = frame
    joiner_head = " " if head.endswith("♪") else ""
    joiner_tail = " " if tail.startswith("♪") else ""
    return f"{head}{joiner_head}{text}{joiner_tail}{tail}"


def _parse_numbered(reply: str, expected: list[int]) -> dict[int, str]:
    """`3. 번역문` 꼴을 읽는다. 모델이 어떻게 답하든 번호를 붙잡는다."""
    found: dict[int, str] = {}
    current = None
    for line in reply.replace("\r\n", "\n").split("\n"):
        m = re.match(r"\s*(\d+)\s*[.):]\s*(.*)$", line)
        if m and int(m.group(1)) in expected:
            current = int(m.group(1))
            found[current] = m.group(2).strip()
        elif current is not None and line.strip():
            found[current] += "\n" + line.strip()
    return {k: v.strip() for k, v in found.items() if v.strip()}


def translate_events(events: list[Event], translator, glossary: Glossary | None = None,
                     batch: int = 12, context: int = 3,
                     progress=None) -> list[TranslatedCue]:
    """자막을 묶어 번역한다. **묶는 이유는 맥락이다.**

    한 줄씩 보내면 빠르지만 대명사와 말투가 자막마다 흔들린다. 앞의 몇 줄을
    함께 보여 주고 이어지는 대사로 옮기게 한다.

    번호가 빠지거나 개수가 어긋나면 그 자막만 다시 한 줄씩 묻는다 — 통째로 다시
    돌리면 잘 나온 것까지 흔들린다.
    """
    say = progress or (lambda _m: None)
    glossary = glossary or Glossary()
    out: list[TranslatedCue] = []
    done: list[TranslatedCue] = []

    for start in range(0, len(events), batch):
        chunk = events[start:start + batch]
        protected = [_protect(ev.text) for ev in chunk]

        before = ""
        if done and context:
            recent = done[-context:]
            before = ("이미 옮긴 앞부분입니다(참고만 하고 다시 내지 마세요):\n"
                      + "\n".join(f"  {c.source} → {c.text}" for c in recent) + "\n\n")

        numbered = "\n".join(f"{ev.index}. {body}"
                             for ev, (body, _) in zip(chunk, protected))
        prompt = (f"{before}다음 자막을 한국어로 옮기세요. "
                  f"**번호를 그대로 붙여 같은 개수로** 내세요."
                  f"{glossary.hint()}\n\n{numbered}")

        say(f"번역 {start + 1}~{start + len(chunk)} / {len(events)}")
        reply = translator.ask(SYSTEM, prompt)
        got = _parse_numbered(reply, [ev.index for ev in chunk])

        for ev, (body, frame) in zip(chunk, protected):
            text = got.get(ev.index, "")
            note = "대사 가운데 있던 태그를 되돌리지 못했습니다" if frame[2] else ""
            if not text:
                # 한 줄만 다시 묻는다. 그래도 안 되면 원문을 남긴다 — 빈 자막은
                # 사람이 못 보고 지나치지만 원문은 눈에 띈다.
                retry = translator.ask(SYSTEM, f"한국어 자막으로 옮기세요:\n{body}")
                text = retry.strip().split("\n")[0].strip()
                note = "번역이 흔들려 다시 물었습니다 — 확인이 필요합니다"
            if not text:
                text, note = ev.text, "번역하지 못했습니다 — 원문을 남겼습니다"

            text = _restore(text, frame)
            missed = glossary.check(ev.text, text)
            if missed:
                note = (note + " / " if note else "") + f"고정 표기 확인: {', '.join(missed)}"
            cue = TranslatedCue(ev.index, ev.text, text, note)
            out.append(cue)
            done.append(cue)

    return out


def to_events(cues: list[TranslatedCue], events: list[Event]) -> list[Event]:
    """번역문을 자막으로. 타임코드는 원어 것을 그대로 쓴다."""
    by_index = {c.index: c.text for c in cues}
    return [Event(ev.index, ev.start_ms, ev.end_ms, by_index.get(ev.index, ev.text))
            for ev in events]
