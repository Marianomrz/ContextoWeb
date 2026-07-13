# Contexto — Portal de noticias con análisis de sesgo

Un portal que publica noticias señalando **hacia dónde se inclina cada cobertura**
(espectro editorial), **con qué foco** fue contada, y el **contexto/trasfondo**
que la nota original no siempre incluye. Un agente automático lee las fuentes,
analiza cada nota con la API de Claude, y publica el resultado.

## Estructura

```
├── index.html          Portal (frontend)
├── styles.css          Estilos
├── app.js              Lógica del frontend (render, filtros, búsqueda, dieta informativa)
├── share.js             Botón de compartir (articulo/ y revista/): share nativo o copiar enlace
├── articles.json       Base de datos de notas — el agente la escribe
├── articulo/           Página estática por nota (las genera build_pages.py)
├── hemeroteca.html      Archivo cronológico de todas las notas, agrupadas por día
├── hemeroteca.js         Lógica de la hemeroteca (independiente de app.js)
├── fuentes.html        Panel de fuentes público
├── brujula.html        Quiz de autoubicación en el espectro editorial
├── compass.js          Lógica de la brújula (independiente de app.js)
├── glosario.html        Glosario de términos periodísticos
├── correcciones.html   Cómo reportar errores (botón a GitHub Issues)
├── legal.html          Aviso legal y privacidad
├── 404.html             Página de error (GitHub Pages la sirve para cualquier ruta rota)
├── revista.html         Índice de la Revista Jurídica
├── blog.js              Lógica de la revista (independiente de app.js)
├── blog.json             Artículos publicados de la revista — juridica.py lo escribe
├── revista/              Página estática por artículo (las genera build_pages.py)
├── blog/
│   ├── borradores/      Artículos entregados, pendientes de dictamen
│   ├── publicados/       Respaldo del .md original ya publicado
│   └── rechazados/       Retirados por el consejo editorial + su .veredicto.json
├── testimonios.json      Reseñas de lectores publicadas — resenas.py lo escribe
├── resenas/
│   ├── borradores/      Reseñas entregadas, pendientes de moderación
│   ├── publicadas/       Respaldo del .md original ya publicado
│   └── rechazadas/       Retiradas por el consejo editorial + su .veredicto.json
├── sitemap.xml          Índice para buscadores (generado)
├── robots.txt           Directivas para crawlers (generado)
├── manifest.json        PWA: nombre, iconos, colores
├── assets/               Favicon, iconos, imágenes OG y arte por categoría
├── agent/
│   ├── agent.py         Agente 1: lector-analista-publicador (noticias + literatura)
│   ├── quality.py       Agente 2: control de calidad (filtra antes de publicar)
│   ├── juridica.py       Pipeline de la Revista Jurídica (análisis + dictamen fail-closed)
│   ├── resenas.py        Pipeline de reseñas de lectores (moderación fail-closed)
│   ├── supabase_client.py  Cliente REST mínimo para leer/actualizar envíos (jurídica + reseñas)
│   ├── budget.py         Tope de gasto diario compartido por los 4 agentes
│   ├── build_pages.py   Generador de páginas por artículo + sitemap (sin API)
│   ├── run_local.sh      Corre un ciclo leyendo la clave de agent/.env (modo manual)
│   ├── seen_urls.json    Memoria de deduplicación (se crea solo)
│   ├── qc_log.json       Bitácora de veredictos del QC (se crea solo)
│   └── spend_log.json    Gasto acumulado del día en la API (se crea solo, se reinicia al cambiar el día)
└── .github/workflows/
    ├── agente.yml      Noticias + literatura: ejecución automática cada hora con GitHub Actions
    └── moderacion.yml   Revista jurídica + reseñas: cada 3 horas (cadencia propia, menor volumen)
```

## Cómo funciona el agente

Cada ciclo:
1. **Lee** los 21 feeds RSS de las fuentes configuradas (ver `SOURCES` en
   `agent/agent.py` y el Panel de fuentes más abajo).
2. **Deduplica** contra lo ya publicado.
3. **Lee la nota completa** de cada candidata (no solo el extracto del feed)
   antes de analizarla — `fetch_article_text()`, agregado el 10 jul 2026.
4. **Busca coberturas del mismo hecho en otros medios** dentro del pool del
   propio ciclo (`find_related_entries()`, mismo día) y se las da al modelo
   como material real de comparación — así "contraste de fuentes" se
   califica con evidencia real, no con lo que el modelo ya sabía de fondo.
5. **Analiza** cada nota nueva con Claude: resumen con palabras propias,
   score de sesgo (-100 a +100), razón del score, enfoque editorial,
   etiquetas y 3 puntos de contexto.
6. **Control de calidad**: un segundo agente (`quality.py`) evalúa cada
   artículo contra su rúbrica editorial y rechaza lo que no da el ancho
   (ver sección siguiente).
7. **Publica** escribiendo `articles.json`; el portal lo consume al instante.
8. **Genera las páginas**: `build_pages.py` crea una página estática por nota
   (`articulo/<id>.html`) con metadatos para compartir en redes (Open Graph)
   y para buscadores (JSON-LD, sitemap.xml) — así cada nota tiene URL propia.

⚖️ El agente nunca copia el texto de la nota — resume, analiza y enlaza al
original. Republicar contenido de los medios violaría sus derechos de autor.

## Control de calidad: el segundo agente

Antes de publicar, **cada artículo pasa por `agent/quality.py`**, que lo
califica de 0 a 10 en cinco criterios según su tipo:

