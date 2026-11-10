"""
Para-choque dianteiro e grade remodelados por script (10/11/2026, o Felipe no menu: "o carro ainda tem alguns detalhes feios e deformados";
a central: "para-choque preto torto e com relevo irregular, grade com uma faixa clara deformada"). A peça do corte do Sketchfab tem a
borda de baixo encaroçada e a grade com frisos tortos; suavizar arredondava os frisos (consertar_carro --alisar, descartado). Aqui as
duas peças são refeitas limpas, NO LUGAR e com os MESMOS nomes e materiais (bumper_front com chassi e luz_ambar, grille com chassi), para
o corte quebrável, o dano e a cadeia do Detonauto seguirem iguais:

  - para-choque: o perfil (recuo da face por altura, medido na fatia do meio) varrido ao longo da curva de planta (a frente em x por y, os
    cantos com raio --raio-canto e as pontas voltando pelos lados até a parte de trás da peça), fechado atrás e nas pontas; um friso
    (degrau de 1,5 cm) na altura em que o perfil medido muda; os piscas como lentes chanfradas de luz_ambar onde ficavam os do corte;
  - grade: moldura, fundo recuado e --frisos frisos horizontais inclinados, na caixa da grade do corte.

    python -I ferramentas/remodelar_frente.py -- <carro.glb> [--saida outro.glb] [--sem-grade] [--sem-para-choque] [--frisos 6]

Medidas: tudo vem da peça do corte (caixa, fatias); nada é fixo por carro.
"""
import math
import os
import sys

import bpy
import bmesh  # depois do bpy (no bpy do PyPI o bmesh só existe com ele carregado)
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
entrada = argv[0]
saida = argv[argv.index('--saida') + 1] if '--saida' in argv else entrada
FRISOS = int(argv[argv.index('--frisos') + 1]) if '--frisos' in argv else 6
RAIO = float(argv[argv.index('--raio-canto') + 1]) if '--raio-canto' in argv else 0.10

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=entrada)
relatorio = []


def mundo(o):
    M = o.matrix_world
    return np.array([tuple(M @ v.co) for v in o.data.vertices])


def material(o, base):
    for i, s in enumerate(o.material_slots):
        if s.material and s.material.name.split('.')[0] == base:
            return i
    m = bpy.data.materials.get(base) or bpy.data.materials.new(base)
    o.data.materials.append(m)
    return len(o.material_slots) - 1


