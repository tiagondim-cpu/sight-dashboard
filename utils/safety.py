import asyncio
from datetime import datetime
from playwright.async_api import Page
from utils.logger import get_logger
from utils.db import get_daily_counts

log = get_logger(__name__)

CAPTCHA_SELECTORS = [
    "#captcha-internal",
    "iframe[src*='captcha']",
    "[data-test-id='captcha']",
]

LIMIT_MESSAGES = [
    "weekly invitation limit",
    "limite semanal",
    "you've reached the weekly",
    "atingiu o limite",
    "you can no longer send",
]


async def check_captcha(page: Page) -> bool:
    for sel in CAPTCHA_SELECTORS:
        if await page.query_selector(sel):
            return True
    return False


async def check_limit_message(page: Page) -> bool:
    content = (await page.content()).lower()
    return any(msg in content for msg in LIMIT_MESSAGES)


async def safety_check(page: Page) -> None:
    """Lança exceção se detectar CAPTCHA ou mensagem de limite."""
    if await check_captcha(page):
        raise RuntimeError("CAPTCHA detectado! Encerrando para proteger a conta.")
    if await check_limit_message(page):
        raise RuntimeError("Limite do LinkedIn atingido! Encerrando.")


def check_daily_limits(cfg: dict) -> dict:
    """Retorna campos que já atingiram o limite diário."""
    counts = get_daily_counts()
    limites = cfg.get("limites", {})
    violacoes = {}
    if counts.get("conexoes_enviadas", 0) >= limites.get("conexoes_por_dia", 15):
        violacoes["conexoes"] = counts["conexoes_enviadas"]
    if counts.get("visitas_por_dia", 0) >= limites.get("visitas_por_dia", 50):
        violacoes["visitas"] = counts["visitas_por_dia"]
    if counts.get("mensagens_enviadas", 0) >= limites.get("mensagens_por_dia", 20):
        violacoes["mensagens"] = counts["mensagens_enviadas"]
    return violacoes


def is_active_hours(cfg: dict) -> bool:
    h = datetime.now().hour
    inicio = cfg.get("limites", {}).get("horas_ativas", {}).get("inicio", 8)
    fim = cfg.get("limites", {}).get("horas_ativas", {}).get("fim", 18)
    return inicio <= h < fim
