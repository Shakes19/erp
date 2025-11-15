import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db


def _write_db(path: Path, value: str):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo(value) VALUES (?)", (value,))
    conn.commit()
    conn.close()


def test_restore_database_replaces_existing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cotacoes.db"
    backup_path = tmp_path / "backup.db"

    _write_db(db_path, "old")
    _write_db(backup_path, "new")

    # Criar ficheiros WAL/SHM antigos para garantir que são removidos
    wal_file = tmp_path / "cotacoes.db-wal"
    shm_file = tmp_path / "cotacoes.db-shm"
    wal_file.write_text("wal")
    shm_file.write_text("shm")

    class DummyEngine:
        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

    dummy_engine = DummyEngine()

    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(db, "engine", dummy_engine)

    db.restore_database(str(backup_path))

    conn = sqlite3.connect(db_path)
    restored_value = conn.execute("SELECT value FROM demo").fetchone()[0]
    conn.close()

    assert restored_value == "new"
    assert dummy_engine.disposed is True
    assert not wal_file.exists()
    assert not shm_file.exists()
