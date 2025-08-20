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
    c.execute("INSERT INTO rfq(fornecedor_id, cliente_id, data, referencia) VALUES (?, ?, '2024-01-01', 'REF1')", (forn_id, cliente_id))
    rfq_id = c.lastrowid
    c.execute("INSERT INTO artigo(rfq_id, artigo_num, descricao, quantidade, unidade) VALUES (?, 'A1', 'Item', 2, 'pcs')", (rfq_id,))
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
    c.execute("SELECT pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf = 'cliente'", (str(rfq_id),))
    assert c.fetchone() is not None
    conn.close()
