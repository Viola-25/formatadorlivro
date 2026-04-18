import docx
import google.generativeai as genai
import json
import os
import time
import re
from typing import Dict, Any, Optional

# Importa configurações centralizadas
from config import (
    STYLE_GUIDE, SYSTEM_INSTRUCTION, PREFERRED_MODELS, FALLBACK_MODEL,
    AI_TEMPERATURE, AI_MAX_RETRIES, AI_RETRY_DELAY, PROGRESS_FILE
)
from logger import logger
from cache import cache_get, cache_set
from exceptions import (
    DocumentParseError, APIException, APIQuotaExhausted,
    APIRateLimitExceeded, ModelNotAvailable
)


SUPERSCRIPT_TO_DIGIT = {
    '⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4',
    '⁵': '5', '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9'
}

DIGIT_TO_SUPERSCRIPT = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹'
}

# Captura:
# 1. [números] com separadores
# 2. Números sobrescritos ¹²³
# 3. Números normais pegados em palavras: palavra12, palavra6 etc.
CITATION_TOKEN_RE = re.compile(
    r'\[(?:\s*\d+(?:\s*[-,;]\s*\d+)*)\]'  # [1], [1, 2], [1-3], etc.
    r'|[⁰¹²³⁴⁵⁶⁷⁸⁹]+'                      # Sobrescritos ¹²³
    r'|(?<=[a-záãâàäéèêëíìîïóòôöõúùûüüýÿ][a-záãâàäéèêëíìîïóòôöõúùûüüýÿ])\d+(?=[,.\s\)\]—–-]|$)'  # Números no fim de palavras (evita H1)
)


def _is_reference_heading_line(line: str) -> bool:
    """Detecta cabeçalhos de seção de referências para limitar a renumeração ao corpo."""
    clean = line.strip().lower().rstrip(':')
    return clean in {
        "referencias",
        "referências",
        "bibliografia",
        "bibliographic references",
        "references"
    }


