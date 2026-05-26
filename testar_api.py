import requests
import json

url = "http://localhost:8080/analisar"

# Usando caminho relativo: o script vai procurar o arquivo na mesma pasta em que está rodando
caminho_arquivo = "sistema_bancario.py"

arquivos = {
    'file': open(caminho_arquivo, 'rb')
}

print("Enviando arquivo para análise distribuída...")
resposta = requests.post(url, files=arquivos)

print(f"Status da API: {resposta.status_code}")
try:
    print("Resposta do Orquestrador:")
    print(json.dumps(resposta.json(), indent=2, ensure_ascii=False))
except requests.exceptions.JSONDecodeError:
    print("O servidor não retornou um JSON. Resposta bruta:")
    print(resposta.text)