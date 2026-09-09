"""PRD_MQ4.md "실험 & 평가" — 실제 코퍼스로 에이전트를 끝까지 돌려 지표를 남긴다.

agent/api.py 서버가 떠 있어야 한다(로컬, 8765). 확인 카드는 전부 "승인"으로
자동 응답한다 — 실제 QC 판단이 아니라 파이프라인이 끝까지 도는지, 회차·
비용·시간이 얼마나 드는지 재는 것이 목적이다(사람 판단력 자체를 측정하는
게 아니다).

**정답지 역대조** — 사용자 지적(2026-09-09): "TC가 더 중요하다." 이 평가셋의
입력 자체가 이미 정답지(실제 납품된 최종 자막)이므로, 에이전트가 고친 결과를
같은 정답지와 다시 대조하면 "자동교정이 실제로 정답을 깼는지"를 값으로 잴 수
있다. 새 비교 로직을 만들지 않고 `checker/evaluate.py::compare/summarize`
(원래 `--against`가 쓰는 것)를 그대로 부른다 — API 호출 없이 로컬 계산만이라
비용이 안 든다.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx

from checker.evaluate import compare, summarize
from checker.parsers import parse as parse_srt

BASE = "http://127.0.0.1:8765"

CASES = [
    ("netflix_sdh_ko_ready-or-not-e01",
     "학습한 TC 및 자막 모음/넷플릭스_드라마A/E01_한국어_SDH.srt", "netflix", "sdh", "ko"),
    ("netflix_translation_en_ready-or-not-e01",
     "학습한 TC 및 자막 모음/넷플릭스_드라마A/E01_영어_번역.srt", "netflix", "translation", "en"),
    ("netflix_sdh_ko_take-a-hike-e01",
     "학습한 TC 및 자막 모음/넷플릭스_예능B/E01_한국어_SDH.srt", "netflix", "sdh", "ko"),
    ("disney_translation_ko_hitler-e01",
     "학습한 TC 및 자막 모음/디즈니플러스_다큐A 심판의 날/E01_한국어_번역.srt", "disney", "translation", "ko"),
    ("coupang_sdh_ko_affair-e05",
     "학습한 TC 및 자막 모음/쿠팡플레이_드라마E/E05_한국어_SDH.srt", "coupang", "sdh", "ko"),
    ("coupang_translation_en_affair-e05",
     "학습한 TC 및 자막 모음/쿠팡플레이_드라마E/E05_영어_번역.srt", "coupang", "translation", "en"),
]


async def drive(client: httpx.AsyncClient, file_id: str, max_steps: int = 10) -> dict:
    state: dict = {}
    for _ in range(max_steps):
        r = await client.get(f"{BASE}/api/sessions/{file_id}")
        state = r.json()
        status = state["status"]
        if status in ("done", "error"):
            return state
        if state.get("needs_fix_approval"):
            await client.post(f"{BASE}/api/sessions/{file_id}/approve-fix")
            continue
        if status == "waiting_for_user" and state.get("pending_question"):
            pq = state["pending_question"]
            answers = [{"rule_id": c["rule_id"], "cue_index": c["cue_index"], "decision": "승인"} for c in pq["cards"]]
            await client.post(
                f"{BASE}/api/sessions/{file_id}/answer",
                json={"question_id": pq["question_id"], "version": pq["version"], "answers": answers},
            )
            continue
        await asyncio.sleep(1)
    return state


async def main() -> None:
    results = []
    async with httpx.AsyncClient(timeout=120) as client:
        for label, path, platform, kind, language in CASES:
            t0 = time.time()
            with open(path, "rb") as f:
                r = await client.post(
                    f"{BASE}/api/sessions",
                    files={"file": (path, f, "text/plain")},
                    data={"platform": platform, "kind": kind, "language": language},
                )
            if r.status_code != 201:
                results.append({"label": label, "status": "create_failed", "detail": r.text})
                print(results[-1])
                continue
            file_id = r.json()["file_id"]
            initial = (await client.get(f"{BASE}/api/sessions/{file_id}")).json()
            initial_violations = len(initial["violations"])
            final = await drive(client, file_id)
            wall_s = time.time() - t0
            disposition = final.get("dispositioned", {})
            se_count = sum(1 for v in disposition.values() if v == "SE로 이관")
            web_count = len(disposition) - se_count
            row = {
                "label": label, "platform": platform, "kind": kind, "language": language,
                "status": final.get("status"),
                "initial_violations": initial_violations,
                "auto_fixed": final.get("auto_fixed_count", 0),
                "web_cards": web_count,
                "se_bookmarks": se_count,
                "remaining": len(final.get("violations", [])),
                "outer_turns": final.get("outer_turns", 0),
                "cost_usd": round(final.get("total_cost_usd", 0), 4),
                "duration_ms": final.get("total_duration_ms", 0),
                "wall_s": round(wall_s, 1),
                "error": final.get("error"),
            }
            if final.get("status") == "done":
                # 입력 자체가 정답지다 — 에이전트 최종 출력과 다시 대조한다.
                truth_events = parse_srt(Path(path))
                ours_events = parse_srt(Path(final["current_path"]))
                summary = summarize(compare(ours_events, truth_events))
                row["against_truth"] = {
                    "start_ms_median": summary["start_ms"]["median"],
                    "start_ms_worst": summary["start_ms"]["worst"],
                    "end_ms_median": summary["end_ms"]["median"],
                    "end_ms_worst": summary["end_ms"]["worst"],
                    "missing": summary["counts"]["missing"],
                    "extra": summary["counts"]["extra"],
                    "text_similarity_median": summary["text_similarity_median"],
                }
            results.append(row)
            print(row)
    with open("agent/_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
