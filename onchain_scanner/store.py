"""Persistence for scan results: SQLite (queryable) + optional CSV export."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS bytes32_hits (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chain      TEXT    NOT NULL,
    block      INTEGER NOT NULL,
    tx_hash    TEXT    NOT NULL,
    source     TEXT    NOT NULL,   -- calldata | log_topic | log_data
    position   INTEGER NOT NULL,
    selector   TEXT,
    contract   TEXT,
    word       TEXT    NOT NULL,   -- 64 hex chars, no 0x
    category   TEXT    NOT NULL,
    note       TEXT,
    value_dec  TEXT
);
CREATE INDEX IF NOT EXISTS idx_hits_category ON bytes32_hits(category);
CREATE INDEX IF NOT EXISTS idx_hits_word     ON bytes32_hits(word);
CREATE INDEX IF NOT EXISTS idx_hits_block    ON bytes32_hits(chain, block);
"""

COLUMNS = [
    "chain", "block", "tx_hash", "source", "position",
    "selector", "contract", "word", "category", "note", "value_dec",
]


class Store:
    def __init__(self, db_path: str):
        self.path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def add_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.conn.executemany(
            f"INSERT INTO bytes32_hits ({','.join(COLUMNS)}) "
            f"VALUES ({','.join('?' * len(COLUMNS))})",
            [tuple(r.get(c) for c in COLUMNS) for r in rows],
        )
        self.conn.commit()

    def counts_by_category(self) -> list[tuple[str, int]]:
        cur = self.conn.execute(
            "SELECT category, COUNT(*) FROM bytes32_hits "
            "GROUP BY category ORDER BY COUNT(*) DESC"
        )
        return cur.fetchall()

    def total(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM bytes32_hits").fetchone()[0]

    def export_csv(self, csv_path: str) -> int:
        cur = self.conn.execute(
            f"SELECT {','.join(COLUMNS)} FROM bytes32_hits ORDER BY id"
        )
        rows = cur.fetchall()
        Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows(rows)
        return len(rows)

    def close(self) -> None:
        self.conn.close()
