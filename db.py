"""Database utilities for the ERP system.

Originally this project targeted a local SQLite database.  The module now
supports both SQLite and PostgreSQL through SQLAlchemy, selecting the engine
based on environment variables.  A single SQLAlchemy engine is exposed so every
part of the application talks to the same database layer.
"""

import os
import sqlite3
from datetime import datetime

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Connection information ----------------------------------------------------
# ``DATABASE_URL`` takes precedence.  When not provided, a local SQLite file is
# used instead.  ``DB_PATH`` is retained for backwards compatibility and for
# features that operate directly on the SQLite file (e.g. backups).
DB_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("DB_PATH", "cotacoes.db")

if DB_URL:
    engine = create_engine(DB_URL)
else:
    engine = create_engine(
        f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class _CursorWrapper:
    """DB-API cursor that adapts SQLite-style ``?`` placeholders.

    The application was originally written for SQLite using ``?`` as the
    placeholder marker.  When running against other backends (notably
    PostgreSQL/psycopg2 which expects ``%s``) this causes syntax errors.  The
    wrapper transparently converts the placeholders so existing queries work
    on both engines.
    """

    def __init__(self, cursor, paramstyle):
        self._cursor = cursor
        self._paramstyle = paramstyle

    def execute(self, query, params=None):
        if params and self._paramstyle in {"pyformat", "format"}:
            query = query.replace("?", "%s")
        return self._cursor.execute(query, params or ())

    def executemany(self, query, seq_of_params):
        if self._paramstyle in {"pyformat", "format"}:
            query = query.replace("?", "%s")
        return self._cursor.executemany(query, seq_of_params)

    def __getattr__(self, name):  # pragma: no cover - simple delegation
        return getattr(self._cursor, name)


class _ConnectionWrapper:
    def __init__(self, conn, paramstyle):
        self._conn = conn
        self._paramstyle = paramstyle

    def cursor(self):
        return _CursorWrapper(self._conn.cursor(), self._paramstyle)

    def __getattr__(self, name):  # pragma: no cover - simple delegation
        return getattr(self._conn, name)


def get_connection():
    """Return a DB-API connection bound to the global engine.

    For SQLite databases, foreign keys and a busy timeout are enabled on every
    connection.  For other backends (e.g. PostgreSQL) a lightweight wrapper is
    returned that converts SQLite-style ``?`` placeholders to the paramstyle
    expected by the backend (e.g. ``%s`` for psycopg2).
    """

    conn = engine.raw_connection()
    if engine.dialect.name == "sqlite":
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    # Non-SQLite backends may use a different paramstyle.  Wrap the connection
    # so calls to ``cursor.execute`` still accept queries written with ``?``
    # placeholders.
    return _ConnectionWrapper(conn, engine.dialect.paramstyle)


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | bytes | None) -> bool:
    """Verify a plaintext password against the stored hash."""

    if hashed is None:
        return False

    # ``hashed`` may come from the DB as ``bytes``/``memoryview`` (e.g. when the
    # column type is BYTEA) or as plain text.  Normalise to ``bytes`` for
    # ``bcrypt`` while keeping a textual representation for fallback checks.
    if isinstance(hashed, (bytes, bytearray, memoryview)):
        hashed_bytes = bytes(hashed)
        hashed_str = hashed_bytes.decode(errors="ignore")
    else:
        hashed_bytes = hashed.encode()
        hashed_str = hashed

    try:
        return bcrypt.checkpw(password.encode(), hashed_bytes)
    except ValueError:
        # Stored password isn't a valid bcrypt hash (legacy plain-text entry).
        return password == hashed_str
    except Exception:
        return False


