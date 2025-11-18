"""Funções auxiliares para envio de emails.

O módulo centraliza a obtenção das configurações SMTP guardadas na base de
dados para evitar duplicação de lógica noutros pontos da aplicação.
"""

from __future__ import annotations

import base64
import json
import smtplib
import sqlite3
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from mimetypes import guess_type

import requests

import streamlit as st

from db import get_connection


DEFAULT_SMTP_CONFIG = {
    "server": "smtp-mail.outlook.com",
    "port": 587,
    "use_tls": True,
    "use_ssl": False,
    "use_graph_api": False,
    "graph_tenant_id": "",
    "graph_client_id": "",
    "graph_client_secret": "",
    "graph_sender": "",
}

_GRAPH_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}

EMAIL_LAYOUT_FILE = Path("email_layout.json")

DEFAULT_EMAIL_LAYOUT = {
    "cotacao_cliente": {
        "subject": "Quotation {numero_cotacao}{referencia_cliente_sufixo}",
        "body": (
            "Dear {nome_cliente},\n\n"
            "Please find attached our offer No {numero_cotacao}.\n\n"
            "{observacoes_bloco}"
            "We remain at your disposal for any further clarification.\n\n"
            "Best regards,\n"
            "{nome_utilizador}"
        ),
    },
    "pedido_fornecedor": {
        "subject": "Request for Quotation – {referencia_interna}",
        "body": (
            "Request for Quotation – {referencia_interna}\n\n"
            "Dear {fornecedor_nome} Team,\n\n"
            "Please find attached our Request for Quotation (RFQ) for internal process {processo_texto} "
            "(Reference: {referencia_texto}).\n\n"
            "Kindly provide us with the following details:\n"
            "- Unit price\n"
            "- Delivery time\n"
            "- HS Code\n"
            "- Country of origin\n"
            "- Weight\n\n"
            "{detalhes_extra_bloco}"
            "We look forward to receiving your quotation.\n"
            "Thank you in advance for your prompt response.\n\n"
            "{nome_utilizador}"
        ),
    },
}


def _load_email_layout_file() -> dict:
    if not EMAIL_LAYOUT_FILE.exists():
        return {}
    try:
        with EMAIL_LAYOUT_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@st.cache_data(show_spinner=False)
def load_email_layout(tipo: str) -> dict[str, str]:
    """Load the layout configuration for email ``tipo`` with defaults."""

    defaults = DEFAULT_EMAIL_LAYOUT.get(tipo, {}).copy()
    stored = _load_email_layout_file().get(tipo, {})
    if isinstance(stored, dict):
        defaults.update({k: v for k, v in stored.items() if isinstance(v, str)})
    return defaults


