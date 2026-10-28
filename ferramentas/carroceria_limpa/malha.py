"""
Monta a carroceria limpa no Blender a partir do corpo.npz (meio carro em loft + tampas), espelha, põe os vidros (material, rebaixo
e borracha em volta), e junta as peças do Meshy que ficam (faróis, lanternas, grade, placas, para-choques, retrovisores, rodas).

    python malha.py -- corpo.npz saida.glb [corte_do_meshy.glb]
"""
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

a = sys.argv[sys.argv.index("--") + 1:]
d = np.load(a[0])
V = d["V"]                                   # [nx, npts, 3] = (x, y, z), meio carro
nx, npts = V.shape[0], V.shape[1]
quad_glass = d["quad_glass"]
bpy.ops.wm.read_factory_settings(use_empty=True)
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tampas import tampa
bm = bmesh.new()
MATS = {}
mats_list = []
for nome, cor in (("pintura", (0.8, 0.1, 0.1, 1)), ("vidro", (0.6, 0.7, 0.8, 1)), ("chassi", (0.03, 0.03, 0.03, 1))):
    m = bpy.data.materials.get(nome) or bpy.data.materials.new(nome)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = cor
        bsdf.inputs["Roughness"].default_value = {"pintura": 0.35, "vidro": 0.05, "chassi": 0.8}[nome]
    MATS[nome] = len(mats_list)
    mats_list.append(m)
# vértices do loft: esquerda [i][j], direita espelhada (o centro j = npts-1 é o mesmo vértice); a ponta (fim das fileiras) marcada
ponta = bm.verts.layers.int.new("ponta")
L = [[bm.verts.new(Vector(V[i, j])) for j in range(npts)] for i in range(nx)]
R = [[(bm.verts.new(Vector((V[i, j, 0], -V[i, j, 1], V[i, j, 2]))) if j < npts - 1 else L[i][npts - 1]) for j in range(npts)]
     for i in range(nx)]
for j in range(npts):
    L[nx - 1][j][ponta] = 1
    R[nx - 1][j][ponta] = 1
    L[0][j][ponta] = 2
    R[0][j][ponta] = 2
nfaces = 0
for i in range(nx - 1):
    for j in range(npts - 1):
        g = MATS["vidro"] if quad_glass[i, j] else MATS["pintura"]
        for q in ((L[i][j], L[i + 1][j], L[i + 1][j + 1], L[i][j + 1]), (R[i][j + 1], R[i + 1][j + 1], R[i + 1][j], R[i][j])):
            try:
                f = bm.faces.new(q)
                f.smooth = True
                f.material_index = g
                nfaces += 1
            except ValueError:
                pass
# tampas: contorno = fim das fileiras (esquerda de baixo para cima pelo teto e direita de cima para baixo)
bolsos = d["bolsos"]
for nome, i_sec, sinal in (("tampa_frente", nx - 1, 1), ("tampa_tras", 0, -1)):
    cont = [L[i_sec][j] for j in range(npts)] + [R[i_sec][j] for j in range(npts - 2, -1, -1)]
    xm = float(d["x_bico"]) if sinal > 0 else float(d["x_rabo"])
    tampa(bm, cont, d[nome], d["tampa_gy"], d["tampa_gz"], bolsos, sinal, MATS["pintura"], MATS["chassi"], xm)
bm.normal_update()
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
me = bpy.data.meshes.new("body")
bm.to_mesh(me)
for m in mats_list:
    me.materials.append(m)
me.update()
ob = bpy.data.objects.new("body", me)
bpy.context.scene.collection.objects.link(ob)
bpy.context.view_layer.objects.active = ob
ob.select_set(True)
bm.free()
verts, faces = me.vertices, me.polygons

