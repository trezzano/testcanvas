# Full-Page Blocking Spinner

## Overview

Lo spinner full-page è un overlay che ricopre l'intero viewport e blocca l'interazione dell'utente durante il caricamento di pagine pesanti o operazioni lunghe.

**Separate and Independent:**
- **Page Spinner** (nuovo): Full-page overlay, blocca interazione, per page-level navigation
- **HTMX Spinner** (esistente): Corner-based, non-bloccante, per richieste HTMX parziali

## Usage

Aggiungi la classe `full-page-spinner` a qualsiasi link per attivare lo spinner all'apertura della pagina:

```html
<!-- Esempio 1: Link semplice -->
<a href="/path/to/page" class="full-page-spinner">Navigate to Page</a>

<!-- Esempio 2: Link con Bootstrap styling -->
<a href="/page" class="btn btn-primary full-page-spinner">Go</a>

<!-- Esempio 3: Form submit (tramite POST) -->
<form method="post" action="/page" class="full-page-spinner">
    {% csrf_token %}
    <button type="submit">Submit and Navigate</button>
</form>
```

## Behavior

1. **Click on link** → Spinner fade-in + overlay appears
2. **Page disabled** → No clicks, scrolling, or interaction possible
3. **Brief delay (100ms)** → Navigation occurs
4. **Page unloads** → Spinner auto-hides on `beforeunload`
5. **Safety timeout (30s)** → If navigation stalls, spinner auto-hides and warning logged to console

## Styling & Customization

### CSS Variables

Lo spinner usa le stesse variabili di colore di TestCanvas:
- `--tc-primary`: colore del ring animato
- `--tc-ink`: colore del testo

Modifica in `static/css/page-spinner.css` per personalizzare:
- Dimensioni: `width` e `height` di `.page-spinner__ring`
- Colori: `border-*-color`
- Backdrop: `background` e `backdrop-filter`
- Animazione: `animation` e `@keyframes page-spinner-rotate`

### Manual Control (Advanced)

Se devi controllare lo spinner manualmente via JavaScript:

```javascript
// Mostra lo spinner
window.PageSpinner.show();

// Nascondi lo spinner
window.PageSpinner.hide();

// Esempio: fetch + spinner
fetch('/api/endpoint', { method: 'POST' })
    .then(res => {
        window.PageSpinner.hide();
        // handle response
    })
    .catch(err => {
        window.PageSpinner.hide();
        console.error(err);
    });
```

## Files

- **CSS**: `static/css/page-spinner.css` — Styling overlay, ring, animations
- **JS**: `static/js/page-spinner.js` — Click handling, show/hide logic, safety timeout
- **HTML**: `templates/testcanvas/bases/base.html` — Overlay element + includes

## Browser Support

- Moderno (ES5+)
- `backdrop-filter`: tutti i browser moderni (Chrome, Firefox, Safari, Edge)
- `prefers-reduced-motion`: rispettato (animazione disabilitata per utenti con preferenze di movimento ridotto)

## Notes

- Non interferisce con HTMX spinner corner-based
- ARIA accessible: `role="status"`, `aria-live="polite"`
- Internazionalizzato: etichetta "Loading…" tradotta via Django `{% translate %}`
- Logging console: `[PageSpinner]` prefix per debugging

