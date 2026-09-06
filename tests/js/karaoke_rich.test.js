const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../sample_plugins/amazify.karaoke-lyrics/src');

function setup() {
  let id = 0;
  const timers = new Map(), frames = new Map(), requests = [], cancels = [];
  const context = vm.createContext({ console, Set, Object, Promise, Math,
    document: { visibilityState: 'visible' }, getComputedStyle: () => ({ display: 'block', visibility: 'visible' }),
    requestAnimationFrame: callback => { frames.set(++id, callback); return id; },
    cancelAnimationFrame: key => frames.delete(key),
    setTimeout: callback => { timers.set(++id, callback); return id; }, clearTimeout: key => timers.delete(key),
    Karaoke: { seek() {}, readPlaybackTime: () => 500, isPlaying: () => true,
      Renderer: function () { this.node = { isConnected: false }; this.setModel = model => { this.model = model; if (!model) this.release(); }; this.claim = (host, presentation) => { this.node.isConnected = true; this.host = host; this.presentation = presentation; }; this.release = () => { this.node.isConnected = false; }; this.update = () => {}; this.destroy = this.release; }
    }
  });
  for (const name of ['normalization.js', 'session.js']) vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), context);
  const provider = { load(track, key) { return new Promise(resolve => requests.push({ track, key, resolve })); }, cancel(key) { cancels.push(key); return Promise.resolve(); } };
  const session = new context.Karaoke.Session(provider);
  const host = { nodeType: 1, isConnected: true, getClientRects: () => [{}] };
  const track = { key: 'amazon:test:A', title: 'A', artists: ['Artist'], hasLyrics: true };
  return { context, session, requests, cancels, frames, timers, host, track };
}
function model(key) { return { schemaVersion: 1, type: 'syllable', source: 'unison', trackKey: key, lines: [{text:'Testing words',startMs:0,endMs:2000,words:[{text:'Testing ',startMs:0,endMs:1000,syllables:[{text:'Test',startMs:0,endMs:500},{text:'ing ',startMs:500,endMs:1000}]},{text:'words',startMs:1000,endMs:2000}]}] }; }
async function flush() { for(let i=0;i<6;i++) await Promise.resolve(); }

test('rich boundary preserves real syllables and rejects line-only, wrong-track and bad timing', () => {
  const { context } = setup(), k = context.Karaoke;
  const rich = k.normalizeRich(model('A'), 'A');
  assert.equal(rich.lines[0].words[0].syllables[1].text, 'ing ');
  assert.equal(k.normalizeRich(model('A'), 'B'), null);
  const bad = model('A'); bad.lines[0].words = [];
  assert.equal(k.normalizeRich(bad, 'A'), null);
  bad.lines[0].words = [{ text:'x', startMs:0, endMs:NaN }];
  assert.equal(k.normalizeRich(bad, 'A'), null);
  assert.equal(k.progress(750, 500, 1000), 0.5);
  assert.equal(k.progress(750, 1000, 1000), 0);
  assert.equal(k.findActiveLine([{startMs:0},{startMs:500},{startMs:1000}], 750),1);
});
test('lazy loading, no refetch loop after a miss, native lyrics preserved', async () => {
  const s = setup();
  s.session.setTrack(s.track); await flush(); assert.equal(s.requests.length, 0);
  s.session.setDefaultHost(s.host); await flush(); assert.equal(s.requests.length, 1);
  s.requests[0].resolve({ status:'no-lyrics',trackKey:s.track.key }); await flush();
  for(let i=0;i<5;i++) s.session.setDefaultHost(s.host);
  await flush(); assert.equal(s.requests.length,1);
  assert.equal(s.session.renderer.node.isConnected,false);
  assert.equal(s.session.snapshot().hasLyrics,true);
  assert.equal(s.frames.size,0);
});
test('stale provider completion and timeout cannot cover the next track', async () => {
  const s=setup(); s.session.setTrack(s.track); s.session.setDefaultHost(s.host); await flush();
  s.session.setTrack({...s.track,key:'amazon:test:B'}); s.session.ensureLoad(); await flush();
  s.requests[0].resolve({status:'ready',trackKey:s.track.key,payload:model(s.track.key)}); await flush();
  assert.equal(s.session.model,null); assert.equal(s.cancels.length,1);
  Array.from(s.timers.values())[0]();
  s.requests[1].resolve({status:'ready',trackKey:'amazon:test:B',payload:model('amazon:test:B')}); await flush();
  assert.equal(s.session.model,null); assert.equal(s.session.status,'native');
});
test('one renderer/RAF survives host changes, closes and reopen without loading again', async () => {
  const s=setup(); s.session.setTrack(s.track); s.session.setDefaultHost(s.host); await flush();
  s.requests[0].resolve({status:'ready',trackKey:s.track.key,payload:model(s.track.key)}); await flush();
  const renderer=s.session.renderer;
  const release=s.session.claimHost(s.host,{presentation:'true-big-mode',priority:100});
  assert.equal(renderer.presentation,'true-big-mode'); assert.equal(s.frames.size,1);
  release(); assert.equal(renderer.presentation,'normal');
  s.session.setDefaultHost(null); assert.equal(renderer.node.isConnected,false); assert.equal(s.frames.size,0);
  s.session.setDefaultHost(s.host); await flush();
  assert.equal(s.requests.length,1); assert.equal(s.session.renderer,renderer);
  s.context.Karaoke.isPlaying = () => false;
  for(const callback of s.frames.values()) { s.frames.clear(); callback(); }
  assert.equal(s.frames.size,0);
  s.session.destroy(); assert.equal(renderer.node.isConnected,false); assert.equal(s.timers.size,0);
});
test('native-only CSS has no unscoped fallback changes or theme palette', () => {
  const css=fs.readFileSync(path.join(root,'../normal.css'),'utf8');
  assert.ok(css.split('\n').filter(line=>line.includes('{')).every(line=>line.includes('.amazify-karaoke-enhanced') || line.includes('.amazify-karaoke-provider-lyrics')));
  const base=fs.readFileSync(path.join(root,'../base.css'),'utf8');
  assert.doesNotMatch(base, /#[0-9a-f]{3,8}\b|font-size:|font-family:|signal-/i);
  const tokens = base.match(/\.amazify-karaoke-line \.lyricsText \.amazify-karaoke-token\s*\{([^}]+)\}/)[1];
  assert.match(tokens, /font:\s*inherit\s*!important/);
  assert.match(tokens, /letter-spacing:\s*inherit\s*!important/);
});
test('bootstrap refuses old Spotify broker before registering any UI', () => {
  const s=setup(); vm.runInContext(fs.readFileSync(path.join(root,'bootstrap.js'),'utf8'),s.context);
  assert.throws(()=>s.context.Karaoke.bootstrap({lyricsProvider:{}}), /1.1.2/);
});

