'use strict';
// The page of "heirloom gui". It calls GuiApi (heirloom/gui/app.py) through pywebview and redraws from
// state() once a second. Text from Epic (titles) only ever goes into textContent or attributes.
// Nodes are kept and updated in place rather than rebuilt, so their transitions run (a cover filling with
// light, a progress ring) and their entrance animations play only when they appear.

const $ = (selector) => document.querySelector(selector);
const SVG = 'http://www.w3.org/2000/svg';
const ACTIVE = new Set(['queued', 'running']);
const DOWNLOADS = new Set(['install', 'uninstall']);
const DOING = {install: 'Installing', uninstall: 'Uninstalling', play: 'Playing', login: 'Logging in'};
const DONE = {install: 'Installed', uninstall: 'Uninstalled', play: 'Game closed', login: 'Logged in'};
const SHELVES = {all: 'Library', installed: 'Installed', updates: 'Updates'};
const RING = '<svg class="meter" viewBox="0 0 24 24" aria-hidden="true">'
  + '<circle class="track" cx="12" cy="12" r="10" pathLength="100"/>'
  + '<circle class="value" cx="12" cy="12" r="10" pathLength="100"/></svg>';

let api;
let state = {user: null, refreshing: false, notice: '', games: [], jobs: []};
let filter = 'all';
let libraryOrder = '';
let jobOrder = '';
let heroKey = '';
const cards = new Map();
const rows = new Map();
// finished jobs taken off the list with "Clear finished"
const cleared = new Set();

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((child) => child != null));
  return node;
}

function icon(name, className = 'icon') {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', className);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function button(label, className, onclick, iconName) {
  return el('button', {type: 'button', className, onclick}, iconName ? icon(iconName) : null, label);
}

function iconButton(iconName, label, className, onclick) {
  const node = el('button', {type: 'button', className: `icon-button ${className}`, title: label, onclick}, icon(iconName));
  node.setAttribute('aria-label', label);
  return node;
}

const run = (call) => call.then(poll);
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

