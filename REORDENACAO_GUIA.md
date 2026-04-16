# 🎯 Reordenação e Organização de Índice - Guia Rápido

## ⚡ Features Adicionadas

### 1. ✴️ Reordenação de Capítulos
- Botões ⬆️ para mover para cima
- Botões ⬇️ para mover para baixo
- Multiselect para reordenação manual
- Confirmação antes de salvar

### 2. 🏷️ Organização em Seções
- Criar novas seções (especialidades)
- Mover capítulos entre seções
- Visualizar seções e seus capítulos
- Deletar seções

### 3. 🗑️ Deletar Capítulos
- Remove capítulo do índice
- Mostra subtópicos antes de deletar
- Confirmação de segurança

### 4. 📊 Relatório e Export
- Gera relatório textual completo
- Export para JSON
- Import de JSON exportado previamente
- Versioning da estrutura

---

## 🚀 Como Usar

### Acessar o Gerenciador

1. Abra a aplicação: `streamlit run app.py`
2. Vá para a aba **"📚 Organizar Índice"**
3. Escolha uma das 4 subtabs

### Exemplo: Organizar por Especialidades

#### Passo 1: Criar Seções
```
Aba: 📚 Organizar Índice
Subtab: 🏷️ Seções → Criar

1. Digite "Cardiologia"
2. Clique em "➕ Criar Seção"
3. Repita para outras especialidades
```

#### Passo 2: Mover Capítulos
```
Subtab: 🏷️ Seções → Mover Capítulo

1. Selecione capítulo
2. Selecione seção destino
3. Clique em "🔗 Mover Capítulo"
```

#### Passo 3: Reordenar
```
Subtab: 📋 Reordenar

1. Use botões ⬆️ ⬇️ ou multiselect
2. Clique em "✅ Confirmar Nova Ordem"
```

#### Passo 4: Gerar Relatório
```
Subtab: 📊 Relatório

1. Visualize a estrutura
2. Faça download em TXT ou JSON
```

---

## 📋 Estrutura de Dados (progresso.json)

```json
{
  "indice_capitulos": {
    "Capítulo 1": ["subtópico 1", "subtópico 2"],
    "Capítulo 2": ["subtópico 3"]
  },
  "secoes": {
    "Cardiologia": ["Capítulo 1"],
    "Infectologia": ["Capítulo 2"]
  },
  "ordem_capitulos": ["Capítulo 2", "Capítulo 1"]
}
```

---

## 🎯 Casos de Uso

### Caso 1: Livro de Protocolos Clínicos
```
Seções:
- Protocolos de Urgência
- Protocolos de Rotina
- Protocolos Preventivos
- Diretrizes Especiais

Ação:
1. Criar 4 seções
2. Mover 12 capítulos para seções
3. Reordenar capítulos dentro de cada seção
4. Export final para versionamento
```

### Caso 2: Livro por Especialidades
```
Seções:
- Cardiologia
- Pneumologia
- Gastroenterologia
- Neurologia

Ação:
1. Criar 4 seções
2. Mover capítulos de cada especialista
3. Estabelecer ordem de leitura
4. Gerar índice hierárquico
```

### Caso 3: Livro com Subdivisões
```
Seções:
- Conceitos Fundamentais
- Diagnóstico
- Tratamento
- Casos Clínicos

Ação:
1. Criar estrutura de seções
2. Atribuir capítulos por tema
3. Reordenar por complexidade
4. Export para documentação
```

---

## ⌨️ Keyboard Shortcuts (Futuro)

- `↑` / `↓` : Navegar entre capítulos (quando implementado)
- `Ctrl+S` : Salvar mudanças (quando implementado)
- `Ctrl+Z` : Desfazer (quando implementado)

---

## 🔒 Segurança e Backup

### Proteções Implementadas
- ✅ Backup automático antes de qualquer mudança
- ✅ Confirmação antes de deletar
- ✅ Logging de todas as operações
- ✅ Restauração fácil de backup

### Como Restaurar de um Backup
```
Terminal:
python -c "
from backup import restore_backup, list_backups
backups = list_backups()
restore_backup(backups[1]['filename'])  # Restaura segundo backup
"
```

---

## 🐛 Troubleshooting

### Problema: Botões ⬆️ ⬇️ não funcionam
**Solução:** Verifique se o capítulo está no topo/final

### Problema: Não consigo criar seção
**Solução:** Use um nome único, sem caracteres especiais

### Problema: Mover capítulo falha
**Solução:** Certifique-se de que a seção existe

### Problema: Export de JSON falha
**Solução:** Verifique permissões de leitura/escrita

---

## 📊 Relatório de Exemplo

```
============================================================
RELATÓRIO DO ÍNDICE DO LIVRO
============================================================

Total de capítulos: 12

SEÇÕES E CAPÍTULOS:
------------------------------------------------------------

[Cardiologia]
  1. Infarto Agudo do Miocárdio
     • Fisiopatologia
     • Diagnóstico
     • Tratamento
  2. Arritmias Cardíacas
     • Classificação
     • ECG
     • Conduta

[Infectologia]
  3. COVID-19
     • Epidemiologia
     • Sintomas
     • Protocolos

============================================================
```

---

## 🎓 Aprendizado

### Conceitos Principais

1. **Índice Estruturado**
   - Hierarquização de conteúdo
   - Seções e subsecções
   - Ordem de apresentação

2. **Flexibilidade**
   - Fácil reorganização
   - Sem perda de dados
   - Versionamento

3. **Usabilidade**
   - Interface intuitiva
   - Confirmações de segurança
   - Feedback imediato

---

## 📚 Recursos Adicionais

- Documentação completa: `INDEX_MANAGER.md`
- Changelog: `CHANGELOG.md#v210`
- API Python: `index_manager.py`

---

**Última atualização**: 2024-04-16  
**Versão**: 2.1.0
