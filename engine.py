import docx
import json
import os
import time
import re
import hashlib
import unicodedata
from collections import Counter
from typing import Dict, Any, Optional
from groq import Groq

# Importa configurações centralizadas
from config import (
    STYLE_GUIDE, SYSTEM_INSTRUCTION, PREFERRED_MODELS, FALLBACK_MODEL,
    AI_PROVIDER,
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

CITATION_PIPELINE_VERSION = "citation-tags-v3"
REFERENCE_TAG_RE = re.compile(r'\[TAG_REF_(\d+)\]')
CITATION_PLACEHOLDER_RE = re.compile(r'\[TAG_CIT_(\d+)\]')
BOX_RESUMO_TAG = "[BOX_RESUMO]"
BOX_RECOMENDACAO_TAG = "[BOX_RECOMENDACAO]"
BOX_ATENCAO_TAG = "[BOX_ATENCAO]"
MAX_RECOMMENDATION_BOXES = 2
MAX_ATTENTION_BOXES = 2

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


def tokenize_citations_for_llm(body_text: str, chapter_name: str = "") -> tuple[str, Dict[str, str]]:
    """Substitui cada citação do corpo por um placeholder único para preservar posição e ordem."""
    if not body_text:
        return body_text, {}

    placeholder_to_token: Dict[str, str] = {}

    def _replace(match: re.Match) -> str:
        token = match.group(0)
        placeholder = f"[TAG_CIT_{len(placeholder_to_token) + 1}]"
        placeholder_to_token[placeholder] = token
        return placeholder

    tagged_body = BODY_CITATION_TOKEN_RE.sub(_replace, body_text)
    logger.debug(
        f"[Refs DEBUG] Tokenização de citações em '{chapter_name or 'capítulo'}': "
        f"{len(placeholder_to_token)} marcador(es) [TAG_CIT_X]"
    )
    if placeholder_to_token:
        preview = list(placeholder_to_token.items())[:5]
        logger.debug(f"[Refs DEBUG] Preview placeholders (até 5): {preview}")
    return tagged_body, placeholder_to_token


def restore_citations_from_placeholders(ai_text: str, placeholder_to_token: Dict[str, str]) -> str:
    """Restaura as citações originais a partir dos placeholders [TAG_CIT_X]."""
    if not ai_text or not placeholder_to_token:
        return ai_text

    restored = ai_text
    # Ordenação por tamanho evita colisões em placeholders com prefixos semelhantes.
    for placeholder in sorted(placeholder_to_token.keys(), key=len, reverse=True):
        restored = restored.replace(placeholder, placeholder_to_token[placeholder])
    return restored


def _normalize_manual_references_text(references_text: str) -> str:
    """Normaliza texto de referências colado pelo usuário, removendo cabeçalho duplicado."""
    if not references_text or not references_text.strip():
        return ""

    lines = references_text.splitlines()
    first_content_index = None
    for idx, line in enumerate(lines):
        if line.strip():
            first_content_index = idx
            break

    if first_content_index is None:
        return ""

    first_line = lines[first_content_index]
    if _is_reference_heading_line(first_line):
        lines = lines[first_content_index + 1:]
    else:
        lines = lines[first_content_index:]

    return "\n".join(lines).strip()


def append_manual_references(ai_body_text: str, manual_references_text: str) -> str:
    """Anexa a seção REFERÊNCIAS (colada pelo usuário) ao texto final, sem alterar citações."""
    normalized_references = _normalize_manual_references_text(manual_references_text)
    if not normalized_references:
        logger.debug("[Refs DEBUG] Nenhuma referência manual recebida; corpo mantido sem seção REFERÊNCIAS")
        return ai_body_text.strip()

    clean_body = ai_body_text.strip()
    if "[DADOS_INDICE]" in clean_body:
        parts = clean_body.split("[DADOS_INDICE]", 1)
        body_main = parts[0].rstrip()
        index_json = parts[1].strip()
        logger.debug("[Refs DEBUG] Referências manuais anexadas antes de [DADOS_INDICE]")
        return f"{body_main}\n\nREFERÊNCIAS\n{normalized_references}\n\n[DADOS_INDICE]\n{index_json}".strip()

    logger.debug("[Refs DEBUG] Referências manuais anexadas ao final do capítulo")
    return f"{clean_body}\n\nREFERÊNCIAS\n{normalized_references}".strip()


def _extract_placeholder_multiset(text: str) -> Counter:
    return Counter(CITATION_PLACEHOLDER_RE.findall(text or ""))


def _extract_placeholder_sequence(text: str) -> list[str]:
    return CITATION_PLACEHOLDER_RE.findall(text or "")


def _placeholder_signature(text: str) -> str:
    sequence = _extract_placeholder_sequence(text)
    payload = "|".join(sequence)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12] if sequence else "none"


