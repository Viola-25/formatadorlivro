import streamlit as st
import json
import os
import time
import re
from typing import Dict, Any

# Importando funções dos módulos
from engine import extract_text_from_docx, get_processed_chapters_summary, process_chapter_text
from formatter import generate_formatted_docx, convert_to_pdf

# Importando configuração centralizada
from config import PROGRESS_FILE, OUTPUT_DIR, TEMP_DIR
from logger import logger
from backup import create_backup, restore_backup, list_backups, validate_progress_file
from validator import validate_index_data, InvalidIndexData
from exceptions import DocumentParseError, APIException
from index_manager import GerenciadorIndice


def load_progress() -> Dict[str, Any]:
    """
    Carrega o estado do progresso a partir do arquivo JSON.
    Valida integridade antes de carregar.
    
    Returns:
        Dict com estado do progresso
    """
    logger.debug("Carregando progresso...")
    
    if os.path.exists(PROGRESS_FILE):
        try:
            # Valida arquivo antes de carregar
            if not validate_progress_file():
                logger.warning("Arquivo de progresso corrompido. Tentando restaurar do backup...")
                backups = list_backups()
                if backups:
                    restore_backup(backups[0]["filename"])
                else:
                    logger.error("Sem backups disponíveis. Reiniciando com estado vazio.")
                    return {"status_capitulos": {}, "indice_capitulos": {}}
            
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar JSON de progresso: {e}")
            st.error("❌ Arquivo de progresso corrompido. Iniciando com estado vazio.")
            return {"status_capitulos": {}, "indice_capitulos": {}}
        except Exception as e:
            logger.error(f"Erro ao carregar progresso: {e}")
            st.error(f"❌ Erro ao carregar progresso: {e}")
            
    # Estado inicial padrão
    logger.debug("Nenhum arquivo de progresso encontrado. Usando estado padrão.")
    return {
        "status_capitulos": {},
        "indice_capitulos": {}
    }


def save_progress(state: Dict[str, Any]) -> bool:
    """
    Salva o estado atual do progresso no arquivo JSON.
    Cria backup automático antes de salvar.
    
    Args:
        state: Estado a salvar
        
    Returns:
        True se salvo com sucesso
    """
    try:
        # Cria backup automático antes de salvar novo estado
        create_backup()
        
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=4)
        
        logger.debug("Progresso salvo com sucesso")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar progresso: {e}")
        st.error(f"⚠️ Erro ao salvar progresso: {e}")
        return False


def update_chapter_status(state: Dict[str, Any], chapter_name: str, status: str) -> bool:
    """
    Atualiza o status de um capítulo específico.
    
    Args:
        state: Estado atual
        chapter_name: Nome do arquivo/capítulo
        status: Novo status
        
    Returns:
        True se atualizado com sucesso
    """
    state["status_capitulos"][chapter_name] = status
    logger.debug(f"Status atualizado para {chapter_name}: {status}")
    return save_progress(state)


def update_chapter_index(state: Dict[str, Any], title: str, subtopics: list) -> bool:
    """
    Salva os dados do índice validados no estado.
    
    Args:
        state: Estado atual
        title: Título do capítulo
        subtopics: Lista de subtópicos
        
    Returns:
        True se atualizado com sucesso
    """
    try:
        # Valida dados com Pydantic antes de salvar
        validated = validate_index_data({
            "titulo_capitulo": title,
            "subtopicos": subtopics
        })
        
        if "indice_capitulos" not in state:
            state["indice_capitulos"] = {}
        
        state["indice_capitulos"][title] = subtopics
        logger.info(f"Índice atualizado: {title} com {len(subtopics)} subtópicos")
        return save_progress(state)
        
    except InvalidIndexData as e:
        logger.warning(f"Dados de índice inválidos: {e}")
        return False

