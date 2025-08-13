import psycopg2
import psycopg2.extras
from datetime import datetime
import json
from config import DB_CONFIG

def obter_conexao():
    """Retorna uma conexão à base de dados PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.Error as e:
        print(f"Erro ao conectar à base de dados: {e}")
        return None

def criar_base_dados():
    """Cria e atualiza a base de dados com todas as tabelas necessárias."""
    conn = None
    try:
        conn = obter_conexao()
        if not conn:
            return False
            
        c = conn.cursor()

        # Tabela de fornecedores
        c.execute("""
            CREATE TABLE IF NOT EXISTS fornecedor (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(255) NOT NULL UNIQUE,
                email VARCHAR(255),
                telefone VARCHAR(50),
                morada TEXT,
                nif VARCHAR(50),
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabela de marcas por fornecedor
        c.execute("""
            CREATE TABLE IF NOT EXISTS fornecedor_marca (
                id SERIAL PRIMARY KEY,
                fornecedor_id INTEGER NOT NULL REFERENCES fornecedor(id) ON DELETE CASCADE,
                marca VARCHAR(255) NOT NULL,
                UNIQUE(fornecedor_id, marca)
            )
        """)

        # Tabela de processos
        c.execute("""
            CREATE TABLE IF NOT EXISTS processo (
                id SERIAL PRIMARY KEY,
                numero VARCHAR(50) NOT NULL UNIQUE,
                descricao TEXT,
                data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                estado VARCHAR(50) DEFAULT 'ativo'
            )
        """)

        # Tabela de utilizadores
        c.execute("""
            CREATE TABLE IF NOT EXISTS utilizador (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                nome VARCHAR(255),
                email VARCHAR(255),
                role VARCHAR(50) NOT NULL,
                email_password TEXT
            )
        """)

        # Tabela RFQ (Request for Quotation)
        c.execute("""
            CREATE TABLE IF NOT EXISTS rfq (
                id SERIAL PRIMARY KEY,
                processo_id INTEGER REFERENCES processo(id) ON DELETE SET NULL,
                fornecedor_id INTEGER NOT NULL REFERENCES fornecedor(id) ON DELETE CASCADE,
                data DATE NOT NULL,
                estado VARCHAR(50) DEFAULT 'pendente',
                referencia VARCHAR(100) NOT NULL UNIQUE,
                observacoes TEXT,
                nome_solicitante VARCHAR(255),
                email_solicitante VARCHAR(255),
                telefone_solicitante VARCHAR(50),
                empresa_solicitante VARCHAR(255),
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                utilizador_id INTEGER REFERENCES utilizador(id) ON DELETE SET NULL
            )
        """)

        # Tabela de artigos
        c.execute("""
            CREATE TABLE IF NOT EXISTS artigo (
                id SERIAL PRIMARY KEY,
                rfq_id INTEGER NOT NULL REFERENCES rfq(id) ON DELETE CASCADE,
                artigo_num VARCHAR(100),
                descricao TEXT NOT NULL,
                quantidade INTEGER NOT NULL DEFAULT 1,
                unidade VARCHAR(50) NOT NULL DEFAULT 'Peças',
                especificacoes TEXT,
                marca VARCHAR(255),
                ordem INTEGER DEFAULT 1
            )
        """)

        # Tabela de respostas dos fornecedores
        c.execute("""
            CREATE TABLE IF NOT EXISTS resposta_fornecedor (
                id SERIAL PRIMARY KEY,
                fornecedor_id INTEGER NOT NULL REFERENCES fornecedor(id) ON DELETE CASCADE,
                rfq_id INTEGER NOT NULL REFERENCES rfq(id) ON DELETE CASCADE,
                artigo_id INTEGER NOT NULL REFERENCES artigo(id) ON DELETE CASCADE,
                descricao TEXT,
                custo DECIMAL(10,2) NOT NULL DEFAULT 0.0,
                prazo_entrega INTEGER NOT NULL DEFAULT 1,
                quantidade_final INTEGER,
                peso DECIMAL(10,2) DEFAULT 0.0,
                hs_code VARCHAR(50),
                pais_origem VARCHAR(100),
                moeda VARCHAR(10) DEFAULT 'EUR',
                margem_utilizada DECIMAL(5,2) DEFAULT 10.0,
                preco_venda DECIMAL(10,2),
                observacoes TEXT,
                data_resposta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                validade_dias INTEGER DEFAULT 30,
                UNIQUE (fornecedor_id, rfq_id, artigo_id)
            )
        """)

        # Tabela para armazenamento de PDFs
        c.execute("""
            CREATE TABLE IF NOT EXISTS pdf_storage (
                id SERIAL PRIMARY KEY,
                rfq_id VARCHAR(50) NOT NULL,
                tipo_pdf VARCHAR(50) NOT NULL,
                pdf_data BYTEA NOT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tamanho_bytes INTEGER,
                nome_ficheiro VARCHAR(255),
                UNIQUE(rfq_id, tipo_pdf)
            )
        """)

        # Tabela de configuração de margens por marca
        c.execute("""
            CREATE TABLE IF NOT EXISTS configuracao_margens (
                id SERIAL PRIMARY KEY,
                fornecedor_id INTEGER REFERENCES fornecedor(id) ON DELETE CASCADE,
                marca VARCHAR(255),
                margem_percentual DECIMAL(5,2) DEFAULT 10.0,
                ativo BOOLEAN DEFAULT TRUE,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabela de configurações de email
        c.execute("""
            CREATE TABLE IF NOT EXISTS configuracao_email (
                id SERIAL PRIMARY KEY,
                smtp_server VARCHAR(255),
                smtp_port INTEGER,
                email_user VARCHAR(255),
                email_password TEXT,
                ativo BOOLEAN DEFAULT TRUE
            )
        """)

        # Tabela de configuração da empresa
        c.execute("""
            CREATE TABLE IF NOT EXISTS configuracao_empresa (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(255),
                morada TEXT,
                nif VARCHAR(50),
                iban VARCHAR(50),
                telefone VARCHAR(50),
                email VARCHAR(255),
                website VARCHAR(255)
            )
        """)

        # Tabela de logs do sistema
        c.execute("""
            CREATE TABLE IF NOT EXISTS sistema_log (
                id SERIAL PRIMARY KEY,
                acao VARCHAR(255) NOT NULL,
                tabela_afetada VARCHAR(100),
                registo_id INTEGER,
                dados_antes TEXT,
                dados_depois TEXT,
                utilizador VARCHAR(100),
                data_log TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

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
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)"
        ]
        
        for indice in indices:
            try:
                c.execute(indice)
            except psycopg2.Error:
                pass  # Índice já existe

        # Inserir utilizador administrador padrão se a tabela estiver vazia
        c.execute("SELECT COUNT(*) FROM utilizador")
        if c.fetchone()[0] == 0:
            c.execute("""
                INSERT INTO utilizador (username, password, nome, email, role, email_password)
                VALUES ('admin', 'admin', 'Administrador', 'admin@example.com', 'admin', '')
            """)

        # Inserir dados de exemplo se as tabelas estão vazias
        inserir_dados_exemplo(c)

        # Inserir margem padrão se não existir
        c.execute("SELECT COUNT(*) FROM configuracao_margens WHERE fornecedor_id IS NULL AND marca IS NULL")
        if c.fetchone()[0] == 0:
            c.execute("""
                INSERT INTO configuracao_margens (fornecedor_id, marca, margem_percentual)
                VALUES (NULL, NULL, 10.0)
            """)

        conn.commit()
        print("Base de dados PostgreSQL criada/atualizada com sucesso!")
        return True
        
    except psycopg2.Error as e:
        print(f"Erro ao criar base de dados: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def inserir_dados_exemplo(cursor):
    """Insere dados de exemplo se as tabelas estão vazias"""
    try:
        # Verificar se já existem fornecedores
        cursor.execute("SELECT COUNT(*) FROM fornecedor")
        count_fornecedores = cursor.fetchone()[0]
        
        if count_fornecedores == 0:
            # Inserir fornecedores de exemplo
            fornecedores_exemplo = [
                ("Falex", "fornecedor@falex.com", "+351 123 456 789", "Rua Industrial, 123", "123456789"),
                ("Sloap", "vendas@sloap.pt", "+351 987 654 321", "Av. Tecnológica, 456", "987654321"),
                ("Nexautomation", "info@nexautomation.com", "+351 555 123 456", "Zona Industrial, Lote 789", "555666777")
            ]
            
            cursor.executemany("""
                INSERT INTO fornecedor (nome, email, telefone, morada, nif) 
                VALUES (%s, %s, %s, %s, %s)
            """, fornecedores_exemplo)
            
            # Obter IDs dos fornecedores inseridos
            cursor.execute("SELECT id, nome FROM fornecedor")
            fornecedores = cursor.fetchall()
            
            # Inserir marcas de exemplo
            marcas_por_fornecedor = {
                "Falex": ["Schneider Electric", "Phoenix Contact", "Weidmuller"],
                "Sloap": ["ABB", "Siemens"],
                "Nexautomation": ["Omron", "Festo", "SMC", "Sick"]
            }
            
            for forn_id, forn_nome in fornecedores:
                if forn_nome in marcas_por_fornecedor:
                    for marca in marcas_por_fornecedor[forn_nome]:
                        cursor.execute("""
                            INSERT INTO fornecedor_marca (fornecedor_id, marca)
                            VALUES (%s, %s)
                        """, (forn_id, marca))
                        
                        # Inserir margem padrão para cada marca
                        cursor.execute("""
                            INSERT INTO configuracao_margens (fornecedor_id, marca, margem_percentual)
                            VALUES (%s, %s, %s)
                        """, (forn_id, marca, 15.0))  # 15% de margem padrão para marcas
            
            print("Fornecedores e marcas de exemplo inseridos.")
    
    except psycopg2.Error as e:
        print(f"Erro ao inserir dados de exemplo: {e}")

def verificar_integridade_db():
    """Verifica a integridade da base de dados."""
    try:
        conn = obter_conexao()
        if not conn:
            return False
            
        c = conn.cursor()
        
        # Verificar se todas as tabelas principais existem
        tabelas_principais = ['fornecedor', 'rfq', 'artigo', 'utilizador', 'resposta_fornecedor']
        
        for tabela in tabelas_principais:
            c.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """, (tabela,))
            
            if not c.fetchone()[0]:
                print(f"❌ Tabela {tabela} não encontrada")
                return False
        
        print("✅ Integridade da base de dados: OK")
        return True
        
    except psycopg2.Error as e:
        print(f"Erro ao verificar integridade: {e}")
        return False
    finally:
        if conn:
            conn.close()

def backup_database(backup_path=None):
    """Cria um backup da base de dados PostgreSQL usando pg_dump"""
    try:
        if not backup_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"backup_cotacoes_{timestamp}.sql"
        
        import subprocess
        import os
        
        # Comando pg_dump
        cmd = [
            'pg_dump',
            '--no-password',
            '--host', DB_CONFIG['host'],
            '--port', str(DB_CONFIG['port']),
            '--username', DB_CONFIG['user'],
            '--dbname', DB_CONFIG['database'],
            '--file', backup_path
        ]
        
        # Definir a password através de variável de ambiente
        env = os.environ.copy()
        env['PGPASSWORD'] = DB_CONFIG['password']
        
        subprocess.run(cmd, env=env, check=True)
        print(f"✅ Backup criado: {backup_path}")
        return backup_path
        
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None

def gerar_numero_processo():
    """Gera um número interno único para o processo no formato QTYYYY-X."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    
    conn = obter_conexao()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT MAX(CAST(SUBSTRING(numero FROM 8) AS INTEGER)) 
            FROM processo 
            WHERE numero LIKE %s
        """, (f"{prefixo}%",))
        
        result = c.fetchone()
        max_seq = result[0] if result and result[0] else 0
        
    finally:
        if conn:
            conn.close()
    
    proximo = max_seq + 1
    return f"{prefixo}{proximo}"

def criar_processo(descricao=""):
    """Cria um novo processo com número interno sequencial por ano."""
    numero = gerar_numero_processo()
    
    conn = obter_conexao()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO processo (numero, descricao) 
            VALUES (%s, %s) 
            RETURNING id
        """, (numero, descricao))
        
        processo_id = c.fetchone()[0]
        conn.commit()
        return processo_id, numero
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Teste da conexão e criação da base de dados
    if criar_base_dados():
        print("Sistema de base de dados inicializado com sucesso!")
        verificar_integridade_db()
    else:
        print("Erro ao inicializar o sistema de base de dados!")
