"""
Detalhes paramétricos sobre um corte limpo (Gol Quadrado do Sketchfab, 29/10/2026): o modelo baixo polígono traz faróis, grade e
lanternas como placas lisas. Este passo refaz essas peças com os detalhes da carroceria_limpa/ e põe o que o modelo não tem:

- faróis e lanternas: moldura preta de 8 mm, lente convexa 4 mm à frente, paredes para trás tapando o bolso; a lanterna traseira em
  três segmentos separados por divisórias pretas (ré, seta, freio: no jogo a lente inteira é o material da lanterna);
- grade: moldura preta, fundo recuado 5 cm e palhetas horizontais pretas;
- palhetas do limpador no para-brisa (duas, deitadas no vidro, 8 mm acima dele);
- maçanetas nas portas (base chata e alça, pretas);
- friso lateral preto ao longo da lateral, cortado por peça (para-lama, porta, carroceria) para ir com a porta;
- faixa de borracha preta na face dos para-choques (desviando da placa da frente).

    python -I ferramentas/detalhes_na_casca.py -- <corte>.glb <saida>.glb [--sem-friso] [--sem-faixa] [--sem-limpador]
        [--sem-macaneta] [--z-friso 0.58] [--z-faixa 0.42]

Materiais só os do corte (`chassi` = plástico preto, `luz` = lente): o kit_names.py do Detonauto já sabe o que fazer com eles.
As normais de canto das peças que só ganham geometria ficam; faróis, lanternas e grade são refeitos e recebem normais por ângulo.
"""
import math
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


Z_FRISO = opt("--z-friso", 0.58)
Z_FAIXA = opt("--z-faixa", 0.42)
relatorio = []

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}


def mat_names(o):
    return [s.material.name.split(".")[0] if s.material else "" for s in o.material_slots]


def slot(o, nome):
    """Índice do material `nome` na peça (acrescenta o material do corte se a peça não o tem)."""
    nomes = mat_names(o)
    if nome in nomes:
        return nomes.index(nome)
    m = next((m for m in bpy.data.materials if m.name.split(".")[0] == nome), None) or bpy.data.materials.new(nome)
    o.data.materials.append(m)
    return len(o.data.materials) - 1


def arvore(nomes):
    bm = bmesh.new()
    for n in nomes:
        o = objs.get(n)
        if not o:
            continue
        b = bmesh.new()
        b.from_mesh(o.data)
        b.transform(o.matrix_world)
        me = bpy.data.meshes.new("_t")
        b.to_mesh(me)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        b.free()
    t = BVHTree.FromBMesh(bm)
    bm.free()
    return t


arvores = {}


def raio(nomes, origem, direcao, dist=4.0):
    """Primeiro ponto atingido entre as peças `nomes`: (ponto, normal, nome) ou None."""
    melhor = None
    for n in nomes:
        if n not in objs:
            continue
        if n not in arvores:
            arvores[n] = arvore([n])
        h = arvores[n].ray_cast(Vector(origem), Vector(direcao).normalized(), dist)
        if h[0] is not None and (melhor is None or h[3] < melhor[3]):
            melhor = (h[0], h[1], n, h[3])
    return melhor


def faces_de(o, material):
    """Caixa (mundo) e normal média das faces de um material na peça."""
    me = o.data
    nomes = mat_names(me and o)
    mw = o.matrix_world
    pts, nrm = [], Vector()
    for p in me.polygons:
        if nomes[p.material_index] != material:
            continue
        for vi in p.vertices:
            pts.append(mw @ me.vertices[vi].co)
        nrm += (mw.to_3x3() @ p.normal) * p.area
    if not pts:
        return None, None
    P = np.array([list(p) for p in pts])
    return [P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()], nrm.normalized()


