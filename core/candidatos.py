"""Candidatos do 2º turno: leitura do banco + cores e ajustes do config/candidatos.json."""
from __future__ import annotations

import json
from functools import lru_cache

import settings
from core import fotos
from core import db
from core.textutil import normalizar


@lru_cache(maxsize=1)
def _config_cache(mtime: float) -> dict:
    with open(settings.CONFIG_DIR / "candidatos.json", encoding="utf-8") as f:
        return json.load(f)


def config() -> dict:
    p = settings.CONFIG_DIR / "candidatos.json"
    return _config_cache(p.stat().st_mtime)


def cor_por_ordem(ordem: int) -> str:
    paleta = config().get("paleta_por_ordem_na_urna") or ["#E5484D", "#3B82F6"]
    return paleta[(max(ordem, 1) - 1) % len(paleta)]


def cor_sem_dados() -> str:
    return config().get("cor_sem_dados", "#8A93A6")


def paleta() -> list[str]:
    return list(config().get("paleta_por_ordem_na_urna") or [])


def listar(cargo: str, uf: str) -> list[dict]:
    """Candidatos do 2º turno para cargo/UF ('BR' para presidente), na ordem da urna."""
    uf = uf.upper()
    chave = f"{cargo}/{uf}"
    manual = (config().get("manual") or {}).get(chave)
    if manual:
        cands = [
            {
                "numero": str(c["numero"]),
                "nome_urna": c.get("nome_urna") or c.get("nome"),
                "nome_completo": c.get("nome_completo") or c.get("nome_urna") or c.get("nome"),
                "partido": c.get("partido", ""),
                "ordem": i + 1,
            }
            for i, c in enumerate(manual)
        ]
    else:
        linhas = db.q(
            "SELECT numero, nome_urna, nome_completo, partido, ordem FROM candidatos "
            "WHERE cargo = ? AND uf = ? ORDER BY ordem, numero",
            (cargo, uf),
        )
        cands = [dict(r) for r in linhas]
        if config().get("ordem") == "numero":
            cands.sort(key=lambda c: int(c["numero"]) if c["numero"].isdigit() else 999)
            for i, c in enumerate(cands):
                c["ordem"] = i + 1
    for c in cands:
        c["cor"] = cor_por_ordem(c["ordem"])
        c["apelidos"] = apelidos(cargo, uf, c)
        c["foto"] = fotos.url(cargo, uf, c["numero"])
    return cands


def ufs_com_2_turno_governador() -> list[str]:
    linhas = db.q("SELECT DISTINCT uf FROM candidatos WHERE cargo = 'governador' ORDER BY uf")
    ufs = {r["uf"] for r in linhas}
    for chave in (config().get("manual") or {}):
        cargo, _, uf = chave.partition("/")
        if cargo == "governador":
            ufs.add(uf.upper())
    return sorted(ufs)


_PALAVRAS_GENERICAS = {
    "professor", "professora", "doutor", "doutora", "dr", "dra", "pastor", "delegado",
    "delegada", "coronel", "capitao", "general", "sargento", "irma", "irmao", "junior",
    "filho", "neto", "da", "de", "do", "dos", "das", "e",
    # primeiros nomes e palavras muito comuns
    "maria", "jose", "joao", "ana", "paulo", "pedro", "carlos", "luiz", "luis", "antonio", "francisco",
    "leao", "rosa", "flor", "branco", "santo", "santa",
}
_SOBRENOMES_COMUNS = {
    "silva", "santos", "souza", "sousa", "oliveira", "pereira", "lima", "ferreira", "costa", "rodrigues",
    "almeida", "nascimento", "gomes", "martins", "araujo", "melo", "barbosa", "ribeiro", "alves", "carvalho",
    "rocha", "dias", "teixeira", "moreira", "cardoso", "soares", "vieira", "monteiro", "mendes", "freitas",
}


def apelidos(cargo: str, uf: str, cand: dict) -> list[str]:
    """Formas normalizadas do nome para localizar o candidato no texto das fontes."""
    # Só o nome de urna (é o que a imprensa usa). Sobrenomes civis comuns geram falsos positivos.
    nomes = set()
    urna = normalizar(cand.get("nome_urna") or "")
    if urna:
        nomes.add(urna)
        toks = [t for t in urna.split()
                if t not in _PALAVRAS_GENERICAS and t not in _SOBRENOMES_COMUNS and len(t) >= 4]
        if toks:
            nomes.add(toks[-1])
            if len(toks) > 1:
                nomes.add(toks[0])
    extra = (config().get("apelidos") or {}).get(f"{cargo}/{uf}/{cand['numero']}") or []
    nomes.update(normalizar(a) for a in extra)
    return sorted(nomes, key=len, reverse=True)


def _tokens_de_outras_disputas(cands: list[dict]) -> set[str]:
    """Palavras dos nomes de candidatos de OUTRAS disputas (ex.: 'lula' numa página sobre
    governador do RN não pode ser lido como o candidato 'Cadu de Lula')."""
    meus = {normalizar(c.get("nome_urna") or "") for c in cands}
    toks: set[str] = set()
    for r in db.q("SELECT DISTINCT nome_urna FROM candidatos"):
        n = normalizar(r["nome_urna"])
        if n and n not in meus:
            toks.add(n)
            toks.update(t for t in n.split() if len(t) >= 4)
    return toks


def apelidos_exclusivos(cands: list[dict]) -> dict[str, list[str]]:
    """Remove apelidos ambíguos (que casariam com mais de um candidato)."""
    out: dict[str, list[str]] = {}
    externos = _tokens_de_outras_disputas(cands)
    for c in cands:
        outros = [o for o in cands if o["numero"] != c["numero"]]
        ok = []
        for a in c["apelidos"]:
            conflito = any(
                a == b or a in b.split() or b in a.split() or (" " in a and a in b)
                for o in outros
                for b in o["apelidos"]
            )
            if " " not in a and a in externos:
                conflito = True
            if not conflito:
                ok.append(a)
        # o nome de urna completo nunca é descartado, a menos que seja idêntico a outro
        urna = normalizar(c.get("nome_urna") or "")
        if urna and urna not in ok and not any(urna == normalizar(o.get("nome_urna") or "") for o in outros):
            ok.insert(0, urna)
        out[c["numero"]] = ok
    return out
