"""Funções auxiliares para envio de emails.

O módulo centraliza a obtenção das configurações SMTP guardadas na base de
dados para evitar duplicação de lógica noutros pontos da aplicação.
"""

from __future__ import annotations

import smtplib
import sqlite3
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import streamlit as st

from db import get_connection


DEFAULT_SMTP_CONFIG = {
    "server": "smtp-mail.outlook.com",
    "port": 587,
}


@st.cache_data(show_spinner=False, ttl=60)
def get_system_email_config() -> dict:
    """Fetch SMTP settings stored under "Configurações de Sistema > Email".

    Legacy bases de dados podem não possuir a coluna ``ativo`` ou até a própria
    tabela, por isso são tratadas todas as exceções e devolvida a configuração
    por omissão quando necessário.
    """

    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT smtp_server, smtp_port FROM configuracao_email "
                "WHERE ativo = TRUE LIMIT 1"
            )
        except sqlite3.OperationalError:
            cursor.execute(
                "SELECT smtp_server, smtp_port FROM configuracao_email LIMIT 1"
            )
        row = cursor.fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()

    if row and row[0]:
        server = row[0]
        try:
            port = int(row[1]) if row[1] is not None else DEFAULT_SMTP_CONFIG["port"]
        except (TypeError, ValueError):
            port = DEFAULT_SMTP_CONFIG["port"]
        return {"server": server, "port": port}

    return DEFAULT_SMTP_CONFIG.copy()


@st.cache_resource(ttl=60)
def get_smtp_connection(server: str, port: int, user: str, password: str):
    """Return a cached SMTP connection."""

    conn = smtplib.SMTP(server, port)
    conn.starttls()
    conn.login(user, password)
    return conn


def clear_email_cache() -> None:
    """Limpa as caches das configurações e ligações SMTP."""

    try:
        get_system_email_config.clear()
    except AttributeError:
        pass

    try:
        get_smtp_connection.clear()
    except AttributeError:
        pass


def send_email(
    destino: str,
    assunto: str,
    corpo: str,
    *,
    pdf_bytes: Optional[bytes] = None,
    pdf_filename: str = "anexo.pdf",
    smtp_server: Optional[str] = None,
    smtp_port: Optional[int] = None,
    email_user: str = "",
    email_password: str = "",
) -> None:
    """Enviar email reutilizando a ligação SMTP em cache."""

    config = get_system_email_config()
    server_host = smtp_server or config["server"]
    server_port = smtp_port or config["port"]

    server = get_smtp_connection(server_host, server_port, email_user, email_password)
    msg = MIMEMultipart()
    msg["From"] = email_user
    msg["To"] = destino
    msg["Subject"] = assunto
    msg.attach(MIMEText(corpo, "plain"))
    if pdf_bytes:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{pdf_filename}"')
        msg.attach(part)
    server.send_message(msg)

