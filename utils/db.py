import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from utils.logger import get_logger

log = get_logger(__name__)

DB_PATH = Path("data/crm.db")

STATUS = [
    "Prospect",
    "Qualificado",
    "Desqualificado",
    "Conexão Enviada",
    "Conectado",
    "DM1 Enviada",
    "Respondeu",
    "Convertido",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    url_perfil           TEXT UNIQUE NOT NULL,
    nome                 TEXT,
    cargo                TEXT,
    empresa              TEXT,
    url_empresa          TEXT,
    tamanho_empresa      TEXT,
    tem_atividade_recente INTEGER DEFAULT 0,
    score_icp            INTEGER DEFAULT 0,
    status               TEXT DEFAULT 'Prospect',
    notas                TEXT,
    mensagem_conexao     TEXT,
    mensagem_dm1         TEXT,
    data_descoberta      DATETIME DEFAULT CURRENT_TIMESTAMP,
    data_ultima_acao     DATETIME,
    data_conexao         DATETIME,
    created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Campos de IA (adicionados via migração em bancos existentes)
    sobre                TEXT,
    experiencias         TEXT,
    posts_recentes       TEXT,
    ai_score             INTEGER DEFAULT 0,
    ai_reasoning         TEXT,
    ai_pontos_fortes     TEXT,
    ai_alertas           TEXT,
    ai_intent            TEXT,
    ai_acao_recomendada  TEXT,
    ai_urgencia          TEXT
);

CREATE TABLE IF NOT EXISTS daily_limits (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    data                 DATE UNIQUE,
    conexoes_enviadas    INTEGER DEFAULT 0,
    perfis_visitados     INTEGER DEFAULT 0,
    mensagens_enviadas   INTEGER DEFAULT 0
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


_AI_COLUMNS = [
    ("sobre",               "TEXT"),
    ("experiencias",        "TEXT"),
    ("posts_recentes",      "TEXT"),
    ("ai_score",            "INTEGER DEFAULT 0"),
    ("ai_reasoning",        "TEXT"),
    ("ai_pontos_fortes",    "TEXT"),
    ("ai_alertas",          "TEXT"),
    ("ai_intent",           "TEXT"),
    ("ai_acao_recomendada", "TEXT"),
    ("ai_urgencia",         "TEXT"),
]


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    _migrate_ai_columns()
    log.info(f"DB inicializado em {DB_PATH}")


def _migrate_ai_columns() -> None:
    """Adiciona colunas de IA a bancos existentes (idempotente)."""
    with get_conn() as conn:
        for col_name, col_type in _AI_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE leads ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass  # coluna já existe


# ─── Sync hook ────────────────────────────────────────────────────────────────

def _sync_to_sheet(url: str) -> None:
    """Tenta sincronizar o lead na planilha Excel (falha silenciosamente)."""
    try:
        from utils.sheets import sync_lead_to_sheet
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM leads WHERE url_perfil=?", (url,)
            ).fetchone()
            if row:
                sync_lead_to_sheet(dict(row))
    except Exception:
        pass  # nunca quebra o fluxo principal


# ─── Leads ────────────────────────────────────────────────────────────────────

def upsert_lead(url: str, **kwargs) -> int:
    fields = {k: v for k, v in kwargs.items()}
    fields["url_perfil"] = url
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "url_perfil")
    sql = f"""
        INSERT INTO leads ({cols}) VALUES ({placeholders})
        ON CONFLICT(url_perfil) DO UPDATE SET {updates}
    """
    with get_conn() as conn:
        cur = conn.execute(sql, list(fields.values()))
        _sync_to_sheet(url)
        return cur.lastrowid


def update_lead_status(url: str, status: str, nota: Optional[str] = None) -> None:
    assert status in STATUS, f"Status inválido: {status}"
    with get_conn() as conn:
        conn.execute(
            "UPDATE leads SET status=?, data_ultima_acao=?, notas=COALESCE(?,notas) WHERE url_perfil=?",
            (status, datetime.now().isoformat(), nota, url),
        )
    _sync_to_sheet(url)


def get_leads_by_status(status: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE status=? ORDER BY score_icp DESC", (status,)
        ).fetchall()


def get_all_leads() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()


# ─── Daily limits ─────────────────────────────────────────────────────────────

def _ensure_today() -> None:
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_limits (data) VALUES (?)", (today,)
        )


def increment_daily(field: str) -> int:
    _ensure_today()
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            f"UPDATE daily_limits SET {field}={field}+1 WHERE data=?", (today,)
        )
        row = conn.execute(
            f"SELECT {field} FROM daily_limits WHERE data=?", (today,)
        ).fetchone()
        return row[0]


def get_daily_counts() -> dict:
    _ensure_today()
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_limits WHERE data=?", (today,)
        ).fetchone()
        return dict(row) if row else {}
