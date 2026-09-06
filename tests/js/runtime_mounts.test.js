const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const localPython = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const python = fs.existsSync(localPython) ? localPython : 'python';
const generated = spawnSync(python, ['-c', 'from amazify.runtime import build_runtime_script; print(build_runtime_script(bridge_url="",bridge_token="",plugins=[]))'], { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 });
assert.equal(generated.status, 0, generated.stderr);
new vm.Script(generated.stdout);
const mountCode = generated.stdout.slice(generated.stdout.indexOf('function mountPlugin('), generated.stdout.indexOf('function unmountPlugin('));

test('unaffected plugins retain state; own source or manifest changes remount', () => {
  const mounted = new Map(), mounts = [], cleanups = [];
  const context = vm.createContext({
    state: { mountedPlugins: mounted }, NATIVE_JSON_STRINGIFY: JSON.stringify,
    NATIVE_MAP_GET: (map, key) => map.get(key), NATIVE_MAP_SET: (map, key, value) => map.set(key, value),
    NATIVE_FUNCTION: Function, NATIVE_ASSIGN: Object.assign, freezeDeep: value => value, clonePlain: value => structuredClone(value),
    buildPluginAssetIndex: () => ({}), listPluginAssets: () => [],
    buildPluginApi: plugin => ({ markMounted: () => mounts.push(plugin.manifest.id), markCleaned: () => cleanups.push(plugin.manifest.id) }),
    unmountPlugin: id => { const previous = mounted.get(id); if (previous && previous.cleanup) previous.cleanup(); mounted.delete(id); },
  });
  vm.runInContext(mountCode, context);
  const plugin = id => ({ manifest: {id, name:id, version:'1.0.0'}, source: { entry: 'Amazify.markMounted(); return () => Amazify.markCleaned();', styles:[] } });
  const lyrics = plugin('lyrics'), theme = plugin('theme');
  context.mountPlugin(lyrics); context.mountPlugin(theme);
  const retained = mounted.get('lyrics');
  context.unmountPlugin('theme');
  context.mountPlugin(structuredClone(lyrics));
  assert.equal(mounted.get('lyrics'), retained);
  assert.deepEqual(mounts, ['lyrics', 'theme']);
  assert.deepEqual(cleanups, ['theme']);
  context.mountPlugin({...lyrics, source:{...lyrics.source, entry:lyrics.source.entry + '\n// updated'}});
  assert.deepEqual(mounts, ['lyrics', 'theme', 'lyrics']);
  context.mountPlugin({...lyrics, manifest:{...lyrics.manifest, version:'1.0.1'}});
  assert.deepEqual(cleanups, ['theme', 'lyrics', 'lyrics']);
});