# ------------------------------------------------------------------------------------------------------------- escrita nas peças
class Escritor:
    """Acrescenta faces a uma peça em coordenadas do mundo. `refazer=True` apaga antes as faces de um material."""

    def __init__(self, o, refazer=None):
        self.o = o
        self.bm = bmesh.new()
        self.bm.from_mesh(o.data)
        self.inv = o.matrix_world.inverted()
        self.n_old = len(o.data.loops)
        self.cn = np.empty(self.n_old * 3)
        o.data.corner_normals.foreach_get("vector", self.cn)
        self.refez = False
        if refazer:
            nomes = mat_names(o)
            fora = [f for f in self.bm.faces if nomes[f.material_index] in refazer]
            if fora:
                bmesh.ops.delete(self.bm, geom=fora, context="FACES")
                self.refez = True
        self.novas = []

    def quad(self, pts, mi, suave=False):
        vs = [self.bm.verts.new(self.inv @ Vector(p)) for p in pts]
        try:
            f = self.bm.faces.new(vs)
        except ValueError:
            return None
        f.material_index = mi
        f.smooth = suave
        self.novas.append(f)
        return f

    def caixa(self, centro, dx, dy, dz, mi, eixos=None):
        """Paralelepípedo centrado; `eixos` = (e1, e2, e3) unitários do mundo (padrão x, y, z)."""
        e1, e2, e3 = eixos or (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        c = Vector(centro)
        P = {}
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    P[(sx, sy, sz)] = c + e1 * (sx * dx / 2) + e2 * (sy * dy / 2) + e3 * (sz * dz / 2)
        caras = [((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)), ((-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)),
                 ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)), ((-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)),
                 ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)), ((-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1))]
        for cara in caras:
            self.quad([P[k] for k in cara], mi)

    def varrer(self, pontos, perfil, mi, fechar=True):
        """Varre um perfil (s, t) ao longo de uma linha 3D; s = normal horizontal para fora (dada por ponto), t = para cima."""
        aneis = []
        for p, nrm in pontos:
            n = Vector((nrm[0], nrm[1], 0.0)).normalized()
            aneis.append([Vector(p) + n * s + Vector((0, 0, t)) for s, t in perfil])
        for i in range(len(aneis) - 1):
            a, b = aneis[i], aneis[i + 1]
            for j in range(len(perfil)):
                self.quad([a[j], b[j], b[(j + 1) % len(perfil)], a[(j + 1) % len(perfil)]], mi, suave=True)
        if fechar and len(aneis) > 1:
            self.quad(aneis[0][::-1], mi)
            self.quad(aneis[-1], mi)

    def fechar(self, normais_por_angulo=False):
        me = self.o.data
        for f in self.novas:
            f.normal_update()
        bmesh.ops.recalc_face_normals(self.bm, faces=self.novas)
        self.bm.to_mesh(me)
        me.update()
        if self.refez or normais_por_angulo:
            # peça refeita: normais por ângulo (as de canto do arquivo não valem mais)
            with bpy.context.temp_override(object=self.o, active_object=self.o, selected_objects=[self.o],
                                           selected_editable_objects=[self.o]):
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
            me.shade_smooth()
            b = bmesh.new()
            b.from_mesh(me)
            vivas = [False] * len(me.edges)
            for e in b.edges:
                if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(30):
                    vivas[e.index] = True
            b.free()
            at = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
            at.data.foreach_set("value", vivas)
        else:
            cn_new = np.empty(len(me.loops) * 3)
            me.corner_normals.foreach_get("vector", cn_new)
            cn_new[: self.n_old * 3] = self.cn
            me.normals_split_custom_set(cn_new.reshape(-1, 3).tolist())
        me.update()
        self.bm.free()


def perfil_arredondado(prof, alt, r, n=3):
    pts = []
    cx, cy = prof / 2 - r, alt / 2 - r
    for (sx, sy, a0) in ((1, 1, 0), (-1, 1, math.pi / 2), (-1, -1, math.pi), (1, -1, 3 * math.pi / 2)):
        for i in range(n + 1):
            a = a0 + (math.pi / 2) * i / n
            pts.append((sx * cx + r * math.cos(a), sy * cy + r * math.sin(a)))
    return pts