def _extract_citation_token_sequence(text: str) -> list[str]:
    return [m.group(0) for m in BODY_CITATION_TOKEN_RE.finditer(text or "")]


def _citation_signature(text: str) -> str:
    sequence = _extract_citation_token_sequence(text)
    payload = "|".join(sequence)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12] if sequence else "none"


def _placeholders_preserved(source_text: str, candidate_text: str) -> bool:
    """Valida placeholders preservando contagem E ordem de aparição."""
    source_sequence = _extract_placeholder_sequence(source_text)
    candidate_sequence = _extract_placeholder_sequence(candidate_text)
    return source_sequence == candidate_sequence


def _summarize_placeholder_diff(source_text: str, candidate_text: str) -> str:
    """Resume diferenças entre placeholders esperados e recebidos para debug."""
    source_counts = _extract_placeholder_multiset(source_text)
    candidate_counts = _extract_placeholder_multiset(candidate_text)

    missing = source_counts - candidate_counts
    unexpected = candidate_counts - source_counts
    sequence_matches = _extract_placeholder_sequence(source_text) == _extract_placeholder_sequence(candidate_text)

    missing_items = sorted(missing.items())[:10]
    unexpected_items = sorted(unexpected.items())[:10]
    return (
        f"esperados={sum(source_counts.values())}, recebidos={sum(candidate_counts.values())}, "
        f"faltando={missing_items}, extras={unexpected_items}, ordem_igual={sequence_matches}"
    )


def _split_index_block(text: str) -> tuple[str, str]:
    """Separa corpo e bloco [DADOS_INDICE] para não contaminar regras de box."""
    if "[DADOS_INDICE]" not in (text or ""):
        return (text or "").strip(), ""

    body, index_block = (text or "").split("[DADOS_INDICE]", 1)
    return body.strip(), index_block.strip()


def _strip_box_tags_only(line: str) -> str:
    """Remove apenas marcadores de box da linha, preservando o conteúdo textual."""
    return (
        line.replace(BOX_RESUMO_TAG, "")
        .replace(BOX_RECOMENDACAO_TAG, "")
        .replace(BOX_ATENCAO_TAG, "")
        .strip()
    )


def _is_heading_candidate(line: str) -> bool:
    clean = line.strip()
    if not clean:
        return False

    return (
        len(clean) < 60
        and not clean.endswith(".")
        and not clean.endswith(":")
        and not clean.startswith("-")
        and not clean.startswith("*")
        and not clean.startswith("[")
    )


def _generate_summary_bullets_from_body(body_text: str) -> list[str]:
    """Gera 3-5 bullets curtos para o box de resumo quando a IA não inserir nenhum."""
    lines: list[str] = []
    skipped_headings = 0
    for raw_line in (body_text or "").splitlines():
        clean = _strip_box_tags_only(raw_line)
        clean = re.sub(r'\[TAG_CIT_\d+\]', '', clean).strip()
        if not clean:
            continue
        if _is_reference_heading_line(clean):
            continue
        if clean.startswith("["):
            continue
        if _is_heading_candidate(clean):
            # Evita incluir titulo/subtitulo como bullet de "PONTOS IMPORTANTES".
            skipped_headings += 1
            if skipped_headings <= 3:
                continue
        lines.append(clean)
        if len(lines) >= 12:
            break

    bullets: list[str] = []
    for line in lines:
        parts = re.split(r'(?<=[\.!?])\s+', line)
        for part in parts:
            sentence = part.strip(" -;,:")
            if len(sentence) < 28:
                continue
            if len(sentence) > 140:
                continue
            if sentence[-1] not in ".!?":
                sentence = sentence + "."
            bullets.append(f"- {sentence}")
            if len(bullets) >= 5:
                break
        if len(bullets) >= 5:
            break

    if len(bullets) < 3:
        fallback = [
            "- Panorama dos pontos clinicos centrais do capitulo.",
            "- Condutas principais e criterios de decisao descritos no texto.",
            "- Alertas de seguranca e aplicacoes praticas para a APS.",
        ]
        bullets.extend(fallback[: 3 - len(bullets)])

    return bullets[:5]


def _insert_summary_box_near_start(body_text: str) -> str:
    """Insere um unico box de resumo logo apos o titulo inicial (ou no topo)."""
    lines = (body_text or "").splitlines()
    insert_at = 0

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        insert_at = i + 1 if _is_heading_candidate(line.strip()) else i
        break

    bullets = _generate_summary_bullets_from_body(body_text)
    summary_block = [BOX_RESUMO_TAG, *bullets, ""]

    new_lines = lines[:insert_at] + summary_block + lines[insert_at:]
    return "\n".join(new_lines).strip()


