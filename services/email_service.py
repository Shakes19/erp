import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional

import streamlit as st

@st.cache_resource(ttl=60)
def get_smtp_connection(server: str, port: int, user: str, password: str):
    """Return a cached SMTP connection."""
    conn = smtplib.SMTP(server, port)
    conn.starttls()
    conn.login(user, password)
    return conn

def send_email(destino: str, assunto: str, corpo: str, *, pdf_bytes: Optional[bytes] = None,
               pdf_filename: str = "anexo.pdf", smtp_server: str = "", smtp_port: int = 0,
               email_user: str = "", email_password: str = "") -> None:
    """Enviar email reutilizando a ligação SMTP em cache."""
    server = get_smtp_connection(smtp_server, smtp_port, email_user, email_password)
    msg = MIMEMultipart()
    msg['From'] = email_user
    msg['To'] = destino
    msg['Subject'] = assunto
    msg.attach(MIMEText(corpo, 'plain'))
    if pdf_bytes:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{pdf_filename}"')
        msg.attach(part)
    server.send_message(msg)
