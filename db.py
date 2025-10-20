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


def _py_casefold(value: object) -> str | None:
    """SQLite helper that aplica ``str.casefold`` preservando ``NULL``."""

    if value is None:
        return None
    if isinstance(value, str):
        return value.casefold()
    return str(value).casefold()


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
    conn.create_function("PYCASEFOLD", 1, _py_casefold)
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


def _get_or_create_value(
    table: str,
    column: str,
    value: str,
    *,
    cursor: sqlite3.Cursor | None = None,
) -> int | None:
    """Insert ``value`` into ``table`` if missing and return the row id."""

    normalized = (value or "").strip()
    if not normalized:
        return None

    own_connection = cursor is None
    conn = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    try:
        cursor.execute(
            f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)",
            (normalized,),
        )
        cursor.execute(
            f"SELECT id FROM {table} WHERE {column} = ?",
            (normalized,),
        )
        row = cursor.fetchone()
        if own_connection and conn is not None:
            conn.commit()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


def ensure_estado(nome: str, cursor: sqlite3.Cursor | None = None) -> int:
    """Return the identifier for ``nome`` in ``estado`` creating it if needed."""

    estado_id = _get_or_create_value("estado", "nome", nome, cursor=cursor)
    if estado_id is None:
        raise ValueError("Estado deve ser um texto não vazio")
    return estado_id


def ensure_moeda(codigo: str, cursor: sqlite3.Cursor | None = None) -> int:
    """Return the identifier for ``codigo`` in ``moeda`` creating it if needed."""

    moeda_id = _get_or_create_value("moeda", "codigo", codigo, cursor=cursor)
    if moeda_id is None:
        raise ValueError("Código de moeda inválido")
    return moeda_id


def ensure_pais(nome: str, cursor: sqlite3.Cursor | None = None) -> int | None:
    """Return the identifier for ``nome`` in ``pais`` creating it if needed."""

    return _get_or_create_value("pais", "nome", nome, cursor=cursor)


def get_marca_id(marca: str, cursor: sqlite3.Cursor | None = None) -> int | None:
    """Return the ``marca`` identifier by normalized name."""

    marca_normalizada = (marca or "").strip().casefold()
    if not marca_normalizada:
        return None

    own_connection = cursor is None
    conn = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id FROM marca WHERE marca_normalizada = ?",
            (marca_normalizada,),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


def get_artigo_catalogo_id(
    artigo_num: str | None, cursor: sqlite3.Cursor | None = None
) -> int | None:
    """Return the catalogue identifier for ``artigo_num`` if it exists."""

    codigo = (artigo_num or "").strip()
    if not codigo:
        return None

    own_connection = cursor is None
    conn = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id FROM artigo_catalogo WHERE artigo_num = ?",
            (codigo,),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


