"""Database utilities for the ERP system.

This module provides a small wrapper around a local SQLite database using
SQLAlchemy.  All data is stored in a file on the same machine that hosts the
application, ensuring the project can run entirely offline without any remote
database dependencies.
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

import bcrypt
from functools import lru_cache
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DEFAULT_UNIDADES = (
    "Peças",
    "Metros",
    "KG",
    "Litros",
    "Caixas",
    "Paletes",
)

# Connection information ----------------------------------------------------
# ``DB_PATH`` points to the SQLite database file.  It can be overridden via an
# environment variable for testing, but the application always uses a local
# SQLite database.
DB_PATH = os.environ.get("DB_PATH", "cotacoes.db")

engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


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

    c.execute("SELECT COUNT(*) FROM unidade")
    unidades_count = c.fetchone()[0]
    if not unidades_count:
        for nome in DEFAULT_UNIDADES:
            ensure_unidade(nome, cursor=c)

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
            ordem INTEGER DEFAULT 1,
            artigo_id INTEGER,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(processo_artigo)")
    proc_art_cols = [row[1] for row in c.fetchall()]
    legacy_cols_to_remove = {"unidade_id", "marca", "marca_id", "artigo_catalogo_id"}
    if "artigo_id" not in proc_art_cols or legacy_cols_to_remove.intersection(
        proc_art_cols
    ):
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE processo_artigo RENAME TO processo_artigo_legacy")
            c.execute(
                """
                CREATE TABLE processo_artigo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    processo_id INTEGER NOT NULL,
                    artigo_num TEXT,
                    descricao TEXT NOT NULL,
                    quantidade INTEGER NOT NULL DEFAULT 1,
                    ordem INTEGER DEFAULT 1,
                    artigo_id INTEGER,
                    FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE CASCADE,
                    FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE SET NULL
                )
                """
            )

            # Garantir que a tabela de artigos existe antes da migração
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS artigo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artigo_num TEXT,
                    descricao TEXT NOT NULL,
                    unidade_id INTEGER NOT NULL,
                    especificacoes TEXT,
                    marca_id INTEGER,
                    FOREIGN KEY (unidade_id) REFERENCES unidade(id) ON DELETE RESTRICT,
                    FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL
                )
                """
            )

            c.execute("PRAGMA table_info(processo_artigo_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]
            if legacy_cols:
                select_cols = ", ".join(legacy_cols)
                c.execute(
                    f"SELECT {select_cols} FROM processo_artigo_legacy ORDER BY id"
                )
                for row in c.fetchall():
                    dados = dict(zip(legacy_cols, row))
                    unidade_id = dados.get("unidade_id")
                    if unidade_id is None:
                        unidade_nome = dados.get("unidade") or "Peças"
                        try:
                            unidade_id = ensure_unidade(unidade_nome, cursor=c)
                        except ValueError:
                            unidade_id = ensure_unidade("Peças", cursor=c)

                    marca_id = dados.get("marca_id")
                    if marca_id is None:
                        marca_nome = (dados.get("marca") or "").strip()
                        if marca_nome:
                            marca_id = get_marca_id(marca_nome, cursor=c)

                    descricao = dados.get("descricao") or ""
                    if not descricao:
                        descricao = "Descrição indisponível"

                    c.execute(
                        """
                        INSERT INTO artigo (
                            artigo_num,
                            descricao,
                            unidade_id,
                            especificacoes,
                            marca_id
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            dados.get("artigo_num"),
                            descricao,
                            unidade_id,
                            None,
                            marca_id,
                        ),
                    )
                    artigo_id = c.lastrowid

                    quantidade = dados.get("quantidade")
                    if quantidade is None:
                        quantidade = 1

                    ordem = dados.get("ordem")
                    if ordem is None:
                        ordem = 1

                    c.execute(
                        """
                        INSERT INTO processo_artigo (
                            id,
                            processo_id,
                            artigo_num,
                            descricao,
                            quantidade,
                            ordem,
                            artigo_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dados.get("id"),
                            dados.get("processo_id"),
                            dados.get("artigo_num"),
                            descricao,
                            quantidade,
                            ordem,
                            artigo_id,
                        ),
                    )

            c.execute("DROP TABLE processo_artigo_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA table_info(processo_artigo)")
        proc_art_cols = [row[1] for row in c.fetchall()]

    # Tabela de artigos (informação base reutilizável entre RFQs)
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artigo_num TEXT,
            descricao TEXT NOT NULL,
            unidade_id INTEGER NOT NULL,
            especificacoes TEXT,
            marca_id INTEGER,
            FOREIGN KEY (unidade_id) REFERENCES unidade(id) ON DELETE RESTRICT,
            FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL
        )
        """
    )

    # Relação entre RFQs e artigos com metadados específicos
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS rfq_artigo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id INTEGER NOT NULL,
            artigo_id INTEGER NOT NULL,
            quantidade INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER DEFAULT 1,
            processo_artigo_id INTEGER,
            artigo_catalogo_id INTEGER,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
            FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
            FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE SET NULL
        )
        """
    )

    c.execute("PRAGMA table_info(artigo)")
    artigo_cols = [row[1] for row in c.fetchall()]
    legacy_columns = {"rfq_id", "quantidade", "ordem", "processo_artigo_id", "artigo_catalogo_id", "unidade", "marca"}
    if legacy_columns.intersection(artigo_cols):
        c.execute("PRAGMA foreign_keys = OFF")
        try:
            c.execute("ALTER TABLE artigo RENAME TO artigo_legacy")
            c.execute(
                """
                CREATE TABLE artigo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artigo_num TEXT,
                    descricao TEXT NOT NULL,
                    unidade_id INTEGER NOT NULL,
                    especificacoes TEXT,
                    marca_id INTEGER,
                    FOREIGN KEY (unidade_id) REFERENCES unidade(id) ON DELETE RESTRICT,
                    FOREIGN KEY (marca_id) REFERENCES marca(id) ON DELETE SET NULL
                )
                """
            )

            c.execute("PRAGMA table_info(rfq_artigo)")
            rfq_artigo_cols = [row[1] for row in c.fetchall()]
            if not rfq_artigo_cols:
                c.execute(
                    """
                    CREATE TABLE rfq_artigo (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rfq_id INTEGER NOT NULL,
                        artigo_id INTEGER NOT NULL,
                        quantidade INTEGER NOT NULL DEFAULT 1,
                        ordem INTEGER DEFAULT 1,
                        processo_artigo_id INTEGER,
                        artigo_catalogo_id INTEGER,
                        FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
                        FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
                        FOREIGN KEY (processo_artigo_id) REFERENCES processo_artigo(id) ON DELETE SET NULL
                    )
                    """
                )

            c.execute("PRAGMA table_info(artigo_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]
            if legacy_cols:
                select_cols = ", ".join(legacy_cols)
                c.execute(f"SELECT {select_cols} FROM artigo_legacy ORDER BY id")
                for row in c.fetchall():
                    dados = dict(zip(legacy_cols, row))
                    unidade_nome = dados.get("unidade") or "Peças"
                    try:
                        unidade_id = ensure_unidade(unidade_nome, cursor=c)
                    except ValueError:
                        unidade_id = ensure_unidade("Peças", cursor=c)
                    marca_id = dados.get("marca_id")
                    if marca_id is None and dados.get("marca"):
                        marca_id = get_marca_id(dados.get("marca"), cursor=c)

                    c.execute(
                        """
                        INSERT INTO artigo (
                            id,
                            artigo_num,
                            descricao,
                            unidade_id,
                            especificacoes,
                            marca_id
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dados.get("id"),
                            dados.get("artigo_num"),
                            dados.get("descricao"),
                            unidade_id,
                            dados.get("especificacoes"),
                            marca_id,
                        ),
                    )

                    rfq_id = dados.get("rfq_id")
                    if rfq_id is not None:
                        quantidade = dados.get("quantidade") or 1
                        ordem = dados.get("ordem") or 1
                        processo_artigo_id = dados.get("processo_artigo_id")
                        artigo_catalogo_id = dados.get("artigo_catalogo_id")
                        c.execute(
                            """
                            INSERT INTO rfq_artigo (
                                rfq_id,
                                artigo_id,
                                quantidade,
                                ordem,
                                processo_artigo_id,
                                artigo_catalogo_id
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                rfq_id,
                                dados.get("id"),
                                quantidade,
                                ordem,
                                processo_artigo_id,
                                artigo_catalogo_id,
                            ),
                        )

            c.execute("DROP TABLE artigo_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA table_info(artigo)")
        artigo_cols = [row[1] for row in c.fetchall()]

    if "marca_id" not in artigo_cols:
        c.execute(
            "ALTER TABLE artigo ADD COLUMN marca_id INTEGER REFERENCES marca(id)"
        )
    # Remover tabela de seleção de artigos (não é mais necessária)
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
            peso REAL DEFAULT 0.0,
            hs_code TEXT,
            pais_origem TEXT,
            moeda TEXT DEFAULT 'EUR',
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

    c.execute("PRAGMA table_info(resposta_fornecedor)")
    resposta_cols = [row[1] for row in c.fetchall()]
    if "pais_origem_id" in resposta_cols or "moeda_id" in resposta_cols:
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
                    peso REAL DEFAULT 0.0,
                    hs_code TEXT,
                    pais_origem TEXT,
                    moeda TEXT DEFAULT 'EUR',
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

            c.execute("PRAGMA table_info(resposta_fornecedor_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]
            column_order = [
                "id",
                "fornecedor_id",
                "rfq_id",
                "artigo_id",
                "descricao",
                "custo",
                "prazo_entrega",
                "quantidade_final",
                "peso",
                "hs_code",
                "pais_origem",
                "moeda",
                "preco_venda",
                "observacoes",
                "data_resposta",
                "validade_preco",
            ]
            common_cols = [col for col in column_order if col in legacy_cols]
            if common_cols:
                cols_csv = ", ".join(common_cols)
                c.execute(
                    f"INSERT INTO resposta_fornecedor ({cols_csv}) SELECT {cols_csv} FROM resposta_fornecedor_legacy"
                )

            c.execute("DROP TABLE resposta_fornecedor_legacy")
        finally:
            c.execute("PRAGMA foreign_keys = ON")

        c.execute("PRAGMA table_info(resposta_fornecedor)")
        resposta_cols = [row[1] for row in c.fetchall()]

    if "margem_utilizada" in resposta_cols:
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
                    peso REAL DEFAULT 0.0,
                    hs_code TEXT,
                    pais_origem TEXT,
                    moeda TEXT DEFAULT 'EUR',
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

            c.execute("PRAGMA table_info(resposta_fornecedor_legacy)")
            legacy_cols = [row[1] for row in c.fetchall()]
            cols_sem_margem = [col for col in legacy_cols if col != "margem_utilizada"]
            if cols_sem_margem:
                cols_csv = ", ".join(cols_sem_margem)
                c.execute(
                    f"INSERT INTO resposta_fornecedor ({cols_csv}) SELECT {cols_csv} FROM resposta_fornecedor_legacy"
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
        "CREATE INDEX IF NOT EXISTS idx_rfq_artigo_processo ON rfq_artigo(processo_artigo_id)",
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

def criar_processo(
    descricao: str = "",
    utilizador_id: int | None = None,
    cliente_id: int | None = None,
    ref_cliente: str | None = None,
):
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