# ---- borda dos vidros encaixada no contorno liso: cada vértice entre vidro e chapa vai para o ponto mais perto do contorno
# (no plano da vista) e volta para a superfície; depois o rebaixo de 5 mm nos vértices só de vidro (a borracha cobre a rampa)
bm = bmesh.new()
bm.from_mesh(me)
bm.verts.ensure_lookup_table()
bm.faces.ensure_lookup_table()
bm.normal_update()
bvh0 = BVHTree.FromBMesh(bm)
tipos = list(d["contorno_tipos"])
conts = [(t, d["contorno_%d" % k]) for k, t in enumerate(tipos)]
nsnap = 0
for v in bm.verts:
    fs = v.link_faces
    if not fs:
        continue
    tem_v = any(f.material_index == MATS["vidro"] for f in fs)
    tem_p = any(f.material_index != MATS["vidro"] for f in fs)
    if not (tem_v and tem_p):
        continue
    n = v.normal
    if abs(n.y) >= abs(n.z):
        tipo, p2 = "lado", np.array([v.co.x, v.co.z])
    else:
        tipo, p2 = "topo", np.array([v.co.x, v.co.y])
    best = None
    for t, P in conts:
        if t != tipo:
            continue
        dd = ((P - p2) ** 2).sum(1)
        k = int(dd.argmin())
        if best is None or dd[k] < best[0]:
            best = (dd[k], P[k])
    if best is None or best[0] > 0.06 ** 2:
        continue
    q = best[1]
    alvo = Vector((q[0], v.co.y, q[1])) if tipo == "lado" else Vector((q[0], q[1] * (1 if v.co.y >= 0 else -1) if tipo == "topo" else q[1], v.co.z))
    if tipo == "topo":
        alvo = Vector((q[0], q[1], v.co.z))
    # volta para a superfície por raio na direção da vista (o ponto mais perto escorregaria pela rampa do para-brisa)
    if tipo == "lado":
        loc, _, _, _ = bvh0.ray_cast(Vector((alvo.x, 1.2 if v.co.y >= 0 else -1.2, alvo.z)), Vector((0, -1 if v.co.y >= 0 else 1, 0)), 2.0)
    else:
        loc, _, _, _ = bvh0.ray_cast(Vector((alvo.x, alvo.y, 2.0)), Vector((0, 0, -1)), 2.0)
    if loc is not None:
        v.co = loc
        nsnap += 1
print("vértices encaixados no contorno:", nsnap)
mv = []
for v in bm.verts:
    fs = v.link_faces
    if fs and all(f.material_index == MATS["vidro"] for f in fs):
        mv.append((v, v.normal.copy()))
for v, n in mv:
    v.co -= n * 0.005
# a face de fora continua para fora (a chapa é uma só, sem espessura): normais consistentes
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(me)
me.update()
bvh_body = BVHTree.FromBMesh(bm)
bm.free()


def smooth(A, s=3):
    kk = np.arange(-3 * s, 3 * s + 1)
    g = np.exp(-0.5 * (kk / s) ** 2)
    g /= g.sum()
    out = np.zeros_like(A)
    for w, q in zip(g, kk):
        out += w * np.roll(A, q, axis=0)
    return out


# ---- borrachas: cordão sobre a borda real de cada vidro na malha (as arestas entre vidro e chapa, já encaixadas no contorno)
ROWS = (-1.0, -0.5, 0.0, 0.5, 1.0)
HW, ALT = 0.012, 0.0035
borrachas = []
bmv = bmesh.new()
bmv.from_mesh(me)
bmv.verts.ensure_lookup_table()
# um laço por vidro (componente conexo das faces de vidro): os vértices da borda em ordem angular na vista do vidro
# (as janelas são convexas; andar pelas arestas embaralhava nos cantos)
bmv.faces.ensure_lookup_table()
visto = set()
lacos = []
for f0 in bmv.faces:
    if f0.index in visto or f0.material_index != MATS["vidro"]:
        continue
    comp = []
    pilha = [f0]
    visto.add(f0.index)
    while pilha:
        f = pilha.pop()
        comp.append(f)
        for e in f.edges:
            for f2 in e.link_faces:
                if f2.index not in visto and f2.material_index == MATS["vidro"]:
                    visto.add(f2.index)
                    pilha.append(f2)
    if len(comp) < 50:
        continue
    vb = {}
    for f in comp:
        for e in f.edges:
            if len(e.link_faces) == 2 and any(g.material_index != MATS["vidro"] for g in e.link_faces):
                for v in e.verts:
                    vb[v.index] = v
    vs = list(vb.values())
    nmed = sum((f.normal for f in comp), Vector()).normalized()
    cen = sum((v.co for v in vs), Vector()) / len(vs)
    if abs(nmed.y) > 0.6:
        ang = lambda v: np.arctan2(v.co.z - cen.z, (v.co.x - cen.x) * (1 if nmed.y > 0 else -1))
    else:
        ang = lambda v: np.arctan2(v.co.y - cen.y, v.co.x - cen.x)
    vs.sort(key=ang)
    lacos.append(vs)