def troca_malha(o, bm):
    """Põe a malha nova (em coordenadas de mundo) no objeto, com uma UV simples (o material do chassi é liso, sem textura)."""
    bm.transform(o.matrix_world.inverted())
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for lo in f.loops:
            lo[uv].uv = (lo.vert.co.y * 0.5, lo.vert.co.z * 0.5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = o.data
    me.clear_geometry()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    me.update()


def caixa(bm, lo, hi, mat):
    """Caixa alinhada (mundo) de lo a hi."""
    vs = [bm.verts.new((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        f = bm.faces.new([vs[i] for i in q])
        f.material_index = mat


def para_choque(o):
    P = mundo(o)
    names = [s.material.name.split('.')[0] if s.material else '' for s in o.material_slots]
    M = o.matrix_world
    pisca = np.array([tuple(M @ p.center) for p in o.data.polygons if names[p.material_index].startswith('luz_ambar')])
    z0, z1 = float(P[:, 2].min()), float(P[:, 2].max())
    W = float(min(abs(P[:, 1].min()), P[:, 1].max()))
    meio = P[np.abs(P[:, 1]) < 0.06]
    F = float(meio[:, 0].max())
    B = float(np.percentile(P[:, 0], 3))
    # o perfil medido: o recuo da frente em 10 alturas
    zs = np.linspace(z0, z1, 10)
    rec = []
    for z in zs:
        s = meio[np.abs(meio[:, 2] - z) < (z1 - z0) / 14]
        rec.append(float(s[:, 0].max()) - F if len(s) else -0.03)
    rec = np.minimum(rec, 0.0)
    # o friso: a altura em que a frente avança mais de 1 cm de uma fatia para a outra (o degrau do para-choque do corte)
    friso = None
    for i in range(1, len(zs) - 1):
        if rec[i] - rec[i - 1] > 0.008 and z0 + 0.25 * (z1 - z0) < zs[i] < z0 + 0.75 * (z1 - z0):
            friso = float(zs[i])
            break
    friso = friso if friso is not None else z0 + 0.55 * (z1 - z0)
    face_alta = (friso, z1 - 0.022)
    perfil = [(-0.066, z0), (-0.025, z0 + 0.014), (-0.017, z0 + 0.032), (-0.016, friso - 0.02), (-0.006, friso - 0.006), (0.0, friso),
              (0.0, face_alta[1]), (-0.018, z1 - 0.009), (-0.06, z1), (-(F - B), z1), (-(F - B), z0)]
    # a curva de planta: lado esquerdo (y = +W) de trás para a frente, canto, frente, canto, lado direito
    caminho = []
    n_lado, n_canto, n_frente = 4, 8, 24
    for i in range(n_lado):
        x = B + (F - RAIO - B) * i / n_lado
        caminho.append((Vector((x, W, 0)), Vector((0, 1, 0))))
    for i in range(n_canto + 1):
        a = math.pi / 2 * (1 - i / n_canto)
        c = Vector((F - RAIO, W - RAIO, 0))
        n = Vector((math.cos(a), math.sin(a), 0))
        caminho.append((c + n * RAIO, n))
    for i in range(1, n_frente):
        y = (W - RAIO) * (1 - 2 * i / n_frente)
        x = F - 0.012 * (y / (W - RAIO)) ** 2
        caminho.append((Vector((x, y, 0)), Vector((1, 0, 0))))
    for i in range(n_canto + 1):
        a = -math.pi / 2 * i / n_canto
        c = Vector((F - RAIO, -(W - RAIO), 0))
        n = Vector((math.cos(a), math.sin(a), 0))
        caminho.append((c + n * RAIO, n))
    for i in range(1, n_lado + 1):
        x = F - RAIO - (F - RAIO - B) * i / n_lado
        caminho.append((Vector((x, -W, 0)), Vector((0, -1, 0))))
    bm = bmesh.new()
    mat_ch = material(o, 'chassi')
    aneis = []
    for p, n in caminho:
        aneis.append([bm.verts.new((p.x + n.x * d, p.y + n.y * d, z)) for d, z in perfil])
    k = len(perfil)
    for a, b in zip(aneis[:-1], aneis[1:]):
        for j in range(k):
            f = bm.faces.new((a[j], a[(j + 1) % k], b[(j + 1) % k], b[j]))
            f.material_index = mat_ch
    for anel in (aneis[0], aneis[-1]):
        f = bm.faces.new(anel)
        f.material_index = mat_ch
    # os piscas: lente chanfrada de luz_ambar na face alta, onde ficavam os do corte
    n_pisca = 0
    if len(pisca):
        mat_amb = material(o, 'luz_ambar')
        for lado in (1, -1):
            c = pisca[pisca[:, 1] * lado > 0]
            if not len(c):
                continue
            yc, zc = float(c[:, 1].mean()), float(np.clip(c[:, 2].mean(), face_alta[0] + 0.03, face_alta[1] - 0.03))
            hy = max(0.04, float(c[:, 1].max() - c[:, 1].min()) / 2)
            hz = min(0.026, (face_alta[1] - face_alta[0]) / 2 - 0.006)
            xf = F - 0.012 * (yc / (W - RAIO)) ** 2
            # moldura escura 7 mm e a lente âmbar 11 mm para fora da face (a carroceria do corte tem o encaixe antigo do pisca rente à frente)
            caixa(bm, (xf - 0.012, yc - hy - 0.006, zc - hz - 0.006), (xf + 0.007, yc + hy + 0.006, zc + hz + 0.006), mat_ch)
            caixa(bm, (xf - 0.010, yc - hy, zc - hz), (xf + 0.011, yc + hy, zc + hz), mat_amb)
            n_pisca += 1
    troca_malha(o, bm)
    return 'bumper_front: refeito, %d faces, perfil de %.0f cm de altura, friso a %.0f cm do chão, frente em x=%.3f, %d pisca(s)' % (
        len(o.data.polygons), (z1 - z0) * 100, friso * 100, F, n_pisca)


def grade(o):
    P = mundo(o)
    x0, x1 = float(P[:, 0].min()), float(P[:, 0].max())
    y0, y1 = float(P[:, 1].min()), float(P[:, 1].max())
    z0, z1 = float(P[:, 2].min()), float(P[:, 2].max())
    bm = bmesh.new()
    m = material(o, 'chassi')
    borda, prof = 0.016, min(0.03, x1 - x0)
    # moldura
    caixa(bm, (x1 - prof, y0, z1 - borda), (x1, y1, z1), m)
    caixa(bm, (x1 - prof, y0, z0), (x1, y1, z0 + borda), m)
    caixa(bm, (x1 - prof, y0, z0), (x1, y0 + borda, z1), m)
    caixa(bm, (x1 - prof, y1 - borda, z0), (x1, y1, z1), m)
    # fundo recuado (o escuro entre os frisos)
    caixa(bm, (x0, y0 + borda, z0 + borda), (x0 + 0.004, y1 - borda, z1 - borda), m)
    # frisos horizontais inclinados (a lâmina desce para a frente, como a grade de carro dos anos 80)
    alto = (z1 - z0 - 2 * borda)
    passo = alto / FRISOS
    esp = min(0.009, passo * 0.45)
    for i in range(FRISOS):
        zc = z0 + borda + passo * (i + 0.5)
        vs = []
        for x, dz in ((x1 - 0.004, -esp * 0.8), (x0 + 0.006, esp * 0.8)):
            for y in (y0 + borda, y1 - borda):
                for e in (-esp / 2, esp / 2):
                    vs.append(bm.verts.new((x, y, zc + dz + e)))
        for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            bm.faces.new([vs[j] for j in q]).material_index = m
    troca_malha(o, bm)
    return 'grille: refeita, %d faces, %d frisos em %.0f x %.0f cm' % (len(o.data.polygons), FRISOS, (y1 - y0) * 100, (z1 - z0) * 100)


if '--sem-para-choque' not in argv and bpy.data.objects.get('bumper_front'):
    relatorio.append(para_choque(bpy.data.objects['bumper_front']))
if '--sem-grade' not in argv and bpy.data.objects.get('grille'):
    relatorio.append(grade(bpy.data.objects['grille']))
if relatorio:
    bpy.ops.export_scene.gltf(filepath=saida, export_format='GLB', use_selection=False, export_apply=False)
for linha in relatorio:
    print('REMODELO ' + os.path.basename(entrada) + ' ' + linha)
