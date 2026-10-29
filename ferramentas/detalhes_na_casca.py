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


CORES_NOVAS = {"luz_ambar": (0.95, 0.42, 0.02, 1.0), "luz_branca": (0.90, 0.90, 0.88, 1.0), "placa": (0.80, 0.80, 0.78, 1.0),
               "luz_vermelha": (0.80, 0.02, 0.015, 1.0), "refletor": (0.95, 0.95, 0.96, 1.0)}


def slot(o, nome):
    """Índice do material `nome` na peça (acrescenta o material do corte se a peça não o tem; cria os de lanterna com cor de prévia)."""
    nomes = mat_names(o)
    if nome in nomes:
        return nomes.index(nome)
    m = next((m for m in bpy.data.materials if m.name.split(".")[0] == nome), None)
    if m is None:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        if b and nome in CORES_NOVAS:
            b.inputs["Base Color"].default_value = CORES_NOVAS[nome]
            b.inputs["Roughness"].default_value = 0.15
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
        self.ref = None            # ponto de dentro: toda face nova olha para longe dele (sem recalc, que inverte ilhas soltas)
        if refazer:
            nomes = mat_names(o)
            fora = [f for f in self.bm.faces if nomes[f.material_index] in refazer]
            if fora:
                bmesh.ops.delete(self.bm, geom=fora, context="FACES")
                self.refez = True
        self.novas = []

    def quad(self, pts, mi, suave=False, ref=None):
        ref = ref if ref is not None else self.ref
        if ref is not None and len(pts) >= 3:
            P = [Vector(p) for p in pts]
            n = (P[1] - P[0]).cross(P[2] - P[0])
            if n.length < 1e-12 and len(P) > 3:
                n = (P[2] - P[0]).cross(P[3] - P[0])
            c = sum(P, Vector()) / len(P)
            if n.dot(c - Vector(ref)) < 0:
                pts = list(pts)[::-1]
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
            self.quad([P[k] for k in cara], mi, ref=c)

    def varrer(self, pontos, perfil, mi, fechar=True):
        """Varre um perfil (s, t) ao longo de uma linha 3D; s = normal horizontal para fora (dada por ponto), t = para cima."""
        aneis = []
        for p, nrm in pontos:
            n = Vector((nrm[0], nrm[1], 0.0)).normalized()
            aneis.append([Vector(p) + n * s + Vector((0, 0, t)) for s, t in perfil])
        P = [Vector(p) for p, _ in pontos]
        for i in range(len(aneis) - 1):
            a, b = aneis[i], aneis[i + 1]
            meio = (P[i] + P[i + 1]) / 2
            for j in range(len(perfil)):
                self.quad([a[j], b[j], b[(j + 1) % len(perfil)], a[(j + 1) % len(perfil)]], mi, suave=True, ref=meio)
        if fechar and len(aneis) > 1:
            self.quad(aneis[0][::-1], mi, ref=P[1])
            self.quad(aneis[-1], mi, ref=P[-2])

    def fechar(self, normais_por_angulo=False):
        me = self.o.data
        for f in self.novas:
            f.normal_update()
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


