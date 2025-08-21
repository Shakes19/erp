from main import extrair_texto_pdf
from fpdf import FPDF


def criar_pdf_texto_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Hello World")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_texto_pdf():
    texto = extrair_texto_pdf(criar_pdf_texto_bytes())
    assert "Hello World" in texto
