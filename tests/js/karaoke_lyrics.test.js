const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..");
const sourceRoot = path.join(root, "sample_plugins", "amazify.karaoke-lyrics", "src");
const context = vm.createContext({ Karaoke: Object.create(null), console });
for (const name of ["slobjpack.js", "normalization.js"]) {
  vm.runInContext(fs.readFileSync(path.join(sourceRoot, name), "utf8"), context, { filename: name });
}

test("SLObjPack decodes bounded objects", () => {
  const result = context.Karaoke.unpackSLObjPack([["text", "hello"], [-1, 1, 0, 1]]);
  assert.equal(result.text, "hello");
});

test("SLObjPack rejects prototype keys and trailing operations", () => {
  assert.throws(() => context.Karaoke.unpackSLObjPack([["__proto__", "x"], [-1, 1, 0, 1]]), /unsafe/);
  assert.throws(() => context.Karaoke.unpackSLObjPack([["x"], [0, 0]]), /trailing/);
});

test("syllables group into words without synthesized timing", () => {
  const words = context.Karaoke.normalizeWords([
    { Text: "Ka", StartTime: 100, EndTime: 200 },
    { Text: "ra", StartTime: 200, EndTime: 300, IsPartOfWord: true },
    { Text: "oke", StartTime: 300, EndTime: 450 },
  ]);
  assert.equal(words.length, 2);
  assert.equal(words[0].text, "Kara");
  assert.equal(words[0].syllables.length, 2);
});

test("binary search and progress are deterministic", () => {
  const lines = [{ startMs: 0 }, { startMs: 1000 }, { startMs: 2000 }];
  assert.equal(context.Karaoke.findActiveLine(lines, 1500), 1);
  assert.equal(context.Karaoke.progress(1500, 1000, 2000), 0.5);
  assert.equal(context.Karaoke.progress(3000, 1000, 2000), 1);
});
