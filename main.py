import streamlit as st
import sqlite3
from datetime import datetime, date
from fpdf import FPDF
import base64
import json
from io import BytesIO
import os
import shutil
import imghdr
from streamlit_option_menu import option_menu
from db import (
    criar_processo,
    criar_base_dados_completa,
    get_connection as obter_conexao,
    backup_database,
    hash_password,
    verify_password,
    DB_PATH,
    engine,
)
from services.pdf_service import (
    load_pdf_config,
    save_pdf_config,
    obter_config_empresa,
    obter_pdf_da_db,
)
from services.email_service import send_email

# ========================== CONFIGURAÇÃO GLOBAL ==========================

# Configurações de Email (servidor e porta padrão)
EMAIL_CONFIG = {
    'smtp_server': 'smtp-mail.outlook.com',
    'smtp_port': 587
}



def _format_iso_date(value):
    """Format ISO 8601 strings or datetime objects to ``dd/mm/YYYY``.

    Returns an empty string if the value is falsy or cannot be parsed.
    """

    if not value:
        return ""

    if isinstance(value, (datetime, date)):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return ""

    return dt.strftime("%d/%m/%Y")


LOGO_PATH = "assets/logo.png"

st.set_page_config(
    page_title="myERP",
    page_icon=LOGO_PATH,
    layout="wide"
)

# ========================== GESTÃO DA BASE DE DADOS ==========================



# ========================== FUNÇÕES DE GESTÃO DE FORNECEDORES ==========================

@st.cache_data(show_spinner=False)
def listar_fornecedores():
    """Obter todos os fornecedores.

    Resultados memorizados para reduzir acessos à base de dados quando o
    utilizador navega entre páginas.
    """
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
            c.execute(
                """
                INSERT INTO fornecedor (nome, email, telefone, morada, nif)
                VALUES (?, ?, ?, ?, ?)
                """,
                (nome, email, telefone, morada, nif),
            )
            conn.commit()
            listar_fornecedores.clear()
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
        listar_fornecedores.clear()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def eliminar_fornecedor_db(fornecedor_id):
    """Eliminar fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM fornecedor WHERE id = ?", (fornecedor_id,))
    conn.commit()
    listar_fornecedores.clear()
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
    except Exception:
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
        "SELECT id, username, nome, email, role, email_password FROM utilizador ORDER BY username"
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
            (username, hash_password(password), nome, email, role, email_password),
        )
        conn.commit()
        return c.lastrowid
    except Exception:
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
            params.append(hash_password(password))
        if email_password is not None:
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
              email_solicitante=""):
    """Criar nova RFQ"""
    conn = obter_conexao()
    c = conn.cursor()

    try:
        utilizador_id = st.session_state.get("user_id")
        processo_id, numero_processo = criar_processo()
        if engine.dialect.name == "sqlite":
            c.execute(
                """
                INSERT INTO rfq (processo_id, fornecedor_id, data, referencia,
                               nome_solicitante, email_solicitante, estado, utilizador_id)
                VALUES (?, ?, ?, ?, ?, ?, 'pendente', ?)
                """,
                (
                    processo_id,
                    fornecedor_id,
                    data.isoformat(),
                    referencia,
                    nome_solicitante,
                    email_solicitante,
                    utilizador_id,
                ),
            )
            rfq_id = c.lastrowid
        else:
            c.execute(
                """
                INSERT INTO rfq (processo_id, fornecedor_id, data, referencia,
                               nome_solicitante, email_solicitante, estado, utilizador_id)
                VALUES (?, ?, ?, ?, ?, ?, 'pendente', ?) RETURNING id
                """,
                (
                    processo_id,
                    fornecedor_id,
                    data.isoformat(),
                    referencia,
                    nome_solicitante,
                    email_solicitante,
                    utilizador_id,
                ),
            )
            rfq_id = c.fetchone()[0]

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
        gerar_e_armazenar_pdf(rfq_id, fornecedor_id, data, artigos)
        # Enviar pedido por email ao fornecedor
        enviar_email_pedido_fornecedor(rfq_id)

        return rfq_id, numero_processo
    except Exception as e:
        conn.rollback()
        if "UNIQUE" in str(e).upper():
            st.error("Erro ao criar RFQ: referência já existente.")
        else:
            st.error(f"Erro ao criar RFQ: {str(e)}")
        return None, None
    finally:
        conn.close()

def obter_todas_cotacoes(filtro_referencia="", estado=None, fornecedor_id=None, utilizador_id=None):
    """Obter todas as cotações com filtros opcionais"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        query = """
            SELECT rfq.id,
                   rfq.data,
                   COALESCE(fornecedor.nome, 'Fornecedor desconhecido'),
                   rfq.estado,
                   COALESCE(processo.numero, 'Sem processo'),
                   rfq.referencia,
                   COUNT(artigo.id) as num_artigos,
                   rfq.nome_solicitante,
                   rfq.email_solicitante,
                   u.nome
            FROM rfq
            LEFT JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
            LEFT JOIN processo ON rfq.processo_id = processo.id
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
            "processo": row[4],
            "referencia": row[5],
            "num_artigos": row[6],
            "nome_solicitante": row[7] if row[7] else "",
            "email_solicitante": row[8] if row[8] else "",
            "criador": row[9] if row[9] else ""
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
            SELECT rfq.*, COALESCE(fornecedor.nome, 'Fornecedor desconhecido')
            FROM rfq
            LEFT JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
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
        c.execute("DELETE FROM resposta_custos WHERE rfq_id = ?", (rfq_id,))
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

