"""정답 대조에서 "글자가 얼마나 겹치나"가 아니라 "뜻이 얼마나 같나"를 잰다.

`align.similarity()`는 `SequenceMatcher`로 **글자 겹침**을 본다. 대본↔전사처럼
같은 언어·같은 문장을 대조할 때는 잘 맞는다(오타·조각남 정도의 차이). 하지만
`--against`로 우리 번역 초안과 정답을 대조할 때는 뜻이 같아도 표현이 다르면
(`"Mister Cho isn't that you?"` vs `"Aren't you Mr. Cho?"`) 글자 겹침이 낮게
나와 **가짜 불일치**로 보인다(실측: 예능A 15회 영어 번역, 2026-08-27).

그래서 `--against`에서만 쓰는 별도 유사도다. `align.similarity()`는 그대로
둔다 — 대본 대조 쪽 계산 값이 바뀌면 안 된다(다른 용도, 다른 보정값).

**밖으로 나가지 않는다.** 로컬 Ollama에 붙는다(번역과 같은 방식).
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

# 4개 후보(bge-m3·paraphrase-multilingual·nomic-embed-text-v2-moe·
# qwen3-embedding:0.6b)를 같은 참/거짓 짝 10개로 재서 골랐다(2026-08-27).
# 참 짝(같은 뜻, 표현만 다름)은 평균 유사도가 높아야 하고 거짓 짝(실제로 다른
# 내용인데 --against가 가짜로 짝지었던 사례들)은 낮아야 한다 — 그 차이
# (분리폭)가 클수록 이 용도(가짜 짝 거르기)에 맞는 모델이다.
#
#     모델                          참 평균  거짓 평균  분리폭
#     bge-m3                        0.927    0.546      0.381
#     paraphrase-multilingual       0.951    0.216      0.735   <- 골랐다
#     nomic-embed-text-v2-moe       0.777    0.244      0.533
#     qwen3-embedding:0.6b          0.837    0.421      0.415
#
# paraphrase-multilingual가 이름 그대로 의역·의미 클러스터링을 위해 만들어진
# 모델이라 우리 용도(뜻은 같은데 표현이 다른 자리를 찾는 것)에 가장 잘 맞았다.
DEFAULT_MODEL = "paraphrase-multilingual"


class EmbeddingUnavailable(RuntimeError):
    pass


class OllamaEmbedder:
    """`translate.OllamaTranslator`와 같은 방식으로 로컬 Ollama를 찾는다."""

    def __init__(self, model: str | None = None, host: str | None = None,
                 timeout: int = 120):
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.host = host or self._find_host()

    @classmethod
    def _find_host(cls) -> str:
        from .translate import OllamaTranslator
        for host in OllamaTranslator._candidates():
            try:
                with urllib.request.urlopen(f"{host}/api/tags", timeout=3):
                    return host
            except Exception:
                continue
        raise EmbeddingUnavailable(
            "Ollama를 찾지 못했습니다. 번역과 같은 서버를 씁니다 — "
            "winget install Ollama.Ollama 로 설치하세요.")

    # **한 번에 너무 많이 보내면 Ollama가 죽는다.** 실측(2026-08-27,
    # paraphrase-multilingual): 200개는 되는데 400개는 매번
    # "내부 토크나이저 프로세스에 못 붙음"(ECONNREFUSED, 매번 다른 포트) 오류로
    # 실패했다 — Ollama 쪽 배치 처리 한계로 보인다(우리 코드 문제가 아니다).
    # 넉넉히 여유를 두고 100개씩 나눠 보낸다.
    CHUNK_SIZE = 100

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """빈 문자열은 걸러서 보낸다(모델이 오류를 낸다) — 자리는 0벡터로 채운다."""
        indices = [i for i, t in enumerate(texts) if t.strip()]
        if not indices:
            return [[] for _ in texts]

        out: list[list[float]] = [[] for _ in texts]
        for start in range(0, len(indices), self.CHUNK_SIZE):
            chunk_indices = indices[start:start + self.CHUNK_SIZE]
            vectors = self._embed_request([texts[i] for i in chunk_indices])
            for i, vec in zip(chunk_indices, vectors):
                out[i] = vec
        return out

    def _embed_request(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                data = json.load(res)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            if "not found" in detail:
                raise EmbeddingUnavailable(
                    f"모델 {self.model}이(가) 없습니다. 받으세요: "
                    f"ollama pull {self.model}") from exc
            raise EmbeddingUnavailable(f"Ollama 오류: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EmbeddingUnavailable(f"Ollama에 닿지 못했습니다: {exc.reason}") from exc

        return data.get("embeddings") or []


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def build_similarity_fn(texts: list[str], embedder: OllamaEmbedder):
    """비교에 쓰일 모든 문장을 **한 번씩만** 임베딩하고, 이후엔 캐시로 답한다.

    짧은 자막("Yes.", "Hello.")은 자주 반복돼 캐시 효과가 크다. 배치 하나로
    묶어 보내는 이유는 호출 수를 줄이기 위해서다 — 자막 수백~수천 개를 한
    쌍씩 부르면 그만큼 느려진다.
    """
    unique = sorted(set(t for t in texts if t.strip()))
    vectors = embedder.embed_batch(unique)
    cache = dict(zip(unique, vectors))

    def fn(a: str, b: str) -> float:
        va, vb = cache.get(a), cache.get(b)
        if va is None or vb is None:
            return 0.0
        return cosine(va, vb)

    return fn
