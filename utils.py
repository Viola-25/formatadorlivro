"""
Funções utilitárias consolidadas para a aplicação.
Centraliza lógica comum para evitar duplicação.
"""

import os
import re
from typing import Dict, Any, Tuple
from config import OUTPUT_DIR, TEMP_DIR, PROGRESS_FILE
from logger import logger
import json
import io
from typing import List, Callable
import difflib
import unicodedata
from typing import Iterable, Optional


def delete_chapter_safe(
    state: Dict[str, Any],
    chapter_name: str,
    gerenciador: Any = None
) -> Tuple[bool, str]:
    """
    Remove um capítulo de forma segura e consistente.
    
    Limpa:
    - status_capitulos
    - indice_capitulos
    - Seções do gerenciador de índice
    - Arquivos temporários (.ai.txt)
    - Arquivos de saída (.docx, .pdf)
    
    Args:
        state: Estado do app (session_state.app_state)
        chapter_name: Nome do arquivo/capítulo
        gerenciador: Instância de GerenciadorIndice (opcional)
        
    Returns:
        Tupla (sucesso: bool, mensagem: str)
    """
    try:
        # 1. Obter informações do capítulo antes de deletar
        status_info = state.get("status_capitulos", {}).get(chapter_name, {})
        titulo_indice = status_info.get("titulo_indice", "")
        
        # 2. Remover do índice de capítulos
        if "indice_capitulos" in state and titulo_indice in state["indice_capitulos"]:
            del state["indice_capitulos"][titulo_indice]
            logger.debug(f"Removido do indice_capitulos: {titulo_indice}")
        
        # 3. Remover do status
        if chapter_name in state.get("status_capitulos", {}):
            del state["status_capitulos"][chapter_name]
            logger.debug(f"Removido do status_capitulos: {chapter_name}")
        
        # 4. Remover de seções no gerenciador (se fornecido)
        if gerenciador and titulo_indice:
            try:
                secoes = gerenciador.estado.get("secoes", {})
                for secao_nome, capitulos_secao in secoes.items():
                    if titulo_indice in capitulos_secao:
                        capitulos_secao.remove(titulo_indice)
                        logger.debug(f"Removido da seção '{secao_nome}': {titulo_indice}")
                
                # Remove de ordem_capitulos
                ordem = gerenciador.estado.get("ordem_capitulos", [])
                if titulo_indice in ordem:
                    ordem.remove(titulo_indice)
                    logger.debug(f"Removido de ordem_capitulos: {titulo_indice}")
                
                gerenciador._salvar_estado()
            except Exception as e:
                logger.warning(f"Erro ao remover de seções: {e}")
        
        # 5. Limpar arquivos
        base_name = os.path.splitext(chapter_name)[0] if '.' in chapter_name else chapter_name
        safe_chapter_name = re.sub(r'[\\/*?:"<>|]', "", base_name).replace(" ", "_")
        
        # Procura por arquivos com padrões similares (pode haver variações no nome)
        files_to_remove = []
        
        # DOCX e PDF
        docx_path = os.path.join(OUTPUT_DIR, f"Capitulo_{safe_chapter_name}_Revisado.docx")
        pdf_path = docx_path.replace(".docx", ".pdf")
        files_to_remove.extend([docx_path, pdf_path])
        
        # AI text file
        ai_txt_path = os.path.join(TEMP_DIR, f"{chapter_name}.ai.txt")
        files_to_remove.append(ai_txt_path)
        
        # Buscar outros padrões de arquivo
        if os.path.exists(OUTPUT_DIR):
            for f in os.listdir(OUTPUT_DIR):
                if safe_chapter_name in f:
                    files_to_remove.append(os.path.join(OUTPUT_DIR, f))
        
        # Remover arquivos
        for file_path in files_to_remove:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Arquivo removido: {file_path}")
                except Exception as e:
                    logger.warning(f"Não foi possível remover {file_path}: {e}")
        
        return True, f"✅ Capítulo '{chapter_name}' excluído completamente!"
        
    except Exception as e:
        logger.error(f"Erro ao deletar capítulo {chapter_name}: {e}", exc_info=True)
        return False, f"❌ Erro ao excluir capítulo: {str(e)}"


def validate_api_key(api_key: str) -> Tuple[bool, str]:
    """
    Valida o formato e presença da chave da API Groq.
    
    Args:
        api_key: Chave a validar
        
    Returns:
        Tupla (válida: bool, mensagem: str)
    """
    if not api_key or not api_key.strip():
        return False, "❌ Nenhuma chave da API detectada. Preencha o campo, configure GROQ_API_KEY ou GROQ_API_KEY_FILE."
    
    api_key = api_key.strip()
    
    if not api_key.startswith("gsk_"):
        return False, "⚠️ Formato inesperado. A chave da Groq normalmente começa com 'gsk_'. Verifique e tente novamente."
    
    if len(api_key) < 20:
        return False, "⚠️ Chave parece muito curta. Verifique se foi copiada corretamente."
    
    return True, "✅ Chave da API válida"


