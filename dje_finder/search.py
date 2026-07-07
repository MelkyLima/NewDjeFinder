import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dje_finder.config import Config
from dje_finder.persistence import get_db_connection


PAGE_SIZE = 50
SORT_RELEVANCE = "relevance"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
VALID_SORTS = {SORT_RELEVANCE, SORT_NEWEST, SORT_OLDEST}
MATCH_ALL_TERMS = "all_terms"
MATCH_EXACT_PHRASE = "exact_phrase"
MATCH_NEAR_CONTEXT = "near_context"
VALID_MATCH_MODES = {MATCH_ALL_TERMS, MATCH_EXACT_PHRASE, MATCH_NEAR_CONTEXT}


@dataclass(frozen=True)
class SearchResult:
    date_str: str
    display_date: str
    year: str
    month: str
    snippet: str
    pdf_path: Path


@dataclass(frozen=True)
class SearchResponse:
    query: str
    normalized_query: str
    results: list
    total: int
    offset: int
    limit: int
    year_counts: dict
    month_counts: dict
    total_pdfs: int
    indexed_pdfs: int
    failed_pdfs: int

    @property
    def has_more(self):
        return self.offset + len(self.results) < self.total

    @property
    def has_pending_indexing(self):
        return self.indexed_pdfs < self.total_pdfs


def format_date(date_str):
    if len(date_str) == 8:
        return f"{date_str[6:8]}/{date_str[4:6]}/{date_str[0:4]}"
    return date_str


def get_pdf_path(date_str):
    return Config.BASE_DIR / date_str[:4] / f"dpj-{date_str}.pdf"


def clean_snippet(snippet, max_length=220):
    snippet = re.sub(r"\s+", " ", snippet or "").strip()
    if len(snippet) <= max_length:
        return snippet
    return snippet[: max_length - 3].rstrip() + "..."


def normalize_fts_query(query):
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    terms = [term.strip() for term in terms if term.strip()]
    return " ".join(f'"{term}"' for term in terms)


def normalize_fts_phrase_query(query):
    terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
    terms = [term.strip() for term in terms if term.strip()]
    return f'"{" ".join(terms)}"' if terms else ""


def normalize_text_for_context(text):
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.casefold()


def tokenize_for_context(text):
    return re.findall(r"\w+", normalize_text_for_context(text), flags=re.UNICODE)


def find_phrase_positions(tokens, phrase):
    phrase_tokens = tokenize_for_context(phrase)
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return []
    size = len(phrase_tokens)
    return [
        index
        for index in range(0, len(tokens) - size + 1)
        if tokens[index : index + size] == phrase_tokens
    ]


def terms_are_near(content, main_query, related_query, distance):
    tokens = tokenize_for_context(content)
    main_positions = find_phrase_positions(tokens, main_query)
    related_positions = find_phrase_positions(tokens, related_query)
    if not main_positions or not related_positions:
        return False
    distance = max(0, int(distance or 0))
    for main_pos in main_positions:
        for related_pos in related_positions:
            if abs(main_pos - related_pos) <= distance:
                return True
    return False


