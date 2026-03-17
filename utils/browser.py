import json
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page
from playwright_stealth import stealth_async
from utils.logger import get_logger
import asyncio
import random

log = get_logger(__name__)

STATE_PATH = Path("config/state.json")


async def human_delay(base: float = 5, variacao: float = 55) -> None:
    """Delay baseado na fórmula: T = base + random(10, 60)s."""
    t = base + random.uniform(10, min(variacao, 60))
    await asyncio.sleep(t)


async def human_mouse_move(page: Page) -> None:
    """Simula movimentos de mouse aleatórios antes de interagir."""
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, 1200)
        y = random.randint(100, 700)
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.1, 0.4))


async def human_scroll(page: Page) -> None:
    """Simula leitura com scroll progressivo."""
    for _ in range(random.randint(3, 7)):
        await page.mouse.wheel(0, random.randint(200, 500))
        await asyncio.sleep(random.uniform(0.5, 2.0))


async def create_context() -> tuple:
    """Cria contexto do browser carregando sessão salva."""
    if not STATE_PATH.exists():
        raise FileNotFoundError(
            f"Sessão não encontrada em {STATE_PATH}.\n"
            "Execute: python main.py save-session"
        )

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        storage_state=str(STATE_PATH),
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
    )
    page = await context.new_page()
    await stealth_async(page)
    log.info("Browser iniciado com sessão salva.")
    return pw, browser, context, page


async def save_session() -> None:
    """Abre o LinkedIn para login manual e salva a sessão."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://www.linkedin.com/login")
    log.info("Faça login no LinkedIn. Quando terminar, pressione ENTER aqui...")
    input()
    await context.storage_state(path=str(STATE_PATH))
    log.info(f"Sessão salva em {STATE_PATH}")
    await browser.close()
    await pw.stop()
