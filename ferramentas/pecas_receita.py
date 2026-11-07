"""
Peças da receita do carro, fase P3 (Detonauto docs/personalizar-carro.md, aprovado pelo Felipe em 07/11/2026): aerofólio, para-choques
dianteiro e traseiro e saias laterais, 3 ou 4 opções por encaixe, geradas por script a partir do corte de cada carro (sem marca, sem
nome de fabricante). CC0, feitas no acervo.

Cada variante sai como um objeto "<peça>__<variante>" no espaço do corte (nos para-choques, só o acréscimo; o Detonauto soma a peça de
fábrica na montagem) (frente +X, esquerda +Y, cima +Z, metros), com os materiais do
corte ("pintura" e "chassi"), num GLB por carro. No Detonauto, o kit_names.py leva cada uma para SK_DN<Modelo>_<Peça>_<variante>: a
variante do para-choque e o aerofólio são a mesma peça do kit de quebra (soltam e voam como a de fábrica); a saia fica presa à carroceria
e amassa com ela pelo material.

    python -I ferramentas/pecas_receita.py -- --id gol-quadrado [--glb <corte.glb>] [--out veiculos/sketchfab/pecas] [--previa]

Peças:
  spoiler__labio, spoiler__medio, spoiler__alto          (sem aerofólio = não ter a peça)
  bumper_front__lip, bumper_front__esportivo, bumper_front__tubo (tubo só em jipe e picape)
  bumper_rear__difusor, bumper_rear__esportivo
  saia__lisa, saia__esportiva                            (as duas saias num objeto só)
  hood__tomada                                           (fase P4; fora o Besouro; a fibra o Detonauto deriva do capô de fábrica)
  escapamento__duplo, escapamento__central               (fase P4; presos à carroceria, como a saia)
  teto__solar, teto__bagageiro                           (fase P4; sem bagageiro no Furgãozinho e no Pão de Forma)
  retrovisor__cromado, retrovisor__preto                 (fase P4; a capa por cima da concha de fábrica)
  grade__tela, grade__barras                             (fase P4; só nos carros com a grade como peça do corte)
"""
import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, ".."))

# carros sem aerofólio (o furgão, o jipe com o estepe na tampa, a picape com caçamba) e os que levam o para-choque de tubo
SEM_AEROFOLIO = {"furgao-classico", "jipe-capota", "tropeiro"}
COM_TUBO = {"jipe-capota", "tropeiro"}
# sem a tomada de ar no capô: o Besouro (o "capô" é a tampa do porta-malas da frente; leva só a fibra)
SEM_TOMADA = {"besouro"}
# o teto: o Furgãozinho já tem bagageiro de fábrica e o Pão de Forma não leva; o jipe de capota mole e a picape ficam sem solar
SEM_BAGAGEIRO = {"furgaozinho", "furgao-classico"}
SEM_SOLAR = {"jipe-capota", "furgao-classico"}


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"out": os.path.join(RAIZ, "veiculos", "sketchfab", "pecas"), "previa": False}
    i = 0
    while i < len(a):
        if a[i] == "--previa":
            out["previa"] = True
            i += 1
        else:
            out[a[i][2:]] = a[i + 1]
            i += 2
    return out


# ------------------------------------------------------------------------------------------------------------------ malha simples

