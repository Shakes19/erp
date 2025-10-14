import os
import sys
import importlib
import sqlite3

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    os.environ["DB_PATH"] = "test_config_email.db"
    if os.path.exists("test_config_email.db"):
        os.remove("test_config_email.db")
    # Create table without 'ativo' column to simulate legacy DB
    conn = sqlite3.connect("test_config_email.db")
    conn.execute(
        "CREATE TABLE configuracao_email (id INTEGER PRIMARY KEY AUTOINCREMENT, smtp_server TEXT)"
    )
    conn.commit()
    conn.close()

    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_config_email.db"):
        os.remove("test_config_email.db")


def test_coluna_ativo_existe():
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("PRAGMA table_info(configuracao_email)")
    cols = [row[1] for row in c.fetchall()]
    conn.close()
    assert "ativo" in cols


def test_clear_email_cache_sem_erro():
    import services.email_service as email_service

    email_service.clear_email_cache()
