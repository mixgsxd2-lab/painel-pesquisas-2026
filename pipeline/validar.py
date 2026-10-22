"""Etapa 3 — valida e publica AUTOMATICAMENTE apenas pesquisas que passam em TODAS as regras:

  1. o número de registro aparece na página da fonte;
  2. pelo menos 2 fontes independentes (domínios diferentes) trazem os mesmos números
     (tolerância de 0,5 ponto);
  3. cargo, UF e turno da página batem com o registro do TSE;
  4. os nomes dos candidatos batem com os candidatos do 2º turno;
  5. soma dos percentuais entre 85% e 101%;
  6. tipo de resultado identificado (votos totais ou válidos) e igual entre as fontes;
  7. data de divulgação pelo menos 5 dias após a data de registro no TSE
     (e já alcançada).
  + margem de erro e nível de confiança conhecidos (exigidos para exibição).

Se falhar: status DESCARTADA (invisível), motivo registrado em log; nova tentativa na próxima rodada.

    python -m pipeline.validar
"""
from __future__ import annotations

import json
import logging

import settings
from core import candidatos as cand_mod
from core import db
from core.textutil import data_br, parse_data

log = logging.getLogger("pipeline.validar")
TIPOS = ("totais", "validos")


def iguais(a: dict, b: dict, tol: float = settings.TOLERANCIA_PONTOS) -> bool:
    """Mesmos percentuais dos candidatos (tolerância de 0,5 ponto). Brancos/nulos e indecisos têm
    confirmação própria (só são exibidos se 2 fontes concordarem)."""
    if set(a["candidatos"]) != set(b["candidatos"]):
        return False
    return all(abs(v - b["candidatos"][n]) <= tol + 1e-9 for n, v in a["candidatos"].items())


def soma(bloco: dict) -> float:
    return sum(bloco["candidatos"].values()) + (bloco.get("brancos_nulos") or 0) + (bloco.get("indecisos") or 0)


def pesquisa_unica(p) -> bool:
    """O instituto tem só esta pesquisa para este cargo e abrangência no 2º turno?"""
    r = db.q1("SELECT COUNT(*) n FROM pesquisas WHERE instituto_chave = ? AND cargo = ? AND "
              "COALESCE(abrangencia, '') = COALESCE(?, '') AND status != 'SEM_REGISTRO'",
              (p["instituto_chave"], p["cargo"], p["abrangencia"]))
    return bool(r) and r["n"] == 1


def checar_datas(p) -> str | None:
    reg = parse_data(p["data_registro"])
    div = parse_data(p["data_divulgacao"])
    if not reg or not div:
        return "Datas de registro/divulgação ausentes no TSE"
    if (div - reg).days < settings.DIAS_MIN_REGISTRO_DIVULGACAO:
        return (f"Divulgação ({data_br(div)}) a menos de {settings.DIAS_MIN_REGISTRO_DIVULGACAO} dias "
                f"do registro ({data_br(reg)})")
    if div > settings.agora().date():
        return f"Data de divulgação ({data_br(div)}) ainda não chegou"
    return None


