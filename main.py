import streamlit as st
import sqlite3
from datetime import datetime
from fpdf import FPDF
import base64
import json
from io import BytesIO
import os
import shutil
import smtplib
from streamlit_option_menu import option_menu
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


# ========================== CONFIGURAÇÃO GLOBAL ==========================
DB_PATH = "cotacoes.db"

# Configurações de Email (servidor e porta padrão)
EMAIL_CONFIG = {
    'smtp_server': 'smtp-mail.outlook.com',
    'smtp_port': 587
}

def load_pdf_config(tipo):
    """Carrega configurações de layout do PDF a partir de pdf_layout.json"""
    try:
        with open('pdf_layout.json', 'r', encoding='utf-8') as f:
            data=json.load(f)
        return data.get(tipo, {})
    except Exception:
        return {}

def save_pdf_config(tipo, config):
    """Guarda configurações de layout no ficheiro pdf_layout.json"""
    try:
        with open('pdf_layout.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[tipo] = config
    with open('pdf_layout.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
            utilizador_id INTEGER,
            FOREIGN KEY (fornecedor_id) REFERENCES fornecedor(id) ON DELETE CASCADE,
            FOREIGN KEY (utilizador_id) REFERENCES utilizador(id) ON DELETE SET NULL
        )
        """)

        # Garantir que coluna utilizador_id existe na tabela rfq
        c.execute("PRAGMA table_info(rfq)")
        if "utilizador_id" not in [row[1] for row in c.fetchall()]:
            c.execute("ALTER TABLE rfq ADD COLUMN utilizador_id INTEGER")

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
            nome_ficheiro TEXT,
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
            role TEXT NOT NULL,
            email_password TEXT
        )
        """)

        # Garantir que coluna email_password existe
        c.execute("PRAGMA table_info(utilizador)")
        if "email_password" not in [row[1] for row in c.fetchall()]:
            c.execute("ALTER TABLE utilizador ADD COLUMN email_password TEXT")

        # Inserir utilizador administrador padrão se a tabela estiver vazia
        c.execute("SELECT COUNT(*) FROM utilizador")
        if c.fetchone()[0] == 0:
            c.execute(
                """
                INSERT INTO utilizador (username, password, nome, email, role, email_password)
                VALUES ('admin', 'admin', 'Administrador', 'admin@example.com', 'admin', '')
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


def listar_todas_marcas():
    """Obter todas as marcas disponíveis"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT DISTINCT marca FROM fornecedor_marca ORDER BY marca")
    marcas = [row[0] for row in c.fetchall()]
    conn.close()
    return marcas


def obter_fornecedor_por_marca(marca):
    """Retorna fornecedor (id, nome, email) associado à marca"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        """
        SELECT f.id, f.nome, f.email
        FROM fornecedor f
        JOIN fornecedor_marca fm ON f.id = fm.fornecedor_id
        WHERE fm.marca = ?
        """,
        (marca,),
    )
    res = c.fetchone()
    conn.close()
    return res


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
        "SELECT id, username, password, nome, email, role, email_password FROM utilizador WHERE username = ?",
        (username,),
    )
    user = c.fetchone()
    conn.close()
    return user


def obter_utilizador_por_id(user_id):
    """Obter utilizador pelo ID"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT id, username, password, nome, email, role, email_password FROM utilizador WHERE id = ?",
        (user_id,),
    )
    user = c.fetchone()
    conn.close()
    return user


