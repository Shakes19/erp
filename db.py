"""Database utilities for the ERP system.

This module provides a small wrapper around a local SQLite database using
SQLAlchemy.  All data is stored in a file on the same machine that hosts the
application, ensuring the project can run entirely offline without any remote
database dependencies.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Connection information ----------------------------------------------------
# ``DB_PATH`` points to the SQLite database file.  It can be overridden via an
# environment variable for testing, but the application always uses a local
# SQLite database.
DB_PATH = os.environ.get("DB_PATH", "cotacoes.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def managed_cursor():
    """Provide a cursor with automatic connection cleanup."""

    conn = get_connection()
    try:
        cursor = conn.cursor()
        yield conn, cursor
    finally:
        conn.close()


def fetch_all(
    query: str,
    params: Sequence[Any] | Iterable[Any] | tuple[Any, ...] = (),
    *,
    ensure_schema: bool = False,
):
    """Execute ``SELECT`` queries returning all rows while avoiding repetition."""

    try:
        with managed_cursor() as (_, cursor):
            cursor.execute(query, params)
            return cursor.fetchall()
    except sqlite3.OperationalError as exc:
        if ensure_schema and "no such table" in str(exc).lower():
            criar_base_dados_completa()
            return []
        raise


def fetch_one(
    query: str,
    params: Sequence[Any] | Iterable[Any] | tuple[Any, ...] = (),
    *,
    ensure_schema: bool = False,
):
    """Execute ``SELECT`` queries returning a single row."""

    try:
        with managed_cursor() as (_, cursor):
            cursor.execute(query, params)
            return cursor.fetchone()
    except sqlite3.OperationalError as exc:
        if ensure_schema and "no such table" in str(exc).lower():
            criar_base_dados_completa()
            return None
        raise


def get_connection():
    """Return a DB-API connection bound to the global engine.

    Foreign keys and a busy timeout are enabled on every connection to improve
    reliability when multiple requests access the database simultaneously.
    """

    conn = engine.raw_connection()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


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


def ensure_artigo_catalogo_schema(conn: sqlite3.Connection) -> None:
    """Ensure the ``artigo_catalogo`` table exists with ``validade_preco`` column.

    Older databases may lack this column, which leads to ``OperationalError``
    when queries reference it. This helper performs a light-weight migration
    by creating the table if missing and adding the column when required.
    """

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(artigo_catalogo)")
    cols = [row[1] for row in cur.fetchall()]

    if not cols:
        # Table missing entirely – create it with the expected structure.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS artigo_catalogo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artigo_num TEXT NOT NULL UNIQUE,
                descricao TEXT NOT NULL,
                fabricante TEXT,
                preco_venda REAL NOT NULL DEFAULT 0.0,
                validade_preco TEXT
            )
            """
        )
        conn.commit()
    elif "validade_preco" not in cols:
        # Column missing – add it so future queries succeed.
        cur.execute("ALTER TABLE artigo_catalogo ADD COLUMN validade_preco TEXT")
        conn.commit()


