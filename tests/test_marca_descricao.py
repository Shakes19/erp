import os
import sys
import importlib

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    os.environ["DB_PATH"] = "test_marca_descricao.db"
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db

    if "main" in sys.modules:
        del sys.modules["main"]
    module.main = importlib.import_module("main")


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_marca_descricao.db"):
        os.remove("test_marca_descricao.db")


def test_garantir_marca_primeira_palavra_normaliza_descricao():
    func = main.garantir_marca_primeira_palavra

    assert func("Sensor indutivo BI2", "Turck") == "Turck Sensor indutivo BI2"
    assert func("turck Sensor indutivo", "Turck") == "Turck Sensor indutivo"
    assert func("Turck Sensor indutivo", "Turck") == "Turck Sensor indutivo"
    assert func("Sensor TURCK BI2", "Turck") == "Turck Sensor BI2"


def test_criar_processo_grava_descricao_com_marca_primeira_palavra():
    artigos = [
        {
            "artigo_num": "2167704",
            "descricao": "Sensor indutivo BI2-G08-VP6X-0,15-PSG4S",
            "quantidade": 2,
            "unidade": "Peças",
            "marca": "Turck",
        }
    ]

    processo_id, numero_processo, processo_artigos = main.criar_processo_com_artigos(artigos)

    assert processo_id > 0
    assert processo_artigos
    descricao_retornada = processo_artigos[0]["descricao"]
    assert descricao_retornada.startswith("Turck ")
    assert "Sensor indutivo" in descricao_retornada

    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT descricao, marca FROM processo_artigo WHERE processo_id = ?",
            (processo_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row[0].startswith("Turck ")
    assert row[1] == "Turck"
