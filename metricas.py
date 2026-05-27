"""
metricas.py — Camada de observabilidade.

Coleta:
  - Latência por tarefa (início → conclusão)
  - Uso de tokens por chamada LLM
  - Taxas de erro por tipo de trabalhador
  - Vazão (tarefas/seg) em janela deslizante
  - Contadores por trabalhador
"""

import time
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class MetricaTarefa:
    id_tarefa: str
    nome_arquivo: str
    tipo_tarefa: str          # "geracao_teste" | "code_smell" | "documentacao" | "agregacao"
    id_trabalhador: str
    iniciado_em: float
    finalizado_em: Optional[float] = None
    status: str = "executando"  # executando | sucesso | erro | dlq
    tokens_entrada: int = 0
    tokens_saida: int = 0
    msg_erro: Optional[str] = None
    tentativa: int = 1

    @property
    def latencia_ms(self) -> Optional[float]:
        if self.finalizado_em:
            return round((self.finalizado_em - self.iniciado_em) * 1000, 1)
        return None

    def para_dicionario(self) -> dict:
        return {
            "id_tarefa": self.id_tarefa,
            "nome_arquivo": self.nome_arquivo,
            "tipo_tarefa": self.tipo_tarefa,
            "id_trabalhador": self.id_trabalhador,
            "status": self.status,
            "latencia_ms": self.latencia_ms,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "msg_erro": self.msg_erro,
            "tentativa": self.tentativa,
            "iniciado_em": self.iniciado_em,
            "finalizado_em": self.finalizado_em,
        }


class ColetorMetricas:
    """Armazenamento de métricas thread-safe."""

    def __init__(self, janela_vazao: float = 60.0):
        self._trava = threading.Lock()
        self._tarefas: Dict[str, MetricaTarefa] = {}
        self._tempos_conclusao: deque = deque()
        self._janela_vazao = janela_vazao
        self._contadores_trabalhador: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._eventos: List[dict] = []

    def iniciar_tarefa(
        self,
        id_tarefa: str,
        nome_arquivo: str,
        tipo_tarefa: str,
        id_trabalhador: str,
        tentativa: int = 1,
    ) -> MetricaTarefa:
        m = MetricaTarefa(
            id_tarefa=id_tarefa,
            nome_arquivo=nome_arquivo,
            tipo_tarefa=tipo_tarefa,
            id_trabalhador=id_trabalhador,
            iniciado_em=time.time(),
            tentativa=tentativa,
        )
        with self._trava:
            self._tarefas[id_tarefa] = m
            self._contadores_trabalhador[id_trabalhador]["iniciadas"] += 1
            self._adicionar_evento("inicio_tarefa", m)
        return m

    def finalizar_tarefa(
        self,
        id_tarefa: str,
        status: str = "sucesso",
        tokens_entrada: int = 0,
        tokens_saida: int = 0,
        msg_erro: Optional[str] = None,
        **kwargs # impede que quebre por receber argumentos não reconhecidos
    ):
        with self._trava:
            m = self._tarefas.get(id_tarefa)
            if not m:
                return
            m.finalizado_em = time.time()
            m.status = status
            m.tokens_entrada = tokens_entrada
            m.tokens_saida = tokens_saida
            m.msg_erro = msg_erro
            if status == "sucesso":
                self._tempos_conclusao.append(m.finalizado_em)
                self._contadores_trabalhador[m.id_trabalhador]["sucesso"] += 1
            else:
                self._contadores_trabalhador[m.id_trabalhador]["erro"] += 1
            self._adicionar_evento("fim_tarefa", m)

    def snapshot(self) -> dict:
        with self._trava:
            agora = time.time()
            corte = agora - self._janela_vazao
            while self._tempos_conclusao and self._tempos_conclusao[0] < corte:
                self._tempos_conclusao.popleft()

            tarefas = list(self._tarefas.values())
            concluidas = [t for t in tarefas if t.status == "sucesso"]
            erros    = [t for t in tarefas if t.status == "erro"]
            executando = [t for t in tarefas if t.status == "executando"]

            latencias = [t.latencia_ms for t in concluidas if t.latencia_ms]
            med_lat = round(sum(latencias) / len(latencias), 1) if latencias else 0
            max_lat = round(max(latencias), 1) if latencias else 0
            p95_lat = round(sorted(latencias)[int(len(latencias) * 0.95)], 1) if len(latencias) >= 5 else max_lat

            total_tokens_in = sum(t.tokens_entrada for t in concluidas)
            total_tokens_out = sum(t.tokens_saida for t in concluidas)

            return {
                "vazao_por_min": len(self._tempos_conclusao),
                "total_tarefas": len(tarefas),
                "concluidas": len(concluidas),
                "executando": len(executando),
                "erros": len(erros),
                "latencia_med_ms": med_lat,
                "latencia_p95_ms": p95_lat,
                "latencia_max_ms": max_lat,
                "total_tokens_entrada": total_tokens_in,
                "total_tokens_saida": total_tokens_out,
                "contadores_trabalhadores": {k: dict(v) for k, v in self._contadores_trabalhador.items()},
                "tarefas": [t.para_dicionario() for t in tarefas],
                "eventos": self._eventos[-200:],
            }

    def _adicionar_evento(self, tipo_evento: str, m: MetricaTarefa):
        self._eventos.append({
            "ts": time.time(),
            "evento": tipo_evento,
            "id_tarefa": m.id_tarefa,
            "id_trabalhador": m.id_trabalhador,
            "tipo_tarefa": m.tipo_tarefa,
            "nome_arquivo": m.nome_arquivo,
            "status": m.status,
            "latencia_ms": m.latencia_ms,
        })

# Singleton
coletor = ColetorMetricas()