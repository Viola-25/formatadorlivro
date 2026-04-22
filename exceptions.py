"""
Exceções customizadas para a plataforma de revisão de livros.
"""


class BookFormatterException(Exception):
    """Exceção base para todos os erros da plataforma."""
    pass


class APIException(BookFormatterException):
    """Erro relacionado à API de IA."""
    pass


class APIQuotaExhausted(APIException):
    """Cota/limite da API foi excedido."""
    pass


class APIRateLimitExceeded(APIException):
    """Taxa de requisições excedida."""
    pass


class ModelNotAvailable(APIException):
    """Modelo de IA não está disponível."""
    pass


class DocumentException(BookFormatterException):
    """Erro relacionado ao processamento de documentos."""
    pass


class DocumentFormatError(DocumentException):
    """Formato de documento não suportado."""
    pass


class DocumentParseError(DocumentException):
    """Erro ao fazer parse do documento."""
    pass


class DocumentTooLarge(DocumentException):
    """Documento excede o tamanho máximo permitido."""
    pass


class FormattingException(BookFormatterException):
    """Erro relacionado à formatação de saída."""
    pass


class InvalidFormattingTagsError(FormattingException):
    """Tags de formatação inválidas ou malformadas."""
    pass


class PDFConversionError(FormattingException):
    """Erro ao converter documento para PDF."""
    pass


class ValidationException(BookFormatterException):
    """Erro de validação de dados."""
    pass


class InvalidIndexData(ValidationException):
    """Dados de índice inválidos ou malformados."""
    pass


class CacheException(BookFormatterException):
    """Erro relacionado ao cache."""
    pass


class BackupException(BookFormatterException):
    """Erro relacionado ao backup de progresso."""
    pass
