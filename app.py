import streamlit as st
import json
import os
import time
from typing import Dict, Any

# Importando as funções dos nossos módulos
from engine import extract_text_from_docx, get_processed_chapters_summary, process_chapter_text
from formatter import generate_formatted_docx, convert_to_pdf

PROGRESS_FILE = 'progresso.json'
OUTPUT_DIR = 'output'
TEMP_DIR = 'temp'

# Garantir que os diretórios existam
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

def load_progress() -> Dict[str, Any]:
    """
    Carrega o estado do progresso a partir do arquivo JSON.
    Se o arquivo não existir, retorna um estado inicial padrão.
    """
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            st.error("Erro ao ler o arquivo de progresso. Iniciando com estado vazio.")
            
    # Estado inicial padrão
    return {
        "status_capitulos": {},
        "indice_capitulos": {}
    }

def save_progress(state: Dict[str, Any]) -> None:
    """
    Salva o estado atual do progresso no arquivo JSON.
    """
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"Erro ao salvar o progresso: {e}")

def update_chapter_status(state: Dict[str, Any], chapter_name: str, status: str) -> None:
    """
    Atualiza o status de um capítulo específico no estado e salva no arquivo.
    """
    state["status_capitulos"][chapter_name] = status
    save_progress(state)

def update_chapter_index(state: Dict[str, Any], title: str, subtopics: list) -> None:
    """
    Salva os dados do índice (título e subtópicos) no estado e atualiza o arquivo.
    """
    if "indice_capitulos" not in state:
        state["indice_capitulos"] = {}
    state["indice_capitulos"][title] = subtopics
    save_progress(state)

def process_files(uploaded_files, api_key: str):
    """
    Pipeline de processamento de arquivos que extrai o texto, 
    envia para IA e formata o resultado.
    """
    if not api_key:
        st.sidebar.error("Por favor, insira a Chave da API (Gemini) antes de processar.")
        return

    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_files = len(uploaded_files)
    
    for i, file in enumerate(uploaded_files):
        try:
            status_text.text(f"Processando arquivo {i+1} de {total_files}: {file.name}")
            
            # Se já está concluído e tem arquivo no disco, podemos pular (opcional). 
            # Aqui vamos re-processar se o usuário clicou no botão.
            update_chapter_status(st.session_state.app_state, file.name, "Em Processamento")
            
            # 1. Salvar o arquivo temporariamente para processar
            temp_path = os.path.join(TEMP_DIR, file.name)
            with open(temp_path, "wb") as f:
                f.write(file.getbuffer())
                
            # 2. Extrair o texto
            chapter_text = ""
            if file.name.endswith('.docx'):
                chapter_text = extract_text_from_docx(temp_path)
            elif file.name.endswith('.txt'):
                with open(temp_path, "r", encoding="utf-8") as f:
                    chapter_text = f.read()
            else:
                status_text.text(f"Ignorando arquivo não suportado para texto: {file.name}")
                update_chapter_status(st.session_state.app_state, file.name, "Ignorado (Não é texto)")
                progress_bar.progress((i + 1) / total_files)
                continue
                
            # 3. Pegar resumos anteriores
            previous_summaries = get_processed_chapters_summary(PROGRESS_FILE)
            
            # 4. Processar com a IA
            status_text.text(f"Enviando {file.name} para a IA...")
            ai_text = process_chapter_text(chapter_text, previous_summaries, api_key)
            
            # 4.5 Extrair dados do Índice e remover do texto principal
            if "[DADOS_INDICE]" in ai_text:
                parts = ai_text.split("[DADOS_INDICE]")
                ai_text = parts[0].strip() # Atualiza o texto para remover a tag e o JSON
                json_str = parts[1].strip()
                
                # Limpar marcadores de bloco de código markdown (```json ... ```) se existirem
                if json_str.startswith("```json"):
                    json_str = json_str[7:]
                elif json_str.startswith("```"):
                    json_str = json_str[3:]
                if json_str.endswith("```"):
                    json_str = json_str[:-3]
                
                try:
                    indice_data = json.loads(json_str.strip())
                    title = indice_data.get("titulo_capitulo", f"Capítulo: {file.name}")
                    subtopics = indice_data.get("subtopicos", [])
                    update_chapter_index(st.session_state.app_state, title, subtopics)
                except json.JSONDecodeError:
                    st.warning(f"Aviso: Não foi possível processar o JSON de índice para {file.name}.")

            # 5. Gerar arquivo DOCX formatado
            status_text.text(f"Formatando e gerando DOCX para {file.name}...")
            output_filename = generate_formatted_docx(ai_text, file.name)
            
            # Mover arquivo final para OUTPUT_DIR
            final_path = os.path.join(OUTPUT_DIR, output_filename)
            if os.path.exists(output_filename):
                os.rename(output_filename, final_path)
            
            # 6. Gerar PDF
            status_text.text(f"Gerando PDF para {file.name}...")
            try:
                convert_to_pdf(final_path)
            except Exception as e:
                st.warning(f"Não foi possível converter {file.name} para PDF. O docx2pdf requer o Microsoft Word instalado (Windows/Mac). Erro: {e}")
            
            # Atualiza o status
            # Como simplificação, criamos um pseudo-resumo para manter a coesão. 
            # Em produção a IA poderia retornar o resumo num formato JSON.
            st.session_state.app_state["status_capitulos"][file.name] = {
                "status": "Concluído",
                "resumo": f"Capítulo {file.name} revisado e formatado."
            }
            save_progress(st.session_state.app_state)
            
        except Exception as e:
            st.error(f"Erro ao processar {file.name}: {e}")
            update_chapter_status(st.session_state.app_state, file.name, f"Erro: {str(e)}")
            
        progress_bar.progress((i + 1) / total_files)

    status_text.text("Processamento concluído!")
    st.success("Todos os arquivos foram processados com sucesso!")
    # Limpa barra de progresso após 3 segundos
    time.sleep(3)
    progress_bar.empty()

