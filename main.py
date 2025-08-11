import streamlit as st
import sqlite3
from datetime import datetime
from fpdf import FPDF
import base64
from io import BytesIO
import os
import shutil
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# ========================== CONFIGURAÇÃO GLOBAL ==========================
DB_PATH = "cotacoes.db"

# Configurações de Email (devem ser configuradas com valores reais)
EMAIL_CONFIG = {
    'smtp_server': 'smtp-mail.outlook.com',
    'smtp_port': 587,
    'email_user': 'GRINYTUI@hotmail.com',
    'email_password': 'ricardo19985'
}

st.set_page_config(
    page_title="ERP KTB Portugal",
    page_icon="📊",
    layout="wide"
)

# ========================== GESTÃO DA BASE DE DADOS ==========================

def criar_base_dados_completa():
    """Cria e configura a base de dados SQLite com todas as tabelas necessárias"""
    
    # Garantir que o diretório existe
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
            morada TEXT,
            nif TEXT,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Tabela de marcas por fornecedor
        c.execute("""
        CREATE TABLE IF NOT EXISTS fornecedor_marca (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER NOT NULL,
            marca TEXT NOT NULL,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            UNIQUE(fornecedor_id, marca)
        )
        """)

        # Tabela RFQ (Request for Quotation)
        c.execute("""
        CREATE TABLE IF NOT EXISTS rfq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE
        )
        """)

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
            marca TEXT,
            ordem INTEGER DEFAULT 1,
            FOREIGN KEY (rfq_id) REFERENCES rfq(id) ON DELETE CASCADE
        )
        """)

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
        """)

        # Tabela para armazenamento de PDFs
        c.execute("""
        CREATE TABLE IF NOT EXISTS pdf_storage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rfq_id TEXT NOT NULL,
            tipo_pdf TEXT NOT NULL,
            pdf_data BLOB NOT NULL,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            tamanho_bytes INTEGER,
            nome_arquivo TEXT,
            UNIQUE(rfq_id, tipo_pdf)
        )
        """)

        # Tabela de configuração de margens por marca
        c.execute("""
        CREATE TABLE IF NOT EXISTS configuracao_margens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fornecedor_id INTEGER,
            marca TEXT,
            margem_percentual REAL DEFAULT 10.0,
            ativo BOOLEAN DEFAULT TRUE,
            data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE
        )
        """)

        # Tabela de configurações de email
        c.execute("""
        CREATE TABLE IF NOT EXISTS configuracao_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            smtp_server TEXT,
            smtp_port INTEGER,
            email_user TEXT,
            email_password TEXT,
            ativo BOOLEAN DEFAULT TRUE
        )
        """)

        # Tabela de utilizadores do sistema
        c.execute("""
        CREATE TABLE IF NOT EXISTS utilizador (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nome TEXT,
            email TEXT,
            role TEXT NOT NULL
        )
        """)

        # Inserir utilizador administrador padrão se a tabela estiver vazia
        c.execute("SELECT COUNT(*) FROM utilizador")
        if c.fetchone()[0] == 0:
            c.execute(
                """
                INSERT INTO utilizador (username, password, nome, email, role)
                VALUES ('admin', 'admin', 'Administrador', 'admin@example.com', 'admin')
                """
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
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizador_username ON utilizador(username)"
        ]
        
        for indice in indices:
            c.execute(indice)

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
        print("Base de dados criada/atualizada com sucesso!")
        return True
        
    except sqlite3.Error as e:
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
                VALUES (?, ?, ?, ?, ?)
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
                            VALUES (?, ?)
                        """, (forn_id, marca))
                        
                        # Inserir margem padrão para cada marca
                        cursor.execute("""
                            INSERT INTO configuracao_margens (fornecedor_id, marca, margem_percentual)
                            VALUES (?, ?, ?)
                        """, (forn_id, marca, 15.0))  # 15% de margem padrão para marcas
            
            print("Fornecedores e marcas de exemplo inseridos.")
    
    except sqlite3.Error as e:
        print(f"Erro ao inserir dados de exemplo: {e}")

def obter_conexao():
    """Retorna uma conexão à base de dados"""
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# ========================== FUNÇÕES DE GESTÃO DE FORNECEDORES ==========================

def listar_fornecedores():
    """Obter todos os fornecedores"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT id, nome, email, telefone, morada, nif FROM fornecedor ORDER BY nome"
    )
    fornecedores = c.fetchall()
    conn.close()
    return fornecedores

def inserir_fornecedor(nome, email="", telefone="", morada="", nif=""):
    """Inserir novo fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    
    try:
        # Verificar se o fornecedor já existe
        c.execute("SELECT id FROM fornecedor WHERE nome = ?", (nome,))
        resultado = c.fetchone()
        
        if resultado:
            return resultado[0]
        else:
            c.execute("""
                INSERT INTO fornecedor (nome, email, telefone, morada, nif) 
                VALUES (?, ?, ?, ?, ?)
            """, (nome, email, telefone, morada, nif))
            conn.commit()
            return c.lastrowid
    finally:
        conn.close()


def atualizar_fornecedor(fornecedor_id, nome, email="", telefone="", morada="", nif=""):
    """Atualizar dados de um fornecedor existente"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE fornecedor
            SET nome = ?, email = ?, telefone = ?, morada = ?, nif = ?
            WHERE id = ?
            """,
            (nome, email, telefone, morada, nif, fornecedor_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def eliminar_fornecedor_db(fornecedor_id):
    """Eliminar fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM fornecedor WHERE id = ?", (fornecedor_id,))
    conn.commit()
    removidos = c.rowcount
    conn.close()
    return removidos > 0

def obter_marcas_fornecedor(fornecedor_id):
    """Obter marcas associadas a um fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("""
        SELECT marca FROM fornecedor_marca 
        WHERE fornecedor_id = ? 
        ORDER BY marca
    """, (fornecedor_id,))
    marcas = [row[0] for row in c.fetchall()]
    conn.close()
    return marcas

def adicionar_marca_fornecedor(fornecedor_id, marca):
    """Adicionar marca a um fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO fornecedor_marca (fornecedor_id, marca)
            VALUES (?, ?)
        """, (fornecedor_id, marca))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remover_marca_fornecedor(fornecedor_id, marca):
    """Remover marca de um fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("""
        DELETE FROM fornecedor_marca
        WHERE fornecedor_id = ? AND marca = ?
    """, (fornecedor_id, marca))
    conn.commit()
    rows_affected = c.rowcount
    conn.close()
    return rows_affected > 0


# ========================== FUNÇÕES DE GESTÃO DE UTILIZADORES ==========================

def listar_utilizadores():
    """Obter todos os utilizadores"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, nome, email, role FROM utilizador ORDER BY username"
    )
    utilizadores = c.fetchall()
    conn.close()
    return utilizadores


def obter_utilizador_por_username(username):
    """Obter utilizador pelo username"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, password, nome, email, role FROM utilizador WHERE username = ?",
        (username,),
    )
    user = c.fetchone()
    conn.close()
    return user