function formatSize(bytes) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit && value < 10 ? 1 : 0)} ${units[unit]}`;
}

function formatPlayed(seconds) {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return 'Less than a minute played';
  const hours = Math.floor(minutes / 60);
  return `${[hours && `${hours} h`, minutes % 60 && `${minutes % 60} min`].filter(Boolean).join(' ')} played`;
}

function formatDay(iso) {
  const day = new Date(iso);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(day.toDateString())) / 864e5);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  const year = day.getFullYear() === today.getFullYear() ? {} : {year: 'numeric'};
  return `on ${day.toLocaleDateString(undefined, {day: 'numeric', month: 'long', ...year})}`;
}

function initials(title) {
  return title.split(/\s+/).filter(Boolean).slice(0, 2).map((word) => word[0].toUpperCase()).join('');
}

function activeJob(appName) {
  return state.jobs.findLast((job) => job.app_name === appName && ACTIVE.has(job.status)) || null;
}

function loggingIn() {
  return state.jobs.some((job) => job.kind === 'login' && ACTIVE.has(job.status));
}

function progressText(job) {
  if (job.status === 'queued') return 'Waiting for the current download';
  const parts = [DOING[job.kind]];
  if (job.progress !== null) parts.push(`${Math.floor(job.progress)}%`);
  if (job.speed) parts.push(job.speed);
  return parts.join(' · ');
}

function finishedText(job) {
  if (job.status === 'done') return DONE[job.kind];
  if (job.status === 'stopped') {
    return job.kind === 'install' ? 'Stopped. Install again to continue where it stopped.' : 'Cancelled';
  }
  return `Failed: ${job.message || 'see the terminal for details'}`;
}

function statusText(game, job) {
  if (job) return progressText(job);
  if (game.store) return `Available from ${game.store}`;
  if (!game.installed) return 'Not installed';
  const parts = [game.update ? 'Update available' : 'Installed'];
  if (game.size) parts.push(formatSize(game.size));
  return parts.join(' · ');
}

function actions(game, job, uninstall = true) {
  if (job) {
    return DOWNLOADS.has(job.kind) ? [button('Stop', 'ghost', () => run(api.stop(job.id)), 'x')] : [];
  }
  if (game.store) return [];
  const install = () => run(api.install(game.app_name));
  // citron is kept for playing and updating, so a library of uninstalled games isn't a wall of it
  if (!game.installed) return [button('Install', 'ghost', install, 'download')];
  const play = () => run(api.play(game.app_name));
  return [
    game.update ? button('Update', 'primary', install, 'updates') : button('Play', 'primary', play, 'play'),
    game.update ? iconButton('play', `Play ${game.title}`, 'ghost', play) : null,
    uninstall ? iconButton('trash', `Uninstall ${game.title}`, 'ghost danger', () => {
      if (confirm(`Uninstall ${game.title}? Its files will be deleted.`)) run(api.uninstall(game.app_name));
    }) : null,
  ].filter(Boolean);
}

// how much of the cover is lit, in percent: installed games are, the rest light up as they download
function lighting(game, job) {
  if (job && job.kind === 'play') return ['playing', 100];
  if (game.installed) return ['installed', 100];
  if (job && job.kind === 'install' && job.status === 'running' && job.progress !== null) return ['filling', job.progress];
  return ['unlit', 0];
}

function coverArt(game) {
  if (!game.cover) return el('span', {className: 'initials', textContent: initials(game.title)});
  return el('img', {
    src: game.cover, alt: '', loading: 'lazy',
    // offline, or the image is gone: show the initials instead
    onerror: (event) => event.target.replaceWith(el('span', {className: 'initials', textContent: initials(game.title)})),
  });
}

function card(game) {
  let entry = cards.get(game.app_name);
  if (!entry) {
    entry = {
      cover: el('div', {className: 'cover'}),
      shade: el('span', {className: 'shade'}),
      wick: el('span', {className: 'wick'}),
      badge: el('span', {className: 'badge', hidden: true}),
      title: el('h3', {className: 'title'}),
      status: el('p', {className: 'status'}),
      buttons: el('div', {className: 'actions'}),
      key: '',
      shown: false,
    };
    entry.node = el('article', {className: 'card'}, entry.cover,
      el('div', {className: 'info'}, entry.title, entry.status, entry.buttons));
    cards.set(game.app_name, entry);
  }
  const job = activeJob(game.app_name);
  const key = JSON.stringify([game, job]);
  if (key === entry.key) return entry;
  entry.key = key;

  if (entry.coverUrl !== game.cover) {
    entry.coverUrl = game.cover;
    entry.cover.replaceChildren(coverArt(game), entry.shade, entry.wick, entry.badge);
  }
  const [lit, percent] = lighting(game, job);
  entry.node.dataset.state = lit;
  entry.cover.style.setProperty('--lit', `${percent}%`);
  const playing = lit === 'playing';
  entry.badge.hidden = !playing && (!game.update || job !== null);
  entry.badge.textContent = playing ? 'Playing' : 'Update';
  entry.badge.classList.toggle('playing', playing);
  entry.title.textContent = game.title;
  entry.node.title = game.version ? `${game.title} (version ${game.version})` : game.title;
  entry.status.textContent = statusText(game, job);
  entry.buttons.replaceChildren(...actions(game, job));
  return entry;
}

function skeleton() {
  return el('div', {className: 'card skeleton', ariaHidden: 'true'},
    el('div', {className: 'cover'}), el('div', {className: 'line'}), el('div', {className: 'line'}));
}

function shown(game, query) {
  return (filter === 'all' || (filter === 'installed' && game.installed) || (filter === 'updates' && game.update))
    && (!query || game.title.toLowerCase().includes(query) || game.app_name.toLowerCase().includes(query));
}

function emptyText(query) {
  if (!state.games.length) {
    if (!state.user) return 'Log in to your Epic Games account to see your library.';
    return 'No games yet. Refresh to load your library.';
  }
  if (query) return `No games match "${$('#search').value.trim()}".`;
  if (filter === 'installed') return 'Nothing installed yet.';
  if (filter === 'updates') return 'Everything is up to date.';
  return 'No games yet.';
}

function renderLibrary() {
  const query = $('#search').value.trim().toLowerCase();
  const library = $('#library');
  const loading = state.refreshing && !state.games.length && Boolean(state.user);
  const entries = state.games.map(card);
  const order = loading ? 'loading' : state.games.map((game) => game.app_name).join('\n');
  if (order !== libraryOrder) {
    libraryOrder = order;
    library.replaceChildren(...(loading ? Array.from({length: 12}, skeleton) : entries.map((entry) => entry.node)));
  }
  let count = 0;
  state.games.forEach((game, index) => {
    const entry = entries[index];
    const show = shown(game, query);
    // a card coming into view rises in, after the ones before it
    if (show && !entry.shown) entry.node.style.setProperty('--i', String(Math.min(count, 14)));
    entry.node.hidden = !show;
    entry.shown = show;
    count += show;
  });
  $('#empty').hidden = loading || count > 0;
  $('#empty-text').textContent = emptyText(query);
  $('#empty-login').hidden = Boolean(state.user || state.games.length || loggingIn());
}

function renderShelves() {
  const installed = state.games.filter((game) => game.installed);
  const updates = state.games.filter((game) => game.update);
  const counts = {all: state.games.length, installed: installed.length, updates: updates.length};
  for (const item of document.querySelectorAll('[data-filter]')) {
    item.querySelector('.count').textContent = counts[item.dataset.filter] || '';
  }
  $('#heading').textContent = SHELVES[filter];
  let summary = '';
  if (filter === 'all' && state.games.length) {
    summary = `${plural(state.games.length, 'game')}, ${installed.length} installed`;
  } else if (filter === 'installed' && installed.length) {
    const size = installed.reduce((total, game) => total + (game.size || 0), 0);
    summary = `${plural(installed.length, 'game')}, ${formatSize(size)} on disk`;
  } else if (filter === 'updates' && updates.length) {
    summary = `${plural(updates.length, 'update')} ready to install`;
  }
  $('#summary').textContent = summary;
}

function moveMarker() {
  const active = document.querySelector(`[data-filter="${filter}"]`);
  $('#shelf-marker').style.setProperty('--y', `${active.offsetTop}px`);
}

function renderHero() {
  const played = state.games.filter((game) => game.installed && game.last_played)
    .sort((a, b) => b.last_played.localeCompare(a.last_played));
  const game = filter === 'all' && !$('#search').value.trim() ? played[0] : null;
  $('#hero').hidden = !game;
  if (!game) return;
  const job = activeJob(game.app_name);
  const key = JSON.stringify([game, job]);
  if (key === heroKey) return;
  heroKey = key;
  const art = $('#hero-art');
  const src = game.art || game.cover;
  if (art.getAttribute('src') !== src) art.src = src;
  art.hidden = !src;
  $('#hero-title').textContent = game.title;
  $('#hero-meta').textContent = job ? progressText(job)
    : `${formatPlayed(game.played)} · last played ${formatDay(game.last_played)}`;
  $('#hero-actions').replaceChildren(...actions(game, job, false));
}

function renderRail() {
  const account = $('#account');
  account.querySelector('.label').textContent = loggingIn() ? 'Logging in…' : state.user || 'Log in';
  account.disabled = loggingIn() || Boolean(state.user);
  account.title = state.user ? `Logged in as ${state.user}` : 'Log in to your Epic Games account';
  const refresh = $('#refresh');
  refresh.disabled = state.refreshing;
  refresh.classList.toggle('busy', state.refreshing);
  refresh.querySelector('.label').textContent = state.refreshing ? 'Refreshing…' : 'Refresh';
  $('#notice').hidden = !state.notice;
  $('#notice').textContent = state.notice;
  // only ever a link to a release page on GitHub
  const update = $('#heirloom-update');
  const release = state.update && state.update.url.startsWith('https://github.com/') ? state.update : null;
  update.hidden = !release;
  if (release) {
    update.href = release.url;
    update.title = `Heirloom ${release.version} "${release.name}" is out: open its download page`;
    update.querySelector('.label').textContent = `Get Heirloom ${release.version}`;
  }
}

function jobEnd(job, kind) {
  if (kind === 'live') return el('span', {className: 'live'});
  if (kind !== 'ring') return icon({done: 'done', failed: 'failed', stopped: 'x'}[kind], 'icon state');
  const label = `Stop ${DOING[job.kind].toLowerCase()} ${job.title}`;
  const stop = el('button', {type: 'button', className: 'ring', title: label, innerHTML: RING,
    onclick: () => run(api.stop(job.id))}, icon('x'));
  stop.setAttribute('aria-label', label);
  return stop;
}

function jobRow(job) {
  let row = rows.get(job.id);
  if (!row) {
    const game = state.games.find((candidate) => candidate.app_name === job.app_name);
    const thumb = game && game.cover ? el('img', {src: game.cover, alt: ''}) : icon(job.kind === 'login' ? 'account' : 'games');
    row = {detail: el('span', {className: 'detail'}), end: el('span', {className: 'job-end'}), kind: ''};
    row.node = el('li', {}, el('span', {className: 'thumb'}, thumb),
      el('span', {className: 'job-text'}, el('span', {className: 'what', textContent: job.title}), row.detail), row.end);
    rows.set(job.id, row);
  }
  const active = ACTIVE.has(job.status);
  row.node.className = `job ${job.status}`;
  row.detail.textContent = active ? progressText(job) : finishedText(job);
  const kind = !active ? job.status : DOWNLOADS.has(job.kind) ? 'ring' : 'live';
  if (kind !== row.kind) {
    row.kind = kind;
    row.end.replaceChildren(jobEnd(job, kind));
  }
  row.end.style.setProperty('--p', String(job.progress || 0));
  return row.node;
}

function renderJobs() {
  const jobs = state.jobs.filter((job) => !cleared.has(job.id)).slice(-8).reverse();
  $('#activity').hidden = jobs.length === 0;
  if (!jobs.length) return;
  const active = jobs.filter((job) => ACTIVE.has(job.status));
  const running = active.find((job) => job.status === 'running' && DOWNLOADS.has(job.kind));
  let title = 'Done';
  if (active.length === 1) title = `${DOING[active[0].kind]} ${active[0].title}`;
  else if (active.length) title = `${active.length} in progress`;
  $('#dock-title').textContent = title;
  $('#dock-progress').style.setProperty('--done', String(running ? (running.progress || 0) / 100 : 0));
  $('#activity-clear').disabled = active.length === jobs.length;
  const nodes = jobs.map(jobRow);
  const order = jobs.map((job) => job.id).join();
  if (order !== jobOrder) {
    jobOrder = order;
    $('#jobs').replaceChildren(...nodes);
  }
}

function render() {
  renderRail();
  renderShelves();
  renderHero();
  renderLibrary();
  renderJobs();
}

async function poll() {
  try {
    state = await api.state();
  } catch (error) {
    console.error('Reading heirloom\'s state failed', error);
    return;
  }
  render();
}

async function showThemes(info) {
  const themes = info || await api.themes();
  document.documentElement.dataset.theme = themes.active;
  $('#theme-css').textContent = themes.css;
  $('#theme').replaceChildren(...themes.themes.map((theme) =>
    el('option', {value: theme.name, textContent: theme.title, selected: theme.name === themes.active})));
  const active = themes.themes.find((theme) => theme.name === themes.active);
  $('#theme-name').textContent = active ? `${active.title} theme` : 'Theme';
}

function setFilter(name) {
  filter = name;
  for (const item of document.querySelectorAll('[data-filter]')) {
    item.setAttribute('aria-pressed', String(item.dataset.filter === name));
  }
  moveMarker();
  renderShelves();
  renderHero();
  renderLibrary();
}

async function start() {
  api = window.pywebview.api;
  const login = () => run(api.login());
  $('#account').onclick = login;
  $('#empty-login').onclick = login;
  $('#refresh').onclick = () => run(api.refresh());
  $('#search').oninput = () => {
    renderHero();
    renderLibrary();
  };
  $('#theme').onchange = async (event) => showThemes(await api.use_theme(event.target.value));
  for (const item of document.querySelectorAll('[data-filter]')) item.onclick = () => setFilter(item.dataset.filter);
  $('#rail-toggle').onclick = () => {
    const collapsed = $('#rail').classList.toggle('collapsed');
    const toggle = $('#rail-toggle');
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.title = collapsed ? 'Expand the sidebar' : 'Collapse the sidebar';
    toggle.querySelector('.label').textContent = collapsed ? 'Expand' : 'Collapse';
  };
  $('#activity-toggle').onclick = () => {
    const collapsed = $('#activity').classList.toggle('collapsed');
    const toggle = $('#activity-toggle');
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.title = collapsed ? 'Show the list' : 'Hide the list';
  };
  $('#activity-clear').onclick = () => {
    for (const job of state.jobs) if (!ACTIVE.has(job.status)) cleared.add(job.id);
    renderJobs();
  };
  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest('input, select, textarea');
    if (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      $('#search').focus();
    }
  });
  moveMarker();
  await showThemes();
  await poll();
  api.refresh();
  setInterval(poll, 1000);
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener('pywebviewready', start, {once: true});
