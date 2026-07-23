"""
conftest.py
───────────
pytest configuration for HarmonyLedger.

Registers custom marks so pytest does not emit PytestUnknownMarkWarning.
"""

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests that require a live network connection "
        "(e.g. real gTTS call). Run with: pytest -m integration",
    )
