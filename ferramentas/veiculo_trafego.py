"""
Veículos de tráfego por script (06/11/2026): as unidades que faltavam ao tráfego dos 30 mapas do Detonauto, geradas inteiras no Blender,
sem marca, logo, emblema, texto ou modelo real. Geometria e cor próprias: CC0 do estúdio, sem IA. Cada veículo sai como fonte
(.blend com a cor procedural, que o zoeira_quebravel.py assa no atlas) mais o config do corte, no padrão dos veículos de zoeira.

    python -I ferramentas/veiculo_trafego.py -- todos|<id> [<id> ...] [--out veiculos/proprios/trafego] [--sem-glb]
    blender -b --python-exit-code 1 -P ferramentas/veiculo_trafego.py -- todos

Saída em --out: fontes/<id>.blend (+ fontes/<id>.glb para olhar) e quebravel/<id>/<id>_config.json; depois:
    python -I ferramentas/zoeira_quebravel.py -- <out>/quebravel/<id>/<id>_config.json <out>/quebravel/<id> --tamanho 1024 --lod1 0.35

Convenções do carro_quebravel/Detonauto: metros, frente +X, ESQUERDA +Y, cima +Z, chão em z = 0, origem entre os eixos. Objetos com os
nomes do kit (body, hood, trunk, door_fl, door_fr, bumper_front, bumper_rear, glass_windshield, glass_rear, headlight_left/right,
taillight_left/right) e as rodas roda_fl, roda_fr, roda_rl, roda_rr (a moto e o tuk-tuk têm a roda da frente em duas metades, uma por
canto, porque o corte pede os quatro cantos). Interior (bancos, painel, volante) faz parte do body e aparece pelo para-brisa.

Os veículos (id: o que é):
    onibus-urbano-12m      ônibus urbano de 12 m, porta à direita (Brasil, Istambul, Roma, Machu Picchu...)
    caminhao-bau           caminhão baú cabine avançada de 2 eixos, 8,6 m
    caminhao-basculante    caminhão basculante de 2 eixos com a caçamba carregada de terra
    moto-urbana            moto urbana de 150 cc com motociclista
    picape-cabine-simples  picape de cabine simples com caçamba aberta
    van-furgao             furgão de teto alto
    taxi-amarelo           sedã táxi amarelo com a luminária no teto (Nova York)
    taxi-branco-faixa      sedã táxi branco com a faixa (São Paulo)
    policia-sedan          sedã de polícia genérico: branco, faixa escura e barra de luz, sem brasão
    ambulancia-van         furgão ambulância genérico: branco, faixa vermelha e barra de luz, sem cruz nem símbolo
    tuk-tuk                autorriquixá de 3 rodas, verde e amarelo (Agra)
    bonde-sf               bonde urbano de um carro, verde e creme, com a vara do trole (São Francisco)
    onibus-dois-andares    ônibus vermelho de dois andares, porta à esquerda (Londres)
    taxi-londres           táxi preto de cabine alta com a luminária (Londres)
    kei-car                carro pequeno e alto de 3,4 m (Tóquio)
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


OUT = opt("--out", os.path.join(RAIZ, "veiculos", "proprios", "trafego"))
SEM_GLB = "--sem-glb" in args
PEDIDOS = [a for a in args if not a.startswith("--") and a != opt("--out", "")] or ["todos"]

cena = None
MAT = {}


# ================================================================================================================================
# materiais (cor com ruído fino e sujeira do chão; o zoeira_quebravel.py assa tudo no atlas)
# ================================================================================================================================
def soquete_cor(sockets, nome):
    return next(k for k in sockets if k.name == nome and k.type == "RGBA")


def material(nome, cor, rug=0.6, metal=0.0, ruido=0.06, sujeira=0.0, escala=40.0):
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rug
    b.inputs["Metallic"].default_value = metal
    base = nt.nodes.new("ShaderNodeRGB"); base.outputs[0].default_value = (*cor, 1.0)
    ruid = nt.nodes.new("ShaderNodeTexNoise"); ruid.inputs["Scale"].default_value = escala; ruid.inputs["Detail"].default_value = 6.0
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    nt.links.new(geo.outputs["Position"], ruid.inputs["Vector"])
    mapa = nt.nodes.new("ShaderNodeMapRange")
    mapa.inputs["From Min"].default_value = 0.3; mapa.inputs["From Max"].default_value = 0.7
    mapa.inputs["To Min"].default_value = 1.0 - ruido; mapa.inputs["To Max"].default_value = 1.0 + ruido
    nt.links.new(ruid.outputs["Fac"], mapa.inputs["Value"])
    mult = nt.nodes.new("ShaderNodeMix"); mult.data_type = "RGBA"; mult.blend_type = "MULTIPLY"
    mult.inputs["Factor"].default_value = 1.0
    nt.links.new(base.outputs[0], soquete_cor(mult.inputs, "A"))
    comb = nt.nodes.new("ShaderNodeCombineColor")
    for k in ("Red", "Green", "Blue"):
        nt.links.new(mapa.outputs["Result"], comb.inputs[k])
    nt.links.new(comb.outputs[0], soquete_cor(mult.inputs, "B"))
    saida = soquete_cor(mult.outputs, "Result")
    if sujeira > 0:
        sep = nt.nodes.new("ShaderNodeSeparateXYZ"); nt.links.new(geo.outputs["Position"], sep.inputs[0])
        alt = nt.nodes.new("ShaderNodeMapRange")
        alt.inputs["From Min"].default_value = 0.75; alt.inputs["From Max"].default_value = 0.05
        alt.inputs["To Min"].default_value = 0.0; alt.inputs["To Max"].default_value = sujeira
        nt.links.new(sep.outputs["Z"], alt.inputs["Value"])
        manchas = nt.nodes.new("ShaderNodeTexNoise"); manchas.inputs["Scale"].default_value = 5.0
        nt.links.new(geo.outputs["Position"], manchas.inputs["Vector"])
        fat = nt.nodes.new("ShaderNodeMath"); fat.operation = "MULTIPLY"
        nt.links.new(alt.outputs["Result"], fat.inputs[0]); nt.links.new(manchas.outputs["Fac"], fat.inputs[1])
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
        nt.links.new(fat.outputs[0], mix.inputs["Factor"])
        nt.links.new(saida, soquete_cor(mix.inputs, "A"))
        soquete_cor(mix.inputs, "B").default_value = (0.14, 0.12, 0.09, 1.0)
        saida = soquete_cor(mix.outputs, "Result")
    nt.links.new(saida, b.inputs["Base Color"])
    return m


def materiais(pintura, faixa=(0.70, 0.08, 0.06), sujeira=0.35):
    """Os materiais de um veículo. Os nomes casam com as regras do config: tv_pintura é a cor trocável; tv_chassi, tv_banco, tv_painel,
    tv_vidro_fixo, tv_faixa, tv_cacamba, tv_bau, tv_roupa, tv_terra viram "chassi"; tv_luz* viram "luz"; tv_cromo, "cromado"; tv_pneu, "pneu"."""
    return {
        "pintura": material("tv_pintura", pintura, 0.35, ruido=0.03, sujeira=sujeira),
        "chassi": material("tv_chassi", (0.020, 0.020, 0.022), 0.65, ruido=0.12, sujeira=0.6),
        "cinza": material("tv_chassi_cinza", (0.09, 0.095, 0.10), 0.55, 0.3, ruido=0.12, sujeira=0.6),
        "banco": material("tv_banco", (0.050, 0.045, 0.040), 0.8, ruido=0.15, escala=120.0),
        "painel": material("tv_painel", (0.030, 0.030, 0.032), 0.7, ruido=0.1),
        "vidro_fixo": material("tv_vidro_fixo", (0.020, 0.028, 0.035), 0.08, ruido=0.04),
        "faixa": material("tv_faixa", faixa, 0.35, ruido=0.03, sujeira=sujeira * 0.6),
        "cacamba": material("tv_cacamba", (0.11, 0.11, 0.11), 0.55, 0.4, ruido=0.2, sujeira=0.5),
        "bau": material("tv_bau", (0.78, 0.78, 0.74), 0.45, ruido=0.04, sujeira=0.5),
        "roupa": material("tv_roupa", (0.045, 0.045, 0.06), 0.8, ruido=0.1),
        "terra": material("tv_terra", (0.20, 0.14, 0.08), 0.95, ruido=0.3, escala=25.0),
        "luz": material("tv_luz", (0.90, 0.90, 0.86), 0.08, ruido=0.0),
        "luz_vermelha": material("tv_luz_vermelha", (0.80, 0.05, 0.03), 0.1, ruido=0.0),
        "luz_laranja": material("tv_luz_laranja", (0.95, 0.40, 0.03), 0.1, ruido=0.0),
        "luz_azul": material("tv_luz_azul", (0.05, 0.20, 0.95), 0.1, ruido=0.0),
        "luz_amarela": material("tv_luz_amarela", (0.98, 0.78, 0.10), 0.12, ruido=0.0),
        "cromo": material("tv_cromo", (0.70, 0.70, 0.72), 0.2, 1.0, ruido=0.02),
        "aro": material("tv_cromo_aro", (0.62, 0.63, 0.65), 0.35, 0.8, ruido=0.05, sujeira=0.5),
        "pneu": material("tv_pneu", (0.022, 0.022, 0.022), 0.88, ruido=0.18, sujeira=0.8, escala=90.0),
    }


# ================================================================================================================================
# malhas
# ================================================================================================================================
def ret_arredondado(larg, alt, raio, n=5, z0=0.0, raio_baixo=None):
    """Contorno (y, z) de um retângulo arredondado, base em z0, anti-horário visto da frente; o raio é limitado pelo tamanho."""
    raio = max(1e-3, min(raio, larg / 2 - 1e-3, alt / 2 - 1e-3))
    rb = raio if raio_baixo is None else max(1e-3, min(raio_baixo, larg / 2 - 1e-3, alt / 2 - 1e-3))
    meia = larg / 2
    pts = []
    cantos = (((meia - rb, z0 + rb), rb, -90.0), ((meia - raio, z0 + alt - raio), raio, 0.0),
              ((-meia + raio, z0 + alt - raio), raio, 90.0), ((-meia + rb, z0 + rb), rb, 180.0))
    # os lados retos entre os cantos ficam em tiras (lado direito, topo, lado esquerdo, base), para a pintura por altura e por
    # largura pegar faces pequenas e não a lateral inteira
    tiras = (DIV_LADO, DIV_TOPO, DIV_LADO, DIV_BASE)
    for i, ((cy, cz), r, a0) in enumerate(cantos):
        for k in range(n + 1):
            a = math.radians(a0 + 90.0 * k / n)
            pts.append((cy + r * math.cos(a), cz + r * math.sin(a)))
        (ny, nz), nr, na = cantos[(i + 1) % 4]
        fim = (ny + nr * math.cos(math.radians(na)), nz + nr * math.sin(math.radians(na)))
        ini = pts[-1]
        for k in range(1, tiras[i]):
            t = k / tiras[i]
            pts.append((ini[0] + (fim[0] - ini[0]) * t, ini[1] + (fim[1] - ini[1]) * t))
    return pts


DIV_LADO, DIV_TOPO, DIV_BASE = 6, 4, 2


def rot_para(d):
    """Matriz que leva +Z ao vetor d."""
    return Vector((0, 0, 1)).rotation_difference(Vector(d).normalized()).to_matrix().to_4x4()


class Malha:
    def __init__(self, nome):
        self.nome, self.bm, self.mats = nome, bmesh.new(), []

    def _i(self, m):
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def _marca(self, faces, m):
        i = self._i(m)
        for f in faces:
            f.material_index = i

    def _faces_de(self, verts):
        return list({f for v in verts for f in v.link_faces})

    def pintar(self, faces, pred, m):
        """Troca o material das faces cujo centro e normal passam em pred(centro, normal)."""
        self.bm.normal_update()
        self._marca([f for f in faces if pred(f.calc_center_median(), f.normal)], m)

    def caixa(self, c, t, m, chanfro=0.0, seg=3, rot=None):
        r = bmesh.ops.create_cube(self.bm, size=1.0)
        mat = Matrix.Translation(c) @ (rot or Matrix.Identity(4)) @ Matrix.Diagonal((*t, 1.0))
        bmesh.ops.transform(self.bm, matrix=mat, verts=r["verts"])
        self._marca(self._faces_de(r["verts"]), m)
        if chanfro > 0:
            ar = list({e for v in r["verts"] for e in v.link_edges})
            bmesh.ops.bevel(self.bm, geom=ar + r["verts"], offset=chanfro, segments=seg, affect="EDGES", profile=0.5)
        return r["verts"]

    def loft(self, secoes, m, tampar=True, passo=0.25):
        """secoes: [(x, [(y, z), ...])], todas com o mesmo número de pontos; pontas fechadas por leque. Entre duas seções a mais de
        passo metros entram seções interpoladas, para a pintura por região (porta, janela, faixa) pegar faces curtas."""
        cheias = [secoes[0]]
        for (xa, pa), (xb, pb) in zip(secoes, secoes[1:]):
            n_ = max(1, int(math.ceil((xb - xa) / passo))) if passo else 1
            for k in range(1, n_ + 1):
                t = k / n_
                cheias.append((xa + (xb - xa) * t, [(ya + (yb - ya) * t, za + (zb_ - za) * t) for (ya, za), (yb, zb_) in zip(pa, pb)]))
        secoes = cheias
        aneis = [[self.bm.verts.new((x, y, z)) for y, z in pts] for x, pts in secoes]
        n = len(aneis[0])
        faces = []
        for a, b in zip(aneis, aneis[1:]):
            for k in range(n):
                faces.append(self.bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k])))
        if tampar:
            for anel, x in ((aneis[0], secoes[0][0]), (aneis[-1], secoes[-1][0])):
                cy = sum(v.co.y for v in anel) / n; cz = sum(v.co.z for v in anel) / n
                c = self.bm.verts.new((x, cy, cz))
                for k in range(n):
                    faces.append(self.bm.faces.new((anel[k], anel[(k + 1) % n], c)))
        self._marca(faces, m)
        return faces

    def cilindro(self, c, raio, prof, m, eixo="z", seg=24, raio2=None, rot=None):
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=raio, radius2=raio if raio2 is None else raio2, depth=prof)
        base = {"x": Matrix.Rotation(math.pi / 2, 4, "Y"), "y": Matrix.Rotation(math.pi / 2, 4, "X"), "z": Matrix.Identity(4)}[eixo]
        bmesh.ops.transform(self.bm, matrix=Matrix.Translation(c) @ (rot or Matrix.Identity(4)) @ base, verts=r["verts"])
        self._marca(self._faces_de(r["verts"]), m)

    def tubo(self, p0, p1, raio, m, seg=12):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        self.cilindro((p0 + p1) / 2, raio, d.length, m, "z", seg, rot=rot_para(d))

    def esfera(self, c, raio, m, seg=16, escala=None):
        r = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=max(6, seg // 2), radius=raio)
        esc = Matrix.Diagonal((*(escala or (1, 1, 1)), 1.0))
        bmesh.ops.transform(self.bm, matrix=Matrix.Translation(c) @ esc, verts=r["verts"])
        self._marca(self._faces_de(r["verts"]), m)

    def toro(self, c, raio, tubo, m, rot=None, seg=32, seg_tubo=8):
        vs = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            anel = []
            for j in range(seg_tubo):
                b = 2 * math.pi * j / seg_tubo
                p = Vector(((raio + tubo * math.cos(b)) * math.cos(a), (raio + tubo * math.cos(b)) * math.sin(a), tubo * math.sin(b)))
                anel.append(self.bm.verts.new(Vector(c) + (rot or Matrix.Identity(4)).to_3x3() @ p))
            vs.append(anel)
        faces = []
        for i in range(seg):
            a, b = vs[i], vs[(i + 1) % seg]
            for j in range(seg_tubo):
                faces.append(self.bm.faces.new((a[j], b[j], b[(j + 1) % seg_tubo], a[(j + 1) % seg_tubo])))
        self._marca(faces, m)

    def revolucao(self, perfil, c, m, eixo="y", seg=36, anel_fechado=False):
        """Sólido de revolução: perfil [(raio, posição no eixo)] girado em volta do eixo por c."""
        c = Vector(c)
        aneis = []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            anel = []
            for r, t in perfil:
                if eixo == "y":
                    p = (c.x + r * math.cos(a), c.y + t, c.z + r * math.sin(a))
                else:
                    p = (c.x + r * math.cos(a), c.y + r * math.sin(a), c.z + t)
                anel.append(self.bm.verts.new(p))
            aneis.append(anel)
        faces = []
        n = len(perfil)
        for i in range(seg):
            a, b = aneis[i], aneis[(i + 1) % seg]
            for j in range(n if anel_fechado else n - 1):
                faces.append(self.bm.faces.new((a[j], a[(j + 1) % n], b[(j + 1) % n], b[j])))
        for j in (() if anel_fechado else (0, n - 1)):
            if perfil[j][0] > 1e-4:
                cc = self.bm.verts.new((c.x, c.y + perfil[j][1], c.z) if eixo == "y" else (c.x, c.y, c.z + perfil[j][1]))
                for i in range(seg):
                    faces.append(self.bm.faces.new((aneis[i][j], aneis[(i + 1) % seg][j], cc)))
        self._marca(faces, m)
        return faces

    def arco_girado(self, c, r_dentro, r_fora, y0, y1, a0, a1, m, passos=24):
        """Chapa curva em volta do eixo y por c (para-lama): de a0 a a1 graus (0 = frente, 90 = em cima)."""
        c = Vector(c)
        perfil = [(r_dentro, y0), (r_fora, y0), (r_fora, y1), (r_dentro, y1)]
        aneis = []
        for i in range(passos + 1):
            a = math.radians(a0 + (a1 - a0) * i / passos)
            aneis.append([self.bm.verts.new((c.x + r * math.cos(a), y, c.z + r * math.sin(a))) for r, y in perfil])
        faces = []
        for a, b in zip(aneis, aneis[1:]):
            for j in range(4):
                faces.append(self.bm.faces.new((a[j], a[(j + 1) % 4], b[(j + 1) % 4], b[j])))
        faces.append(self.bm.faces.new(list(reversed(aneis[0]))))
        faces.append(self.bm.faces.new(aneis[-1]))
        self._marca(faces, m)

    def placa(self, p00, p10, p11, p01, esp, m, desloc=0.0):
        """Chapa de 4 cantos (em ordem) com espessura esp, empurrada desloc ao longo da normal (para fora da carroceria)."""
        pts = [Vector(p) for p in (p00, p10, p11, p01)]
        n = (pts[1] - pts[0]).cross(pts[3] - pts[0]).normalized()
        a = [self.bm.verts.new(p + n * (esp / 2 + desloc)) for p in pts]
        b = [self.bm.verts.new(p - n * (esp / 2 - desloc)) for p in pts]
        faces = [self.bm.faces.new(a), self.bm.faces.new(list(reversed(b)))]
        for k in range(4):
            faces.append(self.bm.faces.new((a[k], b[k], b[(k + 1) % 4], a[(k + 1) % 4])))
        self._marca(faces, m)
        return faces

    def objeto(self, angulo_vivo=38.0):
        me = bpy.data.meshes.new(self.nome)
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        for f in self.bm.faces:
            f.smooth = True
        lim = math.radians(angulo_vivo)
        for e in self.bm.edges:
            e.smooth = not (len(e.link_faces) != 2 or e.calc_face_angle(0.0) > lim)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        o = bpy.data.objects.new(self.nome, me)
        cena.collection.objects.link(o)
        return o


# ================================================================================================================================
# pedaços comuns
# ================================================================================================================================
def roda(nome, c, R, larg, lado, pesado=False, dupla=False, metade=None, aro_raio=0.62):
    """Roda em c (centro do cubo). lado +1 esquerda; pesado = aro de caminhão; dupla = dois pneus (traseira de caminhão e ônibus);
    metade = "l" ou "r" (a roda de moto, cortada no plano y = 0, uma metade por canto)."""
    r = Malha(nome)
    c = Vector(c)
    W2 = larg / 2
    ar = aro_raio * R
    if metade:
        s = 1 if metade == "l" else -1
        perfil = [(0.0, 0.0), (0.22 * R, s * 0.012), (ar * 0.9, s * 0.02), (ar, s * W2 * 0.55), (0.80 * R, s * W2), (0.94 * R, s * W2 * 0.92),
                  (R, s * W2 * 0.55), (R, 0.0)]
        r.revolucao(perfil, c, MAT["pneu"], "y", 32)
        # o aro: a parte de dentro do perfil fica com a cor do aro
        r.pintar(r.bm.faces, lambda p, n: math.hypot(p.x - c.x, p.z - c.z) < ar * 0.97 and abs(p.y - c.y) < W2 * 0.5, MAT["aro"])
        return r.objeto(angulo_vivo=50.0)
    pneus = [0.0] if not dupla else [-W2 * 1.05 * lado, W2 * 1.05 * lado]
    for dy in pneus:
        cc = c + Vector((0, dy, 0))
        pneu = [(ar, -W2 + 0.01), (ar + 0.03, -W2), (0.86 * R, -W2 - 0.004), (0.95 * R, -W2 + 0.012), (R, -W2 + 0.03),
                (R, W2 - 0.03), (0.95 * R, W2 - 0.012), (0.86 * R, W2 + 0.004), (ar + 0.03, W2), (ar, W2 - 0.01)]
        r.revolucao(pneu, cc, MAT["pneu"], "y", 36, anel_fechado=True)
        # sulcos da banda de rodagem
        for k in range(3):
            t = -W2 * 0.5 + k * W2 * 0.5
            r.revolucao([(R - 0.006, t - 0.006), (R + 0.001, t - 0.006), (R + 0.001, t + 0.006), (R - 0.006, t + 0.006)], cc, MAT["chassi"], "y", 36, anel_fechado=True)
    # aro: prato com o fundo recuado (de caminhão: prato liso com os furos; de carro: raios)
    fora = c + Vector((0, lado * (W2 * (1.05 + 1.0) if dupla else 0), 0))
    aro = [(0.0, lado * 0.045), (0.16 * R, lado * 0.045), (0.22 * R, lado * 0.025), (ar * 0.72, lado * 0.02), (ar * 0.8, lado * 0.045),
           (ar + 0.002, lado * 0.05), (ar + 0.002, -lado * 0.045), (ar * 0.85, -lado * 0.04), (ar * 0.72, -lado * 0.015), (0.0, -lado * 0.015)]
    r.revolucao(aro, fora, MAT["aro"], "y", 32)
    furos = 8 if pesado else 5
    for k in range(furos):
        a = 2 * math.pi * k / furos + 0.3
        rr = (0.5 if pesado else 0.48) * ar
        p = fora + Vector((math.cos(a) * rr, lado * 0.03, math.sin(a) * rr))
        r.cilindro(p, (0.025 if pesado else 0.045) * R / 0.32, 0.014, MAT["chassi"], "y", 12)
    r.cilindro(fora + Vector((0, lado * 0.052, 0)), 0.13 * R, 0.02, MAT["cromo"], "y", 16)
    return r.objeto(angulo_vivo=50.0)


def luz(nome, c, t, m, rot=None):
    o = Malha(nome)
    o.caixa(c, t, m, min(t) * 0.3, 2, rot)
    return o.objeto()


def interior_carro(b, x_cowl, x_fundo, Wc, z_piso, zb, volante_y=0.38, bancos_tras=True):
    """Assoalho, painel, volante e bancos dentro da cabine (no body; aparecem pelo para-brisa)."""
    b.caixa(Vector(((x_cowl + x_fundo) / 2, 0, z_piso)), Vector((x_cowl - x_fundo, Wc - 0.06, 0.03)), MAT["chassi"])
    b.loft([(x, ret_arredondado(Wc - 0.08, h, 0.04, 3, zb - 0.22)) for x, h in ((x_cowl - 0.42, 0.18), (x_cowl - 0.30, 0.26), (x_cowl - 0.03, 0.30))], MAT["painel"])
    INCL = Matrix.Rotation(math.radians(-25), 4, "Y")
    b.toro(Vector((x_cowl - 0.62, volante_y, zb + 0.02)), 0.17, 0.016, MAT["banco"], rot=INCL, seg=28, seg_tubo=6)
    b.cilindro(Vector((x_cowl - 0.52, volante_y, zb - 0.05)), 0.02, 0.28, MAT["chassi"], "z", 10, rot=INCL)
    for y in (volante_y, -volante_y):
        b.caixa(Vector((x_cowl - 1.08, y, z_piso + 0.22)), Vector((0.50, 0.48, 0.14)), MAT["banco"], 0.035, 3)
        b.caixa(Vector((x_cowl - 1.36, y, z_piso + 0.55)), Vector((0.12, 0.46, 0.56)), MAT["banco"], 0.035, 3, Matrix.Rotation(math.radians(-12), 4, "Y"))
    if bancos_tras and x_cowl - 2.0 > x_fundo + 0.2:
        b.caixa(Vector((x_cowl - 1.95, 0, z_piso + 0.22)), Vector((0.50, Wc - 0.16, 0.14)), MAT["banco"], 0.035, 3)
        b.caixa(Vector((x_cowl - 2.22, 0, z_piso + 0.55)), Vector((0.12, Wc - 0.16, 0.56)), MAT["banco"], 0.035, 3, Matrix.Rotation(math.radians(-10), 4, "Y"))


def z_topo(secoes, x):
    """Topo (z) da seção interpolada em x, a partir de [(x, larg, z0, z1, ...)]."""
    for (xa, _, _, za, *_), (xb, _, _, zb_, *_) in zip(secoes, secoes[1:]):
        if xa <= x <= xb:
            return za + (zb_ - za) * (x - xa) / max(xb - xa, 1e-6)
    return secoes[0][3] if x < secoes[0][0] else secoes[-1][3]


def tracos(nome, caixa):
    return {"nome": nome, "caixa_m": [round(v, 3) for v in caixa]}


# ================================================================================================================================
# os tipos
# ================================================================================================================================
def carro(sp):
    """Sedã, hatch pequeno, furgão, picape e táxi de cabine alta. sp: L, W, H, EE, R, tipo, portas, cor, extras."""
    L, W, H, EE, R = sp["L"], sp["W"], sp["H"], sp["EE"], sp["R"]
    tipo = sp["tipo"]
    xd, xt = EE / 2, -EE / 2
    fd = {"sedan": 0.50, "hatch": 0.56, "van": 0.56, "picape": 0.48, "londres": 0.52}[tipo]
    x_front, x_rear = xd + (L - EE) * fd, xt - (L - EE) * (1 - fd)
    z0 = max(0.17, R * 0.55)
    zb = sp.get("zb", {"sedan": 0.62, "hatch": 0.56, "picape": 0.56, "van": 0.44, "londres": 0.54}[tipo] * H)
    Wc = W - (0.04 if tipo == "van" else 0.10)
    objs = []
    b = Malha("body")

    # ---- corpo de baixo
    if tipo == "sedan":
        x_cowl, x_cab_rear = xd - 0.25, xt - 0.35
        baixo = [(x_rear, 0.90 * W, z0 + 0.10, zb - 0.02, 0.10), (x_rear + 0.22, W, z0, zb + 0.02, 0.08), (x_cab_rear, W, z0, zb + 0.02, 0.08),
                 (x_cowl, W, z0, zb, 0.08), (x_front - 0.35, 0.98 * W, z0, zb - 0.10, 0.09), (x_front - 0.06, 0.92 * W, z0 + 0.08, zb - 0.18, 0.10),
                 (x_front, 0.86 * W, z0 + 0.14, zb - 0.24, 0.08)]
    elif tipo == "hatch":
        x_cowl, x_cab_rear = xd - 0.22, x_rear + 0.05
        baixo = [(x_rear, 0.92 * W, z0 + 0.08, zb - 0.02, 0.08), (x_rear + 0.15, W, z0, zb + 0.02, 0.08), (x_cowl, W, z0, zb, 0.08),
                 (x_front - 0.30, 0.98 * W, z0, zb - 0.08, 0.09), (x_front - 0.06, 0.92 * W, z0 + 0.08, zb - 0.16, 0.10), (x_front, 0.86 * W, z0 + 0.14, zb - 0.22, 0.08)]
    elif tipo == "van":
        x_cowl, x_cab_rear = xd - 0.10, x_rear + 0.03
        baixo = [(x_rear, 0.94 * W, z0 + 0.06, zb + 0.02, 0.06), (x_rear + 0.10, W, z0, zb + 0.02, 0.06), (x_cowl, W, z0, zb, 0.07),
                 (x_front - 0.30, 0.98 * W, z0, zb - 0.10, 0.09), (x_front - 0.05, 0.92 * W, z0 + 0.08, zb - 0.22, 0.10), (x_front, 0.86 * W, z0 + 0.14, zb - 0.30, 0.08)]
    elif tipo == "picape":
        x_cowl, x_cab_rear = xd - 0.25, xt + 0.75
        x_bed0 = x_cab_rear - 0.04
        baixo = [(x_bed0 - 0.02, W, z0, z0 + 0.25, 0.04), (x_cab_rear, W, z0, zb + 0.02, 0.07), (x_cowl, W, z0, zb, 0.07),
                 (x_front - 0.30, 0.98 * W, z0, zb - 0.08, 0.09), (x_front - 0.05, 0.92 * W, z0 + 0.08, zb - 0.16, 0.10), (x_front, 0.86 * W, z0 + 0.14, zb - 0.22, 0.08)]
    else:  # londres: cabine alta, capô curto e arredondado
        x_cowl, x_cab_rear = xd + 0.05, x_rear + 0.06
        baixo = [(x_rear, 0.90 * W, z0 + 0.08, zb, 0.10), (x_rear + 0.18, W, z0, zb + 0.02, 0.09), (x_cowl, W, z0, zb, 0.09),
                 (x_front - 0.25, 0.96 * W, z0, zb - 0.14, 0.12), (x_front - 0.05, 0.86 * W, z0 + 0.08, zb - 0.26, 0.14), (x_front, 0.78 * W, z0 + 0.16, zb - 0.34, 0.10)]
    fb = b.loft([(x, ret_arredondado(w, z1 - zz0, r, 5, zz0, raio_baixo=0.03)) for x, w, zz0, z1, r in baixo], MAT["pintura"])
    b.pintar(fb, lambda p, n: n.z < -0.6, MAT["chassi"])
    # bolsos das rodas: a lateral escurece em volta de cada roda
    for xr in (xd, xt):
        b.pintar(fb, lambda p, n, xr=xr: abs(n.y) > 0.5 and math.hypot(p.x - xr, p.z - R) < R + 0.05 and p.z < R + 0.12, MAT["chassi"])
    if sp.get("faixa"):
        zf0, zf1 = sp["faixa"]
        b.pintar(fb, lambda p, n: abs(n.y) > 0.5 and zf0 <= p.z <= zf1 and x_rear + 0.3 < p.x < x_front - 0.5, MAT["faixa"])

    # ---- cabine
    if tipo == "sedan":
        x_rt, x_wt = xt + 0.25, xd - 0.95
        cab = [(x_cab_rear, Wc, zb, zb + 0.04, 0.02), (x_rt, Wc - 0.12, zb, H, 0.20), (x_wt, Wc - 0.12, zb, H, 0.20), (x_cowl, Wc, zb, zb + 0.04, 0.02)]
    elif tipo == "hatch":
        x_rt, x_wt = x_rear + 0.22, xd - 0.85
        cab = [(x_cab_rear, Wc, zb, zb + 0.04, 0.02), (x_rt, Wc - 0.06, zb, H, 0.12), (x_wt, Wc - 0.06, zb, H, 0.12), (x_cowl, Wc, zb, zb + 0.04, 0.02)]
    elif tipo == "van":
        x_rt, x_wt = x_rear + 0.10, xd - 0.55
        cab = [(x_cab_rear, Wc, zb, zb + 0.04, 0.02), (x_rt, Wc - 0.04, zb, H, 0.16), (x_wt, Wc - 0.04, zb, H, 0.16), (x_cowl, Wc, zb, zb + 0.04, 0.02)]
    elif tipo == "picape":
        x_rt, x_wt = x_cab_rear + 0.06, xd - 0.80
        cab = [(x_cab_rear, Wc, zb, zb + 0.04, 0.02), (x_rt, Wc - 0.06, zb, H, 0.12), (x_wt, Wc - 0.06, zb, H, 0.12), (x_cowl, Wc, zb, zb + 0.04, 0.02)]
    else:
        x_rt, x_wt = x_rear + 0.22, xd - 0.45
        cab = [(x_cab_rear, Wc, zb, zb + 0.04, 0.02), (x_rt, Wc - 0.06, zb, H, 0.20), (x_wt, Wc - 0.06, zb, H, 0.20), (x_cowl, Wc, zb, zb + 0.04, 0.02)]
    # colunas: seções a mais nas bordas das janelas, para as faces caírem certas
    portas = sp.get("portas", 4)
    x_b = x_wt - 0.05 - (0.95 if portas == 4 else 1.10)   # coluna B (atrás da porta da frente)
    cab_x = sorted({x_rt, x_wt} | ({x_b - 0.05, x_b + 0.05} if x_rt + 0.3 < x_b < x_wt - 0.3 else set()))
    secs = [(x, Wc - cab[1][4] * 0.5, zb, H, cab[1][4]) for x in cab_x]
    cab_sec = [cab[0]] + [s for s in secs] + [cab[-1]]
    fc = b.loft([(x, ret_arredondado(w, z1 - zz0, r, 5, zz0, raio_baixo=0.01)) for x, w, zz0, z1, r in cab_sec], MAT["pintura"])
    janela = lambda p, n: abs(n.y) > 0.6 and zb + 0.07 < p.z < H - 0.09 and x_rt + 0.08 < p.x < x_wt - 0.08 and abs(p.x - x_b) > 0.045
    b.pintar(fc, janela, MAT["vidro_fixo"])
    if tipo == "van" and not sp.get("janelas_lado", False):
        # furgão: só o vidro das portas da frente
        b.pintar(fc, lambda p, n: abs(n.y) > 0.6 and p.x < x_b, MAT["pintura"])

    # ---- vidros que estouram
    vs = Malha("glass_windshield")
    yw = Wc / 2 - 0.10
    vs.placa((x_cowl, -yw, zb + 0.03), (x_cowl, yw, zb + 0.03), (x_wt + 0.02, yw - 0.06, H - 0.08), (x_wt + 0.02, -yw + 0.06, H - 0.08), 0.012, MAT["vidro_fixo"], 0.022)
    objs.append(vs.objeto())
    vr = Malha("glass_rear")
    vr.placa((x_cab_rear, yw, zb + 0.03), (x_cab_rear, -yw, zb + 0.03), (x_rt - 0.02, -yw + 0.06, H - 0.08), (x_rt - 0.02, yw - 0.06, H - 0.08), 0.012, MAT["vidro_fixo"], 0.022)
    objs.append(vr.objeto())

    # ---- capô, tampa, portas, para-choques, luzes
    hood = Malha("hood")
    xs = [x_cowl + 0.03 + (x_front - 0.14 - x_cowl - 0.03) * k / 4 for k in range(5)]
    hood.loft([(x, ret_arredondado((W - 0.18) * (1 - 0.06 * k / 4), 0.03, 0.012, 2, z_topo(baixo, x) - 0.012)) for k, x in enumerate(xs)], MAT["pintura"])
    objs.append(hood.objeto())
    if tipo == "sedan":
        tr = Malha("trunk")
        xs = [x_rear + 0.10 + (x_cab_rear - 0.03 - x_rear - 0.10) * k / 3 for k in range(4)]
        tr.loft([(x, ret_arredondado(W - 0.20, 0.03, 0.012, 2, z_topo(baixo, x) - 0.012)) for x in xs], MAT["pintura"])
        objs.append(tr.objeto())
    elif tipo == "picape":
        pass   # a tampa da caçamba vem abaixo
    else:
        tr = Malha("trunk")
        incl = math.atan2(x_rt - x_cab_rear, H - zb)
        zc = (zb + H) / 2 + 0.02
        tr.caixa(Vector((x_cab_rear - 0.005 + (zc - zb) * math.tan(incl), 0, zc)), Vector((0.03, Wc - 0.26, H - zb - 0.24)), MAT["pintura"], 0.012, 2,
                 Matrix.Rotation(incl, 4, "Y"))
        if tipo == "van":
            tr.caixa(Vector((x_cab_rear - 0.012, 0, zc)), Vector((0.012, 0.03, H - zb - 0.3)), MAT["chassi"])   # a fresta entre as duas folhas
        objs.append(tr.objeto())
    x_d0 = (x_b + 0.02) if portas == 4 else max(x_rt + 0.10, x_b + 0.02)
    x_d1 = x_cowl - 0.04
    for nome, lado in (("door_fl", 1), ("door_fr", -1)):
        d = Malha(nome)
        d.caixa(Vector(((x_d0 + x_d1) / 2, lado * (W / 2 + 0.002), (z0 + 0.10 + zb - 0.03) / 2)), Vector((x_d1 - x_d0, 0.03, zb - z0 - 0.13)), MAT["pintura"], 0.012, 2)
        d.caixa(Vector((x_d0 + 0.22, lado * (W / 2 + 0.022), zb - 0.14)), Vector((0.14, 0.02, 0.03)), MAT["cromo"], 0.006, 1)   # maçaneta
        objs.append(d.objeto())
        b.pintar(fb, lambda p, n, lado=lado: n.y * lado > 0.5 and x_d0 + 0.02 < p.x < x_d1 - 0.02 and z0 + 0.12 < p.z < zb - 0.05, MAT["chassi"])
    if portas == 4:
        for lado in (1, -1):
            d = Malha("door_rl" if lado > 0 else "door_rr")
            xa, xb_ = x_rt + 0.08, x_b - 0.02
            d.caixa(Vector(((xa + xb_) / 2, lado * (W / 2 + 0.002), (z0 + 0.10 + zb - 0.03) / 2)), Vector((xb_ - xa, 0.03, zb - z0 - 0.13)), MAT["pintura"], 0.012, 2)
            d.caixa(Vector((xa + 0.20, lado * (W / 2 + 0.022), zb - 0.14)), Vector((0.14, 0.02, 0.03)), MAT["cromo"], 0.006, 1)
            objs.append(d.objeto())
    for nome, x, m in (("bumper_front", x_front + 0.03, MAT["pintura"]), ("bumper_rear", x_rear - 0.03, MAT["pintura"])):
        p = Malha(nome)
        p.caixa(Vector((x, 0, z0 + 0.12)), Vector((0.14, W - 0.06, 0.18)), m if tipo != "van" else MAT["chassi"], 0.045, 3)
        objs.append(p.objeto())
    zl = zb - 0.26 if tipo != "londres" else zb - 0.30
    for lado, nome in ((1, "headlight_left"), (-1, "headlight_right")):
        objs.append(luz(nome, Vector((x_front + 0.005, lado * (W / 2 - 0.28), zl)), Vector((0.05, 0.30, 0.13)), MAT["luz"]))
        objs.append(luz(nome.replace("headlight", "taillight"), Vector((x_rear - 0.005, lado * (W / 2 - 0.26), zb - 0.14)), Vector((0.05, 0.30, 0.12)), MAT["luz_vermelha"]))
    # grade, placa em branco, retrovisores, escapamento, eixos, assoalho
    b.caixa(Vector((x_front - 0.005, 0, zl)), Vector((0.03, W / 2 - 0.70, 0.10)), MAT["chassi"], 0.01, 2)
    b.caixa(Vector((x_front + 0.085, 0, z0 + 0.12)), Vector((0.02, 0.40, 0.13)), MAT["bau"], 0.0, 1)
    b.caixa(Vector((x_rear - 0.085, 0, z0 + 0.12)), Vector((0.02, 0.40, 0.13)), MAT["bau"], 0.0, 1)
    for lado in (1, -1):
        b.caixa(Vector((x_cowl - 0.08, lado * (W / 2 + 0.11), zb + 0.16)), Vector((0.07, 0.17, 0.11)), MAT["chassi"], 0.02, 2)
        b.caixa(Vector((x_cowl - 0.08, lado * (W / 2 + 0.03), zb + 0.12)), Vector((0.03, 0.06, 0.03)), MAT["chassi"])
    b.cilindro(Vector((x_rear - 0.02, -W / 2 + 0.30, z0 - 0.02)), 0.025, 0.25, MAT["cinza"], "x", 10)
    for x in (xd, xt):
        b.cilindro(Vector((x, 0, R)), 0.045, W - 0.30, MAT["chassi"], "y", 10)
    interior_carro(b, x_cowl, x_cab_rear, Wc, z0 + 0.04, zb, bancos_tras=(tipo != "picape"))

    # ---- extras
    if tipo == "picape":
        xb0, xb1 = x_rear + 0.02, x_cab_rear - 0.06
        b.caixa(Vector(((xb0 + xb1) / 2, 0, z0 + 0.26)), Vector((xb1 - xb0, W - 0.08, 0.03)), MAT["cacamba"])
        for lado in (1, -1):
            b.caixa(Vector(((xb0 + xb1) / 2, lado * (W / 2 - 0.03), (z0 + 0.26 + zb) / 2)), Vector((xb1 - xb0, 0.03, zb - z0 - 0.26)), MAT["pintura"], 0.01, 2)
            b.caixa(Vector(((xb0 + xb1) / 2, lado * (W / 2 - 0.07), (z0 + 0.26 + zb) / 2)), Vector((xb1 - xb0 - 0.06, 0.03, zb - z0 - 0.30)), MAT["cacamba"])
        b.caixa(Vector((xb1 + 0.015, 0, (z0 + 0.26 + zb) / 2)), Vector((0.03, W - 0.08, zb - z0 - 0.26)), MAT["pintura"], 0.01, 2)
        for lado in (1, -1):
            b.caixa(Vector((xt, lado * (W / 2 - 0.22), z0 + 0.26 + 0.17)), Vector((2 * R + 0.24, 0.30, 0.34)), MAT["cacamba"], 0.03, 2)
        tg = Malha("trunk")
        tg.caixa(Vector((xb0 + 0.01, 0, (z0 + 0.26 + zb) / 2)), Vector((0.04, W - 0.12, zb - z0 - 0.30)), MAT["pintura"], 0.012, 2)
        objs.append(tg.objeto())
    if sp.get("taxi_sinal"):
        xc = (x_rt + x_wt) / 2
        b.caixa(Vector((xc, 0, H + 0.02)), Vector((0.26, 0.56, 0.04)), MAT["chassi"], 0.01, 2)
        b.caixa(Vector((xc, 0, H + 0.11)), Vector((0.22, 0.60, 0.15)), MAT["luz_amarela"], 0.025, 2)
    if sp.get("barra_luz"):
        xc = x_wt + 0.25
        b.caixa(Vector((xc, 0, H + 0.03)), Vector((0.22, W * 0.72, 0.05)), MAT["chassi"], 0.012, 2)
        n = 6
        for k in range(n):
            y = -W * 0.33 + k * (W * 0.66) / (n - 1)
            b.caixa(Vector((xc, y, H + 0.10)), Vector((0.20, W * 0.66 / n - 0.015, 0.10)), MAT["luz_azul"] if k % 2 else MAT["luz_vermelha"], 0.015, 2)
    objs.insert(0, b.objeto())

    # ---- rodas
    for nome, x, lado in (("roda_fl", xd, 1), ("roda_fr", xd, -1), ("roda_rl", xt, 1), ("roda_rr", xt, -1)):
        objs.append(roda(nome, (x, lado * (W / 2 - 0.12), R), R, 0.20, lado))
    return objs, {"portas": portas, "linha_de_cintura": round(zb, 3), "topo_da_saia": round(z0, 3), "coluna_a": round(x_wt, 3)}


def onibus(sp):
    """Ônibus urbano (um ou dois andares) e o bonde. sp: L, W, H, EE, R, andares, bonde, porta_lado, cor."""
    L, W, H, EE, R = sp["L"], sp["W"], sp["H"], sp["EE"], sp["R"]
    bonde = sp.get("bonde", False)
    dois = sp.get("andares", 1) == 2
    xd, xt = EE / 2, -EE / 2
    fd = 0.42 if not bonde else 0.5
    x_front, x_rear = xd + (L - EE) * fd, xt - (L - EE) * (1 - fd)
    z0 = 0.38 if not bonde else 0.30
    objs = []
    b = Malha("body")
    rt = 0.22 if not bonde else 0.30
    lado_porta = sp.get("porta_lado", -1)
    # seções: pontas arredondadas e uma seção a cada coluna de janela
    passo = 1.45
    janelas_x0 = x_front - 1.05 if not bonde else x_front - 1.3
    colunas = []
    x = janelas_x0
    while x > x_rear + 0.9:
        colunas.append(x); x -= passo
    xs = sorted({x_rear, x_rear + 0.18, x_front - 0.18, x_front} | {c + d for c in colunas for d in (-0.045, 0.045)})
    sec = []
    for x in xs:
        if x <= x_rear + 0.18 or x >= x_front - 0.18:
            fim = min(x - x_rear, x_front - x)
            k = max(0.0, min(1.0, fim / 0.18))
            sec.append((x, W - 0.16 * (1 - k), z0 + 0.10 * (1 - k), H - 0.12 * (1 - k), rt))
        else:
            sec.append((x, W, z0, H, rt))
    fb = b.loft([(x, ret_arredondado(w, z1 - zz0, r, 6, zz0, raio_baixo=0.05)) for x, w, zz0, z1, r in sec], MAT["pintura"])
    b.pintar(fb, lambda p, n: n.z < -0.6, MAT["chassi"])
    zj0, zj1 = (1.55, 2.55) if not dois else (1.55, 2.45)
    col_perto = lambda px: any(abs(px - c) < 0.05 for c in colunas)
    b.pintar(fb, lambda p, n: abs(n.y) > 0.6 and zj0 < p.z < zj1 and x_rear + 0.95 < p.x < janelas_x0 + 0.02 and not col_perto(p.x), MAT["vidro_fixo"])
    if dois:
        b.pintar(fb, lambda p, n: abs(n.y) > 0.6 and 3.05 < p.z < 4.0 and x_rear + 0.25 < p.x < x_front - 0.3 and not col_perto(p.x), MAT["vidro_fixo"])
        # faixa escura entre os andares e o para-brisa de cima (fixo)
        b.pintar(fb, lambda p, n: abs(n.y) > 0.6 and 2.6 < p.z < 2.85, MAT["chassi"])
        b.placa((x_front + 0.01, -W / 2 + 0.18, 3.0), (x_front + 0.01, W / 2 - 0.18, 3.0), (x_front + 0.01, W / 2 - 0.22, H - 0.18),
                (x_front + 0.01, -W / 2 + 0.22, H - 0.18), 0.012, MAT["vidro_fixo"])
    if bonde:
        # bonde de duas cores: creme da cintura para cima, verde embaixo, friso cromado
        b.pintar(fb, lambda p, n: abs(n.y) > 0.3 and p.z > 1.35, MAT["faixa"])
        b.pintar(fb, lambda p, n: abs(n.y) > 0.6 and zj0 < p.z < zj1 and x_rear + 0.95 < p.x < janelas_x0 + 0.02 and not col_perto(p.x), MAT["vidro_fixo"])
        for lado in (1, -1):
            b.caixa(Vector(((x_front + x_rear) / 2, lado * (W / 2 + 0.005), 1.35)), Vector((L - 0.6, 0.02, 0.05)), MAT["cromo"])
        # a vara do trole e a base
        b.caixa(Vector((0.0, 0, H + 0.05)), Vector((0.5, 0.5, 0.10)), MAT["chassi"], 0.02, 2)
        b.tubo((0.0, 0, H + 0.1), (-3.6, 0, H + 1.55), 0.025, MAT["cinza"])
        b.esfera((-3.6, 0, H + 1.55), 0.06, MAT["cinza"])
        # saia e o "limpa-trilhos" da frente
        b.caixa(Vector((x_front - 0.1, 0, 0.22)), Vector((0.3, W - 0.3, 0.12)), MAT["chassi"], 0.02, 2)
        b.caixa(Vector((x_rear + 0.1, 0, 0.22)), Vector((0.3, W - 0.3, 0.12)), MAT["chassi"], 0.02, 2)
    else:
        # faixa de cor na cintura (ônibus brasileiro) e o letreiro de destino em branco
        if sp.get("faixa"):
            b.pintar(fb, lambda p, n: abs(n.y) > 0.6 and 0.95 < p.z < 1.3 and x_rear + 0.3 < p.x < x_front - 0.3, MAT["faixa"])
        b.caixa(Vector((x_front - 0.02, 0, H - 0.30)), Vector((0.05, W - 0.7, 0.36)), MAT["chassi"], 0.012, 2)
        # portas de passageiros: duas folhas escuras com o vidro
        for xp in (x_front - 0.95, (x_front + x_rear) / 2 - 0.6):
            for k in (-1, 1):
                b.caixa(Vector((xp + k * 0.33, lado_porta * (W / 2 + 0.006), (z0 + zj1) / 2)), Vector((0.62, 0.02, zj1 - z0)), MAT["chassi"], 0.01, 2)
                b.caixa(Vector((xp + k * 0.33, lado_porta * (W / 2 + 0.012), (zj0 + zj1) / 2)), Vector((0.50, 0.015, zj1 - zj0 - 0.1)), MAT["vidro_fixo"])
            b.pintar(fb, lambda p, n, xp=xp: n.y * lado_porta > 0.5 and abs(p.x - xp) < 0.68 and z0 + 0.05 < p.z < zj1 + 0.05, MAT["chassi"])
        # grade do motor atrás
        b.caixa(Vector((x_rear - 0.005, 0, 1.0)), Vector((0.03, W - 0.9, 0.7)), MAT["chassi"], 0.02, 2)
    # para-brisa (estoura) e vidro de trás
    vs = Malha("glass_windshield")
    zw0, zw1 = (1.05, H - 0.55) if not dois else (1.05, 2.45)
    if bonde:
        zw0, zw1 = 1.4, H - 0.45
    vs.placa((x_front + 0.012, -W / 2 + 0.16, zw0), (x_front + 0.012, W / 2 - 0.16, zw0), (x_front + 0.012, W / 2 - 0.20, zw1), (x_front + 0.012, -W / 2 + 0.20, zw1), 0.012, MAT["vidro_fixo"])
    objs.append(vs.objeto())
    vr = Malha("glass_rear")
    zr0, zr1 = (1.65, H - 0.5) if not dois else (3.05, H - 0.4)
    if bonde:
        zr0, zr1 = 1.4, H - 0.45
    vr.placa((x_rear - 0.012, W / 2 - 0.2, zr0), (x_rear - 0.012, -W / 2 + 0.2, zr0), (x_rear - 0.012, -W / 2 + 0.24, zr1), (x_rear - 0.012, W / 2 - 0.24, zr1), 0.012, MAT["vidro_fixo"])
    objs.append(vr.objeto())
    # para-choques, luzes, retrovisores
    for nome, x in (("bumper_front", x_front + 0.04), ("bumper_rear", x_rear - 0.04)):
        p = Malha(nome)
        p.caixa(Vector((x, 0, z0 + 0.16)), Vector((0.16, W - 0.10, 0.30)), MAT["chassi"], 0.05, 3)
        objs.append(p.objeto())
    for lado, nome in ((1, "headlight_left"), (-1, "headlight_right")):
        if bonde and lado < 0:
            continue
        yl = lado * (W / 2 - 0.40) if not bonde else 0.0
        objs.append(luz(nome, Vector((x_front + 0.01, yl, z0 + 0.42)), Vector((0.05, 0.34 if not bonde else 0.26, 0.20)), MAT["luz"]))
    for lado, nome in ((1, "taillight_left"), (-1, "taillight_right")):
        objs.append(luz(nome, Vector((x_rear - 0.01, lado * (W / 2 - 0.30), z0 + 0.62)), Vector((0.05, 0.22, 0.42)), MAT["luz_vermelha"]))
    for lado in (1, -1):
        b.tubo((x_front - 0.45, lado * (W / 2 - 0.05), 2.3), (x_front - 0.05, lado * (W / 2 + 0.38), 2.5), 0.022, MAT["chassi"])
        b.caixa(Vector((x_front - 0.05, lado * (W / 2 + 0.40), 2.35)), Vector((0.08, 0.14, 0.42)), MAT["chassi"], 0.02, 2)
    # motorista: banco, volante e painel pelo para-brisa
    b.caixa(Vector((x_front - 0.6, 0, zw0 - 0.3)), Vector((0.5, W - 0.6, 0.35)), MAT["painel"], 0.03, 2)
    b.toro(Vector((x_front - 1.1, 0.75, zw0 + 0.05)), 0.24, 0.018, MAT["banco"], rot=Matrix.Rotation(math.radians(-55), 4, "Y"), seg=28, seg_tubo=6)
    b.caixa(Vector((x_front - 1.65, 0.75, zw0 - 0.25)), Vector((0.5, 0.5, 0.14)), MAT["banco"], 0.03, 2)
    b.caixa(Vector((x_front - 1.9, 0.75, zw0 + 0.1)), Vector((0.12, 0.5, 0.6)), MAT["banco"], 0.03, 2)
    for x in (xd, xt):
        b.cilindro(Vector((x, 0, R)), 0.08, W - 0.5, MAT["chassi"], "y", 12)
    objs.insert(0, b.objeto())
    larg = 0.28 if not bonde else 0.12
    for nome, x, lado in (("roda_fl", xd, 1), ("roda_fr", xd, -1), ("roda_rl", xt, 1), ("roda_rr", xt, -1)):
        objs.append(roda(nome, (x, lado * (W / 2 - (0.22 if not bonde else 0.45)), R), R, larg, lado, pesado=True, dupla=(x == xt and not bonde)))
    return objs, {"portas": 0, "linha_de_cintura": 1.5, "topo_da_saia": round(z0, 3), "van": True}


def caminhao(sp):
    """Caminhão de cabine avançada com baú ou caçamba basculante. sp: L, W, H (da cabine), EE, R, carga, cor."""
    L, W, H, EE, R = sp["L"], sp["W"], sp["H"], sp["EE"], sp["R"]
    xd, xt = EE / 2, -EE / 2
    x_front = xd + 1.25
    x_rear = x_front - L
    x_cab_rear = xd - 0.55
    z0 = 0.72
    Wc = W - 0.12
    objs = []
    b = Malha("body")
    cab = [(x_cab_rear, Wc, z0, H, 0.14), (x_cab_rear + 0.4, Wc, z0, H, 0.14), (x_front - 0.30, Wc, z0, H, 0.14), (x_front - 0.08, Wc - 0.08, z0 + 0.05, H - 0.10, 0.16),
           (x_front, Wc - 0.24, z0 + 0.12, H - 0.22, 0.14)]
    fc = b.loft([(x, ret_arredondado(w, z1 - zz0, r, 6, zz0, raio_baixo=0.04)) for x, w, zz0, z1, r in cab], MAT["pintura"])
    b.pintar(fc, lambda p, n: n.z < -0.6, MAT["chassi"])
    b.pintar(fc, lambda p, n: abs(n.y) > 0.6 and H - 1.15 < p.z < H - 0.25 and x_cab_rear + 0.12 < p.x < x_front - 0.35, MAT["vidro_fixo"])
    b.caixa(Vector((x_front - 0.01, 0, z0 + 0.62)), Vector((0.05, Wc - 0.5, 0.55)), MAT["chassi"], 0.02, 2)   # grade escura
    for k in range(4):
        b.caixa(Vector((x_front + 0.02, 0, z0 + 0.42 + k * 0.13)), Vector((0.02, Wc - 0.6, 0.03)), MAT["cinza"])
    vs = Malha("glass_windshield")
    vs.placa((x_front + 0.0, -Wc / 2 + 0.18, H - 1.25), (x_front + 0.0, Wc / 2 - 0.18, H - 1.25), (x_front - 0.06, Wc / 2 - 0.24, H - 0.34), (x_front - 0.06, -Wc / 2 + 0.24, H - 0.34), 0.012, MAT["vidro_fixo"], 0.03)
    objs.append(vs.objeto())
    for nome, lado in (("door_fl", 1), ("door_fr", -1)):
        d = Malha(nome)
        xa, xb_ = x_cab_rear + 0.12, x_front - 0.42
        d.caixa(Vector(((xa + xb_) / 2, lado * (Wc / 2 + 0.002), (z0 + 0.1 + H - 1.2) / 2)), Vector((xb_ - xa, 0.03, H - 1.2 - z0 - 0.1)), MAT["pintura"], 0.012, 2)
        d.caixa(Vector((xa + 0.25, lado * (Wc / 2 + 0.022), H - 1.35)), Vector((0.16, 0.02, 0.03)), MAT["cromo"], 0.006, 1)
        objs.append(d.objeto())
        b.pintar(fc, lambda p, n, lado=lado: n.y * lado > 0.5 and xa + 0.02 < p.x < xb_ - 0.02 and z0 + 0.12 < p.z < H - 1.22, MAT["chassi"])
        # degraus e retrovisor
        b.caixa(Vector(((xa + xb_) / 2, lado * (Wc / 2 - 0.1), z0 - 0.2)), Vector((0.6, 0.25, 0.04)), MAT["chassi"], 0.01, 2)
        b.caixa(Vector(((xa + xb_) / 2, lado * (Wc / 2 - 0.2), z0 - 0.5)), Vector((0.5, 0.2, 0.04)), MAT["chassi"], 0.01, 2)
        b.tubo((x_front - 0.5, lado * (Wc / 2 - 0.02), H - 0.6), (x_front - 0.3, lado * (Wc / 2 + 0.40), H - 0.5), 0.02, MAT["chassi"])
        b.caixa(Vector((x_front - 0.3, lado * (Wc / 2 + 0.42), H - 0.75)), Vector((0.07, 0.12, 0.5)), MAT["chassi"], 0.02, 2)
    bf = Malha("bumper_front")
    bf.caixa(Vector((x_front + 0.05, 0, z0 - 0.02)), Vector((0.18, W - 0.05, 0.36)), MAT["chassi"], 0.05, 3)
    objs.append(bf.objeto())
    for lado, nome in ((1, "headlight_left"), (-1, "headlight_right")):
        objs.append(luz(nome, Vector((x_front + 0.15, lado * (W / 2 - 0.30), z0 - 0.02)), Vector((0.05, 0.30, 0.16)), MAT["luz"]))
    b.caixa(Vector((x_front + 0.145, 0, z0 - 0.02)), Vector((0.02, 0.40, 0.13)), MAT["bau"], 0.0, 1)
    # chassi: longarinas, tanque, eixos, para-lamas de trás
    for lado in (1, -1):
        b.caixa(Vector(((x_cab_rear + x_rear) / 2 + 0.3, lado * 0.45, z0 + 0.12)), Vector((x_cab_rear - x_rear + 0.6, 0.10, 0.24)), MAT["chassi"], 0.01, 2)
        b.arco_girado((xt, 0, R), R + 0.06, R + 0.09, *sorted((lado * (W / 2 - 0.5), lado * (W / 2 + 0.02))), 10, 170, MAT["chassi"])
    b.cilindro(Vector((x_cab_rear - 0.6, -W / 2 + 0.25, z0 - 0.15)), 0.26, 0.9, MAT["cinza"], "x", 18)
    for x in (xd, xt):
        b.cilindro(Vector((x, 0, R)), 0.08, W - 0.5, MAT["chassi"], "y", 12)
    interior_carro(b, x_front - 0.05, x_cab_rear, Wc, z0 + 0.03, H - 1.25, volante_y=0.7, bancos_tras=False)
    x_c0 = x_cab_rear - 0.12
    if sp["carga"] == "bau":
        zc0, zc1 = z0 + 0.3, sp.get("H_bau", 3.6)
        fb_ = b.loft([(x, ret_arredondado(W, zc1 - zc0, 0.08, 4, zc0, raio_baixo=0.03)) for x in (x_rear, x_c0)], MAT["bau"])
        b.pintar(fb_, lambda p, n: n.z < -0.6, MAT["chassi"])
        tr = Malha("trunk")
        tr.caixa(Vector((x_rear - 0.01, 0, (zc0 + zc1) / 2)), Vector((0.03, W - 0.2, zc1 - zc0 - 0.2)), MAT["bau"], 0.012, 2)
        tr.caixa(Vector((x_rear - 0.03, 0, (zc0 + zc1) / 2)), Vector((0.01, 0.03, zc1 - zc0 - 0.3)), MAT["chassi"])
        for y in (-0.6, 0.6):
            tr.caixa(Vector((x_rear - 0.04, y, (zc0 + zc1) / 2 - 0.3)), Vector((0.03, 0.04, 0.5)), MAT["cromo"], 0.008, 1)
        objs.append(tr.objeto())
    else:
        # caçamba basculante: chapas, nervuras, o cilindro hidráulico e a terra
        zc0 = z0 + 0.32
        alt = 0.95
        xb0, xb1 = x_rear + 0.05, x_c0 - 0.15
        b.caixa(Vector(((xb0 + xb1) / 2, 0, zc0 + 0.04)), Vector((xb1 - xb0, W - 0.1, 0.08)), MAT["cacamba"], 0.01, 2)
        for lado in (1, -1):
            b.caixa(Vector(((xb0 + xb1) / 2, lado * (W / 2 - 0.045), zc0 + alt / 2)), Vector((xb1 - xb0, 0.09, alt)), MAT["pintura"], 0.012, 2)
            b.caixa(Vector(((xb0 + xb1) / 2, lado * (W / 2 - 0.12), zc0 + alt / 2)), Vector((xb1 - xb0 - 0.1, 0.03, alt - 0.1)), MAT["cacamba"])
            for k in range(4):
                b.caixa(Vector((xb0 + 0.5 + k * (xb1 - xb0 - 1.0) / 3, lado * (W / 2 + 0.01), zc0 + alt / 2)), Vector((0.08, 0.03, alt - 0.05)), MAT["pintura"], 0.008, 1)
        b.caixa(Vector((xb1 + 0.03, 0, zc0 + alt / 2 + 0.15)), Vector((0.09, W - 0.1, alt + 0.3)), MAT["pintura"], 0.012, 2)
        b.caixa(Vector((xb1 - 0.03, 0, zc0 + alt / 2)), Vector((0.03, W - 0.3, alt - 0.1)), MAT["cacamba"])
        b.esfera(((xb0 + xb1) / 2, 0, zc0 + alt - 0.15), 1.0, MAT["terra"], 20, escala=((xb1 - xb0) / 2 - 0.1, W / 2 - 0.15, 0.45))
        b.tubo((xb1 + 0.3, 0, z0 + 0.2), (xb1 + 0.12, 0, zc0 + alt + 0.3), 0.09, MAT["cinza"], 16)
        b.tubo((xb1 + 0.3, 0, z0 + 0.2), (xb1 + 0.2, 0, zc0 + alt * 0.6), 0.12, MAT["chassi"], 16)
        tg = Malha("trunk")
        tg.caixa(Vector((xb0 - 0.02, 0, zc0 + alt / 2 + 0.02)), Vector((0.07, W - 0.14, alt)), MAT["pintura"], 0.012, 2)
        for lado in (1, -1):
            tg.caixa(Vector((xb0 - 0.02, lado * (W / 2 - 0.12), zc0 + alt + 0.03)), Vector((0.12, 0.08, 0.08)), MAT["chassi"], 0.01, 1)
        objs.append(tg.objeto())
        # para-barros
        for lado in (1, -1):
            b.caixa(Vector((xt - R - 0.12, lado * (W / 2 - 0.25), R - 0.05)), Vector((0.03, 0.45, 0.4)), MAT["chassi"])
    br = Malha("bumper_rear")
    br.caixa(Vector((x_rear - 0.04, 0, z0 - 0.15)), Vector((0.10, W - 0.3, 0.14)), MAT["chassi"], 0.03, 2)
    objs.append(br.objeto())
    for lado, nome in ((1, "taillight_left"), (-1, "taillight_right")):
        objs.append(luz(nome, Vector((x_rear - 0.09, lado * (W / 2 - 0.30), z0 - 0.15)), Vector((0.04, 0.28, 0.12)), MAT["luz_vermelha"]))
    objs.insert(0, b.objeto())
    for nome, x, lado in (("roda_fl", xd, 1), ("roda_fr", xd, -1), ("roda_rl", xt, 1), ("roda_rr", xt, -1)):
        objs.append(roda(nome, (x, lado * (W / 2 - 0.24), R), R, 0.28, lado, pesado=True, dupla=(x == xt)))
    return objs, {"portas": 2, "linha_de_cintura": round(H - 1.2, 3), "topo_da_saia": round(z0, 3), "van": True}


def moto(sp):
    """Moto urbana com o motociclista. sp: EE, R, cor."""
    EE, R = sp["EE"], sp["R"]
    xd, xt = EE / 2, -EE / 2
    objs = []
    b = Malha("body")
    # quadro
    cab = (xd - 0.22, 0, 0.86)                      # caixa de direção
    b.tubo(cab, (xt + 0.35, 0, 0.72), 0.022, MAT["chassi"])
    b.tubo(cab, (xd - 0.35, 0, 0.45), 0.022, MAT["chassi"])
    b.tubo((xd - 0.35, 0, 0.45), (xt + 0.25, 0, 0.42), 0.02, MAT["chassi"])
    b.tubo((xt + 0.35, 0, 0.72), (xt + 0.05, 0, 0.42), 0.02, MAT["chassi"])
    for lado in (1, -1):
        b.tubo((xt + 0.25, lado * 0.09, 0.42), (xt, lado * 0.09, R), 0.016, MAT["cinza"])          # balança
        b.tubo((xt + 0.3, lado * 0.09, 0.78), (xt + 0.02, lado * 0.09, R + 0.04), 0.013, MAT["cromo"])  # amortecedor
        b.tubo((xd - 0.18, lado * 0.085, 0.98), (xd, lado * 0.085, R), 0.018, MAT["cromo"])        # bengala
        b.tubo((xd - 0.18, lado * 0.085, 0.98), (xd - 0.08, lado * 0.085, 0.6), 0.03, MAT["chassi"])
    # motor, tanque, banco, carenagens
    b.caixa(Vector((xd - 0.55, 0, 0.50)), Vector((0.40, 0.34, 0.26)), MAT["cinza"], 0.02, 2)
    b.cilindro(Vector((xd - 0.45, 0, 0.70)), 0.08, 0.16, MAT["chassi"], "z", 14)
    b.esfera((xd - 0.60, 0, 0.84), 1.0, MAT["pintura"], 16, escala=(0.30, 0.19, 0.14))
    b.caixa(Vector((xt + 0.25, 0, 0.80)), Vector((0.62, 0.30, 0.09)), MAT["banco"], 0.03, 3)
    b.caixa(Vector((xt - 0.1, 0, 0.78)), Vector((0.30, 0.26, 0.06)), MAT["pintura"], 0.02, 2)        # rabeta
    b.arco_girado((xt, 0, R), R + 0.03, R + 0.05, -0.07, 0.07, 20, 140, MAT["pintura"])
    b.arco_girado((xd, 0, R), R + 0.03, R + 0.05, -0.07, 0.07, 30, 160, MAT["pintura"])
    b.tubo((xd - 0.5, -0.12, 0.42), (xt - 0.05, -0.14, 0.5), 0.03, MAT["cromo"])                   # escapamento
    b.cilindro(Vector((xt - 0.05, -0.14, 0.5)), 0.045, 0.1, MAT["chassi"], "x", 12)
    b.cilindro(Vector((xd - 0.22, 0, 1.02)), 0.014, 0.72, MAT["cromo"], "y", 10)                    # guidão
    for lado in (1, -1):
        b.cilindro(Vector((xd - 0.22, lado * 0.33, 1.02)), 0.018, 0.12, MAT["chassi"], "y", 10)
        b.caixa(Vector((xd - 0.26, lado * 0.25, 1.06)), Vector((0.05, 0.05, 0.1)), MAT["chassi"], 0.01, 1)   # retrovisor
        b.caixa(Vector((xd - 0.3, lado * 0.16, 0.36)), Vector((0.14, 0.05, 0.03)), MAT["chassi"])        # pedaleira
    b.caixa(Vector((xd - 0.1, 0, 0.96)), Vector((0.12, 0.26, 0.20)), MAT["pintura"], 0.03, 2)          # carenagem do farol
    b.caixa(Vector((xd - 0.12, 0, 1.08)), Vector((0.12, 0.14, 0.06)), MAT["chassi"], 0.01, 1)          # painel
    b.caixa(Vector((xt - 0.22, 0, 0.6)), Vector((0.02, 0.25, 0.12)), MAT["bau"], 0.0, 1)               # placa em branco
    # motociclista: capacete, tronco, braços, pernas
    INCL = Matrix.Rotation(math.radians(18), 4, "Y")
    b.esfera((xt + 0.45, 0, 1.45), 0.14, MAT["faixa"], 16)
    b.caixa(Vector((xt + 0.49, 0, 1.42)), Vector((0.1, 0.16, 0.08)), MAT["vidro_fixo"], 0.02, 2)      # viseira
    b.caixa(Vector((xt + 0.40, 0, 1.08)), Vector((0.28, 0.40, 0.46)), MAT["roupa"], 0.06, 3, INCL)
    for lado in (1, -1):
        b.tubo((xt + 0.42, lado * 0.21, 1.33), (xd - 0.26, lado * 0.31, 1.04), 0.045, MAT["roupa"])
        b.tubo((xt + 0.4, lado * 0.15, 0.92), (xd - 0.4, lado * 0.19, 0.78), 0.065, MAT["chassi"])    # coxa
        b.tubo((xd - 0.4, lado * 0.19, 0.78), (xd - 0.32, lado * 0.17, 0.42), 0.05, MAT["chassi"])    # canela
    objs.append(luz("headlight_left", Vector((xd - 0.03, 0, 0.96)), Vector((0.05, 0.18, 0.16)), MAT["luz"]))
    objs.append(luz("taillight_left", Vector((xt - 0.26, 0, 0.78)), Vector((0.04, 0.16, 0.06)), MAT["luz_vermelha"]))
    objs.insert(0, b.objeto())
    for x, pfx in ((xd, "f"), (xt, "r")):
        for lado, m in ((1, "l"), (-1, "r")):
            objs.append(roda("roda_%s%s" % (pfx, m), (x, 0, R), R, 0.13, lado, metade=m, aro_raio=0.72))
    return objs, {"portas": 0, "linha_de_cintura": 0.8, "topo_da_saia": 0.42, "van": False}


def tuktuk(sp):
    """Autorriquixá de 3 rodas: cuba verde, capota amarela, para-brisa, banco de trás."""
    EE, R, W = sp["EE"], sp["R"], sp["W"]
    xd, xt = EE / 2, -EE / 2
    objs = []
    b = Malha("body")
    z0 = 0.28
    zb = 0.78
    x_rear = xt - 0.45
    cuba = [(x_rear, 0.92 * W, z0 + 0.06, zb, 0.10), (x_rear + 0.12, W, z0, zb + 0.02, 0.10), (xt + 0.3, W, z0, zb + 0.02, 0.10),
            (xd - 0.5, W, z0, zb, 0.10), (xd - 0.25, 0.75 * W, z0 + 0.05, zb + 0.05, 0.14), (xd - 0.05, 0.45 * W, z0 + 0.12, zb + 0.12, 0.14),
            (xd + 0.12, 0.30 * W, z0 + 0.16, zb + 0.05, 0.08)]
    fb = b.loft([(x, ret_arredondado(w, z1 - zz0, r, 5, zz0, raio_baixo=0.03)) for x, w, zz0, z1, r in cuba], MAT["pintura"])
    b.pintar(fb, lambda p, n: n.z < -0.6, MAT["chassi"])
    b.pintar(fb, lambda p, n: abs(n.y) > 0.5 and xt + 0.35 < p.x < xd - 0.55 and p.z > z0 + 0.25, MAT["chassi"])   # a abertura de entrada
    # capota: teto, os quatro pilares e a parede de trás de lona
    H = 1.72
    b.loft([(x, ret_arredondado(w, 0.05, 0.02, 2, H)) for x, w in ((x_rear, W * 0.9), (x_rear + 0.1, W), (xd - 0.3, W), (xd - 0.1, W * 0.9))], MAT["faixa"])
    for x, y in ((x_rear + 0.1, W / 2 - 0.05), (x_rear + 0.1, -W / 2 + 0.05), (xd - 0.45, W / 2 - 0.05), (xd - 0.45, -W / 2 + 0.05)):
        b.tubo((x, y, zb), (x, y, H), 0.02, MAT["chassi"])
    b.caixa(Vector((x_rear + 0.06, 0, (zb + H) / 2)), Vector((0.04, W - 0.12, H - zb)), MAT["faixa"], 0.012, 2)
    b.caixa(Vector((x_rear + 0.04, 0, (zb + H) / 2 + 0.1)), Vector((0.02, W - 0.5, 0.4)), MAT["vidro_fixo"], 0.0, 1)
    vs = Malha("glass_windshield")
    vs.placa((xd - 0.4, -W / 2 + 0.12, zb + 0.08), (xd - 0.4, W / 2 - 0.12, zb + 0.08), (xd - 0.5, W / 2 - 0.1, H - 0.05), (xd - 0.5, -W / 2 + 0.1, H - 0.05), 0.012, MAT["vidro_fixo"], 0.01)
    objs.append(vs.objeto())
    # bancos, guidão, motorista no banco da frente (só o banco), medidor
    b.caixa(Vector((xt - 0.05, 0, zb - 0.22)), Vector((0.45, W - 0.2, 0.12)), MAT["banco"], 0.03, 3)
    b.caixa(Vector((xt - 0.28, 0, zb - 0.0)), Vector((0.1, W - 0.2, 0.5)), MAT["banco"], 0.03, 3)
    b.caixa(Vector((xd - 0.75, 0, zb - 0.25)), Vector((0.36, 0.42, 0.10)), MAT["banco"], 0.03, 3)
    b.caixa(Vector((xd - 0.95, 0, zb + 0.0)), Vector((0.08, 0.42, 0.45)), MAT["banco"], 0.03, 3)
    b.tubo((xd - 0.2, 0, zb), (xd - 0.35, 0, zb + 0.32), 0.02, MAT["chassi"])
    b.cilindro(Vector((xd - 0.35, 0, zb + 0.32)), 0.014, 0.62, MAT["cromo"], "y", 10)
    b.caixa(Vector((xd - 0.3, 0, zb + 0.22)), Vector((0.12, 0.2, 0.08)), MAT["painel"], 0.01, 1)
    b.cilindro(Vector((xd, 0, z0 + 0.1)), 0.02, 0.5, MAT["chassi"], "z", 8, rot=Matrix.Rotation(math.radians(20), 4, "Y"))   # a bengala da roda da frente
    b.arco_girado((xd, 0, R), R + 0.03, R + 0.05, -0.08, 0.08, 10, 170, MAT["pintura"])
    for lado in (1, -1):
        b.arco_girado((xt, 0, R), R + 0.03, R + 0.05, *sorted((lado * (W / 2 - 0.3), lado * (W / 2 + 0.06))), 0, 180, MAT["pintura"])
    b.cilindro(Vector((xt, 0, R)), 0.03, W - 0.4, MAT["chassi"], "y", 10)
    b.caixa(Vector((x_rear - 0.02, 0, zb - 0.3)), Vector((0.02, 0.22, 0.10)), MAT["bau"], 0.0, 1)   # placa em branco
    objs.append(luz("headlight_left", Vector((xd + 0.12, 0, zb + 0.0)), Vector((0.05, 0.16, 0.14)), MAT["luz"]))
    for lado, nome in ((1, "taillight_left"), (-1, "taillight_right")):
        objs.append(luz(nome, Vector((x_rear - 0.01, lado * (W / 2 - 0.18), zb - 0.15)), Vector((0.04, 0.12, 0.10)), MAT["luz_vermelha"]))
    objs.insert(0, b.objeto())
    for lado, m in ((1, "l"), (-1, "r")):
        objs.append(roda("roda_f" + m, (xd, 0, R), R, 0.10, lado, metade=m, aro_raio=0.6))
    for lado, m in ((1, "l"), (-1, "r")):
        objs.append(roda("roda_r" + m, (xt, lado * (W / 2 - 0.12), R), R, 0.11, lado, aro_raio=0.6))
    return objs, {"portas": 0, "linha_de_cintura": round(zb, 3), "topo_da_saia": round(z0, 3), "van": False}


# ================================================================================================================================
# a lista
# ================================================================================================================================
VEICULOS = {
    "onibus-urbano-12m": dict(f=onibus, L=12.0, W=2.5, H=3.25, EE=6.0, R=0.50, cor=(0.80, 0.80, 0.78), faixa=True, faixa_cor=(0.05, 0.25, 0.55),
                              porta_lado=-1, classe="bus", massa=11000, valor=9000,
                              titulo="Ônibus urbano de 12 m, branco com faixa azul na cintura, porta à direita"),
    "caminhao-bau": dict(f=caminhao, L=8.6, W=2.45, H=2.95, EE=4.4, R=0.50, carga="bau", cor=(0.10, 0.22, 0.45), classe="truck", massa=9000, valor=12000,
                         titulo="Caminhão baú de 2 eixos e cabine avançada, 8,6 m, cabine azul e baú branco"),
    "caminhao-basculante": dict(f=caminhao, L=7.6, W=2.45, H=2.95, EE=4.2, R=0.50, carga="bascula", cor=(0.85, 0.42, 0.05), classe="truck", massa=12000, valor=14000,
                                titulo="Caminhão basculante de 2 eixos com a caçamba carregada de terra, laranja"),
    "moto-urbana": dict(f=moto, EE=1.38, R=0.30, cor=(0.60, 0.05, 0.05), faixa_cor=(0.85, 0.85, 0.85), classe="moto", massa=180, valor=600,
                        titulo="Moto urbana de 150 cc com o motociclista (capacete branco), vermelha"),
    "picape-cabine-simples": dict(f=carro, tipo="picape", L=5.25, W=1.90, H=1.78, EE=3.05, R=0.36, portas=2, cor=(0.78, 0.78, 0.75), classe="pickup", massa=1800, valor=2200,
                                  titulo="Picape de cabine simples com caçamba aberta, prata"),
    "van-furgao": dict(f=carro, tipo="van", L=5.3, W=2.0, H=2.45, EE=3.3, R=0.35, portas=2, zb=1.05, cor=(0.86, 0.86, 0.84), classe="van", massa=2300, valor=2600,
                       titulo="Furgão de teto alto e carga fechada, branco"),
    "taxi-amarelo": dict(f=carro, tipo="sedan", L=4.85, W=1.85, H=1.47, EE=2.80, R=0.33, portas=4, cor=(0.95, 0.70, 0.04), taxi_sinal=True, classe="sedan", massa=1500, valor=1600,
                         cidades=["nova-york"], titulo="Sedã táxi amarelo com a luminária lisa no teto (Nova York)"),
    "taxi-branco-faixa": dict(f=carro, tipo="sedan", L=4.75, W=1.80, H=1.47, EE=2.70, R=0.32, portas=4, cor=(0.92, 0.92, 0.90), taxi_sinal=True,
                              faixa=(0.56, 0.66), faixa_cor=(0.70, 0.08, 0.06), classe="sedan", massa=1400, valor=1500, cidades=["sao-paulo"],
                              titulo="Sedã táxi branco com a faixa vermelha e a luminária no teto (São Paulo)"),
    "policia-sedan": dict(f=carro, tipo="sedan", L=4.95, W=1.88, H=1.50, EE=2.85, R=0.34, portas=4, cor=(0.92, 0.92, 0.92), barra_luz=True,
                          faixa=(0.52, 0.70), faixa_cor=(0.04, 0.10, 0.32), classe="sedan", massa=1700, valor=3000,
                          titulo="Sedã de polícia genérico: branco, faixa azul-escura e barra de luz vermelha e azul, sem brasão"),
    "ambulancia-van": dict(f=carro, tipo="van", L=5.6, W=2.05, H=2.55, EE=3.45, R=0.36, portas=2, zb=1.08, cor=(0.93, 0.93, 0.92), barra_luz=True,
                           faixa=(0.80, 0.98), faixa_cor=(0.72, 0.06, 0.05), classe="van", massa=3000, valor=5000,
                           titulo="Furgão ambulância genérico: branco, faixa vermelha e barra de luz, sem cruz nem símbolo"),
    "tuk-tuk": dict(f=tuktuk, EE=2.0, R=0.20, W=1.35, cor=(0.08, 0.35, 0.12), faixa_cor=(0.95, 0.75, 0.08), classe="compact", massa=400, valor=500,
                    cidades=["agra"], titulo="Autorriquixá de 3 rodas, cuba verde e capota amarela (Agra)"),
    "bonde-sf": dict(f=onibus, L=10.0, W=2.5, H=3.25, EE=5.8, R=0.33, bonde=True, cor=(0.08, 0.32, 0.18), faixa_cor=(0.92, 0.85, 0.62), classe="bus", massa=16000, valor=15000,
                     cidades=["sao-francisco"], titulo="Bonde urbano de um carro, verde e creme, com a vara do trole (São Francisco)"),
    "onibus-dois-andares": dict(f=onibus, L=10.6, W=2.5, H=4.4, EE=5.6, R=0.50, andares=2, cor=(0.72, 0.04, 0.03), porta_lado=1, classe="bus", massa=12500, valor=14000,
                                cidades=["londres"], titulo="Ônibus vermelho de dois andares, porta à esquerda (Londres)"),
    "taxi-londres": dict(f=carro, tipo="londres", L=4.6, W=1.90, H=1.80, EE=2.75, R=0.32, portas=4, zb=0.95, cor=(0.015, 0.015, 0.016), taxi_sinal=True,
                         classe="sedan", massa=1900, valor=2400, cidades=["londres"], titulo="Táxi preto de cabine alta com a luminária (Londres)"),
    "kei-car": dict(f=carro, tipo="hatch", L=3.4, W=1.48, H=1.66, EE=2.45, R=0.27, portas=4, zb=0.78, cor=(0.78, 0.84, 0.88), classe="compact", massa=850, valor=700,
                    cidades=["toquio"], titulo="Carro pequeno e alto de 3,4 m (kei car), azul-claro (Tóquio)"),
}


def gerar(cid):
    global cena, MAT
    sp = VEICULOS[cid]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cena = bpy.context.scene
    MAT = materiais(sp["cor"], sp.get("faixa_cor", (0.70, 0.08, 0.06)))
    objs, med = sp["f"](sp)
    fontes = os.path.join(OUT, "fontes")
    corte = os.path.join(OUT, "quebravel", cid)
    os.makedirs(fontes, exist_ok=True); os.makedirs(corte, exist_ok=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(fontes, cid + ".blend"), compress=True)
    if not SEM_GLB:
        bpy.ops.export_scene.gltf(filepath=os.path.join(fontes, cid + ".glb"), export_format="GLB", export_yup=True)
    nomes = [o.name for o in objs]
    pecas = [{"nome": n, "objetos": "^%s$" % n} for n in nomes if n not in ("body",) and not n.startswith(("roda_", "glass_"))]
    vidros = [{"nome": n, "objetos": "^%s$" % n} for n in nomes if n.startswith("glass_")]
    cfg = {"id": cid, "fonte": os.path.relpath(os.path.join(fontes, cid + ".blend"), RAIZ).replace(os.sep, "/"), "frente": "+x", "escala": 1.0,
           "rodas": "^roda_", "pecas": pecas, "vidros": vidros,
           "materiais": {"^tv_(chassi|banco|painel|vidro_fixo|faixa|cacamba|bau|roupa|terra)": "chassi", "^tv_luz": "luz", "^tv_cromo": "cromado", "^tv_pneu": "pneu"},
           "pintura_rgb": [round(c, 4) for c in sp["cor"]], "medidas": med,
           "notas": "%s. Veículo de tráfego do Detonauto feito por ferramentas/veiculo_trafego.py (CC0 do estúdio, sem marca, sem texto, sem IA); "
                    "classe de tráfego '%s'%s." % (sp["titulo"], sp["classe"], ("; só em " + ", ".join(sp["cidades"])) if sp.get("cidades") else "")}
    json.dump(cfg, open(os.path.join(corte, cid + "_config.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tri = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in objs)
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for o in objs:
        for v in o.data.vertices:
            mn = Vector(map(min, mn, v.co)); mx = Vector(map(max, mx, v.co))
    print("[trafego] %s: %.2f x %.2f x %.2f m, %d objetos, %d triângulos" % (cid, mx.x - mn.x, mx.y - mn.y, mx.z, len(objs), tri))


ids = list(VEICULOS) if "todos" in PEDIDOS else PEDIDOS
for cid in ids:
    if cid not in VEICULOS:
        raise SystemExit("veículo desconhecido: %s (há %s)" % (cid, ", ".join(VEICULOS)))
    gerar(cid)
