"""Etapa 2 — para cada pesquisa sem resultado, busca na web por "instituto + registro",
prioriza o site oficial do instituto e extrai os percentuais.

    python -m pipeline.buscar_resultados
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

import settings
from core import candidatos as cand_mod
from core import db
from core.textutil import dominio, dominio_raiz, normalizar, regex_registro
from core.ufs import nome_uf
from pipeline import busca_web, extrair, http
from pipeline import tse_texto as tt

log = logging.getLogger("pipeline.buscar")

_GENERICAS = {"instituto", "pesquisa", "pesquisas", "opiniao", "brasil", "dados", "consultoria",
              "projetos", "tecnologia", "inteligencia", "mercado", "estatistica", "comunicacao", "grupo"}


@lru_cache(maxsize=1)
def _institutos_cfg() -> list[dict]:
    try:
        with open(settings.CONFIG_DIR / "institutos.json", encoding="utf-8") as f:
            return json.load(f).get("institutos", [])
    except (OSError, ValueError):
        return []


def dominios_oficiais(instituto: str, razao: str) -> list[str]:
    alvo = normalizar(f"{instituto} {razao}").upper()
    doms = []
    for item in _institutos_cfg():
        if any(normalizar(c).upper() in alvo for c in item.get("contem", [])):
            doms.extend(item.get("dominios", []))
    return doms


def eh_oficial(url: str, instituto: str, razao: str) -> bool:
    host = dominio(url)
    if any(host == d or host.endswith("." + d) for d in dominios_oficiais(instituto, razao)):
        return True
    nome = normalizar(instituto)
    colado = re.sub(r"[^a-z0-9]", "", nome)
    if len(colado) >= 5 and colado in host.replace("-", "").replace(".", ""):
        return True
    raiz = dominio_raiz(host).split(".")[0]
    toks = [t for t in re.findall(r"[a-z0-9]+", nome) if len(t) >= 5 and t not in _GENERICAS]
    return any(t == raiz or (len(t) >= 6 and t in raiz) for t in toks)


def nome_curto(instituto: str) -> str:
    """'Quaest Pesquisas, Consultoria e Projetos' -> 'Quaest' ; 'Real Time BIG Data' -> 'Real Time'."""
    toks = [t for t in re.findall(r"[A-Za-zÀ-ÿ0-9]+", instituto)
            if normalizar(t) not in _GENERICAS and normalizar(t) not in {"de", "da", "do", "e", "ltda", "ss", "me"}]
    return " ".join(toks[:2]) or instituto


def _consultas(p) -> list[str]:
    inst = p["instituto"]
    curto = nome_curto(inst)
    reg = p["registro"]
    cargo = "presidente" if p["cargo"] == "presidente" else "governador"
    local = "" if (p["abrangencia"] in (None, "BR")) else nome_uf(p["abrangencia"])
    qs = [
        f'"{reg}"',
        f"{curto} pesquisa segundo turno {cargo} {local}".strip(),
        f"{curto} {reg}",
    ]
    for d in dominios_oficiais(inst, p["instituto_razao"] or "")[:1]:
        qs.insert(0, f"site:{d} {reg}")
    return qs


def _pesquisas_da_rodada() -> list:
    hoje = settings.agora().date().isoformat()
    return db.q(
        "SELECT * FROM pesquisas "
        "WHERE status IN ('PENDENTE','DESCARTADA') AND data_divulgacao != '' AND data_divulgacao <= ? "
        "ORDER BY (ultima_tentativa IS NOT NULL), ultima_tentativa, data_divulgacao DESC "
        "LIMIT ?",
        (hoje, settings.MAX_PESQUISAS_POR_RODADA),
    )


def processar(p) -> int:
    """Busca e grava as fontes de uma pesquisa. Retorna quantas fontes com números foram achadas."""
    from pipeline.validar import checar_datas

    agora = settings.agora().isoformat()
    uf_cands = "BR" if p["cargo"] == "presidente" else p["uf_registro"]
    cands = cand_mod.listar(p["cargo"], uf_cands)
    if len(cands) < 2 or checar_datas(p):
        # falha que não depende da web: não gasta consultas; a validação registra o motivo
        db.executar(
            "UPDATE pesquisas SET tentativas = tentativas + 1, ultima_tentativa = ? WHERE protocolo = ? AND cargo = ?",
            (agora, p["protocolo"], p["cargo"]),
        )
        return 0
    apelidos = cand_mod.apelidos_exclusivos(cands)
    rx_reg = regex_registro(p["protocolo"])

    achados = busca_web.buscar(_consultas(p), limite=settings.MAX_URLS_POR_PESQUISA * 2)
    curto = normalizar(nome_curto(p["instituto"]))
    local = normalizar(nome_uf(p["abrangencia"])) if p["abrangencia"] not in (None, "BR") else ""
    nomes = [n for lst in apelidos.values() for n in lst]
    for a in achados:
        a["oficial"] = eh_oficial(a["url"], p["instituto"], p["instituto_razao"] or "")
        tit = normalizar(a.get("titulo") or "")
        a["relevancia"] = (2 * (curto in tit) + (bool(local) and local in tit)
                           + any(n in tit for n in nomes) + ("turno" in tit))
    achados.sort(key=lambda a: (not a["oficial"], -a["relevancia"]))
    achados = achados[: settings.MAX_URLS_POR_PESQUISA]

    agora = settings.agora().isoformat()
    paginas = []
    for a in achados:
        pag = http.pagina_texto(a["url"])
        if not pag:
            continue
        titulo, texto = pag
        reg_ok = bool(rx_reg and (rx_reg.search(texto) or rx_reg.search(normalizar(texto))))
        paginas.append((a, titulo, texto, reg_ok))

    # Abrangência não identificada no TSE: aceita a das fontes se ≥2 domínios concordarem
    abrangencia = p["abrangencia"]
    if abrangencia is None:
        votos: dict[str, set] = {}
        for a, _t, texto, reg_ok in paginas:
            if reg_ok:
                uf_pag = tt.abrangencia(texto)
                if uf_pag:
                    votos.setdefault(uf_pag, set()).add(dominio_raiz(a["url"]))
        ranking = sorted(((len(d), uf) for uf, d in votos.items()), reverse=True)
        if ranking and ranking[0][0] >= 2 and (len(ranking) == 1 or ranking[1][0] < ranking[0][0]):
            abrangencia = ranking[0][1]

    linhas = []
    for a, titulo, texto, reg_ok in paginas:
        blocos = extrair.extrair(texto, apelidos)
        extrair.anotar_registro(texto, blocos, rx_reg)
        ctx = extrair.contexto(texto, p["cargo"], abrangencia)
        linhas.append(
            (
                p["protocolo"], p["cargo"], a["url"], dominio_raiz(a["url"]), int(a["oficial"]),
                (titulo or a["titulo"])[:300], int(reg_ok), json.dumps(ctx), json.dumps(blocos),
                tt.margem_erro(texto) if reg_ok else None, tt.nivel_confianca(texto) if reg_ok else None, agora,
            )
        )

    with db.transacao() as c:
        c.execute("DELETE FROM fontes WHERE protocolo = ? AND cargo = ?", (p["protocolo"], p["cargo"]))
        c.executemany(
            "INSERT INTO fontes(protocolo, cargo, url, dominio, oficial, titulo, registro_encontrado, "
            "contexto_ok, extracao, margem_erro, nivel_confianca, obtida_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            linhas,
        )
        if abrangencia != p["abrangencia"]:
            c.execute("UPDATE pesquisas SET abrangencia = ? WHERE protocolo = ? AND cargo = ?",
                      (abrangencia, p["protocolo"], p["cargo"]))
        c.execute(
            "UPDATE pesquisas SET tentativas = tentativas + 1, ultima_tentativa = ? WHERE protocolo = ? AND cargo = ?",
            (agora, p["protocolo"], p["cargo"]),
        )
    return sum(1 for ln in linhas if json.loads(ln[8]))


def executar() -> dict:
    if not busca_web.provedores():
        log.warning("Nenhum provedor de busca configurado; etapa de busca ignorada.")
        return {"processadas": 0}
    lista = _pesquisas_da_rodada()
    total = 0
    for p in lista:
        try:
            total += processar(p)
        except Exception:  # uma pesquisa com problema não derruba a rodada
            log.exception("Erro ao buscar %s/%s", p["protocolo"], p["cargo"])
    http.limpar_cache_antigo()
    resumo = {"processadas": len(lista), "fontes_com_numeros": total}
    log.info("Busca: %s", resumo)
    return resumo


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    db.init_db()
    print(executar())
