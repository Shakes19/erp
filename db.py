import sqlite3
import os

# Definir caminho único da base de dados
DB_PATH = "cotacoes.db"

def criar_base_dados():
    """Cria e configura a base de dados SQLite com todas as tabelas necessárias"""
    
    # Garantir que o diretório existe (se necessário)
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir)
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Ativar foreign keys
        c.execute("PRAGMA foreign_keys = ON")

        # Tabela de fornecedores
        c.execute("""
        CREATE TABLE IF NOT EXISTS fornecedor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            email TEXT,
            telefone TEXT,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Tabela de processos (para futuras expansões)
        c.execute("""
        CREATE TABLE IF NOT EXISTS processo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL UNIQUE,
            descricao TEXT,
            data_abertura TEXT DEFAULT CURRENT_TIMESTAMP,
            estado TEXT DEFAULT 'ativo'
        )
        """)

        # Tabela RFQ (Request for Quotation)
        c.execute("""
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
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (processo_id) REFERENCES processo(id) ON DELETE SET NULL
        )
        """)

        # Verificar e adicionar colunas se não existirem na tabela rfq
        c.execute("PRAGMA table_info(rfq)")
        columns = [column[1] for column in c.fetchall()]
        
        # Verificar se fornecedor_id existe, se não, adicionar
        if 'fornecedor_id' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN fornecedor_id INTEGER")
            # Se existem registros sem fornecedor_id, criar um fornecedor padrão
            c.execute("SELECT COUNT(*) FROM rfq WHERE fornecedor_id IS NULL")
            count_null = c.fetchone()[0]
            if count_null > 0:
                # Inserir fornecedor padrão se não existir
                c.execute("INSERT OR IGNORE INTO fornecedor (nome) VALUES ('Fornecedor Padrão')")
                c.execute("SELECT id FROM fornecedor WHERE nome = 'Fornecedor Padrão'")
                fornecedor_padrao_id = c.fetchone()[0]
                c.execute("UPDATE rfq SET fornecedor_id = ? WHERE fornecedor_id IS NULL", (fornecedor_padrao_id,))
        
        if 'referencia' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN referencia TEXT")
        if 'observacoes' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN observacoes TEXT")
        if 'data_criacao' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN data_criacao TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'data_atualizacao' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN data_atualizacao TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'nome_solicitante' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN nome_solicitante TEXT")
        if 'email_solicitante' not in columns:
            c.execute("ALTER TABLE rfq ADD COLUMN email_solicitante TEXT")

        # Tabela de artigos
        c.execute("""
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
        """)

        # Verificar e migrar tabela de artigos se necessário (remover campo peso antigo)
        c.execute("PRAGMA table_info(artigo)")
        columns = [column[1] for column in c.fetchall()]
        
        if 'peso' in columns:
            # Criar nova tabela sem o campo peso
            c.execute("""
            CREATE TABLE IF NOT EXISTS artigo_new (
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
            """)
            
            # Migrar dados
            c.execute("""
            INSERT INTO artigo_new (id, rfq_id, descricao, quantidade, unidade)
            SELECT id, rfq_id, descricao, quantidade, unidade FROM artigo
            """)
            
            # Substituir tabela
            c.execute("DROP TABLE artigo")
            c.execute("ALTER TABLE artigo_new RENAME TO artigo")

        # Adicionar colunas se não existirem na tabela artigo
        c.execute("PRAGMA table_info(artigo)")
        columns = [column[1] for column in c.fetchall()]
        
        if 'artigo_num' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN artigo_num TEXT")
        if 'especificacoes' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN especificacoes TEXT")
        if 'ordem' not in columns:
            c.execute("ALTER TABLE artigo ADD COLUMN ordem INTEGER DEFAULT 1")

        # Tabela de respostas dos fornecedores
        c.execute("""
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
        """)

        # Verificar e adicionar colunas se não existirem na tabela resposta_fornecedor
        c.execute("PRAGMA table_info(resposta_fornecedor)")
        columns = [column[1] for column in c.fetchall()]
        
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

        # Tabela para armazenamento de PDFs
        c.execute("""
        CREATE TABLE IF NOT EXISTS pdf_storage (
            rfq_id INTEGER PRIMARY KEY,
            pdf_data BLOB NOT NULL,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            tamanho_bytes INTEGER,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
        )
        """)

        # Verificar e adicionar colunas se não existirem na tabela pdf_storage
        c.execute("PRAGMA table_info(pdf_storage)")
        columns = [column[1] for column in c.fetchall()]
        
        if 'data_criacao' not in columns:
            c.execute("ALTER TABLE pdf_storage ADD COLUMN data_criacao TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'tamanho_bytes' not in columns:
            c.execute("ALTER TABLE pdf_storage ADD COLUMN tamanho_bytes INTEGER")

        # Tabela de logs do sistema (para auditoria)
        c.execute("""
        CREATE TABLE IF NOT EXISTS sistema_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acao TEXT NOT NULL,
            tabela_afetada TEXT,
            registro_id INTEGER,
            dados_antes TEXT,
            dados_depois TEXT,
            usuario TEXT,
            data_log TEXT DEFAULT CURRENT_TIMESTAMP
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
            "CREATE INDEX IF NOT EXISTS idx_fornecedor_nome ON fornecedor(nome)"
        ]
        
        for indice in indices:
            c.execute(indice)

        # Inserir dados de exemplo se as tabelas estão vazias
        inserir_dados_exemplo(c)

        # Commit e fechar
        conn.commit()
        print("Base de dados criada/atualizada com sucesso!")
        
    except sqlite3.Error as e:
        print(f"Erro ao criar base de dados: {e}")
        if conn:
            conn.rollback()
    except Exception as e:
        print(f"Erro inesperado: {e}")
        if conn:
            conn.rollback()
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
                ("Falex", "fornecedor@falex.com", "+351 123 456 789"),
                ("Sloap", "vendas@sloap.pt", "+351 987 654 321"),
                ("Nexautomation", "info@nexautomation.com", "+351 555 123 456")
            ]
            
            cursor.executemany("""
                INSERT INTO fornecedor (nome, email, telefone) 
                VALUES (?, ?, ?)
            """, fornecedores_exemplo)
            
            print("Fornecedores de exemplo inseridos.")
    
    except sqlite3.Error as e:
        print(f"Erro ao inserir dados de exemplo: {e}")

