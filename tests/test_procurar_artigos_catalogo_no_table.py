import os
import sys
import importlib
import sqlite3

def test_procurar_artigos_catalogo_missing_table(tmp_path):
    db_path = tmp_path / 'missing.db'
    os.environ['DB_PATH'] = str(db_path)
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    db = importlib.import_module('db')
    importlib.reload(db)
    # Call function without creating tables
    resultados = db.procurar_artigos_catalogo('A')
    assert resultados == []
    # Ensure table exists now
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE name='artigo_catalogo'")
    assert cur.fetchone() is not None
    conn.close()
    db.engine.dispose()
