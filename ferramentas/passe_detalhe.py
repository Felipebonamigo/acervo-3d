"""
Passe de detalhe dos carros nacionais (bloco 4 do plano de realismo do Detonauto, 06/11/2026; Detonauto/docs/carros-materiais.md e
docs/plano-realismo.md, item 4): o que faz um carro de jogo parecer carro de rua visto de perto e que os modelos do Sketchfab e a casca
do corte não trazem. Roda sobre o corte do carro_quebravel.py (a casca: body, door_fl, hood, trunk...) e as medidas do kit v2
(<id>_completo.json do carro_completo.py). Geometria própria, CC0 do estúdio, sem marca, logo nem texto.

    python -I ferramentas/passe_detalhe.py -- --corte <corte>/<id>.glb --kit <kit>/<id>_completo.json --id <id> --out <pasta> [--heroi]
        [--macaneta] [--friso Z] [--antena] [--sem-limpador] [--sem-espelho] [--sem-ponteira] [--sem-emblema] [--sem-folga]
    python -I ferramentas/passe_detalhe.py -- --juntar <corte>/<id>.glb <pasta>/<id>_detalhe.glb <saida>.glb
    python -I ferramentas/passe_detalhe.py -- --todos [--out-raiz veiculos/sketchfab/detalhe]      os 13 nacionais com a tabela CARROS

O que entra (cada coisa só se o carro não tiver; a tabela CARROS diz o que cada um já traz, conferido nas prévias de 06/11):
  folga      vão de porta, capô e tampa: faixa escura de 4 mm na borda de fora da chapa (o corte deixou fresta zero; carro de verdade
             tem 3 a 5 mm, que de longe é a linha escura que desenha a porta). Vai com a peça (door_*, hood, trunk).
  emblema    emblema PRÓPRIO na frente e atrás: hexágono cromado sobre base preta com três barras horizontais decrescentes (não lembra
             emblema de marca nenhuma: nada de oval, losango, círculo, gravata, H, asas, letras).
  limpador   dois braços com palheta no pé do para-brisa, deitados para o lado do carona (-Y), com o pivô e a capa (volante à esquerda).
             Pulado se a casca já tem algo sobre o vidro ali (detecção por raios).
  espelho    o vidro do retrovisor (material cromo) na face de trás de mirror_left/right, se ela não tem espelho.
  ponteira   o fim do escapamento do kit (under_escapamento) até 2 cm além do para-choque, com a ponteira cromada e o miolo escuro.
  antena     (--antena) mastro de 75 cm no para-lama da frente esquerdo, inclinado para trás.
  macaneta   (--macaneta) base preta e alça cromada perto da ponta de trás de cada porta, na cintura.
  friso      (--friso Z) borracha preta de 2,2 cm na lateral à altura Z (m), cortada por peça (o trecho da porta vai com a porta).
  heroi      (--heroi, o Cuiabano) calha de chuva no teto, esguichos no capô, luz de placa e limpador do vidro de trás.
  O disco, a pinça, o cubo e a proteção do freio já vêm no kit v2 (brake_<pos>_*), e a placa sem texto real (material placa, 40 x 13 cm)
  já vem no corte: o passe só confere e escreve no JSON. A roda de aro fundo é o aro_fundo.py.

Saída em --out: <id>_detalhe.glb (um objeto por peça seguida: det_<peça do corte>, materiais com os nomes do corte: chassi, cromo, placa,
luz_branca, pintura, vidro, para o kit_names.py do Detonauto mapear) e <id>_detalhe.json (o que entrou, onde, triângulos e o que foi
pulado e por quê). Com --juntar, cada det_<peça> é fundido na peça de mesmo nome do corte (o que não acha vai para o body) e sai um GLB
igual ao corte com o detalhe dentro: é ele que entra no lugar do corte na cadeia do Detonauto (kit_to_detonauto.py, make_crush_channels.py).

Convenção do corte: metros, frente +X, ESQUERDA +Y, cima +Z, chão em z = 0.
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, ".."))
# o repositório do jogo ao lado (o corte do Tupiniquim mora no LFS dele)
DETONAUTO = os.environ.get("DETONAUTO") or next((p for p in (os.path.join(RAIZ, "..", "detonauto"), os.path.join(RAIZ, "..", "Detonauto"))
                                                  if os.path.isdir(p)), os.path.join(RAIZ, "..", "detonauto"))

# Os 13 nacionais do Detonauto (docs/carros-nacionais.md): corte, kit e o que cada um já traz (prévias de 06/11/2026).
#   macaneta/friso/antena: o modelo não tem; limpador/espelho/ponteira False: o modelo já tem.
SK = "veiculos/sketchfab"
CARROS = {
    "gol-quadrado": dict(nome="Cuiabano", heroi=True, limpador=False, espelho=False, antena=False),
    "tupiniquim": dict(nome="Tupiniquim", corte="{detonauto}/Art/Carros/tupiniquim/quebravel/tupiniquim.glb",
                       kit="veiculos/meshy-conta/completo/tupiniquim/tupiniquim_completo.json", antena=True),
    "caipora": dict(nome="Caipora", antena=True),
    "hatch-redondo-5p": dict(nome="Pampeiro", antena="teto"),
    "barao": dict(nome="Barão", macaneta=True, friso=0.55),
    "furgaozinho": dict(nome="Furgãozinho da Firma", antena=True),
    "besouro": dict(nome="Besouro"),
    "furgao-classico": dict(nome="Pão de Forma"),
    "gaucho-v8": dict(nome="Gaúcho V8"),
    "jipe-capota": dict(nome="Trilheiro", antena=True),
    "lambari": dict(nome="Lambari", antena=True, limpador=False),
    "jabuti": dict(nome="Jabuti"),
    "sagui": dict(nome="Sagui", ponteira=False, limpador=False),
}

M_PRETO, M_CROMO, M_PINTURA, M_LUZ, M_VIDRO = "chassi", "cromo", "pintura", "luz_branca", "vidro"
COR_PREVIA = {M_PRETO: (0.028, 0.028, 0.03, 0.5, 0.0), M_CROMO: (0.62, 0.62, 0.64, 0.05, 1.0), M_PINTURA: (0.42, 0.025, 0.025, 0.25, 0.0),
              M_LUZ: (0.8, 0.8, 0.76, 0.1, 0.0), M_VIDRO: (0.1, 0.1, 0.1, 0.02, 0.0)}


# ================================================================================================================================
# casca e raios
# ================================================================================================================================

class Casca:
    """O corte num BVH só, com o nome do objeto e do material de cada face (raios que pulam o que não interessa)."""

    def __init__(self, objs):
        verts, polys, self.info = [], [], []
        self.objs = {}
        for o in objs:
            if o.type != 'MESH':
                continue
            self.objs[o.name] = o
            me = o.data
            base = len(verts)
            mw = o.matrix_world
            verts.extend(mw @ v.co for v in me.vertices)
            for p in me.polygons:
                polys.append([base + i for i in p.vertices])
                mat = me.materials[p.material_index].name if me.materials and me.materials[p.material_index] else ""
                self.info.append((o.name, mat.split(".")[0]))
        self.bvh = BVHTree.FromPolygons(verts, polys)

    def raio(self, origem, direcao, aceita=None, dist=10.0):
        """Primeiro acerto que 'aceita(obj, mat, normal)' aceita; pula o resto. (ponto, normal, obj, mat) ou None."""
        o = Vector(origem)
        d = Vector(direcao).normalized()
        andou = 0.0
        for _ in range(64):
            loc, nor, idx, dd = self.bvh.ray_cast(o, d, dist - andou)
            if loc is None:
                return None
            obj, mat = self.info[idx]
            if nor.dot(d) > 0:
                nor = -nor
            if aceita is None or aceita(obj, mat, nor):
                return loc, nor, obj, mat
            andou += dd + 0.0005
            o = loc + d * 0.0005
        return None


def nao_vidro(obj, mat, nor):
    return not obj.startswith(("glass_", "wheel_", "hubcap_")) and mat not in ("vidro",)


# ================================================================================================================================
# geometria
# ================================================================================================================================

class Geo:
    """Malha em construção: vértices, faces e o material de cada face."""

    def __init__(self):
        self.v, self.f, self.m = [], [], []

    def face(self, pts, mat):
        b = len(self.v)
        self.v.extend(Vector(p) for p in pts)
        self.f.append(list(range(b, b + len(pts))))
        self.m.append(mat)

    def caixa(self, c, ex, ey, ez, hx, hy, hz, mat):
        """Caixa centrada em c com eixos ex, ey, ez (unitários) e meias medidas."""
        c, ex, ey, ez = Vector(c), Vector(ex), Vector(ey), Vector(ez)
        p = [c + ex * sx * hx + ey * sy * hy + ez * sz * hz for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            self.face([p[i] for i in q], mat)

    def barra(self, a, b, larg, alt, cima, mat):
        """Barra retangular de a até b; 'cima' dá a direção da altura."""
        a, b = Vector(a), Vector(b)
        ex = (b - a)
        L = ex.length
        if L < 1e-5:
            return
        ex.normalize()
        ez = (Vector(cima) - ex * ex.dot(cima)).normalized()
        ey = ez.cross(ex)
        self.caixa((a + b) / 2, ex, ey, ez, L / 2, larg / 2, alt / 2, mat)

    def cilindro(self, a, b, r, mat, seg=12, tampas=True, r2=None):
        a, b = Vector(a), Vector(b)
        ax = (b - a).normalized()
        u = ax.orthogonal().normalized()
        w = ax.cross(u)
        r2 = r if r2 is None else r2
        anel = lambda c, rr: [c + (u * math.cos(t) + w * math.sin(t)) * rr for t in (2 * math.pi * i / seg for i in range(seg))]
        A, B = anel(a, r), anel(b, r2)
        for i in range(seg):
            j = (i + 1) % seg
            self.face([A[i], A[j], B[j], B[i]], mat)
        if tampas:
            self.face(list(reversed(A)), mat)
            self.face(B, mat)

    def poligono(self, c, ex, ey, ez, pts2d, esp, mat):
        """Prisma: polígono (x, y no plano ex, ey) extrudado esp ao longo de ez a partir de c."""
        c, ex, ey, ez = Vector(c), Vector(ex), Vector(ey), Vector(ez)
        base = [c + ex * x + ey * y for x, y in pts2d]
        topo = [p + ez * esp for p in base]
        n = len(base)
        self.face(list(reversed(base)), mat)
        self.face(topo, mat)
        for i in range(n):
            j = (i + 1) % n
            self.face([base[i], base[j], topo[j], topo[i]], mat)

    def anel(self, c, ex, ey, ez, pts_fora, pts_dentro, esp, mat):
        """Moldura entre dois polígonos de mesmo número de pontos, extrudada esp."""
        c, ex, ey, ez = Vector(c), Vector(ex), Vector(ey), Vector(ez)
        F = [c + ex * x + ey * y for x, y in pts_fora]
        D = [c + ex * x + ey * y for x, y in pts_dentro]
        Ft, Dt = [p + ez * esp for p in F], [p + ez * esp for p in D]
        n = len(F)
        for i in range(n):
            j = (i + 1) % n
            self.face([Ft[i], Ft[j], Dt[j], Dt[i]], mat)
            self.face([F[j], F[i], Ft[i], Ft[j]], mat)
            self.face([D[i], D[j], Dt[j], Dt[i]], mat)

    def tris(self):
        return sum(len(f) - 2 for f in self.f)


def base_na_face(nor, cima=Vector((0, 0, 1))):
    """Eixos (ex horizontal, ey 'para cima' na face, ez = normal) de um enfeite deitado na face."""
    ez = Vector(nor).normalized()
    ey = (cima - ez * ez.dot(cima))
    if ey.length < 1e-3:
        ey = Vector((1, 0, 0)) - ez * ez.x
    ey.normalize()
    ex = ey.cross(ez)
    return ex, ey, ez


# ================================================================================================================================
# os detalhes
# ================================================================================================================================

def folga(casca, partes, rel, med_cintura=0.9, largura=0.004, acima=0.0006):
    """Faixa escura na borda de fora da chapa de cada peça móvel (porta, capô, tampa)."""
    for nome in ("door_fl", "door_fr", "door_rl", "door_rr", "hood", "trunk"):
        o = casca.objs.get(nome)
        if o is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        # solda o que está a menos de 1 mm: faces soltas lado a lado no meio da chapa (o vinco do capô do Gol) davam linhas de vão falsas
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
        bm.normal_update()
        mats = [m.name.split(".")[0] if m else "" for m in o.data.materials]
        cen = sum((v.co for v in bm.verts), Vector()) / max(1, len(bm.verts))
        lado = 1.0 if cen.y > 0 else -1.0

        def de_fora(f):
            if not mats or not mats[f.material_index].startswith("pintura"):
                return False
            n = f.normal
            if nome.startswith("door_"):
                return n.y * lado > 0.35
            if nome == "hood":
                return n.z > 0.35 or n.x > 0.6
            return n.z > 0.35 or n.x < -0.35

        sel = {f.index for f in bm.faces if de_fora(f)}
        g = partes.setdefault(nome, Geo())
        n_arestas = 0
        bordas = []
        for e in bm.edges:
            fs = [f for f in e.link_faces if f.index in sel]
            if len(fs) != 1:
                continue
            f = fs[0]
            outras = [x for x in e.link_faces if x is not f]
            # borda de verdade: a malha acaba ali ou dobra para dentro (> 55 graus); troca de material no plano não é vão
            if outras and all(x.normal.dot(f.normal) > math.cos(math.radians(55)) for x in outras):
                continue
            bordas.append((e, f))
        # só as bordas que formam linhas compridas (o contorno da peça): furos e retalhos da malha davam tracinhos soltos na chapa
        pai = {}

        def raiz(i):
            while pai.get(i, i) != i:
                i = pai[i]
            return i
        for e, _ in bordas:
            a, b = raiz(e.verts[0].index), raiz(e.verts[1].index)
            if a != b:
                pai[a] = b
        comprimento = {}
        for e, _ in bordas:
            r = raiz(e.verts[0].index)
            comprimento[r] = comprimento.get(r, 0.0) + e.calc_length()
        # e só perto do contorno da peça (6 cm da caixa vista de lado na porta, de cima no capô, de trás na tampa): a casca de impressão
        # do Barão tinha bordas compridas no meio da porta, que viravam riscos
        eixos = (0, 2) if nome.startswith("door_") else ((0, 1) if nome == "hood" else (1, 2))
        lo = [min(v.co[i] for v in bm.verts) for i in eixos]
        hi = [max(v.co[i] for v in bm.verts) for i in eixos]

        def no_contorno(p, m=0.06):
            return any(p[i] - lo[k] < m or hi[k] - p[i] < m for k, i in enumerate(eixos))
        for e, f in bordas:
            if comprimento[raiz(e.verts[0].index)] < 0.30:
                continue
            meio = (e.verts[0].co + e.verts[1].co) / 2
            if not no_contorno(meio) and not (nome.startswith("door_") and meio.z > med_cintura - 0.04):
                continue
            v1, v2 = e.verts[0].co, e.verts[1].co
            ev = v2 - v1
            if ev.length < 1e-4:
                continue
            d = f.normal.cross(ev).normalized()
            if d.dot(f.calc_center_median() - (v1 + v2) / 2) < 0:
                d = -d
            up = f.normal * acima
            g.face([v1 + up, v2 + up, v2 + d * largura + up, v1 + d * largura + up], M_PRETO)
            n_arestas += 1
        bm.free()
        rel["folga"][nome] = n_arestas


def emblema_geo(g, c, nor, largura, preto=M_PRETO, cromo=M_CROMO):
    """Emblema próprio: hexágono achatado cromado sobre base preta, com três barras horizontais decrescentes."""
    ex, ey, ez = base_na_face(nor)
    a, b = largura / 2, largura * 0.30
    hexa = lambda s: [(a * s, 0), (a * 0.55 * s, b * s), (-a * 0.55 * s, b * s), (-a * s, 0), (-a * 0.55 * s, -b * s), (a * 0.55 * s, -b * s)]
    c = Vector(c) + ez * 0.0008
    g.poligono(c, ex, ey, ez, hexa(1.0), 0.002, preto)
    g.anel(c + ez * 0.002, ex, ey, ez, hexa(1.0), hexa(0.86), 0.003, cromo)
    for k, frac in enumerate((0.62, 0.46, 0.30)):
        y = b * (0.38 - 0.38 * k)
        h = b * 0.13
        g.poligono(c + ez * 0.002 + ey * y, ex, ey, ez, [(-a * frac, -h), (a * frac, -h), (a * frac, h), (-a * frac, h)], 0.0025, cromo)


def emblemas(casca, med, partes, rel):
    def ok(obj, mat, nor):
        return nao_vidro(obj, mat, nor) and not obj.startswith(("plate_", "headlight", "taillight")) and mat not in ("placa", "luz",
                                                                                                                  "lente_farol", "refletor")
    for qual, sx in (("frente", -1.0), ("tras", 1.0)):
        if qual == "frente":
            zs = [med["z_capo_frente"] - 0.06 - 0.02 * i for i in range(30)]
            zs = [z for z in zs if z > med["z_saia"] + 0.12]
            x0 = med["x_frente"] + 0.6
        else:
            topo = med["rg"][4] - 0.06
            zs = [topo - 0.02 * i for i in range(40)]
            zs = [z for z in zs if z > med["z_saia"] + 0.2]
            x0 = med["x_tras"] - 0.6
        achou = None
        for z in zs:
            h = casca.raio((x0, 0.0, z), (sx, 0, 0), None, 2.0)
            if h is None:
                continue
            p, n, obj, mat = h
            if not ok(obj, mat, n) or -sx * n.x < 0.45:
                continue
            # a face tem que ser lisa nos 4 cm em volta (sem pegar a borda de uma grade ou de uma lente)
            liso = True
            for dy, dz in ((0.035, 0), (-0.035, 0), (0, 0.02), (0, -0.02)):
                h2 = casca.raio((x0, dy, z + dz), (sx, 0, 0), None, 2.0)
                if h2 is None or not ok(h2[2], h2[3], h2[1]) or abs((h2[0] - p).x) > 0.02:
                    liso = False
                    break
            if liso:
                achou = h
                break
        if achou is None:
            rel["pulados"].append("emblema %s: sem face lisa no meio" % qual)
            continue
        p, n, obj, mat = achou
        emblema_geo(partes.setdefault(obj, Geo()), p, n, 0.085 if qual == "frente" else 0.07)
        rel["emblema"][qual] = {"peca": obj, "ponto": [round(c, 3) for c in p]}


def tem_coisa_no_vidro(casca, med, y):
    """Algo que não é vidro logo à frente do pé do para-brisa (limpador do modelo)? Raio de frente, 4,5 cm acima da borda de baixo."""
    z = med["ws"][4] + 0.045
    vid = casca.raio((med["x_frente"] + 1.0, y, z), (-1, 0, 0), lambda o, m, n: o.startswith("glass_windshield"), 4.0)
    if vid is None:
        return False
    h = casca.raio((med["x_frente"] + 1.0, y, z), (-1, 0, 0), None, 4.0)
    return h is not None and not h[2].startswith("glass_") and 0.0 < (h[0].x - vid[0].x) < 0.05


def limpadores(casca, med, partes, rel, traseiro=False):
    ws = med["rg"] if traseiro else med["ws"]
    vidro = "glass_rear" if traseiro else "glass_windshield"
    hw = ws[3]
    if not traseiro:
        amostras = [hw * k for k in (-0.6, -0.3, 0.0, 0.3, 0.6)]
        achados = sum(tem_coisa_no_vidro(casca, med, y) for y in amostras)
        if achados >= 2:
            rel["pulados"].append("limpador: a casca já tem algo no pé do para-brisa (%d de 5 raios)" % achados)
            return
    g = partes.setdefault("body" if not traseiro else "trunk", Geo())
    # pé do vidro: raio de frente (de trás, no vidro traseiro) 4,5 cm acima da borda de baixo; serve para-brisa deitado e de pé (furgão)
    z_pe = ws[4] + 0.045
    x_ini, dx = (med["x_frente"] + 1.0, -1.0) if not traseiro else (med["x_tras"] - 1.0, 1.0)
    sobre_vidro = lambda o, m, n: o.startswith(vidro)
    bracos = ((0.45 * hw, 0.50), (-0.18 * hw, 0.42)) if not traseiro else ((0.0, 0.32),)
    feitos = 0
    for y_piv, L in bracos:
        ys = [y_piv - 0.04 - L * i / 10 for i in range(11)]
        # a borda de baixo medida (ws z0) pode estar no friso ou na borracha: sobe até achar o vidro na palheta quase inteira
        for z in (z_pe, z_pe + 0.03, z_pe + 0.07, z_pe + 0.12):
            pts = []
            for y in ys:
                h = casca.raio((x_ini, y, z), (dx, 0, 0), sobre_vidro, 5.0)
                if h is not None:
                    pts.append((h[0] + h[1] * 0.006, h[1]))
            if len(pts) >= 8:
                break
        if len(pts) < 5:
            rel["pulados"].append("limpador %s em y=%.2f: vidro não achado" % ("traseiro" if traseiro else "dianteiro", y_piv))
            continue
        # palheta como a de verdade (foto do Commons, 06/11): a borracha rente ao vidro e a armação 1,5 cm acima, mais larga
        for (a, na), (b, nb) in zip(pts, pts[1:]):
            g.barra(a, b, 0.006, 0.010, na, M_PRETO)                       # borracha
            g.barra(a + na * 0.013, b + nb * 0.013, 0.016, 0.010, na, M_PRETO)  # armação
        meio_p, meio_n = pts[len(pts) // 2]
        # pivô 6 cm abaixo da ponta da palheta, descendo pelo vidro (na grade do capô ou na chapa sob o vidro de trás)
        p0, n0 = pts[0]
        desce = Vector((0, 0, -1)) - n0 * (-n0.z)
        desce = desce.normalized() if desce.length > 1e-3 else Vector((0, 0, -1))
        piv = p0 + desce * 0.06
        pivn = n0
        g.cilindro(piv - pivn * 0.008, piv + pivn * 0.018, 0.016, M_PRETO)
        braco_fim = meio_p + meio_n * 0.022
        g.barra(piv + pivn * 0.012, braco_fim, 0.012, 0.007, meio_n, M_PRETO)
        feitos += 1
    rel["limpador_traseiro" if traseiro else "limpador"] = feitos


def espelhos(casca, partes, rel):
    for nome in ("mirror_left", "mirror_right"):
        o = casca.objs.get(nome)
        if o is None:
            continue
        me = o.data
        mats = [m.name.split(".")[0] if m else "" for m in me.materials]
        mw = o.matrix_world
        nm = mw.to_3x3().inverted().transposed()
        tras = [p for p in me.polygons if (nm @ p.normal).normalized().x < -0.7]
        if not tras:
            rel["pulados"].append("espelho %s: sem face de trás" % nome)
            continue
        area = sum(p.area for p in tras)
        brilho = sum(p.area for p in tras if mats and mats[p.material_index] in ("cromado", "cromo", "vidro", "refletor"))
        if brilho > 0.3 * area:
            rel["pulados"].append("espelho %s: já tem" % nome)
            continue
        pts = [mw @ me.vertices[i].co for p in tras for i in p.vertices]
        xs = min(q.x for q in pts)
        y0, y1 = min(q.y for q in pts), max(q.y for q in pts)
        z0, z1 = min(q.z for q in pts), max(q.z for q in pts)
        cy, cz, hy, hz = (y0 + y1) / 2, (z0 + z1) / 2, (y1 - y0) * 0.42, (z1 - z0) * 0.40
        if hy < 0.02 or hz < 0.015:
            rel["pulados"].append("espelho %s: face pequena" % nome)
            continue
        # o espelho fica 1,5 mm atrás da face mais de trás, num plano reto (a capa costuma ser curva: assim ele não afunda nela)
        h = casca.raio((xs - 0.5, cy, cz), (1, 0, 0), lambda ob, m, n: ob == nome, 1.0)
        x = (h[0].x if h else xs) - 0.0015
        g = partes.setdefault(nome, Geo())
        g.face([(x, cy - hy, cz - hz), (x, cy - hy, cz + hz), (x, cy + hy, cz + hz), (x, cy + hy, cz - hz)], M_CROMO)
        rel["espelho"][nome] = [round(2 * hy, 3), round(2 * hz, 3)]


def ponteira(casca, med, kit, partes, rel):
    esc = [p for p in kit["pecas"] if p["nome"] == "under_escapamento"]
    if not esc:
        rel["pulados"].append("ponteira: o kit não tem escapamento")
        return
    x0, x1, y0, y1, z0, z1 = esc[0]["caixa_m"]
    y = y0 + 0.08
    # fundo da carroceria sobre a ponta
    fundo = casca.raio((med["x_tras"] + 0.12, y, 0.0), (0, 0, 1), nao_vidro, 2.0)
    z = min(z1 - 0.03, (fundo[0].z - 0.05) if fundo else z1 - 0.03)
    z = max(z, 0.12)
    tras = casca.raio((med["x_tras"] - 0.6, y, z + 0.06), (1, 0, 0), nao_vidro, 2.0)
    x_fim = (tras[0].x if tras else med["x_tras"]) - 0.02
    if x_fim > med["x_tras"] + 0.25:  # o raio passou sob o para-choque e pegou o assoalho: a ponta fica 6 cm para dentro da traseira
        x_fim = med["x_tras"] + 0.06
    g = partes.setdefault("body", Geo())
    g.cilindro((x0 + 0.05, y, z), (x_fim + 0.10, y, z), 0.022, M_PRETO, tampas=False)
    g.cilindro((x_fim + 0.10, y, z), (x_fim, y, z), 0.028, M_CROMO, tampas=False, r2=0.030)
    g.cilindro((x_fim + 0.004, y, z), (x_fim + 0.006, y, z), 0.026, M_PRETO, tampas=True)  # o miolo escuro, 4 mm para dentro
    rel["ponteira"] = {"x": round(x_fim, 3), "y": round(y, 3), "z": round(z, 3)}


def antena(casca, med, partes, rel, onde=True):
    """Mastro de 75 cm no para-lama da frente esquerdo (anos 70 a 90) ou, com onde="teto", a antena curta no fim do teto (anos 2000)."""
    if onde == "teto":
        pontos = [(med["rg"][1] + 0.12 + 0.03 * i, 0.0) for i in range(4)]
        compr, incl = 0.20, 35.0
    else:
        pontos = [(med["ws"][1] + 0.10 + dx, med["W"] - dy) for dx in (0.0, 0.08) for dy in (0.10, 0.16, 0.22)]
        compr, incl = 0.75, 12.0
    h = None
    for x, y in pontos:
        h = casca.raio((x, y, 3.0), (0, 0, -1), nao_vidro, 4.0)
        # no capô não: a antena voaria com ele (Caipora, 06/11)
        if h is not None and h[1].z > 0.5 and h[2] != "hood":
            break
        h = None
    if h is None and onde != "teto":
        # sem para-lama livre (o capô cobre a quina): a antena de 40 cm na frente do teto, sobre o para-brisa, comum nos 90
        for x in (med["ws"][0] - 0.05, med["ws"][0] - 0.10):
            h = casca.raio((x, 0.0, 3.0), (0, 0, -1), nao_vidro, 4.0)
            if h is not None and h[1].z > 0.5:
                compr, incl = 0.40, 20.0
                break
            h = None
    if h is None:
        rel["pulados"].append("antena: %s não achado" % ("teto" if onde == "teto" else "para-lama nem teto"))
        return
    p, n, obj, _ = h
    g = partes.setdefault(obj, Geo())
    g.cilindro(p - n * 0.005, p + n * 0.02, 0.011, M_PRETO, r2=0.008)
    topo = p + Vector((-math.sin(math.radians(incl)), 0, math.cos(math.radians(incl)))) * compr
    g.cilindro(p + n * 0.02, topo, 0.0028, M_PRETO, seg=6, r2=0.0018)
    g.cilindro(topo, topo + (topo - p).normalized() * 0.008, 0.0035, M_PRETO, seg=6)
    rel["antena"] = {"peca": obj, "ponto": [round(c, 3) for c in p]}


def macanetas(casca, med, portas, partes, rel):
    for pos, d in portas.items():
        nome = "door_" + pos
        lado = d["lado"]
        x = d["x0"] + 0.11
        z = med["z_cintura"] - 0.06
        h = casca.raio((x, lado * 3.0, z), (0, -lado, 0), lambda o, m, n: o == nome or not o.startswith(("glass_", "mirror_")), 4.0)
        if h is None or h[2] != nome:
            rel["pulados"].append("maçaneta %s: porta não achada no ponto" % pos)
            continue
        p, n, obj, _ = h
        ex, ey, ez = base_na_face(n)
        g = partes.setdefault(obj, Geo())
        g.caixa(p + ez * 0.001, ex, ey, ez, 0.065, 0.02, 0.0015, M_PRETO)
        g.caixa(p + ez * 0.008 - ey * 0.002, ex, ey, ez, 0.055, 0.009, 0.005, M_CROMO)
        rel["macaneta"][pos] = [round(c, 3) for c in p]


def friso(casca, med, z, partes, rel, alto=0.022, saliencia=0.006):
    for lado in (1, -1):
        trechos, atual, ultimo = [], [], None
        x = med["x_tras"] + 0.12
        while x < med["x_frente"] - 0.12:
            h = casca.raio((x, lado * 3.0, z), (0, -lado, 0), None, 4.0)
            ok = h is not None and nao_vidro(h[2], h[3], h[1]) and abs(h[1].y) > 0.6 and h[3].startswith(("pintura", "chassi"))
            if ok and atual and (h[2] != ultimo or (h[0] - atual[-1][0]).length > 0.06):
                trechos.append((ultimo, atual))
                atual = []
            if ok:
                atual.append((h[0], h[1]))
                ultimo = h[2]
            elif atual:
                trechos.append((ultimo, atual))
                atual = []
            x += 0.03
        if atual:
            trechos.append((ultimo, atual))
        for obj, pts in trechos:
            if len(pts) < 3:
                continue
            g = partes.setdefault(obj, Geo())
            for (a, na), (b, nb) in zip(pts, pts[1:]):
                n = (na + nb).normalized()
                g.barra(a + n * saliencia / 2, b + n * saliencia / 2, saliencia, alto, Vector((0, 0, 1)), M_PRETO)
            rel["friso"].setdefault(obj, 0)
            rel["friso"][obj] += len(pts) - 1


def heroi(casca, med, partes, rel):
    """Passe extra do carro herói (Cuiabano): calha de chuva, esguichos no capô, luz de placa e limpador de trás."""
    # calha de chuva: a borda do teto de cada lado, achada descendo raios de fora para dentro
    for lado in (1, -1):
        pts = []
        x = med["rg"][1] - 0.02
        while x < med["ws"][0] + 0.02:
            borda = None
            y = lado * (med["W"] + 0.02)
            while abs(y) > 0.2:
                h = casca.raio((x, y, 3.0), (0, 0, -1), nao_vidro, 4.0)
                if h is not None and h[0].z > med["z_janela"] - 0.02:
                    borda = h
                    break
                y -= lado * 0.005
            if borda is not None:
                pts.append(borda[0] + Vector((0, 0, 0.004)))
            x += 0.05
        g = partes.setdefault("body", Geo())
        for a, b in zip(pts, pts[1:]):
            if (b - a).length < 0.12:
                g.barra(a, b, 0.010, 0.008, Vector((0, 0, 1)), M_PRETO)
        rel["heroi"]["calha_%s" % ("esq" if lado > 0 else "dir")] = len(pts)
    # esguichos do lavador no capô, 8 cm à frente do vidro
    for y in (0.25, -0.25):
        h = casca.raio((max(med["ws"][1], med["tampa_frente"][0]) + 0.08, y, 3.0), (0, 0, -1), lambda o, m, n: o == "hood", 4.0)
        if h is None:
            continue
        ex, ey, ez = base_na_face(h[1])
        g = partes.setdefault("hood", Geo())
        g.caixa(h[0] + ez * 0.006, ex, ey, ez, 0.012, 0.009, 0.006, M_PRETO)
        rel["heroi"].setdefault("esguichos", 0)
        rel["heroi"]["esguichos"] += 1
    # luz de placa: duas lentes brancas na borda de cima da placa de trás
    pl = casca.objs.get("plate_rear")
    if pl is not None:
        vs = [pl.matrix_world @ v.co for v in pl.data.vertices]
        xmin = min(v.x for v in vs)
        ztop = max(v.z for v in vs)
        for y in (0.10, -0.10):
            g = partes.setdefault("trunk" if "trunk" in casca.objs else "body", Geo())
            c = Vector((xmin + 0.012, y, ztop + 0.012))
            g.caixa(c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), 0.014, 0.026, 0.009, M_PRETO)
            g.caixa(c + Vector((0, 0, -0.0095)), Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), 0.010, 0.020, 0.001, M_LUZ)
        rel["heroi"]["luz_de_placa"] = 2
    limpadores(casca, med, partes, rel, traseiro=True)


def conferir_kit(kit, casca, rel):
    nomes = {p["nome"] for p in kit["pecas"]}
    rel["freios_do_kit"] = sorted(n for n in nomes if n.startswith("brake_") and n.endswith(("disco", "pinca", "tambor")))
    placas = [n for n in ("plate_front", "plate_rear") if n in casca.objs]
    rel["placas_do_corte"] = placas
    if len(placas) < 2:
        rel["pulados"].append("placa: o corte tem só %s (rodar o detalhes_na_casca.py, que faz a de 40 x 13 cm)" % placas)


# ================================================================================================================================
# GLB
# ================================================================================================================================

def material(nome):
    m = bpy.data.materials.get(nome)
    if m is None:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        r, g, b, rug, met = COR_PREVIA.get(nome, (0.5, 0.5, 0.5, 0.5, 0.0))
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1.0)
        bsdf.inputs["Roughness"].default_value = rug
        bsdf.inputs["Metallic"].default_value = met
    return m


def objeto(nome, geo):
    me = bpy.data.meshes.new(nome)
    me.from_pydata([tuple(v) for v in geo.v], [], geo.f)
    usados = sorted(set(geo.m))
    for u in usados:
        me.materials.append(material(u))
    for p, mm in zip(me.polygons, geo.m):
        p.material_index = usados.index(mm)
    me.validate()
    for p in me.polygons:
        p.use_smooth = False
    ob = bpy.data.objects.new(nome, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def importar(caminho):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=caminho)
    novos = [o for o in bpy.data.objects if o not in antes]
    for o in novos:
        if o.type == 'MESH' and o.parent is None:
            o.data.transform(o.matrix_world)
            o.matrix_world = Matrix.Identity(4)
    return novos


def exportar(caminho, objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=caminho, export_format='GLB', use_selection=True, export_apply=True, export_yup=True)


def passe(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    corte = importar(args["corte"])
    kit = json.load(open(args["kit"], encoding="utf-8"))
    med = dict(kit["medidas"])
    portas = kit.get("portas", {})
    med.setdefault("z_janela", max([d.get("z_janela", 1.2) for d in portas.values()] or [1.2]))
    casca = Casca(corte)
    partes = {}
    rel = {"id": args["id"], "gerado_por": "acervo-3d/ferramentas/passe_detalhe.py", "licenca": "CC0 (próprio do estúdio; sem marca, logo nem texto)",
           "corte": os.path.basename(args["corte"]), "folga": {}, "emblema": {}, "espelho": {}, "macaneta": {}, "friso": {}, "heroi": {},
           "pulados": []}
    if not args.get("sem_folga"):
        folga(casca, partes, rel, med["z_cintura"])
    if not args.get("sem_emblema"):
        emblemas(casca, med, partes, rel)
    if args.get("limpador", True):
        limpadores(casca, med, partes, rel)
    if args.get("espelho", True):
        espelhos(casca, partes, rel)
    if args.get("ponteira", True):
        ponteira(casca, med, kit, partes, rel)
    if args.get("antena"):
        antena(casca, med, partes, rel, args["antena"])
    if args.get("macaneta"):
        macanetas(casca, med, portas, partes, rel)
    if args.get("friso"):
        friso(casca, med, float(args["friso"]), partes, rel)
    if args.get("heroi"):
        heroi(casca, med, partes, rel)
    conferir_kit(kit, casca, rel)
    for o in corte:
        bpy.data.objects.remove(o, do_unlink=True)
    # os materiais do corte saem também: com o mesmo nome (chassi), o detalhe herdava a textura de 2K do carro e o GLB passava de 3 MB
    for m in list(bpy.data.materials):
        bpy.data.materials.remove(m)
    for im in list(bpy.data.images):
        bpy.data.images.remove(im)
    objs = []
    rel["pecas"] = []
    for nome, g in sorted(partes.items()):
        if not g.f:
            continue
        ob = objeto("det_" + nome, g)
        objs.append(ob)
        rel["pecas"].append({"nome": ob.name, "segue": nome, "triangulos": g.tris(), "materiais": sorted(set(g.m))})
    rel["triangulos"] = sum(p["triangulos"] for p in rel["pecas"])
    os.makedirs(args["out"], exist_ok=True)
    exportar(os.path.join(args["out"], "%s_detalhe.glb" % args["id"]), objs)
    with open(os.path.join(args["out"], "%s_detalhe.json" % args["id"]), "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=1)
    print("DETALHE %s: %d triângulos em %d peças; pulados: %s" % (args["id"], rel["triangulos"], len(objs), rel["pulados"]))
    return rel


def juntar(corte_glb, detalhe_glb, saida):
    """Funde cada det_<peça> na peça do corte de mesmo nome (o resto no body) e grava o corte com o detalhe dentro."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    corte = importar(corte_glb)
    det = importar(detalhe_glb)
    por_nome = {o.name: o for o in corte if o.type == 'MESH'}
    for d in det:
        if d.type != 'MESH':
            continue
        alvo = por_nome.get(d.name[4:].split(".")[0]) or por_nome.get("body")
        # os materiais do detalhe viram os do corte de mesmo nome (pintura, chassi, cromo...), para o slot não duplicar
        for i, m in enumerate(d.data.materials):
            nome = m.name.split(".")[0]
            igual = next((mm for mm in bpy.data.materials if mm.name.split(".")[0] == nome and mm is not m and mm.users), None)
            if igual is not None:
                d.data.materials[i] = igual
        bpy.ops.object.select_all(action='DESELECT')
        d.select_set(True)
        alvo.select_set(True)
        bpy.context.view_layer.objects.active = alvo
        bpy.ops.object.join()
    exportar(saida, [o for o in bpy.data.objects if o.type in ('MESH', 'EMPTY')])
    print("JUNTADO", saida)


