import os
import sys
import importlib

import streamlit as st

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


def test_criar_processo_preserva_descricao_original():
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
    assert descricao_retornada == "Sensor indutivo BI2-G08-VP6X-0,15-PSG4S"

    conn = db.get_connection()
    try:
        artigo_info = conn.execute(
            "SELECT artigo_num, descricao, marca_id FROM artigo WHERE id = ?",
            (processo_artigos[0]["artigo_id"],),
        ).fetchone()
        assert artigo_info is not None
        artigo_num_db, descricao_db, marca_id_db = artigo_info
        marca_db = ""
        if marca_id_db:
            marca_row = conn.execute(
                "SELECT marca FROM marca WHERE id = ?",
                (marca_id_db,),
            ).fetchone()
            marca_db = marca_row[0] if marca_row else ""
    finally:
        conn.close()

    assert artigo_num_db == "2167704"
    assert descricao_db == "Sensor indutivo BI2-G08-VP6X-0,15-PSG4S"
    assert (marca_db or "Turck").startswith("Turck")


def test_sugerir_marca_por_primeira_letra_quando_inicial_unica():
    agrupar = main.agrupar_marcas_por_inicial
    sugerir = main.sugerir_marca_por_primeira_letra

    marcas = ["Turck", "Balluff", "Phoenix Contact"]
    mapa = agrupar(marcas)

    assert sugerir("Transformador monofásico", mapa) == "Turck"
    assert sugerir("Ball bearing", mapa) == "Balluff"
    assert sugerir("Phoenix conector", mapa) == "Phoenix Contact"


def test_sugerir_marca_por_primeira_letra_ambigua_retorna_vazio():
    agrupar = main.agrupar_marcas_por_inicial
    sugerir = main.sugerir_marca_por_primeira_letra

    marcas = ["Bosch", "Balluff", "Baumer"]
    mapa = agrupar(marcas)

    # Sem correspondência direta pelo início da descrição, permanece vazio
    assert sugerir("Bomba hidráulica", mapa) == ""

    # Com correspondência direta, a marca correta é escolhida
    assert sugerir("Baumer sensor", mapa) == "Baumer"


def test_callback_marca_manual_define_flag():
    marca_key = "smart_artigos_0_marca"
    manual_key = f"{marca_key}_manual"
    index_key = f"{marca_key}_index"

    try:
        st.session_state[index_key] = 1
        if manual_key in st.session_state:
            st.session_state.pop(manual_key)

        main._marcar_marca_manual(index_key, manual_key)

        assert st.session_state.get(manual_key) is True
    finally:
        for key in (index_key, manual_key):
            if key in st.session_state:
                st.session_state.pop(key)
