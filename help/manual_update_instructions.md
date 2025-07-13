# Alliance Selection and Match Prediction Updates

## Summary of Changes Made

1. Updated alliance selection backend in `app/routes/alliances.py`:
   - Added dynamic component metric discovery from game_config
   - Created component_metrics_display string for frontend

2. Updated alliance selection frontend in `app/templates/alliances/index.html`:
   - Replaced hardcoded metric display with dynamic component_metrics_display

3. Updated match prediction backend in `app/utils/analysis.py`:
   - Modified predict_match_outcome to use dynamic total metric ID from config

4. Created reusable include for team metric display:
   - Created `app/templates/matches/includes/team_metric_display.html`

## Remaining Manual Changes Needed

1. Update `app/templates/matches/predict.html`:
   - Replace the hardcoded Auto/Teleop/Endgame sections with the include:
   ```html
   {% include 'matches/includes/team_metric_display.html' %}
   ```

2. Update `app/templates/matches/predict_printable.html`:
   - Replace the hardcoded Auto/Teleop/Endgame sections with the include:
   ```html
   {% include 'matches/includes/team_metric_display.html' %}
   ```

3. Check `app/templates/matches/predict_pdf.html` if it exists and update similarly.

## Notes for Manual Implementation

When replacing hardcoded metrics in templates, look for patterns like this:
```html
<div class="col">
    <div class="small fw-bold">Auto</div>
    <div>{{ team_data.metrics.get('auto_points', 0)|round(1) }} pts</div>
</div>
<div class="col">
    <div class="small fw-bold">Teleop</div>
    <div>{{ team_data.metrics.get('teleop_points', 0)|round(1) }} pts</div>
</div>
<div class="col">
    <div class="small fw-bold">Endgame</div>
    <div>{{ team_data.metrics.get('endgame_points', 0)|round(1) }} pts</div>
</div>
```

And replace with:
```html
{% include 'matches/includes/team_metric_display.html' %}
```

Also make sure any conditions checking for these specific metrics (like `metric.id not in ['auto_points', 'teleop_points', 'endgame_points']`) are updated to exclude component metrics: 
```html
{% if not metric.is_total_component %}
```
