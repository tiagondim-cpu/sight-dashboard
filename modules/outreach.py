import asyncio
import random
from datetime import datetime
from playwright.async_api import Page
from utils.browser import create_context, human_mouse_move, human_scroll
from utils.safety import safety_check, check_daily_limits
from utils.db import (
    get_leads_by_status, update_lead_status, upsert_lead,
    increment_daily, get_daily_counts,
)
from utils.logger import get_logger

log = get_logger(__name__)


def render_message(template: str, nome: str, empresa: str, **kwargs) -> str:
    """Renderiza template com variáveis básicas (fallback sem IA)."""
    nome_primeiro = nome.split()[0] if nome else "Profissional"
    return template.format(
        nome=nome_primeiro,
        empresa=empresa or "sua empresa",
        tema="inovação e tecnologia",
        oferta="soluções de inovação",
        **kwargs,
    )


def build_message(tipo: str, lead: dict, cfg: dict) -> str:
    """
    Fluxo 2: Hyper-Personalização.
    Gera mensagem única via IA se habilitada, senão usa template.
    """
    msgs_cfg = cfg.get("mensagens", {})
    ai_cfg = cfg.get("ai", {})
    ai_enabled = ai_cfg.get("habilitado", False)

    nome = lead["nome"] or ""
    empresa = lead["empresa"] or ""
    template = msgs_cfg.get(
        "nota_conexao" if tipo == "nota_conexao" else "dm1",
        "Olá {nome}!"
    )
    template_rendered = render_message(template, nome, empresa)

    if not ai_enabled:
        return template_rendered

    from utils.ai_client import ai_generate_message
    model = ai_cfg.get("modelos", {}).get("mensagens", "claude-opus-4-6")

    return ai_generate_message(
        tipo=tipo,
        nome=nome,
        cargo=lead["cargo"] or "",
        empresa=empresa,
        sobre=lead["sobre"] or "",
        posts_recentes=lead["posts_recentes"] or "",
        oferta_descricao=ai_cfg.get("oferta_descricao", ""),
        template_fallback=template_rendered,
        model=model,
    )


async def send_connection(page: Page, url: str, nota: str) -> bool:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await safety_check(page)
    await human_mouse_move(page)
    await human_scroll(page)
    await asyncio.sleep(random.uniform(3, 8))

    btn = await page.query_selector("button[aria-label*='Connect'], button[aria-label*='Conectar']")
    if not btn:
        more = await page.query_selector("button[aria-label*='More actions'], button[aria-label*='Mais']")
        if more:
            await human_mouse_move(page)
            await more.click()
            await asyncio.sleep(random.uniform(1, 2))
            btn = await page.query_selector("li-icon[type='connect'] ~ span, [data-control-name='connect']")

    if not btn:
        log.warning(f"Botão 'Conectar' não encontrado em {url}")
        return False

    await human_mouse_move(page)
    await btn.click()
    await asyncio.sleep(random.uniform(1, 3))

    add_note = await page.query_selector("button[aria-label*='Add a note'], button[aria-label*='Adicionar nota']")
    if add_note:
        await add_note.click()
        await asyncio.sleep(random.uniform(0.5, 1.5))
        textarea = await page.query_selector("textarea#custom-message")
        if textarea:
            await textarea.fill(nota[:300])
            await asyncio.sleep(random.uniform(1, 2))

    send = await page.query_selector("button[aria-label*='Send invitation'], button[aria-label*='Enviar convite']")
    if send:
        await human_mouse_move(page)
        await send.click()
        await asyncio.sleep(random.uniform(2, 4))
        log.info(f"  Convite enviado para {url}")
        return True

    return False


async def send_dm(page: Page, url: str, mensagem: str) -> bool:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await safety_check(page)
    await asyncio.sleep(random.uniform(2, 5))

    btn = await page.query_selector("button[aria-label*='Message'], button[aria-label*='Mensagem']")
    if not btn:
        log.warning(f"Botão 'Mensagem' não encontrado em {url}")
        return False

    await human_mouse_move(page)
    await btn.click()
    await asyncio.sleep(random.uniform(1, 3))

    textarea = await page.query_selector("div.msg-form__contenteditable")
    if not textarea:
        return False

    await textarea.click()
    await asyncio.sleep(random.uniform(0.5, 1))
    await page.keyboard.type(mensagem, delay=random.randint(30, 80))
    await asyncio.sleep(random.uniform(1, 2))

    send_btn = await page.query_selector("button.msg-form__send-button")
    if send_btn:
        await human_mouse_move(page)
        await send_btn.click()
        await asyncio.sleep(random.uniform(2, 4))
        log.info(f"  DM1 enviada para {url}")
        return True

    return False


async def run_outreach(cfg: dict) -> None:
    violacoes = check_daily_limits(cfg)
    if "conexoes" in violacoes:
        log.warning(f"Limite diário de conexões atingido ({violacoes['conexoes']}). Tente amanhã.")
        return

    qualificados = get_leads_by_status("Qualificado")
    log.info(f"{len(qualificados)} leads qualificados para prospectar.")

    if not qualificados:
        log.info("Nenhum lead qualificado. Execute 'validate' primeiro.")
        return

    ai_enabled = cfg.get("ai", {}).get("habilitado", False)
    log.info(f"Mensagens: {'Hyper-personalizadas (IA)' if ai_enabled else 'Templates padrão'}")

    delays = cfg.get("delays", {})
    limite_dia = cfg.get("limites", {}).get("conexoes_por_dia", 15)

    pw, browser, context, page = await create_context()
    enviados = 0
    try:
        for lead in qualificados:
            counts = get_daily_counts()
            if counts.get("conexoes_enviadas", 0) >= limite_dia:
                log.warning("Limite diário atingido durante a sessão. Encerrando.")
                break

            url = lead["url_perfil"]
            nome = lead["nome"] or ""
            empresa = lead["empresa"] or ""

            log.info(f"Prospectando: {nome} ({empresa}) — {url}")

            # Fluxo 2: gera nota de conexão (IA ou template)
            nota = build_message("nota_conexao", dict(lead), cfg)
            log.info(f"  Nota ({len(nota)} chars): {nota[:80]}...")

            try:
                ok = await send_connection(page, url, nota)
                if ok:
                    update_lead_status(url, "Conexão Enviada")
                    upsert_lead(url, mensagem_conexao=nota)
                    increment_daily("conexoes_enviadas")
                    enviados += 1
            except RuntimeError as e:
                log.error(str(e))
                break
            except Exception as e:
                log.warning(f"Erro em {url}: {e}")

            base = delays.get("entre_visitas", {}).get("base", 300)
            variacao = delays.get("entre_visitas", {}).get("variacao", 300)
            wait = base + random.uniform(0, variacao)
            log.info(f"Aguardando {wait:.0f}s... ({enviados}/{limite_dia} hoje)")
            await asyncio.sleep(wait)
    finally:
        await browser.close()
        await pw.stop()

    log.info(f"Outreach concluído: {enviados} convites enviados hoje.")