def _split_text_before_references(text: str) -> tuple[str, str]:
    """Divide o texto entre corpo e seção de referências (se existir)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _is_reference_heading_line(line):
            return "\n".join(lines[:i]), "\n".join(lines[i:])
    return text, ""


def _decode_superscript_number(token: str) -> Optional[int]:
    try:
        return int("".join(SUPERSCRIPT_TO_DIGIT[ch] for ch in token))
    except Exception:
        return None


def _encode_superscript_number(number: int) -> str:
    return "".join(DIGIT_TO_SUPERSCRIPT[d] for d in str(number))


def _extract_numbers_from_token(token: str) -> list[int]:
    if token.startswith("[") and token.endswith("]"):
        return [int(n) for n in re.findall(r'\d+', token)]

    # Captura números ASCII em formato normal (ex.: "modelo12" -> token "12")
    if re.fullmatch(r'[0-9]+', token):
        return [int(token)]

    number = _decode_superscript_number(token)
    if number is None:
        return []
    return [number]


def _renumber_reference_line_marker(line: str, mapping: Dict[int, int]) -> str:
    """Renumera apenas o marcador inicial da linha de referência, preservando o restante."""
    bracket_match = re.match(r'^(\s*)\[(\d+)\](\s+.*)$', line)
    if bracket_match:
        prefix, old_number, rest = bracket_match.groups()
        new_number = mapping.get(int(old_number), int(old_number))
        return f"{prefix}[{new_number}]{rest}"

    dot_match = re.match(r'^(\s*)(\d+)([\.)])(\s+.*)$', line)
    if dot_match:
        prefix, old_number, suffix, rest = dot_match.groups()
        new_number = mapping.get(int(old_number), int(old_number))
        return f"{prefix}{new_number}{suffix}{rest}"

    superscript_match = re.match(r'^(\s*)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)(\s+.*)$', line)
    if superscript_match:
        prefix, old_sup, rest = superscript_match.groups()
        old_number = _decode_superscript_number(old_sup)
        if old_number is None:
            return line
        new_number = mapping.get(old_number, old_number)
        return f"{prefix}{_encode_superscript_number(new_number)}{rest}"

    return line


def normalize_citation_order(ai_text: str, chapter_name: str = "") -> str:
    """
    Renumera citações para sequência de primeira aparição no corpo do texto.

    Regras:
    - Mantém formato original de cada citação (colchete ou sobrescrito)
    - Não altera conteúdo textual das referências bibliográficas
    - Ajusta apenas o marcador numérico inicial das linhas de referência
    """
    if not ai_text or not ai_text.strip():
        return ai_text

    logger.debug(f"[Refs DEBUG] Iniciando normalização de '{chapter_name or 'capítulo'}'")
    logger.debug(f"[Refs DEBUG] Tamanho total do texto: {len(ai_text)} caracteres")

    body_text, references_text = _split_text_before_references(ai_text)
    
    logger.debug(f"[Refs DEBUG] Corpo do texto: {len(body_text)} caracteres")
    logger.debug(f"[Refs DEBUG] Seção de referências: {len(references_text)} caracteres")
    logger.debug(f"[Refs DEBUG] Primeiros 300 chars do corpo:\n{body_text[:300]}\n")

    mapping: Dict[int, int] = {}
    next_number = 1
    all_tokens = []

    for match in CITATION_TOKEN_RE.finditer(body_text):
        token = match.group(0)
        start_pos = match.start()
        context_start = max(0, start_pos - 30)
        context_end = min(len(body_text), start_pos + len(token) + 30)
        context = body_text[context_start:context_end]
        
        all_tokens.append((token, start_pos, context))
        
        for old_number in _extract_numbers_from_token(token):
            if old_number <= 0:
                continue
            if old_number not in mapping:
                mapping[old_number] = next_number
                logger.debug(f"[Refs DEBUG] Token '{token}' em posição {start_pos}")
                logger.debug(f"[Refs DEBUG]   Contexto: ...{context}...")
                logger.debug(f"[Refs DEBUG]   Número {old_number} (primeira aparição) → novo número {next_number}")
                next_number += 1
            else:
                logger.debug(f"[Refs DEBUG] Token '{token}' número {old_number} já mapeado → {mapping[old_number]}")

    if not mapping:
        logger.warning(f"[Refs] ❌ Nenhuma citação detectada em '{chapter_name or 'capítulo'}'")
        logger.warning(f"[Refs DEBUG] Total de tokens encontrados pela regex: {len(all_tokens)}")
        for token, pos, ctx in all_tokens[:15]:
            logger.debug(f"[Refs DEBUG]   Token '{token}' em posição {pos}: ...{ctx}...")
        return ai_text

    logger.info(f"[Refs] ✓ CITAÇÕES DETECTADAS:")
    logger.info(f"[Refs]   Total de tokens: {len(all_tokens)}")
    logger.info(f"[Refs]   Citações únicas: {len(mapping)}")
    logger.info(f"[Refs]   Mapeamento (origem → novo):")
    for old_num in sorted(mapping.keys()):
        new_num = mapping[old_num]
        logger.info(f"[Refs]      {old_num} → {new_num}")

    def _replace_token(match: re.Match) -> str:
        token = match.group(0)

        if token.startswith("[") and token.endswith("]"):
            # Substitui números dentro de colchetes
            return re.sub(
                r'\d+',
                lambda n: str(mapping.get(int(n.group(0)), int(n.group(0)))),
                token
            )

        old_number = _decode_superscript_number(token)
        if old_number is not None:
            # É sobrescrito - retorna novo sobrescrito
            return _encode_superscript_number(mapping.get(old_number, old_number))

        # É número normal pegado em palavra - tenta converter direto
        try:
            old_num = int(token)
            return str(mapping.get(old_num, old_num))
        except ValueError:
            return token

    normalized_body = CITATION_TOKEN_RE.sub(_replace_token, body_text)

    normalized_references = references_text
    if references_text:
        renumbered_lines = [
            _renumber_reference_line_marker(line, mapping)
            for line in references_text.splitlines()
        ]
        normalized_references = "\n".join(renumbered_lines)

    normalized_text = normalized_body if not references_text else f"{normalized_body}\n{normalized_references}"

    sorted_preview = sorted(mapping.items(), key=lambda x: x[1])
    logger.info(
        f"[Refs] Normalização aplicada em '{chapter_name or 'capítulo'}': "
        f"{len(mapping)} referência(s) mapeada(s). "
        f"Primeira aparição -> Nova numeração."
    )
    for old_num, new_num in sorted_preview:
        logger.debug(f"[Refs]   {old_num} → {new_num}")

    return normalized_text


def extract_text_from_docx(file_path: str) -> str:
    """
    Extrai texto bruto de um arquivo DOCX.

    Raises:
        DocumentParseError: Se não conseguir ler o arquivo
    """
    try:
        logger.info(f"Extraindo texto de: {file_path}")
        doc = docx.Document(file_path)
        text = '\n'.join([para.text for para in doc.paragraphs])
        logger.debug(f"Texto extraído com sucesso ({len(text)} caracteres)")
        return text
    except Exception as e:
        logger.error(f"Erro ao extrair texto de {file_path}: {e}")
        raise DocumentParseError(f"Erro ao ler arquivo '{file_path}': {e}")

def get_processed_chapters_summary(progress_file: str = PROGRESS_FILE) -> str:
    """
    Lê o arquivo progresso.json e extrai os resumos dos capítulos já processados 
    para garantir coesão narrativa.
    
    Args:
        progress_file: Caminho do arquivo de progresso (default: config)
        
    Returns:
        String com resumos concatenados dos capítulos já processados
    """
    if not os.path.exists(progress_file):
        logger.debug("Arquivo de progresso não encontrado")
        return ""
    
    try:
        logger.debug(f"Lendo resumos anteriores de: {progress_file}")
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        status_capitulos = data.get("status_capitulos", {})
        resumos = []
        
        for cap, info in status_capitulos.items():
            if isinstance(info, dict) and info.get("status") == "Concluído" and info.get("resumo"):
                resumos.append(f"Capítulo '{cap}': {info.get('resumo')}")
        
        result = "\n\n".join(resumos)
        logger.info(f"Resumos anteriores agregados: {len(resumos)} capítulo(s)")
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar JSON de progresso: {e}")
        return ""
    except Exception as e:
        logger.warning(f"Erro ao ler resumos anteriores: {e}")
        return ""

def process_chapter_text(
    chapter_text: str,
    previous_summaries: str,
    api_key: Optional[str] = None,
    chapter_name: str = ""
) -> str:
    """
    Envia o texto para a API do Gemini processar de acordo com o STYLE_GUIDE e instruções.
    
    Implementa:
    - Cache para evitar reprocessamento de documentos idênticos
    - Seleção inteligente de modelos baseado em disponibilidade
    - Retry com backoff exponencial
    - Logging detalhado
    - Tratamento robusto de erros
    
    Args:
        chapter_text: Texto bruto do capítulo a processar
        previous_summaries: Resumos de capítulos anteriores para coesão narrativa
        api_key: Chave da API Gemini (configurada na sessão se não fornecida)
        chapter_name: Nome do capítulo/arquivo para logs de debug
        
    Returns:
        Texto processado pela IA com tags de formatação
        
    Raises:
        APIException: Se não conseguir processar com nenhum modelo disponível
        ModelNotAvailable: Se nenhum modelo estiver disponível
    """
    if api_key:
        genai.configure(api_key=api_key)
    
    # Tenta recuperar do cache (otimiza chamadas repetitivas)
    logger.info("Verificando cache para este capítulo...")
    cached_result = cache_get(chapter_text, "gemini-default")
    if cached_result:
        logger.info("✓ Resultado recuperado do cache")
        return normalize_citation_order(cached_result, chapter_name=chapter_name)
    
    # Mapeia modelos disponíveis na API
    logger.debug("Mapeando modelos disponíveis na API...")
    available_models = []
    try:
        available_models = [
            m.name for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
        ]
        logger.debug(f"Modelos disponíveis: {len(available_models)}")
    except Exception as e:
        logger.warning(f"Erro ao listar modelos: {e}")
    
    # Filtra modelos preferidos que estão disponíveis
    valid_models = []
    for tm in PREFERRED_MODELS:
        clean_name = tm.replace("models/", "")
        if tm in available_models or clean_name in available_models:
            valid_models.append(clean_name)
            logger.debug(f"Modelo disponível: {clean_name}")
    
    if not valid_models:
        logger.warning(f"Nenhum modelo preferido disponível. Usando fallback: {FALLBACK_MODEL}")
        valid_models = [FALLBACK_MODEL]
    
    # Constrói prompt com contexto e instruções
    prompt = f"""
