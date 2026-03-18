# Task Handoff: Issue #3 Complete → Issue #4 — Visual Pipeline Progress Stepper on Issue Detail

## Status: Research Complete — Ready for Implementation

---

## Problem Summary

The pipeline panel on `issue_detail.html` only shows `pipeline_stage` as a text badge. There is no horizontal stepper bar showing all 6 pipeline stages with visual distinction for completed (green), active (pulsing cyan), and pending (grey) states.

---

## Current State Analysis

### Template Structure

| Component | File | Status |
|-----------|------|--------|
| Issue detail page | `app/templates/pages/issue_detail.html` | ✅ Exists — right sidebar has `#pipeline-panel` |
| Pipeline panel partial | `app/templates/partials/pipeline_panel.html` | ✅ Exists — only shows badge, no stepper |
| Partials directory | `app/templates/partials/` | ✅ Exists — drop new file here |
| `pipeline_stepper.html` partial | `app/templates/partials/pipeline_stepper.html` | ❌ Does NOT exist yet |

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

**Stage-to-display-label mapping** (STAGE_ORDER key → UI label per issue spec):

| STAGE_ORDER key | Display Label | Agent |
|----------------|---------------|-------|
| `plan` | Research | Charlie |
| `researched` | Plan | Peter |
| `planned` | Code | David |
| `coded` | Test | Tina |
| `tested` | Review | Suzy |
| `reviewed` | Release | Matthews |
| `completed` | (all done) | — |

### HTMX Refresh Pattern (existing)

`issue_detail.html` line 32–34:
```html
<div class="w-80 shrink-0" id="pipeline-panel" hx-get="/api/pipeline/{{ issue.id }}/status" hx-trigger="every 10s">
  {% include "partials/pipeline_panel.html" %}
</div>
```

**Note:** `/api/pipeline/{issue_id}/status` returns **JSON** (not HTML), so the `hx-get` auto-refresh on `#pipeline-panel` produces raw JSON in the div — this is an existing bug. The actual HTML updates come from button form submissions inside `pipeline_panel.html` that target `#pipeline-panel` with `hx-swap="innerHTML"`.

The stepper needs its **own HTMX refresh endpoint** returning an HTML partial.

### Template Context Variables

The `issue_detail` route (`app/routers/pages.py` line 132–152) passes:
- `issue` — full Issue model with `pipeline_stage`, `pipeline_mode`, `pipeline_waiting`
- `comments` — list of ImportedComment
- `stage_agent_name` — the `STAGE_AGENT_NAME` dict

The stepper partial receives the same `issue` object (Jinja `{% include %}` shares context).

### Design System (from `app/templates/base.html`)

Custom Tailwind colors available:
- Success/completed: `text-success` (`#3fb950`), `bg-success/20`
- Active/primary: `text-primary` (`#2f81f7`), `bg-primary`
- Pending/muted: `text-text-muted` (`#7d8590`), `bg-bg-alt` (`#161b22`)
- Border: `border-border` (`#30363d`)

Custom CSS animations already defined in `base.html`:
- `.pulse-dot` keyframe animation
- `animate-pulse` — Tailwind built-in works (CDN includes it)

---

## Implementation Plan

### Step 1: Create `app/templates/partials/pipeline_stepper.html`

Six connected steps, horizontal layout, using Tailwind + Jinja logic:

```html
{% set stages = [
  ('plan', 'Research'),
  ('researched', 'Plan'),
  ('planned', 'Code'),
  ('coded', 'Test'),
  ('tested', 'Review'),
  ('reviewed', 'Release')
] %}

{# Determine current stage index (-1 = not started, 6 = completed) #}
{% set ns = namespace(current_idx=-1) %}
{% if issue.pipeline_stage == 'completed' %}
  {% set ns.current_idx = 6 %}
{% else %}
  {% for stage_key, label in stages %}
    {% if stage_key == issue.pipeline_stage %}
      {% set ns.current_idx = loop.index0 %}
    {% endif %}
  {% endfor %}
{% endif %}

<div class="flex items-center w-full py-3 px-1">
  {% for stage_key, label in stages %}
    {% set i = loop.index0 %}
    {% set is_done = (ns.current_idx > i) or (ns.current_idx == 6) %}
    {% set is_active = ns.current_idx == i %}
    {% set is_pending = ns.current_idx < i and ns.current_idx != 6 %}

    {# Step circle #}
    <div class="flex flex-col items-center relative">
      <div class="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold border-2
        {% if is_done %}border-success bg-success/20 text-success
        {% elif is_active %}border-primary bg-primary/20 text-primary animate-pulse
        {% else %}border-border bg-bg-alt text-text-muted{% endif %}">
        {% if is_done %}✓{% else %}{{ loop.index }}{% endif %}
      </div>
      <span class="text-[9px] mt-1 font-medium
        {% if is_done %}text-success
        {% elif is_active %}text-primary
        {% else %}text-text-muted{% endif %}">
        {{ label }}
      </span>
    </div>

    {# Connector line (not after last step) #}
    {% if not loop.last %}
    <div class="flex-1 h-[2px] mx-1 mb-3
      {% if is_done %}bg-success/60
      {% elif is_active %}bg-primary/40
      {% else %}bg-border{% endif %}">
    </div>
    {% endif %}
  {% endfor %}
</div>
```

### Step 2: Add new HTMX endpoint for stepper HTML

In `app/routers/pipeline.py`, add:

```python
@router.get("/{issue_id}/stepper")
async def pipeline_stepper(request: Request, issue_id: str, db: AsyncSession = Depends(get_db)):
    issue = await db.get(Issue, issue_id)
    if not issue:
        return HTMLResponse("")
    return request.app.state.templates.TemplateResponse("partials/pipeline_stepper.html", {
        "request": request,
        "issue": issue,
    })
```

### Step 3: Include stepper in `issue_detail.html` above the pipeline panel

Replace the right sidebar block (lines 31–34) with:

```html
<!-- Right: Pipeline stepper + panel -->
<div class="w-80 shrink-0 flex flex-col gap-3">
  <!-- Stepper (auto-refreshes every 10s) -->
  <div id="pipeline-stepper"
       hx-get="/api/pipeline/{{ issue.id }}/stepper"
       hx-trigger="load, every 10s"
       hx-swap="outerHTML">
    {% include "partials/pipeline_stepper.html" %}
  </div>

  <!-- Pipeline panel (actions) -->
  <div id="pipeline-panel" hx-get="/api/pipeline/{{ issue.id }}/status" hx-trigger="every 10s">
    {% include "partials/pipeline_panel.html" %}
  </div>
</div>
```

---

## Files to Create/Modify

| File | Action | Details |
|------|--------|---------|
| `app/templates/partials/pipeline_stepper.html` | **Create** | New 6-step stepper partial |
| `app/routers/pipeline.py` | **Edit** | Add `GET /{issue_id}/stepper` HTML endpoint |
| `app/templates/pages/issue_detail.html` | **Edit** | Wrap right sidebar, include stepper above pipeline-panel |

---

## Acceptance Criteria Checklist

| Criteria | Implementation |
|----------|---------------|
| All 6 stages visible as connected steps | ✅ 6-step loop with connector lines |
| Correct visual state: completed (green), active (cyan pulse), pending (grey) | ✅ Jinja conditionals + Tailwind classes |
| Updates when pipeline advances | ✅ HTMX `hx-trigger="every 10s"` on stepper div |

---

## Key Implementation Notes

1. **Jinja namespace trick**: Use `{% set ns = namespace(current_idx=-1) %}` to mutate state inside a for loop — required to find active step index.

2. **`animate-pulse`**: Tailwind CDN includes this utility — safe to use without a build step.

3. **`is_done` when completed**: When `pipeline_stage == 'completed'`, `ns.current_idx = 6` so `is_done` is true for all steps (index 0–5 all satisfy `6 > i`).

4. **Connector line coloring**: Color the connector AFTER a step based on that step's state — so a green step has a green connector leading to the next step.

5. **No model changes needed**: `pipeline_stage` field already exists on the Issue model.

6. **No DB changes needed**: No new migrations required.

---

## Existing Pattern References

- `pipeline_panel.html` — how `issue.pipeline_stage` and `issue.pipeline_mode` are used in templates
- `comments_list.html` + `issue_detail.html` — existing HTMX partial refresh pattern (`hx-trigger="load, every 10s"`, `hx-swap="outerHTML"`)
- `base.html` — custom color tokens (`text-success`, `text-primary`, `border-border`, etc.)
