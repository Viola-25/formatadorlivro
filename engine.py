import docx
import google.generativeai as genai
import json
import os
import time
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


def extract_text_from_docx(file_path: str) -> str:
    """
    Lê um arquivo .docx e retorna o texto completo.
    
    Args:
        file_path: Caminho do arquivo .docx
        
    Returns:
        Texto completo do documento
        
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

def process_chapter_text(chapter_text: str, previous_summaries: str, api_key: Optional[str] = None) -> str:
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
        return cached_result
    
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
5. Mantenha todas as citações/referências numéricas obrigatoriamente entre colchetes (ex: [1], [2], [12]), reutilizando o mesmo número caso a referência se repita. NÃO converta para sobrescrito no meio do texto. O formatador fará isso posteriormente. No final do documento, liste as referências na ordem exata de aparição no texto.
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
