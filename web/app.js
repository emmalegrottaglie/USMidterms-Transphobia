// Anti-trans Rhetoric Monitor: the study page.
//
// Reads data/study.json (monitor/study.py `build`, or the newest frozen version) and
// data/terms.json (monitor/static.py) and draws them. No numbers are made up here: a
// value the data does not have is shown as "—", and a line breaks where a day is
// missing. Day keys in study.json are UTC day starts in seconds, as strings.

const DAY = 86400;
const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const REPO = 'https://github.com/emmalegrottaglie/USMidterms-Transphobia';
const SCALE_LO = 40, SCALE_HI = 250;  // small multiples: one fixed scale for every term
const MIN_REFERENCE_DAYS = 14;        // as monitor/analysis.py

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

let study = null, terms = [], M = null;
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
    phaseDates: `BEFORE ${span(s.window.start, ev.start - DAY)} · ${evDay === 'EVENT' ? `EVENT ${span(ev.start, ev.end)}` : `${event ? event.short : 'EVENT'} DAY ${evDay}`} · AFTER ${span(after.start, after.end)}`,
    baseline: `100 = SAME WEEKDAY, ${refRange}`,
    bandWords: 'SHADED = 5TH–95TH PERCENTILE OF REFERENCE DAYS',
  };
}

// 5th–95th percentile of the reference days, the same rule as monitor/analysis.py `band`
// (linear interpolation, at least 14 reference days, else none). Used for each term's
// own band; the family bands come ready-made in study.json.
function refBand(values) {
  const vs = M.days.map((d, i) => (M.phaseOf(d) === 'ref' ? values[i] : null)).filter(isNum).sort((a, b) => a - b);
  if (vs.length < MIN_REFERENCE_DAYS) return null;
  const q = (p) => { const pos = p * (vs.length - 1), lo = Math.floor(pos), hi = Math.min(lo + 1, vs.length - 1); return vs[lo] + (vs[hi] - vs[lo]) * (pos - lo); };
  return [q(0.05), q(0.95)];
}

// Mean over the after phase, as monitor/study.py `_phases` (null with no day).
function afterMean(values) {
  const vs = values.filter((v, i) => isNum(v) && M.phaseOf(M.days[i]) === 'after');
  return vs.length ? Math.round((vs.reduce((a, b) => a + b, 0) / vs.length) * 100) / 100 : null;
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
function spark(values, cls) {
  const VW = 160, VH = 60, top = 4, h = VH - 8, n = values.length;
  const x = (i) => ((i + 0.5) * VW) / n;
  const y = (v) => top + ((SCALE_HI - Math.max(SCALE_LO, Math.min(SCALE_HI, v))) / (SCALE_HI - SCALE_LO)) * h;
  const b = refBand(values);
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
  const sp = spark(values, cls);
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
    { name: 'Breadth of the anti-trans terms, each term weighted equally', short: 'BREADTH', cls: 's-breadth', values: breadthVals, summary: `after ${n0(afterMean(breadthVals))}` },
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
  const breadthAfter = (k) => afterMean(M.at(s.breadth?.[k]?.daily));
  const placeboWord = (k) => { const a = fam(k).phases?.after; return isNum(a) ? (a >= 100 ? 'AT OR ABOVE' : 'AT OR BELOW') : 'AS FAR FROM 100 AS'; };
  const robRows = [
    ['AFTER · HEADLINE INDEX (PROBE-NORMALISED)', (k) => n1(rob(k).raw_vs_probe?.probe)],
    ['AFTER · WITHOUT PROBE NORMALISATION', (k) => n1(rob(k).raw_vs_probe?.raw)],
    ['AFTER · SUM OF TERM COUNTS, ORIGINAL POSTS', (k) => n1(rob(k).originals_vs_reposts?.posts)],
    ['AFTER · SUM OF TERM COUNTS, REPOSTS', (k) => n1(rob(k).originals_vs_reposts?.reposts)],
    ['AFTER · BREADTH, ALL TERMS', (k) => n1(breadthAfter(k))],
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
    ['CITATION.CFF', `${REPO}/blob/main/CITATION.cff`],
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
    <div class="links">${links.map(([label, href]) => `<a class="chip ghost" href="${esc(href)}"${href.startsWith('http') ? ' rel="noopener"' : ''}>${esc(label)}</a>`).join('')}</div>
    <ul class="notes">
      <li>Every series also has an hourly CSV and JSON file in <code>data/series/</code>, named by its series key. Times are UTC; an hour is stamped at its end.</li>
    </ul>`;

  redrawMain = () => mainChart($('main-chart'), $('main-readout'), { series, bands });
  redrawMain();
  enhance($('view'));
}

function renderPlaceholder(route) {
  $('view').innerHTML = `<h2 class="sect">${esc(route)}</h2>
    <div class="nodata">THIS TAB IS NOT PUBLISHED YET<br><a href="#study">BACK TO THE STUDY</a></div>`;
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
function route() {
  const r = (location.hash || '#study').slice(1) || 'study';
  const known = ['study', 'terms', 'methods', 'context', 'data'];
  const current = known.includes(r) ? r : 'study';
  for (const a of document.querySelectorAll('.nav a')) {
    if (a.dataset.route === current) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
  if (!study) return;
  redrawMain = null;
  if (current === 'study') renderStudy(); else renderPlaceholder(current);
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
  try {
    [study, terms] = await Promise.all([getJson('data/study.json'), getJson('data/terms.json').catch(() => [])]);
  } catch (e) {
    $('boot-step').textContent = 'NO DATA · RELOAD TO RETRY';
    $('boot').insertAdjacentHTML('beforeend', `<div class="boot-line">${esc(e.message.toUpperCase())}</div>`);
    return;
  }
  M = buildModel(study);
  $('title').textContent = `ANTI-TRANS RHETORIC MONITOR · ${study.title.toUpperCase()}`;
  document.title = `${study.title} · Anti-trans Rhetoric Monitor`;
  const asOf = isoTs(study.as_of);
  $('sub-left').textContent = `TWITTER · ENGLISH · ORIGINAL POSTS · DATA TO ${asOf ? dmy(asOf) : '—'}`;
  $('provisional').innerHTML = study.provisional ? '<span class="chip three">PROVISIONAL</span>' : '';
  $('end-left').textContent = `END TRANSMISSION — BUILT ${dmy(isoTs(study.built_at))} ${hhmm(isoTs(study.built_at))} UTC`;
  enhance($('sub-left').parentElement);
  $('boot').hidden = true;
  $('view').hidden = false;
  route();
}

window.addEventListener('hashchange', () => { route(); if (location.hash && location.hash !== '#study') $('view').focus({ preventScroll: true }); });
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