# ------------------------------------------------------------------------------------------------------- faróis e lanternas
def lanterna(w, sinal, box, m_preto, m_lente, segmentos=None, prof=0.03, e=0.008):
    """Moldura preta de `e` na boca do bolso, lente 4 mm à frente (segmentos em y com divisórias) e paredes para trás."""
    x0, x1, y0, y1, z0, z1 = box
    xf = x1 if sinal > 0 else x0
    Y0, Y1, Z0, Z1 = y0, y1, z0, z1
    ext = [(xf, Y0, Z0), (xf, Y1, Z0), (xf, Y1, Z1), (xf, Y0, Z1)]
    inn = [(xf, Y0 + e, Z0 + e), (xf, Y1 - e, Z0 + e), (xf, Y1 - e, Z1 - e), (xf, Y0 + e, Z1 - e)]
    for k in range(4):
        a, b = ext[k], ext[(k + 1) % 4]
        c, d = inn[(k + 1) % 4], inn[k]
        w.quad([a, b, c, d] if sinal > 0 else [d, c, b, a], m_preto)
    xl = xf + sinal * 0.004
    seg = segmentos or [(0.0, 1.0)]
    ya0, ya1 = Y0 + e, Y1 - e
    for i, (u0, u1) in enumerate(seg):
        ya, yb = ya0 + (ya1 - ya0) * u0, ya0 + (ya1 - ya0) * u1
        if i > 0:
            ya += 0.004
        if i < len(seg) - 1:
            yb -= 0.004
        p = [(xl, ya, Z0 + e), (xl, yb, Z0 + e), (xl, yb, Z1 - e), (xl, ya, Z1 - e)]
        w.quad(p if sinal > 0 else p[::-1], m_lente)
        # lado da lente até a moldura (a lente é 4 mm à frente)
        for (a, b) in (((xl, ya, Z0 + e), (xl, yb, Z0 + e)), ((xl, yb, Z1 - e), (xl, ya, Z1 - e)),
                       ((xl, ya, Z1 - e), (xl, ya, Z0 + e)), ((xl, yb, Z0 + e), (xl, yb, Z1 - e))):
            q = [a, b, (xf, b[1], b[2]), (xf, a[1], a[2])]
            w.quad(q if sinal > 0 else q[::-1], m_preto)
    # divisórias entre segmentos
    for i in range(1, len(seg)):
        yd = ya0 + (ya1 - ya0) * seg[i][0]
        p = [(xl, yd - 0.004, Z0 + e), (xl, yd + 0.004, Z0 + e), (xl, yd + 0.004, Z1 - e), (xl, yd - 0.004, Z1 - e)]
        w.quad(p if sinal > 0 else p[::-1], m_preto)
    # paredes para trás, tapando o bolso
    xb = xf - sinal * prof
    paredes = [((xf, Y0, Z0), (xf, Y1, Z0), (xb, Y1, Z0), (xb, Y0, Z0)), ((xf, Y1, Z1), (xf, Y0, Z1), (xb, Y0, Z1), (xb, Y1, Z1)),
               ((xf, Y0, Z1), (xf, Y0, Z0), (xb, Y0, Z0), (xb, Y0, Z1)), ((xf, Y1, Z0), (xf, Y1, Z1), (xb, Y1, Z1), (xb, Y1, Z0)),
               ((xb, Y0, Z0), (xb, Y1, Z0), (xb, Y1, Z1), (xb, Y0, Z1))]
    for p in paredes:
        w.quad(list(p) if sinal > 0 else list(p)[::-1], m_preto)


for nome, sinal in (("headlight_left", 1), ("headlight_right", 1), ("taillight_left", -1), ("taillight_right", -1)):
    o = objs.get(nome)
    if not o:
        continue
    box, nrm = faces_de(o, "luz")
    if box is None:
        continue
    w = Escritor(o, refazer=("luz", "pintura", "cromado"))
    m_preto, m_lente = slot(o, "chassi"), slot(o, "luz")
    esq = "left" in nome
    if sinal < 0:
        # lanterna: ré perto do centro, seta no meio, freio na ponta
        seg = [(0.0, 0.3), (0.3, 0.55), (0.55, 1.0)] if not esq else [(0.0, 0.45), (0.45, 0.7), (0.7, 1.0)]
    else:
        seg = None
    lanterna(w, sinal, box, m_preto, m_lente, seg)
    w.fechar()
    relatorio.append("%s: lente %.0fx%.0f cm na face x=%.3f" % (nome, (box[3] - box[2]) * 100, (box[5] - box[4]) * 100, box[1] if sinal > 0 else box[0]))

