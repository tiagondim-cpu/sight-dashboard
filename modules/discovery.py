import re
import time
import random
from duckduckgo_search import DDGS
from utils.logger import get_logger
from utils.db import upsert_lead

log = get_logger(__name__)

LINKEDIN_PROFILE_RE = re.compile(
    r"https?://(www\.|br\.)?linkedin\.com/in/[a-zA-Z0-9\-_%]+/?",
    re.IGNORECASE,
)


def build_queries(cfg: dict) -> list[str]:
    icp = cfg.get("icp", {})
    loc = icp.get("localizacao", "")
    templates = cfg.get("busca", {}).get("queries_templates", [])
    queries = []
    for cargo in icp.get("cargos", []):
        for tmpl in templates:
            if "{keyword}" in tmpl:
                for kw in icp.get("keywords_extras", []):
                    q = tmpl.format(cargo=cargo, localizacao=loc, keyword=kw)
                    queries.append(q)
            else:
                q = tmpl.format(cargo=cargo, localizacao=loc, keyword="")
                queries.append(q)
    return queries


def extract_linkedin_urls(results: list) -> list[str]:
    urls = []
    for r in results:
        href = r.get("href", "")
        m = LINKEDIN_PROFILE_RE.match(href)
        if m:
            clean = re.sub(r"https?://(www\.|br\.)?linkedin\.com/in/", "", href)
            clean = clean.strip("/")
            url = f"https://www.linkedin.com/in/{clean}/"
            if url not in urls:
                urls.append(url)
    return urls


def _ai_filter_results(results: list, cfg: dict) -> list:
    """
    Fluxo 4: Filtra resultados de busca via IA antes de extrair URLs.
    Descarta vagas de emprego, recrutadores, páginas de empresa e spam.
    """
    from utils.ai_client import ai_filter_discovery
    ai_cfg = cfg.get("ai", {})
    model = ai_cfg.get("modelos", {}).get("filtro_discovery", "claude-haiku-4-5")

    filtered = []
    for r in results:
        titulo = r.get("title", "")
        snippet = r.get("body", "")
        href = r.get("href", "")
        if ai_filter_discovery(titulo, snippet, href, model=model):
            filtered.append(r)
        else:
            log.debug(f"  IA descartou resultado: {titulo[:60]}")
    return filtered


def run_discovery(cfg: dict) -> list[str]:
    queries = build_queries(cfg)
    max_por_query = cfg.get("busca", {}).get("max_resultados_por_query", 20)
    ai_enabled = cfg.get("ai", {}).get("habilitado", False)
    all_urls = []

    log.info(f"Iniciando discovery com {len(queries)} queries... [AI={'on' if ai_enabled else 'off'}]")

    with DDGS() as ddgs:
        for q in queries:
            log.info(f"Query: {q}")
            try:
                results = list(ddgs.text(q, max_results=max_por_query))

                # Fluxo 4: filtro IA antes de salvar
                if ai_enabled:
                    antes = len(results)
                    results = _ai_filter_results(results, cfg)
                    log.info(f"  IA filtrou: {antes} → {len(results)} resultados válidos")

                urls = extract_linkedin_urls(results)
                log.info(f"  → {len(urls)} perfis encontrados")
                for url in urls:
                    if url not in all_urls:
                        all_urls.append(url)
                        upsert_lead(url, status="Prospect")
                time.sleep(random.uniform(3, 8))
            except Exception as e:
                log.warning(f"Erro na query '{q}': {e}")

    log.info(f"Discovery concluído: {len(all_urls)} URLs únicas salvas.")
    return all_urls
