"""
Cirurgia nas bordas do carro do Meshy (decisão do Felipe de 28/10/2026: o Meshy é mais fiel ao modelo; o pedido é o Meshy sem os
borrões, não uma carroceria nova). Mantém a malha, o UV e os detalhes do Meshy e refaz só o que está amassado:

- junta as chapas pintadas (carroceria, portas, capô, tampa, para-lamas, saias) numa casca só, sem as paredes dos cortes antigos
  (tortas) e sem o forro escuro do Meshy colado por baixo da chapa (aparecia como risco preto);
- corta de novo os painéis por planos (portas até a cintura, como no corte do Meshy; capô; para-lamas; tampa), e cada face vai
  para a peça pela região em que o centro cai; a borda do corte recua meia fresta (4 mm no total) e ganha aba escura;
- corta reto o fundo das portas e põe uma saia reta no lugar da borda enrolada;
- lábio limpo em arco nas caixas de roda, por cima da borda amassada;
- (a pele de dentro escura, MI_DNVao, entra por último no pele_de_dentro.py, depois da vedação);
- para-choques inteiros pretos (as manchas vermelhas do Meshy neles são defeito).

Faróis, lanternas, grade, placas, retrovisores, vidros e rodas: os do Meshy, intocados. A malha sai sem normais próprias: rode depois o
vedacao_vidros.py (vidros lisos, chapa passada a ferro em volta deles e borrachas), o alisar_pecas.py (é ele que deixa a chapa lisa no
reflexo), o pele_de_dentro.py, e refaça o kit (carro_completo.py).

    python -I ferramentas/cirurgia_bordas.py -- <corte>.glb <mapa>.json <saida>.glb
"""
import sys
import os
import json
import numpy as np
import bpy
import bmesh
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "carroceria_limpa"))
from cortes import cortar_plano, separar, nomear, fresta_e_aba  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, mapa_path, sai = args[0], args[1], args[2]
mapa = json.load(open(mapa_path, encoding="utf-8"))
med = mapa["medidas"]
parts = {p["name"]: p for p in mapa["parts"]}
CHAPAS = ("body", "door_fl", "door_fr", "hood", "trunk", "fender_front_left", "fender_front_right", "side_skirt_left", "side_skirt_right")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}
mats = {m.name: m for m in bpy.data.materials}
for nome, cor, rug in (("pintura", (0.8, 0.1, 0.1, 1), 0.35), ("chassi", (0.03, 0.03, 0.03, 1), 0.8), ("MI_DNVao", (0.04, 0.04, 0.04, 1), 0.85)):
    if nome not in mats:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        if b:
            b.inputs["Base Color"].default_value = cor
            b.inputs["Roughness"].default_value = rug
        mats[nome] = m

# ------------------------------------------------------------------------------------------------ 1. a casca pintada, uma só
bm = bmesh.new()
MAT = {"pintura": 0, "chassi": 1, "MI_DNVao": 2}
for nome in CHAPAS:
    o = objs.get(nome)
    if o is None:
        continue
    me = o.data
    names = [s.material.name if s.material else "" for s in o.material_slots]
    b = bmesh.new()
    b.from_mesh(me)
    b.transform(o.matrix_world)
    b.verts.ensure_lookup_table()
    b.verts.index_update()
    # paredes e forro do corte antigo saem: ficam só as faces pintadas e o pouco de plástico escuro próprio do Meshy que não é parede
    pint = [f for f in b.faces if names[f.material_index].startswith("pintura")]
    borda_v = set()
    for f in pint:
        for e in f.edges:
            if sum(1 for g in e.link_faces if names[g.material_index].startswith("pintura")) == 1:
                borda_v.update(e.verts)
    bp = np.array([list(v.co) for v in borda_v]) if borda_v else np.zeros((0, 3))
    bvh_p = BVHTree.FromPolygons([list(v.co) for v in b.verts], [[v.index for v in f.verts] for f in pint]) if pint else None
    keep = []
    for f in b.faces:
        mn = names[f.material_index]
        if mn.startswith("pintura"):
            keep.append((f, 0))
        elif mn == "chassi" and len(bp):
            # parede do corte antigo: todos os vértices a menos de 2 cm da borda da pintura
            perto = all(np.min(np.linalg.norm(bp - np.array(v.co), axis=1)) < 0.02 for v in f.verts)
            # forro do Meshy colado por baixo da chapa (a menos de 1 cm e não paralelo a ela): aparecia como risco escuro
            colado = False
            if bvh_p is not None:
                loc, nor, _, dist = bvh_p.find_nearest(f.calc_center_median())
                colado = loc is not None and dist < 0.01 and f.normal.dot(nor) < 0.7
            if not perto and not colado:
                keep.append((f, 1))
    fora = [f for f in b.faces if f not in {k[0] for k in keep}]
    bmesh.ops.delete(b, geom=fora, context="FACES")
    mi = {f: m_ for f, m_ in keep}
    for f in b.faces:
        f.material_index = mi.get(f, 0)
    tmp = bpy.data.meshes.new("tmp")
    b.to_mesh(tmp)
    bm.from_mesh(tmp)
    bpy.data.meshes.remove(tmp)
    b.free()
    bpy.data.objects.remove(o)
