import os
import sys
import importlib
import sqlite3


def test_procurar_artigos_catalogo_missing_column(tmp_path):
    db_path = tmp_path / 'missing_col.db'
    # Create DB with artigo_catalogo table missing validade_preco column
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE artigo_catalogo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_num TEXT NOT NULL UNIQUE,
            descricao TEXT NOT NULL,
            fabricante TEXT,
            preco_venda REAL NOT NULL DEFAULT 0.0
        )
        """
    )
    cur.execute(
        "INSERT INTO artigo_catalogo (artigo_num, descricao, fabricante, preco_venda)"
        " VALUES (?, ?, ?, ?)",
        ("A1", "Desc", "Fab", 10.0),
    )
    conn.commit()
    conn.close()

    os.environ['DB_PATH'] = str(db_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    db = importlib.import_module('db')
    importlib.reload(db)

    resultados = db.procurar_artigos_catalogo('A1')
    assert any(r[0] == 'A1' for r in resultados)

    # Column should have been added by the function
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(artigo_catalogo)")
    cols = {row[1] for row in cur.fetchall()}
    assert 'validade_preco' in cols
    conn.close()
    db.engine.dispose()
