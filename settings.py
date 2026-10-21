"""Configurações do Painel das Pesquisas 2026 (lidas de variáveis de ambiente / .env)."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:  # .env opcional em desenvolvimento
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except Exception:  # pragma: no cover
    pass


def _env(nome: str, padrao: str = "") -> str:
    return os.environ.get(nome, padrao).strip()


def _env_bool(nome: str, padrao: bool = False) -> bool:
    v = os.environ.get(nome)
    if v is None:
        return padrao
    return v.strip().lower() in {"1", "true", "sim", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(_env("DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "logs").mkdir(exist_ok=True)
(DATA_DIR / "og").mkdir(exist_ok=True)
(DATA_DIR / "geo").mkdir(exist_ok=True)
(DATA_DIR / "fonts").mkdir(exist_ok=True)

DEMO = _env_bool("DEMO", False)
DB_PATH = Path(_env("DB_PATH", str(DATA_DIR / ("demo.db" if DEMO else "painel.db"))))

TZ = ZoneInfo("America/Sao_Paulo")

# --- Site -------------------------------------------------------------------
SITE_NOME = "Painel das Pesquisas 2026"
SITE_URL = _env("SITE_URL", "http://localhost:5000").rstrip("/")
SECRET_KEY = _env("SECRET_KEY", "troque-esta-chave-em-producao")
EMAIL_CONTATO = _env("EMAIL_CONTATO", "correcoes@exemplo.com.br")
EMAIL_DONO = _env("EMAIL_DONO", EMAIL_CONTATO)
ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "")  # vazio = /admin desativado
GOOGLE_SITE_VERIFICATION = _env("GOOGLE_SITE_VERIFICATION", "")
BING_SITE_VERIFICATION = _env("BING_SITE_VERIFICATION", "")

# --- E-mail (SMTP) ----------------------------------------------------------
SMTP_HOST = _env("SMTP_HOST", "")
SMTP_PORT = int(_env("SMTP_PORT", "587") or 587)
SMTP_USER = _env("SMTP_USER", "")
SMTP_PASS = _env("SMTP_PASS", "")
SMTP_FROM = _env("SMTP_FROM", SMTP_USER or "nao-responda@localhost")
SMTP_TLS = _env_bool("SMTP_TLS", True)

# --- Eleição ----------------------------------------------------------------
ANO = 2026
DATA_1_TURNO = date(2026, 10, 4)
DATA_2_TURNO = date(2026, 10, 25)
# Abertura da apuração (fechamento das urnas): 25/10/2026 às 17h de Brasília
INICIO_APURACAO = datetime.fromisoformat(
    _env("INICIO_APURACAO", "2026-10-25T17:00:00")
).replace(tzinfo=TZ)

# --- Fontes oficiais ----------------------------------------------------------
TSE_CKAN_URL = "https://dadosabertos.tse.jus.br/api/3/action/package_show?id=pesquisas-eleitorais-{ano}"
TSE_PESQUISAS_ZIP = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_{ano}.zip"
TSE_CONTRATANTE_ZIP = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_contratante_{ano}.zip"
TSE_PAGANTE_ZIP = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_pagante_{ano}.zip"
TSE_RESULTADOS_BASE = "https://resultados.tse.jus.br/oficial"
TSE_RESULTADOS_CONFIG = TSE_RESULTADOS_BASE + "/comum/config/ele-c.json"
# Códigos das eleições (descobertos automaticamente em ele-c.json; estes são o fallback)
TSE_COD_FEDERAL_1T = _env("TSE_COD_FEDERAL_1T", "6257")
TSE_COD_FEDERAL_2T = _env("TSE_COD_FEDERAL_2T", "6258")
TSE_COD_ESTADUAL_1T = _env("TSE_COD_ESTADUAL_1T", "6259")
TSE_COD_ESTADUAL_2T = _env("TSE_COD_ESTADUAL_2T", "6260")
PESQELE_URL = _env(
    "PESQELE_URL", "https://pesqele-divulgacao.tse.jus.br/app/pesquisa/listar.xhtml"
)
IBGE_MALHA_URL = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo%2Bjson&qualidade=minima&intrarregiao=UF"
)

# --- Busca na web -------------------------------------------------------------
BRAVE_API_KEY = _env("BRAVE_API_KEY")
SERPAPI_KEY = _env("SERPAPI_KEY")
GOOGLE_CSE_KEY = _env("GOOGLE_CSE_KEY")
GOOGLE_CSE_CX = _env("GOOGLE_CSE_CX")
BUSCA_DUCKDUCKGO = _env_bool("BUSCA_DUCKDUCKGO", True)  # fallback gratuito, sem chave
MAX_PESQUISAS_POR_RODADA = int(_env("MAX_PESQUISAS_POR_RODADA", "40"))
MAX_URLS_POR_PESQUISA = int(_env("MAX_URLS_POR_PESQUISA", "8"))
USER_AGENT = f"PainelPesquisas2026Bot/1.0 (+{SITE_URL}/metodologia)"

# --- Validação ----------------------------------------------------------------
TOLERANCIA_PONTOS = 0.5
SOMA_MIN, SOMA_MAX = 85.0, 101.0
DIAS_MIN_REGISTRO_DIVULGACAO = 5
MIN_FONTES_INDEPENDENTES = 2

# --- Agendador ------------------------------------------------------------------
RUN_SCHEDULER = _env_bool("RUN_SCHEDULER", True)
INTERVALO_PIPELINE_MIN = int(_env("INTERVALO_PIPELINE_MIN", "60"))
INTERVALO_APURACAO_MIN = int(_env("INTERVALO_APURACAO_MIN", "2"))


def agora() -> datetime:
    """Agora, no fuso de Brasília."""
    return datetime.now(TZ)
