"""Tests for the Radarr Plus missing movie and search services."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiopyarr import ArrConnectionException
from aiopyarr.const import HTTPMethod
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import pytest
import voluptuous as vol

from custom_components.radarr_plus.const import DOMAIN
from custom_components.radarr_plus.services import (
    ATTR_COMMAND,
    ATTR_COUNT,
    ATTR_ENTRY_ID,
    ATTR_MOVIE_IDS,
    ATTR_MOVIES,
    SERVICE_GET_MISSING_MOVIES,
    SERVICE_SEARCH_MOVIES,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from . import setup_integration

CLIENT = "aiopyarr.radarr_client.RadarrClient"


def _movie(movie_id, *, days_ago=None, monitored=True, has_file=False, **dates):
    """Build a movie released days_ago days ago (digital release)."""
    today = dt_util.now().date()
    if days_ago is not None:
        dates.setdefault("digitalRelease", today - timedelta(days=days_ago))
    return SimpleNamespace(
        id=movie_id,
        title=f"Movie {movie_id}",
        year=2026,
        tmdbId=movie_id,
        status="released",
        monitored=monitored,
        hasFile=has_file,
        digitalRelease=dates.get("digitalRelease"),
        physicalRelease=dates.get("physicalRelease"),
        inCinemas=dates.get("inCinemas"),
    )


MOVIES = [
    _movie(1, days_ago=5),
    _movie(2, days_ago=20),
    _movie(3, days_ago=60),
    _movie(4, days_ago=-10),  # not released yet
    _movie(5, days_ago=5, has_file=True),
    _movie(6, days_ago=5, monitored=False),
    _movie(7),  # no dates at all
    _movie(8, inCinemas=dt_util.now().date() - timedelta(days=3)),
    _movie(
        9,
        days_ago=40,
        physicalRelease=dt_util.now().date() - timedelta(days=2),
    ),  # earliest of digital/physical wins
]


async def _get_missing(hass: HomeAssistant, entry, **data):
    with patch(f"{CLIENT}.async_get_movies", AsyncMock(return_value=MOVIES)):
        return await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_MISSING_MOVIES,
            {ATTR_ENTRY_ID: entry.entry_id, **data},
            blocking=True,
            return_response=True,
        )


async def test_get_missing_movies_default_window(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Only missing movies released in the default 30 day window are returned."""
    entry = await setup_integration(hass, aioclient_mock)
    response = await _get_missing(hass, entry)

    assert response[ATTR_MOVIE_IDS] == [1, 2, 8]
    assert response[ATTR_COUNT] == 3
    assert set(response[ATTR_MOVIES]) == {"Movie 1", "Movie 2", "Movie 8"}
    assert response[ATTR_MOVIES]["Movie 1"]["release_date"] == (
        dt_util.now().date() - timedelta(days=5)
    ).isoformat()


async def test_get_missing_movies_custom_days(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The days parameter controls the window."""
    entry = await setup_integration(hass, aioclient_mock)

    assert (await _get_missing(hass, entry, days=4))[ATTR_MOVIE_IDS] == [8]
    assert (await _get_missing(hass, entry, days=90))[ATTR_MOVIE_IDS] == [
        1,
        2,
        3,
        8,
        9,
    ]


async def test_get_missing_movies_uses_earliest_release(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Movie 9 has a digital release 40 days ago and a newer physical release."""
    entry = await setup_integration(hass, aioclient_mock)

    assert 9 not in (await _get_missing(hass, entry, days=30))[ATTR_MOVIE_IDS]
    assert 9 in (await _get_missing(hass, entry, days=45))[ATTR_MOVIE_IDS]


@pytest.mark.parametrize("days", [0, -1, "abc"])
async def test_get_missing_movies_invalid_days(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, days
) -> None:
    """Invalid day values are rejected."""
    entry = await setup_integration(hass, aioclient_mock)
    with pytest.raises(vol.MultipleInvalid):
        await _get_missing(hass, entry, days=days)


async def test_search_movies(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Searching posts a de-duplicated MoviesSearch command."""
    entry = await setup_integration(hass, aioclient_mock)
    mock = AsyncMock(return_value={"id": 42, "status": "queued"})

    with patch(f"{CLIENT}.async_command_other", mock):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH_MOVIES,
            {ATTR_ENTRY_ID: entry.entry_id, ATTR_MOVIE_IDS: [1, 2, 2, "3"]},
            blocking=True,
            return_response=True,
        )

    mock.assert_awaited_once_with(
        "command",
        data={"name": "MoviesSearch", "movieIds": [1, 2, 3]},
        method=HTTPMethod.POST,
    )
    assert response == {
        ATTR_COUNT: 3,
        ATTR_COMMAND: {"id": 42, "status": "queued"},
    }


@pytest.mark.parametrize("ids", [[], [0], ["x"], "5"])
async def test_search_movies_invalid_ids(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, ids
) -> None:
    """An empty or malformed id list is rejected."""
    entry = await setup_integration(hass, aioclient_mock)
    with pytest.raises(vol.MultipleInvalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH_MOVIES,
            {ATTR_ENTRY_ID: entry.entry_id, ATTR_MOVIE_IDS: ids},
            blocking=True,
        )


async def test_search_movies_api_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """API failures surface as HomeAssistantError."""
    entry = await setup_integration(hass, aioclient_mock)
    with (
        patch(
            f"{CLIENT}.async_command_other",
            AsyncMock(side_effect=ArrConnectionException("boom")),
        ),
        pytest.raises(HomeAssistantError, match="Failed to connect"),
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH_MOVIES,
            {ATTR_ENTRY_ID: entry.entry_id, ATTR_MOVIE_IDS: [1]},
            blocking=True,
        )