def enforce_box_policy(ai_text: str, chapter_name: str = "") -> str:
    """
    Enforce de boxes:
    - Exatamente 1 [BOX_RESUMO] no inicio do capitulo (insere se faltar).
    - Limite de [BOX_RECOMENDACAO] e [BOX_ATENCAO] para evitar excesso.
    """
    if not ai_text or not ai_text.strip():
        return ai_text

    body_text, index_block = _split_index_block(ai_text)
    lines = body_text.splitlines()

    resumo_count = 0
    recommendation_count = 0
    attention_count = 0
    filtered_lines: list[str] = []

    for line in lines:
        current = line

        if BOX_RESUMO_TAG in current:
            if resumo_count >= 1:
                current = current.replace(BOX_RESUMO_TAG, "").strip()
            else:
                resumo_count += 1

        if BOX_RECOMENDACAO_TAG in current:
            if recommendation_count >= MAX_RECOMMENDATION_BOXES:
                current = current.replace(BOX_RECOMENDACAO_TAG, "").strip()
            else:
                recommendation_count += 1

        if BOX_ATENCAO_TAG in current:
            if attention_count >= MAX_ATTENTION_BOXES:
                current = current.replace(BOX_ATENCAO_TAG, "").strip()
            else:
                attention_count += 1

        filtered_lines.append(current)

    filtered_body = "\n".join(filtered_lines).strip()

    if resumo_count == 0:
        filtered_body = _insert_summary_box_near_start(filtered_body)

    if "[DADOS_INDICE]" in (ai_text or ""):
        logger.debug(
            f"[Box DEBUG] Politica de boxes aplicada em '{chapter_name or 'capitulo'}': "
            f"resumo={max(resumo_count, 1)}, recomendacao={min(recommendation_count, MAX_RECOMMENDATION_BOXES)}, "
            f"atencao={min(attention_count, MAX_ATTENTION_BOXES)}"
        )
        return f"{filtered_body}\n\n[DADOS_INDICE]\n{index_block}".strip()

    logger.debug(
        f"[Box DEBUG] Politica de boxes aplicada em '{chapter_name or 'capitulo'}': "
        f"resumo={max(resumo_count, 1)}, recomendacao={min(recommendation_count, MAX_RECOMMENDATION_BOXES)}, "
        f"atencao={min(attention_count, MAX_ATTENTION_BOXES)}"
    )
    return filtered_body


def ensure_mandatory_summary_box(ai_text: str, chapter_name: str = "") -> str:
    """Garantia final: todo capítulo precisa conter exatamente um [BOX_RESUMO]."""
    if not ai_text or not ai_text.strip():
        fallback_text = _insert_summary_box_near_start("")
        logger.warning(
            f"[Box] Capítulo vazio em '{chapter_name or 'capitulo'}'; "
            "inserindo box de resumo padrão para manter regra obrigatória."
        )
        return fallback_text

    body_text, index_block = _split_index_block(ai_text)
    count = body_text.count(BOX_RESUMO_TAG)

    if count == 1:
        return ai_text

    logger.warning(
        f"[Box] Ajuste de garantia em '{chapter_name or 'capitulo'}': "
        f"BOX_RESUMO detectados={count}. Reaplicando política obrigatória."
    )

    rebuilt = enforce_box_policy(ai_text, chapter_name=chapter_name)
    rebuilt_body, rebuilt_index = _split_index_block(rebuilt)
    rebuilt_count = rebuilt_body.count(BOX_RESUMO_TAG)

    if rebuilt_count == 0:
        rebuilt_body = _insert_summary_box_near_start(rebuilt_body)
        rebuilt_count = rebuilt_body.count(BOX_RESUMO_TAG)

    if rebuilt_count > 1:
        seen = 0
        dedup_lines: list[str] = []
        for line in rebuilt_body.splitlines():
            current = line
            if BOX_RESUMO_TAG in current:
                if seen >= 1:
                    current = current.replace(BOX_RESUMO_TAG, "").strip()
                else:
                    seen += 1
            dedup_lines.append(current)
        rebuilt_body = "\n".join(dedup_lines).strip()

    if "[DADOS_INDICE]" in rebuilt:
        return f"{rebuilt_body}\n\n[DADOS_INDICE]\n{rebuilt_index}".strip()
    return rebuilt_body