**📰 Noticias** — el objetivo es informar sobre hechos reales con objetividad:

| Criterio | Qué evalúa |
|---|---|
| Veracidad y precisión | Datos, fechas, nombres y citas exactos y comprobables; sin contradicciones internas |
| Contraste de fuentes | Información de fuentes confiables y diversas; el paquete muestra distintas caras del tema |
| Objetividad e imparcialidad | Hechos sin opiniones personales; toda valoración está atribuida |
| Actualidad | Información reciente y oportuna (notas de más de 7 días se rechazan automáticamente) |
| Estructura | Pirámide invertida: lo más importante abre el resumen |

**📚 Literatura** (pieza de mano libre) — el objetivo es explorar la condición
humana y generar una experiencia estética:

| Criterio | Qué evalúa |
|---|---|
| Originalidad y creatividad | Enfoque, trama o lenguaje con perspectiva única; sin lugares comunes |
| Riqueza y estilo del lenguaje | Recursos retóricos (metáforas, símiles) y vocabulario preciso y evocador |
| Estructura narrativa | Coherencia interna, ritmo adecuado, desarrollo sólido de las ideas |
| Voz del autor | Tono consistente y reconocible en todo el texto |
| Profundidad temática | Invita a la reflexión; valor simbólico o universal |

**Regla de aprobación:** promedio ≥ 7.0 **y** ningún criterio por debajo de 5.
Todos los veredictos (aprobados y rechazados) quedan en `agent/qc_log.json`.
Si el QC falla por un error técnico (red, API caída), la nota se publica con
advertencia — el filtro es de calidad, no debe tumbar el portal por un
problema de conexión. Si la pieza literaria del día es rechazada, el
siguiente ciclo genera una nueva.

## Contacto y protección anti-spam

Dos canales, cada uno con su razón de ser:

- **Reportar un error** (`correcciones.html`): botón a GitHub Issues. GitHub
  le avisa al editor por correo sin que la dirección aparezca en ninguna
  página — el reporte además queda público y auditable.
- **Enviar un artículo a la revista** (`revista.html`) y **dejar una reseña**
  (portada, "Correo del lector"): son formularios reales que insertan
  directo en Supabase (ver "Envíos de usuarios (Supabase)" más abajo) — ya
  no dependen de un correo, así que no hay dirección que ofuscar ahí. La
  protección contra spam en estos dos es otra: un campo honeypot oculto por
  CSS, más el hecho de que nada se publica sin pasar moderación (fail-closed).

Si algún día agregas un correo de contacto DIRECTO en el sitio (no vía
formulario/Issues), sigue el patrón anterior — ensámblalo en tiempo de
ejecución partido en fragmentos, nunca lo escribas literal en un `.html`.

## Antes de lanzar al público — pendientes que debes personalizar

- [x] **Contacto**: resuelto con el esquema de arriba.
- [ ] **Vercel — Deployment Protection**: revisa Project Settings →
      Deployment Protection. Si "Vercel Authentication" está activo para
      Production, el sitio queda detrás del login de Vercel y nadie fuera
      de tu equipo puede verlo (se detectó activo el 13 jul 2026, probando
      la URL de producción a mano — devolvía la pantalla de login de
      Vercel en vez del sitio).
- [ ] **Supabase**: crear el proyecto, correr el SQL, y pegar `SUPABASE_URL`/
      `SUPABASE_ANON_KEY` en `blog.js` y `app.js` + `SUPABASE_SERVICE_ROLE_KEY`
      en `agent/.env` y en los secretos de Actions — ver "Envíos de usuarios
      (Supabase)" más abajo. Sin esto, los formularios de la revista y de
      reseñas no tienen a dónde enviar (fallan con un mensaje claro, no
      publican nada, pero tampoco guardan el envío del lector).
- [ ] **`correcciones.html`**: al crear el repositorio, reemplaza
      `TU-USUARIO/TU-REPOSITORIO` en el botón de Issues (hay un `TODO`).
- [ ] **Analytics (opcional)**: en `index.html` hay un snippet de Plausible
      comentado con instrucciones. Si lo activas, actualiza también la
      sección de privacidad en `legal.html`.
- [ ] **Search Console**: verifica el sitio y envía el sitemap (pasos en
      la sección "Vigilancia y salud del portal").
- [ ] **Watch al repositorio** en GitHub para recibir los Issues que abre
      el agente cuando un ciclo falla.
- [ ] `sitemap.xml` y `robots.txt` se regeneran solos en cada ciclo de
      GitHub Actions con la URL real del sitio — pero solo si definiste la
      variable de repo `SITE_BASE_URL` con tu dominio de Vercel (ver
      "Despliegue automático 24/7" más abajo); sin ella, caen de vuelta a
      un dominio de GitHub Pages que no es el que sirve el sitio.

## Puesta en marcha local

```bash
pip install feedparser requests
export ANTHROPIC_API_KEY="tu-clave"   # consíguela en console.anthropic.com

# un solo ciclo:
python agent/agent.py

# modo vigilante (ciclo cada hora, corre indefinidamente):
python agent/agent.py --loop 3600

# servir el portal:
python -m http.server 8000
# abre http://localhost:8000

# regenerar las páginas por artículo sin correr el agente (no usa API):
python agent/build_pages.py
```

## Proveedor de LLM: Anthropic (Claude) o Inception Labs (Mercury)

