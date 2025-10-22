import json
import os
import tempfile
from email import policy
from email.parser import BytesParser

import streamlit as st
from fpdf import FPDF

from db import fetch_one
import extract_msg


def ensure_latin1(value: str | int | float | None) -> str:
    """Return ``value`` coerced to a latin-1 safe string for ``fpdf``."""

    if value is None:
        text = ""
    else:
        text = str(value)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _safe_text(value: str | None) -> str:
    """Backward compatible wrapper retained for older imports."""

    return ensure_latin1(value)

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
    row = fetch_one(
        "SELECT nome, morada, nif, iban, banco, telefone, email, website, logo "
        "FROM configuracao_empresa ORDER BY id DESC LIMIT 1"
    )
    if row:
        return {
            "nome": row[0],
            "morada": row[1],
            "nif": row[2],
            "iban": row[3],
            "banco": row[4],
            "telefone": row[5],
            "email": row[6],
            "website": row[7],
            "logo": row[8],
        }
    return None


def obter_pdf_da_db(rfq_id, tipo_pdf="pedido"):
    """Retrieve stored PDF bytes from the database."""
    result = fetch_one(
        "SELECT pdf_data FROM pdf_storage WHERE rfq_id = ? AND tipo_pdf = ?",
        (str(rfq_id), tipo_pdf),
    )
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
        pdf.multi_cell(0, 10, ensure_latin1(line))

    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_content_disposition():
                body += part.get_content()
    else:
        body = message.get_content()
    pdf.multi_cell(0, 10, ensure_latin1(body.strip()))
    # ``fpdf`` produz saída em texto Latin-1. Alguns emails podem conter
    # caracteres fora desse intervalo (por exemplo, travessões “–”). Ao
    # codificar com ``errors='replace'`` garantimos que o PDF é gerado sem
    # levantar ``UnicodeEncodeError`` e os caracteres não suportados são
    # substituídos por um marcador visual.
    return pdf.output(dest="S").encode("latin-1", errors="replace")


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
            pdf.multi_cell(0, 10, ensure_latin1(line))

        body = message.body or ""
        pdf.multi_cell(0, 10, ensure_latin1(body.strip()))
        return pdf.output(dest="S").encode("latin-1", errors="replace")
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
