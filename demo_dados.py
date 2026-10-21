"""Popula o banco de DEMONSTRAÇÃO (data/demo.db) com dados 100% FICTÍCIOS.

Serve só para ver o visual localmente: o modo DEMO mostra uma faixa de aviso em todas as
páginas, bloqueia indexação (noindex + robots.txt) e desliga o pipeline. Nunca use em produção.
"""
from __future__ import annotations

import json
import random

import settings

assert settings.DEMO, "demo_dados só pode rodar com DEMO=1"

from core import db  # noqa: E402

CANDS = {
    ("presidente", "BR"): [("10", "CANDIDATA A", "Partido Fictício 1"), ("20", "CANDIDATO B", "Partido Fictício 2")],
}
UFS_GOV = ["AC", "AM", "DF", "ES", "RN", "TO"]
for i, uf in enumerate(UFS_GOV):
    CANDS[("governador", uf)] = [(f"{30 + i}", f"CANDIDATA {uf}-1", "Partido Fictício 3"),
                                 (f"{50 + i}", f"CANDIDATO {uf}-2", "Partido Fictício 4")]

INSTITUTOS = ["Instituto Demonstração Alfa", "Instituto Demonstração Beta", "Instituto Demonstração Gama",
              "Instituto Demonstração Delta"]


def popular() -> None:
    if settings.DB_PATH.exists():
        settings.DB_PATH.unlink()
    for ext in ("-wal", "-shm"):
        p = settings.DB_PATH.with_name(settings.DB_PATH.name + ext)
        if p.exists():
            p.unlink()
    db.init_db()
    rnd = random.Random(2026)
    agora = settings.agora().isoformat()
    c = db.conectar()
    for (cargo, uf), lista in CANDS.items():
        for ordem, (n, nome, partido) in enumerate(lista, 1):
            c.execute("INSERT INTO candidatos VALUES(?,?,?,?,?,?,?,?)", (cargo, uf, n, nome, nome, partido, ordem, agora))

    seq = 90000
    alvos = [("presidente", "BR")] * 5 + [("presidente", uf) for uf in ("RN", "SP", "MG", "BA", "PR", "RS", "PE")]
    alvos += [("governador", uf) for uf in ("AM", "DF", "ES", "RN", "TO") for _ in range(2)]
    for k, (cargo, ab) in enumerate(alvos):
        seq += 1
        uf_reg = "BR" if cargo == "presidente" else ab
        protocolo = f"{uf_reg}{seq:05d}2026"
        inst = INSTITUTOS[k % len(INSTITUTOS)]
        dia_fim = 10 + (k % 9)
        a = round(rnd.uniform(40, 51), 1)
        b = round(rnd.uniform(36, 49), 1)
        bn = round(rnd.uniform(3, 7), 1)
        ind = round(max(0.0, 100 - a - b - bn), 1)
        c.execute(
            "INSERT INTO pesquisas(protocolo, cargo, registro, uf_registro, abrangencia, instituto, instituto_razao, "
            "instituto_chave, cnpj, contratantes, pagantes, pesquisa_propria, valor, estatistico, periodo_inicio, periodo_fim, "
            "entrevistados, margem_erro, nivel_confianca, data_registro, data_divulgacao, status, coletada_em, atualizada_em, publicada_em) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (protocolo, cargo, f"{uf_reg}-{seq:05d}/2026", uf_reg, ab, inst, inst.upper() + " LTDA", f"demo{k % 4}", "",
             json.dumps([{"nome": "Empresa de Mídia Fictícia S/A", "valor": 30000.0}]),
             json.dumps([{"nome": "Empresa de Mídia Fictícia S/A", "origem": "Recursos próprios"}]),
             0, 30000.0, "Estatística Fictícia", f"2026-10-{dia_fim - 3:02d}", f"2026-10-{dia_fim:02d}",
             rnd.choice([1200, 1500, 2000, 2400]), rnd.choice([2.0, 2.2, 2.5, 3.0]), 95.0,
             f"2026-10-{dia_fim - 5:02d} 10:00:00", f"2026-10-{dia_fim + 1:02d}", "PUBLICADA", agora, agora, agora),
        )
        uf_c = "BR" if cargo == "presidente" else ab
        n1, n2 = CANDS[(cargo, uf_c)][0][0], CANDS[(cargo, uf_c)][1][0]
        fontes = ["https://exemplo.invalid/fonte-1", "https://exemplo.invalid/fonte-2"]
        c.execute("INSERT INTO resultados VALUES(?,?,?,?,?,?)",
                  (protocolo, cargo, "totais", json.dumps({"candidatos": {n1: a, n2: b}, "brancos_nulos": bn, "indecisos": ind}),
                   json.dumps(fontes), agora))
        va = round(100 * a / (a + b), 1)
        c.execute("INSERT INTO resultados VALUES(?,?,?,?,?,?)",
                  (protocolo, cargo, "validos", json.dumps({"candidatos": {n1: va, n2: round(100 - va, 1)}}),
                   json.dumps(fontes), agora))
        for chave, val in ((n1, a), (n2, b), ("brancos_nulos", bn), ("indecisos", ind)):
            c.execute("INSERT INTO historico(registrado_em, evento, protocolo, cargo, uf, tipo, chave, rotulo, valor, fontes) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)", (agora, "PUBLICACAO", protocolo, cargo, ab, "totais", chave, chave, val, "demo"))
    for chave in ("dados_atualizados_em", "candidatos_atualizados_em", "tse_coletado_em"):
        db.set_meta(chave, agora, c)
    c.commit()
    c.close()

    from pipeline import malha_ibge, og_images, sitemap
    from pipeline.run import configurar_log

    configurar_log()
    malha_ibge.atualizar()
    og_images.gerar_todas()
    sitemap.gerar()
    print(f"Demo populada: {len(alvos)} pesquisas FICTÍCIAS em {settings.DB_PATH}")
