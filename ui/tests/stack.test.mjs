import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const pkg = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url)),
);
test("native Vue3 stack has no Vue2 compiled bridge or unused plugins", () => {
  assert.match(pkg.dependencies.vue, /^3\./);
  for (const name of [
    "@nethserver/ns8-ui-lib",
    "vue-date-fns",
    "lottie-web-vue",
    "vue-debounce",
    "@babel/core",
    "@babel/eslint-parser",
  ])
    assert.equal(
      pkg.dependencies[name] || pkg.devDependencies[name],
      undefined,
      name,
    );
});

test("installed toolchain matches exact manifest pins", () => {
  for (const [name, version] of Object.entries({
    ...pkg.dependencies,
    ...pkg.devDependencies,
  })) {
    const installed = JSON.parse(
      readFileSync(
        new URL(`../node_modules/${name}/package.json`, import.meta.url),
      ),
    );
    assert.equal(installed.version, version, name);
  }
  const carbon = JSON.parse(
    readFileSync(
      new URL("../node_modules/@carbon/vue/package.json", import.meta.url),
    ),
  );
  assert.match(carbon.dependencies["carbon-components"], /10\./);
  const plugin = JSON.parse(
    readFileSync(
      new URL(
        "../node_modules/@vitejs/plugin-vue/package.json",
        import.meta.url,
      ),
    ),
  );
  assert.match(plugin.peerDependencies.vite, /\^8\.0\.0/);
});
