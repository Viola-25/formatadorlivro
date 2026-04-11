import streamlit as st
import json
import os
import time
from typing import Dict, Any

# Importando as funções dos nossos módulos
from engine import extract_text_from_docx, get_processed_chapters_summary, process_chapter_text
from formatter import generate_formatted_docx

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
        "glossario_dinamico": {}
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

def add_glossary_term(state: Dict[str, Any], term: str, definition: str) -> None:
    """
    Adiciona um novo termo ao glossário dinâmico no estado e salva no arquivo.
    """
    state["glossario_dinamico"][term] = definition
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
            
            # 5. Gerar arquivo DOCX formatado
            status_text.text(f"Formatando e gerando DOCX para {file.name}...")
            output_filename = generate_formatted_docx(ai_text, file.name)
            
            # Mover arquivo final para OUTPUT_DIR
            final_path = os.path.join(OUTPUT_DIR, output_filename)
            if os.path.exists(output_filename):
                os.rename(output_filename, final_path)
            
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
                    st.sidebar.download_button(
                        label=f"Baixar {file_name}",
                        data=f,
                        file_name=file_name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )
        else:
            st.sidebar.info("Nenhum arquivo processado disponível.")
            
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
        st.subheader("Glossário Dinâmico")
        glossario_data = st.session_state.app_state.get("glossario_dinamico", {})
        if glossario_data:
            for term, definition in glossario_data.items():
                st.write(f"- **{term}**: {definition}")
        else:
            st.info("O glossário está vazio.")

if __name__ == "__main__":
    main()