def standardize_chapter_status(state: Dict[str, Any]) -> None:
    """
    Converte qualquer status_capitulos em formato dict padronizado.
    Útil para migrar dados antigos.
    
    Args:
        state: Estado a padronizar
    """
    status_capitulos = state.get("status_capitulos", {})
    
    for chapter_name, status_info in status_capitulos.items():
        # Se for string, converte para dict
        if isinstance(status_info, str):
            status_capitulos[chapter_name] = {
                "status": status_info,
                "resumo": "",
                "titulo_indice": ""
            }
            logger.debug(f"Standardized status for {chapter_name}: {status_info}")
        
        # Se for dict mas faltar campos, preenche
        elif isinstance(status_info, dict):
            if "status" not in status_info:
                status_info["status"] = "Desconhecido"
            if "resumo" not in status_info:
                status_info["resumo"] = ""
            if "titulo_indice" not in status_info:
                status_info["titulo_indice"] = ""


def get_chapter_safe_filename(chapter_name: str) -> str:
    """
    Gera um nome de arquivo seguro a partir do nome do capítulo.
    
    Args:
        chapter_name: Nome original do capítulo
        
    Returns:
        Nome sanitizado para uso em arquivos
    """
    base_name = os.path.splitext(chapter_name)[0] if '.' in chapter_name else chapter_name
    safe_name = re.sub(r'[\\/*?:"<>|]', "", base_name).replace(" ", "_")
    return safe_name


def get_processing_stats(state: Dict[str, Any]) -> Dict[str, int]:
    """
    Calcula estatísticas de processamento do estado.
    
    Args:
        state: Estado do app
        
    Returns:
        Dict com contadores {total, concluidos, pendentes, erros, processando}
    """
    status_capitulos = state.get("status_capitulos", {})
    
    stats = {
        "total": len(status_capitulos),
        "concluidos": 0,
        "pendentes": 0,
        "erros": 0,
        "processando": 0
    }
    
    for status_info in status_capitulos.values():
        if isinstance(status_info, dict):
            status = status_info.get("status", "")
        else:
            status = status_info
        
        if status == "Concluído":
            stats["concluidos"] += 1
        elif status == "Pendente":
            stats["pendentes"] += 1
        elif status == "Em Processamento":
            stats["processando"] += 1
        elif "Erro" in status:
            stats["erros"] += 1
    
    return stats


def cleanup_old_backups(max_backups: int = 5) -> None:
    """
    Remove backups antigos, mantendo apenas os N mais recentes.
    
    Args:
        max_backups: Número máximo de backups a manter
    """
    backup_dir = os.path.join(os.path.dirname(PROGRESS_FILE), "backups")
    
    if not os.path.exists(backup_dir):
        return
    
    try:
        backups = []
        for f in os.listdir(backup_dir):
            if f.endswith(".json"):
                full_path = os.path.join(backup_dir, f)
                mtime = os.path.getmtime(full_path)
                backups.append((full_path, mtime))
        
        # Ordena por data (mais recentes primeiro)
        backups.sort(key=lambda x: x[1], reverse=True)
        
        # Remove backups antigos
        for file_path, _ in backups[max_backups:]:
            os.remove(file_path)
            logger.debug(f"Backup antigo removido: {file_path}")
    
    except Exception as e:
        logger.warning(f"Erro ao limpar backups antigos: {e}")


def bulk_delete_chapters(state: Dict[str, Any], chapter_names: List[str], gerenciador: Any = None) -> Dict[str, Tuple[bool, str]]:
    """
    Deleta vários capítulos usando `delete_chapter_safe` e retorna resultados por capítulo.

    Args:
        state: Estado da aplicação
        chapter_names: Lista de nomes de arquivo de capítulos a remover
        gerenciador: Instância de GerenciadorIndice (opcional)

    Returns:
        Dict mapeando capítulo -> (sucesso, mensagem)
    """
    results = {}
    for ch in chapter_names:
        try:
            success, msg = delete_chapter_safe(state, ch, gerenciador=gerenciador)
            results[ch] = (success, msg)
        except Exception as e:
            logger.error(f"Erro ao deletar em lote {ch}: {e}", exc_info=True)
            results[ch] = (False, f"Erro interno: {e}")
    return results


def _normalize_text_for_matching(text: str) -> str:
    if not text:
        return ""
    # remove extension, version markers and normalize unicode
    text = re.sub(r"(?i)\b(vrs?|vers\.|versao|v)\s*\d+(?:[\._\-\d]*)", "", text)
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"\.(docx|txt|pdf)$", "", text, flags=re.IGNORECASE)
    text = unicodedata.normalize('NFD', text)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = re.sub(r"[^\w\s]", " ", text)
    return text.lower().strip()


