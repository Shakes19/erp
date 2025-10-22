import streamlit as st
import sqlite3
from datetime import datetime, date, timedelta
from fpdf import FPDF
import base64
import json
from collections import defaultdict, OrderedDict
from io import BytesIO
import os
import shutil
import imghdr
import tempfile
import re
import copy
import textwrap
from uuid import uuid4
from typing import Iterable
from pypdf import PdfReader
from PIL import Image
import pandas as pd
from streamlit_option_menu import option_menu
from db import (
    criar_processo,
    criar_base_dados_completa,
    get_connection as obter_conexao,
    backup_database,
    hash_password,
    verify_password,
    DB_PATH,
    engine,
    inserir_artigo_catalogo,
    procurar_artigos_catalogo,
    fetch_all,
    fetch_one,
    ensure_estado,
    ensure_unidade,
    get_marca_id,
    get_artigo_catalogo_id,
    resolve_processo_id,
)
from services.pdf_service import (
    ensure_latin1,
    load_pdf_config,
    save_pdf_config,
    obter_config_empresa,
    obter_pdf_da_db,
    processar_upload_pdf,
)
from services.email_service import (
    clear_email_cache,
    get_system_email_config,
    send_email,
)

# ========================== CONFIGURAÇÃO GLOBAL ==========================

def _format_iso_date(value):
    """Format ISO 8601 strings or datetime objects to ``dd/mm/YYYY``.

    Returns an empty string if the value is falsy or cannot be parsed.
    """

    if not value:
        return ""

    if isinstance(value, (datetime, date)):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return ""

    return dt.strftime("%d/%m/%Y")


def limitar_descricao_artigo(texto: str, max_linhas: int = 2) -> str:
    """Mantém apenas as primeiras ``max_linhas`` não vazias de ``texto``.

    Linhas em branco são ignoradas para evitar resultados vazios e
    whitespace no início/fim de cada linha é removido. Retorna uma string
    normalizada com ``\n`` entre as linhas mantidas.
    """

    if not texto:
        return ""

    linhas_filtradas: list[str] = []
    for linha in texto.replace("\r", "\n").split("\n"):
        limpa = linha.strip()
        if not limpa:
            continue
        linhas_filtradas.append(limpa)
        if len(linhas_filtradas) >= max_linhas:
            break

    return "\n".join(linhas_filtradas)


def invalidate_overview_caches() -> None:
    """Limpar caches utilizadas na dashboard principal.

    A dashboard e a área de relatórios reutilizam as funções
    ``obter_todas_cotacoes`` e ``obter_estatisticas_db``. Quando estes dados
    são atualizados a interface podia oscillar entre estados diferentes até
    que as novas informações fossem calculadas novamente, contribuindo para
    *layout shifts*.  Ao invalidarmos explicitamente estas caches sempre que
    existe uma alteração relevante, garantimos que a interface recebe os
    dados finais de forma estável após a submissão da ação do utilizador.
    """

    for nome in ("obter_todas_cotacoes", "obter_estatisticas_db"):
        func = globals().get(nome)
        if func and hasattr(func, "clear"):
            func.clear()


LOGO_PATH = "assets/logo.png"
with open(LOGO_PATH, "rb") as _logo_file:
    LOGO_BYTES = _logo_file.read()
LOGO_IMAGE = Image.open(BytesIO(LOGO_BYTES))

st.set_page_config(
    page_title="myERP",
    page_icon=LOGO_IMAGE,
    layout="wide",
)

# ========================== GESTÃO DA BASE DE DADOS ==========================



# ========================== FUNÇÕES DE GESTÃO DE FORNECEDORES ==========================

@st.cache_data(show_spinner=False)
def listar_fornecedores():
    """Obter todos os fornecedores.

    Resultados memorizados para reduzir acessos à base de dados quando o
    utilizador navega entre páginas.
    """
    rows = fetch_all(
        """
        SELECT id,
               nome,
               email,
               telefone,
               morada,
               nif,
               COALESCE(necessita_pais_cliente_final, 0) AS necessita_pais_cliente_final
          FROM fornecedor
         ORDER BY nome
        """
    )

    fornecedores: list[tuple] = []
    for row in rows:
        if not row:
            continue
        fornecedores.append(
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                bool(row[6]) if len(row) > 6 else False,
            )
        )

    return fornecedores

def inserir_fornecedor(
    nome,
    email="",
    telefone="",
    morada="",
    nif="",
    necessita_pais_cliente_final: bool = False,
):
    """Inserir novo fornecedor"""
    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        return None

    conn = obter_conexao()
    c = conn.cursor()

    try:
        # Verificar se o fornecedor já existe
        c.execute(
            "SELECT id FROM fornecedor WHERE PYCASEFOLD(nome) = PYCASEFOLD(?)",
            (nome_limpo,),
        )
        resultado = c.fetchone()

        if resultado:
            return int(resultado[0])

        c.execute(
            """
            INSERT INTO fornecedor (
                nome,
                email,
                telefone,
                morada,
                nif,
                necessita_pais_cliente_final
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                nome_limpo,
                email,
                telefone,
                morada,
                nif,
                1 if necessita_pais_cliente_final else 0,
            ),
        )
        conn.commit()
        listar_fornecedores.clear()
        return c.lastrowid
    finally:
        conn.close()


def atualizar_fornecedor(
    fornecedor_id,
    nome,
    email="",
    telefone="",
    morada="",
    nif="",
    necessita_pais_cliente_final: bool = False,
):
    """Atualizar dados de um fornecedor existente"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            """
            UPDATE fornecedor
            SET nome = ?, email = ?, telefone = ?, morada = ?, nif = ?, necessita_pais_cliente_final = ?
            WHERE id = ?
            """,
            (
                nome,
                email,
                telefone,
                morada,
                nif,
                1 if necessita_pais_cliente_final else 0,
                fornecedor_id,
            ),
        )
        conn.commit()
        listar_fornecedores.clear()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def eliminar_fornecedor_db(fornecedor_id):
    """Eliminar fornecedor"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM fornecedor WHERE id = ?", (fornecedor_id,))
    conn.commit()
    listar_fornecedores.clear()
    removidos = c.rowcount
    conn.close()
    return removidos > 0

def obter_marcas_fornecedor(fornecedor_id):
    """Obter marcas associadas a um fornecedor."""

    rows = fetch_all(
        """
        SELECT TRIM(marca) AS marca, COALESCE(margem, 0.0)
        FROM marca
        WHERE fornecedor_id = ?
          AND marca IS NOT NULL
        ORDER BY TRIM(marca)
        """,
        (fornecedor_id,),
    )

    marcas = []
    for row in rows:
        if not row:
            continue
        marca_nome = row[0]
        if not marca_nome:
            continue
        marcas.append({"nome": marca_nome, "margem": float(row[1])})

    return marcas

def adicionar_marca_fornecedor(fornecedor_id, marca):
    """Adicionar marca a um fornecedor"""
    marca_limpa = (marca or "").strip()
    if not marca_limpa:
        return False

    marca_normalizada = marca_limpa.casefold()

    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            """
            SELECT fornecedor_id
              FROM marca
             WHERE marca_normalizada = ?
            """,
            (marca_normalizada,),
        )
        if c.fetchone():
            return False

        c.execute(
            """
            INSERT INTO marca (
                fornecedor_id,
                marca,
                marca_normalizada
            )
            VALUES (?, ?, ?)
            """,
            (fornecedor_id, marca_limpa, marca_normalizada),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def remover_marca_fornecedor(fornecedor_id, marca):
    """Remover marca de um fornecedor"""
    marca_limpa = (marca or "").strip()
    if not marca_limpa:
        return False

    marca_normalizada = marca_limpa.casefold()

    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM marca
        WHERE fornecedor_id = ? AND marca_normalizada = ?
        """,
        (fornecedor_id, marca_normalizada),
    )
    conn.commit()
    rows_affected = c.rowcount
    conn.close()
    return rows_affected > 0


def listar_todas_marcas():
    """Obter todas as marcas disponíveis"""
    rows = fetch_all(
        """
        SELECT DISTINCT TRIM(marca)
        FROM marca
        WHERE marca IS NOT NULL AND TRIM(marca) != ''
        ORDER BY TRIM(marca)
        """
    )
    return [row[0] for row in rows if row[0]]


@st.cache_data(show_spinner=False)
def listar_unidades():
    """Obter todas as unidades configuradas."""

    rows = fetch_all(
        """
        SELECT id, nome
          FROM unidade
         WHERE nome IS NOT NULL AND TRIM(nome) != ''
         ORDER BY nome COLLATE NOCASE
        """
    )
    unidades: list[tuple[int, str]] = []
    for row in rows:
        unidades.append((int(row[0]), row[1]))
    return unidades


def inserir_unidade(nome: str) -> int | None:
    """Adicionar uma nova unidade normalizada."""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        return None

    conn = obter_conexao()
    cursor = conn.cursor()
    try:
        unidade_id = ensure_unidade(nome_limpo, cursor=cursor)
        conn.commit()
        listar_unidades.clear()
        return unidade_id
    except (ValueError, sqlite3.IntegrityError):
        conn.rollback()
        return None
    finally:
        conn.close()


def atualizar_unidade(unidade_id: int, nome: str) -> bool:
    """Atualizar o nome de uma unidade existente."""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        return False

    conn = obter_conexao()
    cursor = conn.cursor()
    try:
        nome_normalizado = nome_limpo.casefold()
        cursor.execute(
            "UPDATE unidade SET nome = ?, nome_normalizada = ? WHERE id = ?",
            (nome_limpo, nome_normalizado, unidade_id),
        )
        conn.commit()
        if cursor.rowcount:
            listar_unidades.clear()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def eliminar_unidade(unidade_id: int) -> bool:
    """Eliminar unidade, respeitando referências existentes."""

    conn = obter_conexao()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM unidade WHERE id = ?", (unidade_id,))
        conn.commit()
        if cursor.rowcount:
            listar_unidades.clear()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def obter_nomes_unidades() -> list[str]:
    """Lista de unidades para seleção em formulários."""

    nomes = [nome for _, nome in listar_unidades()]
    if not nomes:
        nomes = ["Peças", "Metros", "KG", "Litros", "Caixas", "Paletes"]
    return nomes


def obter_fornecedores_por_marca(marca):
    """Retorna lista de fornecedores (id, nome, email, requer_dados, margem) associados à marca."""

    marca_limpa = (marca or "").strip()
    if not marca_limpa:
        return []

    marca_normalizada = marca_limpa.casefold()

    rows = fetch_all(
        """
        SELECT f.id,
               f.nome,
               f.email,
               TRIM(m.marca),
               COALESCE(f.necessita_pais_cliente_final, 0) AS necessita_pais_cliente_final,
               COALESCE(m.margem, 0.0)
          FROM fornecedor f
          JOIN marca m ON f.id = m.fornecedor_id
         WHERE m.marca_normalizada = ?
         ORDER BY f.nome
        """,
        (marca_normalizada,),
    )

    fornecedores: list[tuple] = []
    for fornecedor_id, nome, email, marca_db, requer_dados, margem in rows:
        fornecedores.append(
            (fornecedor_id, nome, email, bool(requer_dados), float(margem))
        )

    return fornecedores


def referencia_cliente_existe(referencia: str, cliente_id: int | None = None) -> bool:
    """Verifica se já existe uma cotação com a mesma referência para o cliente."""

    referencia_limpa = (referencia or "").strip()
    if not referencia_limpa:
        return False

    params: list = [referencia_limpa]
    query = "SELECT 1 FROM processo WHERE TRIM(ref_cliente) = ?"
    if cliente_id is not None:
        query += " AND COALESCE(cliente_id, -1) = COALESCE(?, -1)"
        params.append(cliente_id)
    query += " LIMIT 1"
    row = fetch_one(query, tuple(params))
    return bool(row)


def processar_criacao_cotacoes(contexto: dict, forcar: bool = False) -> bool:
    """Processa a criação de cotações para fornecedores, com verificação de duplicados."""

    if not contexto:
        return False

    referencia = (contexto.get("referencia") or "").strip()
    cliente_id = contexto.get("cliente_id")
    origem = contexto.get("origem", "manual")
    artigos = contexto.get("artigos") or []
    requisitos_fornecedores = copy.deepcopy(
        contexto.get("requisitos_fornecedores") or {}
    )
    if not forcar and referencia_cliente_existe(referencia, cliente_id):
        st.session_state["duplicated_ref_context"] = copy.deepcopy(contexto)
        st.session_state["show_duplicate_ref_dialog"] = True
        st.session_state.pop("duplicated_ref_force", None)
        return False

    if not artigos:
        return False

    artigos_posicoes = contexto.get("artigos_posicoes") or [idx + 1 for idx in range(len(artigos))]
    anexos = contexto.get("anexos") or []
    anexo_tipo = contexto.get("anexo_tipo", "anexo_cliente")
    data_cotacao = contexto.get("data") or date.today()

    fornecedores_map: defaultdict[int, list[int]] = defaultdict(list)
    fornecedores_info: dict[int, tuple] = {}
    erros_fornecedores: list[str] = []

    for idx, artigo in enumerate(artigos):
        fornecedores = obter_fornecedores_por_marca(artigo.get("marca"))
        if not fornecedores:
            if origem == "smart":
                pos = artigos_posicoes[idx] if idx < len(artigos_posicoes) else idx + 1
                erros_fornecedores.append(
                    f"Artigo {pos}: configure fornecedores para a marca '{artigo.get('marca', '')}'."
                )
            else:
                erros_fornecedores.append(
                    f"Nenhum fornecedor configurado para a marca '{artigo.get('marca', '')}'"
                )
            continue
        for fornecedor in fornecedores:
            fornecedores_map[fornecedor[0]].append(idx)
            fornecedores_info[fornecedor[0]] = fornecedor

    if erros_fornecedores:
        for mensagem in erros_fornecedores:
            st.error(mensagem)
        return False

    if not fornecedores_map:
        st.error("Não foram encontrados fornecedores elegíveis para os artigos selecionados")
        return False

    fornecedores_requer_dados: list[tuple[int, str]] = []
    for fornecedor_id in fornecedores_map:
        fornecedor_info = fornecedores_info.get(fornecedor_id)
        requer_dados = bool(fornecedor_info[3]) if fornecedor_info and len(fornecedor_info) > 3 else False
        if not requer_dados:
            continue
        dados_existentes = requisitos_fornecedores.get(fornecedor_id) or {}
        cliente_final_val = (dados_existentes.get("cliente_final") or "").strip()
        pais_val = (dados_existentes.get("pais") or "").strip()
        if not pais_val:
            fornecedores_requer_dados.append((fornecedor_id, fornecedor_info[1]))

    if fornecedores_requer_dados:
        st.session_state["supplier_requirement_context"] = copy.deepcopy(contexto)
        st.session_state["supplier_requirement_suppliers"] = [
            {"id": fid, "nome": nome} for fid, nome in fornecedores_requer_dados
        ]
        st.session_state["supplier_requirement_data"] = copy.deepcopy(
            requisitos_fornecedores
        )
        st.session_state["supplier_requirement_origin"] = origem
        st.session_state["show_supplier_requirement_dialog"] = True
        return False

    processo_id, numero_processo, processo_artigos = criar_processo_com_artigos(
        artigos, cliente_id
    )
    rfqs_criados: list[tuple[int, tuple, dict]] = []

    for fornecedor_id, indices in fornecedores_map.items():
        artigos_fornecedor: list[dict] = []
        for indice in indices:
            if indice >= len(processo_artigos):
                continue
            processo_info = processo_artigos[indice]
            artigos_fornecedor.append(
                {
                    **artigos[indice],
                    "processo_artigo_id": processo_info.get("processo_artigo_id"),
                    "ordem": processo_info.get("ordem"),
                }
            )

        rfq_id, _, _, _, email_status = criar_rfq(
            fornecedor_id,
            data_cotacao,
            artigos_fornecedor,
            referencia,
            cliente_id,
            processo_id=processo_id,
            numero_processo=numero_processo,
            processo_artigos=processo_artigos,
            requisitos_fornecedor=requisitos_fornecedores.get(fornecedor_id),
        )

        if rfq_id:
            status_info = email_status or {}
            fornecedor_info = fornecedores_info[fornecedor_id]
            status_info.setdefault("fornecedor", fornecedor_info[1])
            rfqs_criados.append((rfq_id, fornecedor_info, status_info))
            if anexos:
                guardar_pdf_uploads(
                    rfq_id,
                    anexo_tipo,
                    anexos,
                )

    if rfqs_criados:
        st.success(
            f"✅ Cotação {numero_processo} (Ref: {referencia}) criada para {len(rfqs_criados)} fornecedor(es)!"
        )
        st.markdown("**Fornecedores notificados:**")
        for _, fornecedor, _ in rfqs_criados:
            st.write(f"• {fornecedor[1]}")

        pdf_resultados: list[dict[str, object]] = []
        for rfq_id, fornecedor, _ in rfqs_criados:
            pdf_bytes = obter_pdf_da_db(rfq_id, "pedido")
            if not pdf_bytes:
                continue
            pdf_info = {
                "rfq_id": rfq_id,
                "fornecedor": fornecedor[1],
                "pdf_bytes": pdf_bytes,
            }
            pdf_resultados.append(pdf_info)
            if origem == "manual":
                st.download_button(
                    f"📄 PDF - {fornecedor[1]}",
                    data=pdf_bytes,
                    file_name=f"cotacao_{numero_processo}_{fornecedor[1].replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    key=f"download_pdf_{rfq_id}",
                )

        st.session_state.pop("duplicated_ref_context", None)
        st.session_state.pop("duplicated_ref_force", None)
        st.session_state["show_duplicate_ref_dialog"] = False

        for key in (
            "supplier_requirement_context",
            "supplier_requirement_suppliers",
            "supplier_requirement_data",
            "supplier_requirement_ready",
            "supplier_requirement_origin",
            "show_supplier_requirement_dialog",
        ):
            st.session_state.pop(key, None)

        if origem == "manual":
            st.session_state.artigos = [
                {
                    "artigo_num": "",
                    "descricao": "",
                    "quantidade": "",
                    "unidade": "Peças",
                    "marca": "",
                }
            ]
            st.session_state.pedido_cliente_anexos = []
            st.session_state["reset_nova_cotacao_form"] = True
            st.session_state.pop("upload_pedido_cliente", None)
            for key in list(st.session_state.keys()):
                for prefix in ("nova_desc_", "nova_art_num_", "nova_qtd_", "nova_unidade_", "nova_marca_"):
                    if key.startswith(prefix):
                        st.session_state.pop(key, None)
                        break
            st.rerun()

        else:
            st.session_state["smart_success_data"] = {
                "numero_processo": numero_processo,
                "referencia": referencia,
                "fornecedores": [fornecedor[1] for _, fornecedor, _ in rfqs_criados],
                "pdfs": pdf_resultados,
                "emails": [
                    {
                        "fornecedor": status.get("fornecedor") or fornecedor[1],
                        "sucesso": bool(status.get("sucesso")),
                        "mensagem": status.get("mensagem")
                        or f"Email para {fornecedor[1]} não enviado.",
                    }
                    for _, fornecedor, status in rfqs_criados
                ],
            }
            st.session_state["show_smart_success_dialog"] = True
            reset_smart_quotation_state()
            st.session_state.pop("smart_pdf", None)
            st.rerun()

        return True

    mensagem_erro = (
        "Erro ao criar cotação." if origem == "smart" else "Não foi possível criar as cotações para os fornecedores selecionados."
    )
    st.error(mensagem_erro)
    return False


def mostrar_dialogo_referencia_duplicada(origem: str):
    """Mostra diálogo de confirmação quando é detetada referência duplicada."""

    contexto = st.session_state.get("duplicated_ref_context")
    if (
        not contexto
        or contexto.get("origem") != origem
        or not st.session_state.get("show_duplicate_ref_dialog")
    ):
        return

    referencia = contexto.get("referencia", "")
    cliente_nome = (contexto.get("cliente_nome") or "").strip()
    cliente_info = f" para o cliente {cliente_nome}" if cliente_nome else ""

    @st.dialog("Referência duplicada")
    def _dialogo():
        st.warning(
            f"Já existe uma cotação com a referência '{referencia}'{cliente_info}."
        )
        st.write("Deseja criar a cotação mesmo assim?")
        col_ok, col_cancel = st.columns(2)
        if col_ok.button("Sim, criar mesmo assim"):
            st.session_state["duplicated_ref_force"] = origem
            st.session_state["show_duplicate_ref_dialog"] = False
            st.rerun()
        if col_cancel.button("Não, cancelar"):
            st.session_state.pop("duplicated_ref_context", None)
            st.session_state.pop("duplicated_ref_force", None)
            st.session_state["show_duplicate_ref_dialog"] = False
            st.rerun()

    _dialogo()


def mostrar_dialogo_requisitos_fornecedor(origem: str) -> None:
    """Solicita país e cliente final antes do envio ao fornecedor."""

    contexto = st.session_state.get("supplier_requirement_context")
    if (
        not contexto
        or contexto.get("origem") != origem
        or not st.session_state.get("show_supplier_requirement_dialog")
    ):
        return

    fornecedores = st.session_state.get("supplier_requirement_suppliers") or []
    dados_existentes = st.session_state.get("supplier_requirement_data") or {}

    titulo_dialogo = "Informações obrigatórias para o fornecedor"

    @st.dialog(titulo_dialogo)
    def _dialogo():
        st.info(
            "Informe o país do cliente final antes de enviar o pedido ao fornecedor."
        )

        entradas: list[tuple[int, str, str, str]] = []
        for fornecedor_info in fornecedores:
            fornecedor_id = fornecedor_info.get("id")
            fornecedor_nome = (fornecedor_info.get("nome") or "Fornecedor").strip()
            dados = dados_existentes.get(fornecedor_id) or {}
            cliente_key = f"req_cliente_{origem}_{fornecedor_id}"
            pais_key = f"req_pais_{origem}_{fornecedor_id}"

            st.markdown(f"**{fornecedor_nome}**")
            st.text_input(
                "Cliente Final",
                value=dados.get("cliente_final", ""),
                key=cliente_key,
                help="Nome do cliente final associado ao pedido (opcional).",
            )
            st.text_input(
                "País *",
                value=dados.get("pais", ""),
                key=pais_key,
                help="País do cliente final.",
            )
            entradas.append((fornecedor_id, fornecedor_nome, cliente_key, pais_key))

        col_ok, col_cancel = st.columns(2)

        if col_ok.button("Confirmar e continuar"):
            dados_confirmados: dict[int, dict[str, str]] = {}
            em_falta: list[str] = []
            for fornecedor_id, fornecedor_nome, cliente_key, pais_key in entradas:
                cliente_val = (st.session_state.get(cliente_key) or "").strip()
                pais_val = (st.session_state.get(pais_key) or "").strip()
                if not pais_val:
                    em_falta.append(fornecedor_nome)
                dados_confirmados[fornecedor_id] = {
                    "cliente_final": cliente_val,
                    "pais": pais_val,
                }

            if em_falta:
                st.error("Preencha o país obrigatório para cada fornecedor.")
            else:
                st.session_state["supplier_requirement_data"] = dados_confirmados
                st.session_state["supplier_requirement_ready"] = origem
                st.session_state["show_supplier_requirement_dialog"] = False
                st.rerun()

        if col_cancel.button("Cancelar"):
            st.session_state.pop("supplier_requirement_context", None)
            st.session_state.pop("supplier_requirement_suppliers", None)
            st.session_state.pop("supplier_requirement_data", None)
            st.session_state.pop("supplier_requirement_ready", None)
            st.session_state.pop("supplier_requirement_origin", None)
            st.session_state["show_supplier_requirement_dialog"] = False
            st.rerun()

    _dialogo()


def mostrar_dialogo_sucesso_smart() -> None:
    """Apresenta um resumo em formato pop-up após criar cotações via Smart Quotation."""

    if not st.session_state.get("show_smart_success_dialog"):
        return

    payload = st.session_state.get("smart_success_data") or {}
    numero_processo = payload.get("numero_processo") or ""
    referencia = payload.get("referencia") or ""
    fornecedores = payload.get("fornecedores") or []
    pdfs = payload.get("pdfs") or []
    emails = payload.get("emails") or []

    titulo = "Cotação criada"

    @st.dialog(titulo, width="large")
    def _dialog():
        st.success(f"Cotação {numero_processo} criada com sucesso!")
        if referencia:
            st.write(f"**Referência do cliente:** {referencia}")
        if fornecedores:
            st.markdown("**Fornecedores notificados:**")
            for nome in fornecedores:
                st.write(f"• {nome}")

        if emails:
            st.markdown("**Estado do envio de emails:**")
            for idx, info in enumerate(emails, 1):
                mensagem = info.get("mensagem") or "Estado de envio indisponível."
                if info.get("sucesso"):
                    st.success(mensagem)
                else:
                    st.error(mensagem)

        for idx, info in enumerate(pdfs, 1):
            nome_pdf = info.get("fornecedor") or f"Fornecedor {idx}"
            pdf_bytes = info.get("pdf_bytes")
            if not pdf_bytes:
                continue
            st.download_button(
                f"Download PDF - {nome_pdf}",
                data=pdf_bytes,
                file_name=f"cotacao_{numero_processo}_{nome_pdf.replace(' ', '_')}.pdf",
                mime="application/pdf",
                key=f"smart_dialog_pdf_{idx}",
            )

        if st.button("Fechar"):
            st.session_state.pop("smart_success_data", None)
            st.session_state["show_smart_success_dialog"] = False
            st.rerun()

    _dialog()


# ========================== FUNÇÕES DE GESTÃO DE CLIENTES ==========================

@st.cache_data(show_spinner=False)
def listar_empresas():
    """Obter todas as empresas de clientes.

    Tal como acontecia anteriormente com ``listar_clientes``, esta função
    falhava com ``sqlite3.OperationalError`` quando a base de dados ainda não
    estava inicializada (tabela ``cliente_empresa`` inexistente).  Agora o
    erro é interceptado e a base de dados é criada automaticamente,
    devolvendo uma lista vazia.
    """
    return fetch_all(
        "SELECT id, nome, morada, condicoes_pagamento FROM cliente_empresa ORDER BY nome",
        ensure_schema=True,
    )


@st.cache_data(show_spinner=False)
def listar_clientes():
    """Obter todos os clientes.

    Antes desta correção, se a base de dados ainda não tivesse sido
    inicializada a chamada falhava com ``sqlite3.OperationalError`` ao
    tentar aceder à tabela ``cliente``.  Isto acontecia, por exemplo,
    quando o utilizador executava o programa sem ter criado as tabelas
    previamente.  Agora a função verifica essa condição e cria a base de
    dados quando necessário, devolvendo uma lista vazia."""

    return fetch_all(
        """
        SELECT c.id, c.nome, c.email, c.empresa_id, e.nome
        FROM cliente c
        LEFT JOIN cliente_empresa e ON c.empresa_id = e.id
        ORDER BY c.nome
        """,
        ensure_schema=True,
    )


def inserir_empresa(nome, morada="", condicoes_pagamento=""):
    """Inserir nova empresa de cliente"""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        raise ValueError("Nome da empresa é obrigatório")

    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT id FROM cliente_empresa WHERE PYCASEFOLD(nome) = PYCASEFOLD(?)",
            (nome_limpo,),
        )
        existente = c.fetchone()
        if existente:
            return existente[0]

        c.execute(
            "INSERT INTO cliente_empresa (nome, morada, condicoes_pagamento) VALUES (?, ?, ?)",
            (nome_limpo, morada, condicoes_pagamento),
        )
        conn.commit()
        listar_empresas.clear()
        return c.lastrowid
    except sqlite3.OperationalError as e:
        conn.close()
        if "no such table" in str(e).lower():
            criar_base_dados_completa()
            return inserir_empresa(nome_limpo, morada, condicoes_pagamento)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def atualizar_empresa(empresa_id, nome, morada="", condicoes_pagamento=""):
    """Atualizar dados de uma empresa"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "UPDATE cliente_empresa SET nome = ?, morada = ?, condicoes_pagamento = ? WHERE id = ?",
        (nome, morada, condicoes_pagamento, empresa_id),
    )
    conn.commit()
    conn.close()
    listar_empresas.clear()
    return True


def eliminar_empresa_db(empresa_id):
    """Eliminar empresa"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM cliente_empresa WHERE id = ?", (empresa_id,))
    conn.commit()
    conn.close()
    listar_empresas.clear()
    return True


def inserir_cliente(nome, email="", empresa_id=None):
    """Inserir novo cliente"""

    nome_limpo = (nome or "").strip()
    if not nome_limpo:
        raise ValueError("Nome do cliente é obrigatório")

    email_limpo = (email or "").strip()

    conn = obter_conexao()
    c = conn.cursor()
    try:
        # Evitar duplicados pelo nome (ignorando maiúsculas/minúsculas) para a mesma empresa
        c.execute(
            """
            SELECT id
              FROM cliente
             WHERE PYCASEFOLD(nome) = PYCASEFOLD(?)
               AND COALESCE(empresa_id, -1) = COALESCE(?, -1)
            """,
            (nome_limpo, empresa_id),
        )
        existente = c.fetchone()
        if not existente and email_limpo:
            # Se o email já existir reutilizamos o mesmo registo
            c.execute(
                "SELECT id FROM cliente WHERE PYCASEFOLD(email) = PYCASEFOLD(?)",
                (email_limpo,),
            )
            existente = c.fetchone()
        if existente:
            return existente[0]

        c.execute(
            "INSERT INTO cliente (nome, email, empresa_id) VALUES (?, ?, ?)",
            (nome_limpo, email_limpo or None, empresa_id),
        )
        conn.commit()
        listar_clientes.clear()
        return c.lastrowid
    finally:
        conn.close()


def atualizar_cliente(cliente_id, nome, email="", empresa_id=None):
    """Atualizar dados de um cliente"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "UPDATE cliente SET nome = ?, email = ?, empresa_id = ? WHERE id = ?",
        (nome, email, empresa_id, cliente_id),
    )
    conn.commit()
    conn.close()
    listar_clientes.clear()
    return True


def eliminar_cliente_db(cliente_id):
    """Eliminar cliente"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM cliente WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()
    listar_clientes.clear()
    return True


# ========================== FUNÇÕES DE GESTÃO DE UTILIZADORES ==========================

@st.cache_data(show_spinner=False)
def listar_utilizadores():
    """Obter todos os utilizadores"""
    return fetch_all(
        "SELECT id, username, nome, email, role, email_password FROM utilizador ORDER BY username"
    )


def obter_utilizador_por_username(username):
    """Obter utilizador pelo username"""
    return fetch_one(
        "SELECT id, username, password, nome, email, role, email_password FROM utilizador WHERE username = ?",
        (username,),
    )


def obter_utilizador_por_id(user_id):
    """Obter utilizador pelo ID"""
    return fetch_one(
        "SELECT id, username, password, nome, email, role, email_password FROM utilizador WHERE id = ?",
        (user_id,),
    )


def inserir_utilizador(username, password, nome="", email="", role="user", email_password=""):
    """Inserir novo utilizador"""

    username_limpo = (username or "").strip()
    if not username_limpo or not password:
        raise ValueError("Username e palavra-passe são obrigatórios")

    conn = obter_conexao()
    c = conn.cursor()
    try:
        c.execute(
            "SELECT id FROM utilizador WHERE PYCASEFOLD(username) = PYCASEFOLD(?)",
            (username_limpo,),
        )
        existente = c.fetchone()
        if existente:
            return existente[0]

        c.execute(
            """
            INSERT INTO utilizador (username, password, nome, email, role, email_password)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username_limpo,
                hash_password(password),
                nome,
                email,
                role,
                email_password,
            ),
        )
        conn.commit()
        listar_utilizadores.clear()
        return c.lastrowid
    except Exception:
        return None
    finally:
        conn.close()


