"""자막 QC 독립 MCP 서버 — MQ4 확장 시도("MCP 서버를 직접 만들어 내 도메인의
시스템을 에이전트의 도구로 노출해보면 어떨까요?").

`agent/loop.py`는 이 checker 래퍼(`agent/tools.py`)를 SDK 안 in-process
서버로만 노출했다 — 우리 웹앱을 통해서만 쓸 수 있었다. 이 파일은 같은
`agent/tools.py`를 **표준 stdio MCP**로 노출한다. Claude Desktop·Claude
Code·다른 에이전트가 설정 파일에 이 서버 하나만 등록하면, 자기 세션에서
바로 "이 srt 검사해줘"를 도구로 쓸 수 있다 — 우리 웹앱 전용 기능이 아니게
된다.

핵심 설계 원칙은 그대로다 — **대사 원문은 어느 MCP 클라이언트가 붙어도
안 돌려준다.** 규칙ID·조항·건수·큐번호만 나간다(PRD_MQ4.md).

실행(직접):
    python -m agent.mcp_server

Claude Code에 등록(예시, .mcp.json 또는 `claude mcp add`):
    {"mcpServers": {"subtitle-qc": {"command": "python",
                                     "args": ["-m", "agent.mcp_server"],
                                     "cwd": "<이 저장소 경로>"}}}
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

from agent import tools as checker_tools

mcp = MCPServer(
    "subtitle-qc",
    version="1.0.0",
    instructions=(
        "넷플릭스·디즈니+·쿠팡플레이 자막(srt)의 발주처 규정 위반을 검사·자동교정한다. "
        "대사 원문은 절대 안 돌려준다 — 규칙ID·조항·건수·큐번호만 다룬다. "
        "자동교정(fix_subtitle)은 새 파일로만 쓰고 원본은 안 건드린다."
    ),
)

Platform = Literal["netflix", "disney", "coupang"]
Kind = Literal["sdh", "translation"]


def _violation_to_dict(v) -> dict:
    return {"rule_id": v.rule_id, "article": v.article, "count": v.count,
            "severity": v.severity, "locations": v.locations}


@mcp.tool()
def check_subtitle(file_path: str, platform: Platform, kind: Kind, language: str) -> dict:
    """srt 파일의 발주처 규정 위반을 검사한다. 대사 원문은 안 돌려주고
    규칙ID·조항·건수·큐번호(자동/확인 구분 포함)만 돌려준다."""
    try:
        violations = checker_tools.check(Path(file_path), platform, kind, language)
    except checker_tools.CheckerToolError as e:
        return {"error": str(e)}
    return {"violations": [_violation_to_dict(v) for v in violations], "passed": not violations}


@mcp.tool()
def fix_subtitle(file_path: str, output_path: str, platform: Platform, kind: Kind, language: str) -> dict:
    """자동교정 가능(auto)한 위반을 실제로 적용해 output_path에 새 파일을 쓴다.
    file_path(원본)는 절대 안 건드린다. 위험한 도구다 — 호출 전 사람 승인을
    거치는 건 이 도구를 부르는 쪽(클라이언트) 책임이다, 여기서는 강제하지 않는다."""
    try:
        result = checker_tools.fix(Path(file_path), Path(output_path), platform, kind, language)
    except checker_tools.CheckerToolError as e:
        return {"error": str(e)}
    return {
        "output_path": result["output_path"],
        "applied": result["applied"],
        "still_violating": [_violation_to_dict(v) for v in result["still_violating"]],
    }


@mcp.tool()
def export_se_bookmarks(file_path: str, items: list[dict]) -> dict:
    """영상·TC 확인이 필요한 위반을 SubtitleEdit(SE 4.x) 북마크로 내보낸다.
    items는 [{"cue_index": int, "note": str}, ...] 형태다. SE에서 file_path를
    열면 이 큐들에 북마크가 뜬다."""
    pairs = [(item["cue_index"], item["note"]) for item in items]
    out_path = checker_tools.export_bookmarks(Path(file_path), pairs)
    return {"bookmarks_path": str(out_path)}


if __name__ == "__main__":
    mcp.run()  # 기본 stdio