def _extract_chapter_title_from_text(text: str, chapter_name: str = "") -> str:
    """Obtém um título de capítulo confiável a partir do texto final."""
    for line in (text or "").splitlines():
        clean = _strip_box_tags_only(line).strip()
        if not clean:
            continue
        if clean.startswith("["):
            continue
        if clean.startswith("-"):
            continue
        clean = clean.rstrip(".:;!? ")
        if len(clean) < 4:
            continue
        return clean

    fallback_name = chapter_name or "Capítulo"
    fallback_name = os.path.splitext(fallback_name)[0].replace("_", " ").strip()
    return fallback_name or "Capítulo"


def _extract_subtopics_from_text(text: str, chapter_title: str, min_items: int = 3, max_items: int = 5) -> list[str]:
    """Extrai subtópicos por heurística para fallback de índice quando a IA falha."""
    subtopics: list[str] = []
    seen: set[str] = set()

    for line in (text or "").splitlines():
        clean = _strip_box_tags_only(line).strip()
        if not clean or clean.startswith("["):
            continue
        if clean.startswith("-"):
            continue
        candidate = clean.rstrip(".:;!? ")
        if candidate.lower() == chapter_title.lower():
            continue
        if not _is_heading_candidate(candidate):
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        subtopics.append(candidate)
        if len(subtopics) >= max_items:
            break

    if len(subtopics) < min_items:
        defaults = [
            "Contexto clínico",
            "Aplicação prática",
            "Pontos de atenção",
            "Condutas recomendadas",
            "Resumo para decisão clínica",
        ]
        for topic in defaults:
            if topic.lower() == chapter_title.lower():
                continue
            if topic.lower() in seen:
                continue
            subtopics.append(topic)
            seen.add(topic.lower())
            if len(subtopics) >= min_items:
                break

    return subtopics[:max_items]


def _build_index_prompt(chapter_text: str, chapter_name: str = "") -> str:
    """Prompt dedicado para gerar apenas metadados de índice em JSON estrito."""
    return f"""
Extraia metadados de índice do capítulo abaixo.

REGRAS OBRIGATÓRIAS:
- Retorne SOMENTE um JSON válido.
- JSON com exatamente duas chaves: titulo_capitulo (string) e subtopicos (array de 3 a 5 strings).
- Não inclua markdown, comentários ou texto fora do JSON.
- Não invente temas fora do capítulo.

CAPÍTULO (nome de arquivo de origem: {chapter_name or 'capitulo'}):
{chapter_text}
"""


def _parse_index_json(raw_text: str) -> Optional[dict[str, Any]]:
    """Tenta extrair JSON de índice mesmo que a resposta venha com ruído."""
    if not raw_text:
        return None

    candidate = raw_text.strip()
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', candidate, flags=re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
    else:
        obj_match = re.search(r'(\{.*\})', candidate, flags=re.DOTALL)
        if obj_match:
            candidate = obj_match.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except Exception:
        return None

    if not isinstance(parsed, dict):
        return None
    if "titulo_capitulo" not in parsed or "subtopicos" not in parsed:
        return None
    if not isinstance(parsed.get("titulo_capitulo"), str):
        return None
    if not isinstance(parsed.get("subtopicos"), list):
        return None

    cleaned_subtopics = [str(x).strip() for x in parsed["subtopicos"] if str(x).strip()]
    parsed["titulo_capitulo"] = parsed["titulo_capitulo"].strip()
    parsed["subtopicos"] = cleaned_subtopics
    return parsed


def _build_index_metadata(
    client: Groq,
    model_name: str,
    system_instruction: str,
    final_text: str,
    chapter_name: str = "",
) -> dict[str, Any]:
    """Gera metadados de índice em etapa dedicada, com fallback determinístico."""
    body_text, _ = _split_text_before_references(final_text)
    title_fallback = _extract_chapter_title_from_text(body_text, chapter_name=chapter_name)
    subtopics_fallback = _extract_subtopics_from_text(body_text, title_fallback)
    fallback_data = {
        "titulo_capitulo": title_fallback,
        "subtopicos": subtopics_fallback,
        "_source": "fallback",
    }

    try:
        index_prompt = _build_index_prompt(body_text, chapter_name=chapter_name)
        raw_index = _generate_with_groq(
            client,
            model_name,
            system_instruction,
            index_prompt,
            0.1,
        )
        parsed = _parse_index_json(raw_index)
        if not parsed:
            logger.warning(f"[Indice] JSON inválido na etapa dedicada em '{chapter_name or 'capítulo'}'; usando fallback")
            return fallback_data

        title = parsed.get("titulo_capitulo") or title_fallback
        subtopics = parsed.get("subtopicos") or []
        subtopics = [s for s in subtopics if isinstance(s, str) and s.strip()]

        if len(subtopics) < 3:
            subtopics = _extract_subtopics_from_text(body_text, title)
        if len(subtopics) > 5:
            subtopics = subtopics[:5]

        return {
            "titulo_capitulo": str(title).strip() or title_fallback,
            "subtopicos": subtopics,
            "_source": "ai",
        }
    except Exception as e:
        logger.warning(
            f"[Indice] Falha na etapa dedicada de índice em '{chapter_name or 'capítulo'}': {e}. "
            "Aplicando fallback determinístico."
        )
        return fallback_data