def atualizar_utilizador(
    user_id, username, nome, email, role, password=None, email_password=None
):
    """Atualizar dados de um utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        fields = ["username = ?", "nome = ?", "email = ?", "role = ?"]
        params = [username, nome, email, role]
        if password:
            fields.append("password = ?")
            params.append(hash_password(password))
        if email_password is not None:
            fields.append("email_password = ?")
            params.append(email_password)
        params.append(user_id)
        c.execute(
            f"UPDATE utilizador SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()
        listar_utilizadores.clear()
        return True
    finally:
        conn.close()


def eliminar_utilizador(user_id):
    """Eliminar utilizador"""
    conn = obter_conexao()
    c = conn.cursor()
    c.execute("DELETE FROM utilizador WHERE id = ?", (user_id,))
    conn.commit()
    removed = c.rowcount
    conn.close()
    if removed:
        listar_utilizadores.clear()
    return removed > 0

# ========================== FUNÇÕES DE GESTÃO DE RFQs ==========================

def criar_processo_com_artigos(artigos, cliente_id: int | None = None):
    """Criar um novo processo e respetivos artigos base."""

    utilizador_id = st.session_state.get("user_id")
    processo_id, numero_processo = criar_processo(
        utilizador_id=utilizador_id, cliente_id=cliente_id
    )
    conn = obter_conexao()
    c = conn.cursor()
    processo_artigos: list[dict] = []

    try:
        for ordem, art in enumerate(artigos, 1):
            artigo_num = (art.get("artigo_num") or "").strip()
            marca_artigo = (art.get("marca") or "").strip()
            descricao_artigo = garantir_marca_primeira_palavra(
                art.get("descricao", ""), marca_artigo
            )
            quantidade_artigo = art.get("quantidade", 1)
            unidade_artigo = art.get("unidade", "Peças") or "Peças"
            try:
                unidade_id = ensure_unidade(unidade_artigo, cursor=c)
            except ValueError:
                unidade_id = ensure_unidade("Peças", cursor=c)
            marca_id = get_marca_id(marca_artigo, cursor=c)
            artigo_catalogo_id = get_artigo_catalogo_id(artigo_num, cursor=c)
            c.execute(
                """
                INSERT INTO processo_artigo (processo_id, artigo_num, descricao,
                                             quantidade, unidade_id, marca, ordem,
                                             marca_id, artigo_catalogo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    processo_id,
                    artigo_num,
                    descricao_artigo,
                    quantidade_artigo,
                    unidade_id,
                    marca_artigo,
                    ordem,
                    marca_id,
                    artigo_catalogo_id,
                ),
            )
            processo_artigos.append(
                {
                    **art,
                    "artigo_num": artigo_num,
                    "descricao": descricao_artigo,
                    "quantidade": quantidade_artigo,
                    "unidade": unidade_artigo,
                    "marca": marca_artigo,
                    "ordem": ordem,
                    "processo_artigo_id": c.lastrowid,
                    "marca_id": marca_id,
                    "artigo_catalogo_id": artigo_catalogo_id,
                }
            )

        conn.commit()
        return processo_id, numero_processo, processo_artigos
    finally:
        conn.close()


def criar_rfq(
    fornecedor_id,
    data,
    artigos,
    referencia,
    cliente_id=None,
    processo_id=None,
    numero_processo=None,
    processo_artigos=None,
    requisitos_fornecedor: dict | None = None,
):
    """Criar nova RFQ"""
    conn = obter_conexao()
    c = conn.cursor()

    try:
        utilizador_id = st.session_state.get("user_id")

        ordem_para_processo: dict[int, int | None] = {}
        if processo_id is None or numero_processo is None or processo_artigos is None:
            processo_id, numero_processo, processo_artigos = criar_processo_com_artigos(
                artigos, cliente_id
            )
            ordem_para_processo = {
                item.get("ordem", idx + 1): item.get("processo_artigo_id")
                for idx, item in enumerate(processo_artigos)
                if item.get("processo_artigo_id")
            }
        else:
            # Garantir que temos um mapa por ordem caso não exista nos artigos
            ordem_para_processo = {
                item.get("ordem", idx + 1): item.get("processo_artigo_id")
                for idx, item in enumerate(processo_artigos)
                if item.get("processo_artigo_id")
            }

        if processo_id and cliente_id is not None:
            c.execute(
                """
                UPDATE processo
                   SET cliente_id = ?, utilizador_id = COALESCE(utilizador_id, ?)
                 WHERE id = ?
                   AND COALESCE(cliente_id, -1) != COALESCE(?, -1)
                """,
                (cliente_id, utilizador_id, processo_id, cliente_id),
            )

        referencia_limpa = (referencia or "").strip()
        if processo_id and referencia_limpa:
            c.execute(
                """
                UPDATE processo
                   SET ref_cliente = ?,
                       utilizador_id = COALESCE(utilizador_id, ?)
                 WHERE id = ?
                """,
                (referencia_limpa, utilizador_id, processo_id),
            )

        if processo_id and utilizador_id is not None:
            c.execute(
                """
                UPDATE processo
                   SET utilizador_id = ?
                 WHERE id = ?
                   AND COALESCE(utilizador_id, -1) != COALESCE(?, -1)
                """,
                (utilizador_id, processo_id, utilizador_id),
            )

        dados_requisito = requisitos_fornecedor or {}
        cliente_final_nome = (dados_requisito.get("cliente_final") or "").strip()
        cliente_final_pais = (dados_requisito.get("pais") or "").strip()
        cliente_final_nome_db = cliente_final_nome or None
        cliente_final_pais_db = cliente_final_pais or None
        estado_padrao = "pendente"
        estado_id = ensure_estado(estado_padrao, cursor=c)

        def _executar_insercao(conexao: sqlite3.Connection) -> int:
            cursor = conexao.cursor()
            data_atualizacao = data.isoformat()
            if engine.dialect.name == "sqlite":
                cursor.execute(
                    """
                    INSERT INTO rfq (
                        processo_id,
                        fornecedor_id,
                        cliente_final_nome,
                        cliente_final_pais,
                        data_atualizacao,
                        estado_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        processo_id,
                        fornecedor_id,
                        cliente_final_nome_db,
                        cliente_final_pais_db,
                        data_atualizacao,
                        estado_id,
                    ),
                )
                rfq_pk = cursor.lastrowid
            else:
                cursor.execute(
                    """
                    INSERT INTO rfq (
                        processo_id,
                        fornecedor_id,
                        cliente_final_nome,
                        cliente_final_pais,
                        data_atualizacao,
                        estado_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?) RETURNING id
                    """,
                    (
                        processo_id,
                        fornecedor_id,
                        cliente_final_nome_db,
                        cliente_final_pais_db,
                        data_atualizacao,
                        estado_id,
                    ),
                )
                rfq_pk = cursor.fetchone()[0]

            for ordem, art in enumerate(artigos, 1):
                if art.get("descricao", "").strip():
                    marca_art = (art.get("marca") or "").strip()
                    descricao_art = garantir_marca_primeira_palavra(
                        art.get("descricao", ""), marca_art
                    )
                    art["descricao"] = descricao_art
                    art["marca"] = marca_art
                    art["artigo_num"] = (art.get("artigo_num") or "").strip()
                    processo_artigo_id = art.get("processo_artigo_id")
                    if not processo_artigo_id and processo_artigos:
                        processo_artigo_id = ordem_para_processo.get(ordem)
                        if not processo_artigo_id and ordem - 1 < len(processo_artigos):
                            processo_artigo_id = processo_artigos[ordem - 1].get(
                                "processo_artigo_id"
                            )
                    marca_id = get_marca_id(marca_art, cursor=cursor)
                    artigo_catalogo_id = get_artigo_catalogo_id(
                        art.get("artigo_num"), cursor=cursor
                    )
                    unidade_nome = art.get("unidade", "Peças") or "Peças"
                    try:
                        unidade_id = ensure_unidade(unidade_nome, cursor=cursor)
                    except ValueError:
                        unidade_id = ensure_unidade("Peças", cursor=cursor)

                    cursor.execute(
                        """
                        INSERT INTO artigo (rfq_id, artigo_num, descricao, quantidade,
                                          unidade_id, especificacoes, ordem,
                                          processo_artigo_id, marca_id, artigo_catalogo_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rfq_pk,
                            art.get("artigo_num", ""),
                            descricao_art,
                            art.get("quantidade", 1),
                            unidade_id,
                            art.get("especificacoes", ""),
                            ordem,
                            processo_artigo_id,
                            marca_id,
                            artigo_catalogo_id,
                        ),
                    )

            conexao.commit()
            return rfq_pk

        limpeza_migracao_executada = False
        while True:
            try:
                rfq_id = _executar_insercao(conn)
                break
            except sqlite3.OperationalError as db_err:
                # Algumas instalações antigas podem ter ficado com uma tabela
                # temporária ``rfq_old`` quando uma migração falhou a meio.
                # A criação da nova cotação terminava com o erro
                # ``no such table: main.rfq_old`` e não havia nova tentativa de
                # inserção após limpar o esquema.  Este ciclo garante que
                # executamos a rotina de migração apenas uma vez e voltamos a
                # tentar a inserção logo de seguida.
                if "rfq_old" in str(db_err).lower() and not limpeza_migracao_executada:
                    limpeza_migracao_executada = True
                    conn.rollback()
                    conn.close()
                    criar_base_dados_completa()
                    conn = obter_conexao()
                    continue
                raise

        # Gerar PDF
        gerar_e_armazenar_pdf(rfq_id, fornecedor_id, data, artigos)
        # Enviar pedido por email ao fornecedor
        envio_email = enviar_email_pedido_fornecedor(rfq_id)

        invalidate_overview_caches()
        return rfq_id, numero_processo, processo_id, processo_artigos, envio_email
    except Exception as e:
        conn.rollback()
        if "UNIQUE" in str(e).upper():
            st.error("Erro ao criar RFQ: referência já existente.")
        else:
            st.error(f"Erro ao criar RFQ: {str(e)}")
        return None, None, None, None, None
    finally:
        conn.close()


@st.cache_data(show_spinner=False, ttl=30)
def obter_todas_cotacoes(
    filtro_referencia: str = "",
    estado: str | None = None,
    fornecedor_id: int | None = None,
    utilizador_id: int | None = None,
    page: int | None = None,
    page_size: int = 10,
    return_total: bool = False,
):
    """Obter cotações com filtros opcionais e suporte para paginação."""

    try:
        conn = obter_conexao()
        c = conn.cursor()

        base_query = """
            SELECT rfq.id,
                   rfq.processo_id,
                   rfq.data_atualizacao,
                   COALESCE(fornecedor.nome, 'Fornecedor desconhecido'),
                   COALESCE(estado.nome, 'pendente'),
                   COALESCE(processo.numero, 'Sem processo'),
                   COALESCE(processo.ref_cliente, ''),
                   COUNT(artigo.id) as num_artigos,
                   COALESCE(cliente.nome, ''),
                   COALESCE(cliente.email, ''),
                   u.nome
            FROM rfq
            LEFT JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
            LEFT JOIN processo ON rfq.processo_id = processo.id
            LEFT JOIN cliente ON processo.cliente_id = cliente.id
            LEFT JOIN utilizador u ON processo.utilizador_id = u.id
            LEFT JOIN estado ON rfq.estado_id = estado.id
            LEFT JOIN artigo ON rfq.id = artigo.rfq_id
        """

        conditions: list[str] = []
        params: list = []

        if filtro_referencia:
            conditions.append("processo.ref_cliente LIKE ?")
            params.append(f"%{filtro_referencia}%")

        if estado:
            conditions.append("COALESCE(estado.nome, 'pendente') = ?")
            params.append(estado)

        if fornecedor_id:
            conditions.append("rfq.fornecedor_id = ?")
            params.append(fornecedor_id)

        if utilizador_id is not None:
            conditions.append("processo.utilizador_id = ?")
            params.append(utilizador_id)

        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)

        base_query += " GROUP BY rfq.id ORDER BY rfq.data_atualizacao DESC"

        query = base_query
        query_params = list(params)

        if page is not None:
            query += " LIMIT ? OFFSET ?"
            query_params.extend([page_size, page * page_size])

        c.execute(query, query_params)
        resultados = c.fetchall()

        cotacoes = [
            {
                "id": row[0],
                "processo_id": row[1],
                "data": row[2],
                "fornecedor": row[3],
                "estado": row[4],
                "processo": row[5],
                "referencia": row[6],
                "num_artigos": row[7],
                "nome_solicitante": row[8] if row[8] else "",
                "email_solicitante": row[9] if row[9] else "",
                "cliente_nome": row[8] if row[8] else "",
                "cliente_email": row[9] if row[9] else "",
                "criador": row[10] if row[10] else "",
            }
            for row in resultados
        ]

        if return_total:
            count_query = """
                SELECT COUNT(*)
                  FROM rfq
                  LEFT JOIN processo ON rfq.processo_id = processo.id
                  LEFT JOIN estado ON rfq.estado_id = estado.id
            """
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions)
            c.execute(count_query, params)
            total = c.fetchone()[0]
            conn.close()
            return cotacoes, total

        conn.close()
        return cotacoes

    except Exception as e:
        print(f"Erro ao obter cotações: {e}")
        return []

def obter_detalhes_cotacao(rfq_id):
    """Obter detalhes completos de uma cotação"""
    try:
        conn = obter_conexao()
        c = conn.cursor()
        
        c.execute(
            """
            SELECT rfq.id,
                   rfq.fornecedor_id,
                   rfq.data_atualizacao,
                   COALESCE(estado.nome, 'pendente'),
                   COALESCE(processo.ref_cliente, ''),
                   COALESCE(processo.numero, ''),
                   COALESCE(cliente.nome, ''),
                   COALESCE(cliente.email, ''),
                   COALESCE(fornecedor.nome, 'Fornecedor desconhecido'),
                   processo.utilizador_id,
                   COALESCE(rfq.cliente_final_nome, ''),
                   COALESCE(rfq.cliente_final_pais, '')
              FROM rfq
              LEFT JOIN fornecedor ON rfq.fornecedor_id = fornecedor.id
              LEFT JOIN processo ON rfq.processo_id = processo.id
              LEFT JOIN cliente ON processo.cliente_id = cliente.id
              LEFT JOIN estado ON rfq.estado_id = estado.id
             WHERE rfq.id = ?
        """,
            (rfq_id,)
        )
        info = c.fetchone()
        
        if not info:
            conn.close()
            return None
        
        c.execute(
            """
            SELECT a.id,
                   COALESCE(a.artigo_num, ''),
                   a.descricao,
                   a.quantidade,
                   COALESCE(u.nome, ''),
                   COALESCE(a.especificacoes, ''),
                   COALESCE(m.marca, '')
              FROM artigo a
              LEFT JOIN unidade u ON a.unidade_id = u.id
              LEFT JOIN marca m ON a.marca_id = m.id
             WHERE a.rfq_id = ?
             ORDER BY a.ordem, a.id
            """,
            (rfq_id,),
        )
        artigos = [
            {
                "id": row[0],
                "artigo_num": row[1],
                "descricao": row[2],
                "quantidade": row[3],
                "unidade": row[4],
                "especificacoes": row[5],
                "marca": row[6],
            }
            for row in c.fetchall()
        ]
        
        conn.close()
        
        return {
            "id": info[0],
            "fornecedor_id": info[1],
            "data": info[2],
            "estado": info[3],
            "referencia": info[4],
            "processo_numero": info[5],
            "nome_solicitante": info[6],
            "email_solicitante": info[7],
            "fornecedor": info[8],
            "utilizador_id": info[9],
            "cliente_final_nome": info[10],
            "cliente_final_pais": info[11],
            "artigos": artigos,
        }
        
    except Exception as e:
        print(f"Erro ao obter detalhes: {e}")
        return None

def eliminar_cotacao(rfq_id):
    """Eliminar cotação e todos os dados relacionados"""
    conn = obter_conexao()
    c = conn.cursor()
    
    try:
        c.execute("DELETE FROM resposta_fornecedor WHERE rfq_id = ?", (rfq_id,))
        c.execute("DELETE FROM resposta_custos WHERE rfq_id = ?", (rfq_id,))
        c.execute("DELETE FROM artigo WHERE rfq_id = ?", (rfq_id,))
        processo_id = resolve_processo_id(rfq_id, cursor=c)
        if processo_id is not None:
            c.execute(
                "DELETE FROM pdf_storage WHERE processo_id = ?",
                (str(processo_id),),
            )
        c.execute("DELETE FROM rfq WHERE id = ?", (rfq_id,))
        conn.commit()
        invalidate_overview_caches()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao eliminar cotação: {str(e)}")
        return False
    finally:
        conn.close()

# ========================== ARQUIVO DE COTAÇÕES ==========================

def arquivar_cotacao(rfq_id):
    """Arquivar cotação alterando o estado para 'arquivada'"""
    conn = obter_conexao()
    c = conn.cursor()
    try:
        estado_id = ensure_estado("arquivada", cursor=c)
        c.execute(
            "UPDATE rfq SET estado_id = ? WHERE id = ?",
            (estado_id, rfq_id),
        )
        conn.commit()
        invalidate_overview_caches()
        return True
    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao arquivar cotação: {str(e)}")
        return False
    finally:
        conn.close()

# ========================== FUNÇÕES DE GESTÃO DE RESPOSTAS ==========================

