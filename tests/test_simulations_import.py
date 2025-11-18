def test_import_simulations():
    """Simple smoke test: import simulations module to ensure no syntax errors."""
    from app.routes import simulations
    assert hasattr(simulations, 'bp')