# solda as bordas dos cortes antigos (fresta 0: as peças encostam ponto a ponto)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0008)
bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-5)
print("[cirurgia] casca: %d faces" % len(bm.faces))
bvh = BVHTree.FromBMesh(bm)

# ------------------------------------------------------------------------------------------------ 2. cortes por planos
marca = bm.edges.layers.int.new("corte")
big = 9.0
R = med["raio_roda"]
arcos = [(med["eixo_dianteiro"], R, R + 0.085), (med["eixo_traseiro"], R, R + 0.085)]
bd = parts["door_fl"]["box"]
xd0, xd1 = bd[0], bd[1]
z_belt = min(parts["glass_door_fl"]["box"][4], parts["glass_door_fr"]["box"][4]) - 0.012
z_roof = max(parts["glass_door_fl"]["box"][5], parts["glass_door_rl"]["box"][5]) + 0.025
x_cowl = parts["glass_windshield"]["box"][1]
x_rg_top = parts["glass_rear"]["box"][1]
y_capo = parts["hood"]["box"][3]
y_tampa = parts["trunk"]["box"][3] - 0.02
x_farol = min(parts["headlight_left"]["box"][0], parts["headlight_right"]["box"][0]) + 0.01
z_saia = 0.30
n = 0
for s in (1, -1):
    y0, y1 = (0.3, big) if s > 0 else (-big, -0.3)
    # porta: só a chapa abaixo da cintura, como no corte do Meshy (o quadro da janela e as colunas ficam na carroceria)
    n += cortar_plano(bm, (xd0, 0, 0), (1, 0, 0), (xd0 - 0.1, xd0 + 0.1, y0, y1, 0.0, z_belt + 0.01), marca)
    n += cortar_plano(bm, (xd1, 0, 0), (1, 0, 0), (xd1 - 0.1, xd1 + 0.1, y0, y1, 0.0, z_belt + 0.01), marca)
    # para-lama: topo traseiro na cintura (base da coluna A é carroceria) e traseira do topo no cowl
    n += cortar_plano(bm, (0, 0, z_belt - 0.005), (0, 0, 1), (xd0 - 0.02, x_cowl + 0.02, 0.55 if s > 0 else -big, big if s > 0 else -0.55,
                                                           z_belt - 0.1, z_belt + 0.1), marca)
    n += cortar_plano(bm, (x_cowl, 0, 0), (1, 0, 0), (x_cowl - 0.1, x_cowl + 0.1, 0.55 if s > 0 else -big, big if s > 0 else -0.55, 0.85, 1.45), marca)
    # capô: lateral em y = ±y_capo, da frente da porta ao bico
    n += cortar_plano(bm, (0, s * y_capo, 0), (0, 1, 0), (xd1 - 0.02, big, (y_capo - 0.1) if s > 0 else -(y_capo + 0.1),
                                                       (y_capo + 0.1) if s > 0 else -(y_capo - 0.1), 0.6, 1.45), marca)
    # para-lama: frente na borda de fora do farol
    n += cortar_plano(bm, (x_farol, 0, 0), (1, 0, 0), (x_farol - 0.1, x_farol + 0.1, 0.35 if s > 0 else -big, big if s > 0 else -0.35, -0.1, 0.95), marca)
    # tampa: laterais
    n += cortar_plano(bm, (0, s * y_tampa, 0), (0, 1, 0), (-big, x_rg_top, (y_tampa - 0.1) if s > 0 else -(y_tampa + 0.1),
                                                        (y_tampa + 0.1) if s > 0 else -(y_tampa - 0.1), 0.3, 1.45), marca)
    # saia e fundo das portas: reto, entre as caixas de roda
    xe_t, xe_d = arcos[1][0], arcos[0][0]
    n += cortar_plano(bm, (0, 0, z_saia), (0, 0, 1), (xe_t + arcos[1][2], xe_d - arcos[0][2], 0.45 if s > 0 else -big, big if s > 0 else -0.45,
                                                     z_saia - 0.1, z_saia + 0.1), marca)
