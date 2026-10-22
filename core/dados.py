"""Consultas usadas pelo site: pesquisas publicadas, médias, mapa e apuração."""
from __future__ import annotations

import threading
from statistics import mean

import settings
from core import candidatos as cand_mod
from core import db
from core.textutil import dominio, parse_data, registro_slug
from core.ufs import CARGOS, UFS, nome_uf

TIPO_NOME = {"totais": "Votos totais", "validos": "Votos válidos"}

_cache: dict = {}
_cache_lock = threading.Lock()


def versao() -> str:
    return (db.get_meta("dados_atualizados_em") or "0") + "|" + (db.get_meta("candidatos_atualizados_em") or "0")


def _memo(chave, fn):
    v = versao()
    with _cache_lock:
        if _cache.get("_v") != v:
            _cache.clear()
            _cache["_v"] = v
        if chave in _cache:
            return _cache[chave]
    r = fn()
    with _cache_lock:
        _cache[chave] = r
    return r


def uf_candidatos(cargo: str, abrangencia: str, uf_registro: str | None = None) -> str:
    return "BR" if cargo == "presidente" else (uf_registro or abrangencia)


def abrangencia_nome(ab: str | None) -> str:
    if not ab:
        return "Não identificada"
    if ab == "BR":
        return "Nacional"
    return f"Estadual — {nome_uf(ab)} ({ab})"


# --------------------------------------------------------------------------- pesquisas
def _enriquecer(p, resultados_rows) -> dict:
    d = dict(p)
    d["cargo_nome"] = CARGOS[d["cargo"]]["nome"]
    d["slug"] = registro_slug(d["protocolo"])
    d["url"] = f"/pesquisas/{d['slug']}"
    d["contratantes"] = db.jloads(d.get("contratantes"), [])
    d["pagantes"] = db.jloads(d.get("pagantes"), [])
    d["abrangencia_nome"] = abrangencia_nome(d.get("abrangencia"))
    d["local_curto"] = "Brasil" if d.get("abrangencia") == "BR" else (d.get("abrangencia") or "")
    cands = cand_mod.listar(d["cargo"], uf_candidatos(d["cargo"], d["abrangencia"], d["uf_registro"]))
    por_num = {c["numero"]: c for c in cands}
    res = []
    for r in sorted(resultados_rows, key=lambda r: r["tipo"] != "totais"):
        dados = db.jloads(r["dados"], {})
        itens = []
        for num, val in dados.get("candidatos", {}).items():
            c = por_num.get(num, {})
            itens.append({
                "numero": num, "rotulo": c.get("nome_urna", num), "partido": c.get("partido", ""),
                "valor": val, "cor": c.get("cor", cand_mod.cor_sem_dados()), "ordem": c.get("ordem", 9),
            })
        itens.sort(key=lambda i: i["ordem"])
        res.append({
            "tipo": r["tipo"],
            "tipo_nome": TIPO_NOME.get(r["tipo"], r["tipo"]),
            "itens": itens,
            "brancos_nulos": dados.get("brancos_nulos"),
            "indecisos": dados.get("indecisos"),
            "fontes": [{"url": u, "dominio": dominio(u)} for u in db.jloads(r["fontes"], [])],
            "publicado_em": r["publicado_em"],
        })
    d["resultados"] = res
    return d


