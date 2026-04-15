from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image

drawing = svg2rlg("assets/logo.svg")
# Render with black background
renderPM.drawToFile(drawing, "assets/logo_temp.png", fmt="PNG", bg=0x000000)

img = Image.open("assets/logo_temp.png").convert("RGBA")
datas = img.getdata()
new_data = []
for item in datas:
    # If the pixel is pure black background, make it 100% transparent
    if item[0] < 10 and item[1] < 10 and item[2] < 10:
        new_data.append((0, 0, 0, 0))
    else:
        new_data.append(item)

img.putdata(new_data)

# Center it up
bbox = img.getbbox()
if bbox:
    img = img.crop(bbox)

w, h = img.size
sq_size = max(w, h)
sq_img = Image.new('RGBA', (sq_size, sq_size), (0,0,0,0))
sq_img.paste(img, ((sq_size - w) // 2, (sq_size - h) // 2))

sq_img.resize((256, 256), Image.Resampling.LANCZOS).save("assets/panop.ico", format="ICO")