def inserir_utilizador(username, password, nome="", email="", role="user", email_password=""):
    """Inserir novo utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            """
            INSERT INTO utilizador (username, password, nome, email, role, email_password)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password, nome, email, role, email_password),
        )
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def atualizar_utilizador(
    user_id, username, nome, email, role, password=None, email_password=None
):
    """Atualizar dados de um utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        fields = ["username = ?", "nome = ?", "email = ?", "role = ?"]
        params = [username, nome, email, role]
        if password:
            fields.append("password = ?")
            params.append(password)
        if email_password:
            fields.append("email_password = ?")
            params.append(email_password)
        params.append(user_id)
        c.execute(
            f"UPDATE utilizador SET {', '.join(fields)} WHERE id = ?",
            params,
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
        utilizador_id = st.session_state.get("user_id")
        c.execute("""
            INSERT INTO rfq (fornecedor_id, data, referencia,
                           nome_solicitante, email_solicitante, observacoes, estado, utilizador_id)
            VALUES (?, ?, ?, ?, ?, ?, 'pendente', ?)
        """, (fornecedor_id, data.isoformat(), referencia,
              nome_solicitante, email_solicitante, observacoes, utilizador_id))
        
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

def obter_todas_cotacoes(filtro_referencia="", estado=None, fornecedor_id=None, utilizador_id=None):
    """Obter todas as cotações com filtros opcionais"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        query = """
            SELECT rfq.id, rfq.data, fornecedor.nome, rfq.estado, rfq.referencia,
                   COUNT(artigo.id) as num_artigos, rfq.nome_solicitante, rfq.email_solicitante,
                   u.nome
            FROM rfq
            JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
            LEFT JOIN utilizador u ON rfq.utilizador_id = u.id
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

        if fornecedor_id:
            conditions.append("rfq.fornecedor_id = ?")
            params.append(fornecedor_id)

        if utilizador_id:
            conditions.append("rfq.utilizador_id = ?")
            params.append(utilizador_id)
        
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
            "email_solicitante": row[7] if row[7] else "",
            "criador": row[8] if row[8] else ""
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
            "fornecedor": info[13],
            "utilizador_id": info[12],
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
        
        # Obter configurações de email (servidor/porta)
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            SELECT smtp_server, smtp_port
            FROM configuracao_email
            WHERE ativo = TRUE
            LIMIT 1
        """)
        config = c.fetchone()
        conn.close()

        if config:
            smtp_server, smtp_port = config
        else:
            print("⚠️ Usando configurações padrão de email")
            smtp_server = EMAIL_CONFIG['smtp_server']
            smtp_port = EMAIL_CONFIG['smtp_port']

        # Credenciais do utilizador atual
        current_user = obter_utilizador_por_id(st.session_state.get("user_id"))
        if current_user and current_user[4] and current_user[6]:
            email_user = current_user[4]
            email_password = current_user[6]
        else:
            st.error("Configure o seu email e palavra-passe no perfil antes de enviar emails.")
            return False

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
        c.execute("SELECT smtp_server, smtp_port FROM configuracao_email WHERE ativo = TRUE LIMIT 1")
        config = c.fetchone()
        conn.close()

        if config:
            smtp_server, smtp_port = config
        else:
            smtp_server = EMAIL_CONFIG['smtp_server']
            smtp_port = EMAIL_CONFIG['smtp_port']

        current_user = obter_utilizador_por_id(st.session_state.get("user_id"))
        if current_user and current_user[4] and current_user[6]:
            email_user = current_user[4]
            email_password = current_user[6]
        else:
            st.error("Configure o seu email e palavra-passe no perfil antes de enviar emails.")
            return False

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

def guardar_pdf_upload(rfq_id, tipo_pdf, nome_ficheiro, bytes_):
    """Guarda um PDF carregado pelo utilizador na tabela pdf_storage."""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO pdf_storage (rfq_id, tipo_pdf, pdf_data, tamanho_bytes, nome_ficheiro)
            VALUES (?, ?, ?, ?, ?)
        """, (str(rfq_id), tipo_pdf, bytes_, len(bytes_), nome_ficheiro))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro a guardar PDF: {e}")
        return False

# ========================== CLASSES PDF ==========================

class QuotationPDF(FPDF):
    """PDF para pedido de cotação ao fornecedor (sem marca)"""
    def __init__(self, config=None):
        super().__init__()
        self.cfg = config or {}

    def header(self):
        header_cfg = self.cfg.get("header", {})
        logo_cfg = header_cfg.get("logo", {})
        try:
            path = logo_cfg.get("path", "logo.jpeg")
            if os.path.exists(path):
                self.image(path, logo_cfg.get("x", 160), logo_cfg.get("y", 10), logo_cfg.get("w", 40))
        except Exception:
            pass
        font = header_cfg.get("font", "Arial")
        style = header_cfg.get("font_style", "B")
        size = header_cfg.get("font_size", 16)
        title = header_cfg.get("title", "PEDIDO DE COTAÇÃO")
        line_height = header_cfg.get("line_height", 10)
        self.set_font(font, style, size)
        self.cell(0, line_height, title, ln=True, align='C')
        self.ln(header_cfg.get("spacing", 5))

    def add_info(self, fornecedor, data, referencia=""):
        body_cfg = self.cfg.get("body", {})
        font = body_cfg.get("font", "Arial")
        size = body_cfg.get("font_size", 12)
        self.set_font(font, "", size)
        self.cell(0, 10, f"Data: {data}", ln=True)
        self.cell(0, 10, f"Fornecedor: {fornecedor}", ln=True)
        if referencia:
            self.cell(0, 10, f"Referência: {referencia}", ln=True)
        self.ln(8)

    def add_table_header(self):
        table_cfg = self.cfg.get("table", {})
        headers = table_cfg.get("headers", ["#", "Art. Nº", "Descrição", "Qtd", "Unidade", "Preço Unit."])
        widths = table_cfg.get("widths", [10, 25, 85, 20, 25, 25])
        font = table_cfg.get("font", "Arial")
        style = table_cfg.get("font_style", "B")
        size = table_cfg.get("font_size", 10)
        self.set_font(font, style, size)
        for i in range(len(headers)):
            self.cell(widths[i], 8, headers[i], border=1, align='C')
        self.ln()

    def add_table_row(self, idx, artigo):
        table_cfg = self.cfg.get("table", {})
        widths = table_cfg.get("widths", [10, 25, 85, 20, 25, 25])
        row_font = table_cfg.get("font", "Arial")
        row_size = table_cfg.get("row_font_size", 9)
        self.set_font(row_font, "", row_size)
        
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
        note = self.cfg.get("footer_note", "Por favor, preencha os preços unitários e devolva este documento.")
        body_cfg = self.cfg.get("body", {})
        note_size = body_cfg.get("note_font_size", 10)
        self.ln(10)
        self.set_font(body_cfg.get("font", "Arial"), "I", note_size)
        self.cell(0, 5, note, ln=True)

        return self.output(dest='S').encode('latin-1')


