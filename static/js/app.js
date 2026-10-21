/* Painel das Pesquisas 2026 — interface (sem dependências; usa GSAP se disponível) */
(function () {
  "use strict";
  var doc = document.documentElement;
  doc.classList.add("js");
  var reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function fmt(v, casas) {
    return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  }

  /* ---------------- barras e números animados ---------------- */
  function animarNumero(el) {
    if (el.dataset.animado) return;
    el.dataset.animado = "1";
    var alvo = parseFloat(el.dataset.count);
    if (isNaN(alvo) || reduzido) return;
    var texto = el.textContent;
    var pctSufixo = texto.indexOf("%") >= 0;
    var casas = pctSufixo ? 1 : 0;
    var inicio = performance.now(), dur = 1100;
    function passo(t) {
      var k = Math.min(1, (t - inicio) / dur);
      var e = 1 - Math.pow(1 - k, 3);
      el.textContent = fmt(alvo * e, casas) + (pctSufixo ? "%" : "");
      if (k < 1) requestAnimationFrame(passo); else el.textContent = texto;
    }
    requestAnimationFrame(passo);
  }

  function prepararAnimacoes(raiz) {
    var barras = $$(".barra-fill", raiz);
    var nums = $$("[data-count]", raiz);
    if (reduzido || !("IntersectionObserver" in window)) return;
    barras.forEach(function (b) { b.classList.add("esperando"); });
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        if (el.classList.contains("barra-fill")) {
          requestAnimationFrame(function () { el.classList.remove("esperando"); });
        } else { animarNumero(el); }
        io.unobserve(el);
      });
    }, { threshold: 0.2 });
    barras.concat(nums).forEach(function (el) { io.observe(el); });
  }
  prepararAnimacoes(document);

  /* ---------------- contagem regressiva ---------------- */
  $$(".contagem[data-alvo]").forEach(function (box) {
    var alvo = new Date(box.dataset.alvo).getTime();
    var cels = { d: $("[data-u=d]", box), h: $("[data-u=h]", box), m: $("[data-u=m]", box), s: $("[data-u=s]", box) };
    if (!cels.s) return;
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    function trocar(el, v) {
      if (!el || el.textContent === v) return;
      if (reduzido) { el.textContent = v; return; }
      el.classList.add("vira");
      setTimeout(function () { el.textContent = v; el.classList.remove("vira"); }, 180);
    }
    function tique() {
      var r = Math.max(0, Math.floor((alvo - Date.now()) / 1000));
      if (r === 0) { box.innerHTML = '<span class="contagem-fim"><i class="pulso"></i> Apuração em andamento</span>'; clearInterval(id); return; }
      trocar(cels.d, pad(Math.floor(r / 86400)));
      trocar(cels.h, pad(Math.floor(r % 86400 / 3600)));
      trocar(cels.m, pad(Math.floor(r % 3600 / 60)));
      trocar(cels.s, pad(r % 60));
    }
    var id = setInterval(tique, 1000);
    tique();
  });

  /* ---------------- "Conferir no TSE": copia o registro ---------------- */
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("[data-copiar]");
    if (!a || !navigator.clipboard) return;
    navigator.clipboard.writeText(a.dataset.copiar).then(function () {
      a.classList.add("copiado");
      setTimeout(function () { a.classList.remove("copiado"); }, 4000);
    }).catch(function () {});
  });

  /* ---------------- filtros da página Pesquisas ---------------- */
  var filtros = $("form.filtros");
  if (filtros) {
    $$("select", filtros).forEach(function (s) { s.addEventListener("change", function () { filtros.submit(); }); });
  }

  /* ---------------- presença (pico simultâneo) ---------------- */
  try {
    var sid = sessionStorage.getItem("pp_sid");
    if (!sid) { sid = Math.random().toString(36).slice(2) + Date.now().toString(36); sessionStorage.setItem("pp_sid", sid); }
    var ping = function () {
      if (document.visibilityState !== "visible") return;
      fetch("/api/presenca", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sid: sid }), keepalive: true }).catch(function () {});
    };
    ping();
    setInterval(ping, 30000);
    document.addEventListener("visibilitychange", ping);
  } catch (e) { /* armazenamento bloqueado: ignora */ }

  /* ---------------- audiência ao vivo (/anuncie) ---------------- */
  var aud = $("#audiencia");
  if (aud) {
    setInterval(function () {
      fetch(aud.dataset.api, { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
        $$("[data-k]", aud).forEach(function (el) {
          var v = d[el.dataset.k];
          if (typeof v === "number") el.textContent = fmt(v, 0);
        });
      }).catch(function () {});
    }, 20000);
  }

  /* =====================================================================
     MAPA: alternador, gaveta, mapa 2D (SVG) e carregamento do 3D
     ===================================================================== */
  var palco = $("#mapa");
  if (!palco) return;
  var dadosEl = $("#dados-mapa");
  var dados = dadosEl ? JSON.parse(dadosEl.textContent) : null;
  var cargo = palco.dataset.cargo;
  var svg = $("#mapa2d");
  var gaveta = $("#gaveta"), corpo = $("#gaveta-corpo");
  var pilula = $(".pilula");
  var mapa3d = null;

  function posicionarIndicador() {
    if (!pilula) return;
    var sel = $("[aria-selected=true]", pilula), ind = $(".pilula-ind", pilula);
    if (!sel || !ind) return;
    ind.style.width = sel.offsetWidth + "px";
    ind.style.transform = "translateX(" + (sel.offsetLeft - 5) + "px)";
  }
  posicionarIndicador();
  window.addEventListener("resize", posicionarIndicador);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(posicionarIndicador);

  function pintarSvg(c) {
    if (!svg || !dados) return;
    var porUf = {};
    dados[c].estados.forEach(function (e) { porUf[e.uf] = e; });
    $$(".uf", svg).forEach(function (a) {
      var e = porUf[a.dataset.uf];
      if (!e) return;
      a.setAttribute("class", "uf uf-" + e.status + (a.classList.contains("ativo") ? " ativo" : ""));
      a.setAttribute("href", e.url);
      var p = $("path", a);
      p.style.setProperty("--c", e.cor);
      p.style.setProperty("--i", e.intensidade);
    });
  }

  function trocarCargo(novo, origem) {
    if (novo === cargo) return;
    cargo = novo;
    palco.dataset.cargo = novo;
    $$("a[role=tab]", pilula).forEach(function (t) { t.setAttribute("aria-selected", t.dataset.cargo === novo ? "true" : "false"); });
    posicionarIndicador();
    var leg = $(".leg-gov");
    if (leg) leg.hidden = novo !== "governador";
    $$("[data-painel]").forEach(function (p) {
      p.hidden = p.dataset.painel !== novo;
      if (!p.hidden) prepararAnimacoes(p);
    });
    pintarSvg(novo);
    if (mapa3d) mapa3d.definirCargo(novo);
    fecharGaveta();
  }

  if (pilula) {
    pilula.addEventListener("click", function (ev) {
      var t = ev.target.closest("a[role=tab]");
      if (!t || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
      if (pilula.dataset.modo === "local") {
        ev.preventDefault();
        trocarCargo(t.dataset.cargo);
      } else if (t.dataset.cargo !== cargo) {
        // páginas próprias: anima o mapa e navega
        ev.preventDefault();
        $$("a[role=tab]", pilula).forEach(function (x) { x.setAttribute("aria-selected", x === t ? "true" : "false"); });
        posicionarIndicador();
        if (mapa3d) mapa3d.definirCargo(t.dataset.cargo);
        setTimeout(function () { location.href = t.href; }, reduzido ? 0 : 420);
      }
    });
  }

  /* ---------------- gaveta ---------------- */
  var ufAberta = null, controlador = null;
  function abrirGaveta(uf) {
    if (!gaveta) return;
    ufAberta = uf;
    gaveta.hidden = false;
    gaveta.classList.remove("fechando");
    corpo.innerHTML = '<div class="gaveta-carregando"><i></i><i style="width:70%"></i><i style="width:85%"></i><i style="width:60%"></i></div>';
    if (controlador) controlador.abort();
    controlador = "AbortController" in window ? new AbortController() : null;
    fetch("/fragmento/" + cargo + "/" + uf.toLowerCase(), { signal: controlador ? controlador.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        corpo.innerHTML = html;
        corpo.scrollTop = 0;
        prepararAnimacoes(corpo);
        corpo.focus({ preventScroll: true });
        if (window.gsap && !reduzido) gsap.from(corpo.children, { y: 14, opacity: 0, duration: .5, stagger: .06, ease: "power3.out" });
      })
      .catch(function (e) {
        if (e && e.name === "AbortError") return;
        corpo.innerHTML = '<p class="vazio">Não foi possível carregar. <a href="/' + cargo + "/" + uf.toLowerCase() + '">Abrir a página do estado</a>.</p>';
      });
    if (svg) $$(".uf", svg).forEach(function (a) { a.classList.toggle("ativo", a.dataset.uf === uf); });
    if (mapa3d) mapa3d.selecionar(uf);
  }
  function fecharGaveta() {
    if (!gaveta || gaveta.hidden) return;
    gaveta.classList.add("fechando");
    setTimeout(function () { gaveta.hidden = true; gaveta.classList.remove("fechando"); }, reduzido ? 0 : 380);
    ufAberta = null;
    if (mapa3d) mapa3d.selecionar(null);
    if (svg) $$(".uf", svg).forEach(function (a) { a.classList.remove("ativo"); });
  }
  var btnFechar = $("#gaveta-fechar");
  if (btnFechar) btnFechar.addEventListener("click", fecharGaveta);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") fecharGaveta(); });

  // arrastar para baixo fecha a gaveta no celular
  if (gaveta) {
    var y0 = null;
    gaveta.addEventListener("touchstart", function (e) { if (corpo.scrollTop <= 0) y0 = e.touches[0].clientY; }, { passive: true });
    gaveta.addEventListener("touchmove", function (e) {
      if (y0 === null) return;
      var dy = e.touches[0].clientY - y0;
      if (dy > 0) gaveta.style.transform = "translateY(" + dy + "px)";
    }, { passive: true });
    gaveta.addEventListener("touchend", function (e) {
      if (y0 === null) return;
      var dy = e.changedTouches[0].clientY - y0;
      gaveta.style.transform = "";
      y0 = null;
      if (dy > 90) fecharGaveta();
    });
  }

  // cliques no mapa 2D
  if (svg) {
    svg.addEventListener("click", function (ev) {
      var a = ev.target.closest(".uf");
      if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
      ev.preventDefault();
      abrirGaveta(a.dataset.uf);
    });
  }

  /* ---------------- mapa 3D (carregado DEPOIS do conteúdo) ---------------- */
  function temWebGL() {
    try {
      var c = document.createElement("canvas");
      return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
    } catch (e) { return false; }
  }
  function carregar3D() {
    if (!window.__MAPA3D__ || !temWebGL() || !dados) return;
    var host = $("#mapa3d");
    import(window.__MAPA3D__).then(function (mod) {
      return mod.iniciar(host, dados, {
        cargo: cargo,
        ufInicial: palco.dataset.uf || null,
        reduzido: reduzido,
        aoSelecionar: function (uf) { abrirGaveta(uf); },
      });
    }).then(function (api) {
      if (!api) return;
      mapa3d = api;
      palco.classList.add("com-3d");
      var dica = $("#mapa-dica");
      if (dica) dica.textContent = window.matchMedia("(pointer: coarse)").matches ? "Arraste para girar · pinça para zoom · toque em um estado" : "Arraste para girar · Ctrl + rolagem para zoom · clique em um estado";
    }).catch(function (e) { console.warn("Mapa 3D indisponível; usando mapa 2D.", e); });
  }
  var iniciar = function () {
    if ("requestIdleCallback" in window) requestIdleCallback(carregar3D, { timeout: 2500 });
    else setTimeout(carregar3D, 600);
  };
  if (document.readyState === "complete") iniciar(); else window.addEventListener("load", iniciar);
})();
