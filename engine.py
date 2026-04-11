import docx
import google.generativeai as genai
import json
import os
from typing import Dict, Any

STYLE_GUIDE = (
    "Tom formal e acadêmico; 3ª pessoa ou voz passiva; "
    "Terminologia técnica do Ministério da Saúde; Proibido gírias."
)

SYSTEM_INSTRUCTION = (
    "Você é um Editor-Chefe Médico rigoroso, especialista em Atenção Primária à Saúde (APS). "
    "Sua função é revisar, corrigir e reescrever textos médicos focados em guias clínicos e protocolos da APS, "
    "garantindo precisão científica, coesão narrativa entre os capítulos e aderência estrita ao guia de estilo."
)

def extract_text_from_docx(file_path: str) -> str:
    """
    Lê um arquivo .docx e retorna o texto completo.
    """
    try:
        doc = docx.Document(file_path)
        return '\n'.join([para.text for para in doc.paragraphs])
    except Exception as e:
        raise Exception(f"Erro ao ler o arquivo {file_path}: {e}")

def get_processed_chapters_summary(progress_file: str = 'progresso.json') -> str:
    """
    Lê o arquivo progresso.json e extrai os resumos dos capítulos já processados 
    para garantir coesão narrativa.
    """
    if not os.path.exists(progress_file):
        return ""
    
    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
            # Recupera o status dos capítulos. Assume que quando finalizado, 
            # o status pode ser um dicionário contendo um "resumo" do capítulo, 
            # ou haverá um campo dedicado "resumo_capitulos". 
            # Vamos buscar resumos armazenados no estado.
            status_capitulos = data.get("status_capitulos", {})
            resumos = []
            
            for cap, info in status_capitulos.items():
                if isinstance(info, dict) and info.get("status") == "Concluído" and info.get("resumo"):
                    resumos.append(f"Capítulo '{cap}': {info.get('resumo')}")
            
            return "\n\n".join(resumos)
    except Exception as e:
        print(f"Erro ao ler resumos anteriores: {e}")
        return ""

def process_chapter_text(chapter_text: str, previous_summaries: str, api_key: str = None) -> str:
    """
    Envia o texto para a API do Gemini processar de acordo com o STYLE_GUIDE, 
    System Instructions e inserção das tags requeridas.
    """
    if api_key:
        genai.configure(api_key=api_key)
    
    # O modelo gemini-1.5-pro suporta "system_instruction" para definir a persona.
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro",
        system_instruction=SYSTEM_INSTRUCTION
    )
    
    prompt = f"""
Você deve revisar e reescrever o texto do capítulo fornecido abaixo.

REGRAS DE ESTILO (STYLE_GUIDE):
{STYLE_GUIDE}

INSTRUÇÕES DE FORMATAÇÃO E ESTRUTURA:
1. Reescreva o texto de forma uniforme baseando-se estritamente no STYLE_GUIDE.
2. Insira as seguintes tags no texto, onde for mais apropriado:
   - [BOX_RESUMO]: Adicione no topo do texto com os pontos-chave e essenciais do capítulo.
   - [BOX_RECOMENDACAO]: Utilize para destacar intervenções clínicas importantes ou condutas recomendadas.
   - [BOX_ATENCAO]: Utilize para destacar riscos, contraindicações ou alertas clínicos cruciais.
   - [SUGESTAO_EDICAO]: Utilize caso encontre inconsistências técnicas, informando claramente o que precisa ser verificado ou validado pelo autor original.
3. No final do texto, pesquise e sugira 2 ou 3 links oficiais (ex: Ministério da Saúde, OMS, SBMFC ou outras sociedades médicas reconhecidas) para atualização do tema abordado, e insira-os sob a tag [LINKS_ATUALIZACAO].

CONTEXTO DOS CAPÍTULOS ANTERIORES:
(Utilize este contexto para manter a coesão narrativa, evitar repetições desnecessárias e garantir a continuidade do guia)
{previous_summaries if previous_summaries else "Nenhum capítulo processado anteriormente ou sem resumo disponível."}

TEXTO DO CAPÍTULO A SER REVISADO:
{chapter_text}
"""

    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.3, # Baixa temperatura para manter a resposta mais determinística e técnica
        )
    )
    
    return response.text
