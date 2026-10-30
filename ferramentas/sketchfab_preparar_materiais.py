"""
Carro do Sketchfab com vários objetos e materiais texturizados (o Chevette sl 76 do Laerte.Hubaleque, 30/10/2026) -> um objeto só no
nosso referencial (frente +X, esquerda +Y, chão em z = 0, origem entre os eixos), com os materiais do acervo por face: o material de
cada objeto do arquivo vai para um material nosso, direto ou pela cor da textura na face (a lataria azul vira `pintura` e o cinza do
vão, `chassi`; as peças externas viram `cromado`, `chassi`, `luz_vermelha`, `luz_ambar`, `luz_branca`...). O `sketchfab_preparar.py`
é o do Gol Quadrado (3 objetos sem textura útil, janelas achadas por regra); este não muda nada dele.

    python -I ferramentas/sketchfab_preparar_materiais.py -- <scene.gltf> <saida.glb> <regras.json>

O regras.json (um por carro, ao lado do mapa do corte) diz:
  "comprimento": metros reais (escala uniforme),
  "frente": "-y" | "+y" | "-x" | "+x" (onde está a frente no arquivo),
  "fora": padrões (regex) de nomes de objeto que saem (interior, emblemas, freios: o kit do acervo põe os dele),
  "objetos": [{"nome": regex do objeto, "material": nome nosso | "cor"}], o primeiro que casa vale,
  "cores": regras por cor para "material": "cor", na ordem: {"material", "h": [min, max] graus, "s": [min, max], "v": [min, max],
           "metal": [min, max], "objeto": regex opcional}; a última sem limites é o padrão,
  "angulo": graus das arestas vivas nas normais (padrão 30), "aresta": aresta máxima do adensamento em metros (0 = não adensa).
Grava <saida>_medidas.json (eixos, rodas, caixa, faces por material) e a prévia das classes de cor (<saida>_classes.png) se pedido
com CLASSES=1.
"""
import bpy, bmesh, sys, os, re, json, math, colorsys
import numpy as np
from mathutils import Vector, Matrix

a = sys.argv[sys.argv.index("--") + 1:]
ENT, OUT, REG = a[0], a[1], json.load(open(a[2], encoding="utf-8"))
COMP = float(REG["comprimento"])
ANG = float(REG.get("angulo", 30.0))
ARESTA = float(REG.get("aresta", 0.0))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ENT)
fora = [re.compile(p) for p in REG.get("fora", [])]
objs = []
for o in list(bpy.data.objects):
    if o.type != "MESH":
        continue
    if any(p.search(o.name) for p in fora):
        bpy.data.objects.remove(o)
        continue
    objs.append(o)
print("objetos que ficam:", len(objs))


def imagem_de(mat, tipo):
    """A imagem ligada à cor (tipo='cor') ou ao metal-rugosidade (tipo='mr') do material do glTF, como array float (H, W, C)."""
    if mat is None or not mat.use_nodes:
        return None
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return None
    entrada = bsdf.inputs["Base Color"] if tipo == "cor" else bsdf.inputs["Metallic"]
    pilha = [l.from_node for l in entrada.links]
    while pilha:
        n = pilha.pop()
        if n.type == "TEX_IMAGE" and n.image is not None:
            im = n.image
            w, h = im.size
            px = np.empty(w * h * 4, np.float32)
            im.pixels.foreach_get(px)
            return px.reshape(h, w, 4)
        for i in n.inputs:
            pilha.extend(l.from_node for l in i.links)
    return None


cache = {}


def amostra(img, uv):
    h, w = img.shape[:2]
    x = np.clip((uv[:, 0] % 1.0) * w, 0, w - 1).astype(int)
    y = np.clip((uv[:, 1] % 1.0) * h, 0, h - 1).astype(int)   # pixels do Blender começam embaixo, como o v do UV
    return img[y, x]


