"""
mensageria.py — Simulação de fila de mensagens distribuída.

Simula a semântica do AWS SQS:
  - Múltiplas filas identificadas por nome
  - Timeout de visibilidade (mensagem oculta enquanto processada)
  - Retentativa com backoff exponencial
  - Dead Letter Queue após atingir max_receive_count
  - Envelope de mensagem estruturado
"""

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from collections import defaultdict

logger = logging.getLogger("mensageria")


@dataclass
class Mensagem:
    """Envelope de mensagem — reflete o modelo de mensagem do SQS."""
    id_mensagem: str = field(default_factory=lambda: str(uuid.uuid4()))
    corpo: Dict[str, Any] = field(default_factory=dict)
    contagem_recebimento: int = 0
    enfileirado_em: float = field(default_factory=time.time)
    visivel_em: float = field(default_factory=time.time)
    id_trabalhador: Optional[str] = None

    def para_dicionario(self) -> dict:
        return {
            "id_mensagem": self.id_mensagem,
            "corpo": self.corpo,
            "contagem_recebimento": self.contagem_recebimento,
            "enfileirado_em": self.enfileirado_em,
        }


class Fila:
    """
    Fila assíncrona em memória com semântica semelhante ao SQS.
    """

    def __init__(
        self,
        nome: str,
        max_recebimentos: int = 3,
        timeout_visibilidade: float = 30.0,
        dlq: Optional["Fila"] = None,
    ):
        self.nome = nome
        self.max_recebimentos = max_recebimentos
        self.timeout_visibilidade = timeout_visibilidade
        self.dlq = dlq
        self._fila: asyncio.Queue = asyncio.Queue()
        self._em_voo: Dict[str, Mensagem] = {}  
        self._estatisticas = defaultdict(int)

    # ------------------------------------------------------------------ #
    # API Pública                                                        #
    # ------------------------------------------------------------------ #

    async def enviar(self, corpo: Dict[str, Any]) -> Mensagem:
        """Enfileira uma nova mensagem."""
        msg = Mensagem(corpo=corpo)
        await self._fila.put(msg)
        self._estatisticas["enviadas"] += 1
        logger.debug("[%s] ENVIADA msg=%s", self.nome, msg.id_mensagem[:8])
        return msg

    async def receber(self, id_trabalhador: str = "desconhecido") -> Optional[Mensagem]:
        """
        Recebimento não bloqueante. Retorna None se a fila estiver vazia.
        Incrementa a contagem; move para a DLQ se esgotada.
        """
        await self._reenfileirar_expiradas()

        try:
            msg = self._fila.get_nowait()
        except asyncio.QueueEmpty:
            return None

        msg.contagem_recebimento += 1
        msg.id_trabalhador = id_trabalhador
        msg.visivel_em = time.time() + self.timeout_visibilidade

        if msg.contagem_recebimento > self.max_recebimentos:
            await self._enviar_para_dlq(msg)
            return None

        self._em_voo[msg.id_mensagem] = msg
        self._estatisticas["recebidas"] += 1
        logger.debug(
            "[%s] RECV trabalhador=%s msg=%s tentativa=%d",
            self.nome, id_trabalhador, msg.id_mensagem[:8], msg.contagem_recebimento,
        )
        return msg

    async def remover(self, id_mensagem: str) -> bool:
        """Confirma processamento bem-sucedido — remove das mensagens em voo."""
        if id_mensagem in self._em_voo:
            del self._em_voo[id_mensagem]
            self._estatisticas["removidas"] += 1
            logger.debug("[%s] REMOVIDA msg=%s", self.nome, id_mensagem[:8])
            return True
        return False

    async def rejeitar(self, id_mensagem: str, atraso: float = 0.0) -> bool:
        """
        NACK (Negative-acknowledge): torna a mensagem visível novamente após `atraso`.
        Usado para retentativas com backoff.
        """
        if id_mensagem in self._em_voo:
            msg = self._em_voo.pop(id_mensagem)
            msg.visivel_em = time.time() + atraso
            await self._fila.put(msg)
            self._estatisticas["rejeitadas"] += 1
            logger.debug(
                "[%s] NACK msg=%s reenfileirar_em=%.1fs", self.nome, id_mensagem[:8], atraso
            )
            return True
        return False

    def estatisticas(self) -> dict:
        return {
            "fila": self.nome,
            "em_voo": len(self._em_voo),
            "profundidade": self._fila.qsize(),
            **dict(self._estatisticas),
        }

    # ------------------------------------------------------------------ #
    # Uso Interno                                                        #
    # ------------------------------------------------------------------ #

    async def _reenfileirar_expiradas(self):
        """Retorna mensagens expiradas para a fila (timeout de visibilidade)."""
        agora = time.time()
        expiradas = [
            id_m for id_m, msg in self._em_voo.items() if msg.visivel_em < agora
        ]
        for id_m in expiradas:
            msg = self._em_voo.pop(id_m)
            logger.warning(
                "[%s] TIMEOUT_VISIBILIDADE msg=%s — reenfileirando", self.nome, id_m[:8]
            )
            await self._fila.put(msg)

    async def _enviar_para_dlq(self, msg: Mensagem):
        self._estatisticas["enviadas_dlq"] += 1
        logger.error(
            "[%s] DLQ msg=%s após %d tentativas", self.nome, msg.id_mensagem[:8], msg.contagem_recebimento
        )
        if self.dlq:
            await self.dlq.enviar({**msg.corpo, "_motivo_dlq": "max_recebimentos_excedidos"})


class BarramentoMensagens:
    """
    Registro de filas nomeadas. Atua como equivalente em processo de um cliente SQS.
    """
    def __init__(self):
        self._filas: Dict[str, Fila] = {}

    def criar_fila(self, nome: str, **kwargs) -> Fila:
        q = Fila(nome, **kwargs)
        self._filas[nome] = q
        return q

    def obter_fila(self, nome: str) -> Fila:
        return self._filas[nome]

    def todas_estatisticas(self) -> List[dict]:
        return [q.estatisticas() for q in self._filas.values()]

# Singleton a nível de módulo
barramento = BarramentoMensagens()