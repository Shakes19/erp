"""Database utilities for the ERP system.

This module provides a small wrapper around a local SQLite database using
SQLAlchemy.  All data is stored in a file on the same machine that hosts the
application, ensuring the project can run entirely offline without any remote
database dependencies.
"""

import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Connection information ----------------------------------------------------
# ``DB_PATH`` points to the SQLite database file.  It can be overridden via an
# environment variable for testing, but the application always uses a local
# SQLite database.
DB_PATH = os.environ.get("DB_PATH", "cotacoes.db")
EMAIL_SECRET_ENV = "EMAIL_SECRET_KEY"
EMAIL_SECRET_FILE = Path("email.env")

engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@lru_cache(maxsize=1)
def _legacy_get_email_secret_key() -> bytes:
    """Return the symmetric key used by legacy email password encryption."""

    env_value = os.environ.get(EMAIL_SECRET_ENV)
    if env_value:
        return env_value.encode("utf-8")

    if EMAIL_SECRET_FILE.exists():
        saved = EMAIL_SECRET_FILE.read_text(encoding="utf-8").strip()
        if saved:
            os.environ[EMAIL_SECRET_ENV] = saved
            return saved.encode("utf-8")

    generated = Fernet.generate_key()
    EMAIL_SECRET_FILE.write_text(generated.decode("utf-8"), encoding="utf-8")
    os.environ[EMAIL_SECRET_ENV] = generated.decode("utf-8")
    return generated


def encrypt_email_password(password: str | None) -> str | None:
    """Encrypt ``password`` with a symmetric key for later retrieval."""

    if not password:
        return None

    key = _legacy_get_email_secret_key()
    token = Fernet(key).encrypt(password.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_email_password(value: str | bytes | None) -> str | None:
    """Decrypt or normalise stored email passwords.

    Supports existing Fernet tokens and plain-text values (for legacy
    databases).  Bcrypt hashes are intentionally ignored because they are not
    reversible.
    """

    if value is None:
        return None

    if isinstance(value, (bytes, bytearray, memoryview)):
        token = bytes(value).decode("utf-8", errors="ignore")
    else:
        token = str(value)

    token = token.strip()
    if not token or token.startswith("$2"):
        # Bcrypt hashes (new format) cannot be reversed.
        return None

    try:
        key = _legacy_get_email_secret_key()
        plain = Fernet(key).decrypt(token.encode("utf-8"))
        return plain.decode("utf-8")
    except (InvalidToken, ValueError):
        # Value is not encrypted; treat it as plain text so it can be migrated.
        return token


def has_user_email_password(user_id: int | None) -> bool:
    """Return ``True`` when ``user_id`` has an email password stored."""

    if not user_id:
        return False
    row = fetch_one(
        "SELECT email_password FROM utilizador WHERE id = ?",
        (user_id,),
    )
    if not row:
        return False
    value = row[0]
    if value is None:
        return False
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bool(bytes(value).strip())
    return bool(str(value).strip())


def get_user_email_password(user_id: int | None) -> str | None:
    """Return the decrypted email password for ``user_id`` when available."""

    if not user_id:
        return None

    row = fetch_one(
        "SELECT email_password FROM utilizador WHERE id = ?",
        (user_id,),
    )
    if not row:
        return None
    return decrypt_email_password(row[0])


@lru_cache(maxsize=None)
def get_table_columns(table: str) -> set[str]:
    """Return the column names of ``table`` using PRAGMA table_info."""

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table):
        raise ValueError("Nome de tabela inválido")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cursor.fetchall()}
    finally:
        conn.close()


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
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
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


