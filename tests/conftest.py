"""Pytest configuration and fixtures."""

import asyncio
from typing import AsyncGenerator, Generator

import aiohttp
import pytest
from aiohttp import web

from polite_crawler.database import Database


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def in_memory_db() -> AsyncGenerator[Database, None]:
    """Fixture for an in-memory database."""
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_db()
    yield db
    await db.close()


@pytest.fixture
async def test_http_server(event_loop: asyncio.AbstractEventLoop) -> AsyncGenerator[str, None]:
    """Fixture for a test HTTP server."""
    
    async def hello_handler(request: web.Request) -> web.Response:
        return web.Response(text="Hello, World!", status=200)
    
    async def status_handler(request: web.Request) -> web.Response:
        status_code = int(request.match_info.get("code", 200))
        return web.Response(text=f"Status {status_code}", status=status_code)
    
    async def json_handler(request: web.Request) -> web.Response:
        return web.json_response({"message": "Hello, JSON!"})
    
    async def slow_handler(request: web.Request) -> web.Response:
        await asyncio.sleep(0.1)
        return web.Response(text="Slow response", status=200)
    
    app = web.Application()
    app.router.add_get("/hello", hello_handler)
    app.router.add_get("/status/{code}", status_handler)
    app.router.add_get("/json", json_handler)
    app.router.add_get("/slow", slow_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, "localhost", 0)
    await site.start()
    
    port = runner.addresses[0][1]
    server_url = f"http://localhost:{port}"
    
    yield server_url
    
    await runner.cleanup()


@pytest.fixture
async def aiohttp_session() -> AsyncGenerator[aiohttp.ClientSession, None]:
    """Fixture for an aiohttp session."""
    async with aiohttp.ClientSession() as session:
        yield session
