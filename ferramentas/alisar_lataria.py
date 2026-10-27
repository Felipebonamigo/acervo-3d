"""
Alisa a chapa de um carro do Meshy sem mudar a forma (pedido do Felipe de 27/10/2026: "a lataria ainda não está lisa, parece massa de
modelar"; a referência é carro novo de estúdio, reflexo reto).

Método (o alisamento ponto a ponto na malha irregular do Meshy só empurrava as ondas de lugar, teste de 27/10): cada painel grande é quase
um relevo sobre um plano. Os vértices são separados pela direção da normal (pré-alisada) em 5 vistas: lateral esquerda (+Y), lateral
direita (-Y), topo (+Z), frente (+X) e traseira (-X). Em cada vista, a camada de fora (a mais saliente naquela direção, para o interior do
Meshy não se misturar) vira uma grade de alturas de --celula cm; a grade é alisada por um filtro gaussiano de --sigma cm (média ponderada
normalizada, que não puxa as bordas para dentro) e cada vértice volta para a altura alisada. Numa curva de raio R o filtro desloca a
chapa em ~sigma²/(2R): 0,6 mm na lateral (R ~3 m) e 0,9 mm no capô (R ~2 m). Onde a chapa vira (vinco, borda, caixa de roda) a normal sai
da vista e o vértice fica onde está, com transição suave. Depois refaz as normais pela malha alisada.

Rode na malha CHEIA do Meshy e só depois reduza com o decimar.py.

    python -I ferramentas/alisar_lataria.py -- <entrada.glb> <saida.glb> [--sigma 6] [--max-mm 6] [--robusto-mm 6]
        [--lado-x 150 --lado-z 8 --topo-x 60 --topo-y 25 --ponta-y 40 --ponta-z 10]   (filtro da normal por vista, em cm)

A forma anda pouco (filtro de --sigma cm, no máximo --max-mm; o que foge mais que --robusto-mm, como maçaneta e friso, não anda). O que
muda o reflexo é a normal: ela sai de uma superfície bem mais lisa, com filtro longo no comprimento do carro e curto na altura (a
inclinação de uma curva de verdade não muda com o filtro, só os calombos somem). O Meshy faz triângulos grandes e tortos na chapa lisa (a
porta do Cuiabano v2 tem ~250 vértices) e a normal interpolada entre eles era o que mais quebrava o reflexo. Testes de 27/10/2026 (listras
no verniz, meshy/previas/cuiabano-v2/): o alisamento ponto a ponto e o filtro isotrópico pioravam; este deixa as listras retas.
"""
import sys
import numpy as np
import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


SIGMA, CELL, MAX_MM, LAYER = opt("--sigma", 6.0) / 100, opt("--celula", 1.0) / 100, opt("--max-mm", 6.0) / 1000, opt("--camada-cm", 3.0) / 100
ROBUST = opt("--robusto-mm", 6.0) / 1000
TRAVA = opt("--trava-graus", 35.0)
# a normal sai de uma superfície mais lisa que a da forma: a inclinação de uma curva de verdade não muda com o filtro gaussiano (só a
# altura), então dá para filtrar mais sem mexer na forma; o reflexo fica reto como numa chapa estampada
# filtro da normal por vista, anisotrópico (cm no 1º e no 2º eixo da grade): a lateral de um carro é quase reta no comprimento e curva na
# altura (cintura, tumblehome); o capô e o teto curvam mais de lado que no comprimento
LX, LZ = opt("--lado-x", 150.0), opt("--lado-z", 8.0)
TX, TY = opt("--topo-x", 60.0), opt("--topo-y", 25.0)
PY_, PZ = opt("--ponta-y", 40.0), opt("--ponta-z", 10.0)
N_LO, N_HI = 0.80, 0.93   # |normal na direção da vista|: abaixo de N_LO o vértice não anda; acima de N_HI anda inteiro

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
o = [x for x in bpy.data.objects if x.type == "MESH"][0]
me = o.data
me.calc_loop_triangles()
nv = len(me.vertices)
co = np.empty(nv * 3)
me.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
nt = len(me.loop_triangles)
tv = np.empty(nt * 3, np.int64)
me.loop_triangles.foreach_get("vertices", tv)

