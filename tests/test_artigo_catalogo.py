import os
import os
import sys
import importlib
import sqlite3

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    os.environ["DB_PATH"] = "test_artigo_catalogo.db"
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_artigo_catalogo.db"):
        os.remove("test_artigo_catalogo.db")


def test_artigo_catalogo_table_structure():
    conn = sqlite3.connect("test_artigo_catalogo.db")
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(artigo_catalogo)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {
        "id",
        "artigo_num",
        "descricao",
        "fabricante",
        "preco_venda",
        "validade_preco",
    }
    assert expected.issubset(cols)
    conn.close()


def test_inserir_e_procurar_artigos():
    db.inserir_artigo_catalogo("A1", "Desc1", "Fab", 10.0)
    db.inserir_artigo_catalogo("A2", "Outro", "Fab2", 20.0)
    resultados = db.procurar_artigos_catalogo("A1")
    assert any(r[0] == "A1" for r in resultados)
