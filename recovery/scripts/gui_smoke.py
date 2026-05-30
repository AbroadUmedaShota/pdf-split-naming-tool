from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from tkinter import Tk

import fitz
from PIL import ImageGrab

RECOVERY_ROOT = Path(__file__).resolve().parents[1]
if str(RECOVERY_ROOT) not in sys.path:
    sys.path.insert(0, str(RECOVERY_ROOT))

from pdf_splitter_tool.app import MAIN_TAB_LABELS, STEP2_DETAIL_TAB_LABELS, PdfSplitterApp
from pdf_splitter_tool.preset_manager_dialog import PresetManagerDialog


def make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    for page_no in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 72), f"Invoice sample page {page_no}", fontsize=14)
        page.insert_text((72, 108), "Box 01 Binder 02", fontsize=12)
        page.insert_text((72, 144), "BoxNo01", fontsize=12)
        page.insert_text((72, 180), "BinderNo02", fontsize=12)
        page.insert_text((72, 216), "Seq003", fontsize=12)
    doc.save(path)
    doc.close()


def pump(root: Tk, seconds: float = 0.2) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        root.update_idletasks()
        time.sleep(0.02)


def wait_until(root: Tk, condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pump(root, 0.1)
        if condition():
            return
    raise AssertionError("Timed out waiting for GUI smoke condition.")


def capture_widget(widget, output_dir: Path, name: str) -> Path:
    widget.update()
    widget.update_idletasks()
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    width = widget.winfo_width()
    height = widget.winfo_height()
    if width <= 1 or height <= 1:
        raise AssertionError(f"Cannot capture screenshot for {name}: invalid size {width}x{height}")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.png"
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
    return path


def assert_notebook_tabs(notebook, expected: tuple[str, ...]) -> None:
    actual = tuple(notebook.tab(tab_id, "text") for tab_id in notebook.tabs())
    if actual != expected:
        raise AssertionError(f"Notebook tabs mismatch: expected {expected!r}, got {actual!r}")


def listbox_values(listbox) -> tuple[str, ...]:
    return tuple(listbox.get(index) for index in range(listbox.size()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a GUI smoke check and save screenshots for PDF Split Naming Tool.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Screenshot/result output directory.")
    parser.add_argument("--keep-workdir", action="store_true", help="Keep temporary PDF/output/state files for inspection.")
    parser.add_argument("--no-screenshots", action="store_true", help="Run GUI assertions without saving screenshots.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or repo_root / "artifacts" / "ui-screenshots" / timestamp
    work_dir = Path(tempfile.mkdtemp(prefix="pdf_split_gui_smoke_"))
    screenshots: list[str] = []
    root = Tk()
    root.withdraw()
    root.geometry("1180x820+80+80")
    root.deiconify()

    try:
        sample_pdf = work_dir / "gui-smoke-sample.pdf"
        make_sample_pdf(sample_pdf)
        app = PdfSplitterApp(root, work_dir=work_dir)
        pump(root, 0.5)
        assert_notebook_tabs(app.notebook, MAIN_TAB_LABELS)

        app.add_pdf_paths([sample_pdf])
        wait_until(root, lambda: app.current_page_count == 3)
        if app.pdf_list.size() != 1:
            raise AssertionError("Step 1 PDF list did not contain the sample PDF.")
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step1_pdf_selection")))

        app.notebook.select(app.step2)
        pump(root, 0.5)
        wait_until(root, lambda: app._preview_image is not None and "Invoice sample" in app.ocr_text.get("1.0", "end"))
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step2_initial_split")))
        app.step2_details_visible_var.set(True)
        app.toggle_step2_details()
        pump(root, 0.2)
        assert_notebook_tabs(app.step2_detail_tabs, STEP2_DETAIL_TAB_LABELS)
        for tab_index in range(len(STEP2_DETAIL_TAB_LABELS)):
            app.step2_detail_tabs.select(tab_index)
            pump(root, 0.05)
        app.step2_detail_tabs.select(0)
        app.search_var.set("Invoice")
        app.start_text_search()
        wait_until(root, lambda: bool(app.search_hit_pages))
        wait_until(root, lambda: app._preview_image is not None and "検索ハイライト" in app.status_var.get())
        app.split_by_n_pages(1)
        wait_until(root, lambda: len(app.segments) == 3)
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step2_split_and_search")))

        app.notebook.select(app.step3)
        pump(root, 0.3)
        app.step3_assist_visible_var.set(True)
        app.toggle_step3_assist()
        app.refresh_metadata_suggestions()
        suggestions = listbox_values(app.suggestion_list)
        if suggestions[:3] != ("01", "02", "003"):
            raise AssertionError(f"Step 3 suggestions mismatch: {suggestions!r}")
        if not app.suggestion_copy_button.instate(["!disabled"]):
            raise AssertionError("Step 3 suggestion copy button should be enabled when candidates exist")
        if "件" not in app.step3_suggestion_var.get():
            raise AssertionError(f"Step 3 suggestion status should show count: {app.step3_suggestion_var.get()!r}")
        if "Ctrl+C" not in app.step3_suggestion_var.get():
            raise AssertionError(f"Step 3 suggestion status should mention Ctrl+C: {app.step3_suggestion_var.get()!r}")
        if "選択中 01" not in app.step3_suggestion_var.get():
            raise AssertionError(f"Step 3 initial selected suggestion should be visible in status: {app.step3_suggestion_var.get()!r}")
        pump(root, 0.1)
        if root.focus_get() != app.suggestion_list:
            raise AssertionError("Step 3 suggestion list should receive focus after refreshing candidates")
        app.suggestion_list.selection_clear(0, "end")
        app.update_suggestion_copy_state()
        pump(root, 0.1)
        if app.suggestion_copy_button.instate(["!disabled"]):
            raise AssertionError("Step 3 suggestion copy button should be disabled when no candidate is selected")
        if "選択中" in app.step3_suggestion_var.get() or "候補を選択" not in app.step3_suggestion_var.get():
            raise AssertionError(
                f"Step 3 suggestion status should not keep stale selected value: {app.step3_suggestion_var.get()!r}"
            )
        app.suggestion_list.selection_set(1)
        app.update_suggestion_copy_state()
        pump(root, 0.1)
        if not app.suggestion_copy_button.instate(["!disabled"]):
            raise AssertionError("Step 3 suggestion copy button should re-enable after candidate selection")
        if "02" not in app.step3_suggestion_var.get():
            raise AssertionError(f"Step 3 selected suggestion should be visible in status: {app.step3_suggestion_var.get()!r}")
        app.suggestion_list.focus_force()
        pump(root, 0.1)
        app.suggestion_list.event_generate("<Escape>")
        pump(root, 0.1)
        if app.suggestion_copy_button.instate(["!disabled"]):
            raise AssertionError("Step 3 Escape should disable suggestion copy after clearing selection")
        if "解除" not in app.step3_suggestion_var.get():
            raise AssertionError(f"Step 3 Escape should show clear status: {app.step3_suggestion_var.get()!r}")
        app.suggestion_list.selection_set(1)
        app.update_suggestion_copy_state()
        pump(root, 0.1)
        app.suggestion_copy_button.focus_force()
        pump(root, 0.1)
        app.suggestion_copy_button.invoke()
        pump(root, 0.1)
        if root.clipboard_get() != "02":
            raise AssertionError("Step 3 copy button should copy the selected suggestion")
        if root.focus_get() != app.suggestion_list:
            raise AssertionError("Step 3 copy button should return focus to the suggestion list")
        app.suggestion_list.event_generate("<Control-c>")
        pump(root, 0.1)
        if root.clipboard_get() != "02":
            raise AssertionError("Step 3 Ctrl+C should copy the selected suggestion")
        if app.copy_selected_metadata_suggestion() != "break":
            raise AssertionError("Step 3 suggestion copy handler should stop Tk default key handling")
        app.suggestion_list.selection_clear(0, "end")
        app.suggestion_list.selection_set(0)
        app.update_suggestion_copy_state()
        app.suggestion_list.event_generate("<KeyPress-Return>")
        pump(root, 0.1)
        if root.clipboard_get() != "01":
            raise AssertionError("Step 3 Enter key should copy the selected suggestion")
        app.common_metadata_vars["box_no"].set("1")
        app.common_metadata_vars["binder_no"].set("2")
        app.apply_common_metadata_to_segments()
        app.seq_start_var.set("3")
        app.seq_step_var.set("1")
        app.resequence_segment_metadata()
        wait_until(root, lambda: app.metadata_summary_var.get().find("出力可能: 3件") >= 0)
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step3_metadata")))

        app.notebook.select(app.step4)
        app.refresh_output_summary()
        wait_until(root, lambda: str(app.run_output_button.cget("state")) == "normal")
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step4_preflight")))
        app.run_output()
        wait_until(root, lambda: len(list(app.output_dir.glob("*.pdf"))) == 3)
        wait_until(root, lambda: app.output_history.history_path.exists())
        app.notebook.select(app.step5)
        app.refresh_history_view()
        wait_until(root, lambda: "created" in app.history_text.get("1.0", "end"))
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(root, output_dir, "step5_history")))

        dialog = PresetManagerDialog(app)
        pump(root, 0.3)
        if not args.no_screenshots:
            screenshots.append(str(capture_widget(dialog.window, output_dir, "preset_manager")))
        dialog.window.destroy()

        app.save_state()
        result = {
            "status": "passed",
            "work_dir": str(work_dir),
            "sample_pdf": str(sample_pdf),
            "output_dir": str(app.output_dir),
            "output_pdf_count": len(list(app.output_dir.glob("*.pdf"))),
            "screenshots": screenshots,
            "kept_workdir": args.keep_workdir,
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "gui-smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        root.destroy()
        if not args.keep_workdir:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
