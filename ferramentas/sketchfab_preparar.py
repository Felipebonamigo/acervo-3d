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
# --meio-pela-caixa (Furgãozinho, 30/10/2026): o meio em y é o da caixa da carroceria, não a média dos vértices (o bocal e o escape
# de um lado só puxavam o carro 1,3 cm, e o centro pelas janelas não acontece quando elas não passam nas regras do Gol)
MEIO_CAIXA = "--meio-pela-caixa" in a
a = [x for x in a if x not in ("--manter-materiais", "--sem-pca", "--meio-pela-caixa")]
PAPEIS_EXTRA = ("luz", "cromado", "luz_vermelha", "luz_ambar", "luz_branca", "lente_farol", "refletor")
# --juntar <config.json> (Pão de Forma, 30/10/2026): modelo de muitos objetos, cada um com seus materiais. O JSON diz o material
# nosso de cada material do arquivo ("materiais": pintura|vidro|pneu|chassi|luz|cromado|fora), quais objetos são rodas ("rodas":
# trechos do nome), caixas do arquivo cujas ilhas saem inteiras ("fora_caixas": emblema) e onde fica a frente no arquivo ("frente":
# "+x"|"-x"|"+y"|"-y"); "fora_objetos" (trechos do nome) saem; "vidros_raio" cria o vidro de uma janela que o autor deixou
# aberta (raios de fora acham o vão e a moldura; ver _vidros_por_raio). Tudo vira 3 objetos (carroceria, vidros, rodas) e cada face
# guarda o material mapeado (luz e cromado seguem para o take "material" do corte). Sem a opção, nada muda (o Gol sai igual).
CFG = None
if "--juntar" in a:
    i_ = a.index("--juntar")
    CFG = json.load(open(a[i_ + 1]))
    a = a[:i_] + a[i_ + 2:]
# --mat "Plastic_Parts=chassi,Lights_Front=luz": objeto cujo material do arquivo tem esse nome vai inteiro para o nosso material
# (pintura, vidro, pneu, chassi, luz ou cromado); serve aos modelos que já vêm separados por material (Caipora, 30/10/2026)
MAT_ENTRADA = {}
if "--mat" in a:
    i = a.index("--mat")
    MAT_ENTRADA = dict(par.split("=") for par in a[i + 1].split(","))
    del a[i:i + 2]
# --soldar 0.0005: junta vértices a essa distância (m, antes da escala) em cada objeto; modelos de sombreado chapado vêm com cada face
# solta e, sem isso, toda ilha é uma face (nem roda nem vidro são achados)
SOLDAR = 0.0
if "--soldar" in a:
    i = a.index("--soldar")
    SOLDAR = float(a[i + 1])
    del a[i:i + 2]
# --normais-da-original: depois de adensar, as normais vêm da malha de antes (lisas por ângulo), interpoladas na face mais perto.
# No baixo polígono arredondado (Caipora) os triângulos finos do adensamento davam normais tortas e a lataria refletia enrugada
NORMAIS_DA_ORIGINAL = "--normais-da-original" in a
if NORMAIS_DA_ORIGINAL:
    a.remove("--normais-da-original")
# --rodas-no-chao: roda (pneu e o aro dos objetos de roda) que o autor deixou acima do chão desce até ele; no Caipora a da frente
# flutuava 2,5 cm e o corte não acha o contato com o chão
RODAS_NO_CHAO = "--rodas-no-chao" in a
if RODAS_NO_CHAO:
    a.remove("--rodas-no-chao")
# --remapear-z "x0,x1,y0,y1,z0,z1=za,zb" (metros, já no nosso referencial): cada ilha inteira dentro da caixa passa a ocupar za a zb em
# altura. No Caipora, a fechadura da tampa descia até onde vai a placa brasileira de 13 cm; no carro real ela fica logo acima da placa
REMAPEAR_Z = []
while "--remapear-z" in a:
    i = a.index("--remapear-z")
    cx_, zz_ = a[i + 1].split("=")
    REMAPEAR_Z.append(([float(t) for t in cx_.split(",")], [float(t) for t in zz_.split(",")]))
    del a[i:i + 2]
