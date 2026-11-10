"""
Utilitários de malha da lataria por molde (numpy + bpy): subdividir um pedaço da gaiola, assentar na superfície-mestra, achar os laços
de borda, recuar a borda (a fresta), aba, pele de dentro, perfil varrido (a borracha) e o acumulador que vira objeto do Blender.
"""
import math

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def norm(a):
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.maximum(n, 1e-12)


# --------------------------------------------------------------------------------------------------------- subdivisão
def subdividir(verts, faces, uvs, nivel, vinco_vert=None, vinco_aresta=None):
    """
    Catmull-Clark do Blender (OpenSubdiv) sobre um pedaço da gaiola. A borda vira a B-spline do polígono de borda (igual nos dois
    vizinhos de um corte), os cantos arredondam conforme vinco_vert. Devolve (P, quads, st): st por canto de face, bilinear.
    """
    me = bpy.data.meshes.new('tmp')
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    uv = me.uv_layers.new(name='st')
    k = 0
    for f in uvs:
        for c in f:
            uv.data[k].uv = c
            k += 1
    if vinco_vert:
        a = me.attributes.new('crease_vert', 'FLOAT', 'POINT')
        for i, w in vinco_vert.items():
            a.data[i].value = w
    if vinco_aresta:
        a = me.attributes.new('crease_edge', 'FLOAT', 'EDGE')
        for e in me.edges:
            w = vinco_aresta.get((min(e.vertices), max(e.vertices)))
            if w:
                a.data[e.index].value = w
    ob = bpy.data.objects.new('tmp', me)
    bpy.context.scene.collection.objects.link(ob)
    if nivel > 0:
        md = ob.modifiers.new('s', 'SUBSURF')
        md.levels = nivel
        md.render_levels = nivel
        md.boundary_smooth = 'ALL'
        md.uv_smooth = 'NONE'
        md.use_creases = True
        md.use_limit_surface = True
        md.quality = 4
        dg = bpy.context.evaluated_depsgraph_get()
        m2 = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    else:
        m2 = me.copy()
    P = np.zeros(len(m2.vertices) * 3)
    m2.vertices.foreach_get('co', P)
    P = P.reshape(-1, 3)
    Q = np.zeros(len(m2.polygons) * 4, dtype=np.int64)
    m2.polygons.foreach_get('vertices', Q) if all(len(p.vertices) == 4 for p in m2.polygons) else None
    Q = Q.reshape(-1, 4)
    ST = np.zeros(len(m2.loops) * 2)
    m2.uv_layers['st'].data.foreach_get('uv', ST)
    ST = ST.reshape(-1, 4, 2)
    bpy.data.objects.remove(ob)
    bpy.data.meshes.remove(me)
    bpy.data.meshes.remove(m2)
    return P, Q, ST


