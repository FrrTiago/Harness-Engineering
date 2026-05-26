"""
trabalhadores.py — Processo Trabalhador Paralelo Distribuído.
Roda como um processo independente do SO e se comunica via HTTP simulando SQS.
"""
import asyncio
import json
import logging
import time
import os
import argparse
from typing import Dict, Any

from mensageria import FilaDistribuida
from cliente_llm import chamar_llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("trabalhador-distribuido")

MAPA_PROMPTS = {
    "geracao_teste":  "gerador_testes_v1.md",
    "code_smell":     "analisador_smells_v1.md",
    "documentacao":   "gerador_doc_v1.md",
}

class TrabalhadorAnalise:
    def __init__(self, id_trabalhador: str, tipo_tarefa: str):
        self.id_trabalhador = id_trabalhador
        self.tipo_tarefa = tipo_tarefa
        self.fila_entrada = FilaDistribuida("fila-trabalho")
        self.fila_saida = FilaDistribuida("fila-resultado")
        self.fila_eventos = FilaDistribuida("fila-eventos") # Telemetria de rede

    async def executar(self):
        logger.info("[%s] Iniciado na rede. Consumindo fila-trabalho.", self.id_trabalhador)
        while True:
            msg = await self.fila_entrada.receber(id_trabalhador=self.id_trabalhador)
            if not msg:
                await asyncio.sleep(1.0)
                continue
            
            # Filtra apenas mensagens da sua especialidade
            if msg.corpo.get("tipo_tarefa") != self.tipo_tarefa:
                await self.fila_entrada.rejeitar(msg.id_mensagem, atraso=0.5)
                continue

            await self._processar_mensagem(msg)

    async def _processar_mensagem(self, msg):
        corpo = msg.corpo
        id_tarefa = corpo.get("id_tarefa")
        
        await self.fila_eventos.enviar({"acao": "iniciar", "id_tarefa": id_tarefa, "nome_arquivo": corpo["nome_arquivo"], "tipo_tarefa": self.tipo_tarefa, "id_trabalhador": self.id_trabalhador, "tentativa": msg.contagem_recebimento})

        try:
            codigo_fonte = corpo["codigo_fonte"]
            msg_usuario = f"Arquivo: {corpo['nome_arquivo']}\n```python\n{codigo_fonte}\n```"
            
            resultado_llm = await chamar_llm(MAPA_PROMPTS[self.tipo_tarefa], msg_usuario)
            try:
                analisado = json.loads(resultado_llm["texto"])
            except json.JSONDecodeError:
                analisado = {"bruto": resultado_llm["texto"], "erro_parse": True}
            
            resultado_final = {**analisado, "tokens_entrada": resultado_llm["tokens_entrada"], "tokens_saida": resultado_llm["tokens_saida"]}
            
            await self.fila_saida.enviar({"id_tarefa": id_tarefa, "tipo_tarefa": self.tipo_tarefa, "resultado": resultado_final})
            await self.fila_entrada.remover(msg.id_mensagem)
            
            await self.fila_eventos.enviar({"acao": "finalizar", "id_tarefa": id_tarefa, "status": "sucesso", **resultado_final})
            logger.info("[%s] Tarefa %s concluída.", self.id_trabalhador, id_tarefa)

        except Exception as exc:
            await self.fila_eventos.enviar({"acao": "finalizar", "id_tarefa": id_tarefa, "status": "erro", "msg_erro": str(exc)})
            await self.fila_entrada.rejeitar(msg.id_mensagem, atraso=min(2 ** msg.contagem_recebimento, 30))

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", required=True, choices=["geracao_teste", "code_smell", "documentacao"])
    parser.add_argument("--id", required=True)
    args = parser.parse_args()
    
    trab = TrabalhadorAnalise(id_trabalhador=args.id, tipo_tarefa=args.tipo)
    await trab.executar()

if __name__ == "__main__":
    asyncio.run(main())