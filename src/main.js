import './style.css';
import { ENCOUNTERS, createRun, act, getCard } from './game.js';

const app = document.querySelector('#app');
const seed = 123;
let state = createRun(seed);
let deckOpen = false;
let selectedTab = 'deck';
let helpOpen = false;

const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
const icon = (name, size = 20) => {
  const paths = {
    cards: '<rect x="5" y="3" width="12" height="16" rx="2"/><path d="m5 7-3 1 3 13 10-2"/><path d="m11 7 3 4-3 4-3-4z"/>',
    map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15m6-12v15"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    restart: '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7"/>',
    heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7z"/>',
    sword: '<path d="m4 20 4-4m-3-3 6 6m-3-3L20 4V2h-2L6 14"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    book: '<path d="M12 5c-4-3-9-2-9-2v16s5-1 9 2c4-3 9-2 9-2V3s-5-1-9 2zm0 0v16"/>',
    star: '<path d="m12 2 2.4 6.8L22 9l-5.9 4.5L18 21l-6-4.3L6 21l1.9-7.5L2 9l7.6-.2Z"/>',
    volume: '<path d="m4 9 5-1 5-5v18l-5-5-5-1zM18 8a6 6 0 0 1 0 8"/>',
    help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3h.01"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.star}</svg>`;
};

function fogMark(className = '') {
  return `<svg class="${className}" viewBox="0 0 64 64" fill="none" aria-hidden="true"><path d="M32 4 57 18v28L32 60 7 46V18Z" stroke="currentColor"/><path d="M32 12 50 22v20L32 52 14 42V22Z" stroke="currentColor" opacity=".4"/><path d="m22 27 10-9 10 9-10 19Z" fill="currentColor" opacity=".14"/><path d="m17 32 15-14 15 14-15 14Z" stroke="currentColor"/><circle cx="32" cy="32" r="5" stroke="currentColor"/><path d="M32 4v10m0 36v10M7 18l9 5m32 18 9 5M7 46l9-5m32-18 9-5" stroke="currentColor"/></svg>`;
}

function characterArt(kind) {
  if (kind === 'hero') {
    return `<svg class="character-art hero-art" viewBox="0 0 300 330" role="img" aria-label="Original illustration of a masked traveler with a lantern"><defs><linearGradient id="hero-cloak" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#3a4853"/><stop offset="1" stop-color="#10191e"/></linearGradient><radialGradient id="lantern-glow"><stop stop-color="#f8d88a" stop-opacity=".7"/><stop offset="1" stop-color="#d6aa54" stop-opacity="0"/></radialGradient></defs><circle cx="153" cy="153" r="107" fill="none" stroke="#bfa578" opacity=".16"/><circle cx="153" cy="153" r="94" fill="none" stroke="#bfa578" opacity=".08" stroke-dasharray="3 9"/><path d="m153 41 78 129-28 9 45 118H65l36-118-31-9Z" fill="url(#hero-cloak)" stroke="#697779" stroke-opacity=".45"/><path d="m153 55-41 76 18 52 25-9 28-57Z" fill="#101a21"/><path d="m130 120 42-2-4 47-22 13-18-14Z" fill="#879294"/><path d="m130 124 40-1-20 39Z" fill="#a7aeaa" opacity=".3"/><path d="m132 134 12 3m12-1 12-4" stroke="#f0d392" stroke-width="2"/><path d="m143 155 9 2 8-5" stroke="#293741"/><path d="m116 173 36 11 33-12 20 25-27 52-47-7-37-52Z" fill="#23313b" stroke="#647273" stroke-opacity=".4"/><path d="m152 184-4 96m-25-88-35 95m91-95 24 95" stroke="#78837e" stroke-opacity=".25"/><path d="m124 175 24 21 26-23" fill="none" stroke="#b1a07b"/><circle cx="148" cy="197" r="4" fill="#c8aa71"/><path d="m103 180-28 58 15 11 24-34m75-34 20 42-9 8-23-25" fill="#273640" stroke="#667174" stroke-opacity=".4"/><path d="m204 226 4 27" stroke="#c9b887" stroke-width="2"/><circle cx="210" cy="272" r="55" fill="url(#lantern-glow)"/><path d="m199 253 20-1 4 33-27 1Z" fill="#b3a476" stroke="#e6cc8c"/><path d="m204 257 10-1 3 24-16 1Z" fill="#f1cf82"/><path d="m208 251 3-9 4 9M195 287l30-1" stroke="#bdb082" stroke-width="2"/><path d="m83 301 23-12 46 7 36-7 32 13Z" fill="#0a141b"/></svg>`;
  }
  return `<svg class="character-art enemy-art" viewBox="0 0 300 330" role="img" aria-label="Original illustration of a spectral figure suspended in a ritual circle"><defs><linearGradient id="enemy-cloak" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#80696d"/><stop offset=".6" stop-color="#403943"/><stop offset="1" stop-color="#1b2630" stop-opacity="0"/></linearGradient><radialGradient id="enemy-aura"><stop stop-color="#aa7677" stop-opacity=".22"/><stop offset="1" stop-color="#a36365" stop-opacity="0"/></radialGradient></defs><circle cx="153" cy="157" r="131" fill="url(#enemy-aura)"/><circle cx="153" cy="148" r="96" fill="none" stroke="#a5867e" opacity=".25"/><circle cx="153" cy="148" r="103" fill="none" stroke="#a5867e" opacity=".1"/><path d="m153 42 83 144H70Z" fill="none" stroke="#a5867e" opacity=".22"/><path d="m153 253-83-144h166Z" fill="none" stroke="#a5867e" opacity=".15"/><path d="M90 270c26-50-11-43 6-88l17-52 18-45 40-4 23 47 18 39c17 56-4 51 14 89l-35-20-4 34-25-10-8 31-22-39-28 22 5-32Z" fill="url(#enemy-cloak)"/><path d="m119 121 16-29 34 1 18 32-28 22-25-2Z" fill="#18212a"/><path d="m133 112 33-5 5 25-20 15-19-16Z" fill="#a19a91"/><path d="m136 118 11 3m9 0 11-7" stroke="#f0ba9d" stroke-width="3"/><path d="m143 131 10 3 6-4" stroke="#4c4449"/><path d="m115 153 30 14 35-13-10 30-26 7Z" fill="#6c555e"/><path d="m122 174 26 18 26-13-5 56-18 28-28-42Z" fill="#302c36"/><path d="m105 159-19 56-32-19-5 11 46 38 31-51m61-34 27 43 38-18 6 13-51 37-38-50" fill="#5b4752"/><path d="m54 193-14-4-8 16 13 9 7-13m200-20 17-6 9 16-15 11-9-11" fill="#a09a90"/><path d="m38 188-5-12m235-3 5-13" stroke="#a09a90" stroke-width="4"/><path d="M120 90c0-38 62-45 65-7m-59-3c7-19 42-23 51-5" fill="none" stroke="#c1a17e" stroke-width="2" opacity=".6"/><path d="m151 37 1-16m-40 29-11-14m88 16 10-14" stroke="#c1a17e" opacity=".6"/><path d="M71 286c57-25 124-18 158 0" fill="none" stroke="#a47b73" opacity=".2"/><ellipse cx="152" cy="290" rx="83" ry="12" fill="#9e7871" opacity=".08"/></svg>`;
}

function cardArt(type, id) {
  const isAttack = type === 'attack';
  const variation = [...String(id)].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 3;
  const motif = isAttack
    ? '<path d="m37 64 40-41 10-2-2 11-40 40Z" fill="#b7a283" stroke="#e1cba4"/><path d="m43 60 7 8M39 58l13 13m-17 1 8-8" stroke="#33292b" stroke-width="4"/><path d="m54 48 17-17" stroke="#f1dcb7"/>'
    : type === 'power'
      ? '<path d="m60 20 26 20-10 31H44L34 40Z" fill="none" stroke="#c5b287"/><path d="m60 25 10 24-10 21-10-21Z" fill="#d5c294" opacity=".7"/><circle cx="60" cy="48" r="21" fill="none" stroke="#c9b584" opacity=".4"/>'
      : variation === 0
        ? '<path d="m60 22 23 9v19c0 16-23 27-23 27S37 66 37 50V31Z" fill="#596b70" stroke="#b6c3b9"/><path d="m60 29 15 6v15c0 10-15 20-15 20s-15-10-15-20V35Z" fill="none" stroke="#c3c7b2" opacity=".6"/><path d="m50 47 7 8 14-17" fill="none" stroke="#e1d6b5" stroke-width="2"/>'
        : '<path d="M24 49s14-22 36-22 36 22 36 22-14 22-36 22-36-22-36-22Z" fill="none" stroke="#b7bdb5"/><circle cx="60" cy="49" r="13" fill="#80988f" stroke="#d3d6bb"/><circle cx="60" cy="49" r="5" fill="#223a3e"/><path d="M60 17v-7m0 71v7m-34-64-6-5m74 45 6 5m-75-5-6 5m75-45 6-5" stroke="#c8bda1" opacity=".6"/>';
  return `<svg viewBox="0 0 120 96" class="card-art" aria-hidden="true"><circle cx="60" cy="49" r="36" fill="currentColor" opacity=".06"/><circle cx="60" cy="49" r="39" fill="none" stroke="currentColor" opacity=".16" stroke-dasharray="1 5"/>${motif}</svg>`;
}

function cardHTML(id, index, reward = false) {
  const card = getCard(id);
  const disabled = !reward && (state.phase !== 'combat' || Number(card.cost) > state.player.energy);
  return `<button class="playing-card card-${escapeHTML(card.type)} ${disabled ? 'unplayable' : ''}" data-testid="${reward ? 'reward-card' : 'card'}" ${reward ? `data-reward="${escapeHTML(id)}"` : `data-index="${index}"`} ${disabled ? 'disabled' : ''} aria-label="${escapeHTML(card.name)}, cost ${card.cost}. ${escapeHTML(card.description)}">
    <span class="card-cost">${escapeHTML(card.cost)}</span>
    <span class="card-type">${escapeHTML(card.type)}</span>
    ${cardArt(card.type, id)}
    <span class="card-name">${escapeHTML(card.name)}</span>
    <span class="card-description">${escapeHTML(card.description)}</span>
    <span class="card-footer"><span>✦</span> ${escapeHTML(card.rarity || 'common')} <span>✦</span></span>
    ${!reward ? `<span class="card-key">${index + 1}</span>` : ''}
  </button>`;
}

function meter(label, current, max, type, iconName) {
  return `<div class="resource resource-${type}"><span class="resource-icon">${icon(iconName, 18)}</span><div class="resource-content"><div class="resource-label"><span>${label}</span><strong><span data-testid="${type === 'health' ? 'player-hp' : type === 'enemy-health' ? 'enemy-hp' : 'sanity'}">${current}</span> <span>/ ${max}</span></strong></div><div class="meter"><span style="width:${Math.max(0, Math.min(100, current / max * 100))}%"></span></div></div></div>`;
}

function sidebar() {
  const steps = ['The Veiled Gate', 'Whispers Below', 'Beyond the Fog'];
  return `<aside class="sidebar"><a class="brand" href="#" aria-label="Beyond the Gray Fog home">${fogMark('brand-mark')}<span>BEYOND THE<br/><strong>GRAY FOG</strong><small>A ROGUELIKE DECK BUILDER</small></span></a>
    <div class="sidebar-divider"></div><div class="sidebar-caption">YOUR EXPEDITION</div>
    <div class="expedition-name">The first awakening<span>Chapter I · The unknown awaits</span></div>
    <nav class="run-path" aria-label="Expedition progress">${steps.map((name, index) => `<div class="path-node ${index < state.encounter ? 'complete' : index === state.encounter ? 'current' : 'locked'}"><div class="node-symbol">${index < state.encounter ? '✓' : index === state.encounter ? icon('sword', 17) : icon(index === 2 ? 'eye' : 'star', 15)}</div><div><span class="node-label">${index === state.encounter ? 'CURRENT ENCOUNTER' : index < state.encounter ? 'COMPLETED' : `ENCOUNTER ${index + 1}`}</span><strong>${name}</strong></div></div>`).join('')}</nav>
    <div class="sidebar-divider lower-divider"></div><button class="sidebar-button" data-testid="deck-toggle">${icon('cards')}<span>Your collection</span><span class="count-chip">${state.deck.length}</span></button><button class="sidebar-button" data-action="help">${icon('book')}<span>How to play</span><span class="shortcut">?</span></button>
    <div class="sidebar-bottom"><div class="run-seed"><span class="live-dot"></span> LOCAL EXPEDITION <span>#${String(seed).padStart(4, '0')}</span></div><p>Every choice echoes<br/>beyond the gray fog.</p><span class="prototype-badge">ORIGINAL PLAYABLE PROTOTYPE</span></div>
  </aside>`;
}

function render() {
  const enemy = state.enemy;
  const player = state.player;
  const isCombat = state.phase === 'combat';
  app.innerHTML = `<div class="game-shell" data-testid="game">${sidebar()}<main class="main-content"><header class="topbar"><div class="breadcrumb"><span>Expedition</span>${icon('chevron', 13)}<strong>Chapter I</strong></div><div class="topbar-actions"><span class="reference-note">A journey of cards, memory &amp; consequence</span><button class="icon-button" data-action="help" aria-label="How to play">${icon('help', 18)}</button><button class="icon-button" data-testid="restart" aria-label="Restart expedition" title="Restart expedition">${icon('restart', 18)}</button></div></header>
    <section class="encounter-header"><div><div class="eyebrow"><span class="gold-line"></span> ENCOUNTER ${state.encounter + 1} / ${ENCOUNTERS.length}</div><h1>${escapeHTML(enemy?.name || 'Beyond the fog')}</h1><p>A presence stirs in the silence. Choose your next move.</p></div><div class="turn-pill"><span class="turn-dot"></span> TURN <strong data-testid="turn">${state.turn}</strong></div></section>
    <section class="battlefield" aria-label="Battle arena"><div class="arena-grid"></div><div class="arena-mist"></div><div class="arena-caption">THE SPIRIT WORLD</div>
      <div class="combatant player-combatant"><div class="combatant-label"><span class="label-line"></span> THE AWAKENED <span class="label-line"></span></div>${characterArt('hero')}<div class="character-ground"></div><div class="combatant-info"><h2>The Wanderer</h2><p>Seeker of the unknown</p><div class="player-resources">${meter('Vitality', player.hp, player.maxHp, 'health', 'heart')}${meter('Sanity', player.sanity, player.maxSanity, 'sanity', 'eye')}</div><div class="block-badge ${player.block ? 'has-block' : ''}">${icon('shield', 15)}<span>${player.block} block</span></div></div></div>
      <div class="battle-center"><div class="versus-sigil">${fogMark()}</div><span>THE VEIL IS THIN</span><div class="energy-display"><span class="energy-label">ENERGY</span><div class="energy-orb">${icon('bolt', 24)}<strong data-testid="energy">${player.energy}</strong></div><span class="energy-max">of ${player.maxEnergy} available</span></div></div>
      <div class="combatant enemy-combatant"><div class="combatant-label enemy-label"><span class="label-line"></span> ${state.encounter === ENCOUNTERS.length - 1 ? 'FINAL ENCOUNTER' : 'HOSTILE PRESENCE'} <span class="label-line"></span></div><div class="intent-badge intent-${enemy?.intent?.kind || 'attack'}">${icon(enemy?.intent?.kind === 'defend' ? 'shield' : 'sword', 15)}<strong>${escapeHTML(enemy?.intent?.value ?? 0)}</strong><span>${enemy?.intent?.kind === 'defend' ? 'Preparing defense' : 'Preparing to strike'}</span></div>${characterArt('enemy')}<div class="character-ground enemy-ground"></div><div class="combatant-info"><h2>${escapeHTML(enemy?.name || 'Unknown presence')}</h2><p>${state.encounter === ENCOUNTERS.length - 1 ? 'Guardian of the final threshold' : 'A shadow beyond the veil'}</p><div class="enemy-resources">${meter('Vitality', enemy?.hp || 0, enemy?.maxHp || 1, 'enemy-health', 'heart')}</div><div class="block-badge ${enemy?.block ? 'has-block' : ''}">${icon('shield', 15)}<span>${enemy?.block || 0} block</span></div></div></div>
    </section>
    <section class="hand-section" aria-label="Your hand"><div class="hand-toolbar"><div class="hand-heading">${icon('cards', 19)}<h2>Your hand</h2><span>${state.hand.length} cards</span></div><div class="hand-hint">Choose a card to play <span>·</span> Keys <kbd>1</kbd>–<kbd>${Math.max(1, state.hand.length)}</kbd></div><button class="end-turn" data-testid="end-turn" ${!isCombat ? 'disabled' : ''}>End turn ${icon('arrow', 16)}<kbd>E</kbd></button></div><div class="hand-area"><button class="pile draw-pile" data-action="draw-pile" aria-label="Inspect draw pile with ${state.drawPile.length} cards"><span class="pile-illustration">${fogMark()}</span><strong>${state.drawPile.length}</strong><span>Draw pile</span></button><div class="hand-cards">${state.hand.map((id, index) => cardHTML(id, index)).join('')}</div><button class="pile discard-pile" data-action="discard-pile" aria-label="Inspect discard pile with ${state.discardPile.length} cards"><span class="pile-illustration">${icon('cards', 33)}</span><strong>${state.discardPile.length}</strong><span>Discard pile</span></button></div></section>
    <footer class="battle-footer"><span class="battle-log-icon">${icon('book', 16)}</span><div class="latest-log" role="status" aria-live="polite">${escapeHTML(state.log.at(-1) || 'Your expedition begins. The fog remembers.')}</div><button class="log-toggle" data-action="log">Battle log ${icon('chevron', 12)}</button><span class="thai-tip">คลิกการ์ดเพื่อเล่น · E จบเทิร์น</span></footer>
    ${state.phase === 'reward' ? rewardOverlay() : state.phase === 'victory' || state.phase === 'defeat' ? outcomeOverlay() : ''}
    ${helpOpen ? helpOverlay() : ''}
    ${deckOpen ? deckOverlay() : ''}
    </main></div>`;
  bindEvents();
  const dialog = activeDialog();
  if (dialog) {
    app.querySelector('.sidebar').inert = true;
    app.querySelectorAll('.main-content > header, .main-content > section, .main-content > footer').forEach((element) => { element.inert = true; });
  }
}

function activeDialog() {
  return app.querySelector(deckOpen ? '.deck-panel' : helpOpen ? '.help-panel' : state.phase === 'reward' ? '.reward-panel' : state.phase === 'victory' || state.phase === 'defeat' ? '.outcome-panel' : '[data-no-dialog]');
}

function rewardOverlay() {
  return `<div class="overlay reward-overlay"><section class="reward-panel" role="dialog" aria-modal="true" aria-labelledby="reward-title"><div class="reward-symbol">${icon('star', 28)}</div><div class="eyebrow">THE FOG RETREATS</div><h2 id="reward-title">A new possibility</h2><p>Claim one card. Your journey continues beyond this threshold.</p><div class="reward-cards">${state.rewards.map((id, index) => cardHTML(id, index, true)).join('')}</div><span class="reward-footnote">Choose a card to add to your deck and enter the next encounter.</span></section></div>`;
}

function outcomeOverlay() {
  const victory = state.phase === 'victory';
  return `<div class="overlay outcome-overlay"><section class="outcome-panel" role="dialog" aria-modal="true" aria-labelledby="outcome-title">${fogMark('outcome-mark')}<div class="eyebrow">${victory ? 'EXPEDITION COMPLETE' : 'THE FOG REMEMBERS'}</div><h2 id="outcome-title">${victory ? 'Beyond the gray fog' : 'A whisper fades'}</h2><p>${victory ? 'You crossed every threshold. For a moment, the unknown feels familiar.' : 'The spirit world claims another story. Return wiser, and try a different path.'}</p><div class="outcome-stats"><div><strong>${state.encounter + 1} / ${ENCOUNTERS.length}</strong><span>ENCOUNTERS</span></div><div><strong>${state.deck.length}</strong><span>CARDS COLLECTED</span></div><div><strong>${state.turn}</strong><span>FINAL TURN</span></div></div><button class="primary-button" data-testid="restart">${icon('restart', 17)} Begin a new expedition</button></section></div>`;
}

function deckOverlay() {
  const piles = { deck: state.deck, draw: state.drawPile, discard: state.discardPile };
  const cards = selectedTab === 'log' ? [] : piles[selectedTab] || state.deck;
  const grouped = cards.reduce((collection, id) => { collection[id] = (collection[id] || 0) + 1; return collection; }, {});
  return `<div class="overlay deck-overlay" data-action="backdrop"><section class="deck-panel" data-testid="deck-dialog" role="dialog" aria-modal="true" aria-labelledby="deck-title"><header class="modal-header"><div><div class="eyebrow">EXPEDITION ARCHIVE</div><h2 id="deck-title">${selectedTab === 'log' ? 'Battle chronicle' : 'Your collection'}</h2></div><button class="icon-button" data-testid="close-deck" aria-label="Close collection">${icon('close')}</button></header><div class="deck-tabs"><button data-tab="deck" class="${selectedTab === 'deck' ? 'active' : ''}">Deck <span>${state.deck.length}</span></button><button data-tab="draw" class="${selectedTab === 'draw' ? 'active' : ''}">Draw pile <span>${state.drawPile.length}</span></button><button data-tab="discard" class="${selectedTab === 'discard' ? 'active' : ''}">Discard <span>${state.discardPile.length}</span></button><button data-tab="log" class="${selectedTab === 'log' ? 'active' : ''}">Battle log</button></div>${selectedTab === 'log' ? `<ol class="log-list">${state.log.map((line) => `<li>${escapeHTML(line)}</li>`).join('')}</ol>` : `<div class="collection-grid">${Object.entries(grouped).map(([id, count]) => { const card = getCard(id); return `<article class="collection-card"><span class="collection-cost">${card.cost}</span>${cardArt(card.type, id)}<div><h3>${escapeHTML(card.name)} <span>×${count}</span></h3><p>${escapeHTML(card.description)}</p><span class="collection-type">${escapeHTML(card.type)} · ${escapeHTML(card.rarity || 'common')}</span></div></article>`; }).join('') || '<p class="empty-pile">This pile is empty. The next turn may change that.</p>'}</div>`}<p class="modal-footnote">Drawn cards enter your hand. Played cards move to the discard pile.</p></section></div>`;
}

function helpOverlay() {
  return `<div class="overlay help-overlay"><section class="help-panel" role="dialog" aria-modal="true" aria-labelledby="help-title"><button class="icon-button help-close" data-action="close-help" aria-label="Close instructions">${icon('close')}</button>${fogMark('help-mark')}<div class="eyebrow">A FIELD GUIDE TO THE UNKNOWN</div><h2 id="help-title">Make every choice count.</h2><p>Defeat three presences in the spirit world. Spend energy to play cards, protect your vitality with block, and preserve your sanity.</p><div class="help-steps"><div>${icon('cards', 24)}<strong>Build your hand</strong><span>Click a card or press its number key. Its energy cost is shown in the corner.</span></div><div>${icon('eye', 24)}<strong>Read the intent</strong><span>Block absorbs damage for the turn. At zero sanity, lose 3 vitality each turn.</span></div><div>${icon('star', 24)}<strong>Find your path</strong><span>Choose a new card after victory. Recover 8 vitality and 3 sanity before continuing.</span></div></div><p class="thai-help">เล่นการ์ดด้วยเมาส์หรือปุ่มตัวเลข · กด E เพื่อจบเทิร์น · กด D เพื่อดูเด็ค · Esc เพื่อปิดหน้าต่าง</p><button class="primary-button" data-action="close-help">Enter the fog ${icon('arrow', 17)}</button></section></div>`;
}

function takeAction(action) {
  state = act(state, action);
  render();
  const dialog = activeDialog();
  if (dialog) dialog.querySelector('button:not(:disabled)')?.focus();
  else if (action.type === 'END_TURN') app.querySelector('[data-testid="end-turn"]')?.focus();
  else if (action.type === 'PLAY_CARD') {
    const nextCard = app.querySelector(`[data-testid="card"][data-index="${action.index}"]:not(:disabled)`) || app.querySelector('[data-testid="card"]:not(:disabled)');
    (nextCard || app.querySelector('[data-testid="end-turn"]'))?.focus({ preventScroll: true });
  }
}

function openDeck(tab = 'deck') {
  deckOpen = true;
  selectedTab = tab;
  render();
  app.querySelector('[data-testid="close-deck"]')?.focus();
}

function bindEvents() {
  app.querySelectorAll('[data-testid="card"]').forEach((button) => button.addEventListener('click', () => takeAction({ type: 'PLAY_CARD', index: Number(button.dataset.index) })));
  app.querySelectorAll('[data-testid="reward-card"]').forEach((button) => button.addEventListener('click', () => takeAction({ type: 'CHOOSE_REWARD', cardId: button.dataset.reward })));
  app.querySelector('[data-testid="end-turn"]')?.addEventListener('click', () => takeAction({ type: 'END_TURN' }));
  app.querySelectorAll('[data-testid="restart"]').forEach((button) => button.addEventListener('click', () => { state = createRun(seed); deckOpen = false; helpOpen = false; render(); }));
  app.querySelector('[data-testid="deck-toggle"]')?.addEventListener('click', () => openDeck());
  app.querySelector('[data-testid="close-deck"]')?.addEventListener('click', () => { deckOpen = false; render(); app.querySelector('[data-testid="deck-toggle"]')?.focus(); });
  app.querySelectorAll('[data-action="help"]').forEach((button) => button.addEventListener('click', () => { helpOpen = true; render(); app.querySelector('[data-action="close-help"]')?.focus(); }));
  app.querySelectorAll('[data-action="close-help"]').forEach((button) => button.addEventListener('click', () => { helpOpen = false; render(); }));
  app.querySelector('[data-action="draw-pile"]')?.addEventListener('click', () => openDeck('draw'));
  app.querySelector('[data-action="discard-pile"]')?.addEventListener('click', () => openDeck('discard'));
  app.querySelector('[data-action="log"]')?.addEventListener('click', () => openDeck('log'));
  app.querySelector('[data-action="backdrop"]')?.addEventListener('click', (event) => { if (event.target.classList.contains('deck-overlay')) { deckOpen = false; render(); } });
  app.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => { selectedTab = button.dataset.tab; render(); app.querySelector(`[data-tab="${selectedTab}"]`)?.focus(); }));
  app.querySelector('.brand')?.addEventListener('click', (event) => event.preventDefault());
}

document.addEventListener('keydown', (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
  if (event.key === 'Escape') { if (deckOpen || helpOpen) { deckOpen = false; helpOpen = false; render(); app.querySelector('[data-testid="deck-toggle"]')?.focus(); } return; }
  const dialog = activeDialog();
  if (dialog) {
    if (event.key === 'Tab') {
      const focusable = [...dialog.querySelectorAll('button:not(:disabled), [href], [tabindex="0"]')];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    }
    return;
  }
  if (event.key.toLowerCase() === 'd') { event.preventDefault(); openDeck(); return; }
  if (event.key === '?') { event.preventDefault(); helpOpen = true; render(); return; }
  if (state.phase !== 'combat') return;
  if (event.key.toLowerCase() === 'e') { event.preventDefault(); takeAction({ type: 'END_TURN' }); }
  if (/^[1-9]$/.test(event.key)) { const index = Number(event.key) - 1; if (index < state.hand.length && getCard(state.hand[index]).cost <= state.player.energy) { event.preventDefault(); takeAction({ type: 'PLAY_CARD', index }); } }
});

render();
