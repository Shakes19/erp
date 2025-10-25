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
        cols = db.get_table_columns("processo_artigo")
        if "marca" in cols:
            row = conn.execute(
                "SELECT descricao, marca FROM processo_artigo WHERE processo_id = ?",
                (processo_id,),
            ).fetchone()
            descricao_db, marca_db = row if row else (None, None)
        elif "artigo_id" in cols:
            row = conn.execute(
                "SELECT descricao, artigo_id FROM processo_artigo WHERE processo_id = ?",
                (processo_id,),
            ).fetchone()
            descricao_db, artigo_id_db = row if row else (None, None)
            marca_db = ""
            if artigo_id_db:
                artigo_info = conn.execute(
                    "SELECT descricao, marca_id FROM artigo WHERE id = ?",
                    (artigo_id_db,),
                ).fetchone()
                assert artigo_info is not None
                descricao_db = artigo_info[0]
                marca_id_db = artigo_info[1]
                if marca_id_db:
                    marca_row = conn.execute(
                        "SELECT marca FROM marca WHERE id = ?",
                        (marca_id_db,),
                    ).fetchone()
                    marca_db = marca_row[0] if marca_row else ""
        else:
            row = conn.execute(
                "SELECT descricao, '' FROM processo_artigo WHERE processo_id = ?",
                (processo_id,),
            ).fetchone()
            descricao_db, marca_db = row if row else (None, None)
    finally:
        conn.close()

    assert descricao_db is not None
    assert descricao_db.startswith("Turck ")
    assert (marca_db or "Turck").startswith("Turck")
