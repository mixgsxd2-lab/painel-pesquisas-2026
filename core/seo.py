"""Metadados de SEO e dados estruturados (Schema.org)."""
from __future__ import annotations

import settings
from core.textutil import parse_datahora


def abs_url(caminho: str) -> str:
    return settings.SITE_URL + caminho


def iso(v) -> str:
    dt = parse_datahora(v) if isinstance(v, str) else v
    return dt.isoformat(timespec="seconds") if dt else ""


def breadcrumbs_ld(itens: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": nome, "item": abs_url(caminho)}
            for i, (nome, caminho) in enumerate(itens)
        ],
    }


def website_ld() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": settings.SITE_NOME,
        "url": abs_url("/"),
        "inLanguage": "pt-BR",
        "description": "Apuração do 2º turno de 2026 com os resultados oficiais do TSE "
                       "(presidente e governadores).",
    }


def dataset_ld(nome: str, descricao: str, caminho: str, modificado, cobertura: str, n: int) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": nome,
        "description": descricao,
        "url": abs_url(caminho),
        "inLanguage": "pt-BR",
        "isAccessibleForFree": True,
        "keywords": ["pesquisa eleitoral", "2º turno", "eleições 2026", "TSE", cobertura],
        "creator": {"@type": "Organization", "name": settings.SITE_NOME, "url": abs_url("/")},
        "isBasedOn": "https://dadosabertos.tse.jus.br/dataset/pesquisas-eleitorais-2026",
        "spatialCoverage": {"@type": "Place", "name": cobertura},
        "temporalCoverage": "2026-10-05/2026-10-25",
        "dateModified": iso(modificado) or None,
        "variableMeasured": "Intenção de voto (%) por candidato, brancos/nulos e indecisos",
        "size": f"{n} pesquisa(s)",
    }


def faq_ld(perguntas: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": p, "acceptedAnswer": {"@type": "Answer", "text": r}}
            for p, r in perguntas
        ],
    }


def webpage_ld(titulo: str, caminho: str, modificado) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": titulo,
        "url": abs_url(caminho),
        "inLanguage": "pt-BR",
        "dateModified": iso(modificado) or None,
        "isPartOf": {"@type": "WebSite", "name": settings.SITE_NOME, "url": abs_url("/")},
    }
