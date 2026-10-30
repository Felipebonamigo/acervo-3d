"""Carro do Sketchfab em várias malhas (por conjunto de textura, sem objetos de vidro e roda) -> os 3 objetos que o
sketchfab_preparar.py espera: carroceria, vidros, rodas+assoalho. Feito para o Besouro (30/10/2026); o Gol já vinha nos 3 objetos.

    python -I ferramentas/sketchfab_reagrupar.py -- <scene.gltf> <saida.glb> --config <reagrupar.json>

O config (unidades do arquivo, eixos depois da importação do Blender, z para cima):
    "tirar_objetos":  pais cujas malhas saem inteiras (interior de fábrica: o kit faz o nosso)
    "vidro_transmissao": [limiar, "pasta/arquivo_{conjunto}_transmission.png"]: face cuja transmissão na UV passa do limiar é vidro
    "vidro_fora": caixas [x0,x1,y0,y1,z0,z1]: ilhas de vidro que ficam na carroceria (lentes de farol: o mapa as marca como luz)
    "rodas": [[cx, cy, cz, raio, meia_largura], ...] (cy é o eixo do carro): ilha inteira dentro do cilindro vai para as rodas
    "assoalho_z": ilha com o topo abaixo disso vai para rodas+assoalho (material chassi)
    "apagar": caixas: ilha inteira dentro sai (emblema, letreiro)
    "classes": {"cor": "...{conjunto}_baseColor.png", "metal": "...{conjunto}_metallicRoughness.png", "metal_min": 0.5,
                "escuro_max": 0.16}: cada ilha da carroceria pela média da textura original: metálica -> material "cromado",
                escura -> "chassi" (borracha, plástico preto), o resto "pintura"; as lentes de "vidro_fora" saem "luz"; vidro e
                roda saem "base" (o preparo decide pela geometria). O sketchfab_preparar.py --manter-materiais e o
                carro_quebravel.py --materiais-entrada os levam até o corte (frisos, para-choques, borrachas, maçanetas).
Os objetos de saída chamam-se carroceria, vidros e rodas, nessa ordem para o sketchfab_preparar.py.
"""
import bpy, bmesh, sys, json, os, numpy as np
from mathutils import Matrix

a = sys.argv[sys.argv.index("--") + 1:]
ENT, OUT = a[0], a[1]
CFG = json.load(open(a[a.index("--config") + 1]))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ENT)
bpy.context.view_layer.update()

tirar = set(CFG.get("tirar_objetos", []))
lim, padrao = CFG["vidro_transmissao"] if "vidro_transmissao" in CFG else (None, None)
trans = {}
imgs = {}


def imagem(chave, conj):
    """textura do config (caminho com {conjunto}) como matriz float 0..1, ou None"""
    padrao_c = CFG.get("classes", {}).get(chave)
    if padrao_c is None:
        return None
    if (chave, conj) not in imgs:
        from PIL import Image
        p = padrao_c.format(conjunto=conj)
        if not os.path.isabs(p):
            p = os.path.join(os.path.dirname(os.path.abspath(ENT)), p)
        imgs[(chave, conj)] = np.array(Image.open(p).convert("RGB"), dtype=np.float32) / 255 if os.path.exists(p) else None
    return imgs[(chave, conj)]


def amostra(img, f, uv):
    h, w = img.shape[:2]
    u = np.mean([l[uv].uv for l in f.loops], 0)
    return img[int((1 - u[1] % 1) * (h - 1)), int((u[0] % 1) * (w - 1))]


def transmissao(conj):
    if padrao is None:
        return None
    if conj not in trans:
        from PIL import Image
        p = padrao.format(conjunto=conj)
        if not os.path.isabs(p):
            p = os.path.join(os.path.dirname(os.path.abspath(ENT)), p)
        trans[conj] = np.array(Image.open(p).convert("L"), dtype=np.float32) / 255 if os.path.exists(p) else None
    return trans[conj]


def dentro(mn, mx, cx):
    return all(mn[i] >= cx[2 * i] and mx[i] <= cx[2 * i + 1] for i in range(3))


