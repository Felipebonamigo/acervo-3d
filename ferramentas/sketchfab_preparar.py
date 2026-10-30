"""Carro do Sketchfab (3 objetos: carroceria, vidros, rodas+assoalho) -> um objeto só no nosso referencial, adensado, com a carroceria
esticada acima do eixo até a altura real (as rodas ficam redondas), materiais por ilha (pintura, vidro, pneu) e medidas impressas."""
import bpy, bmesh, sys, json, numpy as np
from mathutils import Vector, Matrix
a = sys.argv[sys.argv.index("--") + 1:]
# --manter-materiais (30/10/2026, Sagui): a face que vem com material de nome igual a um papel nosso (o sketchfab_montar.py grava
# assim) fica com esse papel, em vez da regra por ilha; sem a opção, nada muda (o Gol Quadrado sai igual)
MANTER = "--manter-materiais" in a
# --sem-pca: o arquivo já vem com o comprimento em x (o sketchfab_montar.py alinha); a PCA da carroceria torcia 0,2 grau
SEM_PCA = "--sem-pca" in a
a = [x for x in a if x not in ("--manter-materiais", "--sem-pca")]
PAPEIS_EXTRA = ("luz", "cromado", "luz_vermelha", "luz_ambar", "luz_branca", "lente_farol", "refletor")
ent, out, keep = a[0], a[1], a[2].split(",")
COMP, ALT, ARESTA = float(a[3]), float(a[4]), float(a[5])
ANGULO = float(a[6]) if len(a) > 6 else 30.0   # aresta mais dobrada do que isso fica viva; o resto é liso
SUAVIZAR = int(a[7]) if len(a) > 7 else 0        # passos de suavização (Taubin) dos vincos suaves: arredonda as facetas de baixo polígono
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
if MANTER:
    for m in list(bpy.data.materials):          # lista: renomear muda a ordem da coleção (cromado saía "entrada_entrada_")
        m.name = "entrada_" + m.name.split(".")[0]
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.name not in keep:
        bpy.data.objects.remove(o)
objs = [bpy.data.objects[k] for k in keep]
for o in objs:
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = Matrix.Identity(4)
    o.data.transform(M)
bpy.context.view_layer.update()
for o in list(bpy.data.objects):
    if o.type == "EMPTY":
        bpy.data.objects.remove(o)
body = objs[0]


def pts(o):
    return np.array([v.co for v in o.data.vertices])


# 1. alinha (PCA no plano), escala pelo comprimento, chão, frente em +X
P = pts(body)
c = P.mean(0)
Q = P[:, :2] - c[:2]
w, vec = np.linalg.eigh(Q.T @ Q)
ax = vec[:, 1] if not SEM_PCA else np.array([1.0, 0.0])
R = Matrix.Rotation(-np.arctan2(ax[1], ax[0]), 4, "Z")
for o in objs:
    o.data.transform(Matrix.Translation(-Vector(c)))
    o.data.transform(R)
P = pts(body)
s = COMP / (P[:, 0].max() - P[:, 0].min())
for o in objs:
    o.data.transform(Matrix.Scale(s, 4))
allP = np.concatenate([pts(o) for o in objs])
zmin, xmid = allP[:, 2].min(), 0.5 * (allP[:, 0].min() + allP[:, 0].max())
for o in objs:
    o.data.transform(Matrix.Translation(Vector((-xmid, 0, -zmin))))
P = pts(body)
q = 0.22 * (P[:, 0].max() - P[:, 0].min())
zf = np.percentile(P[P[:, 0] > P[:, 0].max() - q, 2], 95)
zr = np.percentile(P[P[:, 0] < P[:, 0].min() + q, 2], 95)
if zf > zr:
    for o in objs:
        o.data.transform(Matrix.Rotation(np.pi, 4, "Z"))