# ------------------------------------------------------------------------------------------------------------------- grade
o = objs.get("grille")
if o:
    box, nrm = faces_de(o, "pintura")
    if box is None:
        box, nrm = faces_de(o, "luz")
    if box is not None:
        w = Escritor(o, refazer=("pintura", "luz", "cromado"))
        m_preto = slot(o, "chassi")
        x0, x1, y0, y1, z0, z1 = box
        xf = x1
        e = 0.012
        ext = [(xf, y0, z0), (xf, y1, z0), (xf, y1, z1), (xf, y0, z1)]
        inn = [(xf, y0 + e, z0 + e), (xf, y1 - e, z0 + e), (xf, y1 - e, z1 - e), (xf, y0 + e, z1 - e)]
        for k in range(4):
            a, b = ext[k], ext[(k + 1) % 4]
            w.quad([a, b, inn[(k + 1) % 4], inn[k]], m_preto)
        prof = 0.05
        xb = xf - prof
        paredes = [((xf, y0 + e, z0 + e), (xf, y1 - e, z0 + e), (xb, y1 - e, z0 + e), (xb, y0 + e, z0 + e)),
                   ((xf, y1 - e, z1 - e), (xf, y0 + e, z1 - e), (xb, y0 + e, z1 - e), (xb, y1 - e, z1 - e)),
                   ((xf, y0 + e, z1 - e), (xf, y0 + e, z0 + e), (xb, y0 + e, z0 + e), (xb, y0 + e, z1 - e)),
                   ((xf, y1 - e, z0 + e), (xf, y1 - e, z1 - e), (xb, y1 - e, z1 - e), (xb, y1 - e, z0 + e)),
                   ((xb, y0 + e, z0 + e), (xb, y1 - e, z0 + e), (xb, y1 - e, z1 - e), (xb, y0 + e, z1 - e))]
        for p in paredes:
            w.quad(list(p), m_preto)
        n_pal = 4
        h = (z1 - z0 - 2 * e) / n_pal
        for k in range(n_pal):
            zc = z0 + e + (k + 0.5) * h
            w.caixa((xf - 0.012, 0.5 * (y0 + y1), zc), 0.02, (y1 - y0 - 2 * e), h * 0.5, m_preto)
        # duas travessas verticais
        for yc in (-(y1 - y0) / 6, (y1 - y0) / 6):
            w.caixa((xf - 0.014, 0.5 * (y0 + y1) + yc, 0.5 * (z0 + z1)), 0.016, 0.012, (z1 - z0 - 2 * e), m_preto)
        w.fechar()
        relatorio.append("grade: %.0fx%.0f cm, %d palhetas" % ((y1 - y0) * 100, (z1 - z0) * 100, n_pal))

# ------------------------------------------------------------------------------------------------------- limpadores
if "--sem-limpador" not in args and "glass_windshield" in objs and "body" in objs:
    g = objs["glass_windshield"]
    box, nrm = faces_de(g, "vidro")
    if box is not None:
        n = nrm if nrm.x > 0 else -nrm
        # base no pé do vidro, 4 cm acima da borda; ponta subindo pelo vidro e para fora
        w = Escritor(objs["body"])
        m_preto = slot(objs["body"], "chassi")
        cima = Vector((0, 0, 1)) - n * n.z
        cima.normalize()
        lado = n.cross(cima).normalized()           # +y
        # as duas palhetas paralelas, descansando quase deitadas e apontando para o lado do carona (-y)
        for s, comp in ((0.22, 0.50), (-0.30, 0.46)):
            h = raio(["glass_windshield"], (box[1] + 0.3, s, box[4] + 0.05), (-n.x, 0, -n.z), 1.0)
            if not h:
                continue
            base = Vector(h[0]) + n * 0.006
            dirn = (cima * 0.42 - lado * 0.91).normalized()
            ponta = base + dirn * comp
            e1, e3 = dirn, n
            e2 = e3.cross(e1).normalized()
            # braço (fino) e palheta (mais larga, nos últimos 60%)
            w.caixa(base + dirn * (comp * 0.5) + n * 0.010, comp, 0.012, 0.008, m_preto, (e1, e2, e3))
            w.caixa(base + dirn * (comp * 0.62) + n * 0.004, comp * 0.72, 0.03, 0.010, m_preto, (e1, e2, e3))
            w.caixa(base + n * 0.012, 0.03, 0.03, 0.02, m_preto, (e1, e2, e3))
        w.fechar()
        relatorio.append("limpadores: 2 no para-brisa")

# ------------------------------------------------------------------------------------------------------- maçanetas
if "--sem-macaneta" not in args:
    for nome, s in (("door_fl", 1), ("door_fr", -1)):
        o = objs.get(nome)
        if not o:
            continue
        box, _ = faces_de(o, "pintura")
        if box is None:
            continue
        x = box[0] + 0.16
        z = box[5] - 0.12 if box[5] < 1.0 else 0.79
        h = raio([nome], (x, s * 1.5, z), (0, -s, 0), 2.0)
        if not h:
            continue
        w = Escritor(o)
        m_preto = slot(o, "chassi")
        yc = h[0].y
        w.caixa((x, yc + s * 0.006, z), 0.13, 0.012, 0.03, m_preto)
        w.caixa((x + 0.015, yc + s * 0.017, z + 0.004), 0.085, 0.012, 0.012, m_preto)
        w.fechar()
        relatorio.append("%s: maçaneta em x=%.2f z=%.2f" % (nome, x, z))

