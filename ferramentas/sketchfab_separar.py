"""Pré-passo do sketchfab_preparar.py para modelos que não vêm nos 3 objetos do Gol (carroceria, vidros, rodas+assoalho).

    python -I ferramentas/sketchfab_separar.py -- <scene.gltf> <saida.glb> <regras.json>

Cada objeto do arquivo vai inteiro para uma classe ("carroceria", "vidros", "rodas", "apagar") por um pedaço do nome, ou "por_ilha":
cada ilha ligada é decidida pelas caixas das regras (a primeira que a contém inteira, em coordenadas do arquivo, depois da
importação) e, se nenhuma, pela cor média da textura (escura -> "escuro", senão -> "claro"). Grava os objetos "carroceria",
"vidros" e "rodas" (UV e materiais do arquivo) e imprime quantas faces foram para cada classe. As faces de "rodas" que não são
rodas viram `chassi` (plástico preto) no sketchfab_preparar.py. Pneu que vem como triângulos soltos: o glTF separa de novo os
vértices na exportação, então a solda é o 9º argumento do sketchfab_preparar.py, não deste passo.

Regras (exemplo: veiculos/sketchfab/quebravel/jipe-capota/jipe-capota_separar.json):
    {"objetos": {"body": "carroceria", "transparent": "vidros", "tire": "rodas", "exterior": "por_ilha"},
     "escuro_max": 0.25, "escuro": "rodas", "claro": "carroceria",
     "caixas": [{"nome": "cabine", "box": [x0, x1, y0, y1, z0, z1], "classe": "apagar"}]}
"""
import bpy, bmesh, sys, json, numpy as np

a = sys.argv[sys.argv.index("--") + 1:]
ent, out, regras = a[0], a[1], json.load(open(a[2]))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
CLASSES = ("carroceria", "vidros", "rodas")


def classe_do_objeto(nome):
    for pre, cl in regras["objetos"].items():
        if pre in nome:
            return cl
    return "apagar"


def textura(o):
    for m in o.data.materials:
        if m and m.use_nodes:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and "normal" not in n.image.name.lower():
                    im = n.image
                    return np.array(im.pixels[:]).reshape(im.size[1], im.size[0], im.channels)[:, :, :3]
    return None


def ilhas(bm):
    comp = [-1] * len(bm.faces)
    k = 0
    for f0 in bm.faces:
        if comp[f0.index] >= 0:
            continue
        pilha = [f0]
        comp[f0.index] = k
        while pilha:
            f = pilha.pop()
            for e in f.edges:
                for g in e.link_faces:
                    if comp[g.index] < 0:
                        comp[g.index] = k
                        pilha.append(g)
        k += 1
    return np.array(comp), k


partes = {c: [] for c in CLASSES}
contagem = {}
for o in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
    cl = classe_do_objeto(o.name)
    M = o.matrix_world.copy()
    o.data.transform(M)
    o.parent = None
    o.matrix_world.identity()
    if cl != "por_ilha":
        if cl in partes:
            partes[cl].append(o)
        contagem[cl] = contagem.get(cl, 0) + len(o.data.polygons)
        continue
    px = textura(o)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.active
    comp, k = ilhas(bm)
    cen = np.array([f.calc_center_median()[:] for f in bm.faces])
    cor = np.zeros((len(bm.faces), 3))
    if px is not None and uv is not None:
        H, W = px.shape[:2]
        for f in bm.faces:
            u = np.mean([l[uv].uv for l in f.loops], 0)
            cor[f.index] = px[min(int((u[1] % 1) * H), H - 1), min(int((u[0] % 1) * W), W - 1)]
    destino = np.empty(len(bm.faces), object)
    for i in range(k):
        s = comp == i
        P = np.array([v.co[:] for f in np.array(bm.faces[:])[s] for v in f.verts])
        mn, mx = P.min(0), P.max(0)
        cl_i = None
        for c in regras.get("caixas", []):
            b = c["box"]
            if mn[0] >= b[0] and mx[0] <= b[1] and mn[1] >= b[2] and mx[1] <= b[3] and mn[2] >= b[4] and mx[2] <= b[5]:
                cl_i = c["classe"]
                break
        if cl_i is None:
            cl_i = regras["escuro"] if cor[s].mean(0).max() <= regras.get("escuro_max", 0.25) else regras["claro"]
        destino[s] = cl_i
    bm.free()
    for cl_i in set(destino.tolist()):
        contagem[cl_i] = contagem.get(cl_i, 0) + int((destino == cl_i).sum())
        if cl_i not in partes:
            continue
        c = o.copy()
        c.data = o.data.copy()
        bpy.context.scene.collection.objects.link(c)
        bm = bmesh.new()
        bm.from_mesh(c.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if destino[f.index] != cl_i], context="FACES")
        bm.to_mesh(c.data)
        bm.free()
        partes[cl_i].append(c)
    bpy.data.objects.remove(o)

for o in [o for o in bpy.data.objects if o.type == "MESH" and not any(o in v for v in partes.values())]:
    bpy.data.objects.remove(o)
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o)
for cl, objs in partes.items():
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = cl
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_image_format="AUTO")
print("faces por classe:", json.dumps(contagem))
