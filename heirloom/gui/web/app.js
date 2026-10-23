'use strict';
// The page of "heirloom gui". It calls GuiApi (heirloom/gui/app.py) through pywebview and redraws from
// state() once a second. Text from Epic (titles) only ever goes into textContent.

const $ = (selector) => document.querySelector(selector);
const ACTIVE = new Set(['queued', 'running']);
const DOWNLOADS = new Set(['install', 'uninstall']);
const DOING = {install: 'Installing', uninstall: 'Uninstalling', play: 'Playing', login: 'Logging in'};
const DONE = {install: 'Installed', uninstall: 'Uninstalled', play: 'Game closed', login: 'Logged in'};

let api;
let state = {user: null, refreshing: false, notice: '', games: [], jobs: []};
let filter = 'all';
const cards = new Map();

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((child) => child != null));
  return node;
}

function button(label, className, onclick) {
  return el('button', {type: 'button', className, textContent: label, onclick});
}

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

function actions(game, job) {
  if (job) {
    return DOWNLOADS.has(job.kind) ? [button('Stop', 'ghost', () => api.stop(job.id).then(poll))] : [];
  }
  if (game.store) return [];
  if (!game.installed) return [button('Install', 'primary', () => api.install(game.app_name).then(poll))];
  const list = [];
  if (game.update) list.push(button('Update', 'primary', () => api.install(game.app_name).then(poll)));
  list.push(button('Play', game.update ? 'ghost' : 'primary', () => api.play(game.app_name).then(poll)));
  list.push(button('Uninstall', 'ghost danger', () => {
    if (confirm(`Uninstall ${game.title}? Its files will be deleted.`)) api.uninstall(game.app_name).then(poll);
  }));
  return list;
}

function card(game) {
  let entry = cards.get(game.app_name);
  if (!entry) {
    entry = {
      cover: el('div', {className: 'cover'}),
      badge: el('span', {className: 'badge', textContent: 'Update', hidden: true}),
      title: el('h3', {className: 'title'}),
      status: el('p', {className: 'status'}),
      fill: el('div', {className: 'bar-fill'}),
      buttons: el('div', {className: 'actions'}),
      key: '',
    };
    entry.track = el('div', {className: 'bar-track', hidden: true}, entry.fill);
    entry.node = el('article', {className: 'card'}, entry.cover,
      el('div', {className: 'info'}, entry.title, entry.status, entry.track, entry.buttons));
    cards.set(game.app_name, entry);
  }
  const job = activeJob(game.app_name);
  const key = JSON.stringify([game, job]);
  if (key === entry.key) return entry.node;
  entry.key = key;

  if (entry.coverUrl !== game.cover) {
    entry.coverUrl = game.cover;
    const art = game.cover
      ? el('img', {src: game.cover, alt: '', loading: 'lazy'})
      : el('span', {className: 'initials', textContent: initials(game.title)});
    entry.cover.replaceChildren(art, entry.badge);
  }
  entry.badge.hidden = !game.update || job !== null;
  entry.title.textContent = game.title;
  entry.node.title = game.version ? `${game.title} (version ${game.version})` : game.title;
  entry.status.textContent = statusText(game, job);
  const progress = job && job.progress !== null ? job.progress : null;
  entry.track.hidden = progress === null;
  entry.fill.style.width = `${progress || 0}%`;
  entry.buttons.replaceChildren(...actions(game, job));
  return entry.node;
}

function visibleGames() {
  const query = $('#search').value.trim().toLowerCase();
  return state.games.filter((game) =>
    (filter === 'all' || (filter === 'installed' && game.installed) || (filter === 'updates' && game.update))
    && (!query || game.title.toLowerCase().includes(query) || game.app_name.toLowerCase().includes(query)));
}

function renderLibrary() {
  const games = visibleGames();
  $('#library').replaceChildren(...games.map(card));
  $('#empty').hidden = games.length > 0;
  if (games.length) return;
  let text = 'No games yet. Refresh to load your library.';
  if (state.games.length) text = 'No games match.';
  else if (!state.user) text = 'Log in to your Epic Games account to see your library.';
  else if (state.refreshing) text = 'Loading your library…';
  $('#empty-text').textContent = text;
  $('#empty-login').hidden = Boolean(state.user || state.games.length || loggingIn());
}

function renderHeader() {
  const account = $('#account');
  account.textContent = loggingIn() ? 'Logging in…' : state.user || 'Log in';
  account.disabled = loggingIn() || Boolean(state.user);
  account.title = state.user ? `Logged in as ${state.user}` : '';
  const refresh = $('#refresh');
  refresh.disabled = state.refreshing;
  refresh.textContent = state.refreshing ? 'Refreshing…' : 'Refresh';
  $('#notice').hidden = !state.notice;
  $('#notice').textContent = state.notice;
}

function renderJobs() {
  const jobs = state.jobs.slice(-6).reverse();
  $('#activity').hidden = jobs.length === 0;
  $('#jobs').replaceChildren(...jobs.map((job) => {
    const active = ACTIVE.has(job.status);
    const row = el('li', {className: `job ${job.status}`},
      el('span', {className: 'what', textContent: job.title}),
      active && DOWNLOADS.has(job.kind) ? button('Stop', 'ghost', () => api.stop(job.id).then(poll)) : null,
      el('span', {className: 'detail', textContent: active ? progressText(job) : finishedText(job)}));
    if (active && job.progress !== null) {
      const fill = el('div', {className: 'bar-fill'});
      fill.style.width = `${job.progress}%`;
      row.append(el('div', {className: 'bar-track'}, fill));
    }
    return row;
  }));
}

function render() {
  renderHeader();
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
}

async function start() {
  api = window.pywebview.api;
  const login = () => api.login().then(poll);
  $('#account').onclick = login;
  $('#empty-login').onclick = login;
  $('#refresh').onclick = () => api.refresh().then(poll);
  $('#search').oninput = renderLibrary;
  $('#activity-toggle').onclick = () => {
    const collapsed = $('#activity').classList.toggle('collapsed');
    $('#activity-toggle').setAttribute('aria-expanded', String(!collapsed));
  };
  $('#theme').onchange = async (event) => showThemes(await api.use_theme(event.target.value));
  for (const chip of document.querySelectorAll('[data-filter]')) {
    chip.onclick = () => {
      filter = chip.dataset.filter;
      for (const other of document.querySelectorAll('[data-filter]')) {
        other.setAttribute('aria-pressed', String(other === chip));
      }
      renderLibrary();
    };
  }
  await showThemes();
  await poll();
  api.refresh();
  setInterval(poll, 1000);
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener('pywebviewready', start, {once: true});