def suave(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def casca_pintada():
    """BVH só das faces pintadas da casca (sem rodas nem vidros)."""
    bm = bmesh.new()
    for n, o in objs.items():
        if n.startswith(("wheel_", "hubcap_", "glass_")):
            continue
        b = bmesh.new()
        b.from_mesh(o.data)
        b.transform(o.matrix_world)
        nomes_o = mat_names(o)
        bmesh.ops.delete(b, geom=[f for f in b.faces if nomes_o[f.material_index] != "pintura"], context="FACES")
        me_t = bpy.data.meshes.new("_p")
        b.to_mesh(me_t)
        bm.from_mesh(me_t)
        bpy.data.meshes.remove(me_t)
        b.free()
    t = BVHTree.FromBMesh(bm)
    bm.free()
    return t


def normais_por_angulo(me, angulo=30):
    """Normais de canto da malha como ficariam sem as do arquivo (lisas, com aresta viva acima de `angulo` graus), sem mexer nela."""
    tmp = me.copy()
    tmp.normals_split_custom_set([(0.0, 0.0, 0.0)] * len(tmp.loops))
    tmp.shade_smooth()
    b = bmesh.new()
    b.from_mesh(tmp)
    vivas = [False] * len(tmp.edges)
    for e in b.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(angulo):
            vivas[e.index] = True
    b.free()
    at = tmp.attributes.get("sharp_edge") or tmp.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    at.data.foreach_set("value", vivas)
    tmp.update()
    cn = np.empty(len(tmp.loops) * 3)
    tmp.corner_normals.foreach_get("vector", cn)
    bpy.data.meshes.remove(tmp)
    return cn.reshape(-1, 3)


def deformar(campo):
    """Aplica `campo(p) -> Vector` (deslocamento no mundo) a todos os vértices da casca. Como o campo só depende da posição, a costura
    entre peças (para-lama e porta, para-choque e carroceria) continua fechada. Nos cantos dos vértices que andaram, as normais do
    arquivo (da forma antiga: o arco de 7 lados continuava aparecendo no reflexo) dão lugar às normais por ângulo da forma nova."""
    n_mov = 0
    for n, o in objs.items():
        if n.startswith(("wheel_", "hubcap_", "glass_")):
            continue
        me = o.data
        mw, inv = o.matrix_world, o.matrix_world.inverted()
        cn = np.empty(len(me.loops) * 3)
        me.corner_normals.foreach_get("vector", cn)
        cn = cn.reshape(-1, 3)
        andou = np.zeros(len(me.vertices), bool)
        for v in me.vertices:
            d = campo(mw @ v.co)
            if d is not None and d.length > 1e-6:
                v.co = inv @ ((mw @ v.co) + d)
                andou[v.index] = True
        me.update()
        if andou.any():
            n_mov += int(andou.sum())
            nova = normais_por_angulo(me)
            lv = np.empty(len(me.loops), np.int64)
            me.loops.foreach_get("vertex_index", lv)
            cn[andou[lv]] = nova[andou[lv]]
            me.normals_split_custom_set(cn.tolist())
            me.update()
    return n_mov


# ------------------------------------------------------------------------------------------- caixas de roda redondas
# o Gol do Sketchfab traz a caixa de roda como um polígono de 6 ou 7 lados, mais apertada na frente de baixo (2 cm do pneu) e com a
# borda saltada 2 cm para fora (cara de alargador). No Gol quadrado de verdade a caixa é um arco redondo, rente à lateral (o Felipe
# achou os para-lamas estranhos, 29/10). Por ângulo, mede-se a borda do arco vista de lado e o quanto ela salta da lateral; o campo
# leva a borda para um círculo de raio R_ARCO em volta do cubo e recolhe o salto inteiro, sumindo 12 cm para fora da borda
if "--sem-arco-redondo" not in args:
    import json
    R_ARCO, FAIXA, RECOLHE = opt("--r-arco", 0.34), 0.12, 1.0
    mapa_p = ent.rsplit("/", 1)[0] + "/" + ent.rsplit("/", 1)[1].replace(".glb", "_mapa.json")
    cubos = []
    try:
        for p in json.load(open(opt("--mapa", mapa_p)))["parts"]:
            if p.get("papel") == "wheel":
                cubos.append((p["centro"][0], p["centro"][2], p["lado"]))
    except (OSError, KeyError, ValueError):
        cubos = []
    if not cubos:
        # sem o mapa: o cubo de cada roda pela caixa do pneu
        for n, o in objs.items():
            if n.startswith("wheel_") and n.endswith("_tire"):
                P = np.array([list(o.matrix_world @ v.co) for v in o.data.vertices])
                cubos.append((0.5 * (P[:, 0].min() + P[:, 0].max()), 0.5 * (P[:, 2].min() + P[:, 2].max()), 1 if P[:, 1].mean() > 0 else -1))
    # as tiras pretas da caixa de roda original que descem abaixo da carroceria (até 15 cm do chão) e saem 3 cm para fora da lateral,
    # na frente da roda da frente e atrás da de trás: de frente e de lado liam como apara-barros soltos. A caixa do kit completo fica
    if "body" in objs:
        bo = objs["body"]
        nb = mat_names(bo)
        bmb = bmesh.new()
        bmb.from_mesh(bo.data)
        bmb.transform(bo.matrix_world)
        abas = [f for f in bmb.faces if nb[f.material_index] != "pintura" and all(v.co.z < 0.275 and abs(v.co.y) > 0.40 for v in f.verts)
                and any(abs(f.calc_center_median().x - cx) < 0.40 for cx, _, _ in cubos)]
        if abas:
            bmesh.ops.delete(bmb, geom=abas, context="FACES")
            bmb.transform(bo.matrix_world.inverted())
            bmb.to_mesh(bo.data)
            bo.data.update()
            relatorio.append("abas da caixa de roda abaixo da carroceria: %d faces fora" % len(abas))
        bmb.free()
    arv_p = casca_pintada()
    ANG = np.arange(-10, 191, 5)
    arcos = []
    for cx, cz, s in cubos:
        re_, sal, ylado = [], [], []
        for th in ANG:
            a = math.radians(th)
            borda, ys = None, []
            for r in np.arange(0.24, 0.52, 0.004):
                h = arv_p.ray_cast(Vector((cx + r * math.cos(a), s * 1.3, cz + r * math.sin(a))), Vector((0, -s, 0)), 0.85)
                if h[0] is not None and h[0].y * s > 0.55:
                    borda = r if borda is None else borda
                    ys.append((r, h[0].y * s))
            if borda is None:
                re_.append(np.nan)
                sal.append(0.0)
                ylado.append(np.nan)
                continue
            lab = [y for r, y in ys if r < borda + 0.02]
            lado = [y for r, y in ys if borda + 0.08 < r < borda + 0.12]
            re_.append(borda)
            sal.append(max(0.0, max(lab) - float(np.median(lado))) if lado else 0.0)
            ylado.append(float(np.median(lado)) if lado else np.nan)
        re_ = np.array(re_)
        ok = ~np.isnan(re_)
        if ok.sum() < 10:
            continue
        re_ = np.interp(ANG, ANG[ok], re_[ok])
        re_ = np.array([np.median(re_[max(0, i - 1):i + 2]) for i in range(len(re_))])     # um raio solto não entorta o arco
        sal = np.array(sal)
        ylado = np.array(ylado)
        okl = ~np.isnan(ylado)
        ylado = np.interp(ANG, ANG[okl], ylado[okl]) if okl.sum() >= 3 else np.full(len(ANG), 9.0)
        arcos.append((cx, cz, s, re_, sal, ylado))
        relatorio.append("caixa de roda x=%+.2f lado %+d: borda de %.3f a %.3f m (vira %.3f), salto até %.1f cm" % (
            cx, s, re_[ok].min() if ok.any() else 0, re_.max(), R_ARCO, 100 * sal.max()))

    def campo_arco(p):
        d = Vector()
        for cx, cz, s, re_, sal, ylado in arcos:
            if p.y * s < 0.30:
                continue
            dx, dz = p.x - cx, p.z - cz
            r = math.hypot(dx, dz)
            if r > R_ARCO + FAIXA + 0.08 or r < 1e-4:
                continue
            th = math.degrees(math.atan2(dz, dx))
            if th < -90:
                th += 360
            w_th = min(1.0, max(0.0, (th + 10) / 20)) * min(1.0, max(0.0, (190 - th) / 20))
            if w_th <= 0:
                continue
            w_y = suave(0.30, 0.42, p.y * s)
            re = float(np.interp(th, ANG, re_))
            d0 = (R_ARCO - re) * w_th * w_y
            if r <= re:
                dr = d0 * r / re
            elif r < re + FAIXA:
                dr = d0 * (1 - (r - re) / FAIXA)
            else:
                dr = 0.0
            d += Vector((dx / r, 0, dz / r)) * dr
            # o salto da borda: a pele que passa do plano da lateral (medido 8 a 12 cm para fora da borda) volta para ele até 7 cm da
            # borda, sumindo até 11 cm (recolher o salto por igual deixava o vinco do alargador 5 cm acima do arco)
            fora_ = p.y * s - float(np.interp(th, ANG, ylado))
            if fora_ > 0 and float(np.interp(th, ANG, sal)) > 0.003:
                g = 1.0 - suave(re + 0.07, re + 0.11, r)
                d += Vector((0, -s * RECOLHE * fora_ * g * w_th, 0))
        return d
    if arcos:
        relatorio.append("caixas de roda redondas: %d vértices movidos" % deformar(campo_arco))

# ------------------------------------------------------------------------------------- face do para-choque da frente
# a barra do para-choque do Gol do Sketchfab tem 8 cm de altura e, embaixo dela, a chapa foge 11 cm para trás em rampa: de lado lia como
# um degrau. No Gol quadrado a face do para-choque é alta e reta, com a placa na metade de baixo (foto de referência: Gol GL 1991-94,
# odg.com.br). O campo empurra a parte de baixo da face até 1,2 cm atrás da barra, arredondando para baixo nos últimos 5,5 cm
if "--sem-face-para-choque" not in args and "bumper_front" in objs:
    bf = objs["bumper_front"]
    arv_b = arvore(["bumper_front"])
    Pb = np.array([list(bf.matrix_world @ v.co) for v in bf.data.vertices])
    z_fundo = float(Pb[:, 2].min())
    YS = np.arange(-0.70, 0.7001, 0.02)
    ZS = np.arange(z_fundo, 0.4451, 0.005)
    xbar = {}
    for y in YS:
        h = arv_b.ray_cast(Vector((3.0, y, 0.48)), Vector((-1, 0, 0)), 3.0)
        xbar[round(float(y), 2)] = h[0].x if h[0] is not None and h[1].x > 0.8 else None
    # no meio, o rebaixo da placa antiga: a barra de fora vale ali também
    fora_ = [x for y, x in xbar.items() if x is not None and 0.25 <= abs(y) <= 0.5]
    x_barra = float(np.median(fora_)) if fora_ else None
    PLACA_Y = 0.23
    for y in xbar:
        if abs(y) < PLACA_Y and x_barra is not None:
            xbar[y] = x_barra
    D = np.zeros((len(YS), len(ZS)))
    XC = np.zeros((len(YS), len(ZS)))
    XT = np.zeros((len(YS), len(ZS)))
    for i, y in enumerate(YS):
        xb = xbar[round(float(y), 2)]
        if xb is None:
            continue
        zs_ok, xc_ok = [], []
        for j, z in enumerate(ZS):
            h = arv_b.ray_cast(Vector((3.0, y, z)), Vector((-1, 0, 0)), 3.0)
            if h[0] is not None and h[1].x >= 0.25:
                zs_ok.append(z)
                xc_ok.append(h[0].x)
        if abs(y) < PLACA_Y:
            # atrás da placa antiga a face de baixo é a da fileira de fora (a do rebaixo é a parede do fundo)
            continue
        if len(zs_ok) < 3:
            continue
        XC[i] = np.interp(ZS, zs_ok, xc_ok)
        XT[i] = [xb - 0.012 - (0.07 * ((0.33 - z) / 0.055) ** 2 if z < 0.33 else 0.0) for z in ZS]
        D[i] = np.maximum(0.0, XT[i] - XC[i])
    # as fileiras do rebaixo copiam a fileira logo fora dele
    i_fora = [i for i, y in enumerate(YS) if abs(y) >= PLACA_Y and D[i].any()]
    for i, y in enumerate(YS):
        if abs(y) < PLACA_Y and i_fora:
            k = min(i_fora, key=lambda q: abs(abs(YS[q]) - PLACA_Y))
            D[i], XC[i], XT[i] = D[k], XC[k], XT[k]
    # suave entre fileiras e sumindo no canto (de 0,58 a 0,72 de y), para o canto não amassar
    w_y = np.array([1.0 - suave(0.58, 0.72, abs(y)) for y in YS])
    D = D * w_y[:, None]
    ker = np.array([1, 2, 3, 2, 1], float)
    ker /= ker.sum()
    Dp = np.pad(D, ((2, 2), (0, 0)), mode="edge")
    D = sum(ker[k] * Dp[k:k + len(YS)] for k in range(5))

    def campo_face(p):
        if not (z_fundo - 0.005 <= p.z <= 0.445 and abs(p.y) <= 0.70 and p.x > 1.5):
            return None
        i = int(round((p.y - YS[0]) / 0.02))
        j = int(round((min(p.z, ZS[-1]) - ZS[0]) / 0.005))
        i, j = min(max(i, 0), len(YS) - 1), min(max(j, 0), len(ZS) - 1)
        d = D[i, j]
        if d <= 0:
            return None
        s_ = suave(XC[i, j] - 0.22, XC[i, j], p.x)
        return Vector((min(d * s_, max(0.0, XT[i, j] - p.x)), 0, 0))
    # só o para-choque (a carroceria atrás dele fica onde está)
    mw_b, inv_b = bf.matrix_world, bf.matrix_world.inverted()
    n_mov = 0
    for v in bf.data.vertices:
        d = campo_face(mw_b @ v.co)
        if d is not None and d.length > 1e-6:
            v.co = inv_b @ ((mw_b @ v.co) + d)
            n_mov += 1
    bf.data.update()
    # as normais de canto do arquivo eram da rampa: o plástico preto passa a normais por ângulo
    with bpy.context.temp_override(object=bf, active_object=bf, selected_objects=[bf], selected_editable_objects=[bf]):
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    bf.data.shade_smooth()
    bmn = bmesh.new()
    bmn.from_mesh(bf.data)
    vivas = [False] * len(bf.data.edges)
    for e in bmn.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(30):
            vivas[e.index] = True
    bmn.free()
    at = bf.data.attributes.get("sharp_edge") or bf.data.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
    at.data.foreach_set("value", vivas)
    bf.data.update()
    arvores.pop("bumper_front", None)
    relatorio.append("face do para-choque da frente reta até z=%.2f: %d vértices (até %.0f cm para a frente)" % (z_fundo, n_mov, 100 * D.max()))

# ---------------------------------------------------------------------------------- chapa pintada no plano dos vidros
# o Gol traz, no plano da janela da porta, uma chapa pintada do corpo a 2 ou 3 mm do vidro (na esquerda na frente, na direita atrás):
# a janela saía vermelha. Some toda face pintada que fica a menos de 1,5 cm de um vidro, em cima dele (a reta até o vidro segue a
# normal do vidro: a chapa em volta da borda, que é a moldura, fica)
vidros = [o for n, o in objs.items() if n.startswith("glass_")]
if vidros:
    bmv = bmesh.new()
    for g in vidros:
        b = bmesh.new()
        b.from_mesh(g.data)
        b.transform(g.matrix_world)
        nomes_g = mat_names(g)
        fora = [f for f in b.faces if nomes_g[f.material_index] != "vidro"]
        bmesh.ops.delete(b, geom=fora, context="FACES")
        me_t = bpy.data.meshes.new("_v")
        b.to_mesh(me_t)
        bmv.from_mesh(me_t)
        bpy.data.meshes.remove(me_t)
        b.free()
    arv_v = BVHTree.FromBMesh(bmv)
    bmv.free()
    for nome, o in objs.items():
        if nome.startswith(("glass_", "wheel_", "hubcap_")):
            continue
        nomes_o = mat_names(o)
        if "pintura" not in nomes_o:
            continue
        mi_p = nomes_o.index("pintura")
        mw = o.matrix_world
        b = bmesh.new()
        b.from_mesh(o.data)
        tirar = []
        for f in b.faces:
            if f.material_index != mi_p:
                continue
            c = mw @ f.calc_center_median()
            loc, nrm, _, dist = arv_v.find_nearest(c, 0.015)
            if loc is None:
                continue
            d = c - loc
            if dist < 1e-5 or abs(d.normalized().dot(nrm)) > 0.94:
                tirar.append(f)
        if tirar:
            bmesh.ops.delete(b, geom=tirar, context="FACES")
            b.to_mesh(o.data)
            o.data.update()
            relatorio.append("%s: %d faces pintadas no plano dos vidros tiradas" % (nome, len(tirar)))
        b.free()
    arvores.clear()

# ---------------------------------------------------------------------------- vidro de duas faces (a de trás era chassi)
# a espessura do vidro (6 mm, carro_quebravel) saía com a face de trás em `chassi`, preto opaco: a janela parecia fumê fechado
# (o Felipe: "os vidros deveriam ser mais transparentes"). A face `chassi` paralela a uma face de vidro e logo atrás dela (até
# 1,2 cm, a reta até o vidro na normal dele) vira vidro; a borracha, na borda, fica
n_trocas = 0
for nome, o in objs.items():
    if not nome.startswith("glass_"):
        continue
    nomes_g = mat_names(o)
    if "vidro" not in nomes_g or "chassi" not in nomes_g:
        continue
    mi_v, mi_c = nomes_g.index("vidro"), nomes_g.index("chassi")
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    bv = b.copy()
    bmesh.ops.delete(bv, geom=[f for f in bv.faces if f.material_index != mi_v], context="FACES")
    arv_g = BVHTree.FromBMesh(bv)
    bv.free()
    trocar = []
    for f in b.faces:
        if f.material_index != mi_c:
            continue
        c = f.calc_center_median()
        loc, nrm, _, dist = arv_g.find_nearest(c, 0.012)
        if loc is None or abs(f.normal.dot(nrm)) < 0.9:
            continue
        if dist < 1e-5 or abs((c - loc).normalized().dot(nrm)) > 0.95:
            trocar.append(f.index)
    b.free()
    if trocar:
        for i in trocar:
            o.data.polygons[i].material_index = mi_v
        o.data.update()
        n_trocas += len(trocar)
        relatorio.append("%s: %d faces de trás do vidro passaram de chassi a vidro" % (nome, len(trocar)))

# ------------------------------------------------------------------------------------------------------- faróis e lanternas
def lanterna(w, sinal, box, m_preto, m_lente, segmentos=None, prof=0.03, e=0.008, frisos="vertical", m_refletor=None, m_lampada=None):
    """Moldura preta de `e` na boca do bolso, lente 4 mm à frente (segmentos em y com divisórias, cada um com o seu material),
    frisos de 1,5 mm na lente (a lente do jogo é opaca e brilhante: o relevo é o que lê como farol) e paredes para trás."""
    x0, x1, y0, y1, z0, z1 = box
    xf = x1 if sinal > 0 else x0
    Y0, Y1, Z0, Z1 = y0, y1, z0, z1
    w.ref = Vector((xf - sinal * 1.0, 0.5 * (y0 + y1), 0.5 * (z0 + z1)))
    ext = [(xf, Y0, Z0), (xf, Y1, Z0), (xf, Y1, Z1), (xf, Y0, Z1)]
    inn = [(xf, Y0 + e, Z0 + e), (xf, Y1 - e, Z0 + e), (xf, Y1 - e, Z1 - e), (xf, Y0 + e, Z1 - e)]
    for k in range(4):
        a, b = ext[k], ext[(k + 1) % 4]
        c, d = inn[(k + 1) % 4], inn[k]
        w.quad([a, b, c, d] if sinal > 0 else [d, c, b, a], m_preto)
    xl = xf + sinal * 0.004
    seg = segmentos or [(0.0, 1.0, m_lente)]
    ya0, ya1 = Y0 + e, Y1 - e
    for i, (u0, u1, m_seg) in enumerate(seg):
        ya, yb = ya0 + (ya1 - ya0) * u0, ya0 + (ya1 - ya0) * u1
        if i > 0:
            ya += 0.004
        if i < len(seg) - 1:
            yb -= 0.004
        p = [(xl, ya, Z0 + e), (xl, yb, Z0 + e), (xl, yb, Z1 - e), (xl, ya, Z1 - e)]
        w.quad(p if sinal > 0 else p[::-1], m_seg)
        # frisos da lente: barras de 1,5 mm, verticais no farol e horizontais na lanterna
        if frisos == "vertical":
            n_fr = max(2, int((yb - ya) / 0.022))
            for k in range(n_fr):
                yc = ya + (yb - ya) * (k + 0.5) / n_fr
                w.caixa((xl + sinal * 0.00075, yc, 0.5 * (Z0 + Z1)), 0.0015, 0.006, (Z1 - Z0 - 2 * e) * 0.9, m_seg)
        elif frisos == "horizontal":
            n_fr = max(2, int((Z1 - Z0 - 2 * e) / 0.02))
            for k in range(n_fr):
                zc = Z0 + e + (Z1 - Z0 - 2 * e) * (k + 0.5) / n_fr
                w.caixa((xl + sinal * 0.00075, 0.5 * (ya + yb), zc), 0.0015, (yb - ya) * 0.92, 0.005, m_seg)
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
    # paredes para trás, tapando o bolso; com refletor, as paredes e o fundo são cromados e o fundo é uma pirâmide rasa (a lente de
    # vidro do farol deixa ver o refletor, como num farol de verdade) com a lâmpada no meio
    xb = xf - sinal * prof
    m_par = m_refletor if m_refletor is not None else m_preto
    paredes = [((xf, Y0, Z0), (xf, Y1, Z0), (xb, Y1, Z0), (xb, Y0, Z0)), ((xf, Y1, Z1), (xf, Y0, Z1), (xb, Y0, Z1), (xb, Y1, Z1)),
               ((xf, Y0, Z1), (xf, Y0, Z0), (xb, Y0, Z0), (xb, Y0, Z1)), ((xf, Y1, Z0), (xf, Y1, Z1), (xb, Y1, Z1), (xb, Y1, Z0))]
    for p in paredes:
        w.quad(list(p) if sinal > 0 else list(p)[::-1], m_par)
    if m_refletor is None:
        p = ((xb, Y0, Z0), (xb, Y1, Z0), (xb, Y1, Z1), (xb, Y0, Z1))
        w.quad(list(p) if sinal > 0 else list(p)[::-1], m_preto)
    else:
        # um refletor por segmento (a lanterna tem três; o farol, um)
        for (u0, u1, _m) in (segmentos or [(0.0, 1.0, None)]):
            ya, yb = Y0 + (Y1 - Y0) * u0, Y0 + (Y1 - Y0) * u1
            c = Vector((xb - sinal * min(0.035, 0.45 * min(yb - ya, Z1 - Z0)), 0.5 * (ya + yb), 0.5 * (Z0 + Z1)))
            cantos = [Vector((xb, ya, Z0)), Vector((xb, yb, Z0)), Vector((xb, yb, Z1)), Vector((xb, ya, Z1))]
            for k in range(4):
                w.quad([cantos[k], cantos[(k + 1) % 4], c], m_refletor, ref=c + Vector((sinal * 1.0, 0, 0)) * -1.0)
            if m_lampada is not None:
                w.caixa(c + Vector((sinal * 0.018, 0, 0)), 0.024, 0.016, 0.016, m_lampada)


for nome, sinal in (("headlight_left", 1), ("headlight_right", 1), ("taillight_left", -1), ("taillight_right", -1)):
    o = objs.get(nome)
    if not o:
        continue
    box, nrm = faces_de(o, "luz")
    if box is None:
        continue
    w = Escritor(o, refazer=("luz", "pintura", "cromado"))
    m_preto, m_lente = slot(o, "chassi"), slot(o, "luz")
    m_ref = slot(o, "refletor")
    esq = "left" in nome
    if sinal > 0:
        # farol de vidro (29/10, "lanternas e sinaleiras mais realistas"): a lente é vidro transparente com frisos, e atrás dela o
        # refletor cromado e a lâmpada
        m_vidro = slot(o, "vidro")
        lanterna(w, sinal, box, m_preto, m_vidro, None, prof=0.045, frisos="vertical", m_refletor=m_ref, m_lampada=m_lente)
        w.fechar()
        relatorio.append("%s: farol de vidro com refletor, lente %.0fx%.0f cm" % (nome, (box[3] - box[2]) * 100, (box[5] - box[4]) * 100))
        continue
    if sinal < 0:
        # lanterna: ré (branca) perto do centro, seta (âmbar) no meio, freio (vermelha) na ponta
        m_amb, m_bra, m_ver = slot(o, "luz_ambar"), slot(o, "luz_branca"), slot(o, "luz_vermelha")
        seg = [(0.0, 0.3, m_bra), (0.3, 0.55, m_amb), (0.55, 1.0, m_ver)] if not esq else \
              [(0.0, 0.45, m_ver), (0.45, 0.7, m_amb), (0.7, 1.0, m_bra)]
    else:
        seg = None
    lanterna(w, sinal, box, m_preto, m_lente, seg, frisos="horizontal", m_refletor=m_ref)
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
        w.ref = Vector((xf - 1.0, 0.5 * (y0 + y1), 0.5 * (z0 + z1)))
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
    w.ref = Vector((cx, 0.5 * (ya + yb), cz))
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
        w.ref = c + Vector((0, 0.5, 0))
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
                w.ref = base + Vector((0, 0, 0.5 * (z0_ + z1_)))
                a0 = [base + Vector((r * math.cos(a), r * math.sin(a), z0_)) for a in ang]
                a1 = [base + Vector((r * math.cos(a), r * math.sin(a), z1_)) for a in ang]
                for i in range(8):
                    w.quad([a0[i], a0[(i + 1) % 8], a1[(i + 1) % 8], a1[i]], m, suave=True)
                w.quad(a1, m)
            relatorio.append("antena em x=%.2f y=%.2f z=%.2f" % (base.x, base.y, base.z))
    w.fechar()

# ------------------------------------------------------------------------------------------------------------ placas
# a placa vinha como chapa pintada (saía na cor do carro): o retângulo da frente vira o material `placa` (no Detonauto,
# MI_DNPlacaCoupe), com moldura preta de 1 cm e dois parafusos. Em branco, sem letras: placa real é proibida
# a da frente é refeita: no modelo era uma chapa de 40 x 10 cm (achatada) presa a um suporte 10 cm fundo, mais uma folha solta da
# carroceria logo abaixo (o "bloco escuro" embaixo da placa). No Gol quadrado a placa (40 x 13 cm, o tamanho brasileiro) fica no meio
# da face do para-choque, na metade de baixo, sobre um suporte preto rente à face
PLACA_L, PLACA_A, PLACA_Z0 = 0.40, 0.13, opt("--z-placa", 0.355)
placa_frente = None
if "plate_front" in objs and "--placa-original" not in args:
    o = objs["plate_front"]
    yc, z0p, z1p = 0.0, PLACA_Z0, PLACA_Z0 + PLACA_A
    # a folha solta da carroceria na frente do para-choque, onde ficava a parte de baixo da placa antiga
    if "body" in objs:
        bo = objs["body"]
        bmb = bmesh.new()
        bmb.from_mesh(bo.data)
        mwb = bo.matrix_world
        soltas = [f for f in bmb.faces if all((lambda q: q.x > 1.94 and abs(q.y) < 0.21 and 0.36 < q.z < 0.445)(mwb @ v.co) for v in f.verts)]
        if soltas:
            bmesh.ops.delete(bmb, geom=soltas, context="FACES")
            bmb.to_mesh(bo.data)
            bo.data.update()
            relatorio.append("folha solta embaixo da placa da frente: %d faces fora" % len(soltas))
        bmb.free()
    # o rebaixo da placa antiga no para-choque (a caixa da peça antiga), a face de baixo atrás da placa nova e a barra fora do rebaixo
    Pp = np.array([list(o.matrix_world @ v.co) for v in o.data.vertices])
    reb = (Pp[:, 1].min(), Pp[:, 1].max(), Pp[:, 2].min(), Pp[:, 2].max())
    xs_face, xs_barra = [], []
    for yy in (-0.15, 0.0, 0.15):
        for zz in np.arange(z0p, z1p + 0.001, 0.01):
            h = raio(["bumper_front"], (3.0, yy, zz), (-1, 0, 0), 4.0)
            if h:
                xs_face.append(h[0].x)
    for yy in (-0.35, -0.3, 0.3, 0.35):
        h = raio(["bumper_front"], (3.0, yy, 0.48), (-1, 0, 0), 4.0)
        if h:
            xs_barra.append(h[0].x)
    if xs_face and xs_barra:
        x_atras, x_frente = min(xs_face), max(xs_barra)
        xp = x_frente + 0.008
        w = Escritor(o, refazer=set(mat_names(o)))
        m_preto, mi_placa = slot(o, "chassi"), slot(o, "placa")
        zc = 0.5 * (z0p + z1p)
        # suporte preto do fundo da face até 3 mm atrás da placa, 5 mm maior que ela em volta e tapando o rebaixo da placa antiga
        sy0, sy1 = min(yc - PLACA_L / 2 - 0.005, reb[0]), max(yc + PLACA_L / 2 + 0.005, reb[1])
        sz0, sz1 = min(z0p - 0.005, reb[2]), max(z1p + 0.005, reb[3] + 0.003)
        w.caixa(((x_atras - 0.01 + xp - 0.003) / 2, 0.5 * (sy0 + sy1), 0.5 * (sz0 + sz1)), xp - 0.003 - (x_atras - 0.01), sy1 - sy0, sz1 - sz0, m_preto)
        # a placa: chapa de 3 mm, em branco (placa real é proibida)
        w.caixa((xp - 0.0015, yc, zc), 0.003, PLACA_L, PLACA_A, mi_placa)
        # moldura de 1 cm e dois parafusos
        w.ref = Vector((xp - 1.0, yc, zc))
        e, xf = 0.010, xp + 0.001
        y0p, y1p = yc - PLACA_L / 2, yc + PLACA_L / 2
        ext = [(xf, y0p - 0.003, z0p - 0.003), (xf, y1p + 0.003, z0p - 0.003), (xf, y1p + 0.003, z1p + 0.003), (xf, y0p - 0.003, z1p + 0.003)]
        inn = [(xf, y0p + e, z0p + e), (xf, y1p - e, z0p + e), (xf, y1p - e, z1p - e), (xf, y0p + e, z1p - e)]
        for k in range(4):
            w.quad([ext[k], ext[(k + 1) % 4], inn[(k + 1) % 4], inn[k]], m_preto)
        w.ref = None
        for yy in (y0p + 0.25 * PLACA_L, y0p + 0.75 * PLACA_L):
            w.caixa((xf + 0.002, yy, z1p - 0.022), 0.004, 0.012, 0.012, m_preto)
        w.fechar(normais_por_angulo=True)
        placa_frente = (xp, y0p - 0.005, y1p + 0.005, z0p - 0.005, z1p + 0.005)
        relatorio.append("plate_front refeita: placa %.0f x %.0f cm em z %.3f-%.3f, %.1f cm à frente da face (suporte preto)" % (
            100 * PLACA_L, 100 * PLACA_A, z0p, z1p, 100 * (xp - x_atras)))

for nome, sinal in (("plate_front", 1), ("plate_rear", -1)):
    if nome == "plate_front" and placa_frente:
        continue
    o = objs.get(nome)
    if not o:
        continue
    nomes = mat_names(o)
    if "pintura" not in nomes:
        continue
    mi_p = nomes.index("pintura")
    mw = o.matrix_world
    # a face da placa: as faces pintadas que olham para fora (frente ou trás) mais à frente
    caras = [p for p in o.data.polygons if p.material_index == mi_p and (mw.to_3x3() @ p.normal).x * sinal > 0.8]
    if not caras:
        continue
    xs = [(mw @ p.center).x for p in caras]
    x_face = max(xs) if sinal > 0 else min(xs)
    caras = [p for p in caras if abs((mw @ p.center).x - x_face) < 0.008]
    P = np.array([list(mw @ o.data.vertices[v].co) for p in caras for v in p.vertices])
    y0, y1, z0, z1 = P[:, 1].min(), P[:, 1].max(), P[:, 2].min(), P[:, 2].max()
    mi_placa = slot(o, "placa")
    m_preto = slot(o, "chassi")
    for p in o.data.polygons:
        if p.material_index == mi_p:
            p.material_index = m_preto        # o resto (bordas, fundo do suporte) fica preto
    for p in caras:
        p.material_index = mi_placa
    o.data.update()
    w = Escritor(o)
    w.ref = Vector((x_face - sinal * 1.0, 0.5 * (y0 + y1), 0.5 * (z0 + z1)))
    xf = x_face + sinal * 0.002
    e = 0.010
    ext = [(xf, y0 - 0.004, z0 - 0.004), (xf, y1 + 0.004, z0 - 0.004), (xf, y1 + 0.004, z1 + 0.004), (xf, y0 - 0.004, z1 + 0.004)]
    inn = [(xf, y0 + e, z0 + e), (xf, y1 - e, z0 + e), (xf, y1 - e, z1 - e), (xf, y0 + e, z1 - e)]
    for k in range(4):
        w.quad([ext[k], ext[(k + 1) % 4], inn[(k + 1) % 4], inn[k]], m_preto)
    for yy in (y0 + 0.25 * (y1 - y0), y0 + 0.75 * (y1 - y0)):
        w.caixa((xf + sinal * 0.002, yy, z1 - 0.022), 0.004, 0.012, 0.012, m_preto)
    w.fechar()
    relatorio.append("%s: placa %.0fx%.0f cm em branco, com moldura" % (nome, (y1 - y0) * 100, (z1 - z0) * 100))

# ------------------------------------------------------------------------------------------- para-choques pretos
if "--para-choque-pintado" not in args:
    for nome in ("bumper_front", "bumper_rear"):
        o = objs.get(nome)
        if not o:
            continue
        nomes = mat_names(o)
        if "pintura" not in nomes:
            continue
        mi_p, mi_c = nomes.index("pintura"), slot(o, "chassi")
        n = 0
        for p in o.data.polygons:
            if p.material_index == mi_p:
                p.material_index = mi_c
                n += 1
        o.data.update()
        relatorio.append("%s: plástico preto (%d faces; --para-choque-pintado mantém a cor do carro)" % (nome, n))
        # retalhos de chapa pintada da carroceria dentro do volume do para-choque (tampas de farol de milha, vincos) ficam pretos
        # também; a moldura da placa (no meio) continua pintada
        body = objs.get("body")
        bb, _ = faces_de(o, "chassi")
        placa = objs.get("plate_front" if nome == "bumper_front" else "plate_rear")
        pb = faces_de(placa, "pintura")[0] if placa else None
        if body and bb:
            nb = mat_names(body)
            if "pintura" in nb:
                mi_p, mi_c = nb.index("pintura"), slot(body, "chassi")
                mw = body.matrix_world
                vs = body.data.vertices
                k = 0
                for p in body.data.polygons:
                    if p.material_index != mi_p:
                        continue
                    # só a face inteira dentro do volume (e 1,5 cm abaixo do topo do para-choque): a que atravessa a borda de
                    # cima é a chapa que aparece acima dele e fica pintada, sem serrote
                    if all((lambda q: bb[0] - 0.01 <= q.x <= bb[1] + 0.01 and bb[2] - 0.01 <= q.y <= bb[3] + 0.01 and bb[4] - 0.01 <= q.z <= bb[5] - 0.015)(mw @ vs[vi].co) for vi in p.vertices):
                        p.material_index = mi_c
                        k += 1
                body.data.update()
                if k:
                    relatorio.append("  + %d faces da carroceria dentro do %s" % (k, nome))

# ----------------------------------------------------------------------------------------------- faixa dos para-choques
if "--sem-faixa" not in args:
    perfil = perfil_arredondado(0.006, 0.03, 0.002)
    for nome, sinal in (("bumper_front", 1), ("bumper_rear", -1)):
        o = objs.get(nome)
        if not o:
            continue
        placa = objs.get("plate_front" if sinal > 0 else "plate_rear")
        pbox = faces_de(placa, "pintura")[0] if placa else None
        if sinal > 0 and placa_frente:
            pbox = [placa_frente[0], placa_frente[0], placa_frente[1], placa_frente[2], placa_frente[3], placa_frente[4]]
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

# ------------------------------------------------------------------------------------------------------ quebra-vento
# no Gol o triângulo entre a janela da porta e a coluna A é o vidro do quebra-vento; o modelo trazia chapa pintada ali (o Felipe
# viu "o vidro perto do retrovisor pintado", 29/10). A chapa é cortada por três planos (frente da janela da porta, a coluna A
# paralela à borda do para-brisa e a cintura) e por outros três 1,2 cm para dentro: o miolo vira vidro, o anel vira borracha
if "--sem-quebra-vento" not in args and "body" in objs:
    o = objs["body"]
    nomes = mat_names(o)
    mi_p, mi_v, mi_c = nomes.index("pintura"), slot(o, "vidro"), slot(o, "chassi")
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    # a borda da coluna A: o maior x da chapa pintada por faixa de altura, ajustado por uma reta x = a + b z
    zs_, xs_ = [], []
    for zc in np.arange(0.93, 1.27, 0.03):
        xm = max(((mw @ p.center).x for p in o.data.polygons if p.material_index == mi_p and (mw @ p.center).y > 0.3
                  and abs((mw @ p.center).z - zc) < 0.015 and 0.2 < (mw @ p.center).x < 0.9), default=None)
        if xm is not None:
            zs_.append(zc)
            xs_.append(xm)
    if len(zs_) >= 4:
        b_, a_ = np.polyfit(zs_, xs_, 1)
        LARG_COLUNA, X_JANELA, Z_BAIXO, E = 0.085, 0.245, 0.935, 0.012
        a_col = a_ - LARG_COLUNA * np.sqrt(1 + b_ * b_)
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.transform(mw)

        def regiao(f, s):
            c = f.calc_center_median()
            return (f.material_index == mi_p and c.y * s > 0.3 and 0.18 < c.x < 0.9 and 0.9 < c.z < 1.32 and f.normal.y * s > 0.4)
        n_vidro = 0
        for s in (1, -1):
            planos = [((X_JANELA, 0, 0), (1, 0, 0)), ((a_col, 0, 0), (1, 0, -b_)), ((0, 0, Z_BAIXO), (0, 0, 1)),
                      ((X_JANELA + E, 0, 0), (1, 0, 0)), ((a_col - E * np.sqrt(1 + b_ * b_), 0, 0), (1, 0, -b_)),
                      ((0, 0, Z_BAIXO + E), (0, 0, 1))]
            for co, no in planos:
                faces = [f for f in bm.faces if regiao(f, s)]
                geom = list({v for f in faces for v in f.verts}) + list({e for f in faces for e in f.edges}) + faces
                bmesh.ops.bisect_plane(bm, geom=geom, plane_co=Vector(co), plane_no=Vector(no).normalized(), clear_inner=False, clear_outer=False)
            for f in bm.faces:
                if not regiao(f, s):
                    continue
                c = f.calc_center_median()
                dentro = c.x > X_JANELA and c.z > Z_BAIXO and c.x < a_col + b_ * c.z
                if not dentro:
                    continue
                miolo = c.x > X_JANELA + E and c.z > Z_BAIXO + E and c.x < a_col - E * np.sqrt(1 + b_ * b_) + b_ * c.z
                f.material_index = mi_v if miolo else mi_c
                n_vidro += int(miolo)
        bm.transform(inv)
        bm.to_mesh(o.data)
        o.data.update()
        relatorio.append("quebra-vento: %d faces de vidro nos dois lados (coluna A: x = %.3f %+.3f z)" % (n_vidro, a_col, b_))

# --------------------------------------------------------------------------------------- sinaleiras no para-choque
# pisca âmbar nas pontas da barra do para-choque da frente (Gol quadrado com pisca no para-choque)
if "--sem-sinaleira" not in args and "bumper_front" in objs:
    o = objs["bumper_front"]
    w = Escritor(o)
    m_preto, m_amb = slot(o, "chassi"), slot(o, "luz_ambar")
    n = 0
    for s in (1, -1):
        y0, y1, z0, z1 = 0.53, 0.65, 0.462, 0.514
        h = raio(["bumper_front"], (3.0, s * 0.5 * (y0 + y1), 0.5 * (z0 + z1)), (-1, 0, 0), 4.0)
        if not h:
            continue
        xf = h[0].x
        w.caixa((xf + 0.004, s * 0.5 * (y0 + y1), 0.5 * (z0 + z1)), 0.008, y1 - y0 + 0.008, z1 - z0 + 0.008, m_preto)
        w.caixa((xf + 0.009, s * 0.5 * (y0 + y1), 0.5 * (z0 + z1)), 0.004, y1 - y0, z1 - z0, m_amb)
        for k in range(5):
            w.caixa((xf + 0.0115, s * (y0 + (y1 - y0) * (k + 0.5) / 5), 0.5 * (z0 + z1)), 0.0015, 0.004, (z1 - z0) * 0.9, m_amb)
        n += 1
    w.fechar()
    relatorio.append("sinaleiras âmbar no para-choque: %d" % n)

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[detalhes_na_casca]", linha)
