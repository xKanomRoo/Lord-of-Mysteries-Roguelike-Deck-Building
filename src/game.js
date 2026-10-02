/**
 * An original, dependency-free roguelike deck-building rules engine.
 * All state changes are returned as new objects; callers may keep old snapshots.
 */

const cards = [
  {
    id: 'etched_strike', name: 'Etched Strike', cost: 1, type: 'attack', rarity: 'basic',
    description: 'Deal 6 damage.', damage: 6,
  },
  {
    id: 'paper_ward', name: 'Paper Ward', cost: 1, type: 'skill', rarity: 'basic',
    description: 'Gain 7 block. Block expires at your next turn.', block: 7,
  },
  {
    id: 'cold_reading', name: 'Cold Reading', cost: 0, type: 'skill', rarity: 'basic',
    description: 'Draw 2 cards. Lose 1 sanity.', draw: 2, sanityCost: 1,
  },
  {
    id: 'spirit_lance', name: 'Spirit Lance', cost: 2, type: 'attack', rarity: 'basic',
    description: 'Deal 15 damage. Lose 2 sanity.', damage: 15, sanityCost: 2,
  },
  {
    id: 'steady_breath', name: 'Steady Breath', cost: 1, type: 'skill', rarity: 'basic',
    description: 'Gain 5 block. Recover 3 sanity.', block: 5, sanity: 3,
  },
  {
    id: 'moon_cut', name: 'Moon Cut', cost: 1, type: 'attack', rarity: 'uncommon',
    description: 'Deal 10 damage.', damage: 10,
  },
  {
    id: 'mirror_shield', name: 'Mirror Shield', cost: 1, type: 'skill', rarity: 'uncommon',
    description: 'Gain 11 block.', block: 11,
  },
  {
    id: 'lantern_flare', name: 'Lantern Flare', cost: 2, type: 'attack', rarity: 'uncommon',
    description: 'Deal 16 damage. Draw 1 card. Lose 1 sanity.', damage: 16, draw: 1, sanityCost: 1,
  },
  {
    id: 'quiet_formula', name: 'Quiet Formula', cost: 0, type: 'skill', rarity: 'uncommon',
    description: 'Recover 3 sanity. Draw 1 card. Exhaust for this encounter.',
    sanity: 3, draw: 1, exhaust: true,
  },
  {
    id: 'red_thread', name: 'Red Thread', cost: 1, type: 'attack', rarity: 'uncommon',
    description: 'Deal 7 damage. Gain 4 block.', damage: 7, block: 4,
  },
  {
    id: 'sealed_oath', name: 'Sealed Oath', cost: 1, type: 'power', rarity: 'rare',
    description: 'Your attacks deal 2 additional damage this encounter. Exhaust.',
    attackBonus: 2, exhaust: true,
  },
];

export const CARD_LIBRARY = Object.freeze(Object.fromEntries(
  cards.map((card) => [card.id, Object.freeze(card)]),
));

export const ENCOUNTERS = Object.freeze([
  Object.freeze({
    id: 'ink_witness', name: 'Ink Witness', maxHp: 30,
    description: 'A silhouette walks out of an unfinished case file.',
    intents: Object.freeze([
      Object.freeze({ kind: 'attack', value: 5 }),
      Object.freeze({ kind: 'attack', value: 7 }),
      Object.freeze({ kind: 'defend', value: 5 }),
    ]),
  }),
  Object.freeze({
    id: 'bell_keeper', name: 'Bell Keeper', maxHp: 42,
    description: 'Every toll makes the empty street a little narrower.',
    intents: Object.freeze([
      Object.freeze({ kind: 'attack', value: 8 }),
      Object.freeze({ kind: 'defend', value: 7 }),
      Object.freeze({ kind: 'attack', value: 10 }),
    ]),
  }),
  Object.freeze({
    id: 'unwritten_fate', name: 'Unwritten Fate', maxHp: 58,
    description: 'The last page refuses the ending you brought with you.',
    intents: Object.freeze([
      Object.freeze({ kind: 'defend', value: 8 }),
      Object.freeze({ kind: 'attack', value: 11 }),
      Object.freeze({ kind: 'attack', value: 13 }),
    ]),
  }),
]);