# posições únicas (as costuras de UV duplicam vértices)
key = np.round(co * 1e5).astype(np.int64)
_, uid, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
inv = inv.ravel()
P = co[uid].copy()
nu = len(P)
T = inv[tv].reshape(-1, 3)

# normais por vértice, pré-alisadas (o calombo não decide a vista)
fnrm = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
vn = np.zeros((nu, 3))
for k in range(3):
    for j in range(3):
        vn[:, j] += np.bincount(T[:, k], fnrm[:, j], nu)
E = np.unique(np.sort(np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]]), axis=1), axis=0)
for _ in range(20):
    s = np.stack([np.bincount(E[:, 0], vn[E[:, 1], j], nu) + np.bincount(E[:, 1], vn[E[:, 0], j], nu) for j in range(3)], axis=1)
    vn = 0.5 * vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12) + 0.5 * s / np.maximum(np.linalg.norm(s, axis=1, keepdims=True), 1e-12)
vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)


def _conv_same(m, k):
    full = np.convolve(m, k, mode="full")            # "same" do numpy erra quando o filtro é maior que a grade
    start = (len(k) - 1) // 2
    return full[start:start + len(m)]


def gauss_blur(a, sigma_u, sigma_v=None):
    """Gaussiano separável, com sigma próprio em cada eixo da grade (em células)."""
    sigma_v = sigma_u if sigma_v is None else sigma_v
    for axis, sg in ((0, sigma_u), (1, sigma_v)):
        r = int(3 * sg)
        x = np.arange(-r, r + 1)
        k = np.exp(-0.5 * (x / max(sg, 1e-6)) ** 2)
        a = np.apply_along_axis(lambda m: _conv_same(m, k), axis, a)
    return a


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# vistas: direção para fora e dois eixos da grade (o 1º, o 2º); o filtro da normal de cada vista em cm nesses eixos. As diagonais pegam a
# chapa inclinada (tampa traseira, frente do capô, cantos do teto), que nas vistas retas ficava sem vista e com a normal torta do Meshy
r2 = 2 ** -0.5
X, Y, Z = np.eye(3)
VIEWS = (
    ("+Y", Y, X, Z, (LX, LZ)), ("-Y", -Y, X, Z, (LX, LZ)),
    ("+Z", Z, X, Y, (TX, TY)),
    ("+X", X, Y, Z, (PY_, PZ)), ("-X", -X, Y, Z, (PY_, PZ)),
    ("+X+Z", (X + Z) * r2, Y, (Z - X) * r2, (PY_, PZ * 2)), ("-X+Z", (Z - X) * r2, Y, (X + Z) * r2, (PY_, PZ * 2)),
    ("+Y+Z", (Y + Z) * r2, X, (Z - Y) * r2, (LX, LZ * 2)), ("-Y+Z", (Z - Y) * r2, X, (Y + Z) * r2, (LX, LZ * 2)),
)
# normal crua por vértice (a do Meshy, para onde nenhuma vista vale)
vn_raw = np.zeros((nu, 3))
for k in range(3):
    for j in range(3):
        vn_raw[:, j] += np.bincount(T[:, k], fnrm[:, j], nu)
