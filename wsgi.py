"""Ponto de entrada de produção (gunicorn wsgi:app).

Não há agendador: as visitas disparam a atualização (veja core/gatilho.py).
"""
from app import app  # noqa: F401
