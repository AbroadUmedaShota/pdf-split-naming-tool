from __future__ import annotations

from .models import Segment


def split_boundary_pages(segments: list[Segment], page_count: int) -> set[int]:
    boundaries: set[int] = set()
    for segment in segments:
        boundary_page = segment.end_page + 1
        if 1 < boundary_page <= page_count:
            boundaries.add(boundary_page)
    return boundaries


def candidate_pages(search_hits: set[int], blank_candidates: set[int], index_candidates: set[int]) -> set[int]:
    return search_hits | blank_candidates | index_candidates


def page_badges(
    page_no: int,
    search_hits: set[int],
    blank_candidates: set[int],
    index_candidates: set[int],
    boundary_pages: set[int],
) -> list[str]:
    badges = []
    if page_no in blank_candidates:
        badges.append("白紙")
    if page_no in search_hits:
        badges.append("検索")
    if page_no in index_candidates:
        badges.append("索引")
    if page_no in boundary_pages:
        badges.append("分割前")
    return badges


def page_list_label(page_no: int, badges: list[str]) -> str:
    suffix = f" [{' '.join(badges)}]" if badges else ""
    return f"{page_no:>4}ページ{suffix}"


def visible_page_numbers(page_count: int, candidates: set[int], candidates_only: bool) -> list[int]:
    if candidates_only:
        return [page_no for page_no in range(1, page_count + 1) if page_no in candidates]
    return list(range(1, page_count + 1))


def segment_for_page(segments: list[Segment], page_no: int) -> Segment | None:
    for segment in segments:
        if segment.start_page <= page_no <= segment.end_page:
            return segment
    return None


def segment_state_text(segments: list[Segment], page_no: int, page_count: int) -> str:
    segment = segment_for_page(segments, page_no)
    if segment is not None:
        return f"所属セグメント: {segment.start_page}-{segment.end_page}ページ"
    start = max((item.end_page for item in segments), default=0) + 1
    if page_count:
        return f"未確定範囲: {start}-{page_count}ページ"
    return "PDF未選択"


def current_page_state_text(
    badges: list[str],
    current_page: int,
    has_current_pdf: bool,
    has_text_layer: bool,
    has_search_query_hit: bool,
    hit_count: int | None = None,
) -> str:
    state = " / ".join(badges) if badges else "通常ページ"
    if has_current_pdf and not has_text_layer:
        state += " / OCR検索には事前OCR済みPDFが必要"
    if has_search_query_hit:
        if hit_count is None:
            state += " / ページ内ヒット確認不可"
        else:
            state += f" / ページ内ヒット {hit_count}件"
    if current_page <= 1:
        state += " / 先頭ページのため前分割不可"
    return state
