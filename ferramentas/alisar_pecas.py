"""
Chapa de carro novo por painel (pedido do Felipe de 27/10/2026: "faça tudo até ficar perfeito"; a referência é carro de estúdio com
reflexo reto). Roda no GLB do carro_quebravel (as peças já separadas) e troca a chapa pintada de cada painel por uma superfície lisa
ajustada a ela: B-spline cúbica com poucos pontos de controle (um a cada --passo cm) e penalidade de curvatura. Uma superfície assim não
tem como ondular: é como uma chapa estampada. O que foge mais que --robusto mm da superfície (maçaneta, friso, borda da caixa de roda)
fica como está.

Painéis: as peças (door_fl/fr, hood, trunk, fender_front_left/right) e a carroceria (body) num conjunto só, separadas por 13 direções de
chapa, abaixo e acima da cintura e, dentro disso, por pedaço de chapa ligado. Com fresta 0 a lateral inteira (para-lama, porta e lateral
traseira) é um pedaço só e o reflexo atravessa as emendas reto.
Só as faces da pintura (o lado de fora) entram.

Por padrão (--max-mm 0) os vértices não andam: só a normal sai da superfície ajustada. É o que o reflexo enxerga, e assim o mapa, as
peças e as frestas continuam valendo (deslocar a forma abria rachas entre as peças nos testes de 27/10/2026).

    python -I ferramentas/alisar_pecas.py -- <corte>.glb <mapa>.json <saida>.glb [--passo 30] [--robusto 10] [--max-mm 0]

Medida de cada pedaço no fim: desvio da chapa em volta da superfície ajustada (p50 e p90).
"""
import sys
import json
import numpy as np
import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, mapa_path, sai = args[0], args[1], args[2]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


PASSO, ROBUST, MAX_MM = opt("--passo", 30.0) / 100, opt("--robusto", 10.0) / 1000, opt("--max-mm", 0.0) / 1000
ROBUST_CIMA = opt("--robusto-cima", 25.0) / 1000   # acima da cintura (colunas, quadros, teto) não há detalhe a preservar: aceita mais
LAM = opt("--lam", 1e-4)
med = json.load(open(mapa_path, encoding="utf-8"))["medidas"]
CINT, XF, XR, R = med["linha_de_cintura"], med["eixo_dianteiro"], med["eixo_traseiro"], med["raio_roda"]


def bspline(x, lo, hi, step):
    n_int = max(2, int(np.ceil((hi - lo) / step)))
    h = (hi - lo) / n_int
    t = np.clip((x - lo) / h, 0, n_int - 1e-9)
    i = np.floor(t).astype(int)
    f = t - i
    b = np.stack([(1 - f) ** 3 / 6, (3 * f ** 3 - 6 * f ** 2 + 4) / 6, (-3 * f ** 3 + 3 * f ** 2 + 3 * f + 1) / 6, f ** 3 / 6], 1)
    db = np.stack([-(1 - f) ** 2 / 2, (9 * f ** 2 - 12 * f) / 6, (-9 * f ** 2 + 6 * f + 3) / 6, f ** 2 / 2], 1) / h
    n = n_int + 3
    B, D = np.zeros((len(x), n)), np.zeros((len(x), n))
    rows = np.arange(len(x))
    for k in range(4):
        np.add.at(B, (rows, i + k), b[:, k])
        np.add.at(D, (rows, i + k), db[:, k])
    return B, D


def d2(n):
    m = np.zeros((max(n - 2, 0), n))
    for k in range(n - 2):
        m[k, k:k + 3] = (1, -2, 1)
    return m