def inserir_utilizador(username, password, nome="", email="", role="user"):
    """Inserir novo utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO utilizador (username, password, nome, email, role)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, password, nome, email, role),
        )
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def atualizar_utilizador(user_id, username, nome, email, role, password=None):
    """Atualizar dados de um utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        if password:
            c.execute(
                """
                UPDATE utilizador
                SET username = ?, password = ?, nome = ?, email = ?, role = ?
                WHERE id = ?
                """,
                (username, password, nome, email, role, user_id),
            )
        else:
            c.execute(
                """
                UPDATE utilizador
                SET username = ?, nome = ?, email = ?, role = ?
                WHERE id = ?
                """,
                (username, nome, email, role, user_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_utilizador(user_id):
    """Eliminar utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM utilizador WHERE id = ?", (user_id,))
    conn.commit()
    removed = c.rowcount
    conn.close()
    return removed > 0

# ========================== FUNÇÕES DE GESTÃO DE RFQs ==========================

def criar_rfq(fornecedor_id, data, artigos, referencia, nome_solicitante="", 
              email_solicitante="", observacoes=""):
    """Criar nova RFQ"""
    conn = obter_conexao()
    c = conn.cursor()
    
    try:
        c.execute("""
            INSERT INTO rfq (fornecedor_id, data, referencia, 
                           nome_solicitante, email_solicitante, observacoes, estado)
            VALUES (?, ?, ?, ?, ?, ?, 'pendente')
        """, (fornecedor_id, data.isoformat(), referencia, 
              nome_solicitante, email_solicitante, observacoes))
        
        rfq_id = c.lastrowid

        # Inserir artigos
        for ordem, art in enumerate(artigos, 1):
            if art.get("descricao", "").strip():
                c.execute("""
                    INSERT INTO artigo (rfq_id, artigo_num, descricao, quantidade, 
                                      unidade, especificacoes, marca, ordem)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (rfq_id, art.get("artigo_num", ""), art["descricao"], 
                      art.get("quantidade", 1), art.get("unidade", "Peças"),
                      art.get("especificacoes", ""), art.get("marca", ""), ordem))
        
        conn.commit()
        
        # Gerar PDF
        c.execute("SELECT nome FROM fornecedor WHERE id = ?", (fornecedor_id,))
        nome_fornecedor = c.fetchone()[0]
        gerar_e_armazenar_pdf(rfq_id, nome_fornecedor, data, artigos, referencia)
        # Enviar pedido por email ao fornecedor
        enviar_email_pedido_fornecedor(rfq_id)
        
        return rfq_id
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao criar RFQ: {str(e)}")
        return None
    finally:
        conn.close()

def obter_todas_cotacoes(filtro_referencia="", estado=None):
    """Obter todas as cotações com filtros opcionais"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        query = """
            SELECT rfq.id, rfq.data, fornecedor.nome, rfq.estado, rfq.referencia,
                   COUNT(artigo.id) as num_artigos, rfq.nome_solicitante, rfq.email_solicitante
            FROM rfq
            JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
            LEFT JOIN artigo ON rfq.id = artigo.rfq_id
        """
        
        conditions = []
        params = []
        
        if filtro_referencia:
            conditions.append("rfq.referencia LIKE ?")
            params.append(f"%{filtro_referencia}%")
        
        if estado:
            conditions.append("rfq.estado = ?")
            params.append(estado)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " GROUP BY rfq.id ORDER BY rfq.data DESC"
        
        c.execute(query, params)
        resultados = c.fetchall()
        conn.close()
        
        return [{
            "id": row[0],
            "data": row[1],
            "fornecedor": row[2],
            "estado": row[3],
            "referencia": row[4],
            "num_artigos": row[5],
            "nome_solicitante": row[6] if row[6] else "",
            "email_solicitante": row[7] if row[7] else ""
        } for row in resultados]
        
    except Exception as e:
        print(f"Erro ao obter cotações: {e}")
        return []

def obter_detalhes_cotacao(rfq_id):
    """Obter detalhes completos de uma cotação"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        c.execute("""
            SELECT rfq.*, fornecedor.nome
            FROM rfq
            JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
            WHERE rfq.id = ?
        """, (rfq_id,))
        info = c.fetchone()
        
        if not info:
            conn.close()
            return None
        
        c.execute("""
            SELECT * FROM artigo
            WHERE rfq_id = ?
            ORDER BY ordem, id
        """, (rfq_id,))
        artigos = [{
            "id": row[0],
            "artigo_num": row[2] if row[2] else "",
            "descricao": row[3],
            "quantidade": row[4],
            "unidade": row[5],
            "especificacoes": row[6] if row[6] else "",
            "marca": row[7] if row[7] else ""
        } for row in c.fetchall()]
        
        conn.close()
        
        return {
            "id": info[0],
            "fornecedor_id": info[1],
            "data": info[2],
            "estado": info[3],
            "referencia": info[4],
            "observacoes": info[5] if info[5] else "",
            "nome_solicitante": info[6] if info[6] else "",
            "email_solicitante": info[7] if info[7] else "",
            "fornecedor": info[12],
            "artigos": artigos
        }
        
    except Exception as e:
        print(f"Erro ao obter detalhes: {e}")
        return None

def eliminar_cotacao(rfq_id):
    """Eliminar cotação e todos os dados relacionados"""
    conn = obter_conexao()
    c = conn.cursor()
    
    try:
        c.execute("DELETE FROM resposta_fornecedor WHERE rfq_id = ?", (rfq_id,))
        c.execute("DELETE FROM artigo WHERE rfq_id = ?", (rfq_id,))
        c.execute("DELETE FROM pdf_storage WHERE rfq_id = ?", (str(rfq_id),))
        c.execute("DELETE FROM rfq WHERE id = ?", (rfq_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao eliminar cotação: {str(e)}")
        return False
    finally:
        conn.close()

# ========================== FUNÇÕES DE GESTÃO DE RESPOSTAS ==========================

def guardar_respostas(rfq_id, respostas):
    """Guardar respostas do fornecedor e enviar email"""
    conn = obter_conexao()
    c = conn.cursor()
    
    try:
        # Obter fornecedor_id diretamente da RFQ [CORREÇÃO]
        c.execute("SELECT fornecedor_id FROM rfq WHERE id = ?", (rfq_id,))
        resultado = c.fetchone()
        
        if not resultado:
            st.error("RFQ não encontrada!")
            return False
            
        fornecedor_id = resultado[0]  # Obtém o ID do fornecedor da RFQ

        # Obter margem para cada artigo baseada na marca
        for item in respostas:
            artigo_id, custo, prazo, peso, hs_code, pais_origem, descricao_editada, quantidade_final = item
            
            # Obter marca do artigo
            c.execute("SELECT marca FROM artigo WHERE id = ?", (artigo_id,))
            marca_result = c.fetchone()
            marca = marca_result[0] if marca_result else None
            
            # Obter margem configurada para a marca
            margem = obter_margem_para_marca(fornecedor_id, marca)
            preco_venda = custo * (1 + margem/100)
            
            c.execute("""
                INSERT OR REPLACE INTO resposta_fornecedor 
                (fornecedor_id, rfq_id, artigo_id, descricao, custo, prazo_entrega, 
                 peso, hs_code, pais_origem, margem_utilizada, preco_venda, quantidade_final)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fornecedor_id, rfq_id, artigo_id, descricao_editada, custo, prazo, 
                  peso, hs_code, pais_origem, margem, preco_venda, quantidade_final))
        
        # Atualizar estado da RFQ
        c.execute("UPDATE rfq SET estado = 'respondido' WHERE id = ?", (rfq_id,))
        
        # Obter informações para email
        c.execute("""
            SELECT nome_solicitante, email_solicitante, referencia 
            FROM rfq WHERE id = ?
        """, (rfq_id,))
        rfq_info = c.fetchone()
        
        conn.commit()
        
        # Gerar PDF de cliente
        pdf_sucesso = gerar_pdf_cliente(rfq_id)
        
        # Enviar email se houver endereço
        if rfq_info and rfq_info[1] and pdf_sucesso:
            enviar_email_orcamento(
                rfq_info[1],  # email
                rfq_info[0] if rfq_info[0] else "Cliente",  # nome
                rfq_info[2],  # referência
                rfq_id
            )
        
        return True
        
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao guardar respostas: {str(e)}")
        return False
    finally:
        conn.close()

def obter_respostas_cotacao(rfq_id):
    """Obter respostas de uma cotação"""
    conn = obter_conexao()
    c = conn.cursor()
    
    c.execute("""
        SELECT rf.*, a.descricao as descricao_original, a.quantidade as quantidade_original
        FROM resposta_fornecedor rf
        JOIN artigo a ON rf.artigo_id = a.id
        WHERE rf.rfq_id = ?
        ORDER BY a.ordem, rf.artigo_id
    """, (rfq_id,))
    
    respostas = []
    for row in c.fetchall():
        respostas.append({
            "id": row[0],
            "fornecedor_id": row[1],
            "rfq_id": row[2],
            "artigo_id": row[3],
            "descricao": row[4] if row[4] else row[16],
            "custo": row[5],
            "prazo_entrega": row[6],
            "quantidade_final": row[7] if row[7] else row[17],
            "peso": row[8],
            "hs_code": row[9],
            "pais_origem": row[10],
            "moeda": row[11],
            "margem_utilizada": row[12],
            "preco_venda": row[13],
            "observacoes": row[14]
        })
    
    conn.close()
    return respostas

# ========================== FUNÇÕES DE GESTÃO DE MARGENS ==========================

def obter_margem_para_marca(fornecedor_id, marca):
    """Obter margem configurada para fornecedor/marca específica"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        # Procurar margem específica para fornecedor e marca
        if marca:
            c.execute("""
                SELECT margem_percentual FROM configuracao_margens
                WHERE fornecedor_id = ? AND marca = ? AND ativo = TRUE
                ORDER BY id DESC LIMIT 1
            """, (fornecedor_id, marca))
            result = c.fetchone()
            if result:
                conn.close()
                return result[0]
        
        # Se não encontrar, usar margem padrão
        c.execute("""
            SELECT margem_percentual FROM configuracao_margens
            WHERE fornecedor_id IS NULL AND marca IS NULL
            ORDER BY id DESC LIMIT 1
        """)
        result = c.fetchone()
        conn.close()
        
        return result[0] if result else 10.0
        
    except Exception as e:
        print(f"Erro ao obter margem: {e}")
        return 10.0

def configurar_margem_marca(fornecedor_id, marca, margem_percentual):
    """Configurar margem para fornecedor/marca"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        # Desativar margens anteriores
        c.execute("""
            UPDATE configuracao_margens SET ativo = FALSE
            WHERE fornecedor_id = ? AND marca = ?
        """, (fornecedor_id, marca))
        
        # Inserir nova margem
        c.execute("""
            INSERT INTO configuracao_margens (fornecedor_id, marca, margem_percentual, ativo)
            VALUES (?, ?, ?, TRUE)
        """, (fornecedor_id, marca, margem_percentual))
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Erro ao configurar margem: {e}")
        return False

# ========================== FUNÇÕES DE EMAIL ==========================

