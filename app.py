"""Painel da Apuração 2026 — aplicação Flask (renderização no servidor)."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, jsonify, make_response, redirect, render_template, request, send_file,
                   send_from_directory, session, url_for)

import settings
from core import anuncios, audiencia, dados, db, gatilho, geo, mailer, seo
from core import candidatos as cand_mod
from core.textutil import data_br, data_curta, datahora_br, dec, nome_proprio, num, pct
from core.ufs import CARGOS, UFS, VIZINHOS, no_uf, nome_uf


def criar_app() -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=settings.SECRET_KEY,
        SEND_FILE_MAX_AGE_DEFAULT=60 * 60 * 24 * 365,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.SITE_URL.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        JSON_AS_ASCII=False,
        COMPRESS_ALGORITHM=["br", "gzip"],
        COMPRESS_MIMETYPES=["text/html", "text/css", "text/xml", "application/xml", "application/json",
                            "application/javascript", "text/javascript", "image/svg+xml", "application/geo+json"],
        COMPRESS_MIN_SIZE=500,
    )
    try:
        from flask_compress import Compress

        Compress(app)
    except ImportError:  # pragma: no cover
        pass

    db.init_db()
    try:  # banco vazio (ex.: reinício no plano gratuito): carrega as pesquisas já validadas
        from pipeline import semente

        semente.importar_se_vazio()
    except Exception:
        app.logger.exception("semente")

    # ------------------------------------------------------------------ filtros/contexto
    app.jinja_env.filters.update(pct=pct, data_br=data_br, data_curta=data_curta, datahora_br=datahora_br,
                                 num=num, dec=dec, nome_uf=nome_uf, no_uf=no_uf,
                                 nome_proprio=nome_proprio)

    _critico = {"css": None, "mtime": 0}

    def css_critico() -> str:
        p = Path(app.static_folder) / "css" / "critical.css"
        m = p.stat().st_mtime if p.exists() else 0
        if m != _critico["mtime"]:
            _critico["css"] = p.read_text(encoding="utf-8") if p.exists() else ""
            _critico["mtime"] = m
        return _critico["css"]

    _versoes: dict[str, tuple[float, str]] = {}

    def static_v(caminho: str) -> str:
        p = Path(app.static_folder) / caminho
        m = p.stat().st_mtime if p.exists() else 0
        if caminho not in _versoes or _versoes[caminho][0] != m:
            _versoes[caminho] = (m, hashlib.md5(f"{caminho}{m}".encode()).hexdigest()[:8])
        return url_for("static", filename=caminho, v=_versoes[caminho][1])

    def csrf_token() -> str:
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_urlsafe(24)
        return session["_csrf"]

    def contagem() -> dict:
        resto = max(0, int((settings.INICIO_APURACAO - settings.agora()).total_seconds()))
        return {"d": resto // 86400, "h": resto % 86400 // 3600, "m": resto % 3600 // 60, "s": resto % 60,
                "fim": resto == 0}

    @app.context_processor
    def contexto_global():
        return {
            "SITE_NOME": settings.SITE_NOME,
            "SITE_URL": settings.SITE_URL,
            "EMAIL_CONTATO": settings.EMAIL_CONTATO,
            "PESQELE_URL": settings.PESQELE_URL,
            "DEMO": settings.DEMO,
            "INICIO_APURACAO_ISO": settings.INICIO_APURACAO.isoformat(),
            "EM_APURACAO": dados.em_apuracao(),
            "GOOGLE_VERIF": settings.GOOGLE_SITE_VERIFICATION,
            "BING_VERIF": settings.BING_SITE_VERIFICATION,
            "css_critico": css_critico,
            "static_v": static_v,
            "csrf_token": csrf_token,
            "anuncio": anuncios.ativo,
            "UFS": UFS,
            "VIZINHOS": VIZINHOS,
            "media_de": dados.media,
            "mapa_svg": geo.caminhos_svg,
            "mapa_centros": lambda: {uf: e["centro"] for uf, e in geo.projetado().items()},
            "contagem": contagem,
            "atualizado_global": dados.atualizado_em,
            "atualizando": gatilho.em_andamento,
            "ano_atual": settings.agora().year,
        }

    # ------------------------------------------------------------------ middleware
    @app.before_request
    def disparar_atualizacao():
        # visitas a páginas disparam a atualização em segundo plano (nunca bloqueiam a resposta)
        if request.method == "GET" and not app.testing and not request.path.startswith(
                ("/static", "/api", "/og", "/geo", "/favicon", "/healthz", "/fragmento")):
            try:
                gatilho.ao_visitar()
            except Exception:
                app.logger.exception("gatilho de atualização")

    @app.after_request
    def depois(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        caminho = request.path
        if caminho.startswith("/admin"):
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
            resp.headers["Cache-Control"] = "no-store"
        elif settings.DEMO:
            resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        if (request.method == "GET" and resp.status_code == 200 and resp.mimetype == "text/html"
                and not caminho.startswith(("/admin", "/fragmento", "/api", "/static"))):
            if "Cache-Control" not in resp.headers:
                resp.headers["Cache-Control"] = "public, max-age=60"
            try:
                ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
                audiencia.registrar(ip, request.headers.get("User-Agent", ""))
            except Exception:
                app.logger.exception("audiência")
        return resp

    def exigir_csrf():
        tok = request.form.get("_csrf", "")
        if not tok or not hmac.compare_digest(tok, session.get("_csrf", "")):
            abort(400)

    def origem_hash() -> str:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        return hashlib.sha256(f"{settings.SECRET_KEY}|{ip}".encode()).hexdigest()[:20]

    def limite_excedido(tabela: str, h: str, maximo: int = 5) -> bool:
        desde = (settings.agora() - timedelta(hours=1)).isoformat()
        n = db.q1(f"SELECT COUNT(*) n FROM {tabela} WHERE origem_hash = ? AND criado_em > ?", (h, desde))["n"]
        return n >= maximo

    # ------------------------------------------------------------------ helpers de página
    def montar_seo(titulo, descricao, caminho, *, og="geral", migalhas=None, extras=None, robots=None,
                   modificado=None, tipo_og="website"):
        migalhas = migalhas or [("Início", "/")]
        ld = [seo.breadcrumbs_ld(migalhas)] + (extras or [])
        return {
            "titulo": titulo,
            "descricao": descricao,
            "canonical": seo.abs_url(caminho),
            "og_imagem": seo.abs_url(f"/og/{og}.png"),
            "og_tipo": tipo_og,
            "robots": robots or ("noindex, nofollow" if settings.DEMO else "index, follow, max-image-preview:large"),
            "jsonld": ld,
            "migalhas": migalhas,
            "modificado": modificado,
            "modificado_iso": seo.iso(modificado),
        }

    def resumo_nacional():
        a = dados.apuracao("presidente", "BR") if dados.em_apuracao() else None
        if not a or not a.get("candidatos"):
            return None
        return {"itens": [{"rotulo": c["nome"], "valor": c.get("pct") or 0, "cor": c["cor"], "foto": c.get("foto")}
                          for c in a["candidatos"]], "pst": a.get("pst") or 0}

    def pacote_mapa():
        return {
            "presidente": dados.mapa("presidente"),
            "governador": dados.mapa("governador"),
            "paleta": cand_mod.paleta(),
            "nacional": resumo_nacional(),
            "cor_sem_dados": cand_mod.cor_sem_dados(),
            "geo_url": url_for("malha"),
        }

    def candidatos_nomes(cargo, uf):
        cs = cand_mod.listar(cargo, uf)
        return " x ".join(c["nome_urna"].title() for c in cs)

    # ------------------------------------------------------------------ páginas
    @app.route("/")
    def home():
        mod = dados.atualizado_em()
        s = montar_seo(
            "Apuração 2º turno 2026: presidente e governadores – resultados do TSE",
            "Apuração do 2º turno de 2026 em tempo real com os resultados oficiais do TSE: presidente e "
            "governadores, com mapa por estado.",
            "/", og="home", modificado=mod, extras=[seo.website_ld(), seo.webpage_ld(settings.SITE_NOME, "/", mod)],
        )
        return render_template(
            "home.html", seo=s, mapa=pacote_mapa(), cargo_inicial="presidente",
            apur_br=dados.apuracao("presidente", "BR") if dados.em_apuracao() else None,
            ufs2t=dados.ufs_2t_governador(), cands_br=cand_mod.listar("presidente", "BR"),
        )

    @app.route("/<cargo>")
    def pagina_cargo(cargo):
        if cargo not in CARGOS:
            abort(404)
        mod = dados.atualizado_em()
        nome = CARGOS[cargo]["nome"].lower()
        apurando = dados.em_apuracao()
        titulo = f"Apuração 2º turno {nome} 2026 – resultados do TSE"
        desc = (f"Apuração do 2º turno para {nome} em 2026 com os resultados oficiais do TSE, "
                f"atualizados durante a contagem dos votos.")
        s = montar_seo(titulo, desc, f"/{cargo}", og=cargo, modificado=mod,
                       migalhas=[("Início", "/"), (CARGOS[cargo]["nome"], f"/{cargo}")])
        ufs2t = dados.ufs_2t_governador()
        return render_template(
            "cargo.html", seo=s, cargo=cargo, cargo_nome=nome, mapa=pacote_mapa(), ufs2t=ufs2t,
            apur=dados.apuracao(cargo, "BR") if (apurando and cargo == "presidente") else None,
            apur_uf={uf: dados.apuracao(cargo, uf) for uf in ufs2t} if (apurando and cargo == "governador") else {},
            cands=cand_mod.listar("presidente", "BR") if cargo == "presidente" else [],
        )

    @app.route("/<cargo>/<uf>")
    def pagina_estado(cargo, uf):
        if cargo not in CARGOS:
            abort(404)
        if uf != uf.lower():
            return redirect(f"/{cargo}/{uf.lower()}", 301)
        UF = uf.upper()
        if UF not in UFS:
            abort(404)
        nome = CARGOS[cargo]["nome"].lower()
        sem_2t = cargo == "governador" and UF not in dados.ufs_2t_governador()
        mod = dados.atualizado_em(cargo, UF)
        titulo = f"Apuração 2º turno {nome} {UF} 2026 – resultados do TSE"
        if sem_2t:
            desc = (f"Governador {no_uf(UF)} em 2026: não consta 2º turno nos dados oficiais do TSE. Veja a "
                    f"apuração para presidente {no_uf(UF)}.")
        else:
            desc = f"Apuração do 2º turno para {nome} {no_uf(UF)} com os resultados oficiais do TSE."
        migalhas = [("Início", "/"), (CARGOS[cargo]["nome"], f"/{cargo}"), (nome_uf(UF), f"/{cargo}/{uf}")]
        s = montar_seo(titulo, desc, f"/{cargo}/{uf}", og=f"{cargo}-{uf}", modificado=mod, migalhas=migalhas)
        apur = dados.apuracao(cargo, UF) if dados.em_apuracao() and not sem_2t else None
        return render_template(
            "estado.html", seo=s, cargo=cargo, cargo_nome=nome, uf=UF,
            sem_2_turno=sem_2t, vizinhos=VIZINHOS[UF], mapa=pacote_mapa(), apur=apur,
            ufs2t=dados.ufs_2t_governador(), cands=cand_mod.listar(cargo, "BR" if cargo == "presidente" else UF),
            outro_cargo="governador" if cargo == "presidente" else "presidente",
        )

    # páginas de pesquisas foram retiradas: o site mostra só a apuração
    @app.route("/pesquisas")
    @app.route("/pesquisas/<path:slug>")
    @app.route("/metodologia")
    def pesquisas_retiradas(slug=None):
        return redirect("/", 301)

    @app.route("/contato", methods=["GET", "POST"])
    def contato():
        enviado = erro = None
        prot = None
        if request.method == "POST":
            exigir_csrf()
            if request.form.get("site"):  # honeypot
                enviado = True
            else:
                email = (request.form.get("email") or "").strip()[:200]
                msg = (request.form.get("mensagem") or "").strip()[:5000]
                nome = (request.form.get("nome") or "").strip()[:200]
                h = origem_hash()
                if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(msg) < 10:
                    erro = "Informe um e-mail válido e descreva a correção (mín. 10 caracteres)."
                elif limite_excedido("correcoes", h):
                    erro = "Muitas mensagens enviadas. Tente novamente mais tarde."
                else:
                    db.executar(
                        "INSERT INTO correcoes(criado_em, protocolo, nome, email, mensagem, origem_hash) VALUES(?,?,?,?,?,?)",
                        (settings.agora().isoformat(), prot, nome, email, msg, h),
                    )
                    mailer.enviar_para_dono(
                        f"[Correção] {prot or 'geral'} — {settings.SITE_NOME}",
                        f"Pesquisa: {prot or '-'}\nNome: {nome}\nE-mail: {email}\n\n{msg}", email,
                    )
                    enviado = True
        s = montar_seo(
            f"Contato e correções – {settings.SITE_NOME}",
            f"Encontrou um erro? Peça correções de dados publicados no {settings.SITE_NOME}.",
            "/contato", migalhas=[("Início", "/"), ("Contato e correções", "/contato")],
        )
        return render_template("contato.html", seo=s, enviado=enviado, erro=erro, prot=None, p_ref=None)

    @app.route("/anuncie", methods=["GET", "POST"])
    def anuncie():
        enviado = erro = None
        if request.method == "POST":
            exigir_csrf()
            if request.form.get("site"):
                enviado = True
            else:
                campos = {k: (request.form.get(k) or "").strip()[:4000] for k in ("nome", "empresa", "email", "mensagem")}
                h = origem_hash()
                if not campos["nome"] or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", campos["email"]) or len(campos["mensagem"]) < 10:
                    erro = "Preencha nome, e-mail válido e mensagem."
                elif not request.form.get("declaracao"):
                    erro = "É preciso confirmar que o anúncio não tem conteúdo político ou eleitoral."
                elif limite_excedido("contatos_anuncio", h):
                    erro = "Muitas mensagens enviadas. Tente novamente mais tarde."
                else:
                    db.executar(
                        "INSERT INTO contatos_anuncio(criado_em, nome, empresa, email, mensagem, origem_hash) VALUES(?,?,?,?,?,?)",
                        (settings.agora().isoformat(), campos["nome"], campos["empresa"], campos["email"], campos["mensagem"], h),
                    )
                    mailer.enviar_para_dono(
                        f"[Anuncie] {campos['empresa'] or campos['nome']} — {settings.SITE_NOME}",
                        "Nome: {nome}\nEmpresa: {empresa}\nE-mail: {email}\n\n{mensagem}".format(**campos), campos["email"],
                    )
                    enviado = True
        s = montar_seo(
            f"Anuncie no {settings.SITE_NOME}",
            "Anuncie para o público que acompanha a apuração do 2º turno de 2026. Formatos, audiência ao vivo e contato.",
            "/anuncie", migalhas=[("Início", "/"), ("Anuncie", "/anuncie")],
        )
        return render_template("anuncie.html", seo=s, enviado=enviado, erro=erro, aud=audiencia.numeros(),
                               espacos=anuncios.ESPACOS)

    # ------------------------------------------------------------------ fragmento da gaveta do mapa
    @app.route("/fragmento/<cargo>/<uf>")
    def fragmento(cargo, uf):
        UF = uf.upper()
        if cargo not in CARGOS or not (UF in UFS or (UF == "BR" and cargo == "presidente")):
            abort(404)
        sem_2t = cargo == "governador" and UF not in dados.ufs_2t_governador()
        apur = dados.apuracao(cargo, UF) if dados.em_apuracao() and not sem_2t else None
        resp = make_response(render_template(
            "fragmento_estado.html", cargo=cargo, cargo_nome=CARGOS[cargo]["nome"].lower(), uf=UF,
            sem_2_turno=sem_2t, apur=apur,
            cands=cand_mod.listar(cargo, "BR" if cargo == "presidente" else UF),
        ))
        resp.headers["X-Robots-Tag"] = "noindex"
        resp.headers["Cache-Control"] = "public, max-age=60"
        return resp

    # ------------------------------------------------------------------ APIs
    @app.route("/api/mapa/<cargo>")
    def api_mapa(cargo):
        if cargo not in CARGOS:
            abort(404)
        r = jsonify(dados.mapa(cargo))
        r.headers["Cache-Control"] = "public, max-age=60"
        return r

    @app.route("/api/presenca", methods=["POST"])
    def api_presenca():
        if not audiencia.eh_robo(request.headers.get("User-Agent", "")):
            audiencia.presenca((request.get_json(silent=True) or {}).get("sid", ""))
        return ("", 204)

    @app.route("/api/audiencia")
    def api_audiencia():
        r = jsonify(audiencia.numeros())
        r.headers["Cache-Control"] = "no-store"
        return r

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True, "atualizando": gatilho.em_andamento(),
                        "ultima_rodada": db.jloads(db.get_meta("ultima_rodada"), {}).get("fim")})

    # ------------------------------------------------------------------ arquivos gerados
    @app.route("/geo/br-uf.json")
    def malha():
        if not geo.disponivel():
            abort(404)
        r = send_file(geo.arquivo(), mimetype="application/geo+json", max_age=60 * 60 * 24 * 7)
        return r

    @app.route("/og/<nome>.png")
    def og_imagem(nome):
        if not re.fullmatch(r"[a-z0-9\-]+", nome):
            abort(404)
        caminho = settings.DATA_DIR / "og" / f"{nome}.png"
        if not caminho.exists():
            caminho = settings.DATA_DIR / "og" / "geral.png"
            if not caminho.exists():
                try:
                    from pipeline import og_images
                    og_images.gerar_todas()
                except Exception:
                    abort(404)
                if not caminho.exists():
                    abort(404)
        return send_file(caminho, mimetype="image/png", max_age=60 * 60 * 24)

    @app.route("/sitemap.xml")
    def sitemap():
        from pipeline import sitemap as sm

        if not sm.ARQUIVO.exists():
            sm.gerar()
        r = send_file(sm.ARQUIVO, mimetype="application/xml", max_age=600)
        return r

    @app.route("/robots.txt")
    def robots():
        if settings.DEMO:
            corpo = "User-agent: *\nDisallow: /\n"
        else:
            corpo = (
                "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /fragmento/\nDisallow: /api/\n"
                f"\nSitemap: {settings.SITE_URL}/sitemap.xml\n"
            )
        r = make_response(corpo)
        r.mimetype = "text/plain"
        return r

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(Path(app.static_folder) / "img", "favicon.svg", mimetype="image/svg+xml")

    # ------------------------------------------------------------------ admin (somente leitura)
    def admin_requerido(fn):
        @wraps(fn)
        def interno(*a, **kw):
            if not settings.ADMIN_PASSWORD:
                abort(404)
            if not session.get("admin"):
                return redirect(url_for("admin_login"))
            return fn(*a, **kw)
        return interno

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if not settings.ADMIN_PASSWORD:
            abort(404)
        erro = None
        if request.method == "POST":
            exigir_csrf()
            time.sleep(0.6)  # dificulta força bruta
            if hmac.compare_digest((request.form.get("senha") or "").encode(), settings.ADMIN_PASSWORD.encode()):
                session.clear()
                session["admin"] = True
                session.permanent = True
                return redirect(url_for("admin"))
            erro = "Senha incorreta."
        s = montar_seo("Admin", "Área restrita", "/admin/login", robots="noindex, nofollow")
        return render_template("admin_login.html", seo=s, erro=erro)

    @app.route("/admin/sair", methods=["POST"])
    def admin_sair():
        exigir_csrf()
        session.clear()
        return redirect("/")

    @app.route("/admin")
    @admin_requerido
    def admin():
        s = montar_seo("Admin", "Área restrita", "/admin", robots="noindex, nofollow")
        ads = []
        try:
            import json as _json
            with open(settings.CONFIG_DIR / "anuncios.json", encoding="utf-8") as f:
                for a in _json.load(f).get("anuncios", []):
                    ads.append({**a, "recusa": anuncios.verificar(a) if a.get("ativo") else "inativo"})
        except (OSError, ValueError) as e:
            ads.append({"marca": "anuncios.json inválido", "recusa": str(e)})
        return render_template(
            "admin.html", seo=s,
            contatos=db.q("SELECT * FROM contatos_anuncio ORDER BY id DESC LIMIT 300"),
            correcoes=db.q("SELECT * FROM correcoes ORDER BY id DESC LIMIT 300"),
            logs=db.q("SELECT * FROM log_validacao ORDER BY id DESC LIMIT 300"),
            historico_n=db.q1("SELECT COUNT(*) n FROM historico")["n"],
            contagens=dados.contagens(), ultima=db.jloads(db.get_meta("ultima_rodada"), {}),
            aud=audiencia.numeros(), ads=ads,
            pendentes=db.q("SELECT registro, cargo, instituto, status, motivo, tentativas, data_divulgacao "
                           "FROM pesquisas WHERE status != 'PUBLICADA' ORDER BY data_divulgacao DESC LIMIT 300"),
        )

    @app.route("/admin/historico.csv")
    @admin_requerido
    def admin_historico():
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["id", "registrado_em", "evento", "protocolo", "cargo", "uf", "tipo", "chave", "rotulo", "valor", "fontes"])
        for r in db.q("SELECT * FROM historico ORDER BY id"):
            w.writerow([r[k] for k in ("id", "registrado_em", "evento", "protocolo", "cargo", "uf", "tipo", "chave", "rotulo", "valor", "fontes")])
        resp = make_response(buf.getvalue())
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = "attachment; filename=historico.csv"
        return resp

    # ------------------------------------------------------------------ erros
    @app.errorhandler(404)
    def nao_encontrado(e):
        s = montar_seo(f"Página não encontrada – {settings.SITE_NOME}", "Página não encontrada.",
                       request.path, robots="noindex, follow")
        return render_template("erro.html", seo=s, codigo=404, mensagem="Página não encontrada."), 404

    @app.errorhandler(400)
    def requisicao_ruim(e):
        s = montar_seo("Requisição inválida", "Requisição inválida.", request.path, robots="noindex")
        return render_template("erro.html", seo=s, codigo=400,
                               mensagem="O formulário expirou. Recarregue a página e tente de novo."), 400

    return app


app = criar_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
