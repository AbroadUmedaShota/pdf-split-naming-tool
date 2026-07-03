from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz
import pytest

from pdf_splitter_tool.pdf_service import PdfService
from pdf_splitter_tool import sidecar
from pdf_splitter_tool.sidecar import handle_request


def make_pdf(path: Path, pages: int) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(path)
    doc.close()


def segment(source: Path, start_page: int, end_page: int, seq: str = "3") -> dict[str, Any]:
    return {
        "pdf_path": str(source),
        "start_page": start_page,
        "end_page": end_page,
        "metadata": {"box_no": "1", "binder_no": "2", "seq": seq},
    }


def pdf_text(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def assert_no_pdfs(path: Path) -> None:
    assert not path.exists() or list(path.glob("*.pdf")) == []


def test_sidecar_export_missing_output_dir_writes_no_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": "",
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 0}
    assert response["items"] == []
    assert response["messages"] == ["missing_output_dir"]
    assert_no_pdfs(tmp_path / "output")


def test_sidecar_export_without_segments_writes_no_pdf(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"

    response = handle_request({"command": "export", "output_dir": str(output_dir), "segments": []})

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 0}
    assert response["items"] == []
    assert response["messages"] == ["no_segments"]
    assert_no_pdfs(output_dir)


def test_sidecar_export_preflight_invalid_writes_no_pdf(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 2)],
        }
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["messages"] == ["preflight_failed"]
    assert response["items"][0]["status"] == "failed"
    assert "PDFは1ページ" in response["items"][0]["messages"][0]
    assert_no_pdfs(output_dir)


def test_sidecar_export_fails_when_reserved_output_path_appears_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)
    original_build_checks = sidecar._build_checks

    def build_checks_then_create_competing_file(request: dict[str, Any], checked_output_dir: Path):
        checks = original_build_checks(request, checked_output_dir)
        checked_output_dir.mkdir(parents=True, exist_ok=True)
        (checked_output_dir / "01_02_003.pdf").write_bytes(b"created after preflight")
        return checks

    monkeypatch.setattr(sidecar, "_build_checks", build_checks_then_create_competing_file)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    reserved_path = output_dir / "01_02_003.pdf"
    escaped_path = output_dir / "01_02_003_2.pdf"
    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["items"][0]["status"] == "failed"
    assert response["items"][0]["requested_filename"] == "01_02_003.pdf"
    assert Path(response["items"][0]["output_path"]) == reserved_path
    assert response["items"][0]["error_type"] == "FileExistsError"
    assert "Output path already exists" in response["items"][0]["error"]
    assert reserved_path.read_bytes() == b"created after preflight"
    assert not escaped_path.exists()


def test_sidecar_export_duplicate_requested_filenames_do_not_collide(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 2)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                segment(source, 1, 1),
                segment(source, 2, 2),
            ],
        }
    )

    output_paths = [Path(item["output_path"]) for item in response["items"]]
    assert response["ok"] is True
    assert response["summary"] == {"created": 2, "failed": 0}
    assert [item["requested_filename"] for item in response["items"]] == ["01_02_003.pdf", "01_02_003.pdf"]
    assert [path.name for path in output_paths] == ["01_02_003.pdf", "01_02_003_2.pdf"]
    assert len(set(output_paths)) == 2
    assert "Page 1" in pdf_text(output_paths[0])
    assert "Page 2" in pdf_text(output_paths[1])


def test_sidecar_preflight_and_export_block_when_existing_output_present(tmp_path: Path) -> None:
    # New behaviour: disk-level conflict => preflight can_run=False, export blocked.
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    existing_path = output_dir / "01_02_003.pdf"
    existing_path.write_bytes(b"existing")
    request = {
        "output_dir": str(output_dir),
        "segments": [
            segment(source, 1, 1),
            segment(source, 2, 2),
        ],
    }

    preflight_response = handle_request({"command": "preflight", **request})
    export_response = handle_request({"command": "export", **request})

    assert preflight_response["ok"] is True
    assert preflight_response["can_run"] is False
    assert any("output_exists" in check["messages"] for check in preflight_response["checks"])
    assert export_response["ok"] is False
    assert export_response["messages"] == ["preflight_failed"]
    assert export_response["summary"] == {"created": 0, "failed": 2}
    # Existing file must not be touched.
    assert existing_path.read_bytes() == b"existing"
    assert_no_pdfs(output_dir / "01_02_003_2.pdf")


def test_pdf_service_publish_file_exclusive_does_not_overwrite_existing_path(tmp_path: Path) -> None:
    source = tmp_path / "source.tmp"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"new")
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        PdfService.publish_file_exclusive(source, output)

    assert output.read_bytes() == b"existing"


