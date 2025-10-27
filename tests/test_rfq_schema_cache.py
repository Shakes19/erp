import os
import sys
import importlib
import types

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _install_streamlit_stub():
    class DummyCtx:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def title(self, *args, **kwargs):
            return None

        def markdown(self, *args, **kwargs):
            return None

        def button(self, *args, **kwargs):
            return False

        def download_button(self, *args, **kwargs):
            return None

        def write(self, *args, **kwargs):
            return None

    dummy = types.ModuleType("streamlit")
    dummy.set_page_config = lambda *a, **k: None
    dummy.title = lambda *a, **k: None
    dummy.subheader = lambda *a, **k: None
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
    dummy.date_input = lambda *a, **k: None
    dummy.write = lambda *a, **k: None
    dummy.info = lambda *a, **k: None
    dummy.warning = lambda *a, **k: None
    dummy.success = lambda *a, **k: None
    dummy.error = lambda *a, **k: None
    dummy.rerun = lambda *a, **k: None
    dummy.image = lambda *a, **k: None
    dummy.stop = lambda *a, **k: None
    dummy.download_button = lambda *a, **k: None
    dummy.file_uploader = lambda *a, **k: None
    dummy.expander = lambda *a, **k: DummyCtx()
    dummy.dialog = lambda *a, **k: (lambda f: f)
    dummy.form = lambda *a, **k: DummyCtx()
    dummy.form_submit_button = lambda *a, **k: False
    dummy.cache_data = lambda *a, **k: (lambda f: f)
    dummy.cache_resource = lambda *a, **k: (lambda f: f)

    class DummySessionState(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__

    dummy.session_state = DummySessionState(
        {
            "sistema_inicializado": True,
            "logged_in": True,
            "role": "admin",
            "user_id": 1,
            "username": "tester",
            "user_email": "tester@example.com",
            "user_nome": "Tester",
        }
    )

    sys.modules["streamlit"] = dummy

    som = types.ModuleType("streamlit_option_menu")
    som.option_menu = lambda *a, **k: ""
    sys.modules["streamlit_option_menu"] = som


def _remove_streamlit_stub():
    sys.modules.pop("streamlit", None)
    sys.modules.pop("streamlit_option_menu", None)


def test_rfq_schema_cache_refresh(tmp_path, monkeypatch):
    db_path = tmp_path / "rfq_schema_cache.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    _install_streamlit_stub()

    try:
        sys.modules.pop("main", None)
        sys.modules.pop("db", None)
        import db as db_module
        import main as main_module

        importlib.reload(db_module)
        importlib.reload(main_module)

        info_before = main_module._rfq_schema_info()
        assert info_before["data_column"] is None

        assert main_module.criar_base_dados() is True

        info_after = main_module._rfq_schema_info()
        assert info_after["data_column"] == "data_atualizacao"

        db_module.engine.dispose()
    finally:
        sys.modules.pop("main", None)
        sys.modules.pop("db", None)
        _remove_streamlit_stub()
        if db_path.exists():
            os.remove(db_path)
