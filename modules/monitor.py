import asyncio
import random
from datetime import datetime
from playwright.async_api import Page
from utils.browser import create_context, human_mouse_move
from utils.safety import safety_check
from utils.db import get_leads_by_status, update_lead_status, upsert_lead, increment_daily
from utils.logger import get_logger
from modules.outreach import send_dm, build_message

log = get_logger(__name__)


async def check_connection_accepted(page: Page, url: str) -> bool:
    """Verifica se a conexão foi aceita — botão 'Mensagem' aparece no perfil."""
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await safety_check(page)
    await asyncio.sleep(random.uniform(2, 4))
    btn = await page.query_selector("button[aria-label*='Message'], button[aria-label*='Mensagem']")
    return btn is not None


async def read_last_reply(page: Page, url: str) -> str:
    """
    Fluxo 3: Tenta ler a última resposta do lead na thread de mensagens.
    Abre a conversa pelo perfil, lê mensagens que não são nossas.
    Retorna string vazia se não houver resposta ou se falhar.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await safety_check(page)
        await asyncio.sleep(random.uniform(2, 3))

        # Abre a thread de mensagens
        btn = await page.query_selector("button[aria-label*='Message'], button[aria-label*='Mensagem']")
        if not btn:
            return ""

        await btn.click()
        await asyncio.sleep(random.uniform(2, 4))

        # Aguarda a thread carregar
        await page.wait_for_selector(
            ".msg-s-event-listitem, .msg-s-message-list__event",
            timeout=8000
        )

        # Pega todas as mensagens na thread
        # Mensagens do lead (não enviadas por mim) ficam alinhadas à esquerda
        # Mensagens nossas ficam à direita (msg-s-event-listitem--other-participant)
        items = await page.query_selector_all(
            ".msg-s-event-listitem:not(.msg-s-event-listitem--other-participant) "
            ".msg-s-event-timeline-item__message"
        )

        # Pega o texto da última mensagem recebida
        textos = []
        for item in items:
            t = (await item.inner_text()).strip()
            if t:
                textos.append(t)

        if textos:
            return textos[-1]  # última resposta do lead

    except Exception as e:
        log.debug(f"Não foi possível ler inbox: {e}")

    return ""


async def _ai_process_reply(url: str, nome: str, resposta: str, cfg: dict) -> None:
    """
    Fluxo 3: Classifica a intenção da resposta e atualiza o CRM.
    """
    if not resposta:
        return

    from utils.ai_client import ai_classify_intent
    ai_cfg = cfg.get("ai", {})
    model = ai_cfg.get("modelos", {}).get("intent", "claude-haiku-4-5")

    try:
        result = ai_classify_intent(resposta, nome, model=model)
        log.info(
            f"  Intenção detectada: [{result.intent}] urgência={result.urgencia}\n"
            f"  Ação recomendada: {result.acao_recomendada}"
        )
        upsert_lead(
            url,
            ai_intent=result.intent,
            ai_acao_recomendada=result.acao_recomendada,
            ai_urgencia=result.urgencia,
            notas=f"[IA] {result.intent}: {result.resumo}",
        )
        # Marca como "Respondeu" para aparecer no CRM
        update_lead_status(url, "Respondeu", nota=f"{result.intent} — {result.acao_recomendada}")
    except Exception as e:
        log.warning(f"  AI intent classification falhou: {e}")


async def run_monitor(cfg: dict) -> None:
    pendentes = get_leads_by_status("Conexão Enviada")
    dm1_enviadas = get_leads_by_status("DM1 Enviada")
    log.info(
        f"{len(pendentes)} conexões pendentes + "
        f"{len(dm1_enviadas)} aguardando resposta."
    )

    ai_enabled = cfg.get("ai", {}).get("habilitado", False)
    msgs_cfg = cfg.get("mensagens", {})
    dm1_min = cfg.get("delays", {}).get("dm_apos_conexao_horas", {}).get("min", 2)
    dm1_max = cfg.get("delays", {}).get("dm_apos_conexao_horas", {}).get("max", 24)

    if not pendentes and not dm1_enviadas:
        log.info("Nada para monitorar.")
        return

    pw, browser, context, page = await create_context()
    try:
        # ── Checa conexões pendentes ──────────────────────────────────────────
        for lead in pendentes:
            url = lead["url_perfil"]
            nome = lead["nome"] or ""
            empresa = lead["empresa"] or ""

            log.info(f"Checando conexão: {nome} — {url}")
            try:
                aceito = await check_connection_accepted(page, url)
                if aceito:
                    log.info(f"  Conexão aceita por {nome}!")
                    update_lead_status(url, "Conectado")
                    upsert_lead(url, data_conexao=datetime.now().isoformat())

                    # Gera DM1 (IA ou template) e aguarda delay aleatório
                    dm1 = build_message("dm1", dict(lead), cfg)
                    delay_horas = random.uniform(dm1_min, dm1_max)
                    log.info(f"  DM1 agendada em {delay_horas:.1f}h para {nome}")
                    await asyncio.sleep(delay_horas * 3600)

                    ok = await send_dm(page, url, dm1)
                    if ok:
                        update_lead_status(url, "DM1 Enviada")
                        upsert_lead(url, mensagem_dm1=dm1)
                        increment_daily("mensagens_enviadas")
            except RuntimeError as e:
                log.error(str(e))
                break
            except Exception as e:
                log.warning(f"Erro checando {url}: {e}")

            await asyncio.sleep(random.uniform(10, 30))

        # ── Fluxo 3: Verifica respostas de DM1 enviadas ───────────────────────
        if ai_enabled and dm1_enviadas:
            log.info(f"Verificando respostas de {len(dm1_enviadas)} DMs enviadas...")
            for lead in dm1_enviadas:
                url = lead["url_perfil"]
                nome = lead["nome"] or ""

                try:
                    resposta = await read_last_reply(page, url)
                    if resposta:
                        log.info(f"  Resposta de {nome}: {resposta[:80]}...")
                        await _ai_process_reply(url, nome, resposta, cfg)
                    else:
                        log.debug(f"  Sem resposta ainda de {nome}")
                except RuntimeError as e:
                    log.error(str(e))
                    break
                except Exception as e:
                    log.warning(f"Erro verificando resposta de {url}: {e}")

                await asyncio.sleep(random.uniform(15, 40))

    finally:
        await browser.close()
        await pw.stop()
