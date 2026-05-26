"""
orquestrador.py — Ponto de entrada principal.

Responsabilidades (Focadas no Tema 7):
  1. Receber submissões de arquivos (via HTTP POST /analisar)
  2. Dividir cada arquivo em chunks (estratégia de particionamento — Seção 4.3)
  3. Enfileirar uma tarefa por (arquivo × tipo_tarefa) na fila de trabalho
  4. Lançar N corrotinas de trabalhadores paralelos por tipo de tarefa
  5. O Trabalhador Agregador consolida os resultados (Fase Reduce)
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional

from aiohttp import web
from aiohttp.web_middlewares import middleware

from mensageria import barramento
from trabalhadores import criar_pool_trabalhadores
from metricas import coletor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)-20s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orquestrador")

# ------------------------------------------------------------------ #
# Configuração                                                       #
# ------------------------------------------------------------------ #

TRABALHADORES_POR_TIPO = int(os.getenv("TRABALHADORES_POR_TIPO", "2"))
LINHAS_POR_CHUNK = int(os.getenv("LINHAS_POR_CHUNK", "120"))
TIPOS_TAREFA = ["geracao_teste", "code_smell", "documentacao"]

# ------------------------------------------------------------------ #
# Configuração de Filas                                              #
# ------------------------------------------------------------------ #

def configurar_filas():
    dlq         = barramento.criar_fila("fila-dead-letter", max_recebimentos=99)
    fila_trab   = barramento.criar_fila("fila-trabalho", max_recebimentos=3, timeout_visibilidade=90, dlq=dlq)
    fila_res    = barramento.criar_fila("fila-resultado", max_recebimentos=3, timeout_visibilidade=120, dlq=dlq)
    fila_final  = barramento.criar_fila("fila-final", max_recebimentos=2, timeout_visibilidade=60, dlq=dlq)
    return fila_trab, fila_res, fila_final


# ------------------------------------------------------------------ #
# Estratégia de Chunking (Seção 4.3)                                 #
# ------------------------------------------------------------------ #

def dividir_codigo_fonte(codigo_fonte: str, tamanho_chunk: int = LINHAS_POR_CHUNK) -> List[str]:
    linhas = codigo_fonte.splitlines()
    if len(linhas) <= tamanho_chunk:
        return [codigo_fonte]

    sobreposicao = 10
    chunks = []
    inicio = 0
    while inicio < len(linhas):
        fim = min(inicio + tamanho_chunk, len(linhas))
        chunks.append("\n".join(linhas[inicio:fim]))
        if fim == len(linhas):
            break
        inicio += tamanho_chunk - sobreposicao
    return chunks

class EstadoApp:
    def __init__(self):
        self.fila_trab = None
        self.fila_res = None
        self.fila_final = None
        self.trabalhadores: list = []
        self.tarefas_trabalhadores: list = []
        self.relatorio_final: Optional[dict] = None
        self.eventos_ao_vivo: list = []

    def ao_receber_evento(self, evento: dict):
        self.eventos_ao_vivo.append(evento)
        if len(self.eventos_ao_vivo) > 500:
            self.eventos_ao_vivo = self.eventos_ao_vivo[-500:]

        if evento.get("evento") == "fim_tarefa" and evento.get("tipo_tarefa") == "agregacao":
            relatorio = evento.get("relatorio")
            if relatorio:
                self.relatorio_final = relatorio

estado = EstadoApp()

@middleware
async def middleware_cors(request, handler):
    if request.method == "OPTIONS":
        return web.Response(
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }
        )
    resp = await handler(request)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

# ------------------------------------------------------------------ #
# Manipuladores HTTP                                                 #
# ------------------------------------------------------------------ #

async def lidar_analisar(request: web.Request) -> web.Response:
    arquivos = []
    tipo_conteudo = request.content_type or ""
    
    if "multipart" in tipo_conteudo:
        leitor = await request.multipart()
        async for parte in leitor:
            if parte.filename and parte.filename.endswith(".py"):
                codigo = (await parte.read()).decode("utf-8", errors="replace")
                arquivos.append({"nome": parte.filename, "conteudo": codigo})
    else:
        corpo = await request.json()
        arquivos = corpo.get("arquivos", [])

    if not arquivos:
        return web.json_response({"erro": "Nenhum arquivo Python fornecido"}, status=400)

    for t in estado.tarefas_trabalhadores:
        t.cancel()
    estado.tarefas_trabalhadores.clear()

    estado.trabalhadores = criar_pool_trabalhadores(
        fila_trabalho=estado.fila_trab,
        fila_resultado=estado.fila_res,
        fila_final=estado.fila_final,
        num_trabalhadores=TRABALHADORES_POR_TIPO,
        tipos_tarefa=TIPOS_TAREFA,
        total_arquivos=sum(len(dividir_codigo_fonte(f["conteudo"])) for f in arquivos),
        ao_receber_evento=estado.ao_receber_evento,
    )

    for trab in estado.trabalhadores:
        tarefa = asyncio.create_task(trab.executar(), name=trab.id_trabalhador)
        estado.tarefas_trabalhadores.append(tarefa)

    enfileirados = 0
    for info_arq in arquivos:
        chunks = dividir_codigo_fonte(info_arq["conteudo"])
        for idx, chunk in enumerate(chunks):
            info_chunk = f"{idx+1}/{len(chunks)}" if len(chunks) > 1 else ""
            for tipo_tarefa in TIPOS_TAREFA:
                id_tarefa = f"{tipo_tarefa}-{uuid.uuid4().hex[:8]}"
                await estado.fila_trab.enviar({
                    "id_tarefa": id_tarefa,
                    "nome_arquivo": info_arq["nome"],
                    "codigo_fonte": chunk,
                    "info_chunk": info_chunk,
                    "tipo_tarefa": tipo_tarefa,
                    "submetido_em": time.time(),
                })
                enfileirados += 1

    logger.info("Análise iniciada: %d arquivos → %d tarefas, %d trabalhadores por tipo", len(arquivos), enfileirados, TRABALHADORES_POR_TIPO)

    return web.json_response({
        "status": "iniciado",
        "arquivos": len(arquivos),
        "tarefas_enfileiradas": enfileirados,
        "trabalhadores_criados": len(estado.trabalhadores),
        "tipos_tarefa": TIPOS_TAREFA,
    })

async def lidar_metricas(request: web.Request) -> web.Response:
    snap = coletor.snapshot()
    snap["estatisticas_filas"] = barramento.todas_estatisticas()
    snap["eventos_ao_vivo"] = estado.eventos_ao_vivo[-100:]
    return web.json_response(snap)

async def lidar_resultados(request: web.Request) -> web.Response:
    if estado.relatorio_final:
        return web.json_response({"status": "pronto", "relatorio": estado.relatorio_final})

    msg = await estado.fila_final.receber(id_trabalhador="manipulador-http")
    if msg:
        estado.relatorio_final = msg.corpo.get("relatorio", {})
        await estado.fila_final.remover(msg.id_mensagem)
        return web.json_response({"status": "pronto", "relatorio": estado.relatorio_final})

    return web.json_response({"status": "pendente"})

async def lidar_estatisticas_filas(request: web.Request) -> web.Response:
    """GET /queue-stats — retorna as estatísticas de todas as filas."""
    return web.json_response(barramento.todas_estatisticas())

async def inicializar(app):
    estado.fila_trab, estado.fila_res, estado.fila_final = configurar_filas()
    logger.info("Filas inicializadas")

def criar_app() -> web.Application:
    app = web.Application(middlewares=[middleware_cors])
    app.on_startup.append(inicializar)
    app.router.add_post("/analisar", lidar_analisar)
    app.router.add_get("/metricas", lidar_metricas)
    app.router.add_get("/resultados", lidar_resultados)
    app.router.add_get("/queue-stats", lidar_estatisticas_filas) 
    
    return app

if __name__ == "__main__":
    porta = int(os.getenv("PORT", "8080"))
    app = criar_app()
    logger.info("Orquestrador iniciando na porta %d", porta)
    web.run_app(app, port=porta, access_log=None)