vn_raw /= np.maximum(np.linalg.norm(vn_raw, axis=1, keepdims=True), 1e-12)
moveP = np.zeros((nu, 3))     # deslocamento de cada vértice
nfit = np.zeros((nu, 3))      # normal da superfície alisada (o reflexo segue ela, não os triângulos tortos do Meshy)
weight = np.zeros(nu)
wsum = np.zeros(nu)
report = []
for name, d_out, e1, e2, (s1, s2) in VIEWS:
    w = smoothstep(N_LO, N_HI, vn @ d_out)
    sel = np.nonzero(w > 0)[0]
    if len(sel) == 0:
        continue
    u, v, h = P[sel] @ e1, P[sel] @ e2, P[sel] @ d_out
    iu = np.floor((u - u.min()) / CELL).astype(int)
    iv = np.floor((v - v.min()) / CELL).astype(int)
    shape = (iu.max() + 1, iv.max() + 1)
    cell = iu * shape[1] + iv
    # camada de fora: só o que está a até LAYER da altura máxima da célula (o interior do Meshy fica fora)
    top = np.full(shape[0] * shape[1], -1e9)
    np.maximum.at(top, cell, h)
    outer = h >= top[cell] - LAYER
    sel, h, cell, w_sel = sel[outer], h[outer], cell[outer], w[sel][outer]
    use = w_sel.copy()
    # robusto: o que foge mais que ROBUST da superfície alisada (maçaneta, friso, degrau do vidro) sai da média e não anda
    for _ in range(3):
        num = np.bincount(cell, h * use, shape[0] * shape[1]).reshape(shape)
        den = np.bincount(cell, use, shape[0] * shape[1]).reshape(shape)
        hs = gauss_blur(num, SIGMA / CELL) / np.maximum(gauss_blur(den, SIGMA / CELL), 1e-9)
        target = hs.ravel()[cell]
        use = np.where(np.abs(target - h) > ROBUST, 0.0, w_sel)
    dh = np.where(np.abs(target - h) > ROBUST, 0.0, np.clip(target - h, -MAX_MM, MAX_MM))
    num = np.bincount(cell, h * use, shape[0] * shape[1]).reshape(shape)
    den = np.bincount(cell, use, shape[0] * shape[1]).reshape(shape)
    hn = gauss_blur(num, s1 / 100 / CELL, s2 / 100 / CELL) / np.maximum(gauss_blur(den, s1 / 100 / CELL, s2 / 100 / CELL), 1e-9)
    gu, gv = np.gradient(hn, CELL)
    n_view = d_out[None, :] - gu.ravel()[cell][:, None] * e1[None, :] - gv.ravel()[cell][:, None] * e2[None, :]
    n_view /= np.linalg.norm(n_view, axis=1, keepdims=True)
    # um vértice em duas vistas: a média pelos pesos (escolher a de maior peso fazia a normal saltar na troca e dobrava a tampa)
    np.add.at(moveP, sel, (w_sel * dh)[:, None] * d_out[None, :])
    np.add.at(nfit, sel, w_sel[:, None] * n_view)
    np.add.at(wsum, sel, w_sel)
    np.maximum.at(weight, sel, w_sel)
    report.append("%s %d" % (name, len(sel)))

moveP = moveP / np.maximum(wsum, 1e-9)[:, None]
nfit = nfit / np.maximum(np.linalg.norm(nfit, axis=1, keepdims=True), 1e-12)
# trava: onde a normal da superfície filtrada se afasta muito da normal média da chapa no ponto (degrau entre a tampa e o painel, que o
# filtro espalha como inclinação falsa e vira uma dobra), a conta não vale: o ponto fica com a normal média (pré-alisada)
agree = smoothstep(np.cos(np.radians(TRAVA)), np.cos(np.radians(TRAVA / 2)), np.einsum("ij,ij->i", nfit, vn))
nfit = agree[:, None] * nfit + (1 - agree[:, None]) * vn
nfit /= np.maximum(np.linalg.norm(nfit, axis=1, keepdims=True), 1e-12)
P = P + moveP * weight[:, None]
moved = np.linalg.norm(moveP, axis=1) * weight

me.vertices.foreach_set("co", P[inv].ravel())
me.update()
bpy.context.view_layer.objects.active = o
o.select_set(True)
if me.has_custom_normals:
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
for p in me.polygons:
    p.use_smooth = True
me.update()
# normais: a da superfície alisada onde a vista vale, a do Meshy nas viradas (vinco, borda), com transição suave
wb = weight[:, None]
nfin = wb * nfit + (1 - wb) * vn_raw
nfin /= np.maximum(np.linalg.norm(nfin, axis=1, keepdims=True), 1e-12)
me.normals_split_custom_set_from_vertices([tuple(n) for n in nfin[inv]])
me.update()
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
m = moved[weight > 0]
print("[alisar] %d vértices; nas vistas %s; deslocamento: média %.2f mm, p99 %.2f mm, máximo %.2f mm"
      % (nu, ", ".join(report), m.mean() * 1000, np.percentile(m, 99) * 1000, m.max() * 1000))
