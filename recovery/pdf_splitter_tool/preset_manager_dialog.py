from __future__ import annotations

from typing import TYPE_CHECKING
from tkinter import BOTH, END, LEFT, RIGHT, Text, Toplevel, StringVar, Listbox, messagebox
from tkinter import ttk

from .models import Preset
from .preset_editing import build_preset_from_editor, format_keywords
from .presets import DEFAULT_PRESET_IDS

if TYPE_CHECKING:
    from .app import PdfSplitterApp


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


