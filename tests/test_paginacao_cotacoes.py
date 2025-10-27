import os
import sys
import importlib

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def setup_module(module):
    # Use dedicated temporary database
    os.environ["DB_PATH"] = "test_paginacao.db"

    for name in ("cotacoes", "db"):
        sys.modules.pop(name, None)

    db = importlib.import_module('db')
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db

    cotacoes = importlib.import_module('cotacoes')
    module.cotacoes = cotacoes


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_paginacao.db"):
        os.remove("test_paginacao.db")


def test_listar_processos_paginados():
    # criar 25 processos
    for i in range(25):
        db.criar_processo(f"desc {i}")

    pagina1, total = cotacoes.listar_processos(page=0, page_size=10)
    pagina2, _ = cotacoes.listar_processos(page=1, page_size=10)
    pagina3, _ = cotacoes.listar_processos(page=2, page_size=10)

    assert total == 25
    assert len(pagina1) == 10
    assert len(pagina2) == 10
    assert len(pagina3) == 5

    ids1 = {p[0] for p in pagina1}
    ids2 = {p[0] for p in pagina2}
    assert ids1.isdisjoint(ids2)
