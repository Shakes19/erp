import os
import sys

# Garantir que o diretório do projeto esteja no ``sys.path`` para permitir
# a importação do módulo ``db`` quando os testes são executados a partir da
# pasta ``tests``.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import hash_password, verify_password


def test_verify_password_with_hash():
    pwd = "secret"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_with_plain_text():
    pwd = "plain"
    assert verify_password(pwd, pwd)
    assert not verify_password("wrong", pwd)


def test_verify_password_with_bytes_and_memoryview():
    pwd = "secret2"
    hashed = hash_password(pwd).encode()
    assert verify_password(pwd, hashed)
    assert verify_password(pwd, memoryview(hashed))