def pesquisas_publicadas(cargo: str | None = None, uf: str | None = None, instituto: str | None = None,
                         de: str | None = None, ate: str | None = None) -> list[dict]:
    def carregar():
        sql = "SELECT * FROM pesquisas WHERE status = 'PUBLICADA'"
        params: list = []
        if cargo:
            sql += " AND cargo = ?"
            params.append(cargo)
        if uf:
            sql += " AND abrangencia = ?"
            params.append(uf.upper())
        if instituto:
            sql += " AND instituto_chave = ?"
            params.append(instituto)
        if de:
            sql += " AND data_divulgacao >= ?"
            params.append(de)
        if ate:
            sql += " AND data_divulgacao <= ?"
            params.append(ate)
        sql += " ORDER BY data_divulgacao DESC, periodo_fim DESC, publicada_em DESC"
        linhas = db.q(sql, params)
        if not linhas:
            return []
        res = db.q(
            f"SELECT * FROM resultados WHERE protocolo IN ({','.join('?' * len(linhas))})",
            [l["protocolo"] for l in linhas],
        )
        por_chave: dict = {}
        for r in res:
            por_chave.setdefault((r["protocolo"], r["cargo"]), []).append(r)
        return [_enriquecer(l, por_chave.get((l["protocolo"], l["cargo"]), [])) for l in linhas]

    return _memo(("pub", cargo, uf, instituto, de, ate), carregar)


def pesquisa(protocolo: str) -> list[dict]:
    """Todas as linhas publicadas (um registro pode cobrir presidente e governador)."""
    return [p for p in pesquisas_publicadas() if p["protocolo"] == protocolo]


def institutos_publicados() -> list[dict]:
    vistos: dict[str, str] = {}
    for p in pesquisas_publicadas():
        vistos.setdefault(p["instituto_chave"], p["instituto"])
    return sorted(({"chave": k, "nome": v} for k, v in vistos.items()), key=lambda i: i["nome"].lower())


# --------------------------------------------------------------------------- médias
def media(cargo: str, uf: str) -> dict | None:
    """Média das pesquisas registradas: média simples da pesquisa mais recente de cada instituto."""
    uf = uf.upper()

    def calc():
        pubs = pesquisas_publicadas(cargo=cargo, uf=uf)
        if not pubs:
            return None
        recentes: dict[str, dict] = {}
        for p in pubs:  # já ordenadas da mais recente para a mais antiga
            k = p["instituto_chave"]
            chave_tempo = (p["periodo_fim"] or "", p["data_divulgacao"] or "", p["publicada_em"] or "")
            if k not in recentes or chave_tempo > recentes[k][0]:
                recentes[k] = (chave_tempo, p)
        ultimas = [p for _, p in recentes.values()]
        por_tipo = {t: [p for p in ultimas if any(r["tipo"] == t for r in p["resultados"])] for t in TIPO_NOME}
        tipo = max(TIPO_NOME, key=lambda t: (len(por_tipo[t]), t == "totais"))
        usadas = por_tipo[tipo]
        if not usadas:
            return None
        cands = cand_mod.listar(cargo, "BR" if cargo == "presidente" else uf)
        res_usados = [next(r for r in p["resultados"] if r["tipo"] == tipo) for p in usadas]
        linhas = []
        for c in cands:
            vals = [i["valor"] for r in res_usados for i in r["itens"] if i["numero"] == c["numero"]]
            if not vals:
                continue
            linhas.append({
                "numero": c["numero"], "rotulo": c["nome_urna"], "partido": c["partido"],
                "cor": c["cor"], "ordem": c["ordem"], "valor": round(mean(vals), 1),
            })
        if len(linhas) < 2:
            return None
        bn = [r["brancos_nulos"] for r in res_usados if r["brancos_nulos"] is not None]
        ind = [r["indecisos"] for r in res_usados if r["indecisos"] is not None]
        ordenado = sorted(linhas, key=lambda l: -l["valor"])
        vantagem = round(ordenado[0]["valor"] - ordenado[1]["valor"], 1)
        usadas.sort(key=lambda p: (p["data_divulgacao"] or "", p["periodo_fim"] or ""), reverse=True)
        return {
            "cargo": cargo,
            "uf": uf,
            "tipo": tipo,
            "tipo_nome": TIPO_NOME[tipo],
            "itens": linhas,
            "brancos_nulos": round(mean(bn), 1) if bn else None,
            "indecisos": round(mean(ind), 1) if ind else None,
            "n_pesquisas": len(usadas),
            "pesquisas": usadas,
            "lider": ordenado[0] if vantagem > 0 else None,
            "vantagem": vantagem,
            "outras_excluidas": len(ultimas) - len(usadas),
            "atualizado": max(p["publicada_em"] or "" for p in usadas),
        }

    return _memo(("media", cargo, uf), calc)