# capô: frente, logo acima dos faróis (o painel da frente com faróis e grade fica na carroceria)
z_capo_f = max(parts["headlight_left"]["box"][5], parts["headlight_right"]["box"][5]) + 0.012
n += cortar_plano(bm, (0, 0, z_capo_f), (0, 0, 1), (1.6, big, -y_capo - 0.02, y_capo + 0.02, z_capo_f - 0.1, z_capo_f + 0.1), marca)
# tampa: fundo no topo do para-choque
z_tampa_f = parts["bumper_rear"]["box"][5] + 0.005
n += cortar_plano(bm, (0, 0, z_tampa_f), (0, 0, 1), (-big, -1.5, -y_tampa - 0.02, y_tampa + 0.02, z_tampa_f - 0.1, z_tampa_f + 0.1), marca)
# capô: traseira no cowl; tampa: frente no vinco do teto
n += cortar_plano(bm, (x_cowl, 0, 0), (1, 0, 0), (x_cowl - 0.1, x_cowl + 0.1, -y_capo - 0.02, y_capo + 0.02, 0.6, 1.45), marca,
                  normal=lambda nv: nv.z > 0.3)
n += cortar_plano(bm, (x_rg_top, 0, 0), (1, 0, 0), (x_rg_top - 0.1, x_rg_top + 0.1, -y_tampa - 0.02, y_tampa + 0.02, 1.0, 1.45), marca,
                  normal=lambda nv: nv.z > 0.3)
print("[cirurgia] arestas de corte:", n)
# o que fica abaixo da saia entre as caixas de roda sai (a borda enrolada do Meshy)
xe_t, xe_d = arcos[1][0], arcos[0][0]
abaixo = [f for f in bm.faces if f.calc_center_median().z < z_saia - 0.002 and abs(f.calc_center_median().y) > 0.45
          and xe_t + arcos[1][2] < f.calc_center_median().x < xe_d - arcos[0][2]]