def testar_conexao_smtp():
    """Teste independente de conexão SMTP"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT * FROM configuracao_email WHERE ativo = TRUE LIMIT 1")
        config = c.fetchone()
        conn.close()

        if not config:
            st.warning("Nenhuma configuração ativa encontrada")
            return False

        smtp_server, smtp_port, email_user, email_password = config[1:5]
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_user, email_password)
            st.success("✅ Conexão SMTP bem-sucedida!")
            return True
            
    except Exception as e:
        st.error(f"❌ Falha na conexão SMTP: {str(e)}")
        return False

# Adicione no menu de Configurações > Email
if st.button("🔌 Testar Conexão SMTP"):
    testar_conexao_smtp()

def enviar_email_orcamento(email_destino, nome_solicitante, referencia, rfq_id):
    """Enviar email com o orçamento ao cliente"""
    try:
        print(f"⏳ Preparando para enviar email para {email_destino}...")

        # Obter PDF do cliente
        pdf_bytes = obter_pdf_da_db(rfq_id, "cliente")
        if not pdf_bytes:
            print("❌ PDF do cliente não encontrado")
            st.error("PDF não encontrado para anexar ao e-mail")
            return False
        
        # Obter configurações de email
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            SELECT smtp_server, smtp_port, email_user, email_password 
            FROM configuracao_email 
            WHERE ativo = TRUE 
            LIMIT 1
        """)
        config = c.fetchone()
        conn.close()
        
        if not config:
            print("⚠️ Usando configurações padrão de email")
            config = (
                EMAIL_CONFIG['smtp_server'],
                EMAIL_CONFIG['smtp_port'],
                EMAIL_CONFIG['email_user'],
                EMAIL_CONFIG['email_password']
            )

        smtp_server, smtp_port, email_user, email_password = config
        print(f"🔧 Configurações SMTP: {smtp_server}:{smtp_port}")
        
        # Criar mensagem
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = email_destino
        msg['Subject'] = f"Orçamento - Ref: {referencia}"
        
        # Corpo do email
        corpo = f"""
        Estimado(a) {nome_solicitante},

        Segue em anexo o orçamento solicitado com a referência {referencia}.

        Ficamos à disposição para qualquer esclarecimento adicional.

        Com os melhores cumprimentos,
        KTB Portugal
        """
        
        msg.attach(MIMEText(corpo, 'plain'))
        
        # Anexar PDF
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="orcamento_{referencia}.pdf"'
        )
        msg.attach(part)
        
        # Enviar email
        print(f"🚀 Tentando enviar email para {email_destino}...")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_user, email_password)
            server.send_message(msg)
            print("✅ Email enviado com sucesso!")
            return True

    except Exception as e:
        print(f"❌ Erro ao enviar email: {str(e)}")
        st.error(f"Falha no envio: {str(e)}")
        return False


def enviar_email_pedido_fornecedor(rfq_id):
    """Envia por email o PDF de pedido ao fornecedor associado à RFQ."""
    try:
        # Buscar fornecedor (nome+email) e referência
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            SELECT f.nome, f.email, r.referencia
            FROM rfq r
            JOIN fornecedor f ON r.fornecedor_id = f.id
            WHERE r.id = ?
        """, (rfq_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            st.warning("Fornecedor não encontrado para a RFQ.")
            return False
        fornecedor_nome, fornecedor_email, referencia = row[0], row[1], row[2]
        if not fornecedor_email:
            st.info("Fornecedor sem email definido — não foi enviado o pedido.")
            return False

        # Obter PDF do pedido
        pdf_bytes = obter_pdf_da_db(rfq_id, "pedido")
        if not pdf_bytes:
            st.error("PDF do pedido não encontrado para envio ao fornecedor.")
            return False

        # Configuração SMTP
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT smtp_server, smtp_port, email_user, email_password FROM configuracao_email WHERE ativo = TRUE LIMIT 1")
        config = c.fetchone()
        conn.close()

        if config:
            smtp_server, smtp_port, email_user, email_password = config
        else:
            smtp_server = EMAIL_CONFIG['smtp_server']
            smtp_port = EMAIL_CONFIG['smtp_port']
            email_user = EMAIL_CONFIG['email_user']
            email_password = EMAIL_CONFIG['email_password']

        # Construir email
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = fornecedor_email
        msg['Subject'] = f"Pedido de Cotação - Ref: {referencia}"

        corpo = f"""
Estimado(a) {fornecedor_nome},

Segue em anexo o pedido de cotação relativo à referência {referencia}.
Agradecemos o envio do preço, prazo de entrega, HS Code, país de origem e peso.

Com os melhores cumprimentos,
KTB Portugal
"""
        msg.attach(MIMEText(corpo, 'plain'))

        part = MIMEBase('application', 'octet-stream')
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="pedido_{referencia}.pdf"')
        msg.attach(part)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_user, email_password)
            server.send_message(msg)

        return True
    except Exception as e:
        st.error(f"Falha ao enviar email ao fornecedor: {e}")
        return False

def guardar_pdf_upload(rfq_id, tipo_pdf, nome_arquivo, bytes_):
    """Guarda um PDF carregado pelo utilizador na tabela pdf_storage."""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO pdf_storage (rfq_id, tipo_pdf, pdf_data, tamanho_bytes, nome_arquivo)
            VALUES (?, ?, ?, ?, ?)
        """, (str(rfq_id), tipo_pdf, bytes_, len(bytes_), nome_arquivo))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro a guardar PDF: {e}")
        return False

# ========================== CLASSES PDF ==========================

class QuotationPDF(FPDF):
    """PDF para pedido de cotação ao fornecedor (sem marca)"""
    def header(self):
        try:
            if os.path.exists("logo.jpeg"):
                self.image("logo.jpeg", 160, 10, 40)
        except:
            pass
        self.set_font("Arial", "B", 16)
        self.cell(0, 10, "PEDIDO DE COTAÇÃO", ln=True, align='C')
        self.ln(5)

    def add_info(self, fornecedor, data, referencia=""):
        self.set_font("Arial", "", 12)
        self.cell(0, 10, f"Data: {data}", ln=True)
        self.cell(0, 10, f"Fornecedor: {fornecedor}", ln=True)
        if referencia:
            self.cell(0, 10, f"Referência: {referencia}", ln=True)
        self.ln(8)

    def add_table_header(self):
        self.set_font("Arial", "B", 10)
        headers = ["#", "Art. Nº", "Descrição", "Qtd", "Unidade", "Preço Unit."]
        widths = [10, 25, 85, 20, 25, 25]
        for i in range(len(headers)):
            self.cell(widths[i], 8, headers[i], border=1, align='C')
        self.ln()

    def add_table_row(self, idx, artigo):
        self.set_font("Arial", "", 9)
        widths = [10, 25, 85, 20, 25, 25]
        
        self.cell(widths[0], 8, str(idx), border=1, align='C')
        self.cell(widths[1], 8, artigo.get('artigo_num', '')[:15], border=1)
        
        # Descrição com quebra de linha se necessário
        desc = artigo['descricao']
        if len(desc) > 45:
            lines = self.split_text(desc, 45)
            self.cell(widths[2], 8, lines[0], border=1)
            self.cell(widths[3], 8, str(artigo['quantidade']), border=1, align='C')
            self.cell(widths[4], 8, artigo['unidade'], border=1)
            self.cell(widths[5], 8, "_______", border=1, align='C')  # Campo vazio para preço
            self.ln()
            
            for line in lines[1:]:
                self.cell(widths[0], 8, "", border=1)
                self.cell(widths[1], 8, "", border=1)
                self.cell(widths[2], 8, line, border=1)
                self.cell(widths[3], 8, "", border=1)
                self.cell(widths[4], 8, "", border=1)
                self.cell(widths[5], 8, "", border=1)
                self.ln()
        else:
            self.cell(widths[2], 8, desc, border=1)
            self.cell(widths[3], 8, str(artigo['quantidade']), border=1, align='C')
            self.cell(widths[4], 8, artigo['unidade'], border=1)
            self.cell(widths[5], 8, "_______", border=1, align='C')  # Campo vazio para preço
            self.ln()

    def split_text(self, text, max_length):
        """Divide texto em linhas"""
        lines = []
        words = text.split()
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if len(test_line) <= max_length:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines if lines else [text[:max_length]]

    def gerar(self, fornecedor, data, artigos, referencia=""):
        self.add_page()
        self.add_info(fornecedor, data, referencia)
        self.add_table_header()
        for idx, art in enumerate(artigos, 1):
            self.add_table_row(idx, art)
        
        # Adicionar nota no final
        self.ln(10)
        self.set_font("Arial", "I", 10)
        self.cell(0, 5, "Por favor, preencha os preços unitários e devolva este documento.", ln=True)
        
        return self.output(dest='S').encode('latin-1')


