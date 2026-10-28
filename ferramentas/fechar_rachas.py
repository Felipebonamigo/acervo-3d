"""
Fecha as rachas finas da chapa do carro cortado (pedido do Felipe de 27/10/2026: "faça tudo até ficar perfeito").

A malha do Meshy tem costuras internas não soldadas: duas fileiras de vértices a menos de 2 mm uma da outra, com a parede da
espessura descendo entre elas. De perto aparecem como riscos pretos no meio do capô, do teto e das portas (o raio passa pela fresta e
vê o escuro de baixo). No capô do Cuiabano v2 eram ~12 m de rachas para 4,5 m de contorno.

Em cada peça, os vértices da borda de cada material (onde a tinta, ou o lado de baixo, acaba) que têm outro vértice de borda a menos de
--dist mm são soldados; as faces que ficam sem área saem. O contorno das peças não muda: lá os vizinhos de borda estão a ~1 cm.
As normais próprias (custom normals) ficam como estavam.

    python -I ferramentas/fechar_rachas.py -- <corte>.glb <saida>.glb [--dist 2]
"""
import sys
import bpy
import bmesh

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]
DIST = (float(args[args.index("--dist") + 1]) if "--dist" in args else 2.0) / 1000

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
relatorio = []
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    names = [s.material.name if s.material else "" for s in o.material_slots]
    if not any(n.startswith("pintura") for n in names):
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)      # as cópias das costuras da textura (mesma posição)
    nv1 = len(bm.verts)
    borda = set()
    for e in bm.edges:
        mats = [f.material_index for f in e.link_faces]
        for m in set(mats):
            if mats.count(m) == 1:
                borda.update(e.verts)
    antes = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    bmesh.ops.remove_doubles(bm, verts=list(borda), dist=DIST)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    soltos = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    depois = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    bm.to_mesh(o.data)
    o.data.update()
    bm.free()
    relatorio.append("%s: vértices %d -> %d, arestas de borda %d -> %d" % (o.name, nv1, len(o.data.vertices), antes, depois))

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[fechar_rachas]", linha)
