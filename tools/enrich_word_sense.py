"""en-ko-word-sense.yaml 후보 낱말에 권위 있는 영-미 사전 뜻풀이를 구워 넣는다.

**왜 실시간 조회가 아닌가.** 교정기가 국립국어원 API를 매번 부르는 건 후보(고유
명사)가 영상마다 새로 생기기 때문이다 — 미리 구울 수가 없다. 이 낱말 사전은
다르다. 사람이 고른 고정 목록이고(`checker/word_sense.py`의 `trigger_words()`),
영상이 바뀐다고 늘어나지 않는다. 그래서 **사람이 항목을 늘릴 때 한 번만** 이
스크립트를 돌려 결과를 파일로 구워 두면 되고, 번역 실행 경로는 그 뒤로 인터넷을
안 탄다(규칙6 — 로컬 전용, 클론한 다른 컴퓨터에서도 그대로 됨).

**낱말 하나씩만 내보낸다.** 대사·문맥·파일 이름은 절대 나가지 않는다 —
`trigger_words()`가 주는 것도 이미 사전에 손으로 올려 둔 일반 영어 단어일 뿐,
미공개 작품에서 뽑은 것이 아니다(`webterms.py`와 같은 원칙).

    python tools/enrich_word_sense.py                 # 사전의 후보 전부 새로 조회
    python tools/enrich_word_sense.py --only little,block
    python tools/enrich_word_sense.py --dry-run        # 조회만 하고 파일에 안 씀

키가 없으면: Merriam-Webster는 https://dictionaryapi.com/register/index 에서
바로 무료 발급, Oxford는 https://developer.oxforddictionaries.com/ 에서 가입
후 발급. `.env`(저장소 루트)에 다음을 넣거나 환경변수로 준다.

    MERRIAM_WEBSTER_API_KEY=...
    OXFORD_APP_ID=...
    OXFORD_APP_KEY=...

키가 하나만 있어도 그것만으로 채운다 — 둘 다 없으면 아무것도 조회하지 않고
알린다(예외를 올리지 않는다: 이 스크립트는 손으로 가끔 돌리는 보조 도구다).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checker.word_sense import DICT_CACHE_PATH, trigger_words  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MW_URL = "https://www.dictionaryapi.com/api/v3/references/collegiate/json/{word}"
OXFORD_URL = "https://od-api.oxforddictionaries.com/api/v2/entries/en-us/{word}"

HEADER = (
    "# Merriam-Webster·Oxford 공식 뜻풀이 캐시 — 기계가 생성한다, 손으로 고치지 않는다.\n"
    "#\n"
    "# `tools/enrich_word_sense.py`가 `en-ko-word-sense.yaml`의 후보 낱말을 사전\n"
    "# API로 조회해서 채운다. 실행 경로(`checker/word_sense.py`)는 이 파일이\n"
    "# 없어도 동작한다 — 있으면 손으로 쓴 note 뒤에 덧붙인다.\n"
    "\n"
    "schema_version: 1\n"
    "kind: dictionary-cache\n"
    "source:\n"
    "  official: true\n"
    "  origin: api\n"
    "\n"
)


def _load_dotenv() -> None:
    """저장소 루트 `.env`를 읽어 없는 값만 채운다. 이미 있는 환경변수는 안 건드린다."""
    import os

    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_json(url: str, headers: dict, timeout: int = 10):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _collect_strings(obj, key: str) -> list[str]:
    """중첩된 dict/list 안에서 `key` 아래 문자열 목록을 다 모은다.

    Oxford 응답은 lexicalEntries -> entries -> senses -> definitions로 깊이
    중첩돼 있고 하위 의미(subsenses)까지 있어, 정확한 스키마를 다 따라가는
    대신 구조를 훑어 모은다."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, list):
                found.extend(s for s in v if isinstance(s, str))
            else:
                found.extend(_collect_strings(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_collect_strings(item, key))
    return found


def fetch_mw(word: str, api_key: str) -> list[str] | None:
    url = MW_URL.format(word=urllib.parse.quote(word)) + f"?key={api_key}"
    try:
        data = _get_json(url, headers={})
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  MW 조회 실패({word}): {exc}")
        return None
    # 정확히 못 찾으면 API가 제안 문자열 목록(list[str])을 준다 — 뜻풀이가 아니다.
    entries = [e for e in (data or []) if isinstance(e, dict)]
    if not entries:
        print(f"  MW: '{word}' 표제어를 못 찾았습니다(제안만 옴).")
        return None
    defs: list[str] = []
    for entry in entries:
        defs.extend(entry.get("shortdef") or [])
    return defs or None


def fetch_oxford(word: str, app_id: str, app_key: str) -> list[str] | None:
    url = OXFORD_URL.format(word=urllib.parse.quote(word.lower()))
    headers = {"app_id": app_id, "app_key": app_key}
    try:
        data = _get_json(url, headers=headers)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  Oxford 조회 실패({word}): {exc}")
        return None
    defs = _collect_strings(data, "definitions")
    return defs or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", help="쉼표로 구분한 낱말만 조회(기본: 사전 전체 후보)")
    ap.add_argument("--dry-run", action="store_true", help="조회만 하고 파일에 쓰지 않는다")
    args = ap.parse_args()

    _load_dotenv()
    import os
    mw_key = os.environ.get("MERRIAM_WEBSTER_API_KEY")
    oxford_id = os.environ.get("OXFORD_APP_ID")
    oxford_key = os.environ.get("OXFORD_APP_KEY")

    if not mw_key and not (oxford_id and oxford_key):
        print("MERRIAM_WEBSTER_API_KEY도 OXFORD_APP_ID/OXFORD_APP_KEY도 없습니다.")
        print("발급: https://dictionaryapi.com/register/index (Merriam-Webster)")
        print("      https://developer.oxforddictionaries.com/ (Oxford)")
        print("받은 키를 저장소 루트 .env에 넣거나 환경변수로 주세요.")
        return 1

    words = [w.strip() for w in args.only.split(",")] if args.only else trigger_words()
    if not words:
        print("조회할 낱말이 없습니다 — en-ko-word-sense.yaml에 항목이 있는지 확인하세요.")
        return 1

    print(f"{len(words)}개 낱말을 조회합니다: {', '.join(words)}")
    if not mw_key:
        print("  (MERRIAM_WEBSTER_API_KEY 없음 — MW는 건너뜁니다)")
    if not (oxford_id and oxford_key):
        print("  (OXFORD_APP_ID/OXFORD_APP_KEY 없음 — Oxford는 건너뜁니다)")

    existing: dict[str, dict] = {}
    if DICT_CACHE_PATH.is_file():
        existing = (yaml.safe_load(DICT_CACHE_PATH.read_text(encoding="utf-8")) or {}).get("entries") or {}

    today = date.today().isoformat()
    for word in words:
        print(f"- {word}")
        record = existing.get(word, {})
        if mw_key:
            mw_defs = fetch_mw(word, mw_key)
            if mw_defs:
                record["mw"] = mw_defs
        if oxford_id and oxford_key:
            ox_defs = fetch_oxford(word, oxford_id, oxford_key)
            if ox_defs:
                record["oxford"] = ox_defs
        if record.get("mw") or record.get("oxford"):
            record["fetched"] = today
            existing[word] = record

    if args.dry_run:
        print("\n--dry-run — 파일에 쓰지 않았습니다.")
        for word in words:
            print(f"{word}: {existing.get(word)}")
        return 0

    DICT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"entries": existing}, allow_unicode=True, sort_keys=True,
                          default_flow_style=False)
    DICT_CACHE_PATH.write_text(HEADER + body, encoding="utf-8")
    print(f"\n{DICT_CACHE_PATH}에 {len(existing)}개 항목을 저장했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
