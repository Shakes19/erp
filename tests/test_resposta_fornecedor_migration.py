import os
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db


def _prepare_isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "cotacoes.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", Session)

    # Garantir que ligações futuras usam o novo caminho
    if hasattr(db.get_table_columns, "cache_clear"):
        db.get_table_columns.cache_clear()

    return db_path


def test_migracao_resposta_fornecedor_preserva_dados(tmp_path, monkeypatch):
    db_path = _prepare_isolated_db(tmp_path, monkeypatch)

    assert db.criar_base_dados_completa() is True

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("INSERT INTO fornecedor(nome) VALUES ('Fornecedor A')")
    fornecedor_id = cursor.lastrowid

    cursor.execute("INSERT INTO cliente_empresa(nome) VALUES ('Empresa X')")
    empresa_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO cliente(nome, empresa_id) VALUES ('Cliente X', ?)",
        (empresa_id,),
    )
    cliente_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO processo(numero, cliente_id) VALUES ('QT24-0001', ?)",
        (cliente_id,),
    )
    processo_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO rfq(processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais)"
        " VALUES (?, ?, 'Cliente Final', 'PT')",
        (processo_id, fornecedor_id),
    )
    rfq_id = cursor.lastrowid

    unidade_id = db.ensure_unidade("Peças", cursor=cursor)
    cursor.execute(
        "INSERT INTO artigo(descricao, unidade_id) VALUES ('Parafuso', ?)",
        (unidade_id,),
    )
    artigo_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO resposta_fornecedor (
            fornecedor_id,
            rfq_id,
            artigo_id,
            descricao,
            custo,
            prazo_entrega,
            quantidade_final,
            moeda,
            preco_venda,
            desconto,
            preco_venda_desconto,
            observacoes,
            validade_preco
        ) VALUES (?, ?, ?, 'Descrição', 10.5, 7, 5, 'USD', 12.0, 5.0, 11.4, 'obs', '2024-12-31')
        """,
        (fornecedor_id, rfq_id, artigo_id),
    )

    cursor.execute("ALTER TABLE resposta_fornecedor ADD COLUMN peso REAL")
    cursor.execute("ALTER TABLE resposta_fornecedor ADD COLUMN hs_code TEXT")
    cursor.execute("ALTER TABLE resposta_fornecedor ADD COLUMN pais_origem TEXT")
    conn.commit()
    conn.close()

    assert db.criar_base_dados_completa() is True

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(resposta_fornecedor)")
    colunas = {row[1] for row in cursor.fetchall()}
    assert "peso" not in colunas
    assert "hs_code" not in colunas
    assert "pais_origem" not in colunas

    cursor.execute(
        """
        SELECT fornecedor_id,
               rfq_id,
               artigo_id,
               descricao,
               custo,
               prazo_entrega,
               quantidade_final,
               moeda,
               preco_venda,
               desconto,
               preco_venda_desconto,
               observacoes,
               validade_preco
          FROM resposta_fornecedor
        """
    )
    linha = cursor.fetchone()
    assert linha == (
        fornecedor_id,
        rfq_id,
        artigo_id,
        "Descrição",
        10.5,
        7,
        5,
        "USD",
        12.0,
        5.0,
        11.4,
        "obs",
        "2024-12-31",
    )
    conn.close()
