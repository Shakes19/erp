import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.pdf_service import converter_eml_para_pdf


def test_converter_eml_para_pdf_passes_content_to_renderer(monkeypatch):
    captured: dict[str, object] = {}

    def fake_render(header_lines, body):
        captured["header_lines"] = header_lines
        captured["body"] = body
        return b"PDF"

    monkeypatch.setattr("services.pdf_service._render_pdf", fake_render)

    eml = (b"From: a@example.com\n"
           b"To: b@example.com\n"
           b"Subject: Teste\n\n"
           b"Corpo do email")

    pdf_bytes = converter_eml_para_pdf(eml)

    assert pdf_bytes == b"PDF"
    assert captured["header_lines"] == [
        "From: a@example.com",
        "To: b@example.com",
        "Subject: Teste",
        "Date: ",
        "",
    ]
    assert captured["body"] == "Corpo do email"


def test_converter_eml_para_pdf_generates_pdf_bytes():
    eml = (b"From: a@example.com\n"
           b"To: b@example.com\n"
           b"Subject: Teste\n\n"
           b"Corpo do email")

    pdf_bytes = converter_eml_para_pdf(eml)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 0
