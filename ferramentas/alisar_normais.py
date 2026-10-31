"""
Normais lisas na pintura de um modelo de poucos polígonos (Caipora do Sketchfab, 31/10/2026): o modelo original tem triângulos grandes
e as normais suaves dele (que o --normais-da-original do preparo passa para a malha densa) mudam de direção em cada aresta do
triângulo original; num reflexo de carro isso aparece como capô e porta "enrugados" (no jogo e na zebra). Aqui a normal de cada canto
da pintura vira a média das normais de face da vizinhança, por alisamento repetido sobre a malha, sem atravessar vinco (aresta com
mais de --vinco graus entre as faces; os triângulos do original chegam a 30 a 50 graus um do outro nas quinas). A malha não muda, só as normais de canto; o resto (vidro, plástico, luzes) fica como veio.

    python -I ferramentas/alisar_normais.py -- <corte>.glb <saida>.glb [--raio-cm 30] [--vinco 60] [--limite 45] [--materiais pintura] [--pecas hood,door_fl,...]

Roda por último no corte (depois do assar_desgaste.py, que mantém as normais com --manter-normais).
"""
import sys
import numpy as np
import bpy

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


RAIO = opt("--raio-cm", 30.0) / 100
VINCO = np.cos(np.radians(opt("--vinco", 60.0)))
MATS = tuple(opt("--materiais", "pintura").split(","))
LIMITE = np.radians(opt("--limite", 45.0))
# --pecas: só estas peças (as chapas grandes); grade, para-choques e retrovisores são estreitos e o alisamento largo os entortava
PECAS = tuple(opt("--pecas", "").split(",")) if "--pecas" in args else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)


def alisar(o):
    me = o.data
    nomes = [s.material.name if s.material else "" for s in o.material_slots]
    alvo = np.array([n.startswith(MATS) for n in nomes] + [False])
    nf, nl = len(me.polygons), len(me.loops)
    if nf == 0:
        return None
    mi = np.empty(nf, int)
    me.polygons.foreach_get("material_index", mi)
    fsel = alvo[np.minimum(mi, len(alvo) - 1)]
    if not fsel.any():
        return None
    ls = np.empty(nf, int)
    lt = np.empty(nf, int)
    me.polygons.foreach_get("loop_start", ls)
    me.polygons.foreach_get("loop_total", lt)
    lv = np.empty(nl, int)
    me.loops.foreach_get("vertex_index", lv)
    lf = np.repeat(np.arange(nf), lt)
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    # vértices na mesma posição (a malha vem partida nas costuras de UV e de material) contam como um só
    _, vid = np.unique(np.round(co / 1e-5).astype(np.int64), axis=0, return_inverse=True)
    vid = vid.ravel()
    fn = np.empty(nf * 3)
    me.polygons.foreach_get("normal", fn)
    fn = fn.reshape(-1, 3)
    fa = np.empty(nf)
    me.polygons.foreach_get("area", fa)
    cn = np.empty(nl * 3)
    me.corner_normals.foreach_get("vector", cn)
    cn = cn.reshape(-1, 3)
    # face virada (a malha do modelo tem algumas): a normal dela é orientada pelos cantos, que já apontam para fora
    media = np.zeros((nf, 3))
    np.add.at(media, lf, cn)
    vir = np.einsum("ij,ij->i", fn, media) < 0
    fn[vir] *= -1
    sel_l = np.nonzero(fsel[lf])[0]
    # leque: cantos do mesmo vértice cujas faces se ligam por aresta lisa (sem vinco) ficam juntos (union-find)
    pai = np.arange(nl)

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    arestas = {}
    for f in np.nonzero(fsel)[0]:
        s, t = ls[f], lt[f]
        for k in range(t):
            a, b = s + k, s + (k + 1) % t
            chave = (min(vid[lv[a]], vid[lv[b]]), max(vid[lv[a]], vid[lv[b]]))
            arestas.setdefault(chave, []).append((f, a, b))
    for chave, lista in arestas.items():
        for i in range(len(lista)):
            for j in range(i + 1, len(lista)):
                f1, a1, b1 = lista[i]
                f2, a2, b2 = lista[j]
                if np.dot(fn[f1], fn[f2]) < VINCO:
                    continue
                for x in (a1, b1):
                    for y in (a2, b2):
                        if vid[lv[x]] == vid[lv[y]]:
                            rx, ry = raiz(x), raiz(y)
                            if rx != ry:
                                pai[rx] = ry
    for l in sel_l:
        raiz(l)
    leque = np.array([raiz(l) for l in range(nl)])
    ids, leque_de = np.unique(leque[sel_l], return_inverse=True)
    n_leq = len(ids)
    # normal inicial de cada leque: média das normais de face, pela área
    soma = np.zeros((n_leq, 3))
    np.add.at(soma, leque_de, fn[lf[sel_l]] * fa[lf[sel_l], None])
    # vizinhança: leques ligados por uma aresta de face (canto k e k+1 da mesma face)
    pos_l = -np.ones(nl, int)
    pos_l[sel_l] = leque_de
    nxt = np.empty(nl, int)
    for f in np.nonzero(fsel)[0]:
        s, t = ls[f], lt[f]
        nxt[s:s + t] = np.roll(np.arange(s, s + t), -1)
    A = pos_l[sel_l]
    B = pos_l[nxt[sel_l]]
    # passos de alisamento: o raio cresce com a raiz do número de passos vezes a aresta média
    el = np.linalg.norm(co[lv[sel_l]] - co[lv[nxt[sel_l]]], axis=1)
    h = max(float(np.median(el)), 1e-4)
    passos = int(min(400, max(1, (RAIO / h) ** 2)))
    n = soma / np.maximum(np.linalg.norm(soma, axis=1, keepdims=True), 1e-12)
    for _ in range(passos):
        acc = n.copy()
        np.add.at(acc, A, n[B])
        np.add.at(acc, B, n[A])
        n = acc / np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
    # a nova normal não se afasta mais que --limite graus da face do canto (inclina até lá, sem salto entre cantos vizinhos): nas
    # peças curvas e pequenas (para-lama, quina do para-choque) o alisamento largo puxaria a normal para fora da peça
    novo = n[leque_de]
    face = fn[lf[sel_l]]
    ang = np.arccos(np.clip(np.einsum("ij,ij->i", novo, face), -1, 1))
    t = np.minimum(1.0, LIMITE / np.maximum(ang, 1e-9))[:, None]
    mix = face * (1 - t) + novo * t
    cn[sel_l] = mix / np.maximum(np.linalg.norm(mix, axis=1, keepdims=True), 1e-12)
    ok = ang <= LIMITE
    me.normals_split_custom_set(cn.tolist())
    me.update()
    return len(sel_l), int(ok.sum()), passos, h


for o in [o for o in bpy.data.objects if o.type == "MESH" and (PECAS is None or o.name in PECAS)]:
    r = alisar(o)
    if r:
        print("[alisar_normais] %s: %d cantos de pintura, %d dentro do limite, %d passos (aresta mediana %.1f cm)" % (o.name, r[0], r[1], r[2], r[3] * 100))
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
