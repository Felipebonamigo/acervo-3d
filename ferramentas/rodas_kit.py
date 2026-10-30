"""
Kit de rodas: aros, pneus (Ok, Flat e Torn) e calotas de carro nacional dos anos 70-80 feitos do zero por geometria, para o
Detonauto (Detonauto/docs/carro-completo.md, seção 4, "O que o Blender gera"). Licença CC0 do estúdio: nada baixado, nada de
IA, sem marca, sem logo, sem letra. Os desenhos são genéricos de época: aro de aço estampado com furos redondos, liga leve com
8 furos ovais e liga leve com 10 raios retos, calota lisa abaulada com furinhos.

Uso (o módulo bpy num venv, ou o Blender):

    python -I ferramentas/rodas_kit.py -- [--out veiculos/proprios/rodas] [--amostras 32] [--sem-previa] [--so p165_80]
    blender -b --python-exit-code 1 -P ferramentas/rodas_kit.py -- [opções]
    python -I ferramentas/test_rodas_kit.py      # confere o que saiu (redondeza, murcho, pivô, orçamento, JSON x GLB)

Saída em --out (padrão veiculos/proprios/rodas/):
    aro_aco13.glb, aro_aco14.glb, aro_aco15.glb, aro_liga13.glb, aro_liga14.glb, aro_liga15.glb   aro com o cubo, 4 parafusos e o bico; objeto aro_<id> e aro_<id>_LOD1
    pneu_p165_70.glb, pneu_p175_70.glb, pneu_p185_60.glb, pneu_p165_95.glb, pneu_p205_60.glb    pneu_<id>_Ok, _Flat, _Torn e os _LOD1 de cada um
    calota13.glb, calota14.glb, calota15.glb                        calota<pol> e calota<pol>_LOD1
    pneu_sulcos_normal.png      normal map dos sulcos da banda (também vai dentro dos GLB dos pneus)
    rodas_kit.json              por item: id, tipo, polegadas, raio externo e largura em cm, triângulos LOD0/LOD1, objetos
    rodas_kit_previa.jpg        folha de prévia em Cycles (os 4 aros montados, o pneu nos 3 estados de lado e de frente, a calota)

Convenção (a do Detonauto e do carro_quebravel.py): metros; eixo da roda em Y, frente do carro +X, cima +Z; pivô de toda malha no
centro do cubo; y = 0 no plano do meio do aro (centro da largura de 5,5"); a face de fora da roda em +Y, que é a roda do lado
esquerdo; para o lado direito, girar 180° em Z. As 3 malhas de um pneu têm o mesmo pivô: no Flat e no Torn o chão fica mais perto
do cubo (o raio físico vem do CSV, RadiusCm, e não da malha).
"""

import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(os.path.dirname(AQUI), "veiculos", "proprios", "rodas")
POL = 0.0254
LARGURA_ARO = 5.5 * POL      # 5,5" entre as abas
SEG = 64                     # segmentos na volta do aro, do pneu Ok/Flat e da calota (desvio < 0,4 mm)
SEG_TORN = 96                # o estourado tem mais segmentos para os rasgos ficarem recortados
LOD1_RAZAO = 0.4
ORCAMENTO_RODA = 9000        # aro + pneu Ok + calota, LOD0
ANGULO_QUINA = 50            # acima disto a aresta fica dura (sulcos, abas, furos)
QUEDA_FLAT = 0.06            # o murcho fica 6 cm mais baixo no ponto de contato
NB_BLOCOS = 56               # blocos da banda na volta (o normal map repete NB_BLOCOS vezes)
NORMAL_PNG = "pneu_sulcos_normal.png"
JSON_KIT = "rodas_kit.json"
PREVIA = "rodas_kit_previa.jpg"

AROS = {
    "aco13": {"tipo": "aco", "pol": 13, "furos": 6, "nome": "Aço estampado 13\" (6 furos redondos)"},
    "aco14": {"tipo": "aco", "pol": 14, "furos": 8, "nome": "Aço estampado 14\" (8 furos redondos)"},
    # furgão dos anos 60-70 (Pão de Forma, 30/10/2026): aro 15 de aço com o pneu diagonal alto
    "aco15": {"tipo": "aco", "pol": 15, "furos": 8, "nome": "Aço estampado 15\" (8 furos redondos)"},
    "liga13": {"tipo": "liga", "pol": 13, "desenho": "ovais", "furos": 8, "nome": "Liga leve 13\" (8 furos ovais)"},
    "liga14": {"tipo": "liga", "pol": 14, "desenho": "raios", "furos": 10, "nome": "Liga leve 14\" (10 raios retos)"},
    # picape aventureira dos anos 2000 (Tropeiro, 30/10/2026): liga 15 com o pneu 205/60, mais alto que o 185/60 do hatch
    "liga15": {"tipo": "liga", "pol": 15, "desenho": "ovais", "furos": 8, "nome": "Liga leve 15\" (8 furos ovais)"},
}
PNEUS = {"p165_70": (165, 70, 13), "p175_70": (175, 70, 13), "p185_60": (185, 60, 14),
         "p165_95": (165, 95, 15), "p205_60": (205, 60, 15),   # o diagonal 6.40-15 do furgão (perfil alto, o máximo do Detonauto): 34,7 cm de raio
         "p165_80": (165, 80, 15)}   # o 5.60-15 do clássico de motor atrás (Besouro, 30/10/2026): 32,2 cm de raio
CALOTAS = {"calota13": 13, "calota14": 14, "calota15": 15}
ESTADOS = ("Ok", "Flat", "Torn")


# ================================================================================================================================
# Geometria pura (sem bpy)
# ================================================================================================================================

