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


def criar_pdf_alba_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "20/08/2025")
    pdf.ln()
    pdf.cell(0, 10, "Info")
    pdf.ln()
    pdf.cell(0, 10, "Ricardo Nogueira")
    pdf.ln()
    pdf.cell(0, 10, "001.00 ALBA gearmotor (rear door)")
    pdf.ln()
    pdf.cell(0, 10, "49NC074")
    pdf.ln()
    pdf.cell(0, 10, "Piece")
    pdf.ln()
    pdf.cell(0, 10, "1")
    pdf.ln()
    pdf.cell(0, 10, "KTB-code:")
    pdf.ln()
    pdf.cell(0, 10, "1991080")
    pdf.ln()
    pdf.cell(0, 10, "i.A. Ricardo Nogueira")
    pdf.ln()
    pdf.cell(0, 10, "Sales Department")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_dados_pdf_alba():
    dados = extrair_dados_pdf(criar_pdf_alba_bytes())
    assert dados["nome"] == "Ricardo Nogueira"
    assert dados["descricao"] == "ALBA gearmotor (rear door) 49NC074"


def criar_pdf_piece_inline_bytes():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Our reference:")
    pdf.ln()
    pdf.cell(0, 10, "01/06/2024")
    pdf.ln()
    pdf.cell(0, 10, "21079 Hamburg - Germany")
    pdf.ln()
    pdf.cell(0, 10, "Smart Client GmbH")
    pdf.ln()
    pdf.cell(0, 10, "Gro\u00dfmoorring 9")
    pdf.ln()
    pdf.cell(0, 10, "001.00 Widget Alpha Piece1")
    pdf.ln()
    pdf.cell(0, 10, "002.00 Widget Beta Piece2")
    return pdf.output(dest="S").encode("latin-1")


def test_extrair_dados_pdf_piece_inline():
    dados = extrair_dados_pdf(criar_pdf_piece_inline_bytes())
    assert dados["cliente"] == "Smart Client GmbH"
    assert dados["descricao"] == "Widget Alpha"
    assert dados["quantidade"] == 1
    assert dados["itens"][0]["codigo"] == "001.00"
    assert dados["itens"][0]["descricao"] == "Widget Alpha"
    assert dados["itens"][0]["quantidade"] == 1
    assert dados["itens"][1]["codigo"] == "002.00"
    assert dados["itens"][1]["descricao"] == "Widget Beta"
    assert dados["itens"][1]["quantidade"] == 2