def ensure_unidade(nome: str, cursor: sqlite3.Cursor | None = None) -> int:
    """Return the identifier for ``nome`` in ``unidade`` creating it if needed."""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        raise ValueError("Unidade deve ser um texto não vazio")

    nome_normalizado = nome_limpo.casefold()
    own_connection = cursor is None
    conn: sqlite3.Connection | None = None
    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    assert cursor is not None
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO unidade (nome, nome_normalizada) VALUES (?, ?)",
            (nome_limpo, nome_normalizado),
        )
        cursor.execute(
            "SELECT id FROM unidade WHERE nome_normalizada = ?",
            (nome_normalizado,),
        )
        row = cursor.fetchone()
        if own_connection and conn is not None:
            conn.commit()
        if not row:
            raise ValueError("Não foi possível garantir a unidade pedida")
        return int(row[0])
    finally:
        if own_connection and conn is not None:
            conn.close()


def obter_processo_id_por_rfq(
    rfq_id: int | str | None, *, cursor: sqlite3.Cursor | None = None
) -> int | None:
    """Return the ``processo_id`` associado a ``rfq_id`` se existir."""

    if rfq_id is None:
        return None

    try:
        rfq_int = int(rfq_id)
    except (TypeError, ValueError):
        return None

    own_connection = cursor is None
    conn: sqlite3.Connection | None = None

    if own_connection:
        conn = get_connection()
        cursor = conn.cursor()

    assert cursor is not None

    try:
        cursor.execute("SELECT processo_id FROM rfq WHERE id = ?", (rfq_int,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        if own_connection and conn is not None:
            conn.close()


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
            condicoes_pagamento TEXT,
            tempo_envio REAL
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
    if "tempo_envio" not in empresa_cols:
        c.execute("ALTER TABLE cliente_empresa ADD COLUMN tempo_envio REAL")

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
                margem REAL NOT NULL DEFAULT 0.0,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                UNIQUE(marca_normalizada)
            )
            """
        )

        if fornecedor_marca_existe:
            c.execute("PRAGMA table_info(fornecedor_marca)")
            fornecedor_marca_cols = {row[1] for row in c.fetchall()}
            coluna_pais_cliente_final = (
                "COALESCE(necessita_pais_cliente_final, 0)"
                if "necessita_pais_cliente_final" in fornecedor_marca_cols
                else "0"
            )
            c.execute(
                f"""
                SELECT id,
                       fornecedor_id,
                       TRIM(marca) AS marca,
                       {coluna_pais_cliente_final}
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
                        margem
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        marca_id,
                        fornecedor_id_ant,
                        marca_limpa,
                        marca_normalizada,
                        float(margem),
                    ),
                )
                if necessita_ant:
                    c.execute(
                        """
                        UPDATE fornecedor
                           SET necessita_pais_cliente_final = 1
                         WHERE id = ?
                        """,
                        (fornecedor_id_ant,),
                    )

            c.execute("DROP TABLE fornecedor_marca")

    c.execute("PRAGMA table_info(marca)")
    marca_cols = [row[1] for row in c.fetchall()]
    if "marca_normalizada" not in marca_cols:
        c.execute("ALTER TABLE marca ADD COLUMN marca_normalizada TEXT")
        marca_cols.append("marca_normalizada")
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

    # Tabela antiga de margens deixa de ser necessária
    c.execute("DROP TABLE IF EXISTS configuracao_margens")

    # Tabela de unidades normalizadas
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS unidade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            nome_normalizada TEXT NOT NULL UNIQUE
        )
        """
    )

    c.execute("PRAGMA table_info(unidade)")
    unidade_cols = [row[1] for row in c.fetchall()]
    if "nome_normalizada" not in unidade_cols:
        c.execute("ALTER TABLE unidade ADD COLUMN nome_normalizada TEXT")
        unidade_cols.append("nome_normalizada")

    c.execute(
        """
        SELECT id, nome
          FROM unidade
         WHERE nome IS NOT NULL
        """
    )
    unidades_existentes = c.fetchall()
    for unidade_id, unidade_nome in unidades_existentes:
        nome_limpo = (unidade_nome or "").strip()
        normalizada = nome_limpo.casefold() if nome_limpo else ""
        c.execute(
            """
            UPDATE unidade
               SET nome = ?, nome_normalizada = ?
             WHERE id = ?
            """,
            (nome_limpo, normalizada, unidade_id),
        )

    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_unidade_nome_normalizada ON unidade(nome_normalizada)"
    )

    # Tabela de estados normalizados
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS estado (
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

    # Tabela de processos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS processo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            descricao TEXT,
            data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
            ref_cliente TEXT,
            utilizador_id INTEGER,
            cliente_id INTEGER,
            FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
            FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo)")
    processo_info = c.fetchall()
    processo_cols = [row[1] for row in processo_info]
    necessita_migracao_processo = False
    if "ref_cliente" not in processo_cols:
        necessita_migracao_processo = True
    if "utilizador_id" not in processo_cols and "responsavel_id" in processo_cols:
        necessita_migracao_processo = True
    if "estado" in processo_cols or "estado_id" in processo_cols:
        necessita_migracao_processo = True

    if necessita_migracao_processo:
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE processo RENAME TO processo_legacy")
            c.execute(
                """
                CREATE TABLE processo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numero TEXT NOT NULL UNIQUE,
                    descricao TEXT,
                    data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
                    ref_cliente TEXT,
                    utilizador_id INTEGER,
                    cliente_id INTEGER,
                    FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
                    FOREIGN KEY (cliente_id) REFERENCES cliente(id) ON DELETE SET NULL
                )
                """
            )

            c.execute("PRAGMA table_info(processo_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]
            select_ref = "ref_cliente" if "ref_cliente" in legacy_cols else "NULL"
            if "referencia" in legacy_cols and "processo_id" in legacy_cols:
                select_ref = "referencia"
            select_utilizador = "utilizador_id" if "utilizador_id" in legacy_cols else (
                "responsavel_id" if "responsavel_id" in legacy_cols else "NULL"
            )
            select_cliente = "cliente_id" if "cliente_id" in legacy_cols else "NULL"
            c.execute(
                f"""
                INSERT INTO processo (id, numero, descricao, data_abertura, ref_cliente, utilizador_id, cliente_id)
                SELECT id,
                       numero,
                       descricao,
                       data_abertura,
                       {select_ref},
                       {select_utilizador},
                       {select_cliente}
                  FROM processo_legacy
                """
            )
            c.execute("DROP TABLE processo_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

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
        CREATE TABLE IF NOT EXISTS rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER,
            fornecedor_id INTEGER NOT NULL,
            cliente_final_nome TEXT,
            cliente_final_pais TEXT,
            data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
            estado_id INTEGER,
            enviado BOOLEAN NOT NULL CHECK (enviado IN (0, 1)) DEFAULT FALSE,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL,
            FOREIGN KEY (estado_id) REFERENCES estado(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(rfq)")
    rfq_columns = [row[1] for row in c.fetchall()]
    colunas_antigas = {
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
        "utilizador_id",
    }
    necessita_migracao_rfq = False
    if "cliente_final_nome" not in rfq_columns or "data_atualizacao" not in rfq_columns:
        necessita_migracao_rfq = True
    if any(col in rfq_columns for col in colunas_antigas):
        necessita_migracao_rfq = True

    if necessita_migracao_rfq:
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE rfq RENAME TO rfq_legacy")
            c.execute(
                """
                CREATE TABLE rfq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    processo_id INTEGER,
                    fornecedor_id INTEGER NOT NULL,
                    cliente_final_nome TEXT,
                    cliente_final_pais TEXT,
                    data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
                    estado_id INTEGER,
                    enviado BOOLEAN NOT NULL CHECK (enviado IN (0, 1)) DEFAULT FALSE,
                    FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                    FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL,
                    FOREIGN KEY (estado_id) REFERENCES estado(id) ON DELETE SET NULL
                )
                """
            )

            c.execute("PRAGMA table_info(rfq_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]

            if "cliente_id" in legacy_cols:
                c.execute(
                    """
                    UPDATE processo
                       SET cliente_id = (
                            SELECT cliente_id
                              FROM rfq_legacy
                             WHERE rfq_legacy.processo_id = processo.id
                               AND cliente_id IS NOT NULL
                             ORDER BY rfq_legacy.id
                             LIMIT 1
                       )
                     WHERE cliente_id IS NULL
                    """
                )

            if "referencia" in legacy_cols and "processo_id" in legacy_cols:
                c.execute(
                    """
                    UPDATE processo
                       SET ref_cliente = (
                           SELECT referencia
                             FROM rfq_legacy
                            WHERE rfq_legacy.processo_id = processo.id
                              AND referencia IS NOT NULL
                              AND TRIM(referencia) != ''
                         ORDER BY rfq_legacy.id DESC
                            LIMIT 1
                       )
                     WHERE (
                        ref_cliente IS NULL OR TRIM(ref_cliente) = ''
                     )
                       AND EXISTS (
                           SELECT 1
                             FROM rfq_legacy
                            WHERE rfq_legacy.processo_id = processo.id
                              AND referencia IS NOT NULL
                              AND TRIM(referencia) != ''
                       )
                    """
                )

            select_processo = "processo_id" if "processo_id" in legacy_cols else "NULL"
            select_fornecedor = "fornecedor_id" if "fornecedor_id" in legacy_cols else "NULL"
            select_cliente_final_nome = (
                "cliente_final_nome" if "cliente_final_nome" in legacy_cols else "NULL"
            )
            select_cliente_final_pais = (
                "cliente_final_pais" if "cliente_final_pais" in legacy_cols else "NULL"
            )
            select_estado_id = "estado_id" if "estado_id" in legacy_cols else "NULL"
            select_data = "data_atualizacao" if "data_atualizacao" in legacy_cols else (
                "data" if "data" in legacy_cols else "CURRENT_TIMESTAMP"
            )
            c.execute(
                f"""
                INSERT INTO rfq (id, processo_id, fornecedor_id, cliente_final_nome, cliente_final_pais, data_atualizacao, estado_id)
                SELECT id,
                       {select_processo},
                       {select_fornecedor},
                       {select_cliente_final_nome},
                       {select_cliente_final_pais},
                       COALESCE({select_data}, CURRENT_TIMESTAMP),
                       {select_estado_id}
                  FROM rfq_legacy
                """
            )

            c.execute("DROP TABLE rfq_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA table_info(rfq)")
        rfq_columns = [row[1] for row in c.fetchall()]

    if "estado_id" not in rfq_columns:
        c.execute("ALTER TABLE rfq ADD COLUMN estado_id INTEGER REFERENCES estado(id)")

    if "enviado" not in rfq_columns:
        c.execute(
            "ALTER TABLE rfq ADD COLUMN enviado BOOLEAN NOT NULL CHECK (enviado IN (0, 1)) DEFAULT FALSE"
        )

    c.execute(
        """
        SELECT id
          FROM rfq
         WHERE estado_id IS NULL
        """
    )
    for (rfq_id,) in c.fetchall():
        estado_id = ensure_estado("pendente", cursor=c)
        c.execute("UPDATE rfq SET estado_id = ? WHERE id = ?", (estado_id, rfq_id))

    c.execute(
        """
        UPDATE rfq
           SET data_atualizacao = COALESCE(data_atualizacao, CURRENT_TIMESTAMP)
        """
    )

    # Tabela de artigos reutilizável entre RFQs
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_num TEXT,
            descricao TEXT NOT NULL,
            unidade_id INTEGER NOT NULL,
            especificacoes TEXT,
            marca_id INTEGER,
            preco_historico REAL,
            validade_historico TEXT,
            peso REAL,
            hs_code TEXT,
            pais_origem TEXT,
            FOREIGN KEY (unidade_id) REFERENCES unidade(id) ON DELETE RESTRICT,
            FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(artigo)")
    artigo_cols = [row[1] for row in c.fetchall()]
    if "marca_id" not in artigo_cols:
        c.execute(
            "ALTER TABLE artigo ADD COLUMN marca_id INTEGER REFERENCES marca(id)"
        )
    if "preco_historico" not in artigo_cols:
        c.execute("ALTER TABLE artigo ADD COLUMN preco_historico REAL")
    if "validade_historico" not in artigo_cols:
        c.execute("ALTER TABLE artigo ADD COLUMN validade_historico TEXT")
    if "peso" not in artigo_cols:
        c.execute("ALTER TABLE artigo ADD COLUMN peso REAL")
    if "hs_code" not in artigo_cols:
        c.execute("ALTER TABLE artigo ADD COLUMN hs_code TEXT")
    if "pais_origem" not in artigo_cols:
        c.execute("ALTER TABLE artigo ADD COLUMN pais_origem TEXT")

    c.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_artigo_num_unique
            ON artigo(artigo_num)
            WHERE artigo_num IS NOT NULL
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS rfq_artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            artigo_id INTEGER NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER DEFAULT 1,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE
        )
        """
    )

    c.execute("PRAGMA table_info(rfq_artigo)")
    rfq_artigo_cols = [row[1] for row in c.fetchall()]
    legacy_rfqa_cols = {"processo_artigo_id", "artigo_catalogo_id"}
    if legacy_rfqa_cols.intersection(rfq_artigo_cols):
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE rfq_artigo RENAME TO rfq_artigo_legacy")
            c.execute(
                """
                CREATE TABLE rfq_artigo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rfq_id INTEGER NOT NULL,
                    artigo_id INTEGER NOT NULL,
                    quantidade INTEGER NOT NULL DEFAULT 1,
                    ordem INTEGER DEFAULT 1,
                    FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
                    FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE
                )
                """
            )

            select_parts = []
            for coluna in ("id", "rfq_id", "artigo_id", "quantidade", "ordem"):
                if coluna in rfq_artigo_cols:
                    if coluna == "quantidade":
                        select_parts.append("COALESCE(quantidade, 1) AS quantidade")
                    else:
                        select_parts.append(coluna)
                elif coluna == "ordem":
                    select_parts.append("1 AS ordem")
                elif coluna == "quantidade":
                    select_parts.append("1 AS quantidade")
            select_clause = ", ".join(select_parts)
            c.execute(
                f"INSERT INTO rfq_artigo (id, rfq_id, artigo_id, quantidade, ordem) "
                f"SELECT {select_clause} FROM rfq_artigo_legacy"
            )

            c.execute("DROP TABLE rfq_artigo_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

    c.execute("DROP TABLE IF EXISTS processo_artigo")
    c.execute("DROP TABLE IF EXISTS processo_artigo_legacy")
    c.execute("DROP TABLE IF EXISTS processo_artigo_selecao")

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
            moeda TEXT DEFAULT 'EUR',
            preco_venda REAL,
            desconto REAL NOT NULL DEFAULT 0.0,
            preco_venda_desconto REAL,
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

    c.execute("PRAGMA table_info(resposta_fornecedor)")
    resposta_cols = [row[1] for row in c.fetchall()]

    colunas_resposta_antigas = {"peso", "hs_code", "pais_origem"}
    colunas_resposta_desejadas = [
        "id",
        "fornecedor_id",
        "rfq_id",
        "artigo_id",
        "descricao",
        "custo",
        "prazo_entrega",
        "quantidade_final",
        "moeda",
        "preco_venda",
        "desconto",
        "preco_venda_desconto",
        "observacoes",
        "data_resposta",
        "validade_preco",
    ]

    needs_resposta_migration = bool(colunas_resposta_antigas.intersection(resposta_cols))
    if not needs_resposta_migration:
        missing_cols = [col for col in colunas_resposta_desejadas if col not in resposta_cols]
        extra_cols = [col for col in resposta_cols if col not in colunas_resposta_desejadas]
        needs_resposta_migration = bool(missing_cols or extra_cols)

    if needs_resposta_migration:
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE resposta_fornecedor RENAME TO resposta_fornecedor_legacy")
            c.execute(
                """
                CREATE TABLE resposta_fornecedor (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fornecedor_id INTEGER NOT NULL,
                    rfq_id INTEGER NOT NULL,
                    artigo_id INTEGER NOT NULL,
                    descricao TEXT,
                    custo REAL NOT NULL DEFAULT 0.0,
                    prazo_entrega INTEGER NOT NULL DEFAULT 1,
                    quantidade_final INTEGER,
                    moeda TEXT DEFAULT 'EUR',
                    preco_venda REAL,
                    desconto REAL NOT NULL DEFAULT 0.0,
                    preco_venda_desconto REAL,
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

            colunas_novas = colunas_resposta_desejadas
            valores_por_omissao = {
                "descricao": "NULL",
                "custo": "0.0",
                "prazo_entrega": "1",
                "quantidade_final": "NULL",
                "moeda": "'EUR'",
                "preco_venda": "NULL",
                "desconto": "0.0",
                "preco_venda_desconto": "preco_venda",
                "observacoes": "NULL",
                "data_resposta": "CURRENT_TIMESTAMP",
                "validade_preco": "NULL",
            }
            select_clause = []
            for coluna in colunas_novas:
                if coluna in resposta_cols:
                    select_clause.append(coluna)
                else:
                    default_expr = valores_por_omissao.get(coluna, "NULL")
                    select_clause.append(f"{default_expr} AS {coluna}")

            c.execute(
                f"INSERT INTO resposta_fornecedor ({', '.join(colunas_novas)}) "
                f"SELECT {', '.join(select_clause)} FROM resposta_fornecedor_legacy"
            )
            c.execute("DROP TABLE resposta_fornecedor_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA table_info(resposta_fornecedor)")
        resposta_cols = [row[1] for row in c.fetchall()]

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

    # Tabela para armazenamento de PDFs (associada ao processo)
    c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pdf_storage'"
    )
    if c.fetchone():
        c.execute("PRAGMA table_info(pdf_storage)")
        pdf_cols = [row[1] for row in c.fetchall()]
        if pdf_cols and "processo_id" not in pdf_cols:
            c.execute("ALTER TABLE pdf_storage RENAME TO pdf_storage_legacy")
            c.execute(
                """
                CREATE TABLE pdf_storage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    processo_id INTEGER NOT NULL,
                    tipo_pdf TEXT NOT NULL,
                    pdf_data BLOB NOT NULL,
                    data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                    tamanho_bytes INTEGER,
                    nome_ficheiro TEXT,
                    UNIQUE(processo_id, tipo_pdf),
                    FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE
                )
                """
            )
            c.execute(
                """
                INSERT OR REPLACE INTO pdf_storage (
                    processo_id,
                    tipo_pdf,
                    pdf_data,
                    data_criacao,
                    tamanho_bytes,
                    nome_ficheiro
                )
                SELECT rfq.processo_id,
                       legacy.tipo_pdf,
                       legacy.pdf_data,
                       legacy.data_criacao,
                       legacy.tamanho_bytes,
                       legacy.nome_ficheiro
                  FROM pdf_storage_legacy AS legacy
                  JOIN rfq ON CAST(legacy.rfq_id AS INTEGER) = rfq.id
                 WHERE rfq.processo_id IS NOT NULL
                """
            )
            c.execute("DROP TABLE pdf_storage_legacy")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS pdf_storage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            processo_id INTEGER NOT NULL,
            tipo_pdf TEXT NOT NULL,
            pdf_data BLOB NOT NULL,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            tamanho_bytes INTEGER,
            nome_ficheiro TEXT,
            UNIQUE(processo_id, tipo_pdf),
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE
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

    # Converter palavras-passe de email antigas para formato encriptado
    c.execute(
        """
        SELECT id, email_password FROM utilizador
        WHERE email_password IS NOT NULL AND email_password != ''
        """
    )
    for user_id, raw_email_password in c.fetchall():
        if raw_email_password is None:
            continue

        plain_password = decrypt_email_password(raw_email_password)
        if not plain_password:
            continue

        encrypted_value = encrypt_email_password(plain_password)
        if not encrypted_value:
            continue

        c.execute(
            "UPDATE utilizador SET email_password = ? WHERE id = ?",
            (encrypted_value, user_id),
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

    # Remover tabelas legadas que deixaram de ser necessárias
    for tabela_legada in ("cliente_final", "moeda", "pais", "solicitante"):
        c.execute(f"DROP TABLE IF EXISTS {tabela_legada}")

    # Criar índices para melhor performance
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_rfq_fornecedor ON rfq(fornecedor_id)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_processo ON rfq(processo_id)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_estado_id ON rfq(estado_id)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_data_atualizacao ON rfq(data_atualizacao)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_artigo_rfq ON rfq_artigo(rfq_id)",
        "CREATE INDEX IF NOT EXISTS idx_rfq_artigo_artigo ON rfq_artigo(artigo_id)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_fornecedor ON resposta_fornecedor(fornecedor_id, rfq_id)",
        "CREATE INDEX IF NOT EXISTS idx_resposta_artigo ON resposta_fornecedor(artigo_id)",
        "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_marca_normalizada ON marca(marca_normalizada)",
        "CREATE INDEX IF NOT EXISTS idx_marca_fornecedor ON marca(fornecedor_id)",
        "CREATE INDEX IF NOT EXISTS idx_cliente_nome ON cliente(nome)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)",
        "CREATE INDEX IF NOT EXISTS idx_processo_utilizador ON processo(utilizador_id)",
        "CREATE INDEX IF NOT EXISTS idx_processo_ref_cliente ON processo(ref_cliente)",
    ]
    for idx in indices:
        c.execute(idx)

    conn.commit()
    if hasattr(get_table_columns, "cache_clear"):
        get_table_columns.cache_clear()

    # Migração leve: garantir coluna custo_embalagem em bases existentes
    try:
        c.execute("PRAGMA table_info(resposta_custos)")
        rc_cols = [row[1] for row in c.fetchall()]
        if "custo_embalagem" not in rc_cols:
            c.execute(
                "ALTER TABLE resposta_custos ADD COLUMN custo_embalagem REAL DEFAULT 0.0"
            )
            conn.commit()
            if hasattr(get_table_columns, "cache_clear"):
                get_table_columns.cache_clear()
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


def restore_database(backup_path: str):
    """Restore ``DB_PATH`` from ``backup_path`` ensuring WAL files are cleaned."""

    backup_file = Path(backup_path)
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup não encontrado: {backup_path}")

    engine.dispose()

    target = Path(DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)

    # Garantir que ficheiros WAL/SHM antigos não interferem com o restauro
    for suffix in ("-wal", "-shm"):
        wal_file = target.with_name(target.name + suffix)
        if wal_file.exists():
            wal_file.unlink()

    temp_target = target.with_name(target.name + ".restoring")
    shutil.copy2(backup_file, temp_target)
    temp_target.replace(target)

def criar_processo(
    descricao: str = "",
    utilizador_id: int | None = None,
    cliente_id: int | None = None,
    ref_cliente: str | None = None,
):
    """Cria um novo processo com número sequencial anual."""
    ano = datetime.now().year % 100
    prefixo = f"QT{ano:02d}-"
    seq_offset = len(prefixo) + 1
    session = SessionLocal()
    try:
        result = session.execute(
            text(
                "SELECT MAX(CAST(SUBSTR(numero, :offset) AS INTEGER)) FROM processo WHERE numero LIKE :prefixo"
            ),
            {"prefixo": f"{prefixo}%", "offset": seq_offset},
        )
        max_seq = result.scalar()
        numero = f"{prefixo}{(max_seq or 0) + 1}"

        insert_result = session.execute(
            text(
                "INSERT INTO processo (numero, descricao, utilizador_id, cliente_id, ref_cliente) "
                "VALUES (:numero, :descricao, :utilizador_id, :cliente_id, :ref_cliente)"
            ),
            {
                "numero": numero,
                "descricao": descricao,
                "utilizador_id": utilizador_id,
                "cliente_id": cliente_id,
                "ref_cliente": ref_cliente,
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


