"""Extração dos percentuais de uma pesquisa a partir do texto de uma página/PDF.

Estratégia conservadora: localiza os nomes dos candidatos do 2º turno, associa a cada
menção o percentual mais próximo, agrupa os dois candidatos em "blocos" e identifica,
no entorno, brancos/nulos, indecisos e o tipo de resultado (votos totais ou válidos).
Qualquer ambiguidade vira bloco sem tipo — e blocos sem tipo nunca são publicados.
"""
from __future__ import annotations

import re

from core.textutil import normalizar
from pipeline import tse_texto as tt

_NUM = r"(\d{1,2}(?:[.,]\d{1,2})?)"
_RE_PCT = re.compile(rf"(?<![\d.,]){_NUM}\s?%")
_RE_BN = re.compile(
    r"(?:brancos?\s*(?:e|/|,|ou|\+)\s*nulos?|nulos?\s*(?:e|/|,|ou|\+)\s*brancos?|branco/nulo)"
    rf"[^%\d.,;]{{0,45}}?{_NUM}\s?%"
)
_RE_BRANCO = re.compile(rf"\bbrancos?\b[^%\d]{{0,25}}?{_NUM}\s?%")
_RE_NULO = re.compile(rf"\bnulos?\b[^%\d]{{0,25}}?{_NUM}\s?%")
_RE_IND = re.compile(
    r"(?:indecisos?|nao (?:sabem?|souberam)(?: ou nao (?:responderam|opinaram))?|nao responderam|"
    r"ns/nr|nao sabe/nao respondeu|nao opinaram)"
    rf"[^%\d.,;]{{0,45}}?{_NUM}\s?%"
)
# forma invertida: "9% disseram que votarão em branco ou nulo", "1% se disseram indecisos"
_RE_BN_INV = re.compile(
    rf"{_NUM}\s?%[^%\d]{{0,60}}?(?:em\s+)?(?:brancos?\s*(?:e|/|,|ou)\s*(?:nulos?|anular)|nulos?\s*(?:e|/|,|ou)\s*brancos?)"
)
_RE_IND_INV = re.compile(rf"{_NUM}\s?%[^%\d]{{0,45}}?(?:indecis|nao sab|nao respond|nao opin)")
_RE_VALIDOS = re.compile(r"votos? validos")
_RE_TOTAIS = re.compile(r"votos? totais|intencao de voto|estimulad|cenario de segundo turno|total de votos")

JANELA_CAND = 70      # distância máx. entre nome e percentual
JANELA_BLOCO = 450    # distância máx. entre os candidatos de um bloco


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _percentuais(t: str) -> list[tuple[int, int, float]]:
    return [(m.start(), m.end(), _f(m.group(1))) for m in _RE_PCT.finditer(t)]


def _mencoes(t: str, apelidos: dict[str, list[str]]) -> list[tuple[int, int, str]]:
    out = []
    for numero, nomes in apelidos.items():
        for nome in nomes:
            if not nome:
                continue
            for m in re.finditer(rf"\b{re.escape(nome)}\b", t):
                out.append((m.start(), m.end(), numero))
    out.sort()
    # remove menções sobrepostas (ex.: 'flavio bolsonaro' e 'bolsonaro')
    filtrado: list[tuple[int, int, str]] = []
    for m in out:
        if filtrado and m[0] < filtrado[-1][1]:
            if (m[1] - m[0]) > (filtrado[-1][1] - filtrado[-1][0]):
                filtrado[-1] = m
            continue
        filtrado.append(m)
    return filtrado


def _valor_da_mencao(t, mencao, pcts, mencoes) -> tuple[int, float] | None:
    ini, fim, numero = mencao
    prox_outro = min((m[0] for m in mencoes if m[0] > fim and m[2] != numero), default=len(t))
    for p_ini, p_fim, v in pcts:
        if p_ini >= fim and p_ini - fim <= JANELA_CAND and p_ini < prox_outro:
            entre = t[fim:p_ini]
            if "." in entre.replace(",", "") and re.search(r"\.\s", entre):
                break  # não atravessa fim de frase
            return p_ini, v
        if p_ini > fim + JANELA_CAND:
            break
    # forma "48% para Fulano" / "48% - Fulano"
    for p_ini, p_fim, v in reversed(pcts):
        if p_fim <= ini and ini - p_fim <= 18 and re.fullmatch(r"[\s\-–:|(]*(?:para|de|a)?\s*", t[p_fim:ini]):
            return p_ini, v
    return None


