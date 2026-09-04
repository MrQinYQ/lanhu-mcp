"use strict";

const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const forbidden = new Set(["__proto__", "prototype", "constructor"]);

/** Read the object paths used by DDS loop bindings without evaluating code. */
function readLoopPath(value, path) {
  if (typeof path !== "string" || !path.length) {
    throw new Error("Invalid DDS loop binding path");
  }
  const tokens = [];
  let offset = 0;
  const identifier = /^[A-Za-z_$][A-Za-z0-9_$]*/;
  const first = identifier.exec(path);
  if (!first) throw new Error("Unsupported DDS loop binding path: " + path);
  tokens.push(first[0]);
  offset = first[0].length;
  while (offset < path.length) {
    if (path[offset] === ".") {
      const next = identifier.exec(path.slice(offset + 1));
      if (!next) throw new Error("Unsupported DDS loop binding path: " + path);
      tokens.push(next[0]);
      offset += next[0].length + 1;
      continue;
    }
    const next = /^\[(?:(0|[1-9][0-9]*)|"([^"\\]*)"|'([^'\\]*)')\]/.exec(
      path.slice(offset)
    );
    if (!next) throw new Error("Unsupported DDS loop binding path: " + path);
    tokens.push(next[1] ?? next[2] ?? next[3]);
    offset += next[0].length;
  }
  for (const token of tokens) {
    if (forbidden.has(token)) {
      throw new Error("Unsupported DDS loop binding property: " + token);
    }
    if (value == null || !hasOwn(value, token)) return undefined;
    value = value[token];
  }
  return value;
}

module.exports = { readLoopPath };
