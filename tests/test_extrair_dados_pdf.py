from fpdf import FPDF
from main import extrair_dados_pdf


def criar_pdf_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "Contact:")
    pdf.ln()
    pdf.cell(0, 10, "Cliente XPTO")
    pdf.ln()
    pdf.cell(0, 10, "Descricao Teste")
    pdf.ln()
    pdf.cell(0, 10, "KTB-code:")
    pdf.ln()
    pdf.cell(0, 10, "ART123")
    pdf.ln()
    pdf.cell(0, 10, "Quantity")
    pdf.ln()
    pdf.cell(0, 10, "3")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_dados_pdf():
    dados = extrair_dados_pdf(criar_pdf_bytes())
    assert dados["cliente"] == "Cliente XPTO"
    assert dados["descricao"] == "Descricao Teste"
    assert dados["artigo_num"] == "ART123"
