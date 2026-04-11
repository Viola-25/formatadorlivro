import os
import io
import re
import qrcode
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX
from docx.oxml.ns import nsdecls
from docx.oxml import parse_xml

def set_cell_background(cell, color_hex: str):
    """
    Define a cor de fundo de uma célula de tabela no python-docx manipulando o XML subjacente.
    """
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    tcPr.append(tcBorders)

def generate_formatted_docx(ai_text: str, chapter_name: str) -> str:
    """
    Lê o texto gerado pela IA linha por linha, aplica estilos e tags, 
    gera QR Codes para os links, e salva o documento Word final formatado.
    """
    doc = Document()
    
    # Configura o estilo Normal (Fonte Arial, Tamanho 11) para o documento padrão
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(11)
    
    lines = ai_text.split('\n')
    
    current_mode = "DEFAULT"
    current_table_cell = None
    
    for line in lines:
        stripped_line = line.strip()
        
        # Tratamento para linhas vazias
        if not stripped_line:
            if current_mode == "DEFAULT":
                doc.add_paragraph("")
            # Sai de blocos de formatação única (exceto resumo e links) se houver quebra de parágrafo
            if current_mode in ["BOX_RECOMENDACAO", "BOX_ATENCAO", "SUGESTAO_EDICAO"]:
                current_mode = "DEFAULT"
            continue
            
        # Identificação de Tags para mudança de estado e aplicação de estilo
        if "[BOX_RESUMO]" in stripped_line:
            current_mode = "BOX_RESUMO"
            table = doc.add_table(rows=1, cols=1)
            current_table_cell = table.cell(0, 0)
            set_cell_background(current_table_cell, "D3D3D3") # Cinza Claro
            
            clean_text = stripped_line.replace("[BOX_RESUMO]", "").strip()
            if clean_text:
                current_table_cell.add_paragraph(clean_text)
            continue
            
        elif "[BOX_RECOMENDACAO]" in stripped_line:
            current_mode = "BOX_RECOMENDACAO"
            clean_text = stripped_line.replace("[BOX_RECOMENDACAO]", "").strip()
            if clean_text:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.5)
                run = p.add_run(clean_text)
                run.bold = True
                run.italic = True
            continue
            
        elif "[BOX_ATENCAO]" in stripped_line:
            current_mode = "BOX_ATENCAO"
            clean_text = stripped_line.replace("[BOX_ATENCAO]", "").strip()
            if clean_text:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.5)
                run = p.add_run(clean_text)
                run.bold = True
                run.italic = True
                # Opcional: Adiciona uma cor para maior destaque (ex: vermelho escuro)
                run.font.color.rgb = RGBColor(180, 0, 0) 
            continue
            
        elif "[SUGESTAO_EDICAO]" in stripped_line:
            current_mode = "SUGESTAO_EDICAO"
            clean_text = stripped_line.replace("[SUGESTAO_EDICAO]", "").strip()
            if clean_text:
                p = doc.add_paragraph()
                run = p.add_run(f"[SUGESTÃO DE EDIÇÃO]: {clean_text}")
                run.font.color.rgb = RGBColor(255, 0, 0) # Texto em vermelho
                run.font.highlight_color = WD_COLOR_INDEX.YELLOW # Fundo amarelo
            continue
            
        elif "[LINKS_ATUALIZACAO]" in stripped_line:
            current_mode = "LINKS_ATUALIZACAO"
            p = doc.add_paragraph()
            run = p.add_run("Links para Atualização:")
            run.bold = True
            
            clean_text = stripped_line.replace("[LINKS_ATUALIZACAO]", "").strip()
            if not clean_text:
                continue
            stripped_line = clean_text # Permite processar URLs que estejam na mesma linha da tag
            
        # Processamento contínuo das linhas baseado no estado atual
        if current_mode == "BOX_RESUMO":
            if current_table_cell:
                current_table_cell.add_paragraph(stripped_line)
                
        elif current_mode in ["BOX_RECOMENDACAO", "BOX_ATENCAO"]:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.5)
            run = p.add_run(stripped_line)
            run.bold = True
            run.italic = True
            if current_mode == "BOX_ATENCAO":
                run.font.color.rgb = RGBColor(180, 0, 0)
                
        elif current_mode == "SUGESTAO_EDICAO":
            p = doc.add_paragraph()
            run = p.add_run(stripped_line)
            run.font.color.rgb = RGBColor(255, 0, 0)
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            
        elif current_mode == "LINKS_ATUALIZACAO":
            # Extração de URLs via Regex
            urls = re.findall(r'(https?://[^\s]+)', stripped_line)
            
            if urls:
                for url in urls:
                    # Gera o QR Code em memória usando BytesIO
                    qr = qrcode.QRCode(box_size=4, border=4)
                    qr.add_data(url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)
                    
                    # Insere a imagem centralizada no documento
                    p_img = doc.add_paragraph()
                    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run_img = p_img.add_run()
                    run_img.add_picture(img_byte_arr, width=Inches(1.2))
                    
                    # Insere a legenda curta (a própria URL em itálico ou descrição caso haja texto)
                    texto_descritivo = stripped_line.replace(url, "").strip(" -*")
                    legenda = f"{texto_descritivo}\n{url}" if texto_descritivo else url
                    
                    p_legenda = doc.add_paragraph(legenda)
                    p_legenda.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p_legenda.runs[0].font.size = Pt(9)
                    p_legenda.runs[0].font.italic = True
            else:
                # Linhas descritivas de links sem URLs identificadas
                doc.add_paragraph(stripped_line)
                
        else:
            # Modo DEFAULT (Texto padrão)
            doc.add_paragraph(stripped_line)

    # Sanitização do nome do arquivo (remove extensão se presente e caracteres inválidos)
    base_name = os.path.splitext(chapter_name)[0] if '.' in chapter_name else chapter_name
    safe_chapter_name = re.sub(r'[\\/*?:"<>|]', "", base_name)
    safe_chapter_name = safe_chapter_name.replace(" ", "_")
    
    output_filename = f"Capitulo_{safe_chapter_name}_Revisado.docx"
    doc.save(output_filename)
    
    return output_filename
