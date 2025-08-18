import json
import streamlit as st
from db import get_connection as obter_conexao

@st.cache_data(show_spinner=False)
def load_pdf_config(tipo):
    """Load PDF layout configuration from ``pdf_layout.json``."""
    try:
        with open('pdf_layout.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get(tipo, {})
    except Exception:
        return {}


def save_pdf_config(tipo, config):
    """Save PDF layout configuration to ``pdf_layout.json``."""
    try:
        with open('pdf_layout.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
    data[tipo] = config
    with open('pdf_layout.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    load_pdf_config.clear()


@st.cache_data(show_spinner=False)
def obter_config_empresa():
    """Fetch company configuration data for PDFs."""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT nome, morada, nif, iban, telefone, email, website, logo FROM configuracao_empresa ORDER BY id DESC LIMIT 1"
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "nome": row[0],
            "morada": row[1],
            "nif": row[2],
            "iban": row[3],
            "telefone": row[4],
            "email": row[5],
            "website": row[6],
            "logo": row[7],
        }
    return None


def obter_pdf_da_db(rfq_id, tipo_pdf="pedido"):
    """Retrieve stored PDF bytes from the database."""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf = ?",
        (str(rfq_id), tipo_pdf),
    )
    result = c.fetchone()
    conn.close()
    return result[0] if result else None
