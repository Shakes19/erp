import os
import sys
import importlib
import types

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def setup_module(module):
    # Use dedicated temporary database
    os.environ["DB_PATH"] = "test_paginacao.db"

    # Stub streamlit to avoid UI during import
    dummy = types.ModuleType("streamlit")
    dummy.set_page_config = lambda *a, **k: None
    dummy.title = lambda *a, **k: None
    dummy.subheader = lambda *a, **k: None
    dummy.columns = lambda n: [types.SimpleNamespace(button=lambda *a, **k: False) for _ in range(n)]
    dummy.button = lambda *a, **k: False
    dummy.write = lambda *a, **k: None
    dummy.selectbox = lambda *a, **k: ""
    dummy.warning = lambda *a, **k: None
    dummy.info = lambda *a, **k: None
    dummy.number_input = lambda *a, **k: 0
    dummy.markdown = lambda *a, **k: None
    dummy.success = lambda *a, **k: None

    class DummySessionState(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__

    dummy.session_state = DummySessionState()
    sys.modules['streamlit'] = dummy

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
    sys.modules.pop('streamlit', None)


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
