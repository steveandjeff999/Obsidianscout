import os
import sys
import json
from app import create_app, db
from app.models import ScoutingData
from app.utils.config_manager import ConfigManager

app = create_app()

# Build a mapping from perm_id to id for all scoring elements
with app.app_context():
    config_manager = ConfigManager()
    game_config = config_manager.game_config
    perm_to_id = {}
    for period in ['auto_period', 'teleop_period', 'endgame_period']:
        if period in game_config:
            for element in game_config[period].get('scoring_elements', []):
                perm_id = element.get('perm_id')
                id_ = element.get('id')
                if perm_id and perm_id != id_:
                    perm_to_id[perm_id] = id_

    print(f"Perm-to-ID mapping: {perm_to_id}")

    # Query all scouting data
    all_data = ScoutingData.query.all()
    updated = 0
    for entry in all_data:
        data = entry.data
        changed = False
        # For each perm_id in the mapping, if present in data, move to id
        for perm_id, id_ in perm_to_id.items():
            if perm_id in data:
                data[id_] = data.pop(perm_id)
                changed = True
        if changed:
            entry.data = data
            updated += 1
    if updated:
        db.session.commit()
    print(f"Updated {updated} ScoutingData entries.") 