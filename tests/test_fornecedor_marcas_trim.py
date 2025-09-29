import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    os.environ["DB_PATH"] = "test_fornecedor_marcas_trim.db"
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db

    if "main" in sys.modules:
        del sys.modules["main"]
    module.main = importlib.import_module("main")


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_fornecedor_marcas_trim.db"):
        os.remove("test_fornecedor_marcas_trim.db")


def test_obter_fornecedores_por_marca_ignores_whitespace():
    forn_id = main.inserir_fornecedor("Fornecedor Trim")
    assert forn_id > 0

    # Introduce surrounding whitespace on purpose
    assert main.adicionar_marca_fornecedor(forn_id, "  Marca Trim  ") is True

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT marca FROM fornecedor_marca WHERE fornecedor_id = ?", (forn_id,)
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0] == "Marca Trim"

    fornecedores = main.obter_fornecedores_por_marca("Marca Trim")
    assert any(f[0] == forn_id for f in fornecedores)

    # The lookup should also succeed when the query contains whitespace
    fornecedores_ws = main.obter_fornecedores_por_marca("  Marca Trim  ")
    assert any(f[0] == forn_id for f in fornecedores_ws)