class Mestra:
    """A superfície-mestra (a gaiola inteira subdividida): ponto mais próximo e normal lisa, para assentar as peças."""

    def __init__(self, P, Q, ST=None, passo=16):
        self.P = P
        self.passo = passo
        self.por_st = {}
        if ST is not None:
            for f, st in zip(Q, ST):
                for v, (u, w) in zip(f, st):
                    self.por_st[(int(round(u * passo)), int(round(w * passo)))] = v
        tris = np.concatenate([Q[:, [0, 1, 2]], Q[:, [0, 2, 3]]])
        self.tris = tris
        fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
        vn = np.zeros_like(P)
        for c in range(3):
            np.add.at(vn, tris[:, c], fn)
        self.vn = norm(vn)
        self.bvh = BVHTree.FromPolygons([tuple(p) for p in P], [tuple(t) for t in tris])

    def assentar(self, X):
        """Para cada ponto: o ponto mais próximo na mestra e a normal interpolada."""
        Y = np.zeros_like(X)
        N = np.zeros_like(X)
        for i, x in enumerate(X):
            loc, _, ti, _ = self.bvh.find_nearest(Vector(x))
            a, b, c = self.tris[ti]
            pa, pb, pc = self.P[a], self.P[b], self.P[c]
            p = np.array(loc)
            v0, v1, v2 = pb - pa, pc - pa, p - pa
            d00, d01, d11, d20, d21 = v0 @ v0, v0 @ v1, v1 @ v1, v2 @ v0, v2 @ v1
            den = d00 * d11 - d01 * d01
            if abs(den) < 1e-18:
                w1 = w2 = 0.0
            else:
                w1 = (d11 * d20 - d01 * d21) / den
                w2 = (d00 * d21 - d01 * d20) / den
            n = self.vn[a] * (1 - w1 - w2) + self.vn[b] * w1 + self.vn[c] * w2
            Y[i] = p
            N[i] = n
        return Y, norm(N)

    def assentar_por_molde(self, P, Q, ST, P_vivo=None, passos=6):
        """
        Assenta uma peça subdividida à parte. Cada vértice parte do ponto da mestra de mesma coordenada de molde (que nunca dobra: é
        o corte exato da mestra pela linha da gaiola) e anda sobre a superfície só o deslize do canto arredondado: a diferença entre
        a peça subdividida com os cantos arredondados (P) e com os cantos vivos (P_vivo). Longe dos cantos o deslize é zero e a
        borda é a própria linha da mestra, igual nos dois vizinhos.
        """
        delta = (P - P_vivo) if P_vivo is not None else None
        Y = P.copy()
        N = np.zeros_like(P)
        base = np.full(len(P), -1, dtype=np.int64)
        for f, st in zip(Q, ST):
            for v, (u, w) in zip(f, st):
                if base[v] < 0:
                    m = self.por_st.get((int(round(u * self.passo)), int(round(w * self.passo))))
                    if m is not None:
                        base[v] = m
        for v in range(len(P)):
            m = base[v]
            if m < 0:
                y, n = self.assentar(P[v][None, :])
                Y[v], N[v] = y[0], n[0]
                continue
            q, n = self.P[m].copy(), self.vn[m]
            alvo = (q + delta[v]) if delta is not None else P[v]
            r = alvo - q
            rt = r - (r @ n) * n
            if np.linalg.norm(rt) < 0.0003:
                Y[v], N[v] = q, n
                continue
            for k in range(passos, 0, -1):
                r = alvo - q
                rt = r - (r @ n) * n
                y, nn = self.assentar((q + rt / k)[None, :])
                q, n = y[0], nn[0]
            Y[v], N[v] = q, n
        return Y, norm(N)

    def raio(self, o, d):
        h = self.bvh.ray_cast(Vector(o), Vector(d))
        return None if h[0] is None else np.array(h[0])


# --------------------------------------------------------------------------------------------------------- bordas
def lacos_de_borda(Q):
    """Laços fechados de vértices de borda, na ordem em que a face os percorre (a face fica à esquerda)."""
    cont = {}
    for f in Q:
        for a, b in zip(f, np.roll(f, -1)):
            cont[(a, b)] = cont.get((a, b), 0) + 1
    prox = {}
    for (a, b) in cont:
        if (b, a) not in cont:
            prox.setdefault(a, []).append(b)
    lacos, visto = [], set()
    for ini in list(prox):
        if ini in visto:
            continue
        laco, v = [], ini
        while v not in visto:
            visto.add(v)
            laco.append(v)
            cand = [w for w in prox.get(v, []) if w not in visto]
            if not cand:
                break
            v = cand[0]
        if len(laco) >= 3:
            lacos.append(np.array(laco))
    return lacos


def quadro_da_borda(P, N, laco):
    """Tangente e direção para dentro da peça (no plano da superfície) em cada vértice do laço."""
    p = P[laco]
    T = norm(np.roll(p, -1, 0) - np.roll(p, 1, 0))
    D = norm(np.cross(N[laco], T))      # a face fica à esquerda de quem anda no laço com a normal para cima
    return T, D


def recuar_borda(P, N, Q, recuo, filtro=None):
    """Recua a borda da peça para dentro, no plano da superfície (meia fresta). filtro(p) escolhe os vértices."""
    P0 = P
    P = P.copy()
    for laco in lacos_de_borda(Q):
        _, D = quadro_da_borda(P0, N, laco)
        p = P0[laco]
        e0, e1 = norm(p - np.roll(p, 1, 0)), norm(np.roll(p, -1, 0) - p)
        meia = np.sqrt(np.clip((1 + np.einsum('ij,ij->i', e0, e1)) / 2, 0.36, 1.0))      # cosseno de meia virada (esquadria)
        for i, v in enumerate(laco):
            if filtro is None or filtro(P0[v]):
                P[v] = P0[v] + D[i] * recuo / meia[i]
    return P


