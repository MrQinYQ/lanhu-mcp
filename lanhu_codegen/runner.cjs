"use strict";

const fs = require("node:fs");
const generator = require("./generator.cjs");
const dependencies = require("./dependencies.cjs");

function generateH5Files(schema, options = {}) {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    throw new Error("A DDS schema object is required");
  }
  if (!options || typeof options !== "object" || Array.isArray(options)) {
    throw new Error("options must be an object");
  }
  const rem = options.rem === undefined ? 37.5 : options.rem;
  if (typeof rem !== "number" || !Number.isFinite(rem) || rem <= 0) {
    throw new Error("options.rem must be a positive finite number");
  }
  const format = options.format === undefined ? true : options.format;
  if (typeof format !== "boolean") {
    throw new Error("options.format must be a boolean");
  }
  // The original generator mutates styles and expands loops in place.
  const input = JSON.parse(JSON.stringify(schema));
  const result = generator(input, {
    _: dependencies.lodash,
    prettier: dependencies.prettier,
    responsive: {
      width: input.style?.width || input.rect?.width || 375,
      viewportWidth: 375,
      remVal: rem,
    },
    utils: { print() {} },
  });
  const files = Object.create(null);
  for (const panel of result.panelDisplay) {
    const extension = panel.panelName.slice(panel.panelName.lastIndexOf(".") + 1);
    files[panel.panelName] = format
      ? dependencies.prettier.format(panel.panelValue, {
          parser: extension,
          plugins: dependencies.plugins,
        })
      : panel.panelValue;
  }
  return {
    files,
    generator: {
      name: "lanhu-dds-h5",
      source: "home.ae626768.js",
      module: "24c8",
      prettier: "2.5.1",
      format,
      rem,
    },
  };
}

if (require.main === module) {
  try {
    const request = JSON.parse(fs.readFileSync(0, "utf8"));
    process.stdout.write(
      JSON.stringify(generateH5Files(request.schema, request.options)) + "\n"
    );
  } catch (error) {
    process.stderr.write(JSON.stringify({ error: error.message }) + "\n");
    process.exitCode = 1;
  }
}

module.exports = { generateH5Files };
