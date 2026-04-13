import docx
import google.generativeai as genai
import json
import os
import time
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
        raise Exception(f"❌ Erro ao ler o arquivo '{file_path}': {e}")

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
        print(f"⚠️ Erro ao ler resumos anteriores: {e}")
        return ""

def process_chapter_text(chapter_text: str, previous_summaries: str, api_key: str = None) -> str:
    """
    Envia o texto para a API do Gemini processar de acordo com o STYLE_GUIDE, 
    System Instructions e inserção das tags requeridas.
    """
    if api_key:
        genai.configure(api_key=api_key)
    
    # Busca os modelos disponíveis para esta chave de API
    available_models = []
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        print(f"🔍 Modelos disponíveis mapeados na API.")
    except Exception as e:
        print(f"⚠️ Erro ao listar modelos: {e}")

    # Ordem de preferência de modelos
    target_models = [
        "models/gemini-2.5-pro",
        "models/gemini-2.5-flash",
        "models/gemini-pro-latest",
        "models/gemini-flash-latest",
        "models/gemini-2.0-flash",
        "models/gemini-1.5-pro", 
        "models/gemini-1.5-flash", 
        "models/gemini-pro"
    ]
    
    valid_models = []
    for tm in target_models:
        clean_name = tm.replace("models/", "")
        if tm in available_models or clean_name in available_models:
            valid_models.append(clean_name)
            
    if not valid_models:
        valid_models = ["gemini-2.0-flash"] # Fallback garantido
    
    prompt = f"""
Você deve revisar e reescrever o texto do capítulo fornecido abaixo.

REGRAS DE ESTILO (STYLE_GUIDE):
{STYLE_GUIDE}

INSTRUÇÕES DE FORMATAÇÃO E ESTRUTURA:
1. Reescreva o texto de forma uniforme baseando-se estritamente no STYLE_GUIDE.
2. Estruture o texto principal utilizando marcações de Títulos (H1) e Subtítulos (H2) curtos e claros em linhas isoladas. Eles devem obrigatoriamente estar SEM pontuação final (como pontos ou dois-pontos) para que o formatador DOCX consiga capturá-los e aplicar os estilos de cabeçalho.
3. Insira as seguintes tags no texto, onde for mais apropriado:
   - [BOX_RESUMO]: Logo após o título do capítulo, extraia de 3 a 5 tópicos cruciais e insira a tag [BOX_RESUMO] seguida do texto "PONTOS IMPORTANTES", estruturando os dados em bullet points curtos e diretos. Evite parágrafos longos dentro deste box.
   - [BOX_RECOMENDACAO]: Utilize para destacar intervenções clínicas importantes ou condutas recomendadas.
   - [BOX_ATENCAO]: Utilize para destacar riscos, contraindicações ou alertas clínicos cruciais.
   - [SUGESTAO_EDICAO]: Utilize caso encontre inconsistências técnicas, informando claramente o que precisa ser verificado ou validado pelo autor original.
4. No final do texto, pesquise e sugira 2 ou 3 links oficiais (ex: Ministério da Saúde, OMS, SBMFC ou outras sociedades médicas reconhecidas) para atualização do tema abordado, e insira-os sob a tag [LINKS_ATUALIZACAO].
5. Ao final de tudo, adicione a tag [DADOS_INDICE] seguida de um JSON estrito contendo duas chaves: 'titulo_capitulo' (o título definitivo do texto lido) e 'subtopicos' (uma lista de strings com os 3 a 5 principais tópicos abordados no capítulo).

CONTEXTO DOS CAPÍTULOS ANTERIORES:
(Utilize este contexto para manter a coesão narrativa, evitar repetições desnecessárias e garantir a continuidade do guia)
{previous_summaries if previous_summaries else "Nenhum capítulo processado anteriormente ou sem resumo disponível."}

TEXTO DO CAPÍTULO A SER REVISADO:
{chapter_text}
"""
    
    last_error = None
    
    print("\n" + "="*50)
    
    for selected_model in valid_models:
        print(f"⚙️ Tentando processar com o modelo: {selected_model}...")
        
        model = genai.GenerativeModel(
            model_name=selected_model,
            system_instruction=SYSTEM_INSTRUCTION
        )
        
        max_retries = 2
        retry_delay = 15 
        
        for attempt in range(max_retries):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.3,
                    )
                )
                print(f"✅ Sucesso usando {selected_model}!")
                print("="*50 + "\n")
                return response.text
            except Exception as e:
                error_msg = str(e)
                last_error = e
                if "429" in error_msg or "quota" in error_msg.lower() or "exhausted" in error_msg.lower():
                    if "limit: 0" in error_msg:
                        print(f"⚠️ Aviso: Modelo {selected_model} não possui cota disponível (Limit: 0). Pulando para o próximo...")
                        break # Quebra o for attempt, vai para o próximo selected_model
                        
                    if attempt < max_retries - 1:
                        print(f"⏳ Aviso (Rate Limit): Limite atingido em {selected_model}. Aguardando {retry_delay}s antes da nova tentativa...")
                        time.sleep(retry_delay)
                        retry_delay += 15
                    else:
                        print(f"❌ Falha em {selected_model} após {max_retries} tentativas devido à cota.")
                else:
                    print(f"❌ Erro inesperado no modelo {selected_model}: {error_msg}")
                    break # Quebra o for attempt para erros que não são de Rate Limit
                    
    raise Exception(f"❌ Todos os modelos tentados falharam. Último erro: {last_error}")
