# Editing Code with Dynamic Config Support

## Overview

This guide explains how to safely edit the codebase while preserving the dynamic configuration system used by ObsidianScout. The dynamic config system allows game rules, scoring elements, and other key settings to be changed without modifying the code, making the app flexible for new games and seasons.

---

## What is the Dynamic Config System?

- **Dynamic config** means that core game logic, scoring elements, and some UI features are defined in JSON files (like `config/game_config.json`) rather than hardcoded in Python.
- The `ConfigManager` class (`app/utils/config_manager.py`) loads and processes these configs at runtime.
- This allows non-developers (admins) to update game rules, scoring, and other settings without touching the code.

---

## Which Files are Safe to Edit?

- **Safe to edit:**
  - Python code in `app/` (routes, models, utils, etc.)
  - HTML templates in `app/templates/`
  - Static assets in `app/static/`
- **Do NOT hardcode game rules, scoring elements, or config-driven logic in code.**
- **Do NOT edit files in `config/` directly unless you intend to change the game configuration for all users.**

---

## How to Add Features that Use Dynamic Config

1. **Access config via `ConfigManager`:**
   - Use `from app.utils.config_manager import get_config_manager` and call methods like `get_config_manager().game_config` or helper functions like `get_scoring_element_by_id()`.
2. **Reference config fields, not hardcoded values:**
   - Example: Instead of `points = 3`, use `points = get_scoring_element_by_id('lsz')['points']`.
3. **Add new config-driven features:**
   - Add new fields to `game_config.json` (or other config files) and update `ConfigManager` if needed.
   - Use config values in your code and templates.
4. **Reload config after changes:**
   - The app usually reloads config at startup. For live changes, call `ConfigManager.load_config()` if needed.

---

## Avoid Breaking Config-Driven Features

- **Never hardcode game logic that should be configurable.**
- When adding new scoring elements, always update both the config file and any code that processes scoring.
- Use helper functions in `config_manager.py` to access config data.
- If you add new config fields, document them in the config file and update any relevant code.
- Test changes with different config scenarios (e.g., add/remove scoring elements, change point values).

---

## File Integrity System

- The file integrity system monitors code and config files for unauthorized changes.
- After legitimate code or config updates, use the **Reinitialize** option in the admin interface to recalculate checksums.
- Excluded files: `game_config.json`, `ai_config.json`, database, uploads, and some temp files (see `help/FILE_INTEGRITY_README.md`).

---

## Best Practices for Developers

- **Always use config values, not hardcoded constants, for anything that might change between games/seasons.**
- **Test with modified config files** to ensure your code is robust.
- **Document any new config fields** you introduce.
- **Coordinate with admins** before making breaking changes to config structure.
- **Back up config files** before major updates.
- **Use version control** (Git) and commit both code and config changes.

---

## Troubleshooting

**Problem:** My new feature doesn't reflect config changes.
- **Solution:** Make sure you are reading values from `ConfigManager` and not using hardcoded values. Reload the config if needed.

**Problem:** App crashes after editing config or code.
- **Solution:** Check for typos or missing fields in the config file. Use helper functions to safely access config data.

**Problem:** File integrity warning after code update.
- **Solution:** Use the admin interface to reinitialize file integrity monitoring after legitimate updates.

**Problem:** Scoring or UI doesn't update after changing config.
- **Solution:** Restart the app to reload config, or call `ConfigManager.load_config()` if supported.

---

For more details, see:
- `help/FILE_INTEGRITY_README.md`
- `app/utils/config_manager.py`
- `config/game_config.json` 