ent, out, keep = a[0], a[1], a[2].split(",")
COMP, ALT, ARESTA = float(a[3]), float(a[4]), float(a[5])
ANGULO = float(a[6]) if len(a) > 6 else 30.0   # aresta mais dobrada do que isso fica viva; o resto é liso
SUAVIZAR = int(a[7]) if len(a) > 7 else 0        # passos de suavização (Taubin) dos vincos suaves: arredonda as facetas de baixo polígono
SOLDA = float(a[8]) if len(a) > 8 else 0.0       # junta vértices a menos disso (unidades do arquivo): pneu em triângulos soltos vira ilha de roda
TODO_VIDRO = len(a) > 9 and a[9] == "1"           # toda ilha do 2º objeto é vidro (as regras de janela são do Gol: o para-brisa do jipe é em pé)


def _vidros_por_raio(espec):
    """Janela sem vidro (a traseira do Pão de Forma): raios paralelos ao eixo "de" (ex. "+y": vêm de +y), numa grade de "passo"
    na "caixa" [t0, t1, z0, z1] (t = o eixo transversal, x ou y; z = altura), coordenadas do arquivo. Célula do vão = raio que não
    bate ou bate além de "fundo" (dentro do carro). Por fileira de z, o trecho contínuo do vão que passa mais perto do meio dá a
    borda esquerda e a direita; a profundidade de cada ponto é a da moldura logo ao lado, "recuo" para dentro. Devolve polígonos."""
    dg = bpy.context.evaluated_depsgraph_get()
    sc = bpy.context.scene
    polis = []
    for e in espec:
        ax = "xy".index(e["de"][1])
        sinal = 1.0 if e["de"][0] == "+" else -1.0
        tr = 1 - ax
        t0, t1, z0, z1 = e["caixa"]
        passo, fundo, recuo = e.get("passo", 1.0), e["fundo"], e.get("recuo", 0.8)
        ts = np.arange(t0, t1 + 1e-6, passo)
        esq, dir_ = [], []
        for z in np.arange(z0, z1 + 1e-6, passo):
            prof = []
            for t in ts:
                o_ = [0.0, 0.0, float(z)]
                o_[ax] = sinal * 1e4
                o_[tr] = float(t)
                d_ = [0.0, 0.0, 0.0]
                d_[ax] = -sinal
                hit, loc, *_ = sc.ray_cast(dg, Vector(o_), Vector(d_))
                prof.append(loc[ax] if hit else None)
            vao = [p_ is None or sinal * (p_ - fundo) < 0 for p_ in prof]
            meio = int(np.argmin(np.abs(ts - 0.5 * (t0 + t1))))
            if not vao[meio]:
                continue
            i0 = i1 = meio
            while i0 > 0 and vao[i0 - 1]:
                i0 -= 1
            while i1 < len(ts) - 1 and vao[i1 + 1]:
                i1 += 1
            if i0 == 0 or i1 == len(ts) - 1:
                continue                                   # o vão vazou da caixa: não é a janela
            for lista, i_b, t_b in ((esq, i0 - 1, ts[i0] - 0.5 * passo), (dir_, i1 + 1, ts[i1] + 0.5 * passo)):
                co = [0.0, 0.0, float(z)]
                co[tr] = float(t_b)
                co[ax] = prof[i_b] - sinal * recuo
                lista.append(Vector(co))
        if len(esq) >= 2:
            polis.append(esq + dir_[::-1])
            print("vidro novo (%s): %d pontos, z %.1f a %.1f" % (e["de"], 2 * len(esq), esq[0].z, esq[-1].z))
    return polis


