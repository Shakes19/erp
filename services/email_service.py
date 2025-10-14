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
    "use_tls": True,
    "use_ssl": False,
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
                "SELECT smtp_server, smtp_port, use_tls, use_ssl FROM configuracao_email "
                "WHERE ativo = TRUE LIMIT 1"
            )
        except sqlite3.OperationalError:
            try:
                cursor.execute(
                    "SELECT smtp_server, smtp_port, use_tls, use_ssl FROM configuracao_email LIMIT 1"
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
        use_tls = DEFAULT_SMTP_CONFIG["use_tls"]
        use_ssl = DEFAULT_SMTP_CONFIG["use_ssl"]
        if len(row) >= 3 and row[2] is not None:
            use_tls = bool(row[2])
        if len(row) >= 4 and row[3] is not None:
            use_ssl = bool(row[3])
        return {
            "server": server,
            "port": port,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
        }

    return DEFAULT_SMTP_CONFIG.copy()


@st.cache_resource(ttl=60)
def get_smtp_connection(
    server: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool = True,
    use_ssl: bool = False,
):
    """Return a cached SMTP connection."""

    if use_ssl:
        conn = smtplib.SMTP_SSL(server, port)
    else:
        conn = smtplib.SMTP(server, port)
        conn.ehlo()
        if use_tls:
            conn.starttls()
            conn.ehlo()
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
    use_tls: Optional[bool] = None,
    use_ssl: Optional[bool] = None,
) -> None:
    """Enviar email reutilizando a ligação SMTP em cache."""

    config = get_system_email_config()
    server_host = smtp_server or config["server"]
    server_port = smtp_port or config["port"]
    tls_flag = config.get("use_tls", True) if use_tls is None else use_tls
    ssl_flag = config.get("use_ssl", False) if use_ssl is None else use_ssl

    try:
        server = get_smtp_connection(
            server_host,
            server_port,
            email_user,
            email_password,
            tls_flag,
            ssl_flag,
        )
    except smtplib.SMTPAuthenticationError as exc:
        clear_email_cache()
        raise RuntimeError(
            "Autenticação no servidor SMTP falhou. Verifique o email, a palavra-passe ou utilize uma App Password."
        ) from exc
    except smtplib.SMTPException:
        clear_email_cache()
        raise

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