def cor_por_regra(rgb, metal, nome_obj):
    r, g, b = [float(c) for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    h *= 360.0
    for rg in REG["cores"]:
        if "objeto" in rg and not re.search(rg["objeto"], nome_obj):
            continue
        ok = True
        for k, val in (("h", h), ("s", s), ("v", v), ("metal", metal)):
            if k in rg:
                lo, hi = rg[k]
                if lo <= hi and not (lo <= val <= hi):
                    ok = False
                if lo > hi and not (val >= lo or val <= hi):     # faixa de matiz que dá a volta (vermelho: 345 a 15)
                    ok = False
        if ok:
            return rg["material"]
    return "chassi"


# 1. material nosso por face, ainda no espaço do arquivo
NOSSOS = []
def idx_mat(n):
    if n not in NOSSOS:
        NOSSOS.append(n)
    return NOSSOS.index(n)


por_obj = {}
for o in objs:
    regra = next((r for r in REG["objetos"] if re.search(r["nome"], o.name)), {"material": "chassi"})
    me = o.data
    uvl = me.uv_layers.active
    alvo = np.zeros(len(me.polygons), np.int32)
    for p in me.polygons:
        src = me.materials[p.material_index] if me.materials else None
        if regra["material"] != "cor" or uvl is None or src is None:
            alvo[p.index] = idx_mat(regra["material"] if regra["material"] != "cor" else "chassi")
            continue
        if src.name not in cache:
            cache[src.name] = (imagem_de(src, "cor"), imagem_de(src, "mr"))
        img, mr = cache[src.name]
        if img is None:
            alvo[p.index] = idx_mat("chassi")
            continue
        uv = np.array([uvl.data[li].uv[:] for li in p.loop_indices])
        uv = np.vstack([uv, uv.mean(0, keepdims=True), 0.5 * (uv + uv.mean(0, keepdims=True))])
        rgb = np.median(amostra(img, uv)[:, :3], 0)
        metal = float(np.median(amostra(mr, uv)[:, 2])) if mr is not None else 0.0   # glTF: metal no azul
        alvo[p.index] = idx_mat(cor_por_regra(rgb, metal, o.name))
    # ilhas pequenas de um material dentro de outro (as venezianas desenhadas na textura da lataria viravam cacos pretos): passam
    # para o material em volta
    for il in REG.get("ilhas_pequenas", []):
        if not re.search(il.get("objeto", "."), o.name) or il["de"] not in NOSSOS or il["para"] not in NOSSOS:
            continue
        de, para = NOSSOS.index(il["de"]), NOSSOS.index(il["para"])
        viz = {}
        aresta_faces = {}
        for p in me.polygons:
            for k in p.edge_keys:
                aresta_faces.setdefault(k, []).append(p.index)
        for p in me.polygons:
            viz[p.index] = {q for k in p.edge_keys for q in aresta_faces[k] if q != p.index}
        visto = set()
        trocadas = 0
        for f0 in range(len(me.polygons)):
            if alvo[f0] != de or f0 in visto:
                continue
            pilha, ilha, borda = [f0], [], set()
            visto.add(f0)
            while pilha:
                f = pilha.pop()
                ilha.append(f)
                for q in viz[f]:
                    if alvo[q] == de:
                        if q not in visto:
                            visto.add(q)
                            pilha.append(q)
                    else:
                        borda.add(int(alvo[q]))
            if len(ilha) <= il["max_faces"] and borda == {para}:
                alvo[ilha] = para
                trocadas += len(ilha)
        print("%s: %d faces de %s viraram %s (ilhas pequenas)" % (o.name, trocadas, il["de"], il["para"]))
    por_obj[o.name] = alvo

# 2. desparenta e junta (os materiais nossos por índice)
mats = {}
for n in NOSSOS:
    m = bpy.data.materials.new(n)
    m.use_nodes = True
    mats[n] = m
for o in objs:
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = Matrix.Identity(4)
    o.data.transform(M)
    me = o.data
    me.materials.clear()
    for n in NOSSOS:
        me.materials.append(mats[n])
    me.polygons.foreach_set("material_index", por_obj[o.name])
    # só uma camada de UV (a primeira) para o join não misturar
    while len(me.uv_layers) > 1:
        me.uv_layers.remove(me.uv_layers[-1])
    if me.uv_layers:
        me.uv_layers[0].name = "UVMap"
# número da ilha original em cada vértice (o corte solda os vértices e as chapas se juntam; com isto o mapa ainda pega o para-lama
# inteiro, ilhas: true no carro_quebravel.py); vai no GLB como o atributo _ilha
prox = 0
for o in objs:
    me = o.data
    pai = list(range(len(me.vertices)))
    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i
    for e in me.edges:
        a_, b_ = raiz(e.vertices[0]), raiz(e.vertices[1])
        if a_ != b_:
            pai[a_] = b_
    ids = {}
    val = []
    for i in range(len(me.vertices)):
        r = raiz(i)
        if r not in ids:
            ids[r] = prox
            prox += 1
        val.append(float(ids[r]))
    at = me.attributes.new("_ilha", "FLOAT", "POINT")
    at.data.foreach_set("value", val)
print("ilhas originais:", prox)
for o in list(bpy.data.objects):
    if o.type == "EMPTY":
        bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
me = ob.data


def pts():
    return np.array([v.co[:] for v in me.vertices])


# 3. frente em +X, escala pelo comprimento, chão em z = 0
giro = {"+x": 0.0, "-x": math.pi, "+y": -math.pi / 2, "-y": math.pi / 2}[REG.get("frente", "+x")]
me.transform(Matrix.Rotation(giro, 4, "Z"))
P = pts()
s = COMP / (P[:, 0].max() - P[:, 0].min())
me.transform(Matrix.Scale(s, 4))
P = pts()
me.transform(Matrix.Translation(Vector((-(P[:, 0].min() + P[:, 0].max()) / 2, -(P[:, 1].min() + P[:, 1].max()) / 2, -P[:, 2].min()))))

# 4. rodas: as faces de pneu, por quadrante; origem entre os eixos
mi = np.zeros(len(me.polygons), np.int32)
me.polygons.foreach_get("material_index", mi)
P = pts()
rodas = []
if "pneu" in NOSSOS:
    ip = NOSSOS.index("pneu")
    vs = sorted({v for p in me.polygons if p.material_index == ip for v in p.vertices})
    Q = P[vs]
    for nome, sx, sy in (("fl", 1, 1), ("fr", 1, -1), ("rl", -1, 1), ("rr", -1, -1)):
        q = Q[(np.sign(Q[:, 0]) == sx) & (np.sign(Q[:, 1]) == sy)]
        if len(q) == 0:
            continue
        mn, mx = q.min(0), q.max(0)
        rodas.append(dict(nome=nome, lado=sy, cx=float((mn[0] + mx[0]) / 2), cz=float((mn[2] + mx[2]) / 2), raio=float((mx[2] - mn[2]) / 2),
                          y_dentro=float(min(abs(mn[1]), abs(mx[1]))), y_fora=float(max(abs(mn[1]), abs(mx[1])))))
    xf = np.mean([r["cx"] for r in rodas if r["nome"][0] == "f"])
    xr = np.mean([r["cx"] for r in rodas if r["nome"][0] == "r"])
    xm = float((xf + xr) / 2)
    # centro em y pelas rodas (a caixa inteira pende para o lado de um retrovisor ou de uma maçaneta)
    ym = float(np.mean([r["lado"] * (r["y_dentro"] + r["y_fora"]) / 2 for r in rodas]))
    me.transform(Matrix.Translation(Vector((-xm, -ym, 0))))
    for r in rodas:
        r["cx"] -= xm
        yc = r["lado"] * (r["y_dentro"] + r["y_fora"]) / 2 - ym
        meia = (r["y_fora"] - r["y_dentro"]) / 2
        r["y_dentro"], r["y_fora"] = abs(yc) - meia, abs(yc) + meia
me.update()

# 5. adensa (opcional), normais por ângulo
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
if ARESTA > 0:
    for _ in range(6):
        longas = [e for e in bm.edges if e.calc_length() > ARESTA]
        if not longas:
            break
        bmesh.ops.subdivide_edges(bm, edges=longas, cuts=1, use_grid_fill=True)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
bm.to_mesh(me)
bm.free()
for p in me.polygons:
    p.use_smooth = True
bm = bmesh.new()
bm.from_mesh(me)
vivas = [False] * len(me.edges)
for e in bm.edges:
    if len(e.link_faces) == 2 and (e.calc_face_angle(0.0) > math.radians(ANG) or
                                   e.link_faces[0].material_index != e.link_faces[1].material_index):
        vivas[e.index] = True
bm.free()
at = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
at.data.foreach_set("value", vivas)
me.update()

# 6. cores de prévia dos materiais (o resto do acervo refaz as dele)
PREVIA = {"pintura": ((0.03, 0.18, 0.6), 0.35, 0.0), "vidro": ((0.1, 0.12, 0.13), 0.05, 0.0), "pneu": ((0.02, 0.02, 0.02), 0.8, 0.0),
          "chassi": ((0.025, 0.025, 0.028), 0.8, 0.0), "cromado": ((0.9, 0.9, 0.9), 0.08, 1.0), "cromo": ((0.8, 0.8, 0.82), 0.15, 1.0), "luz_vermelha": ((0.6, 0.01, 0.01), 0.15, 0.0),
          "luz_ambar": ((0.9, 0.3, 0.02), 0.15, 0.0), "luz_branca": ((0.9, 0.9, 0.9), 0.1, 0.0), "lente_farol": ((0.85, 0.87, 0.9), 0.08, 0.2),
          "refletor": ((0.7, 0.7, 0.7), 0.3, 0.6), "aro": ((0.7, 0.7, 0.68), 0.35, 0.8)}
for n, m in mats.items():
    b = m.node_tree.nodes.get("Principled BSDF")
    cor, rug, met = PREVIA.get(n, ((0.5, 0.5, 0.5), 0.5, 0.0))
    b.inputs["Base Color"].default_value = (*cor, 1)
    b.inputs["Roughness"].default_value = rug
    b.inputs["Metallic"].default_value = met
    if n == "vidro":
        b.inputs["Alpha"].default_value = 0.3

P = pts()
mi = np.zeros(len(me.polygons), np.int32)
me.polygons.foreach_get("material_index", mi)
medidas = {
    "regras": os.path.basename(a[2]), "escala": round(s, 5),
    "caixa": [round(float(v), 4) for v in (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max())],
    "rodas": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rodas],
    "eixos": {"dianteiro": round(float(np.mean([r["cx"] for r in rodas if r["nome"][0] == "f"])), 4) if rodas else None,
              "traseiro": round(float(np.mean([r["cx"] for r in rodas if r["nome"][0] == "r"])), 4) if rodas else None},
    "faces_por_material": {n: int((mi == i).sum()) for i, n in enumerate(NOSSOS)},
    "triangulos": len(me.polygons),
}
ob.name = me.name = "carro"
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_image_format="AUTO", export_attributes=True)
json.dump(medidas, open(OUT[:-4] + "_medidas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(medidas, ensure_ascii=False, indent=1))