def make_context_snippet(content, main_query, related_query, distance, max_length=220):
    words = re.findall(r"\w+|[^\w\s]+", content or "", flags=re.UNICODE)
    word_tokens = [token for token in words if re.match(r"\w+", token, flags=re.UNICODE)]
    normalized_words = tokenize_for_context(" ".join(word_tokens))
    main_positions = find_phrase_positions(normalized_words, main_query)
    related_positions = find_phrase_positions(normalized_words, related_query)
    if not main_positions or not related_positions:
        return clean_snippet(content, max_length)

    best_pair = min(
        ((abs(a - b), a, b) for a in main_positions for b in related_positions),
        default=(0, 0, 0),
    )
    _, start_a, start_b = best_pair
    center = min(start_a, start_b)
    start = max(0, center - min(max(distance // 2, 12), 45))
    end = min(len(word_tokens), max(start_a, start_b) + min(max(distance // 2, 24), 70))
    snippet = " ".join(word_tokens[start:end])
    return clean_snippet(f"...{snippet}...", max_length)


class PDFSearchEngine:
    def __init__(self, page_size=PAGE_SIZE):
        self.page_size = page_size

    def search(
        self,
        query,
        year=None,
        month=None,
        sort=SORT_RELEVANCE,
        offset=0,
        limit=None,
        match_mode=MATCH_ALL_TERMS,
        related_query=None,
        context_distance=50,
    ):
        match_mode = match_mode if match_mode in VALID_MATCH_MODES else MATCH_ALL_TERMS
        if match_mode == MATCH_NEAR_CONTEXT and related_query:
            normalized_query = normalize_fts_phrase_query(query)
            related_normalized_query = normalize_fts_phrase_query(related_query)
            prefilter_query = " ".join(part for part in [normalized_query, related_normalized_query] if part)
            normalized_query = prefilter_query
        elif match_mode == MATCH_EXACT_PHRASE:
            normalized_query = normalize_fts_phrase_query(query)
        else:
            normalized_query = normalize_fts_query(query)
        limit = limit or self.page_size
        offset = max(0, int(offset or 0))
        sort = sort if sort in VALID_SORTS else SORT_RELEVANCE

        stats = self.get_index_stats()
        if not normalized_query:
            return SearchResponse(
                query=query,
                normalized_query="",
                results=[],
                total=0,
                offset=offset,
                limit=limit,
                year_counts={},
                month_counts={},
                total_pdfs=stats["total_pdfs"],
                indexed_pdfs=stats["indexed_pdfs"],
                failed_pdfs=stats["failed_pdfs"],
            )

        conn = get_db_connection()
        try:
            params = [normalized_query]
            filters = ["pdf_pages_fts MATCH ?"]
            if year:
                filters.append("substr(f.date_str, 1, 4) = ?")
                params.append(str(year))
            if month:
                filters.append("substr(f.date_str, 5, 2) = ?")
                params.append(f"{int(month):02d}")

            where_sql = " AND ".join(filters)
            order_sql = self._order_sql(sort)
            cursor = conn.cursor()

            if match_mode == MATCH_NEAR_CONTEXT and related_query:
                matched_rows = self._near_context_rows(
                    cursor,
                    where_sql,
                    params,
                    query,
                    related_query,
                    context_distance,
                    sort,
                )
                total = len(matched_rows)
                year_counts = self._period_counts_from_rows(matched_rows, 0, 4)
                month_counts = self._period_counts_from_rows(
                    [row for row in matched_rows if not year or row["date_str"].startswith(str(year))],
                    4,
                    6,
                )
                page_rows = matched_rows[offset : offset + int(limit)]
                results = [
                    SearchResult(
                        date_str=row["date_str"],
                        display_date=format_date(row["date_str"]),
                        year=row["date_str"][:4],
                        month=row["date_str"][4:6],
                        snippet=make_context_snippet(
                            row["content"],
                            query,
                            related_query,
                            context_distance,
                        ),
                        pdf_path=get_pdf_path(row["date_str"]),
                    )
                    for row in page_rows
                ]
            else:
                count_sql = f"""
                    SELECT COUNT(*)
                    FROM pdf_pages_fts f
                    JOIN pdfs p ON p.date_str = f.date_str
                    WHERE {where_sql}
                """
                cursor.execute(count_sql, params)
                total = cursor.fetchone()[0]

                year_counts = self._counts(cursor, normalized_query, "substr(f.date_str, 1, 4)", None, None)
                month_counts = self._counts(cursor, normalized_query, "substr(f.date_str, 5, 2)", year, None)

                rows_sql = f"""
                    SELECT
                        f.date_str,
                        snippet(pdf_pages_fts, 1, '[', ']', '...', 18) AS snippet
                    FROM pdf_pages_fts f
                    JOIN pdfs p ON p.date_str = f.date_str
                    WHERE {where_sql}
                    {order_sql}
                    LIMIT ? OFFSET ?
                """
                cursor.execute(rows_sql, [*params, int(limit), offset])
                results = [
                    SearchResult(
                        date_str=row["date_str"],
                        display_date=format_date(row["date_str"]),
                        year=row["date_str"][:4],
                        month=row["date_str"][4:6],
                        snippet=clean_snippet(row["snippet"]),
                        pdf_path=get_pdf_path(row["date_str"]),
                    )
                    for row in cursor.fetchall()
                ]

            return SearchResponse(
                query=query,
                normalized_query=normalized_query,
                results=results,
                total=total,
                offset=offset,
                limit=limit,
                year_counts=year_counts,
                month_counts=month_counts,
                total_pdfs=stats["total_pdfs"],
                indexed_pdfs=stats["indexed_pdfs"],
                failed_pdfs=stats["failed_pdfs"],
            )
        except sqlite3.Error as error:
            raise SearchError(str(error)) from error
        finally:
            conn.close()

    def get_index_stats(self):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM pdfs")
            total_pdfs = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM indexed_pdfs WHERE status = 'SUCCESS'")
            indexed_pdfs = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM indexed_pdfs WHERE status = 'FAILED'")
            failed_pdfs = cursor.fetchone()[0]
            return {
                "total_pdfs": total_pdfs,
                "indexed_pdfs": indexed_pdfs,
                "failed_pdfs": failed_pdfs,
            }
        finally:
            conn.close()

    def _order_sql(self, sort):
        if sort == SORT_NEWEST:
            return "ORDER BY f.date_str DESC"
        if sort == SORT_OLDEST:
            return "ORDER BY f.date_str ASC"
        return "ORDER BY bm25(pdf_pages_fts), f.date_str DESC"

    def _near_context_rows(self, cursor, where_sql, params, query, related_query, distance, sort):
        order_sql = self._order_sql(sort)
        cursor.execute(
            f"""
            SELECT f.date_str, f.content
            FROM pdf_pages_fts f
            JOIN pdfs p ON p.date_str = f.date_str
            WHERE {where_sql}
            {order_sql}
            """,
            params,
        )
        rows = cursor.fetchall()
        return [
            row
            for row in rows
            if terms_are_near(row["content"], query, related_query, distance)
        ]

    def _period_counts_from_rows(self, rows, start, end):
        counts = {}
        for row in rows:
            period = row["date_str"][start:end]
            counts[period] = counts.get(period, 0) + 1
        return dict(sorted(counts.items(), reverse=True))

    def _counts(self, cursor, normalized_query, group_expr, year, month):
        params = [normalized_query]
        filters = ["pdf_pages_fts MATCH ?"]
        if year:
            filters.append("substr(f.date_str, 1, 4) = ?")
            params.append(str(year))
        if month:
            filters.append("substr(f.date_str, 5, 2) = ?")
            params.append(f"{int(month):02d}")
        where_sql = " AND ".join(filters)
        cursor.execute(
            f"""
            SELECT {group_expr} AS period, COUNT(*) AS total
            FROM pdf_pages_fts f
            JOIN pdfs p ON p.date_str = f.date_str
            WHERE {where_sql}
            GROUP BY period
            ORDER BY period DESC
            """,
            params,
        )
        return {row["period"]: row["total"] for row in cursor.fetchall()}


class SearchError(Exception):
    pass
