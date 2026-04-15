from PIL import Image

img = Image.open(r'C:\Users\bruno\.gemini\antigravity\brain\b2e86185-a271-4eb9-8ed9-ae9bab958c45\panop_logo_red_1776285238593.png').convert("RGBA")
datas = img.getdata()
new_data = []
for item in datas:
    m = max(item[0], item[1], item[2])
    if m < 20: 
        a = 0
    elif m > 80:
        a = 255
    else:
        a = int((m - 20) * (255.0 / 60.0))
        
    if a > 0 and a < 255 and m > 0:
        new_data.append((min(255, int(item[0]*255/m)), min(255, int(item[1]*255/m)), min(255, int(item[2]*255/m)), a))
    else:
        new_data.append((item[0], item[1], item[2], a))

img.putdata(new_data)
bbox = img.getbbox()
if bbox:
    img = img.crop(bbox)

img.save('assets/logo.png')

w, h = img.size
sq_size = max(w, h)
sq_img = Image.new('RGBA', (sq_size, sq_size), (0,0,0,0))
sq_img.paste(img, ((sq_size - w) // 2, (sq_size - h) // 2))
sq_img = sq_img.resize((256, 256), Image.Resampling.LANCZOS)
sq_img.save('assets/panop.ico', format='ICO')
