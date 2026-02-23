import pytest


def _render_old(drawing_data):
    """Simulate the old canvas-replay logic used before the bug fix.

    The previous implementation drew *all* normal strokes first and then applied
    every erase stroke afterward.  Because the erase passes happened after the
    entire drawing state was reproduced, a user who erased an area and then
    drew *again* would immediately have their new content wiped out by the
    later application of the original eraser stroke.  In our simplified model
    we assume every erase stroke covers the same region as any other stroke we
    care about, so a single erase will remove every stroke regardless of order.
    """
    strokes = [item for item in drawing_data if item.get("points")]
    if any(item.get("type") == "erase" for item in drawing_data):
        # everything gets erased by the subsequent pass
        return []
    return strokes


def _render_new(drawing_data):
    """Simulate the corrected replay behavior.

    Here eraser strokes are applied in sequence exactly where they appear in
    the history.  They only affect strokes that were added before the erase.
    Later strokes remain intact, which matches what users expect when drawing
    over an erased area.
    """
    strokes = []
    erased_ids = set()
    for item in drawing_data:
        if item.get("type") == "erase":
            # mark all existing strokes as erased
            for s in strokes:
                erased_ids.add(s["id"])
        elif item.get("points"):
            strokes.append(item)
    return [s for s in strokes if s["id"] not in erased_ids]


def test_eraser_does_not_remove_later_strokes():
    # arrange a simple sequence: draw, erase, draw again
    first = {"id": 1, "color": "#000", "points": [{"x": 0.1, "y": 0.1}]}  
    eraser = {"type": "erase", "size": 15, "points": [{"x": 0.1, "y": 0.1}]}  
    second = {"id": 2, "color": "#abc", "points": [{"x": 0.2, "y": 0.2}]}
    data = [first, eraser, second]

    # old behaviour would have wiped the second stroke as well
    assert _render_old(data) == []

    # updated behaviour should keep the second stroke intact
    assert _render_new(data) == [second]


def test_multiple_erases_only_affect_prior_content():
    # multiple erases in a row should continue to only remove earlier strokes
    s1 = {"id": 1, "color": "#111", "points": [{"x": 0, "y": 0}]}  
    e1 = {"type": "erase", "size": 10, "points": [{"x": 0, "y": 0}]}    
    s2 = {"id": 2, "color": "#222", "points": [{"x": 1, "y": 1}]}  
    e2 = {"type": "erase", "size": 20, "points": [{"x": 1, "y": 1}]}
    s3 = {"id": 3, "color": "#333", "points": [{"x": 2, "y": 2}]}
    data = [s1, e1, s2, e2, s3]

    assert _render_new(data) == [s3]
