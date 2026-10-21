# Painel das Pesquisas 2026

Agregador automático de **pesquisas eleitorais registradas no TSE** para o **2º turno de 2026**
(presidente e governadores — eleição em 25/10/2026). Roda sozinho: coleta, busca os números,
valida, publica, gera sitemap e imagens de compartilhamento, e às 17h de 25/10 troca o mapa para
o modo **Apuração** com os resultados oficiais do TSE.

> **Antes de publicar, leia a seção [“O que você PRECISA configurar”](#o-que-você-precisa-configurar).**
> Sem uma chave de API de busca, nenhuma pesquisa nova é publicada.

---

## Como funciona (pipeline a cada 1 hora)

| Etapa | Arquivo | O que faz |
|---|---|---|
| Malha | `pipeline/malha_ibge.py` | Baixa o GeoJSON das 27 UFs da API de malhas do IBGE (semanal). |
| Candidatos | `pipeline/coletar_candidatos.py` | Lê os resultados oficiais do 1º turno no TSE e descobre quem foi ao 2º turno (presidente e cada estado) e a **ordem na urna** do 2º turno. Nada é digitado à mão. |
| 1. Coleta TSE | `pipeline/coletar_tse.py` | Baixa os ZIPs de pesquisas, contratantes e pagantes do Portal de Dados Abertos do TSE. Filtra Presidente/Governador com coleta iniciada após o 1º turno. Extrai margem de erro, nível de confiança e abrangência do plano amostral (a base do TSE não tem essas colunas). Pesquisas que somem da base do TSE são ocultadas. |
| 2. Busca | `pipeline/buscar_resultados.py` | Busca “instituto + registro” na web, prioriza o site oficial do instituto, lê páginas e PDFs (respeitando robots.txt) e extrai candidatos, brancos/nulos, indecisos e tipo (totais/válidos). |
| 3. Validação | `pipeline/validar.py` | Publica só se passar em **todas** as regras (abaixo). Se falhar: `DESCARTADA`, invisível, motivo no log, nova tentativa na próxima rodada. |
| Apuração | `pipeline/apuracao.py` | A partir de 25/10 17h (Brasília), lê os resultados do 2º turno em resultados.tse.jus.br a cada 2 minutos. |
| SEO | `pipeline/sitemap.py`, `pipeline/og_images.py` | Regera `sitemap.xml` com `<lastmod>` e as imagens 1200×630 de cada página. |

### Regras de validação (todas obrigatórias)
1. o número de registro aparece na página da fonte;
2. ≥ 2 fontes independentes (domínios diferentes) com os mesmos números (tolerância 0,5 ponto) — brancos/nulos e indecisos também só aparecem se 2 fontes concordarem;
3. cargo, UF e turno da página batem com o registro do TSE;
4. nomes dos candidatos batem com os do 2º turno;
5. soma entre 85% e 101%;
6. tipo de resultado (totais/válidos) identificado e igual entre as fontes;
7. divulgação ≥ 5 dias após o registro no TSE (e a data já chegou);
8. margem de erro e nível de confiança conhecidos.

### Média das pesquisas registradas
Média aritmética simples da **pesquisa mais recente de cada instituto**, por disputa (Brasil, ou
presidente/governador em cada UF). Dados nacionais nunca preenchem estados. Usa o tipo (totais/válidos)
disponível no maior número de institutos. Detalhes na página `/metodologia`.

---

## Estrutura de pastas

```
painel-pesquisas-2026/
├── app.py                 # Flask: rotas, SEO, formulários, admin (renderização no servidor)
├── wsgi.py                # entrada de produção (gunicorn) — liga o agendador junto
├── scheduler.py           # APScheduler: pipeline a cada 1h, apuração a cada 2 min (trava de arquivo = 1 agendador só)
├── settings.py            # configurações via variáveis de ambiente / .env
├── manage.py              # comandos: init, pipeline, servir, anuncios, demo
├── demo_dados.py          # dados FICTÍCIOS só para ver o visual (modo demo, noindex)
├── config/
│   ├── candidatos.json    # cores por ordem na urna + ajustes opcionais
│   ├── anuncios.json      # anúncios (imagem, link, datas) — sem mexer no código
│   └── institutos.json    # domínios oficiais dos institutos (prioridade na busca)
├── core/                  # banco, dados/médias, anúncios, audiência, SEO, textos, geo
├── pipeline/              # coleta, busca, extração, validação, apuração, sitemap, imagens
├── templates/             # Jinja (base, macros, páginas)
├── static/
│   ├── css/critical.css   # CSS crítico (vai inline no <head>)
│   ├── css/site.css       # restante do CSS (carregado sem bloquear)
│   ├── js/app.js          # interface: contagem, barras, gaveta, alternador, presença
│   ├── js/mapa3d.js       # mapa 3D (Three.js + GSAP), carregado só depois do conteúdo
│   ├── anuncios/          # coloque aqui as imagens dos anúncios (.webp)
│   └── img/favicon.svg
├── tests/test_regras.py   # testes das regras críticas
├── data/                  # (gerado) banco SQLite, logs, sitemap, imagens OG, malha — NÃO versionar
├── requirements.txt  Procfile  render.yaml  railway.json  .env.example
```

---

## Rodar no seu computador

Requisitos: Python 3.11+ (testado com 3.13).

```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
```
```bash
pip install -r requirements.txt
```
```bash
copy .env.example .env          # Linux/Mac: cp .env.example .env  — depois edite o .env
```
```bash
python manage.py pipeline       # roda UMA rodada agora (coleta TSE, busca, validação…)
```
```bash
python manage.py servir         # site em http://127.0.0.1:5000 + agendador ligado
```

Ver só o visual com dados **fictícios** (banco separado, faixa de aviso, noindex, pipeline desligado):
```bash
python manage.py demo
```

Testes:
```bash
python -m unittest discover -s tests -v
```

---

## O que você PRECISA configurar

1. **Chave de API de busca (obrigatório para publicar pesquisas novas).**
   O fallback gratuito (DuckDuckGo) responde com verificação anti-robô para servidores, e o sistema
   **não** tenta contornar isso. Configure pelo menos um:
   - `BRAVE_API_KEY` — [Brave Search API](https://brave.com/search/api/) (recomendado; tem plano gratuito com limite mensal);
   - `SERPAPI_KEY` — [SerpAPI](https://serpapi.com/) (Google);
   - `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` — Google Programmable Search.

   **Custo/limite:** cada pesquisa consome ~4 consultas por tentativa. Com `MAX_PESQUISAS_POR_RODADA=40`
   e 24 rodadas/dia, são até ~3.800 consultas/dia na fase de maior volume. Ajuste `MAX_PESQUISAS_POR_RODADA`
   ao seu plano (as pesquisas entram em rodízio, as nunca tentadas primeiro).
2. `SITE_URL` (seu domínio com https), `SECRET_KEY` (aleatória), `ADMIN_PASSWORD`.
3. E-mail: `EMAIL_CONTATO` (exibido no site), `EMAIL_DONO` (recebe os formulários) e SMTP
   (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`). Sem SMTP, os contatos ficam salvos no banco e visíveis em `/admin`.
4. `DATA_DIR` apontando para um **disco persistente** em produção.

---

## Publicar (Render ou Railway) com o agendador ligado

O site e o agendador rodam **no mesmo processo** (`wsgi.py`), porque o SQLite fica num disco que só um
serviço enxerga. Use **1 worker** do gunicorn (com threads) — a trava de arquivo garante um único agendador.

### Render
1. Suba o projeto para um repositório no GitHub (sem a pasta `data/` e sem `.env`).
2. No Render: **New → Blueprint** → escolha o repositório. O `render.yaml` cria o serviço web com
   **disco persistente** em `/var/data` e `DATA_DIR=/var/data`.
3. Preencha as variáveis marcadas como “sync: false” (`SITE_URL`, `ADMIN_PASSWORD`, `BRAVE_API_KEY`, e-mail…).
4. **Use plano pago (Starter ou superior).** O plano gratuito não tem disco persistente e “dorme” sem
   tráfego — o agendador pararia.
5. Domínio próprio: Settings → Custom Domains. Atualize `SITE_URL`.

### Railway
1. **New Project → Deploy from GitHub repo**. O `railway.json` define o comando de início e o healthcheck.
2. Adicione um **Volume** montado em `/data` e defina `DATA_DIR=/data`.
3. Defina as variáveis do `.env.example`. Mantenha **1 réplica**.

Depois do deploy: abra `/healthz` (mostra a última rodada) e `/admin` (status de cada pesquisa e motivos de descarte).

---

## Cadastrar no Google Search Console e no Bing Webmaster Tools

**Google Search Console**
1. Acesse <https://search.google.com/search-console> → **Adicionar propriedade** → **Prefixo do URL** → cole seu `SITE_URL`.
2. Verificação por **tag HTML**: copie só o valor de `content="…"` e coloque em `GOOGLE_SITE_VERIFICATION`
   no ambiente. Reinicie o serviço e clique em **Verificar**. (Ou use o registro DNS do seu domínio.)
3. Menu **Sitemaps** → envie `sitemap.xml` (o endereço completo é `SITE_URL/sitemap.xml`).
4. **Inspeção de URL** → cole e clique em **Solicitar indexação** para as páginas principais:
   `/`, `/presidente`, `/governador`, `/pesquisas` e as páginas dos estados com 2º turno
   (ex.: `/governador/rn`, `/governador/df`, `/governador/to`, `/governador/am`, `/governador/es`, `/governador/ac`).
5. Acompanhe **Desempenho** e **Core Web Vitals**.

**Bing Webmaster Tools**
1. Acesse <https://www.bing.com/webmasters> → **Importar do Google Search Console** (mais rápido) ou adicione o site manualmente.
2. Se manual: verificação por meta tag → valor em `BING_SITE_VERIFICATION`.
3. **Sitemaps** → envie `SITE_URL/sitemap.xml`.
4. **Envio de URL** → envie as páginas principais. (O Bing também atende ao protocolo IndexNow, que pode ser adicionado depois.)

O `robots.txt` aponta para o sitemap e bloqueia `/admin`, `/fragmento/` e `/api/`; o `/admin` também envia `noindex`.

---

## Candidatos e cores — `config/candidatos.json`

Os candidatos são descobertos **automaticamente** no TSE. O arquivo só define:
- `paleta_por_ordem_na_urna`: a 1ª cor vai para o 1º candidato da urna do 2º turno, a 2ª para o 2º (padrão: vermelho, azul);
- `ordem`: `"tse"` (ordem oficial da urna) ou `"numero"`;
- `manual` (opcional): substitui a lista automática de uma disputa, ex.: `"governador/RN": [{"numero": "13", "nome_urna": "…", "partido": "…"}]`;
- `apelidos` (opcional): outras grafias do nome para a busca, ex.: `"presidente/BR/22": ["flávio"]`.

## Anúncios — `config/anuncios.json`

Cada anúncio: `ativo`, `espaco` (`banner_pesquisas`, `gaveta_mapa`, `selo_apuracao`), `marca`,
`texto_alternativo`, `imagem` (em `static/anuncios/`, de preferência WebP), `largura`, `altura`, `link`, `inicio`, `fim`.
Sem anúncio ativo, cada espaço mostra um card “Anuncie aqui” → `/anuncie`.

Regras aplicadas **automaticamente** (recusas vão para `data/logs/anuncios.log` e aparecem no `/admin`):
- rótulo “Publicidade” sempre visível;
- conteúdo político/eleitoral é recusado (termos e nomes de candidatos);
- imagens com mais de 6% de pixels nas cores dos candidatos (vermelho/azul) são recusadas;
- anúncios nunca ficam sobre ou no meio dos números.

Para conferir: `python manage.py anuncios`.

---

## Regras legais atendidas
- Só pesquisas com registro no TSE (e que continuam na base do TSE).
- Agregado chamado “Média das pesquisas registradas”; o site nunca usa “previsão”, “estimativa” ou “projeção” para a média.
- Estados sem pesquisa em cinza, “Sem pesquisas registradas”; nunca preenchidos com dados nacionais.
- Nenhum percentual aparece sem os dados obrigatórios no mesmo card (visíveis ou a um toque, em “Pesquisas usadas no cálculo”).
  As imagens de compartilhamento **não** têm percentuais nem cores de candidatos, pelo mesmo motivo.
- Sem enquetes, votação de usuários, comentários ou imagens de candidatos.
- Rodapé fixo com o aviso legal em todas as páginas.
- Histórico permanente: tabelas `historico` e `log_validacao` com triggers que bloqueiam UPDATE/DELETE; exportável em CSV no `/admin`.

## Limitações conhecidas
- A extração de números de páginas é heurística. Por isso a exigência de 2 fontes independentes: quando
  há dúvida, a pesquisa fica fora (falso negativo), em vez de publicar algo errado.
- A base do TSE não diz se uma pesquisa de presidente feita num só estado é estadual (ela é registrada como “BR”);
  o sistema deduz pelo plano amostral e, se não der, pelas fontes. Casos ambíguos ficam fora.
- O botão “Conferir no TSE” abre a consulta PesqEle e copia o número do registro (o sistema do TSE não aceita link direto por registro).
- Impugnações/suspensões judiciais de pesquisas não constam na base aberta do TSE; use `/contato` e a lista `manual` se precisar intervir.
