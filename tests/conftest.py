import pytest

from gold_ai.brokers.mock_feed import synthetic_spec
from gold_ai.config import Settings
from gold_ai.memory.store import MemoryStore


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url=f"sqlite:///{tmp_path}/t.db", data_dir=str(tmp_path), secret_key="test-secret-key-0123456789")


@pytest.fixture
def store(settings):
    return MemoryStore(settings.database_url)


@pytest.fixture
def spec():
    return synthetic_spec()
