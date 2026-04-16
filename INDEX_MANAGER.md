# 📚 Gerenciador de Índice - Documentação

## Visão Geral

O **Gerenciador de Índice** é um novo módulo que permite organizar, reordenar e estruturar os capítulos do seu livro em seções/especialidades. Ideal para:

- Organizações por especialidades médicas
- Subdivisões de conteúdo
- Reordenação dinâmica de capítulos
- Estruturação hierárquica do livro

## Funcionalidades

### 1. ✴️ Reordenar Capítulos

**O que faz:**
- Visualiza a ordem atual dos capítulos
- Permite mover capítulos para cima/baixo com botões
- Drag-and-drop simulado via multiselect

**Como usar:**
1. Acesse a aba "📚 Organizar Índice"
2. Vá para a subtab "📋 Reordenar"
3. Use os botões ⬆️ ⬇️ para mover capítulos
4. Ou use o multiselect para reordenar manualmente
5. Clique em "✅ Confirmar Nova Ordem"

**Resultado:**
- A ordem dos capítulos é salva permanentemente
- Os backups são criados automaticamente

### 2. 🏷️ Gerenciar Seções

**O que faz:**
- Cria seções/especialidades (ex: Cardiologia, Infectologia)
- Move capítulos entre seções
- Lista e gerencia seções

**Como usar:**

#### Criar Seção:
1. Subtab "Criar"
2. Digite o nome da seção
3. Clique em "➕ Criar Seção"

#### Mover Capítulo para Seção:
1. Subtab "Mover Capítulo"
2. Selecione o capítulo
3. Selecione a seção destino
4. Clique em "🔗 Mover Capítulo"

#### Listar Seções:
1. Subtab "Listar"
2. Expanda cada seção para ver capítulos
3. Deleta seções com botão "🗑️ Deletar Seção"

### 3. 🗑️ Deletar Capítulos

**O que faz:**
- Remove capítulos do índice permanentemente
- Mostra subtópicos antes de deletar

**Como usar:**
1. Subtab "🗑️ Deletar"
2. Selecione o capítulo
3. Revise os subtópicos
4. Clique em "🗑️ Deletar Capítulo do Índice"

### 4. 📊 Relatório

**O que faz:**
- Gera relatório textual da estrutura
- Exporta/importa estrutura em JSON

**Como usar:**

#### Ver Relatório:
1. Subtab "📊 Relatório"
2. Visualiza a estrutura completa
3. Clique em "📥 Baixar Relatório em TXT"

#### Exportar JSON:
1. Clique em "📤 Exportar Estrutura JSON"
2. Faça download do arquivo

#### Importar JSON:
1. Carregue um arquivo JSON previamente exportado
2. Clique em "📥 Importar"

---

## API do GerenciadorIndice

### Inicialização

```python
from index_manager import GerenciadorIndice

gerenciador = GerenciadorIndice()
```

### Métodos Principais

#### Listar Capítulos
```python
capitulos = gerenciador.listar_capitulos()
# Retorna: [(titulo, [subtopicos]), ...]
```

#### Deletar Capítulo
```python
sucesso = gerenciador.deletar_capitulo("Título do Capítulo")
# Retorna: bool
```

#### Reordenar
```python
nova_ordem = ["Cap 3", "Cap 1", "Cap 2"]
sucesso = gerenciador.reordenar_capitulos(nova_ordem)
# Retorna: bool
```

#### Mover Acima/Abaixo
```python
sucesso = gerenciador.mover_capitulo_acima("Título")
sucesso = gerenciador.mover_capitulo_abaixo("Título")
# Retorna: bool
```

#### Criar Seção
```python
sucesso = gerenciador.criar_secao("Cardiologia")
# Retorna: bool
```

#### Mover para Seção
```python
sucesso = gerenciador.mover_capitulo_para_secao("Cap 1", "Cardiologia")
# Retorna: bool
```

#### Obter Seções
```python
secoes = gerenciador.obter_secoes()
# Retorna: ["Cardiologia", "Infectologia"]

capitulos_por_secao = gerenciador.obter_capitulos_por_secao()
# Retorna: {"Cardiologia": ["Cap 1", "Cap 2"], ...}
```

#### Gerar Relatório
```python
relatorio = gerenciador.gerar_relatorio()
print(relatorio)
# Retorna string formatada com a estrutura
```

#### Exportar/Importar
```python
# Exportar
estrutura = gerenciador.exportar_estrutura()

# Importar
sucesso = gerenciador.importar_estrutura(estrutura)
```

---

## Estrutura de Dados

### progresso.json (Atualizado)

```json
{
  "status_capitulos": {
    "arquivo1.docx": {
      "status": "Concluído",
      "resumo": "...",
      "titulo_indice": "Cap 1"
    }
  },
  "indice_capitulos": {
    "Cap 1": ["subtópico 1", "subtópico 2"],
    "Cap 2": ["subtópico 3"]
  },
  "secoes": {
    "Cardiologia": ["Cap 1"],
    "Infectologia": ["Cap 2"]
  },
  "ordem_capitulos": ["Cap 2", "Cap 1"]
}
```

---

## Exemplo de Uso

### Cenário: Organizar Livro de Protocolos

1. **Criar Seções** (especialidades):
   - Cardiologia
   - Infectologia
   - Oncologia
   - Protocolos Gerais

2. **Adicionar Capítulos** às seções:
   - Cardiologia → IAM, Arritmias, HAS
   - Infectologia → COVID-19, Tuberculose, HIV
   - Oncologia → Câncer de Mama, Próstata
   - Protocolos → Vacinação, Triage

3. **Reordenar** capítulos dentro de cada seção

4. **Exportar** JSON para versionar

5. **Gerar** relatório final

---

## Integração com Streamlit

A aba "📚 Organizar Índice" fornece uma interface completa com:

- 4 subtabs para diferentes funcionalidades
- Botões interativos para navegação
- Multiselect para reordenação
- Expanders para visualizar seções
- Download de relatórios e JSON
- Auto-refresh após mudanças

---

## Backup e Segurança

- ✅ Backup automático antes de qualquer operação
- ✅ Restore de backup em caso de erro
- ✅ Validação de dados com Pydantic
- ✅ Logging de todas as operações

---

## Notas

- Todos os dados são salvos em `progresso.json`
- Backups são criados em `.cache/backups/`
- Operações são logadas em `logs/app.log`
- Suporta até 5 versões de backup (configurável)

---

## Troubleshooting

### Problemas Comuns

**P: Não consigo mover capítulos**
R: Certifique-se de que o capítulo foi processado na aba "Processador" primeiro.

**P: As mudanças não são salvas**
R: Verifique se há espaço em disco e permissões de leitura/escrita.

**P: Importação de JSON falha**
R: Verifique se o JSON está no formato correto (use a exportação como referência).

---

**Versão**: 1.0  
**Criado em**: 2024-04-16
