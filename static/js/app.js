/* Painel das Pesquisas 2026 — interface leve, sem dependências. */
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var celular = window.matchMedia("(max-width: 900px)");

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function fmt(v, casas) {
    return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  }

  /* ---------------- barras animadas ao aparecer ---------------- */
  function prepararBarras(raiz) {
    if (reduzido || !("IntersectionObserver" in window)) return;
    var barras = $$(".barra-fill", raiz);
    barras.forEach(function (b) { b.classList.add("esperando"); });
    var io = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        if (!en.isIntersecting) return;
        var el = en.target;
        requestAnimationFrame(function () { el.classList.remove("esperando"); });
        io.unobserve(el);
      });
    }, { threshold: 0.2 });
    barras.forEach(function (b) { io.observe(b); });
  }
  prepararBarras(document);

  /* ---------------- contagem regressiva ---------------- */
  $$(".contagem[data-alvo]").forEach(function (box) {
    var alvo = new Date(box.dataset.alvo).getTime();
    var cels = { d: $("[data-u=d]", box), h: $("[data-u=h]", box), m: $("[data-u=m]", box), s: $("[data-u=s]", box) };
    if (!cels.s) return;
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    function tique() {
      var r = Math.max(0, Math.floor((alvo - Date.now()) / 1000));
      if (r === 0) {
        box.innerHTML = '<span class="contagem-fim"><i class="pulso"></i> Apuração em andamento</span>';
        clearInterval(id);
        return;
      }
      cels.d.textContent = pad(Math.floor(r / 86400));
      cels.h.textContent = pad(Math.floor(r % 86400 / 3600));
      cels.m.textContent = pad(Math.floor(r % 3600 / 60));
      cels.s.textContent = pad(r % 60);
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
  if (filtros) $$("select", filtros).forEach(function (s) { s.addEventListener("change", function () { filtros.submit(); }); });

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
  } catch (e) { /* armazenamento bloqueado */ }

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
     MAPA 2D: alternador de cargo e painel do estado
     ===================================================================== */
  var palco = $("#mapa");
  if (!palco) return;
  var dadosEl = $("#dados-mapa");
  var dados = dadosEl ? JSON.parse(dadosEl.textContent) : null;
  var cargo = palco.dataset.cargo;
  var svg = $("#mapa2d");
  var gaveta = $("#gaveta"), corpo = $("#gaveta-corpo");
  var inicial = corpo ? corpo.innerHTML : "";
  var pilula = $(".pilula");

  function pintar(c) {
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

  function marcarAtivo(uf) {
    if (svg) $$(".uf", svg).forEach(function (a) { a.classList.toggle("ativo", a.dataset.uf === uf); });
  }

  var controlador = null;
  function abrir(uf) {
    if (!gaveta) return;
    marcarAtivo(uf);
    gaveta.classList.add("aberta");
    document.body.classList.toggle("gaveta-aberta", celular.matches);
    corpo.innerHTML = '<div class="gaveta-carregando"><i></i><i style="width:70%"></i><i style="width:85%"></i></div>';
    if (controlador) controlador.abort();
    controlador = "AbortController" in window ? new AbortController() : null;
    fetch("/fragmento/" + cargo + "/" + uf.toLowerCase(), { signal: controlador ? controlador.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        corpo.innerHTML = html;
        corpo.scrollTop = 0;
        prepararBarras(corpo);
        if (!celular.matches) gaveta.scrollIntoView({ block: "nearest", behavior: reduzido ? "auto" : "smooth" });
      })
      .catch(function (e) {
        if (e && e.name === "AbortError") return;
        corpo.innerHTML = '<p class="vazio">Não foi possível carregar. <a href="/' + cargo + "/" + uf.toLowerCase() + '">Abrir a página do estado</a>.</p>';
      });
  }

  function fechar() {
    if (!gaveta) return;
    gaveta.classList.remove("aberta");
    document.body.classList.remove("gaveta-aberta");
    marcarAtivo(null);
    corpo.innerHTML = inicial;
  }

  var btnFechar = $("#gaveta-fechar");
  if (btnFechar) btnFechar.addEventListener("click", fechar);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") fechar(); });

  // arrastar para baixo fecha a folha no celular
  if (gaveta) {
    var y0 = null;
    gaveta.addEventListener("touchstart", function (e) { if (celular.matches && corpo.scrollTop <= 0) y0 = e.touches[0].clientY; }, { passive: true });
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
      if (dy > 90) fechar();
    });
  }

  if (svg) {
    svg.addEventListener("click", function (ev) {
      var a = ev.target.closest(".uf");
      if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
      ev.preventDefault();
      abrir(a.dataset.uf);
    });
  }

  var nacional = $(".mapa-nacional");
  if (nacional) nacional.addEventListener("click", function () { abrir("BR"); });

  if (pilula) {
    pilula.addEventListener("click", function (ev) {
      var t = ev.target.closest("a[role=tab]");
      if (!t || pilula.dataset.modo !== "local" || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
      ev.preventDefault();
      if (t.dataset.cargo === cargo) return;
      cargo = t.dataset.cargo;
      palco.dataset.cargo = cargo;
      $$("a[role=tab]", pilula).forEach(function (x) { x.setAttribute("aria-selected", x === t ? "true" : "false"); });
      var leg = $(".leg-gov");
      if (leg) leg.hidden = cargo !== "governador";
      var legp = $(".leg-pres");
      if (legp) legp.hidden = cargo !== "presidente";
      $$("[data-painel]").forEach(function (p) {
        p.hidden = p.dataset.painel !== cargo;
        if (!p.hidden) prepararBarras(p);
      });
      pintar(cargo);
      $$(".rotulos", svg).forEach(function (g) {
        if (g.dataset.cargo === cargo) g.removeAttribute("hidden"); else g.setAttribute("hidden", "");
      });
      fechar();
    });
  }
})();
