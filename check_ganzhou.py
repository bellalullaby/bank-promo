"""快速提取赣州银行LOGO颜色"""
import sys, io as _io
sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from PIL import Image
from collections import Counter

img = Image.open(r'D:\2-营销活动\各银行LOGO文件\赣州\赣州银行LOGO.jpg')
img = img.convert('RGBA').resize((80, 80))
pixels = list(img.getdata())

colored = []
for r,g,b,a in pixels:
    if a < 128: continue
    if all(c>240 for c in (r,g,b)): continue
    if all(c<25 for c in (r,g,b)): continue
    if max(r,g,b)-min(r,g,b) < 15: continue
    colored.append((r,g,b))

groups = []
for c in colored:
    found = False
    for g in groups:
        if all(abs(c[i]-g['avg'][i])<40 for i in range(3)):
            g['sum'] = tuple(g['sum'][j]+c[j] for j in range(3))
            g['count'] += 1
            g['avg'] = tuple(int(g['sum'][j]/g['count']) for j in range(3))
            found = True
            break
    if not found:
        groups.append({'sum':c, 'count':1, 'avg':c})

groups.sort(key=lambda g: g['count'], reverse=True)
for i, g in enumerate(groups[:3]):
    r, gg, b = g['avg']
    hex_c = '#{:02X}{:02X}{:02X}'.format(r, gg, b)
    if r > b*1.2 and r > gg*1.3: label = '红色'
    elif b > r*1.1 and b > gg*1.2: label = '蓝色'
    elif gg > r*1.1 and gg > b*1.1: label = '绿色'
    elif r > gg*1.2 and r > b*1.2: label = '橙色'
    else: label = '深色'
    light_r = min(255, r + int((255-r)*0.85))
    light_g = min(255, gg + int((255-gg)*0.85))
    light_b = min(255, b + int((255-b)*0.85))
    light = '#{:02X}{:02X}{:02X}'.format(light_r, light_g, light_b)
    print(f'#{i+1}: {hex_c} {label} | 浅色: {light} | 像素: {g["count"]}')
