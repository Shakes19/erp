import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import services.pdf_service as pdf_service


class DummyMessage:
    def __init__(self):
        self.sender = "sender@example.com"
        self.to = "recipient@example.com"
        self.subject = "Assunto"
        self.date = "2024-01-01"
        self.body = "Corpo da mensagem"


def test_converter_msg_para_pdf_passes_content_to_renderer(monkeypatch):
    tmp_paths = {}

    def fake_message(path):
        tmp_paths["path"] = path
        return DummyMessage()

    monkeypatch.setattr(pdf_service.extract_msg, "Message", fake_message)

    removed_paths: list[str] = []
    real_remove = os.remove

    def fake_remove(path):
        removed_paths.append(path)
        real_remove(path)

    monkeypatch.setattr(pdf_service.os, "remove", fake_remove)

    captured: dict[str, object] = {}

    def fake_render(header_lines, body):
        captured["header_lines"] = header_lines
        captured["body"] = body
        return b"PDF"

    monkeypatch.setattr(pdf_service, "_render_pdf", fake_render)

    pdf_bytes = pdf_service.converter_msg_para_pdf(b"dummy data")

    assert pdf_bytes == b"PDF"
    assert captured["header_lines"] == [
        "From: sender@example.com",
        "To: recipient@example.com",
        "Subject: Assunto",
        "Date: 2024-01-01",
        "",
    ]
    assert captured["body"] == "Corpo da mensagem"
    assert tmp_paths["path"] in removed_paths


def test_render_pdf_generates_pdf_bytes():
    pdf_bytes = pdf_service._render_pdf([
        "From: sender@example.com",
        "",
    ], "Corpo")

    assert pdf_bytes.startswith(b"%PDF")
