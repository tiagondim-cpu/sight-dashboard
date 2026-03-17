"""
Script de teste para validar a integração com Google Gemini nos 4 fluxos.
Uso: python tests/test_gemini.py
"""
import os
import sys
from pathlib import Path

# Adiciona o diretório raiz ao path para importar utils
sys.path.append(str(Path(__file__).parent.parent))

from utils.ai_client import (
    ai_qualify_profile,
    ai_generate_message,
    ai_classify_intent,
    ai_filter_discovery
)
from utils.logger import get_logger

log = get_logger("test_gemini")

def test_all():
    log.info("🚀 Iniciando testes de integração Gemini...")

    # 1. Teste de Qualificação
    log.info("\n1. Testando Qualificação Semântica...")
    try:
        res = ai_qualify_profile(
            nome="Tiago",
            cargo="CTO",
            empresa="Tech Solutions",
            tamanho_empresa="201-500",
            sobre="Focado em transformação digital e IA",
            experiencias="10 anos liderando times de tecnologia",
            icp_descricao="Tomadores de decisão em tech",
            oferta_descricao="Consultoria de IA"
        )
        log.info(f"✅ Sucesso! Score: {res.score}, Qualificado: {res.qualificado}")
        log.info(f"   Reasoning: {res.reasoning[:100]}...")
    except Exception as e:
        log.error(f"❌ Erro na Qualificação: {e}")

    # 2. Teste de Mensagem
    log.info("\n2. Testando Geração de Mensagem Personalizada...")
    try:
        msg = ai_generate_message(
            tipo="nota_conexao",
            nome="Tiago",
            cargo="CTO",
            empresa="Tech Solutions",
            sobre="Especialista em Cloud",
            posts_recentes="Post sobre Gemini 2.0",
            oferta_descricao="Aceleração de IA",
            template_fallback="Olá Tiago!"
        )
        log.info(f"✅ Sucesso! Mensagem ({len(msg)} chars): {msg}")
    except Exception as e:
        log.error(f"❌ Erro na Mensagem: {e}")

    # 3. Teste de Intenção
    log.info("\n3. Testando Classificação de Intenção...")
    try:
        intent = ai_classify_intent("Gostei da proposta, podemos marcar na terça às 14h?", "Tiago")
        log.info(f"✅ Sucesso! Intenção: {intent.intent}, Urgência: {intent.urgencia}")
    except Exception as e:
        log.error(f"❌ Erro na Intenção: {e}")

    # 4. Teste de Filtro
    log.info("\n4. Testando Filtro de Discovery...")
    try:
        is_profile = ai_filter_discovery(
            "Tiago Silva | LinkedIn",
            "CTO na Tech Solutions | Especialista em IA",
            "https://linkedin.com/in/tiago-silva"
        )
        log.info(f"✅ Sucesso! É perfil? {is_profile}")
    except Exception as e:
        log.error(f"❌ Erro no Filtro: {e}")

if __name__ == "__main__":
    if not os.environ.get("GOOGLE_API_KEY"):
        log.error("Aborte: GOOGLE_API_KEY não definida no ambiente.")
    else:
        test_all()
