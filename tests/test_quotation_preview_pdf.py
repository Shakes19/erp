import importlib
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_quotation_preview_pdf_starts_with_magic_bytes():
    import main as main_module

    importlib.reload(main_module)

    pdf_bytes = main_module.gerar_pdf_cliente_exemplo()

    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert pdf_bytes.startswith(b"%PDF")
