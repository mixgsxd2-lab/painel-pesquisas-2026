/* Mapa 3D do Brasil — Three.js + GSAP.
   Carregado só depois do conteúdo (import dinâmico). Se algo falhar, o mapa 2D em SVG continua. */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const LAT0 = -15;
const COS0 = Math.cos((LAT0 * Math.PI) / 180);
const ALTURA_BASE = 0.45;
const ALTURA_POR_PONTO = 0.16;
const ALTURA_MAX = 3.6;
const COR_NEUTRA = new THREE.Color("#2A2F3F");

function alturaDe(e) {
  if (e.status === "sem_2_turno") return 0.08;
  if (e.status === "sem_pesquisas") return 0.2;
  if (e.status === "empate") return ALTURA_BASE;
  return Math.min(ALTURA_MAX, ALTURA_BASE + (e.vantagem || 0) * ALTURA_POR_PONTO);
}

function estiloDe(e, corSemDados) {
  if (e.status === "sem_2_turno") return { cor: new THREE.Color("#3A3F4E"), opacidade: 0.16, rug: 0.95, emis: 0 };
  if (e.status === "sem_pesquisas") return { cor: new THREE.Color(corSemDados), opacidade: 0.3, rug: 0.9, emis: 0 };
  if (e.status === "empate") return { cor: new THREE.Color("#B9B4D6"), opacidade: 0.8, rug: 0.35, emis: 0.05 };
  const c = COR_NEUTRA.clone().lerp(new THREE.Color(e.cor), 0.35 + 0.65 * (e.intensidade || 0));
  return { cor: c, opacidade: 0.9, rug: 0.28, emis: 0.06 + 0.12 * (e.intensidade || 0) };
}

