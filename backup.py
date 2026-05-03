"""
Sistema de backup e versionamento para o arquivo de progresso.
Permite recuperação de versões anteriores e proteção contra corrupção.
"""

import json
import os
import shutil
from datetime import datetime
from typing import Optional, List
from config import PROGRESS_FILE, BACKUP_DIR, MAX_BACKUPS
from exceptions import BackupException
from logger import logger


def generate_backup_filename() -> str:
    """
    Gera nome de arquivo de backup com timestamp.
    
    Returns:
        Nome do arquivo: progresso_YYYY-MM-DD_HHmmss.json
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"progresso_{timestamp}.json"


def create_backup() -> Optional[str]:
    """
    Cria backup do arquivo de progresso.
    
    Returns:
        Caminho do arquivo de backup criado, ou None se falhar
    """
    if not os.path.exists(PROGRESS_FILE):
        logger.debug("Arquivo de progresso não existe. Backup não necessário.")
        return None
    
    try:
        backup_filename = generate_backup_filename()
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        # Garantir que o diretório de backup exista
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
        except Exception as mkdir_err:
            logger.error(f"Falha ao criar diretório de backup '{BACKUP_DIR}': {mkdir_err}")
            raise

        # Copia o arquivo de progresso para o local de backup
        shutil.copy2(PROGRESS_FILE, backup_path)
        logger.info(f"Backup criado: {os.path.abspath(backup_path)}")
        
        # Remove backups antigos se exceder MAX_BACKUPS
        cleanup_old_backups()
        
        return backup_path
        
    except FileNotFoundError as e:
        logger.error(f"Erro ao criar backup - arquivo não encontrado: {e}. PROGRESS_FILE={PROGRESS_FILE}, BACKUP_DIR={BACKUP_DIR}")
        parent = os.path.dirname(os.path.abspath(backup_path))
        try:
            logger.debug(f"Conteúdo do diretório pai ({parent}): {os.listdir(parent)}")
        except Exception:
            logger.debug(f"Não foi possível listar o diretório pai: {parent}")
        raise BackupException(f"Falha ao criar backup: {e}")
    except OSError as e:
        logger.error(f"Erro ao criar backup (OS error): {e}. PROGRESS_FILE={PROGRESS_FILE}, BACKUP_DIR={BACKUP_DIR}")
        raise BackupException(f"Falha ao criar backup: {e}")
    except Exception as e:
        logger.error(f"Erro ao criar backup: {e}")
        raise BackupException(f"Falha ao criar backup: {e}")


def restore_backup(backup_filename: str) -> bool:
    """
    Restaura um backup anterior do progresso.
    
    Args:
        backup_filename: Nome do arquivo de backup (ex: progresso_2024-01-15_143022.json)
        
    Returns:
        True se restaurado com sucesso
    """
    try:
        backup_path = os.path.join(BACKUP_DIR, backup_filename)
        
        if not os.path.exists(backup_path):
            logger.error(f"Arquivo de backup não encontrado: {backup_path}")
            raise BackupException(f"Backup não encontrado: {backup_filename}")
        
        # Cria backup do estado atual antes de restaurar
        if os.path.exists(PROGRESS_FILE):
            create_backup()
        
        shutil.copy2(backup_path, PROGRESS_FILE)
        logger.info(f"Progresso restaurado de: {backup_filename}")
        
        return True
        
    except BackupException:
        raise
    except Exception as e:
        logger.error(f"Erro ao restaurar backup: {e}")
        raise BackupException(f"Falha ao restaurar backup: {e}")


def list_backups() -> List[dict]:
    """
    Lista todos os backups disponíveis com metadados.
    
    Returns:
        Lista de dicts com info de cada backup
    """
    try:
        backups = []
        
        if not os.path.exists(BACKUP_DIR):
            return backups
        
        for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
            if not filename.startswith("progresso_") or not filename.endswith(".json"):
                continue
            
            filepath = os.path.join(BACKUP_DIR, filename)
            
            try:
                size_bytes = os.path.getsize(filepath)
                mtime = os.path.getmtime(filepath)
                mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                backups.append({
                    "filename": filename,
                    "size_kb": round(size_bytes / 1024, 2),
                    "created": mtime_str
                })
                
            except Exception as e:
                logger.warning(f"Erro ao obter info de {filename}: {e}")
        
        return backups
        
    except Exception as e:
        logger.error(f"Erro ao listar backups: {e}")
        return []


def cleanup_old_backups() -> int:
    """
    Remove backups mais antigos quando ultrapassa MAX_BACKUPS.
    
    Returns:
        Número de backups removidos
    """
    try:
        if not os.path.exists(BACKUP_DIR):
            return 0
        
        backups = sorted(os.listdir(BACKUP_DIR), reverse=True)
        removed_count = 0
        
        for backup_file in backups[MAX_BACKUPS:]:
            backup_path = os.path.join(BACKUP_DIR, backup_file)
            try:
                os.remove(backup_path)
                removed_count += 1
                logger.debug(f"Backup antigo removido: {backup_file}")
            except Exception as e:
                logger.warning(f"Erro ao remover backup {backup_file}: {e}")
        
        if removed_count > 0:
            logger.info(f"Limpeza de backups: {removed_count} arquivo(s) removido(s)")
        
        return removed_count
        
    except Exception as e:
        logger.error(f"Erro ao limpar backups antigos: {e}")
        return 0


def validate_progress_file() -> bool:
    """
    Valida integridade do arquivo de progresso.
    
    Returns:
        True se válido, False caso contrário
    """
    if not os.path.exists(PROGRESS_FILE):
        logger.warning("Arquivo de progresso não existe")
        return False
    
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            json.load(f)
        logger.debug("Arquivo de progresso validado")
        return True
    except json.JSONDecodeError as e:
        logger.error(f"Arquivo de progresso corrompido: {e}")
        return False
    except Exception as e:
        logger.error(f"Erro ao validar progresso: {e}")
        return False
