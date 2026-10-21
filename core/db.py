"""SQLite: conexão, esquema e helpers.

As tabelas `historico` e `log_validacao` são somente-inserção: triggers no próprio
banco abortam qualquer UPDATE ou DELETE, e a interface não oferece exclusão.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterable

import settings

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

-- Candidatos do 2º turno (derivados automaticamente dos resultados do 1º turno no TSE)
CREATE TABLE IF NOT EXISTS candidatos (
    cargo TEXT NOT NULL,            -- presidente | governador
    uf TEXT NOT NULL,               -- BR ou sigla da UF
    numero TEXT NOT NULL,
    nome_urna TEXT NOT NULL,
    nome_completo TEXT,
    partido TEXT,
    ordem INTEGER NOT NULL,         -- ordem na urna (1, 2)
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (cargo, uf, numero)
);

-- Pesquisas registradas no TSE (uma linha por registro + cargo)
CREATE TABLE IF NOT EXISTS pesquisas (
    protocolo TEXT NOT NULL,        -- BR034362026
    cargo TEXT NOT NULL,            -- presidente | governador
    registro TEXT NOT NULL,         -- BR-03436/2026
    uf_registro TEXT NOT NULL,      -- UF em que foi registrada (BR para presidente)
    abrangencia TEXT,               -- BR (nacional) ou sigla da UF; NULL = não identificada
    instituto TEXT NOT NULL,
    instituto_razao TEXT,
    instituto_chave TEXT NOT NULL,
    cnpj TEXT,
    contratantes TEXT,              -- JSON [{nome, valor}]
    pagantes TEXT,                  -- JSON [{nome, origem}]
    pesquisa_propria INTEGER,
    valor REAL,
    estatistico TEXT,
    periodo_inicio TEXT,
    periodo_fim TEXT,
    entrevistados INTEGER,
    margem_erro REAL,
    nivel_confianca REAL,
    data_registro TEXT,
    data_divulgacao TEXT,
    metodologia TEXT,
    plano_amostral TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE',
        -- PENDENTE | AGUARDANDO_DIVULGACAO | PUBLICADA | DESCARTADA | SEM_REGISTRO
    motivo TEXT,
    tentativas INTEGER NOT NULL DEFAULT 0,
    ultima_tentativa TEXT,
    publicada_em TEXT,
    coletada_em TEXT NOT NULL,
    atualizada_em TEXT NOT NULL,
    PRIMARY KEY (protocolo, cargo)
);
CREATE INDEX IF NOT EXISTS ix_pesq_status ON pesquisas(status, cargo, abrangencia);

-- Fontes encontradas na web para cada pesquisa (reconstruídas a cada tentativa)
CREATE TABLE IF NOT EXISTS fontes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocolo TEXT NOT NULL,
    cargo TEXT NOT NULL,
    url TEXT NOT NULL,
    dominio TEXT NOT NULL,
    oficial INTEGER NOT NULL DEFAULT 0,
    titulo TEXT,
    registro_encontrado INTEGER NOT NULL DEFAULT 0,
    contexto_ok TEXT,               -- JSON {cargo, uf, turno}
    extracao TEXT,                  -- JSON: lista de blocos extraídos
    margem_erro REAL,
    nivel_confianca REAL,
    obtida_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fontes_pesq ON fontes(protocolo, cargo);

-- Resultados publicados (um por pesquisa + cargo + tipo)
CREATE TABLE IF NOT EXISTS resultados (
    protocolo TEXT NOT NULL,
    cargo TEXT NOT NULL,
    tipo TEXT NOT NULL,             -- totais | validos
    dados TEXT NOT NULL,            -- JSON {candidatos:{numero: pct}, brancos_nulos, indecisos}
    fontes TEXT NOT NULL,           -- JSON [url, ...]
    publicado_em TEXT NOT NULL,
    PRIMARY KEY (protocolo, cargo, tipo)
);

-- Histórico permanente: cada número publicado, com data, hora e fonte
CREATE TABLE IF NOT EXISTS historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    registrado_em TEXT NOT NULL,
    evento TEXT NOT NULL,           -- PUBLICACAO | APURACAO
    protocolo TEXT,
    cargo TEXT NOT NULL,
    uf TEXT,
    tipo TEXT,
    chave TEXT NOT NULL,            -- número do candidato, brancos_nulos, indecisos
    rotulo TEXT,
    valor REAL,
    fontes TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS historico_sem_update BEFORE UPDATE ON historico
BEGIN SELECT RAISE(ABORT, 'historico e somente-insercao'); END;
CREATE TRIGGER IF NOT EXISTS historico_sem_delete BEFORE DELETE ON historico
BEGIN SELECT RAISE(ABORT, 'historico e somente-insercao'); END;

-- Log de validação (motivos de descarte, publicações etc.) — também somente-inserção
CREATE TABLE IF NOT EXISTS log_validacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    em TEXT NOT NULL,
    protocolo TEXT,
    cargo TEXT,
    status TEXT NOT NULL,
    motivo TEXT,
    detalhes TEXT
);
CREATE TRIGGER IF NOT EXISTS log_sem_update BEFORE UPDATE ON log_validacao
BEGIN SELECT RAISE(ABORT, 'log e somente-insercao'); END;
CREATE TRIGGER IF NOT EXISTS log_sem_delete BEFORE DELETE ON log_validacao
BEGIN SELECT RAISE(ABORT, 'log e somente-insercao'); END;

-- Apuração oficial (TSE)
CREATE TABLE IF NOT EXISTS apuracao (
    cargo TEXT NOT NULL,
    uf TEXT NOT NULL,
    dados TEXT NOT NULL,            -- JSON {candidatos:[{numero,nome,partido,pct,votos,eleito}], pst, ...}
    pst REAL,
    atualizado_tse TEXT,
    obtido_em TEXT NOT NULL,
    PRIMARY KEY (cargo, uf)
);

-- Cache de páginas baixadas
CREATE TABLE IF NOT EXISTS paginas_cache (
    url TEXT PRIMARY KEY,
    baixada_em TEXT NOT NULL,
    status INTEGER,
    titulo TEXT,
    texto TEXT
);

-- Formulários
CREATE TABLE IF NOT EXISTS contatos_anuncio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    nome TEXT NOT NULL,
    empresa TEXT,
    email TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    origem_hash TEXT
);
CREATE TABLE IF NOT EXISTS correcoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    protocolo TEXT,
    nome TEXT,
    email TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    origem_hash TEXT
);

-- Audiência (sem IP: só hash diário salgado)
CREATE TABLE IF NOT EXISTS audiencia_dia (
    dia TEXT PRIMARY KEY,
    visitantes INTEGER NOT NULL DEFAULT 0,
    paginas INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audiencia_vistos (
    dia TEXT NOT NULL,
    hash TEXT NOT NULL,
    PRIMARY KEY (dia, hash)
);
CREATE TABLE IF NOT EXISTS presenca (
    sid TEXT PRIMARY KEY,
    ultimo REAL NOT NULL
);
"""


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def conn() -> sqlite3.Connection:
    """Conexão por thread (reaproveitada)."""
    c = getattr(_local, "conn", None)
    if c is None:
        c = conectar()
        _local.conn = c
    return c


def init_db() -> None:
    c = conectar()
    c.executescript(SCHEMA)
    c.commit()
    c.close()


@contextmanager
def transacao():
    c = conn()
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise


def q(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return conn().execute(sql, tuple(params)).fetchall()


def q1(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return conn().execute(sql, tuple(params)).fetchone()


def executar(sql: str, params: Iterable[Any] = ()) -> int:
    c = conn()
    cur = c.execute(sql, tuple(params))
    c.commit()
    return cur.lastrowid


def get_meta(chave: str, padrao: str | None = None) -> str | None:
    r = q1("SELECT valor FROM meta WHERE chave = ?", (chave,))
    return r["valor"] if r else padrao


def set_meta(chave: str, valor: Any, c: sqlite3.Connection | None = None) -> None:
    alvo = c or conn()
    alvo.execute(
        "INSERT INTO meta(chave, valor) VALUES(?, ?) "
        "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)),
    )
    if c is None:
        alvo.commit()


def jloads(s: str | None, padrao=None):
    if not s:
        return padrao
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return padrao


def jdumps(o) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))
