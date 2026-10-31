'use strict';
// The page of "heirloom gui". It calls GuiApi (heirloom/gui/app.py) through pywebview and redraws from
// state() once a second. Text from Epic (titles) only ever goes into textContent or attributes.
// Nodes are kept and updated in place rather than rebuilt, so their transitions run (a cover filling with
// light, a progress ring) and their entrance animations play only when they appear.

const $ = (selector) => document.querySelector(selector);
const SVG = 'http://www.w3.org/2000/svg';
const ACTIVE = new Set(['queued', 'running']);
const DOWNLOADS = new Set(['install', 'uninstall', 'repair', 'overlay']);
const DOING = {install: 'Installing', uninstall: 'Uninstalling', repair: 'Repairing', sync: 'Syncing saves',
  play: 'Playing', login: 'Logging in', overlay: 'Installing', overlay_remove: 'Removing', move: 'Moving',
  import: 'Adding', activate: 'Activating'};
const DONE = {install: 'Installed', uninstall: 'Uninstalled', repair: 'Repaired', sync: 'Saves synced',
  play: 'Game closed', login: 'Logged in', overlay: 'Installed and on', overlay_remove: 'Removed', move: 'Moved',
  import: 'Added', activate: 'Activated'};
const SHELVES = {all: 'Library', installed: 'Installed', updates: 'Updates'};
// how the library can be ordered; the library comes sorted by title, which breaks ties
const SORTS = {
  title: ['A to Z', () => 0],
  recent: ['Recently played', (a, b) => (b.last_played || '').localeCompare(a.last_played || '')],
  played: ['Most played', (a, b) => b.played - a.played],
  size: ['Largest', (a, b) => (b.size || 0) - (a.size || 0)],
};
const RING = '<svg class="meter" viewBox="0 0 24 24" aria-hidden="true">'
  + '<circle class="track" cx="12" cy="12" r="10" pathLength="100"/>'
  + '<circle class="value" cx="12" cy="12" r="10" pathLength="100"/></svg>';

let api;
let state = {user: null, refreshing: false, notice: '', games: [], jobs: []};
let libraryDrawn = '';
let filter = 'all';
let sort = 'title';
// the notice closed with its X, until a different one comes
let dismissedNotice = '';
let libraryOrder = '';
let jobOrder = '';
let heroKey = '';
// the states of the Epic overlay's jobs, to redraw Customize when one finishes
let overlayJobs = '';
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

function actions(game, job) {
  if (job) {
    return DOWNLOADS.has(job.kind) ? [button('Stop', 'ghost', () => run(api.stop(job.id)), 'x')] : [];
  }
  // games of other stores are played there; Ubisoft's need adding to the Ubisoft account first
  if (game.store) {
    return game.ubisoft ? [button('Activate', 'ghost', () => run(api.activate_ubisoft()), 'done')] : [];
  }
  const install = () => run(api.install(game.app_name));
  // citron is kept for playing and updating, so a library of uninstalled games isn't a wall of it
  if (!game.installed) return [button('Install', 'ghost', () => openInstall(game), 'download')];
  return [
    game.update ? button('Update', 'primary', install, 'updates')
      : button('Play', 'primary', () => run(api.play(game.app_name)), 'play'),
    manageButton(game),
  ];
}

function manageButton(game) {
  const node = iconButton('manage', `Manage ${game.title}`, 'ghost', (event) => openManage(game, event.currentTarget));
  node.setAttribute('aria-haspopup', 'menu');
  return node;
}

// a choice in a menu: it closes the menu, then does its thing
function menuItem(label, iconName, onclick, className = '') {
  return el('button', {
    type: 'button', role: 'menuitem', className,
    onclick: (event) => {
      event.currentTarget.closest('.menu').hidePopover();
      onclick();
    },
  }, icon(iconName), label);
}

function showMenu(menu, anchor, children, at = null) {
  menu.replaceChildren(...children.filter(Boolean));
  // closing it with Escape or a choice puts the keyboard back on the button
  menu.onbeforetoggle = (event) => {
    if (event.newState === 'closed' && anchor.isConnected && menu.contains(document.activeElement)) anchor.focus();
  };
  menu.showPopover();
  // below the button (or the pointer), or above it when there's no room, and kept inside the window
  const button = at ? {left: at.x, right: at.x, top: at.y, bottom: at.y} : anchor.getBoundingClientRect();
  const {width, height} = menu.getBoundingClientRect();
  const below = button.bottom + 6 + height <= innerHeight;
  menu.style.left = `${Math.max(8, Math.min(button.right - width, innerWidth - width - 8))}px`;
  menu.style.top = `${below ? button.bottom + 6 : Math.max(8, button.top - 6 - height)}px`;
  (menu.querySelector('[aria-checked="true"]') || menu.querySelector('[role^="menuitem"]')).focus();
}

const achievementsItem = (game) => (game.achievements
  ? menuItem('Achievements…', 'done', () => openAchievements(game)) : null);