class Peca:
    """Vértices e quads com o material de cada um (sem bpy, como o Malha do rodas_kit)."""

    def __init__(self):
        self.v = []
        self.f = []

    def caixa(self, mn, mx, mat):
        """Caixa alinhada aos eixos."""
        x0, y0, z0 = mn
        x1, y1, z1 = mx
        b = len(self.v)
        self.v += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)):
            self.f.append(([b + k for k in q], mat))

    def perfil_y(self, perfil, y0, y1, mat, tampa=True):
        """Extruda ao longo de Y um perfil fechado no plano XZ [(x, z), ...] (anti-horário visto de +Y)."""
        b = len(self.v)
        n = len(perfil)
        for y in (y0, y1):
            for x, z in perfil:
                self.v.append((x, y, z))
        for k in range(n):
            a, c = k, (k + 1) % n
            self.f.append(([b + a, b + c, b + n + c, b + n + a], mat))
        if tampa:
            self.f.append(([b + k for k in reversed(range(n))], mat))
            self.f.append(([b + n + k for k in range(n)], mat))

    def fita_x(self, pontos, mat):
        """Faixa extrudada ao longo de X por uma lista de seções [(x, [(y, z), ...] fechada)], todas com o mesmo número de pontos."""
        b = len(self.v)
        n = len(pontos[0][1])
        for x, sec in pontos:
            for y, z in sec:
                self.v.append((x, y, z))
        for s in range(len(pontos) - 1):
            for k in range(n):
                a, c = k, (k + 1) % n
                i0, i1 = b + s * n, b + (s + 1) * n
                self.f.append(([i0 + a, i1 + a, i1 + c, i0 + c], mat))
        self.f.append(([b + k for k in range(n)], mat))
        last = b + (len(pontos) - 1) * n
        self.f.append(([last + k for k in reversed(range(n))], mat))

    def fita_y(self, secoes, mat):
        """Como fita_x, mas as seções andam ao longo de Y: [(y, [(x, z), ...] fechada)]."""
        b = len(self.v)
        n = len(secoes[0][1])
        for y, sec in secoes:
            for x, z in sec:
                self.v.append((x, y, z))
        for s in range(len(secoes) - 1):
            for k in range(n):
                a, c = k, (k + 1) % n
                i0, i1 = b + s * n, b + (s + 1) * n
                self.f.append(([i0 + a, i0 + c, i1 + c, i1 + a], mat))
        self.f.append(([b + k for k in reversed(range(n))], mat))
        last = b + (len(secoes) - 1) * n
        self.f.append(([last + k for k in range(n)], mat))

    def tubo_x(self, p0, p1, raio, mat, lados=10):
        """Tubo reto de p0 a p1 (cilindro com tampas)."""
        ax = [p1[i] - p0[i] for i in range(3)]
        L = math.sqrt(sum(c * c for c in ax)) or 1.0
        ax = [c / L for c in ax]
        ref = (0.0, 0.0, 1.0) if abs(ax[2]) < 0.9 else (1.0, 0.0, 0.0)
        u = [ax[1] * ref[2] - ax[2] * ref[1], ax[2] * ref[0] - ax[0] * ref[2], ax[0] * ref[1] - ax[1] * ref[0]]
        lu = math.sqrt(sum(c * c for c in u))
        u = [c / lu for c in u]
        w = [ax[1] * u[2] - ax[2] * u[1], ax[2] * u[0] - ax[0] * u[2], ax[0] * u[1] - ax[1] * u[0]]
        b = len(self.v)
        for p in (p0, p1):
            for k in range(lados):
                t = 2 * math.pi * k / lados
                self.v.append(tuple(p[i] + raio * (math.cos(t) * u[i] + math.sin(t) * w[i]) for i in range(3)))
        for k in range(lados):
            a, c = k, (k + 1) % lados
            self.f.append(([b + a, b + c, b + lados + c, b + lados + a], mat))
        self.f.append(([b + k for k in reversed(range(lados))], mat))
        self.f.append(([b + lados + k for k in range(lados)], mat))


def aerofolio(asa_perfil_corda, espessura, x_meio, z, meia_larg):
    """Perfil de asa (gota achatada) no plano XZ, a parte grossa na frente (+X), a borda de fuga atrás (-X)."""
    c = asa_perfil_corda
    pts = []
    for k in range(9):
        t = k / 8.0
        x = x_meio + c * 0.5 - c * t
        h = espessura * (1.6 * math.sqrt(max(t, 0.0)) - 1.6 * t) * 1.8
        pts.append((x, z + 0.25 * espessura + h))
    for k in range(7, 0, -1):
        t = k / 8.0
        x = x_meio + c * 0.5 - c * t
        h = espessura * (1.6 * math.sqrt(t) - 1.6 * t) * 0.5
        pts.append((x, z - h))
    return pts


