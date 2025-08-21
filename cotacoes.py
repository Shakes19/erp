import streamlit as st
from sqlalchemy import text
from db import SessionLocal

st.set_page_config(page_title="Preencher Cotações", layout="centered")
st.title("📥 Preencher Cotações Recebidas")


def obter_conexao():
    return SessionLocal()


# Obter todos os processos com número + id (paginado)
def listar_processos(page: int = 0, page_size: int = 10):
    """Devolve os processos paginados e o número total de entradas.

    Args:
        page: Número da página (0-indexed).
        page_size: Quantidade de processos por página.

    Returns:
        tuple[list[tuple], int]: Lista de processos para a página atual e o
        total de processos existentes.
    """

    session = obter_conexao()
    try:
        offset = page * page_size
        processos = session.execute(
            text(
                "SELECT id, numero FROM processo ORDER BY data_abertura DESC "
                "LIMIT :limit OFFSET :offset"
            ),
            {"limit": page_size, "offset": offset},
        ).fetchall()
        total = session.execute(text("SELECT COUNT(*) FROM processo")).scalar()
        return processos, total
    finally:
        session.close()


def contar_processos() -> int:
    """Devolve o número total de processos existentes."""
    session = obter_conexao()
    try:
        return session.execute(text("SELECT COUNT(*) FROM processo")).scalar()
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
PAGE_SIZE = 10

if "processos_page" not in st.session_state:
    st.session_state.processos_page = 0

total_processos = contar_processos()
total_paginas = max(1, (total_processos + PAGE_SIZE - 1) // PAGE_SIZE)

fornecedores = listar_fornecedores()

col1, col2 = st.columns(2)
if col1.button("⬅️ Anterior", disabled=st.session_state.processos_page == 0):
    st.session_state.processos_page -= 1
if col2.button(
    "Próximo ➡️",
    disabled=st.session_state.processos_page >= total_paginas - 1,
):
    st.session_state.processos_page += 1

processos, _ = listar_processos(
    st.session_state.processos_page, PAGE_SIZE
)

st.write(f"Página {st.session_state.processos_page + 1} de {total_paginas}")

if total_processos and fornecedores:
    if processos:
        processo_nome = st.selectbox(
            "Processo:", [f"{p[1]} (ID {p[0]})" for p in processos]
        )
    else:
        st.warning("Nenhum processo disponível nesta página.")
        processo_nome = None

    fornecedor_nome = st.selectbox(
        "Fornecedor:", [f"{f[1]} (ID {f[0]})" for f in fornecedores]
    )

    if processo_nome:
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
                    f"Custo unitário (€) para '{descricao}'",
                    min_value=0.0,
                    format="%.2f",
                    key=f"custo_{artigo_id}",
                )
                prazo = st.number_input(
                    f"Prazo entrega (semanas) para '{descricao}'",
                    min_value=0,
                    format="%d",
                    key=f"prazo_{artigo_id}",
                )
                respostas.append((artigo_id, custo, prazo))

            if st.button("💾 Guardar Respostas"):
                for artigo_id, custo, prazo in respostas:
                    guardar_resposta(
                        fornecedor_id, rfq_id, artigo_id, custo, prazo
                    )
                st.success("Respostas guardadas com sucesso!")
        else:
            st.warning("Este fornecedor ainda não tem um RFQ associado a este processo.")
else:
    st.info("Adiciona primeiro processos e fornecedores no sistema.")