const activate = (game) => (game.ubisoft
  ? menuItem('Activate on Ubisoft Connect', 'done', () => run(api.activate_ubisoft())) : null);

function openManage(game, anchor, at = null) {
  if (!game.installed) {
    showMenu($('#manage'), anchor, [
      el('p', {className: 'menu-title', textContent: game.title}),
      menuItem('Install…', 'download', () => openInstall(game)),
      menuItem('Already on this PC…', 'folder', () => locateGame(game)),
      achievementsItem(game),
      activate(game),
    ], at);
    return;
  }
  showMenu($('#manage'), anchor, [
    el('p', {className: 'menu-title', textContent: game.title}),
    game.update ? menuItem('Play without updating', 'play', () => run(api.play(game.app_name))) : null,
    menuItem('Open folder', 'folder', () => run(api.open_folder(game.app_name))),
    menuItem('Create desktop shortcut', 'desktop', () => run(api.create_shortcut(game.app_name))),
    menuItem('Launch options…', 'play', () => openLaunchOptions(game)),
    achievementsItem(game),
    menuItem('Verify and repair', 'repair', () => run(api.repair(game.app_name))),
    menuItem('Move…', 'folder', () => moveGame(game)),
    game.dlcs ? menuItem('DLC…', 'download', () => openDlcs(game)) : null,
    game.cloud_saves ? menuItem('Cloud saves…', 'cloud', () => openSaves(game)) : null,
    activate(game),
    el('hr'),
    menuItem('Uninstall', 'trash', () => {
      if (confirm(`Uninstall ${game.title}? Its files will be deleted.`)) run(api.uninstall(game.app_name));
    }, 'danger'),
  ], at);
}

// the dialog of the Manage menu's DLC and cloud saves, filled in with its title and rows
function showDetail(title, ...children) {
  $('#detail-title').textContent = title;
  $('#detail-body').replaceChildren(...children.filter(Boolean));
  if (!$('#detail').open) $('#detail').showModal();
}

const hint = (text, className = 'hint') => el('p', {className, textContent: text});
// an action of the dialog: it closes, then the job starts
const detailAction = (call) => () => {
  $('#detail').close();
  run(call());
};

async function moveGame(game) {
  const chosen = await api.choose_folder((await api.settings()).install_dir);
  if (!chosen) return;
  try {
    await run(api.move(game.app_name, chosen.folder));
  } catch (failure) {
    alert(failure.message || String(failure));
  }
}

// adds a game from a folder it is already in, rather than downloading it
async function locateGame(game, current = null) {
  const chosen = await api.choose_folder(current || (await api.settings()).install_dir);
  if (chosen) run(api.import_game(game.app_name, chosen.folder));
}

async function openDlcs(game) {
  const dlcs = await api.dlcs(game.app_name);
  showDetail(`DLC of ${game.title}`, dlcs.length ? el('ul', {className: 'rows'}, ...dlcs.map((dlc) => el('li', {className: 'row'},
    el('span', {className: 'row-text'}, el('span', {className: 'what', textContent: dlc.title}),
      el('span', {className: 'detail', textContent: dlc.installed ? 'Installed' : 'Not installed'})),
    dlc.installed
      ? iconButton('trash', `Uninstall ${dlc.title}`, 'danger', () => {
        if (confirm(`Uninstall ${dlc.title}? Its files will be deleted.`)) detailAction(() => api.uninstall(dlc.app_name))();
      })
      : button('Install', 'ghost', detailAction(() => api.install(dlc.app_name)), 'download'))))
    : hint('Its DLC comes with the game.'));
}

// when a save was made, as "today at 21:40"
const savedAt = (iso) => `${formatDay(iso)} at ${new Date(iso).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`;
const SAVES = {
  local_newer: (saves) => `The saves on this PC, from ${savedAt(saves.local)}, are newer than the cloud's`
    + `${saves.cloud ? `, from ${savedAt(saves.cloud)}` : ''}. Syncing uploads them.`,
  remote_newer: (saves) => `The cloud's saves, from ${savedAt(saves.cloud)}, are newer than the ones on this PC`
    + `${saves.local ? `, from ${savedAt(saves.local)}` : ''}. Syncing downloads them.`,
  same_age: (saves) => `In sync: the saves here and in the cloud are from ${savedAt(saves.cloud)}.`,
  no_save: () => 'No saves yet, here or in the cloud.',
};

async function openSaves(game) {
  const title = `Cloud saves of ${game.title}`;
  const actions = el('div', {className: 'panel-actions'},
    button('Sync now', 'primary', detailAction(() => api.sync_saves(game.app_name)), 'cloud'));
  showDetail(title, hint('Asking Epic…'), actions);
  let found;
  try {
    const saves = await api.save_status(game.app_name);
    found = [hint(SAVES[saves.status](saves)), hint(saves.folder, 'hint path')];
  } catch (failure) {
    found = [hint('Could not ask Epic about them. Syncing may still work.')];
  }
  // unless it was closed, or another game's opened, meanwhile
  if ($('#detail').open && $('#detail-title').textContent === title) showDetail(title, ...found, actions);
}