def process_files(uploaded_files: list, api_key: str) -> None:
    """
    Pipeline de processamento de arquivos que extrai o texto, 
    envia para IA e formata o resultado.
    
    Args:
        uploaded_files: Lista de arquivos enviados
        api_key: Chave da API Gemini
    """
    if not api_key:
        st.error("🔑 Por favor, insira a Chave da API (Gemini) na barra lateral antes de processar.")
        logger.warning("Tentativa de processar sem API key")
        return

    logger.info(f"Iniciando processamento de {len(uploaded_files)} arquivo(s)")
    
    st.markdown("### ⚙️ Processamento em Andamento")
    progress_bar = st.progress(0, text="Iniciando...")
    status_container = st.container(border=True)
    status_text = status_container.empty()
    
    total_files = len(uploaded_files)
    successful_count = 0
    error_count = 0
    
    for i, file in enumerate(uploaded_files):
        try:
            status_text.info(f"**Processando arquivo {i+1} de {total_files}:** `{file.name}`")
            logger.info(f"Processando arquivo: {file.name}")
            
            update_chapter_status(st.session_state.app_state, file.name, "Em Processamento")
            
            # 1. Salvar arquivo temporariamente
            temp_path = os.path.join(TEMP_DIR, file.name)
            with open(temp_path, "wb") as f:
                f.write(file.getbuffer())
            logger.debug(f"Arquivo salvo temporariamente: {temp_path}")
                
            # 2. Extrair o texto
            chapter_text = ""
            if file.name.endswith('.docx'):
                try:
                    chapter_text = extract_text_from_docx(temp_path)
                except DocumentParseError as e:
                    logger.error(f"Erro ao extrair texto de {file.name}: {e}")
                    st.error(f"❌ Erro ao ler arquivo {file.name}: {e}")
                    update_chapter_status(st.session_state.app_state, file.name, f"Erro na extração: {str(e)}")
                    continue
            elif file.name.endswith('.txt'):
                try:
                    with open(temp_path, "r", encoding="utf-8") as f:
                        chapter_text = f.read()
                    logger.debug(f"Texto extraído de TXT: {len(chapter_text)} caracteres")
                except Exception as e:
                    logger.error(f"Erro ao ler arquivo TXT {file.name}: {e}")
                    st.error(f"❌ Erro ao ler arquivo {file.name}: {e}")
                    update_chapter_status(st.session_state.app_state, file.name, f"Erro na leitura: {str(e)}")
                    continue
            else:
                logger.warning(f"Arquivo não suportado: {file.name}")
                status_text.warning(f"Ignorando arquivo não suportado para texto: {file.name}")
                update_chapter_status(st.session_state.app_state, file.name, "Ignorado (Não é texto)")
                progress_bar.progress((i + 1) / total_files)
                continue
                
            # 3. Pegar resumos anteriores para coesão narrativa
            previous_summaries = get_processed_chapters_summary(PROGRESS_FILE)
            
            # 4. Processar com a IA
            status_text.info(f"**Analisando com IA:** `{file.name}` (Isso pode levar alguns instantes...)")
            try:
                logger.info(f"Enviando para IA: {file.name}")
                ai_text = process_chapter_text(
                    chapter_text,
                    previous_summaries,
                    api_key,
                    chapter_name=file.name
                )
                logger.debug(f"IA retornou {len(ai_text)} caracteres")
            except APIException as e:
                logger.error(f"Erro da API ao processar {file.name}: {e}")
                st.error(f"❌ Erro ao processar com IA: {e}")
                update_chapter_status(st.session_state.app_state, file.name, f"Erro na IA: {str(e)}")
                error_count += 1
                progress_bar.progress((i + 1) / total_files, text=f"Concluído {i+1} de {total_files}")
                continue
            
            # 4.5 Extrair e validar dados do Índice
            title = f"Capítulo: {file.name}"
            if "[DADOS_INDICE]" in ai_text:
                try:
                    parts = ai_text.split("[DADOS_INDICE]")
                    ai_text = parts[0].strip()
                    json_str = parts[1].strip()
                    
                    # Limpa marcadores markdown
                    if json_str.startswith("```json"):
                        json_str = json_str[7:]
                    elif json_str.startswith("```"):
                        json_str = json_str[3:]
                    if json_str.endswith("```"):
                        json_str = json_str[:-3]
                    
                    indice_data = json.loads(json_str.strip())
                    
                    # Valida com Pydantic
                    validated = validate_index_data(indice_data)
                    title = validated.titulo_capitulo
                    subtopics = validated.subtopicos
                    
                    update_chapter_index(st.session_state.app_state, title, subtopics)
                    logger.info(f"Índice processado: {title}")
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON de índice inválido para {file.name}: {e}")
                    st.warning(f"⚠️ Aviso: Não foi possível processar o JSON de índice para {file.name}.")
                except InvalidIndexData as e:
                    logger.warning(f"Índice inválido para {file.name}: {e}")
                    st.warning(f"⚠️ Dados de índice inválidos para {file.name}. Continuando...")
                    
            # Salvar texto processado para edição posterior
            ai_text_path = os.path.join(TEMP_DIR, f"{file.name}.ai.txt")
            with open(ai_text_path, "w", encoding="utf-8") as f:
                f.write(ai_text)
            logger.debug(f"Texto da IA salvo: {ai_text_path}")

            # 5. Gerar arquivo DOCX formatado
            status_text.info(f"**Aplicando Guia de Estilos e formatando DOCX:** `{file.name}`")
            try:
                logger.info(f"Gerando DOCX: {file.name}")
                output_filename = generate_formatted_docx(ai_text, file.name)
                
                final_path = os.path.join(OUTPUT_DIR, output_filename)
                if os.path.exists(output_filename):
                    os.rename(output_filename, final_path)
                logger.info(f"DOCX gerado: {final_path}")
            except Exception as e:
                logger.error(f"Erro ao gerar DOCX para {file.name}: {e}")
                st.error(f"❌ Erro ao formatar documento: {e}")
                update_chapter_status(st.session_state.app_state, file.name, f"Erro na formatação: {str(e)}")
                error_count += 1
                progress_bar.progress((i + 1) / total_files, text=f"Concluído {i+1} de {total_files}")
                continue
            
            # 6. Gerar PDF (opcional)
            status_text.info(f"**Convertendo para PDF:** `{file.name}`")
            try:
                logger.info(f"Convertendo para PDF: {file.name}")
                convert_to_pdf(final_path)
                logger.info(f"PDF gerado com sucesso")
            except Exception as e:
                logger.warning(f"Não foi possível converter para PDF: {e}")
                st.warning(f"⚠️ Não foi possível converter para PDF. O docx2pdf requer Microsoft Word. Erro: {e}")
            
            # Atualizar status de conclusão
            st.session_state.app_state["status_capitulos"][file.name] = {
                "status": "Concluído",
                "resumo": f"Capítulo revisado e formatado com sucesso.",
                "titulo_indice": title
            }
            save_progress(st.session_state.app_state)
            successful_count += 1
            logger.info(f"✓ Capítulo processado com sucesso: {file.name}")
            
        except Exception as e:
            logger.error(f"Erro crítico ao processar {file.name}: {e}", exc_info=True)
            st.error(f"❌ Erro crítico ao processar {file.name}: {e}")
            update_chapter_status(st.session_state.app_state, file.name, f"Erro: {str(e)}")
            error_count += 1
            
        progress_bar.progress((i + 1) / total_files, text=f"Concluído {i+1} de {total_files}")

    # Resumo final
    logger.info(f"Processamento concluído: {successful_count} sucesso(s), {error_count} erro(s)")
    
    if successful_count > 0:
        status_text.success(f"✨ Processamento concluído! {successful_count} arquivo(s) processado(s) com sucesso!")
        st.toast(f"✓ {successful_count}/{total_files} arquivos processados!", icon="✅")
        st.balloons()
    
    if error_count > 0:
        st.warning(f"⚠️ {error_count} arquivo(s) falharam no processamento")
    
    time.sleep(2)
    progress_bar.empty()
    status_container.empty()

