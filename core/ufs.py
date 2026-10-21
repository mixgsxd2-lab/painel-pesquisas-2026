"""Unidades da Federação: siglas, nomes, códigos IBGE e vizinhança."""
from __future__ import annotations

UFS: dict[str, dict] = {
    "AC": {"nome": "Acre", "prep": "no", "ibge": "12"},
    "AL": {"nome": "Alagoas", "prep": "em", "ibge": "27"},
    "AP": {"nome": "Amapá", "prep": "no", "ibge": "16"},
    "AM": {"nome": "Amazonas", "prep": "no", "ibge": "13"},
    "BA": {"nome": "Bahia", "prep": "na", "ibge": "29"},
    "CE": {"nome": "Ceará", "prep": "no", "ibge": "23"},
    "DF": {"nome": "Distrito Federal", "prep": "no", "ibge": "53"},
    "ES": {"nome": "Espírito Santo", "prep": "no", "ibge": "32"},
    "GO": {"nome": "Goiás", "prep": "em", "ibge": "52"},
    "MA": {"nome": "Maranhão", "prep": "no", "ibge": "21"},
    "MT": {"nome": "Mato Grosso", "prep": "em", "ibge": "51"},
    "MS": {"nome": "Mato Grosso do Sul", "prep": "em", "ibge": "50"},
    "MG": {"nome": "Minas Gerais", "prep": "em", "ibge": "31"},
    "PA": {"nome": "Pará", "prep": "no", "ibge": "15"},
    "PB": {"nome": "Paraíba", "prep": "na", "ibge": "25"},
    "PR": {"nome": "Paraná", "prep": "no", "ibge": "41"},
    "PE": {"nome": "Pernambuco", "prep": "em", "ibge": "26"},
    "PI": {"nome": "Piauí", "prep": "no", "ibge": "22"},
    "RJ": {"nome": "Rio de Janeiro", "prep": "no", "ibge": "33"},
    "RN": {"nome": "Rio Grande do Norte", "prep": "no", "ibge": "24"},
    "RS": {"nome": "Rio Grande do Sul", "prep": "no", "ibge": "43"},
    "RO": {"nome": "Rondônia", "prep": "em", "ibge": "11"},
    "RR": {"nome": "Roraima", "prep": "em", "ibge": "14"},
    "SC": {"nome": "Santa Catarina", "prep": "em", "ibge": "42"},
    "SP": {"nome": "São Paulo", "prep": "em", "ibge": "35"},
    "SE": {"nome": "Sergipe", "prep": "em", "ibge": "28"},
    "TO": {"nome": "Tocantins", "prep": "no", "ibge": "17"},
}

IBGE_PARA_UF = {v["ibge"]: k for k, v in UFS.items()}

VIZINHOS: dict[str, list[str]] = {
    "AC": ["AM", "RO"],
    "AL": ["PE", "SE", "BA"],
    "AP": ["PA"],
    "AM": ["AC", "RO", "MT", "PA", "RR"],
    "BA": ["SE", "AL", "PE", "PI", "TO", "GO", "MG", "ES"],
    "CE": ["RN", "PB", "PE", "PI"],
    "DF": ["GO", "MG"],
    "ES": ["BA", "MG", "RJ"],
    "GO": ["DF", "MG", "BA", "TO", "MT", "MS"],
    "MA": ["PI", "TO", "PA"],
    "MT": ["RO", "AM", "PA", "TO", "GO", "MS"],
    "MS": ["MT", "GO", "MG", "SP", "PR"],
    "MG": ["SP", "RJ", "ES", "BA", "GO", "DF", "MS"],
    "PA": ["AP", "RR", "AM", "MT", "TO", "MA"],
    "PB": ["RN", "CE", "PE"],
    "PR": ["SP", "MS", "SC"],
    "PE": ["PB", "CE", "PI", "BA", "AL"],
    "PI": ["MA", "CE", "PE", "BA", "TO"],
    "RJ": ["ES", "MG", "SP"],
    "RN": ["CE", "PB"],
    "RS": ["SC"],
    "RO": ["AC", "AM", "MT"],
    "RR": ["AM", "PA"],
    "SC": ["PR", "RS"],
    "SP": ["MG", "RJ", "PR", "MS"],
    "SE": ["AL", "BA"],
    "TO": ["MA", "PI", "BA", "GO", "MT", "PA"],
}

CARGOS = {
    "presidente": {"nome": "Presidente", "codigo_tse": 1},
    "governador": {"nome": "Governador", "codigo_tse": 3},
}


def nome_uf(uf: str) -> str:
    uf = (uf or "").upper()
    if uf == "BR":
        return "Brasil"
    return UFS.get(uf, {}).get("nome", uf)


def no_uf(uf: str) -> str:
    """'no Rio Grande do Norte', 'em São Paulo', 'na Bahia'."""
    uf = (uf or "").upper()
    if uf == "BR":
        return "no Brasil"
    info = UFS.get(uf)
    if not info:
        return f"em {uf}"
    return f"{info['prep']} {info['nome']}"


def uf_valida(uf: str) -> bool:
    return (uf or "").upper() in UFS
