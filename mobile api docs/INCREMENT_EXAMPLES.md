# Increment Examples for Counters 🔧

This file shows example JSON snippets and expected behavior for `step`, `alt_step`, and `alt_step_enabled` when using counters in the game config.

## Fields recap
- `step` (number): primary increment amount (default: 1).
- `alt_step` (number): secondary increment amount (optional, e.g., 5 or 10).
- `alt_step_enabled` (boolean): whether to expose the `alt_step` controls to users.

---

## Example: simple +1 counter (no alt)
JSON:

```
{
  "id": "elem_auto_0",
  "name": "Cargo Scored",
  "type": "counter",
  "default": 0,
  "points": 1,
  "step": 1
}
```

Client behavior:
- Render `-1` and `+1` buttons (or a single ± control with step=1).
- No alt ± buttons shown.

---

## Example: counter with alt step of 5
JSON:

```
{
  "id": "elem_teleop_1",
  "name": "Cargo Scored",
  "type": "counter",
  "default": 0,
  "points": 1,
  "step": 1,
  "alt_step": 5,
  "alt_step_enabled": true
}
```

Client behavior:
- Render: `-1` (primary decrement), `-5` (alt decrement), [numeric input], `+5` (alt increment), `+1` (primary increment).
- Buttons use each button's `data-step` attribute so pressing the alt button changes the value by `alt_step`.

Notes:
- The server and payloads will include `alt_step` only when configured. When `alt_step_enabled` is true but `alt_step` is missing or blank, clients should default the alt-step to the primary `step` value.
- In some editors (the simple editor), the client serializes a `simple_payload` JSON that includes these fields; the server expects them there and will persist them into the saved game config.

---

## Best practices
- Always set `alt_step` when enabling `alt_step_enabled` so clients can render explicit labels (e.g., `+5`).
- Keep `step` and `alt_step` sensible (positive integers).
- If you want the alt button to be bigger (e.g., +10), set `alt_step` to 10 and `alt_step_enabled` to true.

If you want a sample payload (client `simple_payload`) saved to the server, enable the alt step in the simple editor and inspect the `simple_payload` JSON that is submitted — it will include the element objects with `step`, `alt_step_enabled` and `alt_step` fields.