Agregado el 10 jul 2026: `agent/llm_client.py` es un interruptor que deja
correr el pipeline con **Mercury** (Inception Labs) en vez de Claude —
útil para probar sin gastar crédito de Anthropic, ya que una cuenta nueva
en [platform.inceptionlabs.ai](https://platform.inceptionlabs.ai/) trae 10M
tokens gratis, sin tarjeta.

**Cómo cambiar:** una sola variable de entorno, `LLM_PROVIDER`:
- `LLM_PROVIDER=inception` (o sin definir nada más) → usa Mercury. Necesita
  `INCEPTION_API_KEY` (Dashboard → API Keys en platform.inceptionlabs.ai).
- `LLM_PROVIDER=anthropic`, o **borrar la variable** → vuelve a Claude de
  siempre (`ANTHROPIC_API_KEY`).

Dónde poner el interruptor:
- **Local:** en `agent/.env` (ya viene con `LLM_PROVIDER=inception` puesto).
- **GitHub Actions:** en el `env:` de los pasos que llaman al agente, en
  `agente.yml` y `moderacion.yml` (ya vienen en `inception` — cambiá la
  línea `LLM_PROVIDER: inception` a `anthropic` en los dos archivos para
  volver a Claude en producción). El secreto `INCEPTION_API_KEY` hay que
  cargarlo en *Settings → Secrets and variables → Actions* si todavía no
  existe.

⚠ **Esto es un cambio temporal, no la arquitectura objetivo.** Mercury es
un solo modelo genérico — no tiene el ajuste fino que sí tiene el diseño de
Anthropic (Sonnet 5 para el volumen alto, Fable 5 solo para la pieza
literaria diaria, ver sección "Costo" más abajo). `agent.py`/`quality.py`
siguen pidiendo sus modelos de Claude de siempre (`ANALYSIS_MODEL`,
`LITERATURE_MODEL`, etc.) — `llm_client.call_llm()` los ignora y usa
Mercury mientras el interruptor esté en "inception", así que no hace falta
tocar esos archivos para alternar entre proveedores.

## Modo manual — activar el agente tú mismo, cuando quieras

Antes de automatizar con GitHub Actions (que corre cada hora sin supervisión
y gasta crédito solo), puedes correr el agente a mano cada vez que decidas —
útil mientras controlas el gasto o pruebas cambios.

**Una sola vez**, guarda tu clave en un archivo local (nunca se sube a git,
ya está en `.gitignore`):

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-tu-clave-aqui' > agent/.env
chmod +x agent/run_local.sh
```

**Cada vez que quieras un ciclo nuevo**, un solo comando:

```bash
./agent/run_local.sh
```

Lee `agent/.env`, corre un ciclo (feeds → análisis → QC → literatura → QC →
páginas), y termina — sin dejar nada corriendo de fondo. Revista jurídica y
reseñas de lectores ya no corren dentro de `agent.py`; usa
`python agent/juridica.py` o `python agent/resenas.py` para dictaminarlas a
mano (o espera al cron de `moderacion.yml`). Para ver el resultado, sirve el
portal como arriba (`python -m http.server 8000`) y recarga el navegador.

**`MAX_NEW_PER_CYCLE` es una meta de publicación, no un tope de análisis**: el
agente sigue tomando más candidatas del pool de feeds (`fresh`, normalmente
muy por encima de 6) si el QC va rechazando, hasta publicar esa cantidad —
nunca baja la vara del QC para forzar el número. El techo real de gasto por
ciclo lo pone `MAX_ANALYSIS_ATTEMPTS` (4× `MAX_NEW_PER_CYCLE` por defecto):
si se llega a ese techo sin completar la meta, el ciclo publica lo que
alcanzó y lo deja explícito en el log — un día de mala calidad en los feeds
publica menos, no publica peor.

**Para controlar el gasto de cada corrida**, tenés dos palancas:
1. `MAX_NEW_PER_CYCLE` en `agent/agent.py` (por defecto 6 notas — cada
   corrida son, en el peor caso, `MAX_ANALYSIS_ATTEMPTS` notas × 2 llamadas
   + 1 pieza literaria × 2 llamadas). Bájalo a 2 o 3 mientras pruebas para
   gastar menos por corrida.
2. `DAILY_BUDGET_USD` en `agent/budget.py` — un dict con **dos bolsas
   independientes**, no un tope compartido: `news` ($4/día por defecto,
   para `agente.yml`) y `moderation` ($1/día, para `moderacion.yml`), suma
   **$5/día**. Agotar una no le quita presupuesto a la otra — así
   jurídica/reseñas nunca compite por cupo con el flujo de noticias, que es
   la cola de mayor volumen desde el arranque. En cuanto una bolsa se agota,
   cualquier llamada nueva de esa cola se omite sola por el resto del día
   (UTC), sin publicar nada a medio revisar. Ajusta la proporción según el
   volumen real que veas en cada cola — pero la suma de ambas nunca puede
   pasar de `MAX_TOTAL_DAILY_BUDGET_USD` (**$7/día**, techo duro: si lo
   superás, el agente ni siquiera arranca).

## Despliegue automático 24/7 (GitHub Actions + Vercel)

Esta carpeta (`01-contexto-portal`) **es la raíz del repositorio** — no subas
la carpeta maestra `Claude-Trabajos` completa; los tres workflows
(`agente.yml`, `moderacion.yml`, `resumen-diario.yml`) asumen rutas
relativas a esta carpeta (`articles.json`, `agent/agent.py`, etc., sin
ningún prefijo).

El dominio público real es **Vercel** (no GitHub Pages — decisión del 12 jul
2026), conectado directo al repo de GitHub para redesplegar solo en cada
push. Los agentes (`agente.yml`/`moderacion.yml`) solo hacen commit de los
archivos que cambiaron; Vercel se encarga de servir esa nueva versión.

1. Sube esta carpeta a un repositorio nuevo de GitHub (raíz = esta carpeta).
2. En [vercel.com](https://vercel.com), entra con tu cuenta de GitHub →
   **Add New → Project** → elige ese repositorio. **Root Directory:**
   déjalo en blanco/raíz (NO pongas `01-contexto-portal` — el repo entero
   ya es esa carpeta). **Framework Preset:** "Other". **Build Command:**
   vacío. **Output Directory:** `.`. **Deploy.**
3. Revisa **Project Settings → Deployment Protection** en Vercel: si
   "Vercel Authentication" está activo para Production, el sitio queda
   detrás del login de Vercel y nadie fuera de tu equipo puede verlo —
   desactívalo (o déjalo solo para Preview Deployments) antes de anunciar
   el sitio.
4. En **Settings → Secrets and variables → Actions** del repo de GitHub,
   carga los secretos que uses (`ANTHROPIC_API_KEY` y/o
   `INCEPTION_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, y
   opcionalmente `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`) y, en la pestaña
   **Variables** (no secreta, es solo texto público), `SITE_BASE_URL` con
   tu dominio real de Vercel — sin esto, `sitemap.xml` y las etiquetas
   canónicas/OG caen de vuelta a un dominio de GitHub Pages que no es el
   que de verdad sirve el sitio.
