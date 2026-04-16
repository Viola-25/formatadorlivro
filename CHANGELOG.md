# Changelog - Formatador de Livros

## [2.1.0] - 2024-04-16 - Gerenciador de Índice

### ✨ Adicionado

#### 🎯 Novo Módulo: Gerenciador de Índice
- **`index_manager.py`** - Classe `GerenciadorIndice` com funcionalidades:
  - ✅ Reordenação de capítulos
  - ✅ Organização em seções/especialidades
  - ✅ Deletar capítulos
  - ✅ Mover capítulos entre seções
  - ✅ Gerar relatórios
  - ✅ Export/Import JSON

#### 🎨 Nova Aba no Streamlit: "📚 Organizar Índice"
Com 4 subtabs:
1. **📋 Reordenar** - Botões ⬆️⬇️ e drag-and-drop simulado
2. **🏷️ Seções** - Criar, mover e listar seções
3. **🗑️ Deletar** - Remover capítulos do índice
4. **📊 Relatório** - Visualizar, exportar e importar estrutura

#### 📚 Documentação
- **`INDEX_MANAGER.md`** - Guia completo e API do gerenciador

### 🔧 Melhorias

**app.py**
- ✅ Adicionada aba4 com interface completa
- ✅ Session state para persistir gerenciador
- ✅ Integração com Streamlit session

### 📊 Casos de Uso

1. **Estruturação por Especialidades**
   - Cardiologia, Infectologia, Oncologia, etc
   - Organizar capítulos por especialidade

2. **Subdivisões Temáticas**
   - Protocolos, Diretrizes, Condutas
   - Organizar por tipo de conteúdo

3. **Customização de Estrutura**
   - Reordenar em qualquer momento
   - Ajustar divisões conforme necessário

### 🎯 Funcionalidades Principais

#### Reordenação
```python
gerenciador.mover_capitulo_acima("Título")
gerenciador.mover_capitulo_abaixo("Título")
gerenciador.reordenar_capitulos(["Cap 2", "Cap 1", "Cap 3"])
```

#### Seções
```python
gerenciador.criar_secao("Cardiologia")
gerenciador.mover_capitulo_para_secao("Cap 1", "Cardiologia")
gerenciador.obter_capitulos_por_secao()
```

#### Gerenciamento
```python
gerenciador.deletar_capitulo("Título")
gerenciador.gerar_relatorio()
gerenciador.exportar_estrutura()
gerenciador.importar_estrutura(estrutura_json)
```

### 📈 Benefícios

| Funcionalidade | Benefício |
|---|---|
| Reordenação | Flexibilidade na organização |
| Seções | Estrutura hierárquica |
| Deletar | Limpeza de índice |
| Relatório | Visibilidade da estrutura |
| Export/Import | Backup e versionamento |

### 🔒 Segurança

- ✅ Backup automático antes de mudanças
- ✅ Validação de dados
- ✅ Logging de operações
- ✅ Restauração de backup em caso de erro

---

## [2.0.0] - 2024-04-16 - Melhorias Estruturais Completas

### ✨ Adicionado

#### 🔧 Arquivos Novos
- **`config.py`** - Configuração centralizada de toda a plataforma
  - Constantes de estilo, modelos, caminhos, tamanhos
  - Suporte a variáveis de ambiente
  - Fácil customização

- **`logger.py`** - Sistema de logging estruturado
  - Logging em arquivo + console
  - Rotação automática de logs
  - Níveis configuráveis

- **`cache.py`** - Cache inteligente de requisições IA
  - Hash MD5 para deduplicação
  - TTL configurável
  - Limpeza automática

- **`backup.py`** - Backup e versionamento de progresso
  - Backup automático antes de salvar
  - Restauração de versões anteriores
  - Histórico de até 5 versões

- **`validator.py`** - Validação com Pydantic
  - Schema para ChapterIndex
  - Schema para ChapterStatus
  - Erros estruturados

- **`exceptions.py`** - Hierarquia de exceções customizadas
  - APIException e subclasses
  - DocumentException e subclasses
  - FormattingException e subclasses

#### 🎯 Melhorias em Arquivos Existentes

**engine.py**
- ✅ Importa de config centralizada
- ✅ Logging detalhado em todas as funções
- ✅ Cache automático de resultados IA
- ✅ Type hints melhorados
- ✅ Exceções customizadas
- ✅ Tratamento robusto de erros de quota
- ✅ Retry com backoff exponencial

