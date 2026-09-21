/* Real Progress — client side.
 *
 * WebODM draws each task's status label as
 *   div.status-label   with a gradient that cuts at the percentage
 * and a <span> holding the text. React re-renders that label on every poll, so
 * setting it once is not enough: repaint on every cycle and whenever the DOM
 * changes.
 *
 * Rows are matched to tasks by NAME, which is the only identifier present in
 * the DOM while a task is still running — the links carrying the id only appear
 * once it has completed.
 *
 * Strings arrive already translated from the server, in WebODM's active
 * language. The client does not decide languages.
 */
(function () {
  'use strict';

  var POLL_MS = 5000;
  var tasks = {};

  function duration(s) {
    if (s === null || s === undefined) return '';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    if (h) return h + 'h' + String(m).padStart(2, '0');
    if (m) return m + ' min';
    return '< 1 min';
  }

  function number(n) {
    try { return n.toLocaleString(); } catch (e) { return String(n); }
  }

  function poll() {
    fetch('/api/plugins/realprogress/status', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j) { tasks = j.tasks || {}; paint(); } })
      .catch(function () { /* never break the page over a progress readout */ });
  }

  function byName() {
    var m = {};
    Object.keys(tasks).forEach(function (k) {
      var t = tasks[k];
      if (t && t.name && !t.error) m[t.name] = t;
    });
    return m;
  }

  /* The label sits in a narrow column that changes width with the viewport,
     and translated stage names vary a lot in length. So the text is built in
     decreasing levels of detail and the widest one that actually fits is used.
     Order of importance: percentage, time remaining, stage, counts. */
  function variants(t) {
    var pct = (t.pct !== null && t.pct !== undefined) ? t.pct + '%' : null;
    var stage = t.stage_label || null;
    var left = t.remaining_s ? t.words.remaining + ' ' + duration(t.remaining_s) : null;

    var active = (t.steps || []).filter(function (s) {
      return s.total && (s.pct || 0) < 100 && s.done;
    })[0];
    var counts = active
      ? number(active.done) + ' ' + (t.words.of || '/') + ' ' + number(active.total)
      : null;

    return [
      [pct, stage, counts, left],
      [pct, stage, left],
      [pct, left],
      [pct, stage],
      [pct],
    ].map(function (parts) {
      return ' ' + parts.filter(Boolean).join(' · ');
    });
  }

  /* Tooltip: all 13 ODM stages with their state, then the step counters. */
  function tooltip(t) {
    var lines = (t.stages || []).map(function (s) {
      var mark = s.done ? '✓ ' : (s.current ? '▸ ' : '  ');
      return mark + s.label;
    });
    (t.steps || []).forEach(function (s) {
      if (!s.done) return;
      lines.push('    ' + s.label + ': ' + number(s.done) +
                 (s.total ? ' / ' + number(s.total) : '') +
                 (s.pct !== null ? '  (' + s.pct + '%)' : '') +
                 (s.rate ? '  — ' + s.rate + '/s' : ''));
    });
    if (t.eta) lines.push('', t.words.eta + ' ' + t.eta);
    return lines.join('\n');
  }

  /* Writes the widest variant that does not overflow. Measuring costs one
     reflow per attempt, but there are only a handful of running tasks and at
     most five attempts each. */
  function fit(span, options) {
    for (var i = 0; i < options.length; i++) {
      if (span.textContent !== options[i]) span.textContent = options[i];
      if (span.scrollWidth <= span.clientWidth + 1) return;
    }
  }

  function paint() {
    var map = byName();
    document.querySelectorAll('.task-list-item').forEach(function (row) {
      var nameEl = row.querySelector('.name .name-link');
      var label = row.querySelector('.status-label');
      if (!nameEl || !label) return;

      var t = map[nameEl.textContent.trim()];
      if (!t || t.pct === null || t.pct === undefined) return;

      label.classList.add('real-progress');

      var span = label.querySelector('span');
      if (span) fit(span, variants(t));

      // same gradient WebODM uses, with the right percentage
      var p = Math.max(0, Math.min(t.pct, 100));
      label.style.background =
        'linear-gradient(90deg, rgba(124,58,237,.30) ' + p + '%, ' +
        'rgba(255,255,255,0) ' + p + '%)';
      label.title = tooltip(t);
    });
  }

  function start() {
    poll();
    setInterval(poll, POLL_MS);
    // React re-renders rows outside our cycle; repaint when the DOM moves.
    new MutationObserver(function () { paint(); })
      .observe(document.body, { childList: true, subtree: true });
    // The available width changes with the viewport, so re-fit on resize.
    var t = null;
    window.addEventListener('resize', function () {
      clearTimeout(t);
      t = setTimeout(paint, 150);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
