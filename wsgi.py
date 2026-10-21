"""Ponto de entrada de produção (gunicorn wsgi:app). Liga o agendador junto com o site."""
from app import app  # noqa: F401
import scheduler

scheduler.iniciar()