_PT_STOPWORDS = {
    'em','na','no','de','da','e','o','a','dos','das','do','para','com','por','à','ao','a','um','uma','the'
}


def _tokenize(text: str) -> List[str]:
    s = _normalize_text_for_matching(text)
    toks = [t for t in re.split(r"\s+", s) if t and len(t) > 1 and t not in _PT_STOPWORDS]
    return toks


def identify_chapter_title_from_filename(state: Dict[str, Any], filename: str, gerenciador: Any = None) -> str | None:
    """
    Tenta identificar o título do índice correspondente a um arquivo enviado.

    Estratégia:
    - Normaliza nome do arquivo removendo versões e extensões
    - Compara tokens com títulos existentes no `gerenciador` (ou no estado)
    - Usa combinação de correspondência exata de tokens e correspondência aproximada
      via `difflib` para encontrar o melhor candidato.

    Retorna o título do índice correspondente ou `None` se não achar correspondência confiável.
    """
    try:
        if gerenciador:
            candidates = list(gerenciador.estado.get("indice_capitulos", {}).keys())
            # também inclua ordem_capitulos
            ordem = gerenciador.estado.get("ordem_capitulos", []) or []
            for t in ordem:
                if t not in candidates:
                    candidates.append(t)
        else:
            candidates = list(state.get("indice_capitulos", {}).keys())

        if not candidates:
            return None

        fname_tokens = _tokenize(filename)
        if not fname_tokens:
            return None

        best = None
        best_score = 0.0

        for cand in candidates:
            cand_tokens = _tokenize(cand)
            if not cand_tokens:
                continue

            # exact token intersection
            exact_matches = len(set(fname_tokens) & set(cand_tokens))

            # approximate matches: for each fname token, find close match in cand_tokens
            approx = 0
            for ft in fname_tokens:
                close = difflib.get_close_matches(ft, cand_tokens, n=1, cutoff=0.78)
                if close:
                    approx += 1

            # sequence similarity on full normalized strings
            s_fname = _normalize_text_for_matching(filename)
            s_cand = _normalize_text_for_matching(cand)
            seq_ratio = difflib.SequenceMatcher(None, s_fname, s_cand).ratio()

            # combine metrics
            token_score = (exact_matches + 0.8 * approx) / max(len(cand_tokens), 1)
            score = max(token_score, seq_ratio)

            # prefer shorter relative difference if tied
            if score > best_score:
                best_score = score
                best = cand

        # threshold tuned conservatively
        if best_score >= 0.38:
            logger.debug(f"Identificado '{filename}' como '{best}' (score={best_score:.2f})")
            return best
        logger.debug(f"Nenhuma correspondência confiável para '{filename}' (best_score={best_score:.2f})")
        return None
    except Exception as e:
        logger.warning(f"Erro ao identificar título para {filename}: {e}")
        return None


def suggest_index_title_with_ai(ai_text: str, filename: str, candidates: Iterable[str], api_key: Optional[str] = None, model_name: Optional[str] = None) -> Optional[str]:
    """
    Sugere um título do índice para o capítulo processado.

    Estratégia:
    - Se `api_key` e o pacote `groq` estiverem disponíveis, consulta o modelo para escolher
      o título mais apropriado dentre `candidates`.
    - Caso contrário, usa a heurística local `identify_chapter_title_from_filename`.

    Retorna o título escolhido ou `None`.
    """
    # Normalize candidate list
    cand_list = [c for c in (candidates or []) if c]
    if not cand_list:
        return None

    # Prefer AI-based suggestion when possible
    if api_key:
        try:
            try:
                from groq import Groq
            except Exception:
                Groq = None

            if Groq is not None:
                client = Groq(api_key=api_key)
                # Build concise prompt
                prompt = (
                    "Você é um classificador que, dado o texto de um capítulo, deve escolher o título mais apropriado "
                    "entre as opções fornecidas. Responda apenas com o título exato, sem pontuação adicional. Se nenhuma opção "
                    "for adequada, responda 'NENHUMA'.\n\n"
                    f"CAPÍTULO (trecho):\n{ai_text[:4000]}\n\n"
                    "OPÇÕES:\n" + "\n".join(f"- {c}" for c in cand_list[:100]) + "\n\n"
                    "Escolha a melhor opção:"
                )

                # Use a safe model choice via client.chat.completions.create
                resp = client.chat.completions.create(
                    model=(model_name or "gpt-4o-mini"),
                    temperature=0.0,
                    messages=[
                        {"role": "system", "content": "Classificador de títulos de índice - responda apenas com o título exato ou 'NENHUMA'."},
                        {"role": "user", "content": prompt},
                    ],
                )

                if resp and getattr(resp, 'choices', None):
                    content = resp.choices[0].message.content.strip()
                    # If model replied with one of the candidates, return it
                    for c in cand_list:
                        if content.lower() == c.lower():
                            logger.debug(f"AI sugeriu correspondência exata: {c} para arquivo {filename}")
                            return c
                    if content.upper().strip() == 'NENHUMA':
                        return None
                    # Fallback: try to match approximately
                    for c in cand_list:
                        if difflib.SequenceMatcher(None, content.lower(), c.lower()).ratio() > 0.9:
                            return c
        except Exception as e:
            logger.warning(f"Erro ao usar Groq para sugerir título: {e}")

    # Fallback to filename heuristic
    try:
        return identify_chapter_title_from_filename({}, filename, gerenciador=None)
    except Exception:
        return None


