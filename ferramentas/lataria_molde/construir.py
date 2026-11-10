"""
Lataria por molde: constrói o carro inteiro a partir da ficha de texto, sempre igual.

    blender-nuvem.sh ferramentas/lataria_molde/construir.py -- --ficha ferramentas/lataria_molde/fichas/cuiabano.json --out <pasta> [--nivel 3]

Passos:
  1. a gaiola de quadriláteros do gabarito (gabarito_hatch.py) com as cotas da ficha;
  2. a superfície-mestra: a gaiola inteira subdividida (Catmull-Clark). Toda peça é assentada nela e herda a normal dela, então o
     reflexo atravessa as frestas sem degrau;
  3. cada peça é o pedaço da gaiola da sua região, subdividido sozinho: a borda vira uma curva lisa (a mesma nos dois vizinhos do
     corte), os cantos arredondam, e a borda recua meia fresta;
  4. o que nasce da borda: a aba da chapa, a pele de dentro, a borracha do vidro (perfil varrido), o bolso do farol e da lanterna
     (refletor, lâmpada e lente), o lábio do arco e a caixa de roda;
  5. para-choques (perfil varrido na planta do carro), grade, placas, retrovisores, maçanetas, limpadores, emblema e as rodas de kit;
  6. UV por painel num atlas só e a exportação: <id>.glb (LOD de perto), <id>_lod1.glb, <id>_lod2.glb, <id>_wheels.json, <id>_molde.json.

Nomes de peça e de material: os do corte de hoje (Detonauto, Tools/Blender/kit_names.py), para entrar no jogo sem mexer no C++.
"""
import argparse
import json
import math
import os
import sys

import bpy
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import gabarito_hatch  # noqa: E402
import malha_util as mu  # noqa: E402
from malha_util import norm  # noqa: E402

RAIZ = os.path.abspath(os.path.join(AQUI, '..', '..'))
PINTADAS = ('body', 'hood', 'trunk', 'door_fl', 'door_fr', 'fender_front_left', 'fender_front_right')
CORES = {
    'pintura': (0.55, 0.02, 0.02, 1), 'chassi': (0.015, 0.015, 0.015, 1), 'vidro': (0.75, 0.85, 0.82, 1), 'cromo': (0.9, 0.9, 0.9, 1),
    'refletor': (0.9, 0.9, 0.9, 1), 'lente_vidro': (1, 1, 1, 1), 'lente_vermelha': (0.75, 0.01, 0.01, 1), 'lente_ambar': (1, 0.35, 0, 1),
    'lente_branca': (0.95, 0.95, 0.95, 1), 'placa': (0.8, 0.8, 0.8, 1), 'pneu': (0.02, 0.02, 0.02, 1),
}


def argumentos():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--ficha', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--nivel', type=int, default=None)
    p.add_argument('--so-lod0', action='store_true')
    return p.parse_args(argv)


_mats = {}


def material(nome):
    if nome not in _mats:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes.get('Principled BSDF')
        cor = CORES.get(nome, (0.5, 0.5, 0.5, 1))
        b.inputs['Base Color'].default_value = cor
        m.diffuse_color = cor
        if nome in ('cromo', 'refletor'):
            b.inputs['Metallic'].default_value = 1.0
            b.inputs['Roughness'].default_value = 0.1
        elif nome == 'pintura':
            b.inputs['Roughness'].default_value = 0.35
        elif nome.startswith(('vidro', 'lente')):
            b.inputs['Roughness'].default_value = 0.05
            b.inputs['Alpha'].default_value = 0.3 if nome == 'vidro' else 0.6
            m.blend_method = 'BLEND' if hasattr(m, 'blend_method') else m.blend_method
        else:
            b.inputs['Roughness'].default_value = 0.6
        _mats[nome] = m
    return _mats[nome]


# ============================================================================================================== a gaiola
class Gaiola:
    def __init__(self, F):
        g = gabarito_hatch.espelhar(gabarito_hatch.montar(F))
        self.V = np.array(g['verts'])
        self.faces = g['faces']
        for f in self.faces:                       # o lado direito ganha coordenadas de molde próprias (ilhas de UV separadas)
            if f['lado'] < 0:
                f['uv'] = [((u, -v) if u >= 100 else (u + 50, v)) for (u, v) in f['uv']]
        self.toca = {}                             # vértice -> regiões que o tocam
        for f in self.faces:
            for v in f['v']:
                self.toca.setdefault(v, set()).add(f['reg'])
        self.vincos = {}                           # arestas vincadas (a, b) -> peso
        self.z_cintura = F['cotas']['z_cintura']
        c = F['cotas']
        for (a, b, w) in g['vincos']:
            self.vincos[(min(a, b), max(a, b))] = w

    def regioes(self):
        return sorted({f['reg'] for f in self.faces})

    def pedaco(self, reg, raios):
        """As faces da região como malha própria, com o vinco de canto para o raio pedido."""
        fs = [f for f in self.faces if f['reg'] == reg]
        usados = sorted({v for f in fs for v in f['v']})
        loc = {v: i for i, v in enumerate(usados)}
        P = self.V[usados]
        Q = [[loc[v] for v in f['v']] for f in fs]
        UV = [f['uv'] for f in fs]
        nf = {}
        for q in Q:
            for v in q:
                nf[v] = nf.get(v, 0) + 1
        viz = {}
        for laco in mu.lacos_de_borda(np.array(Q)):
            for i, v in enumerate(laco):
                viz[v] = (laco[i - 1], laco[(i + 1) % len(laco)])
        vv = {}
        for v, (a, b) in viz.items():
            if nf[v] in (1, 3):
                t = self.toca[usados[v]]
                if any(r.startswith('glass_door_f') for r in t) and abs(P[v][2] - self.z_cintura) < 0.03:
                    vv[v] = 1.0          # o canto de baixo do vidro da porta é reto: o vidro desce para dentro dela
                    continue
                if any(r.startswith('glass') for r in t):
                    R = raios['vidro']
                elif any(r.startswith(('headlight', 'taillight', 'grille')) for r in t):
                    R = raios['luz']
                else:
                    R = raios['painel']
                la = 0.5 * (np.linalg.norm(P[a] - P[v]) + np.linalg.norm(P[b] - P[v]))
                s = math.log2(max(0.5 * la / R, 1.0))
                if s > 0:
                    vv[v] = min(1.0, math.sqrt(s / 10.0))
        ve = {}
        for (a, b), w in self.vincos.items():
            if a in loc and b in loc:
                ve[(min(loc[a], loc[b]), max(loc[a], loc[b]))] = w
        return P, Q, UV, vv, ve

    def mestra(self, nivel):
        P, Q, ST = mu.subdividir(self.V, [f['v'] for f in self.faces], [f['uv'] for f in self.faces], nivel, vinco_aresta=self.vincos)
        return mu.Mestra(P, Q, ST, passo=2 ** nivel)


