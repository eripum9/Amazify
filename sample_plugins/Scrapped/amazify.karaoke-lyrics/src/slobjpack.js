Karaoke.unpackSLObjPack = function (packed) {
  if (!Array.isArray(packed) || packed.length !== 2 || !Array.isArray(packed[0]) || !Array.isArray(packed[1])) return packed;
  const values = packed[0];
  const stream = packed[1];
  if (values.length > 50000 || stream.length > 250000 || JSON.stringify(packed).length > 4000000) throw new Error("Packed lyrics exceed limits");
  let cursor = 0;
  let nodes = 0;
  function read() {
    if (cursor >= stream.length || cursor > 250000) throw new Error("Packed lyrics ended early");
    return stream[cursor++];
  }
  function count(value, limit, label) {
    if (!Number.isInteger(value) || value < 0 || value > limit) throw new Error("Packed lyrics " + label + " is invalid");
    return value;
  }
  function pointer(index) {
    if (!Number.isInteger(index) || index < 0 || index >= values.length) throw new Error("Packed lyrics pointer is invalid");
    const value = values[index];
    if (typeof value === "string" && value.length > 100000) throw new Error("Packed lyrics string is too large");
    return value;
  }
  function key() {
    const value = pointer(read());
    if (typeof value !== "string" || value.length > 256 || value === "__proto__" || value === "prototype" || value === "constructor") throw new Error("Packed lyrics key is unsafe");
    return value;
  }
  function decode(depth) {
    nodes += 1;
    if (depth > 64 || nodes > 100000) throw new Error("Packed lyrics are too complex");
    const op = read();
    if (!Number.isInteger(op)) throw new Error("Packed lyrics opcode is invalid");
    if (op >= 0) return pointer(op);
    if (op === -4) return [];
    if (op === -5) return [decode(depth + 1)];
    if (op === -6) return Object.create(null);
    if (op === -2) {
      const length = count(read(), 50000, "array length");
      const array = [];
      for (let index = 0; index < length; index += 1) array.push(decode(depth + 1));
      return array;
    }
    if (op === -1 || op === -3) {
      const itemCount = op === -3 ? count(read(), 10000, "item count") : 1;
      const keyCount = count(read(), 512, "key count");
      const keys = [];
      for (let index = 0; index < keyCount; index += 1) keys.push(key());
      const output = [];
      for (let item = 0; item < itemCount; item += 1) {
        const object = Object.create(null);
        for (let index = 0; index < keys.length; index += 1) object[keys[index]] = decode(depth + 1);
        output.push(object);
      }
      return op === -1 ? output[0] : output;
    }
    throw new Error("Packed lyrics opcode is unknown");
  }
  const result = decode(0);
  if (cursor !== stream.length) throw new Error("Packed lyrics contain trailing operations");
  return result;
};
