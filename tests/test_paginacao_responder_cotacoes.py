import os
import sys
import importlib
import sqlite3

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def test_paginacao_responder_cotacoes(tmp_path, monkeypatch):
    db_path = tmp_path / "resp_paginacao.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    import db as db_module
    importlib.reload(db_module)
    import types
    class DummyCtx:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def title(self, *a, **k): pass
        def markdown(self, *a, **k): pass
        def button(self, *a, **k): return False
        def download_button(self, *a, **k): pass
        def write(self, *a, **k): pass

    dummy = types.ModuleType("streamlit")
    dummy.set_page_config = lambda *a, **k: None
    dummy.title = lambda *a, **k: None
    dummy.sidebar = DummyCtx()
    dummy.markdown = lambda *a, **k: None
    def _columns(spec):
        count = spec if isinstance(spec, int) else len(spec)
        return [DummyCtx() for _ in range(count)]
    dummy.columns = _columns
    dummy.button = lambda *a, **k: False
    dummy.text_input = lambda *a, **k: ""
    dummy.selectbox = lambda *a, **k: ""
    dummy.tabs = lambda labels: tuple(DummyCtx() for _ in labels)
    dummy.text_area = lambda *a, **k: ""
    dummy.number_input = lambda *a, **k: 0
    dummy.write = lambda *a, **k: None
    dummy.info = lambda *a, **k: None
    dummy.warning = lambda *a, **k: None
    dummy.success = lambda *a, **k: None
    dummy.error = lambda *a, **k: None
    dummy.rerun = lambda *a, **k: None
    def _stop():
        raise SystemExit
    dummy.stop = _stop
    dummy.download_button = lambda *a, **k: None
    dummy.file_uploader = lambda *a, **k: None
    dummy.expander = lambda *a, **k: DummyCtx()
    dummy.dialog = lambda *a, **k: (lambda f: f)
    dummy.form = lambda *a, **k: DummyCtx()
    dummy.form_submit_button = lambda *a, **k: False
    dummy.cache_data = lambda *a, **k: (lambda f: f)
    class DummySessionState(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__
    dummy.session_state = DummySessionState()
    sys.modules['streamlit'] = dummy

    som = types.ModuleType("streamlit_option_menu")
    som.option_menu = lambda *a, **k: ""
    sys.modules['streamlit_option_menu'] = som

    sys.modules.pop('main', None)
    import importlib.util as importlib_util
    spec = importlib_util.find_spec('main')
    main_module = importlib_util.module_from_spec(spec)
    try:
        spec.loader.exec_module(main_module)
    except SystemExit:
        pass

    db_module.criar_base_dados_completa()
    conn = db_module.get_connection()
    c = conn.cursor()

    c.execute("INSERT INTO fornecedor(nome) VALUES ('F1')")
    forn_id = c.lastrowid

    for i in range(25):
        c.execute(
            "INSERT INTO rfq(fornecedor_id, data, estado, referencia) VALUES (?, '2024-01-01', 'pendente', ?)",
            (forn_id, f'Ref{i}')
        )
    conn.commit()
    conn.close()

    page1, total = main_module.obter_todas_cotacoes(
        estado='pendente', page=0, page_size=10, return_total=True
    )
    page2, _ = main_module.obter_todas_cotacoes(
        estado='pendente', page=1, page_size=10, return_total=True
    )
    page3, _ = main_module.obter_todas_cotacoes(
        estado='pendente', page=2, page_size=10, return_total=True
    )

    assert total == 25
    assert len(page1) == 10
    assert len(page2) == 10
    assert len(page3) == 5
    ids1 = {c['id'] for c in page1}
    ids2 = {c['id'] for c in page2}
    assert ids1.isdisjoint(ids2)
