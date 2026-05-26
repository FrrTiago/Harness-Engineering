"""
trabalhadores.py — Trabalhadores paralelos assíncronos.

Arquitetura (Tema 7 — Programação Distribuída e Paralela):

Cada trabalhador é uma corrotina independente. Não compartilham estado mutável — 
toda coordenação ocorre através das filas de mensagens.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Callable

from mensageria import Fila
from metricas import coletor
from cliente_llm import chamar_llm

logger = logging.getLogger("trabalhadores")

# Mapeamento tipo_tarefa → nome do arquivo de prompt do sistema
MAPA_PROMPTS = {
    "geracao_teste":  "gerador_testes_v1.md",
    "code_smell":     "analisador_smells_v1.md",
    "documentacao":   "gerador_doc_v1.md",
    "agregacao":      "agregador_v1.md",
}

class TrabalhadorBase:
    INTERVALO_PESQUISA = 0.2  

    def __init__(
        self,
        id_trabalhador: str,
        fila_entrada: Fila,
        fila_saida: Optional[Fila],
        tipo_tarefa: str,
        ao_receber_evento: Optional[Callable] = None,
    ):
        self.id_trabalhador = id_trabalhador
        self.fila_entrada = fila_entrada
        self.fila_saida = fila_saida
        self.tipo_tarefa = tipo_tarefa
        self.ao_receber_evento = ao_receber_evento
        self._rodando = False
        self._processados = 0
        self._erros = 0

    async def executar(self):
        self._rodando = True
        logger.info("[%s] iniciado — aguardando tarefas", self.id_trabalhador)
        while self._rodando:
            msg = await self.fila_entrada.receber(id_trabalhador=self.id_trabalhador)
            if msg is None:
                await asyncio.sleep(self.INTERVALO_PESQUISA)
                continue
            await self._manipular(msg)

    async def _manipular(self, msg):
        corpo = msg.corpo
        id_tarefa = corpo.get("id_tarefa", msg.id_mensagem)
        nome_arquivo = corpo.get("nome_arquivo", "desconhecido")

        metric = coletor.iniciar_tarefa(
            id_tarefa=id_tarefa,
            nome_arquivo=nome_arquivo,
            tipo_tarefa=self.tipo_tarefa,
            id_trabalhador=self.id_trabalhador,
            tentativa=msg.contagem_recebimento,
        )
        self._emitir("inicio_tarefa", id_tarefa, nome_arquivo)

        try:
            resultado = await self._processar(corpo)
            await self.fila_entrada.remover(msg.id_mensagem)
            self._processados += 1

            coletor.finalizar_tarefa(
                id_tarefa=id_tarefa,
                status="sucesso",
                tokens_entrada=resultado.get("tokens_entrada", 0),
                tokens_saida=resultado.get("tokens_saida", 0),
            )
            self._emitir("fim_tarefa", id_tarefa, nome_arquivo, resultado)

            if self.fila_saida:
                await self.fila_saida.enviar({
                    "id_tarefa": id_tarefa,
                    "nome_arquivo": nome_arquivo,
                    "tipo_tarefa": self.tipo_tarefa,
                    "resultado": resultado,
                    "id_trabalhador": self.id_trabalhador,
                })

        except Exception as exc:
            self._erros += 1
            backoff = min(2 ** msg.contagem_recebimento, 30)
            logger.error(
                "[%s] ERRO tarefa=%s tentativa=%d backoff=%.0fs: %s",
                self.id_trabalhador, id_tarefa, msg.contagem_recebimento, backoff, exc,
            )
            coletor.finalizar_tarefa(id_tarefa=id_tarefa, status="erro", msg_erro=str(exc)[:300])
            self._emitir("erro_tarefa", id_tarefa, nome_arquivo, {"erro": str(exc)})
            await self.fila_entrada.rejeitar(msg.id_mensagem, atraso=backoff)

    async def _processar(self, corpo: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def _emitir(self, evento: str, id_tarefa: str, nome_arquivo: str, dados: dict = None):
        if self.ao_receber_evento:
            self.ao_receber_evento({
                "evento": evento,
                "id_trabalhador": self.id_trabalhador,
                "tipo_tarefa": self.tipo_tarefa,
                "id_tarefa": id_tarefa,
                "nome_arquivo": nome_arquivo,
                "ts": time.time(),
                **(dados or {}),
            })


class TrabalhadorAnalise(TrabalhadorBase):
    async def _processar(self, corpo: Dict[str, Any]) -> Dict[str, Any]:
        arquivo_prompt = MAPA_PROMPTS[self.tipo_tarefa]
        codigo_fonte = corpo["codigo_fonte"]
        nome_arquivo = corpo["nome_arquivo"]
        info_chunk = corpo.get("info_chunk", "")

        msg_usuario = (
            f"Arquivo: {nome_arquivo}\n"
            + (f"Chunk: {info_chunk}\n" if info_chunk else "")
            + f"\n```python\n{codigo_fonte}\n```"
        )

        resultado_llm = await chamar_llm(
            arquivo_prompt_sistema=arquivo_prompt,
            mensagem_usuario=msg_usuario,
        )

        if self.tipo_tarefa in ("code_smell", "documentacao"):
            try:
                analisado = json.loads(resultado_llm["texto"])
            except json.JSONDecodeError:
                analisado = {"bruto": resultado_llm["texto"], "erro_parse": True}
        else:
            analisado = {"codigo": resultado_llm["texto"]}

        return {
            **analisado,
            "tokens_entrada": resultado_llm["tokens_entrada"],
            "tokens_saida": resultado_llm["tokens_saida"],
            "latencia_ms": resultado_llm["latencia_ms"],
            "tentativas": resultado_llm["tentativas"],
        }


class TrabalhadorAgregador(TrabalhadorBase):
    def __init__(self, *args, total_arquivos: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_arquivos = total_arquivos
        self._resultados: list = []
        self._trava = asyncio.Lock()

    async def executar(self):
        self._rodando = True
        logger.info("[%s] agregador iniciado — aguardando %d arquivos", self.id_trabalhador, self.total_arquivos)
        while self._rodando:
            msg = await self.fila_entrada.receber(id_trabalhador=self.id_trabalhador)
            if msg is None:
                await asyncio.sleep(self.INTERVALO_PESQUISA)
                continue

            async with self._trava:
                self._resultados.append(msg.corpo)
                logger.info("[%s] %d/%d resultados coletados", self.id_trabalhador, len(self._resultados), self.total_arquivos)
                await self.fila_entrada.remover(msg.id_mensagem)

                if len(self._resultados) >= self.total_arquivos:
                    await self._agregar()
                    self._rodando = False

    async def _agregar(self):
        id_tarefa = f"agregacao-{uuid.uuid4().hex[:8]}"
        coletor.iniciar_tarefa(id_tarefa, "todos_arquivos", "agregacao", self.id_trabalhador)
        self._emitir("inicio_tarefa", id_tarefa, "todos_arquivos")

        try:
            msg_usuario = json.dumps(self._resultados, indent=2, ensure_ascii=False)
            resultado_llm = await chamar_llm(
                arquivo_prompt_sistema="agregador_v1.md",
                mensagem_usuario=msg_usuario,
            )
            try:
                relatorio = json.loads(resultado_llm["texto"])
            except json.JSONDecodeError:
                relatorio = {"bruto": resultado_llm["texto"]}

            coletor.finalizar_tarefa(
                id_tarefa, "sucesso",
                tokens_entrada=resultado_llm["tokens_entrada"],
                tokens_saida=resultado_llm["tokens_saida"],
            )
            self._emitir("fim_tarefa", id_tarefa, "todos_arquivos", {"relatorio": relatorio})

            if self.fila_saida:
                await self.fila_saida.enviar({
                    "id_tarefa": id_tarefa,
                    "tipo": "relatorio_final",
                    "relatorio": relatorio,
                    "id_trabalhador": self.id_trabalhador,
                })
        except Exception as exc:
            coletor.finalizar_tarefa(id_tarefa, "erro", msg_erro=str(exc))
            self._emitir("erro_tarefa", id_tarefa, "todos_arquivos", {"erro": str(exc)})

    async def _processar(self, corpo):
        pass


def criar_pool_trabalhadores(
    fila_trabalho: Fila,
    fila_resultado: Fila,
    fila_final: Fila,
    num_trabalhadores: int = 3,
    tipos_tarefa: list = None,
    total_arquivos: int = 1,
    ao_receber_evento: Optional[Callable] = None,
) -> list:
    if tipos_tarefa is None:
        tipos_tarefa = ["geracao_teste", "code_smell", "documentacao"]

    trabalhadores = []
    for tt in tipos_tarefa:
        for i in range(num_trabalhadores):
            wid = f"{tt}-trab-{i+1}"
            trab = TrabalhadorAnalise(
                id_trabalhador=wid,
                fila_entrada=fila_trabalho,
                fila_saida=fila_resultado,
                tipo_tarefa=tt,
                ao_receber_evento=ao_receber_evento,
            )
            trabalhadores.append(trab)

    agregador = TrabalhadorAgregador(
        id_trabalhador="agregador-1",
        fila_entrada=fila_resultado,
        fila_saida=fila_final,
        tipo_tarefa="agregacao",
        total_arquivos=total_arquivos * len(tipos_tarefa),
        ao_receber_evento=ao_receber_evento,
    )
    trabalhadores.append(agregador)
    return trabalhadores