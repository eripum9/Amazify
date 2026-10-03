const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '../..');
const source = fs.readFileSync(
  path.join(root, 'sample_plugins/amazify.true-big-mode/plugin.js'),
  'utf8'
);

function extractFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing ${name}`);
  const open = source.indexOf('{', start);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === '{') depth += 1;
    if (source[index] === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  assert.fail(`unterminated ${name}`);
}

const settingsStart = source.indexOf('if (Amazify.settings && typeof Amazify.settings.subscribe === "function") {');
const settingsEnd = source.indexOf('\nunsubscribeLyricsCapability =', settingsStart);
assert.ok(settingsStart >= 0 && settingsEnd > settingsStart, 'settings subscription block found');
const settingsSubscription = source.slice(settingsStart, settingsEnd);
const testedSource = [
  'let autoFullscreen = false;',
  'let unsubscribeSettings = null;',
  'let fullscreenAttempted = false;',
  'let fullscreenRequestGeneration = 0;',
  extractFunction('requestFullscreenOnce'),
  extractFunction('exitPluginFullscreen'),
  settingsSubscription
].join('\n');

function setup({ setting = false, initiallyActive = false } = {}) {
  const calls = { requests: 0, releases: 0, exits: 0 };
  let resolveRequest;
  let currentSettingsListener;
  let active = initiallyActive;
  let ownsFullscreen = false;
  const context = vm.createContext({
    Promise,
    Amazify: {
      settings: {
        subscribe(listener) {
          currentSettingsListener = listener;
          listener({ autoFullscreen: setting });
          return () => {};
        }
      },
      fullscreen: {
        get active() { return active; },
        request() {
          calls.requests += 1;
          return new Promise(resolve => { resolveRequest = resolve; });
        },
        release() {
          calls.releases += 1;
          if (ownsFullscreen && active) {
            ownsFullscreen = false;
            active = false;
            calls.exits += 1;
            return Promise.resolve(true);
          }
          return Promise.resolve(false);
        }
      }
    },
    getBigModeRoot: () => null,
    syncLyricsPresentation() {},
    scheduleSync() {}
  });
  vm.runInContext(testedSource, context);
  return {
    calls,
    requestFullscreenOnce: () => vm.runInContext('requestFullscreenOnce()', context),
    setAutoFullscreen(value) {
      currentSettingsListener({ autoFullscreen: value });
    },
    isActive: () => active,
    resolveRequest(value) {
      assert.ok(resolveRequest, 'fullscreen request was started');
      resolveRequest(value);
      if (value === true) {
        active = true;
        ownsFullscreen = true;
      }
    }
  };
}

async function flushPromises() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

test('auto fullscreen defaults off and does not request entry', () => {
  const s = setup();
  s.requestFullscreenOnce();
  assert.equal(s.calls.requests, 0);
});

test('enabled auto fullscreen requests entry only once', () => {
  const s = setup({ setting: true });
  s.requestFullscreenOnce();
  s.requestFullscreenOnce();
  assert.equal(s.calls.requests, 1);
});

test('turning the setting off releases fullscreen ownership', () => {
  const s = setup({ setting: true });
  s.requestFullscreenOnce();
  s.setAutoFullscreen(false);
  assert.equal(s.calls.releases, 1);
});

test('late successful entry after disabling is released', async () => {
  const s = setup({ setting: true });
  s.requestFullscreenOnce();
  s.setAutoFullscreen(false);
  s.resolveRequest(true);
  await flushPromises();
  assert.equal(s.calls.releases, 2);
  assert.equal(s.calls.exits, 1);
  assert.equal(s.isActive(), false);
});

test('already-active external fullscreen is borrowed and not exited', async () => {
  const s = setup({ setting: true, initiallyActive: true });
  s.requestFullscreenOnce();
  assert.equal(s.calls.requests, 0);
  s.setAutoFullscreen(false);
  await flushPromises();
  assert.equal(s.calls.releases, 1);
  assert.equal(s.calls.exits, 0);
  assert.equal(s.isActive(), true);
});
