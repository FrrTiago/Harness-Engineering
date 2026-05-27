import requests
import matplotlib.pyplot as plt
from collections import defaultdict

# 1. Coleta os dados em tempo real da API do Orquestrador
url = "http://localhost:8080/metricas"
try:
    dados = requests.get(url).json()
except Exception as e:
    print(f"❌ Erro ao conectar no orquestrador: {e}")
    exit()

tarefas = dados.get("tarefas", [])
eventos = dados.get("eventos", [])

if not tarefas:
    print("⚠️ Nenhuma tarefa encontrada no histórico.")
    exit()

# --- NOVO PROCESSAMENTO: Agrupando dados duplicados por tipo ---
latencias_por_tipo = defaultdict(list)
tokens_in_por_tipo = defaultdict(int)
tokens_out_por_tipo = defaultdict(int)

for t in tarefas:
    if t["status"] == "sucesso":
        tipo = t["tipo_tarefa"]
        latencias_por_tipo[tipo].append(t["latencia_ms"])
        tokens_in_por_tipo[tipo] += t["tokens_entrada"]
        tokens_out_por_tipo[tipo] += t["tokens_saida"]

# Calcula as médias reais eliminando qualquer duplicidade no eixo X
tipos = list(latencias_por_tipo.keys())
latencias = [sum(lista) / len(lista) for lista in latencias_por_tipo.values()]
tokens_in = [tokens_in_por_tipo[tipo] for tipo in tipos]
tokens_out = [tokens_out_por_tipo[tipo] for tipo in tipos]

# ========================================================
# 📊 GRÁFICO 1: LATÊNCIA MÉDIA POR TAREFA
# ========================================================
if latencias:
    fig, ax = plt.subplots(figsize=(8, 4))
    cores = ['#3498db', '#e74c3c', '#2ecc71']
    ax.bar(tipos, latencias, color=cores[:len(tipos)], width=0.6)
    
    ax.set_title("Latência Média por Tipo de Análise (Fase Map)")
    ax.set_ylabel("Tempo Médio (ms)")
    ax.set_xlabel("Trabalhadores Especialistas")
    ax.grid(axis='y', linestyle="--", alpha=0.5)
    
    # Agora a posição do texto 'i' casa perfeitamente com a barra única de cada categoria
    for i, v in enumerate(latencias):
        ax.text(i, v + (v * 0.02), f"{v:.0f} ms", ha='center', fontweight='bold')
        
    plt.tight_layout()
    plt.savefig("graficos/grafico_latencia.png")
    plt.close()
    print("✨ Gráfico 'grafico_latencia.png' corrigido e gerado!")

# ========================================================
# 🪙 GRÁFICO 2: CONSUMO ACUMULADO DE TOKENS
# ========================================================
if tokens_in:
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(tipos))
    
    ax.bar([i - 0.2 for i in x], tokens_in, width=0.4, label='Tokens Entrada (Total)', color='#9b59b6')
    ax.bar([i + 0.2 for i in x], tokens_out, width=0.4, label='Tokens Saída (Total)', color='#f1c40f')
    
    ax.set_xticks(x)
    ax.set_xticklabels(tipos)
    ax.set_title("Volumetria Total de Tokens Trafegados por Agente")
    ax.set_ylabel("Quantidade de Tokens")
    ax.grid(axis='y', linestyle="--", alpha=0.5)
    ax.legend()
    
    plt.tight_layout()
    plt.savefig("graficos/grafico_tokens.png")
    plt.close()
    print("✨ Gráfico 'grafico_tokens.png' corrigido e gerado!")

# ========================================================
# 📈 GRÁFICO 3: THROUGHPUT (Mantenha o código igual ao anterior)
# ========================================================
conclusoes = [e for e in eventos if e["evento"] == "fim_tarefa" and e["status"] == "sucesso"]
if conclusoes:
    conclusoes.sort(key=lambda x: x["ts"])
    ts_inicial = tarefas[0].get("iniciado_em", conclusoes[0]["ts"])
    
    tempos_decorridos = [0.0]
    tarefas_acumuladas = [0]
    
    for idx, evento in enumerate(conclusoes, 1):
        tempo_relativo = evento["ts"] - ts_inicial
        tempos_decorridos.append(tempo_relativo)
        tarefas_acumuladas.append(idx)
        
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.step(tempos_decorridos, tarefas_acumuladas if 'tarefas_acumuladas' in locals() else tarefas_acumuladas, where='post', color='#2ecc71', linewidth=2.5, marker='o')
    ax.set_title("Vazão Temporal (Throughput) - Conclusão de Fragmentos")
    ax.set_xlabel("Tempo Decorrido do Experimento (segundos)")
    ax.set_ylabel("Total Acumulado de Tarefas Concluídas")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0, top=max(tarefas_acumuladas) + 1)
    
    plt.tight_layout()
    plt.savefig("graficos/grafico_throughput.png")
    plt.close()
    print("✨ Gráfico 'grafico_throughput.png' gerado!")