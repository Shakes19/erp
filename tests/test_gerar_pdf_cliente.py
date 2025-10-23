import os
import importlib

import sqlite3


def test_gerar_pdf_cliente(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    import db as db_module
    import main as main_module
    importlib.reload(db_module)
    importlib.reload(main_module)

    db_module.criar_base_dados_completa()
    conn = db_module.get_connection()
    c = conn.cursor()

    c.execute("INSERT INTO fornecedor(nome) VALUES ('Forn')")
    forn_id = c.lastrowid
    c.execute("INSERT INTO cliente_empresa(nome, morada) VALUES ('ClientCo', 'Rua 1')")
    emp_id = c.lastrowid
    c.execute("INSERT INTO cliente(nome, email, empresa_id) VALUES ('Cliente', 'cli@example.com', ?)", (emp_id,))
    cliente_id = c.lastrowid
    c.execute(
        "INSERT INTO processo(numero, descricao, ref_cliente, cliente_id) VALUES (?, ?, ?, ?)",
        ("PROC-1", "Proc", "REF1", cliente_id),
    )
    processo_id = c.lastrowid
    estado_id = db_module.ensure_estado("pendente", cursor=c)
    c.execute(
        "INSERT INTO rfq(processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais, data_atualizacao, estado_id) VALUES (?, ?, NULL, NULL, '2024-01-01', ?)",
        (processo_id, forn_id, estado_id),
    )
    rfq_id = c.lastrowid
    unidade_id = db_module.ensure_unidade("pcs", cursor=c)
    c.execute(
        "INSERT INTO artigo(rfq_id, artigo_num, descricao, quantidade, unidade_id) VALUES (?, 'A1', 'Item', 2, ?)",
        (rfq_id, unidade_id),
    )
    artigo_id = c.lastrowid
    c.execute("""
        INSERT INTO resposta_fornecedor(
            fornecedor_id, rfq_id, artigo_id, descricao, custo,
            prazo_entrega, quantidade_final, peso, hs_code, pais_origem, preco_venda
        ) VALUES (?, ?, ?, 'Desc', 10, 5, 2, 1.2, 'HS', 'PT', 15)
    """, (forn_id, rfq_id, artigo_id))
    conn.commit()
    conn.close()

    assert main_module.gerar_pdf_cliente(rfq_id) is True

    conn = db_module.get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT pdf_data FROM pdf_storage WHERE processo_id = ? AND tipo_pdf = 'cliente'",
        (processo_id,),
    )
    assert c.fetchone() is not None
    conn.close()


def test_limitar_descricao_artigo_mantem_duas_linhas():
    import main as main_module

    importlib.reload(main_module)

    texto = "Linha 1\n\n Linha 2 \nLinha 3\nLinha 4"
    assert main_module.limitar_descricao_artigo(texto) == "Linha 1\nLinha 2"
