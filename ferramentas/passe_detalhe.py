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
  emblema    o emblema do jogo na frente e atrás: o "Estilhaço" (a logo escolhida pelo Felipe em 10/11/2026), estouro cromado de 8
             pontas sobre borda preta, com o D vazado e inclinado; até 10/11 era um hexágono com três barras.
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
    # já tem antena no fim do teto (prévia de 06/11); para-choque pintado com a faixa de borracha da época (revisão da central, 06/11)
    "caipora": dict(nome="Caipora", faixa=True),
    "hatch-redondo-5p": dict(nome="Pampeiro", antena="teto"),
    "barao": dict(nome="Barão", macaneta=True, friso=0.55),
    "furgaozinho": dict(nome="Furgãozinho da Firma", antena=True),
    "besouro": dict(nome="Besouro"),
    "furgao-classico": dict(nome="Pão de Forma"),
    "gaucho-v8": dict(nome="Gaúcho V8"),
    "jipe-capota": dict(nome="Trilheiro", antena=True),
    "lambari": dict(nome="Lambari", antena=True, limpador=False),
    "jabuti": dict(nome="Jabuti"),
    # sem o emblema próprio (rodada do PC de 07/11): no Sagui ele cai na ponta do capô, onde o modelo original tinha o oval da marca, e
    # lê como emblema de marca; a frente e a tampa ficam lisas
    # o Tropeiro entra em 10/11/2026 (revisão dos carros: o retrovisor padrão e o emblema nos 14)
    "tropeiro": dict(nome="Tropeiro"),
    "sagui": dict(nome="Sagui", ponteira=False, limpador=False, sem_emblema=True),
}