def _juntar_por_material(cfg):
    """Os objetos do arquivo -> carro_corpo, carro_vidro, carro_rodas, com os materiais nossos por face (ver --juntar)."""
    mapa = cfg["materiais"]
    rodas_pat = cfg.get("rodas", [])
    caixas = [np.array(c, float) for c in cfg.get("fora_caixas", [])]
    novos = _vidros_por_raio(cfg.get("vidros_raio", []))
    mats = {}
    for nome in NOSSOS:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        mats[nome] = m
    corpo, rodas = [], []
    for o in [o for o in bpy.data.objects if o.type == "MESH"]:
        if any(t in o.name for t in cfg.get("fora_objetos", [])):     # volante, bancos: o kit põe o interior dele
            bpy.data.objects.remove(o)
            continue
        M = o.matrix_world.copy()
        o.parent = None
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_world = Matrix.Identity(4)
        o.data.transform(M)
        me = o.data
        orig = [(m.name.split(".")[0] if m else "") for m in me.materials]
        nossos = [mapa.get(n, "pintura") for n in orig]
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        fora = [f for f in bm.faces if f.material_index < len(nossos) and nossos[f.material_index] == "fora"]
        if caixas:
            # ilha inteira dentro de uma caixa sai (as letras do emblema são ilhas soltas)
            visto = set()
            for f0 in bm.faces:
                if f0.index in visto:
                    continue
                pilha, ilha = [f0], []
                visto.add(f0.index)
                while pilha:
                    f = pilha.pop()
                    ilha.append(f)
                    for e in f.edges:
                        for g in e.link_faces:
                            if g.index not in visto:
                                visto.add(g.index)
                                pilha.append(g)
                P = np.array([v.co[:] for f in ilha for v in f.verts])
                mn, mx = P.min(0), P.max(0)
                if any((mn >= c[0::2]).all() and (mx <= c[1::2]).all() for c in caixas):
                    fora.extend(ilha)
        bmesh.ops.delete(bm, geom=list(set(fora)), context="FACES")
        bm.to_mesh(me)
        bm.free()
        idx = [p.material_index for p in me.polygons]
        me.materials.clear()
        for nome in NOSSOS:
            me.materials.append(mats[nome])
            bsdf = mats[nome].node_tree.nodes["Principled BSDF"]
            bsdf.inputs["Roughness"].default_value = {"vidro": 0.05, "cromado": 0.15, "luz": 0.1}.get(nome, 0.6 if nome != "pintura" else 0.35)
            if nome in ("chassi", "pneu"):
                bsdf.inputs["Base Color"].default_value = (0.03, 0.03, 0.03, 1)
        for p, i in zip(me.polygons, idx):
            p.material_index = NOSSOS.index(nossos[i]) if i < len(nossos) and nossos[i] in NOSSOS else 0
        me.update()
        if not me.polygons:
            bpy.data.objects.remove(o)
            continue
        (rodas if any(t in o.name for t in rodas_pat) else corpo).append(o)
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o)

    def juntar(lista, nome):
        bpy.ops.object.select_all(action="DESELECT")
        for o in lista:
            o.select_set(True)
        bpy.context.view_layer.objects.active = lista[0]
        bpy.ops.object.join()
        ob = bpy.context.view_layer.objects.active
        ob.name = nome
        return ob

    ob_c = juntar(corpo, "carro_corpo")
    juntar(rodas, "carro_rodas")
    if novos:
        bm = bmesh.new()
        bm.from_mesh(ob_c.data)
        for e, poli in zip(cfg["vidros_raio"], novos):
            f = bm.faces.new([bm.verts.new(v) for v in poli])
            f.material_index = NOSSOS.index("vidro")
            f.normal_update()
            if f.normal["xy".index(e["de"][1])] * (1 if e["de"][0] == "+" else -1) < 0:
                f.normal_flip()
            bmesh.ops.triangulate(bm, faces=[f])
        bm.to_mesh(ob_c.data)
        bm.free()
    # o vidro vira objeto à parte (a detecção de janelas da preparação olha o 2º objeto)
    ob_v = ob_c.copy()
    ob_v.data = ob_c.data.copy()
    ob_v.name = "carro_vidro"
    bpy.context.scene.collection.objects.link(ob_v)
    iv = NOSSOS.index("vidro")
    for ob, manter_vidro in ((ob_c, False), (ob_v, True)):
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if (f.material_index == iv) != manter_vidro], context="FACES")
        bm.to_mesh(ob.data)
        bm.free()
    return ["carro_corpo", "carro_vidro", "carro_rodas"]


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
if MANTER:
    for m in list(bpy.data.materials):          # lista: renomear muda a ordem da coleção (cromado saía "entrada_entrada_")
        m.name = "entrada_" + m.name.split(".")[0]
