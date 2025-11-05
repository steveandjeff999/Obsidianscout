import os
import sys
sys.path.insert(0, os.path.abspath('.'))

import json
from app.utils.config_manager import load_game_config

gc = load_game_config(team_number=5454)
print('Endgame:')
print(json.dumps(gc.get('endgame_period', {}), indent=2))

print('\nKey metrics:')
print(json.dumps(gc.get('data_analysis', {}).get('key_metrics', []), indent=2))