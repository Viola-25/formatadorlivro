# Prompt para Construir o Novo Portal de Formatação de Capítulos

## Objetivo Principal
Construir um **portal Streamlit simplificado** para formatação de capítulos de livros que segue o fluxo:
**Upload em lote → Formatação local → Diff de revisão → Sugestões por IA → Aceitação manual por parágrafo/box → Download**

## Stack Tecnológico
- **Framework Web**: Streamlit (Python)
- **LLM**: Groq API (modelos: llama-3.3-70b-versatile, llama-3.1-8b-instant)
- **Processamento de Arquivos**: python-docx (leitura), docx2pdf (conversão)
- **Validação de Dados**: Pydantic
- **Persistência de Estado**: JSON (progresso.json)
- **Backup**: Automático antes de cada escrita de estado
- **Logging**: Sistema rotativo com arquivo e console
- **Diff**: difflib.unified_diff para visualização

## Estrutura de Diretórios
```
.
├── app.py                 # Entrada principal do Streamlit
├── engine.py              # Processamento de texto e IA
├── formatter.py           # Geração DOCX/PDF
├── config.py              # Configurações centralizadas
├── logger.py              # Sistema de logging
├── backup.py              # Gerenciamento de backups
├── cache.py               # Cache MD5 de outputs
├── index_manager.py       # Gerenciador de índice (mantém estrutura)
├── validator.py           # Validações Pydantic
├── utils.py               # Funções auxiliares mínimas
├── exceptions.py          # Exceções customizadas
├── requirements.txt       # Dependências Python
├── progresso.json         # Estado persistente (JSON)
├── groq_api_key.txt       # Chave API (não commitar)
└── temp/
    └── chapters/
        └── {safe_chapter_name}/
            ├── raw.txt                 # Texto bruto do upload
            ├── normalized.txt          # Texto normalizado (sem excesso de quebras)
            ├── review.json             # Sugestões da IA
            └── reviewed.txt            # Texto final com aceites
```

## Estrutura de Estado (progresso.json)
```json
{
  "status_capitulos": {
    "Capitulo_1.docx": {
      "status": "Revisado",
      "resumo": "Descrição",
      "titulo_indice": "Capítulo 1: Introdução"
    }
  },
  "indice_capitulos": {},
  "chapters_workbench": {
    "Capitulo_1.docx": {
      "chapter_name": "Capitulo_1.docx",
      "workdir": "/temp/chapters/Capitulo_1",
      "raw_text_path": "...",
      "normalized_text_path": "...",
      "review_json_path": "...",
      "reviewed_text_path": "...",
      "formatted_docx_path": "...",
      "formatted_pdf_path": "...",
      "stage": "Revisado",
      "uploaded_at": 1234567890
    }
  },
  "workbench_order": ["Capitulo_1.docx", "Capitulo_2.docx"]
}
```

## Estrutura JSON de Revisão (review.json)
```json
{
  "paragraphs": [
    {
      "id": 0,
      "original": "Parágrafo original aqui...",
      "suggested": "Parágrafo melhorado sugerido pela IA...",
      "reason": "Melhor clareza e coesão"
    }
  ],
  "summary_box": {
    "suggested": "Resumo do capítulo em 2-3 frases"
  },
  "attention_box": {
    "suggested": "Pontos de atenção importantes"
  },
  "recommendation_box": {
    "suggested": "Recomendações para o leitor"
  },
  "notes": "Observações gerais da revisão"
}
```

## Funcionalidades Principais

### 1. app.py - Interface Streamlit
**Funções obrigatórias:**
- `load_groq_api_key_from_file(file_path)` → carrega chave do arquivo/env
- `load_progress()` → lê progresso.json com fallback para padrão
- `save_progress(state)` → salva com backup automático
- `ensure_state(state)` → normaliza chaves faltantes
- `chapter_workdir(chapter_name)` → retorna caminho padronizado para workdir
- `read_text_file(path)` → lê UTF-8 com fallback ""
- `write_text_file(path, content)` → escreve UTF-8 com mkdirs
- `extract_uploaded_text(uploaded_file)` → extrai DOCX ou TXT
- `normalize_chapter_text(text)` → remove excesso de linhas em branco
- `register_uploaded_chapter(state, file)` → registra novo upload no workbench
- `reset_workspace(state, gerenciador)` → limpa tudo
- `build_diff_text(original, candidate, chapter_name)` → unified_diff
- `render_review_boxes(chapter_name, review_data)` → widgets Streamlit para boxes
- `assemble_reviewed_text(base_text, review_data, chapter_name, box_state)` → monta texto final com aceites
- `load_review_data(review_json_path)` → carrega review.json ou {}
- `run_simplified_app()` → UI principal

