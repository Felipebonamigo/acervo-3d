"""Corta o monte de areia/chão que o gerador pôs debaixo de um objeto: apaga faces abaixo de --corte (m) que olham para
cima ou para baixo, depois ilhas pequenas, e põe o chão de volta em z=0. uso: python cortar_base.py <ent> <sai> <corte_m>"""
import sys, bpy, bmesh
ent, sai, corte = sys.argv[1], sys.argv[2], float(sys.argv[3])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
o = next(x for x in bpy.context.scene.objects if x.type == "MESH")
bm = bmesh.new(); bm.from_mesh(o.data)
antes = len(bm.faces)
fora = [f for f in bm.faces if f.calc_center_median().z < corte and abs(f.normal.z) > 0.35]
bmesh.ops.delete(bm, geom=fora, context="FACES")
# ilhas pequenas (borda do monte) somem
bm.faces.ensure_lookup_table()
visto, ilhas = set(), []
for f in bm.faces:
    if f.index in visto: continue
    pilha, ilha = [f], []
    visto.add(f.index)
    while pilha:
        g = pilha.pop(); ilha.append(g)
        for e in g.edges:
            for h in e.link_faces:
                if h.index not in visto: visto.add(h.index); pilha.append(h)
    ilhas.append(ilha)
lixo = [f for il in ilhas if len(il) < 0.003 * len(bm.faces) and max(g.calc_center_median().z for g in il) < corte * 1.5 for f in il]
bmesh.ops.delete(bm, geom=lixo, context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
zmin = min(v.co.z for v in bm.verts)
for v in bm.verts: v.co.z -= zmin
bm.to_mesh(o.data); bm.free()
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB")
print(f"[cortar_base] {antes} -> {len(o.data.polygons)} faces; chão novo {zmin:.2f} m acima do antigo")