bmesh.ops.delete(bm, geom=abaixo, context="FACES")
print("[cirurgia] faces abaixo da saia tiradas:", len(abaixo))
# saia reta no lugar: uma tira pintada de z_saia até z_saia - 6 cm, seguindo a chapa, com a borda enrolada para dentro
saia_faces = []
for s in (1, -1):
    xs = np.arange(xe_t + arcos[1][2] + 0.005, xe_d - arcos[0][2] - 0.005, 0.02)
    ys = []
    for x in xs:
        loc, nor, _, _ = bvh.ray_cast(Vector((x, s * 1.2, z_saia + 0.012)), Vector((0, -s, 0)), 1.0)
        ys.append(abs(loc.y) if loc is not None else np.nan)
    ys = np.array(ys)
    ok = ~np.isnan(ys)
    ys = np.interp(xs, xs[ok], ys[ok]) if ok.sum() > 2 else np.full_like(xs, 0.70)
    k = np.arange(-8, 9)
    g = np.exp(-0.5 * (k / 4.0) ** 2)
    g /= g.sum()
    ysp = np.pad(ys, 8, mode="edge")
    ys = np.array([np.dot(g, ysp[i:i + 17]) for i in range(len(ys))])
    perfil = [(0.004, 0.0), (0.0, -0.03), (-0.004, -0.06), (-0.02, -0.07), (-0.05, -0.07)]   # (dy para dentro, dz)
    aneis = []
    for i, x in enumerate(xs):
        aneis.append([bm.verts.new(Vector((x, s * (ys[i] + dy), z_saia + dz))) for dy, dz in perfil])
    for i in range(len(xs) - 1):
        for j in range(len(perfil) - 1):
            f = bm.faces.new((aneis[i][j], aneis[i + 1][j], aneis[i + 1][j + 1], aneis[i][j + 1]))
            f.smooth = True
            f.normal_update()
            if f.normal.y * s < 0 and j < 3:
                f.normal_flip()
            elif j >= 3 and f.normal.z > 0:
                f.normal_flip()
            f.material_index = MAT["pintura"] if j < 2 else MAT["chassi"]
            saia_faces.append(f)
print("[cirurgia] saia reta:", len(saia_faces), "faces")

# ------------------------------------------------------------------------------------------------ 3. separa, nomeia, fresta e aba
# cada face vai para a peça pela posição do centro: os planos já passaram por todas as bordas, então a borda fica reta;
# o plástico escuro (chassi) só vai com a peça na borda das caixas de roda, o resto (poço da roda, painel da frente) é carroceria
def peca_de(f):
    c = f.calc_center_median()
    x, y, z = c.x, abs(c.y), c.z
    pint = f.material_index == MAT["pintura"]
    if xd0 < x < xd1 and y > 0.5 and z_saia - 0.002 < z < z_belt - 0.005 and pint:
        return "door_fl" if c.y > 0 else "door_fr"
    if x > x_cowl and y < y_capo and z > 0.6 and (x < 1.6 or z > z_capo_f) and pint:
        return "hood"
    if x < x_rg_top and y < y_tampa and z > z_tampa_f and (x < -1.6 or z > 1.0) and pint:
        return "trunk"
    if xd1 < x < x_farol and y > 0.45 and z < z_belt - 0.005 and not (x > x_cowl and y < y_capo and z > 0.6) \
            and (pint or (y > 0.70 and z < 0.6)):
        return "fender_front_left" if c.y > 0 else "fender_front_right"
    return "body"
pecas = {}
saia_set = set(saia_faces)
for f in bm.faces:
    pecas.setdefault("body" if f in saia_set else peca_de(f), []).append(f)
dono = {f: k for k, g in pecas.items() for f in g}
entre = [e for e in bm.edges if len(e.link_faces) == 2 and dono[e.link_faces[0]] != dono[e.link_faces[1]]]
print("[cirurgia] arestas entre peças: %d (marcadas: %d)" % (len(entre), sum(1 for e in entre if e[marca])))
bmesh.ops.split_edges(bm, edges=entre)
for nome, g in pecas.items():
    P = np.array([list(v.co) for f in g for v in f.verts])
    print("    peça %-18s faces %6d  x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f" % (nome, len(g), P[:, 0].min(), P[:, 0].max(),
          P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()))
for nome, g in pecas.items():
    fresta_e_aba(bm, g, marca, MAT["chassi"])
print("[cirurgia] peças:", {k: len(v) for k, v in pecas.items()})

