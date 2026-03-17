"""
LinkedIn Hunter CRM — Web Dashboard
FastAPI server + API endpoints.
Uso: uvicorn web.app:app --reload
"""
import sys
import asyncio
import threading
from pathlib import Path
from collections import Counter
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

# Garante que o projeto raiz está no path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.db import init_db, get_all_leads, get_leads_by_status, get_daily_counts
from utils.logger import get_logger

log = get_logger("web")

app = FastAPI(title="LinkedIn Hunter CRM", docs_url="/docs")

# Static files e templates
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Estado do job em background
_job_state = {"running": False, "action": None, "message": ""}


# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ─── Pages ────────────────────────────────────────────────────────────────────

@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ─── API: Leads ───────────────────────────────────────────────────────────────

@app.get("/api/leads")
async def api_leads(status: str = None, search: str = None):
    if status and status != "all":
        leads = get_leads_by_status(status)
    else:
        leads = get_all_leads()

    result = []
    for lead in leads:
        d = dict(lead)
        # Filtra por busca (nome/cargo/empresa)
        if search:
            s = search.lower()
            match = any(
                s in (d.get(f) or "").lower()
                for f in ["nome", "cargo", "empresa"]
            )
            if not match:
                continue
        result.append(d)

    return JSONResponse(result)


@app.get("/api/stats")
async def api_stats():
    leads = get_all_leads()
    counts = get_daily_counts()
    status_count = Counter(dict(l).get("status", "Unknown") for l in leads)

    return JSONResponse({
        "total": len(leads),
        "by_status": dict(status_count),
        "daily": {
            "conexoes_enviadas": counts.get("conexoes_enviadas", 0),
            "perfis_visitados": counts.get("perfis_visitados", 0),
            "mensagens_enviadas": counts.get("mensagens_enviadas", 0),
        },
        "funnel": {
            "prospects": status_count.get("Prospect", 0),
            "qualificados": status_count.get("Qualificado", 0),
            "conexoes_enviadas": status_count.get("Conexão Enviada", 0),
            "conectados": status_count.get("Conectado", 0),
            "dm1_enviadas": status_count.get("DM1 Enviada", 0),
            "responderam": status_count.get("Respondeu", 0),
            "convertidos": status_count.get("Convertido", 0),
        },
    })


# ─── API: Pipeline Actions ───────────────────────────────────────────────────

def _run_action_in_thread(action: str):
    """Executa a ação do pipeline em uma thread separada."""
    import yaml

    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    _job_state["running"] = True
    _job_state["action"] = action
    _job_state["message"] = f"Executando {action}..."

    try:
        if action == "discover":
            from modules.discovery import run_discovery
            urls = run_discovery(cfg)
            _job_state["message"] = f"✓ Discovery concluído: {len(urls)} perfis encontrados."

        elif action == "validate":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from modules.validator import run_validation
            loop.run_until_complete(run_validation(cfg))
            loop.close()
            _job_state["message"] = "✓ Validação concluída."

        elif action == "outreach":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from modules.outreach import run_outreach
            loop.run_until_complete(run_outreach(cfg))
            loop.close()
            _job_state["message"] = "✓ Outreach concluído."

        elif action == "monitor":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            from modules.monitor import run_monitor
            loop.run_until_complete(run_monitor(cfg))
            loop.close()
            _job_state["message"] = "✓ Monitor concluído."

        else:
            _job_state["message"] = f"Ação desconhecida: {action}"

    except Exception as e:
        _job_state["message"] = f"✗ Erro em {action}: {str(e)}"
    finally:
        _job_state["running"] = False


VALID_ACTIONS = {"discover", "validate", "outreach", "monitor"}


@app.post("/api/actions/{action}")
async def api_run_action(action: str):
    if action not in VALID_ACTIONS:
        return JSONResponse({"error": f"Ação inválida: {action}"}, status_code=400)

    if _job_state["running"]:
        return JSONResponse(
            {"error": f"Já existe um job em execução: {_job_state['action']}"},
            status_code=409,
        )

    thread = threading.Thread(target=_run_action_in_thread, args=(action,), daemon=True)
    thread.start()

    return JSONResponse({"status": "started", "action": action})


@app.get("/api/actions/status")
async def api_action_status():
    return JSONResponse({
        "running": _job_state["running"],
        "action": _job_state["action"],
        "message": _job_state["message"],
    })
