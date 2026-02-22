from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

APP_TZ = timezone(timedelta(hours=-5))

def _appdata_dir() -> Path:
    # Windows-friendly default; on non-Windows, fall back to ~/.config
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
        return base / "NAVI-CA"
    return Path.home() / ".config" / "NAVI-CA"

class NavicaDB:
    def __init__(self, db_path: str | None = None):
        self.base_dir = _appdata_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.out_dir = self.base_dir / "exports"
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = Path(db_path) if db_path else (self.base_dir / "navica.db")
        self.conn = sqlite3.connect(str(self.db_path))
        self._init()

    def ensure_out_dir(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        return self.out_dir

    def _init(self):
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS changes (
                change_id TEXT PRIMARY KEY,
                generated_at TEXT,
                findings_json TEXT
            )
        """)
        self.conn.commit()

    def save_change(self, change_id: str, findings: Dict[str, Any]):
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO changes(change_id, generated_at, findings_json)
            VALUES(?, ?, ?)
        """, (change_id, findings.get("generated_at"), json.dumps(findings)))
        self.conn.commit()

    def find_overlaps(self, change_id: str, objects: List[Dict[str, Any]], window_days: int = 30) -> List[Dict[str, Any]]:
        # Overlap vs prior stored changes in last N days (except itself)
        obj_set = set([o.get("normalized_key") for o in objects if o.get("normalized_key")])

        cur = self.conn.cursor()
        cur.execute("SELECT change_id, generated_at, findings_json FROM changes WHERE change_id <> ?", (change_id,))
        rows = cur.fetchall()

        overlaps = []
        now = datetime.now(APP_TZ)
        cutoff = now - timedelta(days=window_days)

        for cid, gen_at, fj in rows:
            try:
                if gen_at:
                    dt = datetime.fromisoformat(gen_at)
                    if dt < cutoff:
                        continue
                other = json.loads(fj)
                other_objs = set([r.get("normalized_key") for r in other.get("object_risks", []) if r.get("normalized_key")])
                # other stored is object_risks list; also accept stored objects if present
                if not other_objs and other.get("objects"):
                    other_objs = set([o.get("normalized_key") for o in other.get("objects", [])])

                shared = sorted(list(obj_set.intersection(other_objs)))
                if shared:
                    overlaps.append({
                        "other_change_id": cid,
                        "shared_object_count": len(shared),
                        "shared_objects": shared[:200],  # cap to keep UI responsive
                    })
            except Exception:
                continue

        overlaps.sort(key=lambda x: x["shared_object_count"], reverse=True)
        return overlaps[:25]