def guardar_respostas(rfq_id, respostas, custo_envio=0.0):
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

        total_custos = sum(item[1] for item in respostas if item[1] > 0)

        # Obter margem para cada artigo baseada na marca
        for item in respostas:
            artigo_id, custo, prazo, peso, hs_code, pais_origem, descricao_editada, quantidade_final = item
            
            # Obter marca do artigo
            c.execute("SELECT marca FROM artigo WHERE id = ?", (artigo_id,))
            marca_result = c.fetchone()
            marca = marca_result[0] if marca_result else None

            proporcao = (custo / total_custos) if total_custos else 0
            custo_total = custo + custo_envio * proporcao

            # Obter margem configurada para a marca
            margem = obter_margem_para_marca(fornecedor_id, marca)
            preco_venda = custo_total * (1 + margem/100)

            c.execute(
                """
                INSERT OR REPLACE INTO resposta_fornecedor
                (fornecedor_id, rfq_id, artigo_id, descricao, custo, prazo_entrega,
                 peso, hs_code, pais_origem, margem_utilizada, preco_venda, quantidade_final)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fornecedor_id,
                    rfq_id,
                    artigo_id,
                    descricao_editada,
                    custo_total,
                    prazo,
                    peso,
                    hs_code,
                    pais_origem,
                    margem,
                    preco_venda,
                    quantidade_final,
                ),
            )
        
        # Guardar custos adicionais
        c.execute(
            "INSERT OR REPLACE INTO resposta_custos (rfq_id, custo_envio) VALUES (?, ?)",
            (rfq_id, custo_envio),
        )

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
        try:
            c.execute(
                "SELECT smtp_server, smtp_port FROM configuracao_email WHERE ativo = TRUE LIMIT 1"
            )
        except sqlite3.OperationalError:
            # Column "ativo" may not existir em bases de dados antigas
            c.execute(
                "SELECT smtp_server, smtp_port FROM configuracao_email LIMIT 1"
            )
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
            st.error(
                "Configure o seu email e palavra-passe no perfil."
            )
            return False

        print(f"🔧 Configurações SMTP: {smtp_server}:{smtp_port}")
        
        corpo = f"""
        Estimado(a) {nome_solicitante},

        Your Reference: {referencia}

        Segue em anexo o orçamento solicitado com a referência {referencia}.

        Ficamos à disposição para qualquer esclarecimento adicional.

        Com os melhores cumprimentos,
        Ricardo Nogueira
        """

        print(f"🚀 Tentando enviar email para {email_destino}...")
        send_email(
            email_destino,
            f"Orçamento - Ref: {referencia}",
            corpo,
            pdf_bytes=pdf_bytes,
            pdf_filename=f"orcamento_{referencia}.pdf",
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            email_user=email_user,
            email_password=email_password,
        )
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
        try:
            c.execute(
                "SELECT smtp_server, smtp_port FROM configuracao_email WHERE ativo = TRUE LIMIT 1"
            )
        except sqlite3.OperationalError:
            c.execute("SELECT smtp_server, smtp_port FROM configuracao_email LIMIT 1")
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
            st.error(
                "Configure o seu email e palavra-passe no perfil."
            )
            return False

        # Construir email
        corpo = f"""
Estimado(a) {fornecedor_nome},

Segue em anexo o pedido de cotação relativo à referência {referencia}.
Agradecemos o envio do preço, prazo de entrega, HS Code, país de origem e peso.

Com os melhores cumprimentos,
Ricardo Nogueira
"""
        send_email(
            fornecedor_email,
            f"Pedido de Cotação - Ref: {referencia}",
            corpo,
            pdf_bytes=pdf_bytes,
            pdf_filename=f"pedido_{referencia}.pdf",
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            email_user=email_user,
            email_password=email_password,
        )
        return True
    except Exception as e:
        st.error(f"Falha ao enviar email ao fornecedor: {e}")
        return False

def guardar_pdf_upload(rfq_id, tipo_pdf, nome_ficheiro, bytes_):
    """Guarda um PDF carregado pelo utilizador na tabela pdf_storage."""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO pdf_storage (rfq_id, tipo_pdf, pdf_data, tamanho_bytes, nome_ficheiro)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (rfq_id, tipo_pdf) DO UPDATE SET
                pdf_data = excluded.pdf_data,
                tamanho_bytes = excluded.tamanho_bytes,
                nome_ficheiro = excluded.nome_ficheiro
            """,
            (str(rfq_id), tipo_pdf, bytes_, len(bytes_), nome_ficheiro),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro a guardar PDF: {e}")
        return False

# ========================== CLASSES PDF ==========================

class InquiryPDF(FPDF):
    """Gera PDF de pedido de cotação seguindo layout profissional"""

    def __init__(self, config=None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.cfg = config or {}
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=18)
        self.recipient = {}

    # ------------------------------------------------------------------
    #  Header e Footer
    # ------------------------------------------------------------------
    def header(self):
        """Cabeçalho com duas colunas e grelha de metadados"""
        header_cfg = self.cfg.get("header", {})
        logo_cfg = header_cfg.get("logo", {})
        logo_path = logo_cfg.get("path", self.cfg.get("logo_path", LOGO_PATH))
        logo_bytes = self.cfg.get("logo_bytes")

        # Grelha de metadados no lado esquerdo
        meta = self.recipient.get("metadata", {})
        meta.setdefault("Page", str(self.page_no()))
        start_y = 15
        for label, value in meta.items():
            self.set_xy(15, start_y)
            self.set_font("Helvetica", "B", 10)
            self.cell(25, 5, f"{label}:")
            self.set_font("Helvetica", "", 10)
            # ``FPDF.cell`` internally calls ``replace`` on the value passed in,
            # which fails if a non-string (e.g. an int) is provided.  Converting
            # to ``str`` ensures metadata like numeric references or dates are
            # handled without errors when generating PDFs.
            self.cell(45, 5, str(value), ln=1)
            start_y += 5

        # Bloco do destinatário abaixo dos metadados
        self.set_xy(15, start_y + 5)
        recip = self.recipient.get("address", [])
        self.set_font("Helvetica", "", 10)
        for line in recip:
            # Garantir que cada linha é string para evitar erros de ``replace``
            # caso algum campo seja numérico.
            self.cell(80, 5, str(line), ln=1)

        # Bloco da empresa (logo + contactos) no lado direito
        if logo_bytes:
            img_type = imghdr.what(None, logo_bytes) or "png"
            self.image(
                BytesIO(logo_bytes),
                logo_cfg.get("x", self.w - 15 - 70),
                logo_cfg.get("y", 15),
                logo_cfg.get("w", 70),
                type=img_type.upper(),
            )
        elif os.path.exists(logo_path):
            self.image(
                logo_path,
                logo_cfg.get("x", self.w - 15 - 70),
                logo_cfg.get("y", 15),
                logo_cfg.get("w", 70),
            )
        company_lines = self.cfg.get(
            "company_lines",
            ["Ricardo Nogueira", "Rua Exemplo 123", "4455-123 Porto", "Portugal"],
        )
        self.set_xy(self.w - 15 - 70, 45)
        self.multi_cell(70, 4, "\n".join(company_lines), align="R")

        # Ajustar posição para início do corpo
        self.set_y(70)

    def footer(self):
        """Rodapé com linha e detalhes bancários"""
        self.set_line_width(0.2)
        self.set_y(-18)
        self.line(15, self.get_y(), self.w - 15, self.get_y())
        self.ln(2)

        bank_cols = self.cfg.get(
            "bank_details",
            [
                {"Bank": "Bank", "SWIFT/BIC": "ABCDEF", "IBAN / Account No.": "PT50 0000 0000 0000"},
            ],
        )
        legal_info = self.cfg.get(
            "legal_info",
            ["VAT ID: PT123", "EORI: PT123", "Registry: 123", "Managing Directors: N/A"],
        )
        col_w = (self.w - 30) / (len(bank_cols) + 1)
        y = self.get_y()
        for i, col in enumerate(bank_cols):
            x = 15 + i * col_w
            self.set_xy(x, y)
            for k, v in col.items():
                self.set_font("Helvetica", "B", 9)
                self.cell(col_w, 4, k, ln=1)
                self.set_font("Helvetica", "", 9)
                self.multi_cell(col_w, 4, v)
            y = self.get_y()
        # Última coluna com info legal
        self.set_xy(15 + len(bank_cols) * col_w, self.get_y())
        self.set_font("Helvetica", "", 9)
        self.multi_cell(col_w, 4, "\n".join(legal_info), align="R")

        # Logo do myERP com hyperlink
        self.set_y(-10)
        try:
            self.image(
                LOGO_PATH,
                x=(self.w - 20) / 2,
                y=self.get_y(),
                w=20,
                link="https://erpktb.streamlit.app/",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Corpo do documento
    # ------------------------------------------------------------------
    def _table_col_widths(self):
        item_w = self.w - 30 - 12 - 25 - 12 - 14
        return [12, 25, 12, 14, item_w]

    def add_title(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 8, "INQUIRY", ln=1)
        self.ln(4)

    def add_reference(self, referencia):
        self.set_font("Helvetica", "B", 11)
        self.cell(35, 5, "Our reference:")
        self.set_font("Helvetica", "", 11)
        self.cell(0, 5, referencia, ln=1)
        self.ln(4)

    def add_intro(self, nome_contacto=""):
        self.set_font("Helvetica", "", 11)
        if nome_contacto:
            self.cell(0, 5, f"Dear Mr./Ms. {nome_contacto},", ln=1)
        else:
            self.cell(0, 5, "Dear Sir/Madam,", ln=1)
        self.ln(4)
        self.cell(0, 5, "Please quote us for:", ln=1)
        self.ln(4)

    def table_header(self):
        col_w = self._table_col_widths()
        self.set_font("Helvetica", "B", 11)
        headers = ["Pos.", "Article No.", "Qty", "Unit", "Item"]
        aligns = ["C", "C", "C", "C", "L"]
        for w, h, a in zip(col_w, headers, aligns):
            self.cell(w, 8, h, border=1, align=a)
        self.ln()

    def add_item(self, idx, item):
        col_w = self._table_col_widths()
        line_height = 5
        # Preparar texto do item
        # ``descricao`` might be ``None`` if the item was partially filled in
        # the UI, so fall back to an empty string before splitting.
        item_text = item.get("descricao") or ""
        lines = item_text.split("\n")
        line_count = len(lines)
        row_height = line_count * line_height
        sub_height = line_height
        # Quebra de página se necessário
        if self.get_y() + row_height + sub_height > self.page_break_trigger:
            self.add_page()
            self.table_header()

        x_start = self.get_x()
        y_start = self.get_y()
        # ``artigo_num`` can be present with a ``None`` value.  ``FPDF.cell``
        # calls ``replace`` on the provided text, which fails for ``None``.
        # Converting to ``""`` avoids the "NoneType has no attribute 'replace'"
        # error when generating the PDF.
        part_no = item.get("artigo_num") or ""
        quantidade = item.get("quantidade")
        quantidade_str = str(quantidade) if quantidade is not None else ""
        unidade = item.get("unidade") or ""
        # Desenhar células
        for i in range(line_count):
            border = "LR"
            if i == 0:
                border = "LTR"
            if i == line_count - 1:
                border = border.replace("R", "RB")
            self.set_xy(x_start, y_start + i * line_height)
            self.cell(col_w[0], line_height, str(idx) if i == 0 else "", border=border, align="C")
            self.cell(col_w[1], line_height, part_no if i == 0 else "", border=border, align="C")
            self.cell(col_w[2], line_height, quantidade_str if i == 0 else "", border=border, align="C")
            self.cell(col_w[3], line_height, unidade if i == 0 else "", border=border, align="C")
            self.cell(col_w[4], line_height, lines[i], border=border)

        self.set_y(y_start + row_height)

    def gerar(self, fornecedor, data, artigos, referencia="", contacto=""):
        """Gera o PDF e devolve bytes"""
        addr_lines = [fornecedor.get("nome", "")]
        if fornecedor.get("morada"):
            addr_lines.extend(fornecedor["morada"].splitlines())
        if fornecedor.get("email"):
            addr_lines.append(fornecedor["email"])
        if fornecedor.get("telefone"):
            addr_lines.append(fornecedor["telefone"])
        if fornecedor.get("nif"):
            addr_lines.append(f"NIF: {fornecedor['nif']}")
        self.recipient = {
            "address": [l for l in addr_lines if l],
            "metadata": {
                "Date": data,
                "Contact": contacto,
            },
        }
        self.add_page()
        self.add_title()
        self.add_reference(referencia)
        self.add_intro(contacto)
        self.table_header()
        for idx, art in enumerate(artigos, 1):
            self.add_item(idx, art)
        return self.output(dest="S").encode("latin-1")


class ClientQuotationPDF(InquiryPDF):
    """PDF para orçamento ao cliente com layout semelhante ao PDF de pedido."""

    def __init__(self, config=None):
        super().__init__(config=config)

    def add_title(self):
        title = self.cfg.get("header", {}).get("title", "QUOTATION")
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 8, title, ln=1)
        self.ln(4)

    def table_header(self):
        table_cfg = self.cfg.get("table", {})
        headers = table_cfg.get(
            "headers",
            [
                "#",
                "Item No.",
                "Description",
                "Qty",
                "Unit Price",
                "Total",
                "Lead Time",
                "Weight",
            ],
        )
        widths = table_cfg.get(
            "widths", [8, 18, 78, 12, 18, 20, 12, 14]
        )
        font = table_cfg.get("font", "Arial")
        style = table_cfg.get("font_style", "B")
        size = table_cfg.get("font_size", 9)
        self.set_font(font, style, size)
        for w, h in zip(widths, headers):
            self.cell(w, 7, h, border=1, align="C")
        self.ln()

    def split_text(self, text, max_length):
        """Divide texto em linhas respeitando quebras de linha"""
        lines = []
        for part in text.split("\n"):
            words = part.split()
            if not words:
                lines.append("")
                continue
            current_line = words[0]
            for word in words[1:]:
                test_line = f"{current_line} {word}"
                if len(test_line) <= max_length:
                    current_line = test_line
                else:
                    lines.append(current_line)
                    current_line = word
            lines.append(current_line)
        return lines if lines else [""]

    def add_item(self, idx, item):
        table_cfg = self.cfg.get("table", {})
        widths = table_cfg.get(
            "widths", [8, 18, 78, 12, 18, 20, 12, 14]
        )
        row_font = table_cfg.get("font", "Arial")
        row_size = table_cfg.get("row_font_size", 8)
        self.set_font(row_font, "", row_size)

        preco_venda = float(item["preco_venda"])
        quantidade = int(item["quantidade_final"])
        total = preco_venda * quantidade

        desc = item.get("descricao") or ""
        max_desc_len = int(widths[2] * 0.9)
        lines = self.split_text(desc, max_desc_len)
        hs_code = item.get("hs_code")
        origem = item.get("pais_origem")
        if hs_code:
            lines.append(f"HS Code: {hs_code}")
        if origem:
            lines.append(f"Origin: {origem}")
        line_count = len(lines)
        row_height = line_count * 6

        if self.get_y() + row_height > self.page_break_trigger:
            self.add_page()
            self.table_header()

        for i, line in enumerate(lines):
            border = "LR"
            if i == 0:
                border = "LTR"
            if i == line_count - 1:
                border = border.replace("R", "RB")
            self.cell(widths[0], 6, str(idx) if i == 0 else "", border=border, align="C")
            self.cell(widths[1], 6, (item.get("artigo_num") or "")[:10] if i == 0 else "", border=border)
            self.cell(widths[2], 6, line, border=border)
            if i == 0:
                self.cell(widths[3], 6, str(quantidade), border=border, align="C")
                self.cell(widths[4], 6, f"EUR {preco_venda:.2f}", border=border, align="R")
                self.cell(widths[5], 6, f"EUR {total:.2f}", border=border, align="R")
                self.cell(
                    widths[6],
                    6,
                    f"{item.get('prazo_entrega', 30)}d",
                    border=border,
                    align="C",
                )
                self.cell(
                    widths[7],
                    6,
                    f"{(item.get('peso') or 0):.1f}kg",
                    border=border,
                    align="C",
                )
            else:
                for w in widths[3:]:
                    self.cell(w, 6, "", border=border)
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
        self.cell(label_w, 8, "TOTAL:", border=1, align="R")
        self.cell(total_w, 8, f"EUR {total_geral:.2f}", border=1, align="C")
        self.cell(extra_w, 8, f"Total Weight: {peso_total:.1f}kg", border=1, align="C")
        self.ln(10)

        conditions = self.cfg.get(
            "conditions",
            [
                "Proposal validity: 30 days",
                "Prices do not include VAT",
                "Payment terms: To be agreed",
            ],
        )
        self.set_font(font, "", size - 1)
        for cond in conditions:
            self.cell(0, 5, cond, ln=True)

    def gerar(self, rfq_info, solicitante_info, itens_resposta):
        addr_lines = []
        if solicitante_info.get("nome"):
            addr_lines.append(solicitante_info["nome"])
        if solicitante_info.get("email"):
            addr_lines.append(solicitante_info["email"])
        self.recipient = {
            "address": addr_lines,
            "metadata": {
                "Date": rfq_info["data"],
                "Reference": rfq_info["referencia"],
            },
        }
        self.add_page()
        self.add_title()
        self.add_reference(rfq_info["referencia"])
        self.table_header()
        total_geral = 0.0
        peso_total = 0.0
        for idx, item in enumerate(itens_resposta, 1):
            total_item = self.add_item(idx, item)
            total_geral += total_item
            peso_total += float(item.get("peso") or 0) * int(item["quantidade_final"])
        self.add_total(total_geral, peso_total)
        return self.output(dest="S").encode("latin-1")
# ========================== FUNÇÕES DE GESTÃO DE PDFs ==========================

def gerar_e_armazenar_pdf(rfq_id, fornecedor_id, data, artigos):
    """Gerar e armazenar PDF de pedido de cotação"""
    try:
        config = load_pdf_config("pedido")

        empresa = obter_config_empresa()
        conn = obter_conexao()
        c = conn.cursor()

        # Dados do utilizador que criou a RFQ
        c.execute(
            """
            SELECT u.nome, u.email
            FROM rfq
            LEFT JOIN utilizador u ON rfq.utilizador_id = u.id
            WHERE rfq.id = ?
            """,
            (rfq_id,),
        )
        user_row = c.fetchone()
        nome_user = user_row[0] if user_row and user_row[0] else ""
        email_user = user_row[1] if user_row and user_row[1] else ""

        if empresa:
            linhas = [empresa.get("nome") or "", empresa.get("morada") or ""]
            if empresa.get("telefone"):
                linhas.append(f"Tel: {empresa['telefone']}")
            if empresa.get("website"):
                linhas.append(empresa["website"])
            if nome_user:
                linhas.append(nome_user)
            if email_user:
                linhas.append(email_user)
            config["company_lines"] = [l for l in linhas if l]
            if empresa.get("iban"):
                config["bank_details"] = [{"IBAN / Account No.": empresa["iban"]}]
            if empresa.get("nif"):
                config.setdefault("legal_info", []).append(f"NIF: {empresa['nif']}")
            if empresa.get("logo"):
                config["logo_bytes"] = empresa["logo"]

        # Dados do fornecedor
        c.execute(
            "SELECT nome, email, telefone, morada, nif FROM fornecedor WHERE id = ?",
            (fornecedor_id,),
        )
        forn_row = c.fetchone()
        fornecedor = {
            "nome": forn_row[0] if forn_row else "",
            "email": forn_row[1] if forn_row else "",
            "telefone": forn_row[2] if forn_row else "",
            "morada": forn_row[3] if forn_row else "",
            "nif": forn_row[4] if forn_row else "",
        }

        c.execute(
            """SELECT processo.numero FROM rfq LEFT JOIN processo ON rfq.processo_id = processo.id
                   WHERE rfq.id = ?""",
            (rfq_id,),
        )
        row = c.fetchone()
        numero_processo = row[0] if row else ""

        pdf_generator = InquiryPDF(config)
        pdf_bytes = pdf_generator.gerar(
            fornecedor,
            data.strftime("%Y-%m-%d"),
            artigos,
            numero_processo,
        )

        c.execute(
            """
            INSERT INTO pdf_storage (rfq_id, tipo_pdf, pdf_data, tamanho_bytes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (rfq_id, tipo_pdf) DO UPDATE SET
                pdf_data = excluded.pdf_data,
                tamanho_bytes = excluded.tamanho_bytes
        """,
            (str(rfq_id), "pedido", pdf_bytes, len(pdf_bytes)),
        )
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
        c.execute(
            """SELECT rfq.*,
                       COALESCE(fornecedor.nome, 'Fornecedor desconhecido') AS fornecedor_nome,
                       processo.numero
                   FROM rfq
                   LEFT JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
                   LEFT JOIN processo ON rfq.processo_id = processo.id
                   WHERE rfq.id = ?""",
            (rfq_id,),
        )
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
        empresa = obter_config_empresa()
        if empresa:
            linhas = [empresa.get("nome") or "", empresa.get("morada") or ""]
            if empresa.get("telefone"):
                linhas.append(f"Tel: {empresa['telefone']}")
            if empresa.get("website"):
                linhas.append(empresa["website"])
            config["company_lines"] = [l for l in linhas if l]
            if empresa.get("iban"):
                config["bank_details"] = [{"IBAN / Account No.": empresa["iban"]}]
            if empresa.get("nif"):
                config.setdefault("legal_info", []).append(f"NIF: {empresa['nif']}")
            if empresa.get("logo"):
                config["logo_bytes"] = empresa["logo"]
        pdf_cliente = ClientQuotationPDF(config)
        pdf_bytes = pdf_cliente.gerar(
            rfq_info={
                'data': _format_iso_date(rfq_data[2]),
                'referencia': rfq_data[14] or '',
            },
            solicitante_info={
                'nome': rfq_data[6] or '',
                'email': rfq_data[7] or ''
            },
            itens_resposta=itens_resposta
        )

        # 4. Armazenar PDF
        c.execute(
            """INSERT INTO pdf_storage
                  (rfq_id, tipo_pdf, pdf_data, tamanho_bytes)
                  VALUES (?, ?, ?, ?)
                  ON CONFLICT (rfq_id, tipo_pdf) DO UPDATE SET
                      pdf_data = excluded.pdf_data,
                      tamanho_bytes = excluded.tamanho_bytes""",
            (str(rfq_id), "cliente", pdf_bytes, len(pdf_bytes)),
        )
        
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


def exibir_pdf(label, data_pdf, *, height: int = 600, expanded: bool = False):
    """Mostra PDF com fallback para pdf.js e opção de abrir em nova aba."""
    if not data_pdf:
        st.warning("PDF não disponível")
        return

    b64 = base64.b64encode(data_pdf).decode()

    with st.expander(label, expanded=expanded):
        pdf_html = f"""
        <object data="data:application/pdf;base64,{b64}" type="application/pdf" width="100%" height="{height}">
            <iframe src="https://mozilla.github.io/pdf.js/web/viewer.html?file=data:application/pdf;base64,{b64}" width="100%" height="{height}" style="border:none;"></iframe>
        </object>
        <div style="text-align:right;margin-top:4px;"><a href="data:application/pdf;base64,{b64}" target="_blank">🔎 Abrir em nova aba</a></div>
        """
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

# ========================== INICIALIZAÇÃO DO SISTEMA ==========================

def inicializar_sistema():
    """Inicializar todo o sistema"""
    print("Inicializando sistema myERP...")
    
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
        # ``strip`` evita falhas de autenticação devido a espaços acidentais
        username = st.text_input("Utilizador").strip()
        password = st.text_input("Palavra-passe", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        user = obter_utilizador_por_username(username)
        if user and verify_password(password, user[2]):
            st.session_state.logged_in = True
            st.session_state.role = user[5]
            st.session_state.user_id = user[0]
            st.session_state.username = user[1]
            st.session_state.user_email = user[4]
            st.rerun()
        else:
            st.error("Credenciais inválidas")
    st.markdown(
        f"<p style='text-align:center'><img src='{LOGO_PATH}' width='120'/></p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;'>Sistema myERP v4.0<br/>© 2025 Ricardo Nogueira</p>",
        unsafe_allow_html=True,
    )


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

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sair", icon="🚪", key="sidebar_logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.user_email = None
        st.rerun()

    st.markdown("---")
    st.markdown(
        f"""
        <div style="text-align: center; font-size: 12px;">
            <p><img src='{LOGO_PATH}' width='80'/></p>
            <p>Sistema myERP v4.0</p>
            <p>© 2025 Ricardo Nogueira</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
                st.write(f"**{cotacao['processo']}** - {cotacao['fornecedor']}")
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
        col1, col2 = st.columns(2)
        with col1:
            nome_solicitante = st.text_input("Cliente")
        with col2:
            email_solicitante = st.text_input("Email do Cliente")

        col_ref, col_pdf = st.columns(2)
        with col_ref:
            referencia_input = st.text_input("Referência Cliente")
        with col_pdf:
            upload_pedido_cliente = st.file_uploader(
                "📎 Pedido do cliente (PDF)",
                type=['pdf'],
                key='upload_pedido_cliente'
            )
            if upload_pedido_cliente is not None:
                exibir_pdf("👁️ PDF carregado", upload_pedido_cliente.getvalue(), expanded=True)

        st.markdown("### 📦 Artigos")

        remover_indice = None
        for i, artigo in enumerate(st.session_state.artigos, 1):
            with st.expander(f"Artigo {i}", expanded=(i == 1)):
                col1, col2, col3, col_del = st.columns([1, 3, 1, 0.5])

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

                with col_del:
                    # st.form_submit_button does not accept a "key" argument in some
                    # Streamlit versions. To keep the delete buttons distinct without
                    # visible numbering, append invisible zero‑width characters so each
                    # label remains unique while displaying only the trash icon.
                    delete_label = "🗑️" + "\u200B" * i
                    if st.form_submit_button(delete_label):
                        remover_indice = i - 1

        col1, col2, col3 = st.columns(3)

        with col1:
            adicionar_artigo = st.form_submit_button("➕ Adicionar Artigo")

        with col2:
            criar_cotacao = st.form_submit_button("✅ Criar Cotação", type="primary")

        with col3:
            limpar_form = st.form_submit_button("🗑️ Limpar Formulário")
    
    # Processar ações
    if remover_indice is not None:
        del st.session_state.artigos[remover_indice]
        if not st.session_state.artigos:
            st.session_state.artigos = [{
                "artigo_num": "",
                "descricao": "",
                "quantidade": 1,
                "unidade": "Peças",
                "marca": ""
            }]
        st.rerun()

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
        elif not referencia_input.strip():
            st.error("Por favor, indique uma referência")
        else:
            fornecedor_id = fornecedor_id_selecionado
            artigos_validos = [a for a in st.session_state.artigos if a['descricao'].strip()]

            if artigos_validos and fornecedor_id:
                rfq_id, numero_processo = criar_rfq(
                    fornecedor_id, data, artigos_validos, referencia_input,
                    nome_solicitante,
                    email_solicitante
                )

                if rfq_id:
                    st.success(
                        f"✅ Cotação {numero_processo} (Ref: {referencia_input}) criada com sucesso!"
                    )
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
            /* Occupy the full viewport with the dialog overlay */
            [data-testid="stDialog"] {
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            /* Limit the inner dialog content to 1200px */
            [data-testid="stDialog"] > div {
                width: 1200px;
                max-width: 1200px;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        detalhes = obter_detalhes_cotacao(cotacao['id'])
        st.info(f"**Respondendo Cotação {cotacao['processo']}**")

        tab_view, tab_replace = st.tabs(["Visualizar PDFs", "Substituir PDFs"])

        with tab_view:
            pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
            if pdf_pedido:
                exibir_pdf("📄 Pedido Interno", pdf_pedido, height=800, expanded=True)

            pdf_cliente = obter_pdf_da_db(cotacao['id'], "cliente")
            if pdf_cliente:
                exibir_pdf("📄 Pedido Cliente", pdf_cliente, height=800, expanded=True)

            pdf_resp_forn = obter_pdf_da_db(cotacao['id'], "anexo_fornecedor")
            if pdf_resp_forn:
                exibir_pdf("📄 Resposta Fornecedor", pdf_resp_forn, height=800, expanded=True)

        with tab_replace:
            novo_pedido_cliente = st.file_uploader(
                "📎 Substituir Pedido Cliente (PDF)",
                type=['pdf'],
                key=f"upload_pedido_cli_{cotacao['id']}"
            )
            if novo_pedido_cliente is not None:
                guardar_pdf_upload(
                    cotacao['id'],
                    'cliente',
                    novo_pedido_cliente.name,
                    novo_pedido_cliente.getvalue()
                )
                st.success("PDF de pedido cliente atualizado!")
                st.rerun()

            novo_resp_forn = st.file_uploader(
                "📎 Substituir Resposta Fornecedor (PDF)",
                type=['pdf'],
                key=f"upload_resp_forn_{cotacao['id']}"
            )
            if novo_resp_forn is not None:
                guardar_pdf_upload(
                    cotacao['id'],
                    'anexo_fornecedor',
                    novo_resp_forn.name,
                    novo_resp_forn.getvalue()
                )
                st.success("PDF de resposta fornecedor atualizado!")
                st.rerun()

        with st.form(f"resposta_form_{cotacao['id']}"):
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

            custo_envio = st.number_input(
                "Custos de envio e embalagem",
                min_value=0.0,
                step=0.01,
                key=f"custo_envio_{cotacao['id']}"
            )

            col1, col2 = st.columns(2)

            with col1:
                enviar = st.form_submit_button("✅ Enviar Resposta e Email", type="primary")

            with col2:
                cancelar = st.form_submit_button("❌ Cancelar")

        if enviar:
            respostas_validas = [r for r in respostas if r[1] > 0]

            if respostas_validas:
                if guardar_respostas(cotacao['id'], respostas_validas, custo_envio):
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
            st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
            if st.button("🔄 Atualizar", key="refresh_pend"):
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        fornecedor_id_pend = opcoes_forn[fornecedor_sel_pend]
        utilizador_id_pend = opcoes_user[utilizador_sel_pend]

        # Obter cotações pendentes
        cotacoes_pendentes = obter_todas_cotacoes(
            filtro_ref_pend, "pendente", fornecedor_id_pend, utilizador_id_pend
        )
        
        if cotacoes_pendentes:
            for cotacao in cotacoes_pendentes:
                with st.expander(f"{cotacao['processo']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
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
                                st.download_button(
                                    label=f"⬇️ {rotulo}",
                                    data=data_pdf,
                                    file_name=nome if nome else f"{tipo}_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"anexo_{cotacao['id']}_{tipo}"
                                )
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")

                    with col2:
                        # Botões de ação
                        pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_pedido:
                            st.download_button(
                                "📄 PDF",
                                data=pdf_pedido,
                                file_name=f"pedido_{cotacao['processo']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_pend_{cotacao['id']}"
                            )

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
            st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
            if st.button("🔄 Atualizar", key="refresh_resp"):
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        fornecedor_id_resp = opcoes_forn[fornecedor_sel_resp]
        utilizador_id_resp = opcoes_user[utilizador_sel_resp]

        # Obter cotações respondidas
        cotacoes_respondidas = obter_todas_cotacoes(
            filtro_ref_resp, "respondido", fornecedor_id_resp, utilizador_id_resp
        )
        
        if cotacoes_respondidas:
            for cotacao in cotacoes_respondidas:
                with st.expander(f"{cotacao['processo']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
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
                                st.download_button(
                                    label=f"⬇️ {rotulo}",
                                    data=data_pdf,
                                    file_name=nome if nome else f"{tipo}_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"anexo_resp_{cotacao['id']}_{tipo}"
                                )
                        # PDF interno
                        pdf_interno = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_interno:
                            st.download_button(
                                "📄 PDF Interno",
                                data=pdf_interno,
                                file_name=f"interno_{cotacao['processo']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_int_{cotacao['id']}"
                            )

                        # PDF cliente
                        pdf_cliente = obter_pdf_da_db(cotacao['id'], "cliente")
                        if pdf_cliente:
                            st.download_button(
                                "💰 PDF Cliente",
                                data=pdf_cliente,
                                file_name=f"cliente_{cotacao['processo']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_cli_{cotacao['id']}"
                            )
                        
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
                                "Processo": c["processo"],
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
            format_func=lambda c: f"{c['processo']} - {c['referencia']}"
        )

        pdf_types = [
            ("Pedido Cliente", "anexo_cliente", "📥"),
            ("Pedido Cotação", "pedido", "📤"),
            ("Resposta Fornecedor", "anexo_fornecedor", "📥"),
            ("Resposta Cliente", "cliente", "📤"),
        ]

        for label, tipo, emoji in pdf_types:
            pdf_bytes = obter_pdf_da_db(cot_sel["id"], tipo)
            if pdf_bytes:
                exibir_pdf(f"{emoji} {label}", pdf_bytes)
            else:
                st.info(f"{label} não encontrado")

        if st.session_state.get("role") == "admin":
            label_selec = st.selectbox(
                "Tipo de PDF a substituir",
                [lbl for lbl, _, _ in pdf_types],
                key="tipo_pdf_gest",
            )
            tipo_pdf = next(t for lbl, t, _ in pdf_types if lbl == label_selec)
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
        tab_pw, tab_email = st.tabs([
            "Alterar Palavra-passe do Sistema",
            "Configuração de Email",
        ])

        with tab_pw:
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
                    ):
                        st.success("Palavra-passe atualizada com sucesso!")
                    else:
                        st.error("Erro ao atualizar palavra-passe")

        with tab_email:
            with st.form("email_form"):
                email_edit = st.text_input("Username", value=user[4] or "")
                email_pw_edit = st.text_input(
                    "Palavra-passe do Email", value=user[6] or "", type="password"
                )
                sub_email = st.form_submit_button("Guardar Email")
            if sub_email:
                if atualizar_utilizador(
                    user[0],
                    user[1],
                    user[3],
                    email_edit,
                    user[5],
                    None,
                    email_pw_edit,
                ):
                    st.success("Dados de email atualizados com sucesso!")
                else:
                    st.error("Erro ao atualizar dados de email")
    else:
        st.error("Utilizador não encontrado")

elif menu_option == "⚙️ Configurações":
    if st.session_state.get("role") not in ["admin", "gestor"]:
        st.error("Sem permissão para aceder a esta área")
    else:
        st.title("⚙️ Configurações do Sistema")
        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
            "Fornecedores",
            "Marcas e Margens",
            "Utilizadores",
            "Email",
            "Backup",
            "Layout PDF",
            "Dados da Empresa",
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

        with tab3:
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
                        password = st.text_input("Palavra-passe *", type="password")

                        if st.form_submit_button("➕ Adicionar"):
                            if username and password:
                                if inserir_utilizador(
                                    username, password, nome, email_user, role
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
                                email_pw_edit = st.text_input("Password Email", user[5] or "", type="password")
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
                                            email_pw_edit or None,
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
        
        with tab4:
            st.subheader("Configuração de Email")
            
            # Obter configuração atual
            conn = obter_conexao()
            c = conn.cursor()
            try:
                c.execute("SELECT * FROM configuracao_email WHERE ativo = TRUE")
            except sqlite3.OperationalError:
                c.execute("SELECT * FROM configuracao_email")
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

                    try:
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
                    except sqlite3.OperationalError:
                        # Coluna "ativo" ausente - manter apenas uma configuração
                        c.execute("DELETE FROM configuracao_email")
                        c.execute(
                            "INSERT INTO configuracao_email (smtp_server, smtp_port) VALUES (?, ?)",
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
                key=f"layout_{tipo_layout}"
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
    
        with tab7:
            st.subheader("Dados da Empresa")
            conn = obter_conexao()
            c = conn.cursor()
            c.execute(
                "SELECT nome, morada, nif, iban, telefone, email, website, logo FROM configuracao_empresa ORDER BY id DESC LIMIT 1"
            )
            dados = c.fetchone()
            conn.close()
            with st.form("empresa_form"):
                nome_emp = st.text_input("Nome", dados[0] if dados else "")
                morada_emp = st.text_area("Morada", dados[1] if dados else "")
                nif_emp = st.text_input("NIF", dados[2] if dados else "")
                iban_emp = st.text_input("IBAN", dados[3] if dados else "")
                telefone_emp = st.text_input("Telefone", dados[4] if dados else "")
                email_emp = st.text_input("Email", dados[5] if dados else "")
                website_emp = st.text_input("Website", dados[6] if dados else "")
                logo_bytes = dados[7] if dados and len(dados) > 7 else None
                logo_upload = st.file_uploader("Logo", type=["png", "jpg", "jpeg"], key="logo_empresa")
                if logo_upload is not None:
                    logo_bytes = logo_upload.getvalue()
                if logo_bytes:
                    st.image(logo_bytes, width=120)
                if st.form_submit_button("💾 Guardar"):
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("DELETE FROM configuracao_empresa")
                    c.execute(
                        "INSERT INTO configuracao_empresa (nome, morada, nif, iban, telefone, email, website, logo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (nome_emp, morada_emp, nif_emp, iban_emp, telefone_emp, email_emp, website_emp, logo_bytes),
                    )
                    conn.commit()
                    conn.close()
                    obter_config_empresa.clear()
                    st.success("Dados da empresa guardados!")

# Footer
st.markdown("---")
st.markdown("""
    <div style="text-align: center; color: #666; font-size: 12px;">
        Sistema myERP v4.0 | Desenvolvido por Ricardo Nogueira | © 2025
    </div>
""", unsafe_allow_html=True)