def criar_base_dados_completa():
    """Create all database tables and apply basic PRAGMAs for SQLite.

    WAL mode and a global busy timeout are enabled to improve concurrency.  A
    default administrator account (username/password ``admin``) is also created
    if the user table is empty.
    """

    # Ensure directory exists for the SQLite database
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = get_connection()
    c = conn.cursor()

    # Limpeza defensiva: versões anteriores podiam deixar a tabela temporária
    # ``rfq_old`` para trás caso a migração fosse interrompida.  Isto fazia com
    # que novas inserções tentassem aceder a ``rfq_old`` e falhassem com
    # ``no such table``.  Garantimos que o esquema volta a um estado consistente
    # antes de continuar com a criação/migração normal.
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rfq_old'"
    )
    has_rfq_old = c.fetchone() is not None
    if has_rfq_old:
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rfq'"
        )
        has_rfq = c.fetchone() is not None
        if not has_rfq:
            c.execute("ALTER TABLE rfq_old RENAME TO rfq")
        else:
            c.execute("DROP TABLE rfq_old")

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

    # Tabela de clientes (empresas)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente_empresa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            morada TEXT,
            condicoes_pagamento TEXT
        )
        """
    )

    # Garantir coluna condicoes_pagamento
    c.execute("PRAGMA table_info(cliente_empresa)")
    empresa_cols = [row[1] for row in c.fetchall()]
    if "condicoes_pagamento" not in empresa_cols:
        c.execute(
            "ALTER TABLE cliente_empresa ADD COLUMN condicoes_pagamento TEXT"
        )

    # Tabela de clientes
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            email TEXT,
            empresa_id INTEGER,
            FOREIGN KEY (empresa_id) REFERENCES cliente_empresa(id) ON DELETE SET NULL
        )
        """
    )

    # Garantir coluna empresa_id
    c.execute("PRAGMA table_info(cliente)")
    cliente_cols = [row[1] for row in c.fetchall()]
    if "empresa_id" not in cliente_cols:
        c.execute("ALTER TABLE cliente ADD COLUMN empresa_id INTEGER")

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

    # Tabela RFQ (pedidos enviados aos fornecedores)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER,
            fornecedor_id INTEGER NOT NULL,
            cliente_id INTEGER,
            data TEXT NOT NULL,
            estado TEXT DEFAULT 'pendente',
            referencia TEXT NOT NULL,
            observacoes TEXT,
            nome_solicitante TEXT,
            email_solicitante TEXT,
            telefone_solicitante TEXT,
            empresa_solicitante TEXT,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
            utilizador_id INTEGER,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE SET NULL,
            FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL
        )
        """
    )

    # Migração: versões anteriores tinham UNIQUE(referencia), impedindo várias
    # perguntas para a mesma referência. Garantir que esse índice foi removido.
    c.execute("PRAGMA index_list('rfq')")
    rfq_indexes = c.fetchall()
    unique_ref_index = None
    for _, idx_name, is_unique, origin, _ in rfq_indexes:
        if not is_unique:
            continue
        c.execute(f"PRAGMA index_info('{idx_name}')")
        cols = [row[2] for row in c.fetchall()]
        if cols == ["referencia"]:
            unique_ref_index = idx_name
            break

    if unique_ref_index:
        # Recriar a tabela sem a restrição UNIQUE. É necessário desativar
        # temporariamente as foreign keys para permitir a operação de rename.
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE rfq RENAME TO rfq_old")
            c.execute(
                """
                CREATE TABLE rfq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    processo_id INTEGER,
                    fornecedor_id INTEGER NOT NULL,
                    cliente_id INTEGER,
                    data TEXT NOT NULL,
                    estado TEXT DEFAULT 'pendente',
                    referencia TEXT NOT NULL,
                    observacoes TEXT,
                    nome_solicitante TEXT,
                    email_solicitante TEXT,
                    telefone_solicitante TEXT,
                    empresa_solicitante TEXT,
                    data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                    data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
                    utilizador_id INTEGER,
                    FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                    FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE SET NULL,
                    FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
                    FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL
                )
                """
            )

            c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rfq_old'"
            )
            has_rfq_old = c.fetchone() is not None

            if has_rfq_old:
                c.execute("PRAGMA table_info(rfq_old)")
                old_columns = [row[1] for row in c.fetchall()]
                column_order = [
                    "id",
                    "processo_id",
                    "fornecedor_id",
                    "cliente_id",
                    "data",
                    "estado",
                    "referencia",
                    "observacoes",
                    "nome_solicitante",
                    "email_solicitante",
                    "telefone_solicitante",
                    "empresa_solicitante",
                    "data_criacao",
                    "data_atualizacao",
                    "utilizador_id",
                ]
                common_cols = [col for col in column_order if col in old_columns]
                cols_csv = ", ".join(common_cols)
                if cols_csv:
                    c.execute(
                        f"INSERT INTO rfq ({cols_csv}) SELECT {cols_csv} FROM rfq_old"
                    )

            c.execute("DROP TABLE IF EXISTS rfq_old")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

    # Garantir colunas adicionais
    c.execute("PRAGMA table_info(rfq)")
    rfq_columns = [row[1] for row in c.fetchall()]
    if "utilizador_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN utilizador_id INTEGER")
    if "processo_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN processo_id INTEGER")
    if "cliente_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN cliente_id INTEGER")

    # Tabela com artigos definidos ao nível de processo para permitir
    # reutilização entre múltiplos fornecedores na mesma cotação
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processo_artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL,
            artigo_num TEXT,
            descricao TEXT NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 1,
            unidade TEXT NOT NULL DEFAULT 'Peças',
            marca TEXT,
            ordem INTEGER DEFAULT 1,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE
        )
        """
    )

    # Tabela de artigos (cada RFQ referencia o artigo do processo)
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
            processo_artigo_id INTEGER,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE CASCADE
        )
        """
    )

    # Garantir coluna de associação ao artigo do processo em bases já existentes
    c.execute("PRAGMA table_info(artigo)")
    artigo_cols = [row[1] for row in c.fetchall()]
    if "processo_artigo_id" not in artigo_cols:
        c.execute(
            "ALTER TABLE artigo ADD COLUMN processo_artigo_id INTEGER REFERENCES processo_artigo(id)"
        )

    # Tabela de catálogo de artigos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artigo_catalogo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_num TEXT NOT NULL UNIQUE,
            descricao TEXT NOT NULL,
            fabricante TEXT,
            preco_venda REAL NOT NULL DEFAULT 0.0,
            validade_preco TEXT
        )
        """
    )

    # Seleção final de artigos por processo (fornecedor escolhido)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processo_artigo_selecao (
            processo_artigo_id INTEGER PRIMARY KEY,
            resposta_id INTEGER,
            selecionado_em TEXT DEFAULT CURRENT_TIMESTAMP,
            enviado_cliente_em TEXT,
            FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE CASCADE,
            FOREIGN KEY (resposta_id) REFERENCES resposta_fornecedor(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo_artigo_selecao)")
    selecao_cols = [row[1] for row in c.fetchall()]
    if "enviado_cliente_em" not in selecao_cols:
        c.execute(
            "ALTER TABLE processo_artigo_selecao ADD COLUMN enviado_cliente_em TEXT"
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
            margem_utilizada REAL DEFAULT 0.0,
            preco_venda REAL,
            observacoes TEXT,
            data_resposta TEXT DEFAULT CURRENT_TIMESTAMP,
            validade_preco TEXT,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
            UNIQUE (fornecedor_id, rfq_id, artigo_id)
        )
        """
    )

    # Tabela para custos adicionais por processo (envio/embalagem)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS resposta_custos (
            rfq_id INTEGER PRIMARY KEY,
            custo_envio REAL DEFAULT 0.0,
            custo_embalagem REAL DEFAULT 0.0,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
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
            margem_percentual REAL DEFAULT 0.0,
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

    # Garantir coluna "ativo" para bases existentes
    c.execute("PRAGMA table_info(configuracao_email)")
    email_cols = [row[1] for row in c.fetchall()]
    if "ativo" not in email_cols:
        c.execute(
            "ALTER TABLE configuracao_email ADD COLUMN ativo BOOLEAN DEFAULT TRUE"
        )
        email_cols.append("ativo")
    if "use_tls" not in email_cols:
        c.execute(
            "ALTER TABLE configuracao_email ADD COLUMN use_tls BOOLEAN DEFAULT TRUE"
        )
        email_cols.append("use_tls")
    if "use_ssl" not in email_cols:
        c.execute(
            "ALTER TABLE configuracao_email ADD COLUMN use_ssl BOOLEAN DEFAULT FALSE"
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
            website TEXT,
            logo BLOB
        )
        """
    )

    # Garantir colunas adicionais
    c.execute("PRAGMA table_info(configuracao_empresa)")
    cols = [row[1] for row in c.fetchall()]
    for col, col_type in [
        ("telefone", "TEXT"),
        ("email", "TEXT"),
        ("website", "TEXT"),
        ("logo", "BLOB"),
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE configuracao_empresa ADD COLUMN {col} {col_type}")

    # Tabela de utilizadores do sistema (inclui palavra-passe de email)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS utilizador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nome TEXT,
            email TEXT,
            role TEXT NOT NULL,
            email_password TEXT
        )
        """
    )

    # Garantir que a coluna email_password exista em bases de dados antigas
    c.execute("PRAGMA table_info(utilizador)")
    user_columns = [row[1] for row in c.fetchall()]
    if "email_password" not in user_columns:
        c.execute("ALTER TABLE utilizador ADD COLUMN email_password TEXT")

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
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_artigo_catalogo_num ON artigo_catalogo(artigo_num)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_fornecedor ON resposta_fornecedor(fornecedor_id, rfq_id)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_artigo ON resposta_fornecedor(artigo_id)",
        "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)",
        "CREATE INDEX IF NOT EXISTS idx_fornecedor_marca ON fornecedor_marca(fornecedor_id, marca)",
        "CREATE INDEX IF NOT EXISTS idx_cliente_nome ON cliente(nome)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)",
    ]
    for idx in indices:
        c.execute(idx)

    conn.commit()

    # Migração leve: garantir coluna custo_embalagem em bases existentes
    try:
        c.execute("PRAGMA table_info(resposta_custos)")
        rc_cols = [row[1] for row in c.fetchall()]
        if "custo_embalagem" not in rc_cols:
            c.execute(
                "ALTER TABLE resposta_custos ADD COLUMN custo_embalagem REAL DEFAULT 0.0"
            )
            conn.commit()
    except Exception:
        pass

    conn.close()
    return True


def backup_database(backup_path: str | None = None):
    """Create a consistent backup of the SQLite database."""

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
        try:
            processo_id = insert_result.lastrowid
        except AttributeError:  # pragma: no cover - defensive fallback
            processo_id = session.execute(text("SELECT last_insert_rowid()")).scalar()

        session.commit()
        return processo_id, numero
    finally:
        session.close()


def inserir_artigo_catalogo(
    artigo_num: str,
    descricao: str,
    fabricante: str = "",
    preco_venda: float = 0.0,
    validade_preco: str | None = None,
):
    """Insert or update an article in the catalogue."""

    if validade_preco is None:
        validade_preco = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    conn = get_connection()
    ensure_artigo_catalogo_schema(conn)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO artigo_catalogo
            (artigo_num, descricao, fabricante, preco_venda, validade_preco)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(artigo_num) DO UPDATE SET
            descricao = excluded.descricao,
            fabricante = excluded.fabricante,
            preco_venda = excluded.preco_venda,
            validade_preco = excluded.validade_preco
        """,
        (
            artigo_num,
            descricao,
            fabricante,
            preco_venda,
            validade_preco,
        ),
    )
    conn.commit()
    conn.close()


def procurar_artigos_catalogo(termo: str = ""):
    """Search catalogue articles by number or description."""

    conn = get_connection()
    ensure_artigo_catalogo_schema(conn)
    c = conn.cursor()
    like = f"%{termo}%"
    c.execute(
        """
        SELECT artigo_num, descricao, fabricante, preco_venda, validade_preco
        FROM artigo_catalogo
        WHERE artigo_num LIKE ? OR descricao LIKE ?
        ORDER BY artigo_num
        """,
        (like, like),
    )
    rows = c.fetchall()
    conn.close()
    return rows
