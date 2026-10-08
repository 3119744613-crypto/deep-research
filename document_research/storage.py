"""Small private SQLite store; no dependency on the platform database."""

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(data_dir, 0o700)
        self.path = data_dir / "document-research.sqlite3"
        if self.path.is_symlink():
            raise ValueError("独立数据库不能是符号链接。")
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS libraries (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    name TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, library_id TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
                    name TEXT NOT NULL, status TEXT NOT NULL, error TEXT, chunks TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def libraries(self, owner: str) -> list[dict]:
        with self.connection() as db:
            return [
                dict(row) | {"kind": "local"}
                for row in db.execute(
                    "SELECT l.*, COUNT(d.id) AS document_count FROM libraries l "
                    "LEFT JOIN documents d ON d.library_id=l.id WHERE l.owner=? GROUP BY l.id ORDER BY l.rowid",
                    (owner,),
                )
            ]

    def library(self, library_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM libraries WHERE id=?", (library_id,)
            ).fetchone()
            return dict(row) if row else None

    def create_library(self, owner: str, name: str) -> dict:
        result = {
            "id": "local:" + uuid.uuid4().hex,
            "name": name,
            "kind": "local",
            "document_count": 0,
        }
        with self.connection() as db:
            db.execute(
                "INSERT INTO libraries(id,owner,name) VALUES(?,?,?)",
                (result["id"], owner, name),
            )
        return result

    def delete_library(self, library_id: str):
        with self.connection() as db:
            db.execute("DELETE FROM libraries WHERE id=?", (library_id,))

    def documents(self, library_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM documents WHERE library_id=? ORDER BY rowid",
                (library_id,),
            )
            return [self._document(row) for row in rows]

    @staticmethod
    def _document(row) -> dict:
        item = dict(row)
        item["chunks"] = json.loads(item["chunks"])
        item["chunk_count"] = len(item["chunks"])
        return item

    def document(self, document_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            return self._document(row) if row else None

    def create_document(
        self, library_id: str, name: str, chunks: list[dict], error: str | None
    ) -> dict:
        item = {
            "id": uuid.uuid4().hex,
            "library_id": library_id,
            "name": name,
            "status": "failed" if error else "ready",
            "error": error,
            "chunks": chunks,
        }
        with self.connection() as db:
            db.execute(
                "INSERT INTO documents(id,library_id,name,status,error,chunks) VALUES(?,?,?,?,?,?)",
                (
                    item["id"],
                    library_id,
                    name,
                    item["status"],
                    error,
                    json.dumps(chunks, ensure_ascii=False),
                ),
            )
            db.execute(
                "UPDATE libraries SET revision=revision+1 WHERE id=?", (library_id,)
            )
        item["chunk_count"] = len(chunks)
        return item

    def delete_document(self, document_id: str):
        with self.connection() as db:
            row = db.execute(
                "SELECT library_id FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            if row:
                db.execute("DELETE FROM documents WHERE id=?", (document_id,))
                db.execute(
                    "UPDATE libraries SET revision=revision+1 WHERE id=?", (row[0],)
                )

    def task(self, task_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_task(self, task: dict):
        with self.connection() as db:
            db.execute(
                "INSERT INTO tasks(id,owner,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (task["id"], task["owner"], json.dumps(task, ensure_ascii=False)),
            )

    def replace_task(self, previous: dict, updated: dict) -> bool:
        """仅替换仍与读取快照一致的任务，避免并发编辑和运行丢失更新。"""
        with self.connection() as db:
            result = db.execute(
                "UPDATE tasks SET payload=? WHERE id=? AND owner=? AND payload=?",
                (
                    json.dumps(updated, ensure_ascii=False),
                    previous["id"],
                    previous["owner"],
                    json.dumps(previous, ensure_ascii=False),
                ),
            )
            return result.rowcount == 1

    def fail_interrupted(self):
        with self.connection() as db:
            for row in db.execute("SELECT id,payload FROM tasks").fetchall():
                task = json.loads(row["payload"])
                if task["status"] == "running":
                    task.update(
                        status="failed",
                        report=None,
                        error="服务重启中断了任务；请重新运行。",
                    )
                    db.execute(
                        "UPDATE tasks SET payload=? WHERE id=?",
                        (json.dumps(task, ensure_ascii=False), row["id"]),
                    )

    def finish_running(self, task: dict, revisions: dict | None = None) -> bool:
        """在同一事务内核验资料版本和运行状态，避免取消或删除后的旧结果落库。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()
            if row is None or json.loads(row[0])["status"] != "running":
                return False
            for library_id, revision in (revisions or {}).items():
                library = db.execute(
                    "SELECT revision FROM libraries WHERE id=?", (library_id,)
                ).fetchone()
                if library is None or library[0] != revision:
                    raise PermissionError("library evidence changed")
            db.execute(
                "UPDATE tasks SET payload=? WHERE id=?",
                (json.dumps(task, ensure_ascii=False), task["id"]),
            )
            return True
