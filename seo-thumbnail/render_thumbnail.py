import sys
import json
import os
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter

def create_gradient(width, height, color1, color2, direction='diagonal'):
    base = Image.new('RGB', (width, height), color1)
    top = Image.new('RGB', (width, height), color2)
    mask = Image.new('L', (width, height))
    mask_data = []
    
    for y in range(height):
        for x in range(width):
            if direction == 'diagonal':
                ratio = (x + y) / (width + height)
            else:
                ratio = x / width
            mask_data.append(int(255 * ratio))
            
    mask.putdata(mask_data)
    base.paste(top, (0, 0), mask)
    return base

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return (0, 0, 0)

def render(spec_path, output_path):
    with open(spec_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    spec = data.get('spec', data)
    frames_info = data.get('frames_selecionados', [])
    
    # Mapeamento dos frames
    frame_paths = { f['papel_id']: f['path'] for f in frames_info }
    
    width = spec.get('canvas', {}).get('width', 1280)
    height = spec.get('canvas', {}).get('height', 720)
    
    canvas = Image.new('RGB', (width, height), (10, 10, 26))
    
    camadas = sorted(spec.get('camadas', []), key=lambda c: c.get('ordem', 0))
    
    for camada in camadas:
        tipo = camada.get('tipo')
        
        if tipo == 'gradiente':
            cores = camada.get('cores', ['#0a0a1a', '#1a0a2e'])
            c1 = hex_to_rgb(cores[0])
            c2 = hex_to_rgb(cores[1] if len(cores) > 1 else cores[0])
            grad = create_gradient(width, height, c1, c2, camada.get('direcao', 'diagonal'))
            canvas.paste(grad, (0, 0))
            
        elif tipo == 'imagem_frame':
            papel = camada.get('papel_id')
            if papel in frame_paths and os.path.exists(frame_paths[papel]):
                img = Image.open(frame_paths[papel]).convert('RGBA')
                
                # Crop logic placeholder (se especificado)
                # Aplicando os ajustes
                ajustes = camada.get('ajustes', {})
                if 'brilho' in ajustes:
                    img = ImageEnhance.Brightness(img).enhance(ajustes['brilho'])
                if 'contraste' in ajustes:
                    img = ImageEnhance.Contrast(img).enhance(ajustes['contraste'])
                if 'saturacao' in ajustes:
                    img = ImageEnhance.Color(img).enhance(ajustes['saturacao'])
                
                pos = camada.get('posicao_canvas', {})
                img = img.resize((pos.get('w', img.width), pos.get('h', img.height)), Image.Resampling.LANCZOS)
                
                # Efeito borda simples (fade)
                if camada.get('efeito_borda') == 'fade_right':
                    mask = Image.new('L', img.size, 255)
                    mask_draw = ImageDraw.Draw(mask)
                    for x in range(int(img.width * 0.8), img.width):
                        alpha = int(255 * (1 - (x - img.width * 0.8) / (img.width * 0.2)))
                        mask_draw.line([(x, 0), (x, img.height)], fill=alpha)
                    img.putalpha(mask)
                    
                canvas.paste(img, (pos.get('x', 0), pos.get('y', 0)), img)
                
        elif tipo == 'texto':
            txt = Image.new('RGBA', (width, height), (0, 0, 0, 0))
            d = ImageDraw.Draw(txt)
            texto = camada.get('conteudo', '')
            cor = hex_to_rgb(camada.get('cor_texto', '#FFFFFF'))
            pos = camada.get('posicao_canvas', {})
            x, y = pos.get('x', 0), pos.get('y', 0)
            
            # Fonte - tentando usar fonte do sistema, fallback default
            f_info = camada.get('fonte', {})
            tamanho = f_info.get('tamanho', 50)
            try:
                # Tenta Arial ou Impact
                font_name = 'impact.ttf' if f_info.get('familia', '').lower() == 'impact' else 'arialbd.ttf'
                font = ImageFont.truetype(font_name, tamanho)
            except:
                font = ImageFont.load_default()
                
            outline = camada.get('outline', {})
            if outline:
                o_cor = hex_to_rgb(outline.get('cor', '#000000'))
                o_esp = outline.get('espessura', 2)
                for dx in range(-o_esp, o_esp + 1):
                    for dy in range(-o_esp, o_esp + 1):
                        d.text((x + dx, y + dy), texto, font=font, fill=o_cor)
            
            d.text((x, y), texto, font=font, fill=cor)
            
            sombra = camada.get('sombra', {})
            if sombra:
                shadow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                sd = ImageDraw.Draw(shadow)
                sx, sy = sombra.get('x', 2), sombra.get('y', 2)
                sd.text((x + sx, y + sy), texto, font=font, fill=hex_to_rgb(sombra.get('cor', '#000000')))
                if sombra.get('blur', 0) > 0:
                    shadow = shadow.filter(ImageFilter.GaussianBlur(sombra.get('blur')))
                canvas.paste(shadow, (0, 0), shadow)
                
            canvas.paste(txt, (0, 0), txt)
            
    # Efeitos globais (ex: vignette simples)
    globais = spec.get('efeitos_globais', {})
    if 'vignette' in globais:
        # vignette simplificada
        vig = Image.new('RGBA', canvas.size, (0,0,0,0))
        vd = ImageDraw.Draw(vig)
        vd.rectangle([0,0, width, height], fill=None, outline=(0,0,0, int(255 * globais['vignette'])), width=40)
        canvas.paste(vig, (0,0), vig)
        
    canvas.save(output_path, format=spec.get('export', {}).get('formato', 'PNG'))
    print(f"SUCESSO:{output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Uso: python render_thumbnail.py <spec_json_path> <output_path>")
        sys.exit(1)
    render(sys.argv[1], sys.argv[2])
