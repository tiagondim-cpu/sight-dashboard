#!/usr/bin/env python3
"""
LinkedIn Hunter — Social Selling Automation
Uso: python main.py [COMMAND]
"""
import asyncio
from pathlib import Path
import typer
import yaml
from rich.table import Table
from rich.console import Console
from utils.logger import get_logger
from utils.db import init_db, get_all_leads, get_daily_counts

app = typer.Typer(
    help="LinkedIn Hunter — Geração de listas e prospecção ABM para conta gratuita.",
    no_args_is_help=True,
)
console = Console()
log = get_logger("main")

CONFIG_PATH = Path("config/settings.yaml")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log.error(f"Arquivo de configuração não encontrado: {CONFIG_PATH}")
        raise typer.Exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.callback(invoke_without_command=True)
def startup(ctx: typer.Context) -> None:
    init_db()


@app.command()
def save_session():
    """Abre o Chrome para login manual no LinkedIn e salva a sessão."""
    from utils.browser import save_session as _save
    asyncio.run(_save())


@app.command()
def discover():
    """Busca perfis do LinkedIn via Google Dorking (DuckDuckGo)."""
    cfg = load_config()
    from modules.discovery import run_discovery
    urls = run_discovery(cfg)
    console.print(f"\n[green]✓ {len(urls)} perfis encontrados e salvos no CRM.[/green]")


@app.command()
def validate():
    """Acessa cada perfil no LinkedIn e qualifica pelo ICP."""
    cfg = load_config()
    asyncio.run(_validate(cfg))


async def _validate(cfg):
    from modules.validator import run_validation
    await run_validation(cfg)


@app.command()
def outreach():
    """Envia convites de conexão para leads qualificados."""
    cfg = load_config()
    asyncio.run(_outreach(cfg))


async def _outreach(cfg):
    from modules.outreach import run_outreach
    await run_outreach(cfg)


@app.command()
def monitor():
    """Checa conexões aceitas e envia DM1 para os novos conectados."""
    cfg = load_config()
    asyncio.run(_monitor(cfg))


async def _monitor(cfg):
    from modules.monitor import run_monitor
    await run_monitor(cfg)


@app.command()
def status():
    """Exibe o estado atual do CRM e os limites diários."""
    init_db()
    leads = get_all_leads()
    counts = get_daily_counts()

    # Tabela de status
    from collections import Counter
    status_count = Counter(l["status"] for l in leads)

    t = Table(title="CRM — Resumo de Leads", show_header=True)
    t.add_column("Status", style="cyan")
    t.add_column("Quantidade", justify="right")
    for s, n in sorted(status_count.items(), key=lambda x: -x[1]):
        t.add_row(s, str(n))
    t.add_row("[bold]TOTAL[/bold]", f"[bold]{len(leads)}[/bold]")
    console.print(t)

    # Limites diários
    t2 = Table(title="Atividade de Hoje", show_header=True)
    t2.add_column("Métrica", style="yellow")
    t2.add_column("Valor", justify="right")
    t2.add_row("Conexões enviadas", str(counts.get("conexoes_enviadas", 0)))
    t2.add_row("Perfis visitados", str(counts.get("perfis_visitados", 0)))
    t2.add_row("Mensagens enviadas", str(counts.get("mensagens_enviadas", 0)))
    console.print(t2)


@app.command()
def sync():
    """Exporta o CRM completo para uma planilha Excel (.xlsx)."""
    init_db()
    cfg = load_config()
    leads = get_all_leads()

    if not leads:
        console.print("[yellow]Nenhum lead no CRM para exportar.[/yellow]")
        return

    from pathlib import Path
    from utils.sheets import export_to_excel, export_to_csv

    planilha_cfg = cfg.get("planilha", {})
    formato = planilha_cfg.get("formato", "xlsx")
    caminho = Path(planilha_cfg.get("caminho", "data/crm_export.xlsx"))

    if formato == "csv":
        caminho = caminho.with_suffix(".csv")
        path = export_to_csv(leads, caminho)
    else:
        path = export_to_excel(leads, caminho)

    console.print(f"\n[green]✓ {len(leads)} leads exportados para: {path}[/green]")


@app.command()
def export_csv():
    """Exporta o CRM para CSV (alternativa rápida)."""
    init_db()
    leads = get_all_leads()

    if not leads:
        console.print("[yellow]Nenhum lead no CRM para exportar.[/yellow]")
        return

    from pathlib import Path
    from utils.sheets import export_to_csv

    path = export_to_csv(leads, Path("data/crm_export.csv"))
    console.print(f"\n[green]✓ {len(leads)} leads exportados para: {path}[/green]")


@app.command()
def run_all():
    """Executa o pipeline completo: discover → validate → outreach → monitor."""
    cfg = load_config()
    console.print("[bold blue]Iniciando pipeline completo...[/bold blue]")
    from modules.discovery import run_discovery
    run_discovery(cfg)
    asyncio.run(_run_full(cfg))


async def _run_full(cfg):
    from modules.validator import run_validation
    from modules.outreach import run_outreach
    from modules.monitor import run_monitor
    await run_validation(cfg)
    await run_outreach(cfg)
    await run_monitor(cfg)


if __name__ == "__main__":
    app()