const STARTING_DECK = Object.freeze([
  'etched_strike', 'etched_strike', 'etched_strike', 'etched_strike', 'etched_strike',
  'paper_ward', 'paper_ward', 'paper_ward', 'paper_ward',
  'cold_reading', 'spirit_lance', 'steady_breath',
]);
const REWARD_CARDS = cards.filter((card) => card.rarity !== 'basic').map((card) => card.id);
const HAND_SIZE = 5;
const STRAIN_DAMAGE = 3;

export function getCard(id) {
  return Object.hasOwn(CARD_LIBRARY, id) ? CARD_LIBRARY[id] : undefined;
}

function log(state, message) {
  state.log.push(message);
  if (state.log.length > 40) state.log.shift();
}

function random(state) {
  let value = state.rng >>> 0;
  value ^= value << 13;
  value ^= value >>> 17;
  value ^= value << 5;
  state.rng = value >>> 0;
  return state.rng / 0x100000000;
}

function shuffle(state, source) {
  const result = [...source];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const other = Math.floor(random(state) * (index + 1));
    [result[index], result[other]] = [result[other], result[index]];
  }
  return result;
}

function draw(state, count) {
  for (let index = 0; index < count; index += 1) {
    if (state.drawPile.length === 0) {
      if (state.discardPile.length === 0) break;
      state.drawPile = shuffle(state, state.discardPile);
      state.discardPile = [];
      log(state, 'The discard pile returns to the draw pile.');
    }
    state.hand.push(state.drawPile.pop());
  }
}

function copyState(state) {
  return {
    ...state,
    player: { ...state.player },
    enemy: { ...state.enemy, intent: { ...state.enemy.intent } },
    powers: { ...state.powers },
    deck: [...state.deck],
    drawPile: [...state.drawPile],
    hand: [...state.hand],
    discardPile: [...state.discardPile],
    exhaustPile: [...state.exhaustPile],
    rewards: [...state.rewards],
    log: [...state.log],
  };
}

function startEncounter(state) {
  const template = ENCOUNTERS[state.encounter];
  state.phase = 'combat';
  state.turn = 1;
  state.enemy = {
    id: template.id,
    name: template.name,
    description: template.description,
    hp: template.maxHp,
    maxHp: template.maxHp,
    block: 0,
    intentIndex: 0,
    intent: { ...template.intents[0] },
  };
  state.player.block = 0;
  state.player.energy = state.player.maxEnergy;
  state.powers = { attackBonus: 0 };
  state.drawPile = shuffle(state, state.deck);
  state.hand = [];
  state.discardPile = [];
  state.exhaustPile = [];
  state.rewards = [];
  log(state, `Encounter ${state.encounter + 1}: ${template.name}.`);
  draw(state, HAND_SIZE);
}

export function createRun(seed = 123) {
  const numericSeed = Number.isFinite(Number(seed)) ? Number(seed) >>> 0 : 123;
  const state = {
    phase: 'combat',
    seed: numericSeed,
    rng: numericSeed || 0x9e3779b9,
    encounter: 0,
    player: { hp: 70, maxHp: 70, block: 0, energy: 3, maxEnergy: 3, sanity: 12, maxSanity: 12 },
    enemy: null,
    deck: [...STARTING_DECK],
    drawPile: [],
    hand: [],
    discardPile: [],
    exhaustPile: [],
    powers: { attackBonus: 0 },
    rewards: [],
    log: [],
    turn: 1,
  };
  startEncounter(state);
  return state;
}

function finishEncounter(state) {
  if (state.enemy.hp > 0) return;
  state.enemy.hp = 0;
  log(state, `${state.enemy.name} is defeated.`);
  if (state.encounter === ENCOUNTERS.length - 1) {
    state.phase = 'victory';
    state.rewards = [];
    log(state, 'You leave the archive with your own ending.');
  } else {
    state.phase = 'reward';
    state.rewards = shuffle(state, REWARD_CARDS).slice(0, 3);
    log(state, 'Choose a card. Then recover 8 health and 3 sanity.');
  }
}