5. Listo: `agente.yml` corre cada hora (noticias + literatura) y
   `moderacion.yml` cada 3 horas (revista jurídica + reseñas), ambos hacen
   commit; Vercel redespliega solo con cada commit. Los dos workflows
   comparten el mismo tope de gasto diario (`agent/budget.py` +
   `agent/spend_log.json`).

Alternativas: un VPS con `cron` (`*/30 * * * * python /ruta/agent/agent.py`),
o servicios como Railway/Render con un worker.

### Docker para desarrollo local (opcional, agregado el 10 jul 2026)

**Esto NO reemplaza GitHub Actions en producción** — sigue siendo la forma
recomendada de correr Contexto 24/7, gratis y sin depender de que ninguna
máquina tuya esté prendida. `Dockerfile` y `docker-compose.yml` (en la raíz
de este proyecto) son para probar el pipeline completo en tu compu antes de
subir un cambio, con las mismas dependencias siempre, igual que tus otros
proyectos en contenedores.

```bash
docker compose run --rm agente        # un ciclo del agente de noticias
docker compose run --rm moderacion    # un ciclo de revista jurídica + reseñas
docker compose up portal              # sirve el sitio en http://localhost:8000
```

Lee las variables de `agent/.env` (mismo archivo que usa
`agent/run_local.sh`, no hay que duplicar nada) — así que también respeta
el interruptor `LLM_PROVIDER` de la sección anterior.

## Funciones interactivas del portal

- **Búsqueda instantánea** (en la portada, junto al termómetro): filtra las
  tarjetas por título, resumen, fuente o etiquetas mientras escribes, sin
  llamadas a red; se combina con el filtro de categoría. Vive en `app.js`.
- **Botón de compartir** (en cada página de artículo, de noticia o de la
  Revista Jurídica): usa el share nativo del sistema si está disponible, o
  copia el enlace al portapapeles con una confirmación visual. Vive en
  `share.js`, un solo script compartido por ambas plantillas.
- **Hemeroteca** (`hemeroteca.html`): el archivo completo del portal,
  agrupado por día de publicación, más reciente primero — útil para volver
  a una nota de hace unos días o ver de un vistazo cuánto se ha publicado.
- **Termómetro del día** (en la portada): promedia el `bias_score` de las
  notas publicadas hoy (o las más recientes si aún no hay del día) y muestra
  qué tan polarizada estuvo la cobertura. Cálculo 100% en el navegador,
  sin llamadas a la API — vive en `app.js`.
- **Brújula editorial** (`brujula.html` + `compass.js`): seis afirmaciones
  tipo Likert sobre economía y sociedad (deliberadamente generales, sin
  coyuntura partidista mexicana) ubican al lector en el mismo espectro
  -100..+100 que usamos para las notas, y lo comparan con su "dieta
  informativa" ya guardada en `localStorage`. Nada se envía a ningún
  servidor; el resultado se olvida al recargar.
- **Glosario editorial** (`glosario.html`): términos del oficio explicados
  sin jerga (pirámide invertida, encuadre, sesgo de confirmación...),
  enlazado desde "Cómo lo medimos".
- **Correo del lector** (en la portada, sección `.reader-letters`): reseñas
  **reales**, moderadas por el consejo editorial antes de publicarse — ver
  la sección siguiente. Sin reseñas todavía, se muestra un estado vacío
  honesto en vez de testimonios de ejemplo.

## Revista Jurídica: el blog con consejo editorial automático

Sección de artículos jurídicos de **distribución gratuita**, escritos por
humanos y dictaminados por los agentes antes de publicarse.

**Cómo publicar un artículo (desde el 10 jul 2026):**
1. El autor llena el formulario de `revista.html` (título, nombre, texto en
   Markdown) y lo envía. El botón inserta directo en Supabase — tabla
   `jur_submissions`, `status='pending'` — sin backend propio, sin correo de
   por medio (antes esto era un `mailto:` y alguien copiaba el texto a mano;
   ver "Envíos de usuarios (Supabase)" más abajo para el porqué del cambio).
