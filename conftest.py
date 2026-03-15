"""Pytest configuration and shared fixtures for NexusMind tests.

Author: Pranav N
"""

import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio event loop policy."""
    return asyncio.DefaultEventLoopPolicy()
