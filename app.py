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
from logger import logger, reset_log_file
from backup import create_backup, restore_backup, list_backups, validate_progress_file
from validator import validate_index_data, InvalidIndexData
from exceptions import DocumentParseError, APIException
from index_manager import GerenciadorIndice
from utils import (
    delete_chapter_safe,
    validate_api_key,
    standardize_chapter_status,
    get_chapter_safe_filename,
    get_processing_stats
)
from utils import bulk_delete_chapters, bulk_move_chapters, reprocess_chapters, identify_chapter_title_from_filename


def load_groq_api_key_from_file(file_path: str) -> str:
    """Carrega a chave da API do Groq a partir de um arquivo local."""
    if not file_path:
        return ""

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read().strip()

        if not raw_content:
            return ""

        # Aceita arquivo contendo apenas a chave OU formato .env (GROQ_API_KEY=...)
        candidate = raw_content.splitlines()[0].strip()
        if "=" in candidate:
            key_name, value = candidate.split("=", 1)
            if key_name.strip().upper() == "GROQ_API_KEY":
                candidate = value.strip()

        # Remove aspas acidentais
        candidate = candidate.lstrip("\ufeff").strip().strip('"').strip("'")
        return candidate
    except FileNotFoundError:
        return ""
    except Exception as e:
        logger.warning(f"Não foi possível ler o arquivo de chave da API: {e}")
        return ""


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


def update_chapter_status(state: Dict[str, Any], chapter_name: str, status: str, resumo: str = "", titulo_indice: str = "") -> bool:
    """
    Atualiza o status de um capítulo específico. Sempre armazena em formato dict.
    
    Args:
        state: Estado atual
        chapter_name: Nome do arquivo/capítulo
        status: Novo status (string)
        resumo: Resumo opcional do capítulo
        titulo_indice: Título no índice (opcional)
        
    Returns:
        True se atualizado com sucesso
    """
    # Sempre armazena em formato dict padronizado
    state["status_capitulos"][chapter_name] = {
        "status": status,
        "resumo": resumo,
        "titulo_indice": titulo_indice
    }
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