# ------------------------------------------------------------------------------------------------- friso lateral
if "--sem-friso" not in args:
    pecas_lado = ["body", "door_fl", "door_fr", "fender_front_left", "fender_front_right", "fender_rear_left", "fender_rear_right"]
    perfil = perfil_arredondado(0.008, 0.025, 0.003)
    for s in (1, -1):
        trechos = {}
        xs = np.arange(-1.78, 1.72, 0.03)
        atual = None
        for x in xs:
            h = raio(pecas_lado, (x, s * 1.5, Z_FRISO), (0, -s, 0), 2.0)
            if not h or abs(h[1].y) < 0.6:
                atual = None
                continue
            nome = h[2]
            if atual is None or atual[0] != nome or (x - atual[1][-1][0].x) > 0.05:
                atual = (nome, [])
                trechos.setdefault(nome, []).append(atual[1])
            atual[1].append((Vector(h[0]) + Vector((0, 0, 0)), (0, s, 0)))
        for nome, listas in trechos.items():
            o = objs.get(nome)
            if not o:
                continue
            w = Escritor(o)
            m_preto = slot(o, "chassi")
            n_tr = 0
            for pts in listas:
                if len(pts) < 3:
                    continue
                # encolhe 1,2 cm nas pontas (fresta) e desloca 1 mm para fora da chapa
                pts = pts[1:-1] if len(pts) > 4 else pts
                pts = [(p + Vector((0, s * 0.001, 0)), nn) for p, nn in pts]
                w.varrer(pts, perfil, m_preto)
                n_tr += 1
            w.fechar()
            relatorio.append("friso %s em %s: %d trecho(s)" % ("esq" if s > 0 else "dir", nome, n_tr))

# ------------------------------------------------------------------------------------------------------- retrovisores
def espelho(w, box, s, m_preto, m_vidro):
    """Caixa arredondada (perfil em x-z varrido em y), espelho na face de trás, haste até a porta."""
    x0, x1, y0, y1, z0, z1 = box
    prof, alt = x1 - x0, z1 - z0
    perfil = perfil_arredondado(prof, alt, min(0.02, prof * 0.3), 3)
    cx, cz = 0.5 * (x0 + x1), 0.5 * (z0 + z1)
    ya, yb = (y0 + 0.02, y1) if s > 0 else (y0, y1 - 0.02)         # a haste ocupa os 2 cm junto da porta
    aneis = []
    for y in (ya, yb):
        aneis.append([Vector((cx + px, y, cz + pz)) for px, pz in perfil])
    a, b = aneis
    n = len(perfil)
    for j in range(n):
        w.quad([a[j], b[j], b[(j + 1) % n], a[(j + 1) % n]] if s > 0 else [b[j], a[j], a[(j + 1) % n], b[(j + 1) % n]], m_preto, suave=True)
    w.quad(a[::-1] if s > 0 else a, m_preto)
    w.quad(b if s > 0 else b[::-1], m_preto)
    # espelho: placa 3 mm atrás da face de trás, um pouco menor
    xe = x0 - 0.003
    e = 0.012
    p = [(xe, ya + e, z0 + e), (xe, yb - e, z0 + e), (xe, yb - e, z1 - e), (xe, ya + e, z1 - e)]
    w.quad(p[::-1], m_vidro)
    # haste: da caixa até a chapa (o triângulo da coluna A)
    h = raio(["door_fl" if s > 0 else "door_fr", "body"], (cx, s * 0.2, cz + 0.01), (0, s, 0), 2.0)
    if h:
        yc = h[0].y
        w.caixa((cx + 0.005, 0.5 * (yc + (y0 if s > 0 else y1)), cz + 0.01), 0.03, abs((y0 if s > 0 else y1) - yc) + 0.01, 0.025, m_preto)
        w.caixa((cx + 0.005, yc + s * 0.004, cz + 0.01), 0.06, 0.008, 0.06, m_preto)


