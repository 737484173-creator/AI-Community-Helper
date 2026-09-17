# AIDC Workbench UI System

## Redesign brief

- Mode: Redesign · Preserve.
- Preserve: navigation labels and groups, page hierarchy, form fields, status values, data tables, actions, session-state keys, and all backend behavior.
- Improve: visual hierarchy, density, spacing rhythm, control states, responsive navigation, keyboard focus, dialogs, empty states, and motion consistency.
- Remove: duplicate cascade layers, excessive glass blur, decorative controls that look clickable, empty HTML wrapper shells, and non-semantic card hover effects.
- Highest-risk change: global Streamlit selector styling. Keep selectors scoped to stable `data-testid`, BaseWeb roles, and named container keys.
- Fallback: presentation remains usable with plain Streamlit styling if a future Streamlit release changes a selector; no business path depends on CSS.

## Design read

- Artifact: high-density Discord community operations dashboard.
- Audience: community operators who scan state, filter queues, and complete actions on desktop, with mobile access for urgent checks.
- Visual language: quiet operational tool — neutral canvas, crisp white surfaces, navy typography, a single cobalt action color, restrained semantic color.
- Dials: visual variance 4/10; motion 3/10; information density 8/10; asset dependence 1/10; brand fidelity 9/10.

## Tokens

- Spacing: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 48.
- Radius: 8 for compact elements, 10 for controls, 14 for cards, 16 for structural panels, 18 for dialogs, full pill only for statuses.
- Shadows: level 1 for rare raised surfaces, level 2 for dropdowns/hover, level 3 for dialogs. Borders and whitespace carry most hierarchy.
- Motion: 140ms press, 180ms hover/state, 280ms restrained entrance; `cubic-bezier(.2,.8,.2,1)`; no large travel, bounce, or loop.
- Typography: Segoe UI Variable / PingFang SC / Microsoft YaHei for an OS-native operations feel; tabular numerals for metrics.

## Responsive contract

- Desktop: fixed 248px navigation rail and a content canvas capped at 1320px.
- Tablet: denser grids collapse without horizontal page overflow.
- Mobile: Streamlit's navigation drawer trigger remains reachable; page headers and command-bar controls stack; controls use at least 44px touch targets; wide data grids remain internally scrollable.