# --------------------------------------------------------------------------- mapa
def apuracao(cargo: str, uf: str) -> dict | None:
    r = db.q1("SELECT * FROM apuracao WHERE cargo = ? AND uf = ?", (cargo, uf.upper()))
    if not r:
        return None
    d = db.jloads(r["dados"], {})
    cands = {c["numero"]: c for c in cand_mod.listar(cargo, "BR" if cargo == "presidente" else uf)}
    for c in d.get("candidatos", []):
        c["cor"] = cands.get(c["numero"], {}).get("cor", cand_mod.cor_por_ordem(c.get("seq") or 1))
    d["atualizado_tse"] = r["atualizado_tse"]
    return d


def em_apuracao() -> bool:
    return settings.agora() >= settings.INICIO_APURACAO


def ufs_2t_governador() -> list[str]:
    return cand_mod.ufs_com_2_turno_governador()


def mapa(cargo: str) -> dict:
    """Estado de cada UF para o mapa (3D e 2D) e para a tabela abaixo dele."""

    def calc():
        apur = em_apuracao()
        ufs2t = set(ufs_2t_governador())
        estados = []
        for uf, info in UFS.items():
            item = {"uf": uf, "nome": info["nome"], "url": f"/{cargo}/{uf.lower()}",
                    "status": "sem_pesquisas", "cor": cand_mod.cor_sem_dados(), "intensidade": 0.0,
                    "vantagem": 0.0, "lider": None, "lider_cor": None}
            if cargo == "governador" and uf not in ufs2t:
                item["status"] = "sem_2_turno"
                estados.append(item)
                continue
            if apur:
                a = apuracao(cargo, uf)
                if a and a.get("pst"):
                    cs = sorted(a["candidatos"], key=lambda c: -(c["pct"] or 0))
                    if len(cs) >= 2:
                        item.update({"status": "apuracao", "vantagem": round((cs[0]["pct"] or 0) - (cs[1]["pct"] or 0), 1),
                                     "lider": cs[0]["nome"], "lider_cor": cs[0]["cor"], "cor": cs[0]["cor"],
                                     "pst": a["pst"], "pct_lider": cs[0]["pct"]})
                        item["intensidade"] = min(1.0, 0.25 + item["vantagem"] / 20)
                    estados.append(item)
                    continue
            m = media(cargo, uf)
            if m:
                frente = max(m["itens"], key=lambda i: i["valor"])
                item.update({"status": "com_pesquisas", "vantagem": m["vantagem"], "n": m["n_pesquisas"],
                             "tipo": m["tipo"], "pct_lider": frente["valor"]})
                if m["lider"]:
                    item.update({"lider": m["lider"]["rotulo"], "lider_cor": m["lider"]["cor"], "cor": m["lider"]["cor"]})
                    item["intensidade"] = min(1.0, 0.25 + m["vantagem"] / 20)
                else:
                    item["status"] = "empate"
            estados.append(item)
        return {"cargo": cargo, "apuracao": apur, "estados": estados}

    return _memo(("mapa", cargo, em_apuracao()), calc)


def atualizado_em(cargo: str | None = None, uf: str | None = None):
    """Data/hora da última alteração de dados relevante para a página."""
    if cargo and uf:
        v = db.get_meta(f"atualizado:{cargo}:{uf.upper()}")
        if v:
            return v
    return db.get_meta("dados_atualizados_em") or db.get_meta("tse_coletado_em")


def contagens() -> dict:
    def calc():
        r = db.q("SELECT status, COUNT(*) n FROM pesquisas GROUP BY status")
        return {x["status"]: x["n"] for x in r}

    return _memo(("contagens",), calc)


def data_iso(d) -> str:
    x = parse_data(d) if isinstance(d, str) else d
    return x.isoformat() if x else ""
