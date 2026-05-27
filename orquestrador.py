"""
orquestrador.py — Orquestrador, API Gateway e Broker SQS simulado.
"""
import asyncio
import json
import logging
import os
import time
import uuid
import subprocess
import sys
from aiohttp import web
from aiohttp.web_middlewares import middleware

from limpador_json import extrair_json_robusto
from mensageria import barramento
from metricas import coletor
from cliente_llm import chamar_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)-20s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("orquestrador")

processos_workers = []
TIPOS_TAREFA = ["geracao_teste", "code_smell", "documentacao"]
TRABALHADORES_POR_TIPO = 1

# ==========================================
# GESTÃO DE WORKERS REAIS (Subprocessos SO)
# ==========================================
def iniciar_processos_paralelos():
    for tipo in TIPOS_TAREFA:
        for i in range(TRABALHADORES_POR_TIPO):
            wid = f"{tipo}-trab-{i+1}"
            p = subprocess.Popen([sys.executable, "trabalhadores.py", "--tipo", tipo, "--id", wid])
            processos_workers.append(p)
    logger.info("🚀 %d Trabalhadores em processos SO independentes (Paralelismo Real) iniciados!", len(processos_workers))

async def limpar_processos(app):
    for p in processos_workers:
        p.terminate()

# ==========================================
# MOTOR DE REDUCE E TELEMETRIA
# ==========================================
estado = {"relatorio_final": None}

async def loop_agregador_reduce(total_arquivos_esperados: int):
    fila_res = barramento.obter_fila("fila-resultado")
    resultados_coletados = []

    logger.info("Agregador iniciado, aguardando %d fragmentos...", total_arquivos_esperados)
    while len(resultados_coletados) < total_arquivos_esperados:
        msg = await fila_res.receber(id_trabalhador="agregador-reduce")
        if msg:
            resultados_coletados.append(msg.corpo)
            await fila_res.remover(msg.id_mensagem)
        else:
            await asyncio.sleep(0.5)

    logger.info("Todos fragmentos coletados. Iniciando LLM Reduce...")
    try:
        resultado_llm = await chamar_llm("agregador_v1.md", json.dumps(resultados_coletados, ensure_ascii=False))
        
        # Garante a extração limpa do JSON do relatório executivo
        texto_limpo = extrair_json_robusto(resultado_llm["texto"])
        estado["relatorio_final"] = json.loads(texto_limpo)
        
    except Exception as e:
        estado["relatorio_final"] = {"erro": "Falha na agregação", "detalhe": str(e)}

async def loop_telemetria():
    fila_evt = barramento.obter_fila("fila-eventos")
    while True:
        msg = await fila_evt.receber(id_trabalhador="telemetria")
        if msg:
            dados = msg.corpo
            acao = dados.pop("acao")
            if acao == "iniciar": coletor.iniciar_tarefa(**dados)
            elif acao == "finalizar": coletor.finalizar_tarefa(**dados)
            await fila_evt.remover(msg.id_mensagem)
        else:
            await asyncio.sleep(0.5)

# ==========================================
# ENDPOINTS HTTP E ROTAS DE FILA
# ==========================================
@middleware
async def middleware_cors(request, handler):
    resp = await handler(request) if request.method != "OPTIONS" else web.Response()
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# Simula AWS SQS via REST para comunicação dos processos
async def api_fila_enviar(req):
    msg = await barramento.obter_fila(req.match_info['nome']).enviar(await req.json())
    return web.json_response(msg.para_dicionario())

async def api_fila_receber(req):
    msg = await barramento.obter_fila(req.match_info['nome']).receber(req.query.get("trab", "desc"))
    return web.json_response(msg.para_dicionario()) if msg else web.json_response({"erro": "vazia"}, status=404)

async def api_fila_remover(req):
    ok = await barramento.obter_fila(req.match_info['nome']).remover(req.match_info['id'])
    return web.json_response({"ok": ok})

async def api_fila_rejeitar(req):
    dados = await req.json()
    ok = await barramento.obter_fila(req.match_info['nome']).rejeitar(req.match_info['id'], dados.get("atraso", 0.0))
    return web.json_response({"ok": ok})

async def lidar_analisar(request: web.Request) -> web.Response:
    arquivos = []
    tipo_conteudo = request.content_type or ""

    # Restaurando a leitura de arquivos multipart que você tinha perfeitamente no código original!
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

    total_chunks = len(arquivos) * len(TIPOS_TAREFA)
    estado["relatorio_final"] = None
    asyncio.create_task(loop_agregador_reduce(total_chunks))

    for arq in arquivos:
        for tipo in TIPOS_TAREFA:
            # Envia direto para a fila especializada do tipo
            fila_trab = barramento.obter_fila(f"fila-trabalho-{tipo}")
            await fila_trab.enviar({
                "id_tarefa": f"{tipo}-{uuid.uuid4().hex[:6]}",
                "nome_arquivo": arq["nome"],
                "codigo_fonte": arq["conteudo"],
                "tipo_tarefa": tipo
            })

    return web.json_response({"status": "MapReduce Iniciado", "tarefas": total_chunks})

async def lidar_metricas(request): 
    return web.json_response(
        coletor.snapshot(), 
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False)
    )

async def lidar_resultados(request): 
    return web.json_response(
        {"relatorio": estado["relatorio_final"]}, 
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False)
    )

async def inicializar(app):
    for tipo in TIPOS_TAREFA:
        barramento.criar_fila(f"fila-trabalho-{tipo}", timeout_visibilidade=60)
    barramento.criar_fila("fila-resultado", timeout_visibilidade=60)
    barramento.criar_fila("fila-eventos", timeout_visibilidade=10)
    asyncio.create_task(loop_telemetria())
    iniciar_processos_paralelos()

def criar_app() -> web.Application:
    app = web.Application(middlewares=[middleware_cors])
    app.on_startup.append(inicializar)
    app.on_cleanup.append(limpar_processos)

    app.router.add_post("/analisar", lidar_analisar)
    app.router.add_get("/metricas", lidar_metricas)
    app.router.add_get("/resultados", lidar_resultados)

    # Endpoints do SQS Simulado
    app.router.add_post("/fila/{nome}/enviar", api_fila_enviar)
    app.router.add_get("/fila/{nome}/receber", api_fila_receber)
    app.router.add_post("/fila/{nome}/remover/{id}", api_fila_remover)
    app.router.add_post("/fila/{nome}/rejeitar/{id}", api_fila_rejeitar)
    return app

if __name__ == "__main__":
    web.run_app(criar_app(), port=8080, access_log=None)