def test_pdf_service_publish_file_exclusive_overwrites_when_flag_set(tmp_path: Path) -> None:
    source = tmp_path / "source.tmp"
    output = tmp_path / "output.pdf"
    source.write_bytes(b"new")
    output.write_bytes(b"existing")

    PdfService.publish_file_exclusive(source, output, overwrite=True)

    # 既存は新内容に置き換わり、temp(source) はアトミック置換で消費される。
    assert output.read_bytes() == b"new"
    assert not source.exists()


def test_sidecar_preflight_and_export_block_duplicate_overwrite_within_batch(tmp_path: Path) -> None:
    # 同名になる2セグメント × overwrite=ON × 同名の既存ファイルあり。
    # 先行セグメントが上書き予約したパスへ後続セグメントも到達すると、同一ファイルへ
    # 二重書き込み(後勝ち)になり created=2 でも1ファイルしか残らない。後続行は
    # duplicate_output_in_batch でブロックし、export を preflight_failed で止める。
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 4)
    existing_path = output_dir / "01_02_003.pdf"
    existing_path.write_bytes(b"existing")
    request = {
        "output_dir": str(output_dir),
        "segments": [
            segment(source, 1, 2),
            segment(source, 3, 4),
        ],
        "overwrite": True,
    }

    preflight_response = handle_request({"command": "preflight", **request})
    export_response = handle_request({"command": "export", **request})

    # 1行目は上書き予約(will_overwrite)、2行目は同名重複でブロック。
    assert preflight_response["ok"] is True
    assert preflight_response["can_run"] is False
    checks = preflight_response["checks"]
    assert checks[0]["ok"] is True
    assert checks[0]["will_overwrite"] is True
    assert "output_will_overwrite" in checks[0]["messages"]
    assert checks[1]["ok"] is False
    assert checks[1]["will_overwrite"] is False
    assert "duplicate_output_in_batch" in checks[1]["messages"]

    # export は止まり、既存ファイルは触られない（サイレント消失が起きない）。
    assert export_response["ok"] is False
    assert export_response["messages"] == ["preflight_failed"]
    assert export_response["summary"] == {"created": 0, "failed": 2}
    assert existing_path.read_bytes() == b"existing"
    assert_no_pdfs(output_dir / "01_02_003_2.pdf")


def test_sidecar_preflight_and_export_overwrite_existing_when_flag_set(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    existing_path = output_dir / "01_02_003.pdf"
    existing_path.write_bytes(b"existing")
    request = {
        "output_dir": str(output_dir),
        "segments": [segment(source, 1, 2)],
        "overwrite": True,
    }

    preflight_response = handle_request({"command": "preflight", **request})
    export_response = handle_request({"command": "export", **request})

    # 上書き許可で preflight は通り、既存衝突の行は will_overwrite として扱われる。
    assert preflight_response["can_run"] is True
    overwrite_checks = [c for c in preflight_response["checks"] if c["will_overwrite"]]
    assert len(overwrite_checks) == 1
    assert "output_will_overwrite" in overwrite_checks[0]["messages"]
    # 別名(_2)へ逃がさず、同名のまま上書きする。
    assert export_response["ok"] is True
    assert export_response["summary"] == {"created": 1, "failed": 0}
    assert not (output_dir / "01_02_003_2.pdf").exists()
    # 既存ファイルが実際に新しいPDFへ置き換わっている。
    assert existing_path.read_bytes() != b"existing"
    assert "Page 1" in pdf_text(existing_path)


def test_sidecar_export_partial_failure_includes_export_incomplete_in_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2セグメント中1つだけ split_pdf が失敗したとき、messages に export_incomplete が含まれること。"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 2)

    call_count = 0
    original_split_pdf = PdfProcessor.split_pdf

    def split_pdf_fail_on_second(seg: object, dest: object, overwrite: bool = False) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated write failure")
        return original_split_pdf(seg, dest, overwrite=overwrite)

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_pdf_fail_on_second))

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                segment(source, 1, 1, "1"),
                segment(source, 2, 2, "2"),
            ],
        }
    )

    assert response["ok"] is False
    assert response["summary"]["created"] == 1
    assert response["summary"]["failed"] == 1
    assert "export_incomplete" in response["messages"]


def test_sidecar_export_all_success_has_empty_messages(tmp_path: Path) -> None:
    """全セグメント成功時は messages が空リストであること。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["messages"] == []


def test_sidecar_export_all_failure_does_not_include_export_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全セグメント失敗（created=0）のときは export_incomplete を出さないこと。"""
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    def split_pdf_always_fail(seg: object, dest: object, overwrite: bool = False) -> object:
        raise RuntimeError("simulated total failure")

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_pdf_always_fail))

    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [segment(source, 1, 1)],
        }
    )

    assert response["ok"] is False
    assert response["summary"]["created"] == 0
    assert response["summary"]["failed"] == 1
    assert "export_incomplete" not in response["messages"]


