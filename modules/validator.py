import asyncio
import json
import random
import re
from playwright.async_api import Page
from utils.browser import create_context, human_mouse_move, human_scroll
from utils.safety import safety_check
from utils.db import upsert_lead, update_lead_status, get_leads_by_status, increment_daily
from utils.logger import get_logger

log = get_logger(__name__)

EMPLOYEE_RANGES = {
    "1-10": (1, 10),
    "11-50": (11, 50),
    "51-200": (51, 200),
    "201-500": (201, 500),
    "501-1000": (501, 1000),
    "1001-5000": (1001, 5000),
    "5001-10000": (5001, 10000),
    "10001+": (10001, 999999),
    "2-10": (2, 10),
}


def parse_employee_count(text: str) -> tuple[int, int]:
    text = text.strip().lower().replace(".", "").replace(",", "")
    for key, val in EMPLOYEE_RANGES.items():
        if key.lower() in text:
            return val
    m = re.search(r"(\d+)", text)
    if m:
        n = int(m.group(1))
        return (n, n)
    return (0, 0)


def score_icp_keyword(cargo: str, min_emp: int, max_emp: int, tem_atividade: bool, cfg: dict) -> int:
    """Score baseado em palavras-chave (fallback quando IA está desabilitada)."""
    score = 0
    icp = cfg.get("icp", {})
    for c in icp.get("cargos", []):
        if c.lower() in cargo.lower():
            score += 40
            break
    emp_min = icp.get("tamanho_empresa", {}).get("min", 50)
    emp_max = icp.get("tamanho_empresa", {}).get("max", 5000)
    if max_emp >= emp_min and min_emp <= emp_max:
        score += 40
    if tem_atividade:
        score += 20
    return score


async def _extract_text(page: Page, selectors: list[str]) -> str:
    """Tenta múltiplos seletores e retorna o primeiro texto encontrado."""
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                return (await el.inner_text()).strip()
        except Exception:
            continue
    return ""


async def _extract_sobre(page: Page) -> str:
    """Extrai a seção 'Sobre' do perfil."""
    selectors = [
        "#about ~ div .inline-show-more-text",
        "section[id='about'] .pvs-list__item--no-padding-in-columns span[aria-hidden='true']",
        ".pv-about-section .pv-about__summary-text",
        "#about + div span[aria-hidden='true']",
    ]
    return await _extract_text(page, selectors)


async def _extract_experiencias(page: Page) -> str:
    """Extrai texto das experiências (as 3 primeiras)."""
    try:
        els = await page.query_selector_all(
            "#experience ~ div .pvs-list__item--line-separated, "
            "section[id='experience'] li.artdeco-list__item"
        )
        textos = []
        for el in els[:3]:
            t = (await el.inner_text()).strip()
            if t:
                textos.append(t)
        return "\n---\n".join(textos)
    except Exception:
        return ""


async def _extract_posts_recentes(page: Page) -> str:
    """Tenta extrair texto dos posts/atividade recente."""
    try:
        # Tenta rolar até a seção de atividade
        el = await page.query_selector("#activity, section[data-section='featured']")
        if el:
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(random.uniform(1, 2))
        els = await page.query_selector_all(
            ".feed-shared-update-v2__description span[dir='ltr'], "
            ".update-components-text span[dir='ltr']"
        )
        textos = []
        for el in els[:2]:
            t = (await el.inner_text()).strip()
            if t and len(t) > 20:
                textos.append(t)
        return "\n---\n".join(textos)
    except Exception:
        return ""


async def validate_profile(page: Page, url: str, cfg: dict) -> dict:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await safety_check(page)
    await human_mouse_move(page)
    await human_scroll(page)

    data = {"url_perfil": url}

    # Nome
    data["nome"] = await _extract_text(page, ["h1"])

    # Cargo
    data["cargo"] = await _extract_text(page, [
        ".text-body-medium.break-words",
        ".pv-text-details__left-panel .text-body-medium",
    ])

    # Empresa
    data["empresa"] = await _extract_text(page, [
        "button[aria-label*='empresa'] span",
        ".pv-text-details__right-panel-item-text",
        ".inline-show-more-text--is-collapsed",
    ])

    # Atividade recente
    tem_atividade = False
    try:
        activity_section = await page.query_selector(
            "section[data-member-id] .pv-recent-activity-section, #activity"
        )
        if activity_section:
            tem_atividade = True
    except Exception:
        pass
    data["tem_atividade_recente"] = int(tem_atividade)

    # Campos para IA
    data["sobre"] = await _extract_sobre(page)
    data["experiencias"] = await _extract_experiencias(page)
    data["posts_recentes"] = await _extract_posts_recentes(page)

    # Tamanho da empresa — navega para página da empresa
    tamanho = ""
    try:
        company_link = await page.query_selector("a[data-field='experience_company_logo']")
        if company_link:
            company_url = await company_link.get_attribute("href")
            if company_url:
                data["url_empresa"] = (
                    f"https://www.linkedin.com{company_url}"
                    if company_url.startswith("/")
                    else company_url
                )
                await page.goto(data["url_empresa"], wait_until="domcontentloaded", timeout=30000)
                await safety_check(page)
                await asyncio.sleep(random.uniform(2, 4))
                el = await page.query_selector("dd[class*='org-page-details']")
                if not el:
                    els = await page.query_selector_all(
                        ".org-about-company-module__company-size-definition-text, dt ~ dd"
                    )
                    for candidate in els:
                        txt = (await candidate.inner_text()).strip()
                        if any(c.isdigit() for c in txt):
                            tamanho = txt
                            break
                else:
                    tamanho = (await el.inner_text()).strip()
    except Exception as e:
        log.debug(f"Erro ao buscar tamanho da empresa: {e}")

    data["tamanho_empresa"] = tamanho
    min_e, max_e = parse_employee_count(tamanho)

    ai_cfg = cfg.get("ai", {})
    ai_enabled = ai_cfg.get("habilitado", False)

    if ai_enabled:
        # Fluxo 1: Qualificação Semântica via IA
        data = await _ai_qualify(data, cfg)
    else:
        # Fallback: score por palavras-chave
        data["score_icp"] = score_icp_keyword(data["cargo"], min_e, max_e, tem_atividade, cfg)
        score_minimo = 60
        data["status"] = "Qualificado" if data["score_icp"] >= score_minimo else "Desqualificado"

    return data


