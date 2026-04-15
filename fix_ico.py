from PIL import Image

img = Image.open("assets/logo_temp.png").convert("RGBA")
datas = img.getdata()
new_data = []
for item in datas:
    if item[0] < 10 and item[1] < 10 and item[2] < 10:
        new_data.append((0, 0, 0, 0))
    else:
        new_data.append(item)

img.putdata(new_data)
bbox = img.getbbox()
if bbox:
    img = img.crop(bbox)

w, h = img.size
sq_size = max(w, h)
sq_img = Image.new('RGBA', (sq_size, sq_size), (0,0,0,0))
sq_img.paste(img, ((sq_size - w) // 2, (sq_size - h) // 2))

# Multi-layered Icon sizes are mandatory for Windows to display it correctly
icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
sq_img.save("assets/panop.ico", format="ICO", sizes=icon_sizes)