def na_roda(mn, mx):
    for cx, cy, cz, r, w in CFG.get("rodas", []):
        if mn[0] < cx - w or mx[0] > cx + w:
            continue
        if mn[1] >= cy - r and mx[1] <= cy + r and mn[2] >= cz - r and mx[2] <= cz + r:
            return True
    return False


saida = {"carroceria": bmesh.new(), "vidros": bmesh.new(), "rodas": bmesh.new()}
uvs = {k: b.loops.layers.uv.new("UVMap") for k, b in saida.items()}
cont = {"carroceria": 0, "vidros": 0, "rodas": 0, "apagadas": 0, "tiradas": 0, "cromado": 0, "chassi": 0, "luz": 0}
CLASSES = ["pintura", "cromado", "chassi", "luz", "base"]   # base: vidro e roda (o preparo decide pela geometria)
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    pai = o.parent.name if o.parent else o.name
    if pai in tirar:
        cont["tiradas"] += len(o.data.polygons)
        continue
    conj = o.data.materials[0].name.rsplit("_", 1)[-1] if o.data.materials else ""
    T = transmissao(conj)
    COR, MET = imagem("cor", conj), imagem("metal", conj)
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv.active
    visto = set()
    for f0 in bm.faces:
        if f0.index in visto:
            continue
        pilha, g = [f0], []
        visto.add(f0.index)
        while pilha:
            f = pilha.pop()
            g.append(f)
            for e in f.edges:
                for f2 in e.link_faces:
                    if f2.index not in visto:
                        visto.add(f2.index)
                        pilha.append(f2)
        P = np.array([v.co for f in g for v in f.verts])
        mn, mx = P.min(0), P.max(0)
        if any(dentro(mn, mx, cx) for cx in CFG.get("apagar", [])):
            cont["apagadas"] += len(g)
            continue
        destino = "carroceria"
        lente = False
        if na_roda(mn, mx) or mx[2] < CFG.get("assoalho_z", -1e9):
            destino = "rodas"
        elif T is not None and uv is not None:
            h, w = T.shape
            val = []
            for f in g:
                u = np.mean([l[uv].uv for l in f.loops], 0)
                val.append(T[int((1 - u[1] % 1) * (h - 1)), int((u[0] % 1) * (w - 1))])
            if np.mean(val) > lim:
                if any(dentro(mn, mx, cx) for cx in CFG.get("vidro_fora", [])):
                    lente = True          # lente de farol: fica na carroceria, com o material "luz"
                else:
                    destino = "vidros"
        classe = 3 if lente else 0
        if lente:
            cont["luz"] += len(g)
        elif destino == "carroceria" and COR is not None and MET is not None and uv is not None:
            cs = np.array([amostra(COR, f, uv) for f in g])
            ms = np.array([amostra(MET, f, uv) for f in g])
            lum = float(np.median(cs @ np.array([0.2126, 0.7152, 0.0722])))
            if float(np.median(ms[:, 2])) >= CFG["classes"].get("metal_min", 0.5):
                classe = 1
            elif lum <= CFG["classes"].get("escuro_max", 0.16):
                classe = 2
            if classe:
                cont[CLASSES[classe]] += len(g)
        if destino != "carroceria":
            classe = 4
        alvo = saida[destino]
        mapa = {}
        for f in g:
            vs = []
            for v in f.verts:
                if v not in mapa:
                    mapa[v] = alvo.verts.new(v.co)
                vs.append(mapa[v])
            try:
                nf = alvo.faces.new(vs)
            except ValueError:
                continue
            nf.smooth = f.smooth
            nf.material_index = classe
            if uv is not None:
                for l, ln in zip(f.loops, nf.loops):
                    ln[uvs[destino]].uv = l[uv].uv
        cont[destino] += len(g)
    bm.free()

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
mats = [bpy.data.materials.new(n) for n in CLASSES]
for nome, b in saida.items():
    me = bpy.data.meshes.new(nome)
    b.to_mesh(me)
    b.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(nome, me)
    bpy.context.scene.collection.objects.link(ob)
print("reagrupado:", json.dumps(cont))
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB")