**app.py**
- ✅ Importa de config centralizada
- ✅ Logging de todas as operações
- ✅ Backup automático antes de salvar
- ✅ Validação com Pydantic
- ✅ Tratamento granular de exceções
- ✅ Contadores de sucesso/erro
- ✅ Type hints em todas as funções

**formatter.py**
- ✅ Importa de config centralizada
- ✅ Logging de formatação
- ✅ Type hints melhorados
- ✅ Tratamento de erros com exceções

#### 📄 Documentação
- **`README.md`** - Guia completo com exemplos
- **`.env.example`** - Variáveis de ambiente padrão
- **`CHANGELOG.md`** - Este arquivo

#### 📋 Dependências
- **`requirements.txt`** - Atualizado com `pydantic>=2.0.0`

### 🎯 Benefícios

| Categoria | Antes | Depois |
|-----------|-------|--------|
| **Performance** | Nenhum cache | Cache inteligente (TTL 24h) |
| **Debugging** | print() apenas | Logging estruturado |
| **Segurança** | Sem backup | Backup automático + histórico |
| **Validação** | Manual | Pydantic automática |
| **Manutenção** | Constantes espalhadas | Config centralizada |
| **Type Safety** | Parcial | Completo com hints |

---

**Versão**: 2.1.0  
**Data**: 2024-04-16  
**Status**: ✅ Produção

### 🔄 Mudanças Internas

#### Fluxo de Processamento Atualizado
```
1. Receeber arquivo
   ↓
2. Validar tipo/tamanho
   ↓
3. Extrair texto (com logging)
   ↓
4. Verificar CACHE ← NOVO
   ├─ Se encontrado → Usar resultado cacheado
   └─ Se não → Continuar
   ↓
5. Processar IA
   - Com retry e backoff
   - Exceções customizadas
   - Logging em cada étapa
   ↓
6. SALVAR CACHE ← NOVO
   ↓
7. Validar resultado (Pydantic) ← NOVO
   ↓
8. CRIAR BACKUP ← NOVO
   ↓
9. Formatar DOCX (com logging)
   ↓
10. Gerar PDF (opcional)
   ↓
11. Retornar resultado
```

#### Estrutura de Logs
```
2024-04-16 14:30:45,123 - BookFormatter - INFO - Iniciando processamento de 1 arquivo(s)
2024-04-16 14:30:45,234 - BookFormatter - DEBUG - Arquivo salvo temporariamente: temp/file.docx
2024-04-16 14:30:45,345 - BookFormatter - INFO - Verificando cache para este capítulo...
2024-04-16 14:30:45,456 - BookFormatter - INFO - Cache hit para abc123_gemini-2.0-flash
2024-04-16 14:30:45,567 - BookFormatter - INFO - Índice processado: Introdução à APS
2024-04-16 14:30:45,678 - BookFormatter - INFO - Backup criado: .cache/backups/progresso_2024-04-16_143045.json
```

#### Estrutura de Cache
```
.cache/
├── abc123_gemini-2.0-flash.json  ← Hash do texto + modelo
└── def456_gemini-1.5-pro.json

Conteúdo:
{
  "cached_at": "2024-04-16T14:30:45.123456",
  "model": "gemini-2.0-flash",
  "text_hash": "abc123def456",
  "result": "texto processado..."
}
```

#### Estrutura de Backup
```
.cache/backups/
├── progresso_2024-04-16_140000.json
├── progresso_2024-04-16_141500.json
├── progresso_2024-04-16_143000.json
└── (máx 5, remove mais antigos)
```

### 🚀 Próximas Melhorias Sugeridas

- [ ] Interface web para gerenciar cache
- [ ] Dashboard de métricas (cache hit rate, tempos médios)
- [ ] Compressão de logs antigos
- [ ] Notificações por email de erros
- [ ] API REST para integração
- [ ] Resumos em banco de dados em vez de JSON
- [ ] Versionamento de capítulos no Git
- [ ] Preview inline dos documentos formatados

### 🔧 Notas Técnicas

- Pydantic 2.0+ com validação mais rigorosa
- Type hints 100% coverage
- Exceções específicas para cada cenário
- Logging com rotação (5 MB por arquivo)
- Cache com expiração (padrão 24h)
- Backup rotativo (máx 5 versões)

---

**Versão**: 2.0.0  
**Data**: 2024-04-16  
**Status**: ✅ Produção
