"""
utils/ai_client.py — Camada de IA com 4 fluxos migrada para Google Gemini:
  1. Qualificação Semântica      (Gemini 2.0 Flash Thinking + JSON)
  2. Hyper-Personalização        (Gemini 2.0 Flash Thinking)
  3. Análise de Intenção         (Gemini 2.0 Flash + JSON)
  4. Filtro de Discovery         (Gemini 2.0 Flash, resposta sim/não)
"""
import json
import os
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv
from pydantic import BaseModel

from utils.logger import get_logger

load_dotenv()
log = get_logger(__name__)

_initialized = False


def _init_genai():
    global _initialized
    if not _initialized:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY não encontrada.\n"
                "Adicione ao arquivo .env: GOOGLE_API_KEY=AIza..."
            )
        genai.configure(api_key=api_key)
        _initialized = True


# ─── Modelos de resposta ──────────────────────────────────────────────────────

class QualificacaoResult(BaseModel):
    qualificado: bool
    score: int          # 0–100
    reasoning: str
    pontos_fortes: list[str]
    alertas: list[str]


class IntentResult(BaseModel):
    intent: str         # "Interessado" | "Objeção Preço" | "Retornar Depois" | "Não É o Momento" | "Neutro" | "Sem Resposta"
    acao_recomendada: str
    urgencia: str       # "alta" | "media" | "baixa"
    resumo: str


# ─── Fluxo 1: Qualificação Semântica ─────────────────────────────────────────

def ai_qualify_profile(
    nome: str,
    cargo: str,
    empresa: str,
    tamanho_empresa: str,
    sobre: str,
    experiencias: str,
    icp_descricao: str,
    oferta_descricao: str,
    model: str = "gemini-2.0-flash-thinking-exp",
) -> QualificacaoResult:
    """
    Usa Gemini 2.0 Flash Thinking para qualificação semântica profunda.
    """
    _init_genai()
    
    gen_model = genai.GenerativeModel(model)

    prompt = f"""Você é especialista em vendas B2B com foco em qualificação de leads para ABM.

## Nosso ICP
{icp_descricao}

## Nossa Oferta
{oferta_descricao}

## Lead para avaliar
- **Nome:** {nome}
- **Cargo atual:** {cargo}
- **Empresa:** {empresa}
- **Tamanho da empresa:** {tamanho_empresa or "Não informado"}
- **Seção Sobre:** {sobre or "Não disponível"}
- **Experiências:** {experiencias or "Não disponível"}

Avalie se este lead se encaixa no ICP. Seja rigoroso — prefira qualidade a quantidade.

Retorne um JSON seguindo exatamente este esquema:
{{
  "qualificado": boolean,
  "score": integer (0-100),
  "reasoning": "string com a explicação",
  "pontos_fortes": ["string", ...],
  "alertas": ["string", ...]
}}

Score de 0 a 100:
- 80–100: Fit excelente, tomador de decisão claro, prioridade máxima
- 60–79: Bom fit, vale abordar
- 40–59: Fit razoável, baixa prioridade
- 0–39: Não qualifica
"""

    response = gen_model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        )
    )
    
    data = json.loads(response.text)
    return QualificacaoResult(**data)


# ─── Fluxo 2: Hyper-Personalização ───────────────────────────────────────────

def ai_generate_message(
    tipo: str,                  # "nota_conexao" | "dm1"
    nome: str,
    cargo: str,
    empresa: str,
    sobre: str,
    posts_recentes: str,
    oferta_descricao: str,
    template_fallback: str,
    model: str = "gemini-2.0-flash-thinking-exp",
) -> str:
    """
    Gera mensagem única e personalizada com base no perfil real do lead.
    """
    _init_genai()
    nome_primeiro = nome.split()[0] if nome else "Profissional"

    if tipo == "nota_conexao":
        instrucao = f"""Escreva uma nota de convite de conexão LinkedIn para {nome_primeiro}.

REGRAS OBRIGATÓRIAS:
- Máximo ABSOLUTO de 280 caracteres
- Mencione algo ESPECÍFICO do perfil ou empresa
- Tom profissional e humano
- Não mencione produto diretamente
- Termine com abertura natural para conversa"""
    else:  # dm1
        instrucao = f"""Escreva a primeira mensagem (DM1) pós-conexão para {nome_primeiro}.

REGRAS OBRIGATÓRIAS:
- Máximo de 500 caracteres
- Abra referenciando algo específico do perfil ou empresa
- Posicione o valor da conversa sem fazer pitch
- Uma única call-to-action clara
- Tom de colega de mercado"""

    prompt = f"""{instrucao}

## Nossa Oferta (contexto interno, não mencionar diretamente)
{oferta_descricao}

## Dados do Lead
- Nome: {nome}
- Cargo: {cargo}
- Empresa: {empresa}
- Seção Sobre: {sobre or "Não disponível"}
- Posts/Atividade Recente: {posts_recentes or "Não disponível"}

Retorne APENAS o texto da mensagem, sem aspas, sem explicações."""

    try:
        gen_model = genai.GenerativeModel(model)
        response = gen_model.generate_content(prompt)
        text = response.text.strip()
        return text if text else template_fallback
    except Exception as e:
        log.warning(f"AI message generation falhou ({e}). Usando template padrão.")
        return template_fallback


# ─── Fluxo 3: Análise de Intenção ────────────────────────────────────────────

def ai_classify_intent(
    texto_resposta: str,
    nome: str,
    model: str = "gemini-2.0-flash",
) -> IntentResult:
    """
    Classifica a intenção da resposta do lead e sugere próxima ação.
    """
    _init_genai()
    gen_model = genai.GenerativeModel(model)

    prompt = f"""Classifique a intenção desta resposta de lead LinkedIn e sugira a próxima ação.

Responda em formato JSON com: intent, acao_recomendada, urgencia, resumo.

Categorias de intent: "Interessado", "Objeção Preço", "Retornar Depois", "Não É o Momento", "Neutro", "Sem Resposta".
Categorias de urgencia: "alta", "media", "baixa".

Resposta de {nome}:
"{texto_resposta}"
"""

    response = gen_model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
        )
    )
    
    data = json.loads(response.text)
    return IntentResult(**data)


# ─── Fluxo 4: Filtro de Discovery ────────────────────────────────────────────

def ai_filter_discovery(
    titulo: str,
    snippet: str,
    url: str,
    model: str = "gemini-2.0-flash",
) -> bool:
    """
    Retorna True se o resultado parecer ser um perfil individual válido.
    """
    _init_genai()
    gen_model = genai.GenerativeModel(model)

    prompt = f"""Este resultado de busca é um perfil individual do LinkedIn (e não vaga, empresa ou bot)?

Título: {titulo}
Trecho: {snippet}
URL: {url}

Responda APENAS "sim" ou "não"."""

    try:
        response = gen_model.generate_content(prompt)
        text = response.text.lower().strip()
        return "sim" in text
    except Exception as e:
        log.debug(f"AI filter erro: {e}. Mantendo resultado.")
        return True