M_PRETO, M_CROMO, M_PINTURA, M_LUZ, M_VIDRO = "chassi", "cromo", "pintura", "luz_branca", "vidro"
M_REFLETOR = "refletor"   # no jogo MI_DNRefletor<Modelo> (kit_names.py)
COR_PREVIA = {M_REFLETOR: (0.80, 0.80, 0.80, 0.12, 1.0), M_PRETO: (0.028, 0.028, 0.03, 0.5, 0.0), M_CROMO: (0.62, 0.62, 0.64, 0.05, 1.0), M_PINTURA: (0.42, 0.025, 0.025, 0.25, 0.0),
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

    def fita(self, pts, alto, saliencia, cima, mat):
        """Fita contínua (frente, topo, base e as duas pontas) ao longo de pontos (p, normal) da chapa: sem as emendas das barras soltas."""
        cima = Vector(cima)
        secoes = []
        for p, n in pts:
            n = Vector(n).normalized()
            up = (cima - n * n.dot(cima)).normalized()
            p = Vector(p)
            secoes.append((p + up * alto / 2, p + up * alto / 2 + n * saliencia, p - up * alto / 2 + n * saliencia, p - up * alto / 2))
        for a, b in zip(secoes, secoes[1:]):
            self.face([a[0], a[1], b[1], b[0]], mat)   # topo
            self.face([a[1], a[2], b[2], b[1]], mat)   # frente
            self.face([a[2], a[3], b[3], b[2]], mat)   # base
        self.face(list(secoes[0]), mat)
        self.face(list(reversed(secoes[-1])), mat)

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

def folga(casca, partes, rel, med_cintura=0.9, largura=0.0025, acima=0.0004):
    """Vão fino (2,5 mm) na borda de fora da chapa de cada peça móvel (porta, capô, tampa). Revisão da central (06/11): com 4 mm e
    também em volta dos vidros, o contorno lia como linha de desenho; a borda junto ao vidro já tem a borracha do corte e fica de fora."""
    vidros = [o for n, o in casca.objs.items() if n.startswith("glass_")]
    bvh_vidro = None
    if vidros:
        vs, ps = [], []
        for o in vidros:
            b = len(vs)
            vs.extend(o.matrix_world @ v.co for v in o.data.vertices)
            ps.extend([b + i for i in p.vertices] for p in o.data.polygons)
        bvh_vidro = BVHTree.FromPolygons(vs, ps)
    for nome in ("door_fl", "door_fr", "door_rl", "door_rr", "hood", "trunk"):
        o = casca.objs.get(nome)
        if o is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(o.matrix_world)
        # solda o que está a menos de 1 mm: faces soltas lado a lado no meio da chapa (o vinco do capô do Cuiabano) davam linhas de vão falsas
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
            if bvh_vidro is not None and bvh_vidro.find_nearest(meio, 0.03)[0] is not None:
                continue  # borda da janela: a borracha do vidro já está lá
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


# o emblema do jogo (10/11/2026, a proposta 2 "Estilhaço" escolhida pelo Felipe; docs/img/logo/proposta-2-estilhaco.svg no Detonauto): o
# estouro de 8 pontas (16 vértices) e o D vazado e inclinado 12 graus, nas coordenadas do SVG (100 x 100, centro do estouro em 50, 51; y para baixo)
ESTILHACO = [(50, 2), (58, 30), (84, 10), (71, 38), (98, 42), (73, 55), (92, 80), (63, 69), (57, 98), (45, 72), (22, 92), (28, 64),
             (2, 60), (26, 46), (8, 20), (37, 31)]
ESTILHACO_CENTRO = (50, 51)


def d_do_estilhaco(cx, r, x0, y0, y1, seg=10):
    """O contorno de um D do SVG (reto em x0, a barriga em meio círculo de raio r em volta de cx, de y0 a y1), inclinado como o
    skewX(-12) em volta de (50, 51)."""
    pts = [(x0, y0)]
    for k in range(seg + 1):
        a = -math.pi / 2 + math.pi * k / seg
        pts.append((cx + r * math.cos(a), (y0 + y1) / 2 + r * math.sin(a)))
    pts.append((x0, y1))
    t = math.tan(math.radians(12))
    return [(x - t * (y - 51), y) for x, y in pts]


def emblema_geo(g, c, nor, largura, preto=M_PRETO, cromo=M_CROMO):
    """Emblema do jogo, o "Estilhaço": a base preta com o contorno do estouro, o estouro cromado por cima e o D vazado (preto) com o
    miolo cromado. Monocromático no desenho; em relevo de 0,5 mm entre as camadas para ler a 2 cm."""
    ex, ey, ez = base_na_face(nor)
    c = Vector(c) + ez * 0.0008

    def mapa(pts, escala=1.0):
        return [((x - ESTILHACO_CENTRO[0]) * escala * largura / 100.0, -(y - ESTILHACO_CENTRO[1]) * escala * largura / 100.0) for x, y in pts]

    def estrela(base, esp, escala, mat):
        # a estrela não é convexa: em leque a partir do centro (o estouro é estrelado em volta dele), com as paredes de lado
        pts = mapa(ESTILHACO, escala)
        meio_b, meio_t = base, base + ez * esp
        B = [base + ex * x + ey * y for x, y in pts]
        T = [p + ez * esp for p in B]
        n = len(B)
        for i in range(n):
            j = (i + 1) % n
            g.face([meio_t, T[i], T[j]], mat)
            g.face([meio_b, B[j], B[i]], mat)
            g.face([B[i], B[j], T[j], T[i]], mat)
    estrela(c, 0.002, 1.06, preto)                     # a borda preta em volta: o estouro lê sobre qualquer pintura
    estrela(c + ez * 0.002, 0.0015, 1.0, cromo)
    g.poligono(c + ez * 0.0035, ex, ey, ez, mapa(d_do_estilhaco(53, 18, 36, 33, 69)), 0.0005, preto)
    g.poligono(c + ez * 0.004, ex, ey, ez, mapa(d_do_estilhaco(52, 9, 45, 42, 60)), 0.0005, cromo)


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
        # o Estilhaço é quase quadrado (10/11/2026): o tamanho cheio pede a face lisa em +-3 cm na vertical; a grade baixa (
        # o Caipora, o Tupiniquim, o jipe e o Lambari só têm +-2 cm, e ali entra o de 4,5 cm, do tamanho do hexágono de antes
        cheio = 0.065 if qual == "frente" else 0.06
        achou, grade = None, []
        for z in zs:
            h = casca.raio((x0, 0.0, z), (sx, 0, 0), None, 2.0)
            if h is None:
                continue
            p, n, obj, mat = h
            if obj.startswith("grille"):
                grade.append(h)
            if not ok(obj, mat, n) or -sx * n.x < 0.45:
                continue
            # a face tem que ser lisa em volta (sem pegar a borda de uma grade ou de uma lente); de cima para baixo, o tamanho cheio
            # antes do pequeno na mesma altura (o emblema não desce para o para-choque)
            for largura, meia_altura in ((cheio, 0.03), (0.045, 0.02)):
                liso = True
                for dy, dz in ((0.035, 0), (-0.035, 0), (0, meia_altura), (0, -meia_altura)):
                    h2 = casca.raio((x0, dy, z + dz), (sx, 0, 0), None, 2.0)
                    if h2 is None or not ok(h2[2], h2[3], h2[1]) or abs((h2[0] - p).x) > 0.02:
                        liso = False
                        break
                if liso:
                    achou = h
                    break
            if achou is not None:
                break
        if achou is None and len(grade) >= 2:
            # grade de frisos sem face lisa (a remodelada do Cuiabano, 6 frisos): o emblema preso na frente dos frisos, no meio da altura
            # da grade, como nos carros de verdade; a borda preta do estouro faz a base
            largura = 0.045
            meio = sorted(grade, key=lambda h: h[0].z)[len(grade) // 2]
            # a frente dos frisos: raios a cada 2 mm em +-3 cm (os de 2 cm passavam entre os frisos e achavam o fundo recuado, e o
            # emblema ficava escondido atrás deles)
            finos = [casca.raio((x0, 0.0, meio[0].z + 0.002 * k), (sx, 0, 0), None, 2.0) for k in range(-15, 16)]
            frente = max(h[0].x * -sx for h in finos + grade if h is not None and h[2].startswith("grille")
                         and abs(h[0].z - meio[0].z) < 0.031) * -sx
            achou = (Vector((frente, 0.0, meio[0].z)), Vector((-sx, 0.0, 0.0)), meio[2], meio[3])
        if achou is None:
            rel["pulados"].append("emblema %s: sem face lisa no meio" % qual)
            continue
        p, n, obj, mat = achou
        emblema_geo(partes.setdefault(obj, Geo()), p, n, largura)
        rel["emblema"][qual] = {"peca": obj, "ponto": [round(c, 3) for c in p], "largura": largura}


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
                    pts.append((h[0] + h[1] * 0.004, h[1]))  # a borracha encosta no vidro (a 6 mm parecia flutuar)
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


# retrovisor padrão por época (revisão de 10/11/2026, item 2: "retrovisor ruim", o do corte era uma chapa fina, de lado sumia e de trás era
# um palito). Substitui o do corte (o --juntar apaga a geometria antiga quando o json diz "retrovisor_padrao"). Carcaça com 8,5 a 10 cm de
# fundo (C2 do checar_carro: 8 cm), espelho na face de trás e o pé na porta. Medidas em metros: largura (para fora), altura, fundo.
ESTILO_RETROVISOR = {
    "70": dict(forma="redondo", larg=0.125, alt=0.095, fundo=0.085, mat=M_CROMO, braco=0.07),
    "80": dict(forma="caixa", larg=0.165, alt=0.090, fundo=0.085, mat=M_PRETO, braco=0.035),
    "90": dict(forma="aero", larg=0.185, alt=0.110, fundo=0.095, mat=M_PRETO, braco=0.030),
    "2000": dict(forma="aero", larg=0.195, alt=0.115, fundo=0.100, mat=M_PINTURA, braco=0.025),
}


def retrovisor_padrao(casca, partes, rel, epoca):
    est = ESTILO_RETROVISOR.get(str(epoca), ESTILO_RETROVISOR["90"])
    feitos = 0
    for nome in ("mirror_left", "mirror_right"):
        o = casca.objs.get(nome)
        if o is None:
            continue
        mw = o.matrix_world
        pts = [mw @ v.co for v in o.data.vertices]
        lado = 1 if sum(q.y for q in pts) > 0 else -1
        # o pé: o ponto do retrovisor antigo mais perto do meio do carro (onde ele encostava na porta), na altura média dele
        y_pe = min(abs(q.y) for q in pts)
        xc = sum(q.x for q in pts) / len(pts)
        zc = sum(q.z for q in pts) / len(pts)
        # encosta o pé na chapa da porta (raio de fora para dentro na altura do pé)
        h = casca.raio((xc, lado * 2.0, zc - 0.02), (0, -lado, 0), lambda ob, m, n: not ob.startswith(("mirror", "glass")), 2.5)
        if h is not None:
            y_pe = abs(h[0].y)
        g = Geo()
        L, A, F, braco, mat = est["larg"], est["alt"], est["fundo"], est["braco"], est["mat"]
        ex, ey, ez = Vector((1, 0, 0)), Vector((0, lado, 0)), Vector((0, 0, 1))
        pe = Vector((xc, lado * y_pe, zc))
        # pé triangular colado na porta (plástico preto), 2 cm de espessura
        g.poligono(pe + ey * -0.002, ex, ez, ey, [(-0.045, -0.03), (0.035, -0.03), (-0.02, 0.035)], 0.02, M_PRETO)
        # braço até a carcaça
        cc = pe + ey * (braco + L / 2) + ez * 0.02
        if est["forma"] == "redondo":
            g.cilindro(pe + ey * 0.015, pe + ey * braco + ez * 0.02, 0.009, M_CROMO, seg=10)
            # a cuia redonda: cilindro deitado no eixo do carro, a tampa de trás é o espelho
            g.cilindro(cc + ex * (F * 0.45), cc - ex * (F * 0.55), A / 2, mat, seg=20, r2=A / 2 * 0.98)
            g.cilindro(cc - ex * (F * 0.55 + 0.001), cc - ex * (F * 0.55 + 0.003), A / 2 * 0.9, M_CROMO, seg=20)
        else:
            g.caixa(pe + ey * (braco / 2 + 0.005) + ez * 0.01, ex, ey, ez, 0.03, braco / 2 + 0.01, 0.018, M_PRETO)
            # a carcaça: uma caixa maior com a frente afinada (a frente "aero" mais curta em cima e embaixo), espelho atrás
            g.caixa(cc + ex * (F * 0.10), ex, ey, ez, F * 0.40, L / 2, A / 2, mat)
            fr = 0.80 if est["forma"] == "aero" else 0.92
            g.caixa(cc + ex * (F * 0.10 + F * 0.40 + F * 0.05), ex, ey, ez, F * 0.05, L / 2 * fr, A / 2 * fr, mat)
            # moldura preta em volta do espelho e o espelho, 1 mm atrás
            g.caixa(cc - ex * (F * 0.30 + 0.004), ex, ey, ez, 0.004, L / 2, A / 2, M_PRETO)
            g.poligono(cc - ex * (F * 0.30 + 0.009), ey, ez, -ex, [(-L / 2 * 0.9, -A / 2 * 0.86), (L / 2 * 0.9, -A / 2 * 0.86),
                                                                     (L / 2 * 0.9, A / 2 * 0.86), (-L / 2 * 0.9, A / 2 * 0.86)], 0.001, M_CROMO)
        partes[nome] = g
        rel.setdefault("retrovisor", {})[nome] = {"estilo": str(epoca), "forma": est["forma"], "fundo_cm": round(F * 100, 1),
                                                  "pe": [round(c, 3) for c in pe]}
        feitos += 1
    if feitos:
        rel["retrovisor_padrao"] = True


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
    elif onde == "teto_frente":
        # anos 90: a antena de 40 cm na frente do teto, sobre o para-brisa (no para-lama ela cruzava o vidro na vista de 3/4)
        pontos = [(med["ws"][0] - 0.05, 0.0), (med["ws"][0] - 0.10, 0.0)]
        compr, incl = 0.40, 20.0
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
    if h is None and onde is True:
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
            g.fita(pts, alto, saliencia, (0, 0, 1), M_PRETO)
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


def farol_interno(casca, partes, rel, folga=0.012, fundo=0.055):
    """Refletor parabólico cromado e lâmpada atrás da lente de cada farol que não tem refletor (revisão da central, 06/11: o farol do
    Caipora lia como mancha bege chapada). Lente larga (mais de 1,7 vez a altura) ganha dois refletores lado a lado, como os faróis duplos.
    No jogo a lente é opaca e o refletor aparece pelo material (LampInterior do M_DNDentParent); esta geometria aparece com a lente
    quebrada e nas prévias, onde a lente é vidro."""
    for nome in ("headlight_left", "headlight_right"):
        o = casca.objs.get(nome)
        if o is None:
            continue
        me = o.data
        mats = [m.name.split(".")[0] if m else "" for m in me.materials]
        if "refletor" in mats:
            rel["pulados"].append("refletor %s: já tem" % nome)
            continue
        mw = o.matrix_world
        nm = mw.to_3x3().inverted().transposed()
        lente = [p for p in me.polygons if mats and mats[p.material_index] in ("lente_farol", "luz")]
        if not lente:
            rel["pulados"].append("refletor %s: sem lente" % nome)
            continue
        area = sum(p.area for p in lente)
        n = sum(((nm @ p.normal).normalized() * p.area for p in lente), Vector()) / area
        n.normalize()
        pts = [mw @ me.vertices[i].co for p in lente for i in p.vertices]
        c = sum(pts, Vector()) / len(pts)
        ex, ey, ez = base_na_face(n)
        a = max(abs((q - c).dot(ex)) for q in pts) * 0.92
        b = max(abs((q - c).dot(ey)) for q in pts) * 0.88
        frente = min((q - c).dot(ez) for q in pts)          # a parte mais funda da lente curva
        # a lente tem espessura (face de trás a ~4 mm) e logo atrás vem o bolso escuro da carroceria: o refletor cabe entre os dois
        base = c + ez * (frente - 0.006)
        bolso = casca.raio(base, -ez, lambda ob, m, nn: not ob.startswith("headlight_"), 0.2)
        espaco = (bolso[0] - base).length - 0.003 if bolso else fundo
        g = partes.setdefault(nome, Geo())
        celulas = [(0.0, a)] if a < 1.7 * b else [(-a / 2, a / 2), (a / 2, a / 2)]
        seg, an = 20, 6
        for cx, ca in celulas:
            ra, rb = ca * 0.95, b
            centro = base + ex * cx
            prof = max(0.010, min(fundo, espaco, 0.9 * min(ra, rb)))
            anel = lambda t, r: centro + ex * (math.cos(t) * ra * r) + ey * (math.sin(t) * rb * r) - ez * (prof * (1 - r * r))
            for i in range(an):
                r0, r1 = i / an, (i + 1) / an
                for j in range(seg):
                    t0, t1 = 2 * math.pi * j / seg, 2 * math.pi * (j + 1) / seg
                    g.face([anel(t0, r0), anel(t0, r1), anel(t1, r1), anel(t1, r0)], M_REFLETOR)
            # lâmpada: o bulbo leitoso no fundo e a capinha que tapa o facho direto
            fundo_p = centro - ez * prof
            haste = min(0.028, prof * 0.7)
            g.cilindro(fundo_p, fundo_p + ez * haste, 0.008, M_LUZ, seg=10)
            g.cilindro(fundo_p + ez * haste, fundo_p + ez * (haste + 0.003), 0.007, M_CROMO, seg=10)
        rel.setdefault("farol_interno", {})[nome] = {"refletores": len(celulas), "fundo_cm": round(100 * max(0.010, min(fundo, espaco)), 1)}


def faixa_para_choque(casca, med, partes, rel, alto=0.045, saliencia=0.008):
    """Faixa de borracha preta texturizada na face dos para-choques pintados (anos 90), à altura de mais saliência, desviando da placa."""
    for nome, sx, x0 in (("bumper_front", -1.0, med["x_frente"] + 0.6), ("bumper_rear", 1.0, med["x_tras"] - 0.6)):
        o = casca.objs.get(nome)
        if o is None:
            continue
        zs = [v.co.z for v in o.data.vertices]
        z0, z1 = min(zs), max(zs)
        # a altura da faixa: onde o para-choque sai mais (raio no meio de cada altura, o primeiro a bater)
        melhor = None
        for k in range(1, 12):
            z = z0 + (z1 - z0) * k / 12
            h = casca.raio((x0, 0.35, z), (sx, 0, 0), lambda ob, m, nn: ob == nome, 2.0)
            if h and (melhor is None or -sx * h[0].x > -sx * melhor[1]):
                melhor = (z, h[0].x)
        if melhor is None:
            continue
        z = melhor[0]
        pts, trecho = [], []
        y = -0.95
        while y <= 0.95:
            h = casca.raio((x0, y, z), (sx, 0, 0), None, 2.0)
            ok = h is not None and h[2] == nome and h[3].startswith("pintura") and -sx * h[1].x > 0.25
            if ok:
                trecho.append((h[0], h[1]))
            elif trecho:
                pts.append(trecho)
                trecho = []
            y += 0.02
        if trecho:
            pts.append(trecho)
        g = partes.setdefault(nome, Geo())
        feitos = 0
        for tr in pts:
            if len(tr) < 4:
                continue
            g.fita(tr, alto, saliencia, (0, 0, 1), M_PRETO)
            feitos += len(tr) - 1
        rel.setdefault("faixa", {})[nome] = {"z": round(z, 3), "segmentos": feitos}


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
    if args.get("retrovisor", True):
        retrovisor_padrao(casca, partes, rel, kit.get("epoca", "90"))
    elif args.get("espelho", True):
        espelhos(casca, partes, rel)
    if args.get("ponteira", True):
        ponteira(casca, med, kit, partes, rel)
    if args.get("antena"):
        antena(casca, med, partes, rel, args["antena"])
    if args.get("macaneta"):
        macanetas(casca, med, portas, partes, rel)
    if args.get("friso"):
        friso(casca, med, float(args["friso"]), partes, rel)
    if args.get("farol", True):
        farol_interno(casca, partes, rel)
    if args.get("faixa"):
        faixa_para_choque(casca, med, partes, rel)
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
    # farol com refletor do passe: a face de trás da lente (chassi opaco a ~4 mm, virada para dentro) vira lente, senão tapa o refletor
    for d in det:
        alvo_nome = d.name[4:].split(".")[0]
        if alvo_nome.startswith("headlight_") and alvo_nome in por_nome and any(
                m and m.name.split(".")[0] == "refletor" for m in d.data.materials):
            o = por_nome[alvo_nome]
            mats = [m.name.split(".")[0] if m else "" for m in o.data.materials]
            if "lente_farol" in mats and "chassi" in mats:
                il, ic = mats.index("lente_farol"), mats.index("chassi")
                lente = [p for p in o.data.polygons if p.material_index == il]
                n = sum((p.normal * p.area for p in lente), Vector()).normalized()
                lo = [min(o.data.vertices[i].co[k] for p in lente for i in p.vertices) for k in range(3)]
                hi = [max(o.data.vertices[i].co[k] for p in lente for i in p.vertices) for k in range(3)]
                trocadas = 0
                for p in o.data.polygons:
                    if p.material_index == ic and p.normal.dot(n) < -0.6 and all(lo[k] - 0.01 <= p.center[k] <= hi[k] + 0.01 for k in range(3)):
                        p.material_index = il
                        trocadas += 1
                print("LENTE %s: %d faces de trás viraram lente" % (alvo_nome, trocadas))
                # e o fundo do bolso da carroceria logo atrás da lente (MI_DNVao a ~2 cm) sai: o refletor do passe fecha o buraco
                cl = sum((o.data.vertices[i].co for p in lente for i in p.vertices), Vector()) / sum(len(p.vertices) for p in lente)
                ex = n.cross(Vector((0, 0, 1))).normalized()
                ey = ex.cross(n)
                pts = [o.data.vertices[i].co for p in lente for i in p.vertices]
                ma = max(abs((q - cl).dot(ex)) for q in pts)
                mb = max(abs((q - cl).dot(ey)) for q in pts)
                tirar = 0
                for nome_b in ("body",) + tuple(k for k in por_nome if k.startswith(("fender_front", "bumper_front"))):
                    b_ = por_nome.get(nome_b)
                    if b_ is None:
                        continue
                    bmats = [m.name.split(".")[0] if m else "" for m in b_.data.materials]
                    if "MI_DNVao" not in bmats:
                        continue
                    iv = bmats.index("MI_DNVao")
                    bm = bmesh.new()
                    bm.from_mesh(b_.data)
                    fora = []
                    for f in bm.faces:
                        if f.material_index != iv:
                            continue
                        v = f.calc_center_median() - cl
                        if -0.08 < v.dot(n) < 0.005 and abs(v.dot(ex)) < ma * 0.95 and abs(v.dot(ey)) < mb * 0.9:
                            fora.append(f)
                    if fora:
                        bmesh.ops.delete(bm, geom=fora, context="FACES")
                        bm.to_mesh(b_.data)
                        tirar += len(fora)
                    bm.free()
                print("BOLSO %s: %d faces do fundo escuro tiradas" % (alvo_nome, tirar))
    # o retrovisor padrão do passe troca o do corte (revisão de 10/11/2026): a geometria antiga sai, o objeto fica (nome e pivô do jogo)
    rel_json = os.path.splitext(detalhe_glb)[0] + ".json"
    if os.path.exists(rel_json) and json.load(open(rel_json, encoding="utf-8")).get("retrovisor_padrao"):
        for nome in ("mirror_left", "mirror_right"):
            o = por_nome.get(nome)
            if o is not None and any(d.name[4:].split(".")[0] == nome for d in det):
                bm = bmesh.new()
                bm.from_mesh(o.data)
                bmesh.ops.delete(bm, geom=list(bm.verts), context="VERTS")
                bm.to_mesh(o.data)
                bm.free()
                print("RETROVISOR %s: o do corte saiu, entra o padrão" % nome)
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
