import sys
from rembg import remove
from PIL import Image

input_path = sys.argv[1] if len(sys.argv) > 1 else 'assets/logo_temp.png'
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
