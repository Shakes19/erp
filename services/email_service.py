"""Funções auxiliares para envio de emails.

O módulo centraliza a obtenção das configurações SMTP guardadas na base de
dados para evitar duplicação de lógica noutros pontos da aplicação.
"""

from __future__ import annotations

import base64
import json
import os
import smtplib
import sqlite3
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional
from mimetypes import guess_type

import msal
import requests
import streamlit as st

from db import get_connection


# Configuração SMTP por omissão para garantir um fallback funcional quando a
# base de dados ainda não possui valores guardados.
DEFAULT_SMTP_CONFIG = {
    "server": "smtp.office365.com",
    "port": 587,
    "use_tls": True,
    "use_ssl": False,
}

EMAIL_LAYOUT_FILE = Path("email_layout.json")
GRAPH_CONFIG_FILE = Path("graph_config.json")

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


def _load_graph_config_file() -> dict:
    if not GRAPH_CONFIG_FILE.exists():
        return {}

    try:
        with GRAPH_CONFIG_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_graph_config() -> dict:
    """Return the stored Microsoft Graph OAuth2 configuration."""

    data = _load_graph_config_file()
    return {
        "tenant_id": str(data.get("tenant_id") or "").strip(),
        "client_id": str(data.get("client_id") or "").strip(),
        "client_secret": str(data.get("client_secret") or "").strip(),
        "sender": str(data.get("sender") or "").strip(),
    }


def save_graph_config(config: dict) -> None:
    """Persist Microsoft Graph OAuth2 configuration to disk."""

    payload = {
        key: str(config.get(key) or "").strip()
        for key in ("tenant_id", "client_id", "client_secret", "sender")
    }

    cleaned = {k: v for k, v in payload.items() if v}

    if cleaned:
        with GRAPH_CONFIG_FILE.open("w", encoding="utf-8") as handle:
            json.dump(cleaned, handle, ensure_ascii=False, indent=2)
    else:
        GRAPH_CONFIG_FILE.unlink(missing_ok=True)

    for env_key, value in (
        ("M365_TENANT_ID", payload.get("tenant_id", "")),
        ("M365_CLIENT_ID", payload.get("client_id", "")),
        ("M365_CLIENT_SECRET", payload.get("client_secret", "")),
        ("M365_SENDER", payload.get("sender", "")),
    ):
        if value:
            os.environ[env_key] = value
        elif env_key in os.environ:
            del os.environ[env_key]

    try:
        load_graph_config.clear()
    except AttributeError:
        pass


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


def _graph_settings(sender_hint: str | None = None) -> dict | None:
    stored_config = load_graph_config()
    tenant_id = (os.getenv("M365_TENANT_ID") or stored_config.get("tenant_id") or "").strip()
    client_id = (os.getenv("M365_CLIENT_ID") or stored_config.get("client_id") or "").strip()
    client_secret = (
        os.getenv("M365_CLIENT_SECRET")
        or stored_config.get("client_secret")
        or ""
    ).strip()
    sender = (
        os.getenv("M365_SENDER")
        or stored_config.get("sender")
        or sender_hint
        or ""
    ).strip()

    if all([tenant_id, client_id, client_secret, sender]):
        return {
            "tenant_id": tenant_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "sender": sender,
        }
    return None


def has_graph_oauth_config(sender_hint: str | None = None) -> bool:
    """Indica se existem variáveis de ambiente suficientes para OAuth2 (Graph)."""

    return _graph_settings(sender_hint) is not None


