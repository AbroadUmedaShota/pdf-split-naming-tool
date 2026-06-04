# Step 2 Details Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step 2の詳細機能をタブ化し、検索、候補、OCR本文、詳細操作が狭い右ペインでも見失われないようにする。

**Architecture:** PDF処理や分割ロジックは変更せず、`PdfSplitterApp._build_step2()` の詳細表示コンテナだけを再配置する。既存の `BooleanVar` と `pack()` / `pack_forget()` による開閉は維持し、GUIスモークが参照する `search_button`、`ocr_text`、`candidate_list` などの属性名も変えない。

**Tech Stack:** Python 3.14、Tkinter/ttk、既存pytest、`scripts/gui_smoke.py`

---

### Task 1: Step 2詳細領域をタブ化する

**Files:**
- Modify: `recovery/pdf_splitter_tool/app.py`
- Test: `recovery/scripts/gui_smoke.py`

- [ ] **Step 1: 詳細領域の現状を確認する**

Run:

```powershell
Select-String -Path recovery\pdf_splitter_tool\app.py -Pattern "self.step2_details_frame|候補検出|OCR本文|詳細な分割操作" -Context 3,6
```

Expected: `候補検出`、`候補/OCR本文Notebook`、`詳細な分割操作` が縦積みで作られている。

- [ ] **Step 2: 詳細領域にNotebookを作る**

In `PdfSplitterApp._build_step2()`, replace the direct children of `self.step2_details_frame` with:

```python
        detail_tabs = ttk.Notebook(self.step2_details_frame)
        detail_tabs.pack(fill=BOTH, expand=True)

        detect_tab = ttk.Frame(detail_tabs, padding=6)
        detail_tabs.add(detect_tab, text="検出")
```

- [ ] **Step 3: 候補検出ウィジェットを検出タブへ移す**

Move the existing search entry, `検索`、`インデックス`、`白紙検出`、`処理中止` buttons into `detect_tab`. Attribute names must remain unchanged:

```python
self.search_entry
self.search_button
self.index_button
self.blank_button
self.cancel_job_button
```

- [ ] **Step 4: 候補、OCR、操作を独立タブへ移す**

Create `候補`、`OCR本文`、`操作` tabs in the same `detail_tabs`. Keep these existing attributes unchanged:

```python
self.candidate_list
self.ocr_text
self.ocr_transfer_combo
```

- [ ] **Step 5: GUIスモークを実行する**

Run:

```powershell
cd recovery
python scripts/gui_smoke.py
```

Expected: Step 2 details are opened by smoke, search succeeds, output PDF count is 3, screenshots are created.

### Task 2: 仕様書へ表示方針を追記する

**Files:**
- Modify: `docs/archive/2026-05-20_画面別機能仕様書.md`

- [ ] **Step 1: 通常作業モード記述を更新する**

Update section `2.1 通常作業モードと詳細機能` to state that Step 2 detailed functions are grouped into detail tabs.

- [ ] **Step 2: Step 2表示項目を更新する**

Update Step 2 right-pane description so detailed functions are `検出`、`候補`、`OCR本文`、`操作` tabs under `詳細機能を表示`.

### Task 3: 検証する

**Files:**
- Test: `recovery/tests`
- Test: `recovery/scripts/gui_smoke.py`

- [ ] **Step 1: Unit tests**

Run:

```powershell
cd recovery
python -m pytest
```

Expected: 37 passed.

- [ ] **Step 2: Compile**

Run:

```powershell
cd recovery
python -m compileall pdf_splitter_tool tests scripts
```

Expected: exit 0.

- [ ] **Step 3: Runtime smoke**

Run:

```powershell
cd recovery
python -m pdf_splitter_tool --smoke
```

Expected: JSON output with app metadata and runtime paths.

- [ ] **Step 4: GUI smoke**

Run:

```powershell
cd recovery
python scripts/gui_smoke.py
```

Expected: status `passed` and `output_pdf_count` 3.
