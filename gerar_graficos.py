import requests
import matplotlib.pyplot as plt

# 1. Coleta os dados em tempo real da API do Orquestrador
url = "http://localhost:8080/metricas"
try:
    dados = requests.get(url).json()
except Exception as e:
    print(f"❌ Erro ao conectar no orquestrador. Certifique-se de que ele está rodando: {e}")
    exit()

tarefas = dados.get("tarefas", [])
eventos = dados.get("eventos", [])

if not tarefas:
    print("⚠️ Nenhuma tarefa encontrada no histórico do sistema de métricas.")
    exit()

# --- Processamento de Dados: Latência e Tokens ---
tipos = []
latencias = []
tokens_in = []
tokens_out = []

for t in tarefas:
    if t["status"] == "sucesso":
        tipos.append(t["tipo_tarefa"])
        latencias.append(t["latencia_ms"])
        tokens_in.append(t["tokens_entrada"])
        tokens_out.append(t["tokens_saida"])

# ========================================================
# 📊 GRÁFICO 1: LATÊNCIA POR TAREFA
# ========================================================
if latencias:
    fig, ax = plt.subplots(figsize=(8, 4))
    cores = ['#3498db', '#e74c3c', '#2ecc71']
    ax.bar(tipos, latencias, color=cores[:len(tipos)])
    
    ax.set_title("Latência por Tipo de Análise (Fase Map)")
    ax.set_ylabel("Tempo (ms)")
    ax.set_xlabel("Trabalhadores Especialistas")
    ax.grid(axis='y', linestyle="--", alpha=0.5)
    
    # Adiciona os rótulos de tempo acima de cada barra
    for i, v in enumerate(latencias):
        ax.text(i, v + (v * 0.02), f"{v:.0f} ms", ha='center', fontweight='bold')
        
    plt.tight_layout()
    plt.savefig("graficos/grafico_latencia.png")
    plt.close()
    print("✨ Gráfico 'grafico_latencia.png' gerado com sucesso!")

# ========================================================
# 🪙 GRÁFICO 2: CONSUMO DE TOKENS
# ========================================================
if tokens_in:
    fig, ax = plt.subplots(figsize=(8, 4))
    x = range(len(tipos))
    
    # Desenha barras agrupadas (Entrada vs Saída)
    ax.bar([i - 0.2 for i in x], tokens_in, width=0.4, label='Tokens Entrada (Prompt)', color='#9b59b6')
    ax.bar([i + 0.2 for i in x], tokens_out, width=0.4, label='Tokens Saída (Resposta)', color='#f1c40f')
    
    ax.set_xticks(x)
    ax.set_xticklabels(tipos)
    ax.set_title("Volumetria e Custo de Tokens por Agente")
    ax.set_ylabel("Quantidade de Tokens")
    ax.grid(axis='y', linestyle="--", alpha=0.5)
    ax.legend()
    
    plt.tight_layout()
    plt.savefig("graficos/grafico_tokens.png")
    plt.close()
    print("✨ Gráfico 'grafico_tokens.png' gerado com sucesso!")

# ========================================================
# 📈 GRÁFICO 3: THROUGHPUT (VAZÃO TEMPORAL)
# ========================================================
conclusoes = [e for e in eventos if e["evento"] == "fim_tarefa" and e["status"] == "sucesso"]
if conclusoes:
    # Ordena cronologicamente pelos registros de conclusão
    conclusoes.sort(key=lambda x: x["ts"])
    
    # Encontra o marco zero do experimento (momento em que a primeira tarefa iniciou)
    ts_inicial = tarefas[0].get("iniciado_em", conclusoes[0]["ts"])
    
    tempos_decorridos = [0.0]
    tarefas_acumuladas = [0]
    
    for idx, evento in enumerate(conclusoes, 1):
        tempo_relativo = evento["ts"] - ts_inicial
        tempos_decorridos.append(tempo_relativo)
        tarefas_acumuladas.append(idx)
        
    fig, ax = plt.subplots(figsize=(8, 4))
    # Desenha o gráfico em formato de escada (ideal para mensageria assíncrona)
    ax.step(tempos_decorridos, tarefas_acumuladas, where='post', color='#2ecc71', linewidth=2.5, marker='o')
    
    ax.set_title("Vazão Temporal (Throughput) - Conclusão de Fragmentos")
    ax.set_xlabel("Tempo Decorrido do Experimento (segundos)")
    ax.set_ylabel("Total Acumulado de Tarefas Concluídas")
    ax.grid(True, linestyle="--", alpha=0.5)
    
    # Ajusta os limites para dar respiro aos cantos
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0, top=max(tarefas_acumuladas) + 1)
    
    plt.tight_layout()
    plt.savefig("graficos/grafico_throughput.png")
    plt.close()
    print("✨ Gráfico 'grafico_throughput.png' gerado com sucesso!")
else:
    print("⚠️ Nenhum evento de sucesso foi localizado para montar a linha de throughput.")