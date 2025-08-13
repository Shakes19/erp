import sqlite3
import os
from datetime import datetime

DB_PATH = "cotacoes.db"


def criar_base_dados():
    """Cria e atualiza a base de dados com todas as tabelas necessárias."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA foreign_keys = ON")

        # Tabela de fornecedores
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS fornecedor (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                email TEXT,
                telefone TEXT,
                data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
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

        # Tabela de RFQs
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS rfq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processo_id INTEGER,
                fornecedor_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                estado TEXT DEFAULT 'pendente',
                referencia TEXT,
                observacoes TEXT,
                nome_solicitante TEXT,
                email_solicitante TEXT,
                data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP,
                utilizador_id INTEGER,
                FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
                FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL,
                FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL
            )
            """
        )

        # Garantir colunas extra em rfq
        c.execute("PRAGMA table_info(rfq)")
        columns = [row[1] for row in c.fetchall()]
        if 'utilizador_id' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN utilizador_id INTEGER")
        if 'referencia' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN referencia TEXT")
        if 'observacoes' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN observacoes TEXT")
        if 'nome_solicitante' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN nome_solicitante TEXT")
        if 'email_solicitante' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN email_solicitante TEXT")
        if 'data_criacao' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN data_criacao TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'data_atualizacao' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP")

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
                ordem INTEGER DEFAULT 1,
                FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
            )
            """
        )

        # Ajustes na tabela artigo
        c.execute("PRAGMA table_info(artigo)")
        columns = [row[1] for row in c.fetchall()]
        if 'artigo_num' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN artigo_num TEXT")
        if 'especificacoes' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN especificacoes TEXT")
        if 'ordem' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN ordem INTEGER DEFAULT 1")

        # Tabela de respostas de fornecedores
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
                peso REAL DEFAULT 0.0,
                hs_code TEXT,
                pais_origem TEXT,
                moeda TEXT DEFAULT 'EUR',
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

        c.execute("PRAGMA table_info(resposta_fornecedor)")
        columns = [row[1] for row in c.fetchall()]
        if 'peso' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN peso REAL DEFAULT 0.0")
        if 'hs_code' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN hs_code TEXT")
        if 'pais_origem' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN pais_origem TEXT")
        if 'moeda' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN moeda TEXT DEFAULT 'EUR'")
        if 'observacoes' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN observacoes TEXT")
        if 'data_resposta' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN data_resposta TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'validade_dias' not in columns:
            c.execute("ALTER TABLE resposta_fornecedor ADD COLUMN validade_dias INTEGER DEFAULT 30")

        # Tabela de PDFs
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS pdf_storage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rfq_id INTEGER NOT NULL,
                tipo_pdf TEXT NOT NULL,
                pdf_data BLOB NOT NULL,
                data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                tamanho_bytes INTEGER,
                nome_ficheiro TEXT,
                UNIQUE(rfq_id, tipo_pdf),
                FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
            )
            """
        )
        c.execute("PRAGMA table_info(pdf_storage)")
        columns = [row[1] for row in c.fetchall()]
        if 'id' not in columns or 'nome_ficheiro' not in columns:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS pdf_storage_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rfq_id INTEGER NOT NULL,
                    tipo_pdf TEXT NOT NULL,
                    pdf_data BLOB NOT NULL,
                    data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                    tamanho_bytes INTEGER,
                    nome_ficheiro TEXT,
                    UNIQUE(rfq_id, tipo_pdf),
                    FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
                )
                """
            )
            c.execute(
                """
                INSERT INTO pdf_storage_new (rfq_id, tipo_pdf, pdf_data, data_criacao, tamanho_bytes)
                SELECT rfq_id, tipo_pdf, pdf_data, data_criacao, tamanho_bytes FROM pdf_storage
                """
            )
            c.execute("DROP TABLE pdf_storage")
            c.execute("ALTER TABLE pdf_storage_new RENAME TO pdf_storage")
            c.execute("PRAGMA table_info(pdf_storage)")
            columns = [row[1] for row in c.fetchall()]
        if 'data_criacao' not in columns:
            c.execute("ALTER TABLE pdf_storage ADD COLUMN data_criacao TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'tamanho_bytes' not in columns:
            c.execute("ALTER TABLE pdf_storage ADD COLUMN tamanho_bytes INTEGER")
        if 'nome_ficheiro' not in columns:
            c.execute("ALTER TABLE pdf_storage ADD COLUMN nome_ficheiro TEXT")

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

        c.execute("PRAGMA table_info(configuracao_empresa)")
        cols = [row[1] for row in c.fetchall()]
        for col in ["telefone", "email", "website"]:
            if col not in cols:
                c.execute(f"ALTER TABLE configuracao_empresa ADD COLUMN {col} TEXT")

        # Tabela de logs
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sistema_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                acao TEXT NOT NULL,
                tabela_afetada TEXT,
                registo_id INTEGER,
                dados_antes TEXT,
                dados_depois TEXT,
                utilizador TEXT,
                data_log TEXT DEFAULT CURRENT_TIMESTAMP
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
            "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)"
        ]
        for indice in indices:
            c.execute(indice)

        conn.commit()
        print("Base de dados criada/atualizada com sucesso!")
    except sqlite3.Error as e:
        print(f"Erro ao criar base de dados: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def verificar_integridade_db():
    """Verifica a integridade da base de dados."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA integrity_check")
        resultado = c.fetchone()[0]
        if resultado == "ok":
            print("✅ Integridade da base de dados: OK")
            return True
        else:
            print(f"❌ Problemas de integridade: {resultado}")
            return False
    except sqlite3.Error as e:
        print(f"Erro ao verificar integridade: {e}")
        return False
    finally:
        if conn:
            conn.close()


def backup_database(backup_path="backup_cotacoes.db"):
    """Cria um backup da base de dados."""
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ Backup criado: {backup_path}")
    except Exception as e:
        print(f"Erro ao criar backup: {e}")


def gerar_numero_processo():
    """Gera um número interno único para o processo no formato QTYYYY-X."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT MAX(CAST(substr(numero, 8) AS INTEGER)) FROM processo WHERE numero LIKE ?",
            (f"{prefixo}%",),
        )
        max_seq = c.fetchone()[0]
    finally:
        conn.close()
    proximo = (max_seq or 0) + 1
    return f"{prefixo}{proximo}"


def criar_processo(descricao=""):
    """Cria um novo processo com número interno sequencial por ano."""
    numero = gerar_numero_processo()
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(
            "INSERT INTO processo (numero, descricao) VALUES (?, ?)",
            (numero, descricao),
        )
        conn.commit()
        return c.lastrowid, numero
    finally:
        conn.close()