function playCard(state, index) {
  const next = copyState(state);
  const card = getCard(next.hand[index]);
  next.player.energy -= card.cost;
  next.hand.splice(index, 1);
  next.player.sanity = Math.min(next.player.maxSanity, Math.max(
    0, next.player.sanity - (card.sanityCost || 0) + (card.sanity || 0),
  ));
  next.player.block += card.block || 0;
  next.powers.attackBonus += card.attackBonus || 0;
  if (card.damage) {
    const damage = card.damage + next.powers.attackBonus;
    const blocked = Math.min(next.enemy.block, damage);
    next.enemy.block -= blocked;
    next.enemy.hp = Math.max(0, next.enemy.hp - (damage - blocked));
    log(next, `${card.name}: ${damage - blocked} damage${blocked ? ` (${blocked} blocked)` : ''}.`);
  } else {
    log(next, `${card.name} played.`);
  }
  // A killing blow closes the encounter before drawing more cards.
  finishEncounter(next);
  if (next.phase === 'combat' && card.draw) draw(next, card.draw);
  // Keep a resolving draw card out of the reshuffle so it cannot draw itself.
  (card.exhaust ? next.exhaustPile : next.discardPile).push(card.id);
  return next;
}

function endTurn(state) {
  const next = copyState(state);
  next.discardPile.push(...next.hand);
  next.hand = [];
  next.enemy.block = 0;

  if (next.player.sanity === 0) {
    next.player.hp = Math.max(0, next.player.hp - STRAIN_DAMAGE);
    log(next, `Mental strain: lose ${STRAIN_DAMAGE} health, ignoring block.`);
  }
  if (next.player.hp > 0) {
    const { kind, value } = next.enemy.intent;
    if (kind === 'attack') {
      const blocked = Math.min(next.player.block, value);
      next.player.block -= blocked;
      next.player.hp = Math.max(0, next.player.hp - (value - blocked));
      log(next, `${next.enemy.name} attacks: ${value - blocked} damage${blocked ? ` (${blocked} blocked)` : ''}.`);
    } else {
      next.enemy.block = value;
      log(next, `${next.enemy.name} gains ${value} block.`);
    }
  }
  if (next.player.hp === 0) {
    next.phase = 'defeat';
    log(next, 'The archive closes around you.');
    return next;
  }

  const intents = ENCOUNTERS[next.encounter].intents;
  next.enemy.intentIndex = (next.enemy.intentIndex + 1) % intents.length;
  next.enemy.intent = { ...intents[next.enemy.intentIndex] };
  next.turn += 1;
  next.player.block = 0;
  next.player.energy = next.player.maxEnergy;
  draw(next, HAND_SIZE);
  return next;
}

/**
 * Apply PLAY_CARD {index}, END_TURN, or CHOOSE_REWARD {cardId}.
 * Invalid actions return the exact same state reference.
 */
export function act(state, action) {
  if (!state || !action || typeof action !== 'object') return state;
  if (state.phase === 'combat') {
    if (action.type === 'PLAY_CARD') {
      if (!Number.isInteger(action.index) || action.index < 0 || action.index >= state.hand.length) return state;
      const card = getCard(state.hand[action.index]);
      if (!card || card.cost > state.player.energy) return state;
      return playCard(state, action.index);
    }
    if (action.type === 'END_TURN') return endTurn(state);
  }
  if (state.phase === 'reward' && action.type === 'CHOOSE_REWARD' && state.rewards.includes(action.cardId)) {
    const next = copyState(state);
    next.deck.push(action.cardId);
    next.player.hp = Math.min(next.player.maxHp, next.player.hp + 8);
    next.player.sanity = Math.min(next.player.maxSanity, next.player.sanity + 3);
    next.encounter += 1;
    log(next, `${getCard(action.cardId).name} joins your deck.`);
    startEncounter(next);
    return next;
  }
  return state;
}