def outer_layer(P, d, cell=0.02, tol=0.015):
    """Só a camada de fora na direção d: atrás da chapa há o forro da caixa de roda e o interior do Meshy, que estragavam o ajuste."""
    a = np.cross(d, [0.0, 0.0, 1.0] if abs(d[2]) < 0.9 else [1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(d, a)
    iu = np.floor((P @ a) / cell).astype(np.int64)
    iv = np.floor((P @ b) / cell).astype(np.int64)
    key = (iu - iu.min()) * (iv.max() - iv.min() + 1) + (iv - iv.min())
    h = P @ d
    top = np.full(key.max() + 1, -1e9)
    np.maximum.at(top, key, h)
    return h >= top[key] - tol


def fit_panel(P, wts, d_hint, ROBUST=ROBUST):
    """Superfície h(u, v) no plano médio do painel. Devolve (posição nova, normal nova, usado?) por ponto e o desvio RMS antes e depois."""
    wts = wts * outer_layer(P, d_hint)
    c = np.average(P, axis=0, weights=wts)
    Q = P - c
    # direção da chapa: a de menor variância (normal do plano médio); e1 a de maior
    _, _, vt = np.linalg.svd(Q * np.sqrt(wts)[:, None], full_matrices=False)
    e1, e2, d = vt[0], vt[1], vt[2]
    u, v, h = Q @ e1, Q @ e2, Q @ d
    Bu, Du = bspline(u, u.min(), u.max(), PASSO)
    Bv, Dv = bspline(v, v.min(), v.max(), PASSO)
    ku, kv = Bu.shape[1], Bv.shape[1]
    A = (Bu[:, :, None] * Bv[:, None, :]).reshape(len(P), -1)
    Au = (Du[:, :, None] * Bv[:, None, :]).reshape(len(P), -1)
    Av = (Bu[:, :, None] * Dv[:, None, :]).reshape(len(P), -1)
    Iu, Iv = np.eye(ku), np.eye(kv)
    Pen = np.kron(d2(ku).T @ d2(ku), Iv) + np.kron(Iu, d2(kv).T @ d2(kv))
    w = wts.copy()
    for _ in range(4):
        AtW = A.T * w
        M = AtW @ A + LAM * w.sum() * Pen + 1e-9 * np.eye(A.shape[1])
        coef = np.linalg.solve(M, AtW @ h)
        r = A @ coef - h
        w = np.where(np.abs(r) > ROBUST, 0.0, wts)
    # transição suave: até ROBUST anda inteiro, some em 3 x ROBUST (antes era tudo ou nada e saía em retalhos)
    t = np.clip((np.abs(r) - ROBUST) / (2 * ROBUST), 0, 1)
    soft = (1 - t * t * (3 - 2 * t)) * (wts > 0)
    used = soft > 0
    move = np.clip(r, -MAX_MM, MAX_MM) * soft
    newP = P + move[:, None] * d[None, :]
    hu, hv = Au @ coef, Av @ coef
    n = d[None, :] - hu[:, None] * e1[None, :] - hv[:, None] * e2[None, :]
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    # o lado de fora: a normal ajustada segue a média das normais originais
    return newP, n, used, d, r, soft


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
PIECES = ("door_fl", "door_fr", "hood", "trunk", "fender_front_left", "fender_front_right")


r2 = 2 ** -0.5
DIRS = {"+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "+X": (1, 0, 0), "-X": (-1, 0, 0),
        "+X+Z": (r2, 0, r2), "-X+Z": (-r2, 0, r2), "+Y+Z": (0, r2, r2), "-Y+Z": (0, -r2, r2),
        # a saia das portas e da lateral vira para baixo, e a frente e a traseira embaixo dos para-choques também
        "+X-Z": (r2, 0, -r2), "-X-Z": (-r2, 0, -r2), "+Y-Z": (0, r2, -r2), "-Y-Z": (0, -r2, -r2),
        # as colunas A e C e os cantos olham na diagonal do plano do chão
        "+X+Y": (r2, r2, 0), "-X+Y": (-r2, r2, 0), "+X-Y": (r2, -r2, 0), "-X-Y": (-r2, -r2, 0)}


def rotulos(n, arestas):
    """Componentes conexos de um grafo (rótulo por ponto), por propagação do menor rótulo."""
    lab = np.arange(n)
    while len(arestas):
        a, b = lab[arestas[:, 0]], lab[arestas[:, 1]]
        m = np.minimum(a, b)
        novo = lab.copy()
        np.minimum.at(novo, arestas[:, 0], m)
        np.minimum.at(novo, arestas[:, 1], m)
        novo = novo[novo]
        if (novo == lab).all():
            break
        lab = novo
    return lab


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


relatorio = []
# todas as peças pintadas num conjunto só de pontos (pela posição no mundo): com fresta 0 a borda da porta e a da carroceria são os
# mesmos pontos, e a lateral inteira (para-lama, porta, lateral traseira) entra num ajuste só; o reflexo atravessa a emenda reto,
# como num carro de verdade (antes cada peça tinha o seu e a emenda da porta com a lateral traseira saía num vinco)
pecas = [o for o in bpy.data.objects if o.type == "MESH" and (o.name in PIECES or o.name == "body")]
dados = []
for o in pecas:
    me = o.data
    names = [s_.material.name if s_.material else "" for s_ in o.material_slots]
    n_loops = len(me.loops)
    cn = np.empty(n_loops * 3)
    me.corner_normals.foreach_get("vector", cn)
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    Mw = np.array(o.matrix_world)
    Rw, tw = Mw[:3, :3], Mw[:3, 3]
    cow = co.reshape(-1, 3) @ Rw.T + tw
    pmat = np.empty(len(me.polygons), np.int64)
    me.polygons.foreach_get("material_index", pmat)
    pnrm = np.empty(len(me.polygons) * 3)
    me.polygons.foreach_get("normal", pnrm)
    pnrm = pnrm.reshape(-1, 3) @ np.linalg.inv(Rw)          # normal: inversa transposta
    pnrm /= np.maximum(np.linalg.norm(pnrm, axis=1, keepdims=True), 1e-12)
    parea = np.empty(len(me.polygons))
    me.polygons.foreach_get("area", parea)
    paint = np.array([names[m].startswith("pintura") if m < len(names) else False for m in pmat])
    lv = np.empty(n_loops, np.int64)
    me.loops.foreach_get("vertex_index", lv)
    lpoly = np.repeat(np.arange(len(me.polygons)), [p_.loop_total for p_ in me.polygons])
    dados.append(dict(o=o, cn=cn.reshape(-1, 3), co=co.reshape(-1, 3), cow=cow, Rw=Rw, paint=paint, pnrm=pnrm, parea=parea,
                      lv=lv, lpoly=lpoly))
# pontos únicos de todas as peças (as cópias da costura da textura e as bordas comuns entre peças andam juntas)
todos_co = np.concatenate([d["cow"] for d in dados])
_, pid_all = np.unique(np.round(todos_co * 1e5).astype(np.int64), axis=0, return_inverse=True)
pid_all = pid_all.ravel()
npt = pid_all.max() + 1
Ppt = np.zeros((npt, 3))
Ppt[pid_all] = todos_co
k0 = 0
for d in dados:
    d["pid"] = pid_all[k0:k0 + len(d["cow"])]
    k0 += len(d["cow"])
vnorm = np.zeros((npt, 3))
varea = np.zeros(npt)
arest = []
for d in dados:
    pl = d["paint"][d["lpoly"]]
    d["pl"] = pl
    pv = d["pid"][d["lv"][pl]]
    np.add.at(vnorm, pv, d["pnrm"][d["lpoly"][pl]] * d["parea"][d["lpoly"][pl], None])
    np.add.at(varea, pv, d["parea"][d["lpoly"][pl]])
    for p_ in d["o"].data.polygons:
        if d["paint"][p_.index]:
            vs = [d["pid"][v] for v in p_.vertices]
            arest += [(vs[i], vs[(i + 1) % len(vs)]) for i in range(len(vs))]
arest = np.array(arest, np.int64).reshape(-1, 2)
vnorm /= np.maximum(np.linalg.norm(vnorm, axis=1, keepdims=True), 1e-12)
disp = np.zeros((npt, 3))
nacc = np.zeros((npt, 3))
wacc = np.zeros(npt)
# abaixo e acima da cintura (a lateral e a coluna são chapas diferentes na mesma direção), com transição suave de 10 cm
fz = smoothstep(-0.05, 0.05, Ppt[:, 2] - (CINT + 0.03))
RUIM_MM = 6.0                                   # acima disso de desvio mediano o pedaço não é uma chapa só
CORTES_X = [XR - 0.15, -0.45, 0.55, XF - 0.25]   # faixas: traseira, lateral traseira, porta, para-lama, frente
zonas = [1 - fz, fz]


def componentes(sel, wv):
    """Pedaços de chapa ligados entre si (pelas arestas das faces pintadas), cada um com o seu ajuste."""
    dentro = np.zeros(npt, bool)
    dentro[sel] = wv[sel] > 0.3
    a = arest[dentro[arest[:, 0]] & dentro[arest[:, 1]]]
    lab = rotulos(npt, a)
    nucleo = np.nonzero(dentro)[0]
    out = []
    for c in np.unique(lab[nucleo]):
        pts = nucleo[lab[nucleo] == c]
        if len(pts) >= 60:
            out.append(pts)
    if not out:
        return []
    # a borda de transição (peso até 0,3) vai junto com o pedaço mais perto
    resto = sel[wv[sel] <= 0.3]
    if len(resto):
        todos = np.concatenate(out)
        dono = np.concatenate([np.full(len(o_), i) for i, o_ in enumerate(out)])
        j = np.concatenate([((Ppt[resto[k:k + 256], None] - Ppt[todos][None]) ** 2).sum(-1).argmin(1)
                            for k in range(0, len(resto), 256)])
        out = [np.concatenate([o_, resto[dono[j] == i]]) for i, o_ in enumerate(out)]
    return out


for (dname, dv), zona in [(kv, zn) for kv in DIRS.items() for zn in zonas]:
    dv = np.array(dv, float)
    rob = ROBUST_CIMA if zona is zonas[1] else ROBUST
    wv = smoothstep(0.70, 0.90, vnorm @ dv) * (varea > 0) * zona
    sel_all = np.nonzero(wv > 0)[0]
    if len(sel_all) < 150:
        continue
    for sel in componentes(sel_all, wv):
        fits = [(sel, wv[sel])]
        newP, nfit, used, d_, r, soft = fit_panel(Ppt[sel], wv[sel] * varea[sel] + 1e-12, dv, rob)
        p50 = np.percentile(np.abs(r[wv[sel] > 0.5]) * 1000, 50) if (wv[sel] > 0.5).any() else 0
        if p50 > RUIM_MM and np.ptp(Ppt[sel, 0]) > 1.2:
            # pedaço comprido que não é uma chapa só (a diagonal do ombro junta capô, para-lama e coluna): refaz em faixas no comprimento,
            # com transição suave de 10 cm
            fx = [smoothstep(-0.05, 0.05, Ppt[sel, 0] - c) for c in CORTES_X]
            faixas = [1 - fx[0]] + [fx[i] * (1 - fx[i + 1]) for i in range(len(fx) - 1)] + [fx[-1]]
            fits = [(sel[f > 0], (wv[sel] * f)[f > 0]) for f in faixas if (f * (wv[sel] > 0.3)).sum() >= 60]
        for sub, wsub in fits:
            P = Ppt[sub]
            if len(fits) > 1 or sub is not sel:
                newP, nfit, used, d_, r, soft = fit_panel(P, wsub * varea[sub] + 1e-12, dv, rob)
            if np.dot(nfit.mean(axis=0), dv) < 0:
                nfit = -nfit
            # normal ajustada que vira mais de 60 graus da normal real do ponto não vale (num canto a superfície
            # ajustada dobra para o outro lado e o reflexo mostrava o chão numa mancha no teto)
            ww = wsub * soft * smoothstep(0.3, 0.6, (nfit * vnorm[sub]).sum(axis=1))
            disp[sub] += (newP - P) * ww[:, None]
            nacc[sub] += nfit * ww[:, None]
            wacc[sub] += ww
            pr = np.percentile(np.abs(r[wsub > 0.5]) * 1000, [50, 90]) if (wsub > 0.5).any() else (0, 0)
            relatorio.append("%s (%.1f m%s): %d pontos, desvio da chapa p50 %.1f mm, p90 %.1f mm" % (
                dname, np.ptp(P, axis=0).max(), ", em faixas" if len(fits) > 1 else "", len(sub), *pr))

ok = wacc > 1e-6
# um ponto em duas direções: a média pelos pesos; o peso total (até 1) diz quanto ele anda
disp[ok] = disp[ok] / wacc[ok, None] * np.minimum(wacc[ok], 1)[:, None]
nacc[ok] /= np.linalg.norm(nacc[ok], axis=1, keepdims=True)
for d in dados:
    me = d["o"].data
    Ri = np.linalg.inv(d["Rw"])
    me.vertices.foreach_set("co", (d["co"] + disp[d["pid"]] @ Ri.T).ravel())
    me.update()
    pid, lv, pl, cn = d["pid"], d["lv"], d["pl"], d["cn"]
    nl = nacc[pid[lv]] @ d["Rw"]                              # de volta ao espaço da peça (normal: transposta)
    wl = np.minimum(wacc[pid[lv]], 1.0) * pl
    m_ = wl[:, None] * nl + (1 - wl[:, None]) * cn
    out = m_ / np.maximum(np.linalg.norm(m_, axis=1, keepdims=True), 1e-9)
    for p_ in me.polygons:
        p_.use_smooth = True
    me.normals_split_custom_set([tuple(x) for x in out])
    me.update()

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[alisar_pecas]", linha)
