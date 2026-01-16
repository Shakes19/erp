import os
from email import policy
from email.message import Message
from email.parser import BytesParser
from html import escape

import pdfkit
import streamlit as st

from db import get_connection

WKHTMLTOPDF_PATH = os.environ.get("WKHTMLTOPDF_PATH", "/usr/local/bin/wkhtmltopdf")
try:
    PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
except (OSError, IOError):
    PDFKIT_CONFIG = None


def _extrair_corpo_html(message: Message) -> str:
    html_body = None
    text_body = None

    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            conteudo = part.get_content()
            if content_type == "text/html" and html_body is None:
                html_body = conteudo
            elif content_type == "text/plain" and text_body is None:
                text_body = conteudo
    else:
        content_type = message.get_content_type()
        conteudo = message.get_content()
        if content_type == "text/html":
            html_body = conteudo
        else:
            text_body = conteudo

    if html_body:
        return html_body

    return f"<pre>{escape(text_body or '')}</pre>"


def _montar_html_email(message: Message) -> tuple[str, str]:
    remetente = message.get("From", "")
    assunto = message.get("Subject", "")
    data = message.get("Date", "")
    corpo_html = _extrair_corpo_html(message)

    header_html = f"""
    <div style="border-bottom: 1px solid #ccc; padding-bottom: 8px; margin-bottom: 12px;">
        <strong>Assunto:</strong> {escape(assunto)}<br>
        <strong>De:</strong> {escape(remetente)}<br>
        <strong>Data:</strong> {escape(data)}
    </div>
    """

    html_final = f"""
    <html>
        <head>
            <meta charset="utf-8">
        </head>
        <body>
            {header_html}
            {corpo_html}
        </body>
    </html>
    """
    return assunto, html_final


def _converter_html_para_pdf(html: str) -> bytes:
    if PDFKIT_CONFIG:
        return pdfkit.from_string(html, False, configuration=PDFKIT_CONFIG)
    return pdfkit.from_string(html, False)


def _salvar_documento_pdf(filename_original: str, assunto: str, pdf_bytes: bytes) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO documentos (filename_original, assunto, pdf_blob)
            VALUES (?, ?, ?)
            """,
            (filename_original, assunto, pdf_bytes),
        )
        conn.commit()
    finally:
        conn.close()


def renderizar_pagina_importacao() -> None:
    st.title("📥 Arquivar e-mails antigos")
    st.markdown(
        "Carregue um ficheiro `.eml` para converter automaticamente em PDF e guardar na base de dados."
    )

    uploaded_file = st.file_uploader(
        "Arraste ou selecione um ficheiro .eml",
        type=["eml"],
        key="email_eml_uploader",
    )

    if st.button("Processar e Arquivar", type="primary"):
        if not uploaded_file:
            st.warning("Selecione um ficheiro .eml para continuar.")
            return

        with st.spinner("A processar o e-mail e a gerar o PDF..."):
            try:
                eml_bytes = uploaded_file.getvalue()
                message = BytesParser(policy=policy.default).parsebytes(eml_bytes)
                assunto, html_final = _montar_html_email(message)
                pdf_bytes = _converter_html_para_pdf(html_final)
                _salvar_documento_pdf(uploaded_file.name, assunto, pdf_bytes)
                st.success("E-mail arquivado com sucesso.")
            except Exception as exc:  # noqa: BLE001 - feedback direto ao utilizador
                st.error(f"Erro ao arquivar e-mail: {exc}")