function texturaFundo() {
  const c = document.createElement("canvas");
  c.width = c.height = 512;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(256, 200, 20, 256, 256, 360);
  grd.addColorStop(0, "#1a1c3a");
  grd.addColorStop(0.55, "#0d0e1a");
  grd.addColorStop(1, "#07080D");
  g.fillStyle = grd;
  g.fillRect(0, 0, 512, 512);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function texturaSombra() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d");
  const grd = g.createRadialGradient(128, 128, 10, 128, 128, 128);
  grd.addColorStop(0, "rgba(0,0,0,0.75)");
  grd.addColorStop(0.6, "rgba(0,0,0,0.35)");
  grd.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grd;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

function poligonos(geom) {
  if (geom.type === "Polygon") return [geom.coordinates];
  if (geom.type === "MultiPolygon") return geom.coordinates;
  return [];
}

export async function iniciar(host, dados, opts) {
  const gsap = window.gsap;
  const reduzido = !!opts.reduzido;
  const resp = await fetch(dados.geo_url);
  if (!resp.ok) throw new Error("malha indisponível");
  const geo = await resp.json();

  // ---------- projeção e escala ----------
  let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
  for (const f of geo.features)
    for (const poly of poligonos(f.geometry))
      for (const [lon, lat] of poly[0]) {
        const x = lon * COS0, y = lat;
        if (x < minx) minx = x; if (x > maxx) maxx = x;
        if (y < miny) miny = y; if (y > maxy) maxy = y;
      }
  const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
  const esc = 40 / Math.max(maxx - minx, maxy - miny);
  const proj = (lon, lat) => [(lon * COS0 - cx) * esc, (lat - cy) * esc];

  // ---------- renderizador ----------
  const coarse = window.matchMedia("(pointer: coarse)").matches;
  const renderer = new THREE.WebGLRenderer({ antialias: !coarse, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, coarse ? 1.5 : 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = texturaFundo();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 600);
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));
  const luz = new THREE.DirectionalLight(0xffffff, 1.6);
  luz.position.set(-20, 40, 25);
  scene.add(luz);
  const contraluz = new THREE.DirectionalLight(0xa78bfa, 1.1);
  contraluz.position.set(25, 18, -30);
  scene.add(contraluz);

  // ---------- estados ----------
  const grupo = new THREE.Group();
  grupo.rotation.x = -Math.PI / 2; // XY do mapa vira o "chão"; extrusão aponta para cima
  scene.add(grupo);

  const meshes = {};
  for (const f of geo.features) {
    const uf = f.properties.uf;
    const shapes = [];
    let sx = 0, sy = 0, n = 0;
    for (const poly of poligonos(f.geometry)) {
      const anel = poly[0].map(([lon, lat]) => new THREE.Vector2(...proj(lon, lat)));
      if (anel.length < 3) continue;
      const s = new THREE.Shape(anel);
      for (let i = 1; i < poly.length; i++) s.holes.push(new THREE.Path(poly[i].map(([lon, lat]) => new THREE.Vector2(...proj(lon, lat)))));
      shapes.push(s);
      for (const v of anel) { sx += v.x; sy += v.y; n++; }
    }
    const geom = new THREE.ExtrudeGeometry(shapes, { depth: 1, bevelEnabled: false, curveSegments: 1 });
    const mat = new THREE.MeshPhysicalMaterial({
      color: COR_NEUTRA, metalness: 0.08, roughness: 0.38, clearcoat: 0.55, clearcoatRoughness: 0.3,
      transparent: true, opacity: 0.9, emissive: new THREE.Color(0x000000), envMapIntensity: 0.55,
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.userData = { uf, nome: f.properties.nome, centro: new THREE.Vector2(sx / n, sy / n), alvo: 0.2, elev: 0 };
    mesh.scale.z = 0.001;
    const borda = new THREE.LineSegments(
      new THREE.EdgesGeometry(geom, 25),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.32 })
    );
    mesh.add(borda);
    mesh.userData.borda = borda;
    grupo.add(mesh);
    meshes[uf] = mesh;
  }

  // sombra de contato
  const sombra = new THREE.Mesh(
    new THREE.PlaneGeometry(64, 64),
    new THREE.MeshBasicMaterial({ map: texturaSombra(), transparent: true, depthWrite: false, opacity: 0.85 })
  );
  sombra.position.z = -0.02;
  grupo.add(sombra);

  // ---------- pós-processamento (bloom suave) ----------
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.32, 0.45, 0.92);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  // ---------- câmera e controles ----------
  const controles = new OrbitControls(camera, renderer.domElement);
  controles.enableDamping = true;
  controles.dampingFactor = 0.08;
  controles.enablePan = false;
  controles.rotateSpeed = 0.6;
  controles.zoomSpeed = 0.7;
  controles.minPolarAngle = 0.12;
  controles.maxPolarAngle = 1.2;
  if (coarse) renderer.domElement.style.touchAction = "pan-y"; // deixa rolar a página no celular
  // rolagem do mouse rola a PÁGINA; zoom só com Ctrl/⌘ + rolagem (ou pinça)
  host.addEventListener("wheel", (e) => { if (!e.ctrlKey && !e.metaKey) e.stopPropagation(); }, { capture: true });

  let distBase = 80;
  function enquadrar(primeira) {
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    composer.setSize(w, h);
    bloom.resolution.set(w / 2, h / 2);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const raio = 25;
    const fitV = raio / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    distBase = fitV * (camera.aspect < 1 ? 0.78 / camera.aspect : 0.72);
    controles.minDistance = distBase * 0.4;
    controles.maxDistance = distBase * 1.5;
    if (primeira) {
      const ang = 0.82;
      camera.position.set(0, distBase * Math.cos(ang), distBase * Math.sin(ang));
      controles.target.set(0, 0, 2);
    }
    controles.update();
  }
  enquadrar(true);

  // ---------- dados → aparência ----------
  let cargo = opts.cargo;
  function porUf(c) {
    const m = {};
    for (const e of dados[c].estados) m[e.uf] = e;
    return m;
  }
  function aplicarCores(c) {
    const est = porUf(c);
    for (const [uf, mesh] of Object.entries(meshes)) {
      const e = est[uf];
      if (!e) continue;
      const s = estiloDe(e, dados.cor_sem_dados);
      mesh.material.color.copy(s.cor);
      mesh.material.opacity = s.opacidade;
      mesh.material.roughness = s.rug;
      mesh.material.emissive.copy(s.cor).multiplyScalar(s.emis);
      mesh.material.transmission = 0;
      mesh.userData.alvo = alturaDe(e);
      mesh.userData.estado = e;
      mesh.userData.borda.material.color.set(e.status === "com_pesquisas" || e.status === "apuracao" ? s.cor.clone().lerp(new THREE.Color("#ffffff"), 0.55) : 0xffffff);
      mesh.userData.borda.material.opacity = e.status === "sem_2_turno" ? 0.12 : e.status === "sem_pesquisas" ? 0.25 : 0.55;
    }
  }

  const ordem = Object.values(meshes).sort((a, b) => a.userData.centro.x - b.userData.centro.x + (b.userData.centro.y - a.userData.centro.y) * 0.4);
  function subir(atraso = 0) {
    if (!gsap || reduzido) {
      for (const m of ordem) m.scale.z = m.userData.alvo;
      return;
    }
    gsap.to(ordem.map((m) => m.scale), {
      z: (i) => ordem[i].userData.alvo, duration: 1.1, ease: "back.out(1.6)", stagger: 0.045, delay: atraso,
    });
  }
  aplicarCores(cargo);
  subir(0.15);

  // ---------- interação ----------
  const raycaster = new THREE.Raycaster();
  const ponteiro = new THREE.Vector2();
  let selecionado = null, sobre = null;
  const dica = document.createElement("div");
  dica.className = "mapa-tooltip";
  dica.hidden = true;
  host.appendChild(dica);

  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    ponteiro.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
    ponteiro.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(ponteiro, camera);
    const hit = raycaster.intersectObjects(Object.values(meshes), false)[0];
    return hit ? hit.object : null;
  }

  function elevar(mesh, valor, brilho) {
    if (!mesh) return;
    const e = mesh.userData.estado || {};
    const s = estiloDe(e, dados.cor_sem_dados);
    const emis = s.emis + brilho;
    if (gsap && !reduzido) {
      gsap.to(mesh.position, { z: valor, duration: 0.45, ease: "power3.out" });
      gsap.to(mesh.material.emissive, { r: s.cor.r * emis, g: s.cor.g * emis, b: s.cor.b * emis, duration: 0.45 });
    } else {
      mesh.position.z = valor;
      mesh.material.emissive.copy(s.cor).multiplyScalar(emis);
    }
  }

  function selecionar(uf) {
    const novo = uf ? meshes[uf] : null;
    if (selecionado && selecionado !== novo) elevar(selecionado, 0, 0);
    selecionado = novo;
    if (novo) { const st = (novo.userData.estado || {}).status; elevar(novo, 1.1, st === "com_pesquisas" || st === "apuracao" ? 0.4 : 0.12); }
  }

  let inicio = null;
  renderer.domElement.addEventListener("pointerdown", (ev) => { inicio = [ev.clientX, ev.clientY]; });
  renderer.domElement.addEventListener("pointerup", (ev) => {
    if (!inicio) return;
    const moveu = Math.hypot(ev.clientX - inicio[0], ev.clientY - inicio[1]);
    inicio = null;
    if (moveu > 6) return;
    const m = pick(ev);
    if (m) { selecionar(m.userData.uf); opts.aoSelecionar && opts.aoSelecionar(m.userData.uf); }
  });
  let rafHover = 0;
  renderer.domElement.addEventListener("pointermove", (ev) => {
    if (ev.pointerType !== "mouse" || rafHover) return;
    rafHover = requestAnimationFrame(() => {
      rafHover = 0;
      const m = pick(ev);
      if (m !== sobre) {
        if (sobre && sobre !== selecionado) elevar(sobre, 0, 0);
        sobre = m;
        if (m && m !== selecionado) elevar(m, 0.35, 0.1);
      }
      renderer.domElement.style.cursor = m ? "pointer" : "grab";
      if (m) {
        const r = host.getBoundingClientRect();
        const e = m.userData.estado || {};
        const status = e.status === "sem_2_turno" ? "Sem 2º turno" : e.status === "sem_pesquisas" ? "Sem pesquisas registradas" :
          e.status === "apuracao" ? "Resultados: TSE — toque para ver" : "Toque para ver a média e as pesquisas";
        dica.innerHTML = "<b></b><span></span>";
        dica.firstChild.textContent = m.userData.nome;
        dica.lastChild.textContent = status;
        dica.style.left = ev.clientX - r.left + "px";
        dica.style.top = ev.clientY - r.top + "px";
        dica.hidden = false;
      } else dica.hidden = true;
    });
  });
  renderer.domElement.addEventListener("pointerleave", () => {
    dica.hidden = true;
    if (sobre && sobre !== selecionado) elevar(sobre, 0, 0);
    sobre = null;
  });

  if (opts.ufInicial && meshes[opts.ufInicial]) setTimeout(() => selecionar(opts.ufInicial), reduzido ? 0 : 1400);

  // ---------- laço de renderização (pausa fora da tela / aba oculta) ----------
  let visivel = true;
  const io = new IntersectionObserver((ents) => { visivel = ents[0].isIntersecting; }, { threshold: 0.01 });
  io.observe(host);
  new ResizeObserver(() => enquadrar(false)).observe(host);
  renderer.setAnimationLoop(() => {
    if (!visivel || document.hidden) return;
    controles.update();
    composer.render();
  });

  return {
    selecionar,
    definirCargo(novo) {
      if (novo === cargo) return;
      cargo = novo;
      selecionar(null);
      if (!gsap || reduzido) { aplicarCores(novo); subir(); return; }
      gsap.to(ordem.map((m) => m.scale), {
        z: 0.02, duration: 0.35, ease: "power2.in", stagger: 0.008,
        onComplete: () => { aplicarCores(novo); subir(0); },
      });
    },
  };
}
