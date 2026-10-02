import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import { createRun, act, getCard } from '../src/game.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}
async function until(fn, label, timeout = 20000) {
  const deadline = Date.now() + timeout;
  let lastError;
  while (Date.now() < deadline) {
    try { const result = await fn(); if (result) return result; } catch (error) { lastError = error; }
    await pause(100);
  }
  throw new Error(`Timed out: ${label}${lastError ? ` (${lastError.message})` : ''}`);
}
function chooseLegalCard(state) {
  const playable = state.hand.map((id, index) => ({ ...getCard(id), index }))
    .filter((card) => card.cost <= state.player.energy);
  const kill = playable.find((card) => card.damage && card.damage + state.powers.attackBonus >= state.enemy.hp + state.enemy.block);
  if (kill) return kill.index;
  const free = playable.find((card) => card.cost === 0);
  if (free) return free.index;
  const power = playable.find((card) => card.type === 'power' && state.turn < 3);
  if (power) return power.index;
  if (state.enemy.intent.kind === 'attack' && state.player.block < state.enemy.intent.value) {
    const guard = playable.filter((card) => card.block).sort((a, b) => (b.block + (b.damage || 0)) - (a.block + (a.damage || 0)))[0];
    if (guard) return guard.index;
  }
  return playable.filter((card) => card.damage).sort((a, b) => (b.damage / b.cost) - (a.damage / a.cost))[0]?.index;
}
class CDP {
  constructor(socket) {
    this.socket = socket;
    this.sequence = 0;
    this.pending = new Map();
    this.errors = [];
    socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(String(data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (!pending) return;
        clearTimeout(pending.timer);
        if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
        else pending.resolve(message.result);
      }
      if (message.method === 'Runtime.exceptionThrown') this.errors.push(message.params.exceptionDetails.text);
      if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
        this.errors.push(message.params.args.map((arg) => arg.value ?? arg.description).join(' '));
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      this.pending.set(id, { resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  }
}

let browser;
let server;
let socket;
let serverOutput = '';
let browserOutput = '';
const profile = await mkdtemp(path.join(tmpdir(), 'fog-smoke-'));
const output = path.join(root, '.local');
try {
  const serverPort = await freePort();
  const browserPort = await freePort();
  server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(serverPort), '--strictPort'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.on('data', (data) => { serverOutput += data; });
  server.stderr.on('data', (data) => { serverOutput += data; });
  await until(async () => { const response = await fetch(`http://127.0.0.1:${serverPort}/`); return response.ok; }, 'Vite readiness');
  browser = spawn(process.env.CHROMIUM_BIN || 'chromium', [
    '--headless', '--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking',
    '--disable-extensions', '--no-first-run', '--no-default-browser-check',
    `--remote-debugging-port=${browserPort}`, `--user-data-dir=${profile}`, 'about:blank',
  ], { cwd: root, stdio: ['ignore', 'ignore', 'pipe'] });
  browser.on('error', (error) => { browserOutput += error.message; });
  browser.stderr.on('data', (data) => { browserOutput += data; });
  const target = await until(async () => {
    const targets = await (await fetch(`http://127.0.0.1:${browserPort}/json/list`)).json();
    return targets.find((entry) => entry.type === 'page' && entry.webSocketDebuggerUrl);
  }, 'Chromium debugging target');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }); });
  const cdp = new CDP(socket);
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${serverPort}/` });
  await until(() => cdp.evaluate("!!document.querySelector('[data-testid=game]') && document.querySelectorAll('[data-testid=card]').length === 5"), 'initial five-card hand');
  assert.match(await cdp.evaluate('document.body.textContent'), /Beyond the Gray Fog/i);
  assert.match(await cdp.evaluate('document.body.textContent'), /Ink Witness/);
  const energyBefore = await cdp.evaluate("document.querySelector('[data-testid=energy]').textContent");
  const htmlBefore = await cdp.evaluate("document.querySelector('[data-testid=game]').innerHTML");
  await cdp.evaluate("[...document.querySelectorAll('[data-testid=card]:not(:disabled)')].find(card => Number(card.querySelector('.card-cost').textContent) > 0).click()");
  assert.notEqual(await cdp.evaluate("document.querySelector('[data-testid=game]').innerHTML"), htmlBefore, 'card click changes rendered state');
  const energyAfter = await cdp.evaluate("document.querySelector('[data-testid=energy]').textContent");
  assert.ok(Number.parseInt(energyAfter, 10) < Number.parseInt(energyBefore, 10), 'card energy cost is applied');
  const turnBefore = await cdp.evaluate("document.querySelector('[data-testid=turn]').textContent");
  await cdp.evaluate("document.querySelector('[data-testid=end-turn]').click()");
  assert.notEqual(await cdp.evaluate("document.querySelector('[data-testid=turn]').textContent"), turnBefore, 'enemy turn advances combat');
  await cdp.evaluate("document.querySelector('[data-testid=deck-toggle]').click()");
  assert.ok(await cdp.evaluate("!!document.querySelector('[data-testid=deck-dialog]')"), 'deck inspector opens');
  await cdp.evaluate("document.querySelector('[data-testid=close-deck]').click()");
  assert.ok(await cdp.evaluate("!document.querySelector('[data-testid=deck-dialog]')"), 'deck inspector closes');
  await cdp.evaluate("document.querySelector('[data-testid=restart]').click()");
  assert.equal(await cdp.evaluate("document.querySelectorAll('[data-testid=card]').length"), 5, 'restart restores opening hand');
  assert.equal(await cdp.evaluate("document.querySelector('[data-testid=turn]').textContent"), turnBefore, 'restart restores first turn');
  await mkdir(output, { recursive: true });
  const desktop = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(path.join(output, 'prototype-desktop.png'), Buffer.from(desktop.data, 'base64'));
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await pause(200);
  assert.ok(await cdp.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1'), 'mobile page has no horizontal overflow');
  assert.ok(await cdp.evaluate("!!document.querySelector('[data-testid=end-turn]') && !document.querySelector('[data-testid=end-turn]').disabled"), 'mobile end-turn is usable');
  const mobile = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  await writeFile(path.join(output, 'prototype-mobile.png'), Buffer.from(mobile.data, 'base64'));
  // Drive the real DOM through a complete run using an independent legal player.
  await cdp.evaluate("document.querySelector('[data-testid=restart]').click()");
  let model = createRun(123);
  let actions = 0;
  let rewards = 0;
  while (['combat', 'reward'].includes(model.phase) && actions < 600) {
    let action;
    if (model.phase === 'reward') {
      const preference = ['moon_cut', 'red_thread', 'sealed_oath', 'lantern_flare', 'mirror_shield', 'quiet_formula'];
      const cardId = preference.find((id) => model.rewards.includes(id));
      action = { type: 'CHOOSE_REWARD', cardId };
      assert.ok(await cdp.evaluate(`!!document.querySelector('[data-testid=reward-card][data-reward="${cardId}"]')`), 'expected reward is offered');
      await cdp.evaluate(`document.querySelector('[data-testid=reward-card][data-reward="${cardId}"]').click()`);
      rewards += 1;
    } else {
      const index = chooseLegalCard(model);
      action = index === undefined ? { type: 'END_TURN' } : { type: 'PLAY_CARD', index };
      await cdp.evaluate(index === undefined
        ? "document.querySelector('[data-testid=end-turn]').click()"
        : `document.querySelector('[data-testid=card][data-index="${index}"]').click()`);
    }
    model = act(model, action);
    assert.equal(Number(await cdp.evaluate("document.querySelector('[data-testid=enemy-hp]').textContent")), model.enemy.hp, 'rendered enemy HP matches rules');
    assert.equal(Number(await cdp.evaluate("document.querySelector('[data-testid=player-hp]').textContent")), model.player.hp, 'rendered player HP matches rules');
    actions += 1;
  }
  assert.equal(model.phase, 'victory', 'complete browser run wins');
  assert.equal(rewards, 2, 'both reward selections worked');
  assert.match(await cdp.evaluate('document.body.textContent'), /EXPEDITION COMPLETE/);
  assert.deepEqual(cdp.errors, [], 'browser has no uncaught runtime or console errors');
  console.log(`PASS: actual Chromium UI — full three-encounter victory (${actions} actions, two rewards), card play, enemy turn, deck dialog, restart, mobile layout, zero runtime errors.`);
  console.log('Screenshots: .local/prototype-desktop.png and .local/prototype-mobile.png');
} catch (error) {
  console.error(error.stack);
  if (serverOutput) console.error('Vite:', serverOutput.slice(-3000));
  if (browserOutput) console.error('Chromium:', browserOutput.slice(-1500));
  process.exitCode = 1;
} finally {
  if (socket) socket.close();
  if (browser) browser.kill('SIGTERM');
  if (server) server.kill('SIGTERM');
  await pause(200);
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
}
