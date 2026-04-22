"""
Configuração de logging estruturado para a plataforma.
"""

import logging
import logging.handlers
import sys
from config import LOG_LEVEL, LOG_FORMAT, LOG_FILE


def setup_logging() -> logging.Logger:
    """
    Configura logging estruturado com arquivo e console.
    
    Returns:
        logging.Logger: Logger configurado
    """
    logger = logging.getLogger("BookFormatter")
    logger.setLevel(LOG_LEVEL)
    
    # Evita adicionar handlers duplicados
    if logger.handlers:
        return logger
    
    # Handler para arquivo com rotação
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Aviso: Não foi possível configurar logging em arquivo: {e}")
    
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # Handler para console (apenas WARNING e acima)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(console_handler)
    
    return logger


# Logger global
logger = setup_logging()