def ensure_cliente_final(
    nome: str, pais: str | None = None, cursor: sqlite3.Cursor | None = None
) -> int | None:
    """Return the identifier for the final client, creating it if needed."""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        return None
    pais_limpo = (pais or "").strip() or None

    own_connection = cursor is None
    conn = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO cliente_final (nome, pais)
            VALUES (?, ?)
            """,
            (nome_limpo, pais_limpo),
        )
        cursor.execute(
            """
            SELECT id
              FROM cliente_final
             WHERE nome = ?
               AND ((pais IS NULL AND ? IS NULL) OR pais = ?)
            """,
            (nome_limpo, pais_limpo, pais_limpo),
        )
        row = cursor.fetchone()
        if own_connection and conn is not None:
            conn.commit()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


def ensure_solicitante(
    nome: str | None = None,
    email: str | None = None,
    telefone: str | None = None,
    empresa: str | None = None,
    cursor: sqlite3.Cursor | None = None,
) -> int | None:
    """Return the identifier for the requester, creating it if needed."""

    nome_limpo = (nome or "").strip()
    email_limpo = (email or "").strip()
    telefone_limpo = (telefone or "").strip()
    empresa_limpa = (empresa or "").strip()

    if not any((nome_limpo, email_limpo, telefone_limpo, empresa_limpa)):
        return None

    own_connection = cursor is None
    conn = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO solicitante (nome, email, telefone, empresa)
            VALUES (?, ?, ?, ?)
            """,
            (nome_limpo, email_limpo, telefone_limpo, empresa_limpa),
        )
        cursor.execute(
            """
            SELECT id
              FROM solicitante
             WHERE nome = ?
               AND email = ?
               AND telefone = ?
               AND empresa = ?
            """,
            (nome_limpo, email_limpo, telefone_limpo, empresa_limpa),
        )
        row = cursor.fetchone()
        if own_connection and conn is not None:
            conn.commit()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


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

    # Garantir que a tabela de catálogo existe antes de referências posteriores
    ensure_artigo_catalogo_schema(conn)

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
            necessita_pais_cliente_final INTEGER NOT NULL DEFAULT 0,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    c.execute("PRAGMA table_info(fornecedor)")
    fornecedor_cols = [row[1] for row in c.fetchall()]
    if "necessita_pais_cliente_final" not in fornecedor_cols:
        c.execute(
            "ALTER TABLE fornecedor ADD COLUMN necessita_pais_cliente_final INTEGER NOT NULL DEFAULT 0"
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

    # Migração da tabela fornecedor_marca para marca com coluna de margem
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='marca'"
    )
    marca_existe = c.fetchone() is not None
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fornecedor_marca'"
    )
    fornecedor_marca_existe = c.fetchone() is not None

    if not marca_existe:
        c.execute(
            """
            CREATE TABLE marca (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fornecedor_id INTEGER NOT NULL,
                marca TEXT NOT NULL,
                marca_normalizada TEXT NOT NULL,
                necessita_pais_cliente_final INTEGER NOT NULL DEFAULT 0,
                margem REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                UNIQUE(marca_normalizada)
            )
            """
        )

        if fornecedor_marca_existe:
            c.execute(
                """
                SELECT id,
                       fornecedor_id,
                       TRIM(marca) AS marca,
                       COALESCE(necessita_pais_cliente_final, 0)
                  FROM fornecedor_marca
                 WHERE marca IS NOT NULL AND TRIM(marca) != ''
                """
            )
            marcas_antigas = c.fetchall()

            c.execute(
                """
                SELECT fornecedor_id,
                       TRIM(marca) AS marca,
                       margem_percentual
                  FROM configuracao_margens
                 WHERE ativo = TRUE
                """
            )
            margens_antigas = c.fetchall()
            mapa_margens: dict[tuple[int, str], float] = {}
            for fornecedor_id_ant, marca_ant, margem in margens_antigas:
                marca_normalizada = (marca_ant or "").strip().casefold()
                if not marca_normalizada:
                    continue
                mapa_margens[(fornecedor_id_ant, marca_normalizada)] = float(margem or 0.0)

            for marca_id, fornecedor_id_ant, marca_ant, necessita_ant in marcas_antigas:
                marca_limpa = (marca_ant or "").strip()
                if not marca_limpa:
                    continue
                marca_normalizada = marca_limpa.casefold()
                margem = mapa_margens.get((fornecedor_id_ant, marca_normalizada), 0.0)
                c.execute(
                    """
                    INSERT OR IGNORE INTO marca (
                        id,
                        fornecedor_id,
                        marca,
                        marca_normalizada,
                        necessita_pais_cliente_final,
                        margem
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        marca_id,
                        fornecedor_id_ant,
                        marca_limpa,
                        marca_normalizada,
                        necessita_ant,
                        float(margem),
                    ),
                )

            c.execute("DROP TABLE fornecedor_marca")

    c.execute("PRAGMA table_info(marca)")
    marca_cols = [row[1] for row in c.fetchall()]
    if "marca_normalizada" not in marca_cols:
        c.execute("ALTER TABLE marca ADD COLUMN marca_normalizada TEXT")
        marca_cols.append("marca_normalizada")
    if "necessita_pais_cliente_final" not in marca_cols:
        c.execute(
            "ALTER TABLE marca ADD COLUMN necessita_pais_cliente_final INTEGER NOT NULL DEFAULT 0"
        )
    if "margem" not in marca_cols:
        c.execute(
            "ALTER TABLE marca ADD COLUMN margem REAL NOT NULL DEFAULT 0.0"
        )

    # Garantir normalização dos nomes das marcas e preencher coluna auxiliar
    c.execute(
        """
        SELECT id, marca
          FROM marca
         WHERE marca IS NOT NULL
        """
    )
    marcas_existentes = c.fetchall()
    for marca_id, marca_nome in marcas_existentes:
        marca_limpa = (marca_nome or "").strip()
        marca_normalizada = marca_limpa.casefold() if marca_limpa else ""
        c.execute(
            """
            UPDATE marca
               SET marca = ?, marca_normalizada = ?
             WHERE id = ?
            """,
            (marca_limpa, marca_normalizada, marca_id),
        )

    # Eliminar duplicados mantendo o primeiro registo encontrado
    c.execute(
        """
        SELECT id, marca_normalizada
          FROM marca
         WHERE marca_normalizada IS NOT NULL AND marca_normalizada != ''
         ORDER BY id
        """
    )
    vistos: set[str] = set()
    duplicados: list[int] = []
    for marca_id, marca_normalizada in c.fetchall():
        if marca_normalizada in vistos:
            duplicados.append(marca_id)
        else:
            vistos.add(marca_normalizada)
    for marca_id in duplicados:
        c.execute("DELETE FROM marca WHERE id = ?", (marca_id,))

    c.execute(
        """
        UPDATE fornecedor
           SET necessita_pais_cliente_final = 1
         WHERE id IN (
            SELECT DISTINCT fornecedor_id
              FROM marca
             WHERE necessita_pais_cliente_final = 1
         )
        """
    )

    # Tabela antiga de margens deixa de ser necessária
    c.execute("DROP TABLE IF EXISTS configuracao_margens")

    # Tabelas de lookup normalizadas
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS estado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente_final (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            pais TEXT,
            UNIQUE(nome, pais)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS moeda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS pais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
        """
    )

    # Valores padrão para tabelas de lookup
    for estado_padrao in ("ativo", "pendente", "respondido", "arquivada"):
        try:
            ensure_estado(estado_padrao, cursor=c)
        except ValueError:
            pass

    try:
        ensure_moeda("EUR", cursor=c)
    except ValueError:
        pass

    # Tabela de processos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            descricao TEXT,
            data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
            estado TEXT DEFAULT 'ativo',
            estado_id INTEGER,
            responsavel_id INTEGER,
            FOREIGN KEY (estado_id) REFERENCES estado(id)
                ON DELETE SET NULL,
            FOREIGN KEY (responsavel_id) REFERENCES utilizador(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo)")
    processo_cols = [row[1] for row in c.fetchall()]
    if "estado_id" not in processo_cols:
        c.execute("ALTER TABLE processo ADD COLUMN estado_id INTEGER REFERENCES estado(id)")
    if "responsavel_id" not in processo_cols:
        c.execute(
            "ALTER TABLE processo ADD COLUMN responsavel_id INTEGER REFERENCES utilizador(id)"
        )

    c.execute(
        "SELECT id, COALESCE(estado, 'ativo') FROM processo WHERE estado_id IS NULL"
    )
    for proc_id, estado_nome in c.fetchall():
        estado_id = ensure_estado(estado_nome or "ativo", cursor=c)
        c.execute(
            "UPDATE processo SET estado_id = ?, estado = ? WHERE id = ?",
            (estado_id, estado_nome or "ativo", proc_id),
        )

    # Tabela RFQ (pedidos enviados aos fornecedores)
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

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS solicitante (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            email TEXT,
            telefone TEXT,
            empresa TEXT,
            UNIQUE(nome, email, telefone, empresa)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER,
            fornecedor_id INTEGER NOT NULL,
            cliente_id INTEGER,
            solicitante_id INTEGER,
            data TEXT NOT NULL,
            estado TEXT DEFAULT 'pendente',
            referencia TEXT NOT NULL,
            observacoes TEXT,
            nome_solicitante TEXT,
            email_solicitante TEXT,
            telefone_solicitante TEXT,
            empresa_solicitante TEXT,
            cliente_final_nome TEXT,
            cliente_final_pais TEXT,
            cliente_final_id INTEGER,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
            utilizador_id INTEGER,
            estado_id INTEGER,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE SET NULL,
            FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL,
            FOREIGN KEY (solicitante_id) REFERENCES solicitante(id) ON DELETE SET NULL,
            FOREIGN KEY (cliente_final_id) REFERENCES cliente_final(id) ON DELETE SET NULL,
            FOREIGN KEY (estado_id) REFERENCES estado(id) ON DELETE SET NULL
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
                    cliente_final_nome TEXT,
                    cliente_final_pais TEXT,
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
                    "cliente_final_nome",
                    "cliente_final_pais",
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
    if "cliente_final_nome" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN cliente_final_nome TEXT")
    if "cliente_final_pais" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN cliente_final_pais TEXT")
    if "cliente_final_id" not in rfq_columns:
        c.execute(
            "ALTER TABLE rfq ADD COLUMN cliente_final_id INTEGER REFERENCES cliente_final(id)"
        )
    if "estado_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN estado_id INTEGER REFERENCES estado(id)")
    if "solicitante_id" not in rfq_columns:
        c.execute(
            "ALTER TABLE rfq ADD COLUMN solicitante_id INTEGER REFERENCES solicitante(id)"
        )
        rfq_columns.append("solicitante_id")

    if {
        "nome_solicitante",
        "email_solicitante",
        "telefone_solicitante",
        "empresa_solicitante",
        "solicitante_id",
    }.issubset(set(rfq_columns)):
        c.execute(
            """
            SELECT id,
                   COALESCE(nome_solicitante, ''),
                   COALESCE(email_solicitante, ''),
                   COALESCE(telefone_solicitante, ''),
                   COALESCE(empresa_solicitante, '')
              FROM rfq
             WHERE solicitante_id IS NULL
            """
        )
        solicitantes_antigos = c.fetchall()
        for rfq_id, nome_ant, email_ant, telefone_ant, empresa_ant in solicitantes_antigos:
            solicitante_id = ensure_solicitante(
                nome_ant, email_ant, telefone_ant, empresa_ant, cursor=c
            )
            if solicitante_id:
                c.execute(
                    "UPDATE rfq SET solicitante_id = ? WHERE id = ?",
                    (solicitante_id, rfq_id),
                )

    if "cliente_final_nome" in rfq_columns and "cliente_final_id" in rfq_columns:
        c.execute(
            """
            INSERT OR IGNORE INTO cliente_final (nome, pais)
            SELECT DISTINCT TRIM(COALESCE(cliente_final_nome, '')),
                            NULLIF(TRIM(COALESCE(cliente_final_pais, '')), '')
              FROM rfq
             WHERE cliente_final_nome IS NOT NULL
               AND TRIM(cliente_final_nome) != ''
            """
        )

        c.execute(
            """
            UPDATE rfq
               SET cliente_final_id = (
                    SELECT id
                      FROM cliente_final
                     WHERE nome = TRIM(COALESCE(rfq.cliente_final_nome, ''))
                       AND (
                            (cliente_final.pais IS NULL AND (rfq.cliente_final_pais IS NULL OR TRIM(rfq.cliente_final_pais) = ''))
                            OR cliente_final.pais = TRIM(COALESCE(rfq.cliente_final_pais, ''))
                       )
                )
             WHERE cliente_final_id IS NULL
               AND cliente_final_nome IS NOT NULL
               AND TRIM(cliente_final_nome) != ''
            """
        )

    c.execute(
        "SELECT id, COALESCE(estado, 'pendente') FROM rfq WHERE estado_id IS NULL"
    )
    for rfq_id, estado_nome in c.fetchall():
        estado_id = ensure_estado(estado_nome or "pendente", cursor=c)
        c.execute(
            "UPDATE rfq SET estado_id = ?, estado = ? WHERE id = ?",
            (estado_id, estado_nome or "pendente", rfq_id),
        )

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
            marca_id INTEGER,
            artigo_catalogo_id INTEGER,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE,
            FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL,
            FOREIGN KEY (artigo_catalogo_id) REFERENCES artigo_catalogo(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo_artigo)")
    proc_art_cols = [row[1] for row in c.fetchall()]
    if "marca_id" not in proc_art_cols:
        c.execute(
            "ALTER TABLE processo_artigo ADD COLUMN marca_id INTEGER REFERENCES marca(id)"
        )
    if "artigo_catalogo_id" not in proc_art_cols:
        c.execute(
            "ALTER TABLE processo_artigo ADD COLUMN artigo_catalogo_id INTEGER REFERENCES artigo_catalogo(id)"
        )

    c.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_processo_artigo_catalogo
        ON processo_artigo(processo_id, artigo_catalogo_id)
        WHERE artigo_catalogo_id IS NOT NULL
        """
    )

    c.execute(
        """
        UPDATE processo_artigo
           SET marca_id = (
                SELECT id
                  FROM marca
                 WHERE marca_normalizada = PYCASEFOLD(COALESCE(processo_artigo.marca, ''))
           )
         WHERE marca_id IS NULL
           AND marca IS NOT NULL
           AND TRIM(marca) != ''
        """
    )

    c.execute(
        """
        UPDATE processo_artigo
           SET artigo_catalogo_id = (
                SELECT id
                  FROM artigo_catalogo
                 WHERE artigo_num = processo_artigo.artigo_num
           )
         WHERE artigo_catalogo_id IS NULL
           AND artigo_num IS NOT NULL
           AND TRIM(artigo_num) != ''
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
            marca_id INTEGER,
            artigo_catalogo_id INTEGER,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE CASCADE,
            FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL,
            FOREIGN KEY (artigo_catalogo_id) REFERENCES artigo_catalogo(id) ON DELETE SET NULL
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
    if "marca_id" not in artigo_cols:
        c.execute(
            "ALTER TABLE artigo ADD COLUMN marca_id INTEGER REFERENCES marca(id)"
        )
    if "artigo_catalogo_id" not in artigo_cols:
        c.execute(
            "ALTER TABLE artigo ADD COLUMN artigo_catalogo_id INTEGER REFERENCES artigo_catalogo(id)"
        )

    c.execute(
        """
        UPDATE artigo
           SET marca_id = (
                SELECT id
                  FROM marca
                 WHERE marca_normalizada = PYCASEFOLD(COALESCE(artigo.marca, ''))
           )
         WHERE marca_id IS NULL
           AND marca IS NOT NULL
           AND TRIM(marca) != ''
        """
    )

    c.execute(
        """
        UPDATE artigo
           SET artigo_catalogo_id = (
                SELECT id
                  FROM artigo_catalogo
                 WHERE artigo_num = artigo.artigo_num
           )
         WHERE artigo_catalogo_id IS NULL
           AND artigo_num IS NOT NULL
           AND TRIM(artigo_num) != ''
        """
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
            selecionado_por INTEGER,
            acao TEXT,
            FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE CASCADE,
            FOREIGN KEY (resposta_id) REFERENCES resposta_fornecedor(id) ON DELETE SET NULL,
            FOREIGN KEY (selecionado_por) REFERENCES utilizador(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo_artigo_selecao)")
    selecao_cols = [row[1] for row in c.fetchall()]
    if "enviado_cliente_em" not in selecao_cols:
        c.execute(
            "ALTER TABLE processo_artigo_selecao ADD COLUMN enviado_cliente_em TEXT"
        )
    if "selecionado_por" not in selecao_cols:
        c.execute(
            "ALTER TABLE processo_artigo_selecao ADD COLUMN selecionado_por INTEGER REFERENCES utilizador(id)"
        )
    if "acao" not in selecao_cols:
        c.execute("ALTER TABLE processo_artigo_selecao ADD COLUMN acao TEXT")

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
            pais_origem_id INTEGER,
            moeda_id INTEGER,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
            FOREIGN KEY (pais_origem_id) REFERENCES pais(id) ON DELETE SET NULL,
            FOREIGN KEY (moeda_id) REFERENCES moeda(id) ON DELETE SET NULL,
            UNIQUE (fornecedor_id, rfq_id, artigo_id)
        )
        """
    )

    c.execute("PRAGMA table_info(resposta_fornecedor)")
    resposta_cols = [row[1] for row in c.fetchall()]
    if "pais_origem_id" not in resposta_cols:
        c.execute(
            "ALTER TABLE resposta_fornecedor ADD COLUMN pais_origem_id INTEGER REFERENCES pais(id)"
        )
    if "moeda_id" not in resposta_cols:
        c.execute(
            "ALTER TABLE resposta_fornecedor ADD COLUMN moeda_id INTEGER REFERENCES moeda(id)"
        )

    c.execute(
        """
        INSERT OR IGNORE INTO moeda (codigo)
        SELECT DISTINCT TRIM(COALESCE(moeda, ''))
          FROM resposta_fornecedor
         WHERE moeda IS NOT NULL
           AND TRIM(moeda) != ''
        """
    )

    c.execute(
        """
        UPDATE resposta_fornecedor
           SET moeda_id = (
                SELECT id
                  FROM moeda
                 WHERE codigo = TRIM(COALESCE(resposta_fornecedor.moeda, ''))
           )
         WHERE moeda_id IS NULL
           AND moeda IS NOT NULL
           AND TRIM(moeda) != ''
        """
    )

    c.execute(
        """
        INSERT OR IGNORE INTO pais (nome)
        SELECT DISTINCT TRIM(COALESCE(pais_origem, ''))
          FROM resposta_fornecedor
         WHERE pais_origem IS NOT NULL
           AND TRIM(pais_origem) != ''
        """
    )

    c.execute(
        """
        UPDATE resposta_fornecedor
           SET pais_origem_id = (
                SELECT id
                  FROM pais
                 WHERE nome = TRIM(COALESCE(resposta_fornecedor.pais_origem, ''))
           )
         WHERE pais_origem_id IS NULL
           AND pais_origem IS NOT NULL
           AND TRIM(pais_origem) != ''
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
            banco TEXT,
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
        ("banco", "TEXT"),
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
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_marca_normalizada ON marca(marca_normalizada)",
        "CREATE INDEX IF NOT EXISTS idx_marca_fornecedor ON marca(fornecedor_id)",
        "CREATE INDEX IF NOT EXISTS idx_cliente_nome ON cliente(nome)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_solicitante ON rfq(solicitante_id)",
        "CREATE INDEX IF NOT EXISTS idx_processo_responsavel ON processo(responsavel_id)",
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

def criar_processo(descricao: str = "", responsavel_id: int | None = None):
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

        estado_nome = "ativo"
        estado_id = ensure_estado(estado_nome)
        insert_result = session.execute(
            text(
                "INSERT INTO processo (numero, descricao, estado, estado_id, responsavel_id) "
                "VALUES (:numero, :descricao, :estado, :estado_id, :responsavel_id)"
            ),
            {
                "numero": numero,
                "descricao": descricao,
                "estado": estado_nome,
                "estado_id": estado_id,
                "responsavel_id": responsavel_id,
            },
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