# ------------------------------------------------------------------------------------------------ 4. lábio das caixas de roda
# meio tubo ao longo do arco (de 0 a 180 graus), encostado na chapa; esconde a borda amassada do Meshy
for (xe, ze, ra) in arcos:
    for s in (1, -1):
        ang = np.linspace(0.0, np.pi, 60)
        cx = xe + ra * np.cos(ang)
        cz = ze + ra * np.sin(ang)
        ys = []
        for x, z in zip(cx, cz):
            loc, nor, _, _ = bvh.find_nearest(Vector((x, s * 0.80, z)))
            ys.append(abs(loc.y) if loc is not None else 0.76)
        ys = np.array(ys)
        k = np.arange(-6, 7)
        g = np.exp(-0.5 * (k / 3.0) ** 2)
        g /= g.sum()
        ysp = np.pad(ys, 6, mode="edge")
        ys = np.array([np.dot(g, ysp[i:i + 13]) for i in range(len(ys))])
        # perfil: do lado de fora (+6 mm) enrolando para dentro da caixa (-18 mm) em arco de 90 graus
        prof = [(0.006 * np.cos(t) + 0.0, -0.012 * np.sin(t) - 0.006 * (1 - np.cos(t))) for t in np.linspace(0, np.pi / 2, 5)]
        aneis = []
        for i, a in enumerate(ang):
            rad = np.array([np.cos(a), 0.0, np.sin(a)])
            anel = []
            for (dy, dr) in prof:
                p = np.array([cx[i], s * (ys[i] + dy), cz[i]]) + rad * dr
                anel.append(bm.verts.new(Vector(p)))
            aneis.append(anel)
        for i in range(len(ang) - 1):
            for j in range(len(prof) - 1):
                f = bm.faces.new((aneis[i][j], aneis[i + 1][j], aneis[i + 1][j + 1], aneis[i][j + 1]))
                f.smooth = True
                f.normal_update()
                if f.normal.dot(Vector((-rad[0] * 0.5, s * 1.0, -rad[2] * 0.5))) < 0:     # para fora e para o centro do arco
                    f.normal_flip()
                f.material_index = MAT["pintura"] if j < 2 else MAT["chassi"]
                pecas.setdefault("body" if abs(xe - xe_t) < 0.1 else ("fender_front_left" if s > 0 else "fender_front_right"), []).append(f)
bm.normal_update()

# ------------------------------------------------------------------------------------------------ 5. objetos, pele de dentro, UV
novos = {}
uv_src = bm.loops.layers.uv.active            # o UV do Meshy (a textura da pintura) vai junto
for nome, g in pecas.items():
    bmp = bmesh.new()
    uv = bmp.loops.layers.uv.new("UVMap")
    vmap = {}
    for f in g:
        if not f.is_valid:
            continue
        vs = []
        for v in f.verts:
            if v not in vmap:
                vmap[v] = bmp.verts.new(v.co)
            vs.append(vmap[v])
        try:
            nf = bmp.faces.new(vs)           # a orientação do Meshy fica como está (um recálculo vira faces para dentro)
            nf.material_index = f.material_index
            nf.smooth = True
            for lo, ln in zip(f.loops, nf.loops):
                ln[uv].uv = lo[uv_src].uv if uv_src is not None else ((lo.vert.co.x + 2.0) / 4.0, (lo.vert.co.z + 0.2) / 1.7)
        except ValueError:
            pass
    # a pele de dentro (MI_DNVao) entra por último, no pele_de_dentro.py, depois da vedação mexer na chapa
    mp = bpy.data.meshes.new(nome)
    bmp.to_mesh(mp)
    for mn in ("pintura", "chassi", "MI_DNVao"):
        mp.materials.append(mats[mn])
    bmp.free()
    op = bpy.data.objects.new(nome, mp)
    bpy.context.scene.collection.objects.link(op)
    novos[nome] = op
    print("[cirurgia] %-20s %6d faces" % (nome, len(mp.polygons)))
bm.free()

# ------------------------------------------------------------------------------------------------ 6. para-choques inteiros pretos
for nome in ("bumper_front", "bumper_rear"):
    o = objs.get(nome)
    if o is None:
        continue
    for slot in o.material_slots:
        if slot.material and slot.material.name.startswith("pintura"):
            slot.material = mats["chassi"]

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO", use_selection=True)
print("[cirurgia] pronto:", sai)