def criar_base_dados_completa():
    """Create all database tables and apply basic PRAGMAs.

    For PostgreSQL (or any non-SQLite backend) this function becomes a no-op, as
    it assumes the schema is managed externally.  When using SQLite, WAL mode and
    a global busy timeout are enabled to improve concurrency.  A default
    administrator account (username/password ``admin``) is also created if the
    user table is empty.
    """

    if engine.dialect.name != "sqlite":
        # Schema creation for PostgreSQL is expected to be handled via separate
        # migration tools; nothing to do here.
        return True

    # Ensure directory exists for the SQLite database
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = get_connection()
    c = conn.cursor()

    # Improve concurrency
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")

    # Tabela de fornecedores
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fornecedor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            email TEXT,
            telefone TEXT,
            morada TEXT,
            nif TEXT,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # Tabela de marcas por fornecedor
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS fornecedor_marca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER NOT NULL,
            marca TEXT NOT NULL,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            UNIQUE(fornecedor_id, marca)
        )
        """
    )

    # Tabela de processos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            descricao TEXT,
            data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
            estado TEXT DEFAULT 'ativo'
        )
        """
    )

    # Tabela RFQ
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER,
            fornecedor_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            estado TEXT DEFAULT 'pendente',
            referencia TEXT NOT NULL UNIQUE,
            observacoes TEXT,
            nome_solicitante TEXT,
            email_solicitante TEXT,
            telefone_solicitante TEXT,
            empresa_solicitante TEXT,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
            utilizador_id INTEGER,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL
        )
        """
    )

    # Garantir colunas adicionais
    c.execute("PRAGMA table_info(rfq)")
    rfq_columns = [row[1] for row in c.fetchall()]
    if "utilizador_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN utilizador_id INTEGER")
    if "processo_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN processo_id INTEGER")

    # Tabela de artigos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            artigo_num TEXT,
            descricao TEXT NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 1,
            unidade TEXT NOT NULL DEFAULT 'Peças',
            especificacoes TEXT,
            marca TEXT,
            ordem INTEGER DEFAULT 1,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
        )
        """
    )

    # Tabela de respostas dos fornecedores
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS resposta_fornecedor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER NOT NULL,
            rfq_id INTEGER NOT NULL,
            artigo_id INTEGER NOT NULL,
            descricao TEXT,
            custo REAL NOT NULL DEFAULT 0.0,
            prazo_entrega INTEGER NOT NULL DEFAULT 1,
            quantidade_final INTEGER,
            peso REAL DEFAULT 0.0,
            hs_code TEXT,
            pais_origem TEXT,
            moeda TEXT DEFAULT 'EUR',
            margem_utilizada REAL DEFAULT 10.0,
            preco_venda REAL,
            observacoes TEXT,
            data_resposta TEXT DEFAULT CURRENT_TIMESTAMP,
            validade_dias INTEGER DEFAULT 30,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
            UNIQUE (fornecedor_id, rfq_id, artigo_id)
        )
        """
    )

    # Tabela para armazenamento de PDFs
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_storage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id TEXT NOT NULL,
            tipo_pdf TEXT NOT NULL,
            pdf_data BLOB NOT NULL,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            tamanho_bytes INTEGER,
            nome_ficheiro TEXT,
            UNIQUE(rfq_id, tipo_pdf)
        )
        """
    )

    # Tabela de configuração de margens por marca
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_margens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER,
            marca TEXT,
            margem_percentual REAL DEFAULT 10.0,
            ativo BOOLEAN DEFAULT TRUE,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE
        )
        """
    )

    # Tabela de configurações de email (sem password)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            smtp_server TEXT,
            smtp_port INTEGER,
            email_user TEXT,
            ativo BOOLEAN DEFAULT TRUE
        )
        """
    )

    # Tabela de configuração da empresa
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao_empresa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            morada TEXT,
            nif TEXT,
            iban TEXT,
            telefone TEXT,
            email TEXT,
            website TEXT
        )
        """
    )

    # Garantir colunas adicionais
    c.execute("PRAGMA table_info(configuracao_empresa)")
    cols = [row[1] for row in c.fetchall()]
    for col in ["telefone", "email", "website"]:
        if col not in cols:
            c.execute(f"ALTER TABLE configuracao_empresa ADD COLUMN {col} TEXT")

    # Tabela de utilizadores do sistema (sem email_password)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS utilizador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nome TEXT,
            email TEXT,
            role TEXT NOT NULL
        )
        """
    )

    # Inserir utilizador administrador padrão se a tabela estiver vazia
    c.execute("SELECT COUNT(*) FROM utilizador")
    if c.fetchone()[0] == 0:
        c.execute(
            """
            INSERT INTO utilizador (username, password, nome, email, role)
            VALUES ('admin', ?, 'Administrador', 'admin@example.com', 'admin')
            """,
            (hash_password("admin"),),
        )

    # Criar índices para melhor performance
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_rfq_fornecedor ON rfq(fornecedor_id)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_data ON rfq(data)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_estado ON rfq(estado)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_referencia ON rfq(referencia)",
        "CREATE INDEX IF NOT EXISTS idx_artigo_rfq ON artigo(rfq_id)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_fornecedor ON resposta_fornecedor(fornecedor_id, rfq_id)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_artigo ON resposta_fornecedor(artigo_id)",
        "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)",
        "CREATE INDEX IF NOT EXISTS idx_fornecedor_marca ON fornecedor_marca(fornecedor_id, marca)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)",
    ]
    for idx in indices:
        c.execute(idx)

    conn.commit()
    conn.close()
    return True


def backup_database(backup_path: str | None = None):
    """Create a consistent backup of the database.

    Currently only SQLite backups are supported.  For PostgreSQL this function
    raises ``NotImplementedError`` and the backup should be handled externally.
    """

    if engine.dialect.name != "sqlite":
        raise NotImplementedError("Backups are only supported for SQLite databases")

    if not backup_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"backup_cotacoes_{timestamp}.db"

    source = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(backup_path)
    with dest:
        source.backup(dest)
    source.close()
    dest.close()
    return backup_path


def criar_processo(descricao: str = ""):
    """Cria um novo processo com número sequencial anual."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    session = SessionLocal()
    try:
        result = session.execute(
            text(
                "SELECT MAX(CAST(SUBSTR(numero, 8) AS INTEGER)) FROM processo WHERE numero LIKE :prefixo"
            ),
            {"prefixo": f"{prefixo}%"},
        )
        max_seq = result.scalar()
        numero = f"{prefixo}{(max_seq or 0) + 1}"
        insert_result = session.execute(
            text(
                "INSERT INTO processo (numero, descricao) VALUES (:numero, :descricao)"
            ),
            {"numero": numero, "descricao": descricao},
        )
        session.commit()
        return insert_result.lastrowid, numero
    finally:
        session.close()