for laco in lacos:
    C3 = np.array([list(v.co) for v in laco])
    N3 = np.array([list(sum((f.normal for f in v.link_faces), Vector()).normalized()) for v in laco])
    cm = C3.mean(axis=0)
    C3 = smooth(C3, 2)
    N3 = smooth(N3, 4)
    N3 /= np.linalg.norm(N3, axis=1, keepdims=True)
    T = np.roll(C3, -1, axis=0) - np.roll(C3, 1, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    side = np.cross(N3, T)
    side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-12)
    bmr = bmesh.new()
    ring = [[bmr.verts.new(Vector(C3[i] + side[i] * s_ * HW + N3[i] * (0.002 + ALT * (1 - s_ * s_)))) for s_ in ROWS]
            for i in range(len(C3))]
    for i in range(len(C3)):
        a_, b_ = ring[i], ring[(i + 1) % len(C3)]
        for j in range(len(ROWS) - 1):
            try:
                f = bmr.faces.new((a_[j], b_[j], b_[j + 1], a_[j + 1]))
                f.smooth = True
            except ValueError:
                pass
    bmr.normal_update()
    for f in bmr.faces:
        _, nor, _, _ = bvh_body.find_nearest(f.calc_center_median())
        if nor is not None and f.normal.dot(nor) < 0:
            f.normal_flip()
    mer = bpy.data.meshes.new("borracha")
    bmr.to_mesh(mer)
    mer.materials.append(bpy.data.materials["chassi"])
    obr = bpy.data.objects.new("borracha", mer)
    bpy.context.scene.collection.objects.link(obr)
    bmr.free()
    # dona: janela da porta -> porta; vidro traseiro -> tampa; o resto -> carroceria
    nz_ = abs(N3[:, 2].mean())
    if nz_ < 0.5 and -0.45 < cm[0] < 0.7:
        dona = "door_fl" if cm[1] > 0 else "door_fr"
    elif nz_ >= 0.5 and cm[0] < -0.5:
        dona = "trunk"
    else:
        dona = "body"
    borrachas.append((obr, dona))
bmv.free()
print("borrachas:", len(lacos), [len(l) for l in lacos])

# ---- cortes dos painéis: portas, capô, para-lamas, tampa; vidros separados; frestas e abas
from cortes import cortar, separar, nomear, fresta_e_aba
janela = None
for k, t in enumerate(tipos):
    P = d["contorno_%d" % k]
    if t == "lado" and P[:, 0].min() < 0.0 < P[:, 0].max():
        topo = P[P[:, 1] > P[:, 1].max() - 0.06]
        q = topo[np.argmax(topo[:, 0])]
        janela = np.array([q[0] + 0.03, q[1] + 0.03])
dd = dict(d)
dd["janela_porta"] = janela
bmc, marca, ncut = cortar(ob, dd)
print("arestas de corte:", ncut)
grupos = separar(bmc, marca)
z_belt = float(d["zw"][1])
nomeados = nomear(grupos, z_belt)
# pedaços pequenos vão para a carroceria
body_faces = []
pecas = {}
for nome, g, area in nomeados:
    if nome in ("lixo", "body"):
        body_faces += g
    else:
        pecas.setdefault(nome, []).extend(g)
pecas["body"] = body_faces
for nome, g in pecas.items():
    if not nome.startswith("glass_"):
        fresta_e_aba(bmc, g, marca, MATS["chassi"])
# um objeto por peça
bpy.data.objects.remove(ob)
objs = {}
for nome, g in pecas.items():
    bmp = bmesh.new()
    vmap = {}
    for f in g:
        vs = []
        for v in f.verts:
            if v not in vmap:
                vmap[v] = bmp.verts.new(v.co)
            vs.append(vmap[v])
        try:
            nf = bmp.faces.new(vs)
            nf.material_index = f.material_index
            nf.smooth = f.smooth
        except ValueError:
            pass
    mp = bpy.data.meshes.new(nome)
    bmp.to_mesh(mp)
    for m in mats_list:
        mp.materials.append(m)
    bmp.free()
    op = bpy.data.objects.new(nome, mp)
    bpy.context.scene.collection.objects.link(op)
    objs[nome] = op
    print("  peça %-20s %6d faces" % (nome, len(mp.polygons)))
# pele de dentro (espessura 1,5 cm, escura, MI_DNVao: o kit_to_detonauto tira o que fica nos vãos do kit) e um mapa UV simples
vao = bpy.data.materials.get("MI_DNVao") or bpy.data.materials.new("MI_DNVao")
vao.use_nodes = True
if vao.node_tree.nodes.get("Principled BSDF"):
    vao.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.04, 0.04, 0.04, 1)
    vao.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.85