def append_index_metadata(final_text: str, index_data: dict[str, Any]) -> str:
    """Anexa o bloco [DADOS_INDICE] de forma determinística no final do capítulo."""
    if not final_text or not final_text.strip():
        return final_text

    body, _existing = _split_index_block(final_text)
    payload = {
        "titulo_capitulo": index_data.get("titulo_capitulo", "Capítulo"),
        "subtopicos": index_data.get("subtopicos", []),
    }
    json_block = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{body}\n\n[DADOS_INDICE]\n{json_block}".strip()


def _build_chapter_prompt(tagged_text: str, previous_summaries: str) -> str:
    """Constrói prompt principal do capítulo com placeholders de citação imutáveis."""
    return f"""
Você deve revisar e reescrever o texto do capítulo fornecido abaixo.

IMPORTANTE: o texto já foi pré-processado pelo Python.
- As citações do corpo foram convertidas para marcadores no formato [TAG_CIT_X].
- A seção bibliográfica NÃO foi enviada para você.
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
3. CITAÇÕES E REFERÊNCIAS: Mantenha rigorosamente a mesma numeração e formato (seja sobrescrito ¹, ², ou colchetes [1]) que vieram no texto original. NÃO tente reordenar, NÃO renumere e NÃO altere referências.
4. Não insira asteriscos (*), hashtags (#) ou outras marcas de markdown no texto final. O texto deve estar limpo e pronto para formatação.
5. NÃO produza JSON, metadados ou blocos [DADOS_INDICE]. Essa etapa será feita separadamente pelo sistema.

*** REGRAS ABSOLUTAS PARA CITAÇÕES E REFERÊNCIAS BIBLIOGRÁFICAS ***
- PROIBIDO ALTERAR NÚMEROS: Você NÃO DEVE, sob nenhuma hipótese, reordenar, renomear ou alterar os números das citações sobrescritas no meio do texto.
- FIDELIDADE À LISTA ORIGINAL: A seção de "REFERÊNCIAS" será inserida pelo sistema no final do texto, mantendo a ordem original do usuário.
- PROIBIDO ALUCINAR LINKS: NÃO adicione links externos, sites (como OPAS, Ministério da Saúde, SBMFC) ou novas referências que não constem no texto base enviado. Limite-se estritamente ao material fornecido.

CONTEXTO DOS CAPÍTULOS ANTERIORES:
(Utilize este contexto para manter a coesão narrativa, evitar repetições desnecessárias e garantir a continuidade do guia)
{previous_summaries if previous_summaries else "Nenhum capítulo processado anteriormente ou sem resumo disponível."}

TEXTO DO CAPÍTULO A SER REVISADO:
{tagged_text}
"""


def _build_paragraph_prompt(tagged_paragraph: str, previous_summaries: str) -> str:
    """Prompt estrito para revisão de um único parágrafo preservando placeholders."""
    return f"""
Reescreva APENAS o parágrafo abaixo mantendo o conteúdo técnico e o estilo do guia.

REGRAS OBRIGATÓRIAS:
- Preserve todos os placeholders [TAG_CIT_X] exatamente como estão.
- NÃO adicione/remova/duplique/reordene placeholders.
- NÃO adicione bibliografia, links, markdown, títulos extras nem JSON.
- Retorne somente o parágrafo revisado.

CONTEXTO NARRATIVO (resumo dos capítulos anteriores):
{previous_summaries if previous_summaries else "Sem contexto anterior."}

PARÁGRAFO:
{tagged_paragraph}
"""


def _build_cohesion_prompt(tagged_text: str, previous_summaries: str) -> str:
    """Prompt de ajuste global de coesão com alterações mínimas e conservadoras."""
    return f"""
Revise o capítulo completo abaixo com foco EXCLUSIVO em coesão textual e consistência interna.

OBJETIVO:
- Melhorar fluidez entre parágrafos e subtítulos.
- Ajustar conectores, pequenas redundâncias e encadeamento lógico.
- Manter terminologia consistente ao longo do capítulo.

REGRAS OBRIGATÓRIAS:
- Faça mudanças mínimas (modo conservador).
- NÃO resuma e NÃO reduza conteúdo técnico.
- NÃO adicionar novos fatos clínicos nem remover informações.
- Preserve TODOS os placeholders [TAG_CIT_X] exatamente (mesma quantidade e ordem).
- NÃO inserir bibliografia, markdown ou JSON.
- Retorne apenas o texto revisado do capítulo.

CONTEXTO DOS CAPÍTULOS ANTERIORES:
{previous_summaries if previous_summaries else "Sem contexto anterior."}

CAPÍTULO:
{tagged_text}
"""


