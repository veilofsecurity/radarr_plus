"""Define services for the Radarr integration."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final, cast

from aiopyarr import exceptions
from aiopyarr.const import HTTPMethod
import voluptuous as vol

from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector, service
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import RadarrConfigEntry
from .helpers import (
    filter_missing_movies,
    format_missing_movies,
    format_movies,
    format_queue,
)

# Service names
SERVICE_GET_MOVIES: Final = "get_movies"
SERVICE_GET_QUEUE: Final = "get_queue"
SERVICE_GET_MISSING_MOVIES: Final = "get_missing_movies"
SERVICE_SEARCH_MOVIES: Final = "search_movies"

# Service attributes
ATTR_MOVIES: Final = "movies"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_MOVIE_IDS: Final = "movie_ids"
ATTR_COUNT: Final = "count"
ATTR_COMMAND: Final = "command"

# Service parameter constants
CONF_MAX_ITEMS = "max_items"
CONF_DAYS = "days"

# Default values - 0 means no limit
DEFAULT_MAX_ITEMS = 0
DEFAULT_MISSING_DAYS = 30

SERVICE_BASE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTRY_ID): selector.ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
    }
)

SERVICE_GET_MOVIES_SCHEMA = SERVICE_BASE_SCHEMA

SERVICE_GET_QUEUE_SCHEMA = SERVICE_BASE_SCHEMA.extend(
    {
        vol.Optional(CONF_MAX_ITEMS, default=DEFAULT_MAX_ITEMS): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=500)
        ),
    }
)

SERVICE_GET_MISSING_MOVIES_SCHEMA = SERVICE_BASE_SCHEMA.extend(
    {
        vol.Optional(CONF_DAYS, default=DEFAULT_MISSING_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=3650)
        ),
    }
)

SERVICE_SEARCH_MOVIES_SCHEMA = SERVICE_BASE_SCHEMA.extend(
    {
        vol.Required(ATTR_MOVIE_IDS): vol.All(
            [vol.All(vol.Coerce(int), vol.Range(min=1))],
            vol.Length(min=1),
        ),
    }
)


async def _handle_api_errors[_T](func: Callable[[], Awaitable[_T]]) -> _T:
    """Handle API errors and raise HomeAssistantError with user-friendly messages."""
    try:
        return await func()
    except exceptions.ArrAuthenticationException as ex:
        raise HomeAssistantError("Authentication failed for Radarr") from ex
    except exceptions.ArrConnectionException as ex:
        raise HomeAssistantError("Failed to connect to Radarr") from ex
    except exceptions.ArrException as ex:
        raise HomeAssistantError(f"Radarr API error: {ex}") from ex


async def _async_get_movies(call: ServiceCall) -> dict[str, Any]:
    """Get all Radarr movies."""
    entry: RadarrConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_ENTRY_ID]
    )

    api_client = entry.runtime_data.status.api_client
    movies_list = await _handle_api_errors(api_client.async_get_movies)

    # Get base URL from config entry for image URLs
    base_url = entry.data[CONF_URL]
    movies = format_movies(cast(list, movies_list), base_url)

    return {
        ATTR_MOVIES: movies,
    }


async def _async_get_queue(call: ServiceCall) -> dict[str, Any]:
    """Get Radarr queue."""
    entry: RadarrConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_ENTRY_ID]
    )
    max_items: int = call.data[CONF_MAX_ITEMS]

    api_client = entry.runtime_data.status.api_client

    if max_items > 0:
        page_size = max_items
    else:
        # Get total count first, then fetch all items
        queue_preview = await _handle_api_errors(
            lambda: api_client.async_get_queue(page_size=1)
        )
        total = queue_preview.totalRecords
        page_size = total if total > 0 else 1

    queue = await _handle_api_errors(
        lambda: api_client.async_get_queue(page_size=page_size, include_movie=True)
    )

    # Get base URL from config entry for image URLs
    base_url = entry.data[CONF_URL]

    movies = format_queue(queue, base_url)

    return {ATTR_MOVIES: movies}


async def _async_get_missing_movies(call: ServiceCall) -> dict[str, Any]:
    """Get monitored movies without a file released within the last N days."""
    entry: RadarrConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_ENTRY_ID]
    )
    days: int = call.data[CONF_DAYS]

    api_client = entry.runtime_data.status.api_client
    movies = await _handle_api_errors(api_client.async_get_movies)

    until = dt_util.now().date()
    missing = filter_missing_movies(
        cast(list, movies), until - timedelta(days=days), until
    )

    base_url = entry.data[CONF_URL]
    return {
        ATTR_COUNT: len(missing),
        ATTR_MOVIE_IDS: [movie.id for movie, _ in missing],
        ATTR_MOVIES: format_missing_movies(missing, base_url),
    }


async def _async_search_movies(call: ServiceCall) -> dict[str, Any]:
    """Ask Radarr to search for the given movies."""
    entry: RadarrConfigEntry = service.async_get_config_entry(
        call.hass, DOMAIN, call.data[ATTR_ENTRY_ID]
    )
    movie_ids: list[int] = list(dict.fromkeys(call.data[ATTR_MOVIE_IDS]))

    api_client = entry.runtime_data.status.api_client
    # aiopyarr has no MoviesSearch command, so post it directly
    command = await _handle_api_errors(
        lambda: api_client.async_command_other(
            "command",
            data={"name": "MoviesSearch", "movieIds": movie_ids},
            method=HTTPMethod.POST,
        )
    )

    return {
        ATTR_COUNT: len(movie_ids),
        ATTR_COMMAND: {
            "id": command.get("id") if isinstance(command, dict) else None,
            "status": command.get("status") if isinstance(command, dict) else None,
        },
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for the Radarr integration."""

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MOVIES,
        _async_get_movies,
        schema=SERVICE_GET_MOVIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_QUEUE,
        _async_get_queue,
        schema=SERVICE_GET_QUEUE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MISSING_MOVIES,
        _async_get_missing_movies,
        schema=SERVICE_GET_MISSING_MOVIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH_MOVIES,
        _async_search_movies,
        schema=SERVICE_SEARCH_MOVIES_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