for nome, op in objs.items():
    mp = op.data
    bmp = bmesh.new()
    bmp.from_mesh(mp)
    if not nome.startswith("glass_"):
        mp.materials.append(vao)
        i_vao = len(mp.materials) - 1
        chapa = [f for f in bmp.faces if f.material_index == MATS["pintura"]]
        r = bmesh.ops.duplicate(bmp, geom=chapa)
        novas = [g for g in r["geom"] if isinstance(g, bmesh.types.BMFace)]
        vnov = {}
        for f in novas:
            for v in f.verts:
                vnov[v] = f.normal
        for v in list(vnov):
            n = Vector()
            for f in v.link_faces:
                n += f.normal
            if n.length > 1e-9:
                v.co -= n.normalized() * 0.015
        for f in novas:
            f.material_index = i_vao
            f.smooth = True
        bmesh.ops.reverse_faces(bmp, faces=novas)
    uv = bmp.loops.layers.uv.new("UVMap")
    for f in bmp.faces:
        for l in f.loops:
            l[uv].uv = ((l.vert.co.x + 2.0) / 4.0, (l.vert.co.z + 0.2) / 1.7)
    bmp.to_mesh(mp)
    bmp.free()
    mp.update()
bmc.free()
# borrachas juntadas às donas
for obr, dona in borrachas:
    alvo = objs.get(dona) or objs["body"]
    bpy.ops.object.select_all(action="DESELECT")
    obr.select_set(True)
    alvo.select_set(True)
    bpy.context.view_layer.objects.active = alvo
    bpy.ops.object.join()
# ---- detalhes paramétricos: para-choques, maçanetas, limpadores
from detalhes import parachoque, macaneta, limpador
def novo_objeto(nome, bmx, mats):
    mx = bpy.data.meshes.new(nome)
    bmx.to_mesh(mx)
    for m in mats:
        mx.materials.append(m)
    ox = bpy.data.objects.new(nome, mx)
    bpy.context.scene.collection.objects.link(ox)
    bmx.free()
    return ox
# lado da carroceria na altura do para-choque, nos cantos
def y_lado_em(x, z):
    loc, _, _, _ = bvh0.ray_cast(Vector((x, 1.5, z)), Vector((0, -1, 0)), 3.0)
    return loc.y if loc else 0.75
xb_f, xb_r = float(d["x_bico"]), float(d["x_rabo"])
for nome, sinal, x_face, x_fim in (("bumper_front", 1, xb_f + 0.085, xb_f - 0.27), ("bumper_rear", -1, xb_r - 0.075, xb_r + 0.28)):
    bmb = bmesh.new()
    yl = y_lado_em(x_fim, 0.45) + 0.03
    parachoque(bmb, x_face, yl, x_fim, sinal, 0)
    bmb.normal_update()
    bmesh.ops.recalc_face_normals(bmb, faces=bmb.faces)
    ob_b = novo_objeto(nome, bmb, [bpy.data.materials["chassi"]])
    objs[nome] = ob_b
# maçanetas nas portas (um terço de trás da porta, logo abaixo da cintura) e limpadores no para-brisa
xd0, xd1 = [float(v) for v in d["door_x"]]
zb_ = float(d["zw"][1]) - 0.10
for nome, lado in (("door_fl", 1), ("door_fr", -1)):
    xm = xd0 + 0.28 * (xd1 - xd0)
    loc, nor, _, _ = bvh0.ray_cast(Vector((xm, 1.5 * lado, zb_)), Vector((0, -lado, 0)), 3.0)
    if loc is None:
        continue
    bmm = bmesh.new()
    macaneta(bmm, xm, loc.y, zb_, lado, 0)
    bmesh.ops.recalc_face_normals(bmm, faces=bmm.faces)
    ob_m = novo_objeto("macaneta", bmm, [bpy.data.materials["chassi"]])
    bpy.ops.object.select_all(action="DESELECT")
    ob_m.select_set(True)
    objs[nome].select_set(True)
    bpy.context.view_layer.objects.active = objs[nome]
    bpy.ops.object.join()
x_cowl = float(d["x_cowl"])
bml = bmesh.new()
for y0, y1 in ((-0.42, 0.12), (0.18, 0.70)):
    pb = bvh0.ray_cast(Vector((x_cowl - 0.04, y0, 2.0)), Vector((0, 0, -1)), 3.0)
    pp = bvh0.ray_cast(Vector((x_cowl - 0.34, y1, 2.0)), Vector((0, 0, -1)), 3.0)
    if pb[0] is not None and pp[0] is not None:
        limpador(bml, pb[0], pp[0], pb[1], 0)
bmesh.ops.recalc_face_normals(bml, faces=bml.faces)
ob_l = novo_objeto("limpadores", bml, [bpy.data.materials["chassi"]])
bpy.ops.object.select_all(action="DESELECT")
ob_l.select_set(True)
objs["body"].select_set(True)
bpy.context.view_layer.objects.active = objs["body"]
bpy.ops.object.join()
# ---- faróis e lanternas paramétricos nos bolsos (no jogo têm material próprio; aqui cores para a prévia)
from detalhes import lanterna
cores = {"cromado": (0.75, 0.75, 0.78, 1), "luz": (0.9, 0.9, 0.85, 1), "luz_vermelha": (0.6, 0.02, 0.02, 1), "luz_ambar": (0.9, 0.5, 0.05, 1)}
mats_luz = []
for nome_m, cor in cores.items():
    m = bpy.data.materials.get(nome_m) or bpy.data.materials.new(nome_m)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = cor
        bsdf.inputs["Roughness"].default_value = 0.15 if nome_m != "cromado" else 0.25
        if nome_m == "cromado":
            bsdf.inputs["Metallic"].default_value = 1.0
    mats_luz.append(m)
for b in d["bolsos"]:
    sinal, bx0, bx1, by0, by1, bz0, bz1, fundo = b
    larg, alt_ = by1 - by0, bz1 - bz0
    if larg > 0.5 or alt_ < 0.08 or abs(by0 + by1) < 0.3:
        continue                                   # grade e placas (no meio) não são lanternas
    bml_ = bmesh.new()
    esq = (by0 + by1) > 0
    # a face do carro no centro do bolso (a caixa do mapa é do Meshy; a lente fica 4 mm para dentro da face limpa)
    gy_, gz_ = d["tampa_gy"], d["tampa_gz"]
    sup = d["tampa_frente"] if sinal > 0 else d["tampa_tras"]
    iy_ = int(np.clip(round((0.5 * (by0 + by1) - gy_[0]) / (gy_[1] - gy_[0])), 0, len(gy_) - 1))
    iz_ = int(np.clip(round((0.5 * (bz0 + bz1) - gz_[0]) / (gz_[1] - gz_[0])), 0, len(gz_) - 1))
    xface = float(sup[iy_, iz_])
    caixa_ = (xface - fundo, xface, by0, by1, bz0, bz1) if sinal > 0 else (xface, xface + fundo, by0, by1, bz0, bz1)
    if sinal > 0:
        nome = "headlight_left" if esq else "headlight_right"
        lanterna(bml_, 1, caixa_, (0, 1))
    else:
        nome = "taillight_left" if esq else "taillight_right"
        # lanterna: ré (branca) perto do centro, seta (âmbar) no meio, freio (vermelha) na ponta
        segs = [(0.0, 0.3, 1), (0.3, 0.55, 3), (0.55, 1.0, 2)] if not esq else [(0.0, 0.45, 2), (0.45, 0.7, 3), (0.7, 1.0, 1)]
        lanterna(bml_, -1, caixa_, (0, 1), segs)
    bmesh.ops.recalc_face_normals(bml_, faces=bml_.faces)
    objs[nome] = novo_objeto(nome, bml_, mats_luz)
# ---- peças do Meshy que ficam
if len(a) > 2:
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=a[2])
    novos = [o for o in bpy.data.objects if o not in antes]
    fica = ("plate_", "mirror_", "wheel_", "hubcap_")
    for o in novos:
        if o.type == "MESH" and not o.name.startswith(fica):
            bpy.data.objects.remove(o)
# ---- grade: palhetas horizontais pretas no bolso da grade
for b in d["bolsos"]:
    sinal, bx0, bx1, by0, by1, bz0, bz1, fundo = b
    if not (sinal > 0 and bz1 - bz0 > 0.15 and by1 - by0 > 0.5):
        continue
    bmg = bmesh.new()
    n_pal = 5
    h = (bz1 - bz0) / n_pal
    for k in range(n_pal):
        zc = bz0 + (k + 0.5) * h
        bmesh.ops.create_cube(bmg, size=1.0)
        for v in bmg.verts:
            if not v.tag:
                v.co = Vector((bx0 + 0.02 + v.co.x * 0.03, 0.5 * (by0 + by1) + v.co.y * (by1 - by0 - 0.02), zc + v.co.z * h * 0.55))
                v.tag = True
    for v in bmg.verts:
        v.tag = False
    meg = bpy.data.meshes.new("grille")
    bmg.to_mesh(meg)
    meg.materials.append(bpy.data.materials["chassi"])
    obg = bpy.data.objects.new("grille", meg)
    bpy.context.scene.collection.objects.link(obg)
    bmg.free()
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=a[1], export_format="GLB", use_selection=True)
print("malha", len(me.vertices), "vértices", len(me.polygons), "faces")
