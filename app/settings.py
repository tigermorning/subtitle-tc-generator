"""작업 기준 창 — 규정을 사람이 고칠 수 있게 연다.

**왜 필요한가**: 넷플릭스·디즈니·쿠팡 기준을 넣어 두는 것만으로는 부족하다.

    규정은 바뀐다            넷플릭스는 프레임 간격 규정을 2020년에 삭제했다
    발주처마다 다르다        같은 넷플릭스 일이라도 에이전시가 자기 기준을 얹는다
    다른 회사 일도 받는다    셋 말고 다른 곳의 기준을 쓸 수 있어야 한다

그래서 값을 코드에 박지 않고 프로파일(YAML)에 두었고, 이 창이 그것을 보여 주고
고치게 한다. **딸려 오는 프로파일은 건드리지 않는다** — 상속받은 새 프로파일을
사용자 폴더에 만든다. 공식 기준이 개정되면 상속본도 따라 바뀐다.

간편함이 기능을 줄이는 쪽으로 가면 안 된다. 그래서 **지금 적용 중인 값을 전부 보여
준다.** 무엇이 걸려 있는지 모르면 결과를 믿을 수 없다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from checker import load_profile
from checker.profile import available_profiles, user_root

# 사람이 자주 고치는 값들. (프로파일 경로, 이름, 최소, 최대)
NUMBERS = (
    (("limits", "chars_per_line"), "한 줄 글자 수", 1, 100),
    (("limits", "max_lines"), "최대 줄 수", 1, 4),
    (("limits", "duration_ms", "min"), "최소 표시 시간(ms)", 100, 5000),
    (("limits", "duration_ms", "max"), "최대 표시 시간(ms)", 1000, 20000),
    (("limits", "reading_speed_cps", "adult"), "읽기 속도(자/초)", 1, 40),
    (("limits", "reading_speed_cps", "children"), "읽기 속도 아동물", 1, 40),
    (("limits", "min_gap_frames"), "자막 사이 최소 프레임", 0, 20),
)

MARKERS = ("(작업 시작 전 선택)", "double_quote", "italic", "bracket", "none")
COLLISIONS = ("(작업 시작 전 선택)", "move_dialogue", "dialogue_only", "keep_both")
PLACES = ("top_center", "top_left", "top_right",
          "bottom_center", "bottom_left", "bottom_right")


def _dig(data: dict, path: tuple):
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


class SettingsDialog(QDialog):
    """지금 적용 중인 기준을 보여 주고, 발주처 기준으로 새로 저장한다."""

    def __init__(self, platform: str, kind: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("작업 기준")
        self.resize(760, 620)
        self.platform, self.kind = platform, kind
        self.profile = load_profile(platform, "ko", kind)
        self.saved_as: str | None = None

        layout = QVBoxLayout(self)
        source = self.profile.get("source") or {}
        official = "공식 문건" if source.get("official") else "실무 자료"
        layout.addWidget(QLabel(
            f"<b>{platform} / {kind}</b> — {source.get('section', '')} "
            f"({official}{', ' + source.get('revision', '') if source.get('revision') else ''})"))

        tabs = QTabWidget()
        tabs.addTab(self._numbers_tab(), "수치")
        tabs.addTab(self._job_tab(), "이 작업에서 정할 것")
        tabs.addTab(self._rules_tab(), f"검사 규칙 ({len(self.profile.get('rules') or [])})")
        tabs.addTab(self._shortcut_tab(), "단축키와 기능")
        tabs.addTab(self._raw_tab(), "적용 중인 값 전부")
        layout.addWidget(tabs, 1)

        naming = QHBoxLayout()
        naming.addWidget(QLabel("발주처 이름"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 우리에이전시 — 비워 두면 저장하지 않습니다")
        naming.addWidget(self.name_edit, 1)
        layout.addLayout(naming)
        layout.addWidget(QLabel(
            "<small>딸려 온 기준은 건드리지 않습니다. 바꾼 값만 담은 프로파일을 "
            f"<code>{user_root()}</code> 에 새로 만듭니다 — 공식 기준이 개정되면 "
            "상속본도 따라 바뀝니다.</small>"))

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- 탭 -----------------------------------------------------------
    def _numbers_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.number_boxes = {}
        for path, label, low, high in NUMBERS:
            value = _dig(self.profile, path)
            box = QSpinBox()
            box.setRange(low, high)
            box.setSpecialValueText("(없음)")
            box.setValue(int(value) if isinstance(value, (int, float)) else low)
            box.setEnabled(value is not None)
            self.number_boxes[path] = (box, value)
            form.addRow(label, box)
        return page

    def _job_tab(self) -> QWidget:
        """작업마다 달라지는 것들. 프로파일이 `ask`로 두면 여기서 정한다."""
        page = QWidget()
        form = QFormLayout(page)
        fn = (self.profile.get("forced_narrative") or {}).get("marker", "ask")
        collision = (self.profile.get("collision") or {})

        self.marker_box = QComboBox()
        self.marker_box.addItems(MARKERS)
        self.marker_box.setCurrentText(fn if fn in MARKERS else MARKERS[0])
        self.collision_box = QComboBox()
        self.collision_box.addItems(COLLISIONS)
        policy = collision.get("policy", "ask")
        self.collision_box.setCurrentText(policy if policy in COLLISIONS else COLLISIONS[0])
        self.move_box = QComboBox()
        self.move_box.addItems(PLACES)
        self.move_box.setCurrentText(collision.get("move_to", "top_center"))

        form.addRow("화면자막 표식", self.marker_box)
        form.addRow("말자막과 겹칠 때", self.collision_box)
        form.addRow("옮길 자리", self.move_box)
        form.addRow(QLabel(
            "<small>정하지 않으면 위치 검사·교정을 하지 않습니다. 어디로 옮길지 "
            "모르는 채로 옮기면 납품물이 틀어집니다.</small>"))
        return page

    def _rules_tab(self) -> QWidget:
        """규칙을 끄고 켠다. **발주처가 안 보는 규칙을 계속 띄우면 리포트가 노이즈가
        되고 진짜 지적이 묻힌다.**"""
        page = QWidget()
        layout = QVBoxLayout(page)
        rules = self.profile.get("rules") or []
        table = QTableWidget(len(rules), 3)
        table.setHorizontalHeaderLabels(["씀", "번호", "무엇을 보는가"])
        table.setColumnWidth(0, 40)
        table.setColumnWidth(1, 70)
        table.horizontalHeader().setStretchLastSection(True)

        self.rule_checks = {}
        for row, rule in enumerate(rules):
            check = QCheckBox()
            check.setChecked(True)
            holder = QWidget()
            box = QHBoxLayout(holder)
            box.addWidget(check)
            box.setAlignment(Qt.AlignCenter)
            box.setContentsMargins(0, 0, 0, 0)
            table.setCellWidget(row, 0, holder)
            table.setItem(row, 1, QTableWidgetItem(rule["id"]))
            table.setItem(row, 2, QTableWidgetItem(
                f"{rule.get('clause', '')} — {rule.get('message', '')}"))
            self.rule_checks[rule["id"]] = check
        layout.addWidget(table)
        return page

    def _shortcut_tab(self) -> QWidget:
        """**무엇을 할 수 있는지 설명하고, 키는 사람이 정한다.**

        기본값은 작업자가 SE에서 쓰던 자리지만, 손이 기억하는 자리는 사람마다 다르다.
        설명 칸을 넓게 둔 이유는 사용자 지적 그대로다 — 어떤 기능이 있는지 알아야
        프로그램을 쓴다.
        """
        from . import shortcuts

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(
            "키 칸을 눌러 원하는 조합을 누르면 바뀝니다. 겹치면 저장할 때 알려 줍니다."))

        keys = shortcuts.load()
        table = QTableWidget(len(shortcuts.ACTIONS), 4)
        table.setHorizontalHeaderLabels(["묶음", "기능", "단축키", "무엇을 하는가"])
        table.setColumnWidth(0, 60)
        table.setColumnWidth(1, 150)
        table.setColumnWidth(2, 150)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setDefaultSectionSize(46)
        table.setWordWrap(True)

        self.key_editors = {}
        for row, action in enumerate(shortcuts.ACTIONS):
            table.setItem(row, 0, QTableWidgetItem(action.group))
            table.setItem(row, 1, QTableWidgetItem(action.title))
            editor = QKeySequenceEdit(keys.get(action.key, action.default))
            table.setCellWidget(row, 2, editor)
            self.key_editors[action.key] = editor
            table.setItem(row, 3, QTableWidgetItem(action.what))
        layout.addWidget(table, 1)

        reset = QPushButton("기본값으로 되돌리기")
        reset.clicked.connect(self._reset_shortcuts)
        layout.addWidget(reset)
        return page

    def _reset_shortcuts(self) -> None:
        from . import shortcuts
        from PySide6.QtGui import QKeySequence

        for action in shortcuts.ACTIONS:
            self.key_editors[action.key].setKeySequence(QKeySequence(action.default))

    def _save_shortcuts(self) -> bool:
        """바꾼 키를 저장한다. 겹치면 **말없이 덮어쓰지 않고** 물어본다."""
        from . import shortcuts

        keys = {name: editor.keySequence().toString()
                for name, editor in self.key_editors.items()}
        clashes = shortcuts.conflicts(keys)
        if clashes:
            lines = "\n".join(f"  {key}: {first} / {second}" for key, first, second in clashes)
            answer = QMessageBox.question(
                self, "단축키가 겹칩니다",
                f"같은 키를 두 기능이 쓰고 있습니다.\n\n{lines}\n\n"
                "겹친 키는 둘 중 하나만 듣습니다. 그래도 저장할까요?")
            if answer != QMessageBox.Yes:
                return False
        shortcuts.save(keys)
        return True

    def _raw_tab(self) -> QWidget:
        """상속까지 끝난 **최종 값**을 보여 준다. 무엇이 걸려 있는지 숨기지 않는다."""
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["항목", "값"])
        table.setColumnWidth(0, 260)
        table.horizontalHeader().setStretchLastSection(True)

        rows = []

        def walk(data, prefix=""):
            for key, value in (data or {}).items():
                if key == "rules":
                    continue
                name = f"{prefix}{key}"
                if isinstance(value, dict):
                    walk(value, f"{name}.")
                else:
                    rows.append((name, str(value)))

        walk(self.profile)
        table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(value))
        layout.addWidget(table)
        return page

    # --- 저장 ---------------------------------------------------------
    def _save(self) -> None:
        # 단축키는 발주처 기준과 무관하다. 이름이 없어도 저장한다.
        if not self._save_shortcuts():
            return

        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.information(
                self, "단축키를 저장했습니다",
                "발주처 기준까지 만들려면 이름을 적어 주세요.")
            self.accept()
            return

        overrides: dict = {}
        for path, (box, original) in self.number_boxes.items():
            if not box.isEnabled():
                continue
            if int(box.value()) != (int(original) if isinstance(original, (int, float)) else None):
                target = overrides
                for key in path[:-1]:
                    target = target.setdefault(key, {})
                target[path[-1]] = int(box.value())

        job: dict = {}
        if not self.marker_box.currentText().startswith("("):
            job.setdefault("forced_narrative", {})["marker"] = self.marker_box.currentText()
        if not self.collision_box.currentText().startswith("("):
            job.setdefault("collision", {})["policy"] = self.collision_box.currentText()
            job["collision"]["move_to"] = self.move_box.currentText()

        disabled = [rule_id for rule_id, check in self.rule_checks.items()
                    if not check.isChecked()]

        folder = user_root() / name
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"ko-{self.kind}.yaml"
        path.write_text(self._to_yaml(name, overrides, job, disabled), encoding="utf-8")
        self.saved_as = name
        QMessageBox.information(
            self, "저장했습니다",
            f"{path}\n\n작업 기준 목록에서 '{name}'을 고르면 이 기준으로 검사합니다.")
        self.accept()

    def _to_yaml(self, name: str, overrides: dict, job: dict, disabled: list[str]) -> str:
        """상속본을 쓴다. **바뀐 값만 적는다** — 통째로 베끼면 공식 기준이 개정돼도
        따라가지 못한다."""
        import yaml

        data = {
            "schema_version": 1,
            "platform": name,
            "language": "ko",
            "kind": self.kind,
            "status": "complete",
            # **저장소 기준 경로로 적는다.** `../netflix/...`처럼 상대 경로로 적으면
            # 사용자 폴더 기준으로 풀려서 못 찾는다(실측). 규정 폴더 기준이면
            # 어디에 저장하든 같은 자리를 가리킨다.
            "extends": f"{self.platform}/ko-{self.kind}.yaml",
            "source": {
                "official": False,
                "client": name,
                "section": f"{self.platform} {self.kind} 기준에 발주처 요구를 얹음",
            },
        }
        data.update(overrides)
        data.update(job)
        if disabled:
            data["disable_rules"] = disabled

        header = (f"# {name} 작업 기준\n"
                  f"#\n"
                  f"# {self.platform}/ko-{self.kind}를 상속하고 **다른 값만** 적었다.\n"
                  f"# 공식 기준이 개정되면 이 파일도 따라 바뀐다.\n"
                  f"# 자막 편집기의 '작업 기준' 창에서 만들었다.\n\n")
        return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
