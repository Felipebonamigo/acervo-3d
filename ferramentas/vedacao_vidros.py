"""
Borracha de vedação lisa em volta de cada vidro do carro cortado (pedido do Felipe de 27/10/2026: "faça tudo até ficar perfeito").

O Meshy pinta o vidro na textura e o corte separa o vidro pelos triângulos: a borda sai em escada (dentes brancos de 2 a 4 cm na borda do
teto e das colunas). Um carro de verdade tem ali uma borracha preta contínua. Este script acha a borda de cada vidro, suaviza a curva
(gaussiana periódica ao longo dela), mede quanto a escada foge da curva e faz por cima uma borracha de perfil arredondado, larga o bastante
para cobrir a escada, assentada na chapa (cada ponto projetado na malha mais perto e levantado pela normal).

A borracha entra na peça pintada vizinha (porta, tampa traseira ou carroceria), com o material `chassi`: quando o vidro estoura, ela fica.
Vértices novos só no fim da malha de cada peça; o resto da malha não muda.

    python -I ferramentas/vedacao_vidros.py -- <corte>.glb <saida>.glb [--sigma 4] [--max-cm 1.8]
"""
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Vector, kdtree
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


SIGMA = opt("--sigma", 4.0) / 100       # suavização da curva da borda, em metros ao longo dela
MAX_HW = opt("--max-cm", 1.8) / 100     # meia largura máxima da borracha (vidros das portas e laterais)
MAX_HW_FIXO = opt("--max-cm-fixo", 2.5) / 100   # para-brisa e vidro traseiro: a borracha de verdade é larga e a borda do Meshy é a pior
MIN_HW = 0.008
SO_BORRACHA = "--so-borracha" in args        # só o cordão de borracha: não alisa o vidro nem passa a ferro a chapa (modelos limpos)
PASSO = 0.008                           # um ponto da borracha a cada 8 mm
ALTURA = 0.003                          # o meio da borracha fica 3 mm acima das bordas (perfil arredondado)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]


def mat_names(o):
    return [s.material.name if s.material else "" for s in o.material_slots]


def world_bm(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)   # o glTF separa os vértices nas costuras da textura
    return bm


def box_mean(M, r):
    """Média num quadrado de lado 2r+1 (separável, por soma acumulada)."""
    out = M.astype(float)
    for ax in (0, 1):
        c = np.cumsum(np.pad(out, [(r + 1, r) if a == ax else (0, 0) for a in (0, 1)]), axis=ax)
        out = (np.take(c, np.arange(2 * r + 1, c.shape[ax]), axis=ax) - np.take(c, np.arange(0, c.shape[ax] - 2 * r - 1), axis=ax)) / (2 * r + 1)
    return out


