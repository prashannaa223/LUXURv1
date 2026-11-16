import json
import os
import sqlite3
import threading
import time
from datetime import datetime

import psutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "Data", "luxur.db")
CHATLOG_PATH = os.path.join(ROOT_DIR, "Data", "ChatLog.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    ended_at TEXT,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    role TEXT,
    content TEXT,
    created_at TEXT,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT CHECK(kind IN ('episodic','semantic','procedural','project')),
    content TEXT,
    source TEXT CHECK(source IN ('user','ai','verified')),
    importance INTEGER DEFAULT 5,
    project_id INTEGER,
    created_at TEXT,
    updated_at TEXT,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS memory_links (
    memory_id INTEGER,
    related_id INTEGER,
    relation TEXT
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    status TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    name TEXT,
    role TEXT,
    instructions TEXT,
    model_key TEXT,
    tools_json TEXT,
    status TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER,
    task_id INTEGER,
    input TEXT,
    output TEXT,
    status TEXT,
    error TEXT,
    started TEXT,
    finished TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    agent_id INTEGER,
    title TEXT,
    intent TEXT,
    plan_json TEXT,
    status TEXT,
    result_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS strands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    steps_json TEXT,
    schedule TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS strand_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strand_id INTEGER,
    status TEXT,
    started TEXT,
    finished TEXT,
    log_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    source TEXT,
    level TEXT,
    type TEXT,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS permissions (
    action_key TEXT PRIMARY KEY,
    risk_level TEXT,
    allowed INTEGER DEFAULT 0,
    ask_each_time INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tool_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    agent_id INTEGER,
    tool TEXT,
    args_json TEXT,
    risk_level TEXT,
    result TEXT,
    approved_by TEXT
);
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    cpu REAL,
    ram REAL,
    active_agents INTEGER,
    state TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""

DEFAULT_AGENTS = [
    ("executive_assistant", "Executive Assistant Agent", "Schedules, reminders, daily briefings, task organization", "chat", "[]", "idle"),
    ("research", "Research Agent", "Deep research, source gathering, structured analysis", "search", '["web_search"]', "idle"),
    ("coding", "Coding Agent", "Programming assistance, debugging, code generation", "chat", '["files"]', "idle"),
    ("business_strategy", "Business Strategy Agent", "Business models, market strategy, planning", "chat", "[]", "idle"),
    ("financial_analysis", "Financial Analysis Agent", "Financial statements, ratios, stock research, NEPSE", "search", '["web_search"]', "idle"),
    ("writing", "Writing Agent", "Writing, editing, content production", "chat", '["files"]', "idle"),
    ("productivity", "Productivity Agent", "Workflow suggestions, focus, task management", "chat", "[]", "idle"),
    ("desktop_operator", "Desktop Operator Agent", "Desktop control: apps, mouse, keyboard, windows", "chat", '["desktop_control"]', "idle"),
    ("memory", "Memory Agent", "Memory management, retrieval, summarization", "chat", '["memory"]', "idle"),
]

VOICE_STATE_MAP = {
    "Available ...": "IDLE",
    "Listening ...": "LISTENING",
    "Thinking ...": "THINKING",
    "Searching ...": "PROCESSING",
    "Answering ...": "SPEAKING",
    "Translating ...": "PROCESSING",
}


class EventBus:
    def __init__(self, db_execute):
        self._execute = db_execute
        self._subscribers = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type, callback):
        with self._lock:
            self._subscribers.setdefault(event_type, []).append(callback)

    def publish(self, event_type, payload=None, source="system", level="info"):
        ts = datetime.now().isoformat(timespec="seconds")
        try:
            self._execute(
                "INSERT INTO events (ts, source, level, type, payload_json) VALUES (?,?,?,?,?)",
                (ts, source, level, event_type, json.dumps(payload or {})),
            )
        except Exception as e:
            print(f"[PulseHub] event insert failed: {e}")
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, []))
            callbacks += list(self._subscribers.get("*", []))
        for cb in callbacks:
            try:
                cb({"type": event_type, "payload": payload, "source": source, "level": level, "ts": ts})
            except Exception as e:
                print(f"[PulseHub] subscriber error: {e}")


