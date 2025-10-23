from services.pdf_service import converter_eml_para_pdf


def test_converter_eml_para_pdf_creates_pdf():
    eml = (b"From: a@example.com\n"
           b"To: b@example.com\n"
           b"Subject: Teste\n\n"
           b"Corpo do email")
    pdf_bytes = converter_eml_para_pdf(eml)
    assert pdf_bytes.startswith(b"%PDF")
