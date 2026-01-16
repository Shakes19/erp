import json
import os
import tempfile
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

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

    text = text.replace("€", "\x80")

    try:
        return text.encode("latin-1", errors="strict").decode("latin-1")
    except UnicodeEncodeError:
        # ``fpdf`` só aceita caracteres latin-1. Convertemos caracteres
        # CP1252 (como travessões) para o intervalo latin-1, substituindo
        # o que ainda for incompatível.
        return text.encode("cp1252", errors="replace").decode("latin-1")


class _HtmlBodyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.image_cids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "img":
            attrs_map = dict(attrs)
            src = attrs_map.get("src") or ""
            if src.lower().startswith("cid:"):
                cid = src[4:].strip().strip("<>").lower()
                if cid:
                    self.image_cids.append(cid)

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(part.strip() for part in self.parts if part.strip())


def _extract_email_body_and_images(message) -> tuple[str, list[tuple[str, bytes]]]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    cid_to_image: dict[str, tuple[str, bytes]] = {}

    if message.is_multipart():
        for part in message.walk():
            content_disposition = part.get_content_disposition()
            content_type = part.get_content_type()
            if content_type == "text/plain" and not content_disposition:
                text_parts.append(part.get_content())
                continue
            if content_type == "text/html" and not content_disposition:
                html_parts.append(part.get_content())
                continue
            if content_type.startswith("image/"):
                cid = (part.get("Content-ID") or "").strip().strip("<>").lower()
                if not cid:
                    cid = (part.get("Content-Location") or "").strip().lower()
                if cid:
                    payload = part.get_content()
                    if isinstance(payload, str):
                        payload = payload.encode()
                    cid_to_image[cid] = (content_type, payload)
    else:
        text_parts.append(message.get_content())

    inline_images: list[tuple[str, bytes]] = []
    body = ""
    if html_parts:
        parser = _HtmlBodyParser()
        parser.feed("\n".join(html_parts))
        body = parser.get_text()
        for cid in parser.image_cids:
            image = cid_to_image.get(cid)
            if image:
                inline_images.append(image)
    if not body:
        body = "\n".join(text_parts).strip()
        if not body and html_parts:
            body = " ".join(html_parts).strip()
    return body, inline_images


def _append_inline_images(pdf: FPDF, inline_images: list[tuple[str, bytes]]) -> None:
    if not inline_images:
        return
    max_width = pdf.w - pdf.l_margin - pdf.r_margin
    temp_files: list[str] = []
    try:
        for content_type, payload in inline_images:
            suffix = ""
            if "/" in content_type:
                suffix = f".{content_type.split('/', 1)[1]}"
            with tempfile.NamedTemporaryFile(suffix=suffix or ".img", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            temp_files.append(tmp_path)
            try:
                pdf.ln(4)
                pdf.image(tmp_path, w=max_width)
                pdf.ln(4)
            except Exception:
                continue
    finally:
        for path in temp_files:
            try:
                os.remove(path)
            except OSError:
                pass


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


def obter_pdf_da_db(rfq_id, tipo_pdf="pedido", *, processo_id=None):
    """Retrieve stored PDF bytes from the database."""

    alvo_processo = processo_id
    fornecedor_id = None
    rfq_int: int | None = None

    if rfq_id is not None:
        try:
            rfq_int = int(rfq_id)
        except (TypeError, ValueError):
            rfq_int = None

    if alvo_processo is None or (tipo_pdf == "pedido" and fornecedor_id is None):
        if rfq_int is None:
            if alvo_processo is None:
                return None
        else:
            row = fetch_one(
                "SELECT processo_id, fornecedor_id FROM rfq WHERE id = ?",
                (rfq_int,),
            )
            if row:
                if alvo_processo is None:
                    alvo_processo = row[0]
                fornecedor_id = row[1] if len(row) > 1 else None
            elif alvo_processo is None:
                return None

    if alvo_processo is None:
        return None

    candidatos: list[str] = [tipo_pdf]
    if tipo_pdf == "pedido":
        if rfq_int is not None:
            candidatos.insert(0, f"pedido_fornecedor_rfq_{rfq_int}")
            candidatos.append(f"pedido_{rfq_int}")
        if fornecedor_id:
            candidatos.append(f"pedido_fornecedor_{fornecedor_id}")

    vistos: set[str] = set()
    for tipo in candidatos:
        if tipo in vistos:
            continue
        vistos.add(tipo)
        result = fetch_one(
            "SELECT pdf_data FROM pdf_storage WHERE processo_id = ? AND tipo_pdf = ?",
            (alvo_processo, tipo),
        )
        if result:
            return result[0]

    if tipo_pdf == "pedido":
        result = fetch_one(
            """
            SELECT pdf_data
              FROM pdf_storage
             WHERE processo_id = ? AND tipo_pdf LIKE ?
             ORDER BY data_criacao DESC, id DESC
             LIMIT 1
            """,
            (alvo_processo, "pedido_%"),
        )
        if result:
            return result[0]

    return None


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

    body, inline_images = _extract_email_body_and_images(message)
    pdf.multi_cell(0, 10, ensure_latin1(body.strip()))
    _append_inline_images(pdf, inline_images)
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
        mime_type = (getattr(item, "type", "") or "").lower()
        is_eml = lower_nome.endswith(".eml") or mime_type == "message/rfc822"
        is_msg = lower_nome.endswith(".msg") or mime_type == "application/vnd.ms-outlook"
        if is_eml:
            nome = os.path.splitext(nome)[0] + ".pdf"
            conteudo = converter_eml_para_pdf(conteudo)
        elif is_msg:
            nome = os.path.splitext(nome)[0] + ".pdf"
            conteudo = converter_msg_para_pdf(conteudo)
        processed.append((nome, conteudo))

    return processed