NOSSOS = ("pintura", "vidro", "pneu", "chassi", "luz", "cromado")
if CFG is not None:
    keep = _juntar_por_material(CFG)
# cada item de keep pode juntar vários objetos com "+" (o 206 de 30/10 vem em 11: Body+FB+RB+Hood+LF+RF,Windows,FL+FR+RL+RR)
grupos = [k.split("+") for k in keep]
todos = [n for g in grupos for n in g]
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.name not in todos:
        bpy.data.objects.remove(o)
mat_do_obj = {n: MAT_ENTRADA.get(bpy.data.objects[n].material_slots[0].material.name.split(".")[0])
              if bpy.data.objects[n].material_slots and bpy.data.objects[n].material_slots[0].material else None for n in todos}
for o in [bpy.data.objects[n] for n in todos]:
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = Matrix.Identity(4)
    o.data.transform(M)
    if SOLDA > 0:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=SOLDA)
        bm.to_mesh(o.data)
        bm.free()
    if SOLDAR > 0:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=SOLDAR)
        # a frente do Caipora vinha com as faces viradas para dentro (o filtro de normal do corte não achava grade nem placa)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        bm.to_mesh(o.data)
        bm.free()
bpy.context.view_layer.update()
for g in grupos:
    if len(g) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for n in g:
            bpy.data.objects[n].select_set(True)
        bpy.context.view_layer.objects.active = bpy.data.objects[g[0]]
        bpy.ops.object.join()
objs = [bpy.data.objects[g[0]] for g in grupos]
# SOLDAR=<distância>: junta vértices repetidos (o 206 vem com cada triângulo solto; sem isso cada vidro vira 30 ilhas)
import os as _os
if _os.environ.get("SOLDAR"):
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        n0 = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=float(_os.environ["SOLDAR"]))
        # face repetida (o vidro de duas faces vira a mesma face duas vezes depois da solda): fica uma
        vistas, dup = set(), []
        for f in bm.faces:
            k = tuple(sorted(v.index for v in f.verts))
            if k in vistas:
                dup.append(f)
            vistas.add(k)
        bmesh.ops.delete(bm, geom=dup, context="FACES_ONLY")
        print(f"soldar {o.name}: {n0} -> {len(bm.verts)} vértices, {len(dup)} faces repetidas tiradas")
        bm.to_mesh(o.data)
        bm.free()
# TIRAR_VERSO=1: o 206 é todo em casca dupla (a chapa de dentro a menos de 2 mm da de fora, normais opostas). Os dois lados brigavam
# no sombreamento e na oclusão assada (manchas e serrilhado); o corte já dá espessura às peças. De cada par colado fica a face que
# olha para fora do carro
if _os.environ.get("TIRAR_VERSO"):
    from mathutils.bvhtree import BVHTree
    todos_p = np.concatenate([np.array([v.co for v in o.data.vertices]) for o in objs])
    ctr = Vector(0.5 * (todos_p.min(0) + todos_p.max(0)))
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        arv = BVHTree.FromBMesh(bm)
        tirar = []
        for f in bm.faces:
            c, n = f.calc_center_median(), f.normal
            loc, nrm, idx, d = arv.ray_cast(c - n * 0.0002, -n, 0.003)
            if loc is None or idx is None or nrm.dot(n) > -0.8:
                continue
            g = bm.faces[idx]
            if n.dot(c - ctr) < g.normal.dot(g.calc_center_median() - ctr):
                tirar.append(f)
        bmesh.ops.delete(bm, geom=tirar, context="FACES")
        print(f"verso {o.name}: {len(tirar)} faces de dentro tiradas, ficam {len(bm.faces)}")
        bm.to_mesh(o.data)
        bm.free()
# com --juntar: cópia das malhas com as normais do arquivo e a soma das transformações, para devolver as normais no fim
REF = [o.data.copy() for o in objs] if CFG is not None else None
TOT = Matrix.Identity(4)
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
if MEIO_CAIXA:
    c[1] = 0.5 * (P[:, 1].min() + P[:, 1].max())
