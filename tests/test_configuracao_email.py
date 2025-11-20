import os
import sys
import importlib
import sqlite3

# Ensure project root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_module(module):
    os.environ["DB_PATH"] = "test_config_email.db"
    if os.path.exists("test_config_email.db"):
        os.remove("test_config_email.db")
    # Create table without 'ativo' column to simulate legacy DB
    conn = sqlite3.connect("test_config_email.db")
    conn.execute(
        "CREATE TABLE configuracao_email (id INTEGER PRIMARY KEY AUTOINCREMENT, smtp_server TEXT)"
    )
    conn.commit()
    conn.close()

    db = importlib.import_module("db")
    importlib.reload(db)
    db.criar_base_dados_completa()
    module.db = db


def teardown_module(module):
    module.db.engine.dispose()
    if os.path.exists("test_config_email.db"):
        os.remove("test_config_email.db")


def test_colunas_email_extras_existem():
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("PRAGMA table_info(configuracao_email)")
    cols = [row[1] for row in c.fetchall()]
    conn.close()
    for expected in {"ativo", "use_tls", "use_ssl"}:
        assert expected in cols
    assert "email_user" not in cols


def test_clear_email_cache_sem_erro():
    import services.email_service as email_service

    email_service.clear_email_cache()


def test_get_system_email_config_devolve_flags_tls_ssl():
    import services.email_service as email_service

    email_service.clear_email_cache()
    config = email_service.get_system_email_config()
    assert "server" in config
    assert "port" in config
    assert "use_tls" in config
    assert "use_ssl" in config


def test_decrypt_email_password_retorna_texto_simples_quando_nao_encriptado():
    env_key = "EMAIL_SECRET_KEY"
    previous_value = os.environ.get(env_key)
    os.environ[env_key] = "TEST_KEY"
    try:
        plain = "segredo123"
        assert db.decrypt_email_password(plain) == plain
    finally:
        if previous_value is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = previous_value