test('an open view can load provider-only lyrics before Amazon creates a wrapper', async () => {
  const s=setup(); s.session.setTrack({...s.track,hasLyrics:false});
  s.session.setDefaultHost(null,s.host); await flush();
  assert.equal(s.requests.length,1);
  s.requests[0].resolve({status:'ready',trackKey:s.track.key,payload:model(s.track.key)}); await flush();
  assert.equal(s.session.snapshot().hasLyrics,true);
  s.session.setDefaultHost(s.host,s.host);
  assert.equal(s.session.snapshot().enhanced,true);
  s.session.setTrack({...s.track,key:'amazon:test:no-lyrics',hasLyrics:false});
  assert.equal(s.session.snapshot().enhanced,false);
  assert.equal(s.session.snapshot().hasLyrics,false);
  s.session.destroy();
});

test('disabled presentation blocks loads, cancels pending work and resumes on release', async () => {
  const s=setup(); s.session.setTrack(s.track);
  const release=s.session.claimHost(s.host,{presentation:'true-big-mode',priority:100,enabled:false});
  s.session.setDefaultHost(null,s.host); await flush();
  assert.equal(s.requests.length,0); assert.equal(s.session.snapshot().suspended,true);
  release(); await flush(); assert.equal(s.requests.length,1);
  const stop=s.session.claimHost(s.host,{presentation:'true-big-mode',priority:100,enabled:false});
  assert.equal(s.cancels.length,1); assert.equal(s.frames.size,0);
  s.requests[0].resolve({status:'ready',trackKey:s.track.key,payload:model(s.track.key)}); await flush();
  assert.equal(s.session.model,null); assert.equal(s.session.loaded,false);
  s.session.setTrack({...s.track,key:'amazon:test:B'}); s.session.ensureLoad(); await flush();
  assert.equal(s.requests.length,1);
  stop(); await flush(); assert.equal(s.requests.length,2);
  assert.equal(s.requests[1].track.key,'amazon:test:B'); s.session.destroy();
});

test('disabled presentation releases enhancement but retains data without refetching', async () => {
  const s=setup(); s.session.setTrack(s.track); s.session.setDefaultHost(s.host); await flush();
  s.requests[0].resolve({status:'ready',trackKey:s.track.key,payload:model(s.track.key)}); await flush();
  const renderer=s.session.renderer, rich=s.session.model;
  const release=s.session.claimHost(s.host,{priority:100,enabled:false});
  assert.equal(renderer.node.isConnected,false); assert.equal(s.frames.size,0);
  assert.equal(s.session.model,rich);
  release(); await flush();
  assert.equal(renderer.node.isConnected,true); assert.equal(s.requests.length,1);
  assert.equal(s.session.renderer,renderer); assert.equal(s.frames.size,1);
  s.session.destroy();
});

test('a synchronous disabled claim prevents a queued provider call on activation', async () => {
  const s=setup(); s.session.setTrack(s.track); s.session.setDefaultHost(s.host);
  s.session.claimHost(s.host,{priority:100,enabled:false}); await flush();
  assert.equal(s.requests.length,0); assert.equal(s.session.loaded,false);
  s.session.destroy();
});
