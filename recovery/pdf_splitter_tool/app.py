from __future__ import annotations

import queue
import os
import sys
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, BooleanVar, Canvas, DoubleVar, Listbox, StringVar, Text, Tk, Toplevel, filedialog, messagebox, simpledialog
from tkinter import ttk

from .app_metadata import APP_NAME
from .models import Preset, Segment
from .preset_editing import build_preset_from_editor, format_keywords
from .presets import DEFAULT_PRESET_IDS, PresetRepository, find_preset
from .processor import OCR_PREREQUISITE_MESSAGE, PdfProcessor
from .state import StateManager
from .workflow import apply_common_metadata, check_segment_outputs, error_messages, resequence_segments


TEXT_WIDGET_CLASSES = {"Entry", "TEntry", "Text", "Spinbox", "TCombobox"}

UI_BG = "#f5f7fb"
UI_SURFACE = "#ffffff"
UI_SURFACE_MUTED = "#f8fafc"
UI_BORDER = "#d7dee8"
UI_TEXT = "#172033"
UI_MUTED_TEXT = "#5b667a"
UI_PRIMARY = "#2563eb"
UI_PRIMARY_HOVER = "#1d4ed8"
UI_READY = "#0f766e"
UI_WARNING = "#b45309"
UI_DANGER = "#b42318"
UI_PREVIEW_BG = "#111827"