class ClientQuotationPDF(FPDF):
    """PDF para orçamento ao cliente com todos os detalhes"""
    def __init__(self, config=None):
        super().__init__()
        self.cfg = config or {}

    def header(self):
        header_cfg = self.cfg.get("header", {})
        logo_cfg = header_cfg.get("logo", {})
        try:
            path = logo_cfg.get("path", "logo.jpeg")
            if os.path.exists(path):
                self.image(path, logo_cfg.get("x", 160), logo_cfg.get("y", 10), logo_cfg.get("w", 40))
        except Exception:
            pass
        font = header_cfg.get("font", "Arial")
        style = header_cfg.get("font_style", "B")
        size = header_cfg.get("font_size", 16)
        title = header_cfg.get("title", "ORÇAMENTO")
        line_height = header_cfg.get("line_height", 10)
        self.set_font(font, style, size)
        self.cell(0, line_height, title, ln=True, align='C')
        self.ln(header_cfg.get("spacing", 5))

    def add_info(self, rfq_info, solicitante_info):
        body_cfg = self.cfg.get("body", {})
        font = body_cfg.get("font", "Arial")
        size = body_cfg.get("font_size", 12)
        self.set_font(font, "", size)
        self.cell(0, 8, f"Data: {rfq_info['data']}", ln=True)
        self.cell(0, 8, f"Referência: {rfq_info['referencia']}", ln=True)
        if solicitante_info.get('nome'):
            self.cell(0, 8, f"Para: {solicitante_info['nome']}", ln=True)
        if solicitante_info.get('email'):
            self.cell(0, 8, f"Email: {solicitante_info['email']}", ln=True)
        self.ln(5)

    def add_table_header(self):
        table_cfg = self.cfg.get("table", {})
        headers = table_cfg.get("headers", ["#", "Art. Nº", "Descrição", "Qtd", "P.Unit.", "Total", "HS Code", "Origem", "Prazo", "Peso"])
        widths = table_cfg.get("widths", [8, 18, 55, 12, 18, 20, 18, 15, 12, 14])
        font = table_cfg.get("font", "Arial")
        style = table_cfg.get("font_style", "B")
        size = table_cfg.get("font_size", 9)
        self.set_font(font, style, size)
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
        table_cfg = self.cfg.get("table", {})
        widths = table_cfg.get("widths", [8, 18, 55, 12, 18, 20, 18, 15, 12, 14])
        row_font = table_cfg.get("font", "Arial")
        row_size = table_cfg.get("row_font_size", 8)
        self.set_font(row_font, "", row_size)
        
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
        totals_cfg = self.cfg.get("totals", {})
        font = totals_cfg.get("font", "Arial")
        style = totals_cfg.get("font_style", "B")
        size = totals_cfg.get("font_size", 11)
        label_w = totals_cfg.get("label_width", 131)
        total_w = totals_cfg.get("total_width", 20)
        extra_w = totals_cfg.get("extra_width", 39)
        self.ln(5)
        self.set_font(font, style, size)
        self.cell(label_w, 8, "TOTAL:", border=1, align='R')
        self.cell(total_w, 8, f"EUR {total_geral:.2f}", border=1, align='C')
        self.cell(extra_w, 8, f"Peso Total: {peso_total:.1f}kg", border=1, align='C')
        self.ln(10)

        conditions = self.cfg.get("conditions", [
            "Validade da proposta: 30 dias",
            "Preços não incluem IVA",
            "Condições de pagamento: A combinar",
        ])
        self.set_font(font, "", size - 1)
        for cond in conditions:
            self.cell(0, 5, cond, ln=True)

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
        config = load_pdf_config("pedido")
        pdf_generator = QuotationPDF(config)
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
        config = load_pdf_config("cliente")
        pdf_cliente = ClientQuotationPDF(config)
        pdf_bytes = pdf_cliente.gerar(
            rfq_info={
                'data': rfq_data[2],
                'referencia': rfq_data[4],
                'fornecedor': rfq_data[13]
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
    if not data_pdf:
        st.warning("PDF não disponível")
        return
    b64 = base64.b64encode(data_pdf).decode()
    pdf_html = f"""
        <iframe src='data:application/pdf;base64,{b64}' width='100%' height='500' style='border:none;'></iframe>
    """

    with st.expander(label):
        st.components.v1.html(pdf_html, height=500)


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
        
        # Contar registos principais
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

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.user_email = None
    st.session_state.user_email_pass = None


def login_screen():
    st.markdown("<h1 style='text-align:center;'>🔐 Login</h1>", unsafe_allow_html=True)
    # Estilizar o formulário para ser mais amplo e centralizado
    st.markdown(
        """
        <style>
        div[data-testid="stForm"] {
            max-width: 400px;
            margin: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.form("login_form"):
        username = st.text_input("Utilizador")
        password = st.text_input("Palavra-passe", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        user = obter_utilizador_por_username(username)
        if user and user[2] == password:
            st.session_state.logged_in = True
            st.session_state.role = user[5]
            st.session_state.user_id = user[0]
            st.session_state.username = user[1]
            st.session_state.user_email = user[4]
            st.session_state.user_email_pass = user[6]
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
    st.markdown(
        """
        <style>
        .nav-link:hover {
            color: #2e7d32 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    opcoes_menu = [
        "🏠 Dashboard",
        "📝 Nova Cotação",
        "📩 Responder Cotações",
        "📊 Relatórios",
        "📄 PDFs",
        "👤 Perfil",
    ]
    if st.session_state.get("role") in ["admin", "gestor"]:
        opcoes_menu.append("⚙️ Configurações")
    menu_option = option_menu(
        "",
        opcoes_menu,
        icons=["" for _ in opcoes_menu],
        menu_icon="",
        default_index=0,
        styles={
            # tornar o fundo do menu transparente para coincidir com a barra lateral
            "container": {"padding": "0", "background-color": "transparent"},
            # ajustar o tamanho de letra e evitar quebras de linha
            "nav-link": {
                "font-size": "14px",
                "text-align": "left",
                "margin": "2px",
                "--hover-color": "#eee",
                "white-space": "nowrap",
                "padding": "4px 2px",
                "line-height": "24px",
            },
            "nav-link-selected": {"background-color": "#d0f0c0"},
            "icon": {"display": "none"},
        },
    )
    
    st.markdown("---")

    # Estatísticas rápidas
    stats = obter_estatisticas_db()
    st.metric("Cotações Pendentes", stats.get('rfq_pendentes', 0))
    st.metric("Cotações Respondidas", stats.get('rfq_respondidas', 0))

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sair", icon="🚪", key="sidebar_logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.user_email = None
        st.session_state.user_email_pass = None
        st.rerun()

    st.markdown("---")
    st.markdown("""
        <div style="text-align: center; font-size: 12px;">
            <p>Sistema ERP v4.0</p>
            <p>© 2025 KTB Portugal</p>
        </div>
    """, unsafe_allow_html=True)

# ========================== PÁGINAS DO SISTEMA ==========================

if menu_option == "🏠 Dashboard":
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

    marcas = listar_todas_marcas()

    col1, col2 = st.columns(2)
    with col1:
        marca_opcoes = [""] + marcas
        marca_selecionada = st.selectbox("Marca *", marca_opcoes, key="marca_select")
        fornecedor_id_selecionado = None
        nome_fornecedor = ""
        if marca_selecionada:
            fornecedor_info = obter_fornecedor_por_marca(marca_selecionada)
            if fornecedor_info:
                fornecedor_id_selecionado, nome_fornecedor, _ = fornecedor_info
    with col2:
        data = st.date_input("Data da cotação", datetime.today())

    with st.form(key="nova_cotacao_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            referencia = st.text_input("Referência *", placeholder="Ex: KTB-2025-001")
        with col2:
            nome_solicitante = st.text_input("Nome do solicitante")
        with col3:
            email_solicitante = st.text_input("Email do solicitante")

        col_obs, col_pdf = st.columns(2)
        with col_obs:
            observacoes = st.text_area("Observações", height=100)
        with col_pdf:
            upload_pedido_cliente = st.file_uploader(
                "📎 Pedido do cliente (PDF)",
                type=['pdf'],
                key='upload_pedido_cliente'
            )

        st.markdown("### 📦 Artigos")

        for i, artigo in enumerate(st.session_state.artigos, 1):
            with st.expander(f"Artigo {i}", expanded=(i == 1)):
                col1, col2, col3 = st.columns([1, 3, 1])

                with col1:
                    artigo['artigo_num'] = st.text_input("Nº Artigo", value=artigo['artigo_num'], key=f"art_num_{i}")
                    st.text_input("Marca", value=marca_selecionada or "", key=f"marca_{i}", disabled=True)
                    artigo['marca'] = marca_selecionada or ""

                with col2:
                    artigo['descricao'] = st.text_area("Descrição *", value=artigo['descricao'], key=f"desc_{i}", height=100)

                with col3:
                    artigo['quantidade'] = st.number_input("Quantidade", min_value=1, value=artigo['quantidade'], key=f"qtd_{i}")

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
        if not marca_selecionada or not fornecedor_id_selecionado:
            st.error("Por favor, selecione uma marca válida")
        elif not referencia:
            st.error("A referência é obrigatória")
        else:
            fornecedor_id = fornecedor_id_selecionado
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
                        guardar_pdf_upload(
                            rfq_id, 'anexo_cliente',
                            upload_pedido_cliente.name,
                            upload_pedido_cliente.getvalue()
                        )
                        st.success("Anexo do cliente guardado!")

                    # Download do PDF
                    pdf_bytes = obter_pdf_da_db(rfq_id, "pedido")
                    if pdf_bytes:
                        st.download_button(
                            "📄 Download PDF",
                            data=pdf_bytes,
                            file_name=f"cotacao_{rfq_id}.pdf",
                            mime="application/pdf",
                        )

                    # Limpar formulário
                    st.session_state.artigos = [{
                        "artigo_num": "",
                        "descricao": "",
                        "quantidade": 1,
                        "unidade": "Peças",
                        "marca": "",
                    }]
                else:
                    st.error("Erro ao criar cotação. Verifique se a referência já não existe.")
            else:
                st.error("Por favor, adicione pelo menos um artigo com descrição")

elif menu_option == "📩 Responder Cotações":
    st.title("📩 Responder Cotações")

    @st.dialog("Responder Cotação")
    def responder_cotacao_dialog(cotacao):
        st.markdown(
            """
            <style>
            [data-testid="stDialog"] {
                width: 100vw;
                height: 100vh;
                max-width: none;
                top: 0;
                left: 0;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        detalhes = obter_detalhes_cotacao(cotacao['id'])
        st.info(f"**Respondendo Cotação #{cotacao['id']}**")

        with st.form(f"resposta_form_{cotacao['id']}"):
            upload_resposta_forn = st.file_uploader(
                "📎 Resposta do fornecedor (PDF)",
                type=['pdf'],
                key=f"upload_resp_{cotacao['id']}"
            )
            respostas = []

            for i, artigo in enumerate(detalhes['artigos'], 1):
                st.subheader(f"Artigo {i}: {artigo['artigo_num'] if artigo['artigo_num'] else 'S/N'}")

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
                    guardar_pdf_upload(
                        cotacao['id'],
                        'anexo_fornecedor',
                        upload_resposta_forn.name,
                        upload_resposta_forn.getvalue()
                    )
                if guardar_respostas(cotacao['id'], respostas_validas):
                    st.success("✅ Resposta guardada e email enviado com sucesso!")
                    st.rerun()
            else:
                st.error("Por favor, preencha pelo menos um preço")

        if cancelar:
            st.rerun()
    
    # Tabs para pendentes e respondidas
    tab1, tab2 = st.tabs(["Pendentes", "Respondidas"])

    with tab1:
        # Filtros
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        with col1:
            filtro_ref_pend = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_pend")
        with col2:
            fornecedores = listar_fornecedores()
            opcoes_forn = {"Todos": None}
            opcoes_forn.update({f[1]: f[0] for f in fornecedores})
            fornecedor_sel_pend = st.selectbox("Fornecedor", list(opcoes_forn.keys()), key="fornecedor_pend")
        with col3:
            utilizadores = listar_utilizadores()
            opcoes_user = {"Todos": None}
            opcoes_user.update({(u[2] or u[1]): u[0] for u in utilizadores})
            utilizador_sel_pend = st.selectbox("Utilizador", list(opcoes_user.keys()), key="utilizador_pend")
        with col4:
            if st.button("🔄 Atualizar", key="refresh_pend"):
                st.rerun()

        fornecedor_id_pend = opcoes_forn[fornecedor_sel_pend]
        utilizador_id_pend = opcoes_user[utilizador_sel_pend]

        # Obter cotações pendentes
        cotacoes_pendentes = obter_todas_cotacoes(
            filtro_ref_pend, "pendente", fornecedor_id_pend, utilizador_id_pend
        )
        
        if cotacoes_pendentes:
            for cotacao in cotacoes_pendentes:
                with st.expander(f"#{cotacao['id']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    # Mostrar informações da cotação
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.write(f"**Data:** {cotacao['data']}")
                        # Mostrar anexos existentes
                        conn = obter_conexao()
                        c = conn.cursor()
                        c.execute(
                            """
                            SELECT tipo_pdf, nome_ficheiro, pdf_data
                            FROM pdf_storage
                            WHERE rfq_id = ? AND tipo_pdf IN ('anexo_cliente', 'anexo_fornecedor')
                            """,
                            (cotacao["id"],),
                        )

                        anexos = c.fetchall()
                        conn.close()
                        if anexos:
                            st.markdown("**Anexos:**")
                            for tipo, nome, data_pdf in anexos:
                                rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                col_anexo_dl, col_anexo_view = st.columns([1, 1])
                                with col_anexo_dl:
                                    st.download_button(
                                        label=f"⬇️ {rotulo}",
                                        data=data_pdf,
                                        file_name=nome if nome else f"{tipo}_{cotacao['id']}.pdf",
                                        mime="application/pdf",
                                        key=f"anexo_{cotacao['id']}_{tipo}"
                                    )
                                with col_anexo_view:
                                    exibir_pdf(f"👁️ {rotulo}", data_pdf)
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")

                    with col2:
                        # Botões de ação
                        pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_pedido:
                            col_pdf_dl, col_pdf_view = st.columns([1, 1])
                            with col_pdf_dl:
                                st.download_button(
                                    "📄 PDF",
                                    data=pdf_pedido,
                                    file_name=f"pedido_{cotacao['id']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_pend_{cotacao['id']}"
                                )
                            with col_pdf_view:
                                exibir_pdf("👁️ PDF", pdf_pedido)

                        if st.button("💬 Responder", key=f"resp_{cotacao['id']}"):
                            responder_cotacao_dialog(cotacao)

                        if st.button("🗑️ Eliminar", key=f"del_pend_{cotacao['id']}"):
                            if eliminar_cotacao(cotacao['id']):
                                st.success("Cotação eliminada!")
                                st.rerun()
        else:
            st.info("Não há cotações pendentes")
    
    with tab2:
        # Filtros
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        with col1:
            filtro_ref_resp = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_resp")
        with col2:
            fornecedores = listar_fornecedores()
            opcoes_forn = {"Todos": None}
            opcoes_forn.update({f[1]: f[0] for f in fornecedores})
            fornecedor_sel_resp = st.selectbox("Fornecedor", list(opcoes_forn.keys()), key="fornecedor_resp")
        with col3:
            utilizadores = listar_utilizadores()
            opcoes_user = {"Todos": None}
            opcoes_user.update({(u[2] or u[1]): u[0] for u in utilizadores})
            utilizador_sel_resp = st.selectbox("Utilizador", list(opcoes_user.keys()), key="utilizador_resp")
        with col4:
            if st.button("🔄 Atualizar", key="refresh_resp"):
                st.rerun()

        fornecedor_id_resp = opcoes_forn[fornecedor_sel_resp]
        utilizador_id_resp = opcoes_user[utilizador_sel_resp]

        # Obter cotações respondidas
        cotacoes_respondidas = obter_todas_cotacoes(
            filtro_ref_resp, "respondido", fornecedor_id_resp, utilizador_id_resp
        )
        
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
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
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
                        c.execute("SELECT tipo_pdf, nome_ficheiro, pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf IN ('anexo_cliente', 'anexo_fornecedor')", (str(cotacao['id']),))
                        anexos = c.fetchall()
                        conn.close()
                        if anexos:
                            st.markdown("**Anexos:**")
                            for tipo, nome, data_pdf in anexos:
                                rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                col_resp_dl, col_resp_view = st.columns([1, 1])
                                with col_resp_dl:
                                    st.download_button(
                                        label=f"⬇️ {rotulo}",
                                        data=data_pdf,
                                        file_name=nome if nome else f"{tipo}_{cotacao['id']}.pdf",
                                        mime="application/pdf",
                                        key=f"anexo_resp_{cotacao['id']}_{tipo}"
                                    )
                                with col_resp_view:
                                    exibir_pdf(f"👁️ {rotulo}", data_pdf)
                        # PDF interno
                        pdf_interno = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_interno:
                            col_int_dl, col_int_view = st.columns([1, 1])
                            with col_int_dl:
                                st.download_button(
                                    "📄 PDF Interno",
                                    data=pdf_interno,
                                    file_name=f"interno_{cotacao['id']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_int_{cotacao['id']}"
                                )
                            with col_int_view:
                                exibir_pdf("👁️ PDF Interno", pdf_interno)

                        # PDF cliente
                        pdf_cliente = obter_pdf_da_db(cotacao['id'], "cliente")
                        if pdf_cliente:
                            col_cli_dl, col_cli_view = st.columns([1, 1])
                            with col_cli_dl:
                                st.download_button(
                                    "💰 PDF Cliente",
                                    data=pdf_cliente,
                                    file_name=f"cliente_{cotacao['id']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_cli_{cotacao['id']}"
                                )
                            with col_cli_view:
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
    
    tab1, tab2, tab3 = st.tabs(["Estatísticas Gerais", "Por Fornecedor", "Por Utilizador"])
    
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

    with tab3:
        st.subheader("Análise por Utilizador")

        utilizadores = listar_utilizadores()

        if utilizadores:
            user_sel = st.selectbox(
                "Selecionar Utilizador",
                options=utilizadores,
                format_func=lambda x: x[1],
            )

            if user_sel:
                conn = obter_conexao()
                c = conn.cursor()

                c.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN estado = 'respondido' THEN 1 ELSE 0 END) as respondidas,
                           SUM(CASE WHEN estado = 'pendente' THEN 1 ELSE 0 END) as pendentes
                    FROM rfq
                    WHERE utilizador_id = ?
                    """,
                    (user_sel[0],),
                )

                stats_user = c.fetchone()

                if stats_user:
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.metric("Total Cotações", stats_user[0])
                    with col2:
                        st.metric("Respondidas", stats_user[1])
                    with col3:
                        st.metric("Pendentes", stats_user[2])

                    st.markdown("---")
                    st.subheader("Processos do Utilizador")

                    cotacoes_user = obter_todas_cotacoes(utilizador_id=user_sel[0])
                    if cotacoes_user:
                        df = [
                            {
                                "ID": c["id"],
                                "Fornecedor": c["fornecedor"],
                                "Data": c["data"],
                                "Estado": c["estado"],
                                "Referência": c["referencia"],
                            }
                            for c in cotacoes_user
                        ]
                        st.dataframe(df)
                    else:
                        st.info("Nenhuma cotação associada")

                conn.close()
        else:
            st.info("Nenhum utilizador registado")

elif menu_option == "📄 PDFs":
    st.title("📄 Gestão de PDFs")

    cotacoes = obter_todas_cotacoes()
    if cotacoes:
        cot_sel = st.selectbox(
            "Selecionar Cotação",
            options=cotacoes,
            format_func=lambda c: f"#{c['id']} - {c['referencia']}"
        )
        tipo_pdf = st.selectbox("Tipo de PDF", ["pedido", "cliente"], key="tipo_pdf_gest")
        pdf_atual = obter_pdf_da_db(cot_sel["id"], tipo_pdf)
        if pdf_atual:
            exibir_pdf("PDF Atual", pdf_atual)
        else:
            st.info("PDF não encontrado")

        if st.session_state.get("role") == "admin":
            novo_pdf = st.file_uploader("Substituir PDF", type=["pdf"], key="upload_pdf_gest")
            if novo_pdf and st.button("💾 Guardar PDF"):
                if guardar_pdf_upload(cot_sel["id"], tipo_pdf, novo_pdf.name, novo_pdf.getvalue()):
                    st.success("PDF atualizado com sucesso!")
        else:
            st.info("Apenas administradores podem atualizar o PDF.")
    else:
        st.info("Nenhuma cotação disponível")

elif menu_option == "👤 Perfil":
    st.title("👤 Meu Perfil")
    user = obter_utilizador_por_id(st.session_state.get("user_id"))
    if user:
        tab_email, tab_palavra_passe = st.tabs(["Email", "Palavra-passe do Sistema"])

        with tab_email:
            with st.form("email_form"):
                st.text_input("Email", value=user[4], disabled=True)
                email_pw = st.text_input("Palavra-passe do Email", type="password")
                sub_email = st.form_submit_button("Atualizar Palavra-passe do Email")
            if sub_email:
                if atualizar_utilizador(
                    user[0],
                    user[1],
                    user[3],
                    user[4],
                    user[5],
                    None,
                    email_pw or None,
                ):
                    st.success("Palavra-passe do email atualizada com sucesso!")
                else:
                    st.error("Erro ao atualizar palavra-passe do email")

        with tab_palavra_passe:
            with st.form("palavra_passe_form"):
                nova_pw = st.text_input("Nova Palavra-passe", type="password")
                confirmar_pw = st.text_input("Confirmar Palavra-passe", type="password")
                sub_pw = st.form_submit_button("Alterar Palavra-passe")
            if sub_pw:
                if not nova_pw or nova_pw != confirmar_pw:
                    st.error("Palavras-passe não coincidem")
                else:
                    if atualizar_utilizador(
                        user[0],
                        user[1],
                        user[3],
                        user[4],
                        user[5],
                        nova_pw,
                        None,
                    ):
                        st.success("Palavra-passe atualizada com sucesso!")
                    else:
                        st.error("Erro ao atualizar palavra-passe")
    else:
        st.error("Utilizador não encontrado")

elif menu_option == "⚙️ Configurações":
    if st.session_state.get("role") not in ["admin", "gestor"]:
        st.error("Sem permissão para aceder a esta área")
    else:
        st.title("⚙️ Configurações do Sistema")
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "Fornecedores",
            "Utilizadores",
            "Marcas e Margens",
            "Email",
            "Backup",
            "Layout PDF",
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
                    email_pass = st.text_input("Palavra-passe do Email", type="password")
                    role = st.selectbox("Role", ["admin", "gestor", "user"])
                    password = st.text_input("Palavra-passe *", type="password")

                    if st.form_submit_button("➕ Adicionar"):
                        if username and password:
                            if inserir_utilizador(
                                username, password, nome, email_user, role, email_pass
                            ):
                                st.success(f"Utilizador {username} adicionado!")
                                st.rerun()
                            else:
                                st.error("Erro ao adicionar utilizador")
                        else:
                            st.error("Username e palavra-passe são obrigatórios")

            with col2:
                st.markdown("### Utilizadores Registados")
                utilizadores = listar_utilizadores()

                for user in utilizadores:
                    with st.expander(user[1]):
                        with st.form(f"edit_user_{user[0]}"):
                            username_edit = st.text_input("Username", user[1])
                            nome_edit = st.text_input("Nome", user[2] or "")
                            email_edit = st.text_input("Email", user[3] or "")
                            email_pass_edit = st.text_input(
                                "Palavra-passe do Email", type="password"
                            )
                            role_edit = st.selectbox(
                                "Role",
                                ["admin", "gestor", "user"],
                                index=["admin", "gestor", "user"].index(user[4]),
                            )
                            password_edit = st.text_input("Palavra-passe", type="password")

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
                                        email_pass_edit or None,
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

            if st.form_submit_button("💾 Guardar Configuração"):
                conn = obter_conexao()
                c = conn.cursor()

                # Desativar configurações anteriores
                c.execute("UPDATE configuracao_email SET ativo = FALSE")

                # Inserir nova configuração
                c.execute(
                    """
                    INSERT INTO configuracao_email (smtp_server, smtp_port, ativo)
                    VALUES (?, ?, TRUE)
                    """,
                    (smtp_server, smtp_port),
                )

                conn.commit()
                conn.close()

                st.success("Configuração de email guardada!")

        st.info("Nota: Para Gmail, usa uma 'App Password' em vez da palavra-passe normal")
    
    with tab5:
        st.subheader("Backup e Restauro")
        
        if st.button("💾 Criar Backup"):
            backup_path = backup_database()
            if backup_path:
                st.success(f"Backup criado: {backup_path}")
                
                # Ler o ficheiro de backup para download
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
            "Selecionar ficheiro de backup",
            type=['db']
        )
        
        if uploaded_backup:
            if st.button("⚠️ Restaurar Backup", type="secondary"):
                # Guardar ficheiro temporário
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

    with tab6:
        st.subheader("Layout dos PDFs")
        tipo_layout = st.selectbox("Tipo de PDF", ["pedido", "cliente"])
        config_atual = load_pdf_config(tipo_layout)
        config_texto = st.text_area(
            "Configuração (JSON)",
            json.dumps(config_atual, ensure_ascii=False, indent=2),
            height=400,
        )
        if st.button("💾 Guardar Layout"):
            try:
                nova_config = json.loads(config_texto)
                save_pdf_config(tipo_layout, nova_config)
                st.success("Layout atualizado com sucesso!")
            except json.JSONDecodeError as e:
                st.error(f"Erro no JSON: {e}")
        st.caption(
            "Altere textos, tamanhos de letra e posições editando o JSON acima."
        )

# Footer
st.markdown("---")
st.markdown("""
    <div style="text-align: center; color: #666; font-size: 12px;">
        Sistema ERP KTB Portugal v4.0 | Desenvolvido por Ricardo Nogueira | © 2025
    </div>
""", unsafe_allow_html=True)