def _generate_with_groq(
    client: Groq,
    model_name: str,
    system_instruction: str,
    prompt: str,
    temperature: float,
) -> str:
    """Executa uma geração de texto usando a API Chat Completions do Groq."""
    response = client.chat.completions.create(
        model=model_name,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ],
    )

    if not response.choices:
        return ""

    content = response.choices[0].message.content
    return content or ""


def _rewrite_by_paragraphs(
    client: Groq,
    model_name: str,
    system_instruction: str,
    tagged_text: str,
    previous_summaries: str,
    chapter_name: str,
) -> tuple[str, dict[str, int]]:
    """Processa o capítulo por parágrafos para reduzir risco de perda de citações."""
    paragraphs = [p for p in tagged_text.split("\n\n")]
    rewritten_paragraphs: list[str] = []
    stats = {
        "total": len(paragraphs),
        "empty": 0,
        "fallback": 0,
        "rewritten": 0,
    }

    logger.debug(
        f"[Pipeline DEBUG] '{chapter_name or 'capítulo'}' em modo estrito por parágrafos: "
        f"{len(paragraphs)} bloco(s)"
    )

    for idx, paragraph in enumerate(paragraphs, start=1):
        if not paragraph.strip():
            rewritten_paragraphs.append(paragraph)
            stats["empty"] += 1
            continue

        paragraph_prompt = _build_paragraph_prompt(paragraph, previous_summaries)
        candidate = _generate_with_groq(
            client,
            model_name,
            system_instruction,
            paragraph_prompt,
            AI_TEMPERATURE,
        ).strip()

        if not _placeholders_preserved(paragraph, candidate):
            logger.warning(
                f"[Refs] Placeholders alterados no parágrafo {idx} de '{chapter_name or 'capítulo'}'. "
                "Aplicando fallback para preservar citação."
            )
            logger.debug(
                f"[Refs DEBUG] Diferença de placeholders no parágrafo {idx}: "
                f"{_summarize_placeholder_diff(paragraph, candidate)}"
            )
            rewritten_paragraphs.append(paragraph)
            stats["fallback"] += 1
            continue

        rewritten_paragraphs.append(candidate)
        stats["rewritten"] += 1

    merged = "\n\n".join(rewritten_paragraphs).strip()
    return merged, stats