def glass_outline(tris, cell=0.003, r_open=0.02, corte=0.3):
    """
    Contorno liso da face de fora do vidro: os triângulos viram uma máscara numa grade de 3 mm no plano do vidro; a máscara é alisada
    (média num disco de ~2 cm e corte em 0,3: tira os dentes finos e enche os vãos da escada) e o contorno sai por raios a partir do centro
    (as janelas são estreladas em relação ao centro). Devolve os pontos 3D no plano do vidro e a base (c, e1, e2, d).
    """
    P = tris.reshape(-1, 3)
    c = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    e1, e2, d = vt
    uv = np.stack([(P - c) @ e1, (P - c) @ e2], 1).reshape(-1, 3, 2)
    pad = 0.06
    lo = uv.reshape(-1, 2).min(0) - pad
    hi = uv.reshape(-1, 2).max(0) + pad
    nx, ny = np.ceil((hi - lo) / cell).astype(int)
    M = np.zeros((nx, ny), bool)
    gx = lo[0] + (np.arange(nx) + 0.5) * cell
    gy = lo[1] + (np.arange(ny) + 0.5) * cell
    for t in uv:
        a, b, cc = t
        i0, i1 = np.clip(((t[:, 0].min() - lo[0]) / cell).astype(int), 0, nx), np.clip(int((t[:, 0].max() - lo[0]) / cell) + 1, 0, nx)
        j0, j1 = np.clip(((t[:, 1].min() - lo[1]) / cell).astype(int), 0, ny), np.clip(int((t[:, 1].max() - lo[1]) / cell) + 1, 0, ny)
        if i1 <= i0 or j1 <= j0:
            continue
        X, Y = np.meshgrid(gx[i0:i1], gy[j0:j1], indexing="ij")
        den = (b[1] - cc[1]) * (a[0] - cc[0]) + (cc[0] - b[0]) * (a[1] - cc[1])
        if abs(den) < 1e-14:
            continue
        l1 = ((b[1] - cc[1]) * (X - cc[0]) + (cc[0] - b[0]) * (Y - cc[1])) / den
        l2 = ((cc[1] - a[1]) * (X - cc[0]) + (a[0] - cc[0]) * (Y - cc[1])) / den
        M[i0:i1, j0:j1] |= (l1 >= -1e-9) & (l2 >= -1e-9) & (1 - l1 - l2 >= -1e-9)
    r = max(1, int(round(r_open / cell)))
    # duas médias em quadrado ~ um disco; o corte abaixo de 0,5 puxa a curva para a ponta dos dentes, e a borracha cobre de lá para dentro
    S = box_mean(box_mean(M, r // 2), r // 2) > corte
    # raios a partir do centro da máscara
    ii, jj = np.nonzero(S)
    ci, cj = ii.mean(), jj.mean()
    ang = np.linspace(0, 2 * np.pi, 1440, endpoint=False)
    pts = []
    rmax = np.hypot(nx, ny)
    for a in ang:
        tt = np.arange(0, rmax, 0.5)
        x = (ci + np.cos(a) * tt).astype(int)
        y = (cj + np.sin(a) * tt).astype(int)
        ok = (x >= 0) & (x < nx) & (y >= 0) & (y < ny)
        x, y, tt = x[ok], y[ok], tt[ok]
        inside = S[x, y]
        if not inside.any():
            continue
        k = np.nonzero(inside)[0][-1]
        pts.append((gx[x[k]], gy[y[k]]))
    pts = np.array(pts)
    return c + pts[:, :1] * e1 + pts[:, 1:2] * e2, (c, e1, e2, d), uv


def ponto_dentro(px, py, poly):
    """Par-ímpar no plano do vidro."""
    x, y = poly[:, 0], poly[:, 1]
    xj, yj = np.roll(x, 1), np.roll(y, 1)
    cruza = ((y > py) != (yj > py)) & (px < x + (py - y) * (xj - x) / (yj - y + 1e-15))
    return bool(cruza.sum() % 2)


def resample_closed(P, step):
    Q = np.vstack([P, P[:1]])
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    L = s[-1]
    n = max(16, int(np.ceil(L / step)))
    t = np.linspace(0, L, n, endpoint=False)
    return np.stack([np.interp(t, s, Q[:, k]) for k in range(3)], 1), L


def smooth_closed(P, sigma_pts):
    n = len(P)
    k = np.arange(-int(3 * sigma_pts), int(3 * sigma_pts) + 1)
    g = np.exp(-0.5 * (k / sigma_pts) ** 2)
    g /= g.sum()
    out = np.zeros_like(P)
    for w, kk in zip(g, k):
        out += w * np.roll(P, kk, axis=0)
    return out


# BVH só da face de fora (tinta e vidro): atrás da chapa ficam a espessura e o vão escuro, e a borracha afundava neles
todos = bmesh.new()
for o in meshes:
    names = mat_names(o)
    if not any(n.startswith(("pintura", "vidro")) for n in names):
        continue
    b = world_bm(o)
    fora = [f for f in b.faces if not (f.material_index < len(names) and names[f.material_index].startswith(("pintura", "vidro")))]
    bmesh.ops.delete(b, geom=fora, context="FACES")
    me_tmp = bpy.data.meshes.new("tmp")
    b.to_mesh(me_tmp)
    todos.from_mesh(me_tmp)
    bpy.data.meshes.remove(me_tmp)
    b.free()
bvh = BVHTree.FromBMesh(todos)

DONA = {"glass_door_fl": "door_fl", "glass_door_fr": "door_fr", "glass_rear": "trunk"}

relatorio = []
VEDA = {}
for g in [o for o in meshes if o.name.startswith("glass_")]:
    bm = world_bm(g)
    bm.faces.ensure_lookup_table()
    # o vidro tem espessura: a borda que conta é a da face de fora (material vidro, virada para o lado médio do vidro)
    gn = mat_names(g)
    fv = [f for f in bm.faces if f.material_index < len(gn) and gn[f.material_index] == "vidro"]
    if not fv:
        bm.free()
        continue
    dm = sum((f.normal * f.calc_area() for f in fv), Vector())
    if dm.length < 1e-6 * max(1, len(fv)):
        # vidro de duas faces opostas (modelos do Sketchfab): a direção média se anula; o lado de fora é o que aponta para longe do carro
        cen_ = sum((f.calc_center_median() for f in fv), Vector()) / len(fv)
        dm = Vector((cen_.x if abs(cen_.x) > 1.0 else 0.0, cen_.y if abs(cen_.x) <= 1.0 else 0.0, 0.3))
    dm.normalize()
    fora = [f for f in fv if f.normal.dot(dm) > 0.3]
    if not fora:
        fora = [f for f in fv if abs(f.normal.dot(dm)) > 0.3]
    tris = []
    for f in fora:
        vs_ = [np.array(v.co) for v in f.verts]
        for k in range(1, len(vs_) - 1):
            tris.append((vs_[0], vs_[k], vs_[k + 1]))
    if not SO_BORRACHA:
        # vidro liso (28/10): a face de fora ganha uma superfície quadrática ajustada (robusta) e todos os vértices do vidro vão para ela,
        # a face de dentro na espessura mediana; o Meshy deixava um vinco vertical no vidro da porta
        Pg = np.array([list(v.co) for v in bm.verts])
        cg = Pg.mean(axis=0)
        _, _, vt = np.linalg.svd(Pg - cg, full_matrices=False)
        ea, eb, en = vt[0], vt[1], vt[2]
        if en @ np.array(dm) < 0:
            en = -en
        fora_v = set(v.index for f in fora for v in f.verts)
        U, Vv, Hh = (Pg - cg) @ ea, (Pg - cg) @ eb, (Pg - cg) @ en
        A = np.stack([np.ones_like(U), U, Vv, U * U, U * Vv, Vv * Vv, U ** 3, U * U * Vv, U * Vv * Vv, Vv ** 3], 1)
        idx = np.array(sorted(fora_v))
        wq = np.ones(len(idx))
        for _ in range(5):
            coef = np.linalg.lstsq(A[idx] * wq[:, None], Hh[idx] * wq, rcond=None)[0]
            rq = A[idx] @ coef - Hh[idx]
            wq = (np.abs(rq) < 0.006).astype(float) + 1e-3
        fit = A @ coef
        rr = Hh - fit
        # de fora ou de dentro: pela normal das faces de vidro de cada vértice (pelo desvio não dá: a face de fora amassada cai no
        # nível da de dentro e o vidro vira cacos); vértice só de parede lateral vai para o nível mais perto
        lado = np.zeros(len(Pg))
        for f in bm.faces:                                   # vidro (face de fora) e chassi (face de dentro e paredes)
            d_ = f.normal.dot(Vector(en))
            if abs(d_) > 0.3:
                for v in f.verts:
                    lado[v.index] += d_ * f.calc_area()
        dentro = lado < 0
        so_parede = lado == 0
        esp = float(np.median(rr[dentro])) if dentro.sum() > 10 else -0.004
        alvo = np.where(dentro, esp, 0.0)
        alvo[so_parede] = np.where(rr[so_parede] < esp / 2, esp, 0.0)
        bm.verts.ensure_lookup_table()
        for k, v in enumerate(bm.verts):
            v.co = Vector(Pg[k] + en * (alvo[k] - rr[k]))
        me_g = g.data
        inv_g = g.matrix_world.inverted()
        # grava no objeto (o bm tem os vértices soldados; grava pelo mais perto)
        kdg = kdtree.KDTree(len(bm.verts))
        for k, v in enumerate(bm.verts):
            kdg.insert(Vector(Pg[k]), k)
        kdg.balance()
        Mg = g.matrix_world
        for v in me_g.vertices:
            _, k, _ = kdg.find(Mg @ v.co)
            v.co = inv_g @ bm.verts[k].co
        me_g.update()
        for f in fora:
            f.normal_update()
        tris = []
        for f in fora:
            vs_ = [np.array(v.co) for v in f.verts]
            for k in range(1, len(vs_) - 1):
                tris.append((vs_[0], vs_[k], vs_[k + 1]))
        relatorio.append("    vidro liso %s: desvio p90 antes %.1f mm, espessura %.1f mm" % (g.name, np.percentile(np.abs(rr[idx]), 90) * 1000, -esp * 1000))
    bm.free()
    tris = np.array(tris)
    raw, (c0, e1, e2, d0), uv = glass_outline(tris)
    R, L = resample_closed(raw, PASSO)
    C = smooth_closed(R, SIGMA / PASSO)
    # a curva vai do plano para a chapa: o ponto mais perto na malha
    C = np.array([tuple(bvh.find_nearest(Vector(p))[0]) for p in C])
    C = smooth_closed(C, 0.03 / PASSO)                      # a projeção traz de volta o calombo da chapa: alisa de novo
    # quanto a escada foge da curva lisa: a borda crua da face de fora (arestas com uma face só do conjunto), medida no plano
    ed = {}
    for t in uv:
        for k in range(3):
            key = tuple(sorted((tuple(np.round(t[k], 5)), tuple(np.round(t[(k + 1) % 3], 5)))))
            ed[key] = ed.get(key, 0) + 1
    borda = np.array([np.array(k[0]) for k, n in ed.items() if n == 1])
    C2 = np.stack([(C - c0) @ e1, (C - c0) @ e2], 1)
    dev = np.array([np.min(np.linalg.norm(C2 - p, axis=1)) for p in borda]) if len(borda) else np.zeros(1)
    dev = dev[dev < 0.06]                                           # ilhas soltas longe da borda não contam
    hw = float(np.clip(np.percentile(dev, 90) + 0.003, MIN_HW, MAX_HW_FIXO if g.name in ("glass_windshield", "glass_rear") else MAX_HW))
    # normal da chapa e direção de lado em cada ponto
    T = np.roll(C, -1, axis=0) - np.roll(C, 1, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    rows = (-1.0, -0.6, 0.0, 0.6, 1.0)
    nr = len(rows)
    # normal da chapa ao longo do contorno, alisada (a do Meshy pula de ponto a ponto e enrugava a borracha)
    Nn = np.array([tuple(bvh.find_nearest(Vector(c))[1]) for c in C])
    Nn[(Nn @ np.array(dm)) < 0] *= -1                       # para fora: o lado da face de fora do vidro
    Nn = smooth_closed(Nn, 0.05 / PASSO)
    Nn /= np.linalg.norm(Nn, axis=1, keepdims=True)
    side = np.cross(Nn, T)
    side /= np.linalg.norm(side, axis=1, keepdims=True)
    B = C[:, None, :] + side[:, None, :] * (np.array(rows) * hw)[None, :, None]
    alt = np.full((len(C), nr), np.nan)
    for i in range(len(C)):
        for j in range(nr):
            # a superfície mais de fora embaixo do ponto: raio de 5 cm para fora, voltando
            hit = bvh.ray_cast(Vector(B[i, j] + Nn[i] * 0.05), Vector(-Nn[i]), 0.08)
            if hit[0] is not None:
                alt[i, j] = 0.05 - hit[3]
    alt = np.clip(np.where(np.isnan(alt), np.nanmedian(alt), alt), -0.01, 0.025)
    # altura única por ponto (a mais alta da seção e dos vizinhos a ±1,5 cm), alisada: cordão liso por cima dos calombos da chapa
    k = max(1, int(round(0.015 / PASSO)))
    env = np.max([np.roll(alt.max(axis=1), kk) for kk in range(-k, k + 1)], axis=0)
    env = smooth_closed(env[:, None], 0.04 / PASSO)[:, 0]
    V = np.zeros_like(B)
    for j, s_ in enumerate(rows):
        V[:, j] = B[:, j] + Nn * (env + 0.002 + ALTURA * (1 - s_ * s_))[:, None]
    gc = tris.reshape(-1, 3).mean(axis=0)
    sgn = 1.0 if np.mean(((gc - C) * side).sum(axis=1)) > 0 else -1.0     # lado positivo = para dentro do vidro
    if not SO_BORRACHA:
        # passar a ferro (28/10): o que fica serrilhado em volta do vidro vai para baixo da borracha. Chapa que invade o vidro volta para
        # o lado de fora da curva e vidro que passa da curva volta para dentro, os dois a 0,3 da meia largura e 3 mm abaixo do topo da chapa
        # ali; e chapa pintada bem dentro do vidro (o Meshy pintou retalhos por cima do vidro) é apagada.
        gc = tris.reshape(-1, 3).mean(axis=0)
        sgn = 1.0 if np.mean(((gc - C) * side).sum(axis=1)) > 0 else -1.0     # lado positivo = para dentro do vidro
        kd = kdtree.KDTree(len(C))
        for i, c in enumerate(C):
            kd.insert(Vector(c), i)
        kd.balance()
        W = hw + 0.05
        for o in meshes:
            on = mat_names(o)
            if not any(n.startswith(("pintura", "vidro")) for n in on):
                continue
            e_vidro = o.name.startswith("glass_")
            if e_vidro and o is not g:
                continue
            M, Mi = o.matrix_world, o.matrix_world.inverted()
            me_o = o.data
            apagar = set()
            mexeu = 0
            # só vértices de tinta ou vidro (as borrachas já feitas e o plástico ficam quietos)
            de_chapa = np.zeros(len(me_o.vertices), bool)
            de_tinta = np.zeros(len(me_o.vertices), bool)
            for pg in me_o.polygons:
                if on[pg.material_index].startswith(("pintura", "vidro")):
                    de_chapa[list(pg.vertices)] = True
                if on[pg.material_index].startswith("pintura"):
                    de_tinta[list(pg.vertices)] = True
            for v in me_o.vertices:
                if not de_chapa[v.index]:
                    continue
                w = M @ v.co
                _, i, dist = kd.find(w)
                rel = np.array(w) - C[i]
                h = float(rel @ Nn[i])
                s_ = float(rel @ side[i]) * sgn
                if dist > 0.15:
                    # longe da borda mas dentro do vidro (divisor serrilhado que o Meshy pintou no meio do vidro): a face sai
                    if not e_vidro and abs(float((np.array(w) - c0) @ d0)) < 0.05 and ponto_dentro(float((np.array(w) - c0) @ e1), float((np.array(w) - c0) @ e2), C2):
                        apagar.add(v.index)
                    continue
                if abs(h) > 0.05:
                    continue
                if e_vidro and not de_tinta[v.index]:
                    # vidro que passa da curva volta para dentro, debaixo da borracha
                    if s_ < -0.3 * hw:
                        v.co = Mi @ Vector(C[i] + side[i] * sgn * (-0.3 * hw) + Nn[i] * min(h, env[i] - 0.003))
                        mexeu += 1
                elif e_vidro:
                    # tinta dentro do vidro (o Meshy pintou retalhos por cima do vidro): sai
                    if s_ > 0.5 * hw:
                        apagar.add(v.index)
                else:
                    # chapa que invade o vidro vai para a faixa debaixo da borracha (um retalho inteiro dentro do vidro vira uma lasca
                    # degenerada ali, invisível); o resto da faixa só desce para baixo da borracha
                    if s_ > hw + 0.01:
                        apagar.add(v.index)
                    elif s_ > 0.3 * hw:
                        v.co = Mi @ Vector(C[i] + side[i] * sgn * (0.3 * hw) + Nn[i] * min(h, env[i] - 0.003))
                        mexeu += 1
                    elif dist <= W and h > env[i] - 0.003:
                        # o que passa da borracha desce para baixo dela (nivelar a faixa inteira achatava o friso da cintura e o
                        # reflexo mostrava manchas: não fazer)
                        v.co = Mi @ Vector(np.array(w) - Nn[i] * (h - (env[i] - 0.003)))
                        mexeu += 1
            n_ap = 0
            if apagar:
                # só faces pintadas com todos os vértices dentro do vidro e perto do plano dele
                b = bmesh.new()
                b.from_mesh(me_o)
                b.verts.ensure_lookup_table()
                fs = [f for f in b.faces if on[f.material_index].startswith("pintura") and all(x.index in apagar for x in f.verts)]
                n_ap = len(fs)
                if fs:
                    n_old_ = len(me_o.loops)
                    cn_ = np.empty(n_old_ * 3)
                    me_o.corner_normals.foreach_get("vector", cn_)
                    cn_ = cn_.reshape(-1, 3)
                    keep_loops = np.ones(n_old_, bool)
                    for f in fs:
                        for l in f.loops:
                            keep_loops[l.index] = False
                    bmesh.ops.delete(b, geom=fs, context="FACES")
                    b.to_mesh(me_o)
                    me_o.update()
                    if len(me_o.loops) == int(keep_loops.sum()):
                        me_o.normals_split_custom_set(cn_[keep_loops].tolist())
                b.free()
            if mexeu or n_ap:
                me_o.update()
                relatorio.append("    ferro %s em %s: %d vértices, %d faces pintadas dentro do vidro apagadas" % (g.name, o.name, mexeu, n_ap))
    # dona: a peça que leva o vidro no jogo (CarGlass.csv, AttachTo); o resto fica na carroceria
    best = DONA.get(g.name, "body")
    dona = bpy.data.objects[best]
    # malha da borracha, no espaço local da dona
    inv = dona.matrix_world.inverted()
    me = dona.data
    names = mat_names(dona)
    if "chassi" not in names:
        me.materials.append(bpy.data.materials.get("chassi") or bpy.data.materials.new("chassi"))
        names = mat_names(dona)
    mi = names.index("chassi")
    bmd = bmesh.new()
    bmd.from_mesh(me)
    nv = len(rows)
    vs = [[bmd.verts.new(inv @ Vector(V[i, j])) for j in range(nv)] for i in range(len(C))]
    up = inv.to_3x3()
    novas = []
    for i in range(len(C)):
        a, b = vs[i], vs[(i + 1) % len(C)]
        for j in range(nv - 1):
            f = bmd.faces.new((a[j], b[j], b[j + 1], a[j + 1]))
            f.material_index = mi
            f.smooth = True
            novas.append((f, i))
    # a face da borracha olha para fora, como a chapa embaixo dela
    for f, i in novas:
        f.normal_update()
        _, n, _, _ = bvh.find_nearest(Vector(C[i]))
        if f.normal.dot((up @ n).normalized()) < 0:
            f.normal_flip()
    # custom normals: guarda as da malha antiga e calcula as da borracha pela forma
    n_old = len(me.loops)
    cn = np.empty(n_old * 3)
    me.corner_normals.foreach_get("vector", cn)
    bmd.to_mesh(me)
    me.update()
    cn_new = np.empty(len(me.loops) * 3)
    me.corner_normals.foreach_get("vector", cn_new)
    cn_new[: n_old * 3] = cn
    me.normals_split_custom_set(cn_new.reshape(-1, 3).tolist())
    me.update()
    bmd.free()
    relatorio.append("%s -> %s: borda %.2f m, escada p90 %.1f mm, borracha %.1f cm de largura" % (
        g.name, best, L, np.percentile(dev, 90) * 1000, 2 * hw * 100))
    # guarda para as colunas: a curva, a borda de fora da borracha (lado contrário ao vidro) e a normal
    VEDA[g.name] = dict(C=C, fora=V[:, 0] if sgn > 0 else V[:, -1], N=Nn, hw=hw)

# ------------------------------------------------------------------------------------------------ colunas A e B (28/10)
# Entre duas borrachas vizinhas o Meshy deixa a coluna como um amontoado de retalhos. A coluna vira uma tira limpa (superfície regrada)
# esticada da borda de fora de uma borracha à da outra; os retalhos pintados no meio saem. As colunas são carroceria.
COLUNAS = [("glass_windshield", "glass_door_fl", 0.16), ("glass_windshield", "glass_door_fr", 0.16),
           ("glass_door_fl", "glass_door_rl", 0.16), ("glass_door_fr", "glass_door_rr", 0.16)] if "--colunas" in args else []
body = bpy.data.objects.get("body")
if body is not None:
    bn = mat_names(body)
    if "pintura" in bn:
        mi_p = bn.index("pintura")
        bmb = bmesh.new()
        bmb.from_mesh(body.data)
        Mb, Mbi = body.matrix_world, body.matrix_world.inverted()
        n_old = len(body.data.loops)
        cn = np.empty(n_old * 3)
        body.data.corner_normals.foreach_get("vector", cn)
        cn = cn.reshape(-1, 3)
        keep_loops = np.ones(n_old, bool)
        bmb.faces.ensure_lookup_table()
        apagar = set()
        tiras = []
        va = {}
        for ga, gb, dmax in COLUNAS:
            if ga not in VEDA or gb not in VEDA:
                continue
            A_, B_ = VEDA[ga], VEDA[gb]
            kdb = kdtree.KDTree(len(B_["fora"]))
            for j, q in enumerate(B_["fora"]):
                kdb.insert(Vector(q), j)
            kdb.balance()
            pares = []
            for i, p_ in enumerate(A_["fora"]):
                _, j, d = kdb.find(Vector(p_))
                pares.append(j if d < dmax else -1)
            pares = np.array(pares)
            # a sequência mais comprida de pontos pareados (a coluna); o resto da curva olha para outro lado
            melhor, atual = [], []
            for i in range(len(pares)):
                if pares[i] >= 0:
                    atual.append(i)
                else:
                    if len(atual) > len(melhor):
                        melhor = atual
                    atual = []
            if len(atual) > len(melhor):
                melhor = atual
            if len(melhor) < 6:
                continue
            seg = [(i, int(pares[i])) for i in melhor]
            # a superfície regrada entre as duas borrachas, amostrada com a normal: os vértices do Meshy no meio vão para ela
            # (projetar, e não apagar e tapar: a tira solta ficava como um adesivo colado por cima da coluna)
            amostras, normais = [], []
            for k in range(len(seg) - 1):
                i0_, j0_ = seg[k]
                i1_, j1_ = seg[k + 1]
                p0, p1 = A_["fora"][i0_], A_["fora"][i1_]
                q0, q1 = B_["fora"][j0_], B_["fora"][j1_]
                nq = np.cross(p1 - p0, q0 - p0)
                if np.linalg.norm(nq) < 1e-12:
                    nq = np.cross(p1 - p0, q1 - p0)
                nq /= max(np.linalg.norm(nq), 1e-12)
                if nq @ (A_["N"][i0_] + B_["N"][j0_]) < 0:
                    nq = -nq
                for t in np.linspace(0.0, 1.0, 12):
                    amostras.append(p0 * (1 - t) + q0 * t)
                    normais.append(nq)
            kds = kdtree.KDTree(len(amostras))
            for k, a_ in enumerate(amostras):
                kds.insert(Vector(a_), k)
            kds.balance()
            normais = np.array(normais)
            n_ap = 0
            for f in bmb.faces:
                if f.material_index != mi_p:
                    continue
                for v in f.verts:
                    if v.index in va:
                        continue
                    w = np.array(Mb @ v.co)
                    _, k, d = kds.find(Vector(w))
                    if d < 0.03:
                        h = float((w - amostras[k]) @ normais[k])
                        t = 1.0 - float(np.clip((d - 0.02) / 0.01, 0.0, 1.0))      # transição nos últimos 10 mm
                        v.co = Mbi @ Vector(w - normais[k] * (h + 0.001) * t)
                        va[v.index] = True
                        n_ap += 1
            novas = 0
            tiras.append((ga, gb, len(seg), n_ap, novas))
        if tiras:
            bmb.to_mesh(body.data)
            body.data.update()
            body.data.normals_split_custom_set(cn.tolist())
            body.data.update()
            for ga, gb, n, n_ap, novas in tiras:
                relatorio.append("    coluna %s-%s: %d pontos pareados, %d vértices projetados na superfície regrada" % (ga, gb, n, n_ap))
        bmb.free()

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[vedacao_vidros]", linha)
