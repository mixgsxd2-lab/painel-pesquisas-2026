"""Textos neutros gerados a partir dos dados (perguntas frequentes, descrições)."""
from __future__ import annotations

from core.textutil import dec, pct
from core.ufs import no_uf


def _lista(itens: list[str]) -> str:
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def pergunta_lider(cargo: str, uf: str) -> str:
    return f"Quem lidera as pesquisas para {cargo} {no_uf(uf)}?"


def resposta_lider(cargo: str, uf: str, media: dict | None) -> str:
    local = no_uf(uf)
    if not media:
        return (f"Ainda não há pesquisas registradas no TSE para {cargo} {local} no 2º turno que tenham "
                f"passado pelas validações automáticas deste site.")
    partes = [f"{i['rotulo']} ({i['partido']}) tem {pct(i['valor'])}" for i in media["itens"]]
    base = ", ".join(
        f"{p['instituto']} ({p['registro']}, divulgada em {p['data_divulgacao'][8:10]}/{p['data_divulgacao'][5:7]}, "
        f"margem de erro de ±{dec(p['margem_erro'])} pontos)"
        for p in media["pesquisas"]
    )
    if media["lider"]:
        abertura = (f"Na média das pesquisas registradas no TSE publicadas neste site, {media['lider']['rotulo']} "
                    f"aparece à frente, com diferença de {dec(media['vantagem'])} ponto(s): ")
    else:
        abertura = "Na média das pesquisas registradas no TSE publicadas neste site, os candidatos aparecem com a mesma média: "
    return (f"{abertura}{_lista(partes)} ({media['tipo_nome'].lower()}). "
            f"A média usa a pesquisa mais recente de cada instituto: {base}. "
            f"A média não é previsão de resultado.")


def faq(cargo: str, uf: str, media: dict | None, pesquisas: list[dict], sem_2_turno: bool = False) -> list[tuple[str, str]]:
    local = no_uf(uf)
    if sem_2_turno:
        return [
            (f"Há 2º turno para governador {local} em 2026?",
             f"Não consta disputa de 2º turno para governador {local} nos dados oficiais do TSE consultados por "
             f"este site. Por isso, não há pesquisas de 2º turno para governador {local} nesta página."),
            ("Quando é o 2º turno das eleições de 2026?",
             "O 2º turno será no domingo, 25 de outubro de 2026. A votação vai das 8h às 17h, horário de Brasília."),
        ]
    perguntas = [(pergunta_lider(cargo, uf), resposta_lider(cargo, uf, media))]
    n = len(pesquisas)
    insts = sorted({p["instituto"] for p in pesquisas})
    if n:
        perguntas.append((
            f"Quantas pesquisas registradas no TSE existem para {cargo} {local} no 2º turno?",
            f"Este site publica {n} pesquisa(s) registrada(s) no TSE para {cargo} {local} no 2º turno, "
            f"de {len(insts)} instituto(s): {_lista(insts)}. Pesquisas que não passaram nas validações "
            f"automáticas não aparecem.",
        ))
        margens = sorted({p["margem_erro"] for p in pesquisas if p["margem_erro"] is not None})
        confs = sorted({p["nivel_confianca"] for p in pesquisas if p["nivel_confianca"] is not None})
        if margens:
            faixa = (f"±{dec(margens[0])} ponto(s)" if len(margens) == 1 else
                     f"de ±{dec(margens[0])} a ±{dec(margens[-1])} pontos")
            conf_txt = _lista([f"{dec(c)}%" for c in confs])
            perguntas.append((
                f"Qual é a margem de erro das pesquisas para {cargo} {local}?",
                f"A margem de erro informada no registro das pesquisas publicadas aqui vai {faixa}, "
                f"com nível de confiança de {conf_txt}. Cada pesquisa tem a sua própria margem, exibida no card.",
            ))
    perguntas.append((
        "Quando é o 2º turno das eleições de 2026?",
        "O 2º turno será no domingo, 25 de outubro de 2026. A votação vai das 8h às 17h, horário de Brasília.",
    ))
    perguntas.append((
        "A média das pesquisas é uma previsão do resultado?",
        "Não. A média das pesquisas registradas é um cálculo simples — a média aritmética da pesquisa mais "
        "recente de cada instituto — e não é previsão de resultado. Este site não realiza pesquisas próprias.",
    ))
    return perguntas