def postprocess_citations_from_llm(
    ai_text: str,
    reference_entries: list[dict[str, Any]],
    chapter_name: str = ""
) -> str:
    """Desativado: mantém o texto da IA intacto, sem reordenação/renumeração de referências."""
    _ = reference_entries
    _ = chapter_name
    return ai_text


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
    chapter_name: str = "",
    manual_references_text: str = "",
    strict_paragraph_mode: bool = False,
    strict_citation_lock: bool = False,
) -> str:
    """
    Envia o texto para a API do Groq processar de acordo com o STYLE_GUIDE e instruções.
    
    Implementa:
    - Cache para evitar reprocessamento de documentos idênticos
    - Seleção inteligente de modelos baseado em disponibilidade
    - Retry com backoff exponencial
    - Logging detalhado
    - Tratamento robusto de erros
    
    Args:
        chapter_text: Texto bruto do capítulo a processar
        previous_summaries: Resumos de capítulos anteriores para coesão narrativa
        api_key: Chave da API Groq (configurada na sessão se não fornecida)
        chapter_name: Nome do capítulo/arquivo para logs de debug
        
    Returns:
        Texto processado pela IA com tags de formatação
        
    Raises:
        APIException: Se não conseguir processar com nenhum modelo disponível
        ModelNotAvailable: Se nenhum modelo estiver disponível
    """
    if not api_key:
        raise APIException("Chave da API Groq não informada")

    client = Groq(api_key=api_key)

    logger.info(
        f"[Pipeline] Início do capítulo '{chapter_name or 'capítulo'}' "
        f"(modo={'PARÁGRAFOS' if strict_paragraph_mode else 'CAPÍTULO'}, "
        f"bloqueio_citacoes={'ON' if strict_citation_lock else 'OFF'})"
    )

    chapter_body_text, original_references = _split_text_before_references(chapter_text)
    normalized_original_references = _normalize_manual_references_text(original_references)
    source_citation_sig = _citation_signature(chapter_body_text)
    source_citation_count = len(_extract_citation_token_sequence(chapter_body_text))
    tagged_text, placeholder_to_token = tokenize_citations_for_llm(
        chapter_body_text,
        chapter_name=chapter_name,
    )
    normalized_manual_references = _normalize_manual_references_text(manual_references_text)
    effective_references = normalized_manual_references or normalized_original_references
    references_source = (
        "manual"
        if normalized_manual_references
        else ("auto-extraidas-do-texto" if normalized_original_references else "nenhuma")
    )
    cache_input = (
        f"{CITATION_PIPELINE_VERSION}\n"
        f"MODE:{'PARAGRAPH' if strict_paragraph_mode else 'CHAPTER'}\n"
        f"BODY:\n{tagged_text}\n"
        f"EFFECTIVE_REFS:\n{effective_references}"
    )
    cache_fingerprint = hashlib.md5(cache_input.encode("utf-8")).hexdigest()[:12]
    logger.debug(
        f"[Pipeline DEBUG] Entrada capítulo='{chapter_name or 'capítulo'}': "
        f"corpo_chars={len(chapter_body_text)}, placeholders={len(placeholder_to_token)}, "
        f"refs_auto_chars={len(normalized_original_references)}, "
        f"refs_manuais_chars={len(normalized_manual_references)}, cache_fp={cache_fingerprint}, "
        f"refs_fonte={references_source}, refs_efetivas_chars={len(effective_references)}, "
        f"cit_sig_in={source_citation_sig}, cit_count_in={source_citation_count}, "
        f"ph_sig_in={_placeholder_signature(tagged_text)}"
    )
    
    valid_models = list(PREFERRED_MODELS)
    if FALLBACK_MODEL not in valid_models:
        valid_models.append(FALLBACK_MODEL)

    logger.debug(
        f"[Pipeline DEBUG] Provider={AI_PROVIDER}; modelos configurados={valid_models}"
    )
    
    prompt = _build_chapter_prompt(tagged_text, previous_summaries)
    
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
            logger.info(
                f"[Resumo Pipeline] capítulo='{chapter_name or 'capítulo'}' | origem=cache | "
                f"modelo={selected_model} | coesao=cache | indice=cache"
            )
            logger.debug(
                f"[Pipeline DEBUG] Cache hit em '{chapter_name or 'capítulo'}' com {selected_model}; "
                "etapas de IA foram puladas nesta execução"
            )
            return cached_result
        
        try:
            system_instruction = f"{SYSTEM_INSTRUCTION}\n\n{CITATION_TAG_RULE}"
            
            for attempt in range(AI_MAX_RETRIES):
                try:
                    corrective_placeholders_used = False
                    cohesion_stage_status = "nao-aplicada"
                    logger.debug(f"Tentativa {attempt + 1}/{AI_MAX_RETRIES}")
                    if strict_paragraph_mode:
                        logger.info("Modo estrito por parágrafos ativado")
                        result_text, paragraph_stats = _rewrite_by_paragraphs(
                            client,
                            selected_model,
                            system_instruction,
                            tagged_text,
                            previous_summaries,
                            chapter_name,
                        )
                        logger.debug(
                            f"[Pipeline DEBUG] Estatísticas parágrafos: "
                            f"total={paragraph_stats['total']}, "
                            f"reescritos={paragraph_stats['rewritten']}, "
                            f"fallback={paragraph_stats['fallback']}, "
                            f"vazios={paragraph_stats['empty']}"
                        )
                    else:
                        result_text = _generate_with_groq(
                            client,
                            selected_model,
                            system_instruction,
                            prompt,
                            AI_TEMPERATURE,
                        )

                    if not _placeholders_preserved(tagged_text, result_text):
                        logger.warning(
                            f"[Refs] Placeholders alterados pela IA em '{chapter_name or 'capítulo'}'. "
                            "Executando tentativa corretiva."
                        )
                        logger.debug(
                            f"[Refs DEBUG] Diferença antes da tentativa corretiva: "
                            f"{_summarize_placeholder_diff(tagged_text, result_text)}"
                        )
                        corrective_prompt = (
                            "Você removeu ou alterou placeholders de citação. "
                            "Reescreva novamente mantendo TODOS os marcadores [TAG_CIT_X] "
                            "exatamente na mesma quantidade do texto original.\n\n"
                            f"TEXTO ORIGINAL COM MARCADORES:\n{tagged_text}\n\n"
                            f"SUA VERSÃO ANTERIOR:\n{result_text}"
                        )
                        corrected_text = _generate_with_groq(
                            client,
                            selected_model,
                            system_instruction,
                            corrective_prompt,
                            0.0,
                        )
                        if _placeholders_preserved(tagged_text, corrected_text):
                            result_text = corrected_text
                            corrective_placeholders_used = True
                            logger.debug("[Refs DEBUG] Tentativa corretiva restaurou os placeholders com sucesso")
                        else:
                            fail_msg = (
                                f"[Refs] Tentativa corretiva falhou em '{chapter_name or 'capítulo'}'. "
                                + (
                                    "Abortando capítulo por bloqueio duro de citações."
                                    if strict_citation_lock
                                    else "Usando texto com placeholders originais para preservar citações."
                                )
                            )
                            logger.warning(fail_msg)
                            logger.debug(
                                f"[Refs DEBUG] Diferença após tentativa corretiva: "
                                f"{_summarize_placeholder_diff(tagged_text, corrected_text)}"
                            )
                            if strict_citation_lock:
                                raise APIException("Bloqueio duro de citações: placeholders não preservados após tentativa corretiva")
                            result_text = tagged_text

                    # Etapa obrigatória e conservadora de coesão global do capítulo.
                    cohesion_prompt = _build_cohesion_prompt(result_text, previous_summaries)
                    cohesion_text = _generate_with_groq(
                        client,
                        selected_model,
                        system_instruction,
                        cohesion_prompt,
                        0.2,
                    ).strip()
                    if _placeholders_preserved(result_text, cohesion_text):
                        result_text = cohesion_text
                        cohesion_stage_status = "ok"
                        logger.debug("[Coesao DEBUG] Ajuste global de coesão aplicado com sucesso")
                    else:
                        cohesion_stage_status = "fallback-seguranca"
                        logger.warning(
                            f"[Coesao] Ajuste global alterou placeholders em '{chapter_name or 'capítulo'}'; "
                            "mantendo versão anterior para segurança."
                        )
                        logger.debug(
                            "[Coesao DEBUG] Diferença de placeholders na etapa de coesão: "
                            + _summarize_placeholder_diff(result_text, cohesion_text)
                        )

                    logger.debug("[Pipeline DEBUG] Restaurando placeholders para citações originais")
                    result_text = restore_citations_from_placeholders(result_text, placeholder_to_token)
                    logger.debug("[Pipeline DEBUG] Aplicando política automática de boxes")
                    result_text = enforce_box_policy(result_text, chapter_name=chapter_name)
                    logger.debug("[Pipeline DEBUG] Validando obrigatoriedade do BOX_RESUMO")
                    result_text = ensure_mandatory_summary_box(result_text, chapter_name=chapter_name)
                    logger.debug(
                        f"[Pipeline DEBUG] Anexando referências ao resultado final (fonte={references_source})"
                    )
                    result_text = append_manual_references(result_text, effective_references)

                    logger.debug("[Pipeline DEBUG] Gerando metadados de índice em etapa dedicada")
                    index_data = _build_index_metadata(
                        client,
                        selected_model,
                        system_instruction,
                        result_text,
                        chapter_name=chapter_name,
                    )
                    index_source = index_data.get("_source", "desconhecido")
                    result_text = append_index_metadata(result_text, index_data)

                    final_body_text, _final_references = _split_text_before_references(result_text)
                    final_citation_sig = _citation_signature(final_body_text)
                    final_citation_count = len(_extract_citation_token_sequence(final_body_text))

                    if final_citation_sig != source_citation_sig or final_citation_count != source_citation_count:
                        logger.warning(
                            f"[Refs] Integridade de citações divergente em '{chapter_name or 'capítulo'}': "
                            f"sig_in={source_citation_sig}, sig_out={final_citation_sig}, "
                            f"count_in={source_citation_count}, count_out={final_citation_count}"
                        )
                        if strict_citation_lock:
                            raise APIException("Bloqueio duro de citações: assinatura final de citações divergente do texto original")

                    logger.debug(
                        f"[Pipeline DEBUG] Saída final de '{chapter_name or 'capítulo'}': {len(result_text)} caracteres"
                    )
                    logger.debug(
                        f"[Pipeline DEBUG] Auditoria citações: sig_in={source_citation_sig}, "
                        f"sig_out={final_citation_sig}, count_in={source_citation_count}, count_out={final_citation_count}"
                    )
                    logger.info(
                        f"[Resumo Pipeline] capítulo='{chapter_name or 'capítulo'}' | "
                        f"modelo={selected_model} | revisao={'ok+corretiva' if corrective_placeholders_used else 'ok'} | "
                        f"coesao={cohesion_stage_status} | indice={index_source} | refs={references_source}"
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
                    if any(x in error_msg.lower() for x in ["429", "quota", "exhausted", "limit", "503", "over capacity"]):
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
