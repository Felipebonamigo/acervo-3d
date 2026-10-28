"""
Pele de dentro (material MI_DNVao) das peças pintadas de um carro cortado: a chapa pintada duplicada 1,5 cm para dentro e virada, escura,
que o kit_to_detonauto.py tira nos vãos onde o kit entra. É o último passo da cadeia (depois do cirurgia_bordas.py, do vedacao_vidros.py
e do alisar_pecas.py), porque a vedação mexe na chapa em volta dos vidros e uma pele feita antes ficava por fora dela.

- a pele fica 2,5 cm longe de toda borda da chapa (fresta, vidro, lábio): junto da borda ela saía por fora como lasca escura;
- acima da cintura (colunas, quadros dos vidros, teto) não tem pele: o kit põe o forro ali, e nas colunas finas ela saía por fora;
- face que vira com o deslocamento (chapa côncava, raio menor que 1,5 cm) sai;
- as normais próprias da chapa (do alisar_pecas.py) ficam como estão; a pele ganha as normais da forma.

    python -I ferramentas/pele_de_dentro.py -- <corte>.glb <mapa>.json <saida>.glb
"""
import sys
import json
import numpy as np
import bpy
import bmesh
from mathutils import Vector, kdtree

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, mapa_p, sai = args[0], args[1], args[2]
mapa = json.load(open(mapa_p))
parts = {p["name"]: p for p in mapa["parts"]}
z_belt = min(parts["glass_door_fl"]["box"][4], parts["glass_door_fr"]["box"][4]) - 0.012
PECAS = ("body", "door_fl", "door_fr", "hood", "trunk", "fender_front_left", "fender_front_right")
ESP = 0.015

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
for nome in PECAS:
    o = bpy.data.objects.get(nome)
    if o is None:
        continue
    me = o.data
    names = [s.material.name if s.material else "" for s in o.material_slots]
    if not any(n.startswith("pintura") for n in names):
        continue
    if "MI_DNVao" not in names:
        me.materials.append(bpy.data.materials.get("MI_DNVao") or bpy.data.materials.new("MI_DNVao"))
        names = [s.material.name if s.material else "" for s in o.material_slots]
    mi_pele = names.index("MI_DNVao")
    bm = bmesh.new()
    bm.from_mesh(me)
    M = o.matrix_world
    pint = [f for f in bm.faces if names[f.material_index].startswith("pintura")]
    # faces antigas de pele saem (a cadeia pode rodar de novo)
    velhas = [f for f in bm.faces if names[f.material_index] == "MI_DNVao"]
    n_old = len(me.loops)
    cn = np.empty(n_old * 3)
    me.corner_normals.foreach_get("vector", cn)
    cn = cn.reshape(-1, 3)
    keep_loops = np.ones(n_old, bool)
    for f in velhas:
        for l in f.loops:
            keep_loops[l.index] = False
    bmesh.ops.delete(bm, geom=velhas, context="FACES")
    pint = [f for f in pint if f.is_valid]
    borda_v = [e.verts[0].co.copy() for e in bm.edges if len(e.link_faces) == 1 or
               any(not names[f.material_index].startswith("pintura") for f in e.link_faces)]
    kd = kdtree.KDTree(len(borda_v))
    for i, co in enumerate(borda_v):
        kd.insert(co, i)
    kd.balance()
    longe = [f for f in pint if (not borda_v or all(kd.find(v.co)[2] > 0.025 for v in f.verts))
             and (M @ f.calc_center_median()).z < z_belt + 0.02]
    r = bmesh.ops.duplicate(bm, geom=longe)
    dup = [x for x in r["geom"] if isinstance(x, bmesh.types.BMFace)]
    n_orig = {f: f.normal.copy() for f in dup}
    vd = set(v for f in dup for v in f.verts)
    for v in vd:
        nn = Vector()
        for f in v.link_faces:
            nn += f.normal
        if nn.length > 1e-9:
            v.co -= nn.normalized() * ESP
    viradas = []
    for f in dup:
        f.normal_update()
        if f.normal.dot(n_orig[f]) < 0.3:
            viradas.append(f)
    bmesh.ops.delete(bm, geom=viradas, context="FACES")
    dup = [f for f in dup if f.is_valid]
    for f in dup:
        f.material_index = mi_pele
        f.smooth = True
    bmesh.ops.reverse_faces(bm, faces=dup)
    # normais próprias: as da chapa ficam (as faces que sobram vêm primeiro, na ordem antiga); a pele, no fim, leva as da forma
    bm.to_mesh(me)
    me.update()
    cn_new = np.empty(len(me.loops) * 3)
    me.corner_normals.foreach_get("vector", cn_new)
    cn_new = cn_new.reshape(-1, 3)
    n_keep = len(me.loops) - sum(len(f.verts) for f in dup)
    if n_keep == int(keep_loops.sum()):
        cn_new[:n_keep] = cn[keep_loops]
    me.normals_split_custom_set(cn_new.tolist())
    me.update()
    bm.free()
    print("[pele_de_dentro] %-18s %5d faces de pele (%d perto da borda ou acima da cintura fora, %d viradas fora)" % (
        nome, len(dup), len(pint) - len(longe), len(viradas)))

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