2. Corre un ciclo de moderación (`python agent/juridica.py`, o espera al
   cron de `moderacion.yml`).
3. El pipeline hace dos pasadas: **análisis editorial** (Sonnet 5 genera el
   abstract y las áreas del derecho) y **dictamen del consejo editorial**
   (Fable 5, rúbrica de 5 criterios: rigor jurídico, claridad, ética y
   deontología, estructura académica, y aporte).
4. **Aprobado** (promedio ≥ 7.0, ningún criterio < 5) → se publica en
   `blog.json`, obtiene página propia en `revista/<id>.html`, aparece en
   `revista.html` y la fila en Supabase pasa a `status='published'`.
   **Inapropiado** → la fila pasa a `status='rejected'` con el veredicto en
   la columna `veredicto`. El criterio de ética castiga con dureza
   difamación, datos personales, incitación a evadir la ley y asesoría
   legal indebida.

A diferencia de las noticias, la moderación es **fail-closed**: si la API
(de Anthropic o de Supabase) falla, el envío sigue `pending` y se reintenta
en el siguiente ciclo — nada se publica sin dictamen. Hay un ejemplo de
artículo aprobado visible en la revista, respaldo del flujo anterior en
`blog/` (ya no se usa para envíos nuevos).

## Correo del lector: reseñas reales con moderación automática

Mismo patrón que la Revista Jurídica, aplicado a los testimonios de la
portada — nada de citas inventadas.

**Cómo se publica una reseña real (desde el 10 jul 2026):**
1. Un lector llena el formulario **"Dejar mi reseña"** de la portada
   (nombre, ocupación opcional, texto) y lo envía — inserta directo en
   Supabase, tabla `resena_submissions`, `status='pending'`.
2. Corre un ciclo de moderación (`python agent/resenas.py`, o espera al
   cron). El consejo editorial (Fable 5, rúbrica de 5 criterios:
   autenticidad del tono, pertinencia, ética/moderación, extensión adecuada
   y claridad) dictamina la reseña — sin paso de análisis previo, va
   directo a QC.
3. **Aprobada** (promedio ≥ 7.0, ningún criterio < 5) → se publica en
   `testimonios.json`, aparece de inmediato en "Correo del lector" y la
   fila pasa a `status='published'`. **Inapropiada** → la fila pasa a
   `status='rejected'` con su veredicto. El criterio de ética castiga con
   dureza insultos o acusaciones contra terceros identificables, discurso
   de odio y contenido promocional.

Igual que la revista, la moderación es **fail-closed**: un error técnico
nunca publica una reseña sin dictamen — queda pendiente para el siguiente
ciclo. Respaldo del flujo anterior en `resenas/` (ya no se usa para envíos
nuevos).

## Envíos de usuarios (Supabase)

Hasta el 9 jul 2026, publicar un artículo jurídico o una reseña era 100%
manual: el botón abría un `mailto:`, el lector escribía, y alguien copiaba
el texto a mano a un `.md` en `blog/borradores/` o `resenas/borradores/`
antes de que el pipeline pudiera procesarlo — cuello de botella real si la
revista crece. Ahora los formularios de `revista.html` e `index.html`
insertan directo en una base de datos de Supabase; `juridica.py`/`resenas.py`
leen de ahí (`agent/supabase_client.py`) en vez de archivos.

**Por qué Supabase y no una base de datos completa para todo el portal:**
el pipeline de noticias (`articles.json`) sigue siendo 100% archivos — no
necesita base de datos, funciona bien tal como está. Solo los envíos de
usuarios (que antes dependían de un humano copiando correos) se movieron a
Supabase.

**Sin SDK nuevo**: `agent/supabase_client.py` habla con la REST de Supabase
(PostgREST) por `requests` directo, mismo estilo que la API de Anthropic —
sigue siendo `pip install feedparser requests`, nada más.

