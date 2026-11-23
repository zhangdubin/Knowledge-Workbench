# Daily workspace experience

Approved context: on 2026-11-22 the user approved the dynamic ontology design and asked to reduce front-end module overload and modernize daily usage. This implementation is the first UI delivery; it must not claim the ontology backend is already implemented.

Default primary navigation has at most five entries: 工作台 `/`, 资料库 `/library`, 知识笔记 `/notes`, 知识图谱 `/knowledge/graph`, 业务应用 `/apps`. Respect existing permissions; use `/graph` as graph fallback when knowledge graph is forbidden but business graph is allowed. At most three custom shortcuts appear separately. All old authorized tools and custom links remain reachable through searchable 全部功能. Desktop, mobile, command menu and catalog use one permission-filtered catalog.

Header: command search, a visible text AI 助手 button, theme and user menu. Cmd/Ctrl+K opens a keyboard-operable command menu with navigation and existing content-search handoff. System and advanced tools are progressively disclosed, never silently removed.

Home: a quiet task-first question composer headed 今天，想了解什么？, explicit assistant submit, two direct actions 导入资料 and 写笔记, real recent-content and recent-files lists. Avoid marketing heroes, rainbow stats, repeated module tiles and implementation terminology. Show truthful loading, empty, partial-error and retry states. Fetch only authorized sections. AI-unavailable users can still search. An explicitly submitted question reaches the existing assistant once; unconfigured AI remains clearly unconfigured.

Visual direction: existing fonts and muted indigo accent, soft neutral sidebar, fine borders, restrained shadows, spacious readable rows. No new raster artwork is required. Adapt existing Element Plus icons and CSS tokens. Support light/dark, normal 1280x720 desktop and 390x844 mobile with no horizontal overflow. Mobile navigation is a drawer. Every interactive action has a meaningful accessible name and keyboard operation.

References: Notion sidebar guidance https://www.notion.com/help/navigate-with-the-sidebar ; Nielsen Norman Group progressive disclosure https://www.nngroup.com/articles/progressive-disclosure/ ; Linear search https://linear.app/docs/search . These inform patterns, not a faithful clone.

Retain Vue3, Vite6 and Element Plus. Add no runtime dependencies. Preserve old routes, authentication, user-custom navigation, roles, version refresh, theme and assistant confirmation/continuation behavior. Do not modify backend or production configuration. Preview backend binds 127.0.0.1:8002 and uses a disposable copy of the verified backup.

Navigation helpers must match path segments, not unsafe prefix strings. All consumers receive filtered entries. Existing mergeNavGroups remains supported. Tests must cover permission and discoverability regressions, not colors or arbitrary source strings.

The home communicates with Layout through shared useWorkspaceActions state. Layout owns overlay rendering. AgentChat accepts initialQuestion and handles explicit home submission once, without losing a new question if already busy. No auto-send based on URL or local storage.

Acceptance: five or fewer primaries, every authorized legacy route in catalog, keyboard command search and content search work, home question transfers, real recent links work, no inaccessible API calls for restricted sections, mobile and dark mode verified, npm test/build pass, original production stays healthy.
