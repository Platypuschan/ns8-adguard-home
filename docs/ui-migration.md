# Coordinated Vue 3 migration

## Scope and disposition of the original proposals

This branch replaces the Vue 2 application runtime, not the NS8 host. The existing
Settings, Status and About views, module/cluster actions, metadata and EN/DE
messages are retained. No module backend/settings schema changes are required.
No old PR is merged or closed by this branch.

| Original PR | Proposal | Disposition in this candidate |
|---|---|---|
| #12 | Babel 8 | Removed direct Babel core/parser. There is no Babel transform or syntax requiring it; Vite 8 compiles the application and ESLint 10 uses its native parser through vue-eslint-parser 10. Transitive Babel parser packages are not application Babel plugins. |
| #13 | Carbon Vue 3 | Adopted `@carbon/vue` 3.0.32; only consumed native Vue 3 components are registered. |
| #14 | Vue ESLint/Prettier config 10 | Adopted 10.2.0 flat config. |
| #15 | carbon-components 11 | **Blocked, not silently adopted.** Carbon Vue 3.0.32 actually depends on carbon-components ^10.58.5 and renders `bx--` markup. The published NS8 host also provides Carbon 10 `core.css`. Carbon 11 changes the Sass layout/API and CSS namespace. Retain explicit 10.59.2 until the host and component library migrate together; Renovate has an explicit `<11` compatibility gate. Carbon 10 is deprecated; this branch does not claim it becomes supported upstream. |
| #16 | ESLint 10 | Adopted 10.14.0 with @eslint/js 10.0.1. |
| #17 | eslint-plugin-prettier 5 | Adopted 5.5.7. |
| #18 | eslint-plugin-vue 10 | Adopted 10.12.0 with vue-eslint-parser 10.4.2. |
| #19 | lottie-web-vue 3 | Removed unused registration/dependency. No view supplies animationData to an empty state; its original static pictogram path remains. No claim to have exercised Lottie. |
| #20 | Prettier 3 | Adopted 3.9.10. |
| #22 | Vite 8 | Adopted 8.1.3 with plugin-vue 6.0.10; installed plugin manifest accepts Vite ^8.0.0. Vue2 plugin removed. |
| #23 | Vue 3 | Adopted 3.5.45; createApp, native Vue3 SFCs, named slots and modelValue bindings. |
| #24 | vue-debounce 6 | Removed unused registration/dependency; no consumed directive or debounce call exists. |
| #25 | vue-i18n 11 | Adopted 11.4.18 composition mode/global injection, EN fallback loaded, empty validation keys avoided, plural calls migrated. The foreign Vue2 host keeps its own `$tc`. |
| #26 | vue-router 5 | Adopted 5.4.0 memory history; parent NS8 hash/router remains authoritative. Sidebar highlighting uses the reactive module route. |
| #27 | Vuex 4 | Adopted 4.1.0; host `core` is explicitly markRaw, not a proxy of a foreign framework. |

#21 (Ubuntu runner) and #28 (Robot browser image) are independent proposals and
are not UI migration claims. Compatible/runtime integration is a separate branch.
This branch's CATALOG_VERSION 0.1.4 is the bump after merging the compatible updates (0.1.3) into main;
the integrator must allocate a fresh version after other source changes merge.

## Why not retain ns8-ui-lib?

The original immutable lock installs @nethserver/ns8-ui-lib 2.1.0. Its actual
manifest requires Vue ^2.6.12, and its compiled ESM imports Carbon Vue2 internal
mixins and uses Vue2 render helpers. Bumping the root Vue package does not port
it. `src/ns8/` is a module-local GPL-3.0-or-later port of the **consumed** bridge
and components, based on the upstream source and reviewed porting patterns:
button, notification, static empty state, info/service/log/backup cards. It is
not a general replacement library and makes no compatibility claim for unused
wizards, modals, animation, clipboard or table plugins.

The unchanged transport contract is real Axios POST to
`parent.core.$root.apiUrl/module/<instance>/tasks` or `/cluster/tasks`, with
Bearer auth read from localStorage.loginInfo and the same action/data/extra
payload. UUIDv4 uses WebCrypto. Host task events retain their exact eventId
suffix and argument ordering, including reversed aborted arguments. Terminal
outcomes release sibling listeners; rejected creation and unmount also clean up.
Delayed/duplicate events cannot refresh a disposed page. Host navigation,
notifications, keyboard-shortcut registration, page titles and metadata links
remain host-owned. Only iframe-local events use the local Vue3 event bus.

## Verification, including limits

Tests run actual production and development bundles inside an iframe, with the
real stylesheet extracted without executing the digest-pinned published NS8 core
image. The core API/event bus/router is explicitly a **fixture**, not a live
cluster. Development tests fail on Vue, router, i18n warnings and page errors;
missing-key warnings are not blanket-disabled. Settings coverage includes all
fields/toggles, credentials/DoH, DNS/node helpers, optional password omission,
72-byte UTF8 limit, indexed validation errors, HTTP denial and aborted tasks.
The original UI has no credential-copy controls; no clipboard coverage is claimed.
All non-submit buttons now explicitly default to button, and Save is submit.
Status/backup coverage includes service/image/volume rows, host links, backup
status ordering and missing statuses. About and parent/menu navigation are covered.

Observed RED before fixes:
- stack test rejected the original Vue ^2.7.0 declaration;
- original built Vue2 UI retained an aborted listener after navigation/completion;
- toolchain tests rejected missing immutable shared builder/real-CSS browser CI;
- native Renovate test rejected separately grouped UI majors;
- development bundle emitted an i18n warning by translating an already formatted
  indexed DNS error; preserve its key/detail until rendering instead;
- native Save had no explicit submit type;
- sidebar stayed highlighted on Status after real parent navigation to Settings.

Production packaging and CI now compile the same `ui/Containerfile --target ui`
with Node 24.22.2-bookworm and project-pinned Yarn 4.18.0. `ui/build.sh` asserts
Yarn equality, installs immutably, lints, checks installed manifests and builds.
The context-free dev stage installs Yarn before the bind mount. Its actual
nonroot build/watch entrypoint and interactive serve are smoke-tested using a
disposable source mount and owned-container cleanup. CI runs these regressions.

`yarn explain peer-requirements` reports no incompatible application peer. The
two remaining unmet requirements are missing Vue declarations in transitive
@vueuse/core 4.11.2 and @vueuse/shared 4.11.2 requested by vue-demi (Carbon's
transitives). Do not suppress them or confuse install success with compatibility;
consumed Carbon components are exercised by both browser modes. Installed
manifests and exact application pins are independently checked.

Before integration, require fresh green existing QEMU install/update legs for
Debian13 and Rocky9 on the exact head, alongside browser/Validate/Renovate jobs.
A local bundle/fixture run is not NS8 lifecycle or real deployed browser acceptance.
No automerge, release dispatch, live deployment or closing of old PRs is authorized.

## Resumed packaging verification

The same-head retry of Publish run 42673262847 reached the real builder and
exposed a rootless overlay packaging regression after the successful UI build:
`buildah mount` was outside a Buildah user namespace. Mount, copy and unmount
now execute together inside `buildah unshare`; the compiled UI and module
contents are otherwise unchanged. A tool-boundary unit fixture reproduces the
namespace denial (RED before the fix) and checks the copied UI contents; it is
not a substitute for actual Buildah packaging or QEMU lifecycle acceptance.
