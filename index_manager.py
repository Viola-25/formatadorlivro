"""
Gerenciador de Índice - Reordenação e organização de capítulos.
Permite deletar, reordenar e organizar capítulos em seções.
"""

import json
import os
from typing import Dict, Any, List, Optional, Tuple
from config import PROGRESS_FILE
from logger import logger
from exceptions import BackupException
from backup import create_backup


class SecaoCapitulos:
    """
    Representa uma seção/divisão do livro.
    Exemplo: Especialidades, Subdivisões, etc.
    """
    def __init__(self, nome: str, ordem: int = 0):
        self.nome = nome
        self.ordem = ordem
        self.capitulos: List[Dict[str, Any]] = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário para serialização."""
        return {
            "nome": self.nome,
            "ordem": self.ordem,
            "capitulos": self.capitulos
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SecaoCapitulos":
        """Cria instância a partir de dicionário."""
        secao = SecaoCapitulos(data["nome"], data.get("ordem", 0))
        secao.capitulos = data.get("capitulos", [])
        return secao


class GerenciadorIndice:
    """
    Gerencia o índice completo do livro com suporte a seções e reordenação.
    """
    
    def __init__(self, progress_file: str = PROGRESS_FILE):
        """
        Inicializa o gerenciador.
        
        Args:
            progress_file: Caminho do arquivo de progresso
        """
        self.progress_file = progress_file
        self.estado = self._carregar_estado()
        # Se existir um índice pré-organizado em Markdown, carregue e mescle
        try:
            md_path = os.path.join(os.path.dirname(__file__), "INDEX_PREORGANIZADO.md")
            if os.path.exists(md_path):
                logger.info(f"Índice pré-organizado detectado: {md_path}. Mesclando com estado atual...")
                parsed = self._load_preorganized_index(md_path)
                if parsed:
                    self._merge_preorganized_index(parsed)
                    logger.info("Mesclagem do índice pré-organizado concluída.")
        except Exception:
            # Não falhar na inicialização por causa do arquivo de índice
            logger.debug("Nenhum índice pré-organizado mesclado")
        logger.debug("Gerenciador de índice inicializado")
    
    def _carregar_estado(self) -> Dict[str, Any]:
        """Carrega o estado do arquivo de progresso."""
        if not os.path.exists(self.progress_file):
            return {
                "indice_capitulos": {},
                "secoes": {},
                "ordem_capitulos": []
            }
        
        try:
            with open(self.progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Arquivo de progresso corrompido ao carregar índice")
            return {
                "indice_capitulos": {},
                "secoes": {},
                "ordem_capitulos": []
            }
    
    def _salvar_estado(self) -> bool:
        """Salva o estado no arquivo de progresso."""
        try:
            create_backup()
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.estado, f, ensure_ascii=False, indent=4)
            logger.debug("Estado do índice salvo")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar estado do índice: {e}")
            return False
    
    def listar_capitulos(self) -> List[Tuple[str, List[str]]]:
        """
        Lista todos os capítulos com sus subtópicos.
        
        Returns:
            Lista de tuplas (titulo, subtopicos)
        """
        indice = self.estado.get("indice_capitulos", {})
        return [(titulo, subtopicos) for titulo, subtopicos in indice.items()]
    
    def obter_capitulo(self, titulo: str) -> Optional[List[str]]:
        """
        Obtém subtópicos de um capítulo específico.
        
        Args:
            titulo: Título do capítulo
            
        Returns:
            Lista de subtópicos ou None
        """
        return self.estado.get("indice_capitulos", {}).get(titulo)
    
    def deletar_capitulo(self, titulo: str) -> bool:
        """
        Deleta um capítulo do índice.
        
        Args:
            titulo: Título do capítulo a deletar
            
        Returns:
            True se deletado com sucesso
        """
        try:
            indice = self.estado.get("indice_capitulos", {})
            
            if titulo not in indice:
                logger.warning(f"Capítulo não encontrado: {titulo}")
                return False
            
            # Remove do índice
            del indice[titulo]
            
            # Remove da ordem se existir
            ordem = self.estado.get("ordem_capitulos", [])
            if titulo in ordem:
                ordem.remove(titulo)
            
            # Remove de seções se existir
            secoes = self.estado.get("secoes", {})
            for secao_nome, capitulos_secao in secoes.items():
                if titulo in capitulos_secao:
                    capitulos_secao.remove(titulo)
            
            logger.info(f"Capítulo deletado: {titulo}")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao deletar capítulo {titulo}: {e}")
            return False
    
    def reordenar_capitulos(self, nova_ordem: List[str]) -> bool:
        """
        Reordena os capítulos.
        
        Args:
            nova_ordem: Nova ordem dos títulos dos capítulos
            
        Returns:
            True se reordenado com sucesso
        """
        try:
            indice = self.estado.get("indice_capitulos", {})
            
            # Valida se todos os capítulos na nova ordem existem
            for titulo in nova_ordem:
                if titulo not in indice:
                    logger.warning(f"Capítulo na nova ordem não existe: {titulo}")
                    return False
            
            # Atualiza a ordem
            self.estado["ordem_capitulos"] = nova_ordem
            
            logger.info(f"Capítulos reordenados. Nova ordem: {nova_ordem}")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao reordenar capítulos: {e}")
            return False
    
    def mover_capitulo_acima(self, titulo: str) -> bool:
        """Move um capítulo uma posição acima."""
        ordem = self.estado.get("ordem_capitulos", [])
        
        if titulo not in ordem:
            logger.warning(f"Capítulo não encontrado na ordem: {titulo}")
            return False
        
        idx = ordem.index(titulo)
        if idx == 0:
            logger.info(f"Capítulo {titulo} já está no topo")
            return False
        
        # Inverte com o anterior
        ordem[idx], ordem[idx - 1] = ordem[idx - 1], ordem[idx]
        return self.reordenar_capitulos(ordem)
    
    def mover_capitulo_abaixo(self, titulo: str) -> bool:
        """Move um capítulo uma posição abaixo."""
        ordem = self.estado.get("ordem_capitulos", [])
        
        if titulo not in ordem:
            logger.warning(f"Capítulo não encontrado na ordem: {titulo}")
            return False
        
        idx = ordem.index(titulo)
        if idx == len(ordem) - 1:
            logger.info(f"Capítulo {titulo} já está no final")
            return False
        
        # Inverte com o próximo
        ordem[idx], ordem[idx + 1] = ordem[idx + 1], ordem[idx]
        return self.reordenar_capitulos(ordem)
    
    def criar_secao(self, nome_secao: str) -> bool:
        """
        Cria uma nova seção (especialidade, subdivisão, etc).
        
        Args:
            nome_secao: Nome da seção
            
        Returns:
            True se criado com sucesso
        """
        try:
            secoes = self.estado.get("secoes", {})
            
            if nome_secao in secoes:
                logger.warning(f"Seção já existe: {nome_secao}")
                return False
            
            secoes[nome_secao] = []
            self.estado["secoes"] = secoes
            
            logger.info(f"Seção criada: {nome_secao}")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao criar seção: {e}")
            return False
    
    def deletar_secao(self, nome_secao: str, mover_capitulos_para: Optional[str] = None) -> bool:
        """
        Deleta uma seção.
        
        Args:
            nome_secao: Nome da seção a deletar
            mover_capitulos_para: Seção para mover os capítulos (ou None para remover associação)
            
        Returns:
            True se deletado com sucesso
        """
        try:
            secoes = self.estado.get("secoes", {})
            
            if nome_secao not in secoes:
                logger.warning(f"Seção não encontrada: {nome_secao}")
                return False
            
            capitulos_secao = secoes[nome_secao]
            
            if mover_capitulos_para:
                if mover_capitulos_para not in secoes:
                    logger.warning(f"Seção destino não existe: {mover_capitulos_para}")
                    return False
                secoes[mover_capitulos_para].extend(capitulos_secao)
            
            del secoes[nome_secao]
            self.estado["secoes"] = secoes
            
            logger.info(f"Seção deletada: {nome_secao}")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao deletar seção: {e}")
            return False
    
    def mover_capitulo_para_secao(self, titulo: str, nome_secao: str) -> bool:
        """
        Move um capítulo para uma seção.
        
        Args:
            titulo: Título do capítulo
            nome_secao: Nome da seção destino
            
        Returns:
            True se movido com sucesso
        """
        try:
            secoes = self.estado.get("secoes", {})
            
            if nome_secao not in secoes:
                logger.warning(f"Seção não existe: {nome_secao}")
                return False
            
            # Remove de outras seções
            for secao_nome, capitulos_secao in secoes.items():
                if titulo in capitulos_secao:
                    capitulos_secao.remove(titulo)
            
            # Adiciona à seção destino
            if titulo not in secoes[nome_secao]:
                secoes[nome_secao].append(titulo)
            
            logger.info(f"Capítulo {titulo} movido para seção: {nome_secao}")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao mover capítulo para seção: {e}")
            return False
    
    def obter_capitulos_por_secao(self) -> Dict[str, List[str]]:
        """
        Obtém mapping de seções para capítulos.
        
        Returns:
            Dict com seções como chaves e lista de capítulos como valores
        """
        return self.estado.get("secoes", {})
    
    def obter_secoes(self) -> List[str]:
        """
        Lista todas as seções existentes.
        
        Returns:
            Lista de nomes de seções
        """
        return list(self.estado.get("secoes", {}).keys())
    
    def exportar_estrutura(self) -> Dict[str, Any]:
        """
        Exporta a estrutura completa do índice.
        
        Returns:
            Dicionário com toda a estrutura
        """
        return {
            "capitulos": self.estado.get("indice_capitulos", {}),
            "secoes": self.estado.get("secoes", {}),
            "ordem": self.estado.get("ordem_capitulos", [])
        }

    def _load_preorganized_index(self, path: str) -> Dict[str, Any]:
        """
        Lê um arquivo Markdown simples com o índice pré-organizado e retorna
        uma estrutura básica: {"ordem": [...], "capitulos": {titulo: []}, "secoes": {}}
        """
        ordem: List[str] = []
        capitulos: Dict[str, List[str]] = {}
        secoes: Dict[str, List[str]] = {}

        with open(path, 'r', encoding='utf-8') as f:
            current_secao: Optional[str] = None
            for raw in f:
                line = raw.strip()
                if not line:
                    continue

                # Detecta UNIDADE/VOLUME como seção
                if line.upper().startswith("UNIDADE") or line.upper().startswith("VOLUME"):
                    current_secao = line
                    secoes.setdefault(current_secao, [])
                    continue

                # Linhas que iniciam com 'Capítulo' são capítulos
                if line.startswith("Capítulo") or line.lower().startswith("capítulo"):
                    # Normaliza título
                    titulo = line
                    ordem.append(titulo)
                    capitulos.setdefault(titulo, [])
                    if current_secao:
                        secoes.setdefault(current_secao, []).append(titulo)
                    continue

                # Detecta subcapítulos numerados como 14.2.1. ou linhas como '15.5.1. Dor'
                if line[0].isdigit() and '.' in line:
                    # tratar como subtópico simples: anexar ao último capítulo
                    if ordem:
                        ultimo = ordem[-1]
                        capitulos.setdefault(ultimo, []).append(line)
                    continue

        return {"ordem": ordem, "capitulos": capitulos, "secoes": secoes}

    def _merge_preorganized_index(self, estrutura: Dict[str, Any]) -> None:
        """
        Mescla a estrutura pré-organizada com o estado atual sem sobrescrever dados
        já existentes. Novos capítulos são adicionados e a ordem é atualizada.
        """
        indice_atual = self.estado.get("indice_capitulos", {})
        ordem_atual = self.estado.get("ordem_capitulos", [])
        secoes_atual = self.estado.get("secoes", {})

        # Adiciona capítulos ausentes
        added_chapters = 0
        for titulo, subt in estrutura.get("capitulos", {}).items():
            if titulo not in indice_atual:
                indice_atual[titulo] = subt
                added_chapters += 1

        # Mescla seções: apenas adiciona capítulos às seções
        added_sections = 0
        for secao, capitulos in estrutura.get("secoes", {}).items():
            if secao not in secoes_atual:
                secoes_atual[secao] = []
                added_sections += 1
            for c in capitulos:
                if c not in secoes_atual[secao]:
                    secoes_atual[secao].append(c)

        # Atualiza ordem mantendo ordem existente e inserindo novos na posição definida
        added_to_order = 0
        for titulo in estrutura.get("ordem", []):
            if titulo not in ordem_atual:
                ordem_atual.append(titulo)
                added_to_order += 1

        self.estado["indice_capitulos"] = indice_atual
        self.estado["secoes"] = secoes_atual
        self.estado["ordem_capitulos"] = ordem_atual
        # Salva estado mesclado
        self._salvar_estado()
        logger.info(f"Índice mesclado: {added_chapters} capítulo(s) adicionados, {added_sections} seção(ões) novas, {added_to_order} entrada(s) adicionadas na ordem.")

    def import_from_markdown(self, path: str, force: bool = False) -> bool:
        """
        Importa um índice a partir de um arquivo Markdown estruturado.

        Args:
            path: Caminho para o arquivo Markdown
            force: Se True, sobrescreve completamente o estado atual; se False, mescla

        Returns:
            True se importado com sucesso
        """
        try:
            if not os.path.exists(path):
                logger.warning(f"Arquivo de índice não encontrado: {path}")
                return False

            estrutura = self._load_preorganized_index(path)
            if not estrutura:
                logger.warning("Arquivo de índice vazio ou inválido")
                return False

            if force:
                logger.info("Importação forçada do índice: sobrescrevendo estado atual.")
                # Sobrescreve completamente
                self.estado["indice_capitulos"] = estrutura.get("capitulos", {})
                self.estado["secoes"] = estrutura.get("secoes", {})
                self.estado["ordem_capitulos"] = estrutura.get("ordem", [])
                return self._salvar_estado()
            else:
                logger.info("Importando índice por mesclagem (não destrutiva).")
                self._merge_preorganized_index(estrutura)
                return True
        except Exception as e:
            logger.error(f"Erro ao importar índice de Markdown: {e}")
            return False
    
    def importar_estrutura(self, estrutura: Dict[str, Any]) -> bool:
        """
        Importa uma estrutura de índice.
        
        Args:
            estrutura: Estrutura a importar
            
        Returns:
            True se importado com sucesso
        """
        try:
            create_backup()
            
            self.estado["indice_capitulos"] = estrutura.get("capitulos", {})
            self.estado["secoes"] = estrutura.get("secoes", {})
            self.estado["ordem_capitulos"] = estrutura.get("ordem", [])
            
            logger.info("Estrutura de índice importada")
            return self._salvar_estado()
            
        except Exception as e:
            logger.error(f"Erro ao importar estrutura: {e}")
            return False
    
    def gerar_relatorio(self, status_capitulos: Optional[Dict[str, Any]] = None) -> str:
        """
        Gera um relatório textual da estrutura com status dos capítulos.
        
        Args:
            status_capitulos: Dicionário com status de cada capítulo (opcional)
        
        Returns:
            String com o relatório formatado
        """
        report = ["=" * 70, "RELATÓRIO DO ÍNDICE DO LIVRO", "=" * 70, ""]
        
        # Total de capítulos
        indice = self.estado.get("indice_capitulos", {})
        status_capitulos = status_capitulos or {}
        
        # Contadores
        total_caps = len(indice)
        concluidos = sum(1 for f in status_capitulos.values() if isinstance(f, dict) and f.get("status") == "Concluído")
        pendentes = sum(1 for f in status_capitulos.values() if isinstance(f, dict) and f.get("status") == "Pendente")
        erros = sum(1 for f in status_capitulos.values() if isinstance(f, dict) and "Erro" in f.get("status", ""))
        
        report.append(f"Total de capítulos: {total_caps}")
        report.append(f"  ✅ Processados: {concluidos}")
        report.append(f"  ⏳ Pendentes: {pendentes}")
        report.append(f"  ❌ Falhados: {erros}\n")
        
        # Seções
        secoes = self.estado.get("secoes", {})
        if secoes:
            report.append("SEÇÕES E CAPÍTULOS:")
            report.append("-" * 70)
            for secao_nome, capitulos_secao in secoes.items():
                report.append(f"\n[{secao_nome}]")
                for i, titulo in enumerate(capitulos_secao, 1):
                    subtopicos = indice.get(titulo, [])
                    status_info = status_capitulos.get(titulo, {})
                    status_emoji = self._get_status_emoji(status_info)
                    report.append(f"  {i}. {status_emoji} {titulo}")
                    for subtopic in subtopicos:
                        report.append(f"     • {subtopic}")
        else:
            report.append("CAPÍTULOS (sem seção):")
            report.append("-" * 70)
            ordem = self.estado.get("ordem_capitulos", list(indice.keys()))
            for i, titulo in enumerate(ordem, 1):
                subtopicos = indice.get(titulo, [])
                status_info = status_capitulos.get(titulo, {})
                status_emoji = self._get_status_emoji(status_info)
                report.append(f"\n{i}. {status_emoji} {titulo}")
                for subtopic in subtopicos:
                    report.append(f"   • {subtopic}")
        
        report.append("\n" + "=" * 70)
        return "\n".join(report)
    
    def _get_status_emoji(self, status_info: Any) -> str:
        """
        Retorna o emoji correspondente ao status do capítulo.
        
        Args:
            status_info: Informação de status (pode ser string ou dict)
        
        Returns:
            String com emoji do status
        """
        if not status_info:
            return "⚪"  # Não processado
        
        if isinstance(status_info, dict):
            status = status_info.get("status", "")
            if status == "Concluído":
                return "✅"
            elif status == "Pendente":
                return "⏳"
            elif "Erro" in status:
                return "❌"
        elif isinstance(status_info, str):
            if status_info == "Concluído":
                return "✅"
            elif status_info == "Pendente":
                return "⏳"
            elif "Erro" in status_info:
                return "❌"
            elif status_info == "Em Processamento":
                return "⚙️"
        
        return "⚪"
    
    def gerar_relatorio_estruturado(self, status_capitulos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Retorna a estrutura do índice com status em formato estruturado (JSON-compatível).
        
        Args:
            status_capitulos: Dicionário com status de cada capítulo
        
        Returns:
            Dicionário com a estrutura e status
        """
        indice = self.estado.get("indice_capitulos", {})
        secoes = self.estado.get("secoes", {})
        ordem = self.estado.get("ordem_capitulos", list(indice.keys()))
        status_capitulos = status_capitulos or {}
        
        estrutura = {
            "resumo": {
                "total": len(indice),
                "concluidos": sum(1 for f in status_capitulos.values() if isinstance(f, dict) and f.get("status") == "Concluído"),
                "pendentes": sum(1 for f in status_capitulos.values() if isinstance(f, dict) and f.get("status") == "Pendente"),
                "falhados": sum(1 for f in status_capitulos.values() if isinstance(f, dict) and "Erro" in f.get("status", "")),
            },
            "secoes": {},
            "capitulos": {}
        }
        
        # Processa seções se existirem
        if secoes:
            for secao_nome, capitulos_secao in secoes.items():
                estrutura["secoes"][secao_nome] = []
                for titulo in capitulos_secao:
                    status_info = status_capitulos.get(titulo, {})
                    emoji = self._get_status_emoji(status_info)
                    subtopicos = indice.get(titulo, [])
                    estrutura["secoes"][secao_nome].append({
                        "titulo": titulo,
                        "status_emoji": emoji,
                        "status": status_info.get("status", "") if isinstance(status_info, dict) else status_info,
                        "subtopicos": subtopicos
                    })
        else:
            # Sem seções, usa ordem
            for titulo in ordem:
                status_info = status_capitulos.get(titulo, {})
                emoji = self._get_status_emoji(status_info)
                subtopicos = indice.get(titulo, [])
                estrutura["capitulos"][titulo] = {
                    "status_emoji": emoji,
                    "status": status_info.get("status", "") if isinstance(status_info, dict) else status_info,
                    "subtopicos": subtopicos
                }
        
        return estrutura
