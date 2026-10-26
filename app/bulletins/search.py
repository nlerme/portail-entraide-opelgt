from __future__ import annotations

import re
import sqlite3
from typing import Any


def escape_fts_token(token: str) -> str:
    return f'"{token.strip().replace(chr(34), chr(34) * 2)}"'


def build_fts_query(keywords: str, mode: str) -> str:
    keywords = keywords.strip()
    mode = mode.lower().strip()
    if not keywords:
        raise ValueError("Veuillez saisir au moins un mot clé.")
    if mode == "raw":
        return keywords
    if mode == "phrase":
        return escape_fts_token(keywords)
    tokens = [token for token in re.split(r"\s+", keywords) if token.strip()]
    if not tokens:
        raise ValueError("Veuillez saisir au moins un mot clé.")
    if mode == "any":
        return " OR ".join(f"{escape_fts_token(token)}*" for token in tokens)
    return " ".join(f"{escape_fts_token(token)}*" for token in tokens)


def search_pages(
    conn: sqlite3.Connection,
    keywords: str,
    mode: str = "all",
    year_from: int | None = None,
    year_to: int | None = None,
    bulletin_from: int | None = None,
    bulletin_to: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    fts_query = build_fts_query(keywords, mode)
    where = ["pages_fts MATCH ?"]
    params: list[Any] = [fts_query]
    for field, operator, value in (
        ("year", ">=", year_from), ("year", "<=", year_to),
        ("number", ">=", bulletin_from), ("number", "<=", bulletin_to),
    ):
        if value is not None:
            where.append(f"CAST({field} AS INTEGER) {operator} ?")
            params.append(value)
    where_sql = " AND ".join(where)
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    total = int(conn.execute(f"SELECT COUNT(*) AS count FROM pages_fts WHERE {where_sql}", params).fetchone()["count"])
    rows = conn.execute(
        f"""
        SELECT rowid AS page_id,title,filename,bulletin_id,page_no,number,year,text_source,
               bm25(pages_fts) AS score,
               snippet(pages_fts,0,'[[[H]]]','[[[/H]]]','…',32) AS excerpt
        FROM pages_fts WHERE {where_sql}
        ORDER BY score ASC, CAST(number AS INTEGER) ASC, CAST(page_no AS INTEGER) ASC, filename ASC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {
        "total": total,
        "results": [
            {
                "pageId": row["page_id"], "bulletinId": row["bulletin_id"], "bulletinTitle": row["title"],
                "filename": row["filename"], "number": row["number"], "year": row["year"],
                "page": row["page_no"], "source": row["text_source"], "score": row["score"],
                "excerpt": row["excerpt"] or "",
                "pdfUrl": f"/api/bulletins/pdf/{row['bulletin_id']}#page={row['page_no']}",
            }
            for row in rows
        ],
        "query": fts_query,
    }
