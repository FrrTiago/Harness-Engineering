"""
cliente_llm.py — Wrapper da API Anthropic com retentativa e backoff exponencial.

Implementa:
  - Retentativa com backoff exponencial + jitter (Seção 4.5 do enunciado)
  - Carregamento de prompts de arquivos markdown versionados (Seção 4.3)
  - Contagem de tokens para métricas (Seção 4.4)
  - Tratamento de timeout
"""

import asyncio
import logging
import os
import random
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("cliente_llm")

URL_API_ANTHROPIC = "https://api.anthropic.com/v1/messages"
MODELO = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096

# Configuração de retentativas (Retry)
MAX_TENTATIVAS = 4
ATRASO_BASE = 1.0     # segundos
MAX_ATRASO = 30.0     # segundos
FATOR_JITTER = 0.3    # ±30% jitter

DIRETORIO_PROMPTS = Path(__file__).parent / "prompts"


# ------------------------------------------------------------------ #
# Carregamento de Prompt (versionado, separado do código — Seção 4.3)#
# ------------------------------------------------------------------ #

_cache_prompts: dict[str, str] = {}

def carregar_prompt_sistema(nome: str) -> str:
    """Carrega um prompt de sistema versionado do diretório prompts/."""
    if nome in _cache_prompts:
        return _cache_prompts[nome]
    caminho = DIRETORIO_PROMPTS / nome
    if not caminho.exists():
        raise FileNotFoundError(f"Prompt de sistema não encontrado: {caminho}")
    # Remove linhas de comentários (iniciadas com #) — são metadados
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    conteudo = "\n".join(linha for linha in linhas if not linha.startswith("#")).strip()
    _cache_prompts[nome] = conteudo
    logger.info("Prompt de sistema carregado: %s (%d caracteres)", nome, len(conteudo))
    return conteudo


# ------------------------------------------------------------------ #
# Chamada Central do LLM                                             #
# ------------------------------------------------------------------ #

async def chamar_llm(
    arquivo_prompt_sistema: str,
    mensagem_usuario: str,
    timeout: float = 120.0,
) -> dict:
    """
    Chama a API da Anthropic com retentativa + backoff exponencial.

    Retorna
    -------
    dict com as chaves: texto, tokens_entrada, tokens_saida, tentativas, latencia_ms
    """
    prompt_sistema = carregar_prompt_sistema(arquivo_prompt_sistema)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        # Chave da API injetada pelo ambiente / proxy — nunca codificada diretamente
    }
    payload = {
        "model": MODELO,
        "max_tokens": MAX_TOKENS,
        "system": prompt_sistema,
        "messages": [{"role": "user", "content": mensagem_usuario}],
    }

    ultimo_erro: Optional[Exception] = None
    t0 = time.time()

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as cliente:
                resp = await cliente.post(URL_API_ANTHROPIC, headers=headers, json=payload)

            if resp.status_code == 200:
                dados = resp.json()
                texto = dados["content"][0]["text"]
                uso = dados.get("usage", {})
                latencia_ms = round((time.time() - t0) * 1000, 1)
                logger.info(
                    "Sucesso LLM tentativa=%d latencia=%.0fms entrada=%d saida=%d",
                    tentativa,
                    latencia_ms,
                    uso.get("input_tokens", 0),
                    uso.get("output_tokens", 0),
                )
                return {
                    "texto": texto,
                    "tokens_entrada": uso.get("input_tokens", 0),
                    "tokens_saida": uso.get("output_tokens", 0),
                    "tentativas": tentativa,
                    "latencia_ms": latencia_ms,
                }

            # Erros HTTP que permitem retentativa
            if resp.status_code in (429, 500, 502, 503, 504):
                ultimo_erro = RuntimeError(
                    f"HTTP {resp.status_code}: {resp.text[:200]}"
                )
                logger.warning(
                    "Erro LLM permite retentativa tentativa=%d status=%d",
                    tentativa, resp.status_code,
                )
            else:
                # Não permite retentativa (4xx diferente de 429)
                raise RuntimeError(
                    f"Erro HTTP LLM não permite retentativa {resp.status_code}: {resp.text[:400]}"
                )

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            ultimo_erro = exc
            logger.warning("Erro de rede LLM tentativa=%d: %s", tentativa, exc)

        if tentativa < MAX_TENTATIVAS:
            atraso = min(ATRASO_BASE * (2 ** (tentativa - 1)), MAX_ATRASO)
            jitter = atraso * FATOR_JITTER * (random.random() * 2 - 1)
            dormir_por = max(0.1, atraso + jitter)
            logger.info("Backoff de %.2fs antes da tentativa %d", dormir_por, tentativa + 1)
            await asyncio.sleep(dormir_por)

    raise RuntimeError(
        f"Falha no LLM após {MAX_TENTATIVAS} tentativas. Último erro: {ultimo_erro}"
    )