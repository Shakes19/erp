import os
import sys
import importlib

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    module.db_path = "test_unidades_iniciais.db"
    os.environ["DB_PATH"] = module.db_path
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists(module.db_path):
        os.remove(module.db_path)


def test_tabela_unidade_inicia_vazia():
    conn = db.get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM unidade").fetchone()[0]
    finally:
        conn.close()

    assert total == 0