for nome, s in (("mirror_left", 1), ("mirror_right", -1)):
    o = objs.get(nome)
    if not o:
        continue
    box, _ = faces_de(o, "pintura")
    if box is None:
        continue
    w = Escritor(o, refazer=("pintura", "luz", "cromado", "chassi", "vidro"))
    espelho(w, box, s, slot(o, "chassi"), slot(o, "luz"))
    w.fechar()
    relatorio.append("%s: caixa %.0fx%.0fx%.0f cm refeita" % (nome, (box[1] - box[0]) * 100, (box[3] - box[2]) * 100, (box[5] - box[4]) * 100))

# ------------------------------------------------------------------------------------- tampa do tanque e antena
if "body" in objs and "--sem-miudezas" not in args:
    w = Escritor(objs["body"])
    m_preto, m_crom = slot(objs["body"], "chassi"), slot(objs["body"], "cromado")
    # tampa do tanque na quarta traseira direita (lado do carona no Brasil)
    h = raio(["body"], (-1.40, -1.5, 0.78), (0, 1, 0), 2.0)
    if h and abs(h[1].y) > 0.6:
        c = Vector(h[0])
        ang = [i * 2 * math.pi / 16 for i in range(16)]
        pts = [c + Vector((0.035 * math.cos(a), -0.004, 0.035 * math.sin(a))) for a in ang]
        w.quad(pts, m_preto)
        pts2 = [c + Vector((0.035 * math.cos(a), 0.0, 0.035 * math.sin(a))) for a in ang]
        for i in range(16):
            w.quad([pts2[i], pts2[(i + 1) % 16], pts[(i + 1) % 16], pts[i]], m_preto)
        relatorio.append("tampa do tanque em x=%.2f z=%.2f (lado direito)" % (c.x, c.z))
    # antena no para-lama esquerdo, junto da base do para-brisa
    # antena no para-lama esquerdo, atrás da caixa de roda (nunca no capô)
    h = None
    for xa in (1.05, 0.95, 0.85):
        h = raio(["fender_front_left", "body"], (xa, 0.63, 2.0), (0, 0, -1), 3.0)
        if h and h[1].z > 0.7:
            break
        h = None
    if h:
        base = Vector(h[0])
        if base.z > 0.6:
            ang = [i * 2 * math.pi / 8 for i in range(8)]
            for (r, z0_, z1_, m) in ((0.012, 0.0, 0.03, m_preto), (0.004, 0.03, 0.62, m_crom)):
                a0 = [base + Vector((r * math.cos(a), r * math.sin(a), z0_)) for a in ang]
                a1 = [base + Vector((r * math.cos(a), r * math.sin(a), z1_)) for a in ang]
                for i in range(8):
                    w.quad([a0[i], a0[(i + 1) % 8], a1[(i + 1) % 8], a1[i]], m, suave=True)
                w.quad(a1, m)
            relatorio.append("antena em x=%.2f y=%.2f z=%.2f" % (base.x, base.y, base.z))
    w.fechar()

# ----------------------------------------------------------------------------------------------- faixa dos para-choques
if "--sem-faixa" not in args:
    perfil = perfil_arredondado(0.006, 0.03, 0.002)
    for nome, sinal in (("bumper_front", 1), ("bumper_rear", -1)):
        o = objs.get(nome)
        if not o:
            continue
        placa = objs.get("plate_front" if sinal > 0 else "plate_rear")
        pbox = faces_de(placa, "pintura")[0] if placa else None
        if pbox and not (pbox[4] - 0.02 < Z_FAIXA < pbox[5] + 0.02):
            pbox = None
        pts = []
        trechos = []
        for y in np.arange(-0.78, 0.781, 0.02):
            if pbox and pbox[2] - 0.03 < y < pbox[3] + 0.03:
                if pts:
                    trechos.append(pts)
                pts = []
                continue
            h = raio([nome], (sinal * 3.0, y, Z_FAIXA), (-sinal, 0, 0), 4.0)
            if not h or abs(h[1].x) < 0.5:
                if pts:
                    trechos.append(pts)
                pts = []
                continue
            pts.append((Vector(h[0]) + Vector((sinal * 0.001, 0, 0)), (sinal, 0, 0)))
        if pts:
            trechos.append(pts)
        w = Escritor(o)
        m_preto = slot(o, "chassi")
        for pts in trechos:
            if len(pts) >= 3:
                w.varrer(pts, perfil, m_preto)
        w.fechar()
        relatorio.append("faixa no %s: %d trecho(s)" % (nome, len(trechos)))

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[detalhes_na_casca]", linha)