def main():
    """
    Função principal que define a interface da aplicação Streamlit.
    """
    st.set_page_config(
        page_title="Revisão - Guia da APS",
        page_icon="📚",
        layout="wide"
    )
    
    st.title("📚 Gerenciador de Revisão e Formatação")
    st.markdown("Bem-vindo ao motor de padronização do **Guia da APS**. Faça o upload dos capítulos para iniciar a revisão guiada por IA.")
    
    # Inicializa e carrega o estado na session_state
    if 'app_state' not in st.session_state:
        st.session_state.app_state = load_progress()
    
    # Configura a barra lateral
    with st.sidebar:
        st.header("⚙️ Configurações")
        api_key = st.text_input("Chave da API Gemini", type="password", help="Insira sua chave da API do Google Gemini para habilitar a inteligência artificial.")
        
        st.divider()
        st.header("📥 Arquivos Processados")
        
        # Botões para baixar arquivos processados
        if os.path.exists(OUTPUT_DIR):
            files = [f for f in os.listdir(OUTPUT_DIR) if not f.startswith('.')]
            if files:
                for file_name in files:
                    file_path = os.path.join(OUTPUT_DIR, file_name)
                    with open(file_path, "rb") as f:
                        if file_name.endswith('.docx'):
                            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                            icon = "📄"
                        elif file_name.endswith('.pdf'):
                            mime_type = "application/pdf"
                            icon = "📕"
                        else:
                            mime_type = "application/octet-stream"
                            icon = "📎"
                            
                        st.download_button(
                            label=f"{icon} Baixar {file_name}",
                            data=f,
                            file_name=file_name,
                            mime=mime_type,
                            use_container_width=True
                        )
            else:
                st.info("Nenhum arquivo processado disponível ainda.")
        else:
            st.info("Pasta de saída não encontrada.")
            
    # Abas principais
    aba1, aba2, aba3, aba4 = st.tabs(['🚀 Processador', '🎨 Configuração e Preview', '✏️ Gerenciar Capítulos', '📚 Organizar Índice'])
    
    with aba1:
        # Área principal de upload
        with st.container(border=True):
            st.subheader("1. Selecione os Arquivos Brutos")
            uploaded_files = st.file_uploader(
                "Faça o upload dos documentos originais (.docx, .txt) para iniciar.", 
                type=['docx', 'txt', 'png', 'jpg'], 
                accept_multiple_files=True
            )
        
        if uploaded_files:
            st.info(f"📁 **{len(uploaded_files)} arquivo(s)** carregado(s) e prontos para processamento na fila.")
            
            # Registrar pendentes silenciosamente
            for file in uploaded_files:
                # Adiciona ao rastreamento com status Pendente
                if file.name not in st.session_state.app_state["status_capitulos"]:
                    update_chapter_status(st.session_state.app_state, file.name, "Pendente")
                    
            # Botão de iniciar processamento na tela principal
            if st.button("▶️ Iniciar Processamento Inteligente", type="primary", use_container_width=True):
                process_files(uploaded_files, api_key)
            
        # Exibição do estado atual do projeto
        st.divider()
        st.header("📊 Resumo do Projeto")
        
        col1, col2 = st.columns(2)
        
        with col1:
            with st.container(border=True):
                st.subheader("📑 Status dos Capítulos")
                status_data = st.session_state.app_state.get("status_capitulos", {})
                if status_data:
                    for cap, status in status_data.items():
                        if isinstance(status, dict):
                            st.markdown(f"📄 **{cap}** <br/> └ Status: `{status.get('status')}`", unsafe_allow_html=True)
                        else:
                            st.markdown(f"📄 **{cap}** <br/> └ Status: `{status}`", unsafe_allow_html=True)
                else:
                    st.info("Nenhum capítulo na fila ou processado ainda.")
                
        with col2:
            with st.container(border=True):
                st.subheader("🗂️ Índice Estruturado da Obra")
                indice_data = st.session_state.app_state.get("indice_capitulos", {})
                if indice_data:
                    for title, subtopics in indice_data.items():
                        st.markdown(f"**📘 {title}**")
                        for topic in subtopics:
                            st.markdown(f"- {topic}")
                        st.markdown("<br/>", unsafe_allow_html=True)
                else:
                    st.info("O índice será gerado automaticamente após o processamento.")
                
    with aba2:
        st.header("Configurações Visuais")
        st.markdown("Ajuste as preferências de formatação. *Nota: Este é um preview visual do guia de estilo que será aplicado no Word.*")
        
        col_config1, col_config2 = st.columns(2)
        with col_config1:
            font_size = st.slider("Tamanho da Fonte Padrão (pt)", min_value=8, max_value=24, value=11)
        with col_config2:
            box_resumo_color = st.color_picker("Cor de Fundo do Box de Resumo", value="#E8F0FE")
            
        st.divider()
        st.subheader("👀 Preview em Tempo Real")
        
        preview_html = f'''
        <div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: {font_size}pt; text-align: justify; padding: 30px; border: 1px solid #ddd; border-radius: 8px; background-color: #fff; color: #333; box-shadow: 0 4px 8px rgba(0,0,0,0.05);">
            <h2 style="color: #2C3E50; font-family: 'Segoe UI', Arial, sans-serif; margin-top: 0;">Título do Capítulo</h2>
            <p>Este é um exemplo de parágrafo padrão no seu documento final. Ele acompanha o tamanho da fonte que você escolher e possui alinhamento justificado, garantindo que o layout final do DOCX mantenha o formato clássico e legível de um livro técnico de medicina.</p>
            
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
                <tr>
                    <td style="background-color: {box_resumo_color}; padding: 16px; border-left: 5px solid #4A90E2; border-radius: 4px;">
                        <strong style="color: #4A90E2; font-size: 1.1em;">PONTOS IMPORTANTES</strong><br><br>
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
        
    with aba3:
        st.header("Gerenciar e Editar Capítulos")
        
        status_data = st.session_state.app_state.get("status_capitulos", {})
        if not status_data:
            st.info("Nenhum capítulo processado para gerenciar. Por favor, processe arquivos na aba 'Processador' primeiro.")
        else:
            selected_chapter = st.selectbox("📌 Selecione um capítulo para revisar", list(status_data.keys()))
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🗑️ Excluir Capítulo", use_container_width=True):
                    info = st.session_state.app_state["status_capitulos"][selected_chapter]
                    if isinstance(info, dict) and "titulo_indice" in info:
                        idx_title = info["titulo_indice"]
                        if "indice_capitulos" in st.session_state.app_state and idx_title in st.session_state.app_state["indice_capitulos"]:
                            del st.session_state.app_state["indice_capitulos"][idx_title]
                    
                    del st.session_state.app_state["status_capitulos"][selected_chapter]
                    save_progress(st.session_state.app_state)
                    
                    base_name = os.path.splitext(selected_chapter)[0] if '.' in selected_chapter else selected_chapter
                    safe_chapter_name = re.sub(r'[\\/*?:"<>|]', "", base_name).replace(" ", "_")
                    
                    docx_path = os.path.join(OUTPUT_DIR, f"Capitulo_{safe_chapter_name}_Revisado.docx")
                    pdf_path = docx_path.replace(".docx", ".pdf")
                    ai_txt_path = os.path.join(TEMP_DIR, f"{selected_chapter}.ai.txt")
                    
                    for p in [docx_path, pdf_path, ai_txt_path]:
                        if os.path.exists(p):
                            os.remove(p)
                            
                    st.toast(f"Capítulo {selected_chapter} excluído do histórico!", icon="🗑️")
                    time.sleep(1.5)
                    st.rerun()
            
            st.divider()
            st.subheader("📝 Edição Manual do Texto (Pré-formatação)")
            st.markdown("Faltou algo no texto gerado pela IA? Edite diretamente aqui antes de re-gerar o Word/PDF final.")
            ai_txt_path = os.path.join(TEMP_DIR, f"{selected_chapter}.ai.txt")
            
            if os.path.exists(ai_txt_path):
                with open(ai_txt_path, "r", encoding="utf-8") as f:
                    current_text = f.read()
                    
                edited_text = st.text_area("Texto cru com as Tags estruturais", value=current_text, height=450)
                
                if st.button("💾 Salvar e Reformatar Arquivos", use_container_width=True):
                    with open(ai_txt_path, "w", encoding="utf-8") as f:
                        f.write(edited_text)
                    
                    with st.spinner("Reformatando DOCX e PDF..."):
                        output_filename = generate_formatted_docx(edited_text, selected_chapter)
                        final_path = os.path.join(OUTPUT_DIR, output_filename)
                        if os.path.exists(output_filename):
                            os.rename(output_filename, final_path)
                            
                        try:
                            convert_to_pdf(final_path)
                        except Exception as e:
                            st.warning(f"Erro ao gerar PDF: {e}")
                            
                    st.success("✅ Arquivos reconstruídos com base nas suas edições com sucesso!")
                    st.balloons()
            else:
                st.warning("⚠️ O texto base deste capítulo não foi encontrado. Processe-o novamente na aba principal para habilitar a edição manual.")
    
    with aba4:
        st.header("📚 Organizar e Reordenar Índice")
        st.markdown("Organize seus capítulos em seções/especialidades, reordene e manage a estrutura do livro.")
        
        # Inicializa o gerenciador de índice
        if 'gerenciador_indice' not in st.session_state:
            st.session_state.gerenciador_indice = GerenciadorIndice()
        
        gerenciador = st.session_state.gerenciador_indice
        
        # Abas secundárias dentro da aba4
        subtab1, subtab2, subtab3, subtab4 = st.tabs(['📋 Reordenar', '🏷️ Seções', '🗑️ Deletar', '📊 Relatório'])
        
        # ========== SUBTAB 1: Reordenar Capítulos ==========
        with subtab1:
            st.subheader("✴️ Reordenar Capítulos")
            
            capitulos = list(gerenciador.estado.get("indice_capitulos", {}).keys())
            
            if not capitulos:
                st.info("Nenhum capítulo no índice para reordenar.")
            else:
                st.info(f"Total de capítulos: **{len(capitulos)}**")
                
                ordem_atual = gerenciador.estado.get("ordem_capitulos", capitulos)
                
                # Exibe a ordem atual com botões para mover
                st.markdown("**Ordem Atual:**")
                
                cols_display = st.columns([3, 1, 1])
                for idx, titulo in enumerate(ordem_atual):
                    with cols_display[0]:
                        st.markdown(f"**{idx + 1}.** {titulo}")
                    
                    with cols_display[1]:
                        if idx > 0:
                            if st.button("⬆️", key=f"up_{idx}", help="Mover acima"):
                                gerenciador.mover_capitulo_acima(titulo)
                                st.session_state.gerenciador_indice = gerenciador
                                st.rerun()
                        else:
                            st.write("")
                    
                    with cols_display[2]:
                        if idx < len(ordem_atual) - 1:
                            if st.button("⬇️", key=f"down_{idx}", help="Mover abaixo"):
                                gerenciador.mover_capitulo_abaixo(titulo)
                                st.session_state.gerenciador_indice = gerenciador
                                st.rerun()
                        else:
                            st.write("")
                
                st.divider()
                
                # Reordenação manual com drag-and-drop simulado
                st.markdown("**Drag-and-Drop Manual:**")
                nova_ordem = st.multiselect(
                    "Clique e arraste para reordenar (ou clique para selecionar a nova ordem)",
                    options=ordem_atual,
                    default=ordem_atual,
                    key="reorder_multiselect"
                )
                
                if st.button("✅ Confirmar Nova Ordem", use_container_width=True):
                    if nova_ordem:
                        if gerenciador.reordenar_capitulos(nova_ordem):
                            st.success("✅ Capítulos reordenados com sucesso!")
                            st.session_state.gerenciador_indice = gerenciador
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ Erro ao reordenar capítulos.")
        
        # ========== SUBTAB 2: Gerenciar Seções ==========
        with subtab2:
            st.subheader("🏷️ Gerenciar Seções/Especialidades")
            
            tab_criar_secao, tab_mover_cap, tab_lista_secao = st.tabs(['Criar', 'Mover Capítulo', 'Listar'])
            
            # Criar nova seção
            with tab_criar_secao:
                st.markdown("**Criar Nova Seção**")
                nome_secao = st.text_input("Nome da seção/especialidade", placeholder="Ex: Cardiologia, Infectologia, Protocolos")
                
                if st.button("➕ Criar Seção", use_container_width=True):
                    if nome_secao.strip():
                        if gerenciador.criar_secao(nome_secao):
                            st.success(f"✅ Seção '{nome_secao}' criada!")
                            st.session_state.gerenciador_indice = gerenciador
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"❌ Erro ao criar seção ou seção já existe.")
                    else:
                        st.warning("Por favor, insira um nome para a seção.")
            
            # Mover capítulo para seção
            with tab_mover_cap:
                st.markdown("**Mover Capítulo para Seção**")
                
                secoes = gerenciador.obter_secoes()
                capitulos = list(gerenciador.estado.get("indice_capitulos", {}).keys())
                
                if not secoes:
                    st.info("Crie seções primeiro na aba 'Criar'.")
                elif not capitulos:
                    st.info("Nenhum capítulo disponível.")
                else:
                    col_cap, col_sec = st.columns(2)
                    
                    with col_cap:
                        cap_selecionado = st.selectbox("Selecione o capítulo", capitulos, key="cap_select")
                    
                    with col_sec:
                        sec_selecionada = st.selectbox("Selecione a seção destino", secoes, key="sec_select")
                    
                    if st.button("🔗 Mover Capítulo", use_container_width=True):
                        if gerenciador.mover_capitulo_para_secao(cap_selecionado, sec_selecionada):
                            st.success(f"✅ Capítulo movido para '{sec_selecionada}'!")
                            st.session_state.gerenciador_indice = gerenciador
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ Erro ao mover capítulo.")
            
            # Listar seções e capítulos
            with tab_lista_secao:
                st.markdown("**Estrutura de Seções**")
                
                secoes_data = gerenciador.obter_capitulos_por_secao()
                
                if not secoes_data:
                    st.info("Nenhuma seção criada ainda.")
                else:
                    for secao_nome, capitulos_secao in secoes_data.items():
                        with st.expander(f"📂 {secao_nome} ({len(capitulos_secao)} capítulo(s))", expanded=False):
                            if capitulos_secao:
                                for i, cap in enumerate(capitulos_secao, 1):
                                    st.markdown(f"{i}. **{cap}**")
                            else:
                                st.write("(Nenhum capítulo nesta seção)")
                            
                            if st.button("🗑️ Deletar Seção", key=f"del_sec_{secao_nome}"):
                                if gerenciador.deletar_secao(secao_nome):
                                    st.success(f"✅ Seção '{secao_nome}' deletada!")
                                    st.session_state.gerenciador_indice = gerenciador
                                    time.sleep(1)
                                    st.rerun()
        
        # ========== SUBTAB 3: Deletar Capítulos ==========
        with subtab3:
            st.subheader("🗑️ Deletar Capítulos do Índice")
            st.warning("⚠️ Esta ação remove o capítulo do índice permanentemente.")
            
            capitulos = list(gerenciador.estado.get("indice_capitulos", {}).keys())
            
            if not capitulos:
                st.info("Nenhum capítulo para deletar.")
            else:
                capitulo_del = st.selectbox("Selecione o capítulo a deletar", capitulos, key="del_cap_select")
                
                # Mostra detalhes do capítulo
                subtopicos = gerenciador.obter_capitulo(capitulo_del)
                if subtopicos:
                    st.markdown(f"**Subtópicos:** {', '.join(subtopicos)}")
                
                if st.button("🗑️ Deletar Capítulo do Índice", use_container_width=True, type="secondary"):
                    if gerenciador.deletar_capitulo(capitulo_del):
                        st.success(f"✅ Capítulo '{capitulo_del}' deletado do índice!")
                        st.session_state.gerenciador_indice = gerenciador
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Erro ao deletar capítulo.")
        
        # ========== SUBTAB 4: Relatório ==========
        with subtab4:
            st.subheader("📊 Relatório da Estrutura")
            
            relatorio = gerenciador.gerar_relatorio()
            st.code(relatorio, language="text")
            
            # Download do relatório
            st.download_button(
                label="📥 Baixar Relatório em TXT",
                data=relatorio,
                file_name="relatorio_indice.txt",
                mime="text/plain"
            )
            
            # Export/Import de estrutura
            st.divider()
            st.markdown("**Export/Import da Estrutura JSON**")
            
            col_exp, col_imp = st.columns(2)
            
            with col_exp:
                if st.button("📤 Exportar Estrutura JSON", use_container_width=True):
                    estrutura = gerenciador.exportar_estrutura()
                    st.json(estrutura)
                    
                    st.download_button(
                        label="📥 Baixar JSON",
                        data=json.dumps(estrutura, ensure_ascii=False, indent=2),
                        file_name="estrutura_indice.json",
                        mime="application/json"
                    )
            
            with col_imp:
                st.markdown("**Importar Estrutura JSON**")
                uploaded_json = st.file_uploader("Selecione um arquivo JSON", type="json")
                if uploaded_json is not None:
                    try:
                        estrutura_json = json.load(uploaded_json)
                        if st.button("📥 Importar", use_container_width=True):
                            if gerenciador.importar_estrutura(estrutura_json):
                                st.success("✅ Estrutura importada com sucesso!")
                                st.session_state.gerenciador_indice = gerenciador
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ Erro ao importar estrutura.")
                    except json.JSONDecodeError:
                        st.error("❌ Arquivo JSON inválido.")

if __name__ == "__main__":
    main()