class ClientQuotationPDF(FPDF):
    """PDF para orçamento ao cliente com todos os detalhes"""
    def header(self):
        try:
            if os.path.exists("logo.jpeg"):
                self.image("logo.jpeg", 160, 10, 40)
        except Exception:
            pass
        self.set_font("Arial", "B", 16)
        self.cell(0, 10, "ORÇAMENTO", ln=True, align='C')
        self.ln(5)

    def add_info(self, rfq_info, solicitante_info):
        self.set_font("Arial", "", 12)
        self.cell(0, 8, f"Data: {rfq_info['data']}", ln=True)
        self.cell(0, 8, f"Referência: {rfq_info['referencia']}", ln=True)
        if solicitante_info.get('nome'):
            self.cell(0, 8, f"Para: {solicitante_info['nome']}", ln=True)
        if solicitante_info.get('email'):
            self.cell(0, 8, f"Email: {solicitante_info['email']}", ln=True)
        self.ln(5)

    def add_table_header(self):
        self.set_font("Arial", "B", 9)
        headers = ["#", "Art. Nº", "Descrição", "Qtd", "P.Unit.", "Total", "HS Code", "Origem", "Prazo", "Peso"]
        widths = [8, 18, 55, 12, 18, 20, 18, 15, 12, 14]
        for i in range(len(headers)):
            self.cell(widths[i], 7, headers[i], border=1, align='C')
        self.ln()

    def split_text(self, text, max_length):
        lines = []
        words = text.split()
        current_line = ""
        for word in words:
            test_line = (current_line + " " + word).strip() if current_line else word
            if len(test_line) <= max_length:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines if lines else [text[:max_length]]

    def add_table_row(self, idx, item):
        self.set_font("Arial", "", 8)
        widths = [8, 18, 55, 12, 18, 20, 18, 15, 12, 14]
        
        preco_venda = float(item['preco_venda'])
        quantidade = int(item['quantidade_final'])
        total = preco_venda * quantidade
        
        # Primeira linha sempre
        self.cell(widths[0], 6, str(idx), border=1, align='C')
        self.cell(widths[1], 6, (item.get('artigo_num') or '')[:10], border=1)
        
        desc = item['descricao']
        if len(desc) > 30:
            lines = self.split_text(desc, 30)
            self.cell(widths[2], 6, lines[0], border=1)
            self.cell(widths[3], 6, str(quantidade), border=1, align='C')
            self.cell(widths[4], 6, f"EUR {preco_venda:.2f}", border=1, align='R')
            self.cell(widths[5], 6, f"EUR {total:.2f}", border=1, align='R')
            self.cell(widths[6], 6, (item.get('hs_code') or '')[:10], border=1, align='C')
            self.cell(widths[7], 6, (item.get('pais_origem') or '')[:8], border=1, align='C')
            self.cell(widths[8], 6, f"{item.get('prazo_entrega', 30)}d", border=1, align='C')
            self.cell(widths[9], 6, f"{(item.get('peso') or 0):.1f}kg", border=1, align='C')
            self.ln()
            
            # Linhas adicionais para descrição longa
            for line in lines[1:]:
                self.cell(widths[0], 6, "", border=1)
                self.cell(widths[1], 6, "", border=1)
                self.cell(widths[2], 6, line, border=1)
                for j in range(3, 10):
                    self.cell(widths[j], 6, "", border=1)
                self.ln()
        else:
            self.cell(widths[2], 6, desc, border=1)
            self.cell(widths[3], 6, str(quantidade), border=1, align='C')
            self.cell(widths[4], 6, f"EUR {preco_venda:.2f}", border=1, align='R')
            self.cell(widths[5], 6, f"EUR {total:.2f}", border=1, align='R')
            self.cell(widths[6], 6, (item.get('hs_code') or '')[:10], border=1, align='C')
            self.cell(widths[7], 6, (item.get('pais_origem') or '')[:8], border=1, align='C')
            self.cell(widths[8], 6, f"{item.get('prazo_entrega', 30)}d", border=1, align='C')
            self.cell(widths[9], 6, f"{(item.get('peso') or 0):.1f}kg", border=1, align='C')
            self.ln()
        
        return total

    def add_total(self, total_geral, peso_total):
        self.ln(5)
        self.set_font("Arial", "B", 11)
        self.cell(131, 8, "TOTAL:", border=1, align='R')
        self.cell(20, 8, f"EUR {total_geral:.2f}", border=1, align='C')
        self.cell(39, 8, f"Peso Total: {peso_total:.1f}kg", border=1, align='C')
        self.ln(10)
        
        self.set_font("Arial", "", 10)
        self.cell(0, 5, "Validade da proposta: 30 dias", ln=True)
        self.cell(0, 5, "Preços não incluem IVA", ln=True)
        self.cell(0, 5, "Condições de pagamento: A combinar", ln=True)

    def gerar(self, rfq_info, solicitante_info, itens_resposta):
        self.add_page()
        self.add_info(rfq_info, solicitante_info)
        self.add_table_header()
        
        total_geral = 0.0
        peso_total = 0.0
        for idx, item in enumerate(itens_resposta, 1):
            total_item = self.add_table_row(idx, item)
            total_geral += total_item
            peso_total += float(item.get('peso') or 0) * int(item['quantidade_final'])
        
        self.add_total(total_geral, peso_total)
        return self.output(dest='S').encode('latin-1')
# ========================== FUNÇÕES DE GESTÃO DE PDFs ==========================

def gerar_e_armazenar_pdf(rfq_id, fornecedor, data, artigos, referencia=""):
    """Gerar e armazenar PDF de pedido de cotação"""
    try:
        pdf_generator = QuotationPDF()
        pdf_bytes = pdf_generator.gerar(fornecedor, data.strftime("%Y-%m-%d"), artigos, referencia)
        
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO pdf_storage (rfq_id, tipo_pdf, pdf_data, tamanho_bytes)
            VALUES (?, ?, ?, ?)
        """, (str(rfq_id), "pedido", pdf_bytes, len(pdf_bytes)))
        conn.commit()
        conn.close()
        
        return pdf_bytes
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {str(e)}")
        return None

def gerar_pdf_cliente(rfq_id):
    """Gerar PDF para cliente com tratamento de erros"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        # 1. Obter dados da RFQ
        c.execute("""SELECT rfq.*, fornecedor.nome 
                   FROM rfq JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id 
                   WHERE rfq.id = ?""", (rfq_id,))
        rfq_data = c.fetchone()
        
        if not rfq_data:
            st.error("RFQ não encontrada")
            return False

        # 2. Obter respostas
        c.execute("""SELECT a.artigo_num, rf.descricao, rf.quantidade_final, 
                    a.unidade, rf.preco_venda, rf.prazo_entrega,
                    rf.peso, rf.hs_code, rf.pais_origem
                 FROM resposta_fornecedor rf
                 JOIN artigo a ON rf.artigo_id = a.id
                 WHERE rf.rfq_id = ?""", (rfq_id,))
        
        itens_resposta = [{
            'artigo_num': row[0] or '',
            'descricao': row[1],
            'quantidade_final': row[2],
            'unidade': row[3],
            'preco_venda': row[4],
            'prazo_entrega': row[5],
            'peso': row[6] or 0,
            'hs_code': row[7] or '',
            'pais_origem': row[8] or ''
        } for row in c.fetchall()]

        if not itens_resposta:
            st.error("Nenhuma resposta encontrada para esta RFQ")
            return False

        # 3. Gerar PDF
        pdf_cliente = ClientQuotationPDF()
        pdf_bytes = pdf_cliente.gerar(
            rfq_info={
                'data': rfq_data[2],
                'referencia': rfq_data[4],
                'fornecedor': rfq_data[12]
            },
            solicitante_info={
                'nome': rfq_data[6] or '',
                'email': rfq_data[7] or ''
            },
            itens_resposta=itens_resposta
        )

        # 4. Armazenar PDF
        c.execute("""INSERT OR REPLACE INTO pdf_storage 
                  (rfq_id, tipo_pdf, pdf_data, tamanho_bytes)
                  VALUES (?, ?, ?, ?)""",
                  (str(rfq_id), "cliente", pdf_bytes, len(pdf_bytes)))
        
        conn.commit()
        return True

    except Exception as e:
        st.error(f"Erro ao gerar PDF: {str(e)}")
        return False
    finally:
        conn.close()

