"""Small desktop front end for :mod:`serum2vital` on macOS and Windows.

The GUI deliberately runs the existing command line interface in a child
process.  That keeps one conversion path, makes cancellation reliable, and
lets the desktop app show the CLI's per-preset progress without changing the
converter itself.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


LAYOUT_PRESERVE = "preserve"
LAYOUT_ORGANIZE = "organize"
LAYOUT_FLATTEN = "flatten"
LAYOUTS = {LAYOUT_PRESERVE, LAYOUT_ORGANIZE, LAYOUT_FLATTEN}
BRAND_LIGHT = ("#006b7a", "#6f42c1")
BRAND_DARK = ("#67e8f9", "#c4b5fd")


def worker_python_executable(
    executable: str | os.PathLike[str] | None = None,
    *,
    platform: str | None = None,
) -> str:
    """Return a Python executable whose stdout/stderr can be captured.

    Windows GUI entry points run under ``pythonw.exe``.  A conversion started
    with that executable has no standard streams, so use ``python.exe`` from
    the same environment for the QProcess worker when it is available.
    """
    selected = os.fspath(executable) if executable is not None else sys.executable
    current_platform = platform if platform is not None else sys.platform
    path = Path(selected)
    if current_platform.startswith("win") and path.name.lower() == "pythonw.exe":
        console_python = path.with_name("python.exe")
        if console_python.is_file():
            return str(console_python)
    return selected


def build_cli_arguments(
    inputs: Sequence[str | os.PathLike[str]],
    output: str | os.PathLike[str],
    *,
    serum_root: str | os.PathLike[str] | None = None,
    layout: str = LAYOUT_PRESERVE,
    include_wavetables: bool = True,
    include_samples: bool = True,
    overwrite: bool = False,
    max_frames: int = 64,
) -> list[str]:
    """Build arguments for ``sys.executable`` from the desktop form values.

    ``-u`` is intentional: the GUI consumes the verbose output as progress,
    and a child Python process connected to a pipe would otherwise buffer it.
    Keeping this function free of Qt imports also makes the command mapping
    testable when the optional GUI dependency is not installed.
    """
    input_strings = [os.fspath(path) for path in inputs]
    output_string = os.fspath(output)
    if not input_strings or any(not path for path in input_strings):
        raise ValueError("at least one input path is required")
    if not output_string:
        raise ValueError("an output path is required")
    if layout not in LAYOUTS:
        raise ValueError(f"unknown layout: {layout}")
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")

    arguments = [
        "-u",
        "-m",
        "serum2vital",
        *input_strings,
        "--out",
        output_string,
        "--max-frames",
        str(max_frames),
    ]
    if serum_root:
        arguments.extend(("--serum-root", os.fspath(serum_root)))
    if layout == LAYOUT_ORGANIZE:
        arguments.append("--organize")
    elif layout == LAYOUT_FLATTEN:
        arguments.append("--flatten")
    if not include_wavetables:
        arguments.append("--no-wavetables")
    if not include_samples:
        arguments.append("--no-samples")
    if overwrite:
        arguments.append("--overwrite")
    arguments.append("-v")
    return arguments


_PROGRESS_RE = re.compile(r"^\[(\d+)/(\d+)\]\s+(ok|skipped|failed)\s+(.*)$")
_SUMMARY_RE = re.compile(
    r"^(\d+) converted, (\d+) skipped, (\d+) failed \(of (\d+)\)$"
)


@dataclass(frozen=True)
class ProgressLine:
    current: int
    total: int
    status: str
    detail: str


def parse_progress_line(line: str) -> ProgressLine | None:
    """Parse one verbose CLI progress line, returning ``None`` otherwise."""
    match = _PROGRESS_RE.match(line.strip())
    if match is None:
        return None
    return ProgressLine(
        current=int(match.group(1)),
        total=int(match.group(2)),
        status=match.group(3),
        detail=match.group(4),
    )


def _load_gui_classes():
    """Import the optional Qt dependency and construct the two widget classes."""
    from PySide6.QtCore import QEvent, QProcess, QTimer, Qt, QUrl, Signal
    from PySide6.QtGui import (
        QCloseEvent,
        QDesktopServices,
        QDragEnterEvent,
        QDropEvent,
        QPalette,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )

    class SourceListWidget(QListWidget):
        paths_dropped = Signal(list)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setAcceptDrops(True)
            self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
            self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            self.setAlternatingRowColors(True)

        @staticmethod
        def _paths(event: QDragEnterEvent | QDropEvent) -> list[str]:
            if not event.mimeData().hasUrls():
                return []
            return [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]

        @staticmethod
        def _is_supported(path_string: str) -> bool:
            path = Path(path_string)
            return path.is_dir() or (path.is_file() and path.suffix.lower() in {".fxp", ".serumpreset"})

        def dragEnterEvent(self, event: QDragEnterEvent) -> None:
            if any(self._is_supported(path) for path in self._paths(event)):
                event.acceptProposedAction()
            else:
                event.ignore()

        def dragMoveEvent(self, event) -> None:
            if any(self._is_supported(path) for path in self._paths(event)):
                event.acceptProposedAction()
            else:
                event.ignore()

        def dropEvent(self, event: QDropEvent) -> None:
            paths = [path for path in self._paths(event) if self._is_supported(path)]
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
            else:
                event.ignore()

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self._process = QProcess(self)
            self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self._process.readyReadStandardOutput.connect(self._read_process_output)
            self._process.finished.connect(self._process_finished)
            self._process.errorOccurred.connect(self._process_error)
            self._kill_timer = QTimer(self)
            self._kill_timer.setSingleShot(True)
            self._kill_timer.timeout.connect(self._kill_if_running)
            self._line_buffer = ""
            self._cancel_requested = False
            self._failed_count = 0
            self._source_keys: set[str] = set()

            self.setWindowTitle("serum2vital")
            self.resize(820, 760)
            self.setMinimumSize(680, 650)
            self._build_ui()
            self._update_actions()

        def _build_ui(self) -> None:
            central = QWidget(self)
            outer = QVBoxLayout(central)
            outer.setContentsMargins(24, 20, 24, 20)
            outer.setSpacing(12)

            self.brand = QLabel()
            self._refresh_brand_colors()
            tagline = QLabel("Serum 1 / 2 のプリセットを Vital へ変換")
            heading = QVBoxLayout()
            heading.setSpacing(1)
            heading.addWidget(self.brand)
            heading.addWidget(tagline)
            outer.addLayout(heading)

            source_box = QGroupBox("変換元")
            source_layout = QVBoxLayout(source_box)
            source_layout.setSpacing(8)
            source_hint = QLabel(
                ".fxp / .SerumPreset またはフォルダを追加（ファイル管理画面からドロップできます）"
            )
            self.source_list = SourceListWidget()
            self.source_list.setMinimumHeight(56)
            self.source_list.setMaximumHeight(120)
            self.source_list.setToolTip("複数のファイルやフォルダをまとめて変換できます")
            self.source_list.paths_dropped.connect(self._add_paths)
            self.source_list.itemSelectionChanged.connect(self._update_actions)
            source_buttons = QHBoxLayout()
            self.add_files_button = QPushButton("ファイルを追加…")
            self.add_folder_button = QPushButton("フォルダを追加…")
            self.remove_button = QPushButton("選択を削除")
            self.add_files_button.clicked.connect(self._choose_files)
            self.add_folder_button.clicked.connect(self._choose_folder)
            self.remove_button.clicked.connect(self._remove_selected)
            source_buttons.addWidget(self.add_files_button)
            source_buttons.addWidget(self.add_folder_button)
            source_buttons.addStretch(1)
            source_buttons.addWidget(self.remove_button)
            source_layout.addWidget(source_hint)
            source_layout.addWidget(self.source_list)
            source_layout.addLayout(source_buttons)
            outer.addWidget(source_box)

            location_box = QGroupBox("保存場所とSerumデータ")
            location_layout = QGridLayout(location_box)
            location_layout.setColumnStretch(1, 1)
            serum_label = QLabel("Serumデータ")
            self.serum_root_edit = QLineEdit()
            self.serum_root_edit.setPlaceholderText("任意 — Tables / Noises を含むフォルダ")
            self.serum_root_button = QPushButton("選択…")
            self.serum_root_button.clicked.connect(self._choose_serum_root)
            output_label = QLabel("出力先")
            self.output_edit = QLineEdit()
            self.output_edit.setPlaceholderText("必須 — .vitalファイルの保存先")
            self.output_edit.textChanged.connect(self._update_actions)
            self.output_button = QPushButton("選択…")
            self.output_button.clicked.connect(self._choose_output)
            location_layout.addWidget(serum_label, 0, 0)
            location_layout.addWidget(self.serum_root_edit, 0, 1)
            location_layout.addWidget(self.serum_root_button, 0, 2)
            location_layout.addWidget(output_label, 1, 0)
            location_layout.addWidget(self.output_edit, 1, 1)
            location_layout.addWidget(self.output_button, 1, 2)
            outer.addWidget(location_box)

            options_box = QGroupBox("変換オプション")
            options_layout = QGridLayout(options_box)
            options_layout.setHorizontalSpacing(20)
            self.layout_combo = QComboBox()
            self.layout_combo.addItem("元のフォルダ構成を維持", LAYOUT_PRESERVE)
            self.layout_combo.addItem("楽器 / タイプ / 特徴で分類", LAYOUT_ORGANIZE)
            self.layout_combo.addItem("1つのフォルダにまとめる", LAYOUT_FLATTEN)
            self.max_frames_spin = QSpinBox()
            self.max_frames_spin.setRange(1, 256)
            self.max_frames_spin.setValue(64)
            self.max_frames_spin.setSuffix(" フレーム")
            self.max_frames_spin.setToolTip("少ないほどファイルサイズが小さくなります")
            self.wavetables_check = QCheckBox("ウェーブテーブルを埋め込む")
            self.wavetables_check.setChecked(True)
            self.samples_check = QCheckBox("ノイズサンプルを埋め込む")
            self.samples_check.setChecked(True)
            self.overwrite_check = QCheckBox("既存ファイルを上書き")
            options_layout.addWidget(QLabel("配置"), 0, 0)
            options_layout.addWidget(self.layout_combo, 0, 1)
            options_layout.addWidget(QLabel("最大キーフレーム"), 0, 2)
            options_layout.addWidget(self.max_frames_spin, 0, 3)
            options_layout.addWidget(self.wavetables_check, 1, 0, 1, 2)
            options_layout.addWidget(self.samples_check, 1, 2)
            options_layout.addWidget(self.overwrite_check, 1, 3)
            options_layout.setColumnStretch(1, 1)
            outer.addWidget(options_box)

            progress_row = QHBoxLayout()
            self.status_label = QLabel("入力と出力先を選択してください")
            self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.progress_bar = QProgressBar()
            self.progress_bar.setMinimumWidth(240)
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            progress_row.addWidget(self.status_label, 1)
            progress_row.addWidget(self.progress_bar)
            outer.addLayout(progress_row)

            self.log = QPlainTextEdit()
            self.log.setReadOnly(True)
            self.log.setPlaceholderText("変換ログがここに表示されます")
            self.log.setMaximumBlockCount(5000)
            self.log.setMinimumHeight(100)
            font = self.log.font()
            font.setFamilies(["SF Mono", "Menlo", "Monaco", "monospace"])
            font.setStyleHint(font.StyleHint.Monospace)
            font.setPointSize(max(10, font.pointSize()))
            self.log.setFont(font)
            outer.addWidget(self.log, 1)

            action_row = QHBoxLayout()
            self.reveal_button = QPushButton("出力先を開く")
            self.reveal_button.clicked.connect(self._reveal_output)
            self.cancel_button = QPushButton("キャンセル")
            self.cancel_button.clicked.connect(self._cancel)
            self.convert_button = QPushButton("変換を開始")
            self.convert_button.setDefault(True)
            self.convert_button.clicked.connect(self._start)
            action_row.addWidget(self.reveal_button)
            action_row.addStretch(1)
            action_row.addWidget(self.cancel_button)
            action_row.addWidget(self.convert_button)
            outer.addLayout(action_row)

            self.setCentralWidget(central)

        def _refresh_brand_colors(self) -> None:
            palette = self.palette()
            background = palette.color(QPalette.ColorRole.Window)
            foreground = palette.color(QPalette.ColorRole.WindowText).name()
            cyan, purple = BRAND_DARK if background.lightnessF() < 0.5 else BRAND_LIGHT
            self.brand.setText(
                f'<span style="font-size:28px; font-weight:650; color:{foreground}">serum</span>'
                f'<span style="font-size:28px; font-weight:700; color:{cyan}">2</span>'
                f'<span style="font-size:28px; font-weight:650; color:{purple}">vital</span>'
            )

        def changeEvent(self, event) -> None:
            super().changeEvent(event)
            if hasattr(self, "brand") and event.type() in (
                QEvent.Type.PaletteChange,
                QEvent.Type.ApplicationPaletteChange,
            ):
                self._refresh_brand_colors()

        def _choose_files(self) -> None:
            paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Serumプリセットを選択",
                "",
                "Serum presets (*.fxp *.SerumPreset);;All files (*)",
            )
            self._add_paths(paths)

        def _choose_folder(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "プリセットフォルダを選択")
            if path:
                self._add_paths([path])

        def _choose_serum_root(self) -> None:
            path = QFileDialog.getExistingDirectory(
                self,
                "Serumデータフォルダを選択",
                self.serum_root_edit.text().strip(),
            )
            if path:
                self.serum_root_edit.setText(path)

        def _choose_output(self) -> None:
            path = QFileDialog.getExistingDirectory(
                self,
                "出力先を選択",
                self.output_edit.text().strip(),
            )
            if path:
                self.output_edit.setText(path)

        def _add_paths(self, paths: Sequence[str]) -> None:
            rejected: list[str] = []
            for raw_path in paths:
                path = Path(raw_path).expanduser()
                if not path.exists() or (
                    not path.is_dir() and path.suffix.lower() not in {".fxp", ".serumpreset"}
                ):
                    rejected.append(str(path))
                    continue
                absolute = str(path.resolve())
                key = os.path.normcase(absolute)
                if key in self._source_keys:
                    continue
                self._source_keys.add(key)
                item = QListWidgetItem(absolute)
                item.setData(Qt.ItemDataRole.UserRole, absolute)
                item.setToolTip(absolute)
                self.source_list.addItem(item)
            if rejected:
                self.log.appendPlainText("対象外の項目を無視しました:\n" + "\n".join(rejected))
            self._update_actions()

        def _remove_selected(self) -> None:
            for item in self.source_list.selectedItems():
                path = item.data(Qt.ItemDataRole.UserRole)
                self._source_keys.discard(os.path.normcase(path))
                self.source_list.takeItem(self.source_list.row(item))
            self._update_actions()

        def _input_paths(self) -> list[str]:
            return [
                self.source_list.item(index).data(Qt.ItemDataRole.UserRole)
                for index in range(self.source_list.count())
            ]

        def _running(self) -> bool:
            return self._process.state() != QProcess.ProcessState.NotRunning

        def _update_actions(self) -> None:
            running = self._running()
            has_inputs = self.source_list.count() > 0
            has_output = bool(self.output_edit.text().strip())
            self.convert_button.setEnabled(not running and has_inputs and has_output)
            self.cancel_button.setEnabled(running and not self._cancel_requested)
            self.remove_button.setEnabled(not running and bool(self.source_list.selectedItems()))
            self.add_files_button.setEnabled(not running)
            self.add_folder_button.setEnabled(not running)
            self.serum_root_edit.setEnabled(not running)
            self.serum_root_button.setEnabled(not running)
            self.output_edit.setEnabled(not running)
            self.output_button.setEnabled(not running)
            self.layout_combo.setEnabled(not running)
            self.max_frames_spin.setEnabled(not running)
            self.wavetables_check.setEnabled(not running)
            self.samples_check.setEnabled(not running)
            self.overwrite_check.setEnabled(not running)
            self.reveal_button.setEnabled(not running and has_output)

        def _start(self) -> None:
            inputs = self._input_paths()
            output = self.output_edit.text().strip()
            serum_root_text = self.serum_root_edit.text().strip()
            serum_root = str(Path(serum_root_text).expanduser()) if serum_root_text else None
            if not inputs or not output:
                return
            if serum_root and not Path(serum_root).expanduser().is_dir():
                QMessageBox.warning(self, "Serumデータ", "Serumデータフォルダが見つかりません。")
                return
            output_path = Path(output).expanduser()
            if output_path.exists() and not output_path.is_dir():
                QMessageBox.warning(self, "出力先", "出力先にはフォルダを指定してください。")
                return

            try:
                arguments = build_cli_arguments(
                    inputs,
                    str(output_path),
                    serum_root=serum_root,
                    layout=self.layout_combo.currentData(),
                    include_wavetables=self.wavetables_check.isChecked(),
                    include_samples=self.samples_check.isChecked(),
                    overwrite=self.overwrite_check.isChecked(),
                    max_frames=self.max_frames_spin.value(),
                )
            except ValueError as exc:
                QMessageBox.warning(self, "入力を確認してください", str(exc))
                return

            self.log.clear()
            self.log.appendPlainText("変換を開始します…")
            self._line_buffer = ""
            self._cancel_requested = False
            self._failed_count = 0
            self.status_label.setText("プリセットを検索しています…")
            self.progress_bar.setRange(0, 0)
            self._process.setProgram(worker_python_executable())
            self._process.setArguments(arguments)
            self._process.start()
            self._update_actions()

        def _read_process_output(self) -> None:
            chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._line_buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                self._consume_line(line)

        def _consume_line(self, line: str) -> None:
            self.log.appendPlainText(line)
            progress = parse_progress_line(line)
            if progress is not None:
                self.progress_bar.setRange(0, progress.total)
                self.progress_bar.setValue(progress.current)
                labels = {"ok": "変換中", "skipped": "スキップ", "failed": "失敗"}
                self.status_label.setText(
                    f"{progress.current} / {progress.total} — "
                    f"{labels.get(progress.status, progress.status)}: {progress.detail}"
                )
                return
            summary = _SUMMARY_RE.match(line.strip())
            if summary is not None:
                converted, skipped, failed, total = map(int, summary.groups())
                self._failed_count = failed
                self.progress_bar.setRange(0, max(1, total))
                self.progress_bar.setValue(total)
                self.status_label.setText(
                    f"{converted}件変換・{skipped}件スキップ・{failed}件失敗"
                )

        def _cancel(self) -> None:
            if not self._running():
                return
            self._cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.status_label.setText("キャンセルしています…")
            self.log.appendPlainText("\nキャンセルを要求しました。")
            self._process.terminate()
            self._kill_timer.start(2000)

        def _kill_if_running(self) -> None:
            if self._running():
                self._process.kill()

        def _process_finished(self, exit_code: int, exit_status) -> None:
            self._kill_timer.stop()
            # A short-lived command can finish before the final ready-read
            # notification is dispatched, so explicitly drain the pipe.
            self._read_process_output()
            if self._line_buffer:
                self._consume_line(self._line_buffer)
                self._line_buffer = ""
            if self._cancel_requested:
                self.status_label.setText("キャンセルしました")
                self.log.appendPlainText("\n変換をキャンセルしました。")
            elif exit_status == QProcess.ExitStatus.CrashExit:
                self.status_label.setText("変換プロセスが予期せず終了しました")
            elif exit_code == 0:
                if self._failed_count:
                    self.status_label.setText(f"完了（一部失敗: {self._failed_count}件）")
                elif self.progress_bar.maximum() == 0:
                    self.status_label.setText("変換が完了しました")
            else:
                self.status_label.setText(f"変換できませんでした（終了コード {exit_code}）")
            self._update_actions()

        def _process_error(self, error) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self.status_label.setText("変換プロセスを起動できませんでした")
                self.log.appendPlainText(self._process.errorString())
                self._update_actions()

        def _reveal_output(self) -> None:
            output = self.output_edit.text().strip()
            if output:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(output).expanduser())))

        def closeEvent(self, event: QCloseEvent) -> None:
            if self._running():
                answer = QMessageBox.question(
                    self,
                    "変換を終了しますか？",
                    "変換中です。終了すると処理をキャンセルします。",
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Close,
                    QMessageBox.StandardButton.Cancel,
                )
                if answer != QMessageBox.StandardButton.Close:
                    event.ignore()
                    return
                self._process.kill()
                self._process.waitForFinished(1500)
            event.accept()

    return QApplication, MainWindow


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop application."""
    try:
        QApplication, MainWindow = _load_gui_classes()
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6" or (exc.name and exc.name.startswith("PySide6.")):
            print(
                'The GUI requires PySide6. Install it with: pip install ".[gui]"',
                file=sys.stderr,
            )
            return 2
        raise

    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("serum2vital")
    app.setOrganizationName("serum2vital")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
