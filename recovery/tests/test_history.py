import json
from pathlib import Path

from pdf_splitter_tool.history import OutputHistory


def test_output_history_appends_run_records(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)

    record = history.append_run(
        summary={"success": 1, "reused": 0, "skipped": 0, "failed": 0},
        items=[
            {
                "source_pdf": "source.pdf",
                "pages": "1,3",
                "metadata": {"seq": "1"},
                "output_path": "output/01.pdf",
                "status": "created",
                "warnings": [],
            }
        ],
    )

    payload = json.loads(history.history_path.read_text(encoding="utf-8"))
    assert record["version"] == 1
    assert payload["runs"][0]["summary"]["success"] == 1
    assert payload["runs"][0]["items"][0]["pages"] == "1,3"
    assert history.load()[0]["items"][0]["output_path"] == "output/01.pdf"


def test_output_history_archives_corrupt_file_before_appending(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)
    history.history_path.write_text("{not valid json", encoding="utf-8")

    record = history.append_run(
        summary={"success": 0, "reused": 0, "skipped": 0, "failed": 1},
        items=[{"source_pdf": "source.pdf", "status": "failed", "warnings": ["history repair"]}],
    )

    archived = list(tmp_path.glob("_pdf_split_history.json.corrupt*"))
    payload = json.loads(history.history_path.read_text(encoding="utf-8"))
    assert record["summary"]["failed"] == 1
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{not valid json"
    assert payload["runs"][0]["items"][0]["warnings"] == ["history repair"]


def test_output_history_load_archives_corrupt_file_and_returns_empty(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)
    history.history_path.write_text("{not valid json", encoding="utf-8")

    assert history.load() == []

    archived = list(tmp_path.glob("_pdf_split_history.json.corrupt*"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{not valid json"
    assert not history.history_path.exists()


def test_output_history_loads_tmp_when_history_file_is_missing(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)
    history.tmp_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "version": 1,
                        "created_at": "2026-05-25T00:00:00+00:00",
                        "summary": {"success": 1},
                        "items": [{"source_pdf": "source.pdf", "status": "created"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runs = history.load()

    assert runs[0]["summary"]["success"] == 1
    assert runs[0]["items"][0]["status"] == "created"
    assert history.history_path.exists()
    assert not history.tmp_path.exists()


def test_output_history_loads_tmp_after_archiving_corrupt_history(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)
    history.history_path.write_text("{broken history", encoding="utf-8")
    history.tmp_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runs": [
                    {
                        "version": 1,
                        "created_at": "2026-05-25T00:00:00+00:00",
                        "summary": {"success": 2},
                        "items": [{"source_pdf": "source.pdf", "status": "created"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runs = history.load()

    archived = list(tmp_path.glob("_pdf_split_history.json.corrupt*"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "{broken history"
    assert runs[0]["summary"]["success"] == 2


def test_output_history_archives_invalid_schema_before_appending(tmp_path: Path) -> None:
    history = OutputHistory(tmp_path)
    history.history_path.write_text(json.dumps({"version": 1, "runs": {"bad": "shape"}}), encoding="utf-8")

    history.append_run(
        summary={"success": 1, "reused": 0, "skipped": 0, "failed": 0},
        items=[{"source_pdf": "source.pdf", "status": "created", "warnings": []}],
    )

    archived = list(tmp_path.glob("_pdf_split_history.json.corrupt*"))
    payload = json.loads(history.history_path.read_text(encoding="utf-8"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["runs"] == {"bad": "shape"}
    assert payload["runs"][0]["summary"]["success"] == 1
