def extrair_json_robusto(texto: str) -> str:
    """Extrai cirurgicamente o conteúdo JSON de uma string, ignorando textos ao redor."""
    texto = texto.strip()
    start_chaves = texto.find('{')
    end_chaves = texto.rfind('}')
    start_colchetes = texto.find('[')
    end_colchetes = texto.rfind(']')

    # Encontra o primeiro e o último caractere estrutural de um JSON
    start = min(i for i in [start_chaves, start_colchetes] if i != -1) if (start_chaves != -1 or start_colchetes != -1) else -1
    end = max(i for i in [end_chaves, end_colchetes] if i != -1) + 1 if (end_chaves != -1 or end_colchetes != -1) else -1

    if start != -1 and end > start:
        return texto[start:end]
    return texto