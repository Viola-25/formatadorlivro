import docx
import google.generativeai as genai
import json
import os
import time
import re
import unicodedata
from typing import Dict, Any, Optional

# Importa configurações centralizadas
from config import (
    STYLE_GUIDE, SYSTEM_INSTRUCTION, PREFERRED_MODELS, FALLBACK_MODEL,
    CITATION_TAG_RULE, AI_TEMPERATURE, AI_MAX_RETRIES, AI_RETRY_DELAY, PROGRESS_FILE
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

CITATION_PIPELINE_VERSION = "citation-tags-v1"
REFERENCE_TAG_RE = re.compile(r'\[TAG_REF_(\d+)\]')

# Captura citações numéricas no texto bruto.
BODY_CITATION_TOKEN_RE = re.compile(
    r'\[(?:\s*\d+(?:\s*[-,;]\s*\d+)*)\]'  # [1], [1, 2], [1-3], etc.
    r'|\((?:\s*\d+(?:\s*[-,;]\s*\d+)*)\)'  # (1), (1, 2), (1-3), etc.
    r'|[⁰¹²³⁴⁵⁶⁷⁸⁹]+'                          # Sobrescritos ¹²³
    r'|(?<=[a-záãâàäéèêëíìîïóòôöõúùûüüýÿ][a-záãâàäéèêëíìîïóòôöõúùûüüýÿ])\d+(?=[,\.\s\)\]—–-]|$)'  # Números no fim de palavras (evita H1)
)


def _is_reference_heading_line(line: str) -> bool:
    """Detecta cabeçalhos de seção de referências para limitar a renumeração ao corpo."""
    clean = line.strip().lower()
    clean = re.sub(r'^[\s#>*\-\d\.\)]+', '', clean)
    clean = re.sub(r'[:\-–—]+\s*$', '', clean)
    clean = unicodedata.normalize('NFD', clean)
    clean = ''.join(ch for ch in clean if unicodedata.category(ch) != 'Mn')
    clean = re.sub(r'\s+', ' ', clean).strip()

    return clean in {
        "referencias",
        "referencias bibliograficas",
        "bibliografia",
        "bibliographic references",
        "references",
        "references list",
        "bibliography"
    }


def _split_text_before_references(text: str) -> tuple[str, str]:
    """Divide o texto entre corpo e seção de referências (se existir)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _is_reference_heading_line(line):
            logger.debug(f"[Refs DEBUG] Cabeçalho de referências detectado na linha {i + 1}: {line!r}")
            return "\n".join(lines[:i]), "\n".join(lines[i:])

    logger.debug("[Refs DEBUG] Nenhum cabeçalho de referências detectado; todo o texto será tratado como corpo")
    return text, ""


def _parse_reference_number(line: str) -> Optional[int]:
    """Extrai o número inicial de uma linha de referência."""
    clean = line.strip()

    bracket_match = re.match(r'^\[(\d+)\]', clean)
    if bracket_match:
        return int(bracket_match.group(1))

    superscript_match = re.match(r'^([⁰¹²³⁴⁵⁶⁷⁸⁹]+)', clean)
    if superscript_match:
        return _decode_superscript_number(superscript_match.group(1))

    dot_match = re.match(r'^(\d+)([\.)\-:]?)(\s+|$)', clean)
    if dot_match:
        return int(dot_match.group(1))

    compact_match = re.match(r'^(\d+)(\S)', clean)
    if compact_match:
        return int(compact_match.group(1))

    return None


def _split_reference_entries(references_text: str) -> list[dict[str, Any]]:
    """Divide a seção de referências em entradas numeradas preservando continuações."""
    entries: list[dict[str, Any]] = []
    current_entry: Optional[dict[str, Any]] = None

    for line in references_text.splitlines():
        if not line.strip():
            continue

        number = _parse_reference_number(line)
        if number is not None:
            if current_entry is not None:
                entries.append(current_entry)
            current_entry = {
                "original_number": number,
                "lines": [line],
            }
            continue

        if current_entry is not None:
            current_entry["lines"].append(line)

    if current_entry is not None:
        entries.append(current_entry)

    return entries


def _render_reference_entry(entry: dict[str, Any], new_number: int) -> str:
    """Renderiza uma entrada bibliográfica com o novo marcador numérico."""
    lines = entry.get("lines", [])
    if not lines:
        return ""

    first_line = lines[0].strip()
    first_line = re.sub(r'^\[(?:\d+)\]\s*', '', first_line)
    first_line = re.sub(r'^[⁰¹²³⁴⁵⁶⁷⁸⁹]+\s*', '', first_line)
    first_line = re.sub(r'^\d+(?:[\.)\-:]?)\s*', '', first_line)
    first_line = re.sub(r'^\d+(?=\S)', '', first_line)
    first_line = first_line.lstrip()

    rendered_lines = [first_line]
    rendered_lines.extend(lines[1:])
    return "\n".join([f"{new_number} {first_line}".rstrip(), *lines[1:]])


def preprocess_citations_for_llm(text: str, chapter_name: str = "") -> tuple[str, list[dict[str, Any]], Dict[int, int]]:
    """Substitui citações numéricas por marcadores TAG_REF antes do envio para a IA."""
    if not text or not text.strip():
        return text, [], {}

    body_text, references_text = _split_text_before_references(text)
    reference_entries = _split_reference_entries(references_text)

    original_number_to_tag_id: Dict[int, int] = {}
    for tag_id, entry in enumerate(reference_entries, start=1):
        entry["tag_id"] = tag_id
        original_number_to_tag_id[int(entry["original_number"])] = tag_id

    logger.debug(
        f"[Refs DEBUG] Pré-processamento de '{chapter_name or 'capítulo'}': "
        f"{len(reference_entries)} referência(s) estruturada(s)"
    )

    def _replace_citation(match: re.Match) -> str:
        token = match.group(0)
        numbers = _extract_numbers_from_token(token)
        if not numbers:
            return token

        replacement_tags: list[str] = []
        for number in numbers:
            tag_id = original_number_to_tag_id.get(number)
            if tag_id is None:
                logger.warning(
                    f"[Refs] Citação {number} em '{chapter_name or 'capítulo'}' sem entrada bibliográfica correspondente"
                )
                continue
            replacement_tags.append(f"[TAG_REF_{tag_id}]")

        if not replacement_tags:
            return token

        return " ".join(replacement_tags)

    tagged_body = BODY_CITATION_TOKEN_RE.sub(_replace_citation, body_text)
    return tagged_body, reference_entries, original_number_to_tag_id


def postprocess_citations_from_llm(
    ai_text: str,
    reference_entries: list[dict[str, Any]],
    chapter_name: str = ""
) -> str:
    """Reconstrói a numeração final das citações e a seção bibliográfica em ordem determinística."""
    if not ai_text or not ai_text.strip():
        return ai_text

    body_text, _ = _split_text_before_references(ai_text)

    tag_to_new_number: Dict[int, int] = {}

    def _replace_tag(match: re.Match) -> str:
        tag_id = int(match.group(1))
        if tag_id not in tag_to_new_number:
            tag_to_new_number[tag_id] = len(tag_to_new_number) + 1
        return _encode_superscript_number(tag_to_new_number[tag_id])

    normalized_body = REFERENCE_TAG_RE.sub(_replace_tag, body_text)

    reference_lookup = {int(entry["tag_id"]): entry for entry in reference_entries if "tag_id" in entry}
    ordered_tag_ids = [tag_id for tag_id in tag_to_new_number.keys() if tag_id in reference_lookup]
    remaining_tag_ids = [tag_id for tag_id in reference_lookup.keys() if tag_id not in tag_to_new_number]

    rendered_entries: list[str] = []
    for tag_id in ordered_tag_ids:
        entry = reference_lookup[tag_id]
        new_number = tag_to_new_number[tag_id]
        rendered = _render_reference_entry(entry, new_number)
        if rendered:
            rendered_entries.append(rendered)

    next_number = len(rendered_entries) + 1
    for tag_id in remaining_tag_ids:
        entry = reference_lookup[tag_id]
        rendered = _render_reference_entry(entry, next_number)
        if rendered:
            rendered_entries.append(rendered)
            next_number += 1

    if not rendered_entries:
        logger.warning(f"[Refs] Nenhuma referência bibliográfica pôde ser reconstruída em '{chapter_name or 'capítulo'}'")
        return normalized_body.strip()

    normalized_body = normalized_body.rstrip()
    normalized_references = "\n".join(rendered_entries)

    logger.info(
        f"[Refs] Pós-processamento aplicado em '{chapter_name or 'capítulo'}': "
        f"{len(tag_to_new_number)} citação(ões) reordenada(s)."
    )
    for tag_id, new_number in sorted(tag_to_new_number.items(), key=lambda item: item[1]):
        logger.debug(f"[Refs]   TAG_REF_{tag_id} -> {new_number}")

    if "[DADOS_INDICE]" in normalized_body:
        parts = normalized_body.split("[DADOS_INDICE]", 1)
        corpo_principal = parts[0].rstrip()
        json_indice = parts[1].strip()
        return f"{corpo_principal}\n\nREFERÊNCIAS\n{normalized_references}\n\n[DADOS_INDICE]\n{json_indice}"

    return f"{normalized_body}\n\nREFERÊNCIAS\n{normalized_references}".strip()


def _format_bracket_citation(token: str, mapping: Dict[int, int]) -> str:
    """Reescreve citações entre colchetes preservando a ordem dos números mapeados."""
    mapped_numbers = [mapping.get(number, number) for number in _extract_numbers_from_token(token)]
    if not mapped_numbers:
        return token

    return "[" + ", ".join(str(number) for number in mapped_numbers) + "]"


def _decode_superscript_number(token: str) -> Optional[int]:
    try:
        return int("".join(SUPERSCRIPT_TO_DIGIT[ch] for ch in token))
    except Exception:
        return None


def _encode_superscript_number(number: int) -> str:
    return "".join(DIGIT_TO_SUPERSCRIPT[d] for d in str(number))


def _extract_numbers_from_token(token: str) -> list[int]:
    if (
        token.startswith("[") and token.endswith("]")
    ) or (
        token.startswith("(") and token.endswith(")")
    ):
        numbers: list[int] = []
        content = token[1:-1]
        for part in re.split(r'\s*[;,]\s*', content):
            if not part:
                continue

            range_match = re.fullmatch(r'(\d+)\s*[-–—]\s*(\d+)', part)
            if range_match:
                start_number = int(range_match.group(1))
                end_number = int(range_match.group(2))
                step = 1 if end_number >= start_number else -1
                numbers.extend(list(range(start_number, end_number + step, step)))
                continue

            numbers.extend(int(n) for n in re.findall(r'\d+', part))

        return numbers

    # Captura números ASCII em formato normal (ex.: "modelo12" -> token "12")
    if re.fullmatch(r'[0-9]+', token):
        return [int(token)]

    number = _decode_superscript_number(token)
    if number is None:
        return []
    return [number]


def _renumber_reference_line_marker(line: str, mapping: Dict[int, int]) -> str:
    """Renumera apenas o marcador inicial da linha de referência, preservando o restante."""
    bracket_match = re.match(r'^(\s*)\[(\d+)\](\s*.*)$', line)
    if bracket_match:
        prefix, old_number, rest = bracket_match.groups()
        new_number = mapping.get(int(old_number), int(old_number))
        suffix = rest.lstrip()
        return f"{prefix}[{new_number}] {suffix}".rstrip()

    dot_match = re.match(r'^(\s*)(\d+)([\.)\-:]?)(\s*.*)$', line)
    if dot_match:
        prefix, old_number, suffix, rest = dot_match.groups()
        new_number = mapping.get(int(old_number), int(old_number))
        suffix_text = rest.lstrip()
        if suffix_text:
            return f"{prefix}{new_number}{suffix} {suffix_text}".rstrip()
        return f"{prefix}{new_number}{suffix}".rstrip()

    superscript_match = re.match(r'^(\s*)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)(\s*.*)$', line)
    if superscript_match:
        prefix, old_sup, rest = superscript_match.groups()
        old_number = _decode_superscript_number(old_sup)
        if old_number is None:
            return line
        new_number = mapping.get(old_number, old_number)
        suffix_text = rest.lstrip()
        if suffix_text:
            return f"{prefix}{_encode_superscript_number(new_number)} {suffix_text}".rstrip()
        return f"{prefix}{_encode_superscript_number(new_number)}".rstrip()

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

    logger.info(f"[Refs] CITAÇÕES DETECTADAS:")
    logger.info(f"[Refs]   Total de tokens: {len(all_tokens)}")
    logger.info(f"[Refs]   Citações únicas: {len(mapping)}")
    logger.info(f"[Refs]   Mapeamento (origem -> novo):")
    for old_num in sorted(mapping.keys()):
        new_num = mapping[old_num]
        logger.info(f"[Refs]      {old_num} -> {new_num}")

    if references_text:
        logger.debug(
            "[Refs DEBUG] Primeiras 5 linhas da seção de referências antes da renumeração:\n"
            + "\n".join(references_text.splitlines()[:5])
        )

    def _replace_token(match: re.Match) -> str:
        token = match.group(0)

        if token.startswith("[") and token.endswith("]"):
            return _format_bracket_citation(token, mapping)

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

    tagged_text, reference_entries, _reference_mapping = preprocess_citations_for_llm(
        chapter_text,
        chapter_name=chapter_name,
    )
    cache_input = f"{CITATION_PIPELINE_VERSION}\n{tagged_text}"
    
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

IMPORTANTE: o texto já foi pré-processado pelo Python.
- As citações do corpo foram convertidas para marcadores no formato [TAG_REF_X].
- A seção bibliográfica original foi removida antes do envio.
- Você é ESTRITAMENTE PROIBIDO de remover, alterar, duplicar ou reordenar esses marcadores.
- Mantenha os marcadores exatamente onde estão nos parágrafos correspondentes, mesmo se resumir ou aglutinar o texto.
- Não crie uma nova bibliografia e não tente numerar referências manualmente.

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
{tagged_text}
"""
    
    last_error = None
    logger.info("=" * 60)
    logger.info("Iniciando processamento de capítulo com IA")
    logger.info("=" * 60)
    
    for selected_model in valid_models:
        logger.info(f"Tentando modelo: {selected_model}")
        logger.info("Verificando cache para este capítulo...")

        cached_result = cache_get(cache_input, selected_model)
        if cached_result:
            logger.info("✓ Resultado recuperado do cache")
            return cached_result
        
        try:
            model = genai.GenerativeModel(
                model_name=selected_model,
                system_instruction=f"{SYSTEM_INSTRUCTION}\n\n{CITATION_TAG_RULE}"
            )
            
            for attempt in range(AI_MAX_RETRIES):
                try:
                    logger.debug(f"Tentativa {attempt + 1}/{AI_MAX_RETRIES}")
                    response = model.generate_content(
                        prompt,
                        generation_config=genai.GenerationConfig(temperature=AI_TEMPERATURE)
                    )
                    
                    result_text = response.text
                    result_text = postprocess_citations_from_llm(
                        result_text,
                        reference_entries,
                        chapter_name=chapter_name,
                    )
                    
                    # Salva em cache para uso futuro
                    cache_set(cache_input, selected_model, result_text)
                    
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