// one achievement: its icon, name and what it takes, then when you got it or how far along you are, and how rare it is
function achievementRow(item) {
  const rarity = item.rarity === null ? '' : `${item.rarity}% of players`;
  const how = item.unlocked ? (item.date ? `Unlocked ${savedAt(item.date)}` : 'Unlocked')
    : item.progress > 0 ? `${Math.floor(item.progress * 100)}% done` : '';
  return el('li', {className: `row achievement${item.unlocked ? ' unlocked' : ''}`},
    item.icon ? el('img', {src: item.icon, alt: '', loading: 'lazy', className: 'achievement-icon'}) : null,
    el('span', {className: 'row-text'}, el('span', {className: 'what', textContent: item.name}),
      el('span', {className: 'detail', textContent: item.description}),
      el('span', {className: 'detail', textContent: [how, rarity].filter(Boolean).join(' · ')})));
}

async function openAchievements(game) {
  const title = `Achievements of ${game.title}`;
  showDetail(title, hint('Asking Epic…'));
  let found;
  try {
    const got = await api.achievements(game.app_name);
    found = got ? [
      hint(`${got.unlocked} of ${got.total} unlocked · ${got.xp} of ${got.total_xp} XP`),
      el('ul', {className: 'rows'}, ...got.achievements.map(achievementRow)),
      got.hidden ? hint(`And ${plural(got.hidden, 'hidden achievement')}, shown once unlocked.`) : null,
    ] : [hint('This game has no achievements.')];
  } catch (failure) {
    found = [hint('Could not ask Epic about them. Try again in a moment.')];
  }
  // unless it was closed, or another game's opened, meanwhile
  if ($('#detail').open && $('#detail-title').textContent === title) showDetail(title, ...found);
  poll();
}

// the tiles over a cover being downloaded, and the order they light up in as it goes: scattered, the same every time
const TILES = 48;
const scatter = (index) => Math.abs(Math.sin(index * 12.9898) * 43758.5453) % 1;
const TILE_TURN = Array.from({length: TILES}, (_, index) => index).sort((a, b) => scatter(a) - scatter(b))
  .reduce((turns, tile, turn) => Object.assign(turns, {[tile]: turn}), []);

function assemble(entry, percent) {
  if (percent === null) {
    if (entry.tiles) entry.tiles.remove();
    entry.tiles = null;
    return;
  }
  if (!entry.tiles) {
    entry.tiles = el('span', {className: 'tiles'}, ...Array.from({length: TILES}, () => el('span')));
    entry.cover.insertBefore(entry.tiles, entry.badge);
  }
  [...entry.tiles.children].forEach((tile, index) => {
    tile.classList.toggle('lit', percent >= (TILE_TURN[index] + 1) / TILES * 100);
  });
}

// a game's launch options, in a small dialog of their own
let launchGame = null;

async function openLaunchOptions(game) {
  launchGame = game;
  $('#launch-title').textContent = game.title;
  $('#launch-options').value = await api.launch_options(game.app_name);
  $('#launch-error').hidden = true;
  $('#launch').showModal();
  $('#launch-options').focus();
}

async function saveLaunchOptions() {
  try {
    await api.set_launch_options(launchGame.app_name, $('#launch-options').value);
    $('#launch').close();
  } catch (failure) {
    $('#launch-error').textContent = `Those options don't parse: ${failure.message || failure}`;
    $('#launch-error').hidden = false;
  }
}

// the games Epic gives away: free now, then next, with a way to claim them on Epic's store
let freeKey = '';

function renderFree() {
  const games = state.free_games || [];
  $('#free').hidden = !games.length || filter !== 'all' || Boolean($('#search').value.trim());
  const key = JSON.stringify(games);
  if (key === freeKey) return;
  freeKey = key;
  const day = (iso) => new Date(iso).toLocaleDateString(undefined, {weekday: 'short', day: 'numeric', month: 'short'});
  $('#free-list').replaceChildren(...games.map((game) => el('article', {className: `free-game${game.now ? '' : ' next'}`},
    el('div', {className: 'free-cover'}, game.image ? el('img', {src: game.image, alt: '', loading: 'lazy'}) : null,
      el('span', {className: 'badge', textContent: game.now ? 'Free now' : 'Next'})),
    el('div', {className: 'free-text'},
      el('h3', {className: 'title', textContent: game.title}),
      el('p', {className: 'status', textContent: game.now ? `Until ${day(game.end)}` : `From ${day(game.start)}`})),
    game.owned ? el('span', {className: 'owned', textContent: 'In your library'})
      : button(game.now ? 'Claim on Epic' : 'See on Epic', game.now ? 'primary' : 'ghost',
        () => api.open_store(game.url)))));
}

