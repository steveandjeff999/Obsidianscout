"""Shim for moved script

This repository has been reorganized. The original `debug_metric_calc.py` has been moved
into `dev_tools/`. This shim keeps the script runnable from the repository root while
delegating work to the module under `dev_tools`.
"""
from importlib import import_module

MODULE_NAME = 'dev_tools.debug_metric_calc'

def _run():
    try:
        mod = import_module(MODULE_NAME)
        if hasattr(mod, 'placeholder'):
            mod.placeholder()
        else:
            print(f"Loaded {MODULE_NAME} but no entrypoint found")
    except Exception as e:
        print("This script was moved to dev_tools and replaced with a shim.")
        print("Import error:", e)

if __name__ == '__main__':
    _run()