import streamlit as st
import sqlite3

# Caminho único da base de dados
DB_PATH = "cotacoes.db"

st.set_page_config(page_title="Preencher Cotações", layout="centered")
st.title("📥 Preencher Cotações Recebidas")

def obter_conexao():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# Obter todos os processos com número + id
def listar_processos():
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT id, numero FROM processo ORDER BY data_abertura DESC")
    processos = c.fetchall()
    conn.close()
    return processos

# Obter fornecedores
def listar_fornecedores():
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT id, nome FROM fornecedor")
    fornecedores = c.fetchall()
    conn.close()
    return fornecedores

# Obter artigos de um RFQ
def obter_artigos(rfq_id):
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT id, descricao, quantidade, unidade FROM artigo WHERE rfq_id = ?", (rfq_id,))
    artigos = c.fetchall()
    conn.close()
    return artigos

# Obter o id do RFQ com base no processo e fornecedor
def obter_rfq_id(processo_id, fornecedor_id):
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("SELECT id FROM rfq WHERE processo_id = ? AND fornecedor_id = ?", (processo_id, fornecedor_id))
    resultado = c.fetchone()
    conn.close()
    return resultado[0] if resultado else None

# Guardar resposta
def guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega):
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("""
        INSERT INTO resposta_fornecedor (fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega)
        VALUES (?, ?, ?, ?, ?)
    """, (fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega))
    conn.commit()
    conn.close()

# Seleção de processo e fornecedor
st.subheader("Selecionar Pedido de Cotação")
processos = listar_processos()
fornecedores = listar_fornecedores()

if processos and fornecedores:
    processo_nome = st.selectbox("Processo:", [f"{p[1]} (ID {p[0]})" for p in processos])
    fornecedor_nome = st.selectbox("Fornecedor:", [f"{f[1]} (ID {f[0]})" for f in fornecedores])

    processo_id = int(processo_nome.split("ID ")[-1].replace(")", ""))
    fornecedor_id = int(fornecedor_nome.split("ID ")[-1].replace(")", ""))

    rfq_id = obter_rfq_id(processo_id, fornecedor_id)

    if rfq_id:
        st.markdown("---")
        st.subheader("Artigos e Respostas do Fornecedor")

        artigos = obter_artigos(rfq_id)

        respostas = []
        for artigo in artigos:
            artigo_id, descricao, quantidade, unidade = artigo
            st.markdown(f"**{descricao}** - {quantidade} {unidade}")
            custo = st.number_input(f"Custo unitário (€) para '{descricao}'", min_value=0.0, format="%.2f", key=f"custo_{artigo_id}")
            prazo = st.number_input(f"Prazo entrega (semanas) para '{descricao}'", min_value=0, format="%d", key=f"prazo_{artigo_id}")
            respostas.append((artigo_id, custo, prazo))

        if st.button("💾 Guardar Respostas"):
            for artigo_id, custo, prazo in respostas:
                guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo)
            st.success("Respostas guardadas com sucesso!")

    else:
        st.warning("Este fornecedor ainda não tem um RFQ associado a este processo.")
else:␊
    st.info("Adiciona primeiro processos e fornecedores no sistema."))