// the install dialog: opens at once with where the game goes, and fills in its sizes when Epic has said
let installing = null;

function showInstall() {
  const {game, folder, free, info, failed} = installing;
  const size = (bytes) => (bytes === null || bytes === undefined ? '' : formatSize(bytes));
  const waiting = !info && !failed;
  $('#install-title').textContent = `Install ${game.title}`;
  $('#install-download').textContent = info ? size(info.download_size) : waiting ? 'Working it out…' : 'Unknown';
  $('#install-disk').textContent = info ? size(info.disk_size) : waiting ? 'Working it out…' : 'Unknown';
  $('#install-free').textContent = free === null ? 'Unknown' : size(free);
  $('#install-folder').textContent = folder;
  $('#install-folder').title = folder;
  const dlcs = info ? info.dlcs : [];
  $('#install-dlc-row').hidden = !dlcs.length;
  $('#install-dlc-list').textContent = dlcs.join(', ');
  const short = info && info.disk_size && free !== null && free < info.disk_size;
  const warning = $('#install-warning');
  warning.hidden = !short && !failed;
  warning.textContent = short ? `Not enough space: it needs ${size(info.disk_size - free)} more there. Choose another folder.`
    : failed ? 'Could not find out its size from Epic. It can still be installed.' : '';
  $('#install-start').disabled = Boolean(short);
}

async function openInstall(game) {
  const settings = await api.settings();
  installing = {game, folder: settings.install_dir, free: await api.free_space(settings.install_dir), info: null, failed: false};
  const opened = installing;
  showInstall();
  $('#install').showModal();
  try {
    const info = await api.install_info(game.app_name);
    if (installing === opened) Object.assign(installing, {info, free: installing.free ?? info.free});
  } catch (error) {
    if (installing === opened) installing.failed = true;
  }
  if (installing === opened) showInstall();
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
    src: game.cover, alt: '', loading: 'lazy', decoding: 'async',
    // offline, or the image is gone: show the initials instead
    onerror: (event) => event.target.replaceWith(el('span', {className: 'initials', textContent: initials(game.title)})),
  });
}

function card(game) {
  let entry = cards.get(game.app_name);
  if (!entry) {
    entry = {
      cover: el('div', {className: 'cover'}),
      badge: el('span', {className: 'badge', hidden: true}),
      title: el('h3', {className: 'title'}),
      status: el('p', {className: 'status'}),
      trophies: el('p', {className: 'status trophies', hidden: true}),
      buttons: el('div', {className: 'actions'}),
      key: '',
      shown: false,
    };
    entry.info = el('div', {className: 'info'}, entry.title, entry.status, entry.trophies);
    entry.node = el('article', {className: 'card'}, entry.cover);
    entry.node.dataset.app = game.app_name;
    cards.set(game.app_name, entry);
  }
  const job = activeJob(game.app_name);
  // a game changes only with the revision of the games, so the card is not compared field by field
  const key = `${state.revision}|${JSON.stringify(job)}`;
  if (key === entry.key) return entry;
  entry.key = key;

  if (entry.coverUrl !== game.cover) {
    entry.coverUrl = game.cover;
    entry.cover.replaceChildren(coverArt(game), entry.badge, entry.info, entry.buttons);
    entry.tiles = null;
  }
  const [lit, percent] = lighting(game, job);
  entry.node.dataset.state = lit;
  entry.cover.style.setProperty('--fill', String(percent));
  assemble(entry, lit === 'filling' ? percent : null);
  // a download that filled the cover lights it up, once it is installed
  if (lit === 'filling') entry.filling = true;
  if (lit === 'installed' && entry.filling) {
    entry.filling = false;
    entry.cover.classList.remove('kindled');
    void entry.cover.offsetWidth;
    entry.cover.classList.add('kindled');
  }
  const playing = lit === 'playing';
  entry.badge.hidden = !playing && (!game.update || job !== null);
  entry.badge.textContent = playing ? 'Playing' : 'Update';
  entry.badge.classList.toggle('playing', playing);
  entry.title.textContent = game.title;
  entry.node.title = game.version ? `${game.title} (version ${game.version})` : game.title;
  entry.status.textContent = statusText(game, job);
  entry.status.classList.toggle('lit', Boolean(game.update && !job) || playing);
  // your achievements, once Heirloom has asked Epic for them
  const trophies = game.achievements && game.achievements.unlocked !== null ? game.achievements : null;
  entry.trophies.hidden = !trophies;
  entry.trophies.textContent = trophies ? `${trophies.unlocked}/${trophies.total} achievements` : '';
  entry.buttons.replaceChildren(...actions(game, job));
  return entry;
}

function skeleton() {
  return el('div', {className: 'card skeleton', ariaHidden: 'true'},
    el('div', {className: 'cover'}), el('div', {className: 'line'}), el('div', {className: 'line'}));
}

