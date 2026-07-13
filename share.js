/* ==========================================================================
   CONTEXTO — share.js
   Botón de compartir para páginas de artículo (articulo/ y revista/).
   Prioriza el share nativo del sistema (móvil); si no existe, copia el
   enlace al portapapeles con confirmación visual. Sin dependencias,
   cargado también por las páginas estáticas generadas por build_pages.py.
   ========================================================================== */

(function () {
  'use strict';

  async function handleShare(btn) {
    const url = btn.dataset.shareUrl || location.href;
    const title = btn.dataset.shareTitle || document.title;
    const label = btn.querySelector('.share-label');

    if (navigator.share) {
      try {
        await navigator.share({ title, url });
      } catch (err) {
        // el usuario canceló el share nativo: no es un error real, no hacer nada
      }
      return;
    }

    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(url);
        showCopied(btn, label);
        return;
      } catch (err) {
        // sigue al fallback de abajo si el portapapeles no está disponible
      }
    }

    // último recurso sin API de portapapeles: seleccionar un input temporal
    const tmp = document.createElement('input');
    tmp.value = url;
    tmp.style.position = 'fixed';
    tmp.style.opacity = '0';
    document.body.appendChild(tmp);
    tmp.select();
    try { document.execCommand('copy'); showCopied(btn, label); } catch (e) { /* nada más que ofrecer */ }
    document.body.removeChild(tmp);
  }

  function showCopied(btn, label) {
    if (!label) return;
    const original = label.textContent;
    label.textContent = '✓ Enlace copiado';
    btn.classList.add('is-copied');
    setTimeout(() => {
      label.textContent = original;
      btn.classList.remove('is-copied');
    }, 2000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-share]').forEach((btn) => {
      btn.addEventListener('click', () => handleShare(btn));
    });
  });
})();
