from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Canvas, Listbox, StringVar, Text, Tk, Toplevel, filedialog, messagebox
from tkinter import ttk

from .app_metadata import APP_NAME
from .models import Preset, Segment
from .preset_editing import build_preset_from_editor, format_field_rows, format_keywords
from .presets import DEFAULT_PRESET_IDS, PresetRepository, find_preset
from .processor import PdfProcessor
from .state import StateManager


TEXT_WIDGET_CLASSES = {"Entry", "TEntry", "Text", "Spinbox", "TCombobox"}


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
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._preview_image = None

        self._build_ui()
        self._bind_keys()
        self._poll_worker_queue()

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=BOTH, expand=True)

        self.step1 = ttk.Frame(self.notebook, padding=8)
        self.step2 = ttk.Frame(self.notebook, padding=8)
        self.step3 = ttk.Frame(self.notebook, padding=8)
        self.step4 = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.step1, text="1 Select")
        self.notebook.add(self.step2, text="2 Split")
        self.notebook.add(self.step3, text="3 Metadata")
        self.notebook.add(self.step4, text="4 Output")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_step4()

    def _build_step1(self) -> None:
        toolbar = ttk.Frame(self.step1)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Add PDFs", command=self.select_pdfs).pack(side=LEFT)
        ttk.Button(toolbar, text="Input Folder", command=self.select_folder).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="Output Folder", command=self.select_output_dir).pack(side=LEFT, padx=4)
        ttk.Button(toolbar, text="Manage Presets", command=self.open_preset_manager).pack(side=LEFT, padx=4)

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

        self.pdf_list = Listbox(self.step1, height=12)
        self.pdf_list.pack(fill=BOTH, expand=True, pady=8)
        self.pdf_list.bind("<<ListboxSelect>>", self.on_pdf_selected)

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
        self.rebuild_metadata_fields()
        self.refresh_segment_list()

    def _build_step2(self) -> None:
        left = ttk.Frame(self.step2)
        left.pack(side=LEFT, fill="y")
        self.page_list = Listbox(left, width=16)
        self.page_list.pack(fill="y", expand=True)
        self.page_list.bind("<<ListboxSelect>>", self.on_page_selected)

        right = ttk.Frame(self.step2)
        right.pack(side=LEFT, fill=BOTH, expand=True, padx=8)
        nav = ttk.Frame(right)
        nav.pack(fill="x")
        ttk.Button(nav, text="Prev", command=self.prev_page).pack(side=LEFT)
        ttk.Button(nav, text="Next", command=self.next_page).pack(side=LEFT, padx=4)
        ttk.Button(nav, text="Split Before Page", command=self.add_split_before_current_page).pack(side=LEFT, padx=4)
        ttk.Button(nav, text="Split by 1 Page", command=lambda: self.split_by_n_pages(1)).pack(side=LEFT, padx=4)
        ttk.Button(nav, text="Blank Scan", command=self.start_blank_scan).pack(side=LEFT, padx=4)

        self.search_var = StringVar()
        self.search_entry = ttk.Entry(nav, textvariable=self.search_var, width=24)
        self.search_entry.pack(side=RIGHT)
        ttk.Button(nav, text="Search", command=self.start_text_search).pack(side=RIGHT, padx=4)
        ttk.Button(nav, text="Index", command=self.start_index_candidate_search).pack(side=RIGHT, padx=4)

        self.preview_canvas = Canvas(right, background="#222", height=520, highlightthickness=1, takefocus=True)
        self.preview_canvas.pack(fill=BOTH, expand=True, pady=8)
        self.preview_canvas.bind("<Button-1>", lambda _event: self.preview_canvas.focus_set())

        self.ocr_text = Text(right, height=8, wrap="word")
        self.ocr_text.pack(fill="x")
        self.status_var = StringVar(value="No PDF loaded")
        ttk.Label(right, textvariable=self.status_var).pack(fill="x")

    def _build_step3(self) -> None:
        self.segment_list = Listbox(self.step3, width=44)
        self.segment_list.pack(side=LEFT, fill="y")
        self.segment_list.bind("<<ListboxSelect>>", self.on_segment_selected)

        self.metadata_frame = ttk.Frame(self.step3, padding=8)
        self.metadata_frame.pack(side=LEFT, fill=BOTH, expand=True)
        self.filename_preview_var = StringVar()
        ttk.Label(self.metadata_frame, textvariable=self.filename_preview_var).pack(fill="x", pady=8)

    def _build_step4(self) -> None:
        toolbar = ttk.Frame(self.step4)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Validate", command=self.refresh_output_summary).pack(side=LEFT)
        ttk.Button(toolbar, text="Run Output", command=self.run_output).pack(side=LEFT, padx=4)
        self.output_text = Text(self.step4, height=24)
        self.output_text.pack(fill=BOTH, expand=True, pady=8)

    def _bind_keys(self) -> None:
        self.root.bind_all("<space>", self.on_space_key)
        self.root.bind_all("<Left>", self.on_left_key)
        self.root.bind_all("<Right>", self.on_right_key)

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

    def select_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        self.add_pdf_paths([Path(path) for path in paths])

    def select_folder(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.add_pdf_paths(sorted(Path(folder).glob("*.pdf")))

    def add_pdf_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path not in self.pdf_paths:
                self.pdf_paths.append(path)
                self.pdf_list.insert(END, str(path))
        if self.pdf_paths and self.current_pdf is None:
            self.set_current_pdf(self.pdf_paths[0])

    def select_output_dir(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir = Path(folder)

    def on_pdf_selected(self, _event) -> None:
        selection = self.pdf_list.curselection()
        if selection:
            self.set_current_pdf(self.pdf_paths[selection[0]])

    def set_current_pdf(self, path: Path) -> None:
        self.current_pdf = path
        self.current_page = 1
        try:
            self.current_page_count = self.processor.page_count(path)
        except Exception as exc:
            messagebox.showerror("PDF error", str(exc))
            self.current_page_count = 0
        self.refresh_page_list()
        self.render_current_page_async()

    def refresh_page_list(self) -> None:
        self.page_list.delete(0, END)
        for page_no in range(1, self.current_page_count + 1):
            self.page_list.insert(END, f"Page {page_no}")
        if self.current_page_count:
            self.page_list.selection_set(self.current_page - 1)

    def on_page_selected(self, _event) -> None:
        selection = self.page_list.curselection()
        if selection:
            self.current_page = selection[0] + 1
            self.render_current_page_async()

    def render_current_page_async(self) -> None:
        if self.current_pdf is None or self.current_page_count == 0:
            return
        pdf_path = self.current_pdf
        page_no = self.current_page
        self.status_var.set(f"Rendering page {page_no}/{self.current_page_count}")

        def worker() -> None:
            try:
                pixmap = self.processor.render_page_pixmap(pdf_path, page_no)
                text = self.processor.extract_page_text(pdf_path, page_no)
                self.worker_queue.put(("rendered", (page_no, pixmap, text)))
            except Exception as exc:
                self.worker_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _display_pixmap(self, pixmap) -> None:
        from PIL import Image, ImageTk

        image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
        self._preview_image = ImageTk.PhotoImage(image)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(8, 8, image=self._preview_image, anchor="nw")

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "rendered":
                    page_no, pixmap, text = payload
                    if page_no == self.current_page:
                        self._display_pixmap(pixmap)
                        self.ocr_text.delete("1.0", END)
                        self.ocr_text.insert("1.0", text)
                        self.status_var.set(f"Page {page_no}/{self.current_page_count}")
                        self.warm_thumbnail_window(page_no)
                elif kind == "search_done":
                    hits = payload
                    self.status_var.set(f"Search hits: {len(hits)}")
                    if hits:
                        self.current_page = hits[0]
                        self.render_current_page_async()
                elif kind == "blank_done":
                    pages = payload
                    self.status_var.set(f"Blank candidates: {', '.join(map(str, pages[:20]))}")
                elif kind == "index_done":
                    hits = payload
                    self.status_var.set(f"Index candidates: {', '.join(map(str, hits[:20]))}")
                    if hits:
                        self.current_page = hits[0]
                        self.render_current_page_async()
                elif kind == "error":
                    self.status_var.set(str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_worker_queue)

    def prev_page(self) -> None:
        if self.current_page > 1:
            self.current_page -= 1
            self.page_list.selection_clear(0, END)
            self.page_list.selection_set(self.current_page - 1)
            self.render_current_page_async()

    def next_page(self) -> None:
        if self.current_page < self.current_page_count:
            self.current_page += 1
            self.page_list.selection_clear(0, END)
            self.page_list.selection_set(self.current_page - 1)
            self.render_current_page_async()

    def add_split_before_current_page(self) -> None:
        if self.current_pdf is None or self.current_page <= 1:
            return
        previous_end = max((segment.end_page for segment in self.segments if segment.pdf_path == self.current_pdf), default=0)
        start_page = previous_end + 1
        end_page = self.current_page - 1
        if start_page <= end_page:
            metadata = self.active_preset.default_metadata()
            metadata["seq"] = str(len(self.segments) + 1)
            self.segments.append(Segment(self.current_pdf, start_page, end_page, metadata))
            self.refresh_segment_list()

    def split_by_n_pages(self, pages_per_segment: int) -> None:
        if self.current_pdf is None or self.current_page_count == 0:
            return
        self.segments = self.processor.build_segments_by_n_pages(
            self.current_pdf,
            self.current_page_count,
            pages_per_segment,
        )
        for index, segment in enumerate(self.segments, start=1):
            segment.metadata.update(self.active_preset.default_metadata())
            segment.metadata["seq"] = str(index)
        self.refresh_segment_list()

    def start_text_search(self) -> None:
        if self.current_pdf is None:
            return
        query = self.search_var.get().strip().lower()
        if not query:
            return
        pdf_path = self.current_pdf
        page_count = self.current_page_count

        def worker() -> None:
            hits: list[int] = []
            for page_no in range(1, page_count + 1):
                text = self.processor.extract_page_text(pdf_path, page_no).lower()
                if query in text:
                    hits.append(page_no)
            self.worker_queue.put(("search_done", hits))

        threading.Thread(target=worker, daemon=True).start()

    def start_index_candidate_search(self) -> None:
        if self.current_pdf is None:
            return
        keywords = tuple(keyword.lower() for keyword in self.active_preset.extraction_keywords if keyword.strip())
        if not keywords:
            return
        pdf_path = self.current_pdf
        page_count = self.current_page_count

        def worker() -> None:
            hits: list[int] = []
            for page_no in range(1, page_count + 1):
                text = self.processor.extract_page_text(pdf_path, page_no).lower()
                if any(keyword in text for keyword in keywords):
                    hits.append(page_no)
            self.worker_queue.put(("index_done", hits))

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
        pdf_path = self.current_pdf
        page_count = self.current_page_count
        threshold = self.active_preset.blank_threshold

        def worker() -> None:
            pages: list[int] = []
            for page_no in range(1, page_count + 1):
                try:
                    if self.processor.is_blank_page(pdf_path, page_no, threshold):
                        pages.append(page_no)
                except Exception as exc:
                    self.worker_queue.put(("error", str(exc)))
                    return
            self.worker_queue.put(("blank_done", pages))

        threading.Thread(target=worker, daemon=True).start()

    def on_preset_selected(self, _event) -> None:
        selected_name = self.preset_var.get()
        for preset in self.presets:
            if preset.name == selected_name:
                self.set_active_preset(preset.id)
                return

    def refresh_segment_list(self) -> None:
        self.segment_list.delete(0, END)
        for segment in self.segments:
            result = self.processor.build_filename_templated(self.active_preset, segment.metadata)
            label = f"{segment.start_page}-{segment.end_page}: {result.normalized_filename or 'invalid'}"
            self.segment_list.insert(END, label)

    def on_segment_selected(self, _event) -> None:
        selection = self.segment_list.curselection()
        self.current_segment_index = selection[0] if selection else None
        self.rebuild_metadata_fields()

    def rebuild_metadata_fields(self) -> None:
        for child in self.metadata_frame.winfo_children():
            child.destroy()
        if self.current_segment_index is None and self.segments:
            self.current_segment_index = 0
            self.segment_list.selection_set(0)
        if self.current_segment_index is None or not self.segments:
            ttk.Label(self.metadata_frame, text="No segment selected").pack()
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

    def on_metadata_changed(self, key: str, value: StringVar) -> None:
        if self.current_segment_index is None:
            return
        self.segments[self.current_segment_index].metadata[key] = value.get()
        self.update_filename_preview()
        self.refresh_segment_list()

    def update_filename_preview(self) -> None:
        if self.current_segment_index is None:
            return
        segment = self.segments[self.current_segment_index]
        result = self.processor.build_filename_templated(self.active_preset, segment.metadata)
        if result.ok:
            self.filename_preview_var.set(f"Output: {result.normalized_filename}")
        else:
            self.filename_preview_var.set("Errors: " + ", ".join(result.errors))

    def refresh_output_summary(self) -> None:
        self.output_text.delete("1.0", END)
        for segment in self.segments:
            result = self.processor.build_filename_templated(self.active_preset, segment.metadata)
            if result.ok:
                self.output_text.insert(END, f"{segment.start_page}-{segment.end_page} -> {result.normalized_filename}\n")
            else:
                self.output_text.insert(END, f"{segment.start_page}-{segment.end_page} ERR {result.errors}\n")

    def run_output(self) -> None:
        errors: list[str] = []
        for segment in self.segments:
            result = self.processor.build_filename_templated(self.active_preset, segment.metadata)
            if not result.ok:
                errors.extend(result.errors)
                continue
            output_path = self.output_dir / result.normalized_filename
            final_path = self.processor.split_pdf(segment, output_path)
            self.output_text.insert(END, f"Wrote {final_path}\n")
        if errors:
            messagebox.showerror("Validation errors", "\n".join(errors))


class PresetManagerDialog:
    def __init__(self, app: PdfSplitterApp) -> None:
        self.app = app
        self.window = Toplevel(app.root)
        self.window.title("Manage Presets")
        self.window.geometry("860x560")
        self.selected_index: int | None = None

        self.id_var = StringVar()
        self.name_var = StringVar()
        self.template_var = StringVar()
        self.blank_threshold_var = StringVar()
        self.index_threshold_var = StringVar()

        self._build_ui()
        self.refresh_list()
        self.select_preset_by_id(app.active_preset_id)
        self.window.transient(app.root)
        self.window.grab_set()

    def _build_ui(self) -> None:
        left = ttk.Frame(self.window, padding=8)
        left.pack(side=LEFT, fill="y")
        self.preset_list = Listbox(left, width=30)
        self.preset_list.pack(fill=BOTH, expand=True)
        self.preset_list.bind("<<ListboxSelect>>", self.on_preset_selected)
        ttk.Button(left, text="New from selected", command=self.new_from_selected).pack(fill="x", pady=(8, 0))
        ttk.Button(left, text="Delete custom", command=self.delete_selected).pack(fill="x", pady=4)

        form = ttk.Frame(self.window, padding=8)
        form.pack(side=LEFT, fill=BOTH, expand=True)
        self._entry_row(form, "Preset ID", self.id_var)
        self._entry_row(form, "Name", self.name_var)
        self._entry_row(form, "Naming template", self.template_var)
        self._entry_row(form, "Blank threshold", self.blank_threshold_var)
        self._entry_row(form, "Index threshold", self.index_threshold_var)

        ttk.Label(form, text="Fields: key|label|required|default").pack(anchor="w", pady=(8, 2))
        self.fields_text = Text(form, height=9, wrap="none")
        self.fields_text.pack(fill=BOTH, expand=True)

        ttk.Label(form, text="Extraction keywords: comma or newline separated").pack(anchor="w", pady=(8, 2))
        self.keywords_text = Text(form, height=4, wrap="word")
        self.keywords_text.pack(fill="x")

        buttons = ttk.Frame(form)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Save", command=self.save_current).pack(side=LEFT)
        ttk.Button(buttons, text="Close", command=self.window.destroy).pack(side=RIGHT)

    def _entry_row(self, parent: ttk.Frame, label: str, variable: StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=18).pack(side=LEFT)
        ttk.Entry(row, textvariable=variable).pack(side=LEFT, fill="x", expand=True)

    def refresh_list(self) -> None:
        self.preset_list.delete(0, END)
        for preset in self.app.presets:
            suffix = " (built-in)" if preset.id in DEFAULT_PRESET_IDS else ""
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
        self.id_var.set(preset.id)
        self.name_var.set(preset.name)
        self.template_var.set(preset.naming_template)
        self.blank_threshold_var.set(str(preset.blank_threshold))
        self.index_threshold_var.set(str(preset.index_threshold))
        self.fields_text.delete("1.0", END)
        self.fields_text.insert("1.0", format_field_rows(preset.fields))
        self.keywords_text.delete("1.0", END)
        self.keywords_text.insert("1.0", format_keywords(preset.extraction_keywords))

    def new_from_selected(self) -> None:
        source = self.app.presets[self.selected_index] if self.selected_index is not None else self.app.active_preset
        base_id = source.id + "-custom"
        preset_ids = {preset.id for preset in self.app.presets}
        candidate = base_id
        counter = 2
        while candidate in preset_ids:
            candidate = f"{base_id}-{counter}"
            counter += 1
        self.selected_index = None
        self.id_var.set(candidate)
        self.name_var.set(source.name + " Copy")
        self.template_var.set(source.naming_template)
        self.blank_threshold_var.set(str(source.blank_threshold))
        self.index_threshold_var.set(str(source.index_threshold))
        self.fields_text.delete("1.0", END)
        self.fields_text.insert("1.0", format_field_rows(source.fields))
        self.keywords_text.delete("1.0", END)
        self.keywords_text.insert("1.0", format_keywords(source.extraction_keywords))

    def save_current(self) -> None:
        try:
            preset = build_preset_from_editor(
                preset_id=self.id_var.get(),
                name=self.name_var.get(),
                field_rows=self.fields_text.get("1.0", "end-1c"),
                naming_template=self.template_var.get(),
                extraction_keywords=self.keywords_text.get("1.0", "end-1c"),
                blank_threshold=self.blank_threshold_var.get(),
                index_threshold=self.index_threshold_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Preset error", str(exc), parent=self.window)
            return
        if preset.id in DEFAULT_PRESET_IDS:
            messagebox.showerror(
                "Preset error",
                "Built-in preset IDs are protected. Use New from selected and save with a different ID.",
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
        messagebox.showinfo("Preset saved", f"Saved preset: {preset.name}", parent=self.window)

    def delete_selected(self) -> None:
        if self.selected_index is None:
            return
        preset = self.app.presets[self.selected_index]
        if preset.id in DEFAULT_PRESET_IDS:
            messagebox.showerror("Preset error", "Built-in presets cannot be deleted.", parent=self.window)
            return
        if not messagebox.askyesno("Delete preset", f"Delete preset '{preset.name}'?", parent=self.window):
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
