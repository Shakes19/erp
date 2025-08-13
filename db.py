import os
from datetime import datetime

import psycopg2
from psycopg2 import extensions


# String de ligação à base de dados. Pode ser configurada através da variável
# de ambiente DATABASE_URL. Inclui a palavra-passe fornecida.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres.metfqkdducobgjkjrris:MkA2w%2FE%21G3ErJUu@"
    "aws-1-eu-west-3.pooler.supabase.com:5432/postgres",
)


class QMarkCursor(psycopg2.extensions.cursor):
    """Cursor que permite o uso do estilo de parâmetros '?' como no sqlite."""

    def execute(self, query, vars=None):  # type: ignore[override]
        if vars is not None:
            query = query.replace("?", "%s")
        return super().execute(query, vars)


def obter_conexao():
    """Devolve uma ligação à base de dados PostgreSQL."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=QMarkCursor)


def criar_base_dados():
    """Cria todas as tabelas necessárias na base de dados."""
    conn = None
    try:
        conn = obter_conexao()
        cur = conn.cursor()

        # Tabela de fornecedores
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fornecedor (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE,
                email TEXT,
                telefone TEXT,
                morada TEXT,
                nif TEXT,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Marcas por fornecedor
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fornecedor_marca (
                id SERIAL PRIMARY KEY,
                fornecedor_id INTEGER NOT NULL,
                marca TEXT NOT NULL,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                UNIQUE(fornecedor_id, marca)
            )
            """
        )

        # Processos
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS processo (
                id SERIAL PRIMARY KEY,
                numero TEXT NOT NULL UNIQUE,
                descricao TEXT,
                data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                estado TEXT DEFAULT 'ativo'
            )
            """
        )

        # RFQ
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS rfq (
                id SERIAL PRIMARY KEY,
                processo_id INTEGER,
                fornecedor_id INTEGER NOT NULL,
                data DATE NOT NULL,
                estado TEXT DEFAULT 'pendente',
                referencia TEXT NOT NULL UNIQUE,
                observacoes TEXT,
                nome_solicitante TEXT,
                email_solicitante TEXT,
                telefone_solicitante TEXT,
                empresa_solicitante TEXT,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                utilizador_id INTEGER,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL,
                FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL
            )
            """
        )

        # Artigos
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS artigo (
                id SERIAL PRIMARY KEY,
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

        # Respostas dos fornecedores
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS resposta_fornecedor (
                id SERIAL PRIMARY KEY,
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
                data_resposta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                validade_dias INTEGER DEFAULT 30,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE,
                FOREIGN KEY (artigo_id) REFERENCES artigo(id) ON DELETE CASCADE,
                UNIQUE (fornecedor_id, rfq_id, artigo_id)
            )
            """
        )

        # Armazenamento de PDFs
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_storage (
                id SERIAL PRIMARY KEY,
                rfq_id TEXT NOT NULL,
                tipo_pdf TEXT NOT NULL,
                pdf_data BYTEA NOT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tamanho_bytes INTEGER,
                nome_ficheiro TEXT,
                UNIQUE(rfq_id, tipo_pdf)
            )
            """
        )

        # Configuração de margens
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracao_margens (
                id SERIAL PRIMARY KEY,
                fornecedor_id INTEGER,
                marca TEXT,
                margem REAL DEFAULT 10.0,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                UNIQUE(fornecedor_id, marca)
            )
            """
        )

        # Configuração de email
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracao_email (
                id SERIAL PRIMARY KEY,
                smtp_server TEXT,
                smtp_port INTEGER,
                email TEXT,
                password TEXT
            )
            """
        )

        # Configuração da empresa
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS configuracao_empresa (
                id SERIAL PRIMARY KEY,
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

        # Utilizadores
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS utilizador (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                nome TEXT,
                email TEXT UNIQUE,
                role TEXT DEFAULT 'user',
                email_password TEXT
            )
            """
        )

        # Logs do sistema
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sistema_log (
                id SERIAL PRIMARY KEY,
                acao TEXT NOT NULL,
                tabela_afetada TEXT,
                registo_id INTEGER,
                dados_antes TEXT,
                dados_depois TEXT,
                utilizador TEXT,
                data_log TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Índices
        indices = [
            "CREATE INDEX IF NOT EXISTS idx_rfq_fornecedor ON rfq(fornecedor_id)",
            "CREATE INDEX IF NOT EXISTS idx_rfq_data ON rfq(data)",
            "CREATE INDEX IF NOT EXISTS idx_rfq_estado ON rfq(estado)",
            "CREATE INDEX IF NOT EXISTS idx_rfq_referencia ON rfq(referencia)",
            "CREATE INDEX IF NOT EXISTS idx_artigo_rfq ON artigo(rfq_id)",
            "CREATE INDEX IF NOT EXISTS idx_resposta_fornecedor ON resposta_fornecedor(fornecedor_id, rfq_id)",
            "CREATE INDEX IF NOT EXISTS idx_resposta_artigo ON resposta_fornecedor(artigo_id)",
            "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)",
        ]
        for indice in indices:
            cur.execute(indice)

        conn.commit()
    finally:
        if conn:
            conn.close()


def verificar_integridade_db():
    """Verifica se a ligação à base de dados está funcional."""
    try:
        conn = obter_conexao()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return True
    except Exception:
        return False
    finally:
        if conn:
            conn.close()


def backup_database(*_args, **_kwargs):
    """Placeholder para backup da base de dados externa."""
    print("Backup não implementado para base de dados externa.")


def gerar_numero_processo():
    """Gera um número interno único para o processo no formato QTYYYY-X."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    conn = obter_conexao()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(CAST(SUBSTRING(numero FROM 8) AS INTEGER)) FROM processo WHERE numero LIKE %s",
            (f"{prefixo}%",),
        )
        max_seq = cur.fetchone()[0]
    finally:
        conn.close()
    proximo = (max_seq or 0) + 1
    return f"{prefixo}{proximo}"


def criar_processo(descricao=""):
    """Cria um novo processo com número interno sequencial por ano."""
    numero = gerar_numero_processo()
    conn = obter_conexao()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO processo (numero, descricao) VALUES (%s, %s)",
            (numero, descricao),
        )
        conn.commit()
        return cur.lastrowid, numero
    finally:
        conn.close()

