// What looks broken in the page: text that spills or is cut off, poor contrast, and bars covered when scrolled.
// A list of problems, as text. window_probe.py runs it on each screen.
() => [...(() => {
  const root = [...document.querySelectorAll('dialog[open]')].pop() || document.body;
  const label = (el) => (el.id ? '#' + el.id : el.tagName.toLowerCase()) + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '');
  const visible = (el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const parse = (c) => { const srgb = c.startsWith('color(srgb'); const m = c.replace('color(srgb', '').match(/[\d.]+(?:e-?\d+)?/g); if (!m) return null; const k = srgb ? 255 : 1; return {r: +m[0] * k, g: +m[1] * k, b: +m[2] * k, a: m[3] === undefined ? 1 : +m[3]}; };
  const lum = ({r, g, b}) => { const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const blend = (top, under) => ({r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1});
  const background = (el) => { const layers = [];
    for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none' || s.backdropFilter && s.backdropFilter !== 'none') { if (s.backgroundImage !== 'none') return null; }
      const c = parse(s.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a === 1) break; } }
    let base = {r: 255, g: 255, b: 255, a: 1};
    if (!layers.length || layers[layers.length - 1].a < 1) { const page = [document.body, document.documentElement].map((e) => parse(getComputedStyle(e).backgroundColor)).find((c) => c && c.a > 0); base = page || parse(getComputedStyle(document.documentElement).getPropertyValue('--bg')) || base; }
    return layers.reverse().reduce((under, top) => blend(top, under), base); };
  const issues = [];
  const add = (kind, el, detail) => issues.push(`${kind} ${label(el)} ${detail}`);
  const page = document.documentElement;
  if (page.scrollWidth > innerWidth + 1) issues.push(`page-wider-than-window ${page.scrollWidth} > ${innerWidth}`);
  const within = root === document.body ? document.body : root;
  for (const el of within.querySelectorAll('*')) {
    if (!visible(el) || el.closest('svg') || el.closest('dialog:not([open])') || el.closest('.card:nth-child(n+40)')) continue;
    if (root === document.body && el.closest('dialog')) continue;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    const text = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0 && s.overflowX === 'visible' && s.display !== 'inline') add('spills-out', el, `${el.scrollWidth}>${el.clientWidth}`);
    if (text && s.overflowX === 'hidden' && s.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 1) add('cut-off-text', el, JSON.stringify(el.textContent.trim().slice(0, 24)));
    if (text && s.overflowY === 'hidden' && el.scrollHeight > el.clientHeight + 2 && !s.webkitLineClamp?.match(/\d/)) add('cut-off-vertically', el, JSON.stringify(el.textContent.trim().slice(0, 24)));
    if (!el.closest('#library') && !el.closest('.shelves') && !el.closest('.scroll') && (r.right > innerWidth + 1 || r.left < -1) && s.position !== 'fixed' && !el.closest('.game-body')) add('off-screen', el, `${Math.round(r.left)}..${Math.round(r.right)}`);
    if (text) {
      const size = parseFloat(s.fontSize);
      if (size < 10.5) add('tiny-text', el, `${size}px`);
      const bg = background(el), fg = parse(s.color);
      if (bg && fg && fg.a > 0) {
        const f = blend(fg, bg), a = lum(f), b = lum(bg), ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        const large = size >= 24 || (size >= 18.66 && +s.fontWeight >= 700);
        if (ratio < (large ? 3 : 4.5) && !el.closest('[disabled]')) add('low-contrast', el, `${ratio.toFixed(1)}:1 ${JSON.stringify(el.textContent.trim().slice(0, 18))}`);
      }
    }
  }
  return [...new Set(issues)];
})(), ...(() => { const issues = [];
  for (const sel of ['.top', '.library-head', '.rail']) { const bar = document.querySelector(sel); if (!bar) continue; const r = bar.getBoundingClientRect();
    if (getComputedStyle(bar).display === 'none' || r.bottom < 4 || r.top > innerHeight) continue;
    for (const fx of [.08, .3, .5, .7, .92]) { const x = r.left + r.width * fx, y = r.top + r.height / 2; const hit = document.elementFromPoint(x, y);
      if (hit && !hit.closest(sel) && !hit.closest('.dock, .menu, dialog')) issues.push(`${sel} covered by ${hit.className || hit.tagName} at ${Math.round(x)},${Math.round(y)}`); } }
  return issues; })()]
