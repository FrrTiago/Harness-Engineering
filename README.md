# Pipeline Distribuído de Análise de Código e Geração de Testes (Tema 7)

Este projeto é uma implementação de um sistema distribuído e paralelo projetado para realizar análises de código estático de forma concorrente utilizando Modelos de Linguagem de Larga Escala (LLMs). O sistema divide arquivos grandes de código-fonte, distribui as tarefas entre múltiplos *workers* assíncronos e, por fim, agrega os resultados (MapReduce).

O foco deste projeto é demonstrar conceitos avançados de **Programação Distribuída e Paralela**, **Engenharia de Contexto (Harness Engineering)** e **Tolerância a Falhas**.

## Arquitetura do Sistema

O sistema é construído sobre uma arquitetura orientada a eventos e filas (Produtor-Consumidor), garantindo isolamento de estado e paralelismo real:

* **Orquestrador (API HTTP):** Recebe o código-fonte, realiza o particionamento (*chunking*) matemático baseado em limites de linhas e enfileira as tarefas (Fase Map).
* **Barramento de Mensagens:** Fila em memória com semântica inspirada no AWS SQS, incluindo *Visibility Timeout* e *Dead Letter Queue* (DLQ).
* **Trabalhadores (Workers):** Corrotinas autônomas que processam três tipos de tarefas em paralelo:
* Geração de Testes Unitários.
* Identificação de Code Smells.
* Geração de Documentação Técnica.


* **Agregador:** Processo focado em aguardar os resultados parciais para compilar um relatório técnico final coeso (Fase Reduce).

## Principais Funcionalidades

* **Paralelismo Real:** Trabalhadores operam concorrentemente via `asyncio`, multiplicando a vazão (*throughput*).
* **Tolerância a Falhas:** Implementação de retentativas com *Backoff Exponencial e Jitter* para instabilidades de rede e roteamento automático para DLQ após sucessivas falhas.
* **Engenharia de Contexto:** Arquivos de *prompt* versionados e separados da lógica de aplicação, com diretrizes estritas de formatação JSON.
* **Observabilidade:** Monitoramento em tempo real de latência, consumo de tokens, saúde das filas e vazão de processamento.

---


## Tecnologias Utilizadas

* **Linguagem:** Python 3.9+
* **Bibliotecas Principais:** `aiohttp` (Servidor Web), `httpx` (Cliente HTTP Assíncrono), `asyncio`.
* **Inteligência Artificial:** API Anthropic (Modelo Claude 3.5 Sonnet).

---

## Instalação e Configuração

**1. Clone o repositório e acesse a pasta:**

```bash
git clone https://github.com/FrrTiago/Harness-Engineering
cd Harness-Engineering

```

**2. Instale as dependências:**

```bash
pip install aiohttp httpx requests

```

**3. Configure os Prompts do Sistema:**
Certifique-se de que a pasta `prompts/` existe na raiz do projeto e contém os seguintes arquivos (fornecidos na documentação do projeto):

* `gerador_testes_v1.md`
* `analisador_smells_v1.md`
* `gerador_doc_v1.md`
* `agregador_v1.md`

**4. Configure a Chave de API:**
No arquivo `cliente_llm.py`, insira sua chave da API no cabeçalho (ou configure para puxar de uma variável de ambiente `.env`):

```python
headers = {
    "Content-Type": "application/json",
    "anthropic-version": "2023-06-01",
    "x-api-key": "SUA_CHAVE_AQUI" 
}

```

---

## Como Executar

**1. Inicie o Orquestrador:**
Abra um terminal e inicie o servidor (ele rodará na porta `8080` por padrão):

```bash
python orquestrador.py

```

**2. Submeta uma carga de trabalho:**
Em outro terminal (ou utilizando ferramentas como Postman), envie um arquivo Python para análise:

```bash
# Usando o script de teste fornecido
python testar_api.py

# OU usando cURL diretamente
curl -X POST http://localhost:8080/analisar -F "file=@caminho/para/sistema_bancario.py"

```

---

## Endpoints de Observabilidade

Com o processamento em andamento, você pode monitorar o comportamento do sistema através das seguintes rotas `GET`:

* **Status das Filas:** Veja a profundidade da fila, mensagens em voo e envios para a DLQ.
```bash
Invoke-RestMethod http://localhost:8080/queue-stats  # Windows PowerShell
curl http://localhost:8080/queue-stats               # Linux/Mac

```


* **Métricas de Desempenho:** Acompanhe a latência, taxa de erro, *throughput* e consumo total de tokens.
```bash
curl http://localhost:8080/metricas

```


* **Relatório Final:** Após a conclusão do *Worker* Agregador, extraia a consolidação dos dados.
```bash
curl http://localhost:8080/resultados

```



---

## Estrutura do Projeto

```text
📁 Harness-Engineering
│
├── 📄 orquestrador.py       # Ponto de entrada (Servidor HTTP e Chunking)
├── 📄 trabalhadores.py      # Lógica dos Workers (Map) e Agregador (Reduce)
├── 📄 mensageria.py         # Barramento de eventos e Filas SQS-like
├── 📄 metricas.py           # Coleta de métricas e estado geral
├── 📄 cliente_llm.py        # Integração API com retentativas (Fault Tolerance)
├── 📄 testar_api.py         # Script utilitário para disparar requisições
│
└── 📁 prompts/              # System Prompts versionados
    ├── 📄 gerador_testes_v1.md
    ├── 📄 analisador_smells_v1.md
    ├── 📄 gerador_doc_v1.md
    └── 📄 agregador_v1.md

```

### 👥 Autores
<table>
  <tr>
    <td align="center">
       <a href="https://github.com/LucasAugustoSS">
         <img src="https://avatars.githubusercontent.com/u/126918429?v=4" style="border-radius: 50%" width="100px;" alt="Lucas augusto"/>
         <br />
         <sub><b>Lucas Augusto 💻</b></sub>
       </a>
     </td>
    <td align="center">
       <a href="https://github.com/FrrTiago">
         <img src="https://avatars.githubusercontent.com/u/132114628?v=4" style="border-radius: 50%" width="100px;" alt="ferreira"/>
         <br />
         <sub><b>Tiago Ferreira 💻</b></sub>
       </a>
     </td>
     <td align="center">
       <a href="https://github.com/JoaoDario632">
         <img src="https://avatars.githubusercontent.com/u/134674876?v=4" style="border-radius: 50%" width="100px;" alt="ferreira"/>
         <br />
         <sub><b>João Dário 💻</b></sub>
       </a>
     </td>
  </tr>
</table>