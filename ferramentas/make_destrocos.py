"""
Destroços de batida do Detonauto (o Felipe, 06/11/2026: "os destroços voam como cubos pretos"): pedaços irregulares por material, para as
lascas e os cacos do Niagara (NS_DNPlasticChips, NS_DNGlassShards) e para os cacos e o farelo de vidro em C++ (ADNGlassShards), no lugar
do cubo da engine. Geometria feita aqui, CC0 do estúdio, sem IA.

    python -I Tools/Blender/make_destrocos.py -- <pasta de saída> [prévia.png]

Saída: um FBX por peça, SM_DNDestroco_<Tipo>_<A|B|C>.fbx, com a maior medida de 10 cm (o Niagara escala), origem no centro de massa,
normais suaves só onde a peça curva. Tipos:
  - Plastico: casca curva de para-choque com a borda serrilhada, 3 mm de espessura;
  - Metal: tira de chapa amassada e torta, borda rasgada, 1 mm;
  - Vidro: caco plano de 5 a 7 lados, 4 mm (vidro de para-brisa laminado e temperado).
A semente é fixa: rodar de novo dá as mesmas peças.
"""
import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SAIDA = args[0]
PREVIA = args[1] if len(args) > 1 else ''
os.makedirs(SAIDA, exist_ok=True)
MAIOR_M = 0.10


def limpa():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def jagged_outline(n, rx, ry, rnd, rough):
    """Contorno fechado irregular: n pontos numa elipse com o raio sorteado."""
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rnd.uniform(-0.35, 0.35) * math.pi / n
        r = 1.0 - rough * rnd.random()
        pts.append((math.cos(a) * rx * r, math.sin(a) * ry * r))
    return pts


def poly_mesh(name, pts, thick, bend=0.0, crumple=0.0, rnd=None, subdiv=0):
    bm = bmesh.new()
    verts = [bm.verts.new((x, y, 0.0)) for x, y in pts]
    face = bm.faces.new(verts)
    if subdiv:
        bmesh.ops.triangulate(bm, faces=[face])
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=subdiv, use_grid_fill=True)
    for v in bm.verts:
        x, y, _ = v.co
        z = bend * (x * x) * 8.0  # curva (para-choque) ou dobra (chapa): 1 a 2 cm de flecha numa peça de 10 cm
        if crumple and rnd:
            z += rnd.uniform(-crumple, crumple)
        v.co.z = z
    ext = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
    moved = [e for e in ext['geom'] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=moved, vec=(0.0, 0.0, -thick))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def normaliza(ob):
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_MASS', center='BOUNDS')
    ob.location = (0, 0, 0)
    d = max(ob.dimensions)
    s = MAIOR_M / d if d > 0 else 1.0
    ob.scale = (s, s, s)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    ob.select_set(False)


def material(ob, nome, cor):
    m = bpy.data.materials.get(nome) or bpy.data.materials.new(nome)
    m.diffuse_color = cor
    ob.data.materials.append(m)


def plastico(letra, seed):
    rnd = random.Random(seed)
    pts = jagged_outline(rnd.randint(9, 13), 0.05, 0.03, rnd, 0.45)
    ob = poly_mesh(f'SM_DNDestroco_Plastico_{letra}', pts, 0.003, bend=rnd.uniform(0.6, 1.2), rnd=rnd, subdiv=2)
    material(ob, 'M_Destroco_Plastico', (0.05, 0.05, 0.055, 1))
    return ob


def metal(letra, seed):
    rnd = random.Random(seed)
    pts = jagged_outline(rnd.randint(10, 14), 0.06, 0.018, rnd, 0.35)
    ob = poly_mesh(f'SM_DNDestroco_Metal_{letra}', pts, 0.001, bend=rnd.uniform(-1.5, 1.5), crumple=0.006, rnd=rnd, subdiv=3)
    material(ob, 'M_Destroco_Metal', (0.45, 0.46, 0.48, 1))
    return ob


def vidro(letra, seed):
    rnd = random.Random(seed)
    pts = jagged_outline(rnd.randint(5, 7), 0.04, 0.03, rnd, 0.55)
    ob = poly_mesh(f'SM_DNDestroco_Vidro_{letra}', pts, 0.004, rnd=rnd)
    material(ob, 'M_Destroco_Vidro', (0.6, 0.75, 0.8, 1))
    return ob


limpa()
pecas = []
for i, letra in enumerate('ABC'):
    pecas += [plastico(letra, 100 + i), metal(letra, 200 + i), vidro(letra, 300 + i)]
for ob in pecas:
    normaliza(ob)
    for o in bpy.context.scene.objects:
        o.select_set(o == ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.export_scene.fbx(filepath=os.path.join(SAIDA, ob.name + '.fbx'), use_selection=True, apply_unit_scale=True,
                             apply_scale_options='FBX_SCALE_UNITS', mesh_smooth_type='FACE', add_leaf_bones=False, bake_anim=False)
    tris = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    print(f'{ob.name}: {tris} triângulos, {ob.dimensions.x * 100:.1f} x {ob.dimensions.y * 100:.1f} x {ob.dimensions.z * 100:.1f} cm')

if PREVIA:
    # prévia: as nove peças numa grade, vistas de cima e de lado, no Workbench (rápido, sem GPU)
    for k, ob in enumerate(pecas):
        ob.location = ((k % 3) * 0.14, (k // 3) * 0.14, 0.0)
        ob.rotation_euler = (math.radians(35), math.radians(20), math.radians(15 * k))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (0.14, -0.38, 0.30)
    cam.rotation_euler = (math.radians(55), 0, 0)
    bpy.context.scene.camera = cam
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.color_type = 'MATERIAL'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.show_cavity = True
    sc.render.resolution_x, sc.render.resolution_y = 900, 700
    sc.render.filepath = PREVIA
    bpy.ops.render.render(write_still=True)
    print('prévia', PREVIA)