def process_files(
    uploaded_files: list,
    api_key: str,
    manual_references_by_file: Dict[str, str] = None,
    strict_paragraph_mode: bool = False,
    strict_citation_lock: bool = False,
) -> None:
    """
    Pipeline de processamento de arquivos que extrai o texto, 
    envia para IA e formata o resultado.
    
    Args:
        uploaded_files: Lista de arquivos enviados
        api_key: Chave da API Groq
        manual_references_by_file: Mapa {nome_arquivo: referências coladas}
        strict_paragraph_mode: Se True, processa em modo estrito por parágrafos
        strict_citation_lock: Se True, bloqueia capítulo quando integridade de citações divergir
    """
    if not api_key:
        st.error("🔑 Informe a Chave da API (Groq) na barra lateral ou defina GROQ_API_KEY no ambiente antes de processar.")
        logger.warning("Tentativa de processar sem API key")
        return

    logger.info(f"Iniciando processamento de {len(uploaded_files)} arquivo(s)")
    logger.debug(
        f"[Pipeline DEBUG] Parâmetros globais: strict_paragraph_mode={strict_paragraph_mode}, "
        f"strict_citation_lock={strict_citation_lock}, "
        f"arquivos_com_referencias={len([k for k, v in (manual_references_by_file or {}).items() if (v or '').strip()])}"
    )

    if manual_references_by_file is None:
        manual_references_by_file = {}
    
    st.markdown("### ⚙️ Processamento em Andamento")
    progress_bar = st.progress(0, text="Iniciando...")
    status_container = st.container(border=True)
    status_text = status_container.empty()
    
    total_files = len(uploaded_files)
    successful_count = 0
    error_count = 0
    
    for i, file in enumerate(uploaded_files):
        try:
            reset_log_file()
            logger.info(f"Log reiniciado para novo capítulo: {file.name}")
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
                manual_references_text = manual_references_by_file.get(file.name, "")
                logger.debug(
                    f"[Pipeline DEBUG] {file.name}: refs_manuais_chars={len((manual_references_text or '').strip())}, "
                    f"modo={'PARÁGRAFOS' if strict_paragraph_mode else 'CAPÍTULO'}, "
                    f"bloqueio_citacoes={'ON' if strict_citation_lock else 'OFF'}"
                )
                ai_text = process_chapter_text(
                    chapter_text,
                    previous_summaries,
                    api_key,
                    chapter_name=file.name,
                    manual_references_text=manual_references_text,
                    strict_paragraph_mode=strict_paragraph_mode,
                    strict_citation_lock=strict_citation_lock,
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

            # Sugestão de alocação no índice: tente usar a IA para mapear para um título existente
            try:
                candidates = list(st.session_state.gerenciador_indice.estado.get("indice_capitulos", {}).keys())
            except Exception:
                candidates = list(st.session_state.app_state.get("indice_capitulos", {}).keys())

            suggested_title = None
            try:
                from utils import suggest_index_title_with_ai
                suggested_title = suggest_index_title_with_ai(ai_text, file.name, candidates, api_key=api_key)
            except Exception:
                suggested_title = None

            if suggested_title:
                title = suggested_title

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
            update_chapter_status(
                st.session_state.app_state,
                file.name,
                "Concluído",
                resumo="Capítulo revisado e formatado com sucesso.",
                titulo_indice=title
            )
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
    
    # Inicializa o gerenciador de índice (necessário antes de usar em qualquer aba)
    if 'gerenciador_indice' not in st.session_state:
        st.session_state.gerenciador_indice = GerenciadorIndice()
    # Disponibiliza uma referência local ao gerenciador para uso nas abas
    gerenciador = st.session_state.gerenciador_indice
    
    # Configura a barra lateral
    with st.sidebar:
        st.header("⚙️ Configurações")
        env_api_key = os.getenv("GROQ_API_KEY", "").strip()
        key_file_path = os.getenv("GROQ_API_KEY_FILE", "groq_api_key.txt").strip()
        file_api_key = load_groq_api_key_from_file(key_file_path)
        api_key_input = st.text_input(
            "Chave da API Groq",
            type="password",
            help="Insira sua chave da API do Groq. Se deixar vazio, o app tentará usar GROQ_API_KEY do ambiente ou o arquivo definido em GROQ_API_KEY_FILE.",
        )
        # Prioridade: campo manual > arquivo local > variável de ambiente
        api_key = (api_key_input or file_api_key or env_api_key).strip()

        if api_key_input:
            st.caption("Usando chave informada no campo")
        elif file_api_key:
            st.caption(f"Usando chave carregada do arquivo: {key_file_path}")
        elif env_api_key:
            st.caption("Usando GROQ_API_KEY do ambiente")
        else:
            st.caption("Sem chave detectada. Preencha o campo, GROQ_API_KEY ou GROQ_API_KEY_FILE")

        if api_key and not api_key.startswith("gsk_"):
            st.warning("Formato de chave inesperado. A chave da Groq normalmente começa com 'gsk_'.")
        
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
                type=['docx', 'txt'], 
                accept_multiple_files=True
            )

            strict_paragraph_mode = st.checkbox(
                "Modo estrito por parágrafos (mais seguro para preservar citações; pode ser mais lento)",
                value=True,
                help="Quando ativado, o texto é revisado em múltiplas requisições por parágrafo para reduzir risco de perda de citações."
            )

            strict_citation_lock = st.checkbox(
                "Bloqueio duro de citações (falha o capítulo se houver divergência)",
                value=False,
                help="Quando ativado, o capítulo é interrompido se a assinatura/ordem das citações finais divergir do texto original."
            )
        
        if uploaded_files:
            st.info(f"📁 **{len(uploaded_files)} arquivo(s)** carregado(s) e prontos para processamento na fila.")
            st.caption(
                "As referências serão detectadas automaticamente no final de cada capítulo enviado."
            )
            
            # Registrar pendentes silenciosamente
            for file in uploaded_files:
                # Adiciona ao rastreamento com status Pendente
                if file.name not in st.session_state.app_state["status_capitulos"]:
                    # Tenta identificar título do índice a partir do nome do arquivo
                    matched_title = None
                    try:
                        matched_title = identify_chapter_title_from_filename(
                            st.session_state.app_state,
                            file.name,
                            gerenciador=st.session_state.get('gerenciador_indice')
                        )
                    except Exception:
                        matched_title = None

                    if matched_title:
                        update_chapter_status(st.session_state.app_state, file.name, "Pendente", titulo_indice=matched_title)
                    else:
                        update_chapter_status(st.session_state.app_state, file.name, "Pendente")
                    
            # Botão de iniciar processamento na tela principal
            if st.button("▶️ Iniciar Processamento Inteligente", type="primary", use_container_width=True):
                # Validar API key antes de processar
                is_valid, msg = validate_api_key(api_key)
                if not is_valid:
                    st.error(msg)
                else:
                    process_files(
                        uploaded_files,
                        api_key,
                        strict_paragraph_mode=strict_paragraph_mode,
                        strict_citation_lock=strict_citation_lock,
                    )
            
        # Exibição do estado atual do projeto
        st.divider()
        st.header("📊 Resumo do Projeto")
        
        col1, col2 = st.columns(2)
        
        with col1:
            with st.container(border=True):
                st.subheader("📑 Status dos Capítulos")
                status_data = st.session_state.app_state.get("status_capitulos", {})
                if status_data:
                    # Contadores
                    concluidos = sum(1 for s in status_data.values() if s.get("status") == "Concluído")
                    pendentes = sum(1 for s in status_data.values() if s.get("status") == "Pendente")
                    erros = sum(1 for s in status_data.values() if "Erro" in s.get("status", ""))
                    
                    st.markdown(f"**✅ Processados:** {concluidos}")
                    st.markdown(f"**⏳ Pendentes:** {pendentes}")
                    st.markdown(f"**❌ Falhados:** {erros}")
                    st.markdown("---")
                    
                    for cap, status in status_data.items():
                        emoji = gerenciador._get_status_emoji(status)
                        st.markdown(f"{emoji} **{cap}**")
                else:
                    st.info("Nenhum capítulo na fila ou processado ainda.")
                
        with col2:
            with st.container(border=True):
                st.subheader("🗂️ Índice Estruturado da Obra")
                indice_data = st.session_state.app_state.get("indice_capitulos", {})
                status_data = st.session_state.app_state.get("status_capitulos", {})
                
                if indice_data:
                    ordem = st.session_state.app_state.get("ordem_capitulos", list(indice_data.keys()))
                    for idx, title in enumerate(ordem, 1):
                        subtopics = indice_data.get(title, [])
                        status_info = status_data.get(title, {})
                        emoji = gerenciador._get_status_emoji(status_info)
                        
                        st.markdown(f"**{idx}. {emoji} {title}**")
                        if subtopics:
                            for topic in subtopics[:5]:  # Mostra apenas os 5 primeiros
                                st.markdown(f"   - {topic}")
                            if len(subtopics) > 5:
                                st.markdown(f"   - ... e {len(subtopics) - 5} tópicos mais")
                        st.markdown("")  # Espaço
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
                # Filtros: busca por nome, status e seção
                st.markdown("**Filtros de Capítulos**")
                col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
                with col_f1:
                    name_search = st.text_input("Buscar por nome", value="", placeholder="Parte do nome do arquivo")
                with col_f2:
                    status_filter = st.selectbox("Filtrar por status", options=["Todos", "Concluído", "Pendente", "Em Processamento", "Erro", "Sem Status"], index=0)
                with col_f3:
                    secoes_all = st.session_state.gerenciador_indice.obter_secoes() if 'gerenciador_indice' in st.session_state else []
                    sec_options = ["Todas"] + secoes_all
                    section_filter = st.selectbox("Filtrar por seção", options=sec_options, index=0)

                # Construir lista de capítulos a partir do estado
                all_chapters = list(status_data.keys())
                filtered_chapters = []
                secoes_map = st.session_state.gerenciador_indice.estado.get("secoes", {}) if 'gerenciador_indice' in st.session_state else {}

                for ch in all_chapters:
                    info = status_data.get(ch, {}) or {}
                    st_status = info.get("status", "")

                    # name filter
                    if name_search and name_search.lower() not in ch.lower():
                        continue

                    # status filter
                    if status_filter != "Todos":
                        if status_filter == "Erro":
                            if "Erro" not in st_status:
                                continue
                        elif status_filter == "Sem Status":
                            if st_status:
                                continue
                        else:
                            if st_status != status_filter:
                                continue

                    # section filter
                    if section_filter != "Todas":
                        # find chapter title in secoes_map values
                        in_section = False
                        for sec_name, caps in secoes_map.items():
                            if ch in caps and sec_name == section_filter:
                                in_section = True
                                break
                        if not in_section:
                            continue

                    filtered_chapters.append(ch)

                if not filtered_chapters:
                    st.info("Nenhum capítulo corresponde aos filtros selecionados.")
                else:
                    selected_chapter = st.selectbox("📌 Selecione um capítulo para revisar", filtered_chapters)
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🗑️ Excluir Capítulo", use_container_width=True):
                    success, msg = delete_chapter_safe(
                        st.session_state.app_state,
                        selected_chapter,
                        gerenciador=st.session_state.gerenciador_indice
                    )
                    save_progress(st.session_state.app_state)
                    
                    if success:
                        st.toast(msg, icon="🗑️")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

            # ===== Operações em Lote =====
            if filtered_chapters:
                multi_selected = st.multiselect("🔁 Selecionar múltiplos capítulos para ações em lote", filtered_chapters, key="bulk_select")
                if multi_selected:
                    st.markdown("**Ações em Lote**")
                    bcol1, bcol2, bcol3 = st.columns(3)
                    with bcol1:
                        if st.button("🗑️ Excluir Selecionados", use_container_width=True):
                            confirm = st.checkbox("Confirmar exclusão em lote", key="confirm_bulk_delete")
                            if confirm:
                                ger = st.session_state.get("gerenciador_indice", None)
                                results = bulk_delete_chapters(st.session_state.app_state, multi_selected, gerenciador=ger)
                                save_progress(st.session_state.app_state)
                                for ch, (ok, m) in results.items():
                                    if ok:
                                        st.success(m)
                                    else:
                                        st.error(f"{ch}: {m}")
                                time.sleep(1)
                                st.rerun()
                    with bcol2:
                        sections = []
                        if 'gerenciador_indice' in st.session_state:
                            sections = st.session_state.gerenciador_indice.obter_secoes()
                        target_section = st.selectbox("Mover para seção", options=["-- Selecionar --"] + sections, key="bulk_move_section")
                        if st.button("🔀 Mover Selecionados", use_container_width=True):
                            if target_section and target_section != "-- Selecionar --":
                                ger = st.session_state.gerenciador_indice
                                status_caps = st.session_state.app_state.get("status_capitulos", {})
                                titles = []
                                for fn in multi_selected:
                                    info = status_caps.get(fn, {}) or {}
                                    titulo = info.get("titulo_indice") or fn
                                    titles.append(titulo)
                                move_results = bulk_move_chapters(ger, titles, target_section)
                                st.session_state.gerenciador_indice = ger
                                for t, ok in move_results.items():
                                    if ok:
                                        st.success(f"{t} → {target_section}")
                                    else:
                                        st.error(f"Falha ao mover {t}")
                                time.sleep(1)
                                st.rerun()
                    with bcol3:
                        if st.button("🔁 Reprocessar Selecionados", use_container_width=True):
                            is_valid, msg = validate_api_key(api_key)
                            if not is_valid:
                                st.error(msg)
                            else:
                                re_results = reprocess_chapters(multi_selected, api_key, process_files, temp_dir=TEMP_DIR)
                                # Construir relatório resumido
                                lines = []
                                for ch, res in re_results.items():
                                    if isinstance(res, str) and ("Pronto" in res or "Pronto para" in res):
                                        lines.append(f"OK: {ch} — {res}")
                                    else:
                                        lines.append(f"FAIL: {ch} — {res}")

                                report_text = "\n".join(lines)
                                if report_text:
                                    st.subheader("Relatório de Reprocessamento")
                                    st.code(report_text, language="text")
                                    st.download_button("📥 Baixar Relatório de Reprocessamento", data=report_text, file_name="reprocess_report.txt", mime="text/plain")
                                else:
                                    st.info("Nenhum item reprocessado.")

                                time.sleep(1)
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
        
        # Usa o gerenciador já inicializado na main
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

                # Filtros: busca por nome, status e seção (aplicados à ordem atual)
                colf1, colf2, colf3 = st.columns([2, 1, 1])
                with colf1:
                    reorder_search = st.text_input("Buscar na ordem por nome", value="", placeholder="Parte do título")
                with colf2:
                    reorder_status = st.selectbox("Filtrar por status", options=["Todos", "Concluído", "Pendente", "Em Processamento", "Erro", "Sem Status"], index=0, key="reorder_status")
                with colf3:
                    reorder_section = st.selectbox("Filtrar por seção", options=["Todas"] + gerenciador.obter_secoes(), index=0, key="reorder_section")

                ordem_atual = gerenciador.estado.get("ordem_capitulos", capitulos)
                status_caps = st.session_state.app_state.get("status_capitulos", {})

                # Aplica filtros à ordem_atual
                ordem_filtered = []
                secoes_map = gerenciador.estado.get("secoes", {})
                for titulo in ordem_atual:
                    # search
                    if reorder_search and reorder_search.lower() not in titulo.lower():
                        continue
                    # status
                    info = status_caps.get(titulo, {}) or {}
                    st_status = info.get("status", "")
                    if reorder_status != "Todos":
                        if reorder_status == "Erro":
                            if "Erro" not in st_status:
                                continue
                        elif reorder_status == "Sem Status":
                            if st_status:
                                continue
                        else:
                            if st_status != reorder_status:
                                continue
                    # section
                    if reorder_section != "Todas":
                        in_section = False
                        for sec_name, caps in secoes_map.items():
                            if titulo in caps and sec_name == reorder_section:
                                in_section = True
                                break
                        if not in_section:
                            continue
                    ordem_filtered.append(titulo)
                
                # Reordenação via multiselect com status emojis
                st.markdown("**📋 Reordene os capítulos:**")
                st.caption("💡 Clique e arraste para reordenar, ou use o multiselect para escolher a nova ordem")
                
                # Cria lista de opções com status emojis
                opcoes_com_status = [f"{gerenciador._get_status_emoji(status_caps.get(titulo, {}))} {titulo}" for titulo in ordem_atual]
                
                nova_ordem_com_status = st.multiselect(
                    "Selecione e reordene os capítulos:",
                    options=opcoes_com_status,
                    default=opcoes_com_status,
                    key="reorder_multiselect"
                )
                
                if st.button("✅ Confirmar Nova Ordem", use_container_width=True, type="primary"):
                    if nova_ordem_com_status and len(nova_ordem_com_status) == len(ordem_atual):
                        # Remove os emojis para obter os títulos originais
                        nova_ordem = [titulo for titulo in ordem_atual 
                                     if any(titulo in opt for opt in nova_ordem_com_status)]
                        if gerenciador.reordenar_capitulos(nova_ordem):
                            st.success("✅ Capítulos reordenados com sucesso!")
                            st.session_state.gerenciador_indice = gerenciador
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("❌ Erro ao reordenar capítulos.")
                    else:
                        st.warning("⚠️ Selecione todos os capítulos!")
        
        
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
                status_caps = st.session_state.app_state.get("status_capitulos", {})
                
                if not secoes_data:
                    st.info("Nenhuma seção criada ainda.")
                else:
                    for secao_nome, capitulos_secao in secoes_data.items():
                        with st.expander(f"📂 {secao_nome} ({len(capitulos_secao)} capítulo(s))", expanded=False):
                            if capitulos_secao:
                                for i, cap in enumerate(capitulos_secao, 1):
                                    emoji = gerenciador._get_status_emoji(status_caps.get(cap, {}))
                                    st.markdown(f"{i}. {emoji} **{cap}**")
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
                    success, msg = delete_chapter_safe(
                        st.session_state.app_state,
                        capitulo_del,
                        gerenciador=gerenciador
                    )
                    
                    if success:
                        save_progress(st.session_state.app_state)
                        st.success(msg)
                        st.session_state.gerenciador_indice = gerenciador
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
        
        # ========== SUBTAB 4: Relatório ==========
        with subtab4:
            st.subheader("📊 Relatório da Estrutura")
            
            status_caps = st.session_state.app_state.get("status_capitulos", {})
            relatorio = gerenciador.gerar_relatorio(status_capitulos=status_caps)
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

        # ========== SUBTAB 5: Outputs & Logs ==========
        with st.container():
            st.header("📁 Outputs & Logs")
            col_out, col_logs = st.columns([1, 1])

            with col_out:
                st.subheader("Arquivos de Saída")
                # Controles: abrir pasta, pesquisa e filtro por tipo
                open_btn = st.button("Abrir pasta no Explorer")
                search_name = st.text_input("Pesquisar arquivos (parte do nome)", value="")
                file_type = st.selectbox("Filtrar por tipo", options=["Todos", "docx", "pdf", "ai.txt"], index=0)

                if open_btn:
                    try:
                        if os.path.exists(OUTPUT_DIR):
                            # No Windows, abre o Explorer na pasta
                            try:
                                os.startfile(OUTPUT_DIR)
                            except Exception:
                                # Cross-platform fallback
                                import subprocess, sys
                                if sys.platform == 'darwin':
                                    subprocess.Popen(["open", OUTPUT_DIR])
                                else:
                                    subprocess.Popen(["xdg-open", OUTPUT_DIR])
                        else:
                            st.error("Pasta de saída não existe.")
                    except Exception as e:
                        st.error(f"Não foi possível abrir a pasta: {e}")

                if os.path.exists(OUTPUT_DIR):
                    all_files = [f for f in os.listdir(OUTPUT_DIR) if not f.startswith('.')]
                    # Aplica filtros
                    files_filtered = []
                    for f in all_files:
                        if search_name and search_name.lower() not in f.lower():
                            continue
                        if file_type != "Todos":
                            if not f.lower().endswith(file_type):
                                continue
                        files_filtered.append(f)

                    if files_filtered:
                        # ordenar por modificação (mais recentes primeiro)
                        files_filtered.sort(key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)
                        for fname in files_filtered:
                            fpath = os.path.join(OUTPUT_DIR, fname)
                            mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(fpath)))
                            size_kb = os.path.getsize(fpath)//1024
                            cols = st.columns([6, 1, 1, 1])
                            with cols[0]:
                                st.markdown(f"**{fname}**  — {size_kb} KB  — {mtime}")
                            with cols[1]:
                                with open(fpath, "rb") as fh:
                                    st.download_button(label="🔽", data=fh, file_name=fname, key=f"dl_{fname}")
                            with cols[2]:
                                if st.button("🗑️", key=f"del_out_{fname}"):
                                    try:
                                        os.remove(fpath)
                                        st.success(f"Arquivo {fname} removido")
                                        st.experimental_rerun()
                                    except Exception as e:
                                        st.error(f"Erro ao remover {fname}: {e}")
                            with cols[3]:
                                if st.button("🔍 Mostrar caminho", key=f"path_{fname}"):
                                    st.caption(fpath)
                    else:
                        st.info("Nenhum arquivo que corresponda aos filtros.")
                else:
                    st.info("Pasta de saída não encontrada.")

                st.divider()
                st.subheader("Backups do Progresso")
                backups = list_backups()
                if backups:
                    backup_dir = os.path.join(os.path.dirname(PROGRESS_FILE), "backups")
                    for b in backups:
                        filename = b.get('filename')
                        created = b.get('created', '')
                        backup_path = os.path.join(backup_dir, filename) if filename else None
                        size_kb = None
                        if backup_path and os.path.exists(backup_path):
                            try:
                                size_kb = os.path.getsize(backup_path) // 1024
                            except Exception:
                                size_kb = None

                        cols = st.columns([6, 1])
                        with cols[0]:
                            line = f"{filename} — {created}"
                            if size_kb is not None:
                                line += f" — {size_kb} KB"
                            st.markdown(line)

                        # Restore workflow with explicit confirmation
                        pending_key = f"pending_restore_{filename}"
                        confirm_key = f"confirm_restore_{filename}"
                        with cols[1]:
                            if not st.session_state.get(pending_key, False):
                                if st.button("↺ Restaurar", key=f"restore_{filename}"):
                                    st.session_state[pending_key] = True
                            else:
                                st.warning(f"Você está prestes a restaurar '{filename}'. Esta ação sobrescreverá o progresso atual.")
                                if st.button("CONFIRMAR RESTAURAR", key=confirm_key):
                                    try:
                                        restore_backup(filename)
                                        st.success(f"Backup {filename} restaurado. Recarregue a aplicação.")
                                        st.session_state[pending_key] = False
                                    except Exception as e:
                                        st.error(f"Erro ao restaurar backup: {e}")
                                        st.session_state[pending_key] = False
                                if st.button("Cancelar", key=f"cancel_{filename}"):
                                    st.session_state[pending_key] = False
                else:
                    st.info("Nenhum backup encontrado.")

            with col_logs:
                st.subheader("Logs de Execução")
                log_path = os.path.join(os.path.dirname(__file__), "logs", "app.log")
                if os.path.exists(log_path):
                    try:
                        with open(log_path, "r", encoding="utf-8") as lf:
                            lines = lf.read().splitlines()
                        # Mostra últimas 400 linhas
                        preview = "\n".join(lines[-400:])
                        st.code(preview, language="text")
                        with open(log_path, "rb") as lfbin:
                            st.download_button("📥 Baixar log completo", data=lfbin, file_name="app.log")
                        if st.button("🧹 Limpar Log"):
                            try:
                                open(log_path, "w", encoding="utf-8").close()
                                st.success("Log limpo com sucesso")
                                st.experimental_rerun()
                            except Exception as e:
                                st.error(f"Erro ao limpar log: {e}")
                    except Exception as e:
                        st.error(f"Erro ao ler log: {e}")
                else:
                    st.info("Arquivo de log não encontrado.")

if __name__ == "__main__":
    main()