// searching ignores case, spaces and punctuation: "hitman3" finds "HITMAN 3"
const searchable = (text) => text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

function shown(game, query) {
  return (filter === 'all' || (filter === 'installed' && game.installed) || (filter === 'updates' && game.update))
    && (!query || searchable(game.title).includes(query) || searchable(game.app_name).includes(query));
}

function sorted(games) {
  return sort === 'title' ? games : [...games].sort(SORTS[sort][1]);
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
  const query = searchable($('#search').value);
  const library = $('#library');
  const loading = state.refreshing && !state.games.length && Boolean(state.user);
  const games = sorted(state.games);
  const entries = games.map(card);
  const order = loading ? 'loading' : games.map((game) => game.app_name).join('\n');
  if (order !== libraryOrder) {
    libraryOrder = order;
    library.replaceChildren(...(loading ? Array.from({length: 12}, skeleton) : entries.map((entry) => entry.node)));
  }
  let count = 0;
  games.forEach((game, index) => {
    const entry = entries[index];
    const show = shown(game, query);
    // a card coming into view rises in, after the ones before it; only the first screenful, as animating
    // hundreds at once makes opening a large library stutter
    if (show && !entry.shown && count < 24) {
      entry.node.style.setProperty('--i', String(Math.min(count, 14)));
      entry.node.classList.add('rising');
      entry.node.addEventListener('animationend', () => entry.node.classList.remove('rising'), {once: true});
    }
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
  $('#ambient').hidden = !game;
  if (!game) return;
  const job = activeJob(game.app_name);
  const key = JSON.stringify([game, job]);
  if (key === heroKey) return;
  heroKey = key;
  const art = $('#hero-art');
  const src = game.art || game.cover;
  if (art.getAttribute('src') !== src) art.src = $('#ambient').src = src;
  art.hidden = $('#ambient').hidden = !src;
  $('#hero-title').textContent = game.title;
  $('#hero-meta').textContent = job ? progressText(job)
    : `${formatPlayed(game.played)} · last played ${formatDay(game.last_played)}`;
  $('#hero-actions').replaceChildren(...actions(game, job));
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
  $('#notice').hidden = !state.notice || state.notice === dismissedNotice;
  $('#notice-text').textContent = state.notice;
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
    onclick: () => run(api.stop(job.id))}, el('span', {className: 'percent', ariaHidden: 'true'}), icon('x'));
  stop.setAttribute('aria-label', label);
  return stop;
}

function jobRow(job, next) {
  let row = rows.get(job.id);
  if (!row) {
    const game = state.games.find((candidate) => candidate.app_name === job.app_name);
    const thumb = game && game.cover ? el('img', {src: game.cover, alt: ''}) : icon(job.kind === 'login' ? 'account' : 'games');
    row = {detail: el('span', {className: 'detail'}), end: el('span', {className: 'job-end'}), kind: '',
      next: iconButton('updates', `Download ${job.title} next`, '', () => run(api.download_next(job.id)))};
    row.node = el('li', {}, el('span', {className: 'thumb'}, thumb),
      el('span', {className: 'job-text'}, el('span', {className: 'what', textContent: job.title}), row.detail),
      el('span', {className: 'job-controls'}, row.next, row.end));
    rows.set(job.id, row);
  }
  const active = ACTIVE.has(job.status);
  row.node.className = `job ${job.status}`;
  // a waiting download can go ahead of the others waiting
  row.next.hidden = job.status !== 'queued' || !DOWNLOADS.has(job.kind) || job.id === next;
  row.detail.textContent = active ? progressText(job) : finishedText(job);
  const kind = !active ? job.status : DOWNLOADS.has(job.kind) ? 'ring' : 'live';
  if (kind !== row.kind) {
    row.kind = kind;
    row.end.replaceChildren(jobEnd(job, kind));
  }
  row.end.style.setProperty('--p', String(job.progress || 0));
  const percent = row.end.querySelector('.percent');
  if (percent) percent.textContent = job.progress === null ? '' : String(Math.floor(job.progress));
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
  // the waiting download that starts next
  const next = (state.jobs.find((job) => job.status === 'queued' && DOWNLOADS.has(job.kind)) || {}).id;
  const nodes = jobs.map((job) => jobRow(job, next));
  const order = jobs.map((job) => job.id).join();
  if (order !== jobOrder) {
    jobOrder = order;
    $('#jobs').replaceChildren(...nodes);
  }
}

function render() {
  renderRail();
  renderJobs();
  // the library is drawn again only when the games or what is being done to them changed
  const drawn = `${state.revision}|${state.refreshing}|${state.user}|${JSON.stringify(state.jobs)}`;
  if (drawn === libraryDrawn) return;
  libraryDrawn = drawn;
  renderShelves();
  renderHero();
  renderFree();
  renderLibrary();
}