def main():
    """
    Função principal que define a interface da aplicação Streamlit.
    """
    st.set_page_config(
        page_title="Revisão - Guia da APS",
        page_icon="📚",
        layout="wide"
    )
    
    st.title("📚 Gerenciador de Revisão e Formatação - Guia da APS")
    st.markdown("Faça o upload dos capítulos e imagens para iniciar o processo de revisão e formatação.")
    
    # Inicializa e carrega o estado na session_state
    if 'app_state' not in st.session_state:
        st.session_state.app_state = load_progress()
    
    # Configura a barra lateral
    st.sidebar.header("Configurações")
    api_key = st.sidebar.text_input("Chave da API Gemini", type="password")
    
    st.sidebar.markdown("---")
    st.sidebar.header("Ações do Guia da APS")
    
    aba1, aba2 = st.tabs(['📚 Processador', '🎨 Configuração e Preview'])
    
    with aba1:
        # Área principal de upload
        st.header("Upload de Arquivos")
        uploaded_files = st.file_uploader(
            "Selecione os arquivos para o Guia da APS", 
            type=['docx', 'txt', 'png', 'jpg'], 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            st.success(f"{len(uploaded_files)} arquivo(s) carregado(s) na sessão!")
            
            # Botão de iniciar processamento na barra lateral
            if st.sidebar.button("Iniciar Processamento", use_container_width=True):
                if uploaded_files:
                    process_files(uploaded_files, api_key)
                else:
                    st.sidebar.warning("Nenhum arquivo para processar.")
                    
            st.subheader("Arquivos na fila:")
            for file in uploaded_files:
                st.text(f"📄 {file.name}")
                
                # Adiciona ao rastreamento com status Pendente
                if file.name not in st.session_state.app_state["status_capitulos"]:
                    update_chapter_status(st.session_state.app_state, file.name, "Pendente")

    # Botão para baixar arquivos processados
    st.sidebar.markdown("---")
    st.sidebar.header("Arquivos Processados")
    if os.path.exists(OUTPUT_DIR):
        files = os.listdir(OUTPUT_DIR)
        if files:
            for file_name in files:
                file_path = os.path.join(OUTPUT_DIR, file_name)
                with open(file_path, "rb") as f:
                    if file_name.endswith('.docx'):
                        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    elif file_name.endswith('.pdf'):
                        mime_type = "application/pdf"
                    else:
                        mime_type = "application/octet-stream"
                        
                    st.sidebar.download_button(
                        label=f"Baixar {file_name}",
                        data=f,
                        file_name=file_name,
                        mime=mime_type,
                        use_container_width=True
                    )
        else:
            st.sidebar.info("Nenhum arquivo processado disponível.")
            
    with aba1:
        # Exibição do estado atual do projeto
        st.markdown("---")
        st.header("Status Atual do Projeto")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Status dos Capítulos")
            status_data = st.session_state.app_state.get("status_capitulos", {})
            if status_data:
                for cap, status in status_data.items():
                    if isinstance(status, dict):
                        st.write(f"- **{cap}**: `{status.get('status')}`")
                    else:
                        st.write(f"- **{cap}**: `{status}`")
            else:
                st.info("Nenhum capítulo processado ainda.")
                
        with col2:
            st.subheader("Índice da Obra")
            indice_data = st.session_state.app_state.get("indice_capitulos", {})
            if indice_data:
                for title, subtopics in indice_data.items():
                    st.markdown(f"**{title}**")
                    for topic in subtopics:
                        st.markdown(f"- {topic}")
                    st.write("") # Espaçamento entre capítulos
            else:
                st.info("O índice está vazio.")
                
    with aba2:
        st.header("Configurações Visuais")
        
        col_config1, col_config2 = st.columns(2)
        with col_config1:
            font_size = st.slider("Tamanho da Fonte Padrão (pt)", min_value=8, max_value=24, value=11)
        with col_config2:
            box_resumo_color = st.color_picker("Cor de Fundo do BOX_RESUMO", value="#D3D3D3")
            
        st.markdown("---")
        st.subheader("Preview em Tempo Real")
        
        preview_html = f'''
        <div style="font-family: Arial, sans-serif; font-size: {font_size}pt; text-align: justify; padding: 20px; border: 1px solid #ddd; border-radius: 8px; background-color: #fff; color: #000;">
            <p><strong>Texto Normal:</strong> Este é um exemplo de parágrafo padrão no seu documento final. Ele acompanha o tamanho da fonte que você escolher e possui alinhamento justificado, garantindo que o layout final do DOCX lembre o formato clássico de um livro.</p>
            
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                <tr>
                    <td style="background-color: {box_resumo_color}; padding: 12px; border: 1px solid #666;">
                        <strong>[BOX_RESUMO]</strong><br>
                        Aqui ficam os pontos-chave e essenciais do capítulo. Esta caixa de destaque simula exatamente a tabela gerada no Word, refletindo a cor de fundo selecionada.
                    </td>
                </tr>
            </table>
            
            <p style="margin-left: 48px; font-weight: bold; font-style: italic;">
                [BOX_RECOMENDACAO] Esta formatação é utilizada para destacar intervenções clínicas importantes ou condutas recomendadas, aplicando negrito, itálico e recuo de parágrafo.
            </p>
            
            <p style="margin-left: 48px; font-weight: bold; font-style: italic; color: rgb(180, 0, 0);">
                [BOX_ATENCAO] Esta formatação destaca riscos, contraindicações ou alertas clínicos cruciais, aplicando os mesmos estilos da recomendação, mas alterando a cor da fonte para vermelho escuro.
            </p>
        </div>
        '''
        st.markdown(preview_html, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
