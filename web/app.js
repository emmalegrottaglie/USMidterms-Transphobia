// Anti-trans Rhetoric Monitor: the study page.
//
// Reads data/study.json (monitor/study.py `build`, or the newest frozen version) and
// data/terms.json (monitor/static.py) and draws them. No numbers are made up here: a
// value the data does not have is shown as "—", and a line breaks where a day is
// missing. Day keys in study.json are UTC day starts in seconds, as strings.

const DAY = 86400;
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const SCALE_LO = 40, SCALE_HI = 250;  // small multiples: one fixed scale for every term

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const utc = (ts) => new Date(ts * 1000);
const dm = (ts) => `${utc(ts).getUTCDate()} ${MON[utc(ts).getUTCMonth()]}`;
const dmy = (ts) => `${dm(ts)} ${utc(ts).getUTCFullYear()}`;
const hhmm = (ts) => `${String(utc(ts).getUTCHours()).padStart(2, '0')}:${String(utc(ts).getUTCMinutes()).padStart(2, '0')}`;
// "29 SEP–19 OCT", or "4–17 NOV" within one month.
const span = (a, b) => (utc(a).getUTCMonth() === utc(b).getUTCMonth() ? `${utc(a).getUTCDate()}–${dm(b)}` : `${dm(a)}–${dm(b)}`);
const n0 = (v) => (isNum(v) ? String(Math.round(v)) : '—');
const n1 = (v) => (isNum(v) ? v.toFixed(1) : '—');
const pct0 = (p) => (isNum(p) ? `${Math.round(p * 100)}%` : '—');
const isoTs = (s) => (s ? Math.floor(Date.parse(s) / 1000) : null);
const glyph = (g) => `<span aria-hidden="true">${g}</span>`;
const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

let study = null, terms = [], rejected = null, M = null;
let redrawMain = null;  // redraws the main chart at its new width

// ── The study's days, phases and series, in one place ──────────────────────────
function buildModel(s) {
  const days = [];
  for (let d = s.reference.start; d <= s.window.end; d += DAY) days.push(d);
  const ev = s.event_days;
  const phaseOf = (d) => (d < s.window.start ? 'ref' : d < ev.start ? 'before' : d <= ev.end ? 'event' : 'after');
  const at = (daily) => days.map((d) => { const v = daily?.[String(d)]; return isNum(v) ? v : null; });
  const evFirst = days.findIndex((d) => d >= ev.start);
  const evLast = days.findIndex((d) => d > ev.end) - 1;
  const event = s.events[0] || null;
  const evDay = evFirst === evLast ? dm(ev.start) : 'EVENT';  // the event column's name
  const refRange = span(s.reference.start, s.reference.end);
  const after = { start: ev.end + 1, end: s.window.end };
  return {
    days, phaseOf, at, evFirst, evLast, evDay, refRange,
    eventShort: event ? event.short : 'EVENT',
    eventLabel: event ? `${event.short} · ${dm(event.ts)}` : 'EVENT',
    phaseName: { ref: 'REFERENCE', before: 'BEFORE', event: evDay, after: 'AFTER' },
    phaseDates: `BEFORE ${span(s.window.start, ev.start - DAY)} · ${evDay === 'EVENT' ? `EVENT ${span(ev.start, ev.end)}` : `${event ? esc(event.short) : 'EVENT'} DAY ${evDay}`} · AFTER ${span(after.start, after.end)}`,
    baseline: `100 = SAME WEEKDAY, ${refRange}`,
    bandWords: 'SHADED = 5TH–95TH PERCENTILE OF REFERENCE DAYS',
  };
}

// ── Main chart: family lines against normal ────────────────────────────────────
function mainChart(el, readout, cfg) {
  const { series, bands } = cfg;
  const days = M.days, n = days.length;
  const W = Math.max(280, Math.round(el.clientWidth));
  const narrow = W < 480;
  const H = narrow ? 250 : 280;
  const L = 34, R = 88, T = 28, B = 46;
  const plotB = H - B;
  const all = series.flatMap((s) => s.values).filter(isNum).concat(bands.flatMap((b) => [b.lo, b.hi]));
  const top = Math.max(150, Math.ceil(Math.max(0, ...all) / 50) * 50);
  const step = top > 300 ? 100 : 50;
  const y = (v) => T + (1 - v / top) * (plotB - T);
  const slot = (W - L - R) / n;
  const x = (i) => L + (i + 0.5) * slot;
  const has = series.some((s) => s.values.some(isNum));

  // Value axis: solid hairline grid from 0, labelled ticks, title.
  let g = '';
  for (let v = 0; v <= top + 1e-9; v += step) {
    g += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>`
      + `<text class="axis" x="${L - 5}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${v}</text>`;
  }
  g += `<text class="axis axis-title" x="0" y="${T - 14}">INDEX</text>`;

  // Time axis: day labels a week apart, counted from the event day so it gets one.
  const every = 7 * slot >= 50 ? 7 : 14;
  const ticks = [];
  for (let i = M.evFirst % every; i < n; i += every) ticks.push(i);
  g += ticks.map((i) => `<line class="tick" x1="${x(i).toFixed(1)}" x2="${x(i).toFixed(1)}" y1="${plotB}" y2="${plotB + 3}"/>`
    + `<text class="axis" x="${x(i).toFixed(1)}" y="${plotB + 13}" text-anchor="middle">${dm(days[i])}</text>`).join('');

  // Phase strip under the dates: which days are reference, before and after.
  const runs = [];
  days.forEach((d, i) => { const p = M.phaseOf(d); if (runs.length && runs[runs.length - 1].p === p) runs[runs.length - 1].i1 = i; else runs.push({ p, i0: i, i1: i }); });
  g += runs.filter((r) => r.p !== 'event').map((r) => {
    const a = L + r.i0 * slot + 1, b = L + (r.i1 + 1) * slot - 1, mid = (a + b) / 2;
    const word = M.phaseName[r.p], fits = word.length * 6.2 < b - a;
    return `<line class="phase" x1="${a.toFixed(1)}" x2="${b.toFixed(1)}" y1="${plotB + 22}" y2="${plotB + 22}"/>`
      + (fits ? `<text class="axis" x="${mid.toFixed(1)}" y="${plotB + 34}" text-anchor="middle">${word}</text>` : '');
  }).join('');

  // Normal bands, then the 100 line with its name, then the event marker.
  const bandRects = bands.map((b) => `<rect class="band ${b.cls}" x="${L}" width="${W - L - R}" y="${y(b.hi).toFixed(1)}" height="${Math.max(1, y(b.lo) - y(b.hi)).toFixed(1)}"/>`).join('');
  const norm = `<line class="norm" x1="${L}" x2="${W - R}" y1="${y(100).toFixed(1)}" y2="${y(100).toFixed(1)}"/>`;
  // The line's name is drawn over the data, on a halo, so lines never cross it out.
  const normLabel = `<text class="axis halo norm-label" x="${L + 4}" y="${(y(100) - 4).toFixed(1)}">100 = NORMAL</text>`;
  const ex = (x(M.evFirst) + x(M.evLast)) / 2;
  const evW = M.eventLabel.length * 6.2;
  const evX = Math.min(W - 4 - evW / 2, Math.max(L + evW / 2, ex));
  const evMark = `<line class="event" x1="${ex.toFixed(1)}" x2="${ex.toFixed(1)}" y1="${T - 4}" y2="${plotB}"/>`
    + `<text class="event-label" x="${evX.toFixed(1)}" y="${T - 8}" text-anchor="middle">${esc(M.eventLabel)}</text>`;

  // Lines break at missing days; a day with no neighbour is a dot.
  const lines = series.map((s) => {
    let d = '', dots = '';
    s.values.forEach((v, i) => {
      if (!isNum(v)) return;
      const prev = i > 0 && isNum(s.values[i - 1]), next = i < n - 1 && isNum(s.values[i + 1]);
      d += `${prev ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      if (!prev && !next) dots += `<circle class="dot ${s.cls}" r="2.5" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}"/>`;
    });
    return `<path class="line ${s.cls}" d="${d}"/>${dots}`;
  }).join('');

  // Each line is named at its end: a short stroke in its style, the name in ink.
  const ends = series.map((s) => {
    let i = n - 1; while (i >= 0 && !isNum(s.values[i])) i -= 1;
    return i < 0 ? null : { s, ly: y(s.values[i]) + 3 };
  }).filter(Boolean).sort((a, b) => a.ly - b.ly);
  for (let k = 1; k < ends.length; k += 1) if (ends[k].ly - ends[k - 1].ly < 12) ends[k].ly = ends[k - 1].ly + 12;
  const over = ends.length ? ends[ends.length - 1].ly - (plotB + 3) : 0;
  if (over > 0) ends.forEach((e) => { e.ly -= over; });
  const endLabels = ends.map(({ s, ly }) => `<line class="line key ${s.cls}" x1="${W - R + 6}" x2="${W - R + 20}" y1="${(ly - 3).toFixed(1)}" y2="${(ly - 3).toFixed(1)}"/>`
    + `<text class="line-label" x="${W - R + 24}" y="${ly.toFixed(1)}">${esc(s.short)}</text>`).join('');

  const empty = has ? '' : `<text class="axis empty" x="${(L + W - R) / 2}" y="${((T + plotB) / 2 + 3).toFixed(1)}" text-anchor="middle">NO DATA FOR THESE SERIES YET</text>`;

  const svgLabel = `Line chart, daily index, 100 = same weekday in the reference period ${M.refRange}, from ${dm(days[0])} to ${dmy(days[n - 1])}. `
    + series.map((s) => {
      const known = s.values.filter(isNum).length;
      return `${s.name}: ${known ? `${known} of ${n} days have a value; ${s.summary}` : 'no values yet'}.`;
    }).join(' ')
    + ` Event marked: ${M.eventLabel}. Every value is in the table below the chart; arrow keys read each day.`;

  el.innerHTML = `<svg class="chart-svg" viewBox="0 0 ${W} ${H}" style="height:${H}px" role="img" tabindex="0" aria-label="${esc(svgLabel)}">
    ${g}${bandRects}${norm}${evMark}${lines}${normLabel}${endLabels}${empty}
    <line class="cursor" x1="0" x2="0" y1="${T}" y2="${plotB}" visibility="hidden"/><g class="hover"></g>
    <rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${plotB - T}"/></svg>`;

  const svg = el.querySelector('svg');
  const cursor = svg.querySelector('.cursor'), hover = svg.querySelector('.hover');
  const describe = (i) => `<b>${dm(days[i])}</b> <span class="muted">· ${M.phaseName[M.phaseOf(days[i])]} ·</span> `
    + series.map((s) => `<span class="muted">${esc(s.short)}</span> <b>${n1(s.values[i])}</b>`).join(' <span class="muted">·</span> ')
    + ' <span class="muted">· INDEX</span>';
  let last = n - 1;
  while (last > 0 && !series.some((s) => isNum(s.values[last]))) last -= 1;
  const idle = () => {
    readout.innerHTML = has ? `<span class="muted">LATEST ·</span> ${describe(last)}` : '<span class="muted">NO VALUES YET · THE TABLE LISTS EVERY DAY</span>';
  };
  const show = (i) => {
    cursor.setAttribute('x1', x(i)); cursor.setAttribute('x2', x(i)); cursor.setAttribute('visibility', 'visible');
    hover.innerHTML = series.filter((s) => isNum(s.values[i])).map((s) => `<circle class="dot ring ${s.cls}" r="3.5" cx="${x(i).toFixed(1)}" cy="${y(s.values[i]).toFixed(1)}"/>`).join('');
    readout.innerHTML = describe(i);
  };
  const hide = () => { cursor.setAttribute('visibility', 'hidden'); hover.innerHTML = ''; idle(); };
  let idx = last;
  const indexAt = (clientX) => {
    const box = svg.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * W;
    return Math.max(0, Math.min(n - 1, Math.floor((px - L) / slot)));
  };
  svg.addEventListener('pointermove', (e) => { idx = indexAt(e.clientX); show(idx); });
  svg.addEventListener('pointerleave', () => { if (document.activeElement !== svg) hide(); });
  svg.addEventListener('blur', hide);
  svg.addEventListener('keydown', (e) => {
    const moves = { ArrowLeft: -1, ArrowRight: 1, PageUp: -7, PageDown: 7, Home: -Infinity, End: Infinity };
    if (!(e.key in moves)) return;
    e.preventDefault();
    idx = Math.max(0, Math.min(n - 1, idx + moves[e.key]));
    show(idx);
  });
  readout.setAttribute('aria-live', 'polite');
  idle();
}

