# Workspace Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Reduce daily navigation overhead while retaining all authorized functionality.

**Architecture:** One permission-filtered navigation catalog powers the sidebar, catalog and command menu. A task-first home uses existing APIs and shared workspace action state to open the existing AI assistant.

**Tech Stack:** Vue 3, Vite 6, Element Plus, existing CSS tokens; no new runtime dependencies.

**Spec:** docs/superpowers/specs/2026-11-22-workspace-experience.md

## Global Constraints

- Work only in this isolated worktree; do not modify the original checkout or production data.
- At most 5 primary destinations and 3 custom shortcuts; all other authorized functionality remains in the searchable catalog.
- Preserve existing routes, authentication, custom navigation, permission and feature gates.
- Existing design tokens, light/dark and 390px responsive layout; no new runtime dependencies.
- No backend, credential, production deployment or data changes in this batch.
- Do not present legacy data models as a completed dynamic ontology engine.

### Task 1: Implement the daily shell and task-first home

**Files:**

- Create `frontend/src/utils/workspaceNavigation.js`: single built-in catalog and pure navigation/search helpers.
- Create `frontend/src/composables/useWorkspaceActions.js`: shared overlay and assistant prompt refs.
- Create `frontend/src/components/workspace/WorkspaceNavigation.vue`: common desktop/mobile navigation.
- Create `frontend/src/components/workspace/WorkspaceCommandMenu.vue`: keyboard commands and content search.
- Create `frontend/src/components/workspace/WorkspaceCatalog.vue`: grouped searchable all-tools overlay.
- Modify `frontend/src/components/Layout.vue`: integrate compact shell, retain auth/version/theme/mobile behavior; remove replaced obsolete shell code.
- Modify `frontend/src/components/AgentChat.vue`: initial question handoff, preserve confirmation and continuation.
- Replace `frontend/src/views/Dashboard.vue`: question composer, direct actions, real recent content/files, partial error/empty/loading states.
- Modify `frontend/src/composables/useNavItems.js` for complete, segment-safe permission mapping while preserving mergeNavGroups contract.
- Create `frontend/tests/workspace-navigation.test.mjs`; add it to package.json test script. Adjust obsolete visual-structure assertions only where necessary, preserving their behavioral intent.
- Optional small focused components under `components/workspace/` may split home sections; avoid large new monoliths.

**Interfaces:**

- `getWorkspaceNavigation({canPage, canFeature, customItems})` returns `{primary, shortcuts, groups}`. Items: `{path,label,icon,description,perm,feature?}`.
- `searchWorkspaceCommands(groups, query)` returns permission-filtered item[] matching trimmed case-insensitive label/description/path.
- `activeWorkspacePath(path, primary)` returns the matching primary path or empty string, with full segment matching.
- `useWorkspaceActions()` returns shared refs `commandOpen,catalogOpen,assistantOpen,assistantQuestion` and `openAssistant(question='')`. Layout renders AgentChat; home invokes this action.

- [ ] Step 1: Add behavioral navigation tests before implementation; run `node tests/workspace-navigation.test.mjs` and record RED. Cover all old built-in routes in catalog, max five primaries, restricted users cannot see system/controlled custom routes, DNA permission mapping, fake prefix paths, duplicate custom paths, trimmed Chinese search, nested active state and no active match.

```js
const nav = getWorkspaceNavigation({canPage: p => p === 'notes', canFeature: () => false, customItems: []})
assert.deepEqual(nav.primary.map(i => i.path), ['/notes'])
assert.equal(activeWorkspacePath('/notes/12', nav.primary), '/notes')
assert.equal(activeWorkspacePath('/notes-fake', nav.primary), '')
```

- [ ] Step 2: Implement catalog from existing Layout NAV exact paths and gates. Filter before exposing entries to consumers, deduplicate custom paths, use full-segment matching, preserve all built-in tools in catalog. Commands search data from this same catalog.
- [ ] Step 3: Implement reusable navigation and overlays with semantic buttons/links. Command menu input needs accessible name, up/down selection, Enter, Escape, focus management and empty states. Typed text supports existing `/search?kw=...` content search. Mobile closes navigation on selection. Header clearly identifies advanced routes.
- [ ] Step 4: Integrate Layout and replace home. Use existing getStats recent data and document-list API, gated by actual page permissions and independently handled. Recent item links use real IDs and proper routes. Add per-section retry/empty/loading. Avoid duplicate module grids and fabricated counters. When AI permission is absent, input can search instead of offering dead AI behavior.
- [ ] Step 5: Explicit home question submission opens AgentChat with that question once. Preserve onOpen config load and input/confirmation/continuation. Busy assistant must not lose a newly submitted question. Unconfigured AI shows real status and never a fabricated successful answer.
- [ ] Step 6: Run focused navigation tests, original `npm test`, `npm run build`. Fix real regressions. Update tests that demand intentionally removed visual scaffolding instead of deleting meaningful coverage. Do not test colors or spacing.
- [ ] Step 7: Self-review permission, legacy route reachability, keyboard, route single-root and cleanup. Commit only owned frontend files. Write report with test commands, RED/GREEN evidence, files changed and concerns to the designated report file.

### Task 2: Browser acceptance and delivery (controller)

**Files:** `docs/frontend-workspace-redesign.md`; screenshots and evidence under the existing project-research/frontend-redesign directory.

- [ ] Verify primary entry count and catalog reachability at normal desktop viewport.
- [ ] Verify Cmd/Ctrl+K, arrows/Enter/Escape, content search and assistant prompt/no-config state.
- [ ] Verify notes/files navigation, an advanced tool, custom links, mobile 390x844, dark mode and console errors through CUA; save evidence screenshots.
- [ ] Build and start a separate loopback production-build frontend preview, preserving original containers and data.
- [ ] Complete task review and whole-branch review, resolve relevant findings, rerun covering checks and present an honest scope status and working URL.
