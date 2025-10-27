"""Database helper functions for the quotations workflow."""

from contextlib import contextmanager

from sqlalchemy import text

from db import SessionLocal


@contextmanager
def obter_sessao():
    """Provide a SQLAlchemy session ensuring proper cleanup."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def listar_processos(page: int = 0, page_size: int = 10):
    """Return paginated processes along with the total count."""

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


def contar_processos() -> int:
    """Return the total number of processes."""

    with obter_sessao() as session:
        return session.execute(text("SELECT COUNT(*) FROM processo")).scalar()


def listar_fornecedores():
    """Return the list of suppliers."""

    with obter_sessao() as session:
        result = session.execute(text("SELECT id, nome FROM fornecedor"))
        return result.fetchall()


def obter_artigos(rfq_id):
    """Return articles associated with an RFQ."""

    with obter_sessao() as session:
        result = session.execute(
            text(
                """
                SELECT a.id,
                       COALESCE(a.descricao, '') AS descricao,
                       COALESCE(ra.quantidade, 0) AS quantidade,
                       COALESCE(u.nome, '') AS unidade
                  FROM rfq_artigo ra
                  JOIN artigo a ON ra.artigo_id = a.id
                  LEFT JOIN unidade u ON a.unidade_id = u.id
                 WHERE ra.rfq_id = :rfq_id
                 ORDER BY COALESCE(ra.ordem, a.id)
                """
            ),
            {"rfq_id": rfq_id},
        )
        return result.fetchall()


def obter_rfq_id(processo_id, fornecedor_id):
    """Return the RFQ identifier for the given process and supplier."""

    with obter_sessao() as session:
        result = session.execute(
            text(
                "SELECT id FROM rfq WHERE processo_id = :processo_id "
                "AND fornecedor_id = :fornecedor_id"
            ),
            {"processo_id": processo_id, "fornecedor_id": fornecedor_id},
        ).fetchone()
        return result[0] if result else None


def guardar_resposta(fornecedor_id, rfq_id, artigo_id, custo, prazo_entrega):
    """Persist a supplier response for a given article."""

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