# --- issue #130: 「失敗分のみ再出力」で output_filename(確定名)を指定する経路 ---


def test_pinned_output_filename_bypasses_name_generation(tmp_path: Path) -> None:
    """output_filename を指定した行は命名生成をスキップし、その名前で出力される。

    metadata は本来 01_02_003.pdf を生むが、確定名 pinned.pdf を指定すると出力は
    pinned.pdf になり、命名生成由来の 01_02_003.pdf は作られないこと。
    """
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    seg = segment(source, 1, 1)
    seg["output_filename"] = "pinned.pdf"
    response = handle_request(
        {"command": "export", "output_dir": str(output_dir), "segments": [seg]}
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert Path(response["items"][0]["output_path"]).name == "pinned.pdf"
    assert (output_dir / "pinned.pdf").exists()
    assert not (output_dir / "01_02_003.pdf").exists()


def test_pinned_output_filename_overwrites_existing_when_flag_set(tmp_path: Path) -> None:
    """本 issue の主目的: 確定名 + overwrite=True で既存ファイルを上書き再出力できる。

    上書きモードで一部失敗した後の「失敗分のみ再出力」を模す。初回に作られた X.pdf を
    確定名で再送し、overwrite=True で置換されること（sha256 が新内容と一致）。
    """
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 1)
    existing_path = output_dir / "01_02_003.pdf"
    existing_path.write_bytes(b"stale contents from a failed first attempt")

    seg = segment(source, 1, 1)
    seg["output_filename"] = "01_02_003.pdf"
    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [seg],
            "overwrite": True,
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["items"][0]["will_overwrite"] is True
    assert "output_will_overwrite" in response["items"][0]["messages"]
    # 既存の中身が実PDFへ置き換わっている（_2 に逃げていない）。
    assert existing_path.read_bytes() != b"stale contents from a failed first attempt"
    assert "Page 1" in pdf_text(existing_path)
    assert not (output_dir / "01_02_003_2.pdf").exists()


def test_pinned_output_retry_does_not_clobber_sibling(tmp_path: Path) -> None:
    """回帰の核: 確定名での再出力が兄弟セグメントの本命ファイルを侵さない。

    初回に本命 X.pdf(item[0]) と別名 X_2.pdf(item[1]) が作られ、item[1] だけ書き込み
    失敗した状況を模す。失敗行の確定名 X_2.pdf のみを overwrite=True で再送しても、
    本命 X.pdf はバイト不変であること（issue #130 で禁止した誤爆が起きない）。
    """
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    # 本命は既に正しく作られている（別内容で存在、上書き対象ではない）。
    primary = output_dir / "01_02_003.pdf"
    primary.write_bytes(b"the correct primary file, must not be touched")
    primary_before = primary.read_bytes()

    # 失敗していた2つ目(確定名 _2)だけを再出力する。
    seg = segment(source, 2, 2)
    seg["output_filename"] = "01_02_003_2.pdf"
    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [seg],
            "overwrite": True,
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert Path(response["items"][0]["output_path"]).name == "01_02_003_2.pdf"
    assert (output_dir / "01_02_003_2.pdf").exists()
    # 本命ファイルは一切変更されていない（誤爆していないことの明示的アサート）。
    assert primary.read_bytes() == primary_before


def test_pinned_output_filename_duplicate_within_batch_blocks(tmp_path: Path) -> None:
    """同一バッチ内で確定名が重複した場合は duplicate_output_in_batch でブロック（#126整合）。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    existing_path = output_dir / "dup.pdf"
    existing_path.write_bytes(b"existing")

    seg1 = segment(source, 1, 1)
    seg1["output_filename"] = "dup.pdf"
    seg2 = segment(source, 2, 2)
    seg2["output_filename"] = "dup.pdf"
    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [seg1, seg2],
            "overwrite": True,
        }
    )

    assert response["ok"] is False
    assert response["messages"] == ["preflight_failed"]
    assert response["summary"] == {"created": 0, "failed": 2}
    assert response["items"][0]["ok"] is True
    assert response["items"][1]["ok"] is False
    assert "duplicate_output_in_batch" in response["items"][1]["messages"]
    # ブロックされたので既存は触られない。
    assert existing_path.read_bytes() == b"existing"


def test_pinned_output_filename_creates_when_absent_without_overwrite(tmp_path: Path) -> None:
    """確定名がディスクに無ければ overwrite=False でも新規作成できる（手動削除後の再出力）。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    seg = segment(source, 1, 1)
    seg["output_filename"] = "01_02_003.pdf"
    response = handle_request(
        {"command": "export", "output_dir": str(output_dir), "segments": [seg]}
    )

    assert response["ok"] is True
    assert response["summary"] == {"created": 1, "failed": 0}
    assert response["items"][0]["will_overwrite"] is False
    assert (output_dir / "01_02_003.pdf").exists()


