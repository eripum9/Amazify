const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = fs.existsSync(localPython) ? localPython : 'python';
const generated = spawnSync(
  python,
  ['-c', 'from amazify.runtime import build_runtime_script; print(build_runtime_script(bridge_url="",bridge_token="",plugins=[]))'],
  { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 }
);
assert.equal(generated.status, 0, generated.stderr);
new vm.Script(generated.stdout);
const start = generated.stdout.indexOf('function fullscreenElement()');
const end = generated.stdout.indexOf('function mapValuesSnapshot');
assert.ok(start >= 0 && end > start);
const fullscreenCode = generated.stdout.slice(start, end);
const cleanupStart = generated.stdout.indexOf('function cleanupPluginRegistrations');
const cleanupEnd = generated.stdout.indexOf('function buildPluginApi');
assert.ok(cleanupStart >= 0 && cleanupEnd > cleanupStart);
const cleanupCode = generated.stdout.slice(cleanupStart, cleanupEnd);

function setup() {
  let timerId = 0;
  const timers = new Map();
  const requests = [];
  const exits = [];
  const element = {};
  const document = {
    documentElement: element,
    fullscreenEnabled: true,
    fullscreenElement: null,
    exitFullscreen() {
      exits.push(true);
      this.fullscreenElement = null;
      context.handleFullscreenChange();
      return Promise.resolve();
    }
  };
  const context = vm.createContext({
    console,
    document,
    runtimeActive: true,
    renderPanel() {},
    NATIVE_FREEZE: Object.freeze,
    NATIVE_MAP: Map,
    NATIVE_MAP_GET: (map, key) => map.get(key),
    NATIVE_MAP_SET: (map, key, value) => map.set(key, value),
    NATIVE_MAP_DELETE: (map, key) => map.delete(key),
    NATIVE_MAP_FOR_EACH: (map, callback) => map.forEach(callback),
    NATIVE_MAP_CLEAR: map => map.clear(),
    NATIVE_PROMISE: Promise,
    NATIVE_SET_TIMEOUT: callback => {
      const id = ++timerId;
      timers.set(id, callback);
      return id;
    },
    NATIVE_CLEAR_TIMEOUT: id => timers.delete(id),
    state: {
      fullscreenSubscribers: new Map(),
      fullscreenRequests: new Map(),
      fullscreenPendingRequests: new Map(),
      pluginLifecycles: new Map(),
      settingsSections: new Map(),
      capabilitySubscribers: new Map(),
      pluginSettingSubscribers: new Map(),
      capabilityProviders: new Map(),
      fullscreenRequestSequence: 0,
      fullscreenSessionSequence: 0,
      fullscreenCurrentSession: null,
      fullscreenError: '',
      activePanel: null,
      preferences: { fullscreenShortcut: true }
    },
    cleanupRenderedSettingsSections() {},
    mapKeysSnapshot: map => Array.from(map.keys()),
    mapValuesSnapshot: map => Array.from(map.values()),
    revokeCapabilityRecord() {},
    window: {
      navigator: { userActivation: { isActive: true } }
    }
  });
  vm.runInContext(fullscreenCode + cleanupCode, context);
  element.requestFullscreen = function requestFullscreen() {
    requests.push(true);
    document.fullscreenElement = this;
    context.handleFullscreenChange();
    return Promise.resolve();
  };
  return { context, document, element, timers, requests, exits };
}

async function flush() {
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
}

function keyEvent(overrides = {}) {
  return {
    type: 'keydown',
    key: 'F11',
    repeat: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    metaKey: false,
    prevented: false,
    preventDefault() { this.prevented = true; },
    ...overrides
  };
}

test('F11 honors enabled state and suppresses repeats', async () => {
  const s = setup();
  const first = keyEvent();
  s.context.handleFullscreenShortcut(first);
  await flush();
  assert.equal(first.prevented, true);
  assert.equal(s.requests.length, 1);

  const repeat = keyEvent({ repeat: true });
  s.context.handleFullscreenShortcut(repeat);
  assert.equal(repeat.prevented, true);
  assert.equal(s.requests.length, 1);

  s.context.handleFullscreenShortcut({ type: 'keyup', key: 'F11' });
  const exit = keyEvent();
  s.context.handleFullscreenShortcut(exit);
  await flush();
  assert.equal(exit.prevented, true);
  assert.equal(s.exits.length, 1);

  const disabled = setup();
  disabled.context.state.preferences.fullscreenShortcut = false;
  const ignored = keyEvent();
  disabled.context.handleFullscreenShortcut(ignored);
  assert.equal(ignored.prevented, false);
  assert.equal(disabled.requests.length, 0);
});

test('requests resolve only after confirmed entry and rejected requests resolve false', async () => {
  const s = setup();
  const entered = await s.context.requestFullscreen(s.element, 'plugin.one');
  assert.equal(entered, true);
  assert.equal(s.context.fullscreenSnapshot().active, true);
  assert.equal(Object.isFrozen(s.context.fullscreenSnapshot()), true);
  assert.equal(Object.isFrozen(s.element), false);

  const rejected = setup();
  rejected.element.requestFullscreen = () => Promise.reject(new Error('denied'));
  const result = await rejected.context.requestFullscreen(rejected.element, 'plugin.one');
  assert.equal(result, false);
  assert.equal(rejected.context.state.fullscreenRequests.size, 0);

  const gated = setup();
  gated.context.window.navigator.userActivation.isActive = false;
  assert.equal(await gated.context.requestFullscreen(gated.element, 'plugin.one'), false);
  assert.equal(gated.requests.length, 0);
});