// ── Small multiples: one tile per term, fixed 40–250 scale ─────────────────────
// `band` is the term's 5th–95th percentile of reference days from study.json (null
// with fewer than 14 reference days).
function spark(values, band, cls) {
  const VW = 160, VH = 60, top = 4, h = VH - 8, n = values.length;
  const x = (i) => ((i + 0.5) * VW) / n;
  const y = (v) => top + ((SCALE_HI - Math.max(SCALE_LO, Math.min(SCALE_HI, v))) / (SCALE_HI - SCALE_LO)) * h;
  const b = Array.isArray(band) && band.every(isNum) ? band : null;
  const bandRect = b ? `<rect class="band ${cls}" x="0" width="${VW}" y="${y(b[1]).toFixed(1)}" height="${Math.max(0.8, y(b[0]) - y(b[1])).toFixed(1)}"/>` : '';
  let d = '', marks = '', dots = '';
  values.forEach((v, i) => {
    if (!isNum(v)) return;
    const prev = i > 0 && isNum(values[i - 1]), next = i < n - 1 && isNum(values[i + 1]);
    d += `${prev ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
    if (!prev && !next) dots += `<circle class="dot ${cls}" r="1.6" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}"/>`;
    // Off the scale: the line is held at the edge and the day gets a mark.
    if (v > SCALE_HI) marks += `<path class="clip" d="M${(x(i) - 2.6).toFixed(1)},4.6L${(x(i) + 2.6).toFixed(1)},4.6L${x(i).toFixed(1)},0Z"/>`;
    if (v < SCALE_LO) marks += `<path class="clip" d="M${(x(i) - 2.6).toFixed(1)},${VH - 4.6}L${(x(i) + 2.6).toFixed(1)},${VH - 4.6}L${x(i).toFixed(1)},${VH}Z"/>`;
  });
  const ex = (x(M.evFirst) + x(M.evLast)) / 2;
  return {
    band: b,
    clipped: values.filter((v) => isNum(v) && (v > SCALE_HI || v < SCALE_LO)).length,
    svg: `<svg class="spark" viewBox="0 0 ${VW} ${VH}" aria-hidden="true">
      <rect class="frame" x="0" y="${top}" width="${VW}" height="${h}"/>${bandRect}
      <line class="norm" x1="0" x2="${VW}" y1="${y(100).toFixed(1)}" y2="${y(100).toFixed(1)}"/>
      <line class="event" x1="${ex.toFixed(1)}" x2="${ex.toFixed(1)}" y1="${top}" y2="${top + h}"/>
      <path class="line ${cls}" d="${d}"/>${dots}${marks}</svg>`,
  };
}

function precisionText(t, info) {
  if (!isNum(t.precision)) return 'PRECISION —';
  const ci = t.precision_ci ? ` · 95% CI ${Math.round(t.precision_ci[0] * 100)}–${Math.round(t.precision_ci[1] * 100)}%` : '';
  return `PRECISION ${pct0(t.precision)}${ci}${info && isNum(info.precision_n) ? ` · N ${info.precision_n}` : ''}`;
}
// The same text for a tile, each part kept on one line.
function precisionHtml(t, info) {
  return esc(precisionText(t, info)).split(' · ').map((p) => `<span class="nw">${p}</span>`).join(' · ');
}

function tile(t, cls) {
  const values = M.at(t.daily);
  const info = terms.find((x) => x.id === t.id);
  const sp = spark(values, t.band, cls);
  const p = t.phases || {};
  const missing = values.filter((v) => !isNum(v)).length;
  const sr = `${t.label}: before ${n0(p.before)}, ${M.evDay} ${n0(p.during)}, after ${n0(p.after)}, index, 100 = normal. `
    + `${sp.band ? `Normal range ${n0(sp.band[0])} to ${n0(sp.band[1])}. ` : 'No normal range: fewer than 14 reference days. '}`
    + `${sp.clipped ? `${sp.clipped} days are off the 40 to 250 scale. ` : ''}${missing ? `${missing} of ${values.length} days have no value. ` : ''}${precisionText(t, info).toLowerCase()}.`;
  const v = (val, name) => `<div><b class="${isNum(val) ? '' : 'unknown'}">${n0(val)}</b><span>${name}</span></div>`;
  return `<div class="mult" role="listitem">
    <div class="mult-name" aria-hidden="true">${esc(t.label.toUpperCase())}</div>
    ${sp.svg}
    <div class="mult-vals" aria-hidden="true">${v(p.before, 'BEFORE')}${v(p.during, M.evDay)}${v(p.after, 'AFTER')}</div>
    <div class="mult-prec" aria-hidden="true">${precisionHtml(t, info)}${sp.clipped ? ` · <span class="nw">${glyph('▲▼')} ${sp.clipped} OFF SCALE</span>` : ''}</div>
    <span class="sr-only">${esc(sr)}</span></div>`;
}

