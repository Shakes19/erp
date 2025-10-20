import os
import sys
import sqlite3
import importlib
from datetime import datetime


def setup_module(module):
    os.environ["DB_PATH"] = "test_rfq_referencia.db"
    if os.path.exists("test_rfq_referencia.db"):
        os.remove("test_rfq_referencia.db")

    # Criar uma tabela RFQ antiga com restrição UNIQUE em referencia
    conn = sqlite3.connect("test_rfq_referencia.db")
    conn.execute(
        """
        CREATE TABLE rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            referencia TEXT NOT NULL UNIQUE
        )
        """
    )
    conn.commit()
    conn.close()

    # Carregar módulo da base de dados após definir o DB_PATH
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_rfq_referencia.db"):
        os.remove("test_rfq_referencia.db")


def test_duplicate_referencia_allowed_for_multiple_suppliers():
    conn = db.get_connection()
    cur = conn.cursor()

    # Criar fornecedores de teste
    cur.execute("INSERT INTO fornecedor (nome) VALUES (?)", ("Fornecedor A",))
    fornecedor_a = cur.lastrowid
    cur.execute("INSERT INTO fornecedor (nome) VALUES (?)", ("Fornecedor B",))
    fornecedor_b = cur.lastrowid
    conn.commit()

    processo_id, _ = db.criar_processo("Processo duplicado")
    referencia = "REF-123"
    data_iso = datetime.now().isoformat()

    cur.execute("UPDATE processo SET ref_cliente = ? WHERE id = ?", (referencia, processo_id))

    estado_id = db.ensure_estado("pendente", cursor=cur)
    cur.execute(
        "INSERT INTO rfq (processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais, data_atualizacao, estado_id) VALUES (?, ?, NULL, NULL, ?, ?)",
        (processo_id, fornecedor_a, data_iso, estado_id),
    )
    cur.execute(
        "INSERT INTO rfq (processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais, data_atualizacao, estado_id) VALUES (?, ?, NULL, NULL, ?, ?)",
        (processo_id, fornecedor_b, data_iso, estado_id),
    )
    conn.commit()

    cur.execute(
        """
        SELECT COUNT(*)
          FROM rfq
          JOIN processo ON rfq.processo_id = processo.id
         WHERE processo.ref_cliente = ?
        """,
        (referencia,),
    )
    count = cur.fetchone()[0]
    conn.close()

    assert count == 2
