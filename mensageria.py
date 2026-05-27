"""
mensageria.py — Sistema de Fila Híbrido (Memória + HTTP Distribuído)
"""

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
from collections import defaultdict
import httpx

logger = logging.getLogger("mensageria")

@dataclass
class Mensagem:
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
            "visivel_em": self.visivel_em,
            "id_trabalhador": self.id_trabalhador
        }

# --- MOTOR LOCAL (Roda no Orquestrador) ---
class FilaLocal:
    def __init__(self, nome: str, max_recebimentos: int = 3, timeout_visibilidade: float = 30.0, dlq=None):
        self.nome = nome
        self.max_recebimentos = max_recebimentos
        self.timeout_visibilidade = timeout_visibilidade
        self.dlq = dlq
        self._fila: asyncio.Queue = asyncio.Queue()
        self._em_voo: Dict[str, Mensagem] = {}
        self._estatisticas = defaultdict(int)

    async def enviar(self, corpo: Dict[str, Any]) -> Mensagem:
        msg = Mensagem(corpo=corpo)
        await self._fila.put(msg)
        self._estatisticas["enviadas"] += 1
        return msg

    async def receber(self, id_trabalhador: str = "desc") -> Optional[Mensagem]:
        agora = time.time()
        expiradas = [id_m for id_m, m in self._em_voo.items() if m.visivel_em < agora]
        for id_m in expiradas:
            await self._fila.put(self._em_voo.pop(id_m))

        try:
            msg = self._fila.get_nowait()
        except asyncio.QueueEmpty:
            return None

        msg.contagem_recebimento += 1
        msg.id_trabalhador = id_trabalhador
        msg.visivel_em = time.time() + self.timeout_visibilidade
        self._em_voo[msg.id_mensagem] = msg
        self._estatisticas["recebidas"] += 1
        return msg

    async def remover(self, id_mensagem: str) -> bool:
        if id_mensagem in self._em_voo:
            del self._em_voo[id_mensagem]
            self._estatisticas["removidas"] += 1
            return True
        return False

    async def rejeitar(self, id_mensagem: str, atraso: float = 0.0) -> bool:
        if id_mensagem in self._em_voo:
            msg = self._em_voo.pop(id_mensagem)
            msg.visivel_em = time.time() + atraso
            await self._fila.put(msg)
            self._estatisticas["rejeitadas"] += 1
            return True
        return False

    def estatisticas(self) -> dict:
        return {"fila": self.nome, "em_voo": len(self._em_voo), "profundidade": self._fila.qsize(), **dict(self._estatisticas)}

class BarramentoMensagensLocal:
    def __init__(self):
        self._filas: Dict[str, FilaLocal] = {}
    def criar_fila(self, nome: str, **kwargs) -> FilaLocal:
        self._filas[nome] = FilaLocal(nome, **kwargs)
        return self._filas[nome]
    def obter_fila(self, nome: str) -> FilaLocal:
        return self._filas[nome]
    def todas_estatisticas(self) -> List[dict]:
        return [q.estatisticas() for q in self._filas.values()]

barramento = BarramentoMensagensLocal()

# --- CLIENTE DISTRIBUÍDO VIA REDE (Simula o SQS via HTTP para os Trabalhadores) ---
class FilaDistribuida:
    def __init__(self, nome: str, base_url: str = "http://127.0.0.1:8080"):
        self.nome = nome
        self.base_url = f"{base_url}/fila/{nome}"
        self.cliente = httpx.AsyncClient(timeout=30.0)

    async def enviar(self, corpo: Dict[str, Any]) -> Mensagem:
        resp = await self.cliente.post(f"{self.base_url}/enviar", json=corpo)
        return Mensagem(**resp.json())

    async def receber(self, id_trabalhador: str = "desc") -> Optional[Mensagem]:
        resp = await self.cliente.get(f"{self.base_url}/receber", params={"trab": id_trabalhador})
        if resp.status_code == 200:
            return Mensagem(**resp.json())
        return None

    async def remover(self, id_mensagem: str) -> bool:
        resp = await self.cliente.post(f"{self.base_url}/remover/{id_mensagem}")
        return resp.json().get("ok", False)

    async def rejeitar(self, id_mensagem: str, atraso: float = 0.0) -> bool:
        resp = await self.cliente.post(f"{self.base_url}/rejeitar/{id_mensagem}", json={"atraso": atraso})
        return resp.json().get("ok", False)