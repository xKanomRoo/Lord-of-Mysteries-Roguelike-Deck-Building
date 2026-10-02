import test from 'node:test';
import assert from 'node:assert/strict';
import { CARD_LIBRARY, ENCOUNTERS, createRun, act, getCard } from '../src/game.js';

function fixture({ hand, player = {}, enemy = {}, ...rest } = {}) {
  const state = createRun(123);
  return {
    ...state,
    ...rest,
    hand: hand || state.hand,
    player: { ...state.player, ...player },
    enemy: { ...state.enemy, ...enemy },
  };
}

function freezeDeep(value) {
  Object.freeze(value);
  for (const child of Object.values(value)) {
    if (child && typeof child === 'object' && !Object.isFrozen(child)) freezeDeep(child);
  }
  return value;
}

test('a seed reproduces a run and shuffle, while another seed changes the hand', () => {
  assert.deepEqual(createRun(456), createRun(456));
  assert.notDeepEqual(createRun(456).hand, createRun(789).hand);
  assert.equal(createRun(0).hand.length, 5);
  assert.equal(createRun().player.energy, 3);
  assert.equal(ENCOUNTERS.length, 3);
  assert.equal(getCard('etched_strike'), CARD_LIBRARY.etched_strike);
  assert.equal(getCard('missing'), undefined);
  assert.equal(getCard('toString'), undefined);
});

test('playing pays energy, deals damage, discards the card, and preserves a frozen snapshot', () => {
  const state = freezeDeep(fixture({ hand: ['etched_strike', 'paper_ward'] }));
  const next = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(next.player.energy, 2);
  assert.equal(next.enemy.hp, state.enemy.hp - 6);
  assert.deepEqual(next.hand, ['paper_ward']);
  assert.deepEqual(next.discardPile, ['etched_strike']);
  assert.equal(state.player.energy, 3);
  assert.equal(state.discardPile.length, 0);
});

test('unaffordable cards, malformed indexes, and unrelated actions leave state unchanged', () => {
  const state = fixture({ hand: ['spirit_lance'], player: { energy: 1 } });
  for (const action of [
    { type: 'PLAY_CARD', index: 0 },
    { type: 'PLAY_CARD', index: -1 },
    { type: 'PLAY_CARD', index: 0.5 },
    { type: 'PLAY_CARD', index: 2 },
    { type: 'CHOOSE_REWARD', cardId: 'moon_cut' },
    { type: 'UNKNOWN' },
    null,
  ]) assert.equal(act(state, action), state);
});

test('block absorbs the enemy attack, then clears and energy refreshes on the next turn', () => {
  const state = fixture({ hand: ['paper_ward'] });
  const guarded = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(guarded.player.block, 7);
  const next = act(guarded, { type: 'END_TURN' });
  assert.equal(next.player.hp, state.player.hp);
  assert.equal(next.player.block, 0);
  assert.equal(next.player.energy, 3);
  assert.equal(next.turn, 2);
  assert.equal(next.hand.length, 5);
  assert.deepEqual(next.enemy.intent, { kind: 'attack', value: 7 });
});

test('enemy defense is announced, blocks player attacks, and expires before its following move', () => {
  const state = fixture({
    hand: ['etched_strike'],
    enemy: { intent: { kind: 'defend', value: 8 }, intentIndex: 2 },
  });
  const defended = act(state, { type: 'END_TURN' });
  assert.equal(defended.enemy.block, 8);
  const struck = act({ ...defended, hand: ['etched_strike'] }, { type: 'PLAY_CARD', index: 0 });
  assert.equal(struck.enemy.block, 2);
  assert.equal(struck.enemy.hp, state.enemy.hp);
  assert.equal(act(struck, { type: 'END_TURN' }).enemy.block, 0);
});

test('drawing crosses an empty draw pile and deterministically reshuffles the discard', () => {
  const state = fixture({
    hand: ['cold_reading'],
    drawPile: ['etched_strike'],
    discardPile: ['paper_ward', 'steady_breath'],
  });
  const next = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(next.hand.length, 2);
  assert.equal(next.hand[0], 'etched_strike');
  assert.deepEqual(next.discardPile, ['cold_reading']);
  assert.equal(next.drawPile.length, 1);
  assert.equal(next.player.sanity, 11);
  assert.deepEqual(next, act(state, { type: 'PLAY_CARD', index: 0 }));
  assert.ok(next.log.some((entry) => entry.includes('discard pile')));
});

test('a resolving draw card cannot shuffle into its own draw effect', () => {
  const state = fixture({ hand: ['cold_reading'], drawPile: [], discardPile: [] });
  const next = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.deepEqual(next.hand, []);
  assert.deepEqual(next.discardPile, ['cold_reading']);
});

