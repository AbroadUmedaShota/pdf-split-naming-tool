from __future__ import annotations

import queue
import os
import sys
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, BooleanVar, Canvas, DoubleVar, Listbox, StringVar, Text, Tk, filedialog, messagebox, simpledialog
from tkinter import ttk

from .app_metadata import APP_NAME
from .history import OutputHistory
from .models import Segment
from .output_controller import build_output_preflight_view
from .presets import PresetRepository, find_preset
from .processor import OCR_PREREQUISITE_MESSAGE, PdfProcessor
from .state import StateManager
from .step2_controller import (
    candidate_pages as build_candidate_pages,
    current_page_state_text,
    page_badges as build_page_badges,
    page_list_label as build_page_list_label,
    segment_for_page as find_segment_for_page,
    segment_state_text,
    split_boundary_pages as build_split_boundary_pages,
    visible_page_numbers,
)
from .ui_theme import (
    UI_BORDER,
    UI_DANGER,
    UI_PREVIEW_BG,
    UI_PRIMARY,
    UI_READY,
    UI_TEXT,
    UI_WARNING,
    configure_app_style,
    style_listbox,
    style_text,
)
from .workflow import (
    OUTPUT_ACTION_CREATE_UNIQUE,
    OUTPUT_ACTION_LABELS,
    OUTPUT_ACTION_REUSE_EXISTING,
    OUTPUT_ACTION_SKIP,
    apply_common_metadata,
    check_segment_outputs,
    delete_segment_pages,
    error_messages,
    extract_segment_pages,
    metadata_suggestions_from_text,
    move_segment_page,
    normalized_output_action,
    resequence_segments,
    rotate_segment_pages,
    segment_page_plan,
)


TEXT_WIDGET_CLASSES = {"Entry", "TEntry", "Text", "Spinbox", "TCombobox"}
MAIN_TAB_LABELS = ("1 PDF取込", "2 ページ整理", "3 入力", "4 出力確認", "5 履歴")
STEP2_DETAIL_TAB_LABELS = ("検出", "候補", "OCR本文", "操作")