# 2. ilhas por objeto, com caixa; rodas = ilhas baixas nos cantos
def ilhas(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    visto = set()
    out = []
    for v0 in bm.verts:
        if v0.index in visto:
            continue
        pilha = [v0]
        visto.add(v0.index)
        g = []
        while pilha:
            v = pilha.pop()
            g.append(v.index)
            for e in v.link_edges:
                u = e.other_vert(v)
                if u.index not in visto:
                    visto.add(u.index)
                    pilha.append(u)
        out.append(np.array(g))
    bm.free()
    return out


medidas = {"vidros": {}, "rodas": [], "retrovisores": [], "pecas_soltas": {}}
candidatas = []
rodas_idx = {}
janela_idx = {}


def eh_janela(mn, mx, n):
    tam = mx - mn
    if mn[2] < 0.75 or mx[0] > 0.8 or n > 14:
        return False
    if tam[0] < 0.4 or tam[2] < 0.25:
        return False
    return (tam[1] > 0.9) or (tam[1] < 0.25 and min(abs(mn[1]), abs(mx[1])) > 0.35)


for o in objs:
    P = pts(o)
    for g in ilhas(o):
        mn, mx = P[g].min(0), P[g].max(0)
        cen = 0.5 * (mn + mx)
        tam = mx - mn
        eh_roda = tam[2] < 0.8 and mn[2] < 0.05 and abs(cen[0]) > 0.8 and abs(cen[1]) > 0.5 and abs(tam[0] - tam[2]) < 0.15 and tam[0] > 0.4
        if eh_roda:
            rodas_idx.setdefault(o.name, []).append(g)
            medidas["rodas"].append(dict(centro=[round(float(cen[0]), 4), round(float(cen[1]), 4), round(float(tam[2] / 2), 4)],
                                         raio=round(float(tam[2] / 2), 4), y=[round(float(min(abs(mn[1]), abs(mx[1]))), 4), round(float(max(abs(mn[1]), abs(mx[1]))), 4)]))
        elif o is objs[1]:
            box = [round(float(v), 4) for v in np.concatenate([[mn[0], mx[0]], [mn[1], mx[1]], [mn[2], mx[2]]])]
            if eh_janela(mn, mx, len(g)):
                candidatas.append((o.name, g, box))
            else:
                medidas["pecas_soltas"][len(medidas["pecas_soltas"])] = dict(box=box, n=int(len(g)))
        elif o is objs[0] and tam[0] < 0.3 and tam[2] < 0.3 and abs(cen[1]) > 0.7:
            medidas["retrovisores"].append([round(float(v), 4) for v in np.concatenate([[mn[0], mx[0]], [mn[1], mx[1]], [mn[2], mx[2]]])])

# janelas laterais só em par espelhado (esquerda/direita com o mesmo x e z); as largas (para-brisa, traseiro) passam direto
for nome_o, g, box in candidatas:
    larga = (box[3] - box[2]) > 0.9
    par = any(abs(b2[0] - box[0]) < 0.04 and abs(b2[4] - box[4]) < 0.04 and abs(b2[1] - box[1]) < 0.04 and
              abs(b2[2] + box[3]) < 0.12 and abs(b2[3] + box[2]) < 0.12 and (b2[3] - b2[2]) < 0.25 for _, _, b2 in candidatas)
    if larga or par:
        janela_idx.setdefault(nome_o, []).append(g)
        medidas["vidros"][len(medidas["vidros"])] = dict(box=box, n=int(len(g)))
    else:
        medidas["pecas_soltas"][len(medidas["pecas_soltas"])] = dict(box=box, n=int(len(g)))
# 2a. origem entre os eixos (as ilhas de roda: 3 por roda, frente e trás)
if medidas["rodas"]:
    xf = float(np.mean([r["centro"][0] for r in medidas["rodas"] if r["centro"][0] > 0]))
    xr = float(np.mean([r["centro"][0] for r in medidas["rodas"] if r["centro"][0] < 0]))
    xm = 0.5 * (xf + xr)
    for o in objs:
        o.data.transform(Matrix.Translation(Vector((-xm, 0, 0))))
    for grupo in (medidas["vidros"], medidas["pecas_soltas"]):
        for d in grupo.values():
            d["box"][0] -= xm
            d["box"][1] -= xm
    for b, _ in zip(medidas["retrovisores"], medidas["retrovisores"]):
        b[0] -= xm
        b[1] -= xm
    for _, _, box in candidatas:
        box[0] -= xm
        box[1] -= xm
    for r in medidas["rodas"]:
        r["centro"][0] -= xm
    medidas["eixos"] = dict(dianteiro=round(xf - xm, 4), traseiro=round(xr - xm, 4), desloc_x=round(xm, 4))
# 2b. centro em Y pelas janelas laterais (o modelo vinha deslocado)
lat = [d["box"] for d in medidas["vidros"].values() if (d["box"][3] - d["box"][2]) < 0.25]
if lat:
    yc = float(np.mean([0.5 * (b[2] + b[3]) for b in lat]))
    for o in objs:
        o.data.transform(Matrix.Translation(Vector((0, -yc, 0))))
    for grupo in (medidas["vidros"], medidas["pecas_soltas"]):
        for d in grupo.values():
            d["box"][2] -= yc
            d["box"][3] -= yc
    medidas["retrovisores"] = [[b[0], b[1], b[2] - yc, b[3] - yc, b[4], b[5]] for b in medidas["retrovisores"]]
    for r in medidas["rodas"]:
        r["centro"][1] -= yc
    medidas["desloc_y"] = round(yc, 4)
# 3. altura real: estica só acima do eixo, rodas intactas
z_eixo = float(np.mean([r["raio"] for r in medidas["rodas"]])) if medidas["rodas"] else 0.3
allP = np.concatenate([pts(o) for o in objs])
k = (ALT - z_eixo) / (allP[:, 2].max() - z_eixo)
for o in objs:
    rod = set(np.concatenate(rodas_idx.get(o.name, [np.array([], int)])).tolist())
    for v in o.data.vertices:
        if v.index in rod:
            continue
        if v.co.z > z_eixo:
            v.co.z = z_eixo + (v.co.z - z_eixo) * k
    o.data.update()
for grupo in (medidas["vidros"], medidas["pecas_soltas"]):
    for key, d in grupo.items():
        b = d["box"]
        d["box"] = b[:4] + [round(float(z_eixo + (z - z_eixo) * k), 4) if z > z_eixo else float(z) for z in b[4:]]
medidas["retrovisores"] = [b[:4] + [round(float(z_eixo + (z - z_eixo) * k), 4) for z in b[4:]] for b in medidas["retrovisores"]]
medidas["estica_acima_do_eixo"] = dict(z_eixo=round(z_eixo, 4), k=round(float(k), 4))

# 4. materiais: pintura (carroceria), vidro, pneu (ilhas de roda), chassi (o resto do assoalho)
# o papel de entrada de cada face (antes de os materiais serem trocados), com --manter-materiais
papel_entrada = {}
if MANTER:
    for o in objs:
        nomes = [(m.name[len("entrada_"):] if m and m.name.startswith("entrada_") else "") for m in o.data.materials]
        papel_entrada[o.name] = [nomes[p.material_index] if p.material_index < len(nomes) else "" for p in o.data.polygons]
mats = {}
for nome in ("pintura", "vidro", "pneu", "chassi") + (PAPEIS_EXTRA if MANTER else ()):
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    mats[nome] = m
tex_img = None
for m in body.data.materials:
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            tex_img = n.image
for nome, m in mats.items():
    bsdf = m.node_tree.nodes["Principled BSDF"]
    if tex_img is not None and nome in ("pintura", "pneu", "vidro"):
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = tex_img
        m.node_tree.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = {"pintura": 0.35, "vidro": 0.05, "pneu": 0.8, "chassi": 0.8}.get(nome, 0.3)
    if nome == "chassi":
        bsdf.inputs["Base Color"].default_value = (0.03, 0.03, 0.03, 1)
    elif MANTER and tex_img is None:
        ent_m = bpy.data.materials.get("entrada_" + nome)
        if ent_m is not None and ent_m.use_nodes and ent_m.node_tree.nodes.get("Principled BSDF"):
            bsdf.inputs["Base Color"].default_value = ent_m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value[:]
for i, o in enumerate(objs):
    me = o.data
    me.materials.clear()
    ordem = list(mats)
    for nome in ordem:
        me.materials.append(mats[nome])
    rod = set(np.concatenate(rodas_idx.get(o.name, [np.array([], int)])).tolist())
    jan = set(np.concatenate(janela_idx.get(o.name, [np.array([], int)])).tolist())
    for p in me.polygons:
        if any(v in jan for v in p.vertices):
            p.material_index = 1
        elif any(v in rod for v in p.vertices):
            p.material_index = 2
        elif i == 2:
            p.material_index = 3
        else:
            p.material_index = 0
        if MANTER:
            pe = papel_entrada[o.name][p.index]
            if pe in ordem:
                p.material_index = ordem.index(pe)
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
me = ob.data
# 5. adensa
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
for _ in range(6):
    longas = [e for e in bm.edges if e.calc_length() > ARESTA]
    if not longas:
        break
    bmesh.ops.subdivide_edges(bm, edges=longas, cuts=1, use_grid_fill=True)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
bm.to_mesh(me)
bm.free()
me.update()
for p in me.polygons:
    p.use_smooth = True
# normais: lisas dentro de cada chapa e vivas nas dobras (sem isso, o vinco da tampa e a saia refletiam o céu em manchas)
import math as _m
bm = bmesh.new()
bm.from_mesh(me)
vivas = [False] * len(me.edges)
for e in bm.edges:
    if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > _m.radians(ANGULO):
        vivas[e.index] = True
if SUAVIZAR > 0:
    # facetas de baixo polígono (quarta traseira, teto): os vértices que não estão numa aresta viva nem numa fronteira de material
    # andam para a média dos vizinhos (Taubin, lambda 0,5 / mu -0,53: arredonda sem encolher); os vincos vivos e os vidros ficam
    fixo = set()
    for e in bm.edges:
        if vivas[e.index] or len(e.link_faces) != 2 or e.link_faces[0].material_index != e.link_faces[1].material_index:
            fixo.update(v.index for v in e.verts)
    bm.verts.ensure_lookup_table()
    moveis = [v for v in bm.verts if v.index not in fixo and not v.is_boundary]
    for passo in range(SUAVIZAR):
        for lam in (0.5, -0.53):
            novo = {}
            for v in moveis:
                viz = [e.other_vert(v).co for e in v.link_edges]
                if viz:
                    media = sum(viz, Vector()) / len(viz)
                    novo[v] = v.co + (media - v.co) * lam
            for v, co in novo.items():
                v.co = co
    bm.to_mesh(me)
    me.update()
    print(f"suavizado: {len(moveis)} vértices livres, {SUAVIZAR} passos")
bm.free()
at = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
at.data.foreach_set("value", vivas)
me.update()
print(f"arestas vivas (> {ANGULO:.0f} graus): {sum(vivas)} de {len(vivas)}")
allP = pts(ob)
medidas["caixa"] = [round(float(v), 4) for v in np.concatenate([[allP[:, 0].min(), allP[:, 0].max()], [allP[:, 1].min(), allP[:, 1].max()], [allP[:, 2].min(), allP[:, 2].max()]])]
medidas["triangulos"] = len(me.polygons)
ob.name = me.name = "carro"
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_image_format="AUTO")
def _py(o):
    if isinstance(o, dict):
        return {k: _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o
medidas = _py(medidas)
json.dump(medidas, open(out[:-4] + "_medidas.json", "w"), indent=1)
print(json.dumps(medidas, indent=1))
