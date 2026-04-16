"""
Sistema de cache para otimizar requisições à API.
Evita reprocessar documentos idênticos.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from config import CACHE_DIR, CACHE_ENABLED, CACHE_TTL_HOURS
from exceptions import CacheException
from logger import logger


def calculate_text_hash(text: str) -> str:
    """
    Calcula hash MD5 do texto para uso como chave de cache.
    
    Args:
        text: Texto a ser hasheado
        
    Returns:
        Hash hexadecimal do texto
    """
    return hashlib.md5(text.encode()).hexdigest()


def get_cache_key(text: str, model_name: str) -> str:
    """
    Gera chave de cache combinando hash do texto + nome do modelo.
    
    Args:
        text: Texto original
        model_name: Nome do modelo de IA usado
        
    Returns:
        Chave única para o cache
    """
    text_hash = calculate_text_hash(text)
    return f"{text_hash}_{model_name}"


def cache_get(text: str, model_name: str) -> Optional[str]:
    """
    Recupera resultado do cache se existir e não expirou.
    
    Args:
        text: Texto original para recuperar resultado
        model_name: Nome do modelo usado
        
    Returns:
        Texto processado do cache, ou None se não encontrado/expirado
    """
    if not CACHE_ENABLED:
        return None
    
    try:
        cache_key = get_cache_key(text, model_name)
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        if not os.path.exists(cache_file):
            logger.debug(f"Cache miss para {cache_key}")
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        # Verifica expiração
        cached_at = datetime.fromisoformat(cache_data["cached_at"])
        expires_at = cached_at + timedelta(hours=CACHE_TTL_HOURS)
        
        if datetime.now() > expires_at:
            logger.info(f"Cache expirado para {cache_key}. Removendo...")
            os.remove(cache_file)
            return None
        
        logger.info(f"Cache hit para {cache_key}")
        return cache_data["result"]
        
    except Exception as e:
        logger.warning(f"Erro ao acessar cache: {e}")
        return None


def cache_set(text: str, model_name: str, result: str) -> bool:
    """
    Armazena resultado em cache.
    
    Args:
        text: Texto original
        model_name: Nome do modelo
        result: Resultado processado pela IA
        
    Returns:
        True se salvo com sucesso, False caso contrário
    """
    if not CACHE_ENABLED:
        return False
    
    try:
        cache_key = get_cache_key(text, model_name)
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        cache_data = {
            "cached_at": datetime.now().isoformat(),
            "model": model_name,
            "text_hash": calculate_text_hash(text),
            "result": result
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Cache salvo para {cache_key}")
        return True
        
    except Exception as e:
        logger.warning(f"Erro ao salvar em cache: {e}")
        return False


def clear_cache() -> int:
    """
    Limpa todos os arquivos de cache expirados.
    
    Returns:
        Número de arquivos removidos
    """
    try:
        removed_count = 0
        
        for filename in os.listdir(CACHE_DIR):
            if not filename.endswith(".json"):
                continue
                
            cache_file = os.path.join(CACHE_DIR, filename)
            
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                cached_at = datetime.fromisoformat(cache_data["cached_at"])
                expires_at = cached_at + timedelta(hours=CACHE_TTL_HOURS)
                
                if datetime.now() > expires_at:
                    os.remove(cache_file)
                    removed_count += 1
                    logger.debug(f"Cache removido: {filename}")
                    
            except Exception as e:
                logger.warning(f"Erro ao processar cache {filename}: {e}")
        
        logger.info(f"Cache limpo: {removed_count} arquivo(s) removido(s)")
        return removed_count
        
    except Exception as e:
        logger.error(f"Erro ao limpar cache: {e}")
        return 0