def obter_pdf_da_db(rfq_id, tipo_pdf="pedido"):
    """Obter PDF da base de dados"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("""
        SELECT pdf_data FROM pdf_storage 
        WHERE rfq_id = ? AND tipo_pdf = ?
    """, (str(rfq_id), tipo_pdf))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def exibir_pdf(label, data_pdf):
    """Mostra PDF diretamente na página"""
    b64 = base64.b64encode(data_pdf).decode()
    pdf_html = f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="500"></iframe>'
    with st.expander(label):
        st.markdown(pdf_html, unsafe_allow_html=True)

def verificar_pdfs(rfq_id):
    """Verifica se os PDFs existem na base de dados"""
    conn = obter_conexao()
    c = conn.cursor()
    
    # Verificar PDF do pedido
    c.execute("SELECT COUNT(*) FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf = 'pedido'", (str(rfq_id),))
    pedido_existe = c.fetchone()[0] > 0
    
    # Verificar PDF do cliente
    c.execute("SELECT COUNT(*) FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf = 'cliente'", (str(rfq_id),))
    cliente_existe = c.fetchone()[0] > 0
    
    conn.close()
    
    return {
        'pedido': pedido_existe,
        'cliente': cliente_existe
    }

# ========================== FUNÇÕES DE UTILIDADE ==========================

def obter_estatisticas_db():
    """Obter estatísticas da base de dados"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        stats = {}
        
        # Contar registros principais
        c.execute("SELECT COUNT(*) FROM rfq")
        stats['rfq'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM fornecedor")
        stats['fornecedor'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM artigo")
        stats['artigo'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM rfq WHERE estado = 'pendente'")
        stats['rfq_pendentes'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM rfq WHERE estado = 'respondido'")
        stats['rfq_respondidas'] = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM pdf_storage WHERE tipo_pdf = 'cliente'")
        stats['pdfs_cliente'] = c.fetchone()[0]
        
        conn.close()
        return stats
        
    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")
        return {}

def backup_database(backup_path=None):
    """Criar backup da base de dados"""
    try:
        if not backup_path:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"backup_cotacoes_{timestamp}.db"
        
        shutil.copy2(DB_PATH, backup_path)
        return backup_path
    except Exception as e:
        print(f"Erro ao criar backup: {e}")
        return None

# ========================== INICIALIZAÇÃO DO SISTEMA ==========================

def inicializar_sistema():
    """Inicializar todo o sistema"""
    print("Inicializando sistema ERP KTB Portugal...")
    
    if criar_base_dados_completa():
        print("✓ Base de dados inicializada")
    else:
        print("✗ Erro ao inicializar base de dados")
    
    stats = obter_estatisticas_db()
    print(f"✓ Sistema inicializado com {stats.get('rfq', 0)} RFQs e {stats.get('fornecedor', 0)} fornecedores")
    
    return True

# ========================== INTERFACE STREAMLIT ==========================

# Inicializar session state
if 'sistema_inicializado' not in st.session_state:
    st.session_state.sistema_inicializado = inicializar_sistema()

if 'artigos' not in st.session_state:
    st.session_state.artigos = [{
        "artigo_num": "",
        "descricao": "",
        "quantidade": 1,
        "unidade": "Peças",
        "marca": ""
    }]

if 'show_response_form' not in st.session_state:
    st.session_state.show_response_form = None

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None


def login_screen():
    st.title("🔐 Login")
    username = st.text_input("Utilizador")
    password = st.text_input("Password", type="password")
    if st.button("Entrar"):
        user = obter_utilizador_por_username(username)
        if user and user[2] == password:
            st.session_state.logged_in = True
            st.session_state.role = user[5]
            st.session_state.username = user[1]
            st.session_state.nome = user[3]
            st.session_state.email = user[4]
            st.rerun()
        else:
            st.error("Credenciais inválidas")


if not st.session_state.logged_in:
    login_screen()
    st.stop()

# CSS personalizado
st.markdown("""
    <style>
    .stButton > button {
        width: 100%;
        margin: 2px 0;
    }
    
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        margin: 10px 0;
    }
    
    .success-message {
        background-color: #d4edda;
        border-color: #c3e6cb;
        color: #155724;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    
    .warning-message {
        background-color: #fff3cd;
        border-color: #ffeeba;
        color: #856404;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)

# Menu lateral
with st.sidebar:
    st.title("📋 Menu Principal")
    opcoes_menu = ["🏠 Dashboard", "📝 Nova Cotação", "📩 Responder Cotações", "📊 Relatórios"]
    if st.session_state.get("role") in ["admin", "gestor"]:
        opcoes_menu.append("⚙️ Configurações")
    menu_option = st.radio(
        "Navegação",
        opcoes_menu,
        label_visibility="collapsed"
    )

    if st.button("🚪 Sair"):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.pop("username", None)
        st.session_state.pop("nome", None)
        st.session_state.pop("email", None)
        st.rerun()

    st.markdown("---")
    
    # Estatísticas rápidas
    stats = obter_estatisticas_db()
    st.metric("Cotações Pendentes", stats.get('rfq_pendentes', 0))
    st.metric("Cotações Respondidas", stats.get('rfq_respondidas', 0))
    
    st.markdown("---")
    st.markdown("""
        <div style="text-align: center; font-size: 12px;">
            <p>Sistema ERP v4.0</p>
            <p>© 2025 KTB Portugal</p>
        </div>
    """, unsafe_allow_html=True)

# ========================== PÁGINAS DO SISTEMA ==========================

if menu_option == "🏠 Dashboard":
    st.title("Dashboard - Sistema ERP KTB Portugal")
    
    # Métricas principais
    col1, col2, col3, col4 = st.columns(4)
    
    stats = obter_estatisticas_db()
    
    with col1:
        st.metric("Total RFQs", stats.get('rfq', 0))
        st.metric("Pendentes", stats.get('rfq_pendentes', 0))
    
    with col2:
        st.metric("Respondidas", stats.get('rfq_respondidas', 0))
        st.metric("Taxa Resposta", f"{(stats.get('rfq_respondidas', 0) / max(stats.get('rfq', 1), 1) * 100):.1f}%")
    
    with col3:
        st.metric("Fornecedores", stats.get('fornecedor', 0))
        st.metric("Artigos", stats.get('artigo', 0))
    
    with col4:
        st.metric("PDFs Gerados", stats.get('pdfs_cliente', 0) * 2)
        st.metric("Orçamentos Enviados", stats.get('pdfs_cliente', 0))
    
    st.markdown("---")
    
    # Últimas cotações
    st.subheader("📋 Últimas Cotações")
    cotacoes_recentes = obter_todas_cotacoes()[:5]
    
    if cotacoes_recentes:
        for cotacao in cotacoes_recentes:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            with col1:
                st.write(f"**#{cotacao['id']}** - {cotacao['fornecedor']}")
            with col2:
                st.write(f"Ref: {cotacao['referencia']}")
            with col3:
                st.write(f"Data: {cotacao['data']}")
            with col4:
                estado_cor = "🟢" if cotacao['estado'] == "respondido" else "🟡"
                st.write(f"{estado_cor} {cotacao['estado'].title()}")
    else:
        st.info("Nenhuma cotação registada ainda.")

elif menu_option == "📝 Nova Cotação":
    st.title("📝 Criar Nova Cotação")
    
    # Obter fornecedor selecionado antes do form para usar nas marcas
    fornecedores = listar_fornecedores()
    
    with st.form(key="nova_cotacao_form"):
        # Fornecedor e Data
        col1, col2 = st.columns(2)
        
        with col1:
            fornecedor_opcoes = [""] + [f[1] for f in fornecedores]
            if st.session_state.get("role") in ["admin", "gestor"]:
                fornecedor_opcoes.append("➕ Novo Fornecedor")
            fornecedor_selecionado = st.selectbox("Fornecedor *", fornecedor_opcoes)

            if fornecedor_selecionado == "➕ Novo Fornecedor":
                nome_fornecedor = st.text_input("Nome do novo fornecedor *")
                email_fornecedor = st.text_input("Email do fornecedor")
                telefone_fornecedor = st.text_input("Telefone")
                fornecedor_id_selecionado = None
            else:
                nome_fornecedor = fornecedor_selecionado
                # Obter ID do fornecedor para buscar marcas
                if fornecedor_selecionado and fornecedor_selecionado != "":
                    fornecedor_id_selecionado = next((f[0] for f in fornecedores if f[1] == fornecedor_selecionado), None)
                else:
                    fornecedor_id_selecionado = None
        
        with col2:
            data = st.date_input("Data da cotação", datetime.today())
        
        # Referência, Nome e Email do solicitante na mesma linha
        col1, col2, col3 = st.columns(3)
        with col1:
            referencia = st.text_input("Referência *", placeholder="Ex: KTB-2025-001")
        with col2:
            nome_solicitante = st.text_input("Nome do solicitante")
        with col3:
            email_solicitante = st.text_input("Email do solicitante")
        
        observacoes = st.text_area("Observações", height=100)
        # Dropbox - anexar pedido do cliente
        upload_pedido_cliente = st.file_uploader("📎 Pedido do cliente (PDF)", type=['pdf'], key='upload_pedido_cliente')

        
        st.markdown("### 📦 Artigos")
        
        # Obter marcas disponíveis para o fornecedor
        marcas_disponiveis = []
        if fornecedor_id_selecionado:
            marcas_disponiveis = obter_marcas_fornecedor(fornecedor_id_selecionado)
        
        # Lista de artigos
        for i, artigo in enumerate(st.session_state.artigos, 1):
            with st.expander(f"Artigo {i}", expanded=(i == 1)):
                # Primeira linha: Nº Artigo, Descrição, Quantidade
                col1, col2, col3 = st.columns([1, 3, 1])
                
                with col1:
                    artigo['artigo_num'] = st.text_input(
                        "Nº Artigo", 
                        value=artigo['artigo_num'],
                        key=f"art_num_{i}"
                    )
                    
                    # Marca logo abaixo do Nº Artigo
                    if fornecedor_id_selecionado:
                        if marcas_disponiveis:
                            # Garantir que o valor atual está na lista
                            current_marca = artigo.get('marca', '')
                            if current_marca not in [""] + marcas_disponiveis:
                                current_marca = ""
                            
                            marca_index = 0
                            try:
                                marca_index = [""] + marcas_disponiveis.index(current_marca) if current_marca in [""] + marcas_disponiveis else 0
                            except:
                                marca_index = 0
                            
                            artigo['marca'] = st.selectbox(
                                "Marca",
                                [""] + marcas_disponiveis,
                                index=marca_index,
                                key=f"marca_{i}"
                            )
                        else:
                            st.info("Sem marcas")
                            artigo['marca'] = ""
                    else:
                        st.info("Selecione fornecedor")
                        artigo['marca'] = ""
                
                with col2:
                    artigo['descricao'] = st.text_area(
                        "Descrição *",
                        value=artigo['descricao'],
                        key=f"desc_{i}",
                        height=100
                    )
                
                with col3:
                    artigo['quantidade'] = st.number_input(
                        "Quantidade",
                        min_value=1,
                        value=artigo['quantidade'],
                        key=f"qtd_{i}"
                    )
                    
                    # Unidade logo abaixo da Quantidade
                    artigo['unidade'] = st.selectbox(
                        "Unidade",
                        ["Peças", "Metros", "KG", "Litros", "Caixas", "Paletes"],
                        index=0,
                        key=f"unidade_{i}"
                    )
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            adicionar_artigo = st.form_submit_button("➕ Adicionar Artigo")
        
        with col2:
            criar_cotacao = st.form_submit_button("✅ Criar Cotação", type="primary")
        
        with col3:
            limpar_form = st.form_submit_button("🗑️ Limpar Formulário")
    
    # Processar ações
    if adicionar_artigo:
        st.session_state.artigos.append({
            "artigo_num": "",
            "descricao": "",
            "quantidade": 1,
            "unidade": "Peças",
            "marca": ""
        })
        st.rerun()
    
    if limpar_form:
        st.session_state.artigos = [{
            "artigo_num": "",
            "descricao": "",
            "quantidade": 1,
            "unidade": "Peças",
            "marca": ""
        }]
        st.rerun()
    
    if criar_cotacao:
        # Validar campos obrigatórios
        if not nome_fornecedor:
            st.error("Por favor, selecione um fornecedor")
        elif not referencia:
            st.error("A referência é obrigatória")
        else:
            # Obter ou criar fornecedor
            if (
                fornecedor_selecionado == "➕ Novo Fornecedor"
                and st.session_state.get("role") in ["admin", "gestor"]
            ):
                fornecedor_id = inserir_fornecedor(
                    nome_fornecedor,
                    email_fornecedor if 'email_fornecedor' in locals() else "",
                    telefone_fornecedor if 'telefone_fornecedor' in locals() else "",
                )
            else:
                fornecedor_id = next((f[0] for f in fornecedores if f[1] == nome_fornecedor), None)
            
            # Criar RFQ
            artigos_validos = [a for a in st.session_state.artigos if a['descricao'].strip()]
            
            if artigos_validos and fornecedor_id:
                rfq_id = criar_rfq(
                    fornecedor_id, data, artigos_validos,
                    referencia, nome_solicitante,
                    email_solicitante, observacoes
                )
                
                if rfq_id:
                    st.success(f"✅ Cotação #{rfq_id} criada com sucesso!")
                    # Guardar PDF do cliente (upload) se existir
                    if upload_pedido_cliente is not None:
                        guardar_pdf_upload(rfq_id, 'anexo_cliente', upload_pedido_cliente.name, upload_pedido_cliente.getvalue())
                        st.success("Anexo do cliente guardado!")
                    
                    # Download do PDF
                    pdf_bytes = obter_pdf_da_db(rfq_id, "pedido")
                    if pdf_bytes:
                        st.download_button(
                            "📄 Download PDF",
                            data=pdf_bytes,
                            file_name=f"cotacao_{rfq_id}.pdf",
                            mime="application/pdf"
                        )
                    
                    # Limpar formulário
                    st.session_state.artigos = [{
                        "artigo_num": "",
                        "descricao": "",
                        "quantidade": 1,
                        "unidade": "Peças",
                        "marca": ""
                    }]
                else:
                    st.error("Erro ao criar cotação. Verifique se a referência já não existe.")
            else:
                st.error("Por favor, adicione pelo menos um artigo com descrição")

elif menu_option == "📩 Responder Cotações":
    st.title("📩 Responder Cotações")
    
    # Tabs para pendentes e respondidas
    tab1, tab2 = st.tabs(["Pendentes", "Respondidas"])
    
    with tab1:
        # Filtros
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            filtro_ref_pend = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_pend")
        with col2:
            st.write("")  # Espaço
        with col3:
            if st.button("🔄 Atualizar", key="refresh_pend"):
                st.rerun()
        
        # Obter cotações pendentes
        cotacoes_pendentes = obter_todas_cotacoes(filtro_ref_pend, "pendente")
        
        if cotacoes_pendentes:
            for cotacao in cotacoes_pendentes:
                with st.expander(f"#{cotacao['id']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    
                    # Se está mostrando o formulário de resposta para esta cotação
                    if st.session_state.show_response_form == cotacao['id']:
                        detalhes = obter_detalhes_cotacao(cotacao['id'])
                        
                        st.info(f"**Respondendo Cotação #{cotacao['id']}**")
                        
                        with st.form(f"resposta_form_{cotacao['id']}"):
                            # Dropbox - anexar resposta do fornecedor
                            upload_resposta_forn = st.file_uploader("📎 Resposta do fornecedor (PDF)", type=['pdf'], key=f"upload_resp_{cotacao['id']}")
                            respostas = []
                            
                            for i, artigo in enumerate(detalhes['artigos'], 1):
                                st.subheader(f"Artigo {i}: {artigo['artigo_num'] if artigo['artigo_num'] else 'S/N'}")
                                
                                # Mostrar margem aplicável
                                margem = obter_margem_para_marca(detalhes['fornecedor_id'], artigo['marca'])
                                st.info(f"Marca: {artigo['marca'] if artigo['marca'] else 'N/A'} | Margem: {margem:.1f}%")
                                
                                col1, col2 = st.columns([3, 1])
                                
                                with col1:
                                    descricao_editada = st.text_area(
                                        "Descrição (editável)",
                                        value=artigo['descricao'],
                                        key=f"desc_{artigo['id']}",
                                        height=80
                                    )
                                
                                with col2:
                                    quantidade_original = artigo['quantidade']
                                    quantidade_final = st.number_input(
                                        f"Qtd (Original: {quantidade_original})",
                                        min_value=1,
                                        value=quantidade_original,
                                        key=f"qtd_{artigo['id']}"
                                    )
                                
                                col3, col4, col5 = st.columns(3)
                                
                                with col3:
                                    custo = st.number_input(
                                        "Preço Compra (EUR )",
                                        min_value=0.0,
                                        step=0.01,
                                        key=f"custo_{artigo['id']}"
                                    )
                                    if custo > 0:
                                        preco_venda = custo * (1 + margem/100)
                                        st.success(f"P.V.: EUR {preco_venda:.2f}")
                                
                                with col4:
                                    prazo = st.number_input(
                                        "Prazo (dias)",
                                        min_value=1,
                                        value=30,
                                        key=f"prazo_{artigo['id']}"
                                    )
                                
                                with col5:
                                    peso = st.number_input(
                                        "Peso (kg)",
                                        min_value=0.0,
                                        step=0.1,
                                        key=f"peso_{artigo['id']}"
                                    )
                                
                                col6, col7 = st.columns(2)
                                
                                with col6:
                                    hs_code = st.text_input(
                                        "HS Code",
                                        key=f"hs_{artigo['id']}"
                                    )
                                
                                with col7:
                                    pais_origem = st.text_input(
                                        "País Origem",
                                        key=f"pais_{artigo['id']}"
                                    )
                                
                                respostas.append((
                                    artigo['id'], custo, prazo, peso, hs_code, 
                                    pais_origem, descricao_editada, quantidade_final
                                ))
                                
                                st.markdown("---")
                            
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                enviar = st.form_submit_button("✅ Enviar Resposta e Email", type="primary")
                            
                            with col2:
                                cancelar = st.form_submit_button("❌ Cancelar")
                        
                        if enviar:
                            respostas_validas = [r for r in respostas if r[1] > 0]
                            
                            if respostas_validas:
                                if upload_resposta_forn is not None:
                                    guardar_pdf_upload(cotacao['id'], 'anexo_fornecedor', upload_resposta_forn.name, upload_resposta_forn.getvalue())
                                if guardar_respostas(cotacao['id'], respostas_validas):
                                    st.success("✅ Resposta guardada e email enviado com sucesso!")
                                    st.session_state.show_response_form = None
                                    st.rerun()
                            else:
                                st.error("Por favor, preencha pelo menos um preço")
                        
                        if cancelar:
                            st.session_state.show_response_form = None
                            st.rerun()
                    
                    else:
                        # Mostrar informações da cotação
                        col1, col2 = st.columns([3, 1])
                        
                        with col1:
                            st.write(f"**Data:** {cotacao['data']}")
                            # Mostrar anexos existentes
                            conn = obter_conexao()
                            c = conn.cursor()
                            c.execute("SELECT tipo_pdf, nome_arquivo, pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf IN ('anexo_cliente', 'anexo_fornecedor')", (str(cotacao['id']),))
                            anexos = c.fetchall()
                            conn.close()
                            if anexos:
                                st.markdown("**Anexos:**")
                                for tipo, nome, data_pdf in anexos:
                                    rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                    st.download_button(
                                        label=f"⬇️ {rotulo}",
                                        data=data_pdf,
                                        file_name=nome if nome else f"{tipo}_{cotacao['id']}.pdf",
                                        mime="application/pdf",
                                        key=f"anexo_{cotacao['id']}_{tipo}"
                                    )
                                    exibir_pdf(f"👁️ {rotulo}", data_pdf)
                            st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                            st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                            st.write(f"**Artigos:** {cotacao['num_artigos']}")
                        
                        with col2:
                            # Botões de ação
                            pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
                            if pdf_pedido:
                                st.download_button(
                                    "📄 PDF",
                                    data=pdf_pedido,
                                    file_name=f"pedido_{cotacao['id']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_pend_{cotacao['id']}"
                                )
                                exibir_pdf("👁️ PDF", pdf_pedido)
                            
                            if st.button("💬 Responder", key=f"resp_{cotacao['id']}"):
                                st.session_state.show_response_form = cotacao['id']
                                st.rerun()
                            
                            if st.button("🗑️ Eliminar", key=f"del_pend_{cotacao['id']}"):
                                if eliminar_cotacao(cotacao['id']):
                                    st.success("Cotação eliminada!")
                                    st.rerun()
        else:
            st.info("Não há cotações pendentes")
    
    with tab2:
        # Filtros
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            filtro_ref_resp = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_resp")
        with col2:
            st.write("")
        with col3:
            if st.button("🔄 Atualizar", key="refresh_resp"):
                st.rerun()
        
        # Obter cotações respondidas
        cotacoes_respondidas = obter_todas_cotacoes(filtro_ref_resp, "respondido")
        
        if cotacoes_respondidas:
            for cotacao in cotacoes_respondidas:
                with st.expander(f"#{cotacao['id']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    # Detalhes da cotação
                    detalhes = obter_detalhes_cotacao(cotacao['id'])
                    respostas = obter_respostas_cotacao(cotacao['id'])
                    
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Data:** {cotacao['data']}")
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")
                        
                        if respostas:
                            st.markdown("---")
                            st.markdown("**Resumo das Respostas:**")
                            total_geral = 0
                            for resp in respostas:
                                preco_total = resp['preco_venda'] * resp['quantidade_final']
                                total_geral += preco_total
                                st.write(f"• {resp['descricao'][:50]}...")
                                st.write(f"  Qtd: {resp['quantidade_final']} | P.V.: EUR {resp['preco_venda']:.2f} | Total: EUR {preco_total:.2f}")
                            st.success(f"**Total Geral: EUR {total_geral:.2f}**")
                    
                    with col2:
                        # Anexos
                        conn = obter_conexao()
                        c = conn.cursor()
                        c.execute("SELECT tipo_pdf, nome_arquivo, pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf IN ('anexo_cliente', 'anexo_fornecedor')", (str(cotacao['id']),))
                        anexos = c.fetchall()
                        conn.close()
                        if anexos:
                            st.markdown("**Anexos:**")
                            for tipo, nome, data_pdf in anexos:
                                rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                st.download_button(
                                    label=f"⬇️ {rotulo}",
                                    data=data_pdf,
                                    file_name=nome if nome else f"{tipo}_{cotacao['id']}.pdf",
                                    mime="application/pdf",
                                    key=f"anexo_resp_{cotacao['id']}_{tipo}"
                                )
                                exibir_pdf(f"👁️ {rotulo}", data_pdf)
                        # PDF interno
                        pdf_interno = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_interno:
                            st.download_button(
                                "📄 PDF Interno",
                                data=pdf_interno,
                                file_name=f"interno_{cotacao['id']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_int_{cotacao['id']}"
                            )
                            exibir_pdf("👁️ PDF Interno", pdf_interno)

                        # PDF cliente
                        pdf_cliente = obter_pdf_da_db(cotacao['id'], "cliente")
                        if pdf_cliente:
                            st.download_button(
                                "💰 PDF Cliente",
                                data=pdf_cliente,
                                file_name=f"cliente_{cotacao['id']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_cli_{cotacao['id']}"
                            )
                            exibir_pdf("👁️ PDF Cliente", pdf_cliente)
                        
                        # Reenviar email
                        if st.button("📧 Reenviar", key=f"reenviar_{cotacao['id']}"):
                            if cotacao['email_solicitante']:
                                # Verificar se o PDF existe antes de tentar enviar
                                pdf_status = verificar_pdfs(cotacao['id'])
                                
                                if not pdf_status['cliente']:
                                    st.warning("PDF do cliente não encontrado. Gerando novo PDF...")
                                    if gerar_pdf_cliente(cotacao['id']):  # Tenta gerar novamente
                                        st.success("PDF gerado com sucesso!")
                                        # Após gerar com sucesso, tenta enviar
                                        if enviar_email_orcamento(
                                            cotacao['email_solicitante'],
                                            cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else "Cliente",
                                            cotacao['referencia'],
                                            cotacao['id']
                                        ):
                                            st.success("✅ E-mail reenviado com sucesso!")
                                        else:
                                            st.error("Falha no reenvio")
                                    else:
                                        st.error("Falha ao gerar PDF. Não foi possível enviar o e-mail.")
                                else:
                                    # PDF já existe, tenta enviar diretamente
                                    if enviar_email_orcamento(
                                        cotacao['email_solicitante'],
                                        cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else "Cliente",
                                        cotacao['referencia'],
                                        cotacao['id']
                                    ):
                                        st.success("✅ E-mail reenviado com sucesso!")
                                    else:
                                        st.error("Falha no reenvio")
                            else:
                                st.warning("Nenhum e-mail do solicitante registrado")
                        
                        if st.button("🗑️ Eliminar", key=f"del_resp_{cotacao['id']}"):
                            if eliminar_cotacao(cotacao['id']):
                                st.success("Cotação eliminada!")
                                st.rerun()
        else:
            st.info("Não há cotações respondidas")

elif menu_option == "📊 Relatórios":
    st.title("📊 Relatórios e Análises")
    
    tab1, tab2 = st.tabs(["Estatísticas Gerais", "Por Fornecedor"])
    
    with tab1:
        st.subheader("Estatísticas Gerais")
        
        stats = obter_estatisticas_db()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total de Cotações", stats.get('rfq', 0))
            st.metric("Artigos Cotados", stats.get('artigo', 0))
        
        with col2:
            st.metric("Taxa de Resposta", 
                     f"{(stats.get('rfq_respondidas', 0) / max(stats.get('rfq', 1), 1) * 100):.1f}%")
            st.metric("Fornecedores Ativos", stats.get('fornecedor', 0))
        
        with col3:
            st.metric("Orçamentos Enviados", stats.get('pdfs_cliente', 0))
            st.metric("PDFs Gerados", stats.get('pdfs_cliente', 0) * 2)
        
        # Gráfico de estado das cotações
        if stats.get('rfq', 0) > 0:
            st.markdown("---")
            st.subheader("Estado das Cotações")
            
            pendentes = stats.get('rfq_pendentes', 0)
            respondidas = stats.get('rfq_respondidas', 0)
            
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"🟡 Pendentes: {pendentes}")
            with col2:
                st.success(f"🟢 Respondidas: {respondidas}")
    
    with tab2:
        st.subheader("Análise por Fornecedor")
        
        fornecedores = listar_fornecedores()
        
        if fornecedores:
            fornecedor_sel = st.selectbox(
                "Selecionar Fornecedor",
                options=fornecedores,
                format_func=lambda x: x[1]
            )
            
            if fornecedor_sel:
                # Estatísticas do fornecedor
                conn = obter_conexao()
                c = conn.cursor()
                
                c.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN estado = 'respondido' THEN 1 ELSE 0 END) as respondidas,
                           SUM(CASE WHEN estado = 'pendente' THEN 1 ELSE 0 END) as pendentes
                    FROM rfq
                    WHERE fornecedor_id = ?
                """, (fornecedor_sel[0],))
                
                stats_forn = c.fetchone()
                
                if stats_forn:
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Total Cotações", stats_forn[0])
                    with col2:
                        st.metric("Respondidas", stats_forn[1])
                    with col3:
                        st.metric("Pendentes", stats_forn[2])
                    
                    # Marcas e margens
                    st.markdown("---")
                    st.subheader("Marcas e Margens Configuradas")
                    
                    marcas = obter_marcas_fornecedor(fornecedor_sel[0])
                    if marcas:
                        for marca in marcas:
                            margem = obter_margem_para_marca(fornecedor_sel[0], marca)
                            st.write(f"**{marca}**: {margem:.1f}%")
                    else:
                        st.info("Nenhuma marca configurada")
                
                conn.close()
        else:
            st.info("Nenhum fornecedor registado")

elif menu_option == "⚙️ Configurações":
    if st.session_state.get("role") not in ["admin", "gestor"]:
        st.error("Sem permissão para aceder a esta área")
    else:
        st.title("⚙️ Configurações do Sistema")

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Fornecedores",
            "Utilizadores",
            "Marcas e Margens",
            "Email",
            "Backup",
        ])

        with tab1:
            st.subheader("Gestão de Fornecedores")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("### Adicionar Fornecedor")
                with st.form("novo_fornecedor_form"):
                    nome = st.text_input("Nome *")
                    email = st.text_input("Email")
                    telefone = st.text_input("Telefone")
                    morada = st.text_area("Morada")
                    nif = st.text_input("NIF")

                    if st.form_submit_button("➕ Adicionar"):
                        if nome:
                            forn_id = inserir_fornecedor(nome, email, telefone, morada, nif)
                            if forn_id:
                                st.success(f"Fornecedor {nome} adicionado!")
                                st.rerun()
                        else:
                            st.error("Nome é obrigatório")

            with col2:
                st.markdown("### Fornecedores Registados")
                fornecedores = listar_fornecedores()

                for forn in fornecedores:
                    with st.expander(forn[1]):
                        with st.form(f"edit_forn_{forn[0]}"):
                            nome_edit = st.text_input("Nome", forn[1])
                            email_edit = st.text_input("Email", forn[2] or "")
                            telefone_edit = st.text_input("Telefone", forn[3] or "")
                            morada_edit = st.text_area("Morada", forn[4] or "")
                            nif_edit = st.text_input("NIF", forn[5] or "")

                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.form_submit_button("💾 Guardar"):
                                    if atualizar_fornecedor(
                                        forn[0],
                                        nome_edit,
                                        email_edit,
                                        telefone_edit,
                                        morada_edit,
                                        nif_edit,
                                    ):
                                        st.success("Fornecedor atualizado")
                                        st.rerun()
                                    else:
                                        st.error("Erro ao atualizar fornecedor")
                            with col_b:
                                if st.form_submit_button("🗑️ Eliminar"):
                                    if eliminar_fornecedor_db(forn[0]):
                                        st.success("Fornecedor eliminado")
                                        st.rerun()
                                    else:
                                        st.error("Erro ao eliminar fornecedor")

                    marcas = obter_marcas_fornecedor(forn[0])
                    st.write(f"**Marcas:** {', '.join(marcas) if marcas else 'Nenhuma'}")
    
    with tab2:
        if st.session_state.get("role") != "admin":
            st.warning("Apenas administradores podem gerir utilizadores.")
        else:
            st.subheader("Gestão de Utilizadores")

            col1, col2 = st.columns(2)

            with col1:
                st.markdown("### Adicionar Utilizador")
                with st.form("novo_user_form"):
                    username = st.text_input("Username *")
                    nome = st.text_input("Nome")
                    email_user = st.text_input("Email")
                    role = st.selectbox("Role", ["admin", "gestor", "user"])
                    password = st.text_input("Password *", type="password")

                    if st.form_submit_button("➕ Adicionar"):
                        if username and password:
                            if inserir_utilizador(username, password, nome, email_user, role):
                                st.success(f"Utilizador {username} adicionado!")
                                st.rerun()
                            else:
                                st.error("Erro ao adicionar utilizador")
                        else:
                            st.error("Username e password são obrigatórios")

            with col2:
                st.markdown("### Utilizadores Registados")
                utilizadores = listar_utilizadores()

                for user in utilizadores:
                    with st.expander(user[1]):
                        with st.form(f"edit_user_{user[0]}"):
                            username_edit = st.text_input("Username", user[1])
                            nome_edit = st.text_input("Nome", user[2] or "")
                            email_edit = st.text_input("Email", user[3] or "")
                            role_edit = st.selectbox(
                                "Role",
                                ["admin", "gestor", "user"],
                                index=["admin", "gestor", "user"].index(user[4]),
                            )
                            password_edit = st.text_input("Password", type="password")

                            col_a, col_b = st.columns(2)
                            with col_a:
                                if st.form_submit_button("💾 Guardar"):
                                    if atualizar_utilizador(
                                        user[0],
                                        username_edit,
                                        nome_edit,
                                        email_edit,
                                        role_edit,
                                        password_edit or None,
                                    ):
                                        st.success("Utilizador atualizado")
                                        st.rerun()
                                    else:
                                        st.error("Erro ao atualizar utilizador")
                            with col_b:
                                if st.form_submit_button("🗑️ Eliminar"):
                                    if eliminar_utilizador(user[0]):
                                        st.success("Utilizador eliminado")
                                        st.rerun()
                                    else:
                                        st.error("Erro ao eliminar utilizador")

    with tab3:
        st.subheader("Configuração de Marcas e Margens")
        
        fornecedores = listar_fornecedores()
        
        if fornecedores:
            fornecedor_sel = st.selectbox(
                "Selecionar Fornecedor",
                options=fornecedores,
                format_func=lambda x: x[1],
                key="forn_marcas"
            )
            
            if fornecedor_sel:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("### Adicionar Marca")
                    with st.form("add_marca_form"):
                        nova_marca = st.text_input("Nome da Marca")
                        margem_marca = st.number_input(
                            "Margem (%)",
                            min_value=0.0,
                            max_value=100.0,
                            value=15.0,
                            step=0.5
                        )
                        
                        if st.form_submit_button("➕ Adicionar Marca"):
                            if nova_marca:
                                if adicionar_marca_fornecedor(fornecedor_sel[0], nova_marca):
                                    configurar_margem_marca(fornecedor_sel[0], nova_marca, margem_marca)
                                    st.success(f"Marca {nova_marca} adicionada!")
                                    st.rerun()
                                else:
                                    st.error("Marca já existe para este fornecedor")
                
                with col2:
                    st.markdown("### Marcas Existentes")
                    marcas = obter_marcas_fornecedor(fornecedor_sel[0])
                    
                    if marcas:
                        for marca in marcas:
                            margem = obter_margem_para_marca(fornecedor_sel[0], marca)
                            
                            with st.expander(f"{marca} - {margem:.1f}%"):
                                nova_margem = st.number_input(
                                    "Nova Margem (%)",
                                    min_value=0.0,
                                    max_value=100.0,
                                    value=margem,
                                    step=0.5,
                                    key=f"margem_{fornecedor_sel[0]}_{marca}"
                                )
                                
                                col1, col2 = st.columns(2)
                                
                                with col1:
                                    if st.button("💾 Atualizar", key=f"upd_{fornecedor_sel[0]}_{marca}"):
                                        if configurar_margem_marca(fornecedor_sel[0], marca, nova_margem):
                                            st.success("Margem atualizada!")
                                            st.rerun()
                                
                                with col2:
                                    if st.button("🗑️ Remover", key=f"del_{fornecedor_sel[0]}_{marca}"):
                                        if remover_marca_fornecedor(fornecedor_sel[0], marca):
                                            st.success("Marca removida!")
                                            st.rerun()
                    else:
                        st.info("Nenhuma marca configurada")
        
        st.markdown("---")
        
        # Margem padrão
        st.subheader("Margem Padrão Global")
        
        margem_global = obter_margem_para_marca(None, None)
        nova_margem_global = st.number_input(
            "Margem Padrão (%)",
            min_value=0.0,
            max_value=100.0,
            value=margem_global,
            step=0.5
        )
        
        if st.button("💾 Guardar Margem Padrão"):
            conn = obter_conexao()
            c = conn.cursor()
            c.execute("""
                UPDATE configuracao_margens 
                SET margem_percentual = ?
                WHERE fornecedor_id IS NULL AND marca IS NULL
            """, (nova_margem_global,))
            conn.commit()
            conn.close()
            st.success("Margem padrão atualizada!")
            st.rerun()
    
    with tab4:
        st.subheader("Configuração de Email")
        
        # Obter configuração atual
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("SELECT * FROM configuracao_email WHERE ativo = TRUE")
        config_atual = c.fetchone()
        conn.close()
        
        with st.form("config_email_form"):
            smtp_server = st.text_input(
                "Servidor SMTP",
                value=config_atual[1] if config_atual else "smtp.gmail.com"
            )
            smtp_port = st.number_input(
                "Porta SMTP",
                value=config_atual[2] if config_atual else 587
            )
            email_user = st.text_input(
                "Email",
                value=config_atual[3] if config_atual else ""
            )
            email_password = st.text_input(
                "Password",
                type="password",
                value=config_atual[4] if config_atual else ""
            )
            
            if st.form_submit_button("💾 Guardar Configuração"):
                conn = obter_conexao()
                c = conn.cursor()
                
                # Desativar configurações anteriores
                c.execute("UPDATE configuracao_email SET ativo = FALSE")
                
                # Inserir nova configuração
                c.execute("""
                    INSERT INTO configuracao_email (smtp_server, smtp_port, email_user, email_password, ativo)
                    VALUES (?, ?, ?, ?, TRUE)
                """, (smtp_server, smtp_port, email_user, email_password))
                
                conn.commit()
                conn.close()
                
                st.success("Configuração de email guardada!")
        
        st.info("Nota: Para Gmail, use uma 'App Password' em vez da password normal")
    
    with tab5:
        st.subheader("Backup e Restauro")
        
        if st.button("💾 Criar Backup"):
            backup_path = backup_database()
            if backup_path:
                st.success(f"Backup criado: {backup_path}")
                
                # Ler o arquivo de backup para download
                with open(backup_path, 'rb') as f:
                    backup_data = f.read()
                
                st.download_button(
                    "⬇️ Download Backup",
                    data=backup_data,
                    file_name=backup_path,
                    mime="application/octet-stream"
                )
        
        st.markdown("---")
        
        st.warning("⚠️ Restaurar backup irá substituir todos os dados atuais!")
        
        uploaded_backup = st.file_uploader(
            "Selecionar arquivo de backup",
            type=['db']
        )
        
        if uploaded_backup:
            if st.button("⚠️ Restaurar Backup", type="secondary"):
                # Salvar arquivo temporário
                temp_path = "temp_restore.db"
                with open(temp_path, 'wb') as f:
                    f.write(uploaded_backup.getvalue())
                
                # Fazer backup atual antes de restaurar
                backup_database("backup_antes_restauro.db")
                
                # Restaurar
                try:
                    shutil.copy2(temp_path, DB_PATH)
                    os.remove(temp_path)
                    st.success("Backup restaurado com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao restaurar: {e}")

# Footer
st.markdown("---")
st.markdown("""
    <div style="text-align: center; color: #666; font-size: 12px;">
        Sistema ERP KTB Portugal v4.0 | Desenvolvido por Ricardo Nogueira | © 2025
    </div>
""", unsafe_allow_html=True)
