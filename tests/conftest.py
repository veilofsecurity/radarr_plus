"""Shared pytest configuration for Sonarr Plus."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in all tests."""
    return


@pytest.fixture
def snapshot(snapshot):
    """Use the Home Assistant syrupy extension for snapshots."""
    from pytest_homeassistant_custom_component.syrupy import (  # noqa: PLC0415
        HomeAssistantSnapshotExtension,
    )

    return snapshot.use_extension(HomeAssistantSnapshotExtension)


@pytest.fixture
def entity_registry_enabled_by_default():
    """Enable entities that are disabled by default."""
    from unittest.mock import PropertyMock, patch  # noqa: PLC0415

    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        PropertyMock(return_value=True),
    ):
        yield