def guardar_respostas(
    rfq_id,
    respostas,
    custo_envio=0.0,
    custo_embalagem=0.0,
    observacoes="",
):
    """Guardar respostas do fornecedor e devolver informação para envio ao cliente."""
    conn = obter_conexao()
    c = conn.cursor()

    try:
        # Obter fornecedor e processo associados à RFQ
        c.execute("SELECT fornecedor_id, processo_id FROM rfq WHERE id = ?", (rfq_id,))
        resultado = c.fetchone()

        if not resultado:
            st.error("RFQ não encontrada!")
            return False, None

        fornecedor_id, processo_id = resultado

        total_custos = sum(item[1] for item in respostas if item[1] > 0)

        # Obter margem para cada artigo baseada na marca
        for item in respostas:
            (
                artigo_id,
                custo,
                validade_preco,
                peso,
                hs_code,
                pais_origem,
                descricao_editada,
                quantidade_final,
                prazo,
            ) = item

            # Obter marca e artigo do processo associado
            c.execute(
                """
                SELECT COALESCE(m.marca, ''), a.processo_artigo_id
                  FROM artigo a
                  LEFT JOIN marca m ON a.marca_id = m.id
                 WHERE a.id = ?
                """,
                (artigo_id,),
            )
            marca_result = c.fetchone()
            marca = marca_result[0] if marca_result else None
            processo_artigo_id = marca_result[1] if marca_result and len(marca_result) > 1 else None

            proporcao = (custo / total_custos) if total_custos else 0
            custo_total = custo + (custo_envio + custo_embalagem) * proporcao

            # Obter margem configurada para a marca
            margem = obter_margem_para_marca(fornecedor_id, marca)
            preco_venda = custo_total * (1 + margem / 100)
            moeda_codigo = "EUR"

            c.execute(
                """
                INSERT OR REPLACE INTO resposta_fornecedor
                (fornecedor_id, rfq_id, artigo_id, descricao, custo, prazo_entrega,
                 peso, hs_code, pais_origem, moeda, preco_venda,
                 quantidade_final, observacoes, validade_preco)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fornecedor_id,
                    rfq_id,
                    artigo_id,
                    descricao_editada,
                    custo_total,
                    prazo,
                    peso,
                    hs_code,
                    pais_origem,
                    moeda_codigo,
                    preco_venda,
                    quantidade_final,
                    observacoes,
                    validade_preco,
                ),
            )

        # Guardar custos adicionais
        c.execute(
            "INSERT OR REPLACE INTO resposta_custos (rfq_id, custo_envio, custo_embalagem) VALUES (?, ?, ?)",
            (rfq_id, custo_envio, custo_embalagem),
        )

        # Atualizar estado da RFQ
        estado_id = ensure_estado("respondido", cursor=c)
        c.execute(
            "UPDATE rfq SET estado_id = ? WHERE id = ?",
            (estado_id, rfq_id),
        )

        # Obter informações para email
        c.execute(
            """
            SELECT COALESCE(cli.nome, ''),
                   COALESCE(cli.email, ''),
                   COALESCE(proc.ref_cliente, ''),
                   proc.numero,
                   COALESCE(cli.nome, ''),
                   COALESCE(cli.email, '')
              FROM rfq r
              LEFT JOIN processo proc ON r.processo_id = proc.id
              LEFT JOIN cliente cli ON proc.cliente_id = cli.id
             WHERE r.id = ?
            """,
            (rfq_id,),
        )
        rfq_info_row = c.fetchone()

        rfq_info = {
            "nome_solicitante": rfq_info_row[0] if rfq_info_row else "",
            "email_solicitante": rfq_info_row[1] if rfq_info_row else "",
            "referencia": rfq_info_row[2] if rfq_info_row else "",
            "numero_processo": rfq_info_row[3] if rfq_info_row else "",
            "cliente_nome": rfq_info_row[4] if rfq_info_row else "",
            "cliente_email": rfq_info_row[5] if rfq_info_row else "",
        }

        conn.commit()
        invalidate_overview_caches()

        return True, {
            "processo_id": processo_id,
            "rfq_info": rfq_info,
        }

    except Exception as e:
        conn.rollback()
        st.error(f"Erro ao guardar respostas: {str(e)}")
        return False, None
    finally:
        conn.close()

def obter_respostas_cotacao(rfq_id):
    """Obter respostas de uma cotação"""
    conn = obter_conexao()
    c = conn.cursor()
    
    c.execute(
        """
        SELECT rf.id,
               rf.fornecedor_id,
               rf.rfq_id,
               rf.artigo_id,
               rf.descricao,
               rf.custo,
               rf.prazo_entrega,
               rf.quantidade_final,
               rf.peso,
               rf.hs_code,
               rf.pais_origem,
               rf.moeda,
               rf.preco_venda,
               rf.observacoes,
               rf.data_resposta,
               rf.validade_preco,
               a.descricao AS descricao_original,
               a.quantidade AS quantidade_original,
               a.processo_artigo_id,
               fornecedor.nome AS fornecedor_nome,
               COALESCE(u.nome, '') AS unidade_nome,
               COALESCE(m.marca, '') AS marca_nome
          FROM resposta_fornecedor rf
          JOIN artigo a ON rf.artigo_id = a.id
          LEFT JOIN fornecedor ON fornecedor.id = rf.fornecedor_id
          LEFT JOIN unidade u ON a.unidade_id = u.id
          LEFT JOIN marca m ON a.marca_id = m.id
         WHERE rf.rfq_id = ?
         ORDER BY a.ordem, rf.artigo_id
        """,
        (rfq_id,),
    )

    respostas = []
    for row in c.fetchall():
        respostas.append(
            {
                "id": row[0],
                "fornecedor_id": row[1],
                "rfq_id": row[2],
                "artigo_id": row[3],
                "descricao": row[4] if row[4] else row[16],
                "custo": row[5],
                "prazo_entrega": row[6],
                "quantidade_final": row[7] if row[7] else row[17],
                "peso": row[8],
                "hs_code": row[9],
                "pais_origem": row[10],
                "moeda": row[11],
                "preco_venda": row[12],
                "observacoes": row[13],
                "data_resposta": row[14],
                "validade_preco": row[15],
                "descricao_original": row[16],
                "quantidade_original": row[17],
                "processo_artigo_id": row[18],
                "fornecedor_nome": row[19] or "",
                "unidade": row[20],
                "marca": row[21],
            }
        )

    conn.close()
    return respostas


def obter_respostas_processo(processo_id):
    """Obter respostas registadas em todas as RFQs de um processo."""

    conn = obter_conexao()
    c = conn.cursor()
    c.execute(
        "SELECT id FROM rfq WHERE processo_id = ?",
        (processo_id,),
    )
    rfq_ids = [row[0] for row in c.fetchall()]
    conn.close()

    respostas: dict[int, dict] = {}
    for rfq_id in rfq_ids:
        for resposta in obter_respostas_cotacao(rfq_id):
            respostas.setdefault(resposta["id"], resposta)

    return sorted(
        respostas.values(),
        key=lambda item: (
            item.get("processo_artigo_id") or 10**6,
            item.get("artigo_id") or 0,
            item["id"],
        ),
    )

def obter_respostas_por_processo(processo_id):
    """Agrega respostas de todos os fornecedores para um processo."""

    conn = obter_conexao()
    c = conn.cursor()

    c.execute(
        """
        SELECT pa.id,
               pa.artigo_num,
               pa.descricao,
               pa.quantidade,
               COALESCE(u.nome, ''),
               pa.marca,
               pa.ordem,
               rf.id as resposta_id,
               rf.preco_venda,
               rf.custo,
               rf.prazo_entrega,
               rf.moeda,
               rf.quantidade_final,
               rf.fornecedor_id,
               f.nome as fornecedor_nome,
               r.id as rfq_id,
               COALESCE(e.nome, 'pendente') as estado_rfq,
               rf.validade_preco
        FROM processo_artigo pa
        LEFT JOIN unidade u ON pa.unidade_id = u.id
        LEFT JOIN artigo a ON a.processo_artigo_id = pa.id
        LEFT JOIN rfq r ON a.rfq_id = r.id
        LEFT JOIN estado e ON r.estado_id = e.id
        LEFT JOIN resposta_fornecedor rf ON rf.artigo_id = a.id AND rf.rfq_id = r.id
        LEFT JOIN fornecedor f ON rf.fornecedor_id = f.id
        WHERE pa.processo_id = ?
        ORDER BY pa.ordem, fornecedor_nome
        """,
        (processo_id,),
    )

    artigos: dict[int, dict] = {}
    fornecedores_estado: dict[int, dict] = {}

    for row in c.fetchall():
        (
            processo_artigo_id,
            artigo_num,
            descricao,
            quantidade,
            unidade,
            marca,
            ordem,
            resposta_id,
            preco_venda,
            custo,
            prazo,
            moeda,
            quantidade_final,
            fornecedor_id,
            fornecedor_nome,
            rfq_id,
            estado_rfq,
            validade_preco,
        ) = row

        artigo_info = artigos.setdefault(
            processo_artigo_id,
            {
                "processo_artigo_id": processo_artigo_id,
                "artigo_num": artigo_num or "",
                "descricao": descricao,
                "quantidade": quantidade,
                "unidade": unidade,
                "marca": marca or "",
                "ordem": ordem,
                "respostas": [],
            },
        )

        if fornecedor_id:
            fornecedor_entry = fornecedores_estado.setdefault(
                fornecedor_id,
                {
                    "id": fornecedor_id,
                    "nome": fornecedor_nome or "Fornecedor",
                    "estado": estado_rfq or "pendente",
                },
            )
            if estado_rfq and estado_rfq != fornecedor_entry["estado"]:
                fornecedor_entry["estado"] = estado_rfq

        if resposta_id:
            artigo_info["respostas"].append(
                {
                    "resposta_id": resposta_id,
                    "preco_venda": preco_venda,
                    "custo": custo,
                    "prazo": prazo,
                    "moeda": moeda,
                    "quantidade_final": quantidade_final,
                    "fornecedor_id": fornecedor_id,
                    "fornecedor_nome": fornecedor_nome or "",
                    "rfq_id": rfq_id,
                    "validade_preco": validade_preco,
                }
            )

    c.execute(
        """
        SELECT rfq.fornecedor_id, fornecedor.nome, COALESCE(estado.nome, 'pendente')
          FROM rfq
          LEFT JOIN fornecedor ON fornecedor.id = rfq.fornecedor_id
          LEFT JOIN estado ON rfq.estado_id = estado.id
         WHERE rfq.processo_id = ?
        """,
        (processo_id,),
    )
    for fornecedor_id, nome, estado in c.fetchall():
        fornecedores_estado.setdefault(
            fornecedor_id,
            {
                "id": fornecedor_id,
                "nome": nome or "Fornecedor",
                "estado": estado or "pendente",
            },
        )

    conn.close()

    artigos_ordenados = sorted(artigos.values(), key=lambda x: x["ordem"])
    fornecedores_lista = sorted(fornecedores_estado.values(), key=lambda x: x["nome"].lower())

    return artigos_ordenados, fornecedores_lista


def procurar_processos_por_termo(termo: str, limite: int = 25):
    """Pesquisa processos pelo número ou por referências de cliente associadas."""

    termo = (termo or "").strip()
    if not termo:
        return []

    conn = obter_conexao()
    c = conn.cursor()

    like_term = f"%{termo}%"
    c.execute(
        """
        SELECT processo.id,
               processo.numero,
               COALESCE(processo.descricao, ''),
               processo.data_abertura,
               COALESCE(processo.ref_cliente, ''),
               COUNT(DISTINCT rfq.id) AS total_pedidos
          FROM processo
          LEFT JOIN rfq ON rfq.processo_id = processo.id
         WHERE processo.numero LIKE ? OR processo.ref_cliente LIKE ?
         GROUP BY processo.id
         ORDER BY processo.data_abertura DESC, processo.numero DESC
         LIMIT ?
        """,
        (like_term, like_term, limite),
    )

    resultados = [
        {
            "id": row[0],
            "numero": row[1],
            "descricao": row[2] or "",
            "data_abertura": row[3],
            "referencia": row[4] or "",
            "estado": "",
            "total_pedidos": row[5] or 0,
        }
        for row in c.fetchall()
    ]

    conn.close()
    return resultados


def obter_detalhes_processo(processo_id: int):
    """Obtém informação consolidada de um processo (artigos e pedidos a fornecedores)."""

    conn = obter_conexao()
    c = conn.cursor()

    c.execute(
        "SELECT id, numero, COALESCE(descricao, ''), data_abertura, COALESCE(ref_cliente, '') FROM processo WHERE id = ?",
        (processo_id,),
    )
    row = c.fetchone()

    if not row:
        conn.close()
        return None

    processo_info = {
        "id": row[0],
        "numero": row[1],
        "descricao": row[2] or "",
        "data_abertura": row[3],
        "referencia": row[4] or "",
    }

    c.execute(
        """
        SELECT pa.id,
               COALESCE(pa.artigo_num, ''),
               pa.descricao,
               pa.quantidade,
               COALESCE(u.nome, ''),
               COALESCE(pa.marca, ''),
               pa.ordem
          FROM processo_artigo pa
          LEFT JOIN unidade u ON pa.unidade_id = u.id
         WHERE pa.processo_id = ?
         ORDER BY pa.ordem, pa.id
        """,
        (processo_id,),
    )

    artigos_processo = [
        {
            "id": artigo_row[0],
            "artigo_num": artigo_row[1] or "",
            "descricao": artigo_row[2],
            "quantidade": artigo_row[3],
            "unidade": artigo_row[4],
            "marca": artigo_row[5] or "",
            "ordem": artigo_row[6],
        }
        for artigo_row in c.fetchall()
    ]

    c.execute(
        """
        SELECT rfq.id,
               COALESCE(processo.ref_cliente, ''),
               COALESCE(estado.nome, 'pendente'),
               rfq.data_atualizacao,
               COALESCE(fornecedor.nome, 'Fornecedor desconhecido') AS fornecedor_nome,
               '' AS observacoes,
               COALESCE(cliente.nome, ''),
               COALESCE(cliente.email, ''),
               processo.utilizador_id
          FROM rfq
          LEFT JOIN fornecedor ON fornecedor.id = rfq.fornecedor_id
          LEFT JOIN processo ON processo.id = rfq.processo_id
          LEFT JOIN cliente ON cliente.id = processo.cliente_id
          LEFT JOIN estado ON rfq.estado_id = estado.id
         WHERE rfq.processo_id = ?
         ORDER BY fornecedor_nome COLLATE NOCASE, rfq.data_atualizacao
        """,
        (processo_id,),
    )

    rfqs_rows = c.fetchall()
    rfq_ids = [rfq_row[0] for rfq_row in rfqs_rows]

    artigos_por_rfq: dict[int, list[dict]] = {rfq_id: [] for rfq_id in rfq_ids}
    respostas_por_rfq: dict[int, int] = {rfq_id: 0 for rfq_id in rfq_ids}

    if rfq_ids:
        placeholders = ",".join(["?"] * len(rfq_ids))

        c.execute(
            f"""
            SELECT a.rfq_id,
                   a.id,
                   COALESCE(a.artigo_num, ''),
                   a.descricao,
                   a.quantidade,
                   COALESCE(u.nome, ''),
                   COALESCE(m.marca, ''),
                   a.ordem,
                   a.processo_artigo_id
              FROM artigo a
              LEFT JOIN unidade u ON a.unidade_id = u.id
              LEFT JOIN marca m ON a.marca_id = m.id
             WHERE a.rfq_id IN ({placeholders})
             ORDER BY a.rfq_id, a.ordem, a.id
            """,
            rfq_ids,
        )

        for artigo_row in c.fetchall():
            artigos_por_rfq.setdefault(artigo_row[0], []).append(
                {
                    "id": artigo_row[1],
                    "artigo_num": artigo_row[2] or "",
                    "descricao": artigo_row[3],
                    "quantidade": artigo_row[4],
                    "unidade": artigo_row[5],
                    "marca": artigo_row[6] or "",
                    "ordem": artigo_row[7],
                    "processo_artigo_id": artigo_row[8],
                }
            )

        c.execute(
            f"""
            SELECT rfq_id, COUNT(*)
            FROM resposta_fornecedor
            WHERE rfq_id IN ({placeholders})
            GROUP BY rfq_id
            """,
            rfq_ids,
        )

        for rfq_id, total in c.fetchall():
            respostas_por_rfq[rfq_id] = total or 0

    conn.close()

    rfqs = []
    for rfq_row in rfqs_rows:
        rfq_id = rfq_row[0]
        artigos_rfq = sorted(
            artigos_por_rfq.get(rfq_id, []),
            key=lambda x: (x.get("ordem") or 0, x.get("id")),
        )
        artigos_clientes = [
            artigo for artigo in artigos_rfq if artigo.get("processo_artigo_id")
        ]
        total_artigos_cliente = len(artigos_clientes)
        rfqs.append(
            {
                "id": rfq_id,
                "referencia": rfq_row[1],
                "estado": rfq_row[2] or "pendente",
                "data": rfq_row[3],
                "fornecedor": rfq_row[4] or "Fornecedor desconhecido",
                "observacoes": rfq_row[5] or "",
                "nome_solicitante": rfq_row[6] or "",
                "email_solicitante": rfq_row[7] or "",
                "cliente": rfq_row[6] or "",
                "utilizador_id": rfq_row[8],
                "artigos": artigos_rfq,
                "total_respostas": respostas_por_rfq.get(rfq_id, 0),
                "total_artigos_cliente": total_artigos_cliente,
                "artigos_enviados_cliente": 0,
            }
        )

    respondidas = sum(
        1
        for rfq in rfqs
        if (rfq.get("estado") or "").lower() == "respondido" or rfq.get("total_respostas", 0) > 0
    )

    return {
        "processo": processo_info,
        "artigos": sorted(artigos_processo, key=lambda x: (x.get("ordem") or 0, x.get("id"))),
        "rfqs": rfqs,
        "total_rfqs": len(rfqs),
        "respondidas": respondidas,
        "cliente_envios": {"total": 0, "enviados": 0},
    }

# ========================== FUNÇÕES DE GESTÃO DE MARGENS ==========================

def obter_margem_para_marca(fornecedor_id, marca):
    """Obter margem configurada para fornecedor/marca específica.

    Caso não exista configuração para a marca/fornecedor indicados é
    devolvido ``0.0``.
    """
    try:
        marca_limpa = (marca or "").strip()
        if not marca_limpa:
            return 0.0

        marca_normalizada = marca_limpa.casefold()

        conn = obter_conexao()
        c = conn.cursor()
        c.execute(
            """
            SELECT COALESCE(margem, 0.0)
              FROM marca
             WHERE fornecedor_id = ?
               AND marca_normalizada = ?
             LIMIT 1
            """,
            (fornecedor_id, marca_normalizada),
        )
        result = c.fetchone()
        conn.close()
        if result:
            return float(result[0])
        return 0.0

    except Exception as e:
        print(f"Erro ao obter margem: {e}")
        return 0.0

def configurar_margem_marca(fornecedor_id, marca, margem_percentual):
    """Configurar margem para fornecedor/marca"""
    try:
        marca_limpa = (marca or "").strip()
        if not marca_limpa:
            return False

        marca_normalizada = marca_limpa.casefold()

        conn = obter_conexao()
        c = conn.cursor()

        c.execute(
            """
            UPDATE marca
               SET margem = ?
             WHERE fornecedor_id = ?
               AND marca_normalizada = ?
            """,
            (margem_percentual, fornecedor_id, marca_normalizada),
        )

        conn.commit()
        atualizados = c.rowcount
        conn.close()
        return atualizados > 0
        
    except Exception as e:
        print(f"Erro ao configurar margem: {e}")
        return False

# ========================== FUNÇÕES DE EMAIL ==========================

def enviar_email_orcamento(
    email_destino,
    nome_cliente,
    referencia_cliente,
    numero_cotacao,
    rfq_id,
    observacoes=None,
):
    """Enviar email com o orçamento ao cliente"""
    try:
        print(f"⏳ Preparando para enviar email para {email_destino}...")

        # Obter PDF do cliente
        pdf_bytes = obter_pdf_da_db(rfq_id, "cliente")
        if not pdf_bytes:
            print("❌ PDF do cliente não encontrado")
            st.error("PDF não encontrado para anexar ao e-mail")
            return False
        
        config_email = get_system_email_config()
        smtp_server = config_email["server"]
        smtp_port = config_email["port"]

        # Credenciais do utilizador atual
        current_user = obter_utilizador_por_id(st.session_state.get("user_id"))
        if current_user and current_user[4] and current_user[6]:
            email_user = current_user[4]
            email_password = current_user[6]
            nome_utilizador = current_user[3]
        else:
            st.error(
                "Configure o seu email e palavra-passe no perfil."
            )
            return False

        print(f"🔧 Configurações SMTP: {smtp_server}:{smtp_port}")

        if observacoes is None:
            conn = obter_conexao()
            c = conn.cursor()
            c.execute(
                "SELECT observacoes FROM resposta_fornecedor WHERE rfq_id = ? AND observacoes IS NOT NULL AND observacoes != '' LIMIT 1",
                (rfq_id,),
            )
            row = c.fetchone()
            conn.close()
            if row:
                observacoes = row[0]

        corpo = f"""
        Dear {nome_cliente},

        Please find attached our offer No {numero_cotacao}
        """
        if observacoes:
            corpo += f"{observacoes}\n\n"
        corpo += """We remain at your disposal for any further clarification.

        Best regards,
                {nome_utilizador}
        """

        assunto = f"Quotation {numero_cotacao}"
        if referencia_cliente:
            assunto += f" ({referencia_cliente})"

        print(f"🚀 Tentando enviar email para {email_destino}...")
        send_email(
            email_destino,
            assunto,
            corpo,
            pdf_bytes=pdf_bytes,
            pdf_filename=f"orcamento_{numero_cotacao}.pdf",
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            email_user=email_user,
            email_password=email_password,
        )
        print("✅ Email enviado com sucesso!")
        return True

    except Exception as e:
        print(f"❌ Erro ao enviar email: {str(e)}")
        st.error(f"Falha no envio: {str(e)}")
        return False


def enviar_email_pedido_fornecedor(rfq_id):
    """Envia por email o PDF de pedido ao fornecedor associado à RFQ.

    Retorna um dicionário com o estado do envio e uma mensagem legível.
    """

    resultado = {
        "sucesso": False,
        "mensagem": "",
        "fornecedor": "",
    }

    try:
        # Buscar fornecedor (nome+email), referência e número de processo
        conn = obter_conexao()
        c = conn.cursor()
        c.execute(
            """
            SELECT f.nome,
                   f.email,
                   COALESCE(p.ref_cliente, ''),
                   COALESCE(p.numero, ''),
                   r.cliente_final_nome,
                   r.cliente_final_pais,
                   r.fornecedor_id,
                   r.data_atualizacao
            FROM rfq r
            JOIN fornecedor f ON r.fornecedor_id = f.id
            LEFT JOIN processo p ON r.processo_id = p.id
            WHERE r.id = ?
            """,
            (rfq_id,),
        )
        row = c.fetchone()
        if not row:
            mensagem = "Fornecedor não encontrado para a RFQ."
            resultado["mensagem"] = mensagem
            st.warning(mensagem)
            return resultado

        (
            fornecedor_nome,
            fornecedor_email,
            referencia,
            numero_processo,
            cliente_final_nome,
            cliente_final_pais,
            fornecedor_id,
            data_atualizacao,
        ) = row
        resultado["fornecedor"] = fornecedor_nome or ""

        if not fornecedor_email:
            mensagem = (
                f"Email para {fornecedor_nome} não enviado: fornecedor sem email definido."
            )
            resultado["mensagem"] = mensagem
            st.info("Fornecedor sem email definido — não foi enviado o pedido.")
            return resultado

        # Obter PDF do pedido
        pdf_bytes = obter_pdf_da_db(rfq_id, "pedido")
        if not pdf_bytes:
            artigos_para_pdf: list[dict] = []
            try:
                c.execute(
                    """
                    SELECT artigo_num,
                           descricao,
                           quantidade,
                           unidade,
                           COALESCE(especificacoes, ''),
                           COALESCE(marca, '')
                      FROM artigo
                     WHERE rfq_id = ?
                     ORDER BY ordem, id
                    """,
                    (rfq_id,),
                )
                artigos_para_pdf = [
                    {
                        "artigo_num": artigo_row[0] or "",
                        "descricao": artigo_row[1] or "",
                        "quantidade": artigo_row[2],
                        "unidade": artigo_row[3] or "",
                        "especificacoes": artigo_row[4] or "",
                        "marca": artigo_row[5] or "",
                    }
                    for artigo_row in c.fetchall()
                ]
            except Exception:
                artigos_para_pdf = []

            data_pdf = None
            if data_atualizacao:
                try:
                    data_pdf = datetime.fromisoformat(str(data_atualizacao)).date()
                except ValueError:
                    data_pdf = None
            if data_pdf is None:
                data_pdf = datetime.now().date()

            pdf_bytes = gerar_e_armazenar_pdf(
                rfq_id,
                fornecedor_id,
                data_pdf,
                artigos_para_pdf,
            )

        if not pdf_bytes:
            mensagem = (
                f"Email para {fornecedor_nome} não enviado: PDF do pedido indisponível."
            )
            resultado["mensagem"] = mensagem
            st.error("PDF do pedido não encontrado para envio ao fornecedor.")
            return resultado

        config_email = get_system_email_config()
        smtp_server = config_email["server"]
        smtp_port = config_email["port"]

        current_user = obter_utilizador_por_id(st.session_state.get("user_id"))
        if current_user and current_user[4] and current_user[6]:
            email_user = current_user[4]
            email_password = current_user[6]
            nome_utilizador = current_user[3]
        else:
            mensagem = (
                f"Email para {fornecedor_nome} não enviado: configure o email do utilizador."
            )
            resultado["mensagem"] = mensagem
            st.error(
                "Configure o seu email e palavra-passe no perfil."
            )
            return resultado

        # Construir email
        referencia_interna = numero_processo or referencia
        referencia_texto = referencia if referencia else "—"
        processo_texto = numero_processo if numero_processo else "—"
        corpo = f"""Request for Quotation – {referencia_interna}

Dear {fornecedor_nome} Team,

Please find attached our Request for Quotation (RFQ) for internal process {processo_texto} (Reference: {referencia_texto}).

Kindly provide us with the following details:
- Unit price
- Delivery time
- HS Code
- Country of origin
- Weight
"""

        detalhes_extra: list[str] = []
        if cliente_final_nome:
            detalhes_extra.append(f"- Final client: {cliente_final_nome}")
        if cliente_final_pais:
            detalhes_extra.append(f"- Final client country: {cliente_final_pais}")

        if detalhes_extra:
            corpo += "\nAdditional information provided:\n" + "\n".join(detalhes_extra) + "\n"

        corpo += """

We look forward to receiving your quotation.
Thank you in advance for your prompt response.

{nome_utilizador}
"""
        assunto = f"Request for Quotation – {referencia_interna}"
        pdf_nome = referencia_interna.replace('/', '-') if referencia_interna else referencia_texto
        pdf_filename = f"pedido_{pdf_nome}.pdf" if pdf_nome else "pedido.pdf"

        send_email(
            fornecedor_email,
            assunto,
            corpo,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            email_user=email_user,
            email_password=email_password,
        )

        mensagem = f"Email para {fornecedor_nome} enviado com sucesso."
        resultado.update({"sucesso": True, "mensagem": mensagem})
        return resultado
    except Exception as e:
        mensagem = f"Email para {resultado['fornecedor'] or 'fornecedor'} não enviado: {e}".strip()
        resultado["mensagem"] = mensagem
        st.error(f"Falha ao enviar email ao fornecedor: {e}")
        return resultado
    finally:
        try:
            conn.close()  # type: ignore[has-type]
        except (AttributeError, NameError):
            pass

def guardar_pdf_uploads(rfq_id, tipo_pdf_base, ficheiros):
    """Guardar múltiplos PDFs na tabela ``pdf_storage`` associando-os ao processo."""

    if not ficheiros:
        return True

    try:
        conn = obter_conexao()
        c = conn.cursor()

        processo_id = resolve_processo_id(rfq_id, cursor=c)
        if processo_id is None:
            st.error("Processo associado ao PDF não encontrado.")
            conn.close()
            return False

        c.execute(
            """
            DELETE FROM pdf_storage
            WHERE processo_id = ? AND (
                tipo_pdf = ? OR tipo_pdf LIKE ?
            )
            """,
            (str(processo_id), tipo_pdf_base, f"{tipo_pdf_base}_%"),
        )

        for idx, (nome_ficheiro, bytes_) in enumerate(ficheiros, start=1):
            tipo_pdf = tipo_pdf_base if len(ficheiros) == 1 else f"{tipo_pdf_base}_{idx}"
            c.execute(
                """
                INSERT INTO pdf_storage (processo_id, tipo_pdf, pdf_data, tamanho_bytes, nome_ficheiro)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(processo_id), tipo_pdf, bytes_, len(bytes_), nome_ficheiro),
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Erro a guardar PDF: {e}")
        return False


def guardar_pdf_upload(rfq_id, tipo_pdf, nome_ficheiro, bytes_):
    """Compatibilidade retroativa para guardar um único PDF."""

    return guardar_pdf_uploads(rfq_id, tipo_pdf, [(nome_ficheiro, bytes_)])

# ========================== CLASSES PDF ==========================

