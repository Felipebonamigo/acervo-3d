"""Tira a borracha dos pneus de um carro queimado (fica o aro) e assenta o carro no chão.
Usa as rodas do mapa de corte (quebravel/<carro>/<carro>_mapa.json), cuja origem fica entre os eixos.
uso: python tirar_pneu.py <entrada.glb> <mapa.json> <saida.glb>"""
import sys, json, bpy, bmesh, numpy as np
ent, mapa, sai = sys.argv[1:4]
rodas = [p for p in json.load(open(mapa))["parts"] if p.get("papel") == "wheel"]
aros = {p["name"].split("_")[1]: p for p in json.load(open(mapa))["parts"] if p.get("papel") == "rim"}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
o = next(x for x in bpy.context.scene.objects if x.type == "MESH")
co = np.array([v.co[:] for v in o.data.vertices])
z0 = co[:, 2].min()
contato = co[co[:, 2] < z0 + 0.02]
xf = np.median(contato[contato[:, 0] > 0, 0]); xr = np.median(contato[contato[:, 0] < 0, 0])
meio = (xf + xr) / 2  # origem do mapa (entre os eixos) no arquivo limpo
bm = bmesh.new(); bm.from_mesh(o.data)
apagar = set()
for r in rodas:
    pos = r["name"].split("_")[1]
    cx, _, cz = r["centro"]; cx += meio; cz += z0
    rt = r["raio"][1]; ra = aros[pos]["raio"][1] if pos in aros else rt * 0.6
    ra = min(max(ra, 0.55 * rt), 0.65 * rt)  # o aro achado pelo corte às vezes sai pequeno ou do tamanho do pneu
    y0, y1 = r["y"]; lado = r["lado"]
    for f in bm.faces:
        c = f.calc_center_median()
        if not (y0 - 0.03 <= c.y * lado <= y1 + 0.04):
            continue
        d = ((c.x - cx) ** 2 + (c.z - cz) ** 2) ** 0.5
        if ra + 0.01 < d < rt + 0.035:
            apagar.add(f)
bmesh.ops.delete(bm, geom=list(apagar), context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
zmin = min(v.co.z for v in bm.verts)
for v in bm.verts:
    v.co.z -= zmin
bm.to_mesh(o.data); bm.free()
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB")
print(f"[tirar_pneu] {len(apagar)} faces de pneu apagadas; eixos em x = {xf:.2f} / {xr:.2f}; carro baixou {zmin - z0:.3f} m")
