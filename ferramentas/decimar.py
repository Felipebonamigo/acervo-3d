"""Reduz um GLB para ~N triângulos (Decimate por colapso, UV mantida) antes do limpar_ia.
uso: python decimar.py <entrada.glb> <saida.glb> <triangulos>"""
import sys, bpy
ent, sai, alvo = sys.argv[1], sys.argv[2], int(sys.argv[3])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
total = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
razao = min(1.0, alvo / total)
for o in objs:
    m = o.modifiers.new("dec", "DECIMATE"); m.ratio = razao
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.modifier_apply(modifier="dec")
depois = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
print(f"[decimar] {total} -> {depois} triângulos (razão {razao:.3f})")
