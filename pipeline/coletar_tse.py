"""Etapa 1 — coleta as pesquisas eleitorais 2026 registradas no TSE (Portal de Dados Abertos).

Baixa os ZIPs de pesquisas, contratantes e pagantes, filtra 2º turno de Presidente e
Governador e grava/atualiza a tabela `pesquisas`.

    python -m pipeline.coletar_tse
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from datetime import timedelta
from pathlib import Path

import requests

import settings
from core import candidatos as cand_mod
from core import db
from core.textutil import chave_instituto, nome_instituto, num_br, parse_data, registro_fmt
from pipeline import http
from pipeline import tse_texto as tt

log = logging.getLogger("pipeline.coletar_tse")

PASTA = settings.DATA_DIR / "tse"
PASTA.mkdir(exist_ok=True)


def _url_recursos() -> dict[str, str]:
    """URLs dos ZIPs (descobertas na API CKAN do portal; fallback para o padrão conhecido)."""
    urls = {
        "pesquisas": settings.TSE_PESQUISAS_ZIP.format(ano=settings.ANO),
        "contratantes": settings.TSE_CONTRATANTE_ZIP.format(ano=settings.ANO),
        "pagantes": settings.TSE_PAGANTE_ZIP.format(ano=settings.ANO),
    }
    try:
        pkg = http.get(settings.TSE_CKAN_URL.format(ano=settings.ANO), timeout=30).json()["result"]
        for r in pkg.get("resources", []):
            u = r.get("url", "")
            if u.endswith(f"pesquisa_eleitoral_{settings.ANO}.zip"):
                urls["pesquisas"] = u
            elif u.endswith(f"pesquisa_contratante_{settings.ANO}.zip"):
                urls["contratantes"] = u
            elif u.endswith(f"pesquisa_pagante_{settings.ANO}.zip"):
                urls["pagantes"] = u
    except (requests.RequestException, ValueError, KeyError) as e:
        log.info("CKAN indisponível, usando URLs padrão: %s", e)
    return urls


def _baixar(url: str, nome: str) -> Path:
    destino = PASTA / nome
    tmp = destino.with_suffix(".tmp")
    http.baixar_arquivo(url, tmp)
    with zipfile.ZipFile(tmp) as z:  # valida antes de substituir
        if z.testzip() is not None:
            raise ValueError(f"ZIP corrompido: {url}")
    tmp.replace(destino)
    return destino


def _linhas_csv(caminho: Path) -> list[dict]:
    """Lê o CSV nacional (_BRASIL.csv) de dentro do ZIP; se não houver, junta os das UFs."""
    with zipfile.ZipFile(caminho) as z:
        nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
        alvo = [n for n in nomes if n.upper().endswith("_BRASIL.CSV")] or nomes
        linhas: list[dict] = []
        for n in alvo:
            bruto = z.read(n)
            try:
                txt = bruto.decode("utf-8")
            except UnicodeDecodeError:
                txt = bruto.decode("latin-1")
            linhas.extend(csv.DictReader(io.StringIO(txt), delimiter=";"))
        return linhas


def _limpo(v: str | None) -> str:
    v = (v or "").strip()
    return "" if v.upper() == "#NULO#" else v


def _cargos_da_linha(ds_cargo: str) -> list[str]:
    ds = (ds_cargo or "").lower()
    out = []
    if "presidente" in ds:
        out.append("presidente")
    if "governador" in ds:
        out.append("governador")
    return out


def coletar() -> dict:
    urls = _url_recursos()
    arq_pesq = _baixar(urls["pesquisas"], "pesquisa_eleitoral.zip")
    arq_cont = _baixar(urls["contratantes"], "pesquisa_contratante.zip")
    arq_pag = _baixar(urls["pagantes"], "pesquisa_pagante.zip")

    linhas = _linhas_csv(arq_pesq)
    if len(linhas) < 10:
        raise RuntimeError(f"CSV de pesquisas suspeito ({len(linhas)} linhas); abortando sem alterar o banco.")

    contratantes: dict[str, list[dict]] = {}
    for r in _linhas_csv(arq_cont):
        p = r.get("NR_PROTOCOLO_REGISTRO", "")
        item = {"nome": _limpo(r.get("NM_CONTRATANTE")), "valor": num_br(r.get("VR_PAGO_CONTRATANTE"))}
        if item["nome"] and item not in contratantes.setdefault(p, []):
            contratantes[p].append(item)
    pagantes: dict[str, list[dict]] = {}
    for r in _linhas_csv(arq_pag):
        p = r.get("NR_PROTOCOLO_REGISTRO", "")
        item = {"nome": _limpo(r.get("NM_PAGANTE")), "origem": _limpo(r.get("DS_ORIGEM_RECURSO"))}
        if item["nome"] and item not in pagantes.setdefault(p, []):
            pagantes[p].append(item)

    ufs_gov_2t = set(cand_mod.ufs_com_2_turno_governador())
    inicio_2t = settings.DATA_1_TURNO + timedelta(days=1)
    hoje = settings.agora().date()
    agora_iso = settings.agora().isoformat()

    vistos: set[tuple[str, str]] = set()
    novos = atualizados = 0

    with db.transacao() as c:
        for r in linhas:
            ini = parse_data(r.get("DT_INICIO_PESQUISA"))
            if not ini or ini < inicio_2t:
                continue  # coleta iniciada antes do 1º turno: não é pesquisa de 2º turno
            protocolo = (r.get("NR_PROTOCOLO_REGISTRO") or "").strip().upper()
            if not protocolo:
                continue
            uf_reg = (r.get("SG_UF") or "").upper()
            texto_plano = (r.get("DS_PLANO_AMOSTRAL") or "") + "\n" + (r.get("DS_METODOLOGIA_PESQUISA") or "")

            for cargo in _cargos_da_linha(r.get("DS_CARGO", "")):
                if cargo == "governador":
                    if uf_reg == "BR" or (ufs_gov_2t and uf_reg not in ufs_gov_2t):
                        continue
                    abrang = uf_reg
                else:
                    abrang = uf_reg if uf_reg != "BR" else tt.abrangencia(texto_plano)

                instituto = nome_instituto(r.get("NM_EMPRESA_FANTASIA", ""), r.get("NM_EMPRESA", ""))
                registro = {
                    "registro": registro_fmt(protocolo),
                    "uf_registro": uf_reg,
                    "instituto": instituto,
                    "instituto_razao": _limpo(r.get("NM_EMPRESA")),
                    "instituto_chave": chave_instituto(r.get("NR_CNPJ_EMPRESA", ""), instituto),
                    "cnpj": _limpo(r.get("NR_CNPJ_EMPRESA")),
                    "contratantes": json.dumps(contratantes.get(protocolo, []), ensure_ascii=False),
                    "pagantes": json.dumps(pagantes.get(protocolo, []), ensure_ascii=False),
                    "pesquisa_propria": 1 if (r.get("ST_PESQUISA_PROPRIA") or "").upper() == "S" else 0,
                    "valor": num_br(r.get("VR_PESQUISA")),
                    "estatistico": _limpo(r.get("NM_ESTATISTICO_RESP")),
                    "periodo_inicio": str(ini),
                    "periodo_fim": str(parse_data(r.get("DT_FIM_PESQUISA")) or ""),
                    "entrevistados": int(num_br(r.get("QT_ENTREVISTADO")) or 0) or None,
                    "margem_erro": tt.margem_erro(texto_plano),
                    "nivel_confianca": tt.nivel_confianca(texto_plano),
                    "data_registro": (r.get("DT_REGISTRO") or "").strip(),
                    "data_divulgacao": str(parse_data(r.get("DT_DIVULGACAO")) or ""),
                    "metodologia": _limpo(r.get("DS_METODOLOGIA_PESQUISA"))[:4000],
                    "plano_amostral": _limpo(r.get("DS_PLANO_AMOSTRAL"))[:8000],
                }
                vistos.add((protocolo, cargo))
                atual = c.execute(
                    "SELECT * FROM pesquisas WHERE protocolo = ? AND cargo = ?", (protocolo, cargo)
                ).fetchone()
                divulg = parse_data(registro["data_divulgacao"])
                if atual is None:
                    status = "AGUARDANDO_DIVULGACAO" if divulg and divulg > hoje else "PENDENTE"
                    cols = ["protocolo", "cargo", "abrangencia", "status", "coletada_em", "atualizada_em", *registro]
                    vals = [protocolo, cargo, abrang, status, agora_iso, agora_iso, *registro.values()]
                    c.execute(
                        f"INSERT INTO pesquisas({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals
                    )
                    novos += 1
                else:
                    # margem/confiança/abrangência obtidas das fontes não são apagadas pelo TSE vazio
                    if registro["margem_erro"] is None:
                        registro["margem_erro"] = atual["margem_erro"]
                    if registro["nivel_confianca"] is None:
                        registro["nivel_confianca"] = atual["nivel_confianca"]
                    mudou = any(str(atual[k] or "") != str(v or "") for k, v in registro.items())
                    novo_abrang = abrang if abrang else atual["abrangencia"]
                    status = atual["status"]
                    if status == "SEM_REGISTRO":
                        status = "PENDENTE"
                    if status == "AGUARDANDO_DIVULGACAO" and divulg and divulg <= hoje:
                        status = "PENDENTE"
                    if mudou or status != atual["status"] or novo_abrang != atual["abrangencia"]:
                        sets = ", ".join(f"{k} = ?" for k in registro)
                        c.execute(
                            f"UPDATE pesquisas SET {sets}, abrangencia = ?, status = ?, atualizada_em = ? "
                            "WHERE protocolo = ? AND cargo = ?",
                            [*registro.values(), novo_abrang, status, agora_iso, protocolo, cargo],
                        )
                        atualizados += 1

        # Pesquisas que sumiram do TSE (registro cancelado/excluído) deixam de ser exibidas
        removidas = 0
        existentes = c.execute(
            "SELECT protocolo, cargo, status FROM pesquisas WHERE status != 'SEM_REGISTRO'"
        ).fetchall()
        if len(vistos) >= 0.8 * len(existentes):
            for e in existentes:
                if (e["protocolo"], e["cargo"]) not in vistos:
                    c.execute(
                        "UPDATE pesquisas SET status = 'SEM_REGISTRO', motivo = ?, atualizada_em = ? "
                        "WHERE protocolo = ? AND cargo = ?",
                        ("Registro não consta mais na base do TSE", agora_iso, e["protocolo"], e["cargo"]),
                    )
                    c.execute(
                        "INSERT INTO log_validacao(em, protocolo, cargo, status, motivo) VALUES(?,?,?,?,?)",
                        (agora_iso, e["protocolo"], e["cargo"], "SEM_REGISTRO",
                         "Registro não consta mais na base de dados abertos do TSE; pesquisa ocultada."),
                    )
                    removidas += 1
        else:
            log.warning("Base do TSE com menos registros que o esperado; nenhuma pesquisa foi ocultada.")

        assinatura = hashlib.sha256(arq_pesq.read_bytes()).hexdigest()[:16]
        db.set_meta("tse_coletado_em", agora_iso, c)
        db.set_meta("tse_assinatura", assinatura, c)

    resumo = {"linhas_tse": len(linhas), "pesquisas_2t": len(vistos), "novas": novos,
              "atualizadas": atualizados, "ocultadas": removidas}
    log.info("Coleta TSE: %s", resumo)
    return resumo


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    db.init_db()
    print(coletar())
