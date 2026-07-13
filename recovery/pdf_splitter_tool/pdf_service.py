from __future__ import annotations

import base64
import os
import re
import time
from uuid import uuid4
from hashlib import sha256
from pathlib import Path

from .models import Segment

try:
    import fitz
except Exception:  # pragma: no cover - depends on local runtime
    fitz = None


MAX_PREVIEW_SIDE_PX = 2400
THUMBNAIL_ZOOM = 0.22
INDEX_CANDIDATE_KEYWORDS = ("インデックス", "目次", "表紙", "区切り", "No.", "番号", "会社名", "書類名")
# 検索結果の上限。これを超えた分は打ち切り、レスポンスに truncated: true を付与する。
SEARCH_TEXT_MAX_RESULTS = 200
# blank_candidates の時間予算（秒）。スキャンPDF全ページ pixmap 化は数十秒になりうるため、
# 予算超過時は途中まで処理した部分結果を返す（partial: true + scanned_until で続きを要求可能）。
BLANK_CANDIDATES_TIME_BUDGET_SECONDS = 8.0


class PdfService:
    @staticmethod
    def _require_fitz():
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for PDF operations.")
        return fitz

    @staticmethod
    def _open_doc(pdf_path, fitz_module=None):
        """Open a PDF document and raise ValueError for password-protected files.

        Returns the fitz.Document. Callers are responsible for closing it
        (use as a context manager or call .close() explicitly).
        """
        if fitz_module is None:
            fitz_module = PdfService._require_fitz()
        doc = fitz_module.open(pdf_path)
        if doc.needs_pass:
            doc.close()
            raise ValueError(
                "パスワード付きPDFには対応していません。"
                f" ({Path(pdf_path).name})"
            )
        return doc

    @staticmethod
    def one_based_page_to_fitz_index(page_no: int) -> int:
        page_no = int(page_no)
        if page_no < 1:
            raise ValueError("PDF page numbers are 1-based and must be positive.")
        return page_no - 1

    @staticmethod
    def one_based_range_to_fitz_indexes(page_count: int, start_page: int, end_page: int) -> tuple[int, int]:
        start_index = PdfService.one_based_page_to_fitz_index(start_page)
        end_index = PdfService.one_based_page_to_fitz_index(end_page)
        if end_index < start_index:
            raise ValueError("PDF page range end must be greater than or equal to start.")
        if end_index >= page_count:
            raise ValueError("PDF page range exceeds document page count.")
        return start_index, end_index

    @staticmethod
    def ensure_unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 2
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def page_count(pdf_path: Path) -> int:
        fitz_module = PdfService._require_fitz()
        with PdfService._open_doc(pdf_path, fitz_module) as doc:
            return doc.page_count

    @staticmethod
    def _bounded_preview_zoom(page_rect, requested_zoom: float) -> float:
        max_page_side = max(float(page_rect.width), float(page_rect.height))
        requested_zoom = float(requested_zoom)
        if max_page_side <= 0:
            return requested_zoom

        max_zoom = MAX_PREVIEW_SIDE_PX / max_page_side
        return min(requested_zoom, max_zoom)

    @staticmethod
    def page_preview_data_url(pdf_path: Path, page_no: int, zoom: float = 1.2) -> str:
        data_url, _page_count = PdfService.page_preview_data_url_with_count(pdf_path, page_no, zoom)
        return data_url

    @staticmethod
    def page_preview_data_url_with_count(pdf_path: Path, page_no: int, zoom: float = 1.2) -> tuple[str, int]:
        """Return (data_url, page_count) using a single fitz.open call.

        Raises ValueError for out-of-range page_no or password-protected files.
        Error message uses "page_no must be between 1 and {page_count}" to preserve
        the sidecar contract expected by existing tests.
        """
        fitz_module = PdfService._require_fitz()
        with PdfService._open_doc(pdf_path, fitz_module) as doc:
            page_count = doc.page_count
            page_no = int(page_no)
            if page_no < 1 or page_no > page_count:
                raise ValueError(f"page_no must be between 1 and {page_count}")
            page_index = page_no - 1
            page = doc.load_page(page_index)
            bounded_zoom = PdfService._bounded_preview_zoom(page.rect, zoom)
            pixmap = page.get_pixmap(matrix=fitz_module.Matrix(bounded_zoom, bounded_zoom), alpha=False)
        # JPEG にするとスキャン由来PDF（写真的な内容）でPNG比 数分の1 のペイロードになり、
        # sidecar との JSON パイプ転送が軽くなる。品質75は分割位置確認の用途に十分。
        encoded = base64.b64encode(pixmap.tobytes("jpg", jpg_quality=75)).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", page_count

    @staticmethod
    def page_thumbnail_data_url(pdf_path: Path, page_no: int, zoom: float = THUMBNAIL_ZOOM) -> str:
        return PdfService.page_preview_data_url(pdf_path, page_no, zoom)

    @staticmethod
    def page_thumbnail_data_url_with_count(pdf_path: Path, page_no: int, zoom: float = THUMBNAIL_ZOOM) -> tuple[str, int]:
        """Return (data_url, page_count) using a single fitz.open call."""
        return PdfService.page_preview_data_url_with_count(pdf_path, page_no, zoom)

    @staticmethod
    def page_text(pdf_path: Path, page_no: int) -> str:
        text, _page_count = PdfService.page_text_with_count(pdf_path, page_no)
        return text

    @staticmethod
    def page_text_with_count(pdf_path: Path, page_no: int) -> tuple[str, int]:
        """Return (text, page_count) using a single fitz.open call.

        Raises ValueError for out-of-range page_no or password-protected files.
        """
        fitz_module = PdfService._require_fitz()
        with PdfService._open_doc(pdf_path, fitz_module) as doc:
            page_count = doc.page_count
            page_no = int(page_no)
            if page_no < 1 or page_no > page_count:
                raise ValueError(f"page_no must be between 1 and {page_count}")
            page_index = page_no - 1
            return doc.load_page(page_index).get_text("text").strip(), page_count

    @staticmethod
    def search_text(
        pdf_paths: list[Path],
        query: str,
        current_pdf: Path | None = None,
        queries: list[str] | None = None,
    ) -> tuple[list[dict[str, object]], bool]:
        """全PDFを対象にテキスト検索する。

        複数用語を受け取り、1ページにつき get_text を1回だけ実行して全用語を照合する
        （NF-B1: 用語数×ページ数のテキスト抽出コストを削減）。

        queries が与えられた場合は queries を優先し、query は後方互換として単独用語に使う。
        results の各エントリ形状はフロント既存のマージロジックと互換（per-term エントリ）:
        {pdf_path, page_no, count, snippet, matched_terms, has_text, is_current_pdf}

        returns: (results, truncated)
          - truncated が True の場合は SEARCH_TEXT_MAX_RESULTS で打ち切られている。
        """
        # queries 優先、なければ query を単一用語として扱う
        raw_terms: list[str]
        if queries is not None:
            raw_terms = [q.strip() for q in queries if q.strip()]
        else:
            stripped = query.strip()
            raw_terms = [stripped] if stripped else []

        if not raw_terms:
            return [], False

        # 用語ごとに1回だけコンパイル（ページ×用語ループ内での毎回 re.escape+compile を避ける）
        term_patterns = [(term, re.compile(re.escape(term), re.IGNORECASE)) for term in raw_terms]

        fitz_module = PdfService._require_fitz()
        results: list[dict[str, object]] = []
        truncated = False

        for pdf_path in pdf_paths:
            is_current = current_pdf is not None and pdf_path == current_pdf
            with PdfService._open_doc(pdf_path, fitz_module) as doc:
                for page_index in range(doc.page_count):
                    if len(results) >= SEARCH_TEXT_MAX_RESULTS:
                        truncated = True
                        break
                    # 1ページ1回のテキスト抽出で全用語を照合（NF-B1）
                    text = doc.load_page(page_index).get_text("text")
                    has_text = bool(text.strip())
                    for term, compiled in term_patterns:
                        if len(results) >= SEARCH_TEXT_MAX_RESULTS:
                            truncated = True
                            break
                        # NF-B4: compiled.search で元文字列上の実際の位置からスニペットを取る
                        # findall を先に取って matches を再利用し、search の重複呼び出しを避ける
                        matches = compiled.findall(text)
                        if not matches:
                            continue
                        count = len(matches)
                        match = compiled.search(text)
                        start = match.start()  # type: ignore[union-attr]  # findall hit guarantees match
                        snippet_start = max(0, start - 28)
                        snippet_end = min(len(text), start + len(term) + 42)
                        snippet = " ".join(text[snippet_start:snippet_end].split())
                        results.append(
                            {
                                "pdf_path": str(pdf_path),
                                "page_no": page_index + 1,
                                "count": count,
                                "snippet": snippet,
                                "matched_terms": [term],
                                "has_text": has_text,
                                "is_current_pdf": is_current,
                            }
                        )
                else:
                    # 内側ループが break なく完了した場合のみ続行（break で外にも抜ける）
                    continue
                break

        return results, truncated

    @staticmethod
    def search_highlights(pdf_path: Path, page_no: int, query: str) -> list[dict[str, float]]:
        rects, _page_count = PdfService.search_highlights_with_count(pdf_path, page_no, query)
        return rects

    @staticmethod
    def search_highlights_with_count(pdf_path: Path, page_no: int, query: str) -> tuple[list[dict[str, float]], int]:
        """Return (rects, page_count) using a single fitz.open call.

        Raises ValueError for out-of-range page_no or password-protected files.
        Returns ([], page_count) when query is empty.
        """
        query = query.strip()
        fitz_module = PdfService._require_fitz()
        with PdfService._open_doc(pdf_path, fitz_module) as doc:
            page_count = doc.page_count
            if not query:
                return [], page_count
            page_no = int(page_no)
            if page_no < 1 or page_no > page_count:
                raise ValueError(f"page_no must be between 1 and {page_count}")
            page_index = page_no - 1
            page = doc.load_page(page_index)
            page_rect = page.rect
            rects = []
            for rect in page.search_for(query):
                rects.append(
                    {
                        "x0": round(float(rect.x0), 3),
                        "y0": round(float(rect.y0), 3),
                        "x1": round(float(rect.x1), 3),
                        "y1": round(float(rect.y1), 3),
                        "page_width": round(float(page_rect.width), 3),
                        "page_height": round(float(page_rect.height), 3),
                    }
                )
            return rects, page_count

    @staticmethod
    def index_candidates(pdf_paths: list[Path], keywords: list[str] | None = None) -> list[dict[str, object]]:
        candidate_keywords = [keyword.strip() for keyword in (keywords or list(INDEX_CANDIDATE_KEYWORDS)) if keyword.strip()]
        if not candidate_keywords:
            return []

        fitz_module = PdfService._require_fitz()
        results: list[dict[str, object]] = []
        for pdf_path in pdf_paths:
            with PdfService._open_doc(pdf_path, fitz_module) as doc:
                for page_index in range(doc.page_count):
                    text = doc.load_page(page_index).get_text("text")
                    if not text.strip():
                        continue
                    text_lower = text.lower()
                    matched = [keyword for keyword in candidate_keywords if keyword.lower() in text_lower]
                    if not matched:
                        continue
                    snippet = " ".join(text.split())[:120]
                    results.append(
                        {
                            "pdf_path": str(pdf_path),
                            "page_no": page_index + 1,
                            "score": round(min(1.0, len(matched) / 3), 4),
                            "reason": " / ".join(matched),
                            "snippet": snippet,
                        }
                    )
        return results

    @staticmethod
    def blank_candidates(
        pdf_path: Path,
        threshold: float = 0.985,
        start_page: int = 1,
        time_budget: float = BLANK_CANDIDATES_TIME_BUDGET_SECONDS,
    ) -> tuple[list[dict[str, object]], bool, int]:
        """白紙ページ候補を検出する。

        閾値設計（偽陰性側に倒す）:
          threshold=0.985: 輝度245以上のピクセルが98.5%以上を白紙とみなす。
          グレー地や薄い影・ウォーターマークがある実務用紙では検出されない設計
          （偽陰性=取りこぼし方向）。スキャン由来の均一白ページは確実に検出される。
          輝度245の根拠: RGB各ch=245/255≈0.96 相当で視覚上はほぼ白だが、
          スキャンノイズによる微妙な色付きを除外できる最小余裕。

        start_page: 1始まりのページ番号。前回 scanned_until+1 を渡すと続きを取得できる。
        time_budget: 単調時計で計測する上限秒数。予算超過時は部分結果で打ち切る。

        returns: (candidates, partial, scanned_until)
          - partial が True の場合は時間予算超過による途中打ち切り。
          - scanned_until は最後に判定したページ番号（1始まり）。完走時は page_count と一致。
        """
        fitz_module = PdfService._require_fitz()
        candidates: list[dict[str, object]] = []
        partial = False
        deadline = time.monotonic() + time_budget

        with PdfService._open_doc(pdf_path, fitz_module) as doc:
            page_count = doc.page_count
            # start_page を 1始まりでクランプ
            start_index = max(0, int(start_page) - 1)
            scanned_until = start_index  # ループ前の初期値（0件の場合に使う）
            for page_index in range(start_index, page_count):
                if time.monotonic() > deadline:
                    partial = True
                    break
                scanned_until = page_index + 1  # 1始まりページ番号
                page = doc.load_page(page_index)
                text = page.get_text("text").strip()
                if text:
                    # テキスト層があるページは白紙ではない
                    continue
                # テキスト層なし（スキャンPDF等）: pixmap で輝度判定
                pixmap = page.get_pixmap(
                    matrix=fitz_module.Matrix(0.08, 0.08),
                    alpha=False,
                    colorspace=fitz_module.csGRAY,
                )
                samples = pixmap.samples
                if not samples:
                    continue
                whiteish = sum(1 for value in samples if value >= 245)
                score = whiteish / len(samples)
                if score >= threshold:
                    candidates.append({"page_no": page_index + 1, "score": round(score, 4)})
            else:
                # ループを break せず完走した場合は scanned_until = page_count
                scanned_until = page_count

        return candidates, partial, scanned_until

    @staticmethod
    def calculate_sha256(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def split_pdf(segment: Segment, output_path: Path, overwrite: bool = False) -> Path:
        fitz_module = PdfService._require_fitz()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
        with PdfService._open_doc(segment.pdf_path, fitz_module) as src:
            start_index, end_index = PdfService.one_based_range_to_fitz_indexes(
                src.page_count,
                segment.start_page,
                segment.end_page,
            )
            with fitz_module.open() as dst:
                dst.insert_pdf(src, from_page=start_index, to_page=end_index)
                dst.save(temp_path)
        try:
            PdfService.publish_file_exclusive(temp_path, output_path, overwrite=overwrite)
        finally:
            temp_path.unlink(missing_ok=True)
        return output_path

    @staticmethod
    def publish_file_exclusive(source_path: Path, output_path: Path, overwrite: bool = False) -> None:
        if overwrite:
            # アトミック置換。新ファイルは temp(source_path) に書き終えてあるので、
            # 既存の出力は置換が成立する瞬間まで残る（書き込み途中で原本を壊さない）。
            os.replace(source_path, output_path)
            return

        # 完成済みtempだけを最終名へ原子的に公開する。Windowsのrenameは既存名を置換せず、
        # Windows以外では同一ディレクトリ内のhard linkが同じno-replace性を持つ。
        # コピー途中のプロセス終了で、不完全なPDFが正規名に残ることを避ける。
        try:
            if os.name == "nt":
                os.rename(source_path, output_path)
            else:
                os.link(source_path, output_path)
        except FileExistsError as exc:
            raise FileExistsError(f"Output path already exists: {output_path}") from exc