// ── Tables ─────────────────────────────────────────────────────────────────────
const th = (label, cls = '') => `<th scope="col"${cls ? ` class="${cls}"` : ''}>${esc(label)}</th>`;
const tdNum = (v, fmt = n1) => `<td class="t-num">${fmt(v)}</td>`;

function dailyTable(caption, cols) {
  return `<div class="table-wrap"><table class="table" aria-label="${esc(caption)}">
    <thead><tr>${th('DATE UTC')}${th('PHASE')}${cols.map((c) => th(c.head, 't-num')).join('')}</tr></thead>
    <tbody>${M.days.map((d, i) => `<tr><td class="t-key">${dm(d)}</td><td class="t-phase">${M.phaseName[M.phaseOf(d)]}</td>${cols.map((c) => tdNum(c.values[i])).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}

function tableToggle(inner) {
  return `<details class="data-table"><summary>SHOW DATA AS A TABLE</summary>${inner}</details>`;
}

// ── The study view ─────────────────────────────────────────────────────────────
function renderStudy() {
  const s = study;
  const fam = (k) => s.families?.[k] || { daily: {}, band: null, phases: {} };
  const anti = fam('anti-trans'), framing = fam('framing');
  const breadth = s.breadth?.['anti-trans'] || { daily: {}, left_out: [] };
  const antiVals = M.at(anti.daily), framVals = M.at(framing.daily), breadthVals = M.at(breadth.daily);
  const summary = (vals, phases) => `before ${n0(phases?.before)}, ${M.evDay} ${n0(phases?.during)}, after ${n0(phases?.after)}`;
  const series = [
    { name: 'Anti-trans terms, one combined query', short: 'ANTI-TRANS', cls: 's-anti', values: antiVals, summary: summary(antiVals, anti.phases) },
    { name: 'Framing terms, one combined query', short: 'FRAMING', cls: 's-framing', values: framVals, summary: summary(framVals, framing.phases) },
    { name: 'Breadth of the anti-trans terms, each term weighted equally', short: 'BREADTH', cls: 's-breadth', values: breadthVals, summary: `before ${n0(breadth.phases?.before)}, ${M.evDay} ${n0(breadth.phases?.during)}, after ${n0(breadth.phases?.after)}` },
  ];
  const bands = [];
  if (anti.band) bands.push({ lo: anti.band[0], hi: anti.band[1], cls: 's-anti' });
  if (framing.band) bands.push({ lo: framing.band[0], hi: framing.band[1], cls: 's-framing' });
  const bandText = `ANTI-TRANS ${anti.band ? `${n0(anti.band[0])}–${n0(anti.band[1])}` : '—'} · FRAMING ${framing.band ? `${n0(framing.band[0])}–${n0(framing.band[1])}` : '—'}`;

  const familyTerms = (k) => (s.terms || []).filter((t) => t.family === k);
  const contextTerms = (s.terms || []).filter((t) => t.family === 'context');
  const countOf = (k) => familyTerms(k).length;

  const heroV = anti.phases?.after;
  const tileRow = (k, name, ph) => [['before', 'BEFORE'], ['during', M.evDay], ['after', 'AFTER']].map(([key, word]) => `<div class="tile" role="listitem">
      <div class="tile-value${key === 'after' && k === 'anti' ? ' hl' : ''}">${n0(ph?.[key])}</div>
      <div class="tile-label">${word} · ${name}</div></div>`).join('');

  const version = s.provisional
    ? `PROVISIONAL · NOT YET FROZEN · BUILT ${dmy(isoTs(s.built_at))} ${hhmm(isoTs(s.built_at))} UTC`
    : `VERSION ${esc(s.version)} · FROZEN ${dmy(isoTs(s.built_at))}${s.note ? ` · ${esc(s.note)}` : ''}`;

  const grid = (title, list, cls, note) => `<h3 class="mult-head">${esc(title)} · ${list.length} ${list.length === 1 ? 'TERM' : 'TERMS'}${note ? ` <span>${esc(note)}</span>` : ''}</h3>
    <div class="mults" role="list" aria-label="${esc(title)}">${list.map((t) => tile(t, cls)).join('')}</div>`;

  const termCols = [...familyTerms('anti-trans'), ...familyTerms('framing'), ...contextTerms];
  const phaseTable = `<div class="table-wrap"><table class="table" aria-label="Each term before, on and after the event, with its hand-checked precision">
    <thead><tr>${th('TERM')}${th('GROUP')}${th('BEFORE', 't-num')}${th(M.evDay, 't-num')}${th('AFTER', 't-num')}${th('PRECISION', 't-num')}${th('95% CI', 't-num')}${th('N CHECKED', 't-num')}</tr></thead>
    <tbody>${termCols.map((t) => {
      const info = terms.find((x) => x.id === t.id);
      return `<tr><td class="t-key wrap">${esc(t.label.toUpperCase())}</td><td class="t-phase">${t.family === 'context' ? 'CONTEXT' : esc(t.family.toUpperCase())}</td>`
        + `${tdNum(t.phases?.before)}${tdNum(t.phases?.during)}${tdNum(t.phases?.after)}`
        + `<td class="t-num">${pct0(t.precision)}</td><td class="t-num">${t.precision_ci ? `${Math.round(t.precision_ci[0] * 100)}–${Math.round(t.precision_ci[1] * 100)}%` : '—'}</td>`
        + `<td class="t-num">${info && isNum(info.precision_n) ? info.precision_n : '—'}</td></tr>`;
    }).join('')}</tbody></table></div>`;

  // Robustness: every alternative version of the after-phase number, per family.
  const rob = (k) => s.robustness?.[k] || {};
  const famKeys = ['anti-trans', 'framing'];
  const loo = (k) => Object.values(rob(k).leave_one_out || {}).filter(isNum);
  const looRange = (k) => (loo(k).length ? `${n0(Math.min(...loo(k)))}–${n0(Math.max(...loo(k)))}` : '—');
  const placeboWord = (k) => { const a = fam(k).phases?.after; return isNum(a) ? (a >= 100 ? 'AT OR ABOVE' : 'AT OR BELOW') : 'AS FAR FROM 100 AS'; };
  const robRows = [
    ['AFTER · HEADLINE INDEX (PROBE-NORMALISED)', (k) => n1(rob(k).raw_vs_probe?.probe)],
    ['AFTER · WITHOUT PROBE NORMALISATION', (k) => n1(rob(k).raw_vs_probe?.raw)],
    ['AFTER · SUM OF TERM COUNTS, ORIGINAL POSTS', (k) => n1(rob(k).originals_vs_reposts?.posts)],
    ['AFTER · SUM OF TERM COUNTS, REPOSTS', (k) => n1(rob(k).originals_vs_reposts?.reposts)],
    ['AFTER · BREADTH, ALL TERMS', (k) => n1(s.breadth?.[k]?.phases?.after)],
    ['AFTER · BREADTH, LEAVING ONE TERM OUT (LOWEST–HIGHEST)', (k) => looRange(k)],
    ['EARLIER DAYS WITH AN INDEX AS EXTREME AS AFTER', (k) => `${pct0(rob(k).placebo_share)}${isNum(rob(k).placebo_share) ? ` <span class="muted">${placeboWord(k)}</span>` : ''}`],
  ];
  const robTable = `<div class="table-wrap"><table class="table rob" aria-label="Robustness of the after-phase index, by family">
    <thead><tr>${th('MEASURE · INDEX, 100 = NORMAL')}${famKeys.map((k) => th(k.toUpperCase(), 't-num')).join('')}</tr></thead>
    <tbody>${robRows.map(([label, f]) => `<tr><td class="t-key wrap">${label}</td>${famKeys.map((k) => `<td class="t-num">${f(k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const looTable = `<div class="table-wrap"><table class="table" aria-label="Breadth after the event, leaving each term out">
    <thead><tr>${th('TERM LEFT OUT')}${th('FAMILY')}${th('BREADTH AFTER', 't-num')}</tr></thead>
    <tbody>${famKeys.flatMap((k) => Object.entries(rob(k).leave_one_out || {}).map(([id, v]) => {
      const t = (s.terms || []).find((x) => x.id === id);
      return `<tr><td class="t-key wrap">${esc((t ? t.label : id).toUpperCase())}</td><td class="t-phase">${k.toUpperCase()}</td>${tdNum(v)}</tr>`;
    })).join('')}</tbody></table></div>`;
  const leftOut = famKeys.flatMap((k) => (s.breadth?.[k]?.left_out || []).map((id) => (s.terms || []).find((x) => x.id === id)?.label || id));

  const series_ = (key) => `data/series/${key}.csv`;
  const links = [
    ['STUDY · JSON', 'data/study.json'],
    ['DAILY TOTALS · CSV', 'data/daily.csv'],
    ['TERMS · JSON', 'data/terms.json'],
    ['REJECTED TERMS · JSON', 'data/rejected.json'],
    ['ANTI-TRANS FAMILY · HOURLY CSV', series_('x.family.anti-trans.en.posts')],
    ['FRAMING FAMILY · HOURLY CSV', series_('x.family.framing.en.posts')],
    ['PROBE · HOURLY CSV', series_('x.probe.en.posts')],
    ...(s.provisional ? [] : [[`STUDY VERSION ${s.version} · JSON`, `data/studies/${s.id}/v${s.version}.json`]]),
    ['CITATION.CFF', 'CITATION.cff'],
    ['METHODS', '#methods'],
  ];

  $('view').innerHTML = `
    <div class="study-head">
      <p class="study-q">${esc(s.question)}</p>
      <p class="note">${version}</p>
      <p class="note">${M.phaseDates} · ${M.baseline}</p>
    </div>

    <div class="hero">
      <div class="hero-row">
        <div class="hero-value${isNum(heroV) ? '' : ' unknown'}">${n0(heroV)}</div>
        <div class="hero-text">
          <div class="hero-meta">ANTI-TRANS TERMS AFTER THE ${esc(M.eventShort)}</div>
          <div class="hero-index">INDEX · 100 = NORMAL (${M.refRange})</div>
        </div>
      </div>
      <div class="hero-meta">MEAN OF ${span(s.event_days.end + 1, s.window.end)} · NORMAL RANGE ${anti.band ? `${n0(anti.band[0])}–${n0(anti.band[1])}` : '—'} (5TH–95TH PERCENTILE OF REFERENCE DAYS)</div>
    </div>
    <div class="tiles" role="list" aria-label="Family index before, on and after the event">
      ${tileRow('anti', 'ANTI-TRANS', anti.phases)}${tileRow('framing', 'FRAMING', framing.phases)}
    </div>

    <h2 class="sect">Daily index · 100 = normal</h2>
    <div class="legend" aria-hidden="true">${series.map((x) => `<span class="legend-item"><svg class="swatch" viewBox="0 0 22 8"><line class="line ${x.cls}" x1="1" x2="21" y1="4" y2="4"/></svg>${esc(x.name.toUpperCase())}</span>`).join('')}</div>
    <div class="readout" id="main-readout"></div>
    <div class="chart" id="main-chart"></div>
    <p class="caption">LINES FROM 0 · ${M.baseline} · ${M.bandWords} (${bandText}) · DASHED VERTICAL = ${esc(M.eventLabel)} · ${dm(M.days[0])}–${dmy(M.days[M.days.length - 1])} UTC</p>
    <div class="chart-tools">${tableToggle(dailyTable('Daily index by family, 100 = normal', [
      { head: 'ANTI-TRANS', values: antiVals }, { head: 'FRAMING', values: framVals }, { head: 'BREADTH (ANTI-TRANS)', values: breadthVals }]))}</div>
    <ul class="notes">
      <li>Each family line is one combined Twitter search for its terms, so a post matching several terms counts once. Each day's count of matching original English posts is divided by a common-word probe (posts with “thing”, “any” or “tell”), then compared with the same weekday in the reference period, ${M.refRange}.</li>
      <li>Breadth averages the ${countOf('anti-trans')} anti-trans terms with equal weight, so one busy term cannot carry it.${leftOut.length ? ` Left out because they have fewer than 14 reference days with a value, or no variation in them: ${esc(leftOut.join(', '))}.` : ''}</li>
      <li>Counts include people quoting the words to object. A gap in a line is a day with fewer than 20 hours collected, not a quiet day.</li>
    </ul>

    <h2 class="sect">Each term · same scale</h2>
    ${grid('ANTI-TRANS TERMS', familyTerms('anti-trans'), 's-anti')}
    ${grid('FRAMING TERMS', familyTerms('framing'), 's-framing')}
    ${contextTerms.length ? grid('CONTEXT', contextTerms, 's-context', 'A TOPIC TERM, NOT HOSTILITY · IN NEITHER FAMILY') : ''}
    <p class="caption">INDEX, SCALE 40–250 ON EVERY TILE · ${M.baseline} (DASHED) · ${M.bandWords}, EACH TERM ITS OWN · VERTICAL = ${esc(M.eventLabel)} · ${glyph('▲▼')} DAY OFF THE SCALE, LINE HELD AT THE EDGE · ${dm(M.days[0])}–${dmy(M.days[M.days.length - 1])} UTC</p>
    <div class="chart-tools">${tableToggle(`<p class="note">BEFORE, ${M.evDay} AND AFTER · INDEX, 100 = NORMAL</p>${phaseTable}
      <p class="note">EACH DAY · INDEX, 100 = NORMAL</p>${dailyTable('Each term, daily index, 100 = normal', termCols.map((t) => ({ head: t.label.toUpperCase(), values: M.at(t.daily) })))}`)}</div>
    <ul class="notes">
      <li>Precision is the share of a hand-checked sample of matching posts that were anti-trans, with its 95% interval. Only terms at 70% or more are counted in a family.</li>
    </ul>

    <h2 class="sect">Robustness</h2>
    ${robTable}
    <details class="data-table"><summary>LEAVE-ONE-OUT BY TERM</summary>${looTable}</details>
    <ul class="notes">
      <li>The headline is one combined search per family, so a single term cannot be removed from it; leaving one term out is done on the breadth index instead.</li>
      <li>The last row is the share of days with data before the study window whose index was as far from normal as the after-phase mean, in the same direction: how often a value like it turned up without the event.</li>
    </ul>

    <h2 class="sect">Data for researchers</h2>
    <div class="links">${links.map(([label, href]) => `<a class="chip ghost" href="${esc(href)}">${esc(label)}</a>`).join('')}</div>
    <ul class="notes">
      <li>Every series also has an hourly CSV and JSON file in <code>data/series/</code>, named by its series key. Times are UTC; an hour is stamped at its end.</li>
    </ul>`;

  redrawMain = () => mainChart($('main-chart'), $('main-readout'), { series, bands });
  redrawMain();
  enhance($('view'));
}

// ── Shared pieces for the other tabs ───────────────────────────────────────────
const MONTH = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const longDate = (ts) => (isNum(ts) ? `${utc(ts).getUTCDate()} ${MONTH[utc(ts).getUTCMonth()]} ${utc(ts).getUTCFullYear()}` : '—');
const int = (v) => (isNum(v) ? Math.round(v).toLocaleString('en-US') : '—');
const ciText = (ci) => (Array.isArray(ci) && ci.length === 2 && ci.every(isNum) ? `${Math.round(ci[0] * 100)}–${Math.round(ci[1] * 100)}%` : '—');
const GROUP = { 'anti-trans': 'ANTI-TRANS', framing: 'FRAMING', context: 'CONTEXT' };
// The tab's own heading: focused when the tab opens, so screen readers start there.
const tabHead = (title, introHtml) => `<div class="tab-head"><h2 class="sect" id="tab-h" tabindex="-1">${esc(title)}</h2>`
  + `${introHtml ? `<p class="study-q">${introHtml}</p>` : ''}</div>`;
const outLink = (href, text) => (href ? `<a href="${esc(href)}" rel="noopener">${esc(text)}</a>` : esc(text || '—'));
const windowText = () => (study?.window ? `${span(study.window.start, study.window.end)} ${utc(study.window.end).getUTCFullYear()}` : '—');
// The same spans in running text: "29 September to 19 October 2026".
const longSpan = (a, b) => `${utc(a).getUTCDate()} ${MONTH[utc(a).getUTCMonth()]} to ${longDate(b)}`;
const windowProse = () => (study?.window ? longSpan(study.window.start, study.window.end) : '—');
const refProse = () => (study?.reference ? longSpan(study.reference.start, study.reference.end) : '—');
const tableWrap = (label, head, rows) => `<div class="table-wrap"><table class="table tab-table" aria-label="${esc(label)}">
  <thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;

// ── Terms tab ──────────────────────────────────────────────────────────────────
function termEntry(t) {
  const v = (val, name) => `<div><b class="${val === '—' ? 'unknown' : ''}">${esc(val)}</b><span>${name}</span></div>`;
  return `<div class="term" role="listitem">
    <h4 class="term-name">${esc(String(t.label).toUpperCase())}</h4>
    <div class="term-vals">${v(int(t.median_posts_a_day), 'POSTS A DAY')}${v(pct0(t.precision), 'PRECISION')}${v(ciText(t.interval), '95% CI')}${v(isNum(t.precision_n) ? String(t.precision_n) : '—', 'N CHECKED')}</div>
    <p class="term-line"><span class="k">QUERY</span> <code>${esc(t.query)}</code></p>
    <p class="term-line"><span class="k">SOURCE</span> ${outLink(t.source_url, t.source)}</p>
  </div>`;
}

function termGroup(title, note, list) {
  return `<h3 class="sect">${esc(title)} · ${list.length} ${list.length === 1 ? 'term' : 'terms'}</h3>
    ${note ? `<p class="note">${esc(note)}</p>` : ''}
    <div class="terms" role="list" aria-label="${esc(title)}">${list.map(termEntry).join('')}</div>`;
}

function rejectedHtml() {
  const rows = Array.isArray(rejected?.terms) ? rejected.terms : null;
  if (!rows) return '<p class="note">SCREENED SEARCHES · — · DATA/REJECTED.JSON COULD NOT BE LOADED</p>';
  const groups = [];
  for (const r of rows) {
    const key = `${r.decision}|${r.reason}`;
    let g = groups.find((x) => x.key === key);
    if (!g) groups.push(g = { key, decision: r.decision, reason: r.reason, rows: [] });
    g.rows.push(r);
  }
  const used = (r) => (isNum(r.anti_trans_checked) && isNum(r.checked_n) ? `${r.anti_trans_checked} OF ${r.checked_n}` : '—');
  return groups.map((g) => `<h4 class="mult-head">${esc(String(g.decision || '—').toUpperCase())} · ${g.rows.length} ${g.rows.length === 1 ? 'SEARCH' : 'SEARCHES'}</h4>
    <p class="prose-line">${esc(g.reason || '—')}</p>
    ${tableWrap(`Searches ${g.decision}: hand-checked precision and other uses`,
      `${th('SEARCH')}${th('ANTI-TRANS USE · CHECKED', 't-num')}${th('PRECISION', 't-num')}${th('POSTS A DAY · ABOUT', 't-num')}${th('MAIN OTHER USES')}`,
      g.rows.map((r) => `<tr><td class="t-key wrap">${esc(String(r.term).toUpperCase())}</td><td class="t-num">${used(r)}</td>`
        + `<td class="t-num">${isNum(r.precision_pct) ? `${r.precision_pct}%` : '—'}</td><td class="t-num">${int(r.posts_a_day_approx)}</td>`
        + `<td class="wrap">${esc(r.other_uses || '—')}</td></tr>`).join(''))}`).join('');
}

function renderTerms() {
  const list = Array.isArray(terms) ? terms : [];
  const fam = (k) => list.filter((t) => t.family === k);
  const tracked = fam('anti-trans').length + fam('framing').length;
  const screened = Array.isArray(rejected?.terms) ? rejected.terms.length : null;
  const allRows = list.map((t) => `<tr><td class="t-key wrap">${esc(String(t.label).toUpperCase())}</td><td class="t-phase">${esc(GROUP[t.family] || t.family)}</td>`
    + `<td class="wrap q"><code>${esc(t.query)}</code></td><td class="t-num">${int(t.median_posts_a_day)}</td><td class="t-num">${pct0(t.precision)}</td>`
    + `<td class="t-num">${ciText(t.interval)}</td><td class="t-num">${isNum(t.precision_n) ? t.precision_n : '—'}</td>`
    + `<td class="t-key">${esc(t.added || '—')}</td><td class="wrap">${outLink(t.source_url, t.source)}</td></tr>`).join('');

  $('view').innerHTML = `
    ${tabHead(`Terms · ${tracked} tracked, ${fam('context').length} context, ${screened ?? '—'} screened out or held`,
      'Every term the monitor counts on Twitter: the search it runs, where the term is documented, how often it is posted, and how often a hand-checked sample of its posts was anti-trans use.')}
    <p class="note">POSTS A DAY = MEDIAN ORIGINAL ENGLISH POSTS A DAY, ${esc(windowText())}, DAYS WITH 20 OR MORE HOURS · PRECISION = SHARE OF A HAND-CHECKED SAMPLE THAT WAS ANTI-TRANS USE, 16 NOV 2026 · 95% CI = WILSON INTERVAL · N = POSTS CHECKED</p>
    ${list.length ? '' : '<div class="nodata">NO TERMS · DATA/TERMS.JSON COULD NOT BE LOADED</div>'}
    ${fam('anti-trans').length ? termGroup('Anti-trans terms', 'SLURS AND MEMES · ONE COMBINED SEARCH IS THE FAMILY HEADLINE', fam('anti-trans')) : ''}
    ${fam('framing').length ? termGroup('Framing terms', 'PHRASES THAT NEWS, LEGAL AND POLICY DISCUSSION ALSO USE · ONE COMBINED SEARCH IS THE FAMILY HEADLINE', fam('framing')) : ''}
    ${fam('context').length ? termGroup('Context', 'A TOPIC TERM, NOT HOSTILITY · IN NEITHER FAMILY · NOT PRECISION-CHECKED', fam('context')) : ''}
    ${list.length ? `<div class="chart-tools">${tableToggle(tableWrap('Every term: group, query, posts a day, precision and source',
      `${th('TERM')}${th('GROUP')}${th('QUERY')}${th('POSTS A DAY', 't-num')}${th('PRECISION', 't-num')}${th('95% CI', 't-num')}${th('N CHECKED', 't-num')}${th('ADDED')}${th('SOURCE')}`, allRows))}</div>` : ''}
    <ul class="notes">
      <li>Only terms whose hand-checked precision is 70% or more are counted in a family. A count still includes people quoting the words to object; precision says how often that happens in a sample.</li>
      <li>Each search adds <code>lang:en</code> and a repost filter. How the checks were done is on the <a href="#methods">Methods</a> tab.</li>
    </ul>

    <h3 class="sect">Screened out or held · ${screened ?? '—'} searches</h3>
    <p class="note">${rejected?.source ? `SOURCE: ${esc(rejected.source.toUpperCase())}` : 'SOURCE —'}</p>
    ${rejectedHtml()}

    <h3 class="sect">Files</h3>
    <div class="links"><a class="chip ghost" href="data/terms.json">TERMS · JSON</a><a class="chip ghost" href="data/rejected.json">REJECTED TERMS · JSON</a></div>`;
  enhance($('view'));
}

// ── Methods tab ────────────────────────────────────────────────────────────────
function precisionTable() {
  const tracked = (Array.isArray(terms) ? terms : []).filter((t) => isNum(t.precision)).map((t) => ({
    name: t.label, p: t.precision, n: t.precision_n, ci: ciText(t.interval), decision: `TRACKED · ${GROUP[t.family] || t.family}`,
  }));
  const screened = (Array.isArray(rejected?.terms) ? rejected.terms : []).map((r) => ({
    name: r.term, p: isNum(r.precision_pct) ? r.precision_pct / 100 : null, n: r.checked_n, ci: '—', decision: String(r.decision || '—').toUpperCase(),
  }));
  const rows = [...tracked, ...screened].sort((a, b) => (b.p ?? -1) - (a.p ?? -1));
  const posts = rows.reduce((sum, r) => sum + (isNum(r.n) ? r.n : 0), 0);
  return {
    searches: rows.length,
    posts,
    html: rows.length ? tableWrap('Precision check of 16 November 2026, every search',
      `${th('SEARCH')}${th('PRECISION', 't-num')}${th('95% CI', 't-num')}${th('N CHECKED', 't-num')}${th('DECISION')}`,
      rows.map((r) => `<tr><td class="t-key wrap">${esc(String(r.name).toUpperCase())}</td><td class="t-num">${pct0(r.p)}</td><td class="t-num">${r.ci}</td>`
        + `<td class="t-num">${isNum(r.n) ? r.n : '—'}</td><td class="t-phase">${esc(r.decision)}</td></tr>`).join(''))
      : '<p class="note">PRECISION TABLE · — · DATA/TERMS.JSON OR DATA/REJECTED.JSON COULD NOT BE LOADED</p>',
  };
}

function renderMethods() {
  const refDays = isNum(study?.reference?.days) ? study.reference.days : '—';
  const pre = isNum(study?.window?.pre_days) ? study.window.pre_days : '—';
  const post = isNum(study?.window?.post_days) ? study.window.post_days : '—';
  const prec = precisionTable();
  const p = (html) => `<p class="prose">${html}</p>`;

  $('view').innerHTML = `
    ${tabHead('Methods · how the numbers are made',
      'What the monitor counts, how a count becomes an index, how the result is checked, and what a count cannot show.')}

    <h3 class="sect">What is collected</h3>
    <ul class="notes">
      <li>Counts from the Twitter API counts endpoint: how many posts matched a search in each hour. No post is read for the counts, and no usernames or account IDs are collected or stored.</li>
      <li>English posts only (<code>lang:en</code>). Each term gets three counts: original posts (replies included), reposts, and replies. The two family searches and the probe count original posts.</li>
      <li>Collection runs once a day. Between events it pauses; it starts again when a new event fits the research, which opens a new study.</li>
      <li>A failed or empty request is recorded as an error, never as zero. An hour in which even the probe returns nothing is a gap in Twitter's data: no point is stored for any series in that hour.</li>
      <li>A day needs at least 20 collected hours to get a value. A day with fewer is a gap, shown as “—” and as a break in a line. Gaps are never zeros.</li>
      <li>Times are UTC. Each hourly value is stamped at the end of its hour.</li>
    </ul>

    <h3 class="sect">Probe normalisation</h3>
    ${p('Posting on Twitter rises and falls for reasons that have nothing to do with trans people: on election night far more people post about everything. So each count is divided by a probe, the number of English original posts containing “thing”, “any” or “tell”. These common words follow overall activity. The method follows Hickey et al. (PLOS ONE, 2025).')}
    ${p('Each family’s headline is one combined search for all its terms, so a post that matches several terms counts once.')}

    <h3 class="sect">The index and the normal range</h3>
    ${p(`Each day’s probe-normalised count is compared with the same weekday in the reference period: the ${esc(refDays)} days before the study window, ${esc(refProse())}. 100 means the same as an average such weekday in that period; 150 means half as much again. Comparing weekday with weekday takes out the weekly cycle.`)}
    ${p('The normal range is the 5th to 95th percentile of the index on the reference days. It needs at least 14 reference days with a value; with fewer, no range is drawn and the page shows “—”.')}
    ${p(`The study window runs from ${esc(pre)} days before the event to ${esc(post)} days after it, ${esc(windowProse())}. The before, event-day and after numbers are means of the daily index over those days.`)}

    <h3 class="sect">Breadth</h3>
    ${p('Breadth shows whether a rise comes from one term or many. It follows the method of the Economic Policy Uncertainty index (Baker, Bloom and Davis, 2016). Each term’s probe-normalised daily rate is divided by the standard deviation of that rate on the reference days. The terms are then averaged with equal weight, and the result is rescaled so the reference days average 100.')}
    ${p('A term with fewer than 14 reference days, or with no variation in them, is left out of breadth, and the study page names it.')}
    ${p('Breadth is not compared weekday with weekday, so it still carries the weekly cycle. Read it across weeks, not from one day to the next.')}

    <h3 class="sect">Robustness</h3>
    ${p('Each study result is shown next to the same number worked out in other ways:')}
    <ul class="notes">
      <li>Leave one term out. This is done on breadth, because each family’s headline is one combined search and a single term cannot be taken out of it.</li>
      <li>With and without the probe: the family index from raw counts as well as from probe-normalised counts.</li>
      <li>Original posts and reposts: the terms’ raw counts added up, once for original posts and once for reposts, each as a weekday index.</li>
      <li>Placebo share: of the days with data before the study window, reference days included, the share whose index was as far from 100 as the after-phase mean, in the same direction. It shows how often a value like it turned up without the event.</li>
    </ul>

    <h3 class="sect">Precision checks</h3>
    ${p(`On 16 November 2026, up to 50 recent English original posts were read for each of ${prec.searches || '—'} searches: about 25 ending about one day earlier and 25 ending about four days earlier, ${prec.posts ? int(prec.posts) : '—'} posts in all. Usernames and links were stripped, nothing was stored, and the text was deleted after coding.`)}
    ${p('Each post was coded as anti-trans use, pushback, neutral or news, another meaning, or unclear. Precision is the share coded as anti-trans use, with a 95% Wilson interval. With 50 posts the intervals are wide: 80% observed means roughly 67% to 89%.')}
    ${p('Four coding agents shared the work. They split on one rule: some counted news-style headlines and AI-assistant replies that repeat the framing as anti-trans use, others counted them as neutral. That moves a few terms by up to about 12 points.')}
    ${p('Only terms at 70% or more are tracked in a family. Each term’s query and source are on the <a href="#terms">Terms</a> tab.')}
    ${prec.html}

    <h3 class="sect">What a count cannot show</h3>
    <ul class="notes">
      <li>The measure is explicit anti-trans term volume, not transphobia as a whole. Keyword counts miss coded and subtle rhetoric (Lu and Jurgens, 2022; Mendelsohn et al., 2023).</li>
      <li>A count includes people quoting the words to object. The precision checks estimate how often that happens; they do not remove it.</li>
      <li>A count does not say who posted, whether accounts are automated, or whether posting was coordinated.</li>
      <li>A change next to an event does not show that the event caused it.</li>
    </ul>

    <h3 class="sect">When the method was fixed</h3>
    ${p('The midterms data had already been seen when this method was fixed, on 17 November 2026, so what the data showed may have shaped the choices. For future events, the method is registered before the event.')}

    <h3 class="sect">References</h3>
    <ul class="notes refs">
      <li>Baker, S. R., Bloom, N. and Davis, S. J. (2016). Measuring economic policy uncertainty. The Quarterly Journal of Economics.</li>
      <li>Hickey et al. (2025). PLOS ONE. The common-word probe used to normalise counts.</li>
      <li>Lu, C. and Jurgens, D. (2022). The subtle language of exclusion: identifying the toxic speech of trans-exclusionary radical feminists. Workshop on Online Abuse and Harms (WOAH).</li>
      <li>Mendelsohn, J., Le Bras, R., Choi, Y. and Sap, M. (2023). From dogwhistles to bullhorns: unveiling coded rhetoric with language models. ACL.</li>
    </ul>`;
  enhance($('view'));
}

// ── Context tab: outside research, kept apart from our measurements ───────────
// Only the items spot-checked on their pages on 18 November 2026 (docs/CONTEXT-ADS.md).
const CONTEXT_SOURCES = [
  { id: 'ap', name: 'AP (Peoples and Kessler), 28 October 2026, republished by News4JAX', url: 'https://www.news4jax.com/news/politics/2026/10/28/republicans-emphasize-transgender-ads-putting-cultural-issues-over-voters-economic-anxiety/' },
  { id: 'wmp', name: 'Wesleyan Media Project, release of 13 August 2026', url: 'https://mediaproject.wesleyan.edu/releases-081326/' },
  { id: 'cnn', name: 'CNN, 16 October 2026, republished by KRDO', url: 'https://krdo.com/news/2026/10/16/musk-contributed-more-than-150-million-to-bolster-gop-in-texas-senate-race-filings-show/' },
  { id: 'advocate', name: 'The Advocate, 9 September 2026', url: 'https://www.advocate.com/politics/election/elon-musk-pac-transgender-attacks' },
  { id: 'factcheck', name: 'FactCheck.org, September 2026', url: 'https://www.factcheck.org/2026/09/america-pac-2/' },
  { id: 'metro', name: 'Metro Weekly, 11 November 2026', url: 'https://www.metroweekly.com/2026/11/anti-trans-ads-midterm-voters/' },
];
const CONTEXT_GROUPS = [
  ['How much was spent', [
    ['AdImpact, reported by AP', 'Republicans aired transgender-themed general-election ads about 217,000 times, for an estimated $183M up to 25 October 2026. At the same point in 2024 the figure was about $151M. Democrats spent about $11M on trans-related ads.', 'ap'],
    ['Wesleyan Media Project', 'Transgender issues came up in 14% of pro-Republican House ad airings from 1 January 2025 to 2 August 2026, the tenth most common topic.', 'wmp'],
    ['Metro Weekly', 'About $187M across nine states: Arizona, Colorado, Georgia, Missouri, Nebraska, Ohio, Texas, Washington and Wisconsin. The article names no data source for this figure. The Human Rights Campaign put the cycle’s anti-trans ad spending at nearly $400M.', 'metro'],
  ]],
  ['Who paid, and where', [
    ['Texas Senate race', 'About $58M and more than 50,000 airings of trans-themed ads up to 25 October 2026 (AdImpact, reported by AP). AP describes Texas PAC as largely funded by Elon Musk.', 'ap'],
    ['Musk, Senate Leadership Fund, Texas PAC', 'Musk gave the Senate Leadership Fund $75M on 9 September and $83M on 23 September 2026. The fund gave Texas PAC $75M on 10 September and $83M on 24 September.', 'cnn'],
    ['Ohio Senate race', 'AP gives nearly $26M as the cost of all attacks on Sherrod Brown by Republican groups led by the Senate Leadership Fund, not by the fund alone.', 'ap'],
    ['America PAC', 'Citing The New York Times, The Advocate reported that each of America PAC’s initial midterm ads focused on transgender issues. They targeted Talarico, Brown, Turek and Peltola. The ads were reported on 8 and 9 September 2026.', 'advocate'],
    ['America PAC spending', 'More than $3.7M on mostly digital or streaming ads as of 23 September 2026 (AdImpact). FactCheck.org says a number of these ads attacked candidates on transgender issues.', 'factcheck'],
  ]],
  ['Voters', [
    ['GLAAD and Morning Consult poll, advocacy-commissioned', '2,026 registered voters were asked on 4 to 6 November 2026; 1,725 of them voted in the midterms. Of those voters, 37% said they were less likely and 18% more likely to support a candidate who ran ads about transgender issues.', 'metro'],
  ]],
];

function renderContext() {
  const src = (id) => CONTEXT_SOURCES.find((s) => s.id === id);
  $('view').innerHTML = `
    ${tabHead('Context · anti-trans political ads, 2026 midterms',
      'Outside research on the anti-trans ad campaign around the election. These figures come from other organisations, not from this project’s Twitter counts.')}
    <section class="outside" aria-labelledby="outside-label">
      <div class="outside-label" id="outside-label"><span class="chip three">OUTSIDE RESEARCH</span><span>NOT THIS PROJECT’S DATA · NOT COMPARED WITH OUR COUNTS</span></div>
      <ul class="notes">
        <li>Each item was checked by hand on its source page on 18 November 2026. Items from the original research that were not checked are left out.</li>
        <li>The figures come from different sources with different scopes and dates. They are not added together.</li>
        <li>This project counts posts on Twitter. It does not measure advertising, and these figures are not part of any chart.</li>
      </ul>
      ${CONTEXT_GROUPS.map(([title, items]) => `<h3 class="sect">${esc(title)}</h3>
        <ul class="facts">${items.map(([lead, text, id]) => {
          const s = src(id);
          return `<li><b>${esc(lead)}.</b> ${esc(text)} <span class="fact-src">SOURCE: ${s ? outLink(s.url, s.name) : '—'}</span></li>`;
        }).join('')}</ul>`).join('')}
      <h3 class="sect">Sources · ${CONTEXT_SOURCES.length}</h3>
      <ul class="notes refs">${CONTEXT_SOURCES.map((s) => `<li>${outLink(s.url, s.name)}</li>`).join('')}</ul>
    </section>
    <ul class="notes">
      <li>Our own measurements are on the <a href="#study">Study</a> tab.</li>
    </ul>`;
  enhance($('view'));
}

// ── Data tab ───────────────────────────────────────────────────────────────────
// Series file names, as monitor/config.py builds them: x.<slug of the query>.en.<metric>.
const slug = (text) => String(text).normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
const METRICS = [['posts', 'ORIGINAL POSTS / H'], ['reposts', 'REPOSTS / H'], ['replies', 'REPLIES / H'], ['repost-share', '% REPOSTS']];
let cff = null, versionsCache = null;

function seriesTable() {
  const fileLinks = (key, what) => `<a href="data/series/${esc(key)}.csv" aria-label="${esc(what)}, hourly CSV">CSV</a> · <a href="data/series/${esc(key)}.json" aria-label="${esc(what)}, hourly JSON">JSON</a>`;
  const list = Array.isArray(terms) ? terms : [];
  const termRows = list.map((t) => `<tr><td class="t-key wrap">${esc(String(t.label).toUpperCase())}</td><td class="t-phase">${esc(GROUP[t.family] || t.family)}</td>`
    + METRICS.map(([m, unit]) => `<td class="t-key">${fileLinks(`x.${slug(t.query)}.en.${m}`, `${t.label}, ${unit.toLowerCase()}`)}</td>`).join('') + '</tr>');
  const famRows = [['anti-trans', 'ANTI-TRANS FAMILY'], ['framing', 'FRAMING FAMILY']].map(([k, name]) => `<tr><td class="t-key wrap">${name}</td><td class="t-phase">${GROUP[k]}</td>`
    + `<td class="t-key">${fileLinks(`x.family.${k}.en.posts`, `${name.toLowerCase()}, original posts per hour`)}</td><td>—</td><td>—</td><td>—</td></tr>`);
  const probeRow = `<tr><td class="t-key wrap">PROBE · THING OR ANY OR TELL</td><td class="t-phase">PROBE</td><td class="t-key">${fileLinks('x.probe.en.posts', 'probe, original posts per hour')}</td><td>—</td><td>—</td><td>—</td></tr>`;
  const files = (list.length * METRICS.length + 3) * 2;
  return {
    files,
    html: tableWrap('Hourly files for every series',
      `${th('SERIES')}${th('GROUP')}${METRICS.map(([, unit]) => th(unit)).join('')}`,
      [...famRows, probeRow, ...termRows].join('')),
  };
}

function citationLine() {
  if (!cff) return null;
  const field = (name) => (cff.match(new RegExp(`^\\s*-?\\s*${name}:\\s*"?([^"\\n]+?)"?\\s*$`, 'm')) || [])[1] || null;
  const family = field('family-names'), given = field('given-names'), title = field('title'), url = field('url') || field('repository-code');
  if (!family || !title) return null;
  const built = study ? (study.provisional ? `provisional build of ${longDate(isoTs(study.built_at))}` : `version ${study.version}, frozen ${longDate(isoTs(study.built_at))}`) : null;
  return `${family}${given ? `, ${given}` : ''}. ${title}. ${study ? `${study.title}, ${built}. ` : ''}${url || ''}`;
}

async function fillData() {
  const go = currentRoute() === 'data';
  if (cff === null) {
    try { const r = await fetch('CITATION.cff', { cache: 'no-cache' }); cff = r.ok ? await r.text() : ''; } catch { cff = ''; }
  }
  if (study && !study.provisional && isNum(study.version) && versionsCache === null) {
    const ns = Array.from({ length: study.version }, (_, i) => i + 1);
    versionsCache = await Promise.all(ns.map((n) => getJson(`data/studies/${study.id}/v${n}.json`).then((v) => ({ n, v }), () => ({ n, v: null }))));
  }
  if (!go || currentRoute() !== 'data') return;  // the reader moved on
  const cite = $('cite-line');
  if (cite) { const c = citationLine(); cite.textContent = c || '—'; enhance(cite.parentElement); }
  const vers = $('versions');
  if (vers && versionsCache) {
    vers.innerHTML = tableWrap('Frozen versions of the study',
      `${th('VERSION', 't-num')}${th('FROZEN UTC')}${th('COMMIT')}${th('NOTE')}${th('FILE')}`,
      versionsCache.slice().reverse().map(({ n, v }) => `<tr><td class="t-num">${n}</td><td class="t-key">${v?.built_at ? `${dmy(isoTs(v.built_at))} ${hhmm(isoTs(v.built_at))}` : '—'}</td>`
        + `<td class="t-key"><code>${esc(v?.commit || '—')}</code></td><td class="wrap">${esc(v?.note || '—')}</td>`
        + `<td class="t-key"><a href="data/studies/${esc(study.id)}/v${n}.json">V${n} · JSON</a></td></tr>`).join(''));
    enhance(vers);
  }
}

function renderData() {
  const ser = seriesTable();
  const fileRow = (href, label, what) => `<tr><td class="t-key"><a href="${esc(href)}">${esc(label)}</a></td><td class="wrap">${what}</td></tr>`;
  let versionsHtml;
  if (!study) versionsHtml = '<p class="prose">The study file could not be loaded, so its versions are not known.</p>';
  else if (study.provisional) versionsHtml = '<p class="prose">No frozen version yet; the study page shows a provisional build.</p>';
  else versionsHtml = '<p class="note">LOADING VERSIONS</p>';

  $('view').innerHTML = `
    ${tabHead('Data · downloads, versions and citation',
      'Every number on this site can be downloaded. The files hold aggregate counts only.')}

    <h3 class="sect">Files</h3>
    ${tableWrap('Data files', `${th('FILE')}${th('WHAT IT HOLDS')}`, [
      fileRow('data/study.json', 'STUDY.JSON', 'Every number on the study page: the daily index of each family and term, normal ranges, before, event-day and after means, breadth and robustness. Provisional until a version is frozen.'),
      fileRow('data/daily.csv', 'DAILY.CSV', 'Daily totals for every series: <code>day_utc, key, value</code>. Only days with 20 or more hours are listed. For <code>repost-share</code> keys the value is a sum of hourly percentages, not a share: use the hourly files for those.'),
      fileRow('data/terms.json', 'TERMS.JSON', 'Each term: group, query, source, precision, 95% interval, posts checked, date added and median posts a day.'),
      fileRow('data/rejected.json', 'REJECTED.JSON', 'Searches screened out or held in the precision check of 16 November 2026, with the reason for each.'),
      fileRow('CITATION.cff', 'CITATION.CFF', 'How to cite the project, in Citation File Format.'),
    ].join(''))}

    <h3 class="sect">Hourly series · ${ser.files} files</h3>
    <p class="note">ONE CSV (<code>hour_end_utc, value</code>) AND ONE JSON (KEY, LABEL, UNIT, GROUP, POINTS) PER SERIES · TIMES UTC, EACH HOUR STAMPED AT ITS END · A MISSING HOUR IS ABSENT, NEVER ZERO</p>
    ${ser.html}

    <h3 class="sect">Frozen versions</h3>
    <div id="versions">${versionsHtml}</div>
    <ul class="notes">
      <li>A study is frozen once its window has closed and its data is in. Each version is kept with a note saying what changed and the code commit it was built from.</li>
    </ul>

    <h3 class="sect">Citation</h3>
    <p class="cite" id="cite-line">LOADING</p>
    <div class="links"><a class="chip ghost" href="CITATION.cff">CITATION.CFF</a></div>

    <h3 class="sect">Data rules</h3>
    <ul class="notes">
      <li>The files hold timestamps and aggregate hourly counts only. They hold no post text, usernames or account IDs, and the database has none to export.</li>
      <li>A failed or empty fetch is recorded as an error, not a zero. Missing hours are left out of the files, and a day with fewer than 20 hours has no daily value.</li>
      <li>The counts come from the Twitter API. How they are turned into an index is on the <a href="#methods">Methods</a> tab.</li>
    </ul>`;
  enhance($('view'));
  fillData();
}

// A lone "—" is read as "no data" (screen readers often skip the dash).
function enhance(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const dashes = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeValue.trim() === '—' && !n.parentElement.closest('[aria-hidden="true"], svg')) dashes.push(n);
  }
  for (const n of dashes) {
    const span_ = document.createElement('span');
    span_.innerHTML = '<span aria-hidden="true">—</span><span class="sr-only">no data</span>';
    n.replaceWith(span_);
  }
  for (const wrap of root.querySelectorAll('.table-wrap')) {
    if (wrap.scrollWidth > wrap.clientWidth + 1) {
      wrap.tabIndex = 0; wrap.setAttribute('role', 'region');
      wrap.setAttribute('aria-label', `${wrap.querySelector('table')?.getAttribute('aria-label') || 'Table'}, scrolls sideways`);
    }
  }
}

// ── Routing, theme, start ──────────────────────────────────────────────────────
// Hash routes: #terms, #methods, #context, #data; anything else is the study.
const ROUTES = { study: renderStudy, terms: renderTerms, methods: renderMethods, context: renderContext, data: renderData };
const TAB_NAME = { terms: 'Terms', methods: 'Methods', context: 'Context', data: 'Data' };
let loaded = false;  // the data files have been asked for and answered (or failed)

function currentRoute() {
  const r = location.hash.slice(1);
  return Object.hasOwn(ROUTES, r) ? r : 'study';
}

// `moveFocus`: a tab change by the reader (link, back or forward). Focus goes to the
// tab's heading so keyboard and screen-reader users start at the top of the new tab.
function route(moveFocus = false) {
  const current = currentRoute();
  for (const a of document.querySelectorAll('.nav a')) {
    if (a.dataset.route === current) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  if (!loaded) return;
  redrawMain = null;
  // Only the study needs study.json; without it the study keeps the boot screen and its error.
  const ready = current !== 'study' || study;
  $('boot').hidden = Boolean(ready);
  $('view').hidden = !ready;
  if (ready) ROUTES[current]();
  document.title = current === 'study'
    ? `${study ? `${study.title} · ` : ''}Anti-trans Rhetoric Monitor`
    : `${TAB_NAME[current]} · Anti-trans Rhetoric Monitor`;
  if (moveFocus) {
    window.scrollTo(0, 0);
    (current === 'study' || !ready ? $('title') : $('tab-h'))?.focus({ preventScroll: true });
  }
}

function setMode(mode, save) {
  document.documentElement.dataset.mode = mode;
  $('mode').setAttribute('aria-pressed', String(mode === 'light'));
  if (save) {
    try { localStorage.setItem('mode', mode); } catch { /* storage unavailable: the choice lasts this visit */ }
  }
}

async function getJson(path) {
  const r = await fetch(path, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function start() {
  setMode(document.documentElement.dataset.mode === 'light' ? 'light' : 'dark', false);
  $('mode').addEventListener('click', () => setMode(document.documentElement.dataset.mode === 'light' ? 'dark' : 'light', true));
  window.matchMedia?.('(prefers-color-scheme: light)').addEventListener?.('change', (e) => {
    let saved = null;
    try { saved = localStorage.getItem('mode'); } catch { /* storage unavailable */ }
    if (!saved) setMode(e.matches ? 'light' : 'dark', false);
  });
  route();
  const [st, te, re] = await Promise.allSettled([getJson('data/study.json'), getJson('data/terms.json'), getJson('data/rejected.json')]);
  study = st.status === 'fulfilled' ? st.value : null;
  terms = te.status === 'fulfilled' && Array.isArray(te.value) ? te.value : [];
  rejected = re.status === 'fulfilled' ? re.value : null;
  loaded = true;
  if (!study) {
    $('boot-step').textContent = 'NO DATA · RELOAD TO RETRY';
    $('boot').insertAdjacentHTML('beforeend', `<div class="boot-line">${esc(String(st.reason?.message || 'data/study.json').toUpperCase())}</div>`);
    route();
    return;
  }
  M = buildModel(study);
  $('title').textContent = `ANTI-TRANS RHETORIC MONITOR · ${study.title.toUpperCase()}`;
  const asOf = isoTs(study.as_of);
  $('sub-left').textContent = `TWITTER · ENGLISH · ORIGINAL POSTS · DATA TO ${asOf ? dmy(asOf) : '—'}`;
  $('provisional').innerHTML = study.provisional ? '<span class="chip three">PROVISIONAL</span>' : '';
  $('end-left').textContent = `END TRANSMISSION — BUILT ${dmy(isoTs(study.built_at))} ${hhmm(isoTs(study.built_at))} UTC`;
  enhance($('sub-left').parentElement);
  route();
}

// Skip links move focus without touching the hash, which is reserved for the tabs.
for (const a of document.querySelectorAll('a.skip')) {
  a.addEventListener('click', (e) => {
    const target = $(a.getAttribute('href').slice(1));
    if (!target) return;
    e.preventDefault();
    target.focus();
  });
}

window.addEventListener('hashchange', () => route(true));
let resizeTimer, lastWidth = window.innerWidth;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (window.innerWidth === lastWidth) return;  // phones fire resize on scroll (address bar)
    lastWidth = window.innerWidth;
    const el = $('main-chart');
    if (el && redrawMain && !el.contains(document.activeElement)) redrawMain();
  }, reduced ? 0 : 200);
});
start();
