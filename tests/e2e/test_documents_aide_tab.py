import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

import pytest
from playwright.async_api import async_playwright

RUN_E2E = os.getenv('RUN_E2E') == '1'
BASE_DIR = Path(__file__).resolve().parents[1]
SERVER_URL = 'http://127.0.0.1:5000'


@pytest.fixture(scope='module')
def app_server():
    if not RUN_E2E:
        pytest.skip('RUN_E2E not enabled')
    env = os.environ.copy()
    env.setdefault('FLASK_DEBUG', '0')
    env.setdefault('OPENAI_API_KEY', 'test-key')
    env.setdefault('PORT', '5000')
    process = subprocess.Popen(
        [sys.executable, 'server.py'],
        cwd=str(BASE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            request.urlopen(f'{SERVER_URL}/api/version', timeout=2)
            break
        except Exception:
            if process.poll() is not None:
                out, err = process.communicate()
                raise RuntimeError(f'Server exited early\nSTDOUT: {out}\nSTDERR: {err}')
            time.sleep(1)
    else:
        process.terminate()
        raise TimeoutError('Server did not start in time')
    yield SERVER_URL
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.mark.e2e
def test_documents_aide_tab_renders(app_server):
    async def run():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()
            await page.goto(f'{app_server}/#documents', wait_until='networkidle')
            await page.wait_for_selector('section[data-tab="documents_aide"]', timeout=15000)
            await page.wait_for_selector('#docAideCatalogGrid', timeout=15000)
            assert not await page.locator('.documents-aide__error').is_visible()
            await browser.close()

    asyncio.run(run())