class PdfSplitterApp:
    def __init__(self, root: Tk, work_dir: Path | None = None) -> None:
        self.root = root
        self.work_dir = work_dir or Path.cwd()
        self.root.title(APP_NAME)
        self.processor = PdfProcessor()
        self.state_manager = StateManager(self.work_dir)
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
        self.footer_status_var = StringVar()
        self.step_status_vars: list[StringVar] = []
        self.page_list_page_numbers: list[int] = []
        self.candidate_list_page_numbers: list[int] = []
        self.search_hit_pages: set[int] = set()
        self.blank_candidate_pages: set[int] = set()
        self.index_candidate_pages: set[int] = set()
        self.show_candidates_only_var = BooleanVar(value=False)
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
        self.state_status_var = StringVar(value="状態未保存")
        self.current_pdf_has_text_layer = False

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
        for label in ("PDF選択", "分割", "入力", "出力"):
            var = StringVar(value=f"{label}: 未完了")
            self.step_status_vars.append(var)
            ttk.Label(tracker, textvariable=var, style="StepStatus.TLabel", padding=(8, 4)).pack(side=LEFT, padx=(0, 6))

        self.notebook = ttk.Notebook(shell)
        self.notebook.pack(fill=BOTH, expand=True)

        self.step1 = ttk.Frame(self.notebook, padding=8)
        self.step2 = ttk.Frame(self.notebook, padding=8)
        self.step3 = ttk.Frame(self.notebook, padding=8)
        self.step4 = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.step1, text="1 PDF選択")
        self.notebook.add(self.step2, text="2 分割")
        self.notebook.add(self.step3, text="3 入力")
        self.notebook.add(self.step4, text="4 出力")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Label(footer, textvariable=self.footer_status_var, style="Footer.TLabel").pack(side=LEFT)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.root.configure(background=UI_BG)
        style.configure(".", background=UI_BG, foreground=UI_TEXT, font=("", 9))
        style.configure("TFrame", background=UI_BG)
        style.configure("TLabel", background=UI_BG, foreground=UI_TEXT)
        style.configure("AppTitle.TLabel", font=("", 17, "bold"), foreground=UI_TEXT)
        style.configure("AppSummary.TLabel", foreground=UI_MUTED_TEXT)
        style.configure("StepStatus.TLabel", background="#e9f1ff", foreground="#1e3a8a", relief="flat")
        style.configure("SectionTitle.TLabel", font=("", 12, "bold"), foreground=UI_TEXT)
        style.configure("Hint.TLabel", foreground=UI_MUTED_TEXT)
        style.configure("Footer.TLabel", foreground=UI_MUTED_TEXT)
        style.configure("TNotebook", background=UI_BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 7), background="#e8edf5", foreground=UI_MUTED_TEXT)
        style.map(
            "TNotebook.Tab",
            background=[("selected", UI_SURFACE), ("active", "#f1f5f9")],
            foreground=[("selected", UI_PRIMARY), ("active", UI_TEXT)],
        )
        style.configure("TButton", padding=(10, 6), background=UI_SURFACE_MUTED, bordercolor=UI_BORDER, focusthickness=1)
        style.map("TButton", background=[("active", "#e8eef8")])
        style.configure(
            "Primary.TButton",
            font=("", 9, "bold"),
            foreground="#ffffff",
            background=UI_PRIMARY,
            bordercolor=UI_PRIMARY,
        )
        style.map(
            "Primary.TButton",
            foreground=[("disabled", "#dbeafe"), ("active", "#ffffff")],
            background=[("disabled", "#93c5fd"), ("active", UI_PRIMARY_HOVER)],
        )
        style.configure("TEntry", fieldbackground=UI_SURFACE, bordercolor=UI_BORDER, lightcolor=UI_BORDER, darkcolor=UI_BORDER)
        style.configure("TCombobox", fieldbackground=UI_SURFACE, bordercolor=UI_BORDER)
        style.configure("TLabelframe", background=UI_SURFACE, bordercolor=UI_BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=UI_SURFACE, foreground=UI_TEXT, font=("", 10, "bold"))
        style.configure("Treeview", background=UI_SURFACE, fieldbackground=UI_SURFACE, foreground=UI_TEXT, rowheight=24, bordercolor=UI_BORDER)
        style.configure("Treeview.Heading", background="#eef2f7", foreground=UI_TEXT, font=("", 9, "bold"))
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", UI_TEXT)])

    def _style_listbox(self, listbox: Listbox) -> None:
        listbox.configure(
            background=UI_SURFACE,
            foreground=UI_TEXT,
            selectbackground="#dbeafe",
            selectforeground=UI_TEXT,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_PRIMARY,
            borderwidth=0,
            relief="flat",
            activestyle="none",
        )

    def _style_text(self, text: Text) -> None:
        text.configure(
            background=UI_SURFACE,
            foreground=UI_TEXT,
            insertbackground=UI_TEXT,
            selectbackground="#dbeafe",
            selectforeground=UI_TEXT,
            highlightthickness=1,
            highlightbackground=UI_BORDER,
            highlightcolor=UI_PRIMARY,
            borderwidth=0,
            relief="flat",
        )

    def _add_section_header(self, parent: ttk.Frame, title: str, hint: str) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text=title, style="SectionTitle.TLabel").pack(anchor="w")
        ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=920).pack(anchor="w", pady=(2, 0))

    def _update_workflow_status(self) -> None:
        checks = check_segment_outputs(self.segments, self.active_preset, self.output_dir, self.processor)
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

        statuses = (
            f"PDF選択: {pdf_status}",
            f"分割: {split_status}",
            f"入力: {input_status}",
            f"出力: {output_status}",
        )
        for var, text in zip(self.step_status_vars, statuses):
            var.set(text)

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
            "segments": [
                {
                    "pdf_path": str(segment.pdf_path),
                    "start_page": segment.start_page,
                    "end_page": segment.end_page,
                    "metadata": dict(segment.metadata),
                }
                for segment in self.segments
            ],
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
            self.segments = []
            valid_paths = set(self.pdf_paths)
            for item in state.get("segments", []):
                if not isinstance(item, dict):
                    continue
                pdf_path = Path(str(item.get("pdf_path", "")))
                if pdf_path not in valid_paths:
                    continue
                self.segments.append(
                    Segment(
                        pdf_path,
                        int(item.get("start_page", 1)),
                        int(item.get("end_page", 1)),
                        dict(item.get("metadata", {})),
                    )
                )
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
            "PDFを選択",
            "処理したいPDFを追加し、案件プリセットと出力先を確認します。ここで選んだPDFが以降の分割作業の対象になります。",
        )
        toolbar = ttk.Frame(self.step1)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="PDFを個別に選択", command=self.select_pdfs, style="Primary.TButton").pack(side=LEFT)
        ttk.Button(toolbar, text="入力フォルダを選択", command=self.select_folder).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="置換読込(PDF)", command=self.replace_with_pdfs).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="置換読込(フォルダ)", command=self.replace_with_folder).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="出力フォルダ", command=self.select_output_dir).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="プリセット管理", command=self.open_preset_manager).pack(side=LEFT, padx=4)

        self.preset_var = StringVar(value=self.active_preset.name)
        self.preset_combo = ttk.Combobox(
            toolbar,
            textvariable=self.preset_var,
            values=[preset.name for preset in self.presets],
            state="readonly",
            width=28,
        )
        self.preset_combo.pack(side=RIGHT)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)

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
        ttk.Checkbutton(common_buttons, text="ファイル名で自動ソート", variable=self.auto_sort_var).pack(side=LEFT, padx=8)
        ttk.Label(common_buttons, textvariable=self.load_status_var, style="Hint.TLabel").pack(side=LEFT, padx=8)
        self.cancel_load_button = ttk.Button(common_buttons, text="中断", command=self.cancel_pdf_loading, state="disabled")
        self.cancel_load_button.pack(side=RIGHT)
        self.rebuild_step1_common_fields()

        ttk.Label(self.step1, text="PDF一覧 - ファイル名、ページ数、保存場所を確認できます。", style="Hint.TLabel").pack(
            anchor="w",
            pady=(8, 0),
        )
        self.pdf_list = Listbox(self.step1, height=12)
        self._style_listbox(self.pdf_list)
        self.pdf_list.pack(fill=BOTH, expand=True, pady=8)
        self.pdf_list.bind("<<ListboxSelect>>", self.on_pdf_selected)
        pdf_buttons = ttk.Frame(self.step1)
        pdf_buttons.pack(fill="x")
        ttk.Button(pdf_buttons, text="選択解除", command=self.remove_selected_pdf).pack(side=LEFT)
        ttk.Button(pdf_buttons, text="全クリア", command=self.clear_pdf_selection).pack(side=LEFT, padx=4)
        ttk.Button(pdf_buttons, text="状態を保存", command=self.save_state).pack(side=RIGHT)
        ttk.Label(pdf_buttons, textvariable=self.state_status_var, style="Hint.TLabel").pack(side=RIGHT, padx=8)

    def open_preset_manager(self) -> None:
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
            "分割位置を決める",
            "左右キーでページ移動、Spaceで現在ページの前に分割を追加します。検索欄やOCR欄の入力中はショートカットを無効化します。",
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

        tools = ttk.LabelFrame(decision, text="候補検出", padding=8)
        tools.pack(fill="x", pady=(8, 0))
        self.search_var = StringVar()
        self.search_entry = ttk.Entry(tools, textvariable=self.search_var, width=28)
        self.search_entry.pack(fill="x")
        tool_buttons = ttk.Frame(tools)
        tool_buttons.pack(fill="x", pady=(6, 0))
        self.search_button = ttk.Button(tool_buttons, text="検索", command=self.start_text_search)
        self.search_button.pack(side=LEFT)
        self.index_button = ttk.Button(tool_buttons, text="インデックス", command=self.start_index_candidate_search)
        self.index_button.pack(side=LEFT, padx=4)
        self.blank_button = ttk.Button(tool_buttons, text="白紙検出", command=self.start_blank_scan)
        self.blank_button.pack(side=LEFT)
        self.cancel_job_button = ttk.Button(tools, text="処理中止", command=self.cancel_active_job, state="disabled")
        self.cancel_job_button.pack(fill="x", pady=(6, 0))

        decision_tabs = ttk.Notebook(decision)
        decision_tabs.pack(fill=BOTH, expand=True, pady=(8, 0))

        split_tab = ttk.Frame(decision_tabs, padding=6)
        decision_tabs.add(split_tab, text="分割位置")
        ttk.Label(split_tab, textvariable=self.split_summary_var).pack(anchor="w")
        self.split_list = Listbox(split_tab, width=36, height=8)
        self._style_listbox(self.split_list)
        self.split_list.pack(fill=BOTH, expand=True, pady=(4, 6))
        ttk.Button(split_tab, text="現在ページの前に分割", command=self.add_split_before_current_page).pack(fill="x")
        ttk.Button(split_tab, text="選択した分割を削除", command=self.delete_selected_split).pack(fill="x", pady=(4, 0))
        ttk.Button(split_tab, text="最後の分割を取り消す", command=self.undo_last_split).pack(fill="x", pady=(4, 0))
        undo_row = ttk.Frame(split_tab)
        undo_row.pack(fill="x", pady=(4, 0))
        ttk.Button(undo_row, text="Undo", command=self.undo_segments).pack(side=LEFT, fill="x", expand=True)
        ttk.Button(undo_row, text="Redo", command=self.redo_segments).pack(side=LEFT, fill="x", expand=True, padx=(4, 0))
        ttk.Button(split_tab, text="1ページごとに分割", command=lambda: self.split_by_n_pages(1)).pack(fill="x", pady=(4, 0))
        ttk.Button(split_tab, text="参照元フォルダを開く", command=self.open_current_pdf_folder).pack(fill="x", pady=(4, 0))
        ttk.Button(split_tab, text="このファイルを改名", command=self.rename_current_pdf_file).pack(fill="x", pady=(4, 0))

        candidate_tab = ttk.Frame(decision_tabs, padding=6)
        decision_tabs.add(candidate_tab, text="候補")
        ttk.Label(candidate_tab, textvariable=self.candidate_summary_var).pack(anchor="w")
        self.candidate_list = Listbox(candidate_tab, width=36, height=8)
        self._style_listbox(self.candidate_list)
        self.candidate_list.pack(fill=BOTH, expand=True, pady=(4, 6))
        self.candidate_list.bind("<<ListboxSelect>>", self.on_candidate_selected)
        ttk.Button(candidate_tab, text="候補ページの前に分割", command=self.add_split_before_current_page).pack(fill="x")

        ocr_tab = ttk.Frame(decision_tabs, padding=6)
        decision_tabs.add(ocr_tab, text="OCR本文")
        self.ocr_text = Text(ocr_tab, height=12, wrap="word")
        self._style_text(self.ocr_text)
        self.ocr_text.pack(fill=BOTH, expand=True)
        transfer = ttk.Frame(ocr_tab)
        transfer.pack(fill="x", pady=(6, 0))
        self.ocr_transfer_combo = ttk.Combobox(transfer, textvariable=self.ocr_transfer_field_var, state="readonly", width=18)
        self.ocr_transfer_combo.pack(side=LEFT)
        ttk.Button(transfer, text="選択OCRを転記", command=self.transfer_selected_ocr_text).pack(side=LEFT, padx=4)
        self.refresh_ocr_transfer_fields()

    def _build_step3(self) -> None:
        self._add_section_header(
            self.step3,
            "出力名に使う情報を入力",
            "共通値をまとめて反映し、連番を再採番してから、各セグメントの出力名と要修正状態を確認します。",
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
        assist_row = ttk.Frame(self.bulk_frame)
        assist_row.pack(fill="x", pady=(6, 0))
        ttk.Button(assist_row, text="前行メタデータコピー", command=self.copy_previous_segment_metadata).pack(side=LEFT)
        ttk.Button(assist_row, text="次の要修正へ移動", command=self.select_next_invalid_segment).pack(side=LEFT, padx=4)
        ttk.Button(assist_row, text="入力補助候補を更新", command=self.refresh_metadata_suggestions).pack(side=LEFT)
        ttk.Button(assist_row, text="出力予定フォルダを開く", command=self.open_output_folder).pack(side=LEFT, padx=4)
        ttk.Label(self.bulk_frame, textvariable=self.step3_suggestion_var, style="Hint.TLabel", wraplength=560).pack(anchor="w", pady=(6, 0))

        self.metadata_frame = ttk.LabelFrame(right, text="選択セグメント", padding=8)
        self.metadata_frame.pack(fill=BOTH, expand=True, pady=(8, 0))
        self.filename_preview_var = StringVar()
        ttk.Label(self.metadata_frame, textvariable=self.filename_preview_var).pack(fill="x", pady=8)

    def _build_step4(self) -> None:
        self._add_section_header(
            self.step4,
            "出力前に確認",
            "出力先、予定ファイル名、未入力や命名エラーを確認します。要修正が残っている場合は出力できません。",
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
        self.output_text = Text(self.step4, height=24)
        self._style_text(self.output_text)
        self.output_text.pack(fill=BOTH, expand=True, pady=8)
        self.output_text.tag_configure("ok", foreground=UI_READY)
        self.output_text.tag_configure("warn", foreground=UI_WARNING)
        self.output_text.tag_configure("error", foreground=UI_DANGER)
        self.output_text.tag_configure("heading", foreground=UI_TEXT, font=("", 10, "bold"))

    def _bind_keys(self) -> None:
        self.root.bind_all("<space>", self.on_space_key)
        self.root.bind_all("<Left>", self.on_left_key)
        self.root.bind_all("<Right>", self.on_right_key)
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
        if self.show_candidates_only_var.get():
            pages = [page_no for page_no in range(1, self.current_page_count + 1) if page_no in candidate_pages]
        else:
            pages = list(range(1, self.current_page_count + 1))
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
        boundaries: set[int] = set()
        for segment in self.segments:
            boundary_page = segment.end_page + 1
            if 1 < boundary_page <= self.current_page_count:
                boundaries.add(boundary_page)
        return boundaries

    def candidate_pages(self) -> set[int]:
        return self.search_hit_pages | self.blank_candidate_pages | self.index_candidate_pages

    def page_badges(self, page_no: int) -> list[str]:
        badges = []
        if page_no in self.blank_candidate_pages:
            badges.append("白紙")
        if page_no in self.search_hit_pages:
            badges.append("検索")
        if page_no in self.index_candidate_pages:
            badges.append("索引")
        if page_no in self.split_boundary_pages():
            badges.append("分割前")
        return badges

    def page_list_label(self, page_no: int) -> str:
        badges = self.page_badges(page_no)
        suffix = f" [{' '.join(badges)}]" if badges else ""
        return f"{page_no:>4}ページ{suffix}"

    def segment_for_page(self, page_no: int) -> Segment | None:
        for segment in self.segments:
            if segment.start_page <= page_no <= segment.end_page:
                return segment
        return None

    def refresh_step2_sidebars(self) -> None:
        if not hasattr(self, "split_list"):
            return
        self.current_page_var.set(f"現在 {self.current_page} / {self.current_page_count or '-'} ページ")
        badges = self.page_badges(self.current_page)
        state = " / ".join(badges) if badges else "通常ページ"
        if self.current_pdf is not None and not self.current_pdf_has_text_layer:
            state += " / OCR検索には事前OCR済みPDFが必要"
        if self.search_var.get().strip() and self.current_page in self.search_hit_pages:
            try:
                hit_count = len(self.processor.search_text_rects(self.current_pdf, self.current_page, self.search_var.get())) if self.current_pdf else 0
                state += f" / ページ内ヒット {hit_count}件"
            except Exception:
                state += " / ページ内ヒット確認不可"
        if self.current_page <= 1:
            state += " / 先頭ページのため前分割不可"
        self.current_page_state_var.set(state)
        segment = self.segment_for_page(self.current_page)
        if segment is None:
            start = max((item.end_page for item in self.segments), default=0) + 1
            if self.current_page_count:
                self.current_segment_var.set(f"未確定範囲: {start}-{self.current_page_count}ページ")
            else:
                self.current_segment_var.set("PDF未選択")
        else:
            self.current_segment_var.set(f"所属セグメント: {segment.start_page}-{segment.end_page}ページ")

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
        copied = [Segment(segment.pdf_path, segment.start_page, segment.end_page, dict(segment.metadata)) for segment in self.segments]
        self.undo_stack.append(copied)
        if len(self.undo_stack) > 40:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def restore_segments_snapshot(self, snapshot: list[Segment]) -> None:
        self.segments = [Segment(segment.pdf_path, segment.start_page, segment.end_page, dict(segment.metadata)) for segment in snapshot]
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

    def undo_segments(self) -> None:
        if not self.undo_stack:
            return
        current = [Segment(segment.pdf_path, segment.start_page, segment.end_page, dict(segment.metadata)) for segment in self.segments]
        self.redo_stack.append(current)
        self.restore_segments_snapshot(self.undo_stack.pop())

    def redo_segments(self) -> None:
        if not self.redo_stack:
            return
        current = [Segment(segment.pdf_path, segment.start_page, segment.end_page, dict(segment.metadata)) for segment in self.segments]
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
        if not self.current_pdf_has_text_layer:
            self.search_hit_pages.clear()
            self.refresh_page_list()
            self.status_var.set(OCR_PREREQUISITE_MESSAGE)
            self.ocr_text.delete("1.0", END)
            self.ocr_text.insert("1.0", OCR_PREREQUISITE_MESSAGE)
            return
        cancel_event = self.start_background_job("検索")
        if cancel_event is None:
            return
        pdf_path = self.current_pdf

        def worker() -> None:
            try:
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
        if not self.current_pdf_has_text_layer:
            self.index_candidate_pages.clear()
            self.refresh_page_list()
            self.status_var.set(OCR_PREREQUISITE_MESSAGE)
            self.ocr_text.delete("1.0", END)
            self.ocr_text.insert("1.0", OCR_PREREQUISITE_MESSAGE)
            return
        cancel_event = self.start_background_job("インデックス検索")
        if cancel_event is None:
            return
        pdf_path = self.current_pdf

        def worker() -> None:
            try:
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
        checks = check_segment_outputs(self.segments, self.active_preset, self.output_dir, self.processor)
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
                    f"{check.segment.start_page}-{check.segment.end_page}",
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
        checks = check_segment_outputs(self.segments, self.active_preset, self.output_dir, self.processor)
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
        text = self.ocr_text.get("1.0", END).strip()
        if not text:
            self.step3_suggestion_var.set("入力補助候補: OCR本文がありません。")
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        candidates = lines[:5]
        self.step3_suggestion_var.set("入力補助候補: " + (" / ".join(candidates) if candidates else "候補なし"))

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
        checks = check_segment_outputs(self.segments, self.active_preset, self.output_dir, self.processor)
        ready = sum(1 for check in checks if check.ok)
        invalid = len(checks) - ready
        self.output_check_summary_var.set(f"出力予定: {ready}件 / 要修正: {invalid}件 / 保存先: {self.output_dir}")
        self.output_text.insert(END, "出力前チェックリスト\n", "heading")
        self.output_text.insert(END, f"[OK] 出力先: {self.output_dir}\n", "ok")
        if checks:
            self.output_text.insert(END, f"[OK] 出力対象: {len(checks)}件\n", "ok")
        else:
            self.output_text.insert(END, "[NG] 出力対象がありません。Step 2で分割を作成してください。\n", "error")
        if invalid:
            self.output_text.insert(END, f"[NG] 要修正: {invalid}件。Step 3で未入力や命名エラーを修正してください。\n", "error")
        else:
            self.output_text.insert(END, "[OK] 未入力・命名エラーなし\n", "ok" if checks else "warn")
        self.output_text.insert(END, "[OK] 同名ファイルがある場合は _2, _3 の連番で重複を回避します。\n\n", "ok")
        self.output_text.insert(END, "出力予定一覧\n", "heading")
        for check in checks:
            if check.ok:
                self.output_text.insert(END, f"[出力可能] {check.segment.start_page}-{check.segment.end_page} -> {check.filename}\n", "ok")
            else:
                self.output_text.insert(
                    END,
                    f"[要修正] {check.segment.start_page}-{check.segment.end_page} -> {' / '.join(check.messages)}\n",
                    "error",
                )
        can_run = bool(checks) and invalid == 0
        self.run_output_button.configure(state="normal" if can_run else "disabled")
        self.output_status_var.set("出力可能" if can_run else "要修正があります")
        self._update_workflow_status()

    def run_output(self) -> None:
        checks = check_segment_outputs(self.segments, self.active_preset, self.output_dir, self.processor)
        invalid = [check for check in checks if not check.ok]
        if invalid:
            messagebox.showerror("出力できません", "未入力または命名エラーのあるセグメントを修正してください。")
            self.refresh_output_summary()
            return
        self.run_output_button.configure(state="disabled")
        self.output_text.insert(END, "\n一括出力ログ\n", "heading")
        success = 0
        failed = 0
        for index, check in enumerate(checks, start=1):
            self.output_progress_var.set(f"出力中: {index}/{len(checks)} {check.filename}")
            self.output_status_var.set("一括実行中")
            self.root.update_idletasks()
            if check.output_path is None:
                failed += 1
                self.output_text.insert(END, f"スキップ: {check.segment.start_page}-{check.segment.end_page}\n", "warn")
                continue
            try:
                final_path = self.processor.split_pdf(check.segment, check.output_path)
                digest = self.processor.calculate_sha256(final_path)
                success += 1
                self.output_text.insert(END, f"成功: {final_path} sha256={digest}\n", "ok")
            except Exception as exc:
                failed += 1
                self.output_text.insert(END, f"出力失敗: {check.filename} {exc}\n", "error")
        self.output_progress_var.set(f"処理終了: 成功 {success}件 / 失敗 {failed}件")
        self.output_status_var.set("出力完了" if failed == 0 else "エラー終了")
        self.output_check_summary_var.set(f"出力完了: 成功 {success}件 / 失敗 {failed}件 / 保存先: {self.output_dir}")
        self.run_output_button.configure(state="normal" if failed == 0 else "disabled")
        self._update_workflow_status()


class PresetManagerDialog:
    def __init__(self, app: PdfSplitterApp) -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.title("プリセット管理")
        self.window.geometry("860x560")
        self.selected_index: int | None = None

        self.id_var = StringVar()
        self.name_var = StringVar()
        self.template_var = StringVar()
        self.blank_threshold_var = StringVar()
        self.index_threshold_var = StringVar()
        self.field_key_var = StringVar()
        self.field_label_var = StringVar()
        self.field_required_var = StringVar(value="false")
        self.field_default_var = StringVar()
        self.readonly_notice_var = StringVar()
        self.form_widgets: list[object] = []
        self.field_buttons: list[object] = []
        self.save_button = None
        self.delete_button = None

        self._build_ui()
        self.refresh_list()
        self.select_preset_by_id(app.active_preset_id)
        self.window.transient(app.root)
        self.window.grab_set()

    def _build_ui(self) -> None:
        left = ttk.Frame(self.window, padding=8)
        left.pack(side=LEFT, fill="y")
        self.preset_list = Listbox(left, width=30)
        self.app._style_listbox(self.preset_list)
        self.preset_list.pack(fill=BOTH, expand=True)
        self.preset_list.bind("<<ListboxSelect>>", self.on_preset_selected)
        ttk.Button(left, text="コピーして新規作成", command=self.new_from_selected).pack(fill="x", pady=(8, 0))
        self.delete_button = ttk.Button(left, text="カスタム削除", command=self.delete_selected)
        self.delete_button.pack(fill="x", pady=4)

        form = ttk.Frame(self.window, padding=8)
        form.pack(side=LEFT, fill=BOTH, expand=True)
        self._entry_row(form, "プリセットID", self.id_var)
        self._entry_row(form, "表示名", self.name_var)
        self._entry_row(form, "命名テンプレート", self.template_var)
        self._entry_row(form, "白紙しきい値", self.blank_threshold_var)
        self._entry_row(form, "インデックスしきい値", self.index_threshold_var)

        ttk.Label(form, textvariable=self.readonly_notice_var, style="Hint.TLabel", wraplength=560).pack(anchor="w", pady=(4, 0))
        self.template_help_var = StringVar()
        ttk.Label(form, textvariable=self.template_help_var).pack(anchor="w", pady=(4, 2))
        ttk.Label(form, text="変数をクリックすると命名テンプレートへ挿入します。", style="Hint.TLabel").pack(anchor="w")
        self.template_vars_frame = ttk.Frame(form)
        self.template_vars_frame.pack(fill="x", pady=(2, 6))

        ttk.Label(form, text="入力項目").pack(anchor="w", pady=(8, 2))
        self.fields_tree = ttk.Treeview(
            form,
            columns=("key", "label", "required", "default"),
            show="headings",
            height=7,
        )
        for column, title, width in (
            ("key", "項目キー", 120),
            ("label", "表示名", 180),
            ("required", "必須", 70),
            ("default", "初期値", 120),
        ):
            self.fields_tree.heading(column, text=title)
            self.fields_tree.column(column, width=width)
        self.fields_tree.pack(fill=BOTH, expand=True)
        self.fields_tree.bind("<<TreeviewSelect>>", self.on_field_selected)

        field_editor = ttk.Frame(form)
        field_editor.pack(fill="x", pady=(4, 8))
        self._small_entry(field_editor, "項目キー", self.field_key_var, 12)
        self._small_entry(field_editor, "表示名", self.field_label_var, 18)
        self._small_entry(field_editor, "必須", self.field_required_var, 8)
        self._small_entry(field_editor, "初期値", self.field_default_var, 12)
        add_button = ttk.Button(field_editor, text="項目を追加/更新", command=self.upsert_field)
        add_button.pack(side=LEFT, padx=4)
        remove_button = ttk.Button(field_editor, text="選択項目を削除", command=self.delete_field)
        remove_button.pack(side=LEFT, padx=4)
        self.field_buttons.extend([add_button, remove_button])

        ttk.Label(form, text="抽出キーワード（カンマまたは改行区切り）").pack(anchor="w", pady=(8, 2))
        self.keywords_text = Text(form, height=4, wrap="word")
        self.app._style_text(self.keywords_text)
        self.keywords_text.pack(fill="x")
        self.form_widgets.append(self.keywords_text)

        buttons = ttk.Frame(form)
        buttons.pack(fill="x", pady=(10, 0))
        self.save_button = ttk.Button(buttons, text="保存", command=self.save_current)
        self.save_button.pack(side=LEFT)
        ttk.Button(buttons, text="閉じる", command=self.window.destroy).pack(side=RIGHT)

    def _entry_row(self, parent: ttk.Frame, label: str, variable: StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=18).pack(side=LEFT)
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side=LEFT, fill="x", expand=True)
        if label == "命名テンプレート":
            self.template_entry = entry
        self.form_widgets.append(entry)

    def _small_entry(self, parent: ttk.Frame, label: str, variable: StringVar, width: int) -> None:
        ttk.Label(parent, text=label).pack(side=LEFT, padx=(0, 2))
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.pack(side=LEFT, padx=(0, 6))
        self.field_buttons.append(entry)

    def refresh_list(self) -> None:
        self.preset_list.delete(0, END)
        for preset in self.app.presets:
            suffix = "（組み込み・読取専用）" if preset.id in DEFAULT_PRESET_IDS else ""
            self.preset_list.insert(END, f"{preset.name}{suffix}")

    def select_preset_by_id(self, preset_id: str) -> None:
        for index, preset in enumerate(self.app.presets):
            if preset.id == preset_id:
                self.preset_list.selection_clear(0, END)
                self.preset_list.selection_set(index)
                self.load_preset(index)
                return

    def on_preset_selected(self, _event) -> None:
        selection = self.preset_list.curselection()
        if selection:
            self.load_preset(selection[0])

    def load_preset(self, index: int) -> None:
        self.selected_index = index
        preset = self.app.presets[index]
        self.set_readonly(False)
        self.id_var.set(preset.id)
        self.name_var.set(preset.name)
        self.template_var.set(preset.naming_template)
        self.blank_threshold_var.set(str(preset.blank_threshold))
        self.index_threshold_var.set(str(preset.index_threshold))
        self.load_fields(preset)
        self.keywords_text.delete("1.0", END)
        self.keywords_text.insert("1.0", format_keywords(preset.extraction_keywords))
        readonly = preset.id in DEFAULT_PRESET_IDS
        self.readonly_notice_var.set(
            "組み込みプリセットです。直接編集せず、左の「コピーして新規作成」から案件別に調整してください。"
            if readonly
            else "カスタムプリセットです。案件に合わせて編集できます。"
        )
        self.set_readonly(readonly)

    def new_from_selected(self) -> None:
        source = self.app.presets[self.selected_index] if self.selected_index is not None else self.app.active_preset
        self.set_readonly(False)
        base_id = source.id + "-custom"
        preset_ids = {preset.id for preset in self.app.presets}
        candidate = base_id
        counter = 2
        while candidate in preset_ids:
            candidate = f"{base_id}-{counter}"
            counter += 1
        self.selected_index = None
        self.id_var.set(candidate)
        self.name_var.set(source.name + " コピー")
        self.template_var.set(source.naming_template)
        self.blank_threshold_var.set(str(source.blank_threshold))
        self.index_threshold_var.set(str(source.index_threshold))
        self.load_fields(source)
        self.keywords_text.delete("1.0", END)
        self.keywords_text.insert("1.0", format_keywords(source.extraction_keywords))
        self.readonly_notice_var.set("コピーを作成しました。項目や命名テンプレートを編集して保存してください。")
        self.set_readonly(False)

    def load_fields(self, preset: Preset) -> None:
        self.fields_tree.delete(*self.fields_tree.get_children())
        for field in preset.fields:
            self.fields_tree.insert(
                "",
                END,
                values=(field.key, field.label, "true" if field.required else "false", field.default),
            )
        self.refresh_template_help()

    def field_rows_from_table(self) -> str:
        rows = []
        for item_id in self.fields_tree.get_children():
            key, label, required, default = self.fields_tree.item(item_id, "values")
            rows.append("|".join((str(key), str(label), str(required), str(default))))
        return "\n".join(rows)

    def refresh_template_help(self) -> None:
        keys = [str(self.fields_tree.item(item_id, "values")[0]) for item_id in self.fields_tree.get_children()]
        values = ", ".join("{" + key + "}" for key in keys)
        self.template_help_var.set(f"テンプレートで使える変数: {values or 'なし'}")
        if hasattr(self, "template_vars_frame"):
            for child in self.template_vars_frame.winfo_children():
                child.destroy()
            for key in keys:
                button = ttk.Button(
                    self.template_vars_frame,
                    text="{" + key + "}",
                    command=lambda value=key: self.insert_template_variable(value),
                )
                button.pack(side=LEFT, padx=(0, 4), pady=2)

    def insert_template_variable(self, key: str) -> None:
        if getattr(self, "template_entry", None) is not None and self.template_entry.cget("state") == "disabled":
            return
        value = "{" + key + "}"
        try:
            self.template_entry.insert("insert", value)
        except Exception:
            self.template_var.set(self.template_var.get() + value)

    def on_field_selected(self, _event) -> None:
        selection = self.fields_tree.selection()
        if not selection:
            return
        key, label, required, default = self.fields_tree.item(selection[0], "values")
        self.field_key_var.set(str(key))
        self.field_label_var.set(str(label))
        self.field_required_var.set(str(required))
        self.field_default_var.set(str(default))

    def upsert_field(self) -> None:
        key = self.field_key_var.get().strip()
        label = self.field_label_var.get().strip()
        required = self.field_required_var.get().strip() or "false"
        default = self.field_default_var.get()
        if not key or not label:
            messagebox.showerror("入力項目", "項目キーと表示名を入力してください。", parent=self.window)
            return
        for item_id in self.fields_tree.get_children():
            values = self.fields_tree.item(item_id, "values")
            if values and values[0] == key:
                self.fields_tree.item(item_id, values=(key, label, required, default))
                self.refresh_template_help()
                return
        self.fields_tree.insert("", END, values=(key, label, required, default))
        self.refresh_template_help()

    def delete_field(self) -> None:
        for item_id in self.fields_tree.selection():
            self.fields_tree.delete(item_id)
        self.refresh_template_help()

    def set_readonly(self, readonly: bool) -> None:
        state = "disabled" if readonly else "normal"
        for widget in self.form_widgets:
            widget.configure(state=state)
        for widget in self.field_buttons:
            widget.configure(state=state)
        self.fields_tree.configure(selectmode="browse")
        if self.save_button is not None:
            self.save_button.configure(state=state)
        if self.delete_button is not None:
            self.delete_button.configure(state="disabled" if readonly else "normal")

    def save_current(self) -> None:
        try:
            preset = build_preset_from_editor(
                preset_id=self.id_var.get(),
                name=self.name_var.get(),
                field_rows=self.field_rows_from_table(),
                naming_template=self.template_var.get(),
                extraction_keywords=self.keywords_text.get("1.0", "end-1c"),
                blank_threshold=self.blank_threshold_var.get(),
                index_threshold=self.index_threshold_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("プリセットエラー", str(exc), parent=self.window)
            return
        if preset.id in DEFAULT_PRESET_IDS:
            messagebox.showerror(
                "プリセットエラー",
                "組み込みプリセットは保護されています。コピーして新規作成してから保存してください。",
                parent=self.window,
            )
            return

        for index, existing in enumerate(self.app.presets):
            if existing.id == preset.id:
                self.app.presets[index] = preset
                break
        else:
            self.app.presets.append(preset)

        self.app.set_active_preset(preset.id)
        self.refresh_list()
        self.select_preset_by_id(preset.id)
        messagebox.showinfo("プリセット保存", f"保存しました: {preset.name}", parent=self.window)

    def delete_selected(self) -> None:
        if self.selected_index is None:
            return
        preset = self.app.presets[self.selected_index]
        if preset.id in DEFAULT_PRESET_IDS:
            messagebox.showerror("プリセットエラー", "組み込みプリセットは削除できません。", parent=self.window)
            return
        if not messagebox.askyesno("プリセット削除", f"'{preset.name}' を削除しますか？", parent=self.window):
            return
        self.app.presets.pop(self.selected_index)
        next_active = self.app.active_preset_id
        if preset.id == self.app.active_preset_id:
            next_active = self.app.presets[0].id
        self.app.set_active_preset(next_active)
        self.refresh_list()
        self.select_preset_by_id(next_active)


def default_work_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main(work_dir: Path | None = None) -> None:
    root = Tk()
    root.geometry("1200x820")
    PdfSplitterApp(root, work_dir or default_work_dir())
    root.mainloop()
