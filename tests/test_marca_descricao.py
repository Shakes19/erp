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


def _inserir_artigo_catalogo(db_module, numero, descricao, unidade="Peças", marca=None):
    if marca is None:
        marca = f"Marca {numero}"

    conn = db_module.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO fornecedor (nome) VALUES (?)", (f"Fornecedor {numero}",))
        fornecedor_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO marca (fornecedor_id, marca, marca_normalizada, margem)
            VALUES (?, ?, ?, 0.0)
            """,
            (fornecedor_id, marca, marca.casefold()),
        )
        marca_id = cursor.lastrowid
        unidade_id = db_module.ensure_unidade(unidade, cursor=cursor)
        cursor.execute(
            """
            INSERT INTO artigo (artigo_num, descricao, unidade_id, marca_id)
            VALUES (?, ?, ?, ?)
            """,
            (numero, descricao, unidade_id, marca_id),
        )
        conn.commit()
    finally:
        conn.close()


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


def test_sugerir_marca_por_primeira_palavra_quando_corresponde():
    agrupar = main.agrupar_marcas_por_inicial
    sugerir = main.sugerir_marca_por_primeira_letra

    marcas = ["Turck", "Balluff", "Wago"]
    mapa = agrupar(marcas)

    assert sugerir("Turck sensor indutivo", mapa) == "Turck"
    assert sugerir("balluff sensor", mapa) == "Balluff"
    assert sugerir("Wago borne", mapa) == "Wago"


def test_sugerir_marca_por_primeira_palavra_sem_correspondencia():
    agrupar = main.agrupar_marcas_por_inicial
    sugerir = main.sugerir_marca_por_primeira_letra

    marcas = ["Bosch", "Balluff", "Baumer"]
    mapa = agrupar(marcas)

    # Sem correspondência direta, a marca permanece vazia
    assert sugerir("Bomba hidráulica", mapa) == ""
    assert sugerir("Rexroth Bosch válvula", mapa) == ""


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


def test_selecao_manual_nao_e_revertida_por_sugestoes():
    marca_key = "smart_artigos_0_marca"
    manual_key = f"{marca_key}_manual"
    index_key = f"{marca_key}_index"

    marcas_disponiveis = ["Balluff", "Bosch", "Turck"]
    marca_options = [None, *marcas_disponiveis]
    marcas_disponiveis_normalizadas = {
        marca.casefold(): marca for marca in marcas_disponiveis
    }
    marcas_disponiveis_por_inicial = main.agrupar_marcas_por_inicial(
        marcas_disponiveis
    )

    try:
        st.session_state[manual_key] = True
        st.session_state[index_key] = 2  # Seleção manual de "Bosch"
        st.session_state[marca_key] = "Bosch"

        main.sincronizar_marca_smart_artigo(
            "Balluff sensor indutivo",
            marca_key,
            manual_key,
            index_key,
            marca_options,
            marcas_disponiveis,
            marcas_disponiveis_normalizadas,
            marcas_disponiveis_por_inicial,
        )

        assert st.session_state[marca_key] == "Bosch"
        assert st.session_state[index_key] == 2
        assert st.session_state[manual_key] is True
    finally:
        for key in (marca_key, manual_key, index_key):
            if key in st.session_state:
                st.session_state.pop(key)


def test_atualizar_campos_catalogo_preenche_e_bloqueia_nova_cotacao():
    numero = "CAT-001"
    descricao_catalogo = "Artigo Catálogo 001"
    unidade_catalogo = "Caixa"
    marca_catalogo = "Marca Cat001"

    _inserir_artigo_catalogo(db, numero, descricao_catalogo, unidade_catalogo, marca_catalogo)

    numero_key = "nova_art_num_1"
    descricao_key = "nova_desc_1"
    unidade_key = "nova_unidade_1"
    marca_key = "nova_marca_1"

    try:
        st.session_state[descricao_key] = "Manual"
        st.session_state[unidade_key] = "Peças"
        st.session_state[marca_key] = "Outra"
        st.session_state[numero_key] = numero

        main.atualizar_campos_artigo_catalogo(
            numero_key=numero_key,
            descricao_key=descricao_key,
            unidade_key=unidade_key,
            marca_key=marca_key,
        )

        assert st.session_state[descricao_key] == descricao_catalogo
        assert st.session_state[unidade_key] == unidade_catalogo
        assert st.session_state[marca_key] == marca_catalogo
        assert st.session_state.get(f"{unidade_key}__disabled") is True
        assert st.session_state.get(f"{marca_key}__disabled") is True
    finally:
        st.session_state.clear()


def test_atualizar_campos_catalogo_desbloqueia_quando_artigo_inexistente():
    numero_key = "nova_art_num_1"
    descricao_key = "nova_desc_1"
    unidade_key = "nova_unidade_1"
    marca_key = "nova_marca_1"

    try:
        st.session_state[descricao_key] = "Descrição manual"
        st.session_state[unidade_key] = "Peças"
        st.session_state[marca_key] = "Marca manual"
        st.session_state[numero_key] = "INEXISTENTE"
        st.session_state[f"{unidade_key}__disabled"] = True
        st.session_state[f"{marca_key}__disabled"] = True

        main.atualizar_campos_artigo_catalogo(
            numero_key=numero_key,
            descricao_key=descricao_key,
            unidade_key=unidade_key,
            marca_key=marca_key,
        )

        assert st.session_state[descricao_key] == "Descrição manual"
        assert st.session_state[unidade_key] == "Peças"
        assert st.session_state[marca_key] == "Marca manual"
        assert st.session_state.get(f"{unidade_key}__disabled") is False
        assert st.session_state.get(f"{marca_key}__disabled") is False
    finally:
        st.session_state.clear()


def test_atualizar_campos_catalogo_preenche_smart_e_reset_manual():
    numero = "CAT-002"
    descricao_catalogo = "Artigo Catálogo 002"
    unidade_catalogo = "Unidade"
    marca_catalogo = "Marca Cat002"

    _inserir_artigo_catalogo(db, numero, descricao_catalogo, unidade_catalogo, marca_catalogo)

    numero_key = "smart_artigos_0_artigo_num"
    descricao_key = "smart_artigos_0_descricao"
    unidade_key = "smart_artigos_0_unidade"
    marca_key = "smart_artigos_0_marca"
    marca_manual_key = f"{marca_key}_manual"

    try:
        st.session_state[descricao_key] = "Descrição manual"
        st.session_state[unidade_key] = "Peças"
        st.session_state[marca_key] = "Marca manual"
        st.session_state[marca_manual_key] = True
        st.session_state[numero_key] = numero

        main.atualizar_campos_artigo_catalogo(
            numero_key=numero_key,
            descricao_key=descricao_key,
            unidade_key=unidade_key,
            marca_key=marca_key,
            marca_manual_key=marca_manual_key,
        )

        assert st.session_state[descricao_key] == descricao_catalogo
        assert st.session_state[unidade_key] == unidade_catalogo
        assert st.session_state[marca_key] == marca_catalogo
        assert st.session_state.get(f"{unidade_key}__disabled") is True
        assert st.session_state.get(f"{marca_key}__disabled") is True
        assert st.session_state.get(marca_manual_key) is False
    finally:
        st.session_state.clear()