class InquiryPDF(FPDF):
    """Gera PDF de pedido de cotação seguindo layout profissional"""

    DEFAULT_HEADER = {
        "title": "INQUIRY",
        "font": "Helvetica",
        "font_style": "B",
        "font_size": 16,
        "spacing": 4,
        "line_height": 5,
        "metadata_font": {"font": "Helvetica", "font_style": "B", "font_size": 10},
        "metadata_value_font": {
            "font": "Helvetica",
            "font_style": "",
            "font_size": 10,
        },
        "address_font": {"font": "Helvetica", "font_style": "", "font_size": 10},
        "company_font": {"font": "Helvetica", "font_style": "", "font_size": 9},
    }

    DEFAULT_BODY = {
        "font": "Helvetica",
        "font_style": "",
        "font_size": 11,
        "reference_spacing": 4,
        "intro_spacing": 4,
        "intro_text": "Please quote us for:",
        "greeting_named": "Dear Mr./Ms. {nome_contacto},",
        "greeting_generic": "Dear Sir/Madam,",
    }

    DEFAULT_TABLE = {
        "headers": ["Pos.", "Article No.", "Qty", "Unit", "Item"],
        "widths": [12, 25, 12, 14, 117],
        "alignments": ["C", "C", "C", "C", "L"],
        "font": "Helvetica",
        "font_style": "B",
        "font_size": 11,
        "header_height": 8,
        "header_spacing": 4,
        "row_font": "Helvetica",
        "row_font_style": "",
        "row_font_size": 10,
        "row_height": 5,
        "row_spacing": 3,
    }

    def __init__(self, config=None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.cfg = config or {}
        self.set_margins(15, 15, 15)
        self.set_auto_page_break(auto=True, margin=18)
        self.recipient = {}
        self.final_client_name = ""
        self.final_client_country = ""

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_cfg(source, default):
        if not isinstance(default, dict):
            return source if source is not None else default

        merged = {key: (value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value)
                  for key, value in default.items()}
        if isinstance(source, dict):
            for key, value in source.items():
                if isinstance(value, dict):
                    merged[key] = value.copy()
                elif isinstance(value, list):
                    merged[key] = list(value)
                else:
                    merged[key] = value
        return merged

    def _header_cfg(self):
        return self._merge_cfg(self.cfg.get("header"), self.DEFAULT_HEADER)

    def _body_cfg(self):
        return self._merge_cfg(self.cfg.get("body"), self.DEFAULT_BODY)

    def _table_cfg(self):
        return self._merge_cfg(self.cfg.get("table"), self.DEFAULT_TABLE)

    @staticmethod
    def _font_tuple(font_cfg, fallback):
        if isinstance(font_cfg, dict):
            return (
                font_cfg.get("font", fallback[0]),
                font_cfg.get("font_style", fallback[1]),
                font_cfg.get("font_size", fallback[2]),
            )
        return fallback

    # ------------------------------------------------------------------
    #  Overrides de escrita para garantir segurança com caracteres
    #  Unicode fora do intervalo Latin-1.
    # ------------------------------------------------------------------
    def cell(
        self,
        w=0,
        h=0,
        txt="",
        border=0,
        ln=0,
        align="",
        fill=False,
        link="",
    ):
        return super().cell(
            w,
            h,
            ensure_latin1(txt),
            border,
            ln,
            align,
            fill,
            link,
        )

    def multi_cell(self, w, h, txt="", border=0, align="J", fill=False):
        return super().multi_cell(
            w,
            h,
            ensure_latin1(txt),
            border,
            align,
            fill,
        )

    # ------------------------------------------------------------------
    #  Header e Footer
    # ------------------------------------------------------------------
    def header(self):
        """Cabeçalho com duas colunas e grelha de metadados"""
        header_cfg = self._header_cfg()
        logo_cfg = header_cfg.get("logo", {})
        logo_path = logo_cfg.get("path", self.cfg.get("logo_path", LOGO_PATH))
        logo_bytes = self.cfg.get("logo_bytes")

        line_height = header_cfg.get("line_height", 5)

        # Grelha de metadados no lado esquerdo
        meta = self.recipient.get("metadata", {})
        meta.setdefault("Page", str(self.page_no()))
        start_y = 15
        for label, value in meta.items():
            self.set_xy(15, start_y)
            self.set_font(*self._font_tuple(header_cfg.get("metadata_font"), ("Helvetica", "B", 10)))
            self.cell(25, line_height, f"{label}:")
            self.set_font(*self._font_tuple(header_cfg.get("metadata_value_font"), ("Helvetica", "", 10)))
            # ``FPDF.cell`` internally calls ``replace`` on the value passed in,
            # which fails if a non-string (e.g. an int) is provided.  Converting
            # to ``str`` ensures metadata like numeric references or dates are
            # handled without errors when generating PDFs.
            self.cell(45, line_height, str(value), ln=1)
            start_y += line_height

        # Bloco do destinatário abaixo dos metadados
        address_line_height = header_cfg.get("address_line_height", line_height)
        self.set_xy(15, start_y + address_line_height)
        recip = self.recipient.get("address", [])
        recipient_lines: list[str] = []
        for line in recip:
            if line is None:
                continue
            for sub_line in str(line).splitlines():
                clean = sub_line.strip()
                if clean:
                    recipient_lines.append(clean)
        self.set_font(*self._font_tuple(header_cfg.get("address_font"), ("Helvetica", "", 10)))
        for line in recipient_lines:
            # Garantir que cada linha é string para evitar erros de ``replace``
            # caso algum campo seja numérico.
            self.cell(80, address_line_height, str(line), ln=1)
            start_y += address_line_height

        # Bloco da empresa (logo + contactos) no lado direito
        max_h = 30  # altura máxima para evitar sobreposição com contactos
        logo_w = logo_cfg.get("w", 70)
        x_logo = logo_cfg.get("x", self.w - self.r_margin - logo_w)
        y_logo = logo_cfg.get("y", 15)
        def _draw_logo(path_or_bytes):
            """Desenha logo redimensionando para altura máxima."""
            if isinstance(path_or_bytes, bytes):
                img = Image.open(BytesIO(path_or_bytes))
            else:
                img = Image.open(path_or_bytes)
            w_px, h_px = img.size
            ratio = h_px / w_px if w_px else 1
            h_logo = logo_w * ratio
            if h_logo > max_h:
                logo_w_adj = max_h / ratio
                h_logo = max_h
            else:
                logo_w_adj = logo_w
            if isinstance(path_or_bytes, bytes):
                img_type = imghdr.what(None, path_or_bytes) or "png"
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{img_type}") as tmp:
                    tmp.write(path_or_bytes)
                    tmp_path = tmp.name
                try:
                    self.image(tmp_path, x_logo, y_logo, logo_w_adj, h_logo)
                finally:
                    os.remove(tmp_path)
            else:
                self.image(path_or_bytes, x_logo, y_logo, logo_w_adj, h_logo)

        if logo_bytes:
            _draw_logo(logo_bytes)
        elif os.path.exists(logo_path):
            _draw_logo(logo_path)
        company_lines = self.cfg.get(
            "company_lines",
            ["Ricardo Nogueira", "Rua Exemplo 123", "4455-123 Porto", "Portugal"],
        )
        self.set_xy(self.w - 15 - 70, 45)
        self.set_font(*self._font_tuple(header_cfg.get("company_font"), ("Helvetica", "", 9)))
        self.multi_cell(70, 4, "\n".join(company_lines), align="R")

        # Ajustar posição para início do corpo
        self.set_y(70)

    def footer(self):
        """Rodapé com linha e detalhes bancários"""
        self.set_line_width(0.2)
        self.set_y(-18)
        self.line(15, self.get_y(), self.w - 15, self.get_y())
        self.ln(2)

        bank_cols = self.cfg.get(
            "bank_details",
            [
                {"Bank": "Bank", "IBAN": "PT50 0000 0000 0000 0000 0000 0"},
            ],
        )
        legal_info = self.cfg.get("legal_info", ["VAT ID: PT123"])
        start_y = self.get_y()
        col_w = (self.w - 30) / (len(bank_cols) + 1)
        max_y = start_y
        for i, col in enumerate(bank_cols):
            x = 15 + i * col_w
            self.set_xy(x, start_y)
            for k, v in col.items():
                self.set_font("Helvetica", "B", 9)
                self.cell(col_w, 4, k, ln=1)
                self.set_font("Helvetica", "", 9)
                self.multi_cell(col_w, 4, v)
            max_y = max(max_y, self.get_y())
        # Última coluna com info legal
        legal_x = 15 + len(bank_cols) * col_w
        self.set_xy(legal_x, start_y)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(col_w, 4, "\n".join(legal_info), align="R")
        max_y = max(max_y, self.get_y())
        self.set_y(max_y)

        # Logo do myERP com hyperlink no canto inferior direito
        try:
            logo_w = 20
            logo_ratio = (
                LOGO_IMAGE.height / LOGO_IMAGE.width if LOGO_IMAGE.width else 1
            )
            logo_h = logo_w * logo_ratio
            margin_px = 50
            px_to_mm = 0.2645833333
            margin_mm = margin_px * px_to_mm
            x = self.w - margin_mm - logo_w
            y = self.h - margin_mm - logo_h
            x = max(self.l_margin, x)
            y = max(max_y + 2, y)
            self.image(
                LOGO_PATH,
                x=x,
                y=y,
                w=logo_w,
                link="https://erpktb.streamlit.app/",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Corpo do documento
    # ------------------------------------------------------------------
    def _table_col_widths(self):
        table_cfg = self._table_cfg()
        widths = table_cfg.get("widths") or self.DEFAULT_TABLE["widths"]
        try:
            widths = [float(w) for w in widths]
        except (TypeError, ValueError):
            widths = list(self.DEFAULT_TABLE["widths"])

        if len(widths) != len(self.DEFAULT_TABLE["headers"]):
            widths = list(self.DEFAULT_TABLE["widths"])

        available = self.w - self.l_margin - self.r_margin
        total = sum(widths)
        if total > available and available > 0:
            scale = available / total
            widths = [round(w * scale, 2) for w in widths]

        return widths

    def _wrap_text(self, texto: str, largura_max: float) -> list[str]:
        """Quebra o texto para caber na largura indicada preservando linhas vazias."""

        if largura_max <= 0:
            return [texto or ""]

        linhas_resultado: list[str] = []
        texto_normalizado = ensure_latin1(texto)

        for linha_original in texto_normalizado.split("\n"):
            linha = linha_original.strip()
            if not linha:
                linhas_resultado.append("")
                continue

            atual = ""
            for palavra in linha.split(" "):
                if not palavra:
                    continue
                candidato = f"{atual} {palavra}".strip() if atual else palavra
                if self.get_string_width(candidato) <= largura_max:
                    atual = candidato
                    continue

                if atual:
                    linhas_resultado.append(atual)
                    atual = ""

                if self.get_string_width(palavra) <= largura_max:
                    atual = palavra
                else:
                    segmento = ""
                    for char in palavra:
                        candidato_segmento = f"{segmento}{char}"
                        if self.get_string_width(candidato_segmento) <= largura_max or not segmento:
                            segmento = candidato_segmento
                        else:
                            linhas_resultado.append(segmento)
                            segmento = char
                    atual = segmento

            linhas_resultado.append(atual.strip())

        return linhas_resultado or [""]

    def add_title(self):
        header_cfg = self._header_cfg()
        self.set_font(*self._font_tuple(header_cfg, ("Helvetica", "B", 16)))
        title = header_cfg.get("title", "INQUIRY")
        height = header_cfg.get("title_height", 8)
        self.cell(0, height, title, ln=1)

        info_lines: list[tuple[str, str]] = []
        nome_final = (self.final_client_name or "").strip()
        pais_final = (self.final_client_country or "").strip()
        if nome_final:
            info_lines.append(("Final client:", nome_final))
        if pais_final:
            info_lines.append(("Final client country:", pais_final))

        spacing = header_cfg.get("spacing", 4)
        if info_lines:
            label_font_cfg = header_cfg.get(
                "metadata_font",
                {"font": "Helvetica", "font_style": "B", "font_size": 10},
            )
            value_font_cfg = header_cfg.get(
                "metadata_value_font",
                {"font": "Helvetica", "font_style": "", "font_size": 10},
            )
            info_height = header_cfg.get("metadata_line_height", 5)
            for label, value in info_lines:
                self.set_font(*self._font_tuple(label_font_cfg, ("Helvetica", "B", 10)))
                self.cell(40, info_height, label)
                self.set_font(*self._font_tuple(value_font_cfg, ("Helvetica", "", 10)))
                self.cell(0, info_height, value, ln=1)
            if spacing:
                self.ln(spacing)
        elif spacing:
            self.ln(spacing)

    def add_reference(self, referencia):
        body_cfg = self._body_cfg()
        label_font = body_cfg.get(
            "reference_label_font",
            {"font": body_cfg.get("font"), "font_style": "B", "font_size": body_cfg.get("font_size", 11)},
        )
        value_font = body_cfg.get(
            "reference_value_font",
            {"font": body_cfg.get("font"), "font_style": body_cfg.get("font_style", ""), "font_size": body_cfg.get("font_size", 11)},
        )
        self.set_font(*self._font_tuple(label_font, ("Helvetica", "B", 11)))
        self.cell(35, 5, "Our reference:")
        self.set_font(*self._font_tuple(value_font, ("Helvetica", "", 11)))
        self.cell(0, 5, referencia, ln=1)
        spacing = body_cfg.get("reference_spacing", 4)
        if spacing:
            self.ln(spacing)

    def add_intro(self, nome_contacto=""):
        body_cfg = self._body_cfg()
        self.set_font(*self._font_tuple(body_cfg, ("Helvetica", "", 11)))
        if nome_contacto:
            saudacao = body_cfg.get("greeting_named", "Dear Mr./Ms. {nome_contacto},").format(
                nome_contacto=nome_contacto
            )
        else:
            saudacao = body_cfg.get("greeting_generic", "Dear Sir/Madam,")
        self.cell(0, 5, saudacao, ln=1)
        spacing = body_cfg.get("intro_spacing", 4)
        if spacing:
            self.ln(spacing)
        self.cell(0, 5, body_cfg.get("intro_text", "Please quote us for:"), ln=1)
        if spacing:
            self.ln(spacing)

    def table_header(self):
        table_cfg = self._table_cfg()
        col_w = self._table_col_widths()
        self.set_font(*self._font_tuple(table_cfg, ("Helvetica", "B", 11)))
        headers = table_cfg.get("headers", self.DEFAULT_TABLE["headers"])
        aligns = table_cfg.get("alignments", self.DEFAULT_TABLE["alignments"])
        header_height = table_cfg.get("header_height", 8)
        for w, h, a in zip(col_w, headers, aligns):
            self.cell(w, header_height, h, align=a, border="B")
        # Move below header row and add uma linha em branco antes do primeiro item
        self.ln()
        spacing = table_cfg.get("header_spacing", 4)
        if spacing:
            self.ln(spacing)

    def add_item(self, idx, item):
        table_cfg = self._table_cfg()
        col_w = self._table_col_widths()
        line_height = table_cfg.get("row_height", 5)
        # Garantir texto dos itens em estilo regular
        row_font = {
            "font": table_cfg.get("row_font", table_cfg.get("font")),
            "font_style": table_cfg.get("row_font_style", ""),
            "font_size": table_cfg.get("row_font_size", 10),
        }
        self.set_font(*self._font_tuple(row_font, ("Helvetica", "", 10)))
        # Preparar texto do item
        # ``descricao`` might be ``None`` if the item was partially filled in
        # the UI, so fall back to an empty string before splitting.
        item_text = item.get("descricao") or ""
        lines = self._wrap_text(item_text, col_w[4])
        line_count = len(lines)
        row_height = line_count * line_height
        sub_height = line_height
        # Quebra de página se necessário
        if self.get_y() + row_height + sub_height > self.page_break_trigger:
            self.add_page()
            self.table_header()

        x_start = self.get_x()
        y_start = self.get_y()
        aligns = table_cfg.get("alignments", self.DEFAULT_TABLE["alignments"])
        # ``artigo_num`` can be present with a ``None`` value.  ``FPDF.cell``
        # calls ``replace`` on the provided text, which fails for ``None``.
        # Converting to ``""`` avoids the "NoneType has no attribute 'replace'"
        # error when generating the PDF.
        part_no = item.get("artigo_num") or ""
        quantidade = item.get("quantidade")
        quantidade_str = str(quantidade) if quantidade is not None else ""
        unidade = item.get("unidade") or ""
        # Desenhar células sem grelha; apenas linha inferior no final do item
        for i in range(line_count):
            border = "B" if i == line_count - 1 else ""
            self.set_xy(x_start, y_start + i * line_height)
            self.cell(col_w[0], line_height, str(idx) if i == 0 else "", border=border, align=aligns[0])
            self.cell(col_w[1], line_height, part_no if i == 0 else "", border=border, align=aligns[1])
            self.cell(
                col_w[2],
                line_height,
                quantidade_str if i == 0 else "",
                border=border,
                align=aligns[2],
            )
            self.cell(col_w[3], line_height, unidade if i == 0 else "", border=border, align=aligns[3])
            self.cell(col_w[4], line_height, lines[i], border=border, align=aligns[4])

        # Espaço extra entre itens
        self.set_y(y_start + row_height)
        spacing = table_cfg.get("row_spacing", 3)
        if spacing:
            self.ln(spacing)

    def gerar(
        self,
        fornecedor,
        data,
        artigos,
        referencia="",
        contacto="",
        cliente_final_nome="",
        cliente_final_pais="",
    ):
        """Gera o PDF e devolve bytes"""
        addr_lines = [fornecedor.get("nome", "")]
        if fornecedor.get("morada"):
            addr_lines.extend(fornecedor["morada"].splitlines())
        if fornecedor.get("email"):
            addr_lines.append(fornecedor["email"])
        if fornecedor.get("telefone"):
            addr_lines.append(fornecedor["telefone"])
        if fornecedor.get("nif"):
            addr_lines.append(f"NIF: {fornecedor['nif']}")
        self.final_client_name = (cliente_final_nome or "").strip()
        self.final_client_country = (cliente_final_pais or "").strip()
        self.recipient = {
            "address": [l for l in addr_lines if l],
            "metadata": {
                "Date": data,
            },
        }
        self.add_page()
        self.add_title()
        self.add_reference(referencia)
        self.add_intro(contacto)
        self.table_header()
        for idx, art in enumerate(artigos, 1):
            self.add_item(idx, art)
        # ``fpdf`` usa Latin-1 internamente. Alguns caracteres provenientes da
        # base de dados (ex.: travessões “–”) não existem nesse conjunto e
        # provocavam ``UnicodeEncodeError`` ao gerar PDFs. Utilizamos
        # ``errors='replace'`` para garantir que o ficheiro é produzido sem
        # falhar e os caracteres problemáticos são substituídos por um marcador
        # visual.
        return self.output(dest="S").encode("latin-1", errors="replace")


class ClientQuotationPDF(InquiryPDF):
    """PDF para orçamento ao cliente com layout semelhante ao PDF de pedido."""

    def __init__(self, config=None):
        super().__init__(config=config)

    def add_title(self):
        title = self.cfg.get("header", {}).get("title", "QUOTATION")
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 8, title, ln=1)
        self.ln(4)

    def add_reference(self, our_ref, your_ref=""):
        self.set_font("Helvetica", "B", 11)
        self.cell(40, 5, "Our Reference:")
        self.set_font("Helvetica", "", 11)
        self.cell(0, 5, our_ref, ln=1)
        if your_ref:
            self.set_font("Helvetica", "B", 11)
            self.cell(40, 5, "Your Reference:")
            self.set_font("Helvetica", "", 11)
            self.cell(0, 5, your_ref, ln=1)
        self.ln(4)

    def table_header(self):
        table_cfg = self.cfg.get("table", {})
        headers = table_cfg.get(
            "headers",
            [
                "#",
                "Item No.",
                "Description",
                "Qty",
                "Unit Price",
                "Total",
                "Lead Time",
                "Weight",
            ],
        )
        widths = table_cfg.get(
            "widths", [8, 18, 78, 12, 18, 20, 12, 14]
        )
        font = table_cfg.get("font", "Arial")
        style = table_cfg.get("font_style", "B")
        size = table_cfg.get("font_size", 9)
        self.set_font(font, style, size)
        for w, h in zip(widths, headers):
            self.cell(w, 7, h, border="B", align="C")
        self.ln()

    def _split_long_word(self, word, max_width):
        """Divide palavras longas para caberem dentro da largura disponível."""

        pieces = []
        current = ""
        for char in word:
            test = f"{current}{char}"
            if self.get_string_width(test) <= max_width:
                current = test
            else:
                if current:
                    pieces.append(current)
                current = char
        if current:
            pieces.append(current)
        return pieces or [""]

    def split_text(self, text, max_width):
        """Divide texto em linhas respeitando a largura máxima disponível."""

        lines = []
        for part in text.split("\n"):
            words = part.split()
            if not words:
                lines.append("")
                continue

            current_line = ""
            for word in words:
                segments = (
                    self._split_long_word(word, max_width)
                    if self.get_string_width(word) > max_width
                    else [word]
                )
                for segment in segments:
                    if not current_line:
                        current_line = segment
                        continue
                    test_line = f"{current_line} {segment}"
                    if self.get_string_width(test_line) <= max_width:
                        current_line = test_line
                    else:
                        lines.append(current_line)
                        current_line = segment

            if current_line:
                lines.append(current_line)
            else:
                lines.append("")

        return lines if lines else [""]

    def add_item(self, idx, item):
        table_cfg = self.cfg.get("table", {})
        widths = table_cfg.get("widths", [8, 18, 78, 12, 18, 20, 12, 14])
        row_font = table_cfg.get("font", "Arial")
        row_size = table_cfg.get("row_font_size", 8)
        self.set_font(row_font, "", row_size)

        preco_venda = float(item["preco_venda"])
        quantidade = int(item["quantidade_final"])
        total = preco_venda * quantidade

        desc = item.get("descricao") or ""
        max_desc_width = max(widths[2] - 1, 1)
        lines = self.split_text(desc, max_desc_width)
        hs_code = item.get("hs_code")
        origem = item.get("pais_origem")
        if hs_code or origem:
            parts = []
            if hs_code:
                parts.append(f"HS Code: {hs_code}")
            if origem:
                parts.append(f"Origin: {origem}")
            lines.append(" ".join(parts))
        line_count = len(lines)
        row_height = line_count * 6

        if self.get_y() + row_height > self.page_break_trigger:
            self.add_page()
            self.table_header()

        for i, line in enumerate(lines):
            border = "B" if i == line_count - 1 else ""
            self.cell(widths[0], 6, str(idx) if i == 0 else "", border=border, align="C")
            self.cell(widths[1], 6, (item.get("artigo_num") or "")[:10] if i == 0 else "", border=border)
            self.cell(widths[2], 6, line, border=border)
            if i == 0:
                self.cell(widths[3], 6, str(quantidade), border=border, align="C")
                self.cell(widths[4], 6, f"EUR {preco_venda:.2f}", border=border, align="R")
                self.cell(widths[5], 6, f"EUR {total:.2f}", border=border, align="R")
                self.cell(widths[6], 6, f"{item.get('prazo_entrega', 0)}d", border=border, align="C")
                self.cell(widths[7], 6, f"{(item.get('peso') or 0):.1f}kg", border=border, align="C")
            else:
                for w in widths[3:]:
                    self.cell(w, 6, "", border=border)
            self.ln()

        return total

    def add_total(self, total_geral, peso_total):
        totals_cfg = self.cfg.get("totals", {})
        font = totals_cfg.get("font", "Arial")
        style = totals_cfg.get("font_style", "B")
        size = totals_cfg.get("font_size", 11)
        label_w = totals_cfg.get("label_width", 131)
        total_w = totals_cfg.get("total_width", 20)
        extra_w = totals_cfg.get("extra_width", 39)
        conditions = self.cfg.get(
            "conditions",
            [
                "Proposal validity: 30 days",
                "Prices do not include VAT",
                "Payment terms: To be agreed",
            ],
        )
        cond_h = 5 * len(conditions)
        block_h = 8 + 5 + cond_h
        start_y = self.h - self.b_margin - block_h
        if self.get_y() > start_y:
            self.add_page()
            start_y = self.h - self.b_margin - block_h
        self.set_y(start_y)
        self.set_font(font, style, size)
        self.cell(label_w, 8, "TOTAL:", border=1, align="R")
        self.cell(total_w, 8, f"EUR {total_geral:.2f}", border=1, align="C")
        self.cell(extra_w, 8, f"Total Weight: {peso_total:.1f}kg", border=1, align="C")
        self.ln()
        self.ln(5)
        self.set_font(font, "", size - 1)
        for cond in conditions:
            self.cell(0, 5, cond, ln=1)

    def gerar(self, rfq_info, solicitante_info, itens_resposta, user_info=None):
        addr_lines = []
        if solicitante_info.get("empresa_nome"):
            addr_lines.append(str(solicitante_info["empresa_nome"]).strip())
        if solicitante_info.get("empresa_morada"):
            addr_lines.extend(
                linha.strip()
                for linha in str(solicitante_info["empresa_morada"]).splitlines()
                if linha.strip()
            )
        if solicitante_info.get("nome"):
            addr_lines.append(str(solicitante_info["nome"]).strip())
        if solicitante_info.get("email"):
            addr_lines.append(str(solicitante_info["email"]).strip())
        metadata = {"Date": rfq_info["data"]}
        self.recipient = {
            "address": addr_lines,
            "metadata": metadata,
        }
        self.add_page()
        self.add_title()
        self.add_reference(rfq_info.get("processo", ""), rfq_info.get("referencia", ""))
        self.table_header()
        total_geral = 0.0
        peso_total = 0.0
        for idx, item in enumerate(itens_resposta, 1):
            total_item = self.add_item(idx, item)
            total_geral += total_item
            quantidade_utilizada = item.get("quantidade_final")
            if quantidade_utilizada is None:
                quantidade_utilizada = item.get("quantidade")
            try:
                quantidade_num = float(quantidade_utilizada)
            except (TypeError, ValueError):
                quantidade_num = 0.0
            peso_total += float(item.get("peso") or 0) * quantidade_num
        self.add_total(total_geral, peso_total)
        return self.output(dest="S").encode("latin-1", errors="replace")
# ========================== FUNÇÕES DE GESTÃO DE PDFs ==========================

def gerar_e_armazenar_pdf(rfq_id, fornecedor_id, data, artigos):
    """Gerar e armazenar PDF de pedido de cotação"""
    try:
        config = load_pdf_config("pedido")

        empresa = obter_config_empresa()
        conn = obter_conexao()
        c = conn.cursor()

        # Dados do utilizador que criou a RFQ
        c.execute(
            """
            SELECT u.nome,
                   u.email,
                   rfq.cliente_final_nome,
                   rfq.cliente_final_pais
              FROM rfq
              LEFT JOIN processo p ON rfq.processo_id = p.id
              LEFT JOIN utilizador u ON p.utilizador_id = u.id
             WHERE rfq.id = ?
            """,
            (rfq_id,),
        )
        user_row = c.fetchone()
        nome_user = user_row[0] if user_row and user_row[0] else ""
        email_user = user_row[1] if user_row and user_row[1] else ""
        cliente_final_nome = user_row[2] if user_row and len(user_row) > 2 and user_row[2] else ""
        cliente_final_pais = user_row[3] if user_row and len(user_row) > 3 and user_row[3] else ""

        if empresa:
            linhas = [empresa.get("nome") or "", empresa.get("morada") or ""]
            if empresa.get("telefone"):
                linhas.append(f"Tel: {empresa['telefone']}")
            if empresa.get("website"):
                linhas.append(empresa["website"])
            if nome_user:
                linhas.append(nome_user)
            if email_user:
                linhas.append(email_user)
            config["company_lines"] = [l for l in linhas if l]
            bank = {}
            if empresa.get("banco"):
                bank["Bank"] = empresa["banco"]
            if empresa.get("iban"):
                bank["IBAN"] = empresa["iban"]
            if bank:
                config["bank_details"] = [bank]
            if empresa.get("nif"):
                config["legal_info"] = [f"VAT ID: {empresa['nif']}"]
            if empresa.get("logo"):
                config["logo_bytes"] = empresa["logo"]

        # Dados do fornecedor
        c.execute(
            "SELECT nome, email, telefone, morada, nif FROM fornecedor WHERE id = ?",
            (fornecedor_id,),
        )
        forn_row = c.fetchone()
        fornecedor = {
            "nome": forn_row[0] if forn_row else "",
            "email": forn_row[1] if forn_row else "",
            "telefone": forn_row[2] if forn_row else "",
            "morada": forn_row[3] if forn_row else "",
            "nif": forn_row[4] if forn_row else "",
        }

        c.execute(
            """
            SELECT processo.numero, rfq.processo_id
              FROM rfq
              LEFT JOIN processo ON rfq.processo_id = processo.id
             WHERE rfq.id = ?
            """,
            (rfq_id,),
        )
        row = c.fetchone()
        numero_processo = row[0] if row else ""
        processo_id = row[1] if row and len(row) > 1 else resolve_processo_id(rfq_id, cursor=c)
        if processo_id is None:
            st.error("Processo associado ao pedido não encontrado.")
            conn.close()
            return None

        pdf_generator = InquiryPDF(config)
        pdf_bytes = pdf_generator.gerar(
            fornecedor,
            data.strftime("%Y-%m-%d"),
            artigos,
            numero_processo,
            cliente_final_nome=cliente_final_nome,
            cliente_final_pais=cliente_final_pais,
        )

        c.execute(
            """
            INSERT INTO pdf_storage (processo_id, tipo_pdf, pdf_data, tamanho_bytes)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (processo_id, tipo_pdf) DO UPDATE SET
                pdf_data = excluded.pdf_data,
                tamanho_bytes = excluded.tamanho_bytes
        """,
            (str(processo_id), "pedido", pdf_bytes, len(pdf_bytes)),
        )
        conn.commit()
        conn.close()

        return pdf_bytes
    except Exception as e:
        st.error(f"Erro ao gerar PDF: {str(e)}")
        return None

def gerar_pdf_cliente(rfq_id, resposta_ids: Iterable[int] | None = None):
    """Gerar PDF para cliente com tratamento de erros.

    Se ``resposta_ids`` for fornecido, apenas as respostas indicadas serão
    incluídas no documento gerado.
    """
    try:
        conn = obter_conexao()
        c = conn.cursor()

        # 1. Obter dados da RFQ e do cliente
        c.execute(
            """
            SELECT COALESCE(p.ref_cliente, ''),
                   rfq.data_atualizacao,
                   COALESCE(c.nome, ''),
                   COALESCE(c.email, ''),
                   ce.nome AS empresa_nome,
                   ce.morada AS empresa_morada,
                   ce.condicoes_pagamento,
                   COALESCE(c.nome, ''),
                   COALESCE(c.email, ''),
                   u.nome AS user_nome,
                   u.email AS user_email,
                   p.numero AS processo_numero,
                   rfq.processo_id,
                   COALESCE(rfq.cliente_final_nome, ''),
                   COALESCE(rfq.cliente_final_pais, '')
            FROM rfq
            LEFT JOIN processo p ON rfq.processo_id = p.id
            LEFT JOIN cliente c ON p.cliente_id = c.id
            LEFT JOIN cliente_empresa ce ON c.empresa_id = ce.id
            LEFT JOIN utilizador u ON p.utilizador_id = u.id
            WHERE rfq.id = ?
            """,
            (rfq_id,),
        )
        row = c.fetchone()

        if not row:
            st.error("RFQ não encontrada")
            return False

        rfq_data = {
            "referencia": row[0],
            "data": row[1],
            "nome_solicitante": row[2],
            "email_solicitante": row[3],
            "empresa_nome": row[4],
            "empresa_morada": row[5],
            "condicoes_pagamento": row[6],
            "cliente_nome": row[7],
            "cliente_email": row[8],
            "user_nome": row[9] if len(row) > 9 else "",
            "user_email": row[10] if len(row) > 10 else "",
            "processo_numero": row[11] if len(row) > 11 else "",
            "processo_id": row[12] if len(row) > 12 else None,
            "cliente_final_nome": row[13] if len(row) > 13 else "",
            "cliente_final_pais": row[14] if len(row) > 14 else "",
        }

        resposta_ids_set = {
            int(rid)
            for rid in (resposta_ids or [])
            if isinstance(rid, (int, str)) and str(rid).isdigit()
        }

        base_query = """
            SELECT a.artigo_num,
                   rf.descricao,
                   COALESCE(rf.quantidade_final, a.quantidade) AS quantidade_final,
                   COALESCE(u.nome, ''),
                   rf.preco_venda,
                   rf.prazo_entrega,
                   rf.peso,
                   rf.hs_code,
                   rf.pais_origem,
                   COALESCE(pa.ordem, a.ordem) AS ordem
            FROM resposta_fornecedor rf
            JOIN artigo a ON rf.artigo_id = a.id
            LEFT JOIN unidade u ON a.unidade_id = u.id
            LEFT JOIN processo_artigo pa ON pa.id = a.processo_artigo_id
        """

        if resposta_ids_set:
            placeholders = ",".join(["?"] * len(resposta_ids_set))
            c.execute(
                f"{base_query} WHERE rf.id IN ({placeholders}) ORDER BY ordem, rf.id",
                tuple(resposta_ids_set),
            )
        else:
            c.execute(
                f"{base_query} WHERE rf.rfq_id = ? ORDER BY ordem, rf.id",
                (rfq_id,),
            )

        itens_resposta = [
            {
                'artigo_num': row[0] or '',
                'descricao': limitar_descricao_artigo(row[1]),
                'quantidade_final': row[2],
                'quantidade': row[2],
                'unidade': row[3],
                'preco_venda': row[4],
                'prazo_entrega': row[5],
                'peso': row[6] or 0,
                'hs_code': row[7] or '',
                'pais_origem': row[8] or ''
            }
            for row in c.fetchall()
        ]

        if not itens_resposta:
            st.error("Nenhuma resposta encontrada para esta RFQ")
            return False

        # 3. Gerar PDF
        config = load_pdf_config("cliente")
        empresa = obter_config_empresa()
        if empresa:
            linhas = [empresa.get("nome") or "", empresa.get("morada") or ""]
            if empresa.get("telefone"):
                linhas.append(f"Tel: {empresa['telefone']}")
            if empresa.get("website"):
                linhas.append(empresa["website"])
            if rfq_data.get("user_nome"):
                linhas.append(rfq_data["user_nome"])
            if rfq_data.get("user_email"):
                linhas.append(rfq_data["user_email"])
            config["company_lines"] = [l for l in linhas if l]
            bank = {}
            if empresa.get("banco"):
                bank["Bank"] = empresa["banco"]
            if empresa.get("iban"):
                bank["IBAN"] = empresa["iban"]
            if bank:
                config["bank_details"] = [bank]
            if empresa.get("nif"):
                config["legal_info"] = [f"VAT ID: {empresa['nif']}"]
            if empresa.get("logo"):
                config["logo_bytes"] = empresa["logo"]

        pagamento = rfq_data.get("condicoes_pagamento")
        if pagamento:
            conds = config.get(
                "conditions",
                [
                    "Proposal validity: 30 days",
                    "Prices do not include VAT",
                    "Payment terms: To be agreed",
                ],
            )
            updated = False
            for i, cond in enumerate(conds):
                if "payment terms" in cond.lower():
                    conds[i] = f"Payment terms: {pagamento}"
                    updated = True
                    break
            if not updated:
                conds.append(f"Payment terms: {pagamento}")
            config["conditions"] = conds
        pdf_cliente = ClientQuotationPDF(config)
        pdf_bytes = pdf_cliente.gerar(
            rfq_info={
                'data': _format_iso_date(rfq_data["data"]),
                'processo': rfq_data["processo_numero"] or '',
                'referencia': rfq_data["referencia"] or '',
            },
            solicitante_info={
                'empresa_nome': rfq_data["empresa_nome"] or '',
                'empresa_morada': rfq_data["empresa_morada"] or '',
                'nome': rfq_data["cliente_nome"] or rfq_data["nome_solicitante"] or '',
                'email': rfq_data["cliente_email"] or rfq_data["email_solicitante"] or '',
            },
            itens_resposta=itens_resposta,
            user_info={
                'nome': rfq_data.get('user_nome', ''),
                'email': rfq_data.get('user_email', ''),
            },
        )

        # 4. Armazenar PDF
        processo_id = rfq_data.get("processo_id") or resolve_processo_id(rfq_id, cursor=c)
        if processo_id is None:
            st.error("Processo associado ao PDF do cliente não encontrado.")
            return False

        c.execute(
            """INSERT INTO pdf_storage
                  (processo_id, tipo_pdf, pdf_data, tamanho_bytes)
                  VALUES (?, ?, ?, ?)
                  ON CONFLICT (processo_id, tipo_pdf) DO UPDATE SET
                      pdf_data = excluded.pdf_data,
                      tamanho_bytes = excluded.tamanho_bytes""",
            (str(processo_id), "cliente", pdf_bytes, len(pdf_bytes)),
        )

        conn.commit()
        invalidate_overview_caches()
        return True

    except Exception as e:
        st.error(f"Erro ao gerar PDF: {str(e)}")
        return False
    finally:
        conn.close()

def exibir_pdf(
    label,
    data_pdf,
    *,
    height: int = 600,
    expanded: bool = False,
    use_expander: bool = True,
    sticky: bool = False,
    sticky_top: int = 0,
):
    """Mostra PDF com fallback para pdf.js."""
    if not data_pdf:
        st.warning("PDF não disponível")
        return

    b64 = base64.b64encode(data_pdf).decode()

    pdf_object = textwrap.dedent(
        f"""
        <object class="embedded-pdf-object" data="data:application/pdf;base64,{b64}" type="application/pdf" style="width:100%; min-height:{height}px;">
            <iframe class="embedded-pdf-iframe" src="https://mozilla.github.io/pdf.js/web/viewer.html?file=data:application/pdf;base64,{b64}" style="width:100%; min-height:{height}px; border:none;"></iframe>
        </object>
        """
    ).strip()

    if use_expander:
        with st.expander(label, expanded=expanded):
            st.markdown(
                textwrap.dedent(
                    f"""
                    <div class="pdf-wrapper-default" style="min-height:{height}px;">
                        {pdf_object}
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
    else:
        if sticky:
            container_id = f"pdf-sticky-{uuid4().hex}"
            sticky_offset = max(sticky_top, 0)
            scrollable_height_css = f"calc(100vh - {sticky_offset + 40}px)"
            st.markdown(
                textwrap.dedent(
                    f"""
                    <style>
                    #{container_id} {{
                        position: -webkit-sticky;
                        position: sticky;
                        top: {sticky_offset}px;
                        z-index: 2;
                        align-self: flex-start;
                    }}
                    #{container_id} .pdf-title {{
                        font-weight: 600;
                        margin-bottom: 0.5rem;
                    }}
                    #{container_id} .pdf-wrapper {{
                        display: flex;
                        flex-direction: column;
                        height: min({scrollable_height_css}, 100vh);
                        max-height: {scrollable_height_css};
                        min-height: min({height}px, {scrollable_height_css});
                        overflow-y: auto;
                        overflow-x: hidden;
                    }}
                    #{container_id} .pdf-wrapper .embedded-pdf-object,
                    #{container_id} .pdf-wrapper .embedded-pdf-iframe {{
                        width: 100%;
                        height: 100%;
                        min-height: min({height}px, {scrollable_height_css});
                    }}
                    </style>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
            st.markdown(
                textwrap.dedent(
                    f"""
                    <div id="{container_id}">
                        <div class="pdf-title">{label}</div>
                        <div class="pdf-wrapper">
                            {pdf_object}
                        </div>
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**{label}**")
            st.markdown(
                textwrap.dedent(
                    f"""
                    <div class="pdf-wrapper-default" style="min-height:{height}px;">
                        {pdf_object}
                    </div>
                    """
                ).strip(),
                unsafe_allow_html=True,
            )


def reset_smart_quotation_state():
    """Limpa os valores guardados para o módulo Smart Quotation."""
    for key in (
        "smart_pdf_uid",
        "smart_referencia",
        "smart_unidade",
        "smart_marca",
        "smart_cliente_index",
        "smart_artigos",
    ):
        st.session_state.pop(key, None)

    artigos_keys = [k for k in st.session_state.keys() if k.startswith("smart_artigos_")]
    for key in artigos_keys:
        st.session_state.pop(key, None)


def normalizar_quebras_linha(texto: str) -> str:
    """Normaliza caracteres de quebra de linha preservando a estrutura original."""

    if not texto:
        return ""

    return texto.replace("\r\n", "\n").replace("\r", "\n")


def descricao_tem_conteudo(texto: str) -> bool:
    """Indica se o texto possui conteúdo relevante após remover tags HTML."""

    if not texto:
        return False

    texto_sem_tags = re.sub(r"<[^>]+>", "", texto)
    return bool(texto_sem_tags.strip())


def extrair_primeira_palavra(texto: str) -> str:
    """Obtém a primeira palavra alfanumérica presente no texto fornecido."""

    if not texto:
        return ""

    texto_limpo = texto.strip()
    if not texto_limpo:
        return ""

    correspondencia = re.search(r"[\wÀ-ÿ0-9][\wÀ-ÿ0-9\-/]*", texto_limpo)
    return correspondencia.group(0) if correspondencia else ""


def garantir_marca_primeira_palavra(descricao: str, marca: str) -> str:
    """Garante que a marca aparece como primeira palavra da descrição.

    Caso a descrição não comece pela marca fornecida, esta função remove
    ocorrências posteriores (ignorando maiúsculas/minúsculas) e coloca a
    marca no início.  Espaços supérfluos são também normalizados para
    evitar duplicações indesejadas.
    """

    descricao_limpa = (descricao or "").strip()
    marca_limpa = (marca or "").strip()

    if not marca_limpa:
        return descricao_limpa

    if not descricao_limpa:
        return marca_limpa

    # Normalizar espaços para facilitar a comparação
    descricao_limpa = re.sub(r"\s+", " ", descricao_limpa)

    padrao_inicio = re.compile(rf"^{re.escape(marca_limpa)}\b", re.IGNORECASE)
    if padrao_inicio.search(descricao_limpa):
        # Substituir a primeira palavra pela marca limpa para manter o
        # formato consistente (ex.: capitalização definida pelo utilizador).
        resto = padrao_inicio.sub("", descricao_limpa, count=1).lstrip()
        return f"{marca_limpa}{(' ' + resto) if resto else ''}".strip()

    padrao = re.compile(rf"\b{re.escape(marca_limpa)}\b", re.IGNORECASE)
    descricao_sem_marca = padrao.sub("", descricao_limpa).strip()
    descricao_sem_marca = re.sub(r"\s+", " ", descricao_sem_marca)

    if descricao_sem_marca:
        return f"{marca_limpa} {descricao_sem_marca}".strip()

    return marca_limpa

@st.dialog("Responder Cotação", width="large")
def responder_cotacao_dialog(cotacao):
    st.markdown(
        """
        <style>
        /* Occupy the full viewport with the dialog overlay */
        [data-testid="stDialog"] {
            position: fixed;
            inset: 0;
            width: 100vw !important;
            height: 100vh !important;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0;
        }
        /* Ensure the immediate container stretches across the overlay */
        [data-testid="stDialog"] > div:first-child {
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        /* Expand inner dialog content to occupy full form */
        [data-testid="stDialog"] > div > div {
            width: min(90vw, 75rem) !important;
            max-width: min(90vw, 75rem) !important;
            max-height: 90vh;
            padding-top: 20px;
            min-width: 60rem;
            overflow-y: auto;
        }
        /* Ensure form stretches to fill available space */
        [data-testid="stDialog"] form {
            width: 100%;
            min-height: 0;
        }
        [data-testid="stDialog"] [data-testid="stVerticalBlock"] > div {
            width: 100%;
        }
        [data-testid="stDialog"] .st-ft {
            min-width: 60rem;
        }
        [data-testid="stDialog"] hr {
            margin: 1.3em 0px;
        }

        [data-testid="stVerticalBlock"]{
            gap: .2rem;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )
    detalhes = obter_detalhes_cotacao(cotacao['id'])
    st.info(f"**Responder a Cotação {cotacao['processo']}**")

    anexos_resposta_key = f"anexos_resposta_{cotacao['id']}"
    if anexos_resposta_key not in st.session_state:
        st.session_state[anexos_resposta_key] = []
    with st.form(f"resposta_form_{cotacao['id']}"):
        respostas = []
        pdf_resposta = st.file_uploader(
            "Resposta do Fornecedor (PDF ou email)",
            type=["pdf", "eml", "msg"],
            accept_multiple_files=True,
            key=f"pdf_{cotacao['id']}"
        )
        if pdf_resposta:
            st.session_state[anexos_resposta_key] = processar_upload_pdf(pdf_resposta)

        if st.session_state[anexos_resposta_key]:
            for idx, (nome_resposta, resposta_bytes) in enumerate(st.session_state[anexos_resposta_key], start=1):
                exibir_pdf(f"📄 Resposta carregada {idx} - {nome_resposta}", resposta_bytes, expanded=False)

        for i, artigo in enumerate(detalhes['artigos'], 1):
            st.subheader(f"Artigo {i}: {artigo['artigo_num'] if artigo['artigo_num'] else 'S/N'}")

            col1, col2, col3 = st.columns([2, 1, 1])

            with col1:
                descricao_editada = st.text_area(
                    "Descrição (editável)",
                    value=artigo['descricao'],
                    key=f"desc_{artigo['id']}",
                    height=180
                )

            with col2:
                quantidade_original = artigo['quantidade']
                quantidade_final = st.number_input(
                    f"Qtd (Original: {quantidade_original})",
                    min_value=1,
                    value=quantidade_original,
                    key=f"qtd_{artigo['id']}"
                )
                peso = st.number_input(
                    "Peso Unitário(kg)",
                    min_value=0.0,
                    step=0.1,
                    key=f"peso_{artigo['id']}"
                )
                prazo = st.number_input(
                    "Prazo (dias)",
                    min_value=0,
                    step=1,
                    key=f"prazo_{artigo['id']}"
                )

            with col3:
                hs_code = st.text_input(
                    "HS Code",
                    key=f"hs_{artigo['id']}"
                )
                pais_origem = st.text_input(
                    "País Origem",
                    key=f"pais_{artigo['id']}"
                )

            margem = obter_margem_para_marca(
                detalhes["fornecedor_id"], artigo.get("marca")
            )

            col4, col5 = st.columns(2)

            with col4:
                custo = st.number_input(
                    "Preço Compra (EUR )",
                    min_value=0.0,
                    step=0.01,
                    key=f"custo_{artigo['id']}"
                )
                if custo > 0:
                    preco_venda = custo * (1 + margem / 100)
                    st.caption(f"Margem aplicada: {margem:.1f}%")
                    st.success(f"P.V.: EUR {preco_venda:.2f}")

            with col5:
                validade_default = date.today() + timedelta(days=30)
                validade_preco = st.date_input(
                    "Validade Preço",
                    value=validade_default,
                    key=f"val_{artigo['id']}"
                )


            respostas.append((
                artigo['id'], custo, validade_preco.isoformat(), peso,
                hs_code, pais_origem, descricao_editada, quantidade_final, prazo
            ))

        st.markdown("---")

        col_obs, col_env = st.columns([3, 1])

        with col_obs:
            observacoes = st.text_area(
                "Observações",
                key=f"obs_{cotacao['id']}",
                height=110
            )

        with col_env:
            custo_envio = st.number_input(
                "Custos Envio",
                min_value=0.0,
                step=0.01,
                key=f"custo_envio_{cotacao['id']}"
            )
            custo_embalagem = st.number_input(
                "Custos Embalagem",
                min_value=0.0,
                step=0.01,
                key=f"custo_emb_{cotacao['id']}"
            )

        col1, col2 = st.columns(2)

        with col1:
            submeter = st.form_submit_button("💾 Submeter Preço", type="primary")

        with col2:
            cancelar = st.form_submit_button("❌ Cancelar")

    if submeter:
        respostas_validas = [r for r in respostas if r[1] > 0]

        if respostas_validas:
            sucesso, info_envio = guardar_respostas(
                cotacao['id'],
                respostas_validas,
                custo_envio,
                custo_embalagem,
                observacoes,
            )

            if sucesso:
                anexos_resposta = st.session_state.get(anexos_resposta_key, [])
                if anexos_resposta:
                    guardar_pdf_uploads(
                        cotacao['id'],
                        'anexo_fornecedor',
                        anexos_resposta,
                    )
                    st.session_state[anexos_resposta_key] = []

                st.success("Resposta guardada com sucesso.")
                st.rerun()
        else:
            st.error("Por favor, preencha pelo menos um preço")

    if cancelar:
        st.rerun()


@st.dialog("Criar Cotação para Cliente")
def criar_cotacao_cliente_dialog(
    rfq_id,
    numero_processo,
    referencia_cliente,
    nome_cliente,
    email_cliente,
    respostas_destacadas: Iterable[int] | None = None,
    processo_id: int | None = None,
):
    respostas_destacadas_ids = {
        int(resposta_id)
        for resposta_id in (respostas_destacadas or [])
        if resposta_id is not None
    }


    respostas = obter_respostas_processo(processo_id) if processo_id else []
    if not respostas:
        respostas = obter_respostas_cotacao(rfq_id)

    pdf_session_key = f"cliente_pdf_state_{rfq_id}"
    existing_pdf_state = st.session_state.get(pdf_session_key)
    if existing_pdf_state:
        st.info("Cotação do cliente já foi gerada anteriormente. Pode descarregar novamente abaixo.")
        st.download_button(
            "⬇️ Descarregar PDF Cliente",
            data=existing_pdf_state["bytes"],
            file_name=existing_pdf_state["file_name"],
            mime="application/pdf",
            key=f"download_cliente_{rfq_id}",
        )
        st.markdown("---")

    if not respostas:
        st.info("Ainda não existem respostas registadas para esta cotação.")
        return
    with st.form(f"cliente_form_{rfq_id}"):
        st.markdown(
            "Selecione os artigos a incluir na cotação do cliente. Os artigos não selecionados serão ignorados.")

        if "_cliente_cotacao_css" not in st.session_state:
            st.markdown(
                """
                <style>
                .cliente-cotacao-form div[data-testid="stCheckbox"] > label {
                    display: inline-flex;
                    align-items: flex-start;
                    gap: 0.5rem;
                    padding: 0.35rem 0.55rem;
                    border-radius: 6px;
                    max-width: min(100%, 48rem);
                }
                .cliente-cotacao-form div[data-testid="stCheckbox"] > label span {
                    font-size: 0.9rem;
                    line-height: 1.25;
                    white-space: normal;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )
            st.session_state["_cliente_cotacao_css"] = True

        st.markdown('<div class="cliente-cotacao-form">', unsafe_allow_html=True)

        selecao_respostas: dict[int, bool] = {}
        for resposta in respostas:
            descricao_completa = resposta.get("descricao") or resposta.get("descricao_original") or "Artigo"
            descricao = limitar_descricao_artigo(descricao_completa)
            descricao_curta = " / ".join(descricao.splitlines()[:2]) or "Artigo"
            if len(descricao_curta) > 80:
                descricao_curta = descricao_curta[:77].rstrip() + "..."
            preco = resposta.get("preco_venda") or 0
            moeda = resposta.get("moeda") or "EUR"
            validade = resposta.get("validade_preco") or ""
            fornecedor_valor = resposta.get("fornecedor_nome")
            fornecedor_nome = fornecedor_valor.strip() if isinstance(fornecedor_valor, str) else ""
            quantidade = resposta.get("quantidade_final") or resposta.get("quantidade_original") or "-"

            resumo_partes = []
            if fornecedor_nome:
                resumo_partes.append(f"[{fornecedor_nome}]")
            if descricao_curta:
                resumo_partes.append(descricao_curta)
            resumo_partes.append(f"Qtd: {quantidade}")
            resumo_partes.append(f"P.V.: {preco:.2f} {moeda}")

            validade_fmt = ""
            if validade:
                try:
                    validade_fmt = _format_iso_date(validade)
                except Exception:
                    validade_fmt = str(validade)
                if validade_fmt:
                    resumo_partes.append(f"Validade: {validade_fmt}")

            legenda = " · ".join([parte for parte in resumo_partes if parte])

            help_linhas = [descricao_completa.strip()]
            if fornecedor_nome:
                help_linhas.append(f"Fornecedor: {fornecedor_nome}")
            prazo = resposta.get("prazo_entrega")
            if prazo:
                help_linhas.append(f"Prazo de entrega: {prazo} dia(s)")
            if validade_fmt:
                help_linhas.append(f"Validade: {validade_fmt}")
            help_text = "\n".join([linha for linha in help_linhas if linha]) or None

            incluir_default = bool((preco and preco > 0) or ((resposta.get("custo") or 0) > 0))
            if respostas_destacadas_ids:
                incluir_default = resposta['id'] in respostas_destacadas_ids
            selecao_respostas[resposta['id']] = st.checkbox(
                legenda,
                value=incluir_default,
                key=f"cliente_sel_{rfq_id}_{resposta['id']}",
                help=help_text,
            )

        st.markdown('</div>', unsafe_allow_html=True)

        enviar_email = bool(email_cliente)
        if email_cliente:
            st.info(
                f"O PDF será enviado automaticamente para {email_cliente} após a criação."
            )
        else:
            st.warning(
                "Nenhum endereço de e-mail disponível para este cliente. A cotação será criada sem envio."
            )
        _, col_botao = st.columns([3, 1])
        with col_botao:
            submitted = st.form_submit_button(
                "Criar e Enviar",
                type="primary",
            )

    if not submitted:
        return

    selecionados = [rid for rid, ativo in selecao_respostas.items() if ativo]
    if not selecionados:
        st.error("Selecione pelo menos um artigo para gerar a cotação do cliente.")
        return

    if not gerar_pdf_cliente(rfq_id, resposta_ids=selecionados):
        st.error("Não foi possível gerar o PDF do cliente.")
        return

    st.success("Cotação do cliente gerada com sucesso!")

    pdf_bytes = obter_pdf_da_db(rfq_id, "cliente")
    if pdf_bytes:
        nome_base = numero_processo or f"cotacao_{rfq_id}"
        ficheiro_pdf = f"cliente_{nome_base}.pdf"
        st.session_state[pdf_session_key] = {
            "bytes": pdf_bytes,
            "file_name": ficheiro_pdf,
        }
        st.download_button(
            "⬇️ Descarregar PDF Cliente",
            data=pdf_bytes,
            file_name=ficheiro_pdf,
            mime="application/pdf",
            key=f"download_cliente_{rfq_id}"
        )

    if enviar_email and email_cliente:
        if enviar_email_orcamento(
            email_cliente,
            nome_cliente or "Cliente",
            referencia_cliente or "",
            numero_processo or "",
            rfq_id,
        ):
            st.success("E-mail enviado ao cliente com sucesso!")
        else:
            st.error("Falha ao enviar o e-mail ao cliente.")


def extrair_texto_pdf(pdf_bytes):
    """Retorna todo o texto contido num PDF."""
    reader = PdfReader(BytesIO(pdf_bytes))
    texto = ""
    for page in reader.pages:
        texto += (page.extract_text() or "") + "\n"
    return texto.strip()


def extrair_dados_pdf(pdf_bytes):
    """Extrai campos relevantes de um PDF de pedido de cotação."""
    reader = PdfReader(BytesIO(pdf_bytes))
    texto = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        texto += page_text + "\n"

    linhas_pdf = texto.splitlines()

    def linha_apos(label):
        idx = texto.find(label)
        if idx == -1:
            return ""
        restante = texto[idx + len(label):]
        for linha in restante.splitlines():
            linha = linha.strip()
            if linha:
                return linha
        return ""

    def proxima_linha_apos(conteudo):
        for idx, linha in enumerate(linhas_pdf):
            if conteudo in linha:
                for prox in linhas_pdf[idx + 1:]:
                    prox = prox.strip()
                    if prox:
                        return prox
                break
        return ""

    referencia = linha_apos("Our reference:")

    def limpar_final_destination(valor: str) -> str:
        """Remove o prefixo ``Final Destination`` e normaliza o resultado."""

        if not valor:
            return ""

        normalizado = re.sub(
            r"^Final\s*Destination\s*[:\-]?\s*",
            "",
            valor.strip(),
            flags=re.IGNORECASE,
        )
        normalizado = normalizado.replace('","', ", ")
        normalizado = re.sub(r"\s{2,}", " ", normalizado)
        normalizado = normalizado.strip().strip(",;\"'")
        return normalizado

    # ----------------------------- CLIENTE -----------------------------
    # Priorizar a extração do contacto ("Contact:" ou assinaturas "i.V."/"i.A.")
    cliente = linha_apos("Contact:")
    nome = cliente if cliente else ""

    if not cliente:
        match_nome = re.search(r"i\.[AV]\.\s*([^\n]+)", texto)
        if match_nome:
            nome = match_nome.group(1).strip()
            cliente = nome

    # Caso não tenha sido possível obter o contacto, usar "Client:" e outros
    if not cliente:
        cliente = linha_apos("Client:")

    # Fallbacks para layouts antigos
    if not cliente:
        match_data = re.search(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", texto)
        if match_data:
            restante = texto[match_data.end():]
            for linha in restante.splitlines():
                linha = linha.strip()
                if not linha:
                    continue
                if "Hamburg - Germany" in linha:
                    continue
                cliente = linha
                break

    cliente_hamburg = proxima_linha_apos("21079 Hamburg - Germany")
    if cliente_hamburg:
        if not cliente or cliente == nome or cliente.lower() in {"info"}:
            cliente = cliente_hamburg
        if not nome:
            nome = cliente_hamburg
    if "Gro\u00dfmoorring 9" in texto:
        idx_addr = texto.find("Gro\u00dfmoorring 9")
        linhas_antes = texto[:idx_addr].splitlines()
        for linha in reversed(linhas_antes):
            linha = linha.strip()
            if linha:
                if not cliente or cliente.lower() in {"info"}:
                    cliente = linha
                break

    # Garantir que o campo "nome" reflete o contacto identificado
    if not nome and cliente:
        nome = cliente

    cliente = limpar_final_destination(cliente)
    nome = limpar_final_destination(nome)

    def limpar_ktb(texto_desc):
        if not texto_desc:
            return ""
        idx = texto_desc.lower().find("ktb-code")
        if idx != -1:
            return texto_desc[:idx].strip()
        return texto_desc

    def extrair_codigo_segmento(segmento: str) -> str:
        """Devolve o primeiro token alfanumérico de um segmento de texto."""

        if not segmento:
            return ""

        segmento = segmento.strip()
        match_codigo = re.search(r"([A-Za-z0-9][A-Za-z0-9/.-]*)", segmento)
        if match_codigo:
            return match_codigo.group(1)
        return segmento

    descricao = ""
    artigo = ""
    ktb_codes: list[str] = []
    for idx, linha in enumerate(linhas_pdf):
        if "ktb-code" in linha.lower():
            codigo_ktb = ""

            match_inline = re.search(
                r"ktb[-\s]*code\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9/.-]*)",
                linha,
                re.IGNORECASE,
            )
            if match_inline:
                codigo_ktb = match_inline.group(1)
            else:
                prox_idx = idx + 1
                while prox_idx < len(linhas_pdf):
                    prox_linha = linhas_pdf[prox_idx].strip()
                    if prox_linha:
                        codigo_ktb = extrair_codigo_segmento(prox_linha)
                        break
                    prox_idx += 1

            if codigo_ktb:
                ktb_codes.append(codigo_ktb.strip())
                if not artigo:
                    artigo = codigo_ktb.strip()
    idx_ktb = texto.find("KTB-code:")
    if idx_ktb != -1:
        if not artigo:
            artigo = extrair_codigo_segmento(linha_apos("KTB-code:"))
        linhas_antes = texto[:idx_ktb].splitlines()
        padrao_item = re.compile(r"\b\d{3}\.00\b")
        extra = ""
        for linha in reversed(linhas_antes):
            linha = linha.strip()
            if not linha or linha.lower() in {"quantity %", "unit", "piece", "quantity"} or linha.isdigit():
                continue
            if re.match(r"^[A-Za-z0-9-]+$", linha) and not padrao_item.search(linha):
                extra = linha + (" " + extra if extra else "")
                continue
            if padrao_item.search(linha):
                linha = padrao_item.sub("", linha).strip()
            descricao = linha
            if extra:
                descricao = f"{descricao} {extra}".strip()
            break

    if not artigo and ktb_codes:
        artigo = ktb_codes[0]

    itens = []
    padrao_item = re.compile(r"^\s*(\d{3}\.\d{2})\s*(.*)")
    padrao_piece_qtd = re.compile(r"Piece\s*(\d+)", re.IGNORECASE)

    i = 0
    while i < len(linhas_pdf):
        linha = linhas_pdf[i].strip()
        m = padrao_item.match(linha)
        if m:
            codigo = m.group(1)
            restante = m.group(2).strip()
            desc_partes = []
            quantidade_item = None

            tokens = restante.split()
            if tokens and tokens[-1].isdigit():
                quantidade_item = int(tokens[-1])
                restante = " ".join(tokens[:-1]).strip()
            match_piece = padrao_piece_qtd.search(restante)
            if match_piece:
                quantidade_item = int(match_piece.group(1))
                restante = restante[:match_piece.start()].strip()
            if restante:
                restante_limpo = limpar_ktb(restante)
                if restante_limpo:
                    desc_partes.append(restante_limpo)
            else:
                # Se a linha do código não tiver descrição, procurar nas linhas anteriores
                k = i - 1
                while k >= 0:
                    prev = linhas_pdf[k].strip()
                    if not prev:
                        k -= 1
                        continue
                    if padrao_item.match(prev) or prev in {"Quantity", "Description"} or prev.endswith(":"):
                        break
                    desc_partes.insert(0, prev)
                    k -= 1
                    break

            j = i + 1
            while j < len(linhas_pdf):
                prox = linhas_pdf[j].strip()
                if not prox:
                    j += 1
                    continue
                if padrao_item.match(prox) or prox in {"Quantity", "Description"} or prox.endswith(":"):
                    break
                if j + 1 < len(linhas_pdf) and padrao_item.match(linhas_pdf[j + 1].strip()):
                    break
                if prox.lower() in {"piece", "quantity", "description", "unit"}:
                    j += 1
                    continue
                if "ktb-code" in prox.lower():
                    break
                match_piece = padrao_piece_qtd.search(prox)
                if match_piece:
                    quantidade_item = int(match_piece.group(1))
                    prox = prox[:match_piece.start()].strip()
                    if not prox:
                        j += 1
                        continue
                tokens = prox.split()
                if quantidade_item is None and tokens and tokens[-1].isdigit():
                    prev_lower = linhas_pdf[j-1].strip().lower() if j > 0 else ""
                    resto_tokens = " ".join(tokens[:-1]).strip()
                    if resto_tokens or ("quantity" in prev_lower or "piece" in prev_lower):
                        quantidade_item = int(tokens[-1])
                        prox = resto_tokens
                if prox:
                    prox_limpo = limpar_ktb(prox)
                    if prox_limpo:
                        desc_partes.append(prox_limpo)
                j += 1

            desc = limpar_ktb(" ".join(desc_partes).strip())
            item_index = len(itens)
            item = {"codigo": codigo, "descricao": desc}
            if item_index < len(ktb_codes):
                item["ktb_code"] = ktb_codes[item_index]
            if quantidade_item is not None:
                item["quantidade"] = quantidade_item
            itens.append(item)
            i = j
        else:
            i += 1

    # Usar sempre a descrição do primeiro item quando disponível
    if itens:
        descricao = itens[0]["descricao"]
        quantidade = itens[0].get("quantidade", 1)
    else:
        if not descricao:
            descricao = linha_apos("Piece")
        quantidade = 1

    descricao = limpar_ktb(descricao)

    marca = descricao.split()[0] if descricao else ""

    return {
        "referencia": referencia,
        "cliente": cliente,
        "artigo_num": artigo,
        "descricao": descricao,
        "quantidade": quantidade,
        "marca": marca,
        "itens": itens,
        "nome": nome,
    }

# ========================== FUNÇÕES DE UTILIDADE ==========================

@st.cache_data(show_spinner=False, ttl=30)
def obter_estatisticas_db(utilizador_id: int | None = None):
    """Obter estatísticas da base de dados."""

    try:
        conn = obter_conexao()
        c = conn.cursor()

        stats: dict[str, int] = {}

        # Contar registos principais
        if utilizador_id is None:
            c.execute("SELECT COUNT(*) FROM rfq")
        else:
            c.execute(
                """
                SELECT COUNT(*)
                  FROM rfq r
                  JOIN processo p ON r.processo_id = p.id
                 WHERE p.utilizador_id = ?
                """,
                (utilizador_id,),
            )
        stats["rfq"] = c.fetchone()[0]

        if utilizador_id is None:
            c.execute("SELECT COUNT(*) FROM fornecedor")
            stats["fornecedor"] = c.fetchone()[0]
        else:
            c.execute(
                """
                SELECT COUNT(DISTINCT r.fornecedor_id)
                  FROM rfq r
                  JOIN processo p ON r.processo_id = p.id
                 WHERE p.utilizador_id = ?
                   AND r.fornecedor_id IS NOT NULL
                """,
                (utilizador_id,),
            )
            stats["fornecedor"] = c.fetchone()[0]

        if utilizador_id is None:
            c.execute("SELECT COUNT(*) FROM artigo")
            stats["artigo"] = c.fetchone()[0]
        else:
            c.execute(
                """
                SELECT COUNT(*)
                  FROM artigo a
                  JOIN rfq r ON a.rfq_id = r.id
                  JOIN processo p ON r.processo_id = p.id
                 WHERE p.utilizador_id = ?
                """,
                (utilizador_id,),
            )
            stats["artigo"] = c.fetchone()[0]

        if utilizador_id is None:
            c.execute(
                """
                SELECT COUNT(*)
                FROM rfq r
                LEFT JOIN estado e ON r.estado_id = e.id
                WHERE COALESCE(e.nome, 'pendente') = 'pendente'
                """
            )
            stats["rfq_pendentes"] = c.fetchone()[0]
        else:
            c.execute(
                """
                SELECT COUNT(*)
                  FROM rfq r
                  JOIN processo p ON r.processo_id = p.id
                  LEFT JOIN estado e ON r.estado_id = e.id
                 WHERE COALESCE(e.nome, 'pendente') = 'pendente'
                   AND p.utilizador_id = ?
                """,
                (utilizador_id,),
            )
            stats["rfq_pendentes"] = c.fetchone()[0]

        if utilizador_id is None:
            c.execute(
                """
                SELECT COUNT(*)
                FROM rfq r
                LEFT JOIN estado e ON r.estado_id = e.id
                WHERE COALESCE(e.nome, 'pendente') = 'respondido'
                """
            )
            stats["rfq_respondidas"] = c.fetchone()[0]
        else:
            c.execute(
                """
                SELECT COUNT(*)
                  FROM rfq r
                  JOIN processo p ON r.processo_id = p.id
                  LEFT JOIN estado e ON r.estado_id = e.id
                 WHERE COALESCE(e.nome, 'pendente') = 'respondido'
                   AND p.utilizador_id = ?
                """,
                (utilizador_id,),
            )
            stats["rfq_respondidas"] = c.fetchone()[0]

        if utilizador_id is None:
            c.execute("SELECT COUNT(*) FROM pdf_storage WHERE tipo_pdf = 'cliente'")
        else:
            c.execute(
                """
                SELECT COUNT(*)
                  FROM pdf_storage ps
                  JOIN processo p ON CAST(ps.processo_id AS INTEGER) = p.id
                 WHERE ps.tipo_pdf = 'cliente'
                   AND p.utilizador_id = ?
                """,
                (utilizador_id,),
            )
        stats["pdfs_cliente"] = c.fetchone()[0]

        conn.close()
        return stats

    except Exception as e:
        print(f"Erro ao obter estatísticas: {e}")
        return {}

# ========================== INICIALIZAÇÃO DO SISTEMA ==========================

def inicializar_sistema():
    """Inicializar todo o sistema"""
    print("Inicializando sistema myERP...")
    
    if criar_base_dados_completa():
        print("✓ Base de dados inicializada")
    else:
        print("✗ Erro ao inicializar base de dados")
    
    stats = obter_estatisticas_db()
    print(f"✓ Sistema inicializado com {stats.get('rfq', 0)} RFQs e {stats.get('fornecedor', 0)} fornecedores")
    
    return True

# ========================== INTERFACE STREAMLIT ==========================

# Inicializar session state
if 'sistema_inicializado' not in st.session_state:
    st.session_state.sistema_inicializado = inicializar_sistema()

if 'artigos' not in st.session_state:
    st.session_state.artigos = [{
        "artigo_num": "",
        "descricao": "",
        "quantidade": "",
        "unidade": "Peças",
        "marca": ""
    }]

for artigo in st.session_state.artigos:
    if isinstance(artigo.get("quantidade"), (int, float)):
        artigo["quantidade"] = str(artigo["quantidade"])

if 'nova_cotacao_referencia' not in st.session_state:
    st.session_state.nova_cotacao_referencia = ""

if 'nova_cotacao_data' not in st.session_state:
    st.session_state.nova_cotacao_data = date.today()

if 'cliente_select_nova' not in st.session_state:
    st.session_state.cliente_select_nova = None

if st.session_state.pop("reset_nova_cotacao_form", False):
    st.session_state.nova_cotacao_referencia = ""
    st.session_state.nova_cotacao_data = date.today()
    st.session_state.cliente_select_nova = None

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.user_email = None
    st.session_state.user_nome = None


def login_screen():
    st.markdown("<h1 style='text-align:center;'>🔐 Login</h1>", unsafe_allow_html=True)
    # Estilizar o formulário para ser mais amplo e centralizado
    st.markdown(
        """
        <style>
        div[data-testid="stForm"] {
            max-width: 400px;
            margin: auto;
        }
        div[data-testid="stFormSubmitButton"] button {
            display: block;
            margin: 0 auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.form("login_form"):
        # ``strip`` evita falhas de autenticação devido a espaços acidentais
        username = st.text_input("Utilizador").strip()
        password = st.text_input("Palavra-passe", type="password")
        submitted = st.form_submit_button("Entrar")
    if submitted:
        user = obter_utilizador_por_username(username)
        if user and verify_password(password, user[2]):
            st.session_state.logged_in = True
            st.session_state.role = user[5]
            st.session_state.user_id = user[0]
            st.session_state.username = user[1]
            st.session_state.user_email = user[4]
            st.session_state.user_nome = user[3] or user[1]
            st.rerun()
        else:
            st.error("Credenciais inválidas")
    st.markdown(
        f"<div style='display:flex; justify-content:center;'>"
        f"<img src='data:image/png;base64,{base64.b64encode(LOGO_BYTES).decode()}' width='120'>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='text-align:center;'>Sistema myERP v4.0<br/>© 2025 Ricardo Nogueira</p>",
        unsafe_allow_html=True,
    )


if not st.session_state.logged_in:
    login_screen()
    st.stop()

# CSS personalizado
st.markdown("""
    <style>
    .stButton > button {
        width: 100%;
        margin: 2px 0;
    }

    .st-h2 {
        min-width: 60%;
    }

    .block-container {
        padding-top: 1rem;
    }
    
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        margin: 10px 0;
    }
    
    .success-message {
        background-color: #d4edda;
        border-color: #c3e6cb;
        color: #155724;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    
    .warning-message {
        background-color: #fff3cd;
        border-color: #ffeeba;
        color: #856404;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }
    </style>
""", unsafe_allow_html=True)

# Menu lateral
with st.sidebar:
    st.title("📋 Menu Principal")
    st.markdown(
        """
        <style>
        .nav-link:hover {
            color: white !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    opcoes_menu = [
        "🏠 Dashboard",
        "📝 Nova Cotação",
        "🤖 Smart Quotation",
        "📩 Process Center",
        "📊 Relatórios",
        "📄 PDFs",
        "📦 Artigos",
        "👤 Perfil",
    ]
    if st.session_state.get("role") in ["admin", "gestor"]:
        opcoes_menu.append("⚙️ Configurações")
    menu_option = option_menu(
        "",
        opcoes_menu,
        icons=["" for _ in opcoes_menu],
        menu_icon="",
        default_index=0,
        styles={
            # tornar o fundo do menu transparente para coincidir com a barra lateral
            "container": {"padding": "0", "background-color": "transparent"},
            # ajustar o tamanho de letra e evitar quebras de linha
            "nav-link": {
                "font-size": "14px",
                "text-align": "left",
                "margin": "2px",
                "--hover-color": "rgb(14, 17, 23)",
                "white-space": "nowrap",
                "padding": "4px 2px",
                "line-height": "24px",
            },
            "nav-link-selected": {"background-color": "rgb(14, 17, 23)", "color": "white"},
            "icon": {"display": "none"},
        },
    )
    
    st.markdown("---")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Sair", icon="🚪", key="sidebar_logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.role = None
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.user_email = None
        st.session_state.user_nome = None
        st.rerun()

    st.markdown("---")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image(LOGO_BYTES, width=80)
    st.markdown(
        "<div style='text-align:center; font-size: 12px;'>"
        "<p>Sistema myERP v4.0</p>"
        "<p>© 2025 Ricardo Nogueira</p>"
        "</div>",
        unsafe_allow_html=True,
    )

# ========================== PÁGINAS DO SISTEMA ==========================

previous_menu_option = st.session_state.get("last_menu_option")
if previous_menu_option != menu_option and menu_option == "🤖 Smart Quotation":
    reset_smart_quotation_state()
st.session_state.last_menu_option = menu_option

if menu_option == "🏠 Dashboard":
    nome_utilizador = (
        (st.session_state.get("user_nome") or st.session_state.get("username") or "")
        .strip()
    )
    if nome_utilizador:
        st.markdown(f"## Bem Vindo, {nome_utilizador}!")
    else:
        st.markdown("## Bem Vindo!")
    st.markdown("")

    stats = obter_estatisticas_db(st.session_state.get("user_id"))

    # Métricas principais
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total RFQs", stats.get('rfq', 0))
        st.metric("Pendentes", stats.get('rfq_pendentes', 0))
    
    with col2:
        st.metric("Respondidas", stats.get('rfq_respondidas', 0))
        st.metric("Taxa Resposta", f"{(stats.get('rfq_respondidas', 0) / max(stats.get('rfq', 1), 1) * 100):.1f}%")
    
    with col3:
        st.metric("Fornecedores", stats.get('fornecedor', 0))
        st.metric("Artigos", stats.get('artigo', 0))
    
    with col4:
        st.metric("PDFs Gerados", stats.get('pdfs_cliente', 0) * 2)
        st.metric("Orçamentos Enviados", stats.get('pdfs_cliente', 0))
    
    st.markdown("---")
    
    # Últimas cotações
    st.subheader("📋 Últimas Cotações")
    cotacoes_recentes = obter_todas_cotacoes(
        utilizador_id=st.session_state.get("user_id")
    )[:5]
    
    if cotacoes_recentes:
        for cotacao in cotacoes_recentes:
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            with col1:
                st.write(f"**{cotacao['processo']}** - {cotacao['fornecedor']}")
            with col2:
                st.write(f"Ref: {cotacao['referencia']}")
            with col3:
                st.write(f"Data: {cotacao['data']}")
            with col4:
                estado_cor = "🟢" if cotacao['estado'] == "respondido" else "🟡"
                st.write(f"{estado_cor} {cotacao['estado'].title()}")
    else:
        st.info("Nenhuma cotação registada ainda.")

elif menu_option == "📝 Nova Cotação":
    st.title("📝 Criar Nova Cotação")

    marcas = listar_todas_marcas()

    st.markdown(
        """
        <style>
        .delete-button-wrapper {
            display: flex;
            height: 100%;
            align-items: flex-end;
        }
        .delete-button-wrapper > div {
            width: 100%;
        }
        .delete-button-wrapper button {
            width: 100%;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.form(key="nova_cotacao_form"):
        clientes = listar_clientes()
        clientes_opcoes = [None] + clientes
        col_data, col_ref, col_cliente = st.columns([1.2, 1.8, 2.5])

        with col_data:
            data = st.date_input(
                "Data da cotação",
                key="nova_cotacao_data",
            )

        with col_ref:
            referencia_input = st.text_input(
                "Referência Cliente",
                key="nova_cotacao_referencia",
                placeholder="Insira a referência do cliente",
            )

        with col_cliente:
            cliente_sel = st.selectbox(
                "Cliente",
                options=clientes_opcoes,
                format_func=lambda x: x[1] if x else "Selecione um cliente",
                key="cliente_select_nova",
                placeholder="Escolha uma opção",
            )

        nome_solicitante = cliente_sel[1] if cliente_sel else ""
        email_solicitante = cliente_sel[2] if cliente_sel else ""

        st.markdown("### 📦 Artigos")

        if "pedido_cliente_anexos" not in st.session_state:
            st.session_state.pedido_cliente_anexos = []

        remover_indice = None
        for i, artigo in enumerate(st.session_state.artigos, 1):
            with st.expander(f"Artigo {i}", expanded=(i == 1)):
                col_desc, col_id, col_qty, col_del = st.columns([3, 1.5, 1, 0.5])

                with col_desc:
                    artigo['descricao'] = st.text_area(
                        "Descrição *",
                        value=artigo['descricao'],
                        key=f"nova_desc_{i}",
                        height=120,
                    )

                with col_id:
                    artigo['artigo_num'] = st.text_input(
                        "Nº Artigo",
                        value=artigo['artigo_num'],
                        key=f"nova_art_num_{i}",
                    )
                    marca_opcoes = ["Selecione"] + [m for m in marcas if m]
                    if artigo.get('marca') and artigo['marca'] not in marca_opcoes:
                        marca_opcoes.append(artigo['marca'])
                    artigo['marca'] = st.selectbox(
                        "Marca *",
                        marca_opcoes,
                        index=marca_opcoes.index(artigo['marca']) if artigo.get('marca') in marca_opcoes else 0,
                        key=f"nova_marca_{i}",
                    )

                with col_qty:
                    artigo['quantidade'] = st.text_input(
                        "Quantidade *",
                        value=str(artigo.get('quantidade', "")),
                        key=f"nova_qtd_{i}",
                        placeholder="Insira a quantidade",
                    )

                    opcoes_unidade = obter_nomes_unidades()
                    unidade_atual = artigo.get('unidade') or (opcoes_unidade[0] if opcoes_unidade else "Peças")
                    if unidade_atual not in opcoes_unidade:
                        opcoes_unidade = [*opcoes_unidade, unidade_atual]
                    indice_unidade = opcoes_unidade.index(unidade_atual) if unidade_atual in opcoes_unidade else 0
                    artigo['unidade'] = st.selectbox(
                        "Unidade",
                        opcoes_unidade,
                        index=indice_unidade,
                        key=f"nova_unidade_{i}",
                    )

                with col_del:
                    # st.form_submit_button does not accept a "key" argument in some
                    # Streamlit versions. To keep the delete buttons distinct without
                    # visible numbering, append invisible zero‑width characters so each
                    # label remains unique while displaying only the trash icon.
                    delete_label = "🗑️" + "\u200B" * i
                    st.markdown("<div class='delete-button-wrapper'>", unsafe_allow_html=True)
                    delete_clicked = st.form_submit_button(delete_label)
                    st.markdown("</div>", unsafe_allow_html=True)
                    if delete_clicked:
                        remover_indice = i - 1

        col_acoes_1, _, _ = st.columns([1, 1, 2])

        with col_acoes_1:
            adicionar_artigo = st.form_submit_button("➕ Adicionar Artigo")

        st.markdown("### 📎 Pedido do cliente")
        col_upload, col_submit = st.columns([3, 1.2])

        with col_upload:
            upload_pedido_cliente = st.file_uploader(
                "📎 Pedido do cliente (PDF ou email)",
                type=["pdf", "eml", "msg"],
                accept_multiple_files=True,
                key='upload_pedido_cliente'
            )
            if upload_pedido_cliente:
                st.session_state.pedido_cliente_anexos = processar_upload_pdf(upload_pedido_cliente)

            if st.session_state.pedido_cliente_anexos:
                for idx, (nome_pdf, pdf_bytes) in enumerate(st.session_state.pedido_cliente_anexos, start=1):
                    exibir_pdf(f"👁️ PDF carregado {idx} - {nome_pdf}", pdf_bytes, expanded=idx == 1)

        with col_submit:
            st.markdown(
                "<div style='height: 20px;'></div>",
                unsafe_allow_html=True,
            )
            criar_cotacao = st.form_submit_button(
                "✅ Criar Cotação",
                type="primary",
                use_container_width=True,
            )
            limpar_form = st.form_submit_button(
                "♻️ Limpar Formulário",
                use_container_width=True,
            )
    
    # Processar ações
    if remover_indice is not None:
        del st.session_state.artigos[remover_indice]
        if not st.session_state.artigos:
            st.session_state.artigos = [{
                "artigo_num": "",
                "descricao": "",
                "quantidade": "",
                "unidade": "Peças",
                "marca": ""
            }]
        st.rerun()

    if adicionar_artigo:
        st.session_state.artigos.append({
            "artigo_num": "",
            "descricao": "",
            "quantidade": "",
            "unidade": "Peças",
            "marca": ""
        })
        st.rerun()

    if limpar_form:
        st.session_state.artigos = [{
            "artigo_num": "",
            "descricao": "",
            "quantidade": "",
            "unidade": "Peças",
            "marca": ""
        }]
        st.rerun()

    if criar_cotacao:
        # Validar campos obrigatórios
        if not referencia_input.strip():
            st.error("Por favor, indique uma referência")
        elif not cliente_sel:
            st.error("Por favor, selecione um cliente")
        else:
            artigos_validos: list[dict] = []
            erros: list[str] = []

            for idx, art in enumerate(st.session_state.artigos, 1):
                descricao = art.get('descricao', '').strip()
                if not descricao:
                    continue
                marca = art.get('marca', '').strip()
                if not marca:
                    erros.append(f"Artigo {idx}: selecione uma marca")
                    continue
                quantidade_str = str(art.get('quantidade', '')).strip()
                if not quantidade_str:
                    erros.append(f"Artigo {idx}: indique uma quantidade")
                    continue
                try:
                    quantidade_valor = float(quantidade_str.replace(',', '.'))
                except ValueError:
                    erros.append(f"Artigo {idx}: quantidade inválida")
                    continue
                if quantidade_valor <= 0:
                    erros.append(f"Artigo {idx}: a quantidade deve ser superior a zero")
                    continue
                if quantidade_valor.is_integer():
                    quantidade_valor = int(quantidade_valor)
                descricao_normalizada = garantir_marca_primeira_palavra(
                    descricao, marca
                )
                artigos_validos.append({
                    "artigo_num": (art.get('artigo_num', '') or '').strip(),
                    "descricao": descricao_normalizada,
                    "quantidade": quantidade_valor,
                    "unidade": art.get('unidade', 'Peças'),
                    "marca": marca,
                })

            if not artigos_validos:
                st.error("Por favor, adicione pelo menos um artigo com descrição")
            elif erros:
                for mensagem in erros:
                    st.error(mensagem)
            else:
                contexto_criacao = {
                    "origem": "manual",
                    "data": data,
                    "referencia": referencia_input.strip(),
                    "cliente_id": cliente_sel[0] if cliente_sel else None,
                    "cliente_nome": cliente_sel[1] if cliente_sel else "",
                    "artigos": artigos_validos,
                    "anexos": st.session_state.get("pedido_cliente_anexos", []),
                    "anexo_tipo": "anexo_cliente",
                }
                processar_criacao_cotacoes(contexto_criacao)

    contexto_dup_manual = st.session_state.get("duplicated_ref_context")
    if contexto_dup_manual and contexto_dup_manual.get("origem") == "manual":
        if st.session_state.get("duplicated_ref_force") == "manual":
            contexto_confirmado = st.session_state.pop("duplicated_ref_context", None)
            st.session_state.pop("duplicated_ref_force", None)
            if contexto_confirmado:
                processar_criacao_cotacoes(contexto_confirmado, forcar=True)
        elif st.session_state.get("show_duplicate_ref_dialog"):
            mostrar_dialogo_referencia_duplicada("manual")

    contexto_req_manual = st.session_state.get("supplier_requirement_context")
    if contexto_req_manual and contexto_req_manual.get("origem") == "manual":
        if st.session_state.get("supplier_requirement_ready") == "manual":
            contexto_confirmado = st.session_state.pop("supplier_requirement_context", None)
            dados_confirmados = copy.deepcopy(
                st.session_state.get("supplier_requirement_data") or {}
            )
            st.session_state.pop("supplier_requirement_suppliers", None)
            st.session_state.pop("supplier_requirement_data", None)
            st.session_state.pop("supplier_requirement_ready", None)
            st.session_state.pop("supplier_requirement_origin", None)
            st.session_state.pop("show_supplier_requirement_dialog", None)
            if contexto_confirmado:
                contexto_confirmado = copy.deepcopy(contexto_confirmado)
                contexto_confirmado["requisitos_fornecedores"] = dados_confirmados
                processar_criacao_cotacoes(contexto_confirmado, forcar=True)
        elif st.session_state.get("show_supplier_requirement_dialog"):
            mostrar_dialogo_requisitos_fornecedor("manual")

elif menu_option == "🤖 Smart Quotation":
    st.title("🤖 Smart Quotation")

    unidades_padrao = obter_nomes_unidades()
    unidade_padrao = unidades_padrao[0] if unidades_padrao else "Peças"
    upload_pdf = st.file_uploader(
        "📎 Pedido do cliente (PDF ou email)",
        type=["pdf", "eml", "msg"],
        accept_multiple_files=False,
        key="smart_pdf",
    )
    if upload_pdf:
        anexos_processados = processar_upload_pdf(upload_pdf)
        if anexos_processados:
            nome_pdf, pdf_bytes = anexos_processados[0]
            dados = extrair_dados_pdf(pdf_bytes)
            clientes = listar_clientes()
            cliente_options: list[tuple | None] = [None] + clientes

            pdf_uid = f"{nome_pdf}:{len(pdf_bytes)}"
            descricao_formatada = normalizar_quebras_linha(
                dados.get("descricao") or ""
            )

            if st.session_state.get("smart_pdf_uid") != pdf_uid:
                reset_smart_quotation_state()
                st.session_state.smart_pdf_uid = pdf_uid
                st.session_state.smart_referencia = dados.get("referencia") or ""
                st.session_state.smart_unidade = unidade_padrao
                st.session_state.smart_marca = dados.get("marca") or ""

                itens_extraidos = dados.get("itens") or []
                artigos_extraidos: list[dict[str, str]] = []
                marca_padrao_pdf = (dados.get("marca") or "").strip()

                for item in itens_extraidos:
                    ktb_code_item = (item.get("ktb_code") or "").strip()
                    descricao_item = normalizar_quebras_linha(
                        (item.get("descricao") or "").strip()
                    )
                    if not descricao_tem_conteudo(descricao_item):
                        continue
                    quantidade_item = item.get("quantidade")
                    quantidade_str = ""
                    if quantidade_item is not None:
                        if isinstance(quantidade_item, (int, float)):
                            quantidade_str = str(quantidade_item)
                        else:
                            quantidade_str = str(quantidade_item).strip()

                    unidade_item = (item.get("unidade") or unidade_padrao).strip() or unidade_padrao
                    marca_item = (item.get("marca") or marca_padrao_pdf).strip()
                    if not marca_item and descricao_item:
                        marca_item = descricao_item.split()[0]

                    artigos_extraidos.append(
                        {
                            "artigo_num": ktb_code_item
                            or (dados.get("artigo_num") or ""),
                            "descricao": descricao_item,
                            "quantidade": quantidade_str,
                            "unidade": unidade_item,
                            "marca": marca_item,
                        }
                    )

                if not artigos_extraidos:
                    quantidade_base = dados.get("quantidade")
                    if isinstance(quantidade_base, (int, float)):
                        quantidade_base_str = str(quantidade_base)
                    else:
                        quantidade_base_str = str(quantidade_base or "").strip()

                    descricao_principal = (
                        descricao_formatada
                        if descricao_tem_conteudo(descricao_formatada)
                        else ""
                    )

                    if descricao_principal:
                        artigos_extraidos = [
                            {
                                "artigo_num": dados.get("artigo_num") or "",
                                "descricao": descricao_principal,
                                "quantidade": quantidade_base_str,
                                "unidade": unidade_padrao,
                                "marca": marca_padrao_pdf,
                            }
                        ]
                    else:
                        artigos_extraidos = [
                            {
                                "artigo_num": "",
                                "descricao": "",
                                "quantidade": quantidade_base_str,
                                "unidade": unidade_padrao,
                                "marca": marca_padrao_pdf,
                            }
                        ]

                st.session_state.smart_artigos = artigos_extraidos
                for idx, artigo in enumerate(artigos_extraidos):
                    st.session_state[f"smart_artigos_{idx}_artigo_num"] = artigo.get(
                        "artigo_num", "",
                    )
                    descricao_guardada = artigo.get("descricao", "")
                    st.session_state[f"smart_artigos_{idx}_descricao"] = descricao_guardada
                    st.session_state[f"smart_artigos_{idx}_quantidade"] = artigo.get(
                        "quantidade", "",
                    )
                    st.session_state[f"smart_artigos_{idx}_unidade"] = artigo.get(
                        "unidade", unidade_padrao
                    ) or unidade_padrao
                    marca_extraida = extrair_primeira_palavra(descricao_guardada)
                    if not marca_extraida:
                        marca_extraida = artigo.get("marca", "") or ""
                    st.session_state[f"smart_artigos_{idx}_marca"] = marca_extraida


                cliente_extraido = (dados.get("cliente") or "").strip().lower()
                default_idx = 0
                if cliente_extraido:
                    for idx, cli in enumerate(cliente_options):
                        if cli and cli[1].strip().lower() == cliente_extraido:
                            default_idx = idx
                            break
                st.session_state.smart_cliente_index = default_idx
            else:
                artigos_existentes = st.session_state.get("smart_artigos", [])
                for idx in range(len(artigos_existentes)):
                    desc_key = f"smart_artigos_{idx}_descricao"
                    if desc_key in st.session_state:
                        st.session_state[desc_key] = normalizar_quebras_linha(
                            st.session_state.get(desc_key, "")
                        )

            def _format_cliente(idx: int) -> str:
                cli = cliente_options[idx]
                if not cli:
                    return "Selecione um cliente"
                nome_cli = cli[1]
                empresa_cli = cli[4] if len(cli) > 4 else ""
                if empresa_cli:
                    return f"{nome_cli} ({empresa_cli})"
                return nome_cli

            col_form, col_pdf = st.columns(2)

            with col_form:
                st.text_input(
                    "Referência Cliente",
                    key="smart_referencia",
                )
                cliente_idx = st.selectbox(
                    "Cliente (Gestão de Clientes)",
                    options=list(range(len(cliente_options))),
                    format_func=_format_cliente,
                    key="smart_cliente_index",
                )
                artigos_guardados = st.session_state.get("smart_artigos", [])
                total_artigos = len(artigos_guardados)
                if total_artigos:
                    st.markdown("---")
                for idx, _ in enumerate(artigos_guardados):
                    st.markdown(f"**Artigo {idx + 1}**")
                    descricao_key = f"smart_artigos_{idx}_descricao"
                    marca_key = f"smart_artigos_{idx}_marca"
                    descricao_atual = st.session_state.get(descricao_key, "")

                    marca_valor_guardado = st.session_state.get(marca_key)
                    marca_registada = (marca_valor_guardado or "").strip()

                    if marca_registada:
                        if marca_valor_guardado != marca_registada:
                            st.session_state[marca_key] = marca_registada
                    else:
                        marca_detectada = extrair_primeira_palavra(descricao_atual)
                        if marca_detectada:
                            st.session_state[marca_key] = marca_detectada
                            marca_registada = marca_detectada

                    col_art, col_qtd, col_uni, col_marca = st.columns([1.4, 1, 1, 1.6])
                    with col_art:
                        st.text_input(
                            "Nº Artigo",
                            key=f"smart_artigos_{idx}_artigo_num",
                        )
                    with col_qtd:
                        st.text_input(
                            "Quantidade",
                            key=f"smart_artigos_{idx}_quantidade",
                        )
                    with col_uni:
                        unidade_key = f"smart_artigos_{idx}_unidade"
                        unidade_atual = st.session_state.get(unidade_key, unidade_padrao)
                        opcoes_unidade = [*unidades_padrao]
                        if unidade_atual not in opcoes_unidade:
                            opcoes_unidade.append(unidade_atual)
                        st.selectbox(
                            "Unidade",
                            options=opcoes_unidade,
                            index=opcoes_unidade.index(unidade_atual)
                            if unidade_atual in opcoes_unidade
                            else 0,
                            key=unidade_key,
                        )
                    with col_marca:
                        st.text_input(
                            "Marca",
                            key=marca_key,
                            help=(
                                "A marca é sugerida automaticamente com base na descrição,"
                                " mas pode ser editada."
                            ),
                        )

                    st.text_area(
                        "Descrição",
                        key=f"smart_artigos_{idx}_descricao",
                        height=140,
                        help="As quebras de linha serão mantidas na geração da cotação.",
                    )

                    if idx < total_artigos - 1:
                        st.markdown("---")

                artigos_atualizados: list[dict[str, str]] = []
                for idx in range(len(artigos_guardados)):
                    artigos_atualizados.append(
                        {
                            "artigo_num": st.session_state.get(
                                f"smart_artigos_{idx}_artigo_num", "",
                            ),
                            "descricao": st.session_state.get(
                                f"smart_artigos_{idx}_descricao", "",
                            ),
                            "quantidade": st.session_state.get(
                                f"smart_artigos_{idx}_quantidade", "",
                            ),
                            "unidade": st.session_state.get(
                                f"smart_artigos_{idx}_unidade", unidade_padrao
                            ),
                            "marca": st.session_state.get(
                                f"smart_artigos_{idx}_marca", "",
                            ),
                        }
                    )
                st.session_state.smart_artigos = artigos_atualizados

                cliente_selecionado = (
                    cliente_options[cliente_idx]
                    if 0 <= cliente_idx < len(cliente_options)
                    else None
                )

                if st.button("Submeter", type="primary", key="smart_submit"):
                    if not cliente_selecionado:
                        st.error("Selecione um cliente existente na gestão de clientes.")
                    else:
                        referencia = (st.session_state.get("smart_referencia") or "").strip()
                        artigos_info = st.session_state.get("smart_artigos") or []
                        artigos_final: list[dict] = []
                        artigos_posicoes: list[int] = []
                        erros: list[str] = []

                        for idx, _ in enumerate(artigos_info):
                            artigo_num_val = (
                                st.session_state.get(
                                    f"smart_artigos_{idx}_artigo_num", "",
                                )
                                or ""
                            ).strip()
                            descricao_input = (
                                st.session_state.get(
                                    f"smart_artigos_{idx}_descricao", "",
                                )
                                or ""
                            ).strip()
                            if not descricao_input:
                                continue
                            if not descricao_tem_conteudo(descricao_input):
                                erros.append(
                                    f"Artigo {idx + 1}: indique uma descrição com conteúdo."
                                )
                                continue

                            marca_key = f"smart_artigos_{idx}_marca"
                            marca_val = (st.session_state.get(marca_key) or "").strip()

                            if not marca_val:
                                erros.append(
                                    f"Artigo {idx + 1}: indique a marca do artigo."
                                )
                                continue

                            unidade_val = (
                                st.session_state.get(
                                    f"smart_artigos_{idx}_unidade", unidade_padrao
                                )
                                or unidade_padrao
                            )
                            unidade_val = str(unidade_val).strip() or unidade_padrao

                            quantidade_raw = (
                                st.session_state.get(
                                    f"smart_artigos_{idx}_quantidade", "",
                                )
                                or ""
                            )
                            quantidade_str = str(quantidade_raw).strip()

                            quantidade_valor: int | float | str
                            if not quantidade_str:
                                quantidade_valor = 1
                            else:
                                try:
                                    quantidade_valor = int(quantidade_str)
                                except ValueError:
                                    try:
                                        quantidade_valor = float(
                                            quantidade_str.replace(",", ".")
                                        )
                                    except ValueError:
                                        quantidade_valor = quantidade_str

                            descricao_normalizada = garantir_marca_primeira_palavra(
                                normalizar_quebras_linha(descricao_input), marca_val
                            )

                            artigos_final.append(
                                {
                                    "artigo_num": artigo_num_val,
                                    "descricao": descricao_normalizada,
                                    "quantidade": quantidade_valor,
                                    "unidade": unidade_val,
                                    "marca": marca_val,
                                }
                            )
                            artigos_posicoes.append(idx + 1)

                        if not artigos_final:
                            if erros:
                                for mensagem in erros:
                                    st.error(mensagem)
                            else:
                                st.error(
                                    "Indique pelo menos um artigo com descrição para gerar a cotação."
                                )
                        elif erros:
                            for mensagem in erros:
                                st.error(mensagem)
                        else:
                            contexto_criacao_smart = {
                                "origem": "smart",
                                "data": datetime.today(),
                                "referencia": referencia,
                                "cliente_id": cliente_selecionado[0],
                                "cliente_nome": cliente_selecionado[1] if cliente_selecionado else "",
                                "artigos": artigos_final,
                                "artigos_posicoes": artigos_posicoes,
                                "anexos": anexos_processados,
                                "anexo_tipo": "anexo_cliente",
                            }
                            processar_criacao_cotacoes(contexto_criacao_smart)

            with col_pdf:
                exibir_pdf(
                    f"👁️ PDF carregado - {nome_pdf}",
                    pdf_bytes,
                    expanded=True,
                    use_expander=False,
                    sticky=True,
                    sticky_top=110,
                )
        else:
            st.warning("Ficheiro carregado não pôde ser processado.")
    else:
        if st.session_state.get("smart_pdf_uid"):
            reset_smart_quotation_state()
        st.session_state.pop("smart_pdf", None)

    contexto_dup_smart = st.session_state.get("duplicated_ref_context")
    if contexto_dup_smart and contexto_dup_smart.get("origem") == "smart":
        if st.session_state.get("duplicated_ref_force") == "smart":
            contexto_confirmado = st.session_state.pop("duplicated_ref_context", None)
            st.session_state.pop("duplicated_ref_force", None)
            if contexto_confirmado:
                processar_criacao_cotacoes(contexto_confirmado, forcar=True)
        elif st.session_state.get("show_duplicate_ref_dialog"):
            mostrar_dialogo_referencia_duplicada("smart")

    contexto_req_smart = st.session_state.get("supplier_requirement_context")
    if contexto_req_smart and contexto_req_smart.get("origem") == "smart":
        if st.session_state.get("supplier_requirement_ready") == "smart":
            contexto_confirmado = st.session_state.pop("supplier_requirement_context", None)
            dados_confirmados = copy.deepcopy(
                st.session_state.get("supplier_requirement_data") or {}
            )
            st.session_state.pop("supplier_requirement_suppliers", None)
            st.session_state.pop("supplier_requirement_data", None)
            st.session_state.pop("supplier_requirement_ready", None)
            st.session_state.pop("supplier_requirement_origin", None)
            st.session_state.pop("show_supplier_requirement_dialog", None)
            if contexto_confirmado:
                contexto_confirmado = copy.deepcopy(contexto_confirmado)
                contexto_confirmado["requisitos_fornecedores"] = dados_confirmados
                processar_criacao_cotacoes(contexto_confirmado, forcar=True)
        elif st.session_state.get("show_supplier_requirement_dialog"):
            mostrar_dialogo_requisitos_fornecedor("smart")

    mostrar_dialogo_sucesso_smart()
elif menu_option == "📩 Process Center":
    st.title("📩 Process Center")

    PAGE_SIZE = 10
    if "cotacoes_pend_page" not in st.session_state:
        st.session_state.cotacoes_pend_page = 0
    if "cotacoes_resp_page" not in st.session_state:
        st.session_state.cotacoes_resp_page = 0
    if "cotacoes_arq_page" not in st.session_state:
        st.session_state.cotacoes_arq_page = 0

    fornecedores = listar_fornecedores()
    fornecedor_options = {"Todos": None}
    fornecedor_options.update({f[1]: f[0] for f in fornecedores})
    fornecedor_option_labels = list(fornecedor_options.keys())

    utilizadores = listar_utilizadores()
    utilizador_options = {"Todos": None}
    utilizador_options.update({(u[2] or u[1]): u[0] for u in utilizadores})
    utilizador_option_labels = list(utilizador_options.keys())

    current_user_id = st.session_state.get("user_id")
    default_user_label = next(
        (label for label, uid in utilizador_options.items() if uid == current_user_id),
        None,
    )
    if default_user_label:
        for key in ("utilizador_pend", "utilizador_resp", "utilizador_arq"):
            if key not in st.session_state:
                st.session_state[key] = default_user_label

    tab_process_center, tab_pendentes, tab_respondidas, tab_arquivados = st.tabs(
        ["Process Center", "Pendentes", "Respondidas", "Arquivados"]
    )

    with tab_pendentes:
        # Filtros
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1], vertical_alignment="bottom")
        with col1:
            filtro_ref_pend = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_pend")
        with col2:
            fornecedor_sel_pend = st.selectbox(
                "Fornecedor",
                fornecedor_option_labels,
                key="fornecedor_pend",
            )
        with col3:
            utilizador_sel_pend = st.selectbox(
                "Utilizador",
                utilizador_option_labels,
                key="utilizador_pend",
            )
        with col4:
            st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
            if st.button("🔄 Atualizar", key="refresh_pend"):
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        fornecedor_id_pend = fornecedor_options[fornecedor_sel_pend]
        utilizador_id_pend = utilizador_options[utilizador_sel_pend]

        cotacoes_pendentes, total_pend = obter_todas_cotacoes(
            filtro_ref_pend,
            "pendente",
            fornecedor_id_pend,
            utilizador_id_pend,
            page=st.session_state.cotacoes_pend_page,
            page_size=PAGE_SIZE,
            return_total=True,
        )
        total_paginas_pend = max(1, (total_pend + PAGE_SIZE - 1) // PAGE_SIZE)

        # Garantir que a página atual está dentro dos limites
        if st.session_state.cotacoes_pend_page > total_paginas_pend - 1:
            st.session_state.cotacoes_pend_page = max(0, total_paginas_pend - 1)
            st.rerun()

        if cotacoes_pendentes:
            for cotacao in cotacoes_pendentes:
                with st.expander(f"{cotacao['processo']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    # Mostrar informações da cotação
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.write(f"**Data:** {cotacao['data']}")
                        # Mostrar anexos existentes
                        conn = obter_conexao()
                        c = conn.cursor()
                        processo_id_pdf = (
                            cotacao.get("processo_id")
                            or resolve_processo_id(cotacao["id"], cursor=c)
                        )
                        anexos = []
                        if processo_id_pdf is not None:
                            c.execute(
                                """
                                SELECT tipo_pdf, nome_ficheiro, pdf_data
                                FROM pdf_storage
                                WHERE processo_id = ? AND (
                                    tipo_pdf = 'anexo_cliente' OR tipo_pdf LIKE 'anexo_cliente_%'
                                    OR tipo_pdf = 'anexo_fornecedor' OR tipo_pdf LIKE 'anexo_fornecedor_%'
                                )
                                ORDER BY data_criacao
                                """,
                                (str(processo_id_pdf),),
                            )
                            anexos = c.fetchall()

                        conn.close()
                        if anexos:
                            st.markdown("**Anexos:**")
                            for tipo, nome, data_pdf in anexos:
                                rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                st.download_button(
                                    label=f"⬇️ {rotulo}",
                                    data=data_pdf,
                                    file_name=nome if nome else f"{tipo}_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"anexo_{cotacao['id']}_{tipo}"
                                )
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")

                    with col2:
                        # Botões de ação
                        pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_pedido:
                            st.download_button(
                                "📄 PDF",
                                data=pdf_pedido,
                                file_name=f"pedido_{cotacao['processo']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_pend_{cotacao['id']}"
                            )

                        st.caption(
                            "Responder à cotação disponível apenas no Process Center."
                        )

                        col_arc, col_del = st.columns(2)

                        with col_arc:
                            if st.button("📦 Arquivar", key=f"arc_pend_{cotacao['id']}"):
                                st.session_state.confirmacao = ("arquivar", cotacao['id'])

                        with col_del:
                            if st.button("🗑️ Eliminar", key=f"del_pend_{cotacao['id']}"):
                                st.session_state.confirmacao = ("eliminar", cotacao['id'])
        else:
            st.info("Não há cotações pendentes")

        st.markdown("---")
        st.write(
            f"Página {st.session_state.cotacoes_pend_page + 1} de {total_paginas_pend}"
        )
        nav_prev, nav_next = st.columns(2)
        if nav_prev.button(
            "⬅️ Anterior",
            key="pend_prev",
            disabled=st.session_state.cotacoes_pend_page == 0,
        ):
            st.session_state.cotacoes_pend_page -= 1
            st.rerun()
        if nav_next.button(
            "Próximo ➡️",
            key="pend_next",
            disabled=st.session_state.cotacoes_pend_page >= total_paginas_pend - 1,
        ):
            st.session_state.cotacoes_pend_page += 1
            st.rerun()

    with tab_respondidas:
        # Filtros
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1], vertical_alignment="bottom")
        with col1:
            filtro_ref_resp = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_resp")
        with col2:
            fornecedor_sel_resp = st.selectbox(
                "Fornecedor",
                fornecedor_option_labels,
                key="fornecedor_resp",
            )
        with col3:
            utilizador_sel_resp = st.selectbox(
                "Utilizador",
                utilizador_option_labels,
                key="utilizador_resp",
            )
        with col4:
            st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
            if st.button("🔄 Atualizar", key="refresh_resp"):
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        fornecedor_id_resp = fornecedor_options[fornecedor_sel_resp]
        utilizador_id_resp = utilizador_options[utilizador_sel_resp]

        cotacoes_respondidas, total_resp = obter_todas_cotacoes(
            filtro_ref_resp,
            "respondido",
            fornecedor_id_resp,
            utilizador_id_resp,
            page=st.session_state.cotacoes_resp_page,
            page_size=PAGE_SIZE,
            return_total=True,
        )
        total_paginas_resp = max(1, (total_resp + PAGE_SIZE - 1) // PAGE_SIZE)

        # Garantir que a página atual está dentro dos limites
        if st.session_state.cotacoes_resp_page > total_paginas_resp - 1:
            st.session_state.cotacoes_resp_page = max(0, total_paginas_resp - 1)
            st.rerun()

        if cotacoes_respondidas:
            for idx_cotacao, cotacao in enumerate(cotacoes_respondidas):
                with st.expander(f"{cotacao['processo']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    # Detalhes da cotação
                    detalhes = obter_detalhes_cotacao(cotacao['id'])
                    respostas = obter_respostas_cotacao(cotacao['id'])
                    
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        st.write(f"**Data:** {cotacao['data']}")
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")

                        if respostas:
                            st.markdown("---")
                            st.markdown("**Resumo das Respostas:**")
                            total_geral = 0
                            for resp in respostas:
                                preco_total = resp['preco_venda'] * resp['quantidade_final']
                                total_geral += preco_total
                                st.write(f"• {resp['descricao'][:50]}...")
                                st.write(f"  Qtd: {resp['quantidade_final']} | P.V.: EUR {resp['preco_venda']:.2f} | Total: EUR {preco_total:.2f}")
                            st.success(f"**Total Geral: EUR {total_geral:.2f}**")

                        artigos_processo, fornecedores_estado = ([], [])
                        if cotacao.get('processo_id'):
                            artigos_processo, fornecedores_estado = obter_respostas_por_processo(cotacao['processo_id'])

                        if fornecedores_estado:
                            st.markdown("---")
                            st.markdown("**Estado dos Fornecedores no Processo:**")
                            for fornecedor_estado in fornecedores_estado:
                                emoji = "🟢" if (fornecedor_estado.get("estado") or "").lower() == "respondido" else "🟡"
                                st.write(f"{emoji} {fornecedor_estado['nome']}")

                        if artigos_processo:
                            st.markdown("---")
                            st.info(
                                "Seleção de propostas e envio ao cliente disponíveis apenas no Process Center."
                            )

                    with col2:
                        # Anexos
                        conn = obter_conexao()
                        c = conn.cursor()
                        processo_id_pdf = (
                            cotacao.get("processo_id")
                            or resolve_processo_id(cotacao['id'], cursor=c)
                        )
                        anexos = []
                        if processo_id_pdf is not None:
                            c.execute(
                                """
                                SELECT tipo_pdf, nome_ficheiro, pdf_data
                                FROM pdf_storage
                                WHERE processo_id = ? AND (
                                    tipo_pdf = 'anexo_cliente' OR tipo_pdf LIKE 'anexo_cliente_%'
                                    OR tipo_pdf = 'anexo_fornecedor' OR tipo_pdf LIKE 'anexo_fornecedor_%'
                                )
                                ORDER BY data_criacao
                                """,
                                (str(processo_id_pdf),),
                            )
                            anexos = c.fetchall()
                        conn.close()
                        if anexos:
                            st.markdown("**Anexos:**")
                            for tipo, nome, data_pdf in anexos:
                                rotulo = f"{tipo} - {nome if nome else 'ficheiro.pdf'}"
                                st.download_button(
                                    label=f"⬇️ {rotulo}",
                                    data=data_pdf,
                                    file_name=nome if nome else f"{tipo}_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"anexo_resp_{cotacao['id']}_{tipo}"
                                )

                        pdf_interno = obter_pdf_da_db(cotacao['id'], "pedido")
                        pdf_cliente = obter_pdf_da_db(cotacao['id'], "cliente")

                        col_pdf_int, col_info = st.columns(2)

                        with col_pdf_int:
                            if pdf_interno:
                                st.download_button(
                                    "📄 PDF Interno",
                                    data=pdf_interno,
                                    file_name=f"interno_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_int_{cotacao['id']}",
                                )

                        with col_info:
                            st.caption(
                                "Envio de respostas ao cliente disponível apenas no Process Center."
                            )

                        col_pdf_cli, col_del = st.columns(2)

                        with col_pdf_cli:
                            if pdf_cliente:
                                st.download_button(
                                    "💰 PDF Cliente",
                                    data=pdf_cliente,
                                    file_name=f"cliente_{cotacao['processo']}.pdf",
                                    mime="application/pdf",
                                    key=f"pdf_cli_{cotacao['id']}",
                                )

                        with col_del:
                            if st.button("🗑️ Eliminar", key=f"del_resp_{cotacao['id']}"):
                                st.session_state.confirmacao = ("eliminar", cotacao['id'])
        else:
            st.info("Não há cotações respondidas")

        st.markdown("---")
        st.write(
            f"Página {st.session_state.cotacoes_resp_page + 1} de {total_paginas_resp}"
        )
        nav_prev_r, nav_next_r = st.columns(2)
        if nav_prev_r.button(
            "⬅️ Anterior",
            key="resp_prev",
            disabled=st.session_state.cotacoes_resp_page == 0,
        ):
            st.session_state.cotacoes_resp_page -= 1
            st.rerun()
        if nav_next_r.button(
            "Próximo ➡️",
            key="resp_next",
            disabled=st.session_state.cotacoes_resp_page >= total_paginas_resp - 1,
        ):
            st.session_state.cotacoes_resp_page += 1
            st.rerun()

    with tab_arquivados:
        # Filtros
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1], vertical_alignment="bottom")
        with col1:
            filtro_ref_arq = st.text_input("🔍 Pesquisar por referência", placeholder="Referência...", key="filtro_arq")
        with col2:
            fornecedor_sel_arq = st.selectbox(
                "Fornecedor",
                fornecedor_option_labels,
                key="fornecedor_arq",
            )
        with col3:
            utilizador_sel_arq = st.selectbox(
                "Utilizador",
                utilizador_option_labels,
                key="utilizador_arq",
            )
        with col4:
            st.markdown("<div style='display:flex;justify-content:center;'>", unsafe_allow_html=True)
            if st.button("🔄 Atualizar", key="refresh_arq"):
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        fornecedor_id_arq = fornecedor_options[fornecedor_sel_arq]
        utilizador_id_arq = utilizador_options[utilizador_sel_arq]

        cotacoes_arq, total_arq = obter_todas_cotacoes(
            filtro_ref_arq,
            "arquivada",
            fornecedor_id_arq,
            utilizador_id_arq,
            page=st.session_state.cotacoes_arq_page,
            page_size=PAGE_SIZE,
            return_total=True,
        )
        total_paginas_arq = max(1, (total_arq + PAGE_SIZE - 1) // PAGE_SIZE)

        if st.session_state.cotacoes_arq_page > total_paginas_arq - 1:
            st.session_state.cotacoes_arq_page = max(0, total_paginas_arq - 1)
            st.rerun()

        if cotacoes_arq:
            for cotacao in cotacoes_arq:
                with st.expander(f"{cotacao['processo']} - {cotacao['fornecedor']} - Ref: {cotacao['referencia']}", expanded=False):
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.write(f"**Data:** {cotacao['data']}")
                        st.write(f"**Solicitante:** {cotacao['nome_solicitante'] if cotacao['nome_solicitante'] else 'N/A'}")
                        st.write(f"**Email:** {cotacao['email_solicitante'] if cotacao['email_solicitante'] else 'N/A'}")
                        st.write(f"**Criado por:** {cotacao['criador'] if cotacao['criador'] else 'N/A'}")
                        st.write(f"**Artigos:** {cotacao['num_artigos']}")

                    with col2:
                        pdf_pedido = obter_pdf_da_db(cotacao['id'], "pedido")
                        if pdf_pedido:
                            st.download_button(
                                "📄 PDF",
                                data=pdf_pedido,
                                file_name=f"pedido_{cotacao['processo']}.pdf",
                                mime="application/pdf",
                                key=f"pdf_arq_{cotacao['id']}"
                            )

                        if st.button("🗑️ Eliminar", key=f"del_arq_{cotacao['id']}"):
                            st.session_state.confirmacao = ("eliminar", cotacao['id'])
        else:
            st.info("Não há cotações arquivadas")

        st.markdown("---")
        st.write(
            f"Página {st.session_state.cotacoes_arq_page + 1} de {total_paginas_arq}"
        )
        nav_prev_a, nav_next_a = st.columns(2)
        if nav_prev_a.button(
            "⬅️ Anterior",
            key="arq_prev",
            disabled=st.session_state.cotacoes_arq_page == 0,
        ):
            st.session_state.cotacoes_arq_page -= 1
            st.rerun()
        if nav_next_a.button(
            "Próximo ➡️",
            key="arq_next",
            disabled=st.session_state.cotacoes_arq_page >= total_paginas_arq - 1,
        ):
            st.session_state.cotacoes_arq_page += 1
            st.rerun()

    with tab_process_center:
        with st.form("process_center_form"):
            col_input, col_button = st.columns([6, 1], vertical_alignment="bottom")
            with col_input:
                termo_pesquisa = st.text_input(
                    "Processo ou referência",
                    key="process_center_term",
                    placeholder="QT2025-0001 ou KTB-DEXXX",
                )
            with col_button:
                submitted = st.form_submit_button(
                    "Pesquisar", type="primary", use_container_width=True
                )

        if submitted:
            termo = (termo_pesquisa or "").strip()
            if not termo:
                st.warning("Introduza um termo de pesquisa válido.")
            else:
                resultados = procurar_processos_por_termo(termo)
                st.session_state.process_center_results = resultados
                st.session_state.process_center_selected_id = (
                    resultados[0]["id"] if resultados else None
                )
                st.session_state.process_center_focus_ref = termo
                if not resultados:
                    st.warning("Nenhum processo encontrado para o termo indicado.")

        resultados = st.session_state.get("process_center_results", [])
        processo_selecionado_id = st.session_state.get("process_center_selected_id")
        foco_referencia = (st.session_state.get("process_center_focus_ref") or "").lower()

        if resultados:
            indices = list(range(len(resultados)))
            indice_default = 0
            for idx, processo in enumerate(resultados):
                if processo.get("id") == processo_selecionado_id:
                    indice_default = idx
                    break

            def _format_result(idx: int) -> str:
                item = resultados[idx]
                descricao = f" • {item['descricao']}" if item.get("descricao") else ""
                return (
                    f"{item['numero']} • {item['total_pedidos']} pedidos{descricao}"
                )

            selected_index = st.selectbox(
                "Processos encontrados",
                options=indices,
                index=indice_default if indices else 0,
                format_func=_format_result,
            )

            processo_escolhido = resultados[selected_index]
            st.session_state.process_center_selected_id = processo_escolhido.get("id")

            detalhes_processo = obter_detalhes_processo(processo_escolhido.get("id"))

            if detalhes_processo:
                processo_info = detalhes_processo.get("processo", {})
                resumo_col, pedido_cliente_col = st.columns(2)

                def _estado_envio_cliente(enviados: int, total: int) -> tuple[str, str]:
                    if not total:
                        return "⚪️", "Sem artigos do cliente"
                    if enviados <= 0:
                        return "🔴", "Sem envios ao cliente"
                    if enviados < total:
                        return "🟡", "Envio parcial ao cliente"
                    return "🟢", "Todos os artigos enviados ao cliente"

                with resumo_col:
                    st.markdown(f"### {processo_info.get('numero', 'Processo')}")
                    if processo_info.get("descricao"):
                        st.caption(processo_info.get("descricao"))

                    info_cols = st.columns(3)
                    with info_cols[0]:
                        st.write(
                            f"**Abertura:** {_format_iso_date(processo_info.get('data_abertura')) or '—'}"
                        )
                    with info_cols[1]:
                        estado = processo_info.get("estado") or ""
                        st.write(f"**Estado:** {estado.title() if estado else '—'}")
                    with info_cols[2]:
                        st.write(
                            f"**Artigos registados:** {len(detalhes_processo.get('artigos', []))}"
                        )

                    metric_cols = st.columns(3)
                    with metric_cols[0]:
                        st.metric("Pedidos fornecedor", detalhes_processo.get("total_rfqs", 0))
                    with metric_cols[1]:
                        st.metric("Respostas recebidas", detalhes_processo.get("respondidas", 0))
                    with metric_cols[2]:
                        pendentes = max(
                            detalhes_processo.get("total_rfqs", 0) - detalhes_processo.get("respondidas", 0),
                            0,
                        )
                        st.metric("Pendentes", pendentes)

                    cliente_envios = detalhes_processo.get("cliente_envios") or {}
                    emoji_envio, texto_envio = _estado_envio_cliente(
                        cliente_envios.get("enviados", 0),
                        cliente_envios.get("total", 0),
                    )
                    st.write(f"**Envio ao cliente:** {emoji_envio} {texto_envio}")

                with pedido_cliente_col:
                    st.subheader("Pedido Cliente")

                    artigos_processo = detalhes_processo.get("artigos", [])
                    if artigos_processo:
                        df_cliente = pd.DataFrame(
                            [
                                {
                                    "Nº Artigo": artigo.get("artigo_num") or "",
                                    "Descrição": artigo.get("descricao"),
                                    "Qtd": artigo.get("quantidade"),
                                    "Unidade": artigo.get("unidade"),
                                    "Marca": artigo.get("marca") or "",
                                }
                                for artigo in artigos_processo
                            ]
                        )
                        st.dataframe(df_cliente, use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum artigo registado para este processo.")

                st.markdown("---")
                st.subheader("Pedidos Fornecedor")

                pedidos_fornecedor = detalhes_processo.get("rfqs", [])
                pedidos_com_resposta = []
                if pedidos_fornecedor:
                    for pedido in pedidos_fornecedor:
                        estado_lower = (pedido.get("estado") or "").lower()
                        if estado_lower == "respondido" or pedido.get("total_respostas", 0) > 0:
                            emoji = "🟢"
                        elif estado_lower == "arquivada":
                            emoji = "⚪️"
                        else:
                            emoji = "🟡"

                        emoji_cliente, texto_cliente = _estado_envio_cliente(
                            pedido.get("artigos_enviados_cliente", 0),
                            pedido.get("total_artigos_cliente", 0),
                        )

                        titulo_expander = (
                            f"{emoji} {pedido.get('fornecedor', 'Fornecedor')}"
                            f" • Ref: {pedido.get('referencia', '—')}"
                        )
                        expanded = foco_referencia and foco_referencia == (pedido.get("referencia") or "").lower()

                        with st.expander(titulo_expander, expanded=bool(expanded)):
                            cotacao_contexto = {
                                "id": pedido.get("id"),
                                "processo": processo_info.get("numero") or "Processo",
                            }
                            botoes_acoes = st.columns([1, 1])
                            with botoes_acoes[0]:
                                if st.button(
                                    "💬 Responder",
                                    key=f"pc_resp_{pedido.get('id')}",
                                ):
                                    responder_cotacao_dialog(cotacao_contexto)

                            with botoes_acoes[1]:
                                pdf_pedido = obter_pdf_da_db(pedido.get("id"), "pedido")
                                if pdf_pedido:
                                    st.download_button(
                                        "📄 PDF Pedido",
                                        data=pdf_pedido,
                                        file_name=(
                                            f"pedido_{processo_info.get('numero') or pedido.get('id')}.pdf"
                                        ),
                                        mime="application/pdf",
                                        key=f"pc_pdf_{pedido.get('id')}"
                                    )

                            if (pedido.get("total_respostas", 0) or 0) > 0 or estado_lower == "respondido":
                                pedidos_com_resposta.append(pedido)

                            meta_cols = st.columns(3)
                            with meta_cols[0]:
                                st.write(
                                    f"**Estado:** {pedido.get('estado').title() if pedido.get('estado') else '—'}"
                                )
                                st.write(
                                    f"**Data:** {_format_iso_date(pedido.get('data')) or '—'}"
                                )
                                st.write(
                                    f"**Envio Cliente:** {emoji_cliente} {texto_cliente}"
                                )
                            with meta_cols[1]:
                                st.write(
                                    f"**Respostas recebidas:** {pedido.get('total_respostas', 0)}"
                                )
                                st.write(
                                    f"**Solicitante:** {pedido.get('nome_solicitante') or '—'}"
                                )
                            with meta_cols[2]:
                                st.write(
                                    f"**Email:** {pedido.get('email_solicitante') or '—'}"
                                )
                                st.write(f"**Cliente:** {pedido.get('cliente') or '—'}")

                            if pedido.get("observacoes"):
                                st.markdown(f"_Observações:_ {pedido.get('observacoes')}")

                            artigos_fornecedor = pedido.get("artigos", [])
                            if artigos_fornecedor:
                                df_fornecedor = pd.DataFrame(
                                    [
                                        {
                                            "Nº Artigo": artigo.get("artigo_num") or "",
                                            "Descrição": artigo.get("descricao"),
                                            "Qtd": artigo.get("quantidade"),
                                            "Unidade": artigo.get("unidade"),
                                            "Marca": artigo.get("marca") or "",
                                        }
                                        for artigo in artigos_fornecedor
                                    ]
                                )
                                st.dataframe(
                                    df_fornecedor,
                                    use_container_width=True,
                                    hide_index=True,
                                )
                            else:
                                st.info("Nenhum artigo associado a este pedido.")
                    if pedidos_com_resposta:
                        st.markdown("---")
                        st.markdown("### Cotação Cliente")

                        respostas_por_artigo: OrderedDict[str, dict] = OrderedDict()
                        resposta_para_pedido: dict[int, dict] = {}
                        for pedido in pedidos_com_resposta:
                            respostas_pedido = obter_respostas_cotacao(pedido.get("id"))
                            artigos_pedido = pedido.get("artigos") or []
                            for resposta in respostas_pedido:
                                resposta_id = resposta.get("id")
                                if resposta_id is not None:
                                    resposta_para_pedido[resposta_id] = pedido
                                proc_art_id = resposta.get("processo_artigo_id") or resposta.get("artigo_id")
                                chave_artigo = str(proc_art_id or f"artigo_{resposta_id}")
                                artigo_relacionado = None
                                if proc_art_id:
                                    for artigo in artigos_pedido:
                                        if artigo.get("processo_artigo_id") == proc_art_id or artigo.get("id") == proc_art_id:
                                            artigo_relacionado = artigo
                                            break
                                if not artigo_relacionado:
                                    artigo_relacionado = {
                                        "artigo_num": resposta.get("artigo_id"),
                                        "descricao": resposta.get("descricao_original")
                                        or resposta.get("descricao"),
                                        "quantidade": resposta.get("quantidade_original")
                                        or resposta.get("quantidade_final"),
                                        "unidade": "",
                                    }
                                grupo = respostas_por_artigo.setdefault(
                                    chave_artigo,
                                    {
                                        "processo_artigo_id": proc_art_id,
                                        "artigo_num": artigo_relacionado.get("artigo_num"),
                                        "descricao": artigo_relacionado.get("descricao")
                                        or resposta.get("descricao_original")
                                        or resposta.get("descricao"),
                                        "quantidade": artigo_relacionado.get("quantidade"),
                                        "unidade": artigo_relacionado.get("unidade"),
                                        "opcoes": [],
                                    },
                                )
                                grupo["opcoes"].append({"pedido": pedido, "resposta": resposta})

                        if respostas_por_artigo:
                            respostas_destacadas: list[int] = []
                            primeiro_pedido: dict | None = None

                            for idx, (chave_artigo, dados_artigo) in enumerate(respostas_por_artigo.items(), start=1):
                                opcoes_artigo = dados_artigo.get("opcoes", [])
                                if not opcoes_artigo:
                                    continue

                                resposta_ids = [
                                    opcao.get("resposta", {}).get("id")
                                    for opcao in opcoes_artigo
                                    if opcao.get("resposta", {}).get("id") is not None
                                ]
                                if not resposta_ids:
                                    continue

                                descricao_artigo = limitar_descricao_artigo(
                                    dados_artigo.get("descricao") or "",
                                    max_linhas=2,
                                ) or "Artigo"
                                numero_artigo = dados_artigo.get("artigo_num") or ""
                                quantidade_artigo = dados_artigo.get("quantidade")
                                unidade_artigo = dados_artigo.get("unidade") or ""

                                detalhes = []
                                if numero_artigo:
                                    detalhes.append(f"Artigo {numero_artigo}")
                                if descricao_artigo:
                                    detalhes.append(descricao_artigo)
                                if quantidade_artigo not in (None, ""):
                                    unidade_txt = f" {unidade_artigo}" if unidade_artigo else ""
                                    detalhes.append(f"Qtd: {quantidade_artigo}{unidade_txt}")

                                titulo_artigo = " • ".join(detalhes) or f"Artigo #{idx}"

                                def _format_resposta(resposta_id: int, opcoes=opcoes_artigo) -> str:
                                    for opcao in opcoes:
                                        resposta_item = opcao.get("resposta", {})
                                        if resposta_item.get("id") != resposta_id:
                                            continue
                                        pedido_item = opcao.get("pedido") or {}
                                        fornecedor = (
                                            pedido_item.get("fornecedor")
                                            or resposta_item.get("fornecedor_nome")
                                            or "Fornecedor"
                                        )
                                        referencia = pedido_item.get("referencia") or "—"
                                        quantidade = (
                                            resposta_item.get("quantidade_final")
                                            or resposta_item.get("quantidade_original")
                                            or "—"
                                        )
                                        preco_venda = resposta_item.get("preco_venda") or 0
                                        moeda = resposta_item.get("moeda") or "EUR"
                                        resumo_preco = (
                                            f" • P.V.: {preco_venda:.2f} {moeda}" if preco_venda else ""
                                        )
                                        prazo = resposta_item.get("prazo_entrega")
                                        resumo_prazo = (
                                            f" • Prazo: {prazo}d"
                                            if prazo not in (None, "")
                                            else ""
                                        )
                                        return (
                                            f"{fornecedor} • Ref: {referencia}"
                                            f" • Qtd: {quantidade}{resumo_preco}{resumo_prazo}"
                                        )
                                    return "Resposta"

                                select_key = (
                                    f"pc_cliente_select_{processo_escolhido.get('id')}_{chave_artigo}"
                                )
                                selecao_resposta = st.selectbox(
                                    f"Resposta para {titulo_artigo}",
                                    options=resposta_ids,
                                    format_func=_format_resposta,
                                    key=select_key,
                                )

                                if selecao_resposta is not None:
                                    respostas_destacadas.append(selecao_resposta)
                                    if primeiro_pedido is None:
                                        primeiro_pedido = resposta_para_pedido.get(
                                            selecao_resposta,
                                        )

                            respostas_destacadas = list(dict.fromkeys(respostas_destacadas))

                            col_criar, _ = st.columns([1, 5])
                            with col_criar:
                                if st.button(
                                    "💰 Criar Cotação Cliente",
                                    key=f"pc_cliente_{processo_escolhido.get('id')}",
                                ):
                                    pedido_sel = primeiro_pedido or (pedidos_com_resposta[0] if pedidos_com_resposta else {})
                                    criar_cotacao_cliente_dialog(
                                        pedido_sel.get("id"),
                                        processo_info.get("numero"),
                                        pedido_sel.get("referencia"),
                                        pedido_sel.get("nome_solicitante")
                                        or pedido_sel.get("cliente"),
                                        pedido_sel.get("email_solicitante"),
                                        respostas_destacadas=respostas_destacadas,
                                        processo_id=processo_escolhido.get("id"),
                                    )
                        else:
                            st.info(
                                "Ainda não existem respostas detalhadas para gerar a cotação do cliente."
                            )
                    else:
                        st.info(
                            "Ainda não existem respostas de fornecedores para gerar a cotação do cliente."
                        )
                else:
                    st.info("Nenhum pedido enviado aos fornecedores para este processo.")
            else:
                st.warning("Não foi possível carregar os detalhes do processo selecionado.")
        else:
            st.info("Introduza um termo de pesquisa para listar processos.")

    # Diálogo de confirmação para eliminar/arquivar
    if "confirmacao" in st.session_state:
        acao, rfq_conf = st.session_state.confirmacao

        @st.dialog("Confirmação")
        def confirmar_acao():
            st.write(
                "Tem a certeza que deseja arquivar este processo?"
                if acao == "arquivar"
                else "Tem a certeza que deseja eliminar este processo?"
            )
            col_ok, col_cancel = st.columns(2)
            if col_ok.button("Sim"):
                if acao == "arquivar":
                    if arquivar_cotacao(rfq_conf):
                        st.success("Cotação arquivada!")
                else:
                    if eliminar_cotacao(rfq_conf):
                        st.success("Cotação eliminada!")
                st.session_state.pop("confirmacao", None)
                st.rerun()
            if col_cancel.button("Não"):
                st.session_state.pop("confirmacao", None)
                st.rerun()

        confirmar_acao()

elif menu_option == "📊 Relatórios":
    st.title("📊 Relatórios e Análises")
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "Estatísticas Gerais",
        "Por Fornecedor",
        "Por Utilizador",
        "Evolução Cumulativa",
    ])
    
    with tab1:
        st.subheader("Estatísticas Gerais")
        
        stats = obter_estatisticas_db()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("Total de Cotações", stats.get('rfq', 0))
            st.metric("Artigos Cotados", stats.get('artigo', 0))
        
        with col2:
            st.metric("Taxa de Resposta", 
                     f"{(stats.get('rfq_respondidas', 0) / max(stats.get('rfq', 1), 1) * 100):.1f}%")
            st.metric("Fornecedores Ativos", stats.get('fornecedor', 0))
        
        with col3:
            st.metric("Orçamentos Enviados", stats.get('pdfs_cliente', 0))
            st.metric("PDFs Gerados", stats.get('pdfs_cliente', 0) * 2)
        
        # Gráfico de estado das cotações
        if stats.get('rfq', 0) > 0:
            st.markdown("---")
            st.subheader("Estado das Cotações")
            
            pendentes = stats.get('rfq_pendentes', 0)
            respondidas = stats.get('rfq_respondidas', 0)
            
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"🟡 Pendentes: {pendentes}")
            with col2:
                st.success(f"🟢 Respondidas: {respondidas}")
    with tab2:
        st.subheader("Análise por Fornecedor")
        
        fornecedores = listar_fornecedores()
        
        if fornecedores:
            fornecedor_sel = st.selectbox(
                "Selecionar Fornecedor",
                options=fornecedores,
                format_func=lambda x: x[1]
            )
            
            if fornecedor_sel:
                # Estatísticas do fornecedor
                conn = obter_conexao()
                c = conn.cursor()
                
                c.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN COALESCE(e.nome, 'pendente') = 'respondido' THEN 1 ELSE 0 END) as respondidas,
                           SUM(CASE WHEN COALESCE(e.nome, 'pendente') = 'pendente' THEN 1 ELSE 0 END) as pendentes
                    FROM rfq r
                    LEFT JOIN estado e ON r.estado_id = e.id
                    WHERE r.fornecedor_id = ?
                    """,
                    (fornecedor_sel[0],),
                )
                
                stats_forn = c.fetchone()
                
                if stats_forn:
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.metric("Total Cotações", stats_forn[0])
                    with col2:
                        st.metric("Respondidas", stats_forn[1])
                    with col3:
                        st.metric("Pendentes", stats_forn[2])
                    
                    # Marcas e margens
                    st.markdown("---")
                    st.subheader("Marcas e Margens Configuradas")
                    
                    marcas = obter_marcas_fornecedor(fornecedor_sel[0])
                    if marcas:
                        for marca_info in marcas:
                            nome_marca = marca_info.get("nome", "")
                            if not nome_marca:
                                continue
                            margem = obter_margem_para_marca(fornecedor_sel[0], nome_marca)
                            st.write(f"**{nome_marca}**: {margem:.1f}%")
                    else:
                        st.info("Nenhuma marca configurada")

                    if len(fornecedor_sel) > 6 and fornecedor_sel[6]:
                        st.caption(
                            "Este fornecedor exige País e Cliente Final nas cotações."
                        )
                
                conn.close()
        else:
            st.info("Nenhum fornecedor registado")

    with tab3:
        st.subheader("Análise por Utilizador")

        utilizadores = listar_utilizadores()

        if utilizadores:
            current_user_id = st.session_state.get("user_id")
            default_index = 0
            if current_user_id is not None:
                for idx, user in enumerate(utilizadores):
                    if user[0] == current_user_id:
                        default_index = idx
                        break

            user_sel = st.selectbox(
                "Selecionar Utilizador",
                options=utilizadores,
                format_func=lambda x: x[1],
                index=default_index,
            )

            if user_sel:
                conn = obter_conexao()
                c = conn.cursor()

                c.execute(
                    """
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN COALESCE(e.nome, 'pendente') = 'respondido' THEN 1 ELSE 0 END) as respondidas,
                           SUM(CASE WHEN COALESCE(e.nome, 'pendente') = 'pendente' THEN 1 ELSE 0 END) as pendentes
                      FROM rfq r
                      JOIN processo p ON r.processo_id = p.id
                      LEFT JOIN estado e ON r.estado_id = e.id
                     WHERE p.utilizador_id = ?
                    """,
                    (user_sel[0],),
                )

                stats_user = c.fetchone()

                if stats_user:
                    col1, col2, col3 = st.columns(3)

                    with col1:
                        st.metric("Total Cotações", stats_user[0])
                    with col2:
                        st.metric("Respondidas", stats_user[1])
                    with col3:
                        st.metric("Pendentes", stats_user[2])

                    st.markdown("---")
                    st.subheader("Processos do Utilizador")

                    cotacoes_user = obter_todas_cotacoes(utilizador_id=user_sel[0])
                    if cotacoes_user:
                        df = [
                            {
                                "Processo": c["processo"],
                                "Fornecedor": c["fornecedor"],
                                "Data": c["data"],
                                "Estado": c["estado"],
                                "Referência": c["referencia"],
                            }
                            for c in cotacoes_user
                        ]
                        st.dataframe(df)
                    else:
                        st.info("Nenhuma cotação associada")

                conn.close()
        else:
            st.info("Nenhum utilizador registado")

    with tab4:
        st.subheader("Evolução Cumulativa")

        conn = obter_conexao()
        c = conn.cursor()

        c.execute(
            "SELECT data_atualizacao, COUNT(*) FROM rfq GROUP BY data_atualizacao ORDER BY data_atualizacao"
        )
        rows = c.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["data_atualizacao", "total"])
            df["data_atualizacao"] = pd.to_datetime(
                df["data_atualizacao"].astype(str).str.replace("T", " ", regex=False),
                errors="coerce",
            )
            df = (
                df.dropna(subset=["data_atualizacao"])
                .set_index("data_atualizacao")
                .sort_index()
            )
            df["cumulativo"] = df["total"].cumsum()
            st.markdown("**Cotações por Dia (Cumulativo)**")
            st.line_chart(df["cumulativo"], height=300)
        else:
            st.info("Sem dados diários")

        c.execute(
            """
            SELECT r.data_atualizacao,
                   SUM(rf.preco_venda * rf.quantidade_final) as total
            FROM rfq r
            JOIN resposta_fornecedor rf ON r.id = rf.rfq_id
            GROUP BY r.data_atualizacao
            ORDER BY r.data_atualizacao
            """
        )
        rows = c.fetchall()
        if rows:
            df_val = pd.DataFrame(rows, columns=["data_atualizacao", "total"])
            df_val["data_atualizacao"] = pd.to_datetime(
                df_val["data_atualizacao"].astype(str).str.replace("T", " ", regex=False),
                errors="coerce",
            )
            df_val = (
                df_val.dropna(subset=["data_atualizacao"])
                .set_index("data_atualizacao")
                .sort_index()
            )
            df_val["cumulativo"] = df_val["total"].cumsum()
            st.markdown("**Preço de Venda por Dia (Cumulativo)**")
            st.line_chart(df_val["cumulativo"], height=300)
        else:
            st.info("Sem dados de preço de venda diário")

        c.execute(
            "SELECT strftime('%Y-%m', data_atualizacao) as mes, COUNT(*) FROM rfq GROUP BY mes ORDER BY mes"
        )
        rows = c.fetchall()
        if rows:
            df_mes = pd.DataFrame(rows, columns=["mes", "total"])
            df_mes["cumulativo"] = df_mes["total"].cumsum()
            st.markdown("**Cotações por Mês (Cumulativo)**")
            st.line_chart(df_mes.set_index("mes")["cumulativo"], height=300)
        else:
            st.info("Sem dados mensais")

        c.execute(
            """
            SELECT strftime('%Y-%m', r.data_atualizacao) as mes,
                   SUM(rf.preco_venda * rf.quantidade_final) as total
            FROM rfq r
            JOIN resposta_fornecedor rf ON r.id = rf.rfq_id
            GROUP BY mes
            ORDER BY mes
            """
        )
        rows = c.fetchall()
        conn.close()
        if rows:
            df_val_mes = pd.DataFrame(rows, columns=["mes", "total"])
            df_val_mes["cumulativo"] = df_val_mes["total"].cumsum()
            st.markdown("**Preço de Venda por Mês (Cumulativo)**")
            st.line_chart(df_val_mes.set_index("mes")["cumulativo"], height=300)
        else:
            st.info("Sem dados de preço de venda mensal")

elif menu_option == "📄 PDFs":
    st.title("📄 Gestão de PDFs")

    cotacoes = obter_todas_cotacoes()
    if cotacoes:
        cot_sel = st.selectbox(
            "Selecionar Cotação",
            options=cotacoes,
            format_func=lambda c: f"{c['processo']} - {c['referencia']}"
        )

        pdf_types = [
            ("Pedido Cliente", "anexo_cliente", "📥"),
            ("Pedido Cotação", "pedido", "📤"),
            ("Resposta Fornecedor", "anexo_fornecedor", "📥"),
            ("Resposta Cliente", "cliente", "📤"),
        ]

        tab_view, tab_replace = st.tabs(["Visualizar PDFs", "Substituir PDFs"])

        with tab_view:
            for label, tipo, emoji in pdf_types:
                if tipo == "pedido":
                    pdf_entries = obter_pdf_da_db(
                        cot_sel["id"],
                        tipo,
                        return_all=True,
                    )
                    if pdf_entries:
                        multiplo = len(pdf_entries) > 1
                        for idx, entry in enumerate(pdf_entries, start=1):
                            pdf_bytes = entry.get("pdf_data")
                            if not pdf_bytes:
                                continue

                            nome_ficheiro = entry.get("nome_ficheiro")
                            if nome_ficheiro:
                                pdf_label = f"{emoji} {label} – {nome_ficheiro}"
                            elif multiplo:
                                pdf_label = f"{emoji} {label} #{idx}"
                            else:
                                pdf_label = f"{emoji} {label}"

                            exibir_pdf(pdf_label, pdf_bytes)
                    else:
                        st.info(f"{label} não encontrado")
                else:
                    pdf_bytes = obter_pdf_da_db(cot_sel["id"], tipo)
                    if pdf_bytes:
                        exibir_pdf(f"{emoji} {label}", pdf_bytes)
                    else:
                        st.info(f"{label} não encontrado")

        with tab_replace:
            if st.session_state.get("role") == "admin":
                label_selec = st.selectbox(
                    "Tipo de PDF a substituir",
                    [lbl for lbl, _, _ in pdf_types],
                    key="tipo_pdf_gest",
                )
                tipo_pdf = next(t for lbl, t, _ in pdf_types if lbl == label_selec)
                novo_pdf = st.file_uploader(
                    "Substituir PDF",
                    type=["pdf", "eml", "msg"],
                    key="upload_pdf_gest",
                )
                if novo_pdf and st.button("💾 Guardar PDF"):
                    anexos_novos = processar_upload_pdf(novo_pdf)
                    if anexos_novos:
                        nome_pdf, bytes_pdf = anexos_novos[0]
                        if guardar_pdf_upload(cot_sel["id"], tipo_pdf, nome_pdf, bytes_pdf):
                            st.success("PDF atualizado com sucesso!")
            else:
                st.info("Apenas administradores podem atualizar o PDF.")
    else:
        st.info("Nenhuma cotação disponível")

elif menu_option == "📦 Artigos":
    st.title("📦 Catálogo de Artigos")
    tab_search, tab_create = st.tabs(["🔍 Procurar", "➕ Criar"])

    with tab_search:
        termo = st.text_input("Pesquisar por nº ou descrição")
        resultados = procurar_artigos_catalogo(termo)
        if resultados:
            df = pd.DataFrame(
                resultados,
                columns=[
                    "Nº Artigo",
                    "Descrição",
                    "Fabricante",
                    "Preço Venda",
                    "Validade Preço",
                ],
            )
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Nenhum artigo encontrado")

    with tab_create:
        with st.form("novo_artigo_catalogo"):
            numero = st.text_input("Nº Artigo *")
            descricao = st.text_area("Descrição *")
            fabricante = st.text_input("Fabricante")
            preco = st.number_input(
                "Preço de venda", min_value=0.0, step=0.01, format="%.2f"
            )
            submit = st.form_submit_button("Guardar Artigo")
        if submit:
            if numero.strip() and descricao.strip():
                inserir_artigo_catalogo(
                    numero.strip(), descricao.strip(), fabricante.strip(), preco
                )
                st.success("Artigo guardado com sucesso")
            else:
                st.error("Preencha os campos obrigatórios")

elif menu_option == "👤 Perfil":
    st.title("👤 Meu Perfil")
    user = obter_utilizador_por_id(st.session_state.get("user_id"))
    if user:
        tab_pw, tab_email = st.tabs([
            "Alterar Palavra-passe do Sistema",
            "Configuração de Email",
        ])

        with tab_pw:
            with st.form("palavra_passe_form"):
                nova_pw = st.text_input("Nova Palavra-passe", type="password")
                confirmar_pw = st.text_input("Confirmar Palavra-passe", type="password")
                sub_pw = st.form_submit_button("Alterar Palavra-passe")
            if sub_pw:
                if not nova_pw or nova_pw != confirmar_pw:
                    st.error("Palavras-passe não coincidem")
                else:
                    if atualizar_utilizador(
                        user[0],
                        user[1],
                        user[3],
                        user[4],
                        user[5],
                        nova_pw,
                    ):
                        st.success("Palavra-passe atualizada com sucesso!")
                    else:
                        st.error("Erro ao atualizar palavra-passe")

        with tab_email:
            with st.form("email_form"):
                email_edit = st.text_input("Username", value=user[4] or "")
                email_pw_edit = st.text_input(
                    "Palavra-passe do Email", value=user[6] or "", type="password"
                )
                sub_email = st.form_submit_button("Guardar Email")
            if sub_email:
                if atualizar_utilizador(
                    user[0],
                    user[1],
                    user[3],
                    email_edit,
                    user[5],
                    None,
                    email_pw_edit,
                ):
                    st.success("Dados de email atualizados com sucesso!")
                else:
                    st.error("Erro ao atualizar dados de email")
    else:
        st.error("Utilizador não encontrado")

elif menu_option == "⚙️ Configurações":
    if st.session_state.get("role") not in ["admin", "gestor"]:
        st.error("Sem permissão para aceder a esta área")
    else:
        st.title("⚙️ Configurações do Sistema")
        (
            tab_gestao_fornecedores,
            tab_clientes,
            tab_users,
            tab_unidades,
            tab_email,
            tab_backup,
            tab_layout,
            tab_empresa,
        ) = st.tabs([
            "Gestão de Fornecedores",
            "Clientes",
            "Utilizadores",
            "Unidades",
            "Email",
            "Backup",
            "Layout PDF",
            "Dados da Empresa",
        ])


        with tab_gestao_fornecedores:
            sub_tab_fornecedores, sub_tab_marcas = st.tabs([
                "Fornecedores",
                "Marcas e Margens",
            ])

            with sub_tab_fornecedores:
                st.subheader("Gestão de Fornecedores")

                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("### Adicionar Fornecedor")
                    with st.form("novo_fornecedor_form"):
                        nome = st.text_input("Nome *")
                        email = st.text_input("Email")
                        telefone = st.text_input("Telefone")
                        morada = st.text_area("Morada")
                        nif = st.text_input("NIF")
                        requer_info = st.checkbox(
                            "Requer País e Cliente Final?",
                            help="Assinale quando este fornecedor exige estas informações em cada pedido.",
                        )

                        if st.form_submit_button("➕ Adicionar"):
                            nome_limpo = (nome or "").strip()
                            if nome_limpo:
                                fornecedores_existentes = listar_fornecedores()
                                nome_normalizado = nome_limpo.casefold()
                                existe_fornecedor = any(
                                    (fornecedor[1] or "").strip().casefold()
                                    == nome_normalizado
                                    for fornecedor in fornecedores_existentes
                                )

                                if existe_fornecedor:
                                    st.warning("Este fornecedor já está registado.")
                                else:
                                    forn_id = inserir_fornecedor(
                                        nome_limpo,
                                        email,
                                        telefone,
                                        morada,
                                        nif,
                                        requer_info,
                                    )
                                    if forn_id:
                                        st.success(f"Fornecedor {nome_limpo} adicionado!")
                                        st.rerun()
                                    else:
                                        st.error("Não foi possível adicionar o fornecedor.")
                            else:
                                st.error("Nome é obrigatório")

                with col2:
                    st.markdown("### Fornecedores Registados")
                    fornecedores = listar_fornecedores()

                    for forn in fornecedores:
                        with st.expander(forn[1]):
                            with st.form(f"edit_forn_{forn[0]}"):
                                nome_edit = st.text_input("Nome", forn[1])
                                email_edit = st.text_input("Email", forn[2] or "")
                                telefone_edit = st.text_input("Telefone", forn[3] or "")
                                morada_edit = st.text_area("Morada", forn[4] or "")
                                nif_edit = st.text_input("NIF", forn[5] or "")
                                requer_info_edit = st.checkbox(
                                    "Requer País e Cliente Final?",
                                    value=bool(forn[6]) if len(forn) > 6 else False,
                                    key=f"forn_req_{forn[0]}",
                                    help="Quando ativo, o sistema solicitará estes dados antes de enviar o pedido.",
                                )

                                col_a, col_b = st.columns(2)
                                with col_a:
                                    if st.form_submit_button("💾 Guardar"):
                                        if atualizar_fornecedor(
                                            forn[0],
                                            nome_edit,
                                            email_edit,
                                            telefone_edit,
                                            morada_edit,
                                            nif_edit,
                                            requer_info_edit,
                                        ):
                                            st.success("Fornecedor atualizado")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao atualizar fornecedor")
                                with col_b:
                                    if st.form_submit_button("🗑️ Eliminar"):
                                        if eliminar_fornecedor_db(forn[0]):
                                            st.success("Fornecedor eliminado")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao eliminar fornecedor")

                            marcas = obter_marcas_fornecedor(forn[0])
                            if marcas:
                                nomes_marcas = [
                                    (info.get("nome", "") or "").strip()
                                    for info in marcas
                                    if (info.get("nome") or "").strip()
                                ]
                                st.write(
                                    f"**Marcas:** {', '.join(nomes_marcas) if nomes_marcas else 'Nenhuma'}"
                                )
                            else:
                                st.write("**Marcas:** Nenhuma")

            with sub_tab_marcas:
                st.subheader("Configuração de Marcas e Margens")

                fornecedores = listar_fornecedores()

                if fornecedores:
                    fornecedor_sel = st.selectbox(
                        "Selecionar Fornecedor",
                        options=fornecedores,
                        format_func=lambda x: x[1],
                        key="forn_marcas"
                    )

                    if fornecedor_sel:
                        col1, col2 = st.columns(2)

                        with col1:
                            st.markdown("### Adicionar Marca")
                            if len(fornecedor_sel) > 6 and fornecedor_sel[6]:
                                st.info(
                                    "Este fornecedor exige País e Cliente Final nas cotações."
                                )
                            with st.form("add_marca_form"):
                                nova_marca = st.text_input("Nome da Marca")
                                margem_marca = st.number_input(
                                    "Margem (%)",
                                    min_value=0.0,
                                    max_value=100.0,
                                    value=15.0,
                                    step=0.5
                                )

                                if st.form_submit_button("➕ Adicionar Marca"):
                                    if nova_marca:
                                        if adicionar_marca_fornecedor(
                                            fornecedor_sel[0], nova_marca
                                        ):
                                            configurar_margem_marca(fornecedor_sel[0], nova_marca, margem_marca)
                                            st.success(f"Marca {nova_marca} adicionada!")
                                            st.rerun()
                                        else:
                                            st.error("Marca já está associada a um fornecedor")

                        with col2:
                            st.markdown("### Marcas Existentes")
                            marcas = obter_marcas_fornecedor(fornecedor_sel[0])

                            if marcas:
                                for info in marcas:
                                    nome_marca = info.get("nome", "").strip()
                                    if not nome_marca:
                                        continue
                                    margem = obter_margem_para_marca(
                                        fornecedor_sel[0], nome_marca
                                    )
                                    titulo_expander = f"{nome_marca} - {margem:.1f}%"

                                    with st.expander(titulo_expander):
                                        nova_margem = st.number_input(
                                            "Nova Margem (%)",
                                            min_value=0.0,
                                            max_value=100.0,
                                            value=margem,
                                            step=0.5,
                                            key=f"margem_{fornecedor_sel[0]}_{nome_marca}"
                                        )

                                        col1, col2 = st.columns(2)

                                        with col1:
                                            st.markdown(
                                                "<div style='display:flex; justify-content:center;'>",
                                                unsafe_allow_html=True,
                                            )
                                            if st.button(
                                                "💾 Atualizar",
                                                key=f"upd_{fornecedor_sel[0]}_{nome_marca}",
                                            ):
                                                margem_alterada = abs(nova_margem - margem) > 1e-6
                                                if not margem_alterada:
                                                    st.info("Nenhuma alteração para guardar.")
                                                else:
                                                    if configurar_margem_marca(
                                                        fornecedor_sel[0],
                                                        nome_marca,
                                                        nova_margem,
                                                    ):
                                                        st.success("Margem atualizada!")
                                                        st.rerun()
                                                    else:
                                                        st.error("Não foi possível atualizar a margem.")
                                            st.markdown("</div>", unsafe_allow_html=True)

                                        with col2:
                                            st.markdown(
                                                "<div style='display:flex; justify-content:center;'>",
                                                unsafe_allow_html=True,
                                            )
                                            if st.button(
                                                "🗑️ Remover",
                                                key=f"del_{fornecedor_sel[0]}_{nome_marca}"
                                            ):
                                                if remover_marca_fornecedor(
                                                    fornecedor_sel[0], nome_marca
                                                ):
                                                    st.success("Marca removida!")
                                                    st.rerun()
                                            st.markdown("</div>", unsafe_allow_html=True)
                            else:
                                st.info("Nenhuma marca configurada")

        with tab_clientes:
            st.subheader("Gestão de Clientes")

            tab_empresas, tab_comerciais = st.tabs([
                "Adicionar Empresa",
                "Adicionar Comercial",
            ])

            with tab_empresas:
                st.markdown("### Gestão de Empresas")
                emp_col1, emp_col2 = st.columns(2)

                with emp_col1:
                    with st.form("nova_empresa_form"):
                        nome_emp = st.text_input("Nome Empresa *")
                        morada_emp = st.text_input("Morada")
                        cond_pag_emp = st.text_input("Condições Pagamento")
                        if st.form_submit_button("➕ Adicionar Empresa"):
                            if nome_emp:
                                inserir_empresa(nome_emp, morada_emp, cond_pag_emp)
                                st.success(f"Empresa {nome_emp} adicionada!")
                            else:
                                st.error("Nome é obrigatório")

                with emp_col2:
                    st.markdown("### Empresas Registadas")
                    empresas = listar_empresas()
                    for emp in empresas:
                        with st.expander(emp[1]):
                            with st.form(f"edit_emp_{emp[0]}"):
                                nome_edit = st.text_input("Nome", emp[1])
                                morada_edit = st.text_input("Morada", emp[2] or "")
                                cond_pag_edit = st.text_input(
                                    "Condições Pagamento", emp[3] or "",
                                )
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    if st.form_submit_button("💾 Guardar"):
                                        atualizar_empresa(
                                            emp[0], nome_edit, morada_edit, cond_pag_edit
                                        )
                                        st.success("Empresa atualizada")
                                        st.rerun()
                                with col_b:
                                    if st.form_submit_button("🗑️ Eliminar"):
                                        eliminar_empresa_db(emp[0])
                                        st.success("Empresa eliminada")
                                        st.rerun()

            with tab_comerciais:
                empresas = listar_empresas()
                if not empresas:
                    st.info("Nenhuma empresa registada. Adicione uma empresa primeiro.")
                else:
                    empresa_sel = st.selectbox(
                        "Selecionar Empresa",
                        empresas,
                        format_func=lambda x: x[1],
                        key="empresa_comercial_sel",
                    )

                    col1, col2 = st.columns(2)

                    with col1:
                        st.markdown("### Adicionar Comercial")
                        with st.form("novo_cliente_form"):
                            nome = st.text_input("Nome *")
                            email = st.text_input("Email")
                            if st.form_submit_button("➕ Adicionar"):
                                if nome:
                                    inserir_cliente(nome, email, empresa_sel[0])
                                    st.success(f"Comercial {nome} adicionado!")
                                    st.rerun()
                                else:
                                    st.error("Nome é obrigatório")

                    with col2:
                        st.markdown("### Comerciais Registados")
                        clientes = [cli for cli in listar_clientes() if cli[3] == empresa_sel[0]]

                        for cli in clientes:
                            with st.expander(cli[1]):
                                with st.form(f"edit_cli_{cli[0]}"):
                                    nome_edit = st.text_input("Nome", cli[1])
                                    email_edit = st.text_input("Email", cli[2] or "")
                                    idx_emp = 0
                                    for idx, emp in enumerate(empresas):
                                        if emp[0] == cli[3]:
                                            idx_emp = idx
                                            break
                                    empresa_sel_edit = st.selectbox(
                                        "Empresa *",
                                        empresas,
                                        index=idx_emp,
                                        format_func=lambda x: x[1],
                                        key=f"emp_{cli[0]}",
                                    )

                                    col_a, col_b = st.columns(2)
                                    with col_a:
                                        if st.form_submit_button("💾 Guardar"):
                                            atualizar_cliente(
                                                cli[0],
                                                nome_edit,
                                                email_edit,
                                                empresa_sel_edit[0],
                                            )
                                            st.success("Comercial atualizado")
                                            st.rerun()
                                    with col_b:
                                        if st.form_submit_button("🗑️ Eliminar"):
                                            eliminar_cliente_db(cli[0])
                                            st.success("Comercial eliminado")
                                            st.rerun()
        with tab_users:
            if st.session_state.get("role") != "admin":
                st.warning("Apenas administradores podem gerir utilizadores.")
            else:
                st.subheader("Gestão de Utilizadores")
    
                col1, col2 = st.columns(2)
    
                with col1:
                    st.markdown("### Adicionar Utilizador")
                    with st.form("novo_user_form"):
                        username = st.text_input("Username *")
                        nome = st.text_input("Nome")
                        email_user = st.text_input("Email")
                        role = st.selectbox("Role", ["admin", "gestor", "user"])
                        password = st.text_input("Palavra-passe *", type="password")

                        if st.form_submit_button("➕ Adicionar"):
                            if username and password:
                                if inserir_utilizador(
                                    username, password, nome, email_user, role
                                ):
                                    st.success(f"Utilizador {username} adicionado!")
                                    st.rerun()
                                else:
                                    st.error("Erro ao adicionar utilizador")
                            else:
                                st.error("Username e palavra-passe são obrigatórios")
    
                with col2:
                    st.markdown("### Utilizadores Registados")
                    utilizadores = listar_utilizadores()
    
                    for user in utilizadores:
                        with st.expander(user[1]):
                            with st.form(f"edit_user_{user[0]}"):
                                username_edit = st.text_input("Username", user[1])
                                nome_edit = st.text_input("Nome", user[2] or "")
                                email_edit = st.text_input("Email", user[3] or "")
                                email_pw_edit = st.text_input("Password Email", user[5] or "", type="password")
                                role_edit = st.selectbox(
                                    "Role",
                                    ["admin", "gestor", "user"],
                                    index=["admin", "gestor", "user"].index(user[4]),
                                )
                                password_edit = st.text_input("Palavra-passe", type="password")
    
                                col_a, col_b = st.columns(2)
                                with col_a:
                                    if st.form_submit_button("💾 Guardar"):
                                        if atualizar_utilizador(
                                            user[0],
                                            username_edit,
                                            nome_edit,
                                            email_edit,
                                            role_edit,
                                            password_edit or None,
                                            email_pw_edit or None,
                                        ):
                                            st.success("Utilizador atualizado")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao atualizar utilizador")
                                with col_b:
                                    if st.form_submit_button("🗑️ Eliminar"):
                                        if eliminar_utilizador(user[0]):
                                            st.success("Utilizador eliminado")
                                            st.rerun()
                                        else:
                                            st.error("Erro ao eliminar utilizador")

        with tab_unidades:
            st.subheader("Gestão de Unidades")

            col_add, col_list = st.columns(2)

            with col_add:
                st.markdown("### Adicionar Unidade")
                with st.form("nova_unidade_form"):
                    nome_unidade = st.text_input("Nome da Unidade *")
                    adicionar_unidade = st.form_submit_button("➕ Adicionar")

                if adicionar_unidade:
                    nome_unidade_limpo = (nome_unidade or "").strip()
                    if not nome_unidade_limpo:
                        st.error("Nome da unidade é obrigatório.")
                    else:
                        unidades_existentes = listar_unidades()
                        nome_unidade_normalizado = nome_unidade_limpo.casefold()
                        existe_unidade = any(
                            (unidade_nome or "").strip().casefold()
                            == nome_unidade_normalizado
                            for _, unidade_nome in unidades_existentes
                        )

                        if existe_unidade:
                            st.warning("Esta unidade já está registada.")
                        else:
                            unidade_id = inserir_unidade(nome_unidade_limpo)
                            if unidade_id:
                                st.success("Unidade adicionada com sucesso!")
                                st.rerun()
                            else:
                                st.error("Não foi possível adicionar a unidade.")

            with col_list:
                st.markdown("### Unidades Registadas")
                unidades_existentes = listar_unidades()

                if unidades_existentes:
                    for unidade_id, unidade_nome in unidades_existentes:
                        titulo_expander = f"{unidade_nome} (ID {unidade_id})"
                        with st.expander(titulo_expander):
                            with st.form(f"editar_unidade_{unidade_id}"):
                                nome_editado = st.text_input("Nome", unidade_nome)
                                col_salvar, col_eliminar = st.columns(2)

                                with col_salvar:
                                    if st.form_submit_button("💾 Guardar"):
                                        if atualizar_unidade(unidade_id, nome_editado):
                                            st.success("Unidade atualizada")
                                            st.rerun()
                                        else:
                                            st.error("Não foi possível atualizar a unidade.")

                                with col_eliminar:
                                    if st.form_submit_button("🗑️ Eliminar"):
                                        if eliminar_unidade(unidade_id):
                                            st.success("Unidade eliminada")
                                            st.rerun()
                                        else:
                                            st.error(
                                                "Não é possível eliminar a unidade enquanto estiver em uso."
                                            )
                else:
                    st.info("Nenhuma unidade registada.")

        with tab_email:
            st.subheader("Configuração de Email")
            
            # Obter configuração atual
            conn = obter_conexao()
            c = conn.cursor()
            try:
                c.execute(
                    "SELECT smtp_server, smtp_port, use_tls, use_ssl FROM configuracao_email WHERE ativo = TRUE ORDER BY id DESC LIMIT 1"
                )
            except sqlite3.OperationalError:
                try:
                    c.execute(
                        "SELECT smtp_server, smtp_port, use_tls, use_ssl FROM configuracao_email ORDER BY id DESC LIMIT 1"
                    )
                except sqlite3.OperationalError:
                    c.execute(
                        "SELECT smtp_server, smtp_port FROM configuracao_email ORDER BY id DESC LIMIT 1"
                    )
            row = c.fetchone()
            conn.close()

            config_atual = {
                "smtp_server": row[0] if row else "",
                "smtp_port": row[1] if row and len(row) > 1 else None,
                "use_tls": row[2] if row and len(row) > 2 else None,
                "use_ssl": row[3] if row and len(row) > 3 else None,
            }

            provider_defaults = {
                "Outlook": {"server": "smtp.office365.com", "port": 587, "use_tls": True, "use_ssl": False},
                "Gmail": {"server": "smtp.gmail.com", "port": 587, "use_tls": True, "use_ssl": False},
                "Personalizado": {},
            }

            server_lower = (config_atual.get("smtp_server") or "").lower()
            provider_guess = "Personalizado"
            if "gmail" in server_lower:
                provider_guess = "Gmail"
            elif any(key in server_lower for key in ("outlook", "office365", "office")):
                provider_guess = "Outlook"

            provider_key = "config_email_provider"
            server_key = "config_email_smtp_server"
            port_key = "config_email_smtp_port"
            tls_key = "config_email_use_tls"
            ssl_key = "config_email_use_ssl"

            if provider_key not in st.session_state:
                st.session_state[provider_key] = provider_guess

            if server_key not in st.session_state:
                st.session_state[server_key] = config_atual.get("smtp_server") or provider_defaults[provider_guess].get("server", "")

            if port_key not in st.session_state:
                st.session_state[port_key] = config_atual.get("smtp_port") or provider_defaults[provider_guess].get("port", 587)

            if tls_key not in st.session_state:
                valor_tls = config_atual.get("use_tls")
                if valor_tls is None:
                    valor_tls = provider_defaults[provider_guess].get("use_tls", True)
                st.session_state[tls_key] = bool(valor_tls)

            if ssl_key not in st.session_state:
                valor_ssl = config_atual.get("use_ssl")
                if valor_ssl is None:
                    valor_ssl = provider_defaults[provider_guess].get("use_ssl", False)
                st.session_state[ssl_key] = bool(valor_ssl)

            provider_prev_key = f"{provider_key}_prev"

            def _aplicar_por_provider(selecao: str) -> None:
                defaults = provider_defaults.get(selecao, {})
                if defaults.get("server"):
                    st.session_state[server_key] = defaults["server"]
                if defaults.get("port"):
                    st.session_state[port_key] = defaults["port"]
                if "use_tls" in defaults:
                    st.session_state[tls_key] = defaults["use_tls"]
                if "use_ssl" in defaults:
                    st.session_state[ssl_key] = defaults["use_ssl"]

            selecao_atual = st.session_state.get(provider_key, provider_guess)
            ultima_selecao = st.session_state.get(provider_prev_key)
            if ultima_selecao is None:
                st.session_state[provider_prev_key] = selecao_atual
            elif selecao_atual != ultima_selecao:
                _aplicar_por_provider(selecao_atual)
                st.session_state[provider_prev_key] = selecao_atual

            with st.form("config_email_form"):
                provider = st.selectbox(
                    "Fornecedor SMTP",
                    list(provider_defaults.keys()),
                    key=provider_key,
                    help="Selecione um fornecedor comum ou mantenha 'Personalizado' para definir valores próprios.",
                )

                smtp_server = st.text_input(
                    "Servidor SMTP",
                    key=server_key,
                )
                smtp_port = st.number_input(
                    "Porta SMTP",
                    min_value=1,
                    step=1,
                    key=port_key,
                )

                col_tls, col_ssl = st.columns(2)
                with col_tls:
                    use_tls_val = st.checkbox(
                        "Usar STARTTLS",
                        value=st.session_state[tls_key],
                        key=tls_key,
                    )
                with col_ssl:
                    use_ssl_val = st.checkbox(
                        "Usar SSL (porta 465)",
                        value=st.session_state[ssl_key],
                        key=ssl_key,
                    )

                if use_ssl_val and use_tls_val:
                    st.warning("SSL e STARTTLS não devem estar ativos em simultâneo. Será utilizada a opção SSL.")

                if st.form_submit_button("💾 Guardar Configuração"):
                    conn = obter_conexao()
                    c = conn.cursor()

                    smtp_server_val = (st.session_state.get(server_key) or "").strip()
                    smtp_port_val = int(st.session_state.get(port_key) or 0)
                    if smtp_port_val <= 0:
                        smtp_port_val = 587
                    use_tls_flag = bool(st.session_state.get(tls_key)) and not bool(st.session_state.get(ssl_key))
                    use_ssl_flag = bool(st.session_state.get(ssl_key))

                    try:
                        # Desativar configurações anteriores
                        c.execute("UPDATE configuracao_email SET ativo = FALSE")

                        # Inserir nova configuração
                        c.execute(
                            """
                            INSERT INTO configuracao_email (smtp_server, smtp_port, use_tls, use_ssl, ativo)
                            VALUES (?, ?, ?, ?, TRUE)
                            """,
                            (smtp_server_val, smtp_port_val, use_tls_flag, use_ssl_flag),
                        )
                    except sqlite3.OperationalError:
                        # Colunas ausentes - manter apenas uma configuração básica
                        c.execute("DELETE FROM configuracao_email")
                        c.execute(
                            "INSERT INTO configuracao_email (smtp_server, smtp_port) VALUES (?, ?)",
                            (smtp_server_val, smtp_port_val),
                        )

                    conn.commit()
                    conn.close()

                    clear_email_cache()

                    st.success("Configuração de email guardada!")

            st.info(
                "Notas: Para Gmail é necessário usar uma 'App Password'. Para Outlook/Office365 o servidor recomendado é smtp.office365.com."
            )
        
        with tab_backup:
            st.subheader("Backup e Restauro")
            
            if st.button("💾 Criar Backup"):
                backup_path = backup_database()
                if backup_path:
                    st.success(f"Backup criado: {backup_path}")
                    
                    # Ler o ficheiro de backup para download
                    with open(backup_path, 'rb') as f:
                        backup_data = f.read()
                    
                    st.download_button(
                        "⬇️ Download Backup",
                        data=backup_data,
                        file_name=backup_path,
                        mime="application/octet-stream"
                    )
            
            st.markdown("---")
            
            st.warning("⚠️ Restaurar backup irá substituir todos os dados atuais!")
            
            uploaded_backup = st.file_uploader(
                "Selecionar ficheiro de backup",
                type=['db']
            )
            
            if uploaded_backup:
                if st.button("⚠️ Restaurar Backup", type="secondary"):
                    # Guardar ficheiro temporário
                    temp_path = "temp_restore.db"
                    with open(temp_path, 'wb') as f:
                        f.write(uploaded_backup.getvalue())
    
                    # Fazer backup atual antes de restaurar
                    backup_database("backup_antes_restauro.db")
    
                    # Restaurar
                    try:
                        shutil.copy2(temp_path, DB_PATH)
                        os.remove(temp_path)
                        st.success("Backup restaurado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao restaurar: {e}")
    
        with tab_layout:
            st.subheader("Layout dos PDFs")
            tipo_layout = st.selectbox("Tipo de PDF", ["pedido", "cliente"])
            config_atual = load_pdf_config(tipo_layout)
            config_texto = st.text_area(
                "Configuração (JSON)",
                json.dumps(config_atual, ensure_ascii=False, indent=2),
                height=400,
                key=f"layout_{tipo_layout}"
            )
            if st.button("💾 Guardar Layout"):
                try:
                    nova_config = json.loads(config_texto)
                    save_pdf_config(tipo_layout, nova_config)
                    st.success("Layout atualizado com sucesso!")
                except json.JSONDecodeError as e:
                    st.error(f"Erro no JSON: {e}")
            st.caption(
                "Altere textos, tamanhos de letra e posições editando o JSON acima."
            )
    
        with tab_empresa:
            st.subheader("Dados da Empresa")
            conn = obter_conexao()
            c = conn.cursor()
            c.execute(
                "SELECT nome, morada, nif, iban, banco, telefone, email, website, logo FROM configuracao_empresa ORDER BY id DESC LIMIT 1"
            )
            dados = c.fetchone()
            conn.close()
            with st.form("empresa_form"):
                nome_emp = st.text_input("Nome", dados[0] if dados else "")
                morada_emp = st.text_area("Morada", dados[1] if dados else "")
                nif_emp = st.text_input("NIF", dados[2] if dados else "")
                iban_emp = st.text_input("IBAN", dados[3] if dados else "")
                banco_emp = st.text_input("Banco", dados[4] if dados else "")
                telefone_emp = st.text_input("Telefone", dados[5] if dados else "")
                email_emp = st.text_input("Email", dados[6] if dados else "")
                website_emp = st.text_input("Website", dados[7] if dados else "")
                logo_guardado = dados[8] if dados and len(dados) > 8 else None
                logo_bytes = logo_guardado
                logo_upload = st.file_uploader(
                    "Logo", type=["png", "jpg", "jpeg"], key="logo_empresa"
                )
                if logo_upload is not None:
                    logo_bytes = logo_upload.getvalue()

                if logo_bytes:
                    st.image(logo_bytes, width=120)

                if st.form_submit_button("💾 Guardar"):
                    logo_para_guardar = logo_bytes
                    conn = obter_conexao()
                    c = conn.cursor()
                    c.execute("DELETE FROM configuracao_empresa")
                    c.execute(
                        "INSERT INTO configuracao_empresa (nome, morada, nif, iban, banco, telefone, email, website, logo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            nome_emp,
                            morada_emp,
                            nif_emp,
                            iban_emp,
                            banco_emp,
                            telefone_emp,
                            email_emp,
                            website_emp,
                            logo_para_guardar,
                        ),
                    )
                    conn.commit()
                    conn.close()
                    obter_config_empresa.clear()
                    st.success("Dados da empresa guardados!")

# Footer
st.markdown("---")
st.markdown("""
    <div style="text-align: center; color: #666; font-size: 12px;">
        Sistema myERP v4.0 | Desenvolvido por Ricardo Nogueira | © 2025
    </div>
""", unsafe_allow_html=True)