w, vec = np.linalg.eigh(Q.T @ Q)
ax = vec[:, 1] if not SEM_PCA else np.array([1.0, 0.0])
R = Matrix.Rotation(-np.arctan2(ax[1], ax[0]), 4, "Z")
for o in objs:
    o.data.transform(Matrix.Translation(-Vector(c)))
    o.data.transform(R)
TOT = R @ Matrix.Translation(-Vector(c)) @ TOT
P = pts(body)
s = COMP / (P[:, 0].max() - P[:, 0].min())
for o in objs:
    o.data.transform(Matrix.Scale(s, 4))
TOT = Matrix.Scale(s, 4) @ TOT
if CFG is not None:
    # os arquivos de muitos objetos vêm com os vértices soltos nas costuras de UV: sem soldar, as normais recalculadas ficam em
    # retalhos e o teto aparece manchado
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=float(CFG.get("soldar_m", 0.0005)))
        bm.to_mesh(o.data)
        bm.free()
allP = np.concatenate([pts(o) for o in objs])
zmin, xmid = allP[:, 2].min(), 0.5 * (allP[:, 0].min() + allP[:, 0].max())
for o in objs:
    o.data.transform(Matrix.Translation(Vector((-xmid, 0, -zmin))))
TOT = Matrix.Translation(Vector((-xmid, 0, -zmin))) @ TOT
P = pts(body)
q = 0.22 * (P[:, 0].max() - P[:, 0].min())
zf = np.percentile(P[P[:, 0] > P[:, 0].max() - q, 2], 95)
zr = np.percentile(P[P[:, 0] < P[:, 0].min() + q, 2], 95)
frente_cfg = (CFG or {}).get("frente")
if frente_cfg:
    eixo_f = Vector({"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0)}[frente_cfg])
    virar = (R.to_3x3() @ eixo_f).x < 0          # num furgão a altura da frente e de trás é a mesma: o JSON manda
else:
    virar = zf > zr
if virar:
    for o in objs:
        o.data.transform(Matrix.Rotation(np.pi, 4, "Z"))
    TOT = Matrix.Rotation(np.pi, 4, "Z") @ TOT

if SOLDAR > 0:
    # face no plano de simetria (todos os vértices em |y| < 1 mm, normal lateral): barbatana interna que o autor deixou no meio do
    # para-brisa e do vidro traseiro do Caipora (aparecia como um risco no vidro e prendia 3 faces numa aresta)
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        fins = [f for f in bm.faces if all(abs(v.co.y) < 0.001 for v in f.verts) and abs(f.normal.y) > 0.9]
        if fins:
            bmesh.ops.delete(bm, geom=fins, context="FACES")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
            bm.to_mesh(o.data)
            print(f"{o.name}: {len(fins)} faces no plano de simetria tiradas")
        bm.free()
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
            if TODO_VIDRO:
                janela_idx.setdefault(o.name, []).append(g)
                medidas["vidros"][len(medidas["vidros"])] = dict(box=box, n=int(len(g)))
            elif _os.environ.get("VIDRO_TODO") or eh_janela(mn, mx, len(g)):   # VIDRO_TODO=1: o objeto dos vidros só tem vidro
                candidatas.append((o.name, g, box))
            else:
                medidas["pecas_soltas"][len(medidas["pecas_soltas"])] = dict(box=box, n=int(len(g)))
        elif o is objs[0] and tam[0] < 0.3 and tam[2] < 0.3 and abs(cen[1]) > 0.7:
            medidas["retrovisores"].append([round(float(v), 4) for v in np.concatenate([[mn[0], mx[0]], [mn[1], mx[1]], [mn[2], mx[2]]])])

if RODAS_NO_CHAO:
    obj_roda = [o for i, o in enumerate(objs) if i == 2 or mat_do_obj.get(o.name) == "pneu"]
    for nome_o, gs in rodas_idx.items():
        o = bpy.data.objects[nome_o]
        P = pts(o)
        for g in gs:
            mn, mx = P[g].min(0), P[g].max(0)
            if mn[2] < 0.003:
                continue
            ya, yb = min(abs(mn[1]), abs(mx[1])) - 0.02, max(abs(mn[1]), abs(mx[1])) + 0.02
            for o2 in obj_roda:
                for v in o2.data.vertices:
                    c = v.co
                    if mn[0] - 0.01 <= c.x <= mx[0] + 0.01 and ya <= abs(c.y) <= yb and c.y * mn[1] > 0 and mn[2] - 0.01 <= c.z <= mx[2] + 0.01:
                        c.z -= mn[2]
                o2.data.update()
            for r in medidas["rodas"]:
                if abs(r["centro"][0] - 0.5 * (mn[0] + mx[0])) < 0.05 and abs(r["centro"][1] - 0.5 * (mn[1] + mx[1])) < 0.05:
                    r["baixada"] = round(float(mn[2]), 4)
            print(f"roda em x {0.5 * (mn[0] + mx[0]):+.3f} y {0.5 * (mn[1] + mx[1]):+.3f}: {100 * mn[2]:.1f} cm acima do chão, baixada")
# janelas laterais só em par espelhado (esquerda/direita com o mesmo x e z); as largas (para-brisa, traseiro) passam direto
for nome_o, g, box in candidatas:
    larga = (box[3] - box[2]) > 0.9
    par = any(abs(b2[0] - box[0]) < 0.04 and abs(b2[4] - box[4]) < 0.04 and abs(b2[1] - box[1]) < 0.04 and
              abs(b2[2] + box[3]) < 0.12 and abs(b2[3] + box[2]) < 0.12 and (b2[3] - b2[2]) < 0.25 for _, _, b2 in candidatas)
    if larga or par or _os.environ.get("VIDRO_TODO"):
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
    TOT = Matrix.Translation(Vector((-xm, 0, 0))) @ TOT
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
    TOT = Matrix.Translation(Vector((0, -yc, 0))) @ TOT
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
# (com --juntar cada face já tem o material mapeado: nada a fazer aqui; com --mat, luz e cromado entram se algum objeto vai para eles)
NOMES_MAT = (("pintura", "vidro", "pneu", "chassi") + (PAPEIS_EXTRA if MANTER else
             tuple(n for n in ("luz", "cromado") if n in mat_do_obj.values()))) if CFG is None else ()
for nome in NOMES_MAT:
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    mats[nome] = m
tex_img = None
for m in body.data.materials:
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            tex_img = n.image
for nome, m in (mats.items() if CFG is None else ()):
    bsdf = m.node_tree.nodes["Principled BSDF"]
    if tex_img is not None and nome in ("pintura", "pneu", "vidro"):
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = tex_img
        m.node_tree.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = {"pintura": 0.35, "vidro": 0.05, "pneu": 0.8, "chassi": 0.8, "luz": 0.15, "cromado": 0.2}.get(nome, 0.3)
    if nome == "chassi":
        bsdf.inputs["Base Color"].default_value = (0.03, 0.03, 0.03, 1)
    elif MANTER and tex_img is None:
        ent_m = bpy.data.materials.get("entrada_" + nome)
        if ent_m is not None and ent_m.use_nodes and ent_m.node_tree.nodes.get("Principled BSDF"):
            bsdf.inputs["Base Color"].default_value = ent_m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value[:]
for i, o in enumerate(objs if CFG is None else ()):
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
    if mat_do_obj.get(o.name) and not rod:
        for p in me.polygons:
            p.material_index = ordem.index(mat_do_obj[o.name])
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
me = ob.data
if REMAPEAR_Z:
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    visto = set()
    for v0 in bm.verts:
        if v0.index in visto:
            continue
        pilha, ilha = [v0], []
        visto.add(v0.index)
        while pilha:
            v = pilha.pop()
            ilha.append(v)
            for e in v.link_edges:
                u = e.other_vert(v)
                if u.index not in visto:
                    visto.add(u.index)
                    pilha.append(u)
        for (x0, x1, y0, y1, z0, z1), (za, zb) in REMAPEAR_Z:
            if all(x0 <= v.co.x <= x1 and y0 <= v.co.y <= y1 and z0 <= v.co.z <= z1 for v in ilha):
                lo, hi = min(v.co.z for v in ilha), max(v.co.z for v in ilha)
                for v in ilha:
                    v.co.z = za + (v.co.z - lo) * (zb - za) / max(hi - lo, 1e-6)
                print(f"ilha de {len(ilha)} vértices: z {lo:.3f}-{hi:.3f} passou a {za:.3f}-{zb:.3f}")
    bm.to_mesh(me)
    bm.free()
    me.update()
# 5. adensa
bm = bmesh.new()
bm.from_mesh(me)
bmesh.ops.triangulate(bm, faces=bm.faces[:])
if NORMAIS_DA_ORIGINAL:
    # as normais de canto de cada triângulo de antes (lisas, vivas nas dobras de mais de ANGULO); cada face guarda de qual veio
    import math as _m0
    cam_orig = bm.faces.layers.int.new("cq_tri_orig")
    for f in bm.faces:
        f[cam_orig] = f.index
    me_g = bpy.data.meshes.new("_grossa")
    bm.to_mesh(me_g)
    bg = bmesh.new()
    bg.from_mesh(me_g)
    bg.edges.ensure_lookup_table()
    viv_g = [len(e.link_faces) == 2 and e.calc_face_angle(0.0) > _m0.radians(ANGULO) for e in bg.edges]
    bg.free()
    for p in me_g.polygons:
        p.use_smooth = True
    ag = me_g.attributes.get("sharp_edge") or me_g.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    ag.data.foreach_set("value", viv_g)
    me_g.update()
    cn = me_g.corner_normals
    tri_orig = {}
    for p in me_g.polygons:
        tri_orig[p.index] = ([Vector(me_g.vertices[me_g.loops[li].vertex_index].co) for li in p.loop_indices],
                             [Vector(cn[li].vector) for li in p.loop_indices])
    bpy.data.meshes.remove(me_g)
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
if REF is not None:
    # as normais do arquivo voltam (face achada pela normal, interpolada): o teto do furgão é um leque de triângulos finos e as
    # normais recalculadas viravam listras; o corte leva estas adiante com --manter-normais
    refs = []
    for i, m_ in enumerate(REF):
        m_.transform(TOT)
        if i != 2:                                   # as rodas não foram esticadas
            for v in m_.vertices:
                if v.co.z > z_eixo:
                    v.co.z = z_eixo + (v.co.z - z_eixo) * k
        r_ = bpy.data.objects.new("ref_%d" % i, m_)
        bpy.context.scene.collection.objects.link(r_)
        refs.append(r_)
    at.data.foreach_set("value", [False] * len(vivas))     # quem manda agora são as normais do arquivo
    mod = ob.modifiers.new("normais", "DATA_TRANSFER")
    mod.use_loop_data = True
    mod.data_types_loops = {"CUSTOM_NORMAL"}
    mod.loop_mapping = "POLYINTERP_LNORPROJ"         # projetado pela normal: o teto tem forro por dentro, a 1 cm
    bpy.ops.object.select_all(action="DESELECT")
    for r_ in refs:
        r_.select_set(True)
    bpy.context.view_layer.objects.active = refs[0]
    bpy.ops.object.join()
    mod.object = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier="normais")
    bpy.data.objects.remove(refs[0])
    print("normais do arquivo transferidas")
if NORMAIS_DA_ORIGINAL:
    from mathutils.geometry import barycentric_transform
    orig = me.attributes["cq_tri_orig"].data
    normais = [None] * len(me.loops)
    for p in me.polygons:
        (a0, a1, a2), (n0, n1, n2) = tri_orig[orig[p.index].value]
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            w = barycentric_transform(co, a0, a1, a2, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
            n = n0 * w.x + n1 * w.y + n2 * w.z
            normais[li] = (n.normalized() if n.length > 1e-9 else Vector(p.normal))[:]
    me.attributes.remove(me.attributes["cq_tri_orig"])
    me.normals_split_custom_set(normais)
    print("normais tiradas da malha antes do adensamento")
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
