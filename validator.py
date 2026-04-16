"""
Validação de dados com Pydantic.
Garante que estruturas JSON estejam corretas antes de usar.
"""

from typing import List
from pydantic import BaseModel, Field, validator
from exceptions import InvalidIndexData
from logger import logger


class ChapterIndex(BaseModel):
    """
    Schema validado para dados de índice de capítulo.
    """
    titulo_capitulo: str = Field(..., min_length=1, max_length=500, description="Título do capítulo")
    subtopicos: List[str] = Field(
        ..., 
        min_items=1, 
        max_items=10,
        description="Lista de subtópicos (3-5 recomendado)"
    )
    
    @validator('titulo_capitulo')
    def titulo_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Título do capítulo não pode estar vazio")
        return v.strip()
    
    @validator('subtopicos')
    def subtopicos_not_empty(cls, v):
        for subtopic in v:
            if not subtopic or not subtopic.strip():
                raise ValueError("Subtópicos não podem conter valores vazios")
        return [s.strip() for s in v]
    
    class Config:
        extra = "forbid"  # Rejeita campos extras
        str_strip_whitespace = True


class ChapterStatus(BaseModel):
    """
    Schema validado para status de um capítulo processado.
    """
    status: str = Field(..., description="Status do processamento (Pendente, Em Processamento, Concluído, Erro)")
    resumo: str = Field(default="", description="Resumo do capítulo processado")
    titulo_indice: str = Field(default="", description="Título extraído do índice")
    
    @validator('status')
    def status_valid(cls, v):
        valid_statuses = ["Pendente", "Em Processamento", "Concluído", "Erro", "Ignorado (Não é texto)"]
        if v not in valid_statuses:
            raise ValueError(f"Status deve ser um de: {valid_statuses}")
        return v


def validate_index_data(data: dict) -> ChapterIndex:
    """
    Valida dados de índice usando Pydantic.
    
    Args:
        data: Dicionário com dados de índice
        
    Returns:
        Objeto ChapterIndex validado
        
    Raises:
        InvalidIndexData: Se dados forem inválidos
    """
    try:
        return ChapterIndex(**data)
    except Exception as e:
        logger.error(f"Dados de índice inválidos: {e}")
        raise InvalidIndexData(f"Validação de índice falhou: {str(e)}")


def validate_chapter_status(data: dict) -> ChapterStatus:
    """
    Valida dados de status de capítulo.
    
    Args:
        data: Dicionário com dados de status
        
    Returns:
        Objeto ChapterStatus validado
        
    Raises:
        InvalidIndexData: Se dados forem inválidos
    """
    try:
        return ChapterStatus(**data)
    except Exception as e:
        logger.error(f"Dados de status inválidos: {e}")
        raise InvalidIndexData(f"Validação de status falhou: {str(e)}")


# Exemplo de uso:
if __name__ == "__main__":
    # Teste válido
    try:
        index = validate_index_data({
            "titulo_capitulo": "Introdução à APS",
            "subtopicos": ["Conceito", "Importância", "Aplicação"]
        })
        print("✓ Índice validado:", index)
    except InvalidIndexData as e:
        print("✗ Erro:", e)
    
    # Teste inválido
    try:
        index = validate_index_data({
            "titulo_capitulo": "",  # Erro: vazio
            "subtopicos": ["Conceito"]
        })
    except InvalidIndexData as e:
        print("✗ Erro esperado:", e)