**Configurarlo (una sola vez):**
1. Crea un proyecto gratis en [supabase.com](https://supabase.com).
2. En el SQL Editor del proyecto, corre:
   ```sql
   create table jur_submissions (
     id uuid primary key default gen_random_uuid(),
     titulo text not null,
     autor text not null,
     body_md text not null,
     status text not null default 'pending',
     veredicto jsonb,
     created_at timestamptz not null default now(),
     processed_at timestamptz
   );

   create table resena_submissions (
     id uuid primary key default gen_random_uuid(),
     nombre text not null,
     ocupacion text,
     texto text not null,
     status text not null default 'pending',
     veredicto jsonb,
     created_at timestamptz not null default now(),
     processed_at timestamptz
   );

   alter table jur_submissions enable row level security;
   alter table resena_submissions enable row level security;

   create policy "insert propio" on jur_submissions for insert to anon with check (true);
   create policy "insert propio" on resena_submissions for insert to anon with check (true);
   -- sin política de select/update/delete para "anon": el frontend puede
   -- insertar pero nunca leer/editar envíos de otros. service_role (backend)
   -- se salta RLS por diseño de Supabase, no necesita política propia.
   ```
3. En **Project Settings → API**, copia el **Project URL** y el **`anon`
   public key** — pégalos en `SUPABASE_URL`/`SUPABASE_ANON_KEY` en `blog.js`
   y `app.js` (los dos archivos, son valores duplicados a propósito — no hay
   paso de build que los inyecte).
4. Copia también el **`service_role` key** (¡ese sí es secreto!) y agrégalo
   a `agent/.env` para pruebas locales (`SUPABASE_SERVICE_ROLE_KEY=...`,
   junto a `SUPABASE_URL=...`) y como secreto de GitHub Actions
   (`Settings → Secrets and variables → Actions`) para `moderacion.yml`.

**Dos credenciales, dos niveles de confianza** — no las confundas: el `anon`
key es público a propósito (protegido por las políticas RLS de arriba, no
por secretismo) y vive literal en el HTML/JS servido al navegador; el
`service_role` key se salta RLS por completo y **nunca** debe llegar al
frontend ni a un commit.

**Anti-spam**: cada formulario lleva un honeypot (`input[name="website"]`
oculto por CSS — un bot que rellena todos los campos lo llena, un humano
nunca lo ve) que descarta el envío en el navegador sin llamar a Supabase.
No hay captcha todavía; el backstop real es que `quality.py` es fail-closed
y `budget.py` topa la bolsa `moderation` en $1/día — en el peor caso, un
ataque de spam agota el presupuesto del día sin publicar nada.

## Vigilancia y salud del portal

El portal se publica solo, así que necesita avisarte cuando algo se rompa:

**1. Aviso automático de fallos (ya integrado).** Si un ciclo del agente
falla, el workflow abre un Issue en el repositorio con el enlace al log
(y si ya hay uno abierto, le agrega un comentario en vez de duplicarlo).
Para enterarte al instante: en GitHub, dale **Watch → All Activity** a tu
propio repositorio, o revisa que en *Settings → Notifications → Actions*
esté activo el aviso de workflows fallidos.

**1.b Aviso por Telegram (opcional, agregado el 10 jul 2026).** Además del
Issue, ambos workflows (`agente.yml` y `moderacion.yml`) intentan mandar un
mensaje de Telegram cuando un ciclo falla — llamada directa a la API de
Telegram desde GitHub Actions, **sin pasar por N8N ni por ninguna máquina
propia**: así el aviso llega siempre, esté tu compu prendida o no. Para
activarlo, agrega estos dos secretos en *Settings → Secrets and variables →
Actions*:
- `TELEGRAM_BOT_TOKEN`: el token que te dio @BotFather.
- `TELEGRAM_CHAT_ID`: el ID numérico de tu chat con el bot (lo obtenés
  mandándole cualquier mensaje al bot y mirando `message.chat.id` en la
  respuesta del trigger, si tenés un flujo de N8N con ese bot, o con
  `https://api.telegram.org/bot<TOKEN>/getUpdates`).

Si no configuras estos secretos, el paso se omite solo (no rompe el
workflow) y el aviso por Issue de GitHub sigue funcionando igual.

**1.c Más avisos por Telegram (mismos dos secretos, agregado el 10 jul
2026).** Con `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` configurados, además
del aviso de fallos llegan estos tres — **ninguno llama a la API de
Anthropic**, todos son gratis:

- **Envíos nuevos pendientes** (`moderacion.yml`, antes de dictaminar):
  cuenta cuántos artículos de la revista y reseñas están `pending` en
  Supabase (consulta directa a la REST de Supabase) y avisa si hay alguno,
  antes de que el ciclo los procese.
- **Presupuesto cerca del techo** (`agente.yml` y `moderacion.yml`, al
  final de cada ciclo): si una bolsa (`news` o `moderation`) alcanza el 80%
  de su tope diario, avisa una sola vez por día — usa
  `budget.budget_warning_needed()`, que marca el aviso como enviado en
  `agent/alert_state.json` (se reinicia solo al cambiar el día, igual que
  `spend_log.json`) para no repetirlo en cada ciclo restante del día.
- **Resumen diario** (`resumen-diario.yml`, nuevo workflow, corre solo a
  las 23:50 UTC): cuenta lo aprobado/rechazado por el QC ese día (lee
  `agent/qc_log.json`) y el gasto acumulado (lee `agent/spend_log.json`) —
  no vuelve a analizar nada, solo lee archivos que los otros dos workflows
  ya generaron. Corre en su propio horario a propósito, desacoplado de los
  ciclos de publicación (mismo criterio que separa `agente.yml` de
  `moderacion.yml`, ver `ARQUITECTURA.md`).

**2. Google Search Console (hazlo al desplegar).** Es el complemento del
`sitemap.xml`: te dice si Google indexa tus páginas y con qué búsquedas
llega la gente. Pasos:
   1. Entra a https://search.google.com/search-console con tu cuenta.
   2. Agrega la propiedad con la URL de tu sitio (la de GitHub Pages).
   3. Método de verificación: **Etiqueta HTML**. Google te da un código;
      pégalo en la línea `google-site-verification` que está comentada en
      el `<head>` de `index.html` y descoméntala. Sube el cambio.
   4. Ya verificado, ve a **Sitemaps** y envía `sitemap.xml`.
   5. En unos días verás qué páginas indexó y los errores que encuentre.

**3. Monitoreo de uptime (opcional).** GitHub Pages rara vez se cae, pero
si quieres el cinturón y los tirantes: https://uptimerobot.com (gratis)
puede revisar tu URL cada 5 minutos y avisarte por correo si no responde.

**Detalles del workflow que ya quedaron blindados:** los ciclos nunca se
enciman (`concurrency`), un ciclo colgado se corta a los 15 minutos
(`timeout-minutes`), y GitHub desactiva los crons tras 60 días sin
actividad — los commits del propio agente la mantienen viva.

## Panel de fuentes: análisis de credibilidad

Criterios usados para incluir una fuente: trayectoria verificable, redacción
profesional con correcciones públicas, autoría identificable, y separación
razonable entre información y opinión. Que una fuente tenga línea editorial
marcada **no la descalifica** — al contrario, tener fuentes de distintos puntos
del espectro es lo que permite triangular; el espectro de cada nota se encarga
de transparentar la inclinación.

| Fuente | Perfil | Inclinación típica | Por qué está en el panel |
|---|---|---|---|
| El Economista | Economía y finanzas MX | Centro / pro-mercado | Especialización técnica, datos verificables |
| El Universal | Diario generalista MX | Centro | Uno de los diarios de mayor trayectoria del país |
| Periódico AM (León) | Local Bajío | Centro | Cobertura local que los nacionales no dan |
| **Aristegui Noticias** | Investigación | Centro-izquierda / crítico del poder | Investigaciones de alto impacto; línea conocida y estable |
| **Etcétera** | Medios y rendición de cuentas | Centro-izquierda | Crítica de medios y periodismo; trayectoria desde 1988 |
| **La Jornada** | Diario generalista | Izquierda | Contrapeso editorial explícito; útil para triangular con Reforma/El Economista |
| **Reforma** | Diario generalista | Centro-derecha / crítico del oficialismo | Uno de los diarios de mayor trayectoria e investigación del país; contrapeso de La Jornada |
| **El Informador (GDL)** | Regional Jalisco | Centro | Diario regional centenario, complementa la mirada local |
| **Infobae México** | Generalista digital | Centro | Cobertura amplia de México (seguridad, sociedad, entretenimiento); gran volumen diario |
| **Expansión** | Negocios y economía | Centro / pro-mercado | Referencia en cobertura empresarial y de mercados en México |
| **BBC News Mundo** | Internacional | Centro | Estatuto de imparcialidad auditado públicamente |
| **El País América** | Internacional | Centro-izquierda | Referencia iberoamericana con corrección pública de errores |
| **DW Español** | Internacional | Centro | Medio público alemán con carta editorial independiente |
| **France24 Español** | Internacional | Centro | Medio público francés, misma familia editorial que DW |
| **La Jornada Deportes** | Deportes | Ídem cabecera | Feed seccional de La Jornada |
| **Infobae Deportes** | Deportes | N/A (encuadres, no política) | Cobertura deportiva de alto volumen, incluye competencias internacionales |
| **Letras Libres** | Revista cultural | Liberal (tradición Paz) | Crítica literaria de primer nivel; su línea intelectual es explícita |
| **La Jornada Cultura** | Cultura | Ídem cabecera | Feed seccional de La Jornada |
| **Xataka** | Tecnología | Centro (foco técnico, no político) | Cubre el hueco real de la categoría "tecnologia": no tenía ninguna fuente propia |
| **Hipertextual** | Tecnología | Centro | Segunda voz en tecnología, para no depender de un solo medio en la categoría |
| **El Sol de México** | Generalista, red OEM | Centro / institucional | Grupo editorial distinto a los demás del panel (OEM); suma volumen y otra ownership |

**Agregadas el 10 jul 2026** (tras encontrar que el pipeline solo aprobaba
~1 de cada 24 candidatas — ver diagnóstico en el historial del proyecto):
Xataka, Hipertextual y El Sol de México, verificadas con respuesta real de
su feed. Se intentó también con Milenio, El Financiero y Récord pero no se
pudo confirmar su feed desde el entorno donde se hizo esta revisión (podría
ser bloqueo anti-bot del lado del feed, o solo una limitación de esa
verificación puntual) — si te interesan, prueba tú directamente
`python -c "import feedparser; print(feedparser.parse('URL').entries[:3])"`
y agrégalas a `SOURCES` si responden.

**Retiradas del panel (9 jul 2026):** Forbes México (su feed ahora exige un
token de autenticación, ya no es RSS público), Latinus (la URL del feed
devuelve la página de inicio en HTML, no un feed real), NYT en Español (el
sitio en español está discontinuado, responde 403 en todas las rutas),
Animal Político (retiró su RSS — 404 en todas las rutas conocidas) y ESPN
Deportes (bloqueo/redirect en bucle). El agente ya no puede leerlas; si algún
día vuelven a publicar un feed válido, pueden reincorporarse.

Fuentes evaluadas y **no incluidas** por ahora: agregadores sin autoría clara,
portales que viven del clickbait, y medios sin política de correcciones. Proceso
y SinEmbargo son periodísticamente sólidos pero devuelven 403 al pedir su feed
(protección anti-scraping o token requerido) — si encuentras una URL de RSS
vigente para cualquiera de los dos, vale la pena agregarlos.

⚠ Las URLs de los feeds cambian con el tiempo. El agente reporta en el log los
que fallan; verifica en el sitio de cada medio la URL vigente.

## La sección de Literatura: mano libre del agente

Además de analizar notas culturales de los feeds (Letras Libres, La Jornada
Cultura), el agente publica **una pieza propia al día** con total libertad
temática: recomendaciones de libros, perfiles de autores, efemérides,
reflexiones. Estas piezas:

- Se marcan visualmente como **"Pieza de mano libre"** — sin espectro de
  sesgo, porque no analizan la cobertura de un medio: son un punto de vista
  asumido como propio.
- Reciben la lista de piezas recientes para no repetir temas.
- Tienen prohibido citar versos o pasajes textuales (derechos de autor):
  describen, recomiendan y contextualizan con palabras propias.
- Solo recomiendan obras y autores reales que el modelo conoce con certeza.

## Ajustes frecuentes

| Qué quiero cambiar | Dónde |
|---|---|
| Agregar/quitar fuentes | Lista `SOURCES` en `agent/agent.py` |
| Frecuencia del ciclo de noticias | `cron:` en `agente.yml` o `--loop N` |
| Frecuencia de moderación (revista/reseñas) | `cron:` en `moderacion.yml` (cada 3 h por defecto — subir cuando haya más volumen de borradores) |
| Cuántas notas publica por ciclo (meta, no tope) | `MAX_NEW_PER_CYCLE` |
| Techo de intentos si el QC rechaza (costo máximo) | `MAX_ANALYSIS_ATTEMPTS` |
| Cuántas notas viven en el portal | `MAX_ARTICLES_KEPT` |
| Cuántas entradas por feed se leen (no cuesta API) | `parsed.entries[:25]` en `fetch_new_entries()`, `agent/agent.py` |
| Tope de gasto diario (los 4 agentes) | `DAILY_BUDGET_USD` en `agent/budget.py` |
| Criterios del análisis de sesgo | `ANALYSIS_SYSTEM_PROMPT` |
| Categorías del portal | `VALID_CATEGORIES` + botones en `index.html` |
| Umbrales del control de calidad | `APPROVAL_THRESHOLD`, `MIN_CRITERION`, `MAX_AGE_DAYS` en `agent/quality.py` |
| Rúbricas del control de calidad | `NEWS_QC_PROMPT`, `LIT_QC_PROMPT`, `JUR_QC_PROMPT`, `RESENA_QC_PROMPT` en `agent/quality.py` |
| Modelos usados | `ANALYSIS_MODEL` / `LITERATURE_MODEL` en `agent.py`; `NEWS_QC_MODEL` / `LIT_QC_MODEL` / `JUR_QC_MODEL` / `RESENA_QC_MODEL` en `quality.py` |
| Umbral de aviso de presupuesto (% del tope diario) | `threshold` en `budget.budget_warning_needed()` (80% por defecto) |
| Hora del resumen diario de Telegram | `cron:` en `.github/workflows/resumen-diario.yml` (23:50 UTC por defecto) |
| Proveedor de LLM (Anthropic ↔ Inception/Mercury) | `LLM_PROVIDER` en `agent/.env` (local) o en el `env:` de `agente.yml`/`moderacion.yml` (producción) |

## Notas importantes

- **Verifica los feeds RSS**: los medios cambian sus URLs de feed con
  frecuencia. Si uno falla, el agente lo reporta en el log y sigue con los
  demás. Busca "RSS" en el sitio de cada medio para la URL vigente.
- **El análisis de sesgo es una guía, no un veredicto**: el propio portal lo
  aclara en su sección de metodología. El modelo evalúa lenguaje, fuentes y
  encuadre del extracto disponible; con extractos muy cortos la confianza
  baja y así se marca en cada nota.
- **Nada de referencias ambiguas**: el `ANALYSIS_SYSTEM_PROMPT` exige que la
  primera mención de cualquier sujeto (equipo, ley, institución, persona)
  incluya su nombre completo y contexto — "la selección mexicana de futbol
  varonil", nunca solo "la selección". Evita resúmenes que solo tienen
  sentido si ya leíste el titular original. Esto aplica a notas analizadas
  a partir de este cambio; las 5 de ejemplo del repo son anteriores.
- **Costo**: cada nota consume 2 llamadas a la API (análisis + control de
  calidad). El portal usa dos modelos distintos según el volumen de cada
  tarea:
  - **Claude Sonnet 5** para noticias (análisis + QC) — corre decenas de
    veces al día, es el grueso del costo. Con notas reales de ~2,000
    tokens de entrada y ~800 de salida por nota (ambas llamadas), cada
    nota cuesta ~$0.012 USD. Con 30-80 notas/día, el gasto mensual ronda
    **$11-29 USD**.
  - **Claude Fable 5** para la pieza literaria diaria (generación + QC) —
    solo 2 llamadas al día, así que el modelo más capaz (y más caro,
    $10/$50 por millón de tokens) sale casi gratis en términos absolutos:
    ~$0.06 USD/nota × 1 nota/día ≈ **menos de $2 USD/mes**.

  Ajusta `MAX_NEW_PER_CYCLE` y la frecuencia del cron para controlar el
  gasto de Sonnet 5, que es la variable que más pesa en el total.

- **Tope duro de gasto diario, en dos bolsas separadas**: las estimaciones de
  arriba son eso, estimaciones — el razonamiento de los modelos antes de
  responder hace que el gasto real varíe. `agent/budget.py` pone un límite
  real: cada llamada exitosa registra su costo verdadero (a partir de los
  tokens que reporta la propia API) en `agent/spend_log.json`, con dos
  contadores independientes — `news` (**$4/día**, noticias + literatura) y
  `moderation` (**$1/día**, revista jurídica + reseñas), suma **$5/día**. En
  cuanto una bolsa se agota, cualquier llamada nueva de esa cola se omite
  sola por el resto del día (UTC) — nada se publica a medio revisar, lo
  pendiente se retoma al día siguiente, y la otra bolsa sigue funcionando
  normal. La suma de las dos bolsas tiene además un techo duro de **$7/día**
  (`MAX_TOTAL_DAILY_BUDGET_USD`): si algún ajuste futuro lo supera, el
  agente falla al arrancar en vez de gastar de más en silencio. Verifica el
  gasto real en cualquier momento en console.anthropic.com → Usage.
