import importlib


def test_gerar_e_armazenar_pdf_salva_pdf(tmp_path, monkeypatch):
    db_path = tmp_path / "pedido.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    import db as db_module
    import main as main_module

    importlib.reload(db_module)
    importlib.reload(main_module)

    db_module.criar_base_dados_completa()
    conn = db_module.get_connection()
    c = conn.cursor()

    c.execute("INSERT INTO utilizador(username, password, role) VALUES ('user', 'pass', 'admin')")
    utilizador_id = c.lastrowid
    c.execute("INSERT INTO fornecedor(nome) VALUES ('Fornecedor X')")
    fornecedor_id = c.lastrowid
    c.execute(
        "INSERT INTO processo(numero, descricao, utilizador_id) VALUES (?, ?, ?)",
        ("PROC-001", "Processo teste", utilizador_id),
    )
    processo_id = c.lastrowid
    estado_id = db_module.ensure_estado("pendente", cursor=c)
    c.execute(
        "INSERT INTO rfq(processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais, estado_id) "
        "VALUES (?, ?, NULL, NULL, ?)",
        (processo_id, fornecedor_id, estado_id),
    )
    rfq_id = c.lastrowid
    conn.commit()
    conn.close()

    artigos = [{"descricao": "Item teste", "quantidade": 2, "unidade": "pcs"}]

    pdf_bytes = main_module.gerar_e_armazenar_pdf(rfq_id, fornecedor_id, main_module.date.today(), artigos)

    assert isinstance(pdf_bytes, bytes) and len(pdf_bytes) > 0

    conn = db_module.get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT pdf_data FROM pdf_storage WHERE processo_id = ? AND tipo_pdf = 'pedido'",
        (str(processo_id),),
    )
    row = c.fetchone()
    conn.close()

    assert row is not None and isinstance(row[0], bytes)
