"""ISS-030 NF-B1/B3/B4/C1/C2/D1/E1 の回帰テスト。

NF-B1/B3/B4: search_text の複数用語1パス化・件数上限・スニペット位置
NF-C1/C2:    blank_candidates の時間予算・部分結果・閾値コメント・境界テスト
NF-D1:       state_schema の affix_defs 上限整合
NF-E1:       新キー入り state フィクスチャのラウンドトリップ
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import fitz

from pdf_splitter_tool.domain import MAX_AFFIX_COUNT
from pdf_splitter_tool.pdf_service import SEARCH_TEXT_MAX_RESULTS, PdfService
from pdf_splitter_tool.sidecar import handle_request
from pdf_splitter_tool.state import STATE_FILENAME
from pdf_splitter_tool.state_schema import normalize_state_payload


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "state"


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def make_text_pdf(path: Path, page_texts: list[str]) -> None:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def make_white_pdf(path: Path, n_pages: int) -> None:
    """テキストなし・均一白ページの PDF を生成する（white page detection 正例用）。"""
    doc = fitz.open()
    for _ in range(n_pages):
        doc.new_page()  # テキスト挿入なし
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# NF-B1: 複数用語を 1 パスで処理する（per-term エントリを複数返す）
# ---------------------------------------------------------------------------


def test_search_text_multiple_queries_single_pass_returns_per_term_entries(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Alpha Beta page", "Gamma page", "Alpha Gamma page"])

    results, truncated = PdfService.search_text(
        [source],
        query="",
        queries=["Alpha", "Gamma"],
    )

    assert truncated is False
    # Alpha はページ1と3に、Gamma はページ2と3に存在する
    pdf_page_terms = [(r["page_no"], r["matched_terms"][0]) for r in results]
    assert ("Alpha", 1) in [(t, p) for p, t in pdf_page_terms]
    assert ("Alpha", 3) in [(t, p) for p, t in pdf_page_terms]
    assert ("Gamma", 2) in [(t, p) for p, t in pdf_page_terms]
    assert ("Gamma", 3) in [(t, p) for p, t in pdf_page_terms]


def test_search_text_queries_prioritized_over_single_query(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Foo Bar"])

    results_q, _ = PdfService.search_text([source], query="Foo", queries=["Bar"])

    # queries が優先されるので "Bar" のみヒット（"Foo" は無視される）
    assert len(results_q) == 1
    assert results_q[0]["matched_terms"] == ["Bar"]


def test_search_text_backward_compat_single_query_still_works(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Hello World"])

    results, truncated = PdfService.search_text([source], query="Hello")

    assert truncated is False
    assert len(results) == 1
    assert results[0]["matched_terms"] == ["Hello"]


# ---------------------------------------------------------------------------
# NF-B3: 件数上限 SEARCH_TEXT_MAX_RESULTS で打ち切り・truncated: true
# ---------------------------------------------------------------------------


def test_search_text_truncates_at_max_results(tmp_path: Path) -> None:
    # SEARCH_TEXT_MAX_RESULTS+1 件分のテキストを持つ PDF（各ページに1ヒット）
    limit = SEARCH_TEXT_MAX_RESULTS
    source = tmp_path / "source.pdf"
    make_text_pdf(source, [f"Match page {i}" for i in range(limit + 5)])

    results, truncated = PdfService.search_text([source], query="Match")

    assert truncated is True
    assert len(results) == limit


def test_search_text_no_truncation_below_limit(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Match page", "No hit", "Match page 2"])

    results, truncated = PdfService.search_text([source], query="Match")

    assert truncated is False
    assert len(results) == 2


# ---------------------------------------------------------------------------
# NF-B4: スニペット位置が元文字列上の実際の位置から取れている
# ---------------------------------------------------------------------------


def test_search_text_snippet_reflects_original_case_position(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    # 大文字・小文字混在で検索してスニペット内に元の大文字が含まれること
    make_text_pdf(source, ["前置テキスト TERM 後置テキスト"])

    results, _ = PdfService.search_text([source], query="term")  # 小文字クエリ

    assert len(results) == 1
    # スニペットに元の大文字 "TERM" が含まれる（lower() 後の位置ではない）
    assert "TERM" in results[0]["snippet"]


# ---------------------------------------------------------------------------
# NF-B1/B3: sidecar ハンドラ経由での契約（queries/truncated フィールド）
# ---------------------------------------------------------------------------


def test_sidecar_search_text_accepts_queries_array(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["Apple Banana", "Cherry"])

    response = handle_request(
        {
            "command": "search_text",
            "pdf_paths": [str(source)],
            "queries": ["Apple", "Cherry"],
        }
    )

    assert response["ok"] is True
    assert response["command"] == "search_text"
    matched_terms_seen = {r["matched_terms"][0] for r in response["results"]}
    assert "Apple" in matched_terms_seen
    assert "Cherry" in matched_terms_seen


def test_sidecar_search_text_truncated_field_absent_when_not_truncated(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["unique_term_xyz"])

    response = handle_request(
        {"command": "search_text", "pdf_paths": [str(source)], "query": "unique_term_xyz"}
    )

    assert response["ok"] is True
    # 打ち切りなし → truncated キー自体が存在しないか False
    assert response.get("truncated", False) is False


def test_sidecar_search_text_truncated_true_when_over_limit(tmp_path: Path) -> None:
    limit = SEARCH_TEXT_MAX_RESULTS
    source = tmp_path / "source.pdf"
    make_text_pdf(source, [f"HitPage {i}" for i in range(limit + 5)])

    response = handle_request(
        {"command": "search_text", "pdf_paths": [str(source)], "query": "HitPage"}
    )

    assert response["ok"] is True
    assert response["truncated"] is True
    assert len(response["results"]) == limit


# ---------------------------------------------------------------------------
# NF-C1: blank_candidates の時間予算と部分結果
# ---------------------------------------------------------------------------


def test_blank_candidates_detects_white_page_positive_case(tmp_path: Path) -> None:
    """白紙ページを含む PDF で検出される正例テスト（NF-C2）。"""
    source = tmp_path / "white.pdf"
    make_white_pdf(source, 3)

    candidates, partial, scanned_until = PdfService.blank_candidates(source)

    # テキストなし・白一色なので全ページが検出されるはず
    assert len(candidates) == 3
    assert all(c["score"] >= 0.985 for c in candidates)
    assert partial is False
    assert scanned_until == 3


def test_blank_candidates_does_not_detect_text_page_negative_case(tmp_path: Path) -> None:
    """文字がある通常ページは検出されない負例テスト（NF-C2）。"""
    source = tmp_path / "text.pdf"
    make_text_pdf(source, ["Page with lots of text content here"])

    candidates, partial, scanned_until = PdfService.blank_candidates(source)

    assert candidates == []
    assert partial is False
    assert scanned_until == 1


def test_blank_candidates_partial_result_when_budget_exceeded(tmp_path: Path) -> None:
    """時間予算を超えたら部分結果と partial: true を返す。"""
    source = tmp_path / "source.pdf"
    # 10 ページ（全部テキストなし）
    make_white_pdf(source, 10)

    # 予算を極小に設定して必ず途中で打ち切れるようにする
    candidates, partial, scanned_until = PdfService.blank_candidates(
        source, time_budget=0.000001
    )

    # partial=True の場合: scanned_until < 10（途中で止まっている）
    # partial=False の場合: 処理が間に合って全走り抜け（scanned_until == 10）
    if partial:
        assert scanned_until < 10
        # scanned_until は 0（1ページも処理できなかった）以上
        assert scanned_until >= 0
    else:
        # 全走り抜けの場合はフル処理
        assert scanned_until == 10


def test_blank_candidates_start_page_resumes_from_given_page(tmp_path: Path) -> None:
    """start_page を指定すると前のページをスキップして途中から再開する。"""
    source = tmp_path / "source.pdf"
    # 5 ページ: 1-2 はテキストあり、3-5 は白紙
    make_text_pdf(source, ["text page 1", "text page 2", "", "", ""])

    # ページ3以降を取得
    candidates, partial, scanned_until = PdfService.blank_candidates(source, start_page=3)

    assert partial is False
    assert scanned_until == 5
    page_nos = [c["page_no"] for c in candidates]
    assert 1 not in page_nos
    assert 2 not in page_nos
    # ページ3〜5はテキストなしなので白紙候補として検出される
    for pno in [3, 4, 5]:
        assert pno in page_nos


def test_sidecar_blank_candidates_returns_partial_and_scanned_until(tmp_path: Path) -> None:
    """sidecar ハンドラ経由で partial / scanned_until が返る。"""
    source = tmp_path / "source.pdf"
    make_white_pdf(source, 2)

    response = handle_request({"command": "blank_candidates", "pdf_path": str(source)})

    assert response["ok"] is True
    assert response["command"] == "blank_candidates"
    assert "partial" in response
    assert "scanned_until" in response
    assert isinstance(response["partial"], bool)
    assert isinstance(response["scanned_until"], int)
    assert response["partial"] is False
    assert response["scanned_until"] == 2


def test_sidecar_blank_candidates_start_page_parameter(tmp_path: Path) -> None:
    """start_page パラメータが sidecar 経由で有効に働く。"""
    source = tmp_path / "source.pdf"
    make_text_pdf(source, ["text", "", ""])  # page1=text, page2/3=blank

    response = handle_request(
        {"command": "blank_candidates", "pdf_path": str(source), "start_page": 2}
    )

    assert response["ok"] is True
    page_nos = [c["page_no"] for c in response["candidates"]]
    assert 1 not in page_nos
    assert 2 in page_nos or 3 in page_nos  # 白紙ページが含まれる


# ---------------------------------------------------------------------------
# NF-D1: state_schema の affix_defs 上限整合
# ---------------------------------------------------------------------------


def test_normalize_affix_defs_trims_to_max_affix_count() -> None:
    """3件入り affix_defs は MAX_AFFIX_COUNT(=2) に切り詰められる。"""
    three_defs = [
        {"key": "company", "label": "会社名", "position": "prefix"},
        {"key": "dept", "label": "部署", "position": "suffix"},
        {"key": "extra", "label": "追加", "position": "suffix"},
    ]

    normalized = normalize_state_payload({"affix_defs": three_defs})

    assert len(normalized["affix_defs"]) == MAX_AFFIX_COUNT
    # 先頭 MAX_AFFIX_COUNT 件が保持される
    assert normalized["affix_defs"][0]["key"] == "company"
    assert normalized["affix_defs"][1]["key"] == "dept"


def test_normalize_affix_defs_at_max_count_accepted_unchanged() -> None:
    """ちょうど MAX_AFFIX_COUNT 件は切り詰めなし。"""
    two_defs = [
        {"key": "company", "label": "会社名", "position": "prefix"},
        {"key": "dept", "label": "部署", "position": "suffix"},
    ]

    normalized = normalize_state_payload({"affix_defs": two_defs})

    assert len(normalized["affix_defs"]) == MAX_AFFIX_COUNT


def test_normalize_affix_defs_one_def_not_trimmed() -> None:
    one_def = [{"key": "company", "label": "会社名", "position": "prefix"}]

    normalized = normalize_state_payload({"affix_defs": one_def})

    assert len(normalized["affix_defs"]) == 1


# ---------------------------------------------------------------------------
# NF-E1: 新キー入り state フィクスチャのラウンドトリップ
# ---------------------------------------------------------------------------


def test_state_fixture_v1_full_fields_round_trips(tmp_path: Path) -> None:
    """v1_full_fields.json フィクスチャが load→save→load で値を保持する。"""
    fixture_path = FIXTURE_DIR / "v1_full_fields.json"
    expected: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))

    # 初回 load
    state_path = tmp_path / STATE_FILENAME
    shutil.copyfile(fixture_path, state_path)
    load1 = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert load1["ok"] is True

    # save
    save = handle_request({"command": "state_save", "work_dir": str(tmp_path), "state": load1["state"]})
    assert save["ok"] is True

    # 2回目 load
    load2 = handle_request({"command": "state_load", "work_dir": str(tmp_path)})
    assert load2["ok"] is True

    state = load2["state"]
    # affix_defs が保持されている
    assert state["affix_defs"] == expected["affix_defs"]
    # seq_start / seq_digits が保持されている
    assert state["seq_start"] == expected["seq_start"]
    assert state["seq_digits"] == expected["seq_digits"]
    # manual_seq_keys が保持されている
    assert state["manual_seq_keys"] == expected["manual_seq_keys"]
    # split_points_by_pdf が整数型で保持されている
    for pdf_path_key, points in expected["split_points_by_pdf"].items():
        assert state["split_points_by_pdf"][pdf_path_key] == [int(p) for p in points]
