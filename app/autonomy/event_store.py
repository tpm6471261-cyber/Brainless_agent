"""SQLite persistence for bounded dashboard/event-bus history."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from threading import Lock
from app.autonomy.events import AutonomousEvent, EventType

class EventStore:
    def __init__(self, path: Path, retention: int = 20_000) -> None:
        path.parent.mkdir(parents=True,exist_ok=True); self.retention=retention; self._lock=Lock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS runtime_events(sequence INTEGER PRIMARY KEY,timestamp TEXT NOT NULL,event_type TEXT NOT NULL,mission_id TEXT,detail_json TEXT NOT NULL,correlation_id TEXT NOT NULL)"); self.db.commit()
    def store_event(self,event:AutonomousEvent)->None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO runtime_events VALUES (?,?,?,?,?,?)",(event.sequence,event.timestamp.isoformat(),event.type.value,event.mission_id,json.dumps(event.detail,sort_keys=True,default=str),event.correlation_id))
            self.db.execute("DELETE FROM runtime_events WHERE sequence NOT IN (SELECT sequence FROM runtime_events ORDER BY sequence DESC LIMIT ?)",(self.retention,)); self.db.commit()
    def recent(self,limit:int)->tuple[AutonomousEvent,...]:
        from datetime import datetime
        with self._lock: rows=self.db.execute("SELECT * FROM runtime_events ORDER BY sequence DESC LIMIT ?",(limit,)).fetchall()
        return tuple(AutonomousEvent(EventType(row[2]),row[3],json.loads(row[4]),datetime.fromisoformat(row[1]),row[5],row[0]) for row in reversed(rows))
    def close(self)->None:
        with self._lock: self.db.close()