@st.cache_data(show_spinner=False, ttl=3300)
def _get_graph_access_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Obter token de acesso para Microsoft Graph (app-only)."""

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    token = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in token:
        raise RuntimeError(
            f"Falha ao obter token OAuth2: {token.get('error_description') or token}"
        )
    return str(token["access_token"])


def _build_graph_attachment(nome_ficheiro: str, dados: bytes, mime: str | None) -> dict:
    content_type = mime or guess_type(nome_ficheiro)[0] or "application/octet-stream"
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": nome_ficheiro,
        "contentType": content_type,
        "contentBytes": base64.b64encode(dados).decode("ascii"),
    }


def _send_email_via_graph(
    destino: str,
    assunto: str,
    corpo: str,
    sender_email: str,
    graph_cfg: dict,
    attachments: list[tuple[str, bytes, Optional[str]]],
) -> None:
    access_token = _get_graph_access_token(
        graph_cfg["tenant_id"], graph_cfg["client_id"], graph_cfg["client_secret"]
    )
    message = {
        "message": {
            "subject": assunto,
            "body": {"contentType": "Text", "content": corpo or ""},
            "from": {"emailAddress": {"address": sender_email}},
            "toRecipients": [{"emailAddress": {"address": destino}}],
            "attachments": [
                _build_graph_attachment(nome, dados, mime)
                for nome, dados, mime in attachments
            ],
        },
        "saveToSentItems": False,
    }

    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=message,
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            error_detail = response.json()
        except ValueError:
            error_detail = response.text
        raise RuntimeError(
            f"Envio via Microsoft Graph falhou ({response.status_code}): {error_detail}"
        )


@st.cache_data(show_spinner=False, ttl=60)
def get_system_email_config() -> dict:
    """Fetch SMTP settings stored under "Configurações de Sistema > Email".

    Se a tabela/colunas estiverem ausentes (bases legacy), devolve-se a
    configuração por defeito. Caso contrário, é usado o último registo ativo ou
    o mais recente disponível.
    """

    config = DEFAULT_SMTP_CONFIG.copy()
    conn: sqlite3.Connection | None = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT smtp_server, smtp_port, use_tls, use_ssl "
                "FROM configuracao_email WHERE ativo = TRUE ORDER BY id DESC LIMIT 1"
            )
        except sqlite3.OperationalError:
            # Bases de dados antigas podem não ter a coluna "ativo".
            cursor.execute(
                "SELECT smtp_server, smtp_port, use_tls, use_ssl "
                "FROM configuracao_email ORDER BY id DESC LIMIT 1"
            )

        row = cursor.fetchone()
    except sqlite3.Error:
        row = None
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    if row:
        server, port, use_tls_val, use_ssl_val = row

        if server:
            config["server"] = server
        if port:
            config["port"] = int(port)
        if use_tls_val is not None:
            config["use_tls"] = bool(use_tls_val)
        if use_ssl_val is not None:
            config["use_ssl"] = bool(use_ssl_val)

    return config


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
    attachments: Optional[list[tuple[str, bytes, Optional[str]]]] = None,
) -> None:
    """Enviar email reutilizando a ligação SMTP em cache."""

    def _coerce_bool(value: object, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "t", "yes", "sim", "on"}:
                return True
            if normalized in {"0", "false", "f", "no", "nao", "off"}:
                return False
        return bool(value)

    email_user = (email_user or "").strip()
    email_password = (email_password or "").strip()
    destino = (destino or "").strip()

    anexos_para_enviar: list[tuple[str, bytes, Optional[str]]] = []
    if pdf_bytes:
        anexos_para_enviar.append((pdf_filename, pdf_bytes, "application/pdf"))
    if attachments:
        anexos_para_enviar.extend(attachments)

    graph_cfg = _graph_settings(email_user)
    if graph_cfg:
        sender_email = graph_cfg["sender"]
        _send_email_via_graph(
            destino,
            assunto,
            corpo,
            sender_email,
            graph_cfg,
            anexos_para_enviar,
        )
        return

    if not email_user or not email_password:
        raise RuntimeError(
            "O email de origem e a palavra-passe são obrigatórios (sem espaços)."
        )

    config = get_system_email_config()
    server_host = (smtp_server or config["server"] or "").strip()
    server_port = smtp_port or config["port"]
    tls_flag = _coerce_bool(config.get("use_tls", True) if use_tls is None else use_tls, True)
    ssl_flag = _coerce_bool(config.get("use_ssl", False) if use_ssl is None else use_ssl, False)

    host_lower = server_host.lower()
    is_outlook = any(key in host_lower for key in ("outlook", "office365", "office"))

    # Normalizar protocolo de segurança para evitar combinações inválidas que a
    # Microsoft rejeita silenciosamente.
    if server_port == 587:
        ssl_flag = False
        tls_flag = True if use_tls is None else bool(tls_flag)
    elif server_port == 465:
        ssl_flag = True
        tls_flag = False

    if ssl_flag and tls_flag:
        # Priorizar SSL apenas quando o porto o exige; caso contrário manter TLS.
        if server_port == 465:
            tls_flag = False
        else:
            ssl_flag = False

    if is_outlook and server_port != 587:
        # Outlook/Office365 apenas aceita STARTTLS em 587; força-se o porto e o
        # modo corretos para evitar erros de autenticação enganadores.
        server_port = 587
        ssl_flag = False
        tls_flag = True

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
        hint = (
            " Confirme que está a usar o porto 587 com STARTTLS ou uma App Password."
            if is_outlook
            else ""
        )
        raise RuntimeError(
            "Autenticação no servidor SMTP falhou. Verifique o email, a palavra-passe ou utilize uma App Password." + hint
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
