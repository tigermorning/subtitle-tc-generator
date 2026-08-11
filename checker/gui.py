"""창 하나짜리 실행기.

명령줄을 모르는 사람이 쓸 수 있어야 제품이다. 아이콘을 여러 개 늘어놓는 대신
**프로파일을 창에서 고르게** 한다 — SDH와 번역이 갈리는 자리가 눈에 보여야 한다.

    python -m checker.gui

tkinter는 파이썬에 딸려 오므로 의존성이 늘지 않는다.
"""

from __future__ import annotations

import queue
import threading
import subprocess
import sys
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cli import _format_text
from .profile import ProfileError, available_profiles, load_profile_file
from .runner import Options, run_files

CORRECTOR_DIRNAME = "korean-subtitle-corrector"


def _guess_corrector_path() -> str:
    """옆 폴더에 교정기가 있으면 잡는다. 사용자가 경로를 치지 않아도 되게."""
    here = Path(__file__).resolve().parent.parent
    candidate = here.parent / CORRECTOR_DIRNAME
    return str(candidate) if (candidate / "subtitle_corrector").is_dir() else ""


def _open_in_explorer(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["explorer", str(path)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        pass


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.targets: list[Path] = []
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_report_path: Path | None = None
        self.running = False

        root.title("자막 규정 검사기")
        root.geometry("880x620")

        outer = ttk.Frame(root, padding=10)
        outer.pack(fill="both", expand=True)

        # --- 1단계: 파일 -----------------------------------------------------
        files_box = ttk.LabelFrame(outer, text="1. 검사할 자막", padding=8)
        files_box.pack(fill="x")
        btns = ttk.Frame(files_box)
        btns.pack(fill="x")
        ttk.Button(btns, text="파일 선택...", command=self.pick_files).pack(side="left")
        ttk.Button(btns, text="폴더 선택...", command=self.pick_folder).pack(side="left", padx=6)
        ttk.Button(btns, text="비우기", command=self.clear_files).pack(side="left")
        self.files_label = ttk.Label(files_box, text="선택된 파일 없음", foreground="#666")
        self.files_label.pack(anchor="w", pady=(6, 0))

        # --- 2단계: 기준 -----------------------------------------------------
        profile_box = ttk.LabelFrame(outer, text="2. 검사 기준 (작업 전에 반드시 맞춘다)", padding=8)
        profile_box.pack(fill="x", pady=8)

        self.profiles = available_profiles()
        self.profile_labels = [
            f"{p['platform']} · {p['language']} · {p['kind']}"
            f"{'  [템플릿]' if p['name'].endswith('template') else ''}"
            f"   ({p['revision']} 개정)"
            for p in self.profiles
        ]
        self.custom_label = "발주처 프로파일 파일 선택..."
        self.profile_combo = ttk.Combobox(
            profile_box, values=self.profile_labels + [self.custom_label],
            state="readonly", width=70,
        )
        default = next((i for i, p in enumerate(self.profiles)
                        if p["language"] == "ko" and p["kind"] == "translation"), 0)
        self.profile_combo.current(default)
        self.profile_combo.pack(anchor="w")
        self.profile_combo.bind("<<ComboboxSelected>>", self.on_profile_change)
        self.custom_profile: Path | None = None
        self.profile_note = ttk.Label(profile_box, text="", foreground="#666")
        self.profile_note.pack(anchor="w", pady=(4, 0))
        self.on_profile_change()

        # --- 3단계: 방식 -----------------------------------------------------
        opts_box = ttk.LabelFrame(outer, text="3. 방식", padding=8)
        opts_box.pack(fill="x")
        self.var_fix = tk.BooleanVar(value=False)
        self.var_korean = tk.BooleanVar(value=True)
        self.var_children = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts_box, text="자동 교정본 만들기 (원본은 그대로, .fixed.srt 로 나감)",
                        variable=self.var_fix).pack(anchor="w")
        ttk.Checkbutton(opts_box, text="한국어 맞춤법·띄어쓰기 함께 검사 (적재에 1~2분)",
                        variable=self.var_korean).pack(anchor="w")
        ttk.Checkbutton(opts_box, text="아동 프로그램 기준 (읽기 속도가 더 느리다)",
                        variable=self.var_children).pack(anchor="w")

        ksc = ttk.Frame(opts_box)
        ksc.pack(fill="x", pady=(6, 0))
        ttk.Label(ksc, text="교정기 위치").pack(side="left")
        self.ksc_var = tk.StringVar(value=_guess_corrector_path())
        ttk.Entry(ksc, textvariable=self.ksc_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(ksc, text="찾기...", command=self.pick_ksc).pack(side="left")

        # --- 실행 ------------------------------------------------------------
        run_row = ttk.Frame(outer)
        run_row.pack(fill="x", pady=8)
        self.run_button = ttk.Button(run_row, text="검사 시작", command=self.start)
        self.run_button.pack(side="left")
        self.open_report_button = ttk.Button(run_row, text="리포트 열기",
                                             command=self.open_report, state="disabled")
        self.open_report_button.pack(side="left", padx=6)
        self.status = ttk.Label(run_row, text="", foreground="#666")
        self.status.pack(side="left", padx=10)

        self.log = tk.Text(outer, wrap="none", height=20)
        self.log.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.log.yview)
        scroll.place(relx=1.0, rely=0.62, relheight=0.36, anchor="ne")
        self.log.configure(yscrollcommand=scroll.set)

        self.root.after(100, self.drain)

    # --- 입력 ---------------------------------------------------------------

    def pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="자막 파일 선택",
            filetypes=[("자막 파일", "*.srt *.vtt"), ("모든 파일", "*.*")])
        if paths:
            self.targets.extend(Path(p) for p in paths)
            self.refresh_files()

    def pick_folder(self) -> None:
        path = filedialog.askdirectory(title="자막 폴더 선택")
        if path:
            self.targets.append(Path(path))
            self.refresh_files()

    def clear_files(self) -> None:
        self.targets.clear()
        self.refresh_files()

    def pick_ksc(self) -> None:
        path = filedialog.askdirectory(title="한국어 교정기 폴더 선택")
        if path:
            self.ksc_var.set(path)

    def refresh_files(self) -> None:
        if not self.targets:
            self.files_label.config(text="선택된 파일 없음")
            return
        names = ", ".join(p.name for p in self.targets[:3])
        more = f" 외 {len(self.targets) - 3}개" if len(self.targets) > 3 else ""
        self.files_label.config(text=f"{names}{more}")

    def on_profile_change(self, _event=None) -> None:
        if self.profile_combo.get() == self.custom_label:
            path = filedialog.askopenfilename(
                title="발주처 프로파일 선택", filetypes=[("프로파일", "*.yaml"), ("모든 파일", "*.*")])
            if path:
                self.custom_profile = Path(path)
                self.profile_note.config(text=f"발주처 프로파일: {self.custom_profile.name}")
            else:
                self.profile_combo.current(0)
                self.custom_profile = None
                self.on_profile_change()
            return
        self.custom_profile = None
        prof = self.profiles[self.profile_combo.current()]
        self.profile_note.config(text=f"기준: {prof['section']}")

    # --- 실행 ---------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        if not self.targets:
            messagebox.showinfo("자막을 고르세요", "검사할 자막 파일이나 폴더를 먼저 고르세요.")
            return
        try:
            profile = (load_profile_file(self.custom_profile) if self.custom_profile
                       else load_profile_file(self.profiles[self.profile_combo.current()]["path"]))
        except ProfileError as e:
            messagebox.showerror("프로파일 오류", str(e))
            return

        options = Options(
            children=self.var_children.get(),
            fix=self.var_fix.get(),
            korean=self.var_korean.get(),
            ksc_path=self.ksc_var.get() or None,
        )

        self.running = True
        self.run_button.config(state="disabled")
        self.open_report_button.config(state="disabled")
        self.status.config(text="검사 중...")
        self.log.delete("1.0", "end")

        targets = list(self.targets)
        threading.Thread(target=self._work, args=(targets, profile, options), daemon=True).start()

    def _work(self, targets, profile, options) -> None:
        try:
            result = run_files(targets, profile, options,
                               progress=lambda m: self.messages.put(("log", m)))
            blocks = [_format_text(r, Path(r["file"])) for r in result.reports]
            if len(result.reports) > 1:
                total = sum(len(r["violations"]) for r in result.reports)
                clean = sum(1 for r in result.reports if not r["violations"])
                blocks.append(f"합계: 파일 {len(result.reports)}개, 위반 {total}건, "
                              f"위반 없는 파일 {clean}개")
            for note in result.notes:
                self.messages.put(("log", note))
            self.messages.put(("log", "\n" + "\n\n".join(blocks)))
            self.messages.put(("done", result))
        except Exception as e:  # 창이 조용히 죽지 않게 한다
            self.messages.put(("log", f"오류가 났습니다: {e}"))
            self.messages.put(("done", None))

    def drain(self) -> None:
        while True:
            try:
                kind, payload = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log.insert("end", str(payload) + "\n")
                self.log.see("end")
            elif kind == "done":
                self.finish(payload)
        self.root.after(100, self.drain)

    def finish(self, result) -> None:
        self.running = False
        self.run_button.config(state="normal")
        if result is None or not result.reports:
            self.status.config(text="끝났습니다(결과 없음)")
            return

        total = sum(len(r["violations"]) for r in result.reports)
        self.status.config(text=f"끝났습니다 — 위반 {total}건")

        first = Path(result.reports[0]["file"])
        report_path = first.parent / "checker-report.txt"
        try:
            report_path.write_text(self.log.get("1.0", "end"), encoding="utf-8")
            self.last_report_path = report_path
            self.open_report_button.config(state="normal")
        except OSError:
            self.last_report_path = None

    def open_report(self) -> None:
        if self.last_report_path and self.last_report_path.exists():
            _open_in_explorer(self.last_report_path)


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