test('sanity is clamped and zero sanity causes damage even through block', () => {
  const state = fixture({ hand: ['spirit_lance'], player: { sanity: 1, block: 20 } });
  const spent = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(spent.player.sanity, 0);
  assert.equal(act(spent, { type: 'END_TURN' }).player.hp, state.player.hp - 3);
  const recovered = act(fixture({ hand: ['steady_breath'], player: { sanity: 11 } }), { type: 'PLAY_CARD', index: 0 });
  assert.equal(recovered.player.sanity, 12);
});

test('powers exhaust and add damage only for the current encounter', () => {
  const state = fixture({ hand: ['sealed_oath', 'etched_strike'] });
  const empowered = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(empowered.powers.attackBonus, 2);
  assert.deepEqual(empowered.exhaustPile, ['sealed_oath']);
  assert.deepEqual(empowered.discardPile, []);
  assert.equal(act(empowered, { type: 'PLAY_CARD', index: 0 }).enemy.hp, state.enemy.hp - 8);
});

test('a defeated enemy offers three unique rewards, and a valid choice advances and restores resources', () => {
  const state = fixture({
    hand: ['etched_strike'],
    player: { hp: 40, sanity: 4 },
    enemy: { hp: 6 },
    powers: { attackBonus: 2 },
  });
  const reward = act(state, { type: 'PLAY_CARD', index: 0 });
  assert.equal(reward.phase, 'reward');
  assert.equal(reward.enemy.hp, 0);
  assert.equal(reward.rewards.length, 3);
  assert.equal(new Set(reward.rewards).size, 3);
  assert.equal(act(reward, { type: 'CHOOSE_REWARD', cardId: 'missing' }), reward);
  assert.equal(act(reward, { type: 'END_TURN' }), reward);
  const next = act(reward, { type: 'CHOOSE_REWARD', cardId: reward.rewards[0] });
  assert.equal(next.phase, 'combat');
  assert.equal(next.encounter, 1);
  assert.equal(next.player.hp, 48);
  assert.equal(next.player.sanity, 7);
  assert.equal(next.player.energy, 3);
  assert.equal(next.powers.attackBonus, 0);
  assert.equal(next.deck.length, state.deck.length + 1);
  assert.equal(next.hand.length, 5);
  assert.equal(next.enemy.name, ENCOUNTERS[1].name);
});

test('lethal damage enters defeat and rejects all later combat actions', () => {
  const state = fixture({ player: { hp: 2, block: 0 } });
  const lost = act(state, { type: 'END_TURN' });
  assert.equal(lost.phase, 'defeat');
  assert.equal(lost.player.hp, 0);
  assert.equal(act(lost, { type: 'END_TURN' }), lost);
  assert.equal(act(lost, { type: 'PLAY_CARD', index: 0 }), lost);
});

// A simple legal player: inspect current cards and intent, defend when needed,
// then spend energy on damage. It never modifies engine state or enemy HP.
function choosePlay(state) {
  const playable = state.hand.map((id, index) => ({ ...getCard(id), index }))
    .filter((card) => card.cost <= state.player.energy);
  const immediateKill = playable.find((card) => card.damage
    && card.damage + state.powers.attackBonus >= state.enemy.hp + state.enemy.block);
  if (immediateKill) return immediateKill.index;
  const free = playable.find((card) => card.cost === 0);
  if (free) return free.index;
  const power = playable.find((card) => card.type === 'power' && state.turn < 3);
  if (power) return power.index;
  if (state.enemy.intent.kind === 'attack' && state.player.block < state.enemy.intent.value) {
    const guard = playable.filter((card) => card.block)
      .sort((a, b) => (b.block + (b.damage || 0)) - (a.block + (a.damage || 0)))[0];
    if (guard) return guard.index;
  }
  const attack = playable.filter((card) => card.damage)
    .sort((a, b) => (b.damage / b.cost) - (a.damage / a.cost))[0];
  return attack?.index;
}

test('a complete seeded run wins all three encounters using only legitimate actions', () => {
  let state = createRun(123);
  let actions = 0;
  let rewardsChosen = 0;
  while (['combat', 'reward'].includes(state.phase) && actions < 600) {
    if (state.phase === 'reward') {
      const preference = ['moon_cut', 'red_thread', 'sealed_oath', 'lantern_flare', 'mirror_shield', 'quiet_formula'];
      const cardId = preference.find((id) => state.rewards.includes(id));
      state = act(state, { type: 'CHOOSE_REWARD', cardId });
      rewardsChosen += 1;
    } else {
      const index = choosePlay(state);
      state = act(state, index === undefined ? { type: 'END_TURN' } : { type: 'PLAY_CARD', index });
    }
    actions += 1;
  }
  assert.equal(state.phase, 'victory', JSON.stringify({ actions, hp: state.player.hp, encounter: state.encounter, log: state.log }));
  assert.equal(state.encounter, 2);
  assert.equal(rewardsChosen, 2);
  assert.ok(state.player.hp > 0);
  assert.equal(state.enemy.hp, 0);
  assert.deepEqual(state.rewards, []);
  assert.equal(act(state, { type: 'END_TURN' }), state);
});