Você deve revisar e reescrever o texto do capítulo fornecido abaixo.

REGRAS DE ESTILO (STYLE_GUIDE):
{STYLE_GUIDE}

INSTRUÇÕES GERAIS DE CONSERVAÇÃO:
- NÃO resuma o texto.
- NÃO elimine conteúdo clínico ou detalhes importantes.
- Mantenha o tamanho do capítulo tão grande quanto o original, preservando todas as informações relevantes.
- Corrija apenas o necessário: gramática, ortografia, coesão, clareza e estilo.
- Faça mudanças mínimas e conservadoras; preserve o significado original.
- Use a mesma estrutura de ideias, ajustando títulos e subtítulos apenas para maior clareza.

INSTRUÇÕES DE FORMATAÇÃO E ESTRUTURA:
1. Reescreva o texto de forma uniforme baseando-se estritamente no STYLE_GUIDE.
2. Estruture o texto principal utilizando marcações de Títulos (H1) e Subtítulos (H2) curtos e claros em linhas isoladas. Eles devem obrigatoriamente estar SEM pontuação final (como pontos ou dois-pontos) para que o formatador DOCX consiga capturá-los e aplicar os estilos de cabeçalho.
3. Insira as seguintes tags no texto, onde for mais apropriado:
   - [BOX_RESUMO]: Logo após o título do capítulo, extraia de 3 a 5 tópicos cruciais e insira a tag [BOX_RESUMO] seguida do texto "PONTOS IMPORTANTES", estruturando os dados em bullet points curtos e diretos. Evite parágrafos longos dentro deste box.
   - [BOX_RECOMENDACAO]: Utilize para destacar intervenções clínicas importantes ou condutas recomendadas.
   - [BOX_ATENCAO]: Utilize para destacar riscos, contraindicações ou alertas clínicos cruciais.
   - [SUGESTAO_EDICAO]: Utilize caso encontre inconsistências técnicas ou mudanças significativas e informe claramente o que precisa ser verificado ou validado pelo autor original.