class PulseHub:
    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        self.voice_state = "IDLE"
        self.active_agents = 0
        self.event_bus = EventBus(self._execute)
        self._telemetry_stop = threading.Event()
        self._telemetry_thread = threading.Thread(target=self._telemetry_loop, daemon=True)
        self._telemetry_thread.start()

        self._seed_agents()
        self.event_bus.publish("hub.started", {"db": DB_PATH})

    def _execute(self, sql, params=()):
        try:
            with self._lock:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
        except Exception as e:
            print(f"[PulseHub] write failed: {e}")

            class _FailedResult:
                lastrowid = -1
            return _FailedResult()

    def _query(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def _seed_agents(self):
        count = self._query("SELECT COUNT(*) AS c FROM agents")[0]["c"]
        if count == 0:
            now = datetime.now().isoformat(timespec="seconds")
            for key, name, role, model_key, tools, status in DEFAULT_AGENTS:
                self._execute(
                    "INSERT INTO agents (key, name, role, instructions, model_key, tools_json, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (key, name, role, "", model_key, tools, status, now),
                )

    def _telemetry_loop(self):
        while not self._telemetry_stop.wait(5):
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                ts = datetime.now().isoformat(timespec="seconds")
                self._execute(
                    "INSERT INTO telemetry (ts, cpu, ram, active_agents, state) VALUES (?,?,?,?,?)",
                    (ts, cpu, ram, self.active_agents, self.voice_state),
                )
            except Exception as e:
                print(f"[PulseHub] telemetry error: {e}")

    def set_voice_state(self, status_text):
        state = VOICE_STATE_MAP.get(status_text, status_text.upper())
        self.voice_state = state
        self.event_bus.publish("voice.state", {"state": state, "text": status_text}, source="voice_engine")

    def current_session(self):
        row = self._query("SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        if row:
            return row[0]["id"]
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._execute("INSERT INTO sessions (started_at) VALUES (?)", (now,))
        return cur.lastrowid

    def end_session(self):
        row = self._query("SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
        if row:
            self._execute(
                "UPDATE sessions SET ended_at=? WHERE id=?",
                (datetime.now().isoformat(timespec="seconds"), row[0]["id"]),
            )

    def log_conversation(self, user_text, assistant_text, meta=None):
        session_id = self.current_session()
        now = datetime.now().isoformat(timespec="seconds")
        self._execute(
            "INSERT INTO messages (session_id, role, content, created_at, meta_json) VALUES (?,?,?,?,?)",
            (session_id, "user", user_text, now, json.dumps(meta or {})),
        )
        self._execute(
            "INSERT INTO messages (session_id, role, content, created_at, meta_json) VALUES (?,?,?,?,?)",
            (session_id, "assistant", assistant_text, now, json.dumps(meta or {})),
        )
        self._append_chatlog_json([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])

    def _append_chatlog_json(self, entries):
        try:
            data = []
            if os.path.exists(CHATLOG_PATH):
                with open(CHATLOG_PATH, "r", encoding="utf-8-sig") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
            data.extend(entries)
            with open(CHATLOG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"[PulseHub] chatlog bridge error: {e}")

    def recent_messages(self, limit=10):
        session_id = self.current_session()
        rows = self._query(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(rows))

    def recent_messages_any(self, limit=10):
        """Last messages across ALL sessions, so context survives restarts."""
        rows = self._query(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return list(reversed(rows))

    def add_memory(self, content, kind="semantic", source="user", importance=5):
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._execute(
            "INSERT INTO memories (kind, content, source, importance, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (kind, content, source, importance, now, now),
        )
        self.event_bus.publish("memory.created", {"id": cur.lastrowid, "kind": kind}, source="memory")
        return cur.lastrowid

    @staticmethod
    def _significant_words(text):
        stop = {"this", "that", "with", "from", "have", "what", "when", "your", "about",
                "like", "just", "they", "will", "would", "there", "their", "which"}
        return {
            w for w in text.lower().replace("?", " ").replace(".", " ")
            .replace(",", " ").replace("!", " ").split()
            if len(w) > 3 and w not in stop
        }

    def add_memory_with_links(self, content, kind="semantic", source="ai", importance=5):
        """Store a memory and auto-link it to related ones (Obsidian-style graph)."""
        memory_id = self.add_memory(content, kind=kind, source=source, importance=importance)
        words = self._significant_words(content)
        for rel in self.search_memories(content, limit=8):
            if rel["id"] == memory_id:
                continue
            overlap = words & self._significant_words(rel["content"])
            if len(overlap) >= 2:
                self._execute(
                    "INSERT OR IGNORE INTO memory_links (memory_id, related_id, relation) VALUES (?,?,?)",
                    (memory_id, rel["id"], "related"),
                )
                self._execute(
                    "INSERT OR IGNORE INTO memory_links (memory_id, related_id, relation) VALUES (?,?,?)",
                    (rel["id"], memory_id, "related"),
                )
        return memory_id

    def linked_memories(self, memory_id):
        rows = self._query(
            "SELECT m.id, m.kind, m.content, l.relation FROM memory_links l "
            "JOIN memories m ON (m.id = l.related_id OR m.id = l.memory_id) "
            "WHERE (l.memory_id = ? OR l.related_id = ?) AND m.id != ?",
            (memory_id, memory_id, memory_id),
        )
        return rows

    def search_memories(self, query, limit=5):
        words = [w for w in query.lower().replace("?", " ").replace(".", " ").split() if len(w) > 2]
        if not words:
            return []
        clauses = " OR ".join(["LOWER(content) LIKE ?"] * len(words))
        params = [f"%{w}%" for w in words]
        rows = self._query(
            f"SELECT id, kind, content, source, importance FROM memories WHERE active=1 AND ({clauses}) ORDER BY importance DESC, id DESC LIMIT ?",
            params + [limit],
        )
        return rows

    def list_memories(self, kind=None, limit=100):
        if kind:
            return self._query(
                "SELECT id, kind, content, source, importance, created_at FROM memories WHERE active=1 AND kind=? ORDER BY importance DESC, id DESC LIMIT ?",
                (kind, limit),
            )
        return self._query(
            "SELECT id, kind, content, source, importance, created_at FROM memories WHERE active=1 ORDER BY importance DESC, id DESC LIMIT ?",
            (limit,),
        )

    def update_memory(self, memory_id, content, importance=None):
        now = datetime.now().isoformat(timespec="seconds")
        if importance is None:
            self._execute("UPDATE memories SET content=?, updated_at=? WHERE id=?", (content, now, memory_id))
        else:
            self._execute(
                "UPDATE memories SET content=?, importance=?, updated_at=? WHERE id=?",
                (content, importance, now, memory_id),
            )

    def delete_memory(self, memory_id, hard=False):
        if hard:
            self._execute("DELETE FROM memories WHERE id=?", (memory_id,))
        else:
            self._execute("UPDATE memories SET active=0 WHERE id=?", (memory_id,))

    def create_task(self, title, intent="", plan=None, agent_id=None, parent_id=None):
        now = datetime.now().isoformat(timespec="seconds")
        cur = self._execute(
            "INSERT INTO tasks (parent_id, agent_id, title, intent, plan_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (parent_id, agent_id, title, intent, json.dumps(plan or []), "queued", now, now),
        )
        task_id = cur.lastrowid
        self.event_bus.publish("task.created", {"id": task_id, "title": title, "intent": intent})
        return task_id

    def update_task(self, task_id, status, result=None, plan=None, intent=None):
        now = datetime.now().isoformat(timespec="seconds")
        sets = ["status=?", "result_json=?", "updated_at=?"]
        params = [status, json.dumps(result or {}), now]
        if intent is not None:
            sets.append("intent=?")
            params.append(intent)
        if plan is not None:
            sets.append("plan_json=?")
            params.append(json.dumps(plan))
        params.append(task_id)
        self._execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)
        self.event_bus.publish("task.updated", {"id": task_id, "status": status})

    def list_agents(self):
        return self._query("SELECT * FROM agents ORDER BY id")

    def get_agent(self, key):
        rows = self._query("SELECT * FROM agents WHERE key=?", (key,))
        return rows[0] if rows else None

    def recent_events(self, limit=30):
        return self._query("SELECT ts, source, level, type, payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,))

    def latest_telemetry(self):
        return self._query("SELECT ts, cpu, ram, active_agents, state FROM telemetry ORDER BY id DESC LIMIT 1")

    def snapshot(self):
        tel = self.latest_telemetry()
        return {
            "voice_state": self.voice_state,
            "active_agents": self.active_agents,
            "cpu": tel[0]["cpu"] if tel else None,
            "ram": tel[0]["ram"] if tel else None,
            "recent_events": self.recent_events(10),
            "recent_tasks": self._query("SELECT id, title, intent, status FROM tasks ORDER BY id DESC LIMIT 10"),
        }

    def shutdown(self):
        self._telemetry_stop.set()
        self.end_session()
        self.event_bus.publish("hub.stopped", {}, level="warning")
        self._conn.close()


if __name__ == "__main__":
    hub = PulseHub()
    print("DB:", DB_PATH)
    print("Agents:", [a["key"] for a in hub.list_agents()])
    print("Session:", hub.current_session())
    hub.log_conversation("test question", "test answer")
    print("Recent:", hub.recent_messages())
    mid = hub.add_memory("Founder is building LUXUR.AI from Nepal", kind="semantic", source="user", importance=9)
    print("Memory search:", hub.search_memories("nepal luxur"))
    hub.delete_memory(mid)
    print("Snapshot:", json.dumps(hub.snapshot(), indent=1)[:800])
    hub.shutdown()