def argumentos():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {}
    i = 0
    while i < len(a):
        k = a[i]
        if k == "--juntar":
            out["juntar"] = a[i + 1:i + 4]
            i += 4
            continue
        if k in ("--heroi", "--antena", "--macaneta", "--todos"):
            out[k[2:]] = True
        elif k.startswith("--sem-"):
            out[k[2:].replace("-", "_")] = True
            out[k[6:]] = False
        else:
            out[k[2:].replace("-", "_")] = a[i + 1]
            i += 1
        i += 1
    return out


def main():
    a = argumentos()
    if "juntar" in a:
        juntar(*a["juntar"])
        return
    if a.get("todos"):
        raiz = os.path.join(RAIZ, a.get("out_raiz", os.path.join(SK, "detalhe")))
        resumo = {}
        for cid, cfg in CARROS.items():
            args = dict(cfg)
            args["id"] = cid
            args["corte"] = os.path.normpath(os.path.join(RAIZ, cfg.get("corte", "%s/quebravel/%s/%s.glb" % (SK, cid, cid)).format(detonauto=DETONAUTO)))
            args["kit"] = os.path.normpath(os.path.join(RAIZ, cfg.get("kit", "%s/completo/%s/%s_completo.json" % (SK, cid, cid))))
            args["out"] = os.path.join(raiz, cid)
            if not os.path.isfile(args["corte"]):
                print("SEM CORTE", cid, args["corte"])
                resumo[cid] = "sem corte"
                continue
            rel = passe(args)
            resumo[cid] = {"triangulos": rel["triangulos"], "pulados": rel["pulados"]}
        print(json.dumps(resumo, ensure_ascii=False, indent=1))
        return
    passe(a)


if __name__ == "__main__":
    main()
