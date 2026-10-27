"""Reduz um GLB para ~N triângulos (Decimate por colapso, UV mantida) antes do limpar_ia, e mede quanto a forma andou.
uso: python decimar.py <entrada.glb> <saida.glb> <triangulos> [--amostras 20000] [--sem-normais]

A medida: sorteia vértices da malha original e acha o ponto mais perto na reduzida (BVH). Imprime a média, o p99 e o máximo em mm.
Régua do carro (27/10/2026): p99 < 2 mm e máximo < 8 mm; acima disso o vinco foi apagado e vale subir o alvo."""
import sys, random, bpy
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai, alvo = args[0], args[1], int(args[2])
amostras = int(args[args.index("--amostras") + 1]) if "--amostras" in args else 20000


def mundo(objs):
    vs, fs = [], []
    for o in objs:
        base = len(vs)
        vs += [o.matrix_world @ v.co for v in o.data.vertices]
        fs += [[base + i for i in p.vertices] for p in o.data.polygons]
    return vs, fs


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
orig_vs, _ = mundo(objs)
total = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
razao = min(1.0, alvo / total)
for o in objs:
    fonte = o.copy(); fonte.data = o.data.copy(); bpy.context.scene.collection.objects.link(fonte)
    m = o.modifiers.new("dec", "DECIMATE"); m.ratio = razao
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.modifier_apply(modifier="dec")
    # normais da original na reduzida: o reflexo do verniz segue a forma de antes e não a faceta nova (27/10/2026)
    if "--sem-normais" not in args:
        t = o.modifiers.new("nor", "DATA_TRANSFER"); t.object = fonte
        t.use_loop_data = True; t.data_types_loops = {"CUSTOM_NORMAL"}; t.loop_mapping = "POLYINTERP_NEAREST"
        bpy.ops.object.modifier_apply(modifier="nor")
    bpy.data.objects.remove(fonte)
depois = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
vs, fs = mundo(objs)
arvore = BVHTree.FromPolygons(vs, fs)
random.seed(7)
dist = sorted((arvore.find_nearest(v)[3] or 0.0) * 1000 for v in random.sample(orig_vs, min(amostras, len(orig_vs))))
media = sum(dist) / len(dist)
p99 = dist[int(len(dist) * 0.99)]
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
print(f"[decimar] {total} -> {depois} triângulos (razão {razao:.3f})")
print(f"[decimar] distância à original: média {media:.2f} mm, p99 {p99:.2f} mm, máximo {dist[-1]:.2f} mm "
      f"({'ok' if p99 < 2 and dist[-1] < 8 else 'ACIMA da régua: suba o alvo'})")
