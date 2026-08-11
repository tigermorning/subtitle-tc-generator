"""영상 재생 — libmpv를 감싼다.

**프레임 단위로 움직여야 한다.** 자막 작업에서 1프레임은 42ms이고, 인점이 한
프레임 어긋나면 검수에서 돌아온다. HTML5 비디오나 일반 재생기 API로는 그 정확도가
안 나온다. mpv는 `frame-step`·`frame-back-step`을 직접 준다.

mpv를 고른 다른 이유: **ffmpeg이 여는 것은 다 연다.** 실무 파일이 avi·mov·mkv로
섞여 온다(연습 과제만 봐도 셋 다 있다).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlayerUnavailable(Exception):
    reason: str

    def __str__(self) -> str:
        return self.reason


class Player:
    """mpv 창을 특정 위젯 안에 띄운다."""

    def __init__(self, window_id: int):
        try:
            import mpv
        except OSError as exc:                   # libmpv를 못 찾음
            raise PlayerUnavailable(str(exc)) from exc

        # `keep-open`은 끝에서 멈춰 서게 한다. 자막 작업은 마지막 프레임을 봐야 한다.
        self._mpv = mpv.MPV(
            wid=str(window_id),
            keep_open="yes",
            osc=False,               # 우리 화면에 우리 조작부를 둔다
            input_default_bindings=False,
            input_vo_keyboard=False,
            hr_seek="yes",           # 정확한 탐색. 이게 없으면 키프레임으로 튄다
            hr_seek_framedrop=False,
        )

        # **자막을 영상 화면 안에 그린다.** mpv는 기본으로 위아래 검은 여백까지
        # 자막 자리로 쓴다(`sub-use-margins=yes`). 그러면 편집기에서 본 위치와 실제
        # 화면에서 보이는 위치가 달라져 작업자가 위치를 판단할 수 없다.
        #
        # 자막 크기는 **영상 크기 기준**으로 잡는다. 창을 키우고 줄여도 화면 대비
        # 비율이 그대로라, 지금 보는 모양이 최종 화면에서 보이는 모양이다.
        #
        # **빌드마다 있는 옵션이 다르다.** `sub-ass-use-margins`는 이 libmpv에 없다.
        # 없는 옵션 하나 때문에 재생기가 통째로 안 열리면 안 된다.
        for name, value in (("sub-use-margins", "no"),
                            ("sub-ass-use-margins", "no"),
                            ("sub-scale-by-window", "no")):
            self._set_optional(name, value)

        self._duration_ms = 0

    def _set_optional(self, name: str, value: str) -> None:
        """있으면 넣고 없으면 넘어간다. 빌드마다 가진 옵션이 다르다."""
        try:
            self._mpv[name] = value
        except Exception:
            pass

    # --- 파일 ---------------------------------------------------------
    def open(self, path: str) -> None:
        self._mpv.play(path)
        self._mpv.wait_until_playing()
        self._mpv.pause = True

    @property
    def duration_ms(self) -> int:
        value = self._mpv.duration
        return int(value * 1000) if value else 0

    @property
    def fps(self) -> float:
        return float(self._mpv.container_fps or 0.0)

    # --- 재생 ---------------------------------------------------------
    @property
    def position_ms(self) -> int:
        value = self._mpv.time_pos
        return int(value * 1000) if value else 0

    def seek(self, ms: int) -> None:
        """정확한 자리로 간다. 키프레임으로 반올림하지 않는다."""
        self._mpv.command("seek", max(0, ms) / 1000, "absolute", "exact")

    def toggle_pause(self) -> bool:
        self._mpv.pause = not self._mpv.pause
        return bool(self._mpv.pause)

    @property
    def paused(self) -> bool:
        return bool(self._mpv.pause)

    def step(self, frames: int = 1) -> None:
        """프레임 단위 이동. 자막 작업에서 가장 많이 쓰는 조작이다."""
        command = "frame-step" if frames > 0 else "frame-back-step"
        for _ in range(abs(frames)):
            self._mpv.command(command)

    # --- 자막 ---------------------------------------------------------
    def set_subtitles(self, path: str) -> None:
        """자막 파일을 영상에 얹는다. 이미 얹혀 있으면 갈아 끼운다.

        **왜 파일로 넘기는가**: mpv의 자막 그리기를 그대로 쓰면 최종 결과와 같은
        모양으로 보인다 — 줄바꿈, 위치 태그(`{\\an8}`), 글자 크기까지. 우리가
        직접 글자를 그리면 "편집기에서는 이렇게 보였는데" 하는 차이가 생긴다.
        """
        # **자막이 하나도 없을 때 `sub-remove`는 예외를 던진다**(실측: SystemError).
        # 그대로 두면 뒤의 `sub-add`까지 못 가서 자막이 조용히 안 뜬다.
        try:
            self._mpv.command("sub-remove")
        except Exception:
            pass
        self._mpv.command("sub-add", path, "select")

    def reload_subtitles(self) -> None:
        """같은 파일을 다시 읽는다. 편집한 내용을 곧바로 보여 줄 때 쓴다."""
        try:
            self._mpv.command("sub-reload")
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass
