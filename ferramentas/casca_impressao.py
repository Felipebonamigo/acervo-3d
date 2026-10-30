"""Casca maciça de impressão 3D (STL do Sketchfab: lataria com espessura, janelas e caixas de roda furadas, sem vidro, sem roda, sem
assoalho e sem material) -> os 3 objetos que a sketchfab_preparar.py espera: "carroceria", "vidros" e "rodas" (rodas do rodas_kit e
uma chapa de assoalho). Nada aqui muda a cadeia do Gol Quadrado, que já traz os 3 objetos do autor.

    python -I ferramentas/casca_impressao.py -- --entrada <scene.gltf> --out <pasta>/<id>_casca.glb --comp 4.39
        [--razao 0.3] [--aro aro_liga14] [--pneu pneu_p185_60] [--rodas veiculos/proprios/rodas] [--frente -y] [--so-casca]

Depois: sketchfab_preparar.py com VIDRO_TODO=1 e --manter-materiais --sem-pca --meio-pela-caixa --soldar 0.0001.
Casca com ondas: grave a casca cheia (--so-casca --razao 1), alise com a alisar_lataria.py e rode de novo sobre ela com --frente +x.

1. Junta, solda (0,5 mm), tira as ilhas soltas, põe frente em +X, centra e reduz (colapso, --razao).
2. Mede a casca por raios numa grade de 5 mm: lateral (de +Y e de -Y) e topo.
3. Vidros: janela lateral é o que o raio atravessa de lado a lado acima de 0,55 m; para-brisa e vidro traseiro, o que o raio de cima
   atravessa. Para cada janela, um polinômio de poucos termos ajustado ao anel de chapa em volta (robusto: o que foge 1 cm sai) dá a
   superfície; o vidro fica 4 mm para dentro dela, face de fora e face de trás 5 mm atrás (ilhas separadas), e cobre o furo com 5 mm de folga (a borda some na chapa).
4. Rodas: as caixas de roda são o fundo da lateral que sobe acima de 0,25 m; um círculo ajustado a cada uma dá o centro. O pneu e o aro
   do kit entram no centro, encostados por dentro da lataria, e a casca sobe até o pneu tocar o chão (z = 0).
5. Assoalho: chapa plana entre as soleiras, de eixo a eixo, no material de chassi.
6. Pele de fora: a parede de ~3 cm da impressão dobra a casca (o atlas da assar_desgaste.py caía a 84 texels por metro e o kit
   esbarrava na pele de dentro). Fica só o que se vê de fora: raios de --pele-direcoes direções (esfera de Fibonacci), numa grade de
   --pele-passo m, com os vidros e uma chapa de chão de ponta a ponta tapando a cabine; face com 2 vizinhas visíveis também fica
   (3 voltas) e ilhas de menos de 200 faces saem. Fica como a casca de uma face só do Gol. --manter-parede pula o passo.
"""
import bpy, bmesh, sys, os, json, math, argparse, numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from scipy.spatial import Delaunay
from skimage import measure, morphology

ap = argparse.ArgumentParser()
ap.add_argument("--entrada", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--comp", type=float, required=True)
ap.add_argument("--razao", type=float, default=0.3)
ap.add_argument("--aro", default="aro_liga14")
ap.add_argument("--pneu", default="pneu_p185_60")
ap.add_argument("--rodas", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "veiculos", "proprios", "rodas"))
ap.add_argument("--frente", default="-y", help="eixo da frente no arquivo, depois de importado (Blender, Z para cima)")
ap.add_argument("--so-casca", action="store_true", help="grava só a casca orientada e soldada (para alisar antes de reduzir) e para")
ap.add_argument("--manter-parede", action="store_true", help="não tira a pele de dentro (a casca sai maciça, com a parede inteira)")
ap.add_argument("--pele-direcoes", type=int, default=160)
ap.add_argument("--pele-passo", type=float, default=0.012)
ap.add_argument("--z-janela", type=float, default=0.55, help="abaixo disso o furo lateral não é janela")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:])
H = 0.005

# 1. junta, solda, orienta, reduz
bpy.ops.wm.read_factory_settings(use_empty=True)
if a.entrada.lower().endswith(".stl"):
    bpy.ops.wm.stl_import(filepath=a.entrada)
else:
    bpy.ops.import_scene.gltf(filepath=a.entrada)
ms = [o for o in bpy.data.objects if o.type == "MESH"]
for o in ms:
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
    o.data.transform(M)
for o in list(bpy.data.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
for o in ms:
    o.select_set(True)
bpy.context.view_layer.objects.active = ms[0]
if len(ms) > 1:
    bpy.ops.object.join()
casca = bpy.context.view_layer.objects.active
me = casca.data
eixo = {"x": 0, "y": 1}[a.frente[-1]]
sinal = -1 if a.frente.startswith("-") else 1
P = np.array([v.co for v in me.vertices])
me.transform(Matrix.Scale(a.comp / (P[:, eixo].max() - P[:, eixo].min()), 4))
ang = math.atan2(0, 1) - math.atan2(sinal * (eixo == 1), sinal * (eixo == 0))
me.transform(Matrix.Rotation(ang, 4, "Z"))
P = np.array([v.co for v in me.vertices])
c = 0.5 * (P.min(0) + P.max(0))
me.transform(Matrix.Translation((-c[0], -c[1], -P[:, 2].min())))
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
lab, grupos = {}, []
for f in bm.faces:
    if f in lab:
        continue
    pilha, g = [f], [f]
    lab[f] = len(grupos)
    while pilha:
        x = pilha.pop()
        for e in x.edges:
            for h in e.link_faces:
                if h not in lab:
                    lab[h] = len(grupos)
                    pilha.append(h)
                    g.append(h)
    grupos.append(g)
grupos.sort(key=len)
bmesh.ops.delete(bm, geom=[f for g in grupos[:-1] for f in g], context="FACES")
bm.to_mesh(me)
bm.free()
md = casca.modifiers.new("reduz", "DECIMATE")
md.ratio = a.razao
md.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier="reduz")
me.materials.clear()
for p in me.polygons:
    p.use_smooth = True
casca.name = me.name = "carroceria"
print(f"casca: {len(grupos)} ilhas, ficou a maior; {len(me.polygons)} triângulos depois da redução")
if a.so_casca:
    bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB")
    sys.exit(0)

# 2. campos de profundidade
dg = bpy.context.evaluated_depsgraph_get()
bvh = BVHTree.FromObject(casca, dg)
xs = np.arange(-a.comp / 2 - 0.05, a.comp / 2 + 0.05, H)
zs = np.arange(0, 1.6, H)
ys = np.arange(-1.1, 1.1, H)


def campo(orig, d, us, vs):
    D = np.full((len(vs), len(us)), np.nan)
    for j, v in enumerate(vs):
        for i, u in enumerate(us):
            hit = bvh.ray_cast(orig(u, v), d, 20)
            if hit[0] is not None:
                D[j, i] = hit[3]
    return D


Y0 = 3.0
lado_e = Y0 - campo(lambda x, z: Vector((x, Y0, z)), Vector((0, -1, 0)), xs, zs)    # y da chapa vista da esquerda (+Y)
lado_d = -Y0 + campo(lambda x, z: Vector((x, -Y0, z)), Vector((0, 1, 0)), xs, zs)   # y da chapa vista da direita (-Y)
topo = Y0 - campo(lambda x, y: Vector((x, y, Y0)), Vector((0, 0, -1)), xs, ys)     # z da chapa vista de cima


def ajusta(u, v, w, termos):
    """w ~ soma c * u^i v^j, robusto: 3 voltas tirando o que foge mais de 1 cm."""
    A = np.stack([u ** i * v ** j for i, j in termos], 1)
    ok = np.ones(len(w), bool)
    for _ in range(4):
        cf = np.linalg.lstsq(A[ok], w[ok], rcond=None)[0]
        r = np.abs(A @ cf - w)
        ok = r < max(0.01, np.percentile(r, 80))
    return lambda uu, vv: np.stack([uu ** i * vv ** j for i, j in termos], -1) @ cf, float(np.sqrt(np.mean((A[ok] @ cf - w[ok]) ** 2)))


def contorno(mask):
    m = np.pad(mask, 2)
    cs = measure.find_contours(m.astype(float), 0.5)
    cmax = max(cs, key=len)
    cmax = measure.approximate_polygon(cmax, 0.7) - 2
    return cmax  # (linha, coluna) em células


def malha_vidro(nome, mask, us, vs, prof, normal_fora, espessura=0.005):
    """Vidro sobre a máscara (linhas = vs, colunas = us); prof(u, v) -> ponto 3D da face de fora."""
    cont = contorno(mask)
    lin, col = cont[:, 0], cont[:, 1]
    borda = np.stack([np.interp(col, np.arange(len(us)), us), np.interp(lin, np.arange(len(vs)), vs)], 1)
    passo = 6
    jj, ii = np.nonzero(morphology.binary_erosion(mask, morphology.disk(3)))
    sel = (jj % passo == 0) & (ii % passo == 0)
    dentro = np.stack([us[ii[sel]], vs[jj[sel]]], 1)
    pts2 = np.concatenate([borda, dentro])
    tri = Delaunay(pts2).simplices
    cen = pts2[tri].mean(1)
    ci = np.clip(np.round(np.interp(cen[:, 0], us, np.arange(len(us)))).astype(int), 0, len(us) - 1)
    cj = np.clip(np.round(np.interp(cen[:, 1], vs, np.arange(len(vs)))).astype(int), 0, len(vs) - 1)
    tri = tri[mask[cj, ci]]
    V = [prof(u, v) for u, v in pts2]
    bmv = bmesh.new()
    vv = [bmv.verts.new(p) for p in V]
    for t in tri:
        try:
            bmv.faces.new([vv[k] for k in t])
        except ValueError:
            pass
    bmesh.ops.remove_doubles(bmv, verts=bmv.verts[:], dist=1e-4)
    for f in bmv.faces:
        if f.normal.dot(normal_fora) < 0:
            f.normal_flip()
    # face de trás como ilha à parte, sem a borda: a borracha_vidro.py acha o contorno limpo da face de fora (numa placa fechada o
    # contorno ramificava na borda e o laço caía a 4 pontos)
    dup = bmesh.ops.duplicate(bmv, geom=bmv.faces[:])
    tras = [g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)]
    bmesh.ops.translate(bmv, verts=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)], vec=-normal_fora * espessura)
    bmesh.ops.reverse_faces(bmv, faces=tras)
    mv = bpy.data.meshes.new(nome)
    bmv.to_mesh(mv)
    bmv.free()
    return mv


vidros = []
medidas = {"janelas": [], "rodas": []}
# 3a. janelas laterais: o raio atravessa de lado a lado
furo = np.isnan(lado_e) & np.isnan(lado_d)
corpo_x = ~np.all(np.isnan(lado_e), 0)
furo &= corpo_x[None, :]
furo[zs < a.z_janela, :] = False
rot = measure.label(furo)
for rp in measure.regionprops(rot):
    area = rp.area * H * H
    if area < 0.01:
        continue
    m = rot == rp.label
    j0, i0, j1, i1 = rp.bbox
    if j1 >= len(zs) - 2:
        continue
    anel = morphology.binary_dilation(m, morphology.disk(8)) & ~morphology.binary_dilation(m, morphology.disk(2))
    mcob = morphology.binary_dilation(m, morphology.disk(1))
    for lado, Ycampo, s in (("e", lado_e, 1), ("d", lado_d, -1)):
        ok = anel & ~np.isnan(Ycampo)
        jj, ii = np.nonzero(ok)
        f, rms = ajusta(xs[ii], zs[jj], Ycampo[jj, ii], [(0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2)])
        prof = lambda u, v, f=f, s=s: Vector((u, float(f(np.array(u), np.array(v))) - s * 0.004, v))
        nome = f"vidro_lat_{lado}_{len(vidros)}"
        vidros.append(malha_vidro(nome, mcob, xs, zs, prof, Vector((0, s, 0))))
        medidas["janelas"].append(dict(nome=nome, area=round(area, 3), x=[round(float(xs[i0]), 3), round(float(xs[i1 - 1]), 3)],
                                       z=[round(float(zs[j0]), 3), round(float(zs[j1 - 1]), 3)], rms_cm=round(rms * 100, 2)))
# 3b. para-brisa e vidro traseiro: o raio de cima atravessa
furo_t = np.isnan(topo)
rot_fora = measure.label(np.pad(furo_t, 1, constant_values=True))[1:-1, 1:-1]
furo_t &= rot_fora != rot_fora[0, 0]          # o que o raio atravessa e não se liga à borda da grade
rot = measure.label(furo_t)
for rp in measure.regionprops(rot):
    area = rp.area * H * H
    if area < 0.15:
        continue
    m = rot == rp.label
    j0, i0, j1, i1 = rp.bbox
    anel = morphology.binary_dilation(m, morphology.disk(8)) & ~morphology.binary_dilation(m, morphology.disk(2))
    ok = anel & ~np.isnan(topo)
    jj, ii = np.nonzero(ok)
    xm = float(xs[(i0 + i1) // 2])
    f, rms = ajusta(xs[ii] - xm, ys[jj], topo[jj, ii], [(i, j) for i in range(4) for j in (0, 2, 4) if i + j <= 5])
    prof = lambda u, v, f=f, xm=xm: Vector((u, v, float(f(np.array(u - xm), np.array(v))) - 0.004))
    nome = "vidro_frente" if xm > 0 else "vidro_tras"
    vidros.append(malha_vidro(nome, morphology.binary_dilation(m, morphology.disk(1)), xs, ys, prof, Vector((math.copysign(0.5, xm), 0, 0.85)).normalized()))
    medidas["janelas"].append(dict(nome=nome, area=round(area, 3), x=[round(float(xs[i0]), 3), round(float(xs[i1 - 1]), 3)],
                                   y=[round(float(ys[j0]), 3), round(float(ys[j1 - 1]), 3)], rms_cm=round(rms * 100, 2)))

# 4. caixas de roda
fundo = np.array([zs[np.argmax(~np.isnan(lado_e[:, i]))] if not np.all(np.isnan(lado_e[:, i])) else np.nan for i in range(len(xs))])
arco = fundo > 0.25
rot = measure.label(arco)
pneu_info = {i["id"]: i for i in json.load(open(os.path.join(a.rodas, "rodas_kit.json")))["itens"]}
R = pneu_info[a.pneu]["raio_externo_cm"] / 100
largura = pneu_info[a.pneu]["largura_cm"] / 100
centros = []
for rp in measure.regionprops(rot[None, :]):
    i0, i1 = rp.bbox[1], rp.bbox[3]
    if (i1 - i0) * H < 0.4:
        continue
    xi, zi = xs[i0:i1], fundo[i0:i1]
    k = zi > zi.max() - 0.18          # a parte de cima do arco (os lados verticais perto da saia atrapalham o círculo)
    A = np.stack([xi[k], zi[k], np.ones(k.sum())], 1)
    b = xi[k] ** 2 + zi[k] ** 2
    cx, cz, cc = np.linalg.lstsq(A, b, rcond=None)[0]
    cx, cz = cx / 2, cz / 2
    ra = math.sqrt(cc + cx * cx + cz * cz)
    centros.append((float(cx), float(cz), float(ra)))
centros.sort()
assert len(centros) == 2, f"esperava 2 caixas de roda, achei {centros}"
# o centro da roda fica no centro do arco; a casca sobe até o pneu tocar o chão
cz_med = 0.5 * (centros[0][1] + centros[1][1])
dz = R - cz_med
casca.data.transform(Matrix.Translation((0, 0, dz)))
# encosto lateral: a face de fora do pneu 2,5 cm para dentro da chapa na altura do cubo
def meia_largura(x):
    i = int(np.argmin(np.abs(xs - x)))
    col = lado_e[:, i]
    zz = zs + dz
    sel = (zz > R + 0.05) & (zz < R + 0.30) & ~np.isnan(col)
    return float(np.nanmax(col[sel]))
for cx, cz, ra in centros:
    yb = min(meia_largura(cx - ra - 0.05), meia_largura(cx + ra + 0.05))
    medidas["rodas"].append(dict(x=round(cx, 4), z_arco=round(cz + dz, 4), raio_arco=round(ra, 4), y_fora=round(yb - 0.025, 4),
                                 y_cubo=round(yb - 0.025 - largura / 2, 4), folga_arco_cm=round((ra - R) * 100, 1)))
for v in vidros:
    v.transform(Matrix.Translation((0, 0, dz)))

# 5. rodas do kit e assoalho
pecas_roda = []
for item in (a.pneu + "_Ok", a.aro):
    arq = os.path.join(a.rodas, (item[:-3] if item.endswith("_Ok") else item) + ".glb")
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(arq))
    novos = [o for o in bpy.data.objects if o not in antes]
    alvo = [o for o in novos if o.type == "MESH" and o.name == item]
    assert alvo, f"{item} não está em {arq}"
    malha = alvo[0].data.copy()
    malha.transform(alvo[0].matrix_world)
    pecas_roda.append(malha)
    for o in novos:
        bpy.data.objects.remove(o)
bmr = bmesh.new()
for r in medidas["rodas"]:
    for s in (1, -1):
        for malha in pecas_roda:
            t = malha.copy()
            if s < 0:
                t.transform(Matrix.Rotation(math.pi, 4, "Z"))
            t.transform(Matrix.Translation((r["x"], s * r["y_cubo"], R)))
            bmr.from_mesh(t)
            bpy.data.meshes.remove(t)
# assoalho: retângulo entre as soleiras, 2 cm acima do fundo da casca entre os eixos
xf, xr = medidas["rodas"][1]["x"], medidas["rodas"][0]["x"]
ra_f, ra_r = medidas["rodas"][1]["raio_arco"], medidas["rodas"][0]["raio_arco"]
x0, x1 = xr + ra_r + 0.02, xf - ra_f - 0.02
i0, i1 = np.searchsorted(xs, [x0, x1])
z_sol = float(np.nanmin(fundo[i0:i1])) + dz + 0.02
y_sol = min(meia_largura(0.5 * (x0 + x1)), 0.9) - 0.06
vs_ = [bmr.verts.new(p) for p in [(x0, -y_sol, z_sol), (x1, -y_sol, z_sol), (x1, y_sol, z_sol), (x0, y_sol, z_sol)]]
bmr.faces.new(vs_)
medidas["assoalho"] = dict(x=[round(x0, 3), round(x1, 3)], meia_largura=round(y_sol, 3), z=round(z_sol, 3))
mr = bpy.data.meshes.new("rodas")
bmr.to_mesh(mr)
bmr.free()

# 6. pele de fora
if not a.manter_parede:
    bmc = bmesh.new()
    bmc.from_mesh(casca.data)
    bmc.faces.ensure_lookup_table()
    bvh_c = BVHTree.FromBMesh(bmc)
    bmo = bmesh.new()
    for v in vidros:
        bmo.from_mesh(v)
    Pc = np.array([v.co for v in casca.data.vertices])
    mn, mx = Pc.min(0), Pc.max(0)
    bmo.faces.new([bmo.verts.new(c) for c in [(mn[0] - 0.05, -0.84, z_sol), (mx[0] + 0.05, -0.84, z_sol),
                                              (mx[0] + 0.05, 0.84, z_sol), (mn[0] - 0.05, 0.84, z_sol)]])
    bvh_o = BVHTree.FromBMesh(bmo)
    cen = Vector((mn + mx) / 2)
    Rb = float(np.linalg.norm(mx - mn)) / 2
    cantos = [Vector((x, y, z)) for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    vis = np.zeros(len(bmc.faces), bool)
    ga = math.pi * (3 - math.sqrt(5))
    for k in range(a.pele_direcoes):
        zz = 1 - 2 * (k + 0.5) / a.pele_direcoes
        rr = math.sqrt(1 - zz * zz)
        d = Vector((rr * math.cos(ga * k), rr * math.sin(ga * k), zz))
        u = d.orthogonal().normalized()
        w = d.cross(u)
        pu = [(c - cen).dot(u) for c in cantos]
        pw = [(c - cen).dot(w) for c in cantos]
        for au in np.arange(min(pu), max(pu), a.pele_passo):
            for aw in np.arange(min(pw), max(pw), a.pele_passo):
                o = cen + d * (Rb + 1) + u * au + w * aw
                h = bvh_c.ray_cast(o, -d, 2 * Rb + 2)
                if h[0] is None:
                    continue
                ho = bvh_o.ray_cast(o, -d, h[3])
                if ho[0] is not None and ho[3] < h[3] - 1e-4:
                    continue
                vis[h[2]] = True
    viz = [[g.index for e in f.edges for g in e.link_faces if g is not f] for f in bmc.faces]
    for _ in range(3):
        novo = vis.copy()
        for i, nb in enumerate(viz):
            if not vis[i] and sum(vis[j] for j in nb) >= 2:
                novo[i] = True
        vis = novo
    bmesh.ops.delete(bmc, geom=[f for f in bmc.faces if not vis[f.index]], context="FACES")
    lab, grupos = {}, []
    for f in bmc.faces:
        if f in lab:
            continue
        pilha, g = [f], [f]
        lab[f] = len(grupos)
        while pilha:
            x = pilha.pop()
            for e in x.edges:
                for h in e.link_faces:
                    if h not in lab:
                        lab[h] = len(grupos)
                        pilha.append(h)
                        g.append(h)
        grupos.append(g)
    peq = [f for g in grupos if len(g) < 200 for f in g]
    bmesh.ops.delete(bmc, geom=peq, context="FACES")
    bmesh.ops.delete(bmc, geom=[v for v in bmc.verts if not v.link_faces], context="VERTS")
    antes = len(casca.data.polygons)
    bmc.to_mesh(casca.data)
    bmc.free()
    bmo.free()
    casca.data.update()
    medidas["pele_de_fora"] = dict(faces_antes=antes, faces_depois=len(casca.data.polygons), ilhas_pequenas_tiradas=len(peq))
    print(f"pele de fora: {antes} -> {len(casca.data.polygons)} faces")

# 7. materiais com os nomes dos papéis (rode a preparação com --manter-materiais): a parede funda da caixa de roda (a casca maciça
# tem a soleira e o fundo do para-lama cheios, e a parede saía pintada como uma placa dentro do arco) vai para `chassi`
mats = {}
for nome in ("pintura", "chassi", "vidro"):
    mats[nome] = bpy.data.materials.new(nome)
cme = casca.data
cme.materials.clear()
cme.materials.append(mats["pintura"])
cme.materials.append(mats["chassi"])
n_poco = 0
for p in cme.polygons:
    c = p.center
    for r in medidas["rodas"]:
        if math.hypot(c.x - r["x"], c.z - R) < r["raio_arco"] + 0.04 and abs(c.y) < r["y_fora"] + 0.005:
            p.material_index = 1
            n_poco += 1
            break
medidas["faces_caixa_de_roda_chassi"] = n_poco
print(f"caixas de roda: {n_poco} faces da parede de dentro em chassi")
# saída: 3 objetos (carroceria, vidros, rodas)
bmv = bmesh.new()
for v in vidros:
    bmv.from_mesh(v)
mv = bpy.data.meshes.new("vidros")
bmv.to_mesh(mv)
bmv.free()
mv.materials.append(mats["vidro"])
for nome, malha in (("vidros", mv), ("rodas", mr)):
    o = bpy.data.objects.new(nome, malha)
    bpy.context.scene.collection.objects.link(o)
    for p in malha.polygons:
        p.use_smooth = nome == "rodas"
Pt = np.array([v.co for v in casca.data.vertices])
medidas.update(desloc_z=round(dz, 4), altura=round(float(Pt[:, 2].max()), 4), entre_eixos=round(xf - xr, 4),
               raio_pneu=R, aro=a.aro, pneu=a.pneu, triangulos=len(casca.data.polygons))
bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB")
json.dump(medidas, open(a.out[:-4] + "_medidas.json", "w"), indent=1, ensure_ascii=False)
print(json.dumps(medidas, indent=1, ensure_ascii=False))