def avaliar(p, fontes: list) -> tuple[dict, list[str], dict]:
    """Retorna (tipos_validados{tipo: {bloco, urls}}, motivos_de_falha, extras)."""
    motivos: list[str] = []
    extras: dict = {}

    m = checar_datas(p)
    if m:
        return {}, [m], extras
    if not p["abrangencia"]:
        motivos.append("Abrangência (nacional ou UF) não identificada no registro nem nas fontes")
    uf_cands = "BR" if p["cargo"] == "presidente" else p["uf_registro"]
    cands = cand_mod.listar(p["cargo"], uf_cands)
    if len(cands) != 2:
        motivos.append("Candidatos do 2º turno não definidos para este cargo/UF")
    if motivos:
        return {}, motivos, extras
    numeros = {c["numero"] for c in cands}

    if not fontes:
        return {}, ["Nenhuma fonte encontrada na web"], extras
    com_registro = [f for f in fontes if f["registro_encontrado"]]
    # sem o número na página: só vale se o instituto tem UMA única pesquisa desta disputa
    # (não há outra com que confundir) e a página cita o instituto
    unica = pesquisa_unica(p)
    sem_registro_ok = [f for f in fontes if not f["registro_encontrado"] and unica
                       and db.jloads(f["contexto_ok"], {}).get("instituto")]
    candidatas = com_registro + sem_registro_ok
    if not candidatas:
        return {}, ["Número de registro não aparece em nenhuma fonte encontrada"], extras

    elegiveis = []
    falhas_ctx = []
    for f in candidatas:
        ctx = db.jloads(f["contexto_ok"], {})
        if ctx.get("cargo") and ctx.get("turno") and ctx.get("uf") is True:
            elegiveis.append(f)
        else:
            faltou = [k for k in ("cargo", "turno", "uf") if ctx.get(k) is not True]
            falhas_ctx.append(f"{f['dominio']} ({', '.join(faltou)})")
    if not elegiveis:
        return {}, ["Cargo/UF/turno da página não conferem com o registro: " + "; ".join(falhas_ctx[:4])], extras

    validados: dict[str, dict] = {}
    motivos_tipo: list[str] = []
    for tipo in TIPOS:
        # um bloco por domínio (fontes independentes), priorizando site oficial
        por_dominio: dict[str, tuple] = {}
        for f in sorted(elegiveis, key=lambda f: (not f["oficial"], f["id"])):
            todos = [b for b in db.jloads(f["extracao"], []) if set(b["candidatos"]) == numeros]
            if not todos:
                continue
            if todos[0].get("pagina_multipla"):
                # página-resumo com várias pesquisas: usa o bloco deste tipo mais perto do registro
                perto = [b for b in todos if b.get("tipo") == tipo and b.get("dist_reg") is not None
                         and b["dist_reg"] <= 1500]
                escolhido = min(perto, key=lambda b: b["dist_reg"]) if perto else None
            elif todos[0].get("tipo") == tipo:
                # o bloco principal (manchete) tem prioridade
                escolhido = todos[0]
            else:
                escolhido = next((b for b in todos[1:] if b.get("tipo") == tipo), None)
            if escolhido and f["dominio"] not in por_dominio:
                por_dominio[f["dominio"]] = (escolhido, f)
        if not por_dominio:
            continue
        melhor = None
        for dom, (ref, fref) in por_dominio.items():
            concord = [(b, f) for d, (b, f) in por_dominio.items() if iguais(ref, b)]
            chave = (len(concord), any(f["registro_encontrado"] for _, f in concord))
            if melhor is None or chave > melhor[2]:
                melhor = ((ref, fref), concord, chave)
        (ref, fref), concord, _ = melhor
        # 1 fonte basta se ela cita o número de registro; sem o número, exige 2 fontes que concordem
        minimo = 1 if any(f["registro_encontrado"] for _, f in concord) else settings.MIN_FONTES_INDEPENDENTES
        if len(concord) < minimo:
            motivos_tipo.append(
                f"Votos {tipo}: só {len(concord)} fonte(s) independente(s) com os mesmos números"
            )
            continue
        bloco = {"candidatos": dict(ref["candidatos"]), "brancos_nulos": None, "indecisos": None}
        if tipo == "totais":
            # brancos/nulos e indecisos só entram se confirmados por 2 fontes independentes
            for k in ("brancos_nulos", "indecisos"):
                vals = [b.get(k) for b, _ in concord if b.get(k) is not None]
                for v in vals:
                    if sum(1 for w in vals if abs(w - v) <= settings.TOLERANCIA_PONTOS) >= min(2, len(concord)):
                        bloco[k] = v
                        break
        s = soma(bloco)
        if not (settings.SOMA_MIN <= s <= settings.SOMA_MAX):
            motivos_tipo.append(f"Votos {tipo}: soma dos percentuais ({s:.1f}%) fora de 85%–101%")
            continue
        urls = [f["url"] for _, f in sorted(concord, key=lambda bf: (not bf[1]["oficial"], bf[1]["id"]))]
        validados[tipo] = {"bloco": bloco, "urls": urls, "fontes": [f for _, f in concord]}

    if not validados:
        if not motivos_tipo:
            motivos_tipo.append("Tipo de resultado (votos totais ou válidos) não identificado nas fontes")
        return {}, motivos_tipo, extras

    # margem de erro e nível de confiança: TSE ou, se ausentes, as fontes que concordaram
    margem, conf = p["margem_erro"], p["nivel_confianca"]
    fontes_ok = [f for v in validados.values() for f in v["fontes"]]
    if margem is None:
        vals = sorted({f["margem_erro"] for f in fontes_ok if f["margem_erro"] is not None})
        margem = vals[0] if len(vals) == 1 else None
    if conf is None:
        vals = sorted({f["nivel_confianca"] for f in fontes_ok if f["nivel_confianca"] is not None})
        conf = vals[0] if len(vals) == 1 else None
    if margem is None or conf is None:
        return {}, ["Margem de erro ou nível de confiança não identificados"], extras
    extras.update({"margem_erro": margem, "nivel_confianca": conf})
    return validados, [], extras