# ------------------------------------------------------------------------------------------------------------------ geração

def gerar(idc, glb, out_dir, previa):
    import bpy
    import bmesh
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(glb))
    objs = {o.name.split(".")[0]: o for o in bpy.data.objects if o.type == "MESH" and not o.name.endswith("_LOD1")}
    mats = {m.name.split(".")[0]: m for m in bpy.data.materials}
    pintura = mats.get("pintura")
    chassi = mats.get("chassi") or mats.get("MI_DNChassi")
    if pintura is None or chassi is None:
        raise RuntimeError("%s: o corte não tem os materiais pintura e chassi" % idc)
    # fase P4: as ponteiras e as capas dos retrovisores em cromo, o teto solar em vidro (sem eles no corte, o chassi)
    cromo = mats.get("cromado") or mats.get("cromo") or chassi
    vidro = mats.get("vidro") or chassi
    ORDEM = ("pintura", "chassi", "cromo", "vidro")
    mapa = json.load(open(os.path.join(os.path.dirname(glb), idc + "_mapa.json"), encoding="utf-8"))

    def pontos(o):
        return [o.matrix_world @ v.co for v in o.data.vertices]

    def caixa_de(o):
        ps = pontos(o)
        return [min(p[i] for p in ps) for i in range(3)], [max(p[i] for p in ps) for i in range(3)]

    # BVH da carroceria e das peças (sem rodas, vidros e lentes) para assentar o que entra por cima
    corpo = [o for n, o in objs.items() if not n.startswith(("wheel_", "hubcap_", "glass_", "headlight", "taillight", "plate_"))]
    verts, polys = [], []
    for o in corpo:
        b = len(verts)
        verts += pontos(o)
        polys += [[b + i for i in p.vertices] for p in o.data.polygons]
    bvh = BVHTree.FromPolygons(verts, polys)

    def chao_em(x, y, z_de_cima):
        hit = bvh.ray_cast(Vector((x, y, z_de_cima)), Vector((0, 0, -1)), 3.0)
        return hit[0].z if hit[0] is not None else None

    def lado_em(x, z, de_fora=1.5):
        hit = bvh.ray_cast(Vector((x, de_fora, z)), Vector((0, -1, 0)), 3.0)
        return hit[0].y if hit[0] is not None else None

    cria = []

    def objeto(nome, peca, base=None, chanfro=True):
        me = bpy.data.meshes.new(nome)
        me.from_pydata(peca.v, [], [f for f, _ in peca.f])
        usados = [m for m in ORDEM if any(mat == m for _, mat in peca.f)]
        for m in usados:
            me.materials.append({"pintura": pintura, "chassi": chassi, "cromo": cromo, "vidro": vidro}[m])
        for poly, (_, mat) in zip(me.polygons, peca.f):
            poly.material_index = usados.index(mat)
        me.validate()
        me.update()
        ob = bpy.data.objects.new(nome, me)
        bpy.context.scene.collection.objects.link(ob)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0002)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        # chanfro de 3 mm nas quinas vivas: a peça de plástico injetado ou de fibra nunca tem aresta de faca (com ela, a caixa lia como
        # protótipo); só nas arestas de ângulo fechado, para o perfil curvo da asa não dobrar de número
        vivas = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(50)] if chanfro else []
        if vivas:
            bmesh.ops.bevel(bm, geom=vivas, offset=0.003, segments=2, affect="EDGES", profile=0.5)
        bm.to_mesh(ob.data)
        bm.free()
        # a variante do para-choque leva só o acréscimo: o Detonauto (Tools/Blender/juntar_pecas_receita.py) soma a peça de fábrica na
        # montagem; copiada aqui, cada variante pesava 17 mil triângulos no GLB do acervo
        for p in ob.data.polygons:
            p.use_smooth = False
        cria.append(ob)
        return ob

    rodas = mapa.get("rodas") or []
    if not rodas:
        # cortes com as rodas como peças do mapa (take "roda"), como na prévia do carro
        rodas = [{"cx": p["centro"][0], "cz": p["centro"][2]} for p in mapa.get("parts", [])
                 if p.get("take") == "roda" and p.get("papel") == "wheel" and p.get("centro")]
    raio = max([r.get("cz", 0.3) for r in rodas] or [0.3])
    eixo_f = max([r.get("cx", 1.2) for r in rodas] or [1.2])
    eixo_t = min([r.get("cx", -1.2) for r in rodas] or [-1.2])

    # --- aerofólio: na borda de trás da tampa, assentado nela por raios
    if "trunk" in objs and idc not in SEM_AEROFOLIO:
        mn, mx = caixa_de(objs["trunk"])
        W = (mx[1] - mn[1]) * 0.92
        x_borda = mn[0] + 0.035
        z_borda = chao_em(x_borda, 0.0, mx[2] + 0.5) or mx[2]
        lab = Peca()
        lab.perfil_y([(x_borda + 0.05, z_borda - 0.002), (x_borda - 0.035, z_borda - 0.002), (x_borda - 0.035, z_borda + 0.028)], -W / 2, W / 2,
                     "pintura")
        objeto("spoiler__labio", lab)
        for nome, alt, corda, esp, placa in (("medio", 0.085, 0.20, 0.022, 0.045), ("alto", 0.17, 0.22, 0.026, 0.07)):
            p = Peca()
            x_asa = x_borda + 0.02
            z_asa = z_borda + alt
            p.perfil_y(aerofolio(corda, esp, x_asa, z_asa, W / 2), -W / 2, W / 2, "pintura")
            for y in (-W * 0.30, W * 0.30):
                zb = chao_em(x_asa, y, mx[2] + 0.5) or z_borda
                p.caixa((x_asa - 0.035, y - 0.016, zb - 0.004), (x_asa + 0.035, y + 0.016, z_asa + 0.004), "chassi")
            for y in (-W / 2, W / 2):
                s = 1 if y > 0 else -1
                p.caixa((x_asa - corda * 0.55, y - 0.004 * s - (0.004 if s > 0 else 0), z_asa - placa * 0.45),
                        (x_asa + corda * 0.45, y + (0.004 if s > 0 else 0.004), z_asa + placa * 0.55), "chassi")
            objeto("spoiler__" + nome, p)

    # --- para-choques: os acréscimos seguem o contorno de baixo da peça de fábrica, por raios de fora para dentro em fatias de Y (com
    # caixas retas, a saia de ar e a extensão saíam como tábuas que passavam dos cantos curvos do para-choque)
    def contorno(o, frente):
        mn, mx = caixa_de(o)
        W = mx[1] - mn[1]
        z = mn[2] + 0.02
        sinal = 1.0 if frente else -1.0
        x_ini = (mx[0] + 0.5) if frente else (mn[0] - 0.5)
        fatias = []
        n = 15
        for k in range(n):
            y = -W * 0.47 + W * 0.94 * k / (n - 1)
            hit = bvh.ray_cast(Vector((x_ini, y, z)), Vector((-sinal, 0, 0)), 1.0)
            if hit[0] is not None:
                fatias.append((y, hit[0].x))
        return fatias, mn[2], sinal

    def acrescimo(fatias, sinal, perfil):
        """perfil(xf) -> [(x, z), ...] fechado, com xf a face da peça naquela fatia; devolve as seções da fita."""
        return [(y, perfil(xf)) for y, xf in fatias]

    if "bumper_front" in objs:
        bf = objs["bumper_front"]
        fatias, zb, sg = contorno(bf, True)
        mn, mx = caixa_de(bf)
        W = mx[1] - mn[1]
        if len(fatias) >= 3:
            lip = Peca()
            lip.fita_y(acrescimo(fatias, sg, lambda xf: [(xf - 0.12, zb - 0.010), (xf + 0.03, zb - 0.010), (xf + 0.03, zb - 0.002),
                                                          (xf - 0.12, zb - 0.002)]), "chassi")
            objeto("bumper_front__lip", lip)
            esp = Peca()
            # a saia de ar pintada com o caimento para trás e a lâmina preta embaixo, os dois no contorno
            esp.fita_y(acrescimo(fatias, sg, lambda xf: [(xf - 0.11, zb + 0.012), (xf - 0.004, zb + 0.012), (xf - 0.018, zb - 0.052),
                                                          (xf - 0.11, zb - 0.052)]), "pintura")
            esp.fita_y(acrescimo(fatias, sg, lambda xf: [(xf - 0.12, zb - 0.062), (xf + 0.012, zb - 0.062), (xf + 0.012, zb - 0.052),
                                                          (xf - 0.12, zb - 0.052)]), "chassi")
            # duas tomadas escuras na frente da saia de ar
            for y_c in (-W * 0.28, W * 0.28):
                xf = min(fatias, key=lambda f: abs(f[0] - y_c))[1]
                esp.caixa((xf - 0.022, y_c - 0.08, zb - 0.040), (xf - 0.008, y_c + 0.08, zb - 0.010), "chassi")
            objeto("bumper_front__esportivo", esp)
        if idc in COM_TUBO:
            t = Peca()
            xf = mx[0] + 0.07
            zm = (mn[2] + mx[2]) / 2
            t.tubo_x((xf, -W * 0.42, zm), (xf, W * 0.42, zm), 0.025, "chassi")
            t.tubo_x((xf, -W * 0.30, zm + 0.20), (xf, W * 0.30, zm + 0.20), 0.022, "chassi")
            for y in (-W * 0.30, W * 0.30):
                t.tubo_x((xf, y, zm - 0.06), (xf, y, zm + 0.22), 0.022, "chassi")
                t.tubo_x((xf - 0.02, y, zm - 0.02), (mx[0] - 0.05, y, zm - 0.02), 0.02, "chassi")
            objeto("bumper_front__tubo", t)

    if "bumper_rear" in objs:
        br = objs["bumper_rear"]
        fatias, zb, sg = contorno(br, False)
        mn, mx = caixa_de(br)
        W = mx[1] - mn[1]
        if len(fatias) >= 3:
            def difusor(p, z_topo):
                # a placa preta no contorno e as aletas verticais embaixo dela
                p.fita_y(acrescimo(fatias, sg, lambda xf: [(xf - 0.010, z_topo - 0.010), (xf + 0.15, z_topo - 0.010), (xf + 0.15, z_topo),
                                                            (xf - 0.010, z_topo)]), "chassi")
                for k in range(5):
                    y = -W * 0.28 + k * W * 0.14
                    xf = min(fatias, key=lambda f: abs(f[0] - y))[1]
                    p.caixa((xf - 0.006, y - 0.004, z_topo - 0.050), (xf + 0.13, y + 0.004, z_topo - 0.010), "chassi")
            d = Peca()
            difusor(d, zb + 0.004)
            objeto("bumper_rear__difusor", d)
            e = Peca()
            e.fita_y(acrescimo(fatias, sg, lambda xf: [(xf + 0.004, zb + 0.012), (xf + 0.12, zb + 0.012), (xf + 0.12, zb - 0.040),
                                                        (xf + 0.016, zb - 0.040)]), "pintura")
            difusor(e, zb - 0.040)
            objeto("bumper_rear__esportivo", e)

    # --- capô (fase P4): a tomada de ar no meio do capô, assentada nele por raios, com a boca escura virada para a frente e a rampa que
    # morre na chapa atrás; o acréscimo é somado a uma cópia do capô de fábrica na montagem, como nos para-choques. A "fibra" (o capô
    # inteiro escuro) não sai daqui: o juntar_pecas_receita.py do Detonauto a deriva do capô de fábrica, sem pesar o GLB do acervo
    if "hood" in objs and idc not in SEM_TOMADA:
        mn, mx = caixa_de(objs["hood"])
        L = mx[0] - mn[0]
        Wc = mx[1] - mn[1]
        larg = min(0.40, Wc * 0.30)
        x_boca = mn[0] + L * 0.62
        x_fim = mn[0] + L * 0.18
        alt = 0.075
        secoes = []
        n = 8
        for k in range(n):
            t = k / (n - 1)
            x = x_boca + (x_fim - x_boca) * t
            h = alt * (1.0 - t) ** 1.3 + 0.004
            zs = [chao_em(x, y, mx[2] + 0.5) for y in (-larg / 2, 0.0, larg / 2)]
            if any(z is None for z in zs):
                continue
            zl, zm, zr = zs
            sec = [(-larg / 2, zl - 0.004), (larg / 2, zr - 0.004), (larg * 0.42, zm + h), (-larg * 0.42, zm + h)]
            secoes.append((x, sec))
        if len(secoes) >= 3:
            tom = Peca()
            tom.fita_x(secoes, "pintura")
            x0, sec0 = secoes[0]
            z_base = min(z for _, z in sec0)
            z_topo = max(z for _, z in sec0)
            # a boca: uma placa escura logo atrás da face da frente (a face da frente fica pintada, como a borda da tomada)
            tom.caixa((x0 - 0.004, -larg * 0.38, z_base + 0.006), (x0 + 0.003, larg * 0.38, z_topo - 0.007), "chassi")
            objeto("hood__tomada", tom)

    # --- escapamento (fase P4): ponteiras na traseira, embaixo do para-choque; a ponteira simples do passe de detalhe é a de fábrica.
    # Duplo: uma de cada lado; central: uma grande no meio. Tubo de cromo com o miolo escuro, preso à carroceria (o jogo a prende ao
    # body, como a saia)
    traseira = objs.get("bumper_rear") or objs.get("body")
    if traseira is not None:
        mn, mx = caixa_de(traseira)
        Wt = mx[1] - mn[1]
        z_cano = mn[2] + 0.045
        x_fim = mn[0] - 0.02

        def ponteira(p, y, r, comp=0.16):
            p.tubo_x((x_fim + comp, y, z_cano), (x_fim, y, z_cano), r, "cromo", lados=16)
            p.tubo_x((x_fim + 0.0005, y, z_cano), (x_fim - 0.0015, y, z_cano), r * 0.80, "chassi", lados=16)

        duplo = Peca()
        for y in (-Wt * 0.30, Wt * 0.30):
            ponteira(duplo, y, 0.032)
        objeto("escapamento__duplo", duplo)
        central = Peca()
        ponteira(central, 0.0, 0.048, 0.20)
        objeto("escapamento__central", central)

    # --- teto (fase P4): o solar (painel de vidro escuro com a moldura preta, assentado no teto por raios) e o bagageiro (duas barras
    # longas em pés e três travessas). O Furgãozinho já tem bagageiro de fábrica e o Pão de Forma não leva; o jipe de capota mole fica
    # sem solar
    corpo_b = objs.get("body")
    if corpo_b is not None:
        mn, mx = caixa_de(corpo_b)
        z_teto = chao_em(0.0, 0.0, mx[2] + 0.5)
        if z_teto is not None and z_teto > mn[2] + 0.9:
            # o teto plano: até onde, para a frente e para trás, ele fica a 4 cm do ponto mais alto
            xs = [k * 0.05 for k in range(-40, 41)]
            alto = [(x, chao_em(x, 0.0, mx[2] + 0.5)) for x in xs]
            plano = [x for x, z in alto if z is not None and z > z_teto - 0.04]
            if plano:
                xa, xb = min(plano), max(plano)
                Wr = (mx[1] - mn[1]) * 0.5
                if idc not in SEM_SOLAR and xb - xa > 0.6:
                    sol = Peca()
                    c = (xa + xb) / 2
                    L2, W2 = min(0.36, (xb - xa) * 0.32), Wr * 0.46
                    zc = max(chao_em(x, y, mx[2] + 0.5) or z_teto for x in (c - L2, c + L2) for y in (-W2, W2))
                    sol.caixa((c - L2 - 0.02, -W2 - 0.02, zc - 0.002), (c + L2 + 0.02, W2 + 0.02, zc + 0.004), "chassi")
                    sol.caixa((c - L2, -W2, zc + 0.004), (c + L2, W2, zc + 0.007), "vidro")
                    objeto("teto__solar", sol)
                # a meia-largura do teto plano no meio dele (a lateral do teto cai antes da carroceria: com a largura da carroceria, as
                # barras passavam da borda e os pés desciam pela coluna)
                c_teto = (xa + xb) / 2
                y_teto = 0.0
                for k in range(1, 60):
                    y = k * 0.0125
                    z = chao_em(c_teto, y, mx[2] + 0.5)
                    if z is None or z < z_teto - 0.04:
                        break
                    y_teto = y
                if idc not in SEM_BAGAGEIRO and xb - xa > 0.6 and y_teto > 0.25:
                    bag = Peca()
                    y_barra = y_teto * 0.85
                    z_barra = z_teto + 0.075
                    for y in (-y_barra, y_barra):
                        bag.tubo_x((xa + 0.02, y, z_barra), (xb - 0.02, y, z_barra), 0.014, "chassi")
                        for x in (xa + 0.06, xb - 0.06):
                            zp = chao_em(x, y, mx[2] + 0.5) or z_teto
                            bag.caixa((x - 0.03, y - 0.018, zp - 0.003), (x + 0.03, y + 0.018, z_barra), "chassi")
                    for k in range(3):
                        x = xa + 0.12 + (xb - xa - 0.24) * k / 2
                        bag.tubo_x((x, -y_barra, z_barra + 0.016), (x, y_barra, z_barra + 0.016), 0.011, "chassi")
                    objeto("teto__bagageiro", bag)

    # --- retrovisores (fase P4): a capa por cima da concha de fábrica (5 mm maior por todos os lados, nas faces de fora e de cima), em
    # cromo ou preta
    espelhos = [objs[n] for n in ("mirror_left", "mirror_right") if n in objs]
    if espelhos:
        for nome, mat in (("cromado", "cromo"), ("preto", "chassi")):
            cap = Peca()
            for o in espelhos:
                a, b = caixa_de(o)
                folga = 0.005
                # a capa cobre a frente, o topo e o lado de fora (a face de trás, com o espelho, fica aberta)
                lado = 1 if (a[1] + b[1]) > 0 else -1
                y_fora = b[1] + folga if lado > 0 else a[1] - folga
                y_dentro = a[1] if lado > 0 else b[1]
                y0, y1 = min(y_fora, y_dentro), max(y_fora, y_dentro)
                xm = (a[0] + b[0]) / 2
                cap.caixa((xm, y0, a[2] - folga), (b[0] + folga, y1, b[2] + folga), mat)
            objeto("retrovisor__" + nome, cap)

    # --- grade (fase P4): a tela na abertura da grade de fábrica (desenho próprio: losangos de barras finas, nunca o desenho de uma
    # marca) e a de barras horizontais grossas, 6 mm à frente da grade de fábrica
    if "grille" in objs:
        a, b = caixa_de(objs["grille"])
        x_g = b[0] + 0.006
        y0, y1, z0, z1 = a[1] + 0.01, b[1] - 0.01, a[2] + 0.008, b[2] - 0.008
        if y1 - y0 > 0.2 and z1 - z0 > 0.04:
            tela = Peca()
            tela.caixa((x_g - 0.004, y0 - 0.008, z0 - 0.008), (x_g + 0.002, y1 + 0.008, z0), "chassi")
            tela.caixa((x_g - 0.004, y0 - 0.008, z1), (x_g + 0.002, y1 + 0.008, z1 + 0.008), "chassi")
            passo = 0.045
            n = int((y1 - y0) / passo)
            for k in range(n + 1):
                y = y0 + (y1 - y0) * k / max(n, 1)
                tela.tubo_x((x_g, y - (z1 - z0) * 0.5, z0), (x_g, y + (z1 - z0) * 0.5, z1), 0.003, "chassi", lados=4)
                tela.tubo_x((x_g, y + (z1 - z0) * 0.5, z0), (x_g, y - (z1 - z0) * 0.5, z1), 0.003, "chassi", lados=4)
            objeto("grade__tela", tela, chanfro=False)   # barras de 3 mm: o chanfro multiplicava os triângulos por 13
            barras = Peca()
            nb = max(2, int((z1 - z0) / 0.035))
            for k in range(nb):
                zc = z0 + (z1 - z0) * (k + 0.5) / nb
                barras.caixa((x_g - 0.004, y0, zc - 0.007), (x_g + 0.006, y1, zc + 0.007), "chassi")
            objeto("grade__barras", barras)

    # --- saias: entre as caixas de roda, seguindo a lateral da carroceria por raios
    if rodas:
        x0, x1 = eixo_t + raio + 0.06, eixo_f - raio - 0.06
        # a base da saia: a borda de baixo da lateral entre as rodas (o ponto mais baixo da carroceria nessa faixa, sem a caixa de roda)
        zs = [p.z for o in corpo for p in pontos(o) if x0 <= p.x <= x1 and abs(p.y) > 0.45]
        z_base = (min(zs) if zs else caixa_de(objs["body"])[0][2]) + 0.015
        for nome in ("lisa", "esportiva"):
            p = Peca()
            for s in (1, -1):
                secoes = []
                n = 9
                for k in range(n):
                    x = x0 + (x1 - x0) * k / (n - 1)
                    ys = None
                    for dz in (0.05, 0.08, 0.12, 0.03):
                        hit = bvh.ray_cast(Vector((x, 1.5 * s, z_base + dz)), Vector((0, -s, 0)), 3.0)
                        if hit[0] is not None:
                            ys = hit[0].y
                            break
                    if ys is None:
                        continue
                    yo = ys + s * 0.032
                    yi = ys - s * 0.010
                    if nome == "lisa":
                        sec = [(yi, z_base - 0.03), (yo, z_base - 0.03), (yo, z_base + 0.065), (yi, z_base + 0.065)]
                    else:
                        sec = [(yi, z_base - 0.045), (yo + s * 0.012, z_base - 0.045), (yo, z_base - 0.02), (yo, z_base + 0.07),
                               (yi, z_base + 0.07), (yi, z_base + 0.01)]
                    if s < 0:
                        sec = list(reversed(sec))
                    secoes.append((x, sec))
                if len(secoes) >= 2:
                    p.fita_x(secoes, "pintura")
                    if nome == "esportiva":
                        lam = []
                        for x, sec in secoes:
                            yo = sec[1][0] if s > 0 else sec[-2][0]
                            yb = yo - s * 0.04
                            pts = [(yb, z_base - 0.052), (yo + s * 0.016, z_base - 0.052), (yo + s * 0.016, z_base - 0.044),
                                   (yb, z_base - 0.044)]
                            lam.append((x, pts if s > 0 else list(reversed(pts))))
                        p.fita_x(lam, "chassi")
            if p.v:
                objeto("saia__" + nome, p)

    # GLB só com as peças novas e sem as texturas do corte (o material compartilhado as levava junto: 6,8 MB por carro); no Detonauto o
    # material é a instância do jogo pelo nome do slot
    for m in bpy.data.materials:
        if m.node_tree:
            for n in [n for n in m.node_tree.nodes if n.type == "TEX_IMAGE"]:
                m.node_tree.nodes.remove(n)
    for im in list(bpy.data.images):
        bpy.data.images.remove(im)
    os.makedirs(out_dir, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in cria:
        o.select_set(True)
    caminho = os.path.join(out_dir, idc + "_pecas.glb")
    bpy.ops.export_scene.gltf(filepath=caminho, use_selection=True, export_format="GLB", export_apply=True)
    resumo = {"id": idc, "pecas": sorted(o.name for o in cria),
              "triangulos": {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in cria}}
    json.dump(resumo, open(os.path.join(out_dir, idc + "_pecas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[pecas] %s: %s" % (idc, ", ".join(resumo["pecas"])))
    return caminho


def main():
    a = args()
    idc = a["id"]
    glb = a.get("glb") or os.path.join(RAIZ, "veiculos", "sketchfab", "quebravel", idc, idc + ".glb")
    gerar(idc, glb, os.path.join(a["out"], idc), a["previa"])


if __name__ == "__main__":
    main()
