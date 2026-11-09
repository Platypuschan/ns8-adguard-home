# Module-local NS8 bridge

GPL-3.0-or-later port of the consumed @nethserver/ns8-ui-lib 2.1.0 APIs and
components (Nethesis S.r.l.). The upstream package requires Vue 2 and is not
retained as a Vue 3 plugin. This is not a general UI-library replacement.

See [migration/disposition and verification](../../../docs/ui-migration.md).
Keep transport/auth/payload/event contracts unchanged. The parent core is a
foreign Vue 2 object and must remain markRaw. Only iframe-local events use
`events.js`; tasks remain on the parent's actual event bus.