@pytest.mark.parametrize("evil_name", ["../evil.pdf", "sub/x.pdf", "sub\\x.pdf"])
def test_pinned_output_filename_rejects_path_traversal(tmp_path: Path, evil_name: str) -> None:
    """確定名がパス区切り・親参照を含む場合は invalid_output_filename でブロック（信頼境界）。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    seg = segment(source, 1, 1)
    seg["output_filename"] = evil_name
    response = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [seg],
            "overwrite": True,
        }
    )

    assert response["ok"] is False
    assert response["messages"] == ["preflight_failed"]
    assert response["items"][0]["ok"] is False
    assert "invalid_output_filename" in response["items"][0]["messages"]
    # 出力ディレクトリ外にも中にも不正ファイルが作られていない。
    assert_no_pdfs(output_dir)
    assert not (tmp_path / "evil.pdf").exists()


def test_pinned_output_filename_rejects_nonexistent_page(tmp_path: Path) -> None:
    """確定名指定でもページ範囲は検証する（存在しないページの再出力を弾く）。"""
    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    make_pdf(source, 1)

    seg = segment(source, 1, 2)  # PDFは1ページ
    seg["output_filename"] = "01_02_003.pdf"
    response = handle_request(
        {"command": "export", "output_dir": str(output_dir), "segments": [seg]}
    )

    assert response["ok"] is False
    assert response["summary"] == {"created": 0, "failed": 1}
    assert response["items"][0]["status"] == "failed"
    assert "PDFは1ページ" in response["items"][0]["messages"][0]
    assert_no_pdfs(output_dir)


def test_pinned_output_filename_end_to_end_retry_over_overwrite_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """end-to-end: 上書きモードで部分失敗 → 失敗分のみ再出力が成功する（本 issue の再現→解消）。

    1) 既存 X.pdf と Y.pdf を上書き対象として置く。
    2) overwrite=True で2セグメント export、2つ目だけ split_pdf が失敗する。
    3) 失敗した2つ目の確定名(items[1].output_path の basename)を overwrite=True で再送。
    4) 全件成功し、Y.pdf が新内容へ置き換わる。X.pdf は初回 export で置換済みで不変。
    """
    from pdf_splitter_tool.processor import PdfProcessor

    source = tmp_path / "source.pdf"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    make_pdf(source, 2)
    x_path = output_dir / "01_02_001.pdf"
    y_path = output_dir / "01_02_002.pdf"
    x_path.write_bytes(b"old X")
    y_path.write_bytes(b"old Y")

    call_count = 0
    original_split_pdf = PdfProcessor.split_pdf

    def split_pdf_fail_on_second(seg: object, dest: object, overwrite: bool = False) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated write failure on second segment")
        return original_split_pdf(seg, dest, overwrite=overwrite)

    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(split_pdf_fail_on_second))

    first = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [
                segment(source, 1, 1, "1"),
                segment(source, 2, 2, "2"),
            ],
            "overwrite": True,
        }
    )

    assert first["ok"] is False
    assert first["summary"] == {"created": 1, "failed": 1}
    assert first["items"][0]["status"] == "created"
    assert first["items"][1]["status"] == "failed"
    # 初回で X は上書き済み、Y は失敗したので旧内容のまま。
    assert x_path.read_bytes() != b"old X"
    x_after_first = x_path.read_bytes()
    assert y_path.read_bytes() == b"old Y"

    # split_pdf を通常動作へ戻して失敗分だけ再出力する。
    monkeypatch.setattr(PdfProcessor, "split_pdf", staticmethod(original_split_pdf))
    pinned = Path(first["items"][1]["output_path"]).name
    assert pinned == "01_02_002.pdf"
    retry_seg = segment(source, 2, 2, "2")
    retry_seg["output_filename"] = pinned
    retry = handle_request(
        {
            "command": "export",
            "output_dir": str(output_dir),
            "segments": [retry_seg],
            "overwrite": True,
        }
    )

    assert retry["ok"] is True
    assert retry["summary"] == {"created": 1, "failed": 0}
    assert retry["items"][0]["will_overwrite"] is True
    # Y が新内容へ置換され、X は初回のまま不変。
    assert y_path.read_bytes() != b"old Y"
    assert "Page 2" in pdf_text(y_path)
    assert x_path.read_bytes() == x_after_first
    assert not (output_dir / "01_02_002_2.pdf").exists()
