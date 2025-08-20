from fpdf import FPDF
from main import extrair_dados_pdf


def criar_pdf_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "01/06/2024")
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


def criar_pdf_hamburg_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "01/06/2024")
    pdf.ln()
    pdf.cell(0, 10, "21079 Hamburg - Germany")
    pdf.ln()
    pdf.cell(0, 10, "Smart Company")
    pdf.ln()
    pdf.cell(0, 10, "Piece")
    pdf.ln()
    pdf.cell(0, 10, "Widget Part ABC")
    pdf.ln()
    pdf.cell(0, 10, "Quantity")
    pdf.ln()
    pdf.cell(0, 10, "7")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_dados_pdf_hamburg():
    dados = extrair_dados_pdf(criar_pdf_hamburg_bytes())
    assert dados["cliente"] == "Smart Company"
    assert dados["descricao"] == "Widget Part ABC"


def criar_pdf_grossmoorring_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "01/06/2024")
    pdf.ln()
    pdf.cell(0, 10, "Info")
    pdf.ln()
    pdf.cell(0, 10, "Smart Quotation GmbH")
    pdf.ln()
    pdf.cell(0, 10, "Gro\u00dfmoorring 9")
    pdf.ln()
    pdf.cell(0, 10, "Descricao A")
    pdf.ln()
    pdf.cell(0, 10, "001.00")
    pdf.ln()
    pdf.cell(0, 10, "Descricao B")
    pdf.ln()
    pdf.cell(0, 10, "002.00")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_dados_pdf_grossmoorring():
    dados = extrair_dados_pdf(criar_pdf_grossmoorring_bytes())
    assert dados["cliente"] == "Smart Quotation GmbH"
    assert dados["descricao"] == "Descricao A"
    assert dados["itens"][0]["descricao"] == "Descricao A"
    assert dados["itens"][0]["codigo"] == "001.00"
    assert dados["itens"][1]["descricao"] == "Descricao B"
    assert dados["itens"][1]["codigo"] == "002.00"