def bulk_move_chapters(gerenciador: Any, chapter_titles: List[str], target_section: str) -> Dict[str, bool]:
    """
    Move múltiplos capítulos (por título do índice) para uma seção alvo.

    Args:
        gerenciador: Instância de GerenciadorIndice
        chapter_titles: Lista de títulos (título do índice) a mover
        target_section: Nome da seção destino

    Returns:
        Dict mapeando título -> sucesso(bool)
    """
    results = {}
    for title in chapter_titles:
        try:
            ok = gerenciador.mover_capitulo_para_secao(title, target_section)
            results[title] = bool(ok)
        except Exception as e:
            logger.error(f"Erro ao mover {title} para {target_section}: {e}", exc_info=True)
            results[title] = False
    return results


def reprocess_chapters(chapter_filenames: List[str], api_key: str, process_files_func: Callable, temp_dir: str = TEMP_DIR, **process_kwargs) -> Dict[str, str]:
    """
    Reprocessa capítulos já salvos em `temp_dir` chamando a função `process_files_func`.

    Esta rotina tenta carregar o arquivo temporário correspondente a cada nome
    e invoca `process_files_func` com objetos em memória compatíveis.

    Args:
        chapter_filenames: Lista de nomes de arquivo (ex: 'Capitulo1.docx')
        api_key: Chave da API a ser usada
        process_files_func: Função de processamento (mesmo contrato que `process_files` em `app.py`)
        temp_dir: Diretório onde os arquivos temporários foram salvos
        process_kwargs: Argumentos extras para passar a `process_files_func`

    Returns:
        Dict mapeando nome de capítulo -> resultado/aviso
    """
    class _MemFile:
        def __init__(self, name: str, data: bytes):
            self.name = name
            self._data = data

        def getbuffer(self):
            return memoryview(self._data)

    prepared = []
    results = {}

    for fname in chapter_filenames:
        # Tenta caminhos previsíveis: TEMP_DIR/fname, TEMP_DIR/safe_name.*, OUTPUT_DIR/*safe_name*
        base = os.path.splitext(fname)[0]
        safe = re.sub(r'[\\/*?:"<>|]', '', base).replace(' ', '_')
        candidates = [os.path.join(temp_dir, fname)]

        # procura por arquivos que contenham o nome seguro em temp_dir
        try:
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    if safe in f and os.path.isfile(os.path.join(temp_dir, f)):
                        candidates.append(os.path.join(temp_dir, f))
        except Exception:
            pass

        # fallback para OUTPUT_DIR (ex: usar o DOCX gerado como fonte)
        try:
            if os.path.exists(OUTPUT_DIR):
                for f in os.listdir(OUTPUT_DIR):
                    if safe in f and os.path.isfile(os.path.join(OUTPUT_DIR, f)):
                        candidates.append(os.path.join(OUTPUT_DIR, f))
        except Exception:
            pass

        found = False
        for path in candidates:
            if not path:
                continue
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'rb') as rf:
                    data = rf.read()
                # Use fname as display name, but keep original bytes
                prepared.append(_MemFile(fname, data))
                results[fname] = f"Pronto para reprocessar (fonte: {os.path.basename(path)})"
                found = True
                break
            except Exception as e:
                logger.error(f"Erro ao ler candidato {path} para {fname}: {e}", exc_info=True)
                continue

        if not found:
            results[fname] = f"Arquivo temporário/backup não encontrado para: {fname}"

    # Se nada preparado, retorna mensagens
    if not prepared:
        return results

    try:
        # Chama a função de processamento com os objetos preparados
        process_files_func(prepared, api_key, **process_kwargs)
    except Exception as e:
        logger.error(f"Erro ao reprocessar lote: {e}", exc_info=True)
        # Marca todos como com erro genérico
        for fname in chapter_filenames:
            results[fname] = f"Erro ao reprocessar: {e}"

    return results
