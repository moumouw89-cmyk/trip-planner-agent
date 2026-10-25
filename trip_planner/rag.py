from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import GUIDES_DB, GUIDES_DIR

try:
    import jieba

    jieba.setLogLevel(20)
except Exception:  # pragma: no cover - jieba is optional for tiny deployments
    jieba = None


@dataclass
class GuideHit:
    doc_id: str
    doc_name: str
    heading: str
    content: str
    score: float = 0.0

    def snippet(self, limit: int = 180) -> str:
        text = re.sub(r"\s+", " ", self.content).strip()
        return text[:limit] + ("..." if len(text) > limit else "")

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "heading": self.heading,
            "snippet": self.snippet(),
            "score": round(self.score, 4),
        }


def tokenize(text: str) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []
    if jieba is not None:
        raw = jieba.lcut(value)
    else:
        raw = re.split(r"[\s,，。！？、;；/|]+", value)
    tokens = []
    for token in raw:
        token = token.strip().lower()
        if len(token) < 1:
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        tokens.append(token)
    return tokens


def _chunks_from_markdown(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    title = path.stem
    chunks = []
    heading = "概览"
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip() or title
        elif line.startswith("## "):
            if buffer:
                chunks.append(
                    {"doc_id": path.stem, "doc_name": title, "heading": heading, "content": "\n".join(buffer).strip()}
                )
            heading = line[3:].strip()
            buffer = []
        elif line.strip():
            buffer.append(line.strip())
    if buffer:
        chunks.append(
            {"doc_id": path.stem, "doc_name": title, "heading": heading, "content": "\n".join(buffer).strip()}
        )
    return [chunk for chunk in chunks if chunk["content"]]


class GuideIndex:
    def __init__(self, db_path: str | Path = GUIDES_DB, guides_dir: str | Path = GUIDES_DIR):
        self.db_path = Path(db_path)
        self.guides_dir = Path(guides_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure()

    def ensure(self) -> None:
        if not self.db_path.exists():
            self.rebuild()
            return
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        finally:
            conn.close()
        if count == 0:
            self.rebuild()

    def rebuild(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    doc_name TEXT NOT NULL,
                    heading TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE chunks_fts USING fts5(
                    tokens, content, doc_name, heading, tokenize='unicode61'
                );
                """
            )
            for path in sorted(self.guides_dir.glob("*.md")):
                for chunk in _chunks_from_markdown(path):
                    tokens = " ".join(tokenize(chunk["content"] + " " + chunk["heading"]))
                    cur = conn.execute(
                        "INSERT INTO chunks (doc_id, doc_name, heading, content, tokens) VALUES (?, ?, ?, ?, ?)",
                        (chunk["doc_id"], chunk["doc_name"], chunk["heading"], chunk["content"], tokens),
                    )
                    conn.execute(
                        "INSERT INTO chunks_fts (rowid, tokens, content, doc_name, heading) VALUES (?, ?, ?, ?, ?)",
                        (cur.lastrowid, tokens, chunk["content"], chunk["doc_name"], chunk["heading"]),
                    )
            conn.commit()
        finally:
            conn.close()

    def search(self, city: str, query: str, limit: int = 5) -> list[GuideHit]:
        tokens = tokenize(query)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            if tokens:
                match = " OR ".join('"' + token.replace('"', "") + '"' for token in tokens[:8])
                rows = conn.execute(
                    """
                    SELECT c.*, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.id = chunks_fts.rowid
                    WHERE chunks_fts MATCH ? AND c.doc_id = ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (match, city, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT *, 0 AS rank FROM chunks WHERE doc_id = ? LIMIT ?",
                    (city, limit),
                ).fetchall()
            return [
                GuideHit(
                    doc_id=row["doc_id"],
                    doc_name=row["doc_name"],
                    heading=row["heading"],
                    content=row["content"],
                    score=abs(float(row["rank"] or 0)),
                )
                for row in rows
            ]
        finally:
            conn.close()
