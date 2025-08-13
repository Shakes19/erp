import streamlit as st
from sqlalchemy import text
from db import SessionLocal

st.set_page_config(page_title="Preencher Cotações", layout="centered")
st.title("📥 Preencher Cotações Recebidas")


def obter_conexao():
    return SessionLocal()


# Obter todos os processos com número + id
def listar_processos():
    session = obter_conexao()
    try:
        result = session.execute(text("SELECT id, numero FROM processo ORDER BY data_abertura DESC"))
        return result.fetchall()
    finally:
        session.close()


# Obter fornecedores
def listar_fornecedores():
    session = obter_conexao()
    try:
        result = session.execute(text("SELECT id, nome FROM fornecedor"))
        return result.fetchall()
    finally:
        session.close()


# Obter artigos de um RFQ
def obter_artigos(rfq_id):
    session = obter_conexao()
    try:
        result = session.execute(
            text("SELECT id, descricao, quantidade, unidade FROM artigo WHERE rfq_id = :rfq_id"),
            {"rfq_id": rfq_id},
        )
        return result.fetchall()
    finally:
        session.close()


# Obter o id do RFQ com base no processo e fornecedor
def obter_rfq_id(processo_id, fornecedor_id):
    session = obter_conexao()
    try:
        result = session.execute(
            text("SELECT id FROM rfq WHERE processo_id = :processo_id AND fornecedor_id = :fornecedor_id"),
            {"processo_id": processo_id, "fornecedor_id": fornecedor_id},
        ).fetchone()
        return result[0] if result else None
    finally:
        session.close()


# Guardar resposta
def guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega):
    session = obter_conexao()
    try:
        session.execute(
            text(
                """
        INSERT INTO resposta_fornecedor (fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega)
        VALUES (:fornecedor_id, :rfq_id, :artigo_id, :custo, :prazo_entrega)
        """
            ),
            {
                "fornecedor_id": fornecedor_id,
                "rfq_id": rfq_id,
                "artigo_id": artigo_id,
                "custo": custo,
                "prazo_entrega": prazo_entrega,
            },
        )
        session.commit()
    finally:
        session.close()


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
            custo = st.number_input(
                f"Custo unitário (€) para '{descricao}'", min_value=0.0, format="%.2f", key=f"custo_{artigo_id}"
            )
            prazo = st.number_input(
                f"Prazo entrega (semanas) para '{descricao}'", min_value=0, format="%d", key=f"prazo_{artigo_id}"
            )
            respostas.append((artigo_id, custo, prazo))

        if st.button("💾 Guardar Respostas"):
            for artigo_id, custo, prazo in respostas:
                guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo)
            st.success("Respostas guardadas com sucesso!")

    else:
        st.warning("Este fornecedor ainda não tem um RFQ associado a este processo.")
else:
    st.info("Adiciona primeiro processos e fornecedores no sistema.")
