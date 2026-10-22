"""Comandos de manutenção.

    python manage.py init            cria/atualiza o banco
    python manage.py pipeline        roda UMA rodada completa do pipeline agora
    python manage.py servir          sobe o site (visitas disparam a atualização)
    python manage.py anuncios        confere os anúncios do config/anuncios.json
    python manage.py demo            sobe uma DEMONSTRAÇÃO com dados FICTÍCIOS (banco separado, noindex)
"""
from __future__ import annotations

import os
import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ajuda"

    if cmd == "demo":
        os.environ["DEMO"] = "1"
        os.environ["AUTO_ATUALIZAR"] = "0"
        from demo_dados import popular

        popular()
        from app import app

        print("\nDEMONSTRAÇÃO com dados FICTÍCIOS em http://127.0.0.1:5000  (Ctrl+C para sair)\n")
        app.run(port=int(os.environ.get("PORT", 5000)), debug=False)
        return

    from core import db

    db.init_db()
    if cmd == "init":
        print("Banco pronto em", __import__("settings").DB_PATH)
    elif cmd == "pipeline":
        import time

        from core import gatilho
        from pipeline.run import configurar_log, rodada

        configurar_log()
        # ocupa a mesma reserva usada pelas visitas, para não rodar duas atualizações juntas
        db.set_meta("reserva:pipeline", repr(time.time() + 3600))
        db.set_meta("inicio:pipeline", repr(time.time()))
        try:
            print(rodada())
        finally:
            gatilho.liberar("pipeline")
    elif cmd == "servir":
        from app import app

        app.run(port=int(os.environ.get("PORT", 5000)), debug=False, use_reloader=False)
    elif cmd == "anuncios":
        import json

        import settings
        from core import anuncios

        with open(settings.CONFIG_DIR / "anuncios.json", encoding="utf-8") as f:
            for a in json.load(f).get("anuncios", []):
                motivo = anuncios.verificar(a)
                estado = "inativo" if not a.get("ativo") else ("RECUSADO: " + motivo if motivo else "OK")
                print(f"- [{a.get('espaco')}] {a.get('marca')}: {estado}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