async function poll() {
  if (document.hidden) return;
  try {
    // the games come only when they changed since the ones the page has
    const next = await api.state(state.revision);
    state = 'games' in next ? next : {...next, games: state.games, free_games: state.free_games};
  } catch (error) {
    console.error('Reading heirloom\'s state failed', error);
    return;
  }
  render();
  const overlay = state.jobs.filter((job) => job.kind.startsWith('overlay')).map((job) => job.status).join();
  if (overlay !== overlayJobs) {
    overlayJobs = overlay;
    if ($('#customize').open) showOverlay(await api.overlay());
  }
}

// Settings: shows the options, and saves each as it changes
function showSettings(settings) {
  $('#install-dir').textContent = settings.install_dir;
  $('#install-dir').title = settings.install_dir;
  for (const name of ['max_download_speed', 'max_download_speed_while_playing', 'max_workers', 'max_memory',
    'preferred_cdn']) {
    if (document.activeElement !== $(`#${name}`)) $(`#${name}`).value = settings[name];
  }
  // not while one end is being set, before the other
  if (![$('#window-start'), $('#window-end')].includes(document.activeElement)) {
    const [start = '', end = ''] = settings.update_window ? settings.update_window.split('-') : [];
    $('#window-start').value = start;
    $('#window-end').value = end;
  }
  for (const name of ['auto_updates', 'cloud_saves', 'update_notice', 'starts_with_windows']) {
    $(`#${name}`).checked = settings[name];
  }
  $('#startup-row').hidden = !settings.tray;
  $('#starts_with_windows').disabled = !settings.startup_possible;
  $('#startup-detail').textContent = settings.startup_possible
    ? 'In the tray, so games update before you play. Closing the window keeps Heirloom there; Quit is in its menu.'
    : 'Install Heirloom with its installer to start it with Windows. Closing the window keeps it in the tray.';
}

async function saveSetting(name, value) {
  const error = $('#settings-error');
  try {
    showSettings(await api.set_setting(name, value));
    error.hidden = true;
  } catch (failure) {
    // pywebview hands a Python error over with its message
    error.textContent = failure.message || String(failure);
    error.hidden = false;
    showSettings(await api.settings());
  }
}

// the Epic overlay's row in Customize: what it is, how it stands, and what can be done with it
function showOverlay(info) {
  $('#overlay-section').hidden = !info;
  if (!info) return;
  const busy = state.jobs.some((job) => job.kind.startsWith('overlay') && ACTIVE.has(job.status));
  let detail = 'Not installed';
  if (busy) detail = 'Working on it, see the downloads panel';
  else if (info.installed) detail = `Version ${info.version}, ${info.enabled ? 'on' : 'off'} for every game`;
  else if (info.enabled) detail = 'On, from the Epic Games Launcher';
  const install = () => run(api.install_overlay()).then(() => showOverlay(info));
  $('#overlay-row').replaceChildren(...[
    el('span', {className: 'row-text'},
      el('span', {className: 'what', textContent: 'Friends, invites and achievements in games'}),
      el('span', {className: 'detail', textContent: detail})),
    !busy && (info.installed || info.enabled) ? el('input', {
      type: 'checkbox', role: 'switch', className: 'switch', checked: info.enabled, ariaLabel: 'Epic overlay on',
      onchange: async (event) => showOverlay(await api.set_overlay(event.target.checked)),
    }) : null,
    !busy && !info.installed ? button('Install', 'ghost', install, 'download') : null,
    !busy && info.installed ? iconButton('updates', 'Update the Epic overlay', '', install) : null,
    !busy && info.installed ? iconButton('trash', 'Remove the Epic overlay', 'danger', () => {
      if (confirm('Remove the Epic overlay? Games stop showing it.')) run(api.remove_overlay());
    }) : null,
  ].filter(Boolean));
}

async function showThemes(info) {
  const themes = info || await api.themes();
  document.documentElement.dataset.theme = themes.active;
  $('#theme-css').textContent = themes.css;
  // a choice only once there is a theme besides the window's own look
  const choice = themes.themes.length > 1;
  $('#theme-list').hidden = !choice;
  $('#themes-hint').hidden = choice;
  $('#theme-list').replaceChildren(...themes.themes.map((theme) => el('label', {className: 'choice'},
    el('input', {
      type: 'radio', name: 'theme', value: theme.name, checked: theme.name === themes.active,
      onchange: async () => showThemes(await api.use_theme(theme.name)),
    }),
    el('span', {textContent: theme.title}))));
}

// a plugin's name and what it does, then what can be done with it
function pluginRow(plugin, ...controls) {
  return el('li', {className: 'row'},
    el('span', {className: 'row-text'}, el('span', {className: 'what', textContent: plugin.title}),
      el('span', {className: 'detail', textContent: plugin.description})),
    ...controls);
}

