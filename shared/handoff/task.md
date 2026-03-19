# Task Handoff: Issue #4 — Visual Pipeline Progress Stepper on Issue Detail

## Status: RESEARCH COMPLETE — 2026-03-19

---

## Problem Summary

The pipeline panel on `issue_detail.html` only shows `pipeline_stage` as a text badge. There is no horizontal stepper bar showing all 6 pipeline stages with visual distinction for completed (green), active (pulsing cyan), and pending (grey) states.

---

## Current State Analysis

### Implementation Status

| Component | File | Status |
|-----------|------|--------|
| Issue detail page | `app/templates/pages/issue_detail.html` | ✅ Exists — right sidebar has `#pipeline-panel` with 10s HTMX refresh |
| Pipeline panel partial | `app/templates/partials/pipeline_panel.html` | ✅ Modified — includes `pipeline_stepper.html` at top |
| Pipeline stepper partial | `app/templates/partials/pipeline_stepper.html` | ✅ Created — full 6-step horizontal stepper |
| Pipeline router | `app/routers/pipeline.py` | ✅ Has `/panel` GET endpoint for HTMX refresh |

### Pipeline Stage Definition (from `app/agents/pipeline.py`)

```python
STAGE_ORDER = ["plan", "researched", "planned", "coded", "tested", "reviewed"]

STAGE_AGENT_NAME = {
    "plan": "Charlie (Research)",
    "researched": "Peter Plan (Architecture)",
    "planned": "David Dev (Coding)",
    "coded": "Tina (Testing)",
    "tested": "Suzy (Review)",
    "reviewed": "Matthews (Merge)",
}
```

**Stage-to-display-label mapping:**

| STAGE_ORDER key | Display Label | Agent |
|----------------|---------------|-------|
| `plan` | Research | Charlie |
| `researched` | Plan | Peter |
| `planned` | Code | David |
| `coded` | Test | Tina |
| `tested` | Review | Suzy |
| `reviewed` | Release | Matthews |
| `completed` | (all done — all steps green) | — |

### HTMX Refresh Pattern

`issue_detail.html` lines 32–37:
```html
<div class="w-80 shrink-0 flex flex-col gap-0" id="pipeline-panel"
     hx-get="/api/pipeline/{{ issue.id }}/panel"
     hx-trigger="every 10s"
     hx-swap="innerHTML">
  {% include "partials/pipeline_panel.html" %}
</div>
```

The stepper is embedded inside `pipeline_panel.html` via `{% include "partials/pipeline_stepper.html" %}` at line 1, so it refreshes automatically when the panel refreshes — no separate endpoint needed.

### Stepper Logic (`pipeline_stepper.html`)

```jinja
{% set stage_to_idx = {"plan": 0, "researched": 1, "planned": 2, "coded": 3, "tested": 4, "reviewed": 5} %}
{%- if issue.pipeline_stage == "completed" -%}
  {%- set current_idx = 6 -%}
{%- elif issue.pipeline_stage and issue.pipeline_stage in stage_to_idx -%}
  {%- set current_idx = stage_to_idx[issue.pipeline_stage] -%}
{%- else -%}
  {%- set current_idx = -1 -%}
{%- endif -%}
```

Step state logic:
- `state == "completed"` → `current_idx >= 6 or step.idx < current_idx`
- `state == "active"` → `step.idx == current_idx`
- `state == "pending"` → default

Visual classes:
- Completed: `bg-success text-white` + checkmark `✓`
- Active: `bg-primary text-white stepper-active` (custom `@keyframes stepper-pulse` CSS animation)
- Pending: `bg-bg-alt border border-border text-text-muted`

Connector lines between steps color based on following step's state:
- Left connector green when `step.idx <= current_idx`
- Right connector green when `step.idx < current_idx`

### Design System (from `app/templates/base.html`)

Custom Tailwind colors:
- Success/completed: `text-success` (`#3fb950`), `bg-success`
- Active/primary: `text-primary` (`#2f81f7`), `bg-primary`
- Pending/muted: `text-text-muted` (`#7d8590`), `bg-bg-alt` (`#161b22`)
- Border: `border-border` (`#30363d`)

HTMX version: `htmx.org@2.0.4` loaded from CDN.

---

## Implementation Summary

### Files Modified/Created

| File | Action | Change |
|------|--------|--------|
| `app/templates/partials/pipeline_stepper.html` | **Created** | New 6-step horizontal stepper partial with Jinja state logic and CSS pulse animation |
| `app/templates/partials/pipeline_panel.html` | **Modified** | Added `{% include "partials/pipeline_stepper.html" %}` at line 1 |
| `app/templates/pages/issue_detail.html` | **Modified** | Pipeline panel div now uses `hx-get="/api/pipeline/{{ issue.id }}/panel"` (returns HTML, not JSON) |
| `app/routers/pipeline.py` | **Modified** | `/panel` GET endpoint confirmed for HTMX HTML partial refresh |

---

## Acceptance Criteria

| Criteria | Status |
|----------|--------|
| All 6 stages visible as connected steps | ✅ 6-step loop with connector lines between each |
| Completed stages highlighted green | ✅ `bg-success text-white` + checkmark icon |
| Active stage pulsing cyan | ✅ `bg-primary text-white` + `stepper-pulse` CSS animation |
| Pending stages grey | ✅ `bg-bg-alt border border-border text-text-muted` |
| Updates when pipeline advances | ✅ Included in pipeline_panel which refreshes every 10s via HTMX |

---

## Key Implementation Notes

1. **Stepper embedded in panel**: Rather than a separate HTMX endpoint, the stepper is `{% include %}`d inside `pipeline_panel.html`. This means it refreshes whenever the panel refreshes via `hx-get="/api/pipeline/{issue_id}/panel"` — simpler, no extra endpoint needed.

2. **Stage index mapping**: Uses a static dict `stage_to_idx` (not namespace loop) to map stage key → integer index. `current_idx = 6` when `completed` so all steps show green.

3. **Custom CSS animation**: `@keyframes stepper-pulse` is defined inline in the stepper template itself (not base.html) — box-shadow pulse on active step.

4. **Connector line coloring**: Left connector of a step turns green when `step.idx <= current_idx` (step and all predecessors done). Right connector turns green when `step.idx < current_idx`.

5. **No model changes**: `pipeline_stage` field already exists on the Issue model. No migrations required.
