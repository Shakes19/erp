import streamlit as st
from sqlalchemy import text
from contextlib import contextmanager

from db import SessionLocal

st.set_page_config(page_title="Preencher Cotações", layout="centered")
st.title("📥 Preencher Cotações Recebidas")


@contextmanager
def obter_sessao():
    """Fornece uma sessão SQLAlchemy garantindo o fecho da ligação."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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

    with obter_sessao() as session:
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


# Obter fornecedores
def listar_fornecedores():
    with obter_sessao() as session:
        result = session.execute(text("SELECT id, nome FROM fornecedor"))
        return result.fetchall()


# Obter artigos de um RFQ
def obter_artigos(rfq_id):
    with obter_sessao() as session:
        result = session.execute(
            text(
                """
                SELECT a.id,
                       a.descricao,
                       a.quantidade,
                       COALESCE(u.nome, '') AS unidade
                  FROM artigo a
                  LEFT JOIN unidade u ON a.unidade_id = u.id
                 WHERE a.rfq_id = :rfq_id
                """
            ),
            {"rfq_id": rfq_id},
        )
        return result.fetchall()


# Obter o id do RFQ com base no processo e fornecedor
def obter_rfq_id(processo_id, fornecedor_id):
    with obter_sessao() as session:
        result = session.execute(
            text("SELECT id FROM rfq WHERE processo_id = :processo_id AND fornecedor_id = :fornecedor_id"),
            {"processo_id": processo_id, "fornecedor_id": fornecedor_id},
        ).fetchone()
        return result[0] if result else None


# Guardar resposta
def guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega):
    with obter_sessao() as session:
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


# Seleção de processo e fornecedor
st.subheader("Selecionar Pedido de Cotação")
PAGE_SIZE = 10

if "processos_page" not in st.session_state:
    st.session_state.processos_page = 0

processos, total_processos = listar_processos(
    st.session_state.processos_page, PAGE_SIZE
)
total_paginas = max(1, (total_processos + PAGE_SIZE - 1) // PAGE_SIZE)

# Garantir que a página atual está dentro dos limites válidos
if st.session_state.processos_page > total_paginas - 1:
    st.session_state.processos_page = max(0, total_paginas - 1)
    processos, total_processos = listar_processos(
        st.session_state.processos_page, PAGE_SIZE
    )

fornecedores = listar_fornecedores()

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

# Controles de paginação no fundo da página
st.markdown("---")
st.write(f"Página {st.session_state.processos_page + 1} de {total_paginas}")
nav_prev, nav_next = st.columns(2)
if nav_prev.button("⬅️ Anterior", disabled=st.session_state.processos_page == 0):
    st.session_state.processos_page -= 1
    st.rerun()
if nav_next.button(
    "Próximo ➡️",
    disabled=st.session_state.processos_page >= total_paginas - 1,
):
    st.session_state.processos_page += 1
    st.rerun()