function showPlugins(plugins) {
  const update = async (call) => showPlugins(await call);
  $('#plugins-hint').hidden = plugins.installed.length > 0;
  $('#plugin-list').replaceChildren(...plugins.installed.map((plugin) => pluginRow(plugin,
    el('input', {
      type: 'checkbox', role: 'switch', className: 'switch', checked: plugin.enabled,
      ariaLabel: `${plugin.title} on`,
      onchange: (event) => {
        // plugins run inside Heirloom with your Epic account and files; the store's come with Heirloom
        const fromStore = plugins.store.some((entry) => entry.name === plugin.name);
        if (event.target.checked && !fromStore
          && !confirm(`Turn on ${plugin.title}? Plugins run inside Heirloom with access to your Epic account `
            + 'and files, so only turn on ones you trust.')) {
          event.target.checked = false;
          return;
        }
        update(api.set_plugin(plugin.name, event.target.checked));
      },
    }),
    iconButton('trash', `Remove ${plugin.title}`, 'danger', () => {
      if (confirm(`Remove ${plugin.title}? Its folder is deleted.`)) update(api.remove_plugin(plugin.name));
    }))));
  $('#store-list').replaceChildren(...plugins.store.map((plugin) => pluginRow(plugin, plugin.installed
    ? el('span', {className: 'installed', textContent: 'Installed'})
    : button('Install', 'ghost', () => update(api.install_plugin(plugin.name)), 'download'))));
}

// names the cards on screen for a view transition, by their place in the library, so each glides from where it
// was to where it is; the rest of a large library is left out, and stays cheap
function nameCards() {
  [...$('#library').children].forEach((node, index) => {
    const box = node.getBoundingClientRect();
    node.style.viewTransitionName = !node.hidden && box.bottom > 0 && box.top < innerHeight ? `card-${index}` : '';
  });
}

// a change of what the library shows, with the cards gliding to their new places
function smoothly(update) {
  if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    update();
    return;
  }
  nameCards();
  const transition = document.startViewTransition(() => {
    update();
    nameCards();
  });
  // skipped in a minimized window, say: the update still happens, just without the glide
  transition.ready.catch(() => {});
  transition.finished.finally(() => {
    for (const node of $('#library').children) node.style.viewTransitionName = '';
  });
}

// keeps the shelf, the sort order and the sidebar for the next time the window opens
function saveView() {
  api.set_view({filter, sort, rail_collapsed: $('#rail').classList.contains('collapsed')});
}

function setSort(name) {
  sort = name;
  $('#sort-name').textContent = SORTS[name][0];
  smoothly(renderLibrary);
}

function setRailCollapsed(collapsed) {
  $('#rail').classList.toggle('collapsed', collapsed);
  const toggle = $('#rail-toggle');
  toggle.setAttribute('aria-expanded', String(!collapsed));
  toggle.title = collapsed ? 'Expand the sidebar' : 'Collapse the sidebar';
  toggle.querySelector('.label').textContent = collapsed ? 'Expand' : 'Collapse';
}

function setFilter(name) {
  filter = name;
  for (const item of document.querySelectorAll('[data-filter]')) {
    item.setAttribute('aria-pressed', String(item.dataset.filter === name));
  }
  moveMarker();
  smoothly(() => {
    renderShelves();
    renderHero();
    renderFree();
    renderLibrary();
  });
}