class PdfSplitterApp:
    def __init__(self, root: Tk, work_dir: Path | None = None) -> None:
        self.root = root
        self.work_dir = work_dir or Path.cwd()
        self.root.title(APP_NAME)
        self.processor = PdfProcessor()
        self.state_manager = StateManager(self.work_dir)
        self.output_history = OutputHistory(self.work_dir)
        self.preset_repo = PresetRepository(self.work_dir / "presets.json")
        self.presets, self.active_preset_id = self.preset_repo.load()
        self.active_preset = find_preset(self.presets, self.active_preset_id)

        self.pdf_paths: list[Path] = []
        self.current_pdf: Path | None = None
        self.current_page = 1
        self.current_page_count = 0
        self.output_dir = self.work_dir / "output"
        self.segments: list[Segment] = []
        self.current_segment_index: int | None = None
        self.metadata_vars: dict[str, StringVar] = {}
        self.common_metadata_vars: dict[str, StringVar] = {}
        self.step1_common_metadata_vars: dict[str, StringVar] = {}
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._preview_image = None
        self._preview_offset = (8, 8)
        self._preview_zoom = 1.2
        self._render_generation = 0
        self._render_lock = threading.Lock()
        self._pending_render = False
        self.active_job_cancel: threading.Event | None = None
        self.active_job_name = ""
        self.load_cancel_event: threading.Event | None = None
        self.undo_stack: list[list[Segment]] = []
        self.redo_stack: list[list[Segment]] = []
        self._restoring_state = False
        self.workflow_summary_var = StringVar()
        self.next_action_var = StringVar(value="次にやること: PDFまたは入力フォルダを選択してください。")
        self.footer_status_var = StringVar()
        self.step_status_vars: list[StringVar] = []
        self.page_list_page_numbers: list[int] = []
        self.candidate_list_page_numbers: list[int] = []
        self.search_hit_pages: set[int] = set()
        self.blank_candidate_pages: set[int] = set()
        self.index_candidate_pages: set[int] = set()
        self.show_candidates_only_var = BooleanVar(value=False)
        self.step1_details_visible_var = BooleanVar(value=False)
        self.step2_details_visible_var = BooleanVar(value=False)
        self.step3_assist_visible_var = BooleanVar(value=False)
        self.current_page_var = StringVar(value="現在 - / - ページ")
        self.current_page_state_var = StringVar(value="PDFを選択してください")
        self.current_segment_var = StringVar(value="セグメント未作成")
        self.split_summary_var = StringVar(value="分割位置: 0件")
        self.candidate_summary_var = StringVar(value="候補: 0件")
        self.metadata_summary_var = StringVar(value="セグメント未作成")
        self.output_check_summary_var = StringVar(value="出力前チェックを実行してください")
        self.load_status_var = StringVar(value="読込待機中")
        self.auto_sort_var = BooleanVar(value=True)
        self.zoom_var = DoubleVar(value=120.0)
        self.zoom_mode_var = StringVar(value="手動")
        self.page_jump_var = StringVar(value="1")
        self.ocr_transfer_field_var = StringVar()
        self.step3_suggestion_var = StringVar(value="入力補助候補: 未生成")
        self.output_progress_var = StringVar(value="出力待機中")
        self.output_instruction_var = StringVar(value="出力前チェックを実行してください。")
        self.history_summary_var = StringVar(value="履歴未読込")
        self.state_status_var = StringVar(value="状態未保存")
        self.output_action_var = StringVar(value=OUTPUT_ACTION_LABELS[OUTPUT_ACTION_CREATE_UNIQUE])
        self.current_pdf_has_text_layer = False
        self.output_action_overrides: dict[str, str] = {}

        self._build_ui()
        self._bind_keys()
        self._update_workflow_status()
        self.root.after(50, self.load_state_on_startup)
        self._poll_worker_queue()

    def _build_ui(self) -> None:
        self.root.geometry("1180x820")
        self.root.minsize(980, 680)
        self._configure_style()

        shell = ttk.Frame(self.root, padding=(12, 10, 12, 8))
        shell.pack(fill=BOTH, expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text=APP_NAME, style="AppTitle.TLabel").pack(side=LEFT)
        ttk.Label(header, textvariable=self.workflow_summary_var, style="AppSummary.TLabel").pack(side=RIGHT)

        tracker = ttk.Frame(shell)
        tracker.pack(fill="x", pady=(0, 8))
        for label in ("PDF取込", "ページ整理", "項目入力", "出力確認", "履歴"):
            var = StringVar(value=f"{label}: 未完了")
            self.step_status_vars.append(var)
            ttk.Label(tracker, textvariable=var, style="StepStatus.TLabel", padding=(8, 4)).pack(side=LEFT, padx=(0, 6))

        ttk.Label(shell, textvariable=self.next_action_var, style="NextAction.TLabel", padding=(10, 7)).pack(
            fill="x",
            pady=(0, 8),
        )

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill=BOTH, expand=True)

        self.step1 = ttk.Frame(self.notebook, padding=8)
        self.step2 = ttk.Frame(self.notebook, padding=8)
        self.step3 = ttk.Frame(self.notebook, padding=8)
        self.step4 = ttk.Frame(self.notebook, padding=8)
        self.step5 = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.step1, text=MAIN_TAB_LABELS[0])
        self.notebook.add(self.step2, text=MAIN_TAB_LABELS[1])
        self.notebook.add(self.step3, text=MAIN_TAB_LABELS[2])
        self.notebook.add(self.step4, text=MAIN_TAB_LABELS[3])
        self.notebook.add(self.step5, text=MAIN_TAB_LABELS[4])
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()
        self._build_step5()

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, textvariable=self.footer_status_var, style="Footer.TLabel").pack(side=LEFT)

    def _configure_style(self) -> None:
        configure_app_style(self.root)

    def _style_listbox(self, listbox: Listbox) -> None:
        style_listbox(listbox)

    def _style_text(self, text: Text) -> None:
        style_text(text)

    def _add_section_header(self, parent: ttk.Frame, title: str, hint: str) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=920).pack(anchor="w", pady=(2, 0))

    def toggle_step1_details(self) -> None:
        if self.step1_details_visible_var.get():
            self.step1_details_frame.pack(fill="x", pady=(6, 0))
        else:
            self.step1_details_frame.pack_forget()

    def toggle_step2_details(self) -> None:
        if self.step2_details_visible_var.get():
            self.step2_details_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        else:
            self.step2_details_frame.pack_forget()

    def toggle_step3_assist(self) -> None:
        if self.step3_assist_visible_var.get():
            self.step3_assist_frame.pack(fill="x", pady=(6, 0))
        else:
            self.step3_assist_frame.pack_forget()

    def _update_workflow_status(self) -> None:
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        ready = sum(1 for check in checks if check.ok)
        invalid = len(checks) - ready

        pdf_status = "未選択"
        if self.current_pdf is not None and self.current_page_count:
            pdf_status = f"OK {len(self.pdf_paths)}件 / {self.current_page_count}ページ"
        elif self.pdf_paths:
            pdf_status = f"選択済み {len(self.pdf_paths)}件"

        split_status = f"{len(self.segments)}件" if self.segments else "未作成"
        input_status = "未作成" if not checks else (f"OK {ready}件" if invalid == 0 else f"要修正 {invalid}件")
        output_status = "実行可能" if checks and invalid == 0 else "確認待ち"

        try:
            history_count = len(self.output_history.load())
        except Exception:
            history_count = 0
        statuses = (
            f"PDF取込: {pdf_status}",
            f"ページ整理: {split_status}",
            f"項目入力: {input_status}",
            f"出力確認: {output_status}",
            f"履歴: {history_count}件",
        )
        for var, text in zip(self.step_status_vars, statuses):
            var.set(text)

        if not self.pdf_paths:
            next_action = "次にやること: PDFまたは入力フォルダを選択し、出力先を指定してください。"
        elif not self.segments:
            next_action = "次にやること: Step 2でPDFを確認し、分割位置を追加してください。"
        elif invalid:
            next_action = f"次にやること: Step 3で要修正 {invalid}件の入力を確認してください。"
        elif checks:
            next_action = "次にやること: Step 4で出力前チェックを確認し、出力実行してください。"
        else:
            next_action = "次にやること: Step 2で分割セグメントを作成してください。"
        self.next_action_var.set(next_action)

        current_name = self.current_pdf.name if self.current_pdf else "PDF未選択"
        self.workflow_summary_var.set(f"{current_name} / {self.active_preset.name}")
        self.footer_status_var.set(f"出力先: {self.output_dir}    作業フォルダ: {self.work_dir}")

    def build_state_payload(self) -> dict[str, object]:
        return {
            "version": 2,
            "active_preset_id": self.active_preset_id,
            "pdf_paths": [str(path) for path in self.pdf_paths],
            "current_pdf": str(self.current_pdf) if self.current_pdf else "",
            "current_page": self.current_page,
            "output_dir": str(self.output_dir),
            "segments": [segment.to_dict() for segment in self.segments],
            "output_actions": dict(self.output_action_overrides),
            "step1_common_metadata": {key: var.get() for key, var in self.step1_common_metadata_vars.items()},
        }

    def save_state(self) -> None:
        try:
            self.state_manager.save(self.build_state_payload())
            self.state_status_var.set("作業状態を保存しました。")
            self.footer_status_var.set(f"作業状態を保存しました: {self.state_manager.state_path}")
        except Exception as exc:
            messagebox.showerror("状態保存", str(exc))

    def load_state_on_startup(self) -> None:
        try:
            state = self.state_manager.load()
        except Exception as exc:
            self.state_status_var.set(f"状態復元をスキップしました: {exc}")
            return
        if not state:
            return
        if state.get("version") != 2:
            self.state_status_var.set("旧形式の状態ファイルは復元対象外です。")
            return
        self.restore_state(state)

    def restore_state(self, state: dict[str, object]) -> None:
        self._restoring_state = True
        try:
            preset_id = str(state.get("active_preset_id", self.active_preset_id))
            self.active_preset = find_preset(self.presets, preset_id)
            self.active_preset_id = self.active_preset.id
            self.refresh_preset_combo()
            self.rebuild_step1_common_fields()
            self.refresh_ocr_transfer_fields()
            self.pdf_paths = [Path(path) for path in state.get("pdf_paths", []) if Path(str(path)).exists()]
            self.output_dir = Path(str(state.get("output_dir", self.output_dir)))
            self.output_action_overrides = {
                str(key): normalized_output_action(str(value))
                for key, value in dict(state.get("output_actions", {})).items()
            }
            self.segments = []
            valid_paths = set(self.pdf_paths)
            for item in state.get("segments", []):
                if not isinstance(item, dict):
                    continue
                pdf_path = Path(str(item.get("pdf_path", "")))
                if pdf_path not in valid_paths:
                    continue
                segment = Segment.from_dict(item)
                if segment.pdf_path == pdf_path:
                    self.segments.append(segment)
            for key, value in dict(state.get("step1_common_metadata", {})).items():
                if key in self.step1_common_metadata_vars:
                    self.step1_common_metadata_vars[key].set(str(value))
            current_pdf = Path(str(state.get("current_pdf", "")))
            self.current_pdf = current_pdf if current_pdf in valid_paths else (self.pdf_paths[0] if self.pdf_paths else None)
            self.current_page = max(1, int(state.get("current_page", 1)))
            if self.current_pdf is not None:
                self.current_page_count = self.processor.page_count(self.current_pdf)
                self.current_pdf_has_text_layer = self.processor.has_text_layer(self.current_pdf, max_pages=5)
                self.current_page = min(self.current_page, self.current_page_count)
                self.page_jump_var.set(str(self.current_page))
            self.refresh_pdf_list()
            self.refresh_page_list()
            self.refresh_segment_list()
            self.rebuild_metadata_fields()
            self.refresh_output_summary()
            if self.current_pdf is not None:
                self.render_current_page_async()
            self.state_status_var.set("前回状態を復元しました")
            self._update_workflow_status()
        except Exception as exc:
            self.state_status_var.set(f"状態復元に失敗しました: {exc}")
        finally:
            self._restoring_state = False

    def _build_step1(self) -> None:
        self._add_section_header(
            self.step1,
            "1. PDFと出力先を選ぶ",
            "上から順に確認してください。PDFを追加し、共通項目と出力先を揃えると分割作業へ進めます。",
        )

        status = ttk.LabelFrame(self.step1, text="準備状況", padding=8)
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.state_status_var, style="Hint.TLabel").pack(anchor="w")

        preset_frame = ttk.LabelFrame(self.step1, text="案件プリセット", padding=8)
        preset_frame.pack(fill="x", pady=(8, 0))
        preset_row = ttk.Frame(preset_frame)
        preset_row.pack(fill="x")
        ttk.Label(preset_row, text="プリセット:", width=12).pack(side=LEFT)

        self.preset_var = StringVar(value=self.active_preset.name)
        self.preset_combo = ttk.Combobox(
            preset_row,
            textvariable=self.preset_var,
            values=[preset.name for preset in self.presets],
            state="readonly",
            width=28,
        )
        self.preset_combo.pack(side=LEFT)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)
        ttk.Label(preset_row, text="通常作業では選択だけ行います。編集は詳細設定から開きます。", style="Hint.TLabel").pack(
            side=LEFT,
            padx=10,
        )
        ttk.Checkbutton(
            preset_frame,
            text="詳細設定を表示",
            variable=self.step1_details_visible_var,
            command=self.toggle_step1_details,
        ).pack(anchor="w", pady=(6, 0))
        self.step1_details_frame = ttk.Frame(preset_frame)
        ttk.Button(self.step1_details_frame, text="プリセット管理", command=self.open_preset_manager).pack(side=LEFT)
        ttk.Button(self.step1_details_frame, text="置換読込(PDF)", command=self.replace_with_pdfs).pack(side=LEFT, padx=4)
        ttk.Button(self.step1_details_frame, text="置換読込(フォルダ)", command=self.replace_with_folder).pack(side=LEFT, padx=4)
        self.toggle_step1_details()

        common = ttk.LabelFrame(self.step1, text="共通項目（下書き）", padding=8)
        common.pack(fill="x", pady=(8, 0))
        ttk.Label(
            common,
            text="ここで入力した値は下書きです。「共通項目を全PDFへ適用」で初めて分割済みセグメントへ反映されます。",
            style="Hint.TLabel",
        ).pack(anchor="w")
        self.step1_common_fields_frame = ttk.Frame(common)
        self.step1_common_fields_frame.pack(fill="x", pady=(6, 0))
        common_buttons = ttk.Frame(common)
        common_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(common_buttons, text="共通項目を全PDFへ適用", command=self.apply_step1_common_metadata).pack(side=LEFT)
        self.rebuild_step1_common_fields()

        load_frame = ttk.LabelFrame(self.step1, text="PDF読込", padding=8)
        load_frame.pack(fill="x", pady=(8, 0))
        ttk.Button(load_frame, text="PDFを個別に選択", command=self.select_pdfs, style="Primary.TButton").pack(side=LEFT)
        ttk.Button(load_frame, text="入力フォルダを選択", command=self.select_folder, style="Primary.TButton").pack(side=LEFT, padx=6)
        ttk.Checkbutton(load_frame, text="ファイル名で自動ソート", variable=self.auto_sort_var).pack(side=LEFT, padx=10)
        ttk.Label(load_frame, textvariable=self.load_status_var, style="Hint.TLabel").pack(side=LEFT, padx=8)
        self.cancel_load_button = ttk.Button(load_frame, text="中断", command=self.cancel_pdf_loading, state="disabled")
        self.cancel_load_button.pack(side=RIGHT)

        ttk.Label(self.step1, text="PDF一覧 - ファイル名、ページ数、保存場所を確認できます。", style="Hint.TLabel").pack(
            anchor="w",
            pady=(8, 0),
        )
        self.pdf_list = Listbox(self.step1, height=3)
        self._style_listbox(self.pdf_list)
        self.pdf_list.pack(fill="x", pady=6)
        self.pdf_list.bind("<<ListboxSelect>>", self.on_pdf_selected)
        pdf_buttons = ttk.Frame(self.step1)
        pdf_buttons.pack(fill="x")
        ttk.Button(pdf_buttons, text="選択解除", command=self.remove_selected_pdf).pack(side=LEFT)
        ttk.Button(pdf_buttons, text="全クリア", command=self.clear_pdf_selection).pack(side=LEFT, padx=4)
        ttk.Button(pdf_buttons, text="状態を保存", command=self.save_state).pack(side=RIGHT)

        output_frame = ttk.LabelFrame(self.step1, text="出力設定", padding=8)
        output_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(output_frame, textvariable=self.footer_status_var, style="Hint.TLabel").pack(side=LEFT, fill="x", expand=True)
        ttk.Button(output_frame, text="出力フォルダを選択", command=self.select_output_dir, style="Primary.TButton").pack(side=RIGHT)

    def open_preset_manager(self) -> None:
        from .preset_manager_dialog import PresetManagerDialog

        PresetManagerDialog(self)

    def refresh_preset_combo(self) -> None:
        self.preset_combo["values"] = [preset.name for preset in self.presets]
        self.preset_var.set(self.active_preset.name)

    def set_active_preset(self, preset_id: str) -> None:
        self.active_preset = find_preset(self.presets, preset_id)
        self.active_preset_id = self.active_preset.id
        self.preset_repo.save(self.presets, self.active_preset_id)
        self.refresh_preset_combo()
        self.rebuild_step1_common_fields()
        self.refresh_ocr_transfer_fields()
        self.rebuild_metadata_fields()
        self.refresh_segment_list()
        self._update_workflow_status()

    def rebuild_step1_common_fields(self) -> None:
        if not hasattr(self, "step1_common_fields_frame"):
            return
        for child in self.step1_common_fields_frame.winfo_children():
            child.destroy()
        self.step1_common_metadata_vars = {}
        for index, field in enumerate(field for field in self.active_preset.fields if field.key != "seq"):
            row = ttk.Frame(self.step1_common_fields_frame)
            row.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 12), pady=2)
            ttk.Label(row, text=field.label, width=14).pack(side=LEFT)
            var = StringVar(value=field.default)
            self.step1_common_metadata_vars[field.key] = var
            ttk.Entry(row, textvariable=var, width=18).pack(side=LEFT)
        for column in range(3):
            self.step1_common_fields_frame.columnconfigure(column, weight=1)

    def apply_step1_common_metadata(self) -> None:
        values = {key: var.get() for key, var in self.step1_common_metadata_vars.items() if var.get().strip()}
        if not values:
            messagebox.showinfo("共通項目", "反映する値が入力されていません。")
            return
        if not self.segments:
            messagebox.showinfo("共通項目", "分割済みセグメントがありません。Step 2で分割を作成後に反映してください。")
            return
        apply_common_metadata(self.segments, values)
        self.refresh_segment_list()
        self.rebuild_metadata_fields()
        self.refresh_output_summary()
        self.state_status_var.set("共通項目を分割済みセグメントへ反映しました")
        self._update_workflow_status()

    def _build_step2(self) -> None:
        self._add_section_header(
            self.step2,
            "2. ページを見ながら分割する",
            "通常作業では、ページを確認して「現在ページの前に分割」を押します。検索やOCRは必要なときだけ詳細機能から開きます。",
        )
        workspace = ttk.Frame(self.step2)
        workspace.pack(fill=BOTH, expand=True)

        left = ttk.Frame(workspace)
        left.pack(side=LEFT, fill="y")
        left_header = ttk.Frame(left)
        left_header.pack(fill="x")
        ttk.Label(left_header, text="ページ状態", style="Hint.TLabel").pack(side=LEFT)
        ttk.Checkbutton(
            left_header,
            text="候補のみ",
            variable=self.show_candidates_only_var,
            command=self.refresh_page_list,
        ).pack(side=RIGHT)
        self.page_list = Listbox(left, width=30)
        self._style_listbox(self.page_list)
        self.page_list.pack(fill="y", expand=True)
        self.page_list.bind("<<ListboxSelect>>", self.on_page_selected)

        center = ttk.Frame(workspace)
        center.pack(side=LEFT, fill=BOTH, expand=True, padx=8)
        preview_bar = ttk.Frame(center)
        preview_bar.pack(fill="x")
        ttk.Label(preview_bar, textvariable=self.current_page_var, style="SectionTitle.TLabel").pack(side=LEFT)
        ttk.Button(preview_bar, text="前ページ", command=self.prev_page).pack(side=RIGHT)
        ttk.Button(preview_bar, text="次ページ", command=self.next_page).pack(side=RIGHT, padx=4)
        ttk.Button(preview_bar, text="Space: 現在ページの前で分割", command=self.add_split_before_current_page).pack(
            side=RIGHT,
            padx=4,
        )
        nav_row = ttk.Frame(center)
        nav_row.pack(fill="x", pady=(4, 0))
        ttk.Label(nav_row, text="ページ指定").pack(side=LEFT)
        ttk.Entry(nav_row, textvariable=self.page_jump_var, width=8).pack(side=LEFT, padx=(4, 2))
        ttk.Button(nav_row, text="移動", command=self.go_to_page).pack(side=LEFT)
        ttk.Label(nav_row, text="ズーム").pack(side=LEFT, padx=(14, 2))
        ttk.Scale(nav_row, from_=60, to=220, variable=self.zoom_var, command=self.on_zoom_changed, length=140).pack(side=LEFT)
        ttk.Button(nav_row, text="幅に合わせる", command=lambda: self.set_zoom_mode("幅")).pack(side=LEFT, padx=4)
        ttk.Button(nav_row, text="全体表示", command=lambda: self.set_zoom_mode("全体")).pack(side=LEFT)
        ttk.Label(nav_row, textvariable=self.zoom_mode_var, style="Hint.TLabel").pack(side=LEFT, padx=8)
        ttk.Label(center, text="←/→でページ移動。入力欄・OCR本文にフォーカス中は通常入力を優先します。", style="Hint.TLabel").pack(
            anchor="w",
            pady=(4, 0),
        )

        self.preview_canvas = Canvas(
            center,
            background=UI_PREVIEW_BG,
            height=520,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_PRIMARY,
            borderwidth=0,
            relief="flat",
            takefocus=True,
        )
        self.preview_canvas.pack(fill=BOTH, expand=True, pady=8)
        self.preview_canvas.bind("<Button-1>", lambda _event: self.preview_canvas.focus_set())
        self.status_var = StringVar(value="PDF未選択")
        ttk.Label(center, textvariable=self.status_var).pack(fill="x")

        decision = ttk.Frame(workspace)
        decision.pack(side=LEFT, fill="y")
        page_state = ttk.LabelFrame(decision, text="現在ページ状態", padding=8)
        page_state.pack(fill="x")
        ttk.Label(page_state, textvariable=self.current_page_state_var, wraplength=280).pack(anchor="w")
        ttk.Label(page_state, textvariable=self.current_segment_var, style="Hint.TLabel", wraplength=280).pack(anchor="w", pady=(4, 0))

        main_split = ttk.LabelFrame(decision, text="分割操作", padding=8)
        main_split.pack(fill="x", pady=(8, 0))
        ttk.Label(main_split, textvariable=self.split_summary_var).pack(anchor="w")
        self.split_list = Listbox(main_split, width=36, height=5)
        self._style_listbox(self.split_list)
        self.split_list.pack(fill="x", pady=(4, 6))
        ttk.Button(main_split, text="現在ページの前に分割", command=self.add_split_before_current_page, style="Primary.TButton").pack(fill="x")
        ttk.Button(main_split, text="最後の分割を取り消す", command=self.undo_last_split).pack(fill="x", pady=(4, 0))
        ttk.Button(main_split, text="1ページごとに分割", command=lambda: self.split_by_n_pages(1)).pack(fill="x", pady=(4, 0))

        ttk.Checkbutton(
            decision,
            text="詳細機能を表示",
            variable=self.step2_details_visible_var,
            command=self.toggle_step2_details,
        ).pack(anchor="w", pady=(8, 0))
        self.step2_details_frame = ttk.Frame(decision)

        self.step2_detail_tabs = ttk.Notebook(self.step2_details_frame)
        self.step2_detail_tabs.pack(fill=BOTH, expand=True)

        detect_tab = ttk.Frame(self.step2_detail_tabs, padding=6)
        self.step2_detail_tabs.add(detect_tab, text=STEP2_DETAIL_TAB_LABELS[0])
        self.search_var = StringVar()
        self.search_entry = ttk.Entry(detect_tab, textvariable=self.search_var, width=28)
        self.search_entry.pack(fill="x")
        tool_buttons = ttk.Frame(detect_tab)
        tool_buttons.pack(fill="x", pady=(6, 0))
        self.search_button = ttk.Button(tool_buttons, text="検索", command=self.start_text_search)
        self.search_button.pack(side=LEFT, fill="x", expand=True)
        self.index_button = ttk.Button(tool_buttons, text="インデックス", command=self.start_index_candidate_search)
        self.index_button.pack(side=LEFT, fill="x", expand=True, padx=4)
        self.blank_button = ttk.Button(tool_buttons, text="白紙検出", command=self.start_blank_scan)
        self.blank_button.pack(side=LEFT, fill="x", expand=True)
        self.cancel_job_button = ttk.Button(detect_tab, text="処理中止", command=self.cancel_active_job, state="disabled")
        self.cancel_job_button.pack(fill="x", pady=(6, 0))
        ttk.Label(
            detect_tab,
            text="検索、インデックス候補、白紙候補は必要な時だけ実行します。",
            style="Hint.TLabel",
            wraplength=260,
        ).pack(anchor="w", pady=(6, 0))

        candidate_tab = ttk.Frame(self.step2_detail_tabs, padding=6)
        self.step2_detail_tabs.add(candidate_tab, text=STEP2_DETAIL_TAB_LABELS[1])
        ttk.Label(candidate_tab, textvariable=self.candidate_summary_var).pack(anchor="w")
        self.candidate_list = Listbox(candidate_tab, width=36, height=8)
        self._style_listbox(self.candidate_list)
        self.candidate_list.pack(fill=BOTH, expand=True, pady=(4, 6))
        self.candidate_list.bind("<<ListboxSelect>>", self.on_candidate_selected)
        ttk.Button(candidate_tab, text="候補ページの前に分割", command=self.add_split_before_current_page).pack(fill="x")

        ocr_tab = ttk.Frame(self.step2_detail_tabs, padding=6)
        self.step2_detail_tabs.add(ocr_tab, text=STEP2_DETAIL_TAB_LABELS[2])
        self.ocr_text = Text(ocr_tab, height=12, wrap="word")
        self._style_text(self.ocr_text)
        self.ocr_text.pack(fill=BOTH, expand=True)
        transfer = ttk.Frame(ocr_tab)
        transfer.pack(fill="x", pady=(6, 0))
        self.ocr_transfer_combo = ttk.Combobox(transfer, textvariable=self.ocr_transfer_field_var, state="readonly", width=18)
        self.ocr_transfer_combo.pack(side=LEFT)
        ttk.Button(transfer, text="選択OCRを転記", command=self.transfer_selected_ocr_text).pack(side=LEFT, padx=4)
        self.refresh_ocr_transfer_fields()

        advanced_split = ttk.Frame(self.step2_detail_tabs, padding=6)
        self.step2_detail_tabs.add(advanced_split, text=STEP2_DETAIL_TAB_LABELS[3])
        ttk.Button(advanced_split, text="選択した分割を削除", command=self.delete_selected_split).pack(fill="x")
        organize = ttk.LabelFrame(advanced_split, text="現在ページの整理", padding=6)
        organize.pack(fill="x", pady=(6, 0))
        ttk.Button(organize, text="現在ページを除外", command=self.delete_current_page_from_segment).pack(fill="x")
        ttk.Button(organize, text="現在ページを右回転", command=self.rotate_current_page_in_segment).pack(fill="x", pady=(4, 0))
        move_row = ttk.Frame(organize)
        move_row.pack(fill="x", pady=(4, 0))
        ttk.Button(move_row, text="前へ移動", command=lambda: self.move_current_page_in_segment(-1)).pack(side=LEFT, fill="x", expand=True)
        ttk.Button(move_row, text="後ろへ移動", command=lambda: self.move_current_page_in_segment(1)).pack(side=LEFT, fill="x", expand=True, padx=(4, 0))
        ttk.Button(organize, text="現在ページだけを抽出", command=self.extract_current_page_as_segment).pack(fill="x", pady=(4, 0))
        undo_row = ttk.Frame(advanced_split)
        undo_row.pack(fill="x", pady=(4, 0))
        ttk.Button(undo_row, text="Undo", command=self.undo_segments).pack(side=LEFT, fill="x", expand=True)
        ttk.Button(undo_row, text="Redo", command=self.redo_segments).pack(side=LEFT, fill="x", expand=True, padx=(4, 0))
        ttk.Button(advanced_split, text="参照元フォルダを開く", command=self.open_current_pdf_folder).pack(fill="x", pady=(4, 0))
        ttk.Button(advanced_split, text="このファイルを改名", command=self.rename_current_pdf_file).pack(fill="x", pady=(4, 0))
        self.toggle_step2_details()

    def _build_step3(self) -> None:
        self._add_section_header(
            self.step3,
            "3. 出力名に使う情報を入力する",
            "左の表で分割単位を選び、右側で箱No・バインダーNo・連番を入力します。補助操作は必要なときだけ開きます。",
        )
        left = ttk.Frame(self.step3)
        left.pack(side=LEFT, fill="y")
        ttk.Label(left, textvariable=self.metadata_summary_var, style="Hint.TLabel").pack(anchor="w")
        self.segment_list = ttk.Treeview(
            left,
            columns=("no", "pages", "box", "binder", "seq", "filename", "status"),
            show="headings",
            height=20,
        )
        for column, title, width in (
            ("no", "#", 42),
            ("pages", "ページ", 80),
            ("box", "箱No", 70),
            ("binder", "バインダー", 90),
            ("seq", "連番", 70),
            ("filename", "出力名", 170),
            ("status", "状態", 80),
        ):
            self.segment_list.heading(column, text=title)
            self.segment_list.column(column, width=width, stretch=(column == "filename"))
        self.segment_list.tag_configure("ready", foreground=UI_READY)
        self.segment_list.tag_configure("invalid", foreground=UI_DANGER)
        self.segment_list.pack(side=LEFT, fill=BOTH, expand=True)
        self.segment_list.bind("<<ListboxSelect>>", self.on_segment_selected)
        self.segment_list.bind("<<TreeviewSelect>>", self.on_segment_selected)

        right = ttk.Frame(self.step3, padding=8)
        right.pack(side=LEFT, fill=BOTH, expand=True)
        self.bulk_frame = ttk.LabelFrame(right, text="一括入力", padding=8)
        self.bulk_frame.pack(fill="x")
        self.common_fields_frame = ttk.Frame(self.bulk_frame)
        self.common_fields_frame.pack(fill="x")
        seq_row = ttk.Frame(self.bulk_frame)
        seq_row.pack(fill="x", pady=(6, 0))
        self.seq_start_var = StringVar(value="1")
        self.seq_step_var = StringVar(value="1")
        ttk.Label(seq_row, text="連番開始", width=10).pack(side=LEFT)
        ttk.Entry(seq_row, textvariable=self.seq_start_var, width=8).pack(side=LEFT)
        ttk.Label(seq_row, text="増分", width=6).pack(side=LEFT, padx=(8, 0))
        ttk.Entry(seq_row, textvariable=self.seq_step_var, width=8).pack(side=LEFT)
        ttk.Button(seq_row, text="共通値を全件へ反映", command=self.apply_common_metadata_to_segments).pack(side=LEFT, padx=8)
        ttk.Button(seq_row, text="連番を再採番", command=self.resequence_segment_metadata).pack(side=LEFT)

        ttk.Checkbutton(
            self.bulk_frame,
            text="補助操作を表示",
            variable=self.step3_assist_visible_var,
            command=self.toggle_step3_assist,
        ).pack(anchor="w", pady=(6, 0))
        self.step3_assist_frame = ttk.Frame(self.bulk_frame)
        assist_row = ttk.Frame(self.step3_assist_frame)
        assist_row.pack(fill="x")
        ttk.Button(assist_row, text="前行メタデータコピー", command=self.copy_previous_segment_metadata).pack(side=LEFT)
        ttk.Button(assist_row, text="次の要修正へ移動", command=self.select_next_invalid_segment).pack(side=LEFT, padx=4)
        ttk.Button(assist_row, text="入力補助候補を更新", command=self.refresh_metadata_suggestions).pack(side=LEFT)
        ttk.Button(assist_row, text="選択候補をコピー", command=self.copy_selected_metadata_suggestion).pack(side=LEFT, padx=4)
        ttk.Button(assist_row, text="出力予定フォルダを開く", command=self.open_output_folder).pack(side=LEFT, padx=4)
        ttk.Label(self.step3_assist_frame, textvariable=self.step3_suggestion_var, style="Hint.TLabel", wraplength=560).pack(anchor="w", pady=(6, 0))
        self.suggestion_list = Listbox(self.step3_assist_frame, height=4, exportselection=False)
        self._style_listbox(self.suggestion_list)
        self.suggestion_list.pack(fill="x", pady=(4, 0))
        self.suggestion_list.bind("<Double-Button-1>", lambda _event: self.copy_selected_metadata_suggestion())
        self.toggle_step3_assist()

        self.metadata_frame = ttk.LabelFrame(right, text="選択セグメント", padding=8)
        self.metadata_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.filename_preview_var = StringVar()
        ttk.Label(self.metadata_frame, textvariable=self.filename_preview_var).pack(fill="x", pady=8)

    def _build_step4(self) -> None:
        self._add_section_header(
            self.step4,
            "4. 出力前に確認して実行する",
            "まず出力前チェックを押してください。問題がなければ出力実行、要修正があればStep 3へ戻って入力を直します。",
        )
        ttk.Label(self.step4, textvariable=self.output_instruction_var, style="NextAction.TLabel", padding=(8, 5)).pack(
            fill="x",
            pady=(0, 8),
        )
        toolbar = ttk.Frame(self.step4)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="出力前チェック", command=self.refresh_output_summary).pack(side=LEFT)
        self.run_output_button = ttk.Button(
            toolbar,
            text="出力実行",
            command=self.run_output,
            state="disabled",
            style="Primary.TButton",
        )
        self.run_output_button.pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="出力フォルダを開く", command=self.open_output_folder).pack(side=LEFT)
        self.output_status_var = StringVar(value="出力前チェックを実行してください")
        ttk.Label(toolbar, textvariable=self.output_status_var).pack(side=LEFT, padx=8)
        ttk.Label(toolbar, textvariable=self.output_progress_var, style="Hint.TLabel").pack(side=LEFT)
        ttk.Label(self.step4, textvariable=self.output_check_summary_var, style="Hint.TLabel").pack(anchor="w", pady=(8, 0))

        action_row = ttk.Frame(self.step4)
        action_row.pack(fill="x", pady=(8, 4))
        ttk.Label(action_row, text="選択行の処理").pack(side=LEFT)
        self.output_action_combo = ttk.Combobox(
            action_row,
            textvariable=self.output_action_var,
            values=list(OUTPUT_ACTION_LABELS.values()),
            state="readonly",
            width=22,
        )
        self.output_action_combo.pack(side=LEFT, padx=6)
        ttk.Button(action_row, text="処理方針を反映", command=self.apply_selected_output_action).pack(side=LEFT)
        ttk.Label(action_row, text="既存ファイルの上書きは行いません。", style="Hint.TLabel").pack(side=LEFT, padx=8)

        self.output_tree = ttk.Treeview(
            self.step4,
            columns=("no", "pages", "filename", "existing", "action", "status"),
            show="headings",
            height=8,
        )
        for column, label, width in (
            ("no", "No", 48),
            ("pages", "ページ", 90),
            ("filename", "予定ファイル名", 260),
            ("existing", "既存", 100),
            ("action", "処理方針", 150),
            ("status", "状態", 120),
        ):
            self.output_tree.heading(column, text=label)
            self.output_tree.column(column, width=width, stretch=column == "filename")
        self.output_tree.tag_configure("ready", foreground=UI_READY)
        self.output_tree.tag_configure("warn", foreground=UI_WARNING)
        self.output_tree.tag_configure("invalid", foreground=UI_DANGER)
        self.output_tree.bind("<<TreeviewSelect>>", self.on_output_check_selected)
        self.output_tree.pack(fill="x", pady=(0, 8))

        self.output_text = Text(self.step4, height=12)
        self._style_text(self.output_text)
        self.output_text.pack(fill=BOTH, expand=True, pady=8)
        self.output_text.tag_configure("ok", foreground=UI_READY)
        self.output_text.tag_configure("warn", foreground=UI_WARNING)
        self.output_text.tag_configure("error", foreground=UI_DANGER)
        self.output_text.tag_configure("heading", foreground=UI_TEXT, font=("", 10, "bold"))

    def _build_step5(self) -> None:
        self._add_section_header(
            self.step5,
            "5. 出力履歴を確認する",
            "過去の出力日時、元PDF、ページ操作、出力ファイル、警告結果をローカル履歴として確認できます。",
        )
        toolbar = ttk.Frame(self.step5)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="履歴を更新", command=self.refresh_history_view).pack(side=LEFT)
        ttk.Label(toolbar, textvariable=self.history_summary_var, style="Hint.TLabel").pack(side=LEFT, padx=8)
        self.history_text = Text(self.step5, height=24, wrap="word")
        self._style_text(self.history_text)
        self.history_text.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.history_text.tag_configure("heading", foreground=UI_TEXT, font=("", 10, "bold"))
        self.history_text.tag_configure("ok", foreground=UI_READY)
        self.history_text.tag_configure("warn", foreground=UI_WARNING)
        self.history_text.tag_configure("error", foreground=UI_DANGER)
        self.refresh_history_view()

    def _bind_keys(self) -> None:
        self.root.bind_all("<space>", self.on_space_key)
        self.root.bind_all("<Left>", self.on_left_key)
        self.root.bind_all("<Right>", self.on_right_key)
        self.root.bind_all("<Alt-Left>", self.on_alt_left_key)
        self.root.bind_all("<Alt-Right>", self.on_alt_right_key)
        self.root.bind_all("<Control-s>", self.on_save_key)
        self.root.bind_all("<Control-z>", self.on_undo_key)
        self.root.bind_all("<Control-y>", self.on_redo_key)
        self.root.bind_all("<Delete>", self.on_delete_key)

    def _is_shortcut_blocking_focus_widget(self) -> bool:
        focused = self.root.focus_get()
        if focused is None:
            return False
        class_name = focused.winfo_class()
        if class_name in TEXT_WIDGET_CLASSES:
            return True
        return False

    def on_space_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.add_split_before_current_page()
        return "break"

    def on_left_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.prev_page()
        return "break"

    def on_right_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.next_page()
        return "break"

    def on_alt_left_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.prev_pdf()
        return "break"

    def on_alt_right_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.next_pdf()
        return "break"

    def on_save_key(self, event) -> str:
        self.save_state()
        return "break"

    def on_undo_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.undo_segments()
        return "break"

    def on_redo_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.redo_segments()
        return "break"

    def on_delete_key(self, event) -> str | None:
        if self.notebook.index(self.notebook.select()) != 1 or self._is_shortcut_blocking_focus_widget():
            return None
        self.delete_selected_split()
        return "break"

    def _on_tab_changed(self, _event) -> None:
        if self.notebook.index(self.notebook.select()) == 1:
            self.root.after(50, self.preview_canvas.focus_set)
            self.refresh_page_list()
            self.render_current_page_async()
        elif self.notebook.index(self.notebook.select()) == 2:
            self.refresh_segment_list()
            self.rebuild_metadata_fields()
        elif self.notebook.index(self.notebook.select()) == 3:
            self.refresh_output_summary()
        self._update_workflow_status()

    def select_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        self.add_pdf_paths([Path(path) for path in paths])

    def select_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.add_pdf_paths(list(Path(folder).glob("*.pdf")))

    def replace_with_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if paths:
            self.clear_pdf_selection(confirm=False)
            self.add_pdf_paths([Path(path) for path in paths])

    def replace_with_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.clear_pdf_selection(confirm=False)
            self.add_pdf_paths(list(Path(folder).glob("*.pdf")))

    def add_pdf_paths(self, paths: list[Path]) -> None:
        if self.auto_sort_var.get():
            paths = sorted(paths, key=lambda item: item.name.lower())
        self.load_cancel_event = threading.Event()
        self.cancel_load_button.configure(state="normal")
        total = len(paths)
        for index, path in enumerate(paths, start=1):
            if self.load_cancel_event.is_set():
                self.load_status_var.set(f"読込中断: {index - 1}/{total}件")
                break
            if path not in self.pdf_paths:
                self.pdf_paths.append(path)
                self.pdf_list.insert(END, f"{path.name} | 未読込 | {path}")
            self.load_status_var.set(f"読込進捗: {index}/{total}件")
            self.root.update_idletasks()
        self.cancel_load_button.configure(state="disabled")
        self.load_cancel_event = None
        if self.pdf_paths and self.current_pdf is None:
            self.set_current_pdf(self.pdf_paths[0])
        self.refresh_pdf_list()
        if total:
            self.load_status_var.set(f"読込完了: {len(self.pdf_paths)}件")
        self._update_workflow_status()

    def cancel_pdf_loading(self) -> None:
        if self.load_cancel_event is not None:
            self.load_cancel_event.set()

    def remove_selected_pdf(self) -> None:
        selection = self.pdf_list.curselection()
        if not selection:
            return
        index = selection[0]
        path = self.pdf_paths[index]
        self.pdf_paths.pop(index)
        self.segments = [segment for segment in self.segments if segment.pdf_path != path]
        if self.current_pdf == path:
            self.current_pdf = self.pdf_paths[0] if self.pdf_paths else None
            if self.current_pdf is not None:
                self.set_current_pdf(self.current_pdf)
            else:
                self.current_page_count = 0
                self.current_pdf_has_text_layer = False
                self.preview_canvas.delete("all")
                self.ocr_text.delete("1.0", END)
        self.refresh_pdf_list()
        self.refresh_page_list()
        self.refresh_segment_list()
        self._update_workflow_status()

    def clear_pdf_selection(self, confirm: bool = True) -> None:
        if confirm and self.pdf_paths and not messagebox.askyesno("全クリア", "PDF選択、分割、候補情報をすべてクリアします。よろしいですか。"):
            return
        self.pdf_paths.clear()
        self.current_pdf = None
        self.current_page = 1
        self.current_page_count = 0
        self.current_pdf_has_text_layer = False
        self.segments.clear()
        self.search_hit_pages.clear()
        self.blank_candidate_pages.clear()
        self.index_candidate_pages.clear()
        self.output_action_overrides.clear()
        self.pdf_list.delete(0, END)
        self.page_list.delete(0, END)
        self.preview_canvas.delete("all")
        self.ocr_text.delete("1.0", END)
        self.refresh_segment_list()
        self.refresh_step2_sidebars()
        self._update_workflow_status()

    def select_output_dir(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir = Path(folder)
            self.refresh_output_summary()
            self._update_workflow_status()

    def on_pdf_selected(self, _event) -> None:
        selection = self.pdf_list.curselection()
        if selection:
            self.set_current_pdf(self.pdf_paths[selection[0]])

    def set_current_pdf(self, path: Path) -> None:
        self.current_pdf = path
        self.current_page = 1
        self.page_jump_var.set("1")
        self.search_hit_pages.clear()
        self.blank_candidate_pages.clear()
        self.index_candidate_pages.clear()
        try:
            self.current_page_count = self.processor.page_count(path)
            self.current_pdf_has_text_layer = self.processor.has_text_layer(path, max_pages=5)
            self.refresh_pdf_list()
        except Exception as exc:
            messagebox.showerror("PDFエラー", str(exc))
            self.current_page_count = 0
            self.current_pdf_has_text_layer = False
        self.refresh_page_list()
        self.render_current_page_async()
        self._update_workflow_status()

    def refresh_pdf_list(self) -> None:
        self.pdf_list.delete(0, END)
        for path in self.pdf_paths:
            if path == self.current_pdf and self.current_page_count:
                status = f"{self.current_page_count}ページ"
            else:
                try:
                    status = f"{self.processor.page_count(path)}ページ"
                except Exception:
                    status = "読込エラー"
            self.pdf_list.insert(END, f"{path.name} | {status} | {path.parent}")

    def refresh_page_list(self) -> None:
        self.page_list.delete(0, END)
        candidate_pages = self.candidate_pages()
        pages = visible_page_numbers(self.current_page_count, candidate_pages, self.show_candidates_only_var.get())
        self.page_list_page_numbers = pages
        for page_no in pages:
            self.page_list.insert(END, self.page_list_label(page_no))
        if self.current_page in pages:
            self.page_list.selection_clear(0, END)
            self.page_list.selection_set(pages.index(self.current_page))
        self.refresh_step2_sidebars()

    def on_page_selected(self, _event) -> None:
        selection = self.page_list.curselection()
        if selection:
            self.current_page = self.page_list_page_numbers[selection[0]]
            self.page_jump_var.set(str(self.current_page))
            self.refresh_step2_sidebars()
            self.render_current_page_async()

    def on_candidate_selected(self, _event) -> None:
        selection = self.candidate_list.curselection()
        if selection and selection[0] < len(self.candidate_list_page_numbers):
            self.current_page = self.candidate_list_page_numbers[selection[0]]
            self.page_jump_var.set(str(self.current_page))
            self.sync_page_list_selection()
            self.render_current_page_async()

    def sync_page_list_selection(self) -> None:
        if self.current_page in self.page_list_page_numbers:
            self.page_list.selection_clear(0, END)
            self.page_list.selection_set(self.page_list_page_numbers.index(self.current_page))
        self.refresh_step2_sidebars()

    def split_boundary_pages(self) -> set[int]:
        return build_split_boundary_pages(self.segments, self.current_page_count)

    def candidate_pages(self) -> set[int]:
        return build_candidate_pages(self.search_hit_pages, self.blank_candidate_pages, self.index_candidate_pages)

    def page_badges(self, page_no: int) -> list[str]:
        return build_page_badges(
            page_no,
            self.search_hit_pages,
            self.blank_candidate_pages,
            self.index_candidate_pages,
            self.split_boundary_pages(),
        )

    def page_list_label(self, page_no: int) -> str:
        return build_page_list_label(page_no, self.page_badges(page_no))

    def segment_for_page(self, page_no: int) -> Segment | None:
        return find_segment_for_page(self.segments, page_no)

    def refresh_step2_sidebars(self) -> None:
        if not hasattr(self, "split_list"):
            return
        self.current_page_var.set(f"現在 {self.current_page} / {self.current_page_count or '-'} ページ")
        badges = self.page_badges(self.current_page)
        hit_count = None
        has_hit_count = False
        if self.search_var.get().strip() and self.current_page in self.search_hit_pages:
            try:
                hit_count = len(self.processor.search_text_rects(self.current_pdf, self.current_page, self.search_var.get())) if self.current_pdf else 0
                has_hit_count = True
            except Exception:
                hit_count = None
        state = current_page_state_text(
            badges,
            current_page=self.current_page,
            has_current_pdf=self.current_pdf is not None,
            has_text_layer=self.current_pdf_has_text_layer,
            has_search_query_hit=bool(self.search_var.get().strip() and self.current_page in self.search_hit_pages),
            hit_count=hit_count if has_hit_count else None,
        )
        self.current_page_state_var.set(state)
        self.current_segment_var.set(segment_state_text(self.segments, self.current_page, self.current_page_count))

        boundaries = sorted(self.split_boundary_pages())
        self.split_summary_var.set(f"分割位置: {len(boundaries)}件 / セグメント: {len(self.segments)}件")
        self.split_list.delete(0, END)
        if boundaries:
            for page_no in boundaries:
                self.split_list.insert(END, f"{page_no}ページの前で分割")
        else:
            self.split_list.insert(END, "分割位置は未作成です")

        candidates = sorted(self.candidate_pages())
        self.candidate_list_page_numbers = candidates
        self.candidate_summary_var.set(
            f"候補: {len(candidates)}件  白紙{len(self.blank_candidate_pages)} / 検索{len(self.search_hit_pages)} / 索引{len(self.index_candidate_pages)}"
        )
        self.candidate_list.delete(0, END)
        if candidates:
            for page_no in candidates:
                self.candidate_list.insert(END, self.page_list_label(page_no))
        else:
            self.candidate_list.insert(END, "候補はまだありません")

    def render_current_page_async(self) -> None:
        if self.current_pdf is None or self.current_page_count == 0:
            return
        pdf_path = self.current_pdf
        page_no = self.current_page
        self.refresh_step2_sidebars()
        self._render_generation += 1
        generation = self._render_generation
        zoom = self.effective_zoom()
        query = self.search_var.get().strip()
        self.status_var.set(f"{page_no}/{self.current_page_count}ページを表示中")
        if not self._render_lock.acquire(blocking=False):
            self._pending_render = True
            return

        def worker() -> None:
            try:
                pixmap = self.processor.render_page_pixmap(pdf_path, page_no, zoom=zoom)
                text = self.processor.extract_page_text(pdf_path, page_no)
                rects = []
                if query and page_no in self.search_hit_pages:
                    rects = self.processor.search_text_rects(pdf_path, page_no, query)
                self.worker_queue.put(("rendered", (generation, page_no, zoom, pixmap, text, rects)))
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))
            finally:
                self._render_lock.release()
                if self._pending_render:
                    self._pending_render = False
                    self.worker_queue.put(("render_again", None))

        threading.Thread(target=worker, daemon=True).start()

    def effective_zoom(self) -> float:
        if self.zoom_mode_var.get() == "幅" and self.current_page_count >= 200:
            return 0.9
        if self.zoom_mode_var.get() == "全体":
            return 0.75
        return max(0.6, min(2.2, self.zoom_var.get() / 100))

    def on_zoom_changed(self, _value: str) -> None:
        self.zoom_mode_var.set(f"手動 {int(self.zoom_var.get())}%")
        self.render_current_page_async()

    def set_zoom_mode(self, mode: str) -> None:
        self.zoom_mode_var.set(mode)
        if mode == "幅":
            self.zoom_var.set(90 if self.current_page_count >= 200 else 120)
        elif mode == "全体":
            self.zoom_var.set(75)
        self.render_current_page_async()

    def _display_pixmap(self, zoom: float, pixmap, highlight_rects: list[tuple[float, float, float, float]]) -> None:
        from PIL import Image, ImageTk

        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        self._preview_image = ImageTk.PhotoImage(image)
        self._preview_zoom = zoom
        self.preview_canvas.delete("all")
        offset_x, offset_y = self._preview_offset
        self.preview_canvas.create_image(offset_x, offset_y, image=self._preview_image, anchor="nw")
        for x0, y0, x1, y1 in highlight_rects:
            self.preview_canvas.create_rectangle(
                offset_x + x0 * zoom,
                offset_y + y0 * zoom,
                offset_x + x1 * zoom,
                offset_y + y1 * zoom,
                fill="#fde68a",
                outline="#f59e0b",
                stipple="gray50",
                tags=("search_highlight",),
            )

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "rendered":
                    generation, page_no, zoom, pixmap, text, rects = payload
                    if generation == self._render_generation and page_no == self.current_page:
                        self._display_pixmap(zoom, pixmap, rects)
                        self.ocr_text.delete("1.0", END)
                        self.ocr_text.insert("1.0", text)
                        hit_text = f" / 検索ハイライト {len(rects)}件" if rects else ""
                        self.status_var.set(f"{page_no}/{self.current_page_count}ページ{hit_text}")
                        if self.active_job_cancel is None:
                            self.warm_thumbnail_window(page_no)
                elif kind == "render_again":
                    self.render_current_page_async()
                elif kind == "job_progress":
                    name, current, total = payload
                    self.status_var.set(f"{name}: {current}/{total}ページ")
                elif kind == "search_done":
                    hits, canceled = payload
                    self.finish_active_job()
                    self.search_hit_pages = set(hits)
                    self.refresh_page_list()
                    prefix = "検索を中止しました" if canceled else "検索完了"
                    self.status_var.set(f"{prefix}: {len(hits)}件")
                    if hits:
                        self.current_page = hits[0]
                        self.page_jump_var.set(str(self.current_page))
                        self.sync_page_list_selection()
                        self.render_current_page_async()
                elif kind == "blank_done":
                    pages, canceled = payload
                    self.finish_active_job()
                    self.blank_candidate_pages = set(pages)
                    self.refresh_page_list()
                    prefix = "白紙検出を中止しました" if canceled else "白紙候補"
                    self.status_var.set(f"{prefix}: {', '.join(map(str, pages[:20])) or 'なし'}")
                elif kind == "index_done":
                    hits, canceled = payload
                    self.finish_active_job()
                    self.index_candidate_pages = set(hits)
                    self.refresh_page_list()
                    prefix = "インデックス検索を中止しました" if canceled else "インデックス候補"
                    self.status_var.set(f"{prefix}: {', '.join(map(str, hits[:20])) or 'なし'}")
                    if hits:
                        self.current_page = hits[0]
                        self.page_jump_var.set(str(self.current_page))
                        self.sync_page_list_selection()
                        self.render_current_page_async()
                elif kind == "ocr_prerequisite":
                    target = payload
                    self.finish_active_job()
                    if target == "search":
                        self.search_hit_pages.clear()
                    elif target == "index":
                        self.index_candidate_pages.clear()
                    self.refresh_page_list()
                    self.status_var.set(OCR_PREREQUISITE_MESSAGE)
                    self.ocr_text.delete("1.0", END)
                    self.ocr_text.insert("1.0", OCR_PREREQUISITE_MESSAGE)
                elif kind == "error":
                    self.finish_active_job()
                    self.status_var.set(str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_worker_queue)

    def start_background_job(self, name: str) -> threading.Event | None:
        if self.active_job_cancel is not None:
            messagebox.showinfo("処理中", f"{self.active_job_name}が実行中です。完了または中止してから再実行してください。")
            return None
        cancel_event = threading.Event()
        self.active_job_cancel = cancel_event
        self.active_job_name = name
        self.cancel_job_button.configure(state="normal")
        self.search_button.configure(state="disabled")
        self.index_button.configure(state="disabled")
        self.blank_button.configure(state="disabled")
        return cancel_event

    def finish_active_job(self) -> None:
        self.active_job_cancel = None
        self.active_job_name = ""
        self.cancel_job_button.configure(state="disabled")
        self.search_button.configure(state="normal")
        self.index_button.configure(state="normal")
        self.blank_button.configure(state="normal")

    def cancel_active_job(self) -> None:
        if self.active_job_cancel is not None:
            self.active_job_cancel.set()
            self.status_var.set(f"{self.active_job_name}を中止しています")

    def prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self.page_jump_var.set(str(self.current_page))
            self.sync_page_list_selection()
            self.render_current_page_async()

    def next_page(self) -> None:
        if self.current_page < self.current_page_count:
            self.current_page += 1
            self.page_jump_var.set(str(self.current_page))
            self.sync_page_list_selection()
            self.render_current_page_async()

    def prev_pdf(self) -> None:
        self.move_pdf(-1)

    def next_pdf(self) -> None:
        self.move_pdf(1)

    def move_pdf(self, delta: int) -> None:
        if self.current_pdf is None or self.current_pdf not in self.pdf_paths:
            return
        index = self.pdf_paths.index(self.current_pdf) + delta
        if index < 0 or index >= len(self.pdf_paths):
            return
        self.set_current_pdf(self.pdf_paths[index])
        self.pdf_list.selection_clear(0, END)
        self.pdf_list.selection_set(index)
        self.pdf_list.see(index)
        self.status_var.set(f"PDFを移動しました: {self.current_pdf.name}")

    def go_to_page(self) -> None:
        if self.current_page_count <= 0:
            return
        try:
            page_no = int(self.page_jump_var.get())
        except ValueError:
            messagebox.showerror("ページ移動", "ページ番号は数値で入力してください。")
            return
        self.current_page = max(1, min(self.current_page_count, page_no))
        self.page_jump_var.set(str(self.current_page))
        self.sync_page_list_selection()
        self.render_current_page_async()

    def snapshot_segments_for_undo(self) -> None:
        if self._restoring_state:
            return
        copied = [segment.copy() for segment in self.segments]
        self.undo_stack.append(copied)
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_segments_snapshot(self, snapshot: list[Segment]) -> None:
        self.segments = [segment.copy() for segment in snapshot]
        self.refresh_page_list()
        self.refresh_segment_list()
        self.refresh_output_summary()
        self._update_workflow_status()

    def add_split_before_current_page(self) -> None:
        if self.current_pdf is None or self.current_page <= 1:
            return
        previous_end = max((segment.end_page for segment in self.segments if segment.pdf_path == self.current_pdf), default=0)
        start_page = previous_end + 1
        end_page = self.current_page - 1
        if start_page <= end_page:
            self.snapshot_segments_for_undo()
            metadata = self.active_preset.default_metadata()
            metadata["seq"] = str(len(self.segments) + 1)
            self.segments.append(Segment(self.current_pdf, start_page, end_page, metadata))
            self.refresh_page_list()
            self.refresh_segment_list()
            self._update_workflow_status()

    def undo_last_split(self) -> None:
        if not self.segments:
            return
        self.snapshot_segments_for_undo()
        self.segments.pop()
        self.refresh_page_list()
        self.refresh_segment_list()
        self._update_workflow_status()

    def delete_selected_split(self) -> None:
        selection = self.split_list.curselection()
        boundaries = sorted(self.split_boundary_pages())
        if not selection or not boundaries or selection[0] >= len(boundaries):
            return
        boundary = boundaries[selection[0]]
        delete_index = next((index for index, segment in enumerate(self.segments) if segment.end_page + 1 == boundary), None)
        if delete_index is None:
            return
        self.snapshot_segments_for_undo()
        self.segments.pop(delete_index)
        self.refresh_page_list()
        self.refresh_segment_list()
        self._update_workflow_status()

    def current_page_segment_index(self) -> int | None:
        if self.current_pdf is None:
            return None
        return next(
            (
                index
                for index, segment in enumerate(self.segments)
                if segment.pdf_path == self.current_pdf and self.current_page in segment.pages
            ),
            None,
        )

    def replace_segment(self, index: int, segment: Segment) -> None:
        self.segments[index] = segment
        self.refresh_page_list()
        self.refresh_segment_list()
        self.refresh_output_summary()
        self._update_workflow_status()

    def delete_current_page_from_segment(self) -> None:
        index = self.current_page_segment_index()
        if index is None:
            messagebox.showinfo("ページ整理", "現在ページを含む分割セグメントがありません。先に分割を作成してください。")
            return
        segment = self.segments[index]
        self.snapshot_segments_for_undo()
        if len(segment.pages) <= 1:
            self.segments.pop(index)
            self.refresh_page_list()
            self.refresh_segment_list()
            self.refresh_output_summary()
            self._update_workflow_status()
            return
        self.replace_segment(index, delete_segment_pages(segment, {self.current_page}))

    def rotate_current_page_in_segment(self) -> None:
        index = self.current_page_segment_index()
        if index is None:
            messagebox.showinfo("ページ整理", "現在ページを含む分割セグメントがありません。先に分割を作成してください。")
            return
        self.snapshot_segments_for_undo()
        self.replace_segment(index, rotate_segment_pages(self.segments[index], {self.current_page}, 90))
        self.render_current_page_async()

    def move_current_page_in_segment(self, offset: int) -> None:
        index = self.current_page_segment_index()
        if index is None:
            messagebox.showinfo("ページ整理", "現在ページを含む分割セグメントがありません。先に分割を作成してください。")
            return
        self.snapshot_segments_for_undo()
        self.replace_segment(index, move_segment_page(self.segments[index], self.current_page, offset))

    def extract_current_page_as_segment(self) -> None:
        if self.current_pdf is None:
            return
        source_index = self.current_page_segment_index()
        source = self.segments[source_index] if source_index is not None else Segment(self.current_pdf, self.current_page, self.current_page)
        self.snapshot_segments_for_undo()
        segment = extract_segment_pages(source, [self.current_page])
        segment.metadata.update(self.active_preset.default_metadata())
        segment.metadata["seq"] = str(len(self.segments) + 1)
        self.segments.append(segment)
        self.refresh_page_list()
        self.refresh_segment_list()
        self.refresh_output_summary()
        self._update_workflow_status()

    def undo_segments(self) -> None:
        if not self.undo_stack:
            return
        current = [segment.copy() for segment in self.segments]
        self.redo_stack.append(current)
        self.restore_segments_snapshot(self.undo_stack.pop())

    def redo_segments(self) -> None:
        if not self.redo_stack:
            return
        current = [segment.copy() for segment in self.segments]
        self.undo_stack.append(current)
        self.restore_segments_snapshot(self.redo_stack.pop())

    def split_by_n_pages(self, pages_per_segment: int) -> None:
        if self.current_pdf is None or self.current_page_count == 0:
            return
        self.snapshot_segments_for_undo()
        self.segments = self.processor.build_segments_by_n_pages(
            self.current_pdf,
            self.current_page_count,
            pages_per_segment,
        )
        for index, segment in enumerate(self.segments, start=1):
            segment.metadata.update(self.active_preset.default_metadata())
            segment.metadata["seq"] = str(index)
        self.refresh_page_list()
        self.refresh_segment_list()
        self._update_workflow_status()

    def open_current_pdf_folder(self) -> None:
        if self.current_pdf is None:
            messagebox.showinfo("参照元フォルダ", "PDFが選択されていません。")
            return
        self.open_folder(self.current_pdf.parent)

    def open_output_folder(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.open_folder(self.output_dir)

    def open_folder(self, path: Path) -> None:
        try:
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror("フォルダを開けません", str(exc))

    def rename_current_pdf_file(self) -> None:
        if self.current_pdf is None:
            return
        current = self.current_pdf
        new_name = simpledialog.askstring("ファイル名変更", "新しいPDFファイル名を入力してください。", initialvalue=current.name)
        if not new_name:
            return
        if not new_name.lower().endswith(".pdf"):
            new_name += ".pdf"
        safe_name, warnings = self.processor.sanitize_filename(new_name)
        target = current.with_name(safe_name)
        if target == current:
            return
        if target.exists():
            messagebox.showerror("ファイル名変更", "同名ファイルが既に存在します。")
            return
        if not messagebox.askyesno("ファイル名変更", "元PDFのファイル名だけを変更します。PDF本文は変更しません。よろしいですか。"):
            return
        try:
            current.rename(target)
        except Exception as exc:
            messagebox.showerror("ファイル名変更", str(exc))
            return
        self.remap_pdf_references(current, target)
        note = "（使用できない文字を置換しました）" if warnings else ""
        self.status_var.set(f"ファイル名を変更しました: {target.name}{note}")

    def remap_pdf_references(self, old_path: Path, new_path: Path) -> None:
        self.pdf_paths = [new_path if path == old_path else path for path in self.pdf_paths]
        for segment in self.segments:
            if segment.pdf_path == old_path:
                segment.pdf_path = new_path
        self.current_pdf = new_path if self.current_pdf == old_path else self.current_pdf
        self.search_hit_pages.clear()
        self.blank_candidate_pages.clear()
        self.index_candidate_pages.clear()
        self.processor.preview_cache.clear()
        self.processor.thumbnail_cache.clear()
        self.refresh_pdf_list()
        self.refresh_page_list()
        self.refresh_segment_list()
        self.render_current_page_async()

    def start_text_search(self) -> None:
        if self.current_pdf is None:
            return
        query = self.search_var.get().strip().lower()
        if not query:
            return
        cancel_event = self.start_background_job("検索")
        if cancel_event is None:
            return
        pdf_path = self.current_pdf

        def worker() -> None:
            try:
                if not self.processor.has_text_layer(pdf_path):
                    self.worker_queue.put(("ocr_prerequisite", "search"))
                    return
                hits = self.processor.search_text_pages(
                    pdf_path,
                    query,
                    progress=lambda current, total: self.worker_queue.put(("job_progress", ("検索", current, total))),
                    cancel=cancel_event.is_set,
                )
                self.worker_queue.put(("search_done", (hits, cancel_event.is_set())))
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def start_index_candidate_search(self) -> None:
        if self.current_pdf is None:
            return
        keywords = tuple(keyword.lower() for keyword in self.active_preset.extraction_keywords if keyword.strip())
        if not keywords:
            return
        cancel_event = self.start_background_job("インデックス検索")
        if cancel_event is None:
            return
        pdf_path = self.current_pdf

        def worker() -> None:
            try:
                if not self.processor.has_text_layer(pdf_path):
                    self.worker_queue.put(("ocr_prerequisite", "index"))
                    return
                hits = self.processor.index_candidate_pages(
                    pdf_path,
                    keywords,
                    progress=lambda current, total: self.worker_queue.put(("job_progress", ("インデックス検索", current, total))),
                    cancel=cancel_event.is_set,
                )
                self.worker_queue.put(("index_done", (hits, cancel_event.is_set())))
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def warm_thumbnail_window(self, center_page: int) -> None:
        if self.current_pdf is None:
            return
        pdf_path = self.current_pdf
        pages = range(max(1, center_page - 3), min(self.current_page_count, center_page + 3) + 1)

        def worker() -> None:
            for page_no in pages:
                try:
                    self.processor.render_thumbnail_pixmap(pdf_path, page_no)
                except Exception:
                    return

        threading.Thread(target=worker, daemon=True).start()

    def start_blank_scan(self) -> None:
        if self.current_pdf is None:
            return
        cancel_event = self.start_background_job("白紙検出")
        if cancel_event is None:
            return
        pdf_path = self.current_pdf
        threshold = self.active_preset.blank_threshold

        def worker() -> None:
            try:
                pages = self.processor.blank_pages(
                    pdf_path,
                    threshold,
                    progress=lambda current, total: self.worker_queue.put(("job_progress", ("白紙検出", current, total))),
                    cancel=cancel_event.is_set,
                )
                self.worker_queue.put(("blank_done", (pages, cancel_event.is_set())))
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def on_preset_selected(self, _event) -> None:
        selected_name = self.preset_var.get()
        for preset in self.presets:
            if preset.name == selected_name:
                self.set_active_preset(preset.id)
                return

    def refresh_ocr_transfer_fields(self) -> None:
        if not hasattr(self, "ocr_transfer_combo"):
            return
        values = [f"{field.label} ({field.key})" for field in self.active_preset.fields]
        self.ocr_transfer_combo["values"] = values
        if values and not self.ocr_transfer_field_var.get():
            priority = next((value for value in values if "(box_no)" in value), values[0])
            self.ocr_transfer_field_var.set(priority)

    def selected_ocr_text(self) -> str:
        try:
            return self.ocr_text.get("sel.first", "sel.last").strip()
        except Exception:
            return ""

    def selected_ocr_transfer_key(self) -> str | None:
        selected = self.ocr_transfer_field_var.get()
        if "(" in selected and selected.endswith(")"):
            return selected.rsplit("(", 1)[1][:-1]
        return self.active_preset.fields[0].key if self.active_preset.fields else None

    def transfer_selected_ocr_text(self) -> None:
        if self.current_pdf is not None and not self.current_pdf_has_text_layer:
            messagebox.showinfo("OCR転記", OCR_PREREQUISITE_MESSAGE)
            return
        text = self.selected_ocr_text()
        if not text:
            messagebox.showinfo("OCR転記", "OCR本文で転記したい文字を選択してください。")
            return
        if self.current_segment_index is None or not self.segments:
            messagebox.showinfo("OCR転記", "Step 3で転記先のセグメントを選択してください。")
            return
        key = self.selected_ocr_transfer_key()
        if key is None:
            messagebox.showinfo("OCR転記", "転記先の入力項目がありません。")
            return
        self.segments[self.current_segment_index].metadata[key] = text
        if key in self.metadata_vars:
            self.metadata_vars[key].set(text)
        self.refresh_segment_list()
        self.rebuild_metadata_fields()
        self.refresh_output_summary()
        self.status_var.set(f"OCR選択テキストを {key} へ転記しました")
        self._update_workflow_status()

    def refresh_segment_list(self) -> None:
        self.segment_list.delete(*self.segment_list.get_children())
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        ready = 0
        for index, check in enumerate(checks):
            status = "出力可能" if check.ok else "要入力"
            if check.ok:
                ready += 1
            filename = check.filename if check.ok else "未入力あり"
            metadata = check.segment.metadata
            self.segment_list.insert(
                "",
                END,
                iid=str(index),
                values=(
                    index + 1,
                    check.segment.page_label,
                    metadata.get("box_no", ""),
                    metadata.get("binder_no", ""),
                    metadata.get("seq", ""),
                    filename,
                    status,
                ),
                tags=("ready" if check.ok else "invalid",),
            )
        invalid = len(checks) - ready
        self.metadata_summary_var.set(f"セグメント: {len(checks)}件 / 出力可能: {ready}件 / 要入力: {invalid}件")
        if self.current_segment_index is not None and str(self.current_segment_index) in self.segment_list.get_children():
            self.segment_list.selection_set(str(self.current_segment_index))

    def on_segment_selected(self, _event) -> None:
        selection = self.segment_list.selection()
        self.current_segment_index = int(selection[0]) if selection else None
        self.rebuild_metadata_fields()

    def rebuild_metadata_fields(self) -> None:
        self.rebuild_common_fields()
        for child in self.metadata_frame.winfo_children():
            child.destroy()
        if self.current_segment_index is not None and self.current_segment_index >= len(self.segments):
            self.current_segment_index = None
        if self.current_segment_index is None and self.segments:
            self.current_segment_index = 0
            if "0" in self.segment_list.get_children():
                self.segment_list.selection_set("0")
        if self.current_segment_index is None or not self.segments:
            ttk.Label(self.metadata_frame, text="セグメントが選択されていません").pack()
            return
        segment = self.segments[self.current_segment_index]
        self.metadata_vars = {}
        for field in self.active_preset.fields:
            row = ttk.Frame(self.metadata_frame)
            row.pack(fill="x", pady=2)
            label = field.label + (" *" if field.required else "")
            ttk.Label(row, text=label, width=16).pack(side=LEFT)
            var = StringVar(value=segment.metadata.get(field.key, field.default))
            var.trace_add("write", lambda *_args, key=field.key, value=var: self.on_metadata_changed(key, value))
            self.metadata_vars[field.key] = var
            ttk.Entry(row, textvariable=var).pack(side=LEFT, fill="x", expand=True)
        self.filename_preview_var = StringVar()
        ttk.Label(self.metadata_frame, textvariable=self.filename_preview_var).pack(fill="x", pady=8)
        self.update_filename_preview()

    def rebuild_common_fields(self) -> None:
        for child in self.common_fields_frame.winfo_children():
            child.destroy()
        self.common_metadata_vars = {}
        editable_fields = [field for field in self.active_preset.fields if field.key != "seq"]
        for index, field in enumerate(editable_fields):
            row = ttk.Frame(self.common_fields_frame)
            row.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 12), pady=2)
            ttk.Label(row, text=field.label, width=16).pack(side=LEFT)
            var = StringVar(value=field.default)
            self.common_metadata_vars[field.key] = var
            ttk.Entry(row, textvariable=var, width=24).pack(side=LEFT)
        self.common_fields_frame.columnconfigure(0, weight=1)
        self.common_fields_frame.columnconfigure(1, weight=1)

    def apply_common_metadata_to_segments(self) -> None:
        if not self.segments:
            messagebox.showinfo("一括入力", "反映するセグメントがありません。")
            return
        values = {key: value.get() for key, value in self.common_metadata_vars.items() if value.get().strip()}
        apply_common_metadata(self.segments, values)
        self.refresh_segment_list()
        self.rebuild_metadata_fields()
        self.refresh_output_summary()
        self._update_workflow_status()

    def copy_previous_segment_metadata(self) -> None:
        if self.current_segment_index is None or self.current_segment_index <= 0:
            messagebox.showinfo("前行コピー", "コピー元となる前行がありません。")
            return
        previous = self.segments[self.current_segment_index - 1]
        current = self.segments[self.current_segment_index]
        for key, value in previous.metadata.items():
            if key != "seq":
                current.metadata[key] = value
        self.refresh_segment_list()
        self.rebuild_metadata_fields()
        self.refresh_output_summary()
        self._update_workflow_status()

    def select_next_invalid_segment(self) -> None:
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        if not checks:
            messagebox.showinfo("未入力ナビ", "確認するセグメントがありません。")
            return
        start = 0 if self.current_segment_index is None else self.current_segment_index + 1
        order = list(range(start, len(checks))) + list(range(0, start))
        for index in order:
            if not checks[index].ok:
                self.current_segment_index = index
                self.segment_list.selection_set(str(index))
                self.segment_list.see(str(index))
                self.rebuild_metadata_fields()
                return
        messagebox.showinfo("未入力ナビ", "要修正のセグメントはありません。")

    def refresh_metadata_suggestions(self) -> None:
        self.suggestion_list.delete(0, END)
        text = self.ocr_text.get("1.0", END).strip()
        if not text:
            self.step3_suggestion_var.set("入力補助候補: OCR本文がありません。")
            return
        candidates = metadata_suggestions_from_text(text)
        for candidate in candidates:
            self.suggestion_list.insert(END, candidate)
        if candidates:
            self.suggestion_list.selection_set(0)
            self.step3_suggestion_var.set("入力補助候補: 候補を選択してコピーできます。")
        else:
            self.step3_suggestion_var.set("入力補助候補: 候補なし")

    def copy_selected_metadata_suggestion(self) -> None:
        selection = self.suggestion_list.curselection()
        if not selection:
            messagebox.showinfo("入力補助候補", "コピーする候補を選択してください。")
            return
        candidate = self.suggestion_list.get(selection[0])
        self.root.clipboard_clear()
        self.root.clipboard_append(candidate)
        self.step3_suggestion_var.set(f"入力補助候補をコピーしました: {candidate}")

    def resequence_segment_metadata(self) -> None:
        if not self.segments:
            messagebox.showinfo("連番再採番", "再採番するセグメントがありません。")
            return
        try:
            start = int(self.seq_start_var.get())
            step = int(self.seq_step_var.get())
        except ValueError:
            messagebox.showerror("連番再採番", "連番開始と増分は数値で入力してください。")
            return
        resequence_segments(self.segments, start=start, step=step)
        self.refresh_segment_list()
        self.rebuild_metadata_fields()
        self.refresh_output_summary()
        self._update_workflow_status()

    def on_metadata_changed(self, key: str, value: StringVar) -> None:
        if self.current_segment_index is None:
            return
        self.segments[self.current_segment_index].metadata[key] = value.get()
        self.update_filename_preview()
        self.refresh_segment_list()
        self._update_workflow_status()

    def update_filename_preview(self) -> None:
        if self.current_segment_index is None:
            return
        segment = self.segments[self.current_segment_index]
        result = self.processor.build_filename_templated(self.active_preset, segment.metadata)
        if result.ok:
            self.filename_preview_var.set(f"出力名: {result.normalized_filename}")
        else:
            self.filename_preview_var.set("要修正: " + " / ".join(error_messages(self.active_preset, result.errors)))

    def refresh_output_summary(self) -> None:
        self.output_text.delete("1.0", END)
        self.output_tree.delete(*self.output_tree.get_children())
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        view = build_output_preflight_view(checks, self.output_dir)
        warning_count = sum(1 for check in checks if check.ok and (check.has_existing_output or check.action in {OUTPUT_ACTION_REUSE_EXISTING, OUTPUT_ACTION_SKIP}))
        for index, check in enumerate(checks):
            if check.ok:
                if check.action == OUTPUT_ACTION_SKIP:
                    tag = "warn"
                    status = "スキップ"
                elif check.action == OUTPUT_ACTION_REUSE_EXISTING:
                    tag = "warn"
                    status = "再利用"
                else:
                    tag = "ready"
                    status = "出力可能"
            else:
                tag = "invalid"
                status = "要修正"
            existing = str(check.existing_path) if check.has_existing_output and check.existing_path else "なし"
            self.output_tree.insert(
                "",
                END,
                iid=str(index),
                values=(
                    index + 1,
                    check.segment.page_label,
                    check.filename or check.requested_filename,
                    existing,
                    check.action_label,
                    status,
                ),
                tags=(tag,),
            )
        self.output_check_summary_var.set(view.summary_text)
        if not checks:
            self.output_instruction_var.set("要確認: 出力対象がありません。Step 1でPDFを選択し、Step 2で分割を作成してください。")
        elif view.invalid_count:
            self.output_instruction_var.set(f"要修正: {view.invalid_count}件あります。Step 3で入力内容と出力名を確認してください。")
        elif warning_count:
            self.output_instruction_var.set(f"警告: {warning_count}件の既存ファイル処理があります。処理方針を確認してから出力してください。")
        else:
            self.output_instruction_var.set(f"OK: {view.ready_count}件を出力できます。保存先を確認してから出力実行してください。")
        for line in view.lines:
            self.output_text.insert(END, line.text, line.tag)
        self.run_output_button.configure(state="normal" if view.can_run else "disabled")
        self.output_status_var.set(view.status_text)
        self._update_workflow_status()

    def refresh_history_view(self) -> None:
        if not hasattr(self, "history_text"):
            return
        self.history_text.delete("1.0", END)
        try:
            runs = self.output_history.load()
        except Exception as exc:
            self.history_summary_var.set(f"履歴読込失敗: {exc}")
            return
        self.history_summary_var.set(f"履歴: {len(runs)}件 / 保存先: {self.output_history.history_path}")
        if not runs:
            self.history_text.insert(END, "まだ出力履歴はありません。\n", "warn")
            return
        for run in reversed(runs[-50:]):
            summary = run.get("summary", {})
            self.history_text.insert(
                END,
                f"{run.get('created_at', '')}  成功 {summary.get('success', 0)} / 再利用 {summary.get('reused', 0)} / "
                f"スキップ {summary.get('skipped', 0)} / 失敗 {summary.get('failed', 0)}\n",
                "heading",
            )
            for item in run.get("items", []):
                status = str(item.get("status", ""))
                tag = "ok" if status in {"created", "reused"} else ("warn" if status == "skipped" else "error")
                self.history_text.insert(
                    END,
                    f"  [{status}] {item.get('pages', '')} {item.get('requested_filename', '')} -> {item.get('output_path', '')}\n",
                    tag,
                )
            self.history_text.insert(END, "\n")

    def selected_output_check(self):
        selection = self.output_tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        return checks[index] if index < len(checks) else None

    def on_output_check_selected(self, _event) -> None:
        check = self.selected_output_check()
        if check is None:
            return
        self.output_action_var.set(check.action_label)

    def apply_selected_output_action(self) -> None:
        selection = self.output_tree.selection()
        check = self.selected_output_check()
        if check is None:
            messagebox.showinfo("処理方針", "処理方針を変更する出力行を選択してください。")
            return
        if not check.action_key:
            messagebox.showinfo("処理方針", "未入力または命名エラーのある行は、先にStep 3で修正してください。")
            return
        selected_label = self.output_action_var.get()
        action = next((key for key, label in OUTPUT_ACTION_LABELS.items() if label == selected_label), OUTPUT_ACTION_CREATE_UNIQUE)
        self.output_action_overrides[check.action_key] = action
        self.refresh_output_summary()
        if selection and self.output_tree.exists(selection[0]):
            self.output_tree.selection_set(selection[0])
        self.state_status_var.set("出力処理方針を変更しました。必要に応じて状態を保存してください。")

    def run_output(self) -> None:
        checks = check_segment_outputs(
            self.segments,
            self.active_preset,
            self.output_dir,
            self.processor,
            self.output_action_overrides,
        )
        invalid = [check for check in checks if not check.ok]
        if invalid:
            messagebox.showerror("出力できません", "未入力または命名エラーのあるセグメントを修正してください。")
            self.refresh_output_summary()
            return
        self.run_output_button.configure(state="disabled")
        self.output_text.insert(END, "\n一括出力ログ\n", "heading")
        success = 0
        reused = 0
        skipped = 0
        failed = 0
        history_items: list[dict[str, object]] = []
        for index, check in enumerate(checks, start=1):
            self.output_progress_var.set(f"出力中: {index}/{len(checks)} {check.filename}")
            self.output_status_var.set("一括実行中")
            self.root.update_idletasks()
            item = {
                **segment_page_plan(check.segment),
                "metadata": dict(check.segment.metadata),
                "requested_filename": check.requested_filename,
                "action": check.action,
                "warnings": list(check.messages),
            }
            if check.action == OUTPUT_ACTION_SKIP:
                skipped += 1
                self.output_text.insert(END, f"スキップ: {check.segment.page_label} {check.filename}\n", "warn")
                history_items.append({**item, "status": "skipped", "output_path": ""})
                continue
            if check.action == OUTPUT_ACTION_REUSE_EXISTING:
                if check.output_path is None:
                    failed += 1
                    self.output_text.insert(END, f"再利用失敗: {check.filename} 既存ファイルがありません\n", "error")
                    history_items.append({**item, "status": "failed", "output_path": "", "error": "existing file missing"})
                    continue
                digest = self.processor.calculate_sha256(check.output_path)
                reused += 1
                self.output_text.insert(END, f"再利用: {check.output_path} sha256={digest}\n", "warn")
                history_items.append({**item, "status": "reused", "output_path": str(check.output_path), "sha256": digest})
                continue
            if check.output_path is None:
                failed += 1
                self.output_text.insert(END, f"スキップ: {check.segment.page_label}\n", "warn")
                history_items.append({**item, "status": "failed", "output_path": "", "error": "missing output path"})
                continue
            try:
                final_path = self.processor.split_pdf(check.segment, check.output_path)
                digest = self.processor.calculate_sha256(final_path)
                success += 1
                self.output_text.insert(END, f"成功: {final_path} sha256={digest}\n", "ok")
                history_items.append({**item, "status": "created", "output_path": str(final_path), "sha256": digest})
            except Exception as exc:
                failed += 1
                self.output_text.insert(END, f"出力失敗: {check.filename} {exc}\n", "error")
                history_items.append({**item, "status": "failed", "output_path": str(check.output_path), "error": str(exc)})
        self.output_progress_var.set(f"処理終了: 成功 {success}件 / 再利用 {reused}件 / スキップ {skipped}件 / 失敗 {failed}件")
        self.output_status_var.set("出力完了" if failed == 0 else "エラー終了")
        self.output_check_summary_var.set(
            f"出力完了: 成功 {success}件 / 再利用 {reused}件 / スキップ {skipped}件 / 失敗 {failed}件 / 保存先: {self.output_dir}"
        )
        self.output_instruction_var.set(
            "OK: 出力が完了しました。出力フォルダを確認してください。"
            if failed == 0
            else f"要確認: 出力失敗が {failed}件あります。ログを確認してください。"
        )
        try:
            self.output_history.append_run(
                summary={"success": success, "reused": reused, "skipped": skipped, "failed": failed, "output_dir": str(self.output_dir)},
                items=history_items,
            )
            self.refresh_history_view()
        except Exception as exc:
            self.output_text.insert(END, f"履歴保存失敗: {exc}\n", "error")
        self.run_output_button.configure(state="normal" if failed == 0 else "disabled")
        self._update_workflow_status()


def default_work_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main(work_dir: Path | None = None) -> None:
    root = Tk()
    root.geometry("1200x820")
    PdfSplitterApp(root, work_dir or default_work_dir())
    root.mainloop()
