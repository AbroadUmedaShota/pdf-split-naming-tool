from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, Canvas, Listbox, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from .models import Preset, Segment
from .presets import PresetRepository, find_preset
from .processor import PdfProcessor
from .state import StateManager


TEXT_WIDGET_CLASSES = {"Entry", "TEntry", "Text", "Spinbox", "TCombobox"}


class PdfSplitterApp:
    def __init__(self, root: Tk, work_dir: Path | None = None) -> None:
        self.root = root
        self.work_dir = work_dir or Path.cwd()
        self.root.title("PDF Split Naming Tool Recovery")
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
                self.active_preset = preset
                self.active_preset_id = preset.id
                self.preset_repo.save(self.presets, self.active_preset_id)
                self.rebuild_metadata_fields()
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


def main() -> None:
    root = Tk()
    root.geometry("1200x820")
    PdfSplitterApp(root)
    root.mainloop()
