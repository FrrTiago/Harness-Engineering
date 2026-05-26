import requests

url = "http://localhost:8080/analisar"

# O 'r' antes da string é essencial no Windows para ler as barras invertidas corretamente
caminho_arquivo = r"C:\Users\tiago\OneDrive\Desktop\Harness Engineering\sistema_bancario.py"

arquivos = {
    'file': open(caminho_arquivo, 'rb')
}

print("Enviando arquivo para análise...")
resposta = requests.post(url, files=arquivos)

print(f"Status da API: {resposta.status_code}")
print("Resposta do Orquestrador:")
print(resposta.json())