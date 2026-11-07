import os

import pytest


def pytest_collection_modifyitems(config, items):
    for item in items:
        if ("integration" in item.keywords or "e2e" in item.keywords) and os.getenv("RUN_INTEGRATION") != "1":
            item.add_marker(pytest.mark.skip(reason="Set RUN_INTEGRATION=1 for actual configured services"))
