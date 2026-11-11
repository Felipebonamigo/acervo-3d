"""
Sobrepõe o perfil do carro novo ao do modelo-régua, de lado, de frente e de trás, e mede a diferença. A régua continua só régua:
daqui saem contornos e centímetros, nenhuma geometria.

    blender-nuvem.sh ferramentas/lataria_molde/sobrepor.py -- <regua.glb> <novo.glb> <saida.jpg> [--json medidas.json]

Na imagem: a régua em cinza cheio (vidro em azul claro, luzes em amarelo), o novo em traço vermelho (vidro em azul, luzes em laranja).
"""
import json, sys
import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

argv = sys.argv[sys.argv.index('--') + 1:]
REGUA, NOVO, SAIDA = argv[:3]
JS = argv[argv.index('--json') + 1] if '--json' in argv else None
PASSO = 0.006
FORA = ('wheel_', 'hubcap_', 'mirror', 'plate')


def classe(nome, mat):
    if nome.startswith('glass') and mat.startswith('vidro'):
        return 5 if nome.startswith('glass_door_f') else (6 if nome.startswith('glass_door_r') else 2)
    if nome.startswith(('headlight', 'taillight')):
        return 3
    if nome.startswith('bumper'):
        return 4
    return 1


def mapas(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    for o in list(bpy.data.objects):
        n = o.name.split('.')[0]
        if o.type != 'MESH' or n.startswith(FORA) or n.endswith(('_LOD1', '_LOD2')) or '__' in n:
            bpy.data.objects.remove(o)
    dg = bpy.context.evaluated_depsgraph_get()
    cena = bpy.context.scene
    out = {}
    vistas = {'lado': ((-2.1, 2.1), (0.0, 1.5), lambda a, b: ((a, 3.0, b), (0, -1, 0))),
              'frente': ((-0.95, 0.95), (0.0, 1.5), lambda a, b: ((4.0, a, b), (-1, 0, 0))),
              'tras': ((-0.95, 0.95), (0.0, 1.5), lambda a, b: ((-4.0, a, b), (1, 0, 0)))}
    for v, ((a0, a1), (b0, b1), raio) in vistas.items():
        na, nb = int((a1 - a0) / PASSO), int((b1 - b0) / PASSO)
        m = np.zeros((nb, na), dtype=np.uint8)
        for j in range(nb):
            for i in range(na):
                o, d = raio(a0 + (i + 0.5) * PASSO, b0 + (j + 0.5) * PASSO)
                ok, loc, n, idx, ob, _ = cena.ray_cast(dg, Vector(o), Vector(d))
                if ok:
                    mt = ob.data.materials[ob.data.polygons[idx].material_index].name if ob.data.materials else ''
                    m[j, i] = classe(ob.name.split('.')[0], mt)
        out[v] = (m, a0, b0)
    return out


R, Nv = mapas(REGUA), mapas(NOVO)


def caixa(m, a0, b0, cls, lado=None):
    ys, xs = np.nonzero(m == cls)
    if lado is not None:
        sel = (a0 + xs * PASSO > 0) if lado > 0 else (a0 + xs * PASSO < 0)
        ys, xs = ys[sel], xs[sel]
    if len(xs) == 0:
        return None
    return [round(float(a0 + xs.min() * PASSO) * 100, 1), round(float(a0 + (xs.max() + 1) * PASSO) * 100, 1),
            round(float(b0 + ys.min() * PASSO) * 100, 1), round(float(b0 + (ys.max() + 1) * PASSO) * 100, 1)]


def perfil(m, a0, b0):
    cheio = m > 0
    topo = np.where(cheio.any(0), b0 + (cheio.shape[0] - np.argmax(cheio[::-1], 0)) * PASSO, np.nan)
    return topo


med = {}
for nome, M in (('regua', R), ('novo', Nv)):
    m, a0, b0 = M['lado']
    t = perfil(m, a0, b0)
    xs = a0 + (np.arange(len(t)) + 0.5) * PASSO
    d = {}
    ok = ~np.isnan(t)
    d['x_frente'] = round(float(xs[ok].max()) * 100, 1)
    d['x_tras'] = round(float(xs[ok].min()) * 100, 1)
    d['altura'] = round(float(np.nanmax(t)) * 100, 1)
    for x in (1.7, 1.4, 1.0, 0.8, 0.6, 0.4, 0.2, -0.4, -1.0, -1.2, -1.4, -1.6, -1.75):
        k = int((x - a0) / PASSO)
        d['topo_x%+d' % int(x * 100)] = None if np.isnan(t[k]) else round(float(t[k]) * 100, 1)
    # corpo sem para-choque (classe 1, 2 e 3): frente e traseira da lataria
    corpo = np.isin(m, (1, 2, 3, 5, 6))
    cx = xs[corpo.any(0)]
    d['x_frente_lataria'] = round(float(cx.max()) * 100, 1)
    d['x_tras_lataria'] = round(float(cx.min()) * 100, 1)
    # vidros laterais, pelo nome da peça (a régua separa o quebra-vento; aqui conta o vão inteiro da porta)
    d['vidro_porta'] = caixa(m, a0, b0, 5)
    d['vidro_tras_lateral'] = caixa(m, a0, b0, 6)
    for v, cls, nm, ld in (('frente', 3, 'farol_esq', -1), ('tras', 3, 'lanterna_esq', 1), ('frente', 2, 'para_brisa', None), ('tras', 2, 'vidro_traseiro', None),
                           ('frente', 4, 'para_choque_frente', None), ('tras', 4, 'para_choque_tras', None)):
        mm, aa, bb = M[v]
        d[nm] = caixa(mm, aa, bb, cls, ld)
    mm, aa, bb = M['frente']
    larg = (mm > 0).any(0)
    ys = aa + (np.nonzero(larg)[0] + 0.5) * PASSO
    d['meia_largura'] = round(float(np.abs(ys).max()) * 100, 1)
    med[nome] = d

# ------------------------------------------------------------------------------------------------ a imagem
ESC = 3
COR_R = {1: (205, 205, 208), 2: (190, 220, 235), 5: (190, 220, 235), 6: (190, 220, 235), 3: (240, 225, 150), 4: (165, 165, 170)}
COR_N = {1: (200, 20, 20), 2: (20, 90, 200), 5: (20, 90, 200), 6: (20, 90, 200), 3: (230, 120, 0), 4: (90, 20, 20)}


def painel(v):
    mr, a0, b0 = R[v]
    mn = Nv[v][0]
    h, w = mr.shape
    im = np.full((h, w, 3), 250, dtype=np.uint8)
    for c, cor in COR_R.items():
        im[mr == c] = cor
    borda = np.zeros((h, w), dtype=np.uint8)
    for c in COR_N:
        b = (mn == c)
        e = b & ~(np.roll(b, 1, 0) & np.roll(b, -1, 0) & np.roll(b, 1, 1) & np.roll(b, -1, 1))
        borda[e] = c
    img = Image.fromarray(im[::-1]).resize((w * ESC, h * ESC), Image.NEAREST)
    bi = np.kron(borda[::-1], np.ones((ESC, ESC), dtype=np.uint8))
    arr = np.array(img)
    for c, cor in COR_N.items():
        arr[bi == c] = cor
    return Image.fromarray(arr)


pl, pf, pt = painel('lado'), painel('frente'), painel('tras')
W = pl.size[0]
H = pl.size[1] + pf.size[1] + 70
folha = Image.new('RGB', (W, H), (250, 250, 250))
folha.paste(pl, (0, 40))
folha.paste(pf, (0, 60 + pl.size[1]))
folha.paste(pt, (W - pt.size[0], 60 + pl.size[1]))
d = ImageDraw.Draw(folha)
try:
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 22)
except Exception:
    f = ImageFont.load_default()
d.text((10, 8), 'Perfil sobreposto: régua em cinza cheio (vidro azul claro, luzes amarelo); carro novo em traço vermelho (vidro azul, luzes laranja)', font=f, fill=(20, 20, 20))
d.text((10, 44 + pl.size[1]), 'De frente', font=f, fill=(20, 20, 20))
d.text((W - pt.size[0] + 10, 44 + pl.size[1]), 'De trás', font=f, fill=(20, 20, 20))
folha.save(SAIDA, quality=90)
dif = {}
for k, v in med['regua'].items():
    n = med['novo'].get(k)
    if isinstance(v, (int, float)) and isinstance(n, (int, float)):
        dif[k] = round(n - v, 1)
    elif isinstance(v, list) and isinstance(n, list):
        dif[k] = [round(b - a, 1) for a, b in zip(v, n)]
med['diferenca_cm'] = dif
if JS:
    json.dump(med, open(JS, 'w'), ensure_ascii=False, indent=1)
for k in med['regua']:
    print('%-22s regua %-28s novo %-28s dif %s' % (k, med['regua'][k], med['novo'].get(k), dif.get(k)))