4. O box [BOX_RESUMO] deve conter apenas 3 a 5 bullet points curtos com as mensagens principais do capítulo. Esta é a única parte do texto que pode ser menor; o restante do capítulo deve manter o tamanho original e todas as informações relevantes.
5. CITAÇÕES E REFERÊNCIAS: Mantenha rigorosamente a mesma numeração e formato (seja sobrescrito ¹, ², ou colchetes [1]) que vieram no texto original. NÃO tente reordenar, NÃO renumere e NÃO altere a lista bibliográfica no final do documento. Apenas preserve a citação exatamente onde ela estava.
6. Não insira asteriscos (*), hashtags (#) ou outras marcas de markdown no texto final. O texto deve estar limpo e pronto para formatação.
7. No final do texto, pesquise e sugira 2 ou 3 links oficiais (ex: Ministério da Saúde, OMS, SBMFC ou outras sociedades médicas reconhecidas) para atualização do tema abordado, e insira-os sob a tag [LINKS_ATUALIZACAO].
8. Ao final de tudo, adicione a tag [DADOS_INDICE] seguida de um JSON estrito contendo duas chaves: 'titulo_capitulo' (o título definitivo do texto lido) e 'subtopicos' (uma lista de strings com os 3 a 5 principais tópicos abordados no capítulo).

CONTEXTO DOS CAPÍTULOS ANTERIORES:
(Utilize este contexto para manter a coesão narrativa, evitar repetições desnecessárias e garantir a continuidade do guia)
{previous_summaries if previous_summaries else "Nenhum capítulo processado anteriormente ou sem resumo disponível."}

TEXTO DO CAPÍTULO A SER REVISADO:
{chapter_text}
"""
    
    last_error = None
    logger.info("=" * 60)
    logger.info("Iniciando processamento de capítulo com IA")
    logger.info("=" * 60)
    
    for selected_model in valid_models:
        logger.info(f"Tentando modelo: {selected_model}")
        
        try:
            model = genai.GenerativeModel(
                model_name=selected_model,
                system_instruction=SYSTEM_INSTRUCTION
            )
            
            for attempt in range(AI_MAX_RETRIES):
                try:
                    logger.debug(f"Tentativa {attempt + 1}/{AI_MAX_RETRIES}")
                    response = model.generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(temperature=AI_TEMPERATURE)
                    )
                    
                    result_text = response.text
                    result_text = normalize_citation_order(result_text, chapter_name=chapter_name)
                    
                    # Salva em cache para uso futuro
                    cache_set(chapter_text, selected_model, result_text)
                    
                    logger.info(f"✓ Sucesso usando {selected_model}!")
                    logger.info("=" * 60)
                    return result_text
                    
                except Exception as e:
                    error_msg = str(e)
                    last_error = e
                    
                    # Tratamento específico de erros de quota/rate limit
                    if any(x in error_msg.lower() for x in ["429", "quota", "exhausted", "limit"]):
                        if "limit: 0" in error_msg:
                            logger.warning(f"Modelo {selected_model} sem cota (Limit: 0). Pulando...")
                            break
                        
                        if attempt < AI_MAX_RETRIES - 1:
                            wait_time = AI_RETRY_DELAY * (attempt + 1)
                            logger.warning(f"Rate limit atingido. Aguardando {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            logger.error(f"Rate limit persistente após {AI_MAX_RETRIES} tentativas")
                            raise APIRateLimitExceeded(f"Rate limit no modelo {selected_model}")
                    else:
                        logger.error(f"Erro inesperado em {selected_model}: {error_msg}")
                        raise APIException(f"Erro na IA: {error_msg}")
                        
        except (APIRateLimitExceeded, APIQuotaExhausted):
            logger.debug(f"Erro de quota/rate limit detectado, pulando para próximo modelo...")
            continue
        except APIException as e:
            logger.debug(f"Erro da API: {e}, tentando próximo modelo...")
            last_error = e
            continue
        except Exception as e:
            logger.error(f"Erro inesperado com {selected_model}: {e}")
            last_error = e
            continue
    
    # Se chegou aqui, todos os modelos falharam
    logger.error(f"Todos os modelos falharam. Último erro: {last_error}")
    raise APIException(f"Processamento falhou com todos os modelos. Erro: {last_error}")
