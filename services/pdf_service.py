import json
import os
import tempfile
from email import policy
from email.parser import BytesParser

import streamlit as st
from fpdf import FPDF

from db import get_connection as obter_conexao
import extract_msg

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


def converter_eml_para_pdf(eml_bytes: bytes) -> bytes:
    """Convert raw EML bytes to PDF bytes."""
    message = BytesParser(policy=policy.default).parsebytes(eml_bytes)
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_font("Arial", size=12)

    header_lines = [
        f"From: {message.get('From', '')}",
        f"To: {message.get('To', '')}",
        f"Subject: {message.get('Subject', '')}",
        f"Date: {message.get('Date', '')}",
        "",
    ]
    for line in header_lines:
        pdf.multi_cell(0, 10, line)

    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_content_disposition():
                body += part.get_content()
    else:
        body = message.get_content()
    pdf.multi_cell(0, 10, body.strip())
    return pdf.output(dest="S").encode("latin-1")


def converter_msg_para_pdf(msg_bytes: bytes) -> bytes:
    """Convert Outlook ``.msg`` files to PDF bytes."""
    with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
        tmp.write(msg_bytes)
        tmp_path = tmp.name
    try:
        message = extract_msg.Message(tmp_path)
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Arial", size=12)

        header_lines = [
            f"From: {message.sender or ''}",
            f"To: {message.to or ''}",
            f"Subject: {message.subject or ''}",
            f"Date: {message.date or ''}",
            "",
        ]
        for line in header_lines:
            pdf.multi_cell(0, 10, line)

        body = message.body or ""
        pdf.multi_cell(0, 10, body.strip())
        return pdf.output(dest="S").encode("latin-1")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def processar_upload_pdf(uploaded_file):
    """Return a list of ``(filename, bytes)`` tuples for uploaded files.

    Supports PDF, EML and MSG files. EML/MSG uploads are converted to PDF
    bytes to maintain consistent downstream processing.
    """

    if not uploaded_file:
        return []

    if not isinstance(uploaded_file, list):
        uploaded_files = [uploaded_file]
    else:
        uploaded_files = uploaded_file

    processed = []
    for item in uploaded_files:
        nome = item.name
        conteudo = item.getvalue()
        lower_nome = nome.lower()
        if lower_nome.endswith(".eml"):
            nome = os.path.splitext(nome)[0] + ".pdf"
            conteudo = converter_eml_para_pdf(conteudo)
        elif lower_nome.endswith(".msg"):
            nome = os.path.splitext(nome)[0] + ".pdf"
            conteudo = converter_msg_para_pdf(conteudo)
        processed.append((nome, conteudo))

    return processed