**Fluxo da UI:**
1. **Sidebar**: API key input (text_input, type="password"), métricas (capítulos/formatados/revisados), botão limpar, downloads
2. **Seção 1 - Upload**: file_uploader (docx/txt), botão "Registrar capítulos"
3. **Seção 2 - Por Capítulo**: expander para cada capítulo com:
   - Coluna esquerda: Preview texto bruto, diff (se houver review)
   - Coluna direita: Botões (Formatar, Revisar por IA, Excluir, Downloads)
   - Se houver review: checkboxes para aceitar cada parágrafo + aceitação de boxes
   - Diff da seleção atual
   - Botão "Aplicar sugestões aceitas"
4. **Seção 3 - Resumo**: Expandível com status de cada capítulo

### 2. engine.py - Processamento de Texto e IA
**Funções obrigatórias:**
- `extract_text_from_docx(path)` → retorna texto bruto do DOCX
- `generate_review_suggestions(chapter_text, api_key, chapter_name, model_name=None)` → retorna JSON com:
  - `paragraphs`: list of {id, original, suggested, reason}
  - `summary_box`: {suggested: "..."}
  - `attention_box`: {suggested: "..."}
  - `recommendation_box`: {suggested: "..."}
  - `notes`: "..."
  
**Estratégia de geração de sugestões:**
- Prompt conservador que pede apenas edições pontuais (clareza, coesão, gramática)
- Aviso explícito: "Não reescreva o texto. Faça apenas edições leves."
- Retorno JSON estruturado
- Cache MD5 para evitar reaproveitar sugestões antigas

### 3. formatter.py - Geração de DOCX/PDF
**Funções obrigatórias:**
- `generate_formatted_docx(text, chapter_name)` → cria DOCX com styling, retorna filename
  - Interpreta [BOX_RESUMO], [BOX_ATENCAO], [BOX_RECOMENDACAO] como boxes especiais
  - Aplicar cores/fontes conforme config
  - Salvar em OUTPUT_DIR
- `convert_to_pdf(docx_path)` → gera PDF opcional, swallow errors

### 4. config.py - Configurações
**Constantes necessárias:**
- `TEMP_DIR = "temp"`
- `OUTPUT_DIR = "output"`
- `PROGRESS_FILE = "progresso.json"`
- `GROQ_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]`
- Cores e estilos para boxes
- Limites (max boxes, etc)

### 5. utils.py - Utilidades Mínimas
**Funções necessárias:**
- `delete_chapter_safe(state, chapter_name, gerenciador=None)` → remove da workbench e filesystem, retorna (bool, str)
- `get_chapter_safe_filename(chapter_name)` → sanitiza nome para arquivo
- `get_processing_stats(state)` → retorna dict com counts

### 6. logger.py, backup.py, cache.py, index_manager.py, validator.py, exceptions.py
- Manter as implementações existentes

## Fluxo de Uso (do ponto de vista do usuário)

1. **Upload**: Seleciona múltiplos arquivos .docx/.txt → clica "Registrar capítulos"
2. **Formatação**: Para cada capítulo, clica "Formatar capítulo"
   - Remove excesso de quebras de linha
   - Gera DOCX formatado em OUTPUT_DIR
   - Stage passa para "Formatado"
3. **Revisão por IA**: Clica "Revisar por IA" (se API key presente)
   - Envia texto normalizado para Groq
   - IA retorna sugestões (parágrafo a parágrafo + boxes)
   - JSON salvo em `review.json`
   - Stage passa para "Sugestões IA"
4. **Aceite Manual**: Para cada parágrafo, checkbox "Usar sugestão?"
   - Visualiza original vs sugestão em expander
   - Checkboxes para aceitar/rejeitar boxes (resumo, atenção, recomendação)
   - Vê diff da seleção atual
   - Clica "Aplicar sugestões aceitas"
5. **Download**: Arquivo final em DOCX/PDF em OUTPUT_DIR

## Requisitos Funcionais

### Upload
- [ ] Aceitar .docx e .txt
- [ ] Batch upload (múltiplos arquivos)
- [ ] Registrar cada um em workbench com timestamp