def save_email_layout(tipo: str, config: dict[str, str]) -> None:
    """Persist updated email layout configuration for ``tipo``."""

    data = _load_email_layout_file()
    data[tipo] = {
        "subject": config.get("subject", DEFAULT_EMAIL_LAYOUT.get(tipo, {}).get("subject", "")),
        "body": config.get("body", DEFAULT_EMAIL_LAYOUT.get(tipo, {}).get("body", "")),
    }
    with EMAIL_LAYOUT_FILE.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    try:
        load_email_layout.clear()
    except AttributeError:
        pass


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
        base_query = (
            "SELECT smtp_server, smtp_port, use_tls, use_ssl, use_graph_api, "
            "graph_tenant_id, graph_client_id, graph_client_secret, graph_sender "
            "FROM configuracao_email"
        )
        try:
            cursor.execute(base_query + " WHERE ativo = TRUE LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute(base_query + " LIMIT 1")
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
        use_graph = DEFAULT_SMTP_CONFIG["use_graph_api"]
        graph_tenant_id = DEFAULT_SMTP_CONFIG["graph_tenant_id"]
        graph_client_id = DEFAULT_SMTP_CONFIG["graph_client_id"]
        graph_client_secret = DEFAULT_SMTP_CONFIG["graph_client_secret"]
        graph_sender = DEFAULT_SMTP_CONFIG["graph_sender"]
        if len(row) >= 3 and row[2] is not None:
            use_tls = bool(row[2])
        if len(row) >= 4 and row[3] is not None:
            use_ssl = bool(row[3])
        if len(row) >= 5 and row[4] is not None:
            use_graph = bool(row[4])
        if len(row) >= 6 and row[5] is not None:
            graph_tenant_id = row[5]
        if len(row) >= 7 and row[6] is not None:
            graph_client_id = row[6]
        if len(row) >= 8 and row[7] is not None:
            graph_client_secret = row[7]
        if len(row) >= 9 and row[8] is not None:
            graph_sender = row[8]
        return {
            "server": server,
            "port": port,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
            "use_graph_api": use_graph,
            "graph_tenant_id": graph_tenant_id or "",
            "graph_client_id": graph_client_id or "",
            "graph_client_secret": graph_client_secret or "",
            "graph_sender": graph_sender or "",
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

    _GRAPH_TOKEN_CACHE.clear()


def _get_graph_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    cache_key = (tenant_id, client_id)
    cached = _GRAPH_TOKEN_CACHE.get(cache_key)
    now = time.time()
    if cached and cached[1] > now:
        return cached[0]

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    response = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Falha ao obter token do Microsoft Graph: {response.status_code} - {response.text}"
        )
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Resposta inesperada do Microsoft Graph ao pedir token.")
    expires_in = int(payload.get("expires_in", 3600))
    _GRAPH_TOKEN_CACHE[cache_key] = (token, now + max(expires_in - 60, 60))
    return token


def _send_email_via_graph(
    *,
    destino: str,
    assunto: str,
    corpo: str,
    config: dict,
    email_user: str,
    attachments: list[tuple[str, bytes, Optional[str]]],
) -> None:
    tenant_id = (config.get("graph_tenant_id") or "").strip()
    client_id = (config.get("graph_client_id") or "").strip()
    client_secret = (config.get("graph_client_secret") or "").strip()
    sender = (config.get("graph_sender") or email_user or "").strip()

    missing_fields = [
        label
        for label, value in {
            "Tenant ID": tenant_id,
            "Client ID": client_id,
            "Client secret": client_secret,
            "Remetente": sender,
        }.items()
        if not value
    ]
    if missing_fields:
        raise RuntimeError(
            "Configuração Microsoft Graph incompleta: " + ", ".join(missing_fields)
        )

    token = _get_graph_access_token(tenant_id, client_id, client_secret)

    graph_attachments = []
    for nome_ficheiro, dados, mime in attachments:
        mime_type = mime or guess_type(nome_ficheiro)[0] or "application/octet-stream"
        graph_attachments.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": nome_ficheiro,
                "contentType": mime_type,
                "contentBytes": base64.b64encode(dados).decode("ascii"),
            }
        )

    message = {
        "subject": assunto,
        "body": {"contentType": "Text", "content": corpo},
        "toRecipients": [
            {
                "emailAddress": {
                    "address": destino,
                }
            }
        ],
    }
    if graph_attachments:
        message["attachments"] = graph_attachments

    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message, "saveToSentItems": True},
        timeout=15,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Erro ao enviar email via Microsoft Graph: {response.status_code} - {response.text}"
        )


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
    attachments: Optional[list[tuple[str, bytes, Optional[str]]]] = None,
) -> None:
    """Enviar email reutilizando a ligação SMTP em cache."""

    config = get_system_email_config()
    server_host = smtp_server or config["server"]
    server_port = smtp_port or config["port"]
    tls_flag = config.get("use_tls", True) if use_tls is None else use_tls
    ssl_flag = config.get("use_ssl", False) if use_ssl is None else use_ssl

    anexos_para_enviar: list[tuple[str, bytes, Optional[str]]] = []
    if pdf_bytes:
        anexos_para_enviar.append((pdf_filename, pdf_bytes, "application/pdf"))
    if attachments:
        anexos_para_enviar.extend(attachments)

    if config.get("use_graph_api"):
        _send_email_via_graph(
            destino=destino,
            assunto=assunto,
            corpo=corpo,
            config=config,
            email_user=email_user,
            attachments=anexos_para_enviar,
        )
        return

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

    for nome_ficheiro, dados, mime in anexos_para_enviar:
        tipo_mime = mime or guess_type(nome_ficheiro)[0] or "application/octet-stream"
        try:
            tipo_principal, tipo_secundario = tipo_mime.split("/", 1)
        except ValueError:
            tipo_principal, tipo_secundario = "application", "octet-stream"
        part = MIMEBase(tipo_principal, tipo_secundario)
        part.set_payload(dados)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", f'attachment; filename="{nome_ficheiro}"'
        )
        msg.attach(part)
    server.send_message(msg)

