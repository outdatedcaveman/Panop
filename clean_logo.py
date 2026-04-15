from rembg import remove
from PIL import Image

input_path = r'C:\Users\bruno\.gemini\antigravity\brain\b2e86185-a271-4eb9-8ed9-ae9bab958c45\panop_logo_red_1776285238593.png'
output_path = 'assets/logo.png'

inp = Image.open(input_path)
out = remove(inp)

bbox = out.getbbox()
if bbox:
    out = out.crop(bbox)
out.save(output_path)

w, h = out.size
sq_size = max(w, h)
sq_img = Image.new('RGBA', (sq_size, sq_size), (0,0,0,0))
sq_img.paste(out, ((sq_size - w) // 2, (sq_size - h) // 2))
sq_img = sq_img.resize((256, 256), Image.Resampling.LANCZOS)
sq_img.save('assets/panop.ico', format='ICO')
