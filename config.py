"""
Configuração centralizada da plataforma de revisão de livros.
Define constantes, estilos, modelos de IA e parâmetros globais.
"""

import os
from typing import List

# ========== CAMINHOS E DIRETÓRIOS ==========
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
TEMP_DIR = os.getenv("TEMP_DIR", "temp")
PROGRESS_FILE = os.getenv("PROGRESS_FILE", "progresso.json")
LOG_DIR = os.getenv("LOG_DIR", "logs")
CACHE_DIR = os.getenv("CACHE_DIR", ".cache")

# Criar diretórios se não existirem
for dir_path in [OUTPUT_DIR, TEMP_DIR, LOG_DIR, CACHE_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ========== CONFIGURAÇÕES DE LOGGING ==========
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# ========== CONFIGURAÇÕES DE IA E MODELOS ==========
# Ordem de preferência de modelos (tenta em sequência)
PREFERRED_MODELS: List[str] = [
    "models/gemini-2.5-pro",
    "models/gemini-2.5-flash",
    "models/gemini-pro-latest",
    "models/gemini-flash-latest",
    "models/gemini-2.0-flash",
    "models/gemini-1.5-pro",
    "models/gemini-1.5-flash",
    "models/gemini-pro"
]

# Fallback se nenhum modelo disponível
FALLBACK_MODEL = "gemini-2.0-flash"

# Configurações de geração de conteúdo
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "2"))
AI_RETRY_DELAY = int(os.getenv("AI_RETRY_DELAY", "15"))

# ========== GUIA DE ESTILO E INSTRUÇÕES ==========
STYLE_GUIDE = (
    "Tom formal e acadêmico; 3ª pessoa ou voz passiva; "
    "Terminologia técnica do Ministério da Saúde; Proibido gírias."
)

SYSTEM_INSTRUCTION = (
    "Você é um Editor-Chefe Médico rigoroso, especialista em Atenção Primária à Saúde (APS). "
    "Sua função é revisar, corrigir e reescrever textos médicos focados em guias clínicos e protocolos da APS, "
    "garantindo precisão científica, coesão narrativa entre os capítulos e aderência estrita ao guia de estilo."
)

# ========== TAGS DE FORMATAÇÃO ==========
FORMATTING_TAGS = {
    "BOX_RESUMO": "[BOX_RESUMO]",
    "BOX_RECOMENDACAO": "[BOX_RECOMENDACAO]",
    "BOX_ATENCAO": "[BOX_ATENCAO]",
    "SUGESTAO_EDICAO": "[SUGESTAO_EDICAO]",
    "LINKS_ATUALIZACAO": "[LINKS_ATUALIZACAO]",
    "DADOS_INDICE": "[DADOS_INDICE]"
}

# ========== CONFIGURAÇÕES DE FORMATAÇÃO DOCX ==========
# Dimensões em centímetros
DOCUMENT_WIDTH_CM = 17
DOCUMENT_HEIGHT_CM = 24
MARGIN_CM = 1.5

# Fontes e tamanhos
DEFAULT_FONT = "Times New Roman"
DEFAULT_FONT_SIZE = 10
HEADING_FONT = "Arial"
HEADING_FONT_SIZE = 14
BOX_FONT_SIZE = 9

# Cores (RGB)
COLOR_NORMAL = (0, 0, 0)
COLOR_ALERT = (180, 0, 0)
COLOR_ERROR = (255, 0, 0)
COLOR_BOX_BG = "F2F2F2"

# ========== CONFIGURAÇÕES DE VALIDAÇÃO ==========
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
ALLOWED_INPUT_FORMATS = ["docx", "txt", "png", "jpg"]
ALLOWED_TEXT_FORMATS = ["docx", "txt"]

# ========== CONFIGURAÇÕES DE CACHE ==========
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "True").lower() == "true"
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))

# ========== CONFIGURAÇÕES DE BACKUP ==========
BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "True").lower() == "true"
BACKUP_DIR = os.path.join(CACHE_DIR, "backups")
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", "5"))

os.makedirs(BACKUP_DIR, exist_ok=True)
