// Execute inside the pinned official Renovate image; no network or repository writes.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolveConfigPresets } from '/usr/local/renovate/dist/config/presets/index.js';
import { applyPackageRules } from '/usr/local/renovate/dist/util/package-rules/index.js';
import { init } from '/usr/local/renovate/dist/logger/index.js';
await init();
const raw = JSON.parse(await readFile('renovate.json', 'utf8'));
const { config } = await resolveConfigPresets(raw);
assert.equal(config.automerge, false, 'dependency proposals must require manual merge');
console.log('PASS manual merge gate');
const { GlobalConfig } = await import('/usr/local/renovate/dist/config/global.js');
const { setPlatformScmApi } = await import('/usr/local/renovate/dist/modules/platform/scm.js');
const { bumpVersions } = await import('/usr/local/renovate/dist/workers/repository/update/branch/bump-versions.js');
const { extractPackageFile } = await import('/usr/local/renovate/dist/modules/manager/custom/regex/index.js');
GlobalConfig.set({ localDir: process.cwd(), platform: 'local' });
setPlatformScmApi('local');
let passed = 1;
function check(name, actual, expected) {
  assert.deepEqual(actual, expected, name);
  console.log(`PASS ${name}`);
  passed++;
}
const rule = (dep) => applyPackageRules({ ...config, packageName: dep.depName, ...dep });
const shell = config.customManagers.find(m => m.description?.startsWith('Shell image pins'));
for (const [file, expected] of [['build-images.sh', ['docker.io/adguard/adguardhome', 'docker.io/library/node']], ['test-module.sh', ['ghcr.io/marketsquare/robotframework-browser/rfbrowser-stable']]]) {
  const result = extractPackageFile(await readFile(file, 'utf8'), file, shell);
  check(`native RE2 extracts ${file}`, result.deps.map(d => d.depName), expected);
  if (file === 'build-images.sh') check('runtime digest retained', result.deps[0].currentDigest.startsWith('sha256:'), true);
}
const python = config.customManagers.find(m => m.description === 'Pinned Python test dependencies');
for (const [file, expected] of [['test-module.sh', 'robotframework-sshlibrary'], ['.github/workflows/validate.yml', 'PyYAML']]) {
  check(`extracts Python pin in ${file}`, extractPackageFile(await readFile(file, 'utf8'), file, python).deps[0].depName, expected);
}
for (const [manager, depName, packageFile, depType] of [
  ['custom.regex', 'docker.io/library/node', 'build-images.sh', undefined],
  ['dockerfile', 'node', 'ui/Containerfile', undefined],
  ['github-actions', 'actions/node-versions', '.github/workflows/validate.yml', 'uses-with']
]) {
  const result = await rule({ manager, depName, packageFile, depType, updateType: 'minor' });
  check(`coordinated Node ${manager}`, [result.groupName, result.allowedVersions], ['Node.js toolchain', '<25']);
}
const ui = await rule({ manager: 'npm', depName: 'axios', packageFile: 'ui/package.json', updateType: 'patch' });
const workflow = await rule({ manager: 'github-actions', depName: 'actions/checkout', depType: 'action', packageFile: '.github/workflows/validate.yml', updateType: 'major' });
check('major dashboard approval', [workflow.dependencyDashboardApproval, workflow.automerge], [true, false]);
check('workflow grouping', workflow.groupName, 'GitHub Actions');
check('UI grouping', ui.groupName, 'UI non-major dependencies');
for (const depName of ['vue', '@carbon/vue', 'vue-router', 'vue-i18n', 'vuex', 'vite', 'eslint', 'eslint-plugin-vue', 'prettier', '@vue/eslint-config-prettier', 'eslint-plugin-prettier']) {
  const major = await rule({ manager: 'npm', depName, packageFile: 'ui/package.json', updateType: 'major' });
  check(`UI major coordinated ${depName}`, [major.groupName, major.dependencyDashboardApproval, major.automerge], ['UI coordinated majors', true, false]);
}
const carbon = await rule({ manager: 'npm', depName: 'carbon-components', packageFile: 'ui/package.json', updateType: 'major' });
check('host Carbon10 compatibility gate', carbon.allowedVersions, '<11');
check('lockfile maintenance enabled', config.lockFileMaintenance.enabled, true);
const current = (await readFile('CATALOG_VERSION', 'utf8')).trim();
const parts = current.split('.').map(Number);
const next = `${parts[0]}.${parts[1]}.${parts[2] + 1}`;
async function bump(name, upgrades, packagePath, artifactPath, expected) {
  const branch = { upgrades, updatedPackageFiles: packagePath ? [{ type: 'addition', path: packagePath, contents: 'test change' }] : [], updatedArtifacts: artifactPath ? [{ type: 'addition', path: artifactPath, contents: 'test artifact' }] : [] };
  await bumpVersions(branch);
  check(name, branch.updatedArtifacts.find(f => f.path === 'CATALOG_VERSION')?.contents.trim() ?? null, expected);
  check(`${name}: no artifact errors`, branch.artifactErrors ?? [], []);
}
await bump('manifest triggers patch bump', [ui], 'ui/package.json', null, next);
await bump('lockfile-only maintenance triggers bump', [await rule({ manager: 'npm', packageFile: 'ui/package.json', updateType: 'lockFileMaintenance' })], null, 'ui/yarn.lock', next);
await bump('mixed group workflow-first triggers bump', [workflow, ui], '.github/workflows/validate.yml', 'ui/yarn.lock', next);
await bump('duplicate bump rules increment once', [ui, ui], 'ui/package.json', null, next);
await bump('workflow-only leaves version unchanged', [workflow], '.github/workflows/validate.yml', null, null);
await bump('no-op leaves version unchanged', [ui], null, null, null);
const runtime = await rule({ manager: 'custom.regex', depName: 'docker.io/adguard/adguardhome', packageFile: 'build-images.sh', updateType: 'digest' });
await bump('runtime digest triggers bump', [runtime], 'build-images.sh', null, next);
check('runtime immutable digest policy', runtime.pinDigests, true);
check('automerge adguard runtime patch', (await rule({ manager: 'custom.regex', packageFile: 'build-images.sh', depName: 'docker.io/adguard/adguardhome', updateType: 'patch' })).automerge, true);
check('no automerge adguard runtime minor', (await rule({ manager: 'custom.regex', packageFile: 'build-images.sh', depName: 'docker.io/adguard/adguardhome', updateType: 'minor' })).automerge !== true, true);
check('automerge CI action minor', (await rule({ manager: 'github-actions', packageFile: '.github/workflows/validate.yml', depName: 'actions/checkout', depType: 'action', updateType: 'minor' })).automerge, true);
check('no automerge UI npm patch', (await rule({ manager: 'npm', packageFile: 'ui/package.json', depName: 'vite', updateType: 'patch' })).automerge !== true, true);
check('no automerge CI action major', (await rule({ manager: 'github-actions', packageFile: '.github/workflows/validate.yml', depName: 'actions/checkout', depType: 'action', updateType: 'major' })).automerge !== true, true);
console.log(`${passed} Renovate behavioral assertions passed`);
