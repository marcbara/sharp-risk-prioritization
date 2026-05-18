"""SHARP SQLite schema and DB initialization.

Schema:
  risks                     One row per project risk (the 7-field structure from
                            the prior LLM risk register work, plus optional
                            ground_truth_tier for evaluation).
  classifications           One row per AI tier classification (tier, confidence,
                            justification, model + timestamp). History-friendly:
                            new classifications append, allowing longitudinal
                            analysis of how a risk's tier evolves.
  events                    Project events that would trigger reclassification
                            cycles in the full system. Not exercised in the
                            minimal pipeline (single static pass), but the
                            schema supports it for the dynamic version.
"""

import csv
import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS risks (
    risk_id              INTEGER PRIMARY KEY,
    type                 TEXT NOT NULL,
    root_cause           TEXT,
    incident             TEXT,
    impact               TEXT,
    response_strategy    TEXT,
    response_action      TEXT,
    ground_truth_tier    TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    classification_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id              INTEGER NOT NULL REFERENCES risks(risk_id),
    tier                 TEXT NOT NULL CHECK (tier IN ('MONITOR','FLAG','ESCALATE')),
    confidence           REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    justification        TEXT NOT NULL,
    model                TEXT NOT NULL,
    classified_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    triggering_event_id  INTEGER REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS events (
    event_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type           TEXT NOT NULL,
    description          TEXT NOT NULL,
    occurred_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_classifications_risk_id ON classifications(risk_id);
CREATE INDEX IF NOT EXISTS idx_classifications_classified_at ON classifications(classified_at);
"""


def init_db(db_path: str, csv_path: Optional[str] = None) -> sqlite3.Connection:
    """Create schema. If csv_path is given, load risks from it."""
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    if csv_path and Path(csv_path).exists():
        cur = conn.cursor()
        # Idempotent reload: clear risks (cascading to classifications would
        # require FK enforcement; for this minimal pipeline we just delete both).
        cur.execute("DELETE FROM classifications")
        cur.execute("DELETE FROM risks")
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute(
                    """INSERT INTO risks
                       (risk_id, type, root_cause, incident, impact,
                        response_strategy, response_action, ground_truth_tier)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(row["Risk ID"]),
                        row["Type"],
                        row["Root Cause"],
                        row["Incident"],
                        row["Impact"],
                        row["Response Strategy"],
                        row["Response Action"],
                        row.get("ground_truth_tier"),
                    ),
                )
        conn.commit()
    return conn


def list_risks_for_classification(conn: sqlite3.Connection) -> list:
    """Return risks in the format the classifier expects (no ground truth leak)."""
    cur = conn.execute(
        """SELECT risk_id, type, root_cause, incident, impact,
                  response_strategy, response_action
           FROM risks ORDER BY risk_id"""
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def record_classification(
    conn: sqlite3.Connection,
    risk_id: int,
    tier: str,
    confidence: float,
    justification: str,
    model: str,
) -> None:
    conn.execute(
        """INSERT INTO classifications
           (risk_id, tier, confidence, justification, model)
           VALUES (?, ?, ?, ?, ?)""",
        (risk_id, tier, confidence, justification, model),
    )
    conn.commit()


if __name__ == "__main__":
    conn = init_db("sharp.db", "sharp_dataset.csv")
    n = conn.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
    print(f"Loaded {n} risks into sharp.db")
