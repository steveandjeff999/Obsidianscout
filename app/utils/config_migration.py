import copy
import json
from flask import current_app
from app.models import ScoutingData

def _gather_elements_by_period(cfg):
    by_period = {}
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        elems = cfg.get(period, {}).get('scoring_elements', [])
        by_period[period] = [e for e in elems]
    return by_period

def compute_mapping_suggestions(old_cfg, new_cfg):
    """Compute suggested mapping between old and new configs' scoring elements.

    Returns a dict mapping period -> list of mapping objects:
        { 'period': [ { 'old': {id,name,perm_id}, 'suggested_new_id': '...', 'suggestions': [{'id', 'name'}...] } ] }
    """
    results = {}
    old_periods = _gather_elements_by_period(old_cfg or {})
    new_periods = _gather_elements_by_period(new_cfg or {})

    # Build a global list of new elements across all periods and any legacy top-level
    new_all = []
    for p in ['auto_period', 'teleop_period', 'endgame_period']:
        new_all.extend(new_periods.get(p, []))
    # Legacy top-level 'scoring_elements' fallback
    for el in new_cfg.get('scoring_elements', []) if isinstance(new_cfg, dict) else []:
        new_all.append(el)

    # Deduplicate new_all by id keeping first occurrence
    seen = set()
    deduped_new_all = []
    for el in new_all:
        if not isinstance(el, dict):
            continue
        eid = el.get('id')
        if eid and eid not in seen:
            seen.add(eid)
            deduped_new_all.append(el)

    for period, old_elems in old_periods.items():
        # Prefer new elements from the same period, but include others as secondary suggestions
        new_elems_same = new_periods.get(period, [])
        # Build a fallback list merging same-period first then the rest
        new_elems = list(new_elems_same) + [e for e in deduped_new_all if e not in new_elems_same]
        suggestions = []
        # Build lookups for suggestions
        new_by_id = {e.get('id'): e for e in new_elems}
        new_by_perm = {e.get('perm_id'): e for e in new_elems if e.get('perm_id')}
        new_by_name = {e.get('name'): e for e in new_elems if e.get('name')}

        for old in old_elems:
            suggested = None
            # Prefer perm_id matches
            if old.get('perm_id') and old.get('perm_id') in new_by_perm:
                suggested = new_by_perm[old.get('perm_id')]['id']
            # exact id match
            elif old.get('id') in new_by_id:
                suggested = old.get('id')
            # name match
            elif old.get('name') and old.get('name') in new_by_name:
                suggested = new_by_name[old.get('name')]['id']

            # Build list of possible choices (same-period first, then others)
            suggestion_list = [{'id': e.get('id'), 'name': e.get('name')} for e in new_elems]

            suggestions.append({
                'old': { 'id': old.get('id'), 'name': old.get('name'), 'perm_id': old.get('perm_id') },
                'suggested_new_id': suggested,
                'suggestions': suggestion_list
            })
        results[period] = suggestions

    return results

def apply_mapping(mapping, team_number=None, alliance_id=None, new_config=None, dry_run=False):
    """Apply a mapping of old_id -> new_id to the database. Returns a dict with counts.

    Mapping format expected: { 'old_id': 'new_id', ... }
    If team_number provided, only ScoutingData for that team will be migrated.
    """
    # Validate mapping
    try:
        if not mapping or not isinstance(mapping, dict):
            return { 'success': False, 'message': 'No mapping provided', 'updated': 0 }

        # Query scouting data
        q = ScoutingData.query
        if team_number:
            q = q.filter_by(scouting_team_number=team_number)
        # If alliance_id provided, restrict to teams that are members of the alliance
        if alliance_id:
            try:
                from app.models import ScoutingAllianceMember, Team
                member_teams = [m.team_number for m in ScoutingAllianceMember.query.filter_by(alliance_id=alliance_id, status='accepted').all()]
                if member_teams:
                    q = q.join(Team, ScoutingData.team).filter(Team.team_number.in_(member_teams))
                else:
                    # no teams, no entries
                    q = q.filter(False)
            except Exception:
                pass

        entries = q.all()
        updated_count = 0
        affected_entries = []
        # Build a config lookup to map new IDs to perm_id when available
        from app.utils.config_manager import get_current_game_config
        cfg = new_config or get_current_game_config() or {}
        period_lookup = {}
        for period in ['auto_period', 'teleop_period', 'endgame_period']:
            for e in cfg.get(period, {}).get('scoring_elements', []):
                period_lookup[e.get('id')] = e

        for entry in entries:
            data = entry.data
            changed = False
            for old_k, v in mapping.items():
                # mapping[v] may be either a direct id (legacy) or a dict with new_id and old_perm_id
                if isinstance(v, dict):
                    new_k = v.get('new_id')
                    old_perm_k = v.get('old_perm_id')
                else:
                    new_k = v
                    old_perm_k = None

                # Check either the old key or the old perm key in the data
                found_key = None
                if old_k in data:
                    found_key = old_k
                elif old_perm_k and old_perm_k in data:
                    found_key = old_perm_k
                if not found_key:
                    continue
                # Don't overwrite existing new_k unless it's empty
                new_key = new_k
                # If new_k exists in the config and defines a perm_id, prefer storing under perm_id
                try:
                    new_elem = period_lookup.get(new_k)
                    if new_elem and new_elem.get('perm_id'):
                        new_key = new_elem.get('perm_id')
                except Exception:
                    pass
                if new_key in data and data.get(new_key) not in [None, '', 0, False]:
                    # skip overwriting to avoid data loss
                    continue
                # Move value from old key to new key
                try:
                    data[new_key] = data.pop(found_key)
                    try:
                        current_app.logger.debug(f"Migrated key {found_key} -> {new_key} for ScoutingData id={entry.id} team={entry.team_id}")
                    except Exception:
                        pass
                except KeyError:
                    continue
                changed = True
            if changed:
                entry.data = data
                updated_count += 1
                # Record a lightweight sample of the updated entry for preview purposes
                try:
                    team_num = getattr(entry, 'team', None)
                    team_num = team_num.team_number if team_num else entry.team_id
                except Exception:
                    team_num = entry.team_id if hasattr(entry, 'team_id') else None
                affected_entries.append({ 'id': getattr(entry, 'id', None), 'team': team_num })

        if updated_count and not dry_run:
            from app import db
            db.session.commit()
        result = { 'success': True, 'updated': updated_count }
        if dry_run:
            # return a small sample of affected entries for preview (max 10 entries)
            result['sample'] = affected_entries[:10]
        return result
    except Exception as e:
        current_app.logger.exception('apply_mapping error')
        return { 'success': False, 'message': str(e), 'updated': 0 }
