import os
import sys
import importlib
from datetime import datetime

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    # Use a dedicated temporary database for this module
    os.environ["DB_PATH"] = "test_criar_processo.db"
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_criar_processo.db"):
        os.remove("test_criar_processo.db")


def test_criar_processo_returns_valid_id_and_number():
    pid1, numero1 = db.criar_processo("desc 1")
    pid2, numero2 = db.criar_processo("desc 2")

    assert pid1 > 0
    assert pid2 == pid1 + 1

    prefix = f"QT{datetime.now().year}-"
    assert numero1.startswith(prefix)
    assert numero2.startswith(prefix)

    seq1 = int(numero1[len(prefix):])
    seq2 = int(numero2[len(prefix):])
    assert seq2 == seq1 + 1