def _norm(a):
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def normal_newell(pts):
    nx = ny = nz = 0.0
    for k in range(len(pts)):
        a, b = pts[k], pts[(k + 1) % len(pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


class Malha:
    """Vértices e faces (índices, material, UV por canto ou None) de um objeto, antes de ir para o Blender."""

    def __init__(self, nome):
        self.nome = nome
        self.v = []
        self.f = []
        self.cache = {}
        self.uma_face = False

    def vert(self, p, cache=False):
        if cache:
            k = (round(p[0] * 1e5), round(p[1] * 1e5), round(p[2] * 1e5))
            i = self.cache.get(k)
            if i is not None:
                return i
            self.cache[k] = len(self.v)
        self.v.append([p[0], p[1], p[2]])
        return len(self.v) - 1

    def face(self, idx, mat, uv=None, frente=None):
        idx = list(idx)
        uv = list(uv) if uv else None
        k = 0
        while k < len(idx) and len(idx) > 2:          # tira índice repetido (polo da revolução)
            if idx[k] == idx[(k + 1) % len(idx)]:
                del idx[k]
                if uv:
                    del uv[k]
            else:
                k += 1
        if len(set(idx)) < 3:
            return
        if frente is not None:
            n = normal_newell([self.v[i] for i in idx])
            if _dot(n, frente) < 0:
                idx.reverse()
                if uv:
                    uv.reverse()
        self.f.append((idx, mat, uv))

    def juntar(self, o):
        base = len(self.v)
        self.v += [list(p) for p in o.v]
        self.f += [([i + base for i in idx], m, uv) for idx, m, uv in o.f]

    def transformar(self, fn):
        self.v = [list(fn(p)) for p in self.v]

    def copia(self, nome):
        c = Malha(nome)
        c.v = [list(p) for p in self.v]
        c.f = [(list(i), m, list(uv) if uv else None) for i, m, uv in self.f]
        return c

    def triangulos(self):
        return sum(len(i) - 2 for i, _, _ in self.f)


def orientar(perfil, extra=None):
    """Perfil fechado em (r, y) no sentido horário (r na horizontal): a normal da revolução sai para fora."""
    a = sum(perfil[i][0] * perfil[(i + 1) % len(perfil)][1] - perfil[(i + 1) % len(perfil)][0] * perfil[i][1]
            for i in range(len(perfil)))
    if a > 0:
        perfil = perfil[::-1]
        if extra is not None:
            extra = extra[::-1]
    return (perfil, extra) if extra is not None else perfil


def revolucao(m, perfil, mat, n=SEG, fase=0.0, fechado=False, vs=None, urep=1.0, cache=False, pular=None):
    """Gira o perfil [(r, y)] em volta do eixo Y (x = r cos t, z = r sin t). A normal é a esquerda do caminho em (r, y): um perfil
    aberto andando para fora em r com y constante olha para +Y; um fechado no sentido horário olha para fora. Devolve a grade de
    índices [ponto][segmento]. vs: coordenada v da UV de cada ponto (padrão: comprimento do perfil); u = segmento / n * urep."""
    thetas = [fase + 2 * math.pi * j / n for j in range(n)]
    grade = []
    for (r, y) in perfil:
        if r < 1e-7:
            k = m.vert((0.0, y, 0.0), cache)
            grade.append([k] * n)
        else:
            grade.append([m.vert((r * math.cos(t), y, r * math.sin(t)), cache) for t in thetas])
    if vs is None:
        comp = [0.0]
        for a, b in zip(perfil, perfil[1:]):
            comp.append(comp[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        tot = comp[-1] or 1.0
        vs = [c / tot for c in comp]
    pares = list(range(len(perfil) - 1)) + ([len(perfil) - 1] if fechado else [])
    for i in pares:
        i1 = (i + 1) % len(perfil)
        v0, v1 = vs[i], vs[i1]
        if fechado and i1 == 0:
            v1 = vs[i] + 0.02
        for j in range(n):
            if pular and pular(i, j):
                continue
            j1 = (j + 1) % n
            u0, u1 = j / n * urep, (j + 1) / n * urep
            m.face([grade[i][j], grade[i][j1], grade[i1][j1], grade[i1][j]], mat, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
    return grade


def revolucao_em(m, perfil, mat, n, origem, eixo, fase=0.0):
    """Revolução de um perfil polo a polo (do polo de cima para fora e para baixo) em volta de um eixo qualquer."""
    t = Malha("tmp")
    revolucao(t, perfil, mat, n=n, fase=fase)
    e = _norm(eixo)
    ref = (1.0, 0.0, 0.0) if abs(e[0]) < 0.9 else (0.0, 0.0, 1.0)
    e1 = _norm(_cross(e, ref))
    e2 = _cross(e1, e)
    # local: x -> e2, y -> e, z -> e1 (mantém a mão: e2 x e = e1... conferido pela normal de Newell no fim)
    t.transformar(lambda p: (origem[0] + p[0] * e2[0] + p[1] * e[0] + p[2] * e1[0],
                             origem[1] + p[0] * e2[1] + p[1] * e[1] + p[2] * e1[1],
                             origem[2] + p[0] * e2[2] + p[1] * e[2] + p[2] * e1[2]))
    m.juntar(t)


def chapa_furada(m, mat, fy, r0, r1, nf, rc, forma, na, nr, aneis, fase=0.0, vies=1.0, uni=0.0):
    """Faixa da chapa entre r0 e r1, com y = fy(r), com nf furos centrados em rc. Cada setor (ângulo 2π/nf) é uma grade do contorno
    do furo até o contorno do setor (na pontos em cada arco, nr em cada lado radial), por raios saindo do centro do furo, então o
    furo fica com o contorno exato de forma(u, v) = 1 (u radial, v tangencial, em metros). O arco de dentro e o de fora ficam com
    nf * na pontos iguais, com fase fase - π/nf, e casam com as revoluções vizinhas pelo cache de vértices. uni (0 a 1) puxa os pontos
    do contorno do furo para ângulos iguais em volta do centro (furo redondo fica redondo, sem lado comprido)."""
    alfa = math.pi / nf
    for k in range(nf):
        phi = fase + 2 * math.pi * k / nf
        er = (math.cos(phi), math.sin(phi))
        et = (-math.sin(phi), math.cos(phi))
        borda = [(r0, -alfa + 2 * alfa * i / na) for i in range(na)]
        borda += [(r0 + (r1 - r0) * i / nr, alfa) for i in range(nr)]
        borda += [(r1, alfa - 2 * alfa * i / na) for i in range(na)]
        borda += [(r1 - (r1 - r0) * i / nr, -alfa) for i in range(nr)]
        ext = [(r * math.cos(phi + a), r * math.sin(phi + a)) for r, a in borda]
        C = (rc * er[0], rc * er[1])
        furo = []
        betas = [math.atan2(B[1] - C[1], B[0] - C[0]) for B in ext]
        N = len(ext)
        passo = (betas[1] - betas[0] + math.pi) % (2 * math.pi) - math.pi
        sentido = 1.0 if passo > 0 else -1.0
        for q, B in enumerate(ext):
            L = math.hypot(B[0] - C[0], B[1] - C[1])
            ang = betas[q]
            if uni:
                alvo = betas[0] + sentido * 2 * math.pi * q / N
                ang += uni * ((alvo - ang + math.pi) % (2 * math.pi) - math.pi)
            dx, dz = math.cos(ang), math.sin(ang)
            lo, hi = 0.0, L
            for _ in range(48):
                s = (lo + hi) / 2
                u = s * (dx * er[0] + dz * er[1])
                v = s * (dx * et[0] + dz * et[1])
                if forma(u, v) < 1.0:
                    lo = s
                else:
                    hi = s
            furo.append((C[0] + dx * lo, C[1] + dz * lo))
        grade = []
        for a in range(aneis + 1):
            t = (a / aneis) ** vies
            linha = []
            for H, B in zip(furo, ext):
                x, z = H[0] + (B[0] - H[0]) * t, H[1] + (B[1] - H[1]) * t
                if a == aneis:
                    x, z = B
                linha.append(m.vert((x, fy(math.hypot(x, z)), z), cache=(a == aneis)))
            grade.append(linha)
        for a in range(aneis):
            for q in range(N):
                q1 = (q + 1) % N
                m.face([grade[a][q], grade[a][q1], grade[a + 1][q1], grade[a + 1][q]], mat, frente=(0.0, 1.0, 0.0))


def espessar(m, t):
    """Dá espessura t a uma chapa aberta (para trás da normal), com paredes nas bordas (furos, cubo). Devolve uma Malha nova."""
    nv = len(m.v)
    acc = [[0.0, 0.0, 0.0] for _ in range(nv)]
    for idx, _, _ in m.f:
        n = normal_newell([m.v[i] for i in idx])
        for i in idx:
            acc[i][0] += n[0]
            acc[i][1] += n[1]
            acc[i][2] += n[2]
    o = Malha(m.nome)
    o.v = [list(p) for p in m.v]
    for p, n in zip(m.v, acc):
        n = _norm(n)
        o.v.append([p[0] - n[0] * t, p[1] - n[1] * t, p[2] - n[2] * t])
    arestas = set()
    for idx, mat, uv in m.f:
        o.f.append((list(idx), mat, uv))
        o.f.append(([i + nv for i in reversed(idx)], mat, list(reversed(uv)) if uv else None))
        for k in range(len(idx)):
            arestas.add((idx[k], idx[(k + 1) % len(idx)]))
    mats = {}
    for idx, mat, _ in m.f:
        for k in range(len(idx)):
            mats[(idx[k], idx[(k + 1) % len(idx)])] = mat
    for (a, b) in arestas:
        if (b, a) not in arestas:
            o.f.append(([b, a, a + nv, b + nv], mats[(a, b)], None))
    return o


def filete(pts, raios, n=2):
    """Arredonda os cantos de uma polilinha 2D (raio por índice); n segmentos por arco."""
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        P, rr = pts[k], raios.get(k, 0.0)
        if rr <= 0:
            out.append(P)
            continue
        a = (pts[k - 1][0] - P[0], pts[k - 1][1] - P[1])
        b = (pts[k + 1][0] - P[0], pts[k + 1][1] - P[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        a, b = (a[0] / la, a[1] / la), (b[0] / lb, b[1] / lb)
        ang = math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1])))
        if ang > math.pi - 1e-3:
            out.append(P)
            continue
        d = min(rr / math.tan(ang / 2), 0.45 * min(la, lb))
        rr = d * math.tan(ang / 2)
        bis = (a[0] + b[0], a[1] + b[1])
        lbis = math.hypot(*bis)
        bis = (bis[0] / lbis, bis[1] / lbis)
        c = (P[0] + bis[0] * rr / math.sin(ang / 2), P[1] + bis[1] * rr / math.sin(ang / 2))
        T1 = (P[0] + a[0] * d, P[1] + a[1] * d)
        T2 = (P[0] + b[0] * d, P[1] + b[1] * d)
        a1 = math.atan2(T1[1] - c[1], T1[0] - c[0])
        a2 = math.atan2(T2[1] - c[1], T2[0] - c[0])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        for s in range(n + 1):
            aa = a1 + da * s / n
            out.append((c[0] + rr * math.cos(aa), c[1] + rr * math.sin(aa)))
    out.append(pts[-1])
    return out


def deslocar(pts, t, alvo):
    """Desloca cada ponto da polilinha 2D por t ao longo da normal, para o lado do ponto alvo (meia-esquadria nos cantos)."""
    out = []
    for k, P in enumerate(pts):
        A = pts[max(k - 1, 0)]
        B = pts[min(k + 1, len(pts) - 1)]
        tx, ty = B[0] - A[0], B[1] - A[1]
        L = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / L, tx / L
        if (alvo[0] - P[0]) * nx + (alvo[1] - P[1]) * ny < 0:
            nx, ny = -nx, -ny
        out.append((P[0] + nx * t, P[1] + ny * t))
    return out


# ------------------------------------------------------------------------------------------------------------------- aros

def medidas_aro(pol):
    Rb = pol * POL / 2                  # raio do assento do talão (o "aro 13")
    W = LARGURA_ARO / 2
    return Rb, W


def perfil_tambor(Rb, W, t):
    """Tambor do aro (abas, assentos, poço), fechado com a espessura t para dentro. Abas de 19 mm com a ponta virada para fora."""
    sup = [(Rb + 0.0150, W + 0.0092),     # 0 ponta da aba
           (Rb + 0.0192, W + 0.0048),     # 1 topo da aba (arredondado)
           (Rb + 0.0172, W + 0.0004),     # 2
           (Rb + 0.0010, W),              # 3 pé da aba (escondido no talão)
           (Rb - 0.0010, W - 0.0200),     # 4 fim do assento
           (Rb - 0.0260, W - 0.0330),     # 5 fundo do poço
           (Rb - 0.0260, -W + 0.0400),    # 6
           (Rb - 0.0010, -W + 0.0220),    # 7
           (Rb + 0.0010, -W),             # 8
           (Rb + 0.0172, -W - 0.0004),    # 9
           (Rb + 0.0192, -W - 0.0048),    # 10
           (Rb + 0.0150, -W - 0.0092)]    # 11
    alvo = (Rb - 0.05, 0.0)
    off = deslocar(sup, t, alvo)
    # do lado de dentro bastam os pontos que dão a forma (o resto não aparece)
    # (o de fora aparece entre a aba e o disco; o de trás só de dentro do carro, então é mais simples)
    dentro = [(Rb + 0.0150 - t, W + 0.0092 + t * 0.3),       # ponta da aba de fora
              (Rb + 0.0192 - t * 0.7, W + 0.0048 + t * 0.7),  # topo da aba (a espessura vai para +y, o lado de fora)
              (Rb + 0.0010 - t, W + t),                       # pé da aba
              off[5],                                         # fundo do poço
              (Rb + 0.0010 - t, -W - t),                      # pé da aba de trás
              (Rb + 0.0150 - t, -W - 0.0092 - t * 0.3)]       # ponta da aba de trás
    return orientar(sup + dentro[::-1])


def disco_aco(m, Rb, nf, mat):
    k = Rb / 0.165
    Rw_in = Rb - 0.026 - 0.003
    r0, r1 = 0.086 * k, 0.128 * k
    y0, y1 = 0.0335, 0.0265
    fy = lambda r: y0 + (y1 - y0) * (r - r0) / (r1 - r0)
    na, nr, aneis = max(3, 24 // nf), 4, 2
    fase = math.pi / nf
    fase_anel = fase - math.pi / nf
    d = Malha("disco")
    hcubo = 0.0392
    perfil_in = [(0.0290 * k, hcubo), (0.0400 * k, hcubo), (0.0630 * k, hcubo), (0.0700 * k, 0.0452), (0.0775 * k, 0.0448), (r0, y0)]
    revolucao(d, perfil_in, mat, n=nf * na, fase=fase_anel, cache=True)
    hr = 0.0135 * k
    chapa_furada(d, mat, fy, r0, r1, nf, 0.106 * k, lambda u, v: (u * u + v * v) / (hr * hr), na, nr, aneis, fase=fase, uni=1.0)
    perfil_out = [(r1, y1), (Rw_in - 0.0030, y1 - 0.0025), (Rw_in - 0.0005, 0.0140), (Rw_in + 0.0015, 0.0060)]
    revolucao(d, perfil_out, mat, n=nf * na, fase=fase_anel, cache=True)
    m.juntar(espessar(d, 0.0040))
    return hcubo


def disco_liga(m, Rb, nf, desenho, mat):
    k = Rb / 0.165
    r0, r1 = 0.070 * k, 0.148 * k
    y0, y1 = 0.0470, 0.0570
    fy = lambda r: y0 + (y1 - y0) * max(0.0, min(1.0, (r - r0) / (r1 - r0))) ** 1.5
    fase = math.pi / nf
    fase_anel = fase - math.pi / nf
    d = Malha("disco")
    hcubo = 0.0500
    rcen = 0.109 * k
    if desenho == "ovais":
        na, nr, aneis = 4, 4, 2
        a, b = 0.0300 * k, 0.0165 * k
        forma = lambda u, v: (u / a) ** 2 + (v / b) ** 2
    else:                                   # raios retos: janela que alarga para fora, raio de largura constante
        na, nr, aneis = 4, 5, 2
        a, larg_raio, p = 0.0315 * k, 0.0230 * k, 6.0
        def forma(u, v):
            bb = max((rcen + u) * math.pi / nf - larg_raio / 2, 1e-4)
            return abs(u / a) ** p + abs(v / bb) ** 2.4
    perfil_in = [(0.0315 * k, hcubo), (0.0640 * k, hcubo), (0.0665 * k, 0.0480), (r0, y0)]
    revolucao(d, perfil_in, mat, n=nf * na, fase=fase_anel, cache=True)
    chapa_furada(d, mat, fy, r0, r1, nf, rcen, forma, na, nr, aneis, fase=fase, uni=0.5 if desenho == "ovais" else 0.0)
    perfil_out = [(r1, y1), (0.1545 * k, 0.0605), (Rb - 0.0060, 0.0612), (Rb - 0.0005, 0.0590)]
    revolucao(d, perfil_out, mat, n=nf * na, fase=fase_anel, cache=True)
    m.juntar(espessar(d, 0.0110))
    # tampa do centro, lisa (sem logo)
    revolucao_em(m, [(0.0, 0.0585), (0.0170 * k, 0.0580), (0.0270 * k, 0.0555), (0.0322 * k, 0.0515), (0.0322 * k, 0.0440), (0.0, 0.0440)],
                 mat, 24, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    return hcubo


def parafusos(m, y0, mat, pcd=0.100, fase=math.pi / 4):
    """4 parafusos de cabeça sextavada 17 mm com a arruela cônica, no PCD 4 x 100."""
    for i in range(4):
        a = fase + i * math.pi / 2
        x, z = pcd / 2 * math.cos(a), pcd / 2 * math.sin(a)
        revolucao_em(m, [(0.0, 0.0150), (0.0072, 0.0150), (0.0098, 0.0128), (0.0098, 0.0034), (0.0, 0.0034)], mat, 6,
                     (x, y0, z), (0.0, 1.0, 0.0), fase=math.pi / 6 + a)
        revolucao_em(m, [(0.0, 0.0036), (0.0110, 0.0036), (0.0110, 0.0012), (0.0092, -0.0015), (0.0, -0.0015)], mat, 12,
                     (x, y0, z), (0.0, 1.0, 0.0))


def cubo(m, mat):
    """Ponta do cubo do carro com a tampinha de graxa, que aparece pelo furo do centro do aro de aço."""
    revolucao_em(m, [(0.0, 0.0530), (0.0130, 0.0522), (0.0205, 0.0485), (0.0215, 0.0445), (0.0265, 0.0440), (0.0265, 0.0300),
                     (0.0, 0.0300)], mat, 12, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def bico(m, Rb, W):
    """Bico de ar no poço, saindo para fora entre o disco e a aba."""
    a = math.radians(-100)
    r = Rb - 0.0130
    base = (r * math.cos(a), W - 0.0270, r * math.sin(a))
    eixo = (0.35 * math.cos(a), 1.0, 0.35 * math.sin(a))
    revolucao_em(m, [(0.0, 0.0240), (0.0034, 0.0240), (0.0044, 0.0200), (0.0056, 0.0030), (0.0060, -0.0040), (0.0, -0.0040)],
                 "pneu", 10, base, eixo)
    e = _norm(eixo)
    revolucao_em(m, [(0.0, 0.0345), (0.0030, 0.0345), (0.0033, 0.0225), (0.0, 0.0225)], "parafuso", 8,
                 (base[0], base[1], base[2]), e)


def aro(rid):
    cfg = AROS[rid]
    Rb, W = medidas_aro(cfg["pol"])
    mat = "aro_aco" if cfg["tipo"] == "aco" else "aro_liga"
    m = Malha(f"aro_{rid}")
    t = 0.0030 if cfg["tipo"] == "aco" else 0.0045
    revolucao(m, perfil_tambor(Rb, W, t), mat, n=SEG, fechado=True)
    if cfg["tipo"] == "aco":
        hc = disco_aco(m, Rb, cfg["furos"], mat)
        cubo(m, "parafuso")
    else:
        hc = disco_liga(m, Rb, cfg["furos"], cfg["desenho"], mat)
    parafusos(m, hc, "parafuso")
    bico(m, Rb, W)
    return m


# ---------------------------------------------------------------------------------------------------------------- calotas

def calota(cid):
    pol = CALOTAS[cid]
    Rb, W = medidas_aro(pol)
    k = Rb / 0.165
    m = Malha(cid)
    d = Malha(cid)
    nf, na, nr, aneis = 10, 4, 1, 1
    fase = 0.0
    fase_anel = fase - math.pi / nf
    r0, r1 = 0.1060 * k, 0.1290 * k
    y0, y1 = 0.0838, 0.0808
    fy = lambda r: y0 + (y1 - y0) * (r - r0) / (r1 - r0)
    hf = 0.0058 * k
    perfil_in = [(0.0, 0.0955), (0.0300 * k, 0.0950), (0.0345 * k, 0.0905), (0.0700 * k, 0.0878), (r0, y0)]
    revolucao(d, perfil_in, "calota", n=nf * na, fase=fase_anel, cache=True)
    chapa_furada(d, "calota", fy, r0, r1, nf, 0.1175 * k, lambda u, v: (u * u + v * v) / (hf * hf), na, nr, aneis, fase=fase,
                 uni=1.0)
    W_ = W + 0.0035
    perfil_out = [(r1, y1), (0.1395 * k, 0.0765), (0.1490 * k, 0.0808), (Rb - 0.0020, 0.0795), (Rb + 0.0060, W_ + 0.0030),
                  (Rb + 0.0055, W_)]
    revolucao(d, perfil_out, "calota", n=nf * na, fase=fase_anel, cache=True)
    # chapa estampada de 1 face: o material calota é de duas faces (doubleSided no glTF), então a calota solta também aparece por trás
    m.juntar(d)
    m.uma_face = True
    return m


def calota_lod1(cid, seg=28):
    """LOD1 da calota feito por geometria (o decimate serrilha a borda da chapa de uma face): o mesmo perfil, sem os furinhos."""
    Rb, W = medidas_aro(CALOTAS[cid])
    k = Rb / 0.165
    W_ = W + 0.0035
    m = Malha(cid + "_LOD1")
    revolucao(m, [(0.0, 0.0955), (0.0345 * k, 0.0905), (0.1060 * k, 0.0838), (0.1290 * k, 0.0808), (0.1395 * k, 0.0765),
                  (0.1490 * k, 0.0808), (Rb + 0.0060, W_ + 0.0030), (Rb + 0.0055, W_)], "calota", n=seg)
    m.uma_face = True
    return m


# ----------------------------------------------------------------------------------------------------------------- pneus

def medidas_pneu(pid):
    larg, perf, pol = PNEUS[pid]
    Rb, W = medidas_aro(pol)
    S = larg / 2000.0
    H = larg * perf / 100000.0
    R = Rb + H
    T = S * (0.80 if perf >= 70 else 0.84)
    return {"Rb": Rb, "W": W, "S": S, "H": H, "R": R, "T": T, "pol": pol, "larg_mm": larg, "perfil": perf}


def perfil_pneu(M):
    """Perfil aberto do pneu, do talão de fora (+y) ao talão de dentro (-y), passando pela banda, com a coordenada v de cada ponto
    (o normal map tem a banda em v de 0,3 a 0,7) e o índice dos pontos da banda."""
    Rb, W, S, H, R, T = M["Rb"], M["W"], M["S"], M["H"], M["R"], M["T"]
    talao = [(Rb + 0.0175, W - 0.0015), (Rb + 0.0215, W + 0.0040)]
    flanco = [(Rb + 0.28 * H, S - 0.0040), (Rb + 0.55 * H, S), (Rb + 0.80 * H, S - 0.0050), (R - 0.0100, T + 0.0090),
              (R - 0.0012, T - 0.0030)]
    lado = talao + flanco
    comp = [0.0]
    for a, b in zip(lado, lado[1:]):
        comp.append(comp[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    v_lado = [0.3 * c / comp[-1] for c in comp]
    qs = (0.405, 0.390, 0.330, 0.315, -0.315, -0.330, -0.390, -0.405)
    fundo = {0.390, 0.330, -0.330, -0.390}
    banda = []
    for q in qs:
        r = R - 0.0012 * q * q - (0.0075 if q in fundo else 0.0)
        banda.append((r, q * T))
    v_banda = [0.5 - 0.2 * q for q in qs]
    pts = lado + banda + [(r, -y) for r, y in reversed(lado)]
    vs = v_lado + v_banda + [1.0 - v for v in reversed(v_lado)]
    i_banda = (len(lado) - 1, len(lado) + len(banda))   # segmentos da banda: do fim do flanco + ao começo do flanco -
    return pts, vs, i_banda


def pneu_ok(pid):
    M = medidas_pneu(pid)
    pts, vs, _ = perfil_pneu(M)
    m = Malha(f"pneu_{pid}_Ok")
    # fechado pelo forro (cilindro escondido no poço do aro)
    revolucao(m, pts, "pneu", n=SEG, fechado=True, vs=vs, urep=NB_BLOCOS)
    return m, M


def deformacao_murcha(M, Rf, bojo, rugas=0.0, chao=None, bagunca=0.0):
    """Murcha o pneu em volta do cubo: a banda achata no plano z = -Rf (perto do chão), o flanco encolhe na altura e estufa para
    fora (bojo, em metros, onde o pneu mais encolheu), a banda alarga um pouco no contato. rugas: dobras no flanco amassado."""
    Rb, R = M["Rb"], M["R"]
    H = R - Rb

    def f(p):
        x, y, z = p
        rho = math.hypot(x, z)
        if rho < 1e-9:
            return p
        c = -z / rho
        Reff = R
        if c > 1e-6:
            Reff = min(R, Rf / c)
        th = math.atan2(z, x)
        if bagunca:
            Reff -= bagunca * (0.5 + 0.5 * math.sin(3 * th + 0.7)) * (0.6 + 0.4 * math.sin(7 * th))
        s = (Reff - Rb) / H
        t = max(0.0, min(1.0, (rho - Rb) / H))
        rho2 = Rb + (rho - Rb) * s
        comp = 1.0 - s
        dy = bojo / 0.5 * comp * math.sin(math.pi * min(t, 0.999)) ** 0.8 if comp > 0 else 0.0
        if rugas and comp > 0.05:
            dy += rugas * comp * math.sin(9 * th + 1.3) * math.sin(math.pi * t)
            rho2 += 0.5 * rugas * comp * math.sin(13 * th) * math.sin(math.pi * t)
        y2 = y + math.copysign(dy, y) if abs(y) > 1e-6 else y
        if t > 0.8:
            y2 *= 1.0 + 0.10 * comp * (t - 0.8) / 0.2
        x2, z2 = rho2 * x / rho, rho2 * z / rho
        if chao is not None and z2 < chao:
            z2 = chao
        return (x2, y2, z2)
    return f


def pneu_flat(pid, ok, M):
    m = ok.copia(f"pneu_{pid}_Flat")
    Rf = M["R"] - QUEDA_FLAT
    m.transformar(deformacao_murcha(M, Rf, bojo=0.026, chao=-Rf))
    return m


def _rasgo(i, j, n, i_banda, i_flanco):
    """Células da banda (e do ombro de fora) que somem nos rasgos do estourado; bordas recortadas."""
    def borda(i, sem):
        return 0.5 + 0.5 * math.sin(i * 2.3 + sem) * math.cos(i * 1.1 + 2 * sem)
    th = 360.0 * (j + 0.5) / n
    rasgos = ((40.0, 11.0, 0.0, i_flanco, i_banda[1] - 2), (152.0, 7.0, 1.7, i_banda[0], i_banda[1] - 1),
              (255.0, 5.0, 3.1, i_banda[0] + 2, i_banda[1] - 3))
    for c, hw, sem, ia, ib in rasgos:
        if ia <= i <= ib:
            w = hw * (0.55 + 0.6 * borda(i, sem))
            if abs((th - c + 180.0) % 360.0 - 180.0) < w:
                return True
    return False


def fita(m, pts, larg, esp, mat, torcao=0.0):
    """Tira solta de borracha ao longo da linha pts (seção retangular larg x esp, a largura no eixo Y da roda)."""
    secs = []
    for k, C in enumerate(pts):
        A, B = pts[max(k - 1, 0)], pts[min(k + 1, len(pts) - 1)]
        d = _norm((B[0] - A[0], B[1] - A[1], B[2] - A[2]))
        w = (0.0, 1.0, 0.0)
        w = _norm((w[0] - d[0] * d[1], w[1] - d[1] * d[1], w[2] - d[2] * d[1]))
        nn = _cross(d, w)
        a = torcao * k / max(len(pts) - 1, 1)
        w, nn = (_norm((w[0] * math.cos(a) + nn[0] * math.sin(a), w[1] * math.cos(a) + nn[1] * math.sin(a),
                        w[2] * math.cos(a) + nn[2] * math.sin(a))),
                 _norm((nn[0] * math.cos(a) - w[0] * math.sin(a), nn[1] * math.cos(a) - w[1] * math.sin(a),
                        nn[2] * math.cos(a) - w[2] * math.sin(a))))
        fim = 1.0 - 0.6 * (k / (len(pts) - 1)) ** 3         # afina na ponta
        hw, he = larg / 2 * fim, esp / 2
        sec = []
        for sw, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            sec.append(m.vert((C[0] + w[0] * hw * sw + nn[0] * he * sn, C[1] + w[1] * hw * sw + nn[1] * he * sn,
                               C[2] + w[2] * hw * sw + nn[2] * he * sn)))
        secs.append(sec)
    for s0, s1 in zip(secs, secs[1:]):
        for q in range(4):
            q1 = (q + 1) % 4
            m.face([s0[q], s0[q1], s1[q1], s1[q]], mat)
    m.face(secs[0][::-1], mat)
    m.face(secs[-1], mat)


def pneu_torn(pid, M):
    """Estourado: casca oca (9 mm de borracha), banda com rasgos de borda recortada e paredes no corte, a metade de baixo caída
    (o aro fica a ~1,6 cm do chão pela borracha dobrada), flanco amassado com dobras e tiras soltas penduradas."""
    pts, vs, i_banda = perfil_pneu(M)
    mm = len(pts)
    centro = (M["Rb"] + 0.5 * M["H"], 0.0)
    dentro = deslocar(pts, 0.009, centro)
    loop = pts + dentro[::-1]
    vloop = vs + vs[::-1]
    i_flanco = 4                                         # do meio do flanco de fora até a banda
    n = SEG_TORN

    def i_fora(seg):
        if seg <= mm - 2:
            return seg
        if mm <= seg <= 2 * mm - 2:
            return 2 * mm - 2 - seg
        return None

    def pular(seg, j):
        i = i_fora(seg)
        return i is not None and _rasgo(i, j, n, i_banda, i_flanco)

    m = Malha(f"pneu_{pid}_Torn")
    grade = revolucao(m, loop, "pneu", n=n, fechado=True, vs=vloop, urep=NB_BLOCOS, pular=pular)
    par = {}
    for i in range(mm):
        for j in range(n):
            par[grade[i][j]] = grade[2 * mm - 1 - i][j]
    arestas = set()
    for idx, _, _ in m.f:
        for k in range(len(idx)):
            arestas.add((idx[k], idx[(k + 1) % len(idx)]))
    corte = set()
    for (a, b) in list(arestas):
        if (b, a) not in arestas and a in par and b in par:
            m.face([b, a, par[a], par[b]], "pneu")
            corte.update((a, b))
    import random
    rnd = random.Random(7)
    for a in sorted(corte):                  # borda rasgada: cada ponto do corte anda um pouco em ângulo, de lado e afunda
        dth = math.radians(rnd.uniform(-2.6, 2.6))
        dy = rnd.uniform(-0.005, 0.005)
        dr = -rnd.uniform(0.0, 0.010)
        for vi in (a, par[a]):
            x, y, z = m.v[vi]
            rho = math.hypot(x, z)
            th = math.atan2(z, x) + dth
            m.v[vi] = [(rho + dr) * math.cos(th), y + dy, (rho + dr) * math.sin(th)]
    Rf = M["Rb"] + 0.0192 + 0.0165
    f = deformacao_murcha(M, Rf, bojo=0.050, rugas=0.007, chao=-Rf, bagunca=0.006)
    m.transformar(f)
    # tiras soltas: saem da borda de trás do rasgo grande e de um dos menores, descolam e caem
    R, T = M["R"], M["T"]
    for th0, q, comp, larg, tor, lado in ((40.0 - 9.0, 0.20, 0.20, 0.055, 1.1, 1), (40.0 + 9.0, -0.40, 0.13, 0.045, -0.9, -1),
                                          (152.0 + 6.0, 0.05, 0.16, 0.060, 0.8, -1)):
        a = math.radians(th0)
        P = [R * math.cos(a), q * T, R * math.sin(a)]
        tang = (-math.sin(a) * lado, 0.0, math.cos(a) * lado)
        rad = (math.cos(a), 0.0, math.sin(a))
        d = _norm((0.35 * tang[0] + 0.95 * rad[0], 0.0, 0.35 * tang[2] + 0.95 * rad[2]))
        linha = [(P[0] - tang[0] * 0.012, P[1], P[2] - tang[2] * 0.012)]
        ds = comp / 10
        for k in range(11):
            linha.append(tuple(P))
            d = _norm((d[0] * 0.8, d[1] + 0.05 * math.sin(1.7 * k), d[2] - 0.55))    # a gravidade puxa a tira para baixo
            P = [P[0] + d[0] * ds, P[1] + d[1] * ds, P[2] + d[2] * ds]
            if P[2] < -Rf + 0.006:
                P[2] = -Rf + 0.006
        linha = [f(p) if i < 2 else p for i, p in enumerate(linha)]
        fita(m, linha, larg, 0.0085, "pneu", torcao=tor)
    return m


def triangulos_roda(t_aro, t_pneu, t_calota=0):
    return t_aro + t_pneu + t_calota


# ================================================================================================================================
# Blender
# ================================================================================================================================

def mapa_sulcos(caminho, W=96, Hpx=512):
    """Normal map dos sulcos (um bloco da banda por ladrilho em u; v de 0,3 a 0,7 é a banda, o resto é o flanco)."""
    import numpy as np
    u = (np.arange(W) + 0.5) / W
    v = (np.arange(Hpx) + 0.5) / Hpx
    U, V = np.meshgrid(u, v)
    q = (0.5 - V) / 0.2
    aq = np.abs(q)
    h = np.zeros_like(U)

    def sulco(uc, larg, prof, mascara, macio=0.35):
        du = np.abs(((U - uc + 0.5) % 1.0) - 0.5)
        borda = larg / 2
        perfil = np.clip((borda - du) / (borda * macio + 1e-6), 0.0, 1.0)
        return -prof * perfil * mascara

    def faixa(a, b, macio=0.02):
        return np.clip((aq - a) / macio, 0, 1) * np.clip((b - aq) / macio, 0, 1)

    lado = np.where(q >= 0, 0.0, 0.5)
    ombro = faixa(0.43, 1.18, 0.03)
    h += sulco(0.50 + lado + 0.20 * (aq - 0.43), 0.11, 1.0, ombro)
    h += sulco(0.00 + lado + 0.20 * (aq - 0.43), 0.035, 0.6, faixa(0.47, 0.92))
    meio = faixa(0.0, 0.30, 0.02)
    h += sulco(0.15 + 0.45 * (q + 0.30) / 0.60, 0.040, 0.8, meio)
    h += sulco(0.65 + 0.45 * (q + 0.30) / 0.60, 0.040, 0.8, meio)
    h -= 0.5 * np.clip((0.02 - aq) / 0.01, 0, 1)                  # sulquinho do centro
    # flanco: friso de proteção perto do aro e frisos finos concêntricos (sem letra)
    vs = np.minimum(V, 1.0 - V)
    h += 0.6 * np.clip(1 - np.abs(vs - 0.045) / 0.012, 0, 1)
    h += 0.25 * np.clip(1 - np.abs(vs - 0.235) / 0.006, 0, 1)
    h += 0.08 * np.sin(2 * np.pi * vs * 90) * ((vs > 0.07) & (vs < 0.20))
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) / 2
    dy = np.gradient(h, axis=0)
    s = 2.2
    nx, ny, nz = -dx * s, -dy * s, np.ones_like(h)
    L = np.sqrt(nx * nx + ny * ny + nz * nz)
    img = np.stack([(nx / L + 1) / 2, (ny / L + 1) / 2, (nz / L + 1) / 2, np.ones_like(h)], axis=-1).astype(np.float32)
    import bpy
    im = bpy.data.images.new("pneu_sulcos_normal", W, Hpx, alpha=False)
    im.colorspace_settings.name = "Non-Color"
    im.pixels.foreach_set(img.ravel())
    im.filepath_raw = caminho
    im.file_format = "PNG"
    im.save()
    return im


def materiais(out):
    import bpy

    def principled(nome, cor, metal, rug, spec=0.5):
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*cor, 1.0)
        b.inputs["Metallic"].default_value = metal
        b.inputs["Roughness"].default_value = rug
        try:
            b.inputs["Specular IOR Level"].default_value = spec
        except KeyError:
            pass
        return m, b
    mats = {}
    # 29/10 (o Felipe: "pneus e rodas têm que ter mais cara de realismo"): aro de aço com tinta prata de fábrica (não o cinza
    # chumbo de antes), liga e calota mais espelhadas, pneu de borracha nova (preto fosco, não preto chapado)
    # 29/10 (noite, no jogo): espelhadas, calota e aro só refletiam o chão e o escuro da caixa de roda e a roda saía preta. A calota
    # da época é plástico pintado de prata e o aro é aço pintado: acetinados, pouco metal, claros por conta própria
    mats["aro_aco"], _ = principled("aro_aco", (0.60, 0.61, 0.62), 0.40, 0.35)
    mats["aro_liga"], _ = principled("aro_liga", (0.66, 0.66, 0.65), 0.60, 0.25)
    mats["calota"], _ = principled("calota", (0.78, 0.79, 0.80), 0.35, 0.22)
    mats["calota"].use_backface_culling = False
    mats["parafuso"], _ = principled("parafuso", (0.55, 0.55, 0.53), 1.0, 0.35)
    m, b = principled("pneu", (0.034, 0.034, 0.036), 0.0, 0.72, spec=0.45)
    im = mapa_sulcos(os.path.join(out, NORMAL_PNG))
    nt = m.node_tree
    tx = nt.nodes.new("ShaderNodeTexImage")
    tx.image = im
    tx.interpolation = "Linear"
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nm.inputs["Strength"].default_value = 1.0
    nt.links.new(tx.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], b.inputs["Normal"])
    mats["pneu"] = m
    return mats


def finalizar(m, mats):
    """Malha -> objeto do Blender: materiais na ordem de uso, UV (planar onde não tem), normais para fora, quinas duras."""
    import bmesh
    import bpy
    nomes = []
    for _, mat, _ in m.f:
        if mat not in nomes:
            nomes.append(mat)
    me = bpy.data.meshes.new(m.nome)
    me.from_pydata([tuple(p) for p in m.v], [], [idx for idx, _, _ in m.f])
    uvl = me.uv_layers.new(name="UVMap")
    for poly, (idx, mat, uv) in zip(me.polygons, m.f):
        poly.material_index = nomes.index(mat)
        n = normal_newell([m.v[i] for i in idx])
        ax = max(range(3), key=lambda i: abs(n[i]))
        for k, li in enumerate(poly.loop_indices):
            if uv:
                uvl.data[li].uv = uv[k]
            else:
                c = m.v[idx[k]]
                a, b = [(1, 2), (0, 2), (0, 1)][ax]
                uvl.data[li].uv = (c[a] * 10, c[b] * 10)
    for nm in nomes:
        me.materials.append(mats[nm])
    if not m.uma_face:                    # sólidos fechados: normais para fora; a chapa de 1 face já sai com a frente em +Y
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    me.set_sharp_from_angle(angle=math.radians(ANGULO_QUINA))
    me.validate()
    return bpy.data.objects.new(m.nome, me)


def tri(ob):
    ob.data.calc_loop_triangles()
    return len(ob.data.loop_triangles)


def fazer_lod1(ob, col, razao=LOD1_RAZAO):
    import bpy
    mod = ob.modifiers.new("lod1", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = razao
    mod.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(mod)
    me.name = ob.name + "_LOD1"
    me.set_sharp_from_angle(angle=math.radians(ANGULO_QUINA))
    lod = bpy.data.objects.new(ob.name + "_LOD1", me)
    col.objects.link(lod)
    return lod


def exportar(objs, caminho):
    import bpy
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=caminho, export_format="GLB", use_selection=True, export_apply=True,
                              export_image_format="AUTO", export_extras=True, export_yup=True)


def caixa(ob):
    xs = [v.co.x for v in ob.data.vertices]
    ys = [v.co.y for v in ob.data.vertices]
    zs = [v.co.z for v in ob.data.vertices]
    return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]


def raio_max(ob):
    return max(math.hypot(v.co.x, v.co.z) for v in ob.data.vertices)


# ------------------------------------------------------------------------------------------------------------------ prévia

def preparar_cena(amostras):
    import bmesh
    import bpy
    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = amostras
    cena.cycles.use_denoising = True
    try:
        cena.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    cena.cycles.max_bounces = 8
    ids = [i.identifier for i in cena.view_settings.bl_rna.properties["view_transform"].enum_items]
    cena.view_settings.view_transform = "AgX" if "AgX" in ids else "Standard"
    cena.render.resolution_x, cena.render.resolution_y = 1400, 350
    cena.render.image_settings.file_format = "PNG"
    mundo = bpy.data.worlds.new("previa")
    mundo.use_nodes = True
    bg = mundo.node_tree.nodes["Background"]
    sky = mundo.node_tree.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "HOSEK_WILKIE"
        sky.sun_direction = (0.4, 0.6, 0.7)
    except Exception:
        pass
    mundo.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.8
    cena.world = mundo
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 4.0
    sol.data.angle = math.radians(6)
    sol.rotation_euler = (math.radians(52), math.radians(0), math.radians(150))
    cena.collection.objects.link(sol)
    chao = bpy.data.meshes.new("chao")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=20)
    bm.to_mesh(chao)
    bm.free()
    ob = bpy.data.objects.new("chao", chao)
    mt = bpy.data.materials.new("chao")
    mt.use_nodes = True
    nt = mt.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.9
    ruido = nt.nodes.new("ShaderNodeTexNoise")
    ruido.inputs["Scale"].default_value = 40.0
    rampa = nt.nodes.new("ShaderNodeValToRGB")
    rampa.color_ramp.elements[0].color = (0.16, 0.16, 0.155, 1)
    rampa.color_ramp.elements[1].color = (0.27, 0.265, 0.25, 1)
    nt.links.new(ruido.outputs["Fac"], rampa.inputs["Fac"])
    nt.links.new(rampa.outputs["Color"], b.inputs["Base Color"])
    chao.materials.append(mt)
    cena.collection.objects.link(ob)
    # luz de preenchimento do lado da câmera (como um céu nublado refletido)
    lz = bpy.data.objects.new("preench", bpy.data.lights.new("preench", "AREA"))
    lz.data.energy = 450
    lz.data.size = 4.0
    lz.location = (1.8, 5.0, 3.0)
    from mathutils import Vector
    lz.rotation_euler = (Vector((1.8, 0, 0.3)) - lz.location).to_track_quat("-Z", "Y").to_euler()
    cena.collection.objects.link(lz)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cena.collection.objects.link(cam)
    cena.camera = cam
    return cena, cam


def montar(cena, nome, objs, x, rz, alvo_chao=True):
    """Coloca cópias (mesma malha) dos objetos num vazio em x, girado rz em Z, com o ponto mais baixo no chão."""
    import bpy
    from mathutils import Matrix
    piv = bpy.data.objects.new(nome, None)
    cena.collection.objects.link(piv)
    zmin = min(min(v.co.z for v in o.data.vertices) for o in objs)
    piv.location = (x, 0.0, -zmin if alvo_chao else 0.0)
    piv.rotation_euler = (0.0, 0.0, rz)
    cop = []
    for o in objs:
        c = bpy.data.objects.new(nome + "_" + o.name, o.data)
        cena.collection.objects.link(c)
        c.parent = piv
        c.matrix_parent_inverse = Matrix.Identity(4)
        cop.append(c)
    return [piv] + cop


def previa(itens, out, amostras):
    import bpy
    from mathutils import Vector
    cena, cam = preparar_cena(amostras)
    for o in bpy.context.view_layer.objects:
        if o.type == "MESH" and o.name != "chao":
            o.hide_render = True
    cam.data.lens = 38
    cam.data.sensor_fit = "HORIZONTAL"
    linhas = []
    # linha 1: os 4 aros montados (13" no p175_70, 14" no p185_60) e o aço 13" com a calota, a 4 m, um pouco de 3/4
    pn = {13: itens["pneu_p175_70"]["Ok"], 14: itens["pneu_p185_60"]["Ok"]}
    montagens = [("aco13", 13, None), ("aco14", 14, None), ("liga13", 13, None), ("liga14", 14, None), ("aco13", 13, "calota13")]
    grupos = []
    for k, (rid, pol, cal) in enumerate(montagens):
        objs = [itens["aro_" + rid]["obj"], pn[pol]]
        if cal:
            objs.append(itens[cal]["obj"])
        grupos.append(montar(cena, f"A{k}", objs, -k * 0.78, math.radians(-22)))
    xs = [-k * 0.78 for k in range(len(montagens))]
    linhas.append((grupos, xs, ["aço 13\" (p175/70)", "aço 14\" (p185/60)", "liga 13\" (p175/70)", "liga 14\" (p185/60)",
                                "aço 13\" + calota"]))
    # linha 2: o p175_70 no aço 13" nos 3 estados, de lado e de frente
    grupos2 = []
    xs2 = [-x for x in (0.0, 0.70, 1.40, 2.12, 2.62, 3.12)]
    nomes2 = []
    p = itens["pneu_p175_70"]
    for k, est in enumerate(ESTADOS):
        grupos2.append(montar(cena, f"B{k}", [itens["aro_aco13"]["obj"], p[est]], xs2[k], 0.0))
        nomes2.append(f"{est} (lado)")
    for k, est in enumerate(ESTADOS):
        grupos2.append(montar(cena, f"C{k}", [itens["aro_aco13"]["obj"], p[est]], xs2[3 + k], math.radians(90)))
        nomes2.append(f"{est} (frente)")
    linhas.append((grupos2, xs2, nomes2))
    arquivos = []
    for li, (gr, xs_, _) in enumerate(linhas):
        for lj, (gr2, _, _) in enumerate(linhas):
            for o in [o for g in gr2 for o in g]:
                o.hide_render = (lj != li)
        xc = (xs_[0] + xs_[-1]) / 2
        cam.location = (xc, 4.0, 0.62)
        cam.rotation_euler = (Vector((xc, 0.0, 0.30)) - cam.location).to_track_quat("-Z", "Y").to_euler()
        arq = os.path.join(out, f"_previa_{li}.png")
        cena.render.filepath = arq
        bpy.ops.render.render(write_still=True)
        arquivos.append(arq)
    from PIL import Image, ImageDraw, ImageFont
    folha = Image.new("RGB", (1400, 700))
    try:
        fonte = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    except OSError:
        fonte = ImageFont.load_default()
    for li, arq in enumerate(arquivos):
        im = Image.open(arq).convert("RGB")
        folha.paste(im, (0, li * 350))
        os.remove(arq)
    d = ImageDraw.Draw(folha)
    # rótulos sob cada objeto: projeta o x de cada montagem na imagem
    from bpy_extras.object_utils import world_to_camera_view
    for li, (gr, xs_, nomes) in enumerate(linhas):
        xc = (xs_[0] + xs_[-1]) / 2
        cam.location = (xc, 4.0, 0.62)
        cam.rotation_euler = (Vector((xc, 0.0, 0.30)) - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        for x, nome in zip(xs_, nomes):
            c = world_to_camera_view(cena, cam, Vector((x, 0.0, 0.0)))
            px = int(c.x * 1400)
            w = d.textlength(nome, font=fonte)
            d.text((px - w / 2, li * 350 + 326), nome, fill=(235, 235, 235), font=fonte)
    d.text((10, 8), "rodas_kit.py: aros, pneu Ok/Flat/Torn e calota (CC0, geometria própria), a 4 m", fill=(20, 20, 20), font=fonte)
    caminho = os.path.join(out, PREVIA)
    folha.save(caminho, quality=88)
    return caminho


# ------------------------------------------------------------------------------------------------------------------ principal

def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(description="Kit de rodas CC0 (aros, pneus Ok/Flat/Torn, calotas) para o Detonauto")
    p.add_argument("--out", default=SAIDA)
    p.add_argument("--amostras", type=int, default=32)
    p.add_argument("--sem-previa", action="store_true")
    # só estes itens (ex.: p165_80): os outros GLBs ficam como estão e o rodas_kit.json recebe os novos, sem perder
    # os que já tinha; sem prévia
    p.add_argument("--so", default="")
    return p.parse_args(argv)


def principal(argv):
    a = parse_args(argv)
    import bpy
    os.makedirs(a.out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = materiais(a.out)
    col = bpy.data.collections.new("rodas")
    bpy.context.scene.collection.children.link(col)
    col1 = bpy.data.collections.new("rodas_LOD1")
    bpy.context.scene.collection.children.link(col1)

    def obj(malha):
        ob = finalizar(malha, mats)
        col.objects.link(ob)
        return ob

    itens = {}
    rel = {"gerado_por": "acervo-3d/ferramentas/rodas_kit.py",
           "licenca": "CC0 (próprio do estúdio; geometria feita pelo script, nada baixado, nada de IA, sem marca, logo nem letra)",
           "convencao": "metros; eixo da roda em Y, frente +X, cima +Z; pivô no centro do cubo; y = 0 no meio da largura do aro; face de "
                        "fora em +Y (roda esquerda; a direita gira 180° em Z); as 3 malhas de um pneu têm o mesmo pivô",
           "segmentos": {"aro_pneu_calota": SEG, "pneu_torn": SEG_TORN}, "lod1_razao": LOD1_RAZAO,
           "normal_map": NORMAL_PNG, "orcamento_roda_lod0": ORCAMENTO_RODA, "itens": []}
    so = {x.strip() for x in a.so.split(",") if x.strip()}
    for rid, cfg in AROS.items():
        if so and rid not in so:
            continue
        ob = obj(aro(rid))
        l1 = fazer_lod1(ob, col1)
        iid = "aro_" + rid
        exportar([ob, l1], os.path.join(a.out, iid + ".glb"))
        bb = caixa(ob)
        itens[iid] = {"obj": ob, "lod": l1}
        rel["itens"].append({"id": iid, "tipo": "aro", "material": ob.data.materials[0].name, "nome": cfg["nome"],
                             "polegadas": cfg["pol"], "largura_aro_pol": 5.5, "raio_externo_cm": round(raio_max(ob) * 100, 2),
                             "largura_cm": round((bb[3] - bb[2]) * 100, 2), "triangulos_lod0": tri(ob), "triangulos_lod1": tri(l1),
                             "objetos": [ob.name, l1.name], "arquivo": iid + ".glb"})
    for cid in CALOTAS:
        if so and cid not in so:
            continue
        ob = obj(calota(cid))
        l1 = finalizar(calota_lod1(cid), mats)
        col1.objects.link(l1)
        exportar([ob, l1], os.path.join(a.out, cid + ".glb"))
        bb = caixa(ob)
        itens[cid] = {"obj": ob, "lod": l1}
        rel["itens"].append({"id": cid, "tipo": "calota", "material": "calota", "polegadas": CALOTAS[cid],
                             "raio_externo_cm": round(raio_max(ob) * 100, 2), "largura_cm": round((bb[3] - bb[2]) * 100, 2),
                             "triangulos_lod0": tri(ob), "triangulos_lod1": tri(l1), "objetos": [ob.name, l1.name],
                             "arquivo": cid + ".glb"})
    for pid in PNEUS:
        if so and pid not in so:
            continue
        ok_m, M = pneu_ok(pid)
        objs = {"Ok": obj(ok_m), "Flat": obj(pneu_flat(pid, ok_m, M)), "Torn": obj(pneu_torn(pid, M))}
        lods = {e: fazer_lod1(o, col1) for e, o in objs.items()}
        iid = "pneu_" + pid
        exportar([objs[e] for e in ESTADOS] + [lods[e] for e in ESTADOS], os.path.join(a.out, iid + ".glb"))
        bb = caixa(objs["Ok"])
        itens[iid] = dict(objs)
        larg, perf, pol = PNEUS[pid]
        rel["itens"].append({"id": iid, "tipo": "pneu", "material": "pneu", "medida": f"{larg}/{perf} R{pol}", "polegadas": pol,
                             "largura_mm": larg, "perfil_pct": perf,
                             "raio_externo_cm": round(raio_max(objs["Ok"]) * 100, 2),
                             "raio_nominal_cm": round(M["R"] * 100, 2),
                             "largura_cm": round((bb[3] - bb[2]) * 100, 2),
                             "raio_contato_cm": {e: round(-min(v.co.z for v in objs[e].data.vertices) * 100, 2) for e in ESTADOS},
                             "triangulos_lod0": sum(tri(objs[e]) for e in ESTADOS),
                             "triangulos_lod1": sum(tri(lods[e]) for e in ESTADOS),
                             "triangulos_por_objeto": {**{objs[e].name: tri(objs[e]) for e in ESTADOS},
                                                       **{lods[e].name: tri(lods[e]) for e in ESTADOS}},
                             "objetos": [objs[e].name for e in ESTADOS] + [lods[e].name for e in ESTADOS],
                             "arquivo": iid + ".glb"})
    if so:
        # junta ao JSON que já existe: os itens novos substituem os de mesmo id
        antigo = os.path.join(a.out, JSON_KIT)
        if os.path.exists(antigo):
            with open(antigo, encoding="utf-8") as f:
                velho = json.load(f)
            novos = {it["id"] for it in rel["itens"]}
            rel["itens"] = [it for it in velho.get("itens", []) if it["id"] not in novos] + rel["itens"]
            if velho.get("previa"):
                rel["previa"] = velho["previa"]
        a.sem_previa = True
    # orçamento: cada aro com cada pneu da mesma polegada (e a calota, nos de aço)
    tri_de = {it["id"]: it for it in rel["itens"]}
    rodas = []
    for rid, cfg in AROS.items():
        for pid, (_, _, pol) in PNEUS.items():
            if pol != cfg["pol"]:
                continue
            if "aro_" + rid not in tri_de or "pneu_" + pid not in tri_de:
                continue
            t_aro = tri_de["aro_" + rid]["triangulos_lod0"]
            t_ok = tri_de["pneu_" + pid]["triangulos_por_objeto"][f"pneu_{pid}_Ok"]
            cal = f"calota{pol}" if cfg["tipo"] == "aco" else None
            t_cal = tri_de[cal]["triangulos_lod0"] if cal else 0
            tot = triangulos_roda(t_aro, t_ok, t_cal)
            rodas.append({"aro": "aro_" + rid, "pneu": f"pneu_{pid}_Ok", "calota": cal, "triangulos_lod0": tot,
                          "dentro_do_orcamento": tot <= ORCAMENTO_RODA})
    rel["rodas_completas"] = rodas
    for it in rel["itens"]:
        print(f"{it['id']:16s} LOD0 {it['triangulos_lod0']:6d}  LOD1 {it['triangulos_lod1']:6d}  raio {it['raio_externo_cm']} cm  "
              f"largura {it['largura_cm']} cm")
    for r in rodas:
        print(f"roda {r['aro']} + {r['pneu']} + {r['calota']}: {r['triangulos_lod0']} triângulos")
    if not a.sem_previa:
        rel["previa"] = os.path.basename(previa(itens, a.out, a.amostras))
    with open(os.path.join(a.out, JSON_KIT), "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=1)
    return 0


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(principal(argv))


if __name__ == "__main__":
    main()
