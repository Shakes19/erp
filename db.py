"""Database utilities for process management.

This module previously relied on a remote PostgreSQL connection defined in
Streamlit ``st.secrets``.  In the testing environment that connection is not
available, which caused ``criar_processo`` to fail and left RFQs without an
associated process.  To make the application self‑contained, we now use a local
SQLite database (the same one used by the rest of the application).
"""

import os
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# Path of the SQLite database used by the main application.
DB_PATH = os.environ.get("DB_PATH", "cotacoes.db")

# SQLAlchemy engine/session factory targeting the local SQLite DB.  ``check_same_thread``
# is disabled so the connection can be shared across different threads that
# Streamlit might use.
engine = create_engine(
    f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def criar_processo(descricao: str = ""):
    """Cria um novo processo com número sequencial anual."""
    ano = datetime.now().year
    prefixo = f"QT{ano}-"
    session = SessionLocal()
    try:
        # SQLite uses ``SUBSTR`` instead of ``SUBSTRING``
        result = session.execute(
            text(
                "SELECT MAX(CAST(SUBSTR(numero, 8) AS INTEGER)) FROM processo WHERE numero LIKE :prefixo"
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