# ============================================================================================================== o carro
class Carro:
    def __init__(self, F, nivel, detalhes=True):
        self.F, self.c, self.nivel, self.detalhes = F, F['cotas'], nivel, detalhes
        self.a = F.get('acabamento', {})
        self.gaiola = Gaiola(F)
        self.mestra = self.gaiola.mestra(max(nivel + 1, 4))
        self.obras = {}
        self.fresta = self.a.get('fresta', 0.004)
        self.raios = self.a.get('raios_de_canto', {'vidro': 0.03, 'luz': 0.012, 'painel': 0.008})
        self.medidas = {}

    def obra(self, nome):
        if nome not in self.obras:
            self.obras[nome] = mu.Obra(nome)
        return self.obras[nome]

    def no_arco(self, p, com_canto=False):
        c = self.c
        if p[2] < c['z_soleira'] + (-0.002 if com_canto else 0.004):
            return False
        for xa in (c['eixo_dianteiro'], c['eixo_traseiro']):
            r = math.hypot(p[0] - xa, p[2] - c['z_centro_arco'])
            if abs(r - c['raio_arco']) < 0.02:
                return True
        return False

    def arco_no_circulo(self, P, Q, extra=0.0):
        """A borda do arco vai para o círculo exato (no plano xz); o y é o da superfície."""
        c = self.c
        P = P.copy()
        for laco in mu.lacos_de_borda(Q):
            for v in laco:
                if not self.no_arco(P[v], com_canto=True):
                    continue
                xa = c['eixo_dianteiro'] if P[v][0] > 0 else c['eixo_traseiro']
                dx, dz = P[v][0] - xa, P[v][2] - c['z_centro_arco']
                r = math.hypot(dx, dz)
                R = c['raio_arco'] + extra
                q = np.array((xa + dx / r * R, P[v][1], c['z_centro_arco'] + dz / r * R))
                h = self.mestra.raio((q[0], 2.0 * np.sign(q[1]), q[2]), (0, -np.sign(q[1]), 0))
                if h is not None and abs(h[1] - q[1]) < 0.01:
                    q[1] = h[1]
                P[v] = q
        return P

    def pele(self, reg, nivel):
        P, Q, UV, vv, ve = self.gaiola.pedaco(reg, self.raios)
        P0 = P
        P, Qs, ST = mu.subdividir(P0, Q, UV, nivel, vv, ve)
        Pv, _, _ = mu.subdividir(P0, Q, UV, nivel, {k: 1.0 for k in vv}, ve)      # a mesma peça com os cantos vivos
        P, N = self.mestra.assentar_por_molde(P, Qs, ST, P_vivo=Pv)
        return P, N, Qs, ST

    # ---------------------------------------------------------------------------------------------------- chapa pintada
    def chapas(self):
        g2 = self.fresta / 2
        for reg in PINTADAS:
            P, N, Q, ST = self.pele(reg, self.nivel)
            P = mu.recuar_borda(P, N, Q, g2, filtro=lambda p: not self.no_arco(p))
            P = self.arco_no_circulo(P, Q)
            o = self.obra(reg)
            o.somar(P, N, [tuple(f) for f in Q], 'pintura', uv=[[tuple(c) for c in f] for f in ST], ilha='pele')
            fundo = 0.019 if reg == 'body' else 0.011
            mu.aba(o, P, N, Q, fundo, 'pintura', filtro=lambda p: not self.no_arco(p))
            mu.aba(o, P, N, Q, 0.022, 'pintura', filtro=self.no_arco, puxar=0.004, qualquer=True)       # o lábio do arco
            if self.detalhes:
                # a pele de dentro: a mesma superfície um nível abaixo, com a mesma borda, na profundidade da aba (fecha a peça)
                P2, N2, Q2, _ = self.pele(reg, max(self.nivel - 1, 1))
                P2 = mu.recuar_borda(P2, N2, Q2, g2, filtro=lambda p: not self.no_arco(p))
                P2 = self.arco_no_circulo(P2, Q2, extra=0.004)      # por fora da caixa de roda (a corda do nível de baixo não entra no vão)
                o.somar(P2 - N2 * fundo, -N2, [tuple(f) for f in Q2], 'chassi')
            self.medidas[reg] = dict(borda=[P[l].tolist() for l in mu.lacos_de_borda(Q)])

    def caixas_de_roda(self):
        c = self.c
        o = self.obra('body')
        R = c['raio_arco'] + 0.003
        za = c['z_centro_arco']
        n = 28
        for xa in (c['eixo_dianteiro'], c['eixo_traseiro']):
            for lado in (1, -1):
                y1 = lado * 0.33
                P, N, F = [], [], []
                a0 = math.degrees(math.asin((c['z_soleira'] + 0.004 - za) / R))
                angs = [math.radians(a0 + (180 - 2 * a0) * k / n) for k in range(n + 1)]
                for t in angs:
                    x, z = xa + R * math.cos(t), za + R * math.sin(t)
                    h = self.mestra.raio((x, lado * 2.0, max(z, c['z_soleira'] + 0.01)), (0, -lado, 0))
                    y0 = (h[1] if h is not None else lado * c['meia_largura']) - lado * 0.006
                    P += [(x, y0, z), (x, y1, z)]
                    nn = (-math.cos(t), 0, -math.sin(t))
                    N += [nn, nn]
                for k in range(n):
                    a, b, d, e = 2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2
                    F.append((a, b, d, e) if lado > 0 else (e, d, b, a))
                # a parede do fundo
                base = len(P)
                P.append((xa, y1, za))
                N.append((0, lado, 0))
                for k in range(n + 1):
                    P.append(P[2 * k + 1])
                    N.append((0, lado, 0))
                for k in range(n):
                    F.append((base, base + 1 + k, base + 2 + k) if lado > 0 else (base, base + 2 + k, base + 1 + k))
                o.somar(P, N, F, 'chassi')
                # o lado de dentro (o morro no porta-malas), 4 mm afastado
                P2 = [tuple(np.array(p) - np.array(n) * 0.004) for p, n in zip(P, N)]
                o.somar(P2, [tuple(-np.array(n)) for n in N], [tuple(reversed(f)) for f in F], 'chassi')
                # as duas pontas da casca (embaixo), fechadas
                for k in (0, n):
                    q = [P[2 * k], P[2 * k + 1], P2[2 * k + 1], P2[2 * k]]
                    o.somar(q, [(0, 0, -1)] * 4, [(0, 1, 2, 3)], 'chassi')

    # ---------------------------------------------------------------------------------------------------- vidros
    def vidros(self):
        perfil = self.a.get('borracha', [(-0.0045, -0.006), (-0.0045, 0.0012), (-0.002, 0.0028), (0.004, 0.0028), (0.011, -0.0015), (0.012, -0.009)])
        for reg in ('glass_windshield', 'glass_rear', 'glass_door_fl', 'glass_door_fr', 'glass_door_rl', 'glass_door_rr'):
            P, N, Q, ST = self.pele(reg, self.nivel)
            o = self.obra(reg)
            for laco in mu.lacos_de_borda(Q):
                _, D = mu.quadro_da_borda(P, N, laco)
                mu.varrer_perfil(o, P[laco], N[laco], D, perfil, 'chassi')
            Pv = mu.recuar_borda(P, N, Q, 0.006) - N * 0.004
            o.somar(Pv, N, [tuple(f) for f in Q], 'vidro', uv=[[tuple(c) for c in f] for f in ST], ilha='pele')

    # ---------------------------------------------------------------------------------------------------- luzes
    def luzes(self):
        for reg in ('headlight_left', 'headlight_right', 'taillight_left', 'taillight_right'):
            P, N, Q, ST = self.pele(reg, self.nivel)
            o = self.obra(reg)
            farol = reg.startswith('head')
            eixo = norm(N.mean(0))
            cen = P.mean(0)
            # a lente: a própria superfície, fechada com 3 mm de espessura
            Pl = mu.recuar_borda(P, N, Q, 0.0012)

            def mat_da_face(st):
                if farol:
                    return 'lente_vidro'
                v = abs(st[:, 1].mean())
                if v < 3.05:
                    return 'lente_vermelha'
                return 'lente_branca' if v < 3.40 else 'lente_ambar'

            por_mat = {}
            for f, st in zip(Q, ST):
                por_mat.setdefault(mat_da_face(st), []).append((tuple(f), [tuple(c) for c in st]))
            for m, fs in por_mat.items():
                o.somar(Pl, N, [f for f, _ in fs], m, uv=[u for _, u in fs], ilha='pele')
            # o bolso: a parede e o fundo de refletor. O fundo é a própria lente encolhida e recuada, em degraus horizontais (o
            # friso do refletor, que dá as faixas de brilho de um farol de verdade)
            fundo = 0.065 if farol else 0.04
            enc = 0.84
            est = ST[:, :, 0]
            passo_u = 2 ** self.nivel
            Pf, Nf, Ff = [], [], []
            for f, st in zip(Q, ST):
                base = len(Pf)
                iu = np.round((st[:, 0] - np.floor(st[:, 0].min() + 1e-6)) * passo_u).astype(int)
                for v, k in zip(f, iu):
                    Pf.append(cen + (P[v] - cen) * enc - eixo * (fundo + (0.007 if k % 2 else 0.0)))
                Ff.append((base, base + 1, base + 2, base + 3))
                q = np.array(Pf[base:base + 4])
                n = np.cross(q[1] - q[0], q[3] - q[0])
                n = n / max(np.linalg.norm(n), 1e-12)
                if n @ eixo < 0:
                    n = -n
                Nf += [n] * 4
            o.somar(np.array(Pf), np.array(Nf), Ff, 'refletor')
            o.somar(cen + (np.array(Pf) - cen) * 1.06 - eixo * 0.011, -np.tile(eixo, (len(Pf), 1)), Ff, 'chassi')
            for laco in mu.lacos_de_borda(Q):
                C = P[laco] - N[laco] * 0.004
                B = cen + (P[laco] - cen) * enc - eixo * (fundo + 0.004)
                n = len(laco)
                F = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
                Nn = norm(np.concatenate([cen - C, cen - B]) + eixo * 0.3)
                o.somar(np.concatenate([C, B]), Nn, F, 'refletor')
                o.somar(np.concatenate([C, B]) - Nn * 0.004, -Nn, F, 'chassi')       # a carcaça por trás (vista do cofre e do porta-malas)
            # a lâmpada
            if farol:
                lat = norm(np.cross(eixo, (0, 0, 1)))
                mu.caixa_arredondada(o, cen - eixo * (fundo - 0.02), (eixo, lat, (0, 0, 1)), (0.02, 0.017, 0.017), 'cromo', nivel=2)
            else:
                # as divisórias pretas entre as cores
                lat = norm(np.cross(eixo, (0, 0, 1)))
                ymin, ymax = np.abs(P[:, 1]).min(), np.abs(P[:, 1]).max()
                sy = np.sign(cen[1])
                zc, dz = cen[2], 0.5 * (P[:, 2].max() - P[:, 2].min())
                for fr in ((3.05 - 2) / 2.0, (3.40 - 2) / 2.0):
                    y = sy * (ymin + (ymax - ymin) * fr)
                    h = self.mestra.raio((-3.0, y, zc), (1, 0, 0))
                    if h is not None:
                        mu.caixa_arredondada(o, h - eixo * 0.022, (eixo, lat, (0, 0, 1)), (0.018, 0.0025, dz - 0.004), 'chassi', nivel=1, vinco=1.0)
            self.medidas[reg] = dict(eixo=eixo.tolist(), centro=cen.tolist())

    def grade(self):
        P, N, Q, ST = self.pele('grille', self.nivel - 1)
        o = self.obra('grille')
        eixo = np.array((1.0, 0, 0))
        fundo = 0.055
        o.somar(P - eixo * fundo, N, [tuple(f) for f in Q], 'chassi')
        o.somar(P - eixo * (fundo + 0.004), -N, [tuple(reversed(f)) for f in Q], 'chassi')
        for laco in mu.lacos_de_borda(Q):
            C = P[laco] - N[laco] * 0.003
            B = C - eixo * (fundo + 0.008)
            n = len(laco)
            cen = C.mean(0)
            F = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
            T, D = mu.quadro_da_borda(P, N, laco)
            Nn = np.concatenate([D, D])
            o.somar_duplo(np.concatenate([C, B]), Nn, F, 'chassi', afastar=0.004)
        if not self.detalhes:
            return
        # as lâminas: desenho do estúdio, 5 horizontais inclinadas e uma travessa central com o emblema
        z0, z1 = P[:, 2].min(), P[:, 2].max()
        ymax = np.abs(P[:, 1]).max()
        n_lam = self.a.get('grade_laminas', 5)
        ys = np.linspace(-ymax + 0.004, ymax - 0.004, 25)
        for k in range(n_lam):
            z = z0 + (z1 - z0) * (k + 1.0) / (n_lam + 1)
            C = []
            for y in ys:
                h = self.mestra.raio((3.0, y, z), (-1, 0, 0))
                C.append(h if h is not None else (0, y, z))
            C = np.array(C) - eixo * 0.006
            Nn = np.tile((0.0, 0.0, 1.0), (len(C), 1))
            D = np.tile(-eixo, (len(C), 1))
            mu.varrer_perfil(o, C, Nn, D, [(0.0, 0.0045), (0.0, -0.0045), (0.034, -0.0125), (0.034, -0.0035)], 'chassi', fechado=False)

    # ---------------------------------------------------------------------------------------------------- para-choques
    def para_choque(self, nome, sinal):
        c = self.c
        pc = self.a.get('para_choque', {})
        zt = c['z_topo_para_choque']
        zb = pc.get('z_base', 0.30)
        zm = 0.5 * (zt + zb)
        fora_f, fora_l = pc.get('saliencia_frente', 0.06), pc.get('saliencia_lado', 0.022)
        x_arco = (c['eixo_dianteiro'] if sinal > 0 else c['eixo_traseiro']) + sinal * (c['raio_arco'] + 0.004)

        def frente(y):
            h = self.mestra.raio((sinal * 3.0, y, zm), (-sinal, 0, 0))
            return h[0] + sinal * fora_f

        def lado(x):
            h = self.mestra.raio((x, 2.0, zm), (0, -1, 0))
            return h[1] + fora_l

        xq = frente(0.45)
        y_canto = lado(xq - sinal * 0.10)
        meio = [(frente(y), y) for y in (0.0, 0.20, 0.40, 0.54)]
        canto = [(frente(0.54) - sinal * 0.004, y_canto - 0.03), (frente(0.54) - sinal * 0.035, y_canto + 0.002)]
        xs_l = np.linspace(xq - sinal * 0.14, x_arco, 3)
        lateral = [(x, lado(x)) for x in xs_l]
        metade = meio + canto + lateral
        caminho = [(x, -y) for (x, y) in reversed(metade[1:])] + metade
        # o perfil (para fora, z): fechado, no sentido anti-horário visto com "fora" à direita
        perfil = pc.get('perfil', [(-0.075, zt + 0.004), (-0.012, zt + 0.004), (0.0, zt - 0.02), (0.0, zb + 0.145), (0.010, zb + 0.135),
                                    (0.010, zb + 0.095), (0.0, zb + 0.085), (0.0, zb + 0.03), (-0.014, zb), (-0.075, zb)])
        npf, nc = len(perfil), len(caminho)
        cam = np.array(caminho)
        V, Fc, UV = [], [], []
        for i in range(nc):
            a, b = cam[max(i - 1, 0)], cam[min(i + 1, nc - 1)]
            t = norm(np.array([b[0] - a[0], b[1] - a[1]]))
            fora = np.array([t[1], -t[0]]) * sinal
            if i in (0, nc - 1):
                fora = np.array([0.0, np.sign(cam[i][1])])
            for (d, z) in perfil:
                V.append((cam[i][0] + fora[0] * d, cam[i][1] + fora[1] * d, z))
        for i in range(nc - 1):
            for k in range(npf):
                l = (k + 1) % npf
                q = (i * npf + k, (i + 1) * npf + k, (i + 1) * npf + l, i * npf + l)
                Fc.append(q)
                UV.append([(i, k), (i + 1, k), (i + 1, k + 1), (i, k + 1)])
        Fc.append(tuple(range(npf)))
        UV.append([(0, 0)] * npf)
        Fc.append(tuple(reversed(range((nc - 1) * npf, nc * npf))))
        UV.append([(0, 0)] * npf)
        ve = {}
        for i in range(nc - 1):
            for k in (1, 2, 7, 8):
                ve[(i * npf + k, (i + 1) * npf + k)] = 0.45
        for i in (0, nc - 1):
            for k in range(npf):
                a_, b_ = i * npf + k, i * npf + (k + 1) % npf
                ve[(min(a_, b_), max(a_, b_))] = 0.8
        P, Q, ST = self._sub_ngon(V, Fc, UV, min(self.nivel, 2) if self.detalhes else 1, ve)
        # sólido fechado: o volume com sinal diz o lado das faces
        vol = np.einsum('ij,ij->i', P[Q[:, 0]], np.cross(P[Q[:, 1]], P[Q[:, 2]])).sum() + np.einsum('ij,ij->i', P[Q[:, 0]], np.cross(P[Q[:, 2]], P[Q[:, 3]])).sum()
        if vol < 0:
            Q = Q[:, ::-1]
            ST = ST[:, ::-1]
        N = mu.normais_de_malha(P, Q)
        o = self.obra(nome)
        pisca = pc.get('pisca', True) and sinal > 0
        mats = []
        for st in ST:
            u, k = st[:, 0].mean(), st[:, 1].mean()
            i_pisca = (nc // 2 + 2 < u < nc // 2 + 3) or (nc // 2 - 3 < u < nc // 2 - 2)
            mats.append('lente_ambar' if (pisca and i_pisca and 2.0 < k < 3.0) else 'chassi')
        for m in sorted(set(mats)):
            sel = [i for i, x in enumerate(mats) if x == m]
            o.somar(P, N, [tuple(Q[i]) for i in sel], m, uv=[[tuple(c) for c in ST[i]] for i in sel], ilha='pele')
        sel = [i for i, x in enumerate(mats) if x == 'lente_ambar']
        if sel:
            o.somar(P - N * 0.010, N, [tuple(Q[i]) for i in sel], 'refletor')
        self.medidas[nome] = dict(x_fora=float(P[:, 0].max() if sinal > 0 else P[:, 0].min()), z=[float(zb), float(zt)])

    def _sub_ngon(self, V, F, UV, nivel, ve):
        me = bpy.data.meshes.new('tmp')
        me.from_pydata([tuple(v) for v in V], [], [tuple(f) for f in F])
        uv = me.uv_layers.new(name='st')
        k = 0
        for f in UV:
            for cc in f:
                uv.data[k].uv = cc
                k += 1
        a = me.attributes.new('crease_edge', 'FLOAT', 'EDGE')
        for e in me.edges:
            w = ve.get((min(e.vertices), max(e.vertices)))
            if w:
                a.data[e.index].value = w
        ob = bpy.data.objects.new('tmp', me)
        bpy.context.scene.collection.objects.link(ob)
        md = ob.modifiers.new('s', 'SUBSURF')
        md.levels = md.render_levels = max(nivel, 1)
        md.uv_smooth = 'NONE'
        dg = bpy.context.evaluated_depsgraph_get()
        m2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        P = np.zeros(len(m2.vertices) * 3)
        m2.vertices.foreach_get('co', P)
        Q = np.zeros(len(m2.polygons) * 4, dtype=np.int64)
        m2.polygons.foreach_get('vertices', Q)
        ST = np.zeros(len(m2.loops) * 2)
        m2.uv_layers['st'].data.foreach_get('uv', ST)
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
        bpy.data.meshes.remove(m2)
        return P.reshape(-1, 3), Q.reshape(-1, 4), ST.reshape(-1, 4, 2)

    # ---------------------------------------------------------------------------------------------------- detalhes
    def placas(self):
        L, A = 0.40, 0.13
        for nome, sinal, z0 in (('plate_front', 1, self.a.get('z_placa_frente', 0.335)), ('plate_rear', -1, self.a.get('z_placa_tras', 0.607))):
            if sinal > 0:
                xf = self.medidas['bumper_front']['x_fora'] + 0.012
            else:
                h = self.mestra.raio((-3.0, 0.0, z0 + A / 2), (1, 0, 0))
                xf = h[0] - 0.006
            o = self.obra(nome)
            zc = z0 + A / 2
            ex, ey, ez = (sinal, 0, 0), (0, 1, 0), (0, 0, 1)
            mu.caixa_arredondada(o, (xf - sinal * 0.006, 0, zc), (ex, ey, ez), (0.006, L / 2 + 0.008, A / 2 + 0.008), 'chassi', nivel=2, vinco=0.6)
            x = xf + sinal * 0.0008
            P = [(x, sinal * L / 2, z0), (x, -sinal * L / 2, z0), (x, -sinal * L / 2, z0 + A), (x, sinal * L / 2, z0 + A)]
            P = [P[i] for i in (1, 0, 3, 2)] if True else P
            # visto de fora: u cresce da esquerda de quem olha para a direita
            o.somar(P, [ex] * 4, [(0, 1, 2, 3)] if sinal < 0 else [(0, 1, 2, 3)], 'placa', uv=[[(0, 0), (1, 0), (1, 1), (0, 1)]], ilha='placa')
            # confere o lado da face
            a, b, d = np.array(P[0]), np.array(P[1]), np.array(P[3])
            if np.cross(b - a, d - a) @ np.array(ex) < 0:
                o.F[-1] = tuple(reversed(o.F[-1]))
                o.UV[-1] = list(reversed(o.UV[-1]))

    def retrovisores(self):
        c = self.c
        x, z = self.a.get('retrovisor_x', c['x_porta_frente'] - 0.08), self.a.get('retrovisor_z', c['z_cintura'] + 0.04)
        for nome, lado in (('mirror_left', 1), ('mirror_right', -1)):
            h = self.mestra.raio((x, lado * 2.0, z), (0, -lado, 0))
            if h is None:
                continue
            o = self.obra(nome)
            ey = (0, lado, 0)
            mu.caixa_arredondada(o, h + np.array((0, lado * 0.03, -0.012)), ((1, 0, 0), ey, (0, 0, 1)), (0.022, 0.04, 0.013), 'chassi', nivel=2, vinco=0.3)
            cab = h + np.array((-0.012, lado * 0.105, 0.012))
            mu.caixa_arredondada(o, cab, ((1, 0, 0), ey, (0, 0, 1)), (0.030, 0.075, 0.048), 'chassi', nivel=2, vinco=0.25)
            xe = cab[0] - 0.0305
            P = [(xe, cab[1] - 0.062, cab[2] - 0.037), (xe, cab[1] + 0.062, cab[2] - 0.037), (xe, cab[1] + 0.062, cab[2] + 0.037), (xe, cab[1] - 0.062, cab[2] + 0.037)]
            o.somar(P, [(-1, 0, 0)] * 4, [(3, 2, 1, 0)], 'cromo')

    def macanetas(self):
        c = self.c
        x, z = self.a.get('macaneta_x', c['x_porta_tras'] + 0.14), self.a.get('macaneta_z', c['z_cintura'] - 0.095)
        for nome, lado in (('door_fl', 1), ('door_fr', -1)):
            h = self.mestra.raio((x, lado * 2.0, z), (0, -lado, 0))
            if h is None:
                continue
            o = self.obra(nome)
            mu.caixa_arredondada(o, h + np.array((0, lado * 0.001, 0)), ((1, 0, 0), (0, lado, 0), (0, 0, 1)), (0.062, 0.006, 0.019), 'chassi', nivel=2, vinco=0.5)
            mu.caixa_arredondada(o, h + np.array((0.004, lado * 0.007, 0.004)), ((1, 0, 0), (0, lado, 0), (0, 0, 1)), (0.045, 0.004, 0.009), 'cromo', nivel=2, vinco=0.4)

    def frisos(self):
        """O friso lateral de borracha, na altura da faixa do para-choque; cada trecho mora na peça em que está (o da porta vai com ela)."""
        c = self.c
        z = self.a.get('friso_z', 0.45)
        dx = math.sqrt(max(c['raio_arco'] ** 2 - (z - c['z_centro_arco']) ** 2, 0.0)) + 0.02
        trechos = [('fender_front_%s', c['eixo_dianteiro'] - dx, c['x_porta_frente'] + 0.008),
                   ('door_f%s', c['x_porta_frente'] - 0.008, c['x_porta_tras'] + 0.008),
                   ('body', c['x_porta_tras'] - 0.008, c['eixo_traseiro'] + dx)]
        perfil = [(-0.012, -0.001), (-0.009, 0.0045), (0.009, 0.0045), (0.012, -0.001)]
        for nome, x0, x1 in trechos:
            for lado, suf_longo, suf_curto in ((1, 'left', 'l'), (-1, 'right', 'r')):
                alvo = nome % (suf_longo if 'fender' in nome else suf_curto) if '%s' in nome else nome
                xs = np.linspace(x0, x1, max(3, int(abs(x1 - x0) / 0.03)))
                C = []
                for x in xs:
                    h = self.mestra.raio((x, lado * 2.0, z), (0, -lado, 0))
                    if h is not None:
                        C.append(h)
                if len(C) < 3:
                    continue
                C, Nn = self.mestra.assentar(np.array(C))
                T = norm(np.gradient(C, axis=0))
                D = norm(np.cross(Nn, T))
                mu.varrer_perfil(self.obra(alvo), C, Nn, D, perfil, 'chassi', fechado=False)

    def limpadores(self):
        o = self.obra('body')
        c = self.c
        for y0, y1 in ((0.36, 0.02), (-0.12, -0.44)):
            pts = []
            for t in np.linspace(0, 1, 9):
                y = y0 + (y1 - y0) * t
                x = c['x_porta_frente'] + 0.10 - 0.16 * t
                h = self.mestra.raio((x, y, 3.0), (0, 0, -1))
                if h is not None:
                    pts.append(h + np.array((0, 0, 0.012)))
            if len(pts) < 3:
                continue
            C, Nn = self.mestra.assentar(np.array(pts) - np.array((0, 0, 0.012)))
            C = C + Nn * 0.012
            T = norm(np.gradient(C, axis=0))
            D = norm(np.cross(Nn, T))
            mu.varrer_perfil(o, C, Nn, D, [(-0.006, 0.004), (-0.006, -0.006), (0.006, -0.006), (0.006, 0.004)], 'chassi', fechado=False)
            mu.caixa_arredondada(o, C[0] + np.array((0, 0, -0.004)), ((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.016, 0.016, 0.012), 'chassi', nivel=1)

    def emblema(self):
        """A logo "Estilhaço" do jogo (Detonauto, docs/img/logo/proposta-2-estilhaco.svg), em cromo: na grade e na tampa."""
        pts = [(50, 2), (58, 30), (84, 10), (71, 38), (98, 42), (73, 55), (92, 80), (63, 69), (57, 98), (45, 72), (22, 92), (28, 64), (2, 60),
               (26, 46), (8, 20), (37, 31)]
        lugares = []
        h = self.mestra.raio((3.0, 0.0, 0.5 * (self.c['fiadas_frente'][3] + self.c['fiadas_frente'][4])), (-1, 0, 0))
        if h is not None:
            lugares.append(('grille', h + np.array((0.004, 0, 0)), 1, 0.085))
        zt = self.a.get('emblema_tras_z', 0.80)
        h = self.mestra.raio((-3.0, 0.0, zt), (1, 0, 0))
        if h is not None:
            lugares.append(('trunk', h + np.array((-0.0015, 0, 0)), -1, 0.07))
        for nome, p, sinal, tam in lugares:
            o = self.obra(nome)
            P, N = [], []
            for (u, v) in pts:
                P.append((p[0], p[1] + sinal * (u - 50) / 100.0 * tam, p[2] + (50 - v) / 100.0 * tam))
                N.append((sinal, 0, 0))
            P.append(tuple(p))
            N.append((sinal, 0, 0))
            n = len(pts)
            F = [(n, (i + 1) % n, i) for i in range(n)]
            a, b, d = np.array(P[F[0][0]]), np.array(P[F[0][1]]), np.array(P[F[0][2]])
            if np.cross(b - a, d - a)[0] * sinal < 0:
                F = [tuple(reversed(f)) for f in F]
            o.somar(P, N, F, 'cromo')
            if nome == 'grille':     # o apoio do emblema na grade
                mu.caixa_arredondada(o, p - np.array((0.02, 0, 0)), ((1, 0, 0), (0, 1, 0), (0, 0, 1)), (0.018, tam * 0.36, tam * 0.36), 'chassi', nivel=1)

    def rodas(self):
        r = self.F.get('rodas')
        if not r:
            return
        pasta = os.path.join(RAIZ, 'veiculos', 'proprios', 'rodas')
        c = self.c
        for nome, xa, lado in (('fl', c['eixo_dianteiro'], 1), ('fr', c['eixo_dianteiro'], -1), ('rl', c['eixo_traseiro'], 1), ('rr', c['eixo_traseiro'], -1)):
            for arq, obj, final in ((r['aro'], None, 'wheel_%s_rim'), (r['pneu'], '_Ok', 'wheel_%s_tire'), (r.get('calota'), None, 'hubcap_%s')):
                if not arq:
                    continue
                antes = set(bpy.data.objects)
                bpy.ops.import_scene.gltf(filepath=os.path.join(pasta, arq + '.glb'))
                novos = [o for o in bpy.data.objects if o not in antes]
                alvo = None
                for o in novos:
                    if o.type == 'MESH' and not o.name.split('.')[0].endswith(('_LOD1', '_Flat', '_Torn')) and alvo is None and (obj is None or obj in o.name):
                        alvo = o
                for o in novos:
                    if o is not alvo:
                        bpy.data.objects.remove(o)
                alvo.parent = None
                alvo.name = final % nome
                alvo.data.name = alvo.name
                alvo.location = (xa, lado * r['cubo_y'], r['raio'])
                alvo.rotation_mode = 'XYZ'
                alvo.rotation_euler = (0, 0, 0 if lado > 0 else math.pi)

    # ---------------------------------------------------------------------------------------------------- tudo
    def construir(self):
        self.chapas()
        self.caixas_de_roda()
        self.vidros()
        self.luzes()
        self.grade()
        self.para_choque('bumper_front', 1)
        self.para_choque('bumper_rear', -1)
        if self.detalhes:
            self.placas()
            self.retrovisores()
            self.macanetas()
            self.frisos()
            self.limpadores()
            self.emblema()


# ============================================================================================================== UV num atlas só
def empacotar_uv(obras, margem=0.004):
    """
    UV por painel: cada ilha é (peça, remendo do molde, lado). As coordenadas de molde viram medidas reais (comprimento médio de cada
    faixa), para a densidade ser a mesma no carro todo; as ilhas são empacotadas em prateleiras num atlas de 0 a 1.
    """
    ilhas = []
    for nome, o in obras.items():
        P = np.concatenate(o.P) if o.P else np.zeros((0, 3))
        grupos = {}
        for i, (f, uv, il) in enumerate(zip(o.F, o.UV, o.ILHA)):
            if uv is None or il is None or len(f) != 4:
                continue
            if il == 'placa':
                continue
            u0 = min(c[0] for c in uv)
            v0 = np.mean([c[1] for c in uv])
            chave = ('T', 0) if u0 >= 100 else (('D', 0) if u0 >= 50 else ('E', 0))
            if nome.startswith('bumper'):
                chave = ('B', 0)
            grupos.setdefault(chave, []).append(i)
        for chave, fs in grupos.items():
            UVa = np.array([o.UV[i] for i in fs])            # (n, 4, 2)
            Fa = np.array([o.F[i] for i in fs])
            Pa = P[Fa]                                        # (n, 4, 3)
            # comprimento real por unidade de u e de v, por faixa inteira
            escala = []
            for eixo in (0, 1):
                d = {}
                for k in range(4):
                    a, b = UVa[:, k], UVa[:, (k + 1) % 4]
                    du = b[:, eixo] - a[:, eixo]
                    dv = b[:, 1 - eixo] - a[:, 1 - eixo]
                    ok = (np.abs(du) > 1e-9) & (np.abs(dv) < 1e-9)
                    comp = np.linalg.norm(Pa[:, (k + 1) % 4] - Pa[:, k], axis=1)
                    faixa = np.floor(np.minimum(a[:, eixo], b[:, eixo]) + 1e-6)
                    for fx, cp, dd in zip(faixa[ok], comp[ok], np.abs(du[ok])):
                        d.setdefault(fx, []).append(cp / dd)
                ks = sorted(d)
                acum, tab = 0.0, {}
                for kx in ks:
                    tab[kx] = (acum, float(np.mean(d[kx])))
                    acum += tab[kx][1]
                escala.append((tab, ks))

            def mapear(val, eixo):
                tab, ks = escala[eixo]
                fx = np.floor(val - 1e-6) if val > ks[0] else ks[0]
                fx = min(max(fx, ks[0]), ks[-1])
                if fx not in tab:
                    fx = min(ks, key=lambda q: abs(q - fx))
                a0, comp = tab[fx]
                return a0 + (val - fx) * comp

            novo = np.zeros_like(UVa)
            cache = ({}, {})
            for n in range(len(fs)):
                for k in range(4):
                    for eixo in (0, 1):
                        val = round(float(UVa[n, k, eixo]), 6)
                        if val not in cache[eixo]:
                            cache[eixo][val] = mapear(val, eixo)
                        novo[n, k, eixo] = cache[eixo][val]
            novo -= novo.reshape(-1, 2).min(0)
            tam = novo.reshape(-1, 2).max(0)
            ilhas.append(dict(obra=o, faces=fs, uv=novo, tam=tam))
    if not ilhas:
        return 0.0
    # prateleiras: tenta escalas até caber
    ilhas.sort(key=lambda i: -i['tam'][1])
    area = sum(i['tam'][0] * i['tam'][1] for i in ilhas)
    lado = math.sqrt(area) * 1.15
    while True:
        x = y = alt = 0.0
        pos = []
        ok = True
        for il in ilhas:
            w, h = il['tam'][0] + margem * lado, il['tam'][1] + margem * lado
            if w > lado:
                ok = False
                break
            if x + w > lado:
                x, y, alt = 0.0, y + alt, 0.0
            pos.append((x, y))
            x += w
            alt = max(alt, h)
        if ok and y + alt <= lado:
            break
        lado *= 1.04
    for il, (x, y) in zip(ilhas, pos):
        uv = (il['uv'] + np.array((x, y))) / lado * 0.98 + 0.012
        for n, fi in enumerate(il['faces']):
            il['obra'].UV[fi] = [tuple(c) for c in uv[n]]
    for o in obras.values():                        # o resto (abas, peles de dentro, miudezas) vai para um canto reservado
        for i, il in enumerate(o.ILHA):
            if il != 'placa' and (il is None or o.UV[i] is None or len(o.F[i]) != 4):
                o.UV[i] = [(0.004, 0.004)] * len(o.F[i])
    return 1.0 / lado


def exportar(car, caminho, com_rodas=True):
    bpy.ops.object.select_all(action='DESELECT')
    for o in bpy.data.objects:
        o.select_set(o.type == 'MESH')
    bpy.ops.export_scene.gltf(filepath=caminho, export_apply=True, use_selection=True, export_normals=True, export_yup=True)


def gerar(F, nivel, caminho, detalhes=True, rodas=True):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _mats.clear()
    car = Carro(F, nivel, detalhes)
    car.construir()
    densidade = empacotar_uv(car.obras)
    tri = {}
    for nome, o in car.obras.items():
        o.objeto(material)
        tri[nome] = o.tri()
    if rodas:
        car.rodas()
    exportar(car, caminho)
    return car, tri, densidade


PAPEIS = (('glass_door', 'glass_door'), ('glass_windshield', 'glass_windshield'), ('glass_rear', 'glass_rear'), ('headlight', 'headlight'),
          ('taillight', 'taillight'), ('mirror', 'mirror'), ('plate', 'plate'), ('grille', 'grille'), ('bumper_front', 'bumper_front'),
          ('bumper_rear', 'bumper_rear'), ('hood', 'hood'), ('trunk', 'trunk'), ('door', 'door'), ('fender', 'fender'))


def mapa_do_corte(F, car):
    """O <id>_mapa.json no formato do corte (carro_quebravel.py): as medidas e a caixa de cada peça, para a cadeia do jogo
    (make_crush_channels.py) e para o kit completo (carro_completo.py)."""
    c, r = F['cotas'], F.get('rodas', {})
    raio = r.get('raio', 0.29)
    caixas = {}
    for nome, o in car.obras.items():
        P = np.concatenate(o.P)
        caixas[nome] = [round(float(v), 4) for v in (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max())]
    x0 = min(b[0] for b in caixas.values())
    x1 = max(b[1] for b in caixas.values())
    gb = caixas.get('glass_windshield', [c['x_porta_frente'], 0, 0, 0, 0, 0])
    medidas = dict(comprimento=round(x1 - x0, 3), meia_largura=round(max(b[3] for n, b in caixas.items() if not n.startswith('mirror')), 3),
                   altura=round(max(b[5] for b in caixas.values()), 3), eixo_dianteiro=c['eixo_dianteiro'], eixo_traseiro=c['eixo_traseiro'],
                   raio_roda=raio, linha_de_cintura=c['z_cintura'], coluna_a=c['x_porta_frente'], coluna_b=c['x_porta_tras'],
                   base_do_para_brisa=round(gb[1], 4), topo_para_choque_dianteiro=c['z_topo_para_choque'],
                   topo_para_choque_traseiro=c['z_topo_para_choque'], topo_da_saia=c['z_base_porta'], portas=2, van=False)
    parts = []
    for nome, lado, xa in (('fl', 1, c['eixo_dianteiro']), ('fr', -1, c['eixo_dianteiro']), ('rl', 1, c['eixo_traseiro']), ('rr', -1, c['eixo_traseiro'])):
        for suf, papel, rr in (('rim', 'rim', [0.0, 0.2]), ('tire', 'wheel', [0.0, raio + 0.02])):
            parts.append(dict(take='roda', centro=[xa, 0.0, raio], lado=lado, y=[0.4, 0.92], thickness=0.0, pocket=0.0, name='wheel_%s_%s' % (nome, suf),
                              papel=papel, raio=rr))
    for nome in sorted(caixas):
        if nome == 'body':
            continue
        papel = next((pp for pre, pp in PAPEIS if nome.startswith(pre)), None)
        if papel:
            parts.append(dict(name=nome, papel=papel, take='faces', box=caixas[nome], thickness=0.004, pocket=0.02))
    cubo = r.get('cubo_y', 0.6)
    larg = 0.175
    rodas = [dict(nome=n, lado=l, cx=xa, cz=raio, raio=raio, y_dentro=round(cubo - larg / 2, 3), y_fora=round(cubo + larg / 2, 3),
                  y_alcance=round(cubo + larg / 2, 3), raio_aro=0.19, raio_calota=None)
             for n, l, xa in (('fl', 1, c['eixo_dianteiro']), ('fr', -1, c['eixo_dianteiro']), ('rl', 1, c['eixo_traseiro']), ('rr', -1, c['eixo_traseiro']))]
    return dict(car=F['carro'], notes='Mapa escrito por ferramentas/lataria_molde/construir.py a partir da ficha e das peças geradas (lataria por molde). '
                'Metros, frente +X, ESQUERDA +Y, cima +Z, chão em z = 0, origem entre os eixos.', medidas=medidas, parts=parts, rodas=rodas)


def main():
    a = argumentos()
    F = json.load(open(a.ficha, encoding='utf-8'))
    cid = F['carro']
    os.makedirs(a.out, exist_ok=True)
    nivel = a.nivel or F.get('acabamento', {}).get('nivel', 3)
    car, tri, dens = gerar(F, nivel, os.path.join(a.out, cid + '.glb'))
    resumo = dict(carro=cid, ficha=os.path.basename(a.ficha), nivel=nivel, triangulos=tri, triangulos_total=sum(tri.values()),
                  materiais=sorted(_mats), uv_por_metro=dens, fresta=car.fresta,
                  arcos=dict(raio=car.c['raio_arco'], z=car.c['z_centro_arco'], x=[car.c['eixo_dianteiro'], car.c['eixo_traseiro']]))
    if not a.so_lod0:
        for suf, nv in (('_lod1', max(nivel - 1, 1)), ('_lod2', 1)):
            _, t, _ = gerar(F, nv, os.path.join(a.out, cid + suf + '.glb'), detalhes=(suf == '_lod1'), rodas=False)
            resumo['triangulos' + suf] = sum(t.values())
    r = F.get('rodas')
    if r:
        json.dump({'front_axle_cm': car.c['eixo_dianteiro'] * 100, 'rear_axle_cm': car.c['eixo_traseiro'] * 100, 'wheel_radius_cm': r['raio'] * 100,
                   'hub_y_cm': r['cubo_y'] * 100, 'nota': 'lataria por molde (ferramentas/lataria_molde); formato de Tools/Unreal/damage_body.py'},
                  open(os.path.join(a.out, cid + '_wheels.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(resumo, open(os.path.join(a.out, cid + '_molde.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(mapa_do_corte(F, car), open(os.path.join(a.out, cid + '_mapa.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # o <id>_pecas.json que a cadeia do jogo lê (glb_texturas.py --pintura): a pintura é cor lisa, a tinta do jogo é que dá a cor
    json.dump(dict(id=cid, entrada=os.path.basename(a.ficha), gerado_por='acervo-3d/ferramentas/lataria_molde/construir.py (lataria por molde)',
                   textura=dict(pintura_rgb=list(CORES['pintura'][:3]), pintura_sat=1.0)),
              open(os.path.join(a.out, cid + '_pecas.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('lataria por molde: %s, %d triângulos sem as rodas, %d materiais' % (cid, resumo['triangulos_total'], len(_mats)))


if __name__ == '__main__':
    main()