### Formatação Local
- [ ] Normalizar: remover excesso de linhas em branco (max 1 linha vazia entre parágrafos)
- [ ] Salvar em `normalized.txt`
- [ ] Gerar DOCX formatado com styling

### Diff Preview
- [ ] Mostrar unified_diff entre original e sugestão
- [ ] Atualizar em tempo real conforme user muda checkboxes

### Revisão por IA
- [ ] Prompt conservador (edições leves apenas)
- [ ] Retorno JSON estruturado
- [ ] Cache para evitar reaproveitar sugestões antigas
- [ ] Fallback se API falhar

### Aceite Manual
- [ ] Checkbox por parágrafo
- [ ] Aceite de cada box (resumo, atenção, recomendação)
- [ ] Visualização side-by-side em expandible
- [ ] Diff em tempo real

### Saída
- [ ] Gerar DOCX final com boxes interpretados
- [ ] Gerar PDF opcional
- [ ] Salvar em OUTPUT_DIR com download direto

## Requisitos Não-Funcionais

### Robustez
- [ ] Backup automático antes de salvar estado
- [ ] Validação de JSON ao carregar progresso.json
- [ ] Fallback para default state se corrupted
- [ ] Logging de todas as operações

### Performance
- [ ] Cache MD5 para IA outputs
- [ ] Não reprocessar se entry já completa
- [ ] Lazy load de review.json

### UX
- [ ] Sidebar com métricas e controles
- [ ] Expandible per-chapter (lazy render)
- [ ] Feedback visual claro (stage, metrics, alerts)
- [ ] Botões desabilitados se precondição não atendida

### Segurança
- [ ] API key em arquivo (groq_api_key.txt, não commitar) ou env var
- [ ] Validação de caminhos para evitar path traversal
- [ ] Sanitização de nomes de arquivo

## Dependências (requirements.txt)
```
streamlit>=1.28.0
python-docx>=0.8.11
docx2pdf>=0.1.8
pydantic>=2.0.0
groq>=0.4.0
```

## Notas Importantes

1. **Não é um remake completo do LLM**: O workbench trabalha com o LLM de forma **pontual e assistiva**, não como juiz final. O usuário vê tudo e aceita/rejeita manualmente.

2. **Conservadorismo**: As sugestões da IA devem ser **edições leves** (gramática, clareza, coesão), não rewrite completo. Sempre avisar no prompt.

3. **Per-chapter isolation**: Cada capítulo tem seu próprio workdir (`temp/chapters/{safe_name}/`). Permite processamento em paralelo no futuro.

4. **Determinístico quando possível**: Normalização de texto é feita em Python puro, antes de enviar para IA. Isso evita surpresas.

5. **State recovery**: Se o app cair, o progresso é recuperado de `progresso.json`. Backups automáticos permitem rollback.

6. **Boxes como markup**: [BOX_RESUMO], [BOX_ATENCAO], [BOX_RECOMENDACAO] são interpretados durante DOCX generation. Permite styling customizado.

## Checklist de Implementação

- [ ] Estrutura de diretórios criada
- [ ] config.py com todas as constantes
- [ ] logger.py com logging rotativo
- [ ] backup.py com snapshots automáticos
- [ ] cache.py com cache MD5
- [ ] exceptions.py com exceções customizadas
- [ ] validator.py com Pydantic models
- [ ] index_manager.py com GerenciadorIndice
- [ ] utils.py com funções mínimas (delete_chapter_safe, etc)
- [ ] engine.py com extract_text_from_docx + generate_review_suggestions
- [ ] formatter.py com generate_formatted_docx + convert_to_pdf
- [ ] app.py com run_simplified_app() e helpers
- [ ] requirements.txt com todas as dependências
- [ ] Testes de import (app, engine, utils carregam)
- [ ] Streamlit inicia sem erros (streamlit run app.py)
- [ ] UI carrega com upload section visível
- [ ] Upload funciona → registra capítulos
- [ ] Formatação funciona → gera DOCX
- [ ] Revisão IA funciona → gera review.json
- [ ] Aceite manual funciona → monta texto final
- [ ] Download funciona → DOCX/PDF em OUTPUT_DIR

---

**Pronto para usar**: Cole este prompt em uma nova conversa comigo e peça "Construa o novo portal seguindo este prompt. Implemente todos os arquivos necessários."