# --------------------------------------------------------------------------------------------------------- acumulador
class Obra:
    """Junta vértices, normais, faces, material e UV de uma peça e vira um objeto do Blender."""

    def __init__(self, nome):
        self.nome = nome
        self.P, self.N, self.F, self.M, self.UV, self.ILHA = [], [], [], [], [], []
        self.n = 0

    def somar(self, P, N, faces, material, uv=None, ilha=None):
        """faces: lista de tuplas de índices locais (3 ou 4); uv: por face, lista de (u, v) por canto; ilha: rótulo da ilha de UV."""
        base = self.n
        P = np.asarray(P, dtype=float)
        N = np.asarray(N, dtype=float)
        self.P.append(P)
        self.N.append(N)
        self.n += len(P)
        for k, f in enumerate(faces):
            f = [int(i) for i in f]
            u = uv[k] if uv is not None else None
            # o lado da face é o da normal dada: a geometria nunca fica do avesso por engano de ordem
            g = np.cross(P[f[1]] - P[f[0]], P[f[-1]] - P[f[0]])
            if len(f) == 4:
                g = g + np.cross(P[f[3]] - P[f[2]], P[f[1]] - P[f[2]])
            if g @ N[f].sum(0) < 0:
                f = f[::-1]
                u = list(u)[::-1] if u is not None else None
            self.F.append(tuple(i + base for i in f))
            self.M.append(material)
            self.UV.append(u)
            self.ILHA.append(ilha)
        return base

    def somar_duplo(self, P, N, faces, material, afastar=0.003):
        """Uma casca com os dois lados (o de trás afastado), para o que é visto por dentro e por fora."""
        P = np.asarray(P, dtype=float)
        N = norm(np.asarray(N, dtype=float))
        self.somar(P, N, faces, material)
        self.somar(P - N * afastar, -N, faces, material)

    def tri(self):
        return sum(len(f) - 2 for f in self.F)

    def objeto(self, materiais):
        P = np.concatenate(self.P) if self.P else np.zeros((0, 3))
        N = np.concatenate(self.N) if self.N else np.zeros((0, 3))
        # o quadrilátero torto ou em cunha (cantos arredondados, bordas recuadas) é partido aqui pela diagonal boa: deixado ao
        # exportador, a diagonal ruim dá um triângulo virado (uma dobra de 180 graus na pele)
        Fs, Ms, UVs = [], [], []
        Nn = norm(N) if len(N) else N
        for f, m, u in zip(self.F, self.M, self.UV):
            if len(f) == 4:
                q = P[list(f)]
                n = Nn[list(f)].sum(0)
                ar = lambda a, b, c: float(np.cross(q[b] - q[a], q[c] - q[a]) @ n)
                m02, m13 = min(ar(0, 1, 2), ar(0, 2, 3)), min(ar(0, 1, 3), ar(1, 2, 3))
                tris = None
                if m02 < 0.3 * m13:
                    tris = ((0, 1, 3), (1, 2, 3))
                elif m13 < 0.3 * m02:
                    tris = ((0, 1, 2), (0, 2, 3))
                if tris:
                    for t in tris:
                        Fs.append(tuple(f[i] for i in t))
                        Ms.append(m)
                        UVs.append([u[i] for i in t] if u is not None else None)
                    continue
            Fs.append(f)
            Ms.append(m)
            UVs.append(u)
        me = bpy.data.meshes.new(self.nome)
        me.from_pydata([tuple(p) for p in P], [], Fs)
        nomes = []
        for m in Ms:
            if m not in nomes:
                nomes.append(m)
        for m in nomes:
            me.materials.append(materiais(m))
        uv = me.uv_layers.new(name='UVMap')
        k = 0
        for p, m, u in zip(me.polygons, Ms, UVs):
            p.material_index = nomes.index(m)
            p.use_smooth = True
            for c in range(len(p.vertices)):
                uv.data[k].uv = u[c] if u is not None else (0.005, 0.005)
                k += 1
        me.normals_split_custom_set_from_vertices([tuple(n) for n in norm(N)])
        ob = bpy.data.objects.new(self.nome, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob


# --------------------------------------------------------------------------------------------------------- construções
def aba(obra, P, N, Q, fundo, material, filtro=None, puxar=0.0, qualquer=False):
    """A aba da borda: a chapa dobra para dentro (-normal) por `fundo`. A borda de fora é a da pele (soma depois da pele, mesma posição)."""
    for laco in lacos_de_borda(Q):
        T, D = quadro_da_borda(P, N, laco)
        n = len(laco)
        ok = np.array([filtro is None or filtro(P[v]) for v in laco])
        if not ok.any():
            continue
        a = P[laco]
        b = a - N[laco] * fundo + D * puxar
        na = N[laco]
        nb = -D
        faces = []
        for i in range(n):
            j = (i + 1) % n
            if ((ok[i] or ok[j]) if qualquer else (ok[i] and ok[j])) and np.linalg.norm(a[i] - a[j]) < 0.2:
                faces.append((j, i, n + i, n + j))
        obra.somar(np.concatenate([a, b]), np.concatenate([norm(na * 0.6 - D * 0.4), nb]), faces, material)


def pele_de_dentro(obra, P, N, Q, espessura, material, recuo=0.003):
    """A pele de dentro: a mesma superfície deslocada para dentro e virada, com a borda um pouco recuada."""
    P2 = recuar_borda(P, N, Q, recuo) - N * espessura
    obra.somar(P2, -N, [tuple(reversed(f)) for f in Q], material)


def varrer_perfil(obra, C, N, D, perfil, material, fechado=True):
    """
    Varre um perfil fechado ao longo de uma curva fechada C (pontos, com a normal N e a direção D para dentro do vão).
    perfil: lista de (d, n) em metros, no sentido horário visto com D para a direita e N para cima.
    """
    n, m = len(C), len(perfil)
    Pp, Nn = [], []
    pf = np.array(perfil)
    cen = pf.mean(0)
    for (d, h) in perfil:
        Pp.append(C + D * d + N * h)
        r = np.array([d - cen[0], h - cen[1]])
        r = r / max(np.linalg.norm(r), 1e-9)
        Nn.append(norm(D * r[0] + N * r[1]))
    faces = []
    for i in range(n if fechado else n - 1):
        j = (i + 1) % n
        for k in range(m):
            l = (k + 1) % m
            faces.append((k * n + i, k * n + j, l * n + j, l * n + i))
    Pp, Nn = np.concatenate(Pp), np.concatenate(Nn)
    obra.somar(Pp, Nn, faces, material)
    if not fechado:                      # tampas nas duas pontas
        for i, sinal in ((0, -1.0), (n - 1, 1.0)):
            t = norm(C[min(i + 1, n - 1)] - C[max(i - 1, 0)]) * sinal
            anel = np.array([Pp[k * n + i] for k in range(m)])
            Pt = np.concatenate([anel, anel.mean(0)[None, :]])
            obra.somar(Pt, np.tile(t, (m + 1, 1)), [(k, (k + 1) % m, m) for k in range(m)], material)


def caixa_arredondada(obra, centro, eixos, meias, material, nivel=2, vinco=0.0, uv=None):
    """Uma caixa suavizada por subdivisão. eixos: 3 vetores unitários; meias: as 3 meias-medidas."""
    c = np.array(centro, dtype=float)
    E = [np.array(e, dtype=float) for e in eixos]
    V = [c + sx * E[0] * meias[0] + sy * E[1] * meias[1] + sz * E[2] * meias[2] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    Fc = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    ar = {}
    if vinco:
        for f in Fc:
            for a, b in zip(f, f[1:] + f[:1]):
                ar[(min(a, b), max(a, b))] = vinco
    P, Q, _ = subdividir(V, Fc, [[(0, 0)] * 4] * 6, nivel, vinco_aresta=ar)
    if (normais_de_malha(P, Q)[0] @ (P[0] - c)) < 0:
        Q = Q[:, ::-1]
    N = normais_de_malha(P, Q)
    obra.somar(P, N, [tuple(f) for f in Q], material, uv=uv)


def normais_de_malha(P, Q):
    fn = np.cross(P[Q[:, 1]] - P[Q[:, 0]], P[Q[:, 3]] - P[Q[:, 0]])
    vn = np.zeros_like(P)
    for c in range(Q.shape[1]):
        np.add.at(vn, Q[:, c], fn)
    return norm(vn)