def _tipo(t: str, ini: int, fim: int, cand_vals: dict, bn, ind) -> str | None:
    soma_c = sum(cand_vals.values())
    if bn is not None or ind is not None:
        return "totais"
    janela_ini = max(0, ini - 260)
    janela = t[janela_ini: fim + 160]
    pos_v = [janela_ini + m.start() for m in _RE_VALIDOS.finditer(janela)]
    pos_t = [janela_ini + m.start() for m in _RE_TOTAIS.finditer(janela)]
    if 98.5 <= soma_c <= 101.0:
        return "validos"
    if pos_v and not pos_t:
        return "validos" if 98.5 <= soma_c <= 101.0 else None
    if pos_t and not pos_v:
        return "totais"
    if pos_v and pos_t:
        dv = min(abs(p - ini) for p in pos_v)
        dt = min(abs(p - ini) for p in pos_t)
        return "totais" if dt < dv else None
    return None


def extrair(texto: str, apelidos: dict[str, list[str]]) -> list[dict]:
    """Retorna blocos [{tipo, candidatos{numero: pct}, brancos_nulos, indecisos, pos}]."""
    t = normalizar(texto)
    pcts = _percentuais(t)
    mencoes = _mencoes(t, apelidos)
    numeros = list(apelidos)
    if len(numeros) < 2 or not pcts or not mencoes:
        return []

    valores = []
    for m in mencoes:
        r = _valor_da_mencao(t, m, pcts, mencoes)
        if r:
            valores.append((m[0], m[2], r[1], r[0]))

    blocos: list[dict] = []
    usados = set()
    for i, (pos, numero, v, ppos) in enumerate(valores):
        if i in usados:
            continue
        grupo = {numero: (v, pos)}
        idx = [i]
        for j in range(i + 1, len(valores)):
            pj, nj, vj, _ = valores[j]
            if pj - pos > JANELA_BLOCO:
                break
            if nj not in grupo:
                grupo[nj] = (vj, pj)
                idx.append(j)
            if len(grupo) == len(numeros):
                break
        if len(grupo) != len(numeros):
            continue
        usados.update(idx)
        ini = min(p for _, p in grupo.values())
        fim = max(p for _, p in grupo.values()) + 40
        cauda = t[ini: fim + 320]
        # posições (relativas à cauda) dos percentuais que pertencem aos candidatos
        pos_cands = {valores[j][3] - ini for j in idx}

        def _primeiro(rx_direta, rx_inv):
            m = rx_direta.search(cauda)
            if m:
                return _f(m.group(1))
            for mi in rx_inv.finditer(cauda):
                if mi.start(1) not in pos_cands:
                    return _f(mi.group(1))
            return None

        bn = _primeiro(_RE_BN, _RE_BN_INV)
        if bn is None:
            mb, mn = _RE_BRANCO.search(cauda), _RE_NULO.search(cauda)
            if mb and mn and mb.start() != mn.start():
                bn = round(_f(mb.group(1)) + _f(mn.group(1)), 2)
        ind = _primeiro(_RE_IND, _RE_IND_INV)
        cand_vals = {n: val for n, (val, _) in grupo.items()}
        tipo = _tipo(t, ini, fim, cand_vals, bn, ind)
        if tipo == "validos":
            bn = ind = None
        bloco = {"tipo": tipo, "candidatos": cand_vals, "brancos_nulos": bn, "indecisos": ind, "pos": ini}
        if not any(b["candidatos"] == bloco["candidatos"] and b["tipo"] == tipo for b in blocos):
            blocos.append(bloco)
    # bloco sem tipo herda o tipo de um bloco posterior com os MESMOS números na mesma página
    for i, b in enumerate(blocos):
        if b["tipo"] is None:
            for o in blocos[i + 1:]:
                if o["tipo"] and all(abs(o["candidatos"][n] - v) < 0.05 for n, v in b["candidatos"].items()):
                    b["tipo"] = o["tipo"]
                    if o["tipo"] == "totais":
                        b["brancos_nulos"] = b["brancos_nulos"] if b["brancos_nulos"] is not None else o["brancos_nulos"]
                        b["indecisos"] = b["indecisos"] if b["indecisos"] is not None else o["indecisos"]
                    break
    if blocos:
        blocos[0]["principal"] = True
    return blocos


def contexto(texto: str, cargo: str, abrangencia: str | None) -> dict:
    """Confere se a página fala do mesmo cargo, UF e turno do registro."""
    t = normalizar(texto)
    if cargo == "presidente":
        cargo_ok = bool(re.search(r"presiden|planalto", t))
    else:
        cargo_ok = bool(re.search(r"governador|governo d[oae]", t))
    turno_ok = tt.menciona_segundo_turno(t)
    uf_ok = None
    uf_pagina = tt.abrangencia(t)
    if abrangencia and abrangencia != "BR":
        from core.ufs import UFS

        nome = normalizar(UFS[abrangencia]["nome"])
        sigla_presente = bool(re.search(rf"(?<![a-z]){abrangencia}(?![a-z])", texto))
        uf_ok = (nome in t) or sigla_presente
    elif abrangencia == "BR":
        pts = tt.pontuar_ufs(t)
        uf_ok = not pts or max(pts.values()) < 3 or uf_pagina == "BR"
    return {"cargo": cargo_ok, "turno": turno_ok, "uf": uf_ok, "uf_pagina": uf_pagina}
