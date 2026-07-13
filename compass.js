/* ==========================================================================
   CONTEXTO — compass.js
   Lógica de la brújula editorial (brujula.html): quiz de autoubicación en
   el mismo espectro -100..+100 que usamos para calificar coberturas, y
   comparación con la "dieta informativa" ya guardada en localStorage.
   ========================================================================== */

(function () {
  'use strict';

  const $ = (sel, ctx = document) => ctx.querySelector(sel);
  const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  // dir: +1 si estar de acuerdo inclina a la derecha, -1 si inclina a la izquierda.
  // Afirmaciones generales de economía/sociedad, sin coyuntura partidista de México.
  const QUESTIONS = [
    { id: 'q1', dir: -1, text: 'El Estado debe intervenir activamente en la economía para reducir desigualdades.' },
    { id: 'q2', dir: 1, text: 'Bajar impuestos y reducir regulaciones impulsa más el crecimiento que el gasto público.' },
    { id: 'q3', dir: 1, text: 'Las instituciones y tradiciones establecidas merecen más peso que los cambios acelerados.' },
    { id: 'q4', dir: -1, text: 'La redistribución de la riqueza mediante impuestos progresivos es una prioridad justa.' },
    { id: 'q5', dir: 1, text: 'El libre mercado, más que el gobierno, es quien mejor asigna los recursos.' },
    { id: 'q6', dir: -1, text: 'Ampliar los programas sociales es más urgente que reducir el déficit público.' },
  ];

  const LIKERT = [
    { v: -2, label: 'Muy en desacuerdo' },
    { v: -1, label: 'En desacuerdo' },
    { v: 0, label: 'Neutral' },
    { v: 1, label: 'De acuerdo' },
    { v: 2, label: 'Muy de acuerdo' },
  ];

  const MAX_SCORE = QUESTIONS.length * 2; // suma máxima posible de |dir * v|

  function esc(str) {
    // escapa también comillas (revisión de seguridad 10 jul 2026): el truco
    // textContent->innerHTML solo codifica & < > — pero esc() se usa dentro
    // de atributos (href="...", datetime="..."), donde una comilla doble en
    // el dato rompería el atributo e inyectaría atributos arbitrarios.
    const d = document.createElement('div');
    d.textContent = String(str == null ? '' : str);
    return d.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function spectrumPercent(score) {
    const clamped = Math.max(-100, Math.min(100, Number(score) || 0));
    return ((clamped + 100) / 2).toFixed(1);
  }

  function spectrumVerdict(score) {
    const s = Number(score) || 0;
    if (s <= -60) return { text: 'Marcadamente a la izquierda', cls: 'v-left' };
    if (s <= -25) return { text: 'Inclinada a la izquierda', cls: 'v-left' };
    if (s < 25) return { text: 'Cerca del centro', cls: 'v-center' };
    if (s < 60) return { text: 'Inclinada a la derecha', cls: 'v-right' };
    return { text: 'Marcadamente a la derecha', cls: 'v-right' };
  }

  function sideOf(score) {
    const s = Number(score) || 0;
    return s <= -25 ? 'left' : s >= 25 ? 'right' : 'center';
  }

  function renderQuestions() {
    const wrap = $('#compassQuestions');
    wrap.innerHTML = QUESTIONS.map((q, i) => `
      <fieldset class="compass-question" data-qid="${q.id}">
        <legend>${i + 1}. ${esc(q.text)}</legend>
        <div class="likert-row">
          ${LIKERT.map(l => `
            <label class="likert-option">
              <input type="radio" name="${q.id}" value="${l.v}">
              <span>${esc(l.label)}</span>
            </label>`).join('')}
        </div>
      </fieldset>`).join('');
  }

  function computeScore() {
    let total = 0;
    for (const q of QUESTIONS) {
      const checked = document.querySelector(`input[name="${q.id}"]:checked`);
      if (!checked) return null;
      total += q.dir * Number(checked.value);
    }
    return Math.max(-100, Math.min(100, (total / MAX_SCORE) * 100));
  }

  function loadDiet() {
    try {
      return JSON.parse(localStorage.getItem('contexto-dieta')) || { left: 0, center: 0, right: 0 };
    } catch (_) {
      return { left: 0, center: 0, right: 0 };
    }
  }

  const SIDE_LABEL = { left: 'la izquierda', center: 'el centro', right: 'la derecha' };

  function compareWithDiet(userScore) {
    const diet = loadDiet();
    const total = (diet.left || 0) + (diet.center || 0) + (diet.right || 0);
    if (total < 3) {
      return `Aún no tenemos suficientes datos de tu lectura en Contexto para comparar
        (necesitamos que abras el análisis de al menos 3 notas). Sigue leyendo y
        la próxima vez que vuelvas aquí podrás ver cómo se compara tu propia
        posición con lo que consumes.`;
    }
    const userSide = sideOf(userScore);
    const entries = [['left', diet.left || 0], ['center', diet.center || 0], ['right', diet.right || 0]];
    entries.sort((a, b) => b[1] - a[1]);
    const [topSide, topCount] = entries[0];
    const isTie = entries[1][1] === topCount;

    if (isTie) {
      return `Tu lectura reciente en Contexto está bastante repartida entre los
        distintos ángulos — vas bien encaminado a triangular.`;
    }
    const pct = Math.round((topCount / total) * 100);
    if (topSide === userSide) {
      return `Tu lectura reciente en Contexto se inclina hacia ${SIDE_LABEL[topSide]}
        (${pct}% de lo que has abierto) — coincide con tu propia posición. Vale la
        pena asomarte también al ángulo opuesto de vez en cuando.`;
    }
    return `Interesante: tu lectura reciente en Contexto se inclina hacia
      ${SIDE_LABEL[topSide]} (${pct}% de lo que has abierto), mientras que tú te
      ubicas más hacia ${SIDE_LABEL[userSide]}. Ya estás triangulando sin
      proponértelo.`;
  }

  function showResult(score) {
    const pct = spectrumPercent(score);
    const verdict = spectrumVerdict(score);
    $('#compassMarker').dataset.target = pct;
    $('#compassTrackLabel').setAttribute('aria-label', `Tu posición: ${verdict.text}`);
    $('#compassVerdictText').innerHTML =
      `Te ubicas <span class="spectrum-verdict ${verdict.cls}">${esc(verdict.text)}</span> en este espectro.`;
    $('#compassCompare').textContent = compareWithDiet(score);

    $('#compassForm').hidden = true;
    const result = $('#compassResult');
    result.hidden = false;
    result.scrollIntoView({ behavior: 'smooth', block: 'start' });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      $('#compassMarker').style.left = `${pct}%`;
    }));
  }

  function initForm() {
    renderQuestions();
    $('#compassForm').addEventListener('submit', (e) => {
      e.preventDefault();
      const score = computeScore();
      const errorEl = $('#compassError');
      if (score === null) {
        errorEl.hidden = false;
        errorEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      errorEl.hidden = true;
      showResult(score);
    });
    $('#compassRetry').addEventListener('click', () => {
      $('#compassForm').reset();
      $('#compassForm').hidden = false;
      $('#compassResult').hidden = true;
      $('#compassMarker').style.left = '50%';
      $('#compassForm').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  document.addEventListener('DOMContentLoaded', initForm);
})();