async def _ai_qualify(data: dict, cfg: dict) -> dict:
    """
    Fluxo 1: Qualificação Semântica.
    Chama o LLM para entender contexto real do perfil além de palavras-chave.
    """
    from utils.ai_client import ai_qualify_profile

    ai_cfg = cfg.get("ai", {})
    model = ai_cfg.get("modelos", {}).get("qualificacao", "claude-opus-4-6")
    icp_descricao = ai_cfg.get("icp_descricao", "")
    oferta_descricao = ai_cfg.get("oferta_descricao", "")
    score_minimo = ai_cfg.get("score_minimo", 60)

    try:
        result = ai_qualify_profile(
            nome=data.get("nome", ""),
            cargo=data.get("cargo", ""),
            empresa=data.get("empresa", ""),
            tamanho_empresa=data.get("tamanho_empresa", ""),
            sobre=data.get("sobre", ""),
            experiencias=data.get("experiencias", ""),
            icp_descricao=icp_descricao,
            oferta_descricao=oferta_descricao,
            model=model,
        )
        data["ai_score"] = result.score
        data["score_icp"] = result.score  # usa AI score como score principal
        data["ai_reasoning"] = result.reasoning
        data["ai_pontos_fortes"] = json.dumps(result.pontos_fortes, ensure_ascii=False)
        data["ai_alertas"] = json.dumps(result.alertas, ensure_ascii=False)
        data["status"] = "Qualificado" if result.qualificado and result.score >= score_minimo else "Desqualificado"

        log.info(
            f"  AI score: {result.score}/100 → {data['status']}\n"
            f"  Reasoning: {result.reasoning[:120]}..."
        )
    except Exception as e:
        log.warning(f"  AI qualification falhou: {e}. Usando score por keywords.")
        from modules.validator import parse_employee_count, score_icp_keyword
        min_e, max_e = parse_employee_count(data.get("tamanho_empresa", ""))
        data["score_icp"] = score_icp_keyword(
            data.get("cargo", ""), min_e, max_e,
            bool(data.get("tem_atividade_recente")), cfg
        )
        score_minimo = ai_cfg.get("score_minimo", 60)
        data["status"] = "Qualificado" if data["score_icp"] >= score_minimo else "Desqualificado"

    return data


async def run_validation(cfg: dict) -> None:
    prospects = get_leads_by_status("Prospect")
    log.info(f"{len(prospects)} prospects para validar.")

    if not prospects:
        log.info("Nenhum prospect encontrado. Execute 'discover' primeiro.")
        return

    ai_enabled = cfg.get("ai", {}).get("habilitado", False)
    log.info(f"Modo de qualificação: {'Semântica (IA)' if ai_enabled else 'Palavras-chave'}")

    delays = cfg.get("delays", {})
    base = delays.get("entre_visitas", {}).get("base", 300)
    variacao = delays.get("entre_visitas", {}).get("variacao", 300)

    pw, browser, context, page = await create_context()
    try:
        for lead in prospects:
            url = lead["url_perfil"]
            log.info(f"Validando: {url}")
            try:
                data = await validate_profile(page, url, cfg)
                upsert_lead(url, **{k: v for k, v in data.items() if k != "url_perfil"})
                increment_daily("perfis_visitados")
                log.info(
                    f"  {data.get('nome', '')} | {data.get('cargo', '')} | "
                    f"score={data.get('score_icp', 0)} → {data['status']}"
                )
            except RuntimeError as e:
                log.error(str(e))
                break
            except Exception as e:
                log.warning(f"Erro validando {url}: {e}")
                update_lead_status(url, "Prospect", nota=f"Erro: {e}")

            wait = base + random.uniform(0, variacao)
            log.info(f"Aguardando {wait:.0f}s antes do próximo perfil...")
            await asyncio.sleep(wait)
    finally:
        await browser.close()
        await pw.stop()