def verificar_integridade_db():
    """Verifica a integridade da base de dados"""
    
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Verificar integridade
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
    """Cria um backup da base de dados"""
    
    try:
        import shutil
        shutil.copy2(DB_PATH, backup_path)
        print(f"✅ Backup criado: {backup_path}")
        return True
    except Exception as e:
        print(f"❌ Erro ao criar backup: {e}")
        return False

def limpar_dados_orfaos():
    """Limpa dados órfãos da base de dados"""
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Limpar PDFs órfãos
        c.execute("""
            DELETE FROM pdf_storage 
            WHERE rfq_id NOT IN (SELECT id FROM rfq)
        """)
        pdfs_removidos = c.rowcount
        
        # Limpar respostas órfãs
        c.execute("""
            DELETE FROM resposta_fornecedor 
            WHERE rfq_id NOT IN (SELECT id FROM rfq)
        """)
        respostas_removidas = c.rowcount
        
        # Limpar artigos órfãos
        c.execute("""
            DELETE FROM artigo 
            WHERE rfq_id NOT IN (SELECT id FROM rfq)
        """)
        artigos_removidos = c.rowcount
        
        conn.commit()
        
        print(f"✅ Limpeza concluída:")
        print(f"   - PDFs removidos: {pdfs_removidos}")
        print(f"   - Respostas removidas: {respostas_removidas}")
        print(f"   - Artigos removidos: {artigos_removidos}")
        
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Erro na limpeza: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def obter_estatisticas_db():
    """Retorna estatísticas da base de dados"""
    
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        stats = {}
        
        # Contar registros em cada tabela
        tabelas = ['rfq', 'fornecedor', 'artigo', 'resposta_fornecedor', 'pdf_storage']
        
        for tabela in tabelas:
            c.execute(f"SELECT COUNT(*) FROM {tabela}")
            stats[tabela] = c.fetchone()[0]
        
        # Estatísticas específicas
        c.execute("SELECT COUNT(*) FROM rfq WHERE estado = 'pendente'")
        stats['rfq_pendentes'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM rfq WHERE estado = 'respondido'")
        stats['rfq_respondidas'] = c.fetchone()[0]
        
        # Tamanho da base de dados
        c.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
        stats['tamanho_db_bytes'] = c.fetchone()[0]
        
        return stats
        
    except sqlite3.Error as e:
        print(f"Erro ao obter estatísticas: {e}")
        return {}
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Executar criação da base de dados se o script for executado diretamente
    print("Criando/Atualizando base de dados...")
    criar_base_dados()
    
    print("\nVerificando integridade...")
    verificar_integridade_db()
    
    print("\nEstatísticas da base de dados:")
    stats = obter_estatisticas_db()
    for chave, valor in stats.items():
        print(f"  {chave}: {valor}")
    
    print("\nLimpando dados órfãos...")
    limpar_dados_orfaos()