test('legacy void requests require entry confirmation and time out otherwise', async () => {
  const s = setup();
  s.element.requestFullscreen = () => undefined;
  const pending = s.context.requestFullscreen(s.element, 'plugin.one');
  assert.equal(s.context.state.fullscreenPendingRequests.size, 1);
  const timeout = s.timers.values().next().value;
  timeout();
  assert.equal(await pending, false);
  assert.equal(s.context.state.fullscreenPendingRequests.size, 0);
  assert.equal(s.context.state.fullscreenRequests.size, 0);

  const confirmed = setup();
  confirmed.element.requestFullscreen = function () {
    confirmed.document.fullscreenElement = this;
    return undefined;
  };
  assert.equal(await confirmed.context.requestFullscreen(confirmed.element, 'plugin.one'), true);
});

test('released legacy void request exits a matching late entry without touching unrelated fullscreen', async () => {
  const late = setup();
  late.element.requestFullscreen = () => undefined;
  const pending = late.context.requestFullscreen(late.element, 'plugin.one');
  assert.equal(await late.context.releaseFullscreenForPlugin('plugin.one'), false);
  late.document.fullscreenElement = late.element;
  late.context.handleFullscreenChange();
  assert.equal(await pending, false);
  assert.equal(late.exits.length, 1);
  assert.equal(late.document.fullscreenElement, null);

  const unrelated = setup();
  const otherElement = {};
  unrelated.element.requestFullscreen = () => undefined;
  const unrelatedPending = unrelated.context.requestFullscreen(unrelated.element, 'plugin.one');
  await unrelated.context.releaseFullscreenForPlugin('plugin.one');
  unrelated.document.fullscreenElement = otherElement;
  unrelated.context.handleFullscreenChange();
  assert.equal(unrelated.exits.length, 0);
  const timeout = unrelated.timers.values().next().value;
  timeout();
  assert.equal(await unrelatedPending, false);
  assert.equal(unrelated.document.fullscreenElement, otherElement);
});

test('late unmount releases owned fullscreen, while later user fullscreen is not released', async () => {
  const s = setup();
  s.context.state.pluginLifecycles.set('plugin.one', { active: true });
  assert.equal(await s.context.requestFullscreen(s.element, 'plugin.one'), true);
  s.context.cleanupPluginRegistrations('plugin.one');
  await flush();
  assert.equal(s.document.fullscreenElement, null);
  assert.equal(s.exits.length, 1);

  const later = setup();
  assert.equal(await later.context.requestFullscreen(later.element, 'plugin.one'), true);
  later.document.fullscreenElement = null;
  later.context.handleFullscreenChange();
  later.document.fullscreenElement = later.element;
  later.context.handleFullscreenChange();
  assert.equal(await later.context.releaseFullscreenForPlugin('plugin.one'), false);
  assert.equal(later.exits.length, 0);
  assert.equal(later.document.fullscreenElement, later.element);
});

test('duplicate pending owner requests do not create a second request', async () => {
  const s = setup();
  let resolveNative;
  s.element.requestFullscreen = () => new Promise(resolve => { resolveNative = resolve; });
  const first = s.context.requestFullscreen(s.element, 'plugin.one');
  const duplicate = await s.context.requestFullscreen(s.element, 'plugin.one');
  assert.equal(duplicate, false);
  assert.equal(s.context.state.fullscreenPendingRequests.size, 1);
  resolveNative();
  const timeout = s.timers.values().next().value;
  timeout();
  assert.equal(await first, false);
  assert.equal(s.context.state.fullscreenRequests.size, 0);

  const superseded = setup();
  superseded.element.requestFullscreen = () => undefined;
  const oldOwner = superseded.context.requestFullscreen(superseded.element, 'plugin.one');
  const newOwner = superseded.context.requestFullscreen(superseded.element, 'plugin.two');
  assert.equal(await oldOwner, false);
  const supersededTimeout = superseded.timers.values().next().value;
  supersededTimeout();
  assert.equal(await newOwner, false);
  assert.equal(superseded.context.state.fullscreenPendingRequests.size, 0);
});

test('fullscreen subscriber cleanup is scoped to the returned subscription', () => {
  const s = setup();
  const first = [];
  const second = [];
  const unsubscribeFirst = s.context.subscribeFullscreenForPlugin('plugin.one', snapshot => first.push(snapshot.active));
  s.context.subscribeFullscreenForPlugin('plugin.one', snapshot => second.push(snapshot.active));
  unsubscribeFirst();
  s.document.fullscreenElement = s.element;
  s.context.handleFullscreenChange();
  assert.deepEqual(first, [false]);
  assert.deepEqual(second, [false, true]);
});
