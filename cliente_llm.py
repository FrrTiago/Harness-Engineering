"""
cliente_llm.py — Wrapper LLM com tolerância a falhas e SLM local.
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

# Alternar entre Ollama local (Bônus 10pts) e Nuvem
USAR_OLLAMA = os.getenv("USAR_OLLAMA", "true").lower() == "true"

URL_API_ANTHROPIC = "https://api.anthropic.com/v1/messages"
URL_API_OLLAMA = "http://127.0.0.1:11434/api/chat"
MODELO_NUVEM = "claude-3-haiku-20240307"
MODELO_SLM = "llama3.2" # Ou gemma:2b

MAX_TENTATIVAS = 4
ATRASO_BASE = 1.0     
MAX_ATRASO = 30.0     
FATOR_JITTER = 0.3    

DIRETORIO_PROMPTS = Path(__file__).parent / "prompts"
_cache_prompts: dict[str, str] = {}

def carregar_prompt_sistema(nome: str) -> str:
    if nome in _cache_prompts: return _cache_prompts[nome]
    caminho = DIRETORIO_PROMPTS / nome
    if not caminho.exists(): return "Aja como um analista de código sênior."
    conteudo = "\n".join(linha for linha in caminho.read_text(encoding="utf-8").splitlines() if not linha.startswith("#")).strip()
    _cache_prompts[nome] = conteudo
    return conteudo

async def chamar_llm(arquivo_prompt_sistema: str, mensagem_usuario: str, timeout: float = 120.0) -> dict:
    prompt_sistema = carregar_prompt_sistema(arquivo_prompt_sistema)
    t0 = time.time()
    ultimo_erro = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as cliente:
                if USAR_OLLAMA:
                    payload = {"model": MODELO_SLM, "messages": [{"role": "system", "content": prompt_sistema}, {"role": "user", "content": mensagem_usuario}], "stream": False}
                    resp = await cliente.post(URL_API_OLLAMA, json=payload)
                    resp.raise_for_status()
                    dados = resp.json()
                    texto = dados["message"]["content"]
                    tokens_in, tokens_out = dados.get("prompt_eval_count", 0), dados.get("eval_count", 0)
                else:
                    # Configuração original Anthropic
                    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": os.getenv("ANTHROPIC_API_KEY", "")}
                    payload = {"model": MODELO_NUVEM, "max_tokens": 4096, "system": prompt_sistema, "messages": [{"role": "user", "content": mensagem_usuario}]}
                    resp = await cliente.post(URL_API_ANTHROPIC, headers=headers, json=payload)
                    resp.raise_for_status()
                    dados = resp.json()
                    texto = dados["content"][0]["text"]
                    tokens_in, tokens_out = dados.get("usage", {}).get("input_tokens", 0), dados.get("usage", {}).get("output_tokens", 0)

            latencia_ms = round((time.time() - t0) * 1000, 1)
            logger.info("Sucesso LLM tentativa=%d latencia=%.0fms", tentativa, latencia_ms)
            return {"texto": texto, "tokens_entrada": tokens_in, "tokens_saida": tokens_out, "tentativas": tentativa, "latencia_ms": latencia_ms}
            
        except Exception as exc:
            ultimo_erro = exc
            logger.warning("Erro LLM tentativa=%d: %s", tentativa, exc)
            if tentativa < MAX_TENTATIVAS:
                atraso = min(ATRASO_BASE * (2 ** (tentativa - 1)), MAX_ATRASO)
                await asyncio.sleep(max(0.1, atraso + (atraso * FATOR_JITTER * (random.random() * 2 - 1))))

    raise RuntimeError(f"Falha no LLM após {MAX_TENTATIVAS} tentativas. Erro: {ultimo_erro}")