def publicar(p, validados: dict, extras: dict) -> None:
    agora = settings.agora().isoformat()
    uf = p["abrangencia"]
    cands = {c["numero"]: c for c in cand_mod.listar(p["cargo"], "BR" if p["cargo"] == "presidente" else p["uf_registro"])}
    with db.transacao() as c:
        for tipo, v in validados.items():
            c.execute(
                "INSERT INTO resultados(protocolo, cargo, tipo, dados, fontes, publicado_em) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(protocolo, cargo, tipo) DO NOTHING",
                (p["protocolo"], p["cargo"], tipo, db.jdumps(v["bloco"]), db.jdumps(v["urls"]), agora),
            )
            fontes_txt = " | ".join(v["urls"])
            itens = [(n, cands.get(n, {}).get("nome_urna", n), val) for n, val in v["bloco"]["candidatos"].items()]
            itens += [("brancos_nulos", "Brancos/nulos", v["bloco"].get("brancos_nulos")),
                      ("indecisos", "Indecisos", v["bloco"].get("indecisos"))]
            for chave, rotulo, val in itens:
                if val is None:
                    continue
                c.execute(
                    "INSERT INTO historico(registrado_em, evento, protocolo, cargo, uf, tipo, chave, rotulo, valor, fontes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (agora, "PUBLICACAO", p["protocolo"], p["cargo"], uf, tipo, chave, rotulo, val, fontes_txt),
                )
        c.execute(
            "UPDATE pesquisas SET status = 'PUBLICADA', motivo = NULL, publicada_em = ?, atualizada_em = ?, "
            "margem_erro = ?, nivel_confianca = ? WHERE protocolo = ? AND cargo = ?",
            (agora, agora, extras["margem_erro"], extras["nivel_confianca"], p["protocolo"], p["cargo"]),
        )
        c.execute(
            "INSERT INTO log_validacao(em, protocolo, cargo, status, motivo, detalhes) VALUES(?,?,?,?,?,?)",
            (agora, p["protocolo"], p["cargo"], "PUBLICADA", "Todas as validações aprovadas",
             json.dumps({t: v["urls"] for t, v in validados.items()}, ensure_ascii=False)),
        )
        db.set_meta("dados_atualizados_em", agora, c)
        db.set_meta(f"atualizado:{p['cargo']}:{uf}", agora, c)
    log.info("PUBLICADA %s/%s (%s)", p["registro"], p["cargo"], ", ".join(validados))


def descartar(p, motivos: list[str]) -> None:
    agora = settings.agora().isoformat()
    motivo = " · ".join(motivos)[:1000]
    with db.transacao() as c:
        c.execute(
            "UPDATE pesquisas SET status = 'DESCARTADA', motivo = ?, atualizada_em = ? WHERE protocolo = ? AND cargo = ?",
            (motivo, agora, p["protocolo"], p["cargo"]),
        )
        c.execute(
            "INSERT INTO log_validacao(em, protocolo, cargo, status, motivo) VALUES(?,?,?,?,?)",
            (agora, p["protocolo"], p["cargo"], "DESCARTADA", motivo),
        )
    log.info("DESCARTADA %s/%s: %s", p["registro"], p["cargo"], motivo)


def validar_uma(protocolo: str, cargo: str) -> str | None:
    """Valida (e publica, se passar) uma única pesquisa logo após a busca."""
    p = db.q1("SELECT * FROM pesquisas WHERE protocolo = ? AND cargo = ?", (protocolo, cargo))
    if not p or p["status"] not in ("PENDENTE", "DESCARTADA"):
        return None
    fontes = db.q("SELECT * FROM fontes WHERE protocolo = ? AND cargo = ? ORDER BY id", (protocolo, cargo))
    validados, motivos, extras = avaliar(p, fontes)
    if validados:
        publicar(p, validados, extras)
        try:
            from pipeline import semente
            semente.exportar()
        except Exception:
            log.exception("Falha ao salvar a semente")
        return "PUBLICADA"
    descartar(p, motivos)
    return "DESCARTADA"


def executar() -> dict:
    # avalia as pesquisas que passaram pela busca desde a última avaliação
    lista = db.q(
        "SELECT * FROM pesquisas WHERE status IN ('PENDENTE','DESCARTADA') "
        "AND ultima_tentativa IS NOT NULL AND ultima_tentativa >= atualizada_em"
    )
    pub = desc = 0
    for p in lista:
        fontes = db.q("SELECT * FROM fontes WHERE protocolo = ? AND cargo = ? ORDER BY id", (p["protocolo"], p["cargo"]))
        validados, motivos, extras = avaliar(p, fontes)
        if validados:
            publicar(p, validados, extras)
            pub += 1
        else:
            descartar(p, motivos)
            desc += 1
    resumo = {"avaliadas": len(lista), "publicadas": pub, "descartadas": desc}
    log.info("Validação: %s", resumo)
    return resumo


if __name__ == "__main__":
    from pipeline.run import configurar_log

    configurar_log()
    db.init_db()
    print(executar())
