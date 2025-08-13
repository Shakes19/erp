import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from datetime import datetime

engine = create_engine(
    st.secrets["DATABASE_URL"],
    pool_size=5, max_overflow=5, pool_pre_ping=True, pool_recycle=1800
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def criar_processo(descricao: str = ""):
    """Cria um novo processo com número sequencial anual."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    session = SessionLocal()
    try:
        result = session.execute(
            text(
                "SELECT MAX(CAST(SUBSTRING(numero, 8) AS INTEGER)) FROM processo WHERE numero LIKE :prefixo"
            ),
            {"prefixo": f"{prefixo}%"},
        )
        max_seq = result.scalar()
        numero = f"{prefixo}{(max_seq or 0) + 1}"
        new_id = session.execute(
            text(
                "INSERT INTO processo (numero, descricao) VALUES (:numero, :descricao) RETURNING id"
            ),
            {"numero": numero, "descricao": descricao},
        ).scalar()
        session.commit()
        return new_id, numero
    finally:
        session.close()