async function start() {
  api = window.pywebview.api;
  const login = () => run(api.login());
  $('#account').onclick = login;
  $('#empty-login').onclick = login;
  $('#refresh').onclick = () => run(api.refresh());
  $('#search').oninput = () => smoothly(() => {
    renderHero();
    renderFree();
    renderLibrary();
  });
  for (const item of document.querySelectorAll('[data-filter]')) {
    item.onclick = () => {
      setFilter(item.dataset.filter);
      saveView();
    };
  }
  $('#rail-toggle').onclick = () => {
    setRailCollapsed(!$('#rail').classList.contains('collapsed'));
    saveView();
  };
  $('#sort').onclick = (event) => showMenu($('#sort-menu'), event.currentTarget, [
    el('p', {className: 'menu-title', textContent: 'Sort by'}),
    ...Object.entries(SORTS).map(([name, [label]]) => {
      const item = menuItem(label, name === sort ? 'done' : 'sort', () => {
        setSort(name);
        saveView();
      });
      item.setAttribute('role', 'menuitemradio');
      item.setAttribute('aria-checked', String(name === sort));
      return item;
    }),
  ]);
  $('#notice-close').onclick = () => {
    dismissedNotice = state.notice;
    renderRail();
  };
  // Escape empties the search, then leaves it
  $('#search').onkeydown = (event) => {
    if (event.key !== 'Escape') return;
    if (!event.target.value) {
      event.target.blur();
      return;
    }
    event.target.value = '';
    event.target.dispatchEvent(new Event('input'));
  };
  const gameOf = (event) => {
    const node = event.target.closest('.card[data-app]');
    return node && {node, game: state.games.find((game) => game.app_name === node.dataset.app)};
  };
  // a double click on an installed game plays it
  $('#library').ondblclick = (event) => {
    const found = gameOf(event);
    if (!found || !found.game || !found.game.installed || event.target.closest('button')
      || activeJob(found.game.app_name)) return;
    run(api.play(found.game.app_name));
  };
  // a right click on a game opens its Manage menu where it was clicked
  $('#library').oncontextmenu = (event) => {
    const found = gameOf(event);
    if (!found) return;
    event.preventDefault();
    // games of other stores have nothing to manage here
    if (found.game && !found.game.store) openManage(found.game, found.node, {x: event.clientX, y: event.clientY});
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
  const library = $('#library');
  library.onpointermove = (event) => {
    const cover = event.target.closest('.cover');
    if (!cover || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const box = cover.getBoundingClientRect();
    cover.style.setProperty('--rx', `${((event.clientX - box.left) / box.width - .5) * 10}deg`);
    cover.style.setProperty('--ry', `${(.5 - (event.clientY - box.top) / box.height) * 10}deg`);
  };
  library.onpointerout = (event) => {
    const cover = event.target.closest('.cover');
    if (cover && !cover.contains(event.relatedTarget)) {
      cover.style.removeProperty('--rx');
      cover.style.removeProperty('--ry');
    }
  };
  $('#customize-open').onclick = async () => {
    // themes and plugins added in their folders meanwhile show up too
    await showThemes();
    showOverlay(await api.overlay());
    showPlugins(await api.plugins());
    $('#customize').showModal();
  };
  $('#customize-close').onclick = () => $('#customize').close();
  $('#settings-open').onclick = async () => {
    $('#settings-error').hidden = true;
    showSettings(await api.settings());
    $('#settings').showModal();
  };
  $('#settings-close').onclick = () => $('#settings').close();
  $('#launch-close').onclick = () => $('#launch').close();
  $('#launch-cancel').onclick = () => $('#launch').close();
  $('#launch-save').onclick = saveLaunchOptions;
  $('#launch-options').onkeydown = (event) => {
    if (event.key === 'Enter') saveLaunchOptions();
  };
  const closeInstall = () => {
    installing = null;
    $('#install').close();
  };
  $('#install-close').onclick = closeInstall;
  $('#install-cancel').onclick = closeInstall;
  $('#install').onclose = () => {
    installing = null;
  };
  $('#install-folder-change').onclick = async () => {
    const chosen = await api.choose_folder(installing.folder);
    if (chosen && installing) {
      Object.assign(installing, chosen);
      showInstall();
    }
  };
  $('#install-start').onclick = async () => {
    const {game, folder, info} = installing;
    const settings = await api.settings();
    const dlcs = info && info.dlcs.length ? $('#install-dlcs').checked : null;
    closeInstall();
    run(api.install(game.app_name, folder === settings.install_dir ? null : folder, dlcs));
  };
  $('#install-locate').onclick = () => {
    const {game, folder} = installing;
    closeInstall();
    locateGame(game, folder);
  };
  $('#detail-close').onclick = () => $('#detail').close();
  $('#install-dir-change').onclick = async () => showSettings(await api.choose_install_dir());
  for (const name of ['max_download_speed', 'max_download_speed_while_playing', 'max_workers', 'max_memory',
    'preferred_cdn']) {
    $(`#${name}`).onchange = (event) => saveSetting(name, event.target.value);
  }
  // saved once both ends are set, or both emptied
  for (const end of ['#window-start', '#window-end']) {
    $(end).onchange = () => {
      const [start, until] = [$('#window-start').value, $('#window-end').value];
      if (Boolean(start) === Boolean(until)) saveSetting('update_window', start ? `${start}-${until}` : '');
    };
  }
  for (const name of ['auto_updates', 'cloud_saves', 'update_notice', 'starts_with_windows']) {
    $(`#${name}`).onchange = (event) => saveSetting(name, event.target.checked);
  }
  for (const folder of document.querySelectorAll('[data-folder]')) {
    folder.onclick = () => api.open_config_folder(folder.dataset.folder);
  }
  for (const menu of document.querySelectorAll('.menu')) {
    menu.onkeydown = (event) => {
      const items = [...menu.querySelectorAll('[role^="menuitem"]')];
      const step = {ArrowDown: 1, ArrowUp: -1}[event.key];
      if (!step) return;
      event.preventDefault();
      items[(items.indexOf(document.activeElement) + step + items.length) % items.length].focus();
    };
  }
  document.addEventListener('keydown', (event) => {
    const typing = event.target.closest('input, select, textarea');
    if (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      $('#search').focus();
    }
  });
  // the window opens as it was left
  const view = await api.view();
  setRailCollapsed(view.rail_collapsed);
  setSort(view.sort);
  setFilter(view.filter);
  await showThemes();
  await poll();
  api.refresh();
  setInterval(poll, 1000);
  // a window brought back from the tray is up to date at once, rather than at the next poll
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
}

if (window.pywebview && window.pywebview.api) start();
else window.addEventListener('pywebviewready', start, {once: true});
