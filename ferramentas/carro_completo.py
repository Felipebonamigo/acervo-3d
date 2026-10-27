"""
Carro completo: gera, para um carro do acervo já cortado pelo carro_quebravel.py, as partes que faltam para ele ficar completo por
dentro e por baixo (pedido do Felipe de 26/10/2026, Detonauto/docs/pedido-carro-completo.md: "o carro tem que ser real, com as partes
internas, externas, TUDO COMPLETO"), encaixadas nas medidas DELE.

Uso (Blender 5.2 ou o módulo bpy num venv; a parte de medidas roda em Python puro):

    python -I ferramentas/carro_completo.py -- --corte <pasta do corte> --id <carro> --out <pasta> [opções]
    blender -b --python-exit-code 1 -P ferramentas/carro_completo.py -- --corte <pasta> --id <carro> --out <pasta>

    --corte <pasta>      pasta com <id>_mapa.json e <id>_wheels.json (veiculos/meshy-conta/quebravel/<id>/); se tiver também o
                         <id>.glb do carro_quebravel (saída completa, regerada em ~2,5 min), as peças são assentadas na casca por
                         raios (forro do teto, forro de porta, acabamentos laterais, capô) e as prévias saem com o carro
    --glb <arquivo>      o <id>.glb do corte, se não estiver na pasta --corte
    --dados <json>       tabela de carros e épocas (padrão: ferramentas/carro_completo_dados.json)
    --epoca 70|80|90|2000, --motor l4_transversal|l4_longitudinal|v8_longitudinal|boxer_traseiro   forçam o que a tabela diz
    --amostras <n>       amostras do Cycles nas prévias (padrão 24)
    --sem-previa         não renderiza
    --so-medidas         só imprime as medidas derivadas (não precisa do bpy)

Saída em --out:
    <id>_completo.glb        as peças novas no espaço do carro do corte, um objeto por peça, e as mesmas peças simplificadas
                             (LOD1, ~30 % dos triângulos, sufixo _LOD1) no mesmo arquivo, para as texturas não irem duas vezes
    <id>_completo.json       peças (grupo, peça do kit que ela segue, triângulos, caixa, materiais), medidas derivadas, época, e os
                             vãos (caixas) onde a casca escura MI_DNVao do corte deve sair quando o kit entra
    <id>_porta.jpg, _porta_solta.jpg, _cabine.jpg, _painel.jpg, _motor.jpg (_capo.jpg no motor traseiro), _baixo.jpg
                             prévias em Cycles na CPU (com --glb)

Convenções do carro_quebravel/Detonauto: metros, frente +X, ESQUERDA +Y, cima +Z, chão em z = 0, origem entre os eixos. Volante à
esquerda (Brasil). Nomes no padrão do kit de quebra: interior_*, door_card_<pos>_*, jamb_<pos>_*, engine_*, under_*, brake_<pos>_*.
Peças que andam com uma peça do corte dizem qual em "segue" (forro de porta com door_fl, disco e cubo girando com a roda, pinça na
manga). Tudo é geometria e textura próprias deste script: licença CC0 do estúdio, sem marca, sem logo, sem texto.
"""

import json
import math
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "carro_completo_dados.json")
EPOCAS = ("70", "80", "90", "2000")
MOTORES = ("l4_transversal", "l4_longitudinal", "v8_longitudinal", "boxer_traseiro")
TEX = 256              # lado das texturas assadas (px)
LOD1_RAZAO = 0.3       # fração dos triângulos no LOD1


# ================================================================================================================================
# Parte pura (sem bpy): medidas do carro a partir do corte
# ================================================================================================================================

def ler_corte(pasta, cid):
    """Lê <id>_mapa.json, <id>_wheels.json e, se houver, <id>_pecas.json da pasta do corte."""
    def ler(nome, obrigatorio=True):
        arq = os.path.join(pasta, f"{cid}_{nome}.json")
        if not os.path.isfile(arq):
            if obrigatorio:
                raise FileNotFoundError(arq)
            return None
        with open(arq, encoding="utf-8") as f:
            return json.load(f)
    return {"mapa": ler("mapa"), "wheels": ler("wheels", False), "pecas": ler("pecas", False)}


def ler_dados(caminho=DADOS):
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def config_carro(dados, cid, epoca=None, motor=None):
    """Época e mecânica do carro (tabela + linha de comando). Devolve (cfg, estilo da época, avisos)."""
    avisos = []
    cfg = dict(dados["padrao"])
    if cid in dados["carros"]:
        cfg.update(dados["carros"][cid])
    else:
        avisos.append(f"{cid} fora da tabela de carros: usei o padrão ({cfg['epoca']}, {cfg['motor']})")
    if epoca:
        cfg["epoca"] = str(epoca)
    if motor:
        cfg["motor"] = motor
    if cfg["epoca"] not in EPOCAS:
        raise ValueError(f"época {cfg['epoca']} fora de {EPOCAS}")
    if cfg["motor"] not in MOTORES:
        raise ValueError(f"motor {cfg['motor']} fora de {MOTORES}")
    return cfg, dados["epocas"][cfg["epoca"]], avisos


def _limitar(v, a, b):
    return max(a, min(b, v))


def caixas_do_mapa(mapa):
    """{nome: [xmin, xmax, ymin, ymax, zmin, zmax]} das peças com caixa; rodas por posição."""
    caixas, rodas = {}, {}
    for p in mapa["parts"]:
        if "box" in p:
            caixas[p["name"]] = p["box"]
        if p.get("take") == "roda" and p.get("papel") == "wheel":
            pos = p["name"].split("_")[1]
            y0, y1 = p["y"]
            rodas[pos] = {"x": p["centro"][0], "z": p["centro"][2], "lado": p["lado"], "y_dentro": y0, "y_fora": y1,
                          "y_meio": (y0 + y1) / 2.0}
    return caixas, rodas


def medidas(corte, cfg=None):
    """
    Medidas derivadas do carro para encaixar as peças (metros, espaço do carro). Só usa os JSON do corte:
    cabine pela caixa dos vidros e do teto, entre-eixos e bitola pelas rodas, vão do motor pelo capô, porta-malas pela tampa.
    """
    cfg = cfg or {}
    mapa = corte["mapa"]
    med = mapa["medidas"]
    cx, rodas = caixas_do_mapa(mapa)
    W = med["meia_largura"]
    H = med["altura"]
    R = med["raio_roda"]
    xd, xt = med["eixo_dianteiro"], med["eixo_traseiro"]
    wh = corte.get("wheels")
    if wh:
        xd, xt = wh["front_axle_cm"] / 100.0, wh["rear_axle_cm"] / 100.0
        R = wh["wheel_radius_cm"] / 100.0
    M = {"id": mapa.get("car"), "W": W, "H": H, "R": R, "xd": xd, "xt": xt, "entre_eixos": xd - xt,
         "comprimento": med["comprimento"], "portas": med.get("portas", 2)}

    # rodas: bitola (centro da banda de rodagem) e face de dentro do pneu, por eixo
    def eixo(pfx):
        rs = [r for k, r in rodas.items() if k.startswith(pfx)]
        if not rs:
            return 0.62 * W * 2, W - 0.24
        return sum(r["y_meio"] for r in rs) / len(rs) * 2.0, min(r["y_dentro"] for r in rs)
    M["bitola_d"], M["y_pneu_dentro_d"] = eixo("f")
    M["bitola_t"], M["y_pneu_dentro_t"] = eixo("r")
    M["rodas"] = {k: {"x": r["x"], "z": r["z"], "lado": r["lado"], "y_dentro": r["y_dentro"], "y_fora": r["y_fora"]}
                  for k, r in sorted(rodas.items())}

    # pontas
    bf, bt = cx.get("bumper_front"), cx.get("bumper_rear")
    M["x_frente"] = (bf[1] - 0.05) if bf else xd + 0.45 * med["comprimento"] / 2
    M["x_tras"] = (bt[0] + 0.05) if bt else xt - 0.45 * med["comprimento"] / 2

    # alturas
    M["z_saia"] = med["topo_da_saia"]
    M["z_cintura"] = med["linha_de_cintura"]
    M["z_piso"] = _limitar(M["z_saia"] - 0.10, 0.62 * R, M["z_saia"] - 0.04)
    M["z_teto"] = H

    # vidros: para-brisa, traseiro, laterais
    ws = cx.get("glass_windshield") or [xd - 0.95, xd - 0.30, -W + 0.15, W - 0.15, M["z_cintura"], H - 0.05]
    rg = cx.get("glass_rear") or [xt - 0.55, xt + 0.10, -W + 0.2, W - 0.2, M["z_cintura"], H - 0.08]
    M["ws"], M["rg"] = ws, rg
    M["x_corta_fogo"] = ws[1] - 0.03
    M["z_painel"] = ws[4] - 0.005
    M["prof_painel"] = _limitar(0.30 + 0.25 * (ws[1] - ws[0]), 0.36, 0.55)
    M["x_painel"] = ws[1] - M["prof_painel"]
    M["meia_interna"] = W - 0.13
    M["meia_teto"] = W - 0.22
    M["z_teto_int"] = H - 0.06
    M["x_teto_frente"] = ws[0] + 0.02
    M["x_teto_tras"] = rg[1] - 0.02
    M["inclinacao_para_brisa"] = (ws[1] - ws[0]) / max(0.05, ws[5] - ws[4])

    # bancos
    cb = med.get("coluna_b", xt + 0.4 * M["entre_eixos"])
    M["coluna_b"] = cb
    M["coluna_a"] = med.get("coluna_a", ws[1] - 0.2)
    M["x_encosto_d"] = min(cb + 0.02, M["x_corta_fogo"] - 1.05)
    M["x_encosto_t"] = _limitar(xt + 0.05, rg[0] + 0.12, M["x_encosto_d"] - 0.75)
    M["y_banco"] = max(0.27, M["meia_interna"] - 0.36)
    M["z_assento"] = M["z_piso"] + 0.26
    M["z_assento_t"] = M["z_piso"] + 0.24

    # portas: caixa do corte, vidro da mesma posição para a altura da janela
    portas = {}
    for nome, b in cx.items():
        if nome.startswith("door_") and len(nome) == 7:
            pos = nome[5:]
            vid = cx.get("glass_door_" + pos)
            portas[pos] = {"x0": b[0], "x1": b[1], "z0": max(b[4], M["z_saia"]), "z1": b[5], "lado": 1 if pos[1] == "l" else -1,
                           "z_janela": (vid[5] if vid else H - 0.08), "x_vidro": ([vid[0], vid[1]] if vid else [b[0], b[1]])}
    M["portas"] = dict(sorted(portas.items()))

    # vão do motor e porta-malas: capô e tampa
    hood, trunk = cx.get("hood"), cx.get("trunk")
    motor_tras = cfg.get("motor") == "boxer_traseiro"
    M["motor_traseiro"] = motor_tras
    fr = hood or [M["x_corta_fogo"], M["x_frente"], -W + 0.2, W - 0.2, M["z_saia"], H]
    tr = trunk or [M["x_tras"], M["x_encosto_t"], -W + 0.2, W - 0.2, M["z_saia"], H]
    M["tampa_frente"], M["tampa_tras"] = fr, tr
    y_caixa_d = min(M["y_pneu_dentro_d"] - 0.04, W - 0.18)
    y_caixa_t = min(M["y_pneu_dentro_t"] - 0.04, W - 0.18)
    M["y_caixa_d"], M["y_caixa_t"] = y_caixa_d, y_caixa_t
    # altura da tampa da frente na emenda com o para-brisa e na ponta (sem a casca, pela caixa dos vidros e dos faróis)
    hl = cx.get("headlight_left") or cx.get("headlight_right")
    z_frente_topo = (hl[5] if hl else med.get("topo_para_choque_dianteiro", 0.5) + 0.25)
    M["z_capo_tras"] = ws[4] - 0.03
    M["z_capo_frente"] = max(z_frente_topo, med.get("topo_para_choque_dianteiro", 0.45) + 0.12)
    M["x_radiador"] = M["x_frente"] - 0.20
    tl = cx.get("taillight_left") or cx.get("taillight_right")
    M["z_tampa_tras_borda"] = (tl[4] - 0.02) if tl else med.get("topo_para_choque_traseiro", 0.5) + 0.05
    if cfg.get("carroceria") == "hatch":
        M["z_mala"] = M["z_piso"] + 0.08
    else:
        M["z_mala"] = min(M["z_piso"] + 0.15, med.get("topo_para_choque_traseiro", 0.5) - 0.03)
    M["x_mala_frente"] = M["x_encosto_t"] - 0.10
    M["x_mala_tras"] = M["x_tras"] + 0.14

    # caixas onde a casca escura do corte (MI_DNVao) sai quando o kit entra
    vaos = {"cabine": [M["x_encosto_t"] - 0.30, M["x_corta_fogo"] + 0.03, -W - 0.06, W + 0.06, M["z_saia"] - 0.03, H + 0.05]}
    vaos["traseira"] = [M["x_tras"] - 0.05, M["x_encosto_t"] - 0.30, -W - 0.06, W + 0.06, M["z_mala"] - 0.05, H + 0.05]
    vaos["frente"] = [M["x_corta_fogo"] + 0.03, M["x_frente"] + 0.05, -fr[3] - 0.02, fr[3] + 0.02, M["z_saia"] - 0.15, H + 0.05]
    M["vaos"] = vaos
    # fundo liso da casca do Meshy (sob o assoalho e o motor): sai quando o kit entra, para o embaixo aparecer
    M["fundo"] = {"caixa": [M["x_tras"] + 0.12, M["x_frente"] - 0.12, -(W - 0.05), W - 0.05, -0.2, M["z_piso"] + 0.03],
                  "normal_z_max": -0.6, "pecas": ["body"]}

    # sanidade
    av = []
    if M["x_painel"] - M["x_encosto_d"] < 0.55:
        av.append(f"pouco espaço entre o painel e o banco ({M['x_painel'] - M['x_encosto_d']:.2f} m)")
    if M["z_piso"] < 0.12:
        av.append(f"assoalho baixo demais ({M['z_piso']:.2f} m)")
    if M["z_teto_int"] - M["z_assento"] < 0.80:
        av.append(f"pouca altura de cabine ({M['z_teto_int'] - M['z_assento']:.2f} m)")
    M["avisos"] = av
    return M


def resumo(M):
    linhas = [f"{M['id']}: entre-eixos {M['entre_eixos']:.3f} m, bitola {M['bitola_d']:.3f}/{M['bitola_t']:.3f} m, roda R {M['R']:.3f}",
              f"  piso {M['z_piso']:.3f}, saia {M['z_saia']:.3f}, cintura {M['z_cintura']:.3f}, teto {M['z_teto']:.3f}",
              f"  corta-fogo x {M['x_corta_fogo']:.3f}, painel x {M['x_painel']:.3f} (prof {M['prof_painel']:.2f}), "
              f"encosto dianteiro x {M['x_encosto_d']:.3f}, traseiro x {M['x_encosto_t']:.3f}, banco y ±{M['y_banco']:.3f}",
              "  portas: " + ", ".join(f"{k} x[{p['x0']:.2f},{p['x1']:.2f}] z[{p['z0']:.2f},{p['z1']:.2f}] janela {p['z_janela']:.2f}"
                                        for k, p in M["portas"].items()),
              f"  porta-malas x[{M['x_mala_tras']:.2f},{M['x_mala_frente']:.2f}] z {M['z_mala']:.2f}; radiador x {M['x_radiador']:.2f}"]
    for a in M["avisos"]:
        linhas.append("  AVISO: " + a)
    return "\n".join(linhas)


# ================================================================================================================================
# Blender: geometria
# ================================================================================================================================

def _bl():
    import bmesh  # noqa: F401
    import bpy  # noqa: F401
    from mathutils import Matrix, Vector  # noqa: F401
    return True


def V(*a):
    from mathutils import Vector
    if len(a) == 1:
        return Vector(a[0])
    return Vector(a)


def T(x, y, z):
    from mathutils import Matrix
    return Matrix.Translation((x, y, z))


def Rx(a):
    from mathutils import Matrix
    return Matrix.Rotation(a, 4, "X")


def Ry(a):
    from mathutils import Matrix
    return Matrix.Rotation(a, 4, "Y")


def Rz(a):
    from mathutils import Matrix
    return Matrix.Rotation(a, 4, "Z")


def S(x, y, z):
    from mathutils import Matrix
    return Matrix.Diagonal((x, y, z, 1.0))


def alinhar_z(d):
    """Matriz de rotação que leva o eixo Z local para a direção d."""
    from mathutils import Vector
    d = Vector(d).normalized()
    return d.to_track_quat("Z", "Y").to_matrix().to_4x4()


def _se(c, e):
    return math.copysign(abs(c) ** e, c)


class Peca:
    """Uma peça do kit: um bmesh com materiais por nome. As primitivas criam direto no espaço do carro (matriz M)."""

    def __init__(self, nome, grupo, segue=None, nota=None):
        import bmesh
        self.nome, self.grupo, self.segue, self.nota = nome, grupo, segue, nota
        self.bm = bmesh.new()
        self.mats = []
        self.fix = self.bm.faces.layers.int.new("uvfix")
        self.uv = self.bm.loops.layers.uv.new("UVMap")

    def m(self, nome):
        if nome not in self.mats:
            self.mats.append(nome)
        return self.mats.index(nome)

    # -- utilidades --------------------------------------------------------------------------------------------------------------
    def _mat(self, faces, mat):
        mi = self.m(mat)
        for f in faces:
            f.material_index = mi

    def caixa(self, mat, M, sx, sy, sz, ch=0.006, seg=2):
        """Caixa centrada na origem local com arestas chanfradas (ch em metros, antes da matriz)."""
        import bmesh
        t = bmesh.new()
        bmesh.ops.create_cube(t, size=1.0, matrix=S(sx, sy, sz))
        c = min(ch, 0.45 * min(sx, sy, sz))
        if c > 0:
            bmesh.ops.bevel(t, geom=list(t.edges), offset=c, offset_type="OFFSET", segments=seg, profile=0.5,
                            affect="EDGES", clamp_overlap=True)
        return self._copiar(t, M, mat)

    def _copiar(self, t, M, mat):
        """Copia o bmesh temporário t (transformado por M) para a peça, com o material."""
        mi = self.m(mat)
        mapa = {}
        for v in t.verts:
            mapa[v] = self.bm.verts.new(M @ v.co)
        fs = []
        for f in t.faces:
            try:
                nf = self.bm.faces.new([mapa[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = mi
            fs.append(nf)
        t.free()
        return fs

    def almofada(self, mat, M, sx, sy, sz, e1=0.32, e2=0.32, nu=24, nv=14):
        """Superelipsoide (estofado, borda macia): tamanho total sx, sy, sz centrado na origem local."""
        bm = self.bm
        a, b, c = sx / 2, sy / 2, sz / 2
        topo = bm.verts.new(M @ V(0, 0, c))
        base = bm.verts.new(M @ V(0, 0, -c))
        aneis = []
        for i in range(1, nv):
            v = -math.pi / 2 + math.pi * i / nv
            anel = []
            for j in range(nu):
                u = -math.pi + 2 * math.pi * j / nu
                p = V(a * _se(math.cos(v), e1) * _se(math.cos(u), e2), b * _se(math.cos(v), e1) * _se(math.sin(u), e2),
                      c * _se(math.sin(v), e1))
                anel.append(bm.verts.new(M @ p))
            aneis.append(anel)
        fs = []
        for j in range(nu):
            fs.append(bm.faces.new((base, aneis[0][(j + 1) % nu], aneis[0][j])))
            fs.append(bm.faces.new((topo, aneis[-1][j], aneis[-1][(j + 1) % nu])))
        for i in range(len(aneis) - 1):
            for j in range(nu):
                fs.append(bm.faces.new((aneis[i][j], aneis[i][(j + 1) % nu], aneis[i + 1][(j + 1) % nu], aneis[i + 1][j])))
        self._mat(fs, mat)
        return fs

    def revolucao(self, mat, M, perfil, seg=32, a0=0.0, a1=2 * math.pi):
        """Sólido de revolução em torno do Z local: perfil [(r, z), ...]; r = 0 nas pontas fecha num vértice."""
        bm = self.bm
        cheio = abs(a1 - a0 - 2 * math.pi) < 1e-6
        n = seg if cheio else seg + 1
        aneis = []
        for r, z in perfil:
            if r <= 1e-6:
                aneis.append([bm.verts.new(M @ V(0, 0, z))])
            else:
                aneis.append([bm.verts.new(M @ V(r * math.cos(a0 + (a1 - a0) * j / seg), r * math.sin(a0 + (a1 - a0) * j / seg), z))
                              for j in range(n)])
        fs = []
        for i in range(len(aneis) - 1):
            A, B = aneis[i], aneis[i + 1]
            for j in range(seg if cheio else seg):
                j1 = (j + 1) % n if cheio else j + 1
                if len(A) == 1 and len(B) == 1:
                    continue
                if len(A) == 1:
                    fs.append(bm.faces.new((A[0], B[j], B[j1])))
                elif len(B) == 1:
                    fs.append(bm.faces.new((A[j], B[0], A[j1])))
                else:
                    fs.append(bm.faces.new((A[j], A[j1], B[j1], B[j])))
        self._mat(fs, mat)
        return fs

    def cilindro(self, mat, M, r, h, seg=24, ch=0.0, r2=None):
        """Cilindro (ou tronco) no Z local, centrado, com borda chanfrada pelo perfil."""
        r2 = r if r2 is None else r2
        c = min(ch, 0.45 * min(r, r2), 0.45 * h)
        if c > 0:
            p = [(0, -h / 2), (r - c, -h / 2), (r - c * 0.3, -h / 2 + c * 0.3), (r, -h / 2 + c), (r2, h / 2 - c),
                 (r2 - c * 0.3, h / 2 - c * 0.3), (r2 - c, h / 2), (0, h / 2)]
        else:
            p = [(0, -h / 2), (r, -h / 2), (r2, h / 2), (0, h / 2)]
        return self.revolucao(mat, M, p, seg)

    def toro(self, mat, M, R, rr, rz=None, seg=48, segm=12, a0=0.0, a1=2 * math.pi):
        """Toro no plano XY local (aro de volante, anel de saída de ar); seção elíptica rr x rz."""
        bm = self.bm
        rz = rr if rz is None else rz
        cheio = abs(a1 - a0 - 2 * math.pi) < 1e-6
        n = seg if cheio else seg + 1
        aneis = []
        for i in range(n):
            t = a0 + (a1 - a0) * i / seg
            c, s = math.cos(t), math.sin(t)
            anel = []
            for j in range(segm):
                q = 2 * math.pi * j / segm
                rad = R + rr * math.cos(q)
                anel.append(bm.verts.new(M @ V(rad * c, rad * s, rz * math.sin(q))))
            aneis.append(anel)
        fs = []
        for i in range(seg):
            A, B = aneis[i], aneis[(i + 1) % n]
            for j in range(segm):
                fs.append(bm.faces.new((A[j], B[j], B[(j + 1) % segm], A[(j + 1) % segm])))
        if not cheio:
            for anel in (aneis[0], aneis[-1]):
                fs.append(bm.faces.new(anel))
        self._mat(fs, mat)
        return fs

    def tubo(self, mat, pts, r, seg=10, sub=4, tampa=True, raios=None):
        """Tubo por uma polilinha (suavizada por Catmull-Rom), com quadros por transporte paralelo."""
        from mathutils import Vector
        bm = self.bm
        P = [Vector(p) for p in pts]
        if sub > 1 and len(P) > 2:
            Q = []
            for i in range(len(P) - 1):
                p0, p1, p2, p3 = P[max(i - 1, 0)], P[i], P[i + 1], P[min(i + 2, len(P) - 1)]
                for k in range(sub):
                    t = k / sub
                    t2, t3 = t * t, t * t * t
                    Q.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
            Q.append(P[-1])
            P = Q
        rs = raios or [r] * len(pts)
        if len(rs) != len(P):
            rs = [rs[min(int(i * (len(rs) - 1) / max(1, len(P) - 1) + 0.5), len(rs) - 1)] for i in range(len(P))]
        tang = []
        for i in range(len(P)):
            a, b = P[max(i - 1, 0)], P[min(i + 1, len(P) - 1)]
            tang.append((b - a).normalized())
        ref = Vector((0, 0, 1)) if abs(tang[0].z) < 0.9 else Vector((1, 0, 0))
        n = tang[0].cross(ref).normalized()
        aneis = []
        for i, p in enumerate(P):
            if i > 0:
                ax = tang[i - 1].cross(tang[i])
                if ax.length > 1e-6:
                    ang = tang[i - 1].angle(tang[i])
                    from mathutils import Matrix
                    n = (Matrix.Rotation(ang, 3, ax.normalized()) @ n).normalized()
            b = tang[i].cross(n)
            anel = [bm.verts.new(p + rs[i] * (math.cos(2 * math.pi * j / seg) * n + math.sin(2 * math.pi * j / seg) * b))
                    for j in range(seg)]
            aneis.append(anel)
        fs = []
        for i in range(len(aneis) - 1):
            A, B = aneis[i], aneis[i + 1]
            for j in range(seg):
                fs.append(bm.faces.new((A[j], A[(j + 1) % seg], B[(j + 1) % seg], B[j])))
        if tampa:
            fs.append(bm.faces.new(list(reversed(aneis[0]))))
            fs.append(bm.faces.new(aneis[-1]))
        self._mat(fs, mat)
        return fs

    def fita(self, mat, pts, larg, esp, normal):
        """Fita (cinto, correia): seção retangular larg x esp ao longo da polilinha; 'normal' é a direção da espessura."""
        from mathutils import Vector
        bm = self.bm
        P = [Vector(p) for p in pts]
        nrm = Vector(normal).normalized()
        aneis = []
        for i, p in enumerate(P):
            t = (P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]).normalized()
            lado = t.cross(nrm).normalized()
            nn = lado.cross(t).normalized()
            h, e = lado * larg / 2, nn * esp / 2
            aneis.append([bm.verts.new(p + h + e), bm.verts.new(p - h + e), bm.verts.new(p - h - e), bm.verts.new(p + h - e)])
        fs = []
        for i in range(len(aneis) - 1):
            A, B = aneis[i], aneis[i + 1]
            for j in range(4):
                fs.append(bm.faces.new((A[j], A[(j + 1) % 4], B[(j + 1) % 4], B[j])))
        fs.append(bm.faces.new(list(reversed(aneis[0]))))
        fs.append(bm.faces.new(aneis[-1]))
        self._mat(fs, mat)
        return fs

    def prisma(self, mat, M, poli, esp, ch=0.0, seg=2):
        """Polígono no plano XY local (lista de (u, v), anti-horário) extrudado em Z de 0 a esp, com chanfro."""
        import bmesh
        t = bmesh.new()
        base = [t.verts.new(V(u, v, 0)) for u, v in poli]
        topo = [t.verts.new(V(u, v, esp)) for u, v in poli]
        t.faces.new(list(reversed(base)))
        t.faces.new(topo)
        n = len(poli)
        for i in range(n):
            t.faces.new((base[i], base[(i + 1) % n], topo[(i + 1) % n], topo[i]))
        if ch > 0:
            t.normal_update()
            vivas = [e for e in t.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > math.radians(28)]
            bmesh.ops.bevel(t, geom=vivas, offset=ch, offset_type="OFFSET", segments=seg, profile=0.5,
                            affect="EDGES", clamp_overlap=True)
        return self._copiar(t, M, mat)

    def grade(self, mat, nu, nv, ponto, esp, normal_fn=None, bordas=True):
        """
        Chapa de espessura esp sobre uma superfície paramétrica ponto(u, v) -> Vector, u e v em [0, 1]; a espessura vai no sentido
        de normal_fn(u, v) (padrão: a normal da grade). Usada no carpete, forros, assoalho.
        """
        from mathutils import Vector
        bm = self.bm
        cima, baixo = [], []
        for i in range(nu + 1):
            lc, lb = [], []
            for j in range(nv + 1):
                u, v = i / nu, j / nv
                p = ponto(u, v)
                if normal_fn:
                    n = Vector(normal_fn(u, v)).normalized()
                else:
                    du = ponto(min(u + 1e-3, 1), v) - ponto(max(u - 1e-3, 0), v)
                    dv = ponto(u, min(v + 1e-3, 1)) - ponto(u, max(v - 1e-3, 0))
                    n = du.cross(dv).normalized()
                lc.append(bm.verts.new(p))
                lb.append(bm.verts.new(p - n * esp))
            cima.append(lc)
            baixo.append(lb)
        fs = []
        for i in range(nu):
            for j in range(nv):
                fs.append(bm.faces.new((cima[i][j], cima[i + 1][j], cima[i + 1][j + 1], cima[i][j + 1])))
                fs.append(bm.faces.new((baixo[i][j], baixo[i][j + 1], baixo[i + 1][j + 1], baixo[i + 1][j])))
        if bordas:
            borda = [(i, 0) for i in range(nu)] + [(nu, j) for j in range(nv)] + [(i, nv) for i in range(nu, 0, -1)] + \
                    [(0, j) for j in range(nv, 0, -1)]
            for k in range(len(borda)):
                (i0, j0), (i1, j1) = borda[k], borda[(k + 1) % len(borda)]
                fs.append(bm.faces.new((cima[i1][j1], cima[i0][j0], baixo[i0][j0], baixo[i1][j1])))
        self._mat(fs, mat)
        return fs

    def disco_uv(self, mat, M, r, seg=48):
        """Disco plano no XY local com UV radial ocupando a imagem toda (mostradores, alto-falante)."""
        bm = self.bm
        c = bm.verts.new(M @ V(0, 0, 0))
        anel = [bm.verts.new(M @ V(r * math.cos(2 * math.pi * j / seg), r * math.sin(2 * math.pi * j / seg), 0)) for j in range(seg)]
        fs = []
        for j in range(seg):
            f = bm.faces.new((c, anel[j], anel[(j + 1) % seg]))
            f[self.fix] = 1
            for lp in f.loops:
                p = M.inverted() @ lp.vert.co
                lp[self.uv].uv = (0.5 + 0.5 * p.x / r, 0.5 + 0.5 * p.y / r)
            fs.append(f)
        self._mat(fs, mat)
        return fs

    def helice(self, mat, M, R, r, h, voltas, seg=8):
        """Mola helicoidal no Z local (de 0 a h)."""
        n = int(voltas * 16)
        pts = [M @ V(R * math.cos(2 * math.pi * voltas * i / n), R * math.sin(2 * math.pi * voltas * i / n), h * i / n)
               for i in range(n + 1)]
        return self.tubo(mat, pts, r, seg=seg, sub=1)


# ================================================================================================================================
# Blender: materiais (texturas procedurais assadas em numpy, ladrilháveis, TEX x TEX)
# ================================================================================================================================

def _srgb_lin(c):
    return tuple((x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


class Texturas:
    def __init__(self, semente=7):
        import numpy as np
        self.np = np
        self.rng = np.random.default_rng(semente)
        n = TEX
        self.n = n
        g = np.arange(n) / n
        self.u, self.v = np.meshgrid(g, g)

    def ruido(self, f, fy=None):
        """Ruído de valor ladrilhável, f células em x (fy em y)."""
        np = self.np
        fy = fy or f
        L = self.rng.random((fy, f))
        x = self.u * f
        y = self.v * fy
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        tx, ty = x - x0, y - y0
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        a = L[y0 % fy, x0 % f]
        b = L[y0 % fy, (x0 + 1) % f]
        c = L[(y0 + 1) % fy, x0 % f]
        d = L[(y0 + 1) % fy, (x0 + 1) % f]
        return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty

    def fbm(self, f, oit=4, ganho=0.5, fy=None):
        t, amp, s = 0, 1.0, 0
        for k in range(oit):
            t = t + amp * self.ruido(f * 2 ** k, (fy or f) * 2 ** k)
            s += amp
            amp *= ganho
        return t / s

    def celulas(self, k):
        """Distância à célula mais próxima (Voronoi F1) ladrilhável, k x k células."""
        np = self.np
        pts = (np.stack(np.meshgrid(np.arange(k), np.arange(k)), -1) + self.rng.random((k, k, 2))) / k
        d = np.full(self.u.shape, 9.0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = pts + np.array([dx, dy])
                for q in p.reshape(-1, 2):
                    dd = (self.u - q[0]) ** 2 + (self.v - q[1]) ** 2
                    d = np.minimum(d, dd)
        return np.sqrt(d) * k

    def normal(self, h, forca):
        np = self.np
        dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * forca
        dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * forca
        n = np.stack([-dx, -dy, np.ones_like(h)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        return n * 0.5 + 0.5


def _altura(tx, tipo):
    """Mapa de altura 0-1 e variação de cor por tipo de superfície."""
    np = tx.np
    u, v = tx.u, tx.v
    if tipo == "tecido":
        k = 48
        fu, fv = (u * k) % 1.0, (v * k) % 1.0
        pu = np.cos((fu - 0.5) * math.pi) ** 2
        pv = np.cos((fv - 0.5) * math.pi) ** 2
        xadrez = ((np.floor(u * k) + np.floor(v * k)) % 2).astype(bool)
        h = np.where(xadrez, pu, pv) * 0.8 + tx.fbm(32, 2) * 0.2
        var = 0.85 + 0.3 * tx.fbm(8, 3)
        return h, var
    if tipo == "tecido_estampa":     # miolo dos anos 90: trama + pontinhos
        h, var = _altura(tx, "tecido")
        pont = (np.sin(u * 2 * math.pi * 16) * np.sin(v * 2 * math.pi * 16) > 0.85)
        return h, var * np.where(pont, 1.5, 1.0)
    if tipo == "listras":            # anos 80: listras finas no tecido
        h, var = _altura(tx, "tecido")
        lis = 0.8 + 0.35 * (np.sin(v * 2 * math.pi * 12) > 0.6)
        return h, var * lis
    if tipo == "vinil":
        c = tx.celulas(24)
        h = np.clip(c, 0, 1) ** 0.6 * 0.7 + tx.fbm(16, 3) * 0.3
        return h, 0.92 + 0.12 * tx.fbm(6, 3)
    if tipo == "plastico":
        c = tx.celulas(56)
        h = np.clip(c, 0, 1) * 0.5 + tx.fbm(48, 3) * 0.5
        return h, 0.95 + 0.08 * tx.fbm(6, 2)
    if tipo == "borracha":
        h = tx.fbm(48, 3)
        return h, 0.9 + 0.15 * tx.fbm(8, 2)
    if tipo == "carpete":
        h = tx.fbm(64, 2) * 0.6 + tx.rng.random(u.shape) * 0.4
        return h, 0.8 + 0.35 * tx.fbm(16, 3)
    if tipo == "feltro":
        h = tx.fbm(32, 3) * 0.7 + tx.rng.random(u.shape) * 0.3
        return h, 0.94 + 0.08 * tx.fbm(8, 3)
    if tipo == "escovado":
        h = tx.fbm(4, 3, fy=128)
        return h, 0.92 + 0.12 * tx.fbm(4, 2, fy=64)
    if tipo == "fundido":
        h = tx.fbm(24, 4) * 0.7 + (tx.celulas(30) < 0.15) * -0.3
        return h, 0.85 + 0.25 * tx.fbm(6, 3)
    if tipo == "pintura":
        h = tx.fbm(48, 2)
        return h, 0.97 + 0.04 * tx.fbm(4, 2)
    if tipo == "chassi":
        h = tx.fbm(20, 4)
        return h, 0.8 + 0.35 * tx.fbm(6, 3)
    if tipo == "ferro":
        f = tx.fbm(6, 4)
        return tx.fbm(24, 3), 0.75 + 0.4 * f
    if tipo == "radiador":
        aleta = np.abs(np.sin(u * math.pi * 64))
        tubo = (np.sin(v * math.pi * 8) > 0.75)
        h = np.where(tubo, 1.0, aleta * 0.6)
        return h, np.where(tubo, 1.0, 0.55 + 0.45 * aleta)
    if tipo == "alto_falante":
        furo = (np.sin(u * 2 * math.pi * 24) * np.sin(v * 2 * math.pi * 24)) > 0.55
        h = np.where(furo, 0.0, 1.0)
        return h, np.where(furo, 0.15, 1.0)
    if tipo == "cinto":
        h = 0.5 + 0.5 * np.sin(v * 2 * math.pi * 40) * np.sign(np.sin(u * 2 * math.pi * 40))
        return h, 0.9 + 0.1 * h
    return np.zeros_like(u), np.ones_like(u)


def _mostrador(tx):
    """Mostrador sem texto: fundo preto, marcas brancas num arco de 270°, anel e miolo."""
    np = tx.np
    x, y = tx.u * 2 - 1, tx.v * 2 - 1
    r = np.sqrt(x * x + y * y)
    a = np.arctan2(y, x)
    cor = np.zeros(r.shape + (3,)) + 0.015
    arco = (a > -math.pi * 0.75) | (a < -math.pi * 0.25)
    rel = ((-(a) - math.pi * 0.25) % (2 * math.pi)) / (1.5 * math.pi)
    grossa = (np.abs((rel * 10) - np.round(rel * 10)) < 0.035) & (r > 0.68) & (r < 0.86) & arco
    fina = (np.abs((rel * 50) - np.round(rel * 50)) < 0.06) & (r > 0.77) & (r < 0.86) & arco
    anel = (r > 0.93) & (r < 0.97)
    verm = (rel > 0.82) & (rel < 1.0) & (r > 0.86) & (r < 0.90) & arco
    branco = grossa | fina | anel
    cor[branco] = 0.85
    cor[verm] = (0.7, 0.05, 0.03)
    cor[r < 0.09] = 0.05
    return cor


class Materiais:
    """Os materiais do kit, criados uma vez por carro (cores da época e a cor da pintura do carro)."""

    TIPOS = {
        # nome: (tipo de textura, metálico, aspereza, força do relevo, ladrilho em metros)
        "banco": ("tecido", 0.0, 0.9, 1.4, 0.05), "banco_miolo": ("tecido_estampa", 0.0, 0.92, 1.4, 0.07),
        "vinil": ("vinil", 0.0, 0.42, 0.45, 0.14), "vinil_2": ("vinil", 0.0, 0.42, 0.45, 0.14),
        "listrado": ("listras", 0.0, 0.9, 1.4, 0.08),
        "plastico": ("plastico", 0.0, 0.62, 0.5, 0.10), "plastico_claro": ("plastico", 0.0, 0.6, 0.5, 0.10),
        "plastico_liso": ("plastico", 0.0, 0.38, 0.3, 0.30), "carpete": ("carpete", 0.0, 1.0, 2.5, 0.12),
        "forro_teto": ("feltro", 0.0, 0.95, 0.25, 0.15), "borracha": ("borracha", 0.0, 0.85, 0.8, 0.10),
        "cinto": ("cinto", 0.0, 0.7, 1.0, 0.03), "cromado": ("escovado", 1.0, 0.12, 0.1, 0.30),
        "aluminio": ("escovado", 1.0, 0.32, 0.6, 0.25), "fundido": ("fundido", 1.0, 0.55, 1.5, 0.25),
        "pintura_interna": ("pintura", 0.0, 0.32, 0.04, 0.60), "chassi": ("chassi", 0.0, 0.8, 0.35, 0.25),
        "ferro": ("ferro", 0.6, 0.75, 1.2, 0.30), "metal_preto": ("pintura", 0.4, 0.55, 0.08, 0.4),
        "radiador": ("radiador", 1.0, 0.45, 2.0, 0.06), "alto_falante": ("alto_falante", 0.0, 0.7, 1.5, 0.05),
        "reservatorio": ("plastico", 0.0, 0.45, 0.4, 0.15), "espelho": ("pintura", 1.0, 0.03, 0.0, 1.0),
        "bateria": ("plastico", 0.0, 0.55, 0.6, 0.12), "vermelho": ("plastico", 0.0, 0.5, 0.4, 0.1),
        "amarelo": ("plastico", 0.0, 0.5, 0.4, 0.1), "motor_pintado": ("fundido", 0.3, 0.45, 0.8, 0.25),
        "instrumentos": (None, 0.0, 0.3, 0.0, 1.0), "lente": ("pintura", 0.0, 0.1, 0.0, 0.3),
        "pinca": ("fundido", 0.2, 0.5, 1.0, 0.15), "disco": ("escovado", 1.0, 0.35, 0.5, 0.2),
    }

    def __init__(self, estilo, pintura_rgb):
        import bpy
        self.bpy = bpy
        self.tx = Texturas()
        e = estilo
        cin = (0.33, 0.33, 0.33)
        self.cores = {
            "banco": e["cor_banco"], "banco_miolo": e["cor_banco_2"], "vinil": e["cor_banco"], "vinil_2": e["cor_banco_2"],
            "listrado": e["cor_banco_2"], "plastico": e["cor_plastico"],
            "plastico_claro": tuple(min(1, c * 2.6 + 0.08) for c in e["cor_plastico"]),
            "plastico_liso": e["cor_plastico"], "carpete": e["cor_carpete"], "forro_teto": e["cor_teto"],
            "borracha": (0.02, 0.02, 0.02), "cinto": (0.06, 0.06, 0.065), "cromado": (0.92, 0.92, 0.92),
            "aluminio": (0.75, 0.75, 0.74), "fundido": (0.52, 0.52, 0.5), "pintura_interna": pintura_rgb,
            "chassi": (0.06, 0.06, 0.06), "ferro": (0.20, 0.17, 0.15), "metal_preto": (0.03, 0.03, 0.03),
            "radiador": (0.30, 0.30, 0.31), "alto_falante": (0.02, 0.02, 0.02), "reservatorio": (0.78, 0.77, 0.70),
            "espelho": (0.95, 0.95, 0.95), "bateria": (0.13, 0.13, 0.14), "vermelho": (0.5, 0.03, 0.02),
            "amarelo": (0.85, 0.6, 0.02), "motor_pintado": (0.10, 0.12, 0.16), "instrumentos": cin,
            "lente": (0.9, 0.9, 0.85), "pinca": (0.25, 0.25, 0.26), "disco": (0.45, 0.44, 0.43),
        }
        self.cache = {}
        self.alturas = {}
        self.imgs = {}

    def get(self, nome):
        if nome in self.cache:
            return self.cache[nome]
        bpy = self.bpy
        np = self.tx.np
        tipo, metal, rug, forca, ladrilho = self.TIPOS[nome]
        mat = bpy.data.materials.new(nome)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        n = TEX
        if nome == "instrumentos":
            cor = _mostrador(self.tx)
            h = np.zeros((n, n))
            var = np.ones((n, n))
        else:
            if tipo not in self.alturas:     # um relevo por tipo, com semente própria: materiais do mesmo tipo dividem as imagens
                import zlib
                self.tx.rng = np.random.default_rng(zlib.crc32(tipo.encode()))
                self.alturas[tipo] = _altura(self.tx, tipo)
            h, var = self.alturas[tipo]
            base = np.array(_srgb_lin(self.cores[nome]))
            cor = np.clip(base[None, None, :] * var[..., None], 0, 1)
            cor = np.power(cor, 1 / 2.2)   # a imagem de cor é sRGB
        rgba = np.concatenate([cor, np.ones((n, n, 1))], -1)
        img = self._img(f"T_{nome}_cor", rgba, "sRGB")
        tc = nt.nodes.new("ShaderNodeTexImage")
        tc.image = img
        nt.links.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
        # ORM: R oclusão (1), G aspereza, B metálico
        hn = (h - h.min()) / max(1e-6, (h.max() - h.min()))
        r = np.clip(rug + (0.5 - hn) * 0.12, 0.02, 1.0)
        if nome == "instrumentos":
            r = np.full((n, n), 0.35)
        chave = ("orm", tipo, rug, metal)
        if chave not in self.imgs:
            orm = np.stack([np.ones((n, n)), r, np.full((n, n), metal), np.ones((n, n))], -1)
            self.imgs[chave] = self._img(f"T_{tipo}_{int(rug * 100)}_{int(metal * 100)}_orm", orm, "Non-Color")
        io = self.imgs[chave]
        to = nt.nodes.new("ShaderNodeTexImage")
        to.image = io
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(to.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        if forca > 0:
            chave = ("nor", tipo, forca)
            if chave not in self.imgs:
                nm = self.tx.normal(hn, forca * 6.0)
                self.imgs[chave] = self._img(f"T_{tipo}_{int(forca * 100)}_nor", np.concatenate([nm, np.ones((n, n, 1))], -1), "Non-Color")
            inn = self.imgs[chave]
            tn = nt.nodes.new("ShaderNodeTexImage")
            tn.image = inn
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(tn.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        if nome == "reservatorio":
            bsdf.inputs["Transmission Weight"].default_value = 0.25
        mat["ladrilho_m"] = ladrilho
        self.cache[nome] = mat
        return mat

    def _img(self, nome, arr, cs):
        bpy = self.bpy
        n = arr.shape[0]
        img = bpy.data.images.new(nome, n, n, alpha=False)
        img.colorspace_settings.name = cs
        img.pixels.foreach_set(arr.astype("float32").ravel())
        img.file_format = "PNG"
        img.pack()
        return img


# ================================================================================================================================
# Blender: casca do carro (raios para assentar as peças) e a cena
# ================================================================================================================================

class Casca:
    """BVH da carroceria (sem a casca escura de vão) e das peças, para achar teto, laterais, portas e capô por raios."""

    def __init__(self, objs, vaos):
        import bmesh
        from mathutils.bvhtree import BVHTree
        self.arv = {}
        for nome, ob in objs.items():
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            bm.transform(ob.matrix_world)
            vi = [i for i, m in enumerate(ob.data.materials) if m and m.name == "MI_DNVao"]
            if vi:
                tira = [f for f in bm.faces if f.material_index in vi and _dentro_vaos(f.calc_center_median(), vaos)]
                bmesh.ops.delete(bm, geom=tira, context="FACES")
            self.arv[nome] = BVHTree.FromBMesh(bm)
            bm.free()

    def raio(self, nomes, origem, direcao, dist=3.0):
        from mathutils import Vector
        melhor = None
        for n in nomes:
            a = self.arv.get(n)
            if not a:
                continue
            loc, nor, idx, d = a.ray_cast(Vector(origem), Vector(direcao).normalized(), dist)
            if loc is not None and (melhor is None or d < melhor[1]):
                melhor = (loc, d, n)
        return melhor


def _dentro(p, b, folga=0.0):
    return b[0] - folga <= p[0] <= b[1] + folga and b[2] - folga <= p[1] <= b[3] + folga and b[4] - folga <= p[2] <= b[5] + folga


def _dentro_vaos(p, vaos):
    return any(_dentro(p, b) for b in vaos.values())


# ================================================================================================================================
# Construção das partes
# ================================================================================================================================

class Kit:
    def __init__(self, M, cfg, estilo, mats, casca=None):
        self.M, self.cfg, self.e, self.mats, self.casca = M, cfg, estilo, mats, casca
        self.pecas = []

    def nova(self, nome, grupo, segue=None, nota=None):
        p = Peca(nome, grupo, segue, nota)
        self.pecas.append(p)
        return p

    # ---------------------------------------------------------------------------------------------------------------- medidas finas
    def teto_em(self, x, y):
        """Altura de baixo do teto em (x, y): pela casca (raio para cima) ou pela caixa."""
        M = self.M
        if self.casca:
            o = M["z_cintura"]
            for _ in range(5):
                h = self.casca.raio(["body"], (x, y, o), (0, 0, 1), 1.5)
                if not h:
                    break
                if h[0].z > M["z_cintura"] + 0.25:
                    return h[0].z
                o = h[0].z + 0.005
        yy = abs(y) / max(0.2, M["meia_teto"] + 0.12)
        return M["z_teto_int"] + 0.02 - 0.16 * yy ** 2

    def tem_teto(self, x, y):
        """Há chapa de teto (e não vidro) logo acima de (x, y)?"""
        M = self.M
        if not self.casca:
            return M["x_teto_tras"] <= x <= M["x_teto_frente"]
        o = M["z_cintura"] + 0.1
        for _ in range(5):
            h = self.casca.raio(["body", "glass_windshield", "glass_rear", "trunk", "glass_door_fl", "glass_door_fr", "glass_door_rl",
                                 "glass_door_rr"], (x, y, o), (0, 0, 1), 1.5)
            if not h:
                return False
            if h[2] != "body":
                return False
            if h[0].z > M["z_teto"] - 0.25:
                return True
            o = h[0].z + 0.005
        return False

    def lado_em(self, x, z, s, nomes=("body",), y0=0.15, folga=0.0):
        """|y| da face de dentro da lateral em (x, z) do lado s: pela casca (raio de dentro para fora) ou pela meia largura."""
        M = self.M
        if self.casca:
            h = self.casca.raio(list(nomes), (x, s * y0, z), (0, s, 0), 1.5)
            if h and abs(h[0].y) > y0 + 0.08:      # teto curvo (Besouro): a lateral pode estar bem para dentro
                return abs(h[0].y) - folga
        return M["W"] - 0.05 - folga

    def y_janela(self, x, z, s, pos=None):
        """|y| do plano do vidro lateral em (x, z) (pelo vidro da porta ou da carroceria); sem casca, pela queda do teto."""
        M = self.M
        nomes = ([f"glass_door_{pos}"] if pos else ["glass_door_fl" if s > 0 else "glass_door_fr"]) + ["body"]
        if self.casca:
            h = self.casca.raio(nomes, (x, s * 0.2, z), (0, s, 0), 1.2)
            if h and abs(h[0].y) > 0.30:
                return abs(h[0].y)
        t = _limitar((z - M["z_cintura"]) / max(0.1, M["z_teto"] - M["z_cintura"]), 0, 1)
        return M["W"] - 0.03 - 0.12 * t

    def capo_em(self, x, y):
        """Altura de baixo do capô (tampa da frente) em (x, y)."""
        M = self.M
        if self.casca:
            for n in (["hood"], ["body"]):
                h = self.casca.raio(n, (x, y, M["H"] + 0.5), (0, 0, -1), 1.6)
                if h:
                    return h[0].z - 0.015
        t = (x - M["x_corta_fogo"]) / max(0.2, M["x_frente"] - M["x_corta_fogo"])
        return M["z_capo_tras"] + (M["z_capo_frente"] - M["z_capo_tras"]) * _limitar(t, 0, 1)

    # ================================================================================================================ HABITÁCULO
    def habitaculo(self):
        self.carpete()
        for s in (1, -1):
            self.banco_dianteiro(s)
        self.banco_traseiro()
        self.painel()
        self.volante()
        self.pedais()
        self.cambio_freio_mao()
        self.console()
        self.cintos()
        self.forro_teto()
        self.quebra_sois_retrovisor()
        self.acabamentos()

    def carpete(self):
        M = self.M
        p = self.nova("interior_carpete", "habitaculo")
        x0, x1 = M["x_encosto_t"] - 0.14, M["x_corta_fogo"] - 0.01
        yi = M["W"] - 0.15
        zp = M["z_piso"]
        tun_h = 0.13 if self.cfg["tracao"] == "dianteira" else 0.17
        x_degrau = M["x_encosto_t"] + 0.50
        xa = M["x_corta_fogo"] - 0.30

        def ponto(u, v):
            x = x0 + (x1 - x0) * u
            y = -yi + 2 * yi * v
            z = zp
            ay = abs(y)
            if ay < 0.17:
                z += tun_h * math.cos(ay / 0.17 * math.pi / 2) ** 1.5
            if x < x_degrau:      # degrau sob o banco traseiro
                z += 0.10 * _limitar((x_degrau - x) / 0.06, 0, 1)
            if x > xa:            # rampa dos pés até o corta-fogo
                z += 0.24 * ((x - xa) / (x1 - xa)) ** 1.4
            if ay > yi - 0.07:    # sobe até a soleira
                z += (M["z_saia"] - 0.02 - zp) * ((ay - (yi - 0.07)) / 0.07) ** 2
            return V(x, y, z)
        p.grade("carpete", 44, 30, ponto, 0.012, normal_fn=lambda u, v: (0, 0, 1))

    # ---------------------------------------------------------------------------------------------------------------- bancos
    def _estofado(self, p, M0, larg, comp, esp, frente_alto=True):
        """Assento ou encosto estofado no plano XY local (X = comprimento, Y = largura, Z = espessura para cima)."""
        e = self.e
        mat1 = "vinil" if e["banco"] == "vinil" else "banco"
        mat2 = "vinil_2" if e["banco"] == "vinil" else ("listrado" if self.cfg["epoca"] == "80" else "banco_miolo")
        # base estofada
        p.almofada(mat1, M0 @ T(0, 0, esp * 0.35), comp, larg, esp * 0.7, 0.25, 0.25)
        if e["abas_laterais"]:
            for s in (1, -1):
                p.almofada(mat1, M0 @ T(0, s * (larg / 2 - 0.055), esp * 0.62), comp * 0.96, 0.12, esp * 0.62, 0.3, 0.35)
            n = max(1, e["gomos"])
            mio = larg - 0.20
            for k in range(n):
                cx = -comp / 2 + comp * (k + 0.5) / n
                p.almofada(mat2, M0 @ T(cx * 0.92, 0, esp * 0.55), comp * 0.92 / n - 0.008, mio, esp * 0.42, 0.22, 0.25)
        else:
            n = max(1, e["gomos"])
            for k in range(n):
                cy = -larg / 2 + 0.05 + (larg - 0.10) * (k + 0.5) / n
                p.almofada(mat2 if k % 2 else mat1, M0 @ T(0, cy, esp * 0.62), comp * 0.94, (larg - 0.10) / n - 0.004,
                           esp * 0.45, 0.3, 0.3)

    def banco_dianteiro(self, s):
        M, e = self.M, self.e
        lado = "esq" if s > 0 else "dir"
        p = self.nova(f"interior_banco_dianteiro_{lado}", "habitaculo")
        y = s * M["y_banco"]
        xb = M["x_encosto_d"]
        zs = M["z_assento"]
        larg = 0.50
        comp = 0.50
        # trilhos e base
        for dy in (-0.17, 0.17):
            p.caixa("aluminio", T(xb + 0.25, y + dy, M["z_piso"] + 0.02), 0.62, 0.03, 0.025, 0.004)
        p.caixa("plastico", T(xb + 0.26, y, (M["z_piso"] + zs - 0.08) / 2 + 0.02), comp - 0.08, larg - 0.06,
                zs - 0.08 - M["z_piso"], 0.02)
        # assento, levemente inclinado (frente mais alta)
        Ms = T(xb + 0.28, y, zs - 0.07) @ Ry(-math.radians(6))
        self._estofado(p, Ms, larg, comp, 0.13)
        # encosto: articulado no fundo do assento, reclinado 17°
        h = 0.60
        Mb = T(xb + 0.02, y, zs - 0.03) @ Ry(math.radians(-17)) @ T(0, 0, h / 2) @ Ry(math.radians(90)) @ Rz(math.pi)
        self._estofado(p, Mb @ T(0, 0, -0.06), larg - 0.02, h, 0.12)
        # costas do encosto (plástico)
        topo = T(xb + 0.02, y, zs - 0.03) @ Ry(math.radians(-17))
        p.caixa("plastico", topo @ T(-0.065, 0, h / 2), 0.03, larg - 0.06, h - 0.04, 0.012)
        # encosto de cabeça com hastes
        Mh = topo @ T(0.0, 0, h + 0.13)
        p.almofada("vinil" if e["banco"] == "vinil" else "banco", Mh, 0.10, 0.26, 0.19, 0.3, 0.3)
        for dy in (-0.07, 0.07):
            a = topo @ V(-0.005, dy, h - 0.03)
            b = topo @ V(-0.005, dy, h + 0.06)
            p.tubo("cromado", [a, b], 0.0055, seg=8, sub=1)
        # alavanca de reclinar e capa lateral (lado de fora)
        p.caixa("plastico", T(xb + 0.12, y + s * (larg / 2 + 0.01), zs - 0.10) @ Rx(0), 0.20, 0.02, 0.09, 0.008)
        p.caixa("plastico", T(xb + 0.06, y + s * (larg / 2 + 0.025), zs - 0.08) @ Ry(math.radians(20)), 0.10, 0.015, 0.025, 0.006)
        # fivela do cinto (lado de dentro)
        yb = y - s * (larg / 2 + 0.015)
        p.tubo("cinto", [(xb + 0.05, yb, M["z_piso"] + 0.10), (xb + 0.08, yb, zs - 0.02)], 0.01, seg=6, sub=1)
        p.caixa("plastico_liso", T(xb + 0.09, yb, zs + 0.03) @ Ry(math.radians(-20)), 0.035, 0.025, 0.075, 0.008)
        p.caixa("vermelho", T(xb + 0.092, yb, zs + 0.05) @ Ry(math.radians(-20)), 0.02, 0.028, 0.012, 0.003)

    def banco_traseiro(self):
        M, e = self.M, self.e
        p = self.nova("interior_banco_traseiro", "habitaculo")
        xb = M["x_encosto_t"]
        larg = 2 * (M["meia_interna"] - 0.07)
        comp = 0.46
        zb = M["z_piso"] + 0.10
        zs = M["z_assento_t"]
        p.caixa("plastico", T(xb + 0.25, 0, (zb + zs - 0.08) / 2), comp - 0.04, larg - 0.04, zs - 0.08 - zb + 0.02, 0.02)
        self._estofado(p, T(xb + 0.26, 0, zs - 0.08) @ Ry(-math.radians(8)), larg, comp, 0.14)
        h = min(0.58, M["z_teto_int"] - zs - 0.18)
        Mb = T(xb, 0, zs - 0.04) @ Ry(math.radians(-24)) @ T(0, 0, h / 2) @ Ry(math.radians(90)) @ Rz(math.pi)
        self._estofado(p, Mb @ T(0, 0, -0.06), larg, h, 0.12)
        topo = T(xb, 0, zs - 0.04) @ Ry(math.radians(-24))
        p.caixa("plastico", topo @ T(-0.07, 0, h / 2), 0.03, larg - 0.04, h - 0.02, 0.012)
        if e.get("encosto_cabeca_traseiro"):
            for yy in (-larg * 0.3, larg * 0.3):
                Mh = topo @ T(0, yy, h + 0.10)
                p.almofada("vinil" if e["banco"] == "vinil" else "banco", Mh, 0.09, 0.24, 0.15, 0.3, 0.3)
                for dy in (-0.065, 0.065):
                    p.tubo("cromado", [topo @ V(-0.005, yy + dy, h - 0.03), topo @ V(-0.005, yy + dy, h + 0.04)], 0.005, seg=8, sub=1)

    # ---------------------------------------------------------------------------------------------------------------- painel
    def painel(self):
        M, e = self.M, self.e
        p = self.nova("interior_painel", "habitaculo")
        xf, xp = M["x_corta_fogo"], M["x_painel"]
        zt = M["z_painel"]
        yd = M["W"] - 0.11
        # frente estreita (Besouro): o painel não passa da lateral na altura dele
        for xx in (xp + 0.05, (xp + xf) / 2, xf - 0.02):
            for zz in (zt - 0.02, zt - 0.15):
                yd = min(yd, min(self.lado_em(xx, zz, 1), self.lado_em(xx, zz, -1)) - 0.015)
        zb = M["z_piso"] + 0.30
        estilo = e["painel"]
        # perfil lateral (x, z) do painel: topo até o para-brisa, face, parte de baixo e corta-fogo
        if estilo == "chapa":
            # anos 70: rolo acolchoado no topo e chapa pintada na frente (aberto embaixo)
            pa = [(xf + 0.05, zt - 0.05), (xf + 0.05, zt + 0.004), (xp + 0.12, zt), (xp + 0.03, zt - 0.015), (xp, zt - 0.045),
                  (xp + 0.02, zt - 0.07), (xp + 0.10, zt - 0.07)]
            p.prisma("vinil", T(0, -yd, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), pa, 2 * yd, ch=0.012, seg=3)
            chapa = [(xp + 0.01, zt - 0.07), (xp + 0.04, zt - 0.07), (xp + 0.05, zt - 0.30), (xp + 0.02, zt - 0.30)]
            p.prisma("pintura_interna", T(0, -yd + 0.02, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), chapa, 2 * yd - 0.04, ch=0.006)
            face_x = xp + 0.012
            face_z = zt - 0.18
        else:
            topo_curvo = estilo in ("arredondado", "duas_cores")
            pts = [(xf + 0.05, zt + 0.004)]
            if topo_curvo:
                for k in range(1, 7):
                    t = k / 7
                    pts.append((xf + 0.05 + (xp + 0.06 - xf - 0.05) * t, zt + 0.004 + 0.03 * math.sin(math.pi * t) - 0.014 * t))
            pts += [(xp + 0.05, zt), (xp + 0.01, zt - 0.03), (xp, zt - 0.08), (xp + 0.015, zt - 0.22), (xp + 0.06, zt - 0.30),
                    (xp + 0.20, zb), (xf - 0.02, zb - 0.05), (xf - 0.02, zt - 0.10)]
            if estilo == "duas_cores":
                corte = 3 + 6
                cima = pts[:corte] + [(xp + 0.006, zt - 0.10), (xf - 0.02, zt - 0.10)]
                baixo = [(xf - 0.02, zt - 0.10), (xp + 0.006, zt - 0.10)] + pts[corte + 1:]
                p.prisma("plastico", T(0, -yd, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), cima, 2 * yd, ch=0.012, seg=3)
                p.prisma("plastico_claro", T(0, -yd + 0.003, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), baixo, 2 * yd - 0.006,
                         ch=0.01, seg=2)
            else:
                p.prisma("plastico", T(0, -yd, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), pts, 2 * yd, ch=0.012, seg=3)
            face_x = xp + 0.003
            face_z = zt - 0.12
        self.face_painel = (face_x, face_z)
        yv = M["y_banco"]
        # capuz dos instrumentos e quadro
        mostr = e["mostradores"]
        if estilo == "chapa":
            zc = zt - 0.13
            r0 = mostr[0][0]
            p.revolucao("cromado", T(face_x + 0.002, yv, zc) @ Ry(-math.pi / 2), [(r0 + 0.012, 0), (r0 + 0.012, 0.012),
                                                                                    (r0 - 0.002, 0.016), (r0 - 0.002, 0.004)], 40)
            p.disco_uv("instrumentos", T(face_x - 0.001, yv, zc) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), r0)
            self._ponteiro(p, face_x - 0.004, yv, zc, r0)
            r1 = mostr[1][0]
            for k, dy in enumerate((-0.14, 0.14)):
                p.revolucao("cromado", T(face_x + 0.002, yv + dy, zc + 0.01) @ Ry(-math.pi / 2),
                            [(r1 + 0.008, 0), (r1 + 0.008, 0.01), (r1 - 0.002, 0.012), (r1 - 0.002, 0.004)], 28)
                p.disco_uv("instrumentos", T(face_x - 0.001, yv + dy, zc + 0.01) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), r1)
                self._ponteiro(p, face_x - 0.004, yv + dy, zc + 0.01, r1)
        else:
            larg_q = 0.40 if len(mostr) > 2 else 0.32
            zc = zt - 0.02
            xs = face_x - 0.035
            # capuz em arco sobre o quadro, aberto para o motorista
            a, b, ee = larg_q / 2 + 0.03, 0.135, 0.022
            arco = [(a * math.cos(math.pi * k / 14), b * math.sin(math.pi * k / 14)) for k in range(15)]
            arco += [((a - ee) * math.cos(math.pi * k / 14), (b - ee) * math.sin(math.pi * k / 14)) for k in range(14, -1, -1)]
            p.prisma("plastico", T(face_x - 0.11, yv, zc - 0.07) @ Ry(math.pi / 2) @ Rz(math.pi / 2), arco, 0.13, ch=0.006, seg=2)
            # fundo do quadro, um pouco à frente da face do painel
            p.caixa("plastico_liso", T(face_x - 0.012, yv, zc - 0.005), 0.03, 2 * a - 0.02, 0.125, 0.006)
            if len(mostr) == 2:
                lugares = [(yv + 0.075, zc, mostr[0][0]), (yv - 0.075, zc, mostr[1][0])]
            else:
                lugares = [(yv + 0.07, zc, mostr[0][0]), (yv - 0.07, zc, mostr[1][0]), (yv + 0.165, zc - 0.015, mostr[2][0]),
                           (yv - 0.165, zc - 0.015, mostr[3][0])]
            for (yy, zz, rr) in lugares:
                p.revolucao("cromado" if self.cfg["epoca"] == "80" else "plastico_liso", T(xs + 0.006, yy, zz) @ Ry(-math.pi / 2),
                            [(rr + 0.006, 0), (rr + 0.006, 0.006), (rr - 0.001, 0.008), (rr - 0.001, 0.002)], 36)
                p.disco_uv("instrumentos", T(xs + 0.005, yy, zz) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), rr)
                self._ponteiro(p, xs + 0.002, yy, zz, rr)
        # saídas de ar
        self._saidas(p, face_x, zt, yd)
        # centro: rádio e controles do ar, porta-luvas, alto-falante no topo (anos 70)
        zr = zt - (0.20 if estilo != "chapa" else 0.22)
        p.caixa("plastico_liso", T(face_x + 0.006, 0, zr), 0.012, 0.19, 0.06, 0.004)
        p.caixa("metal_preto", T(face_x - 0.001, 0, zr), 0.004, 0.11, 0.022, 0.002)
        for dy in (-0.075, 0.075):
            p.cilindro("plastico_liso", T(face_x - 0.012, dy, zr) @ Ry(math.pi / 2), 0.012, 0.022, 20, 0.003)
        for k in range(5):
            p.caixa("plastico", T(face_x - 0.002, -0.04 + k * 0.02, zr - 0.022), 0.008, 0.014, 0.008, 0.002)
        zc2 = zr - 0.085
        if self.cfg["epoca"] in ("2000",):
            for dy in (-0.06, 0.0, 0.06):
                p.cilindro("plastico_liso", T(face_x - 0.008, dy, zc2) @ Ry(math.pi / 2), 0.022, 0.025, 28, 0.004)
                p.caixa("cromado", T(face_x - 0.022, dy, zc2 + 0.012), 0.004, 0.004, 0.014, 0.001)
        elif estilo != "chapa":
            p.caixa("plastico_liso", T(face_x + 0.004, 0, zc2), 0.01, 0.18, 0.05, 0.004)
            for k, dy in enumerate((-0.05, 0.0, 0.05)):
                p.caixa("metal_preto", T(face_x - 0.001, dy, zc2), 0.004, 0.004, 0.034, 0.001)
                p.caixa("plastico", T(face_x - 0.008, dy, zc2 + (k - 1) * 0.008), 0.012, 0.014, 0.01, 0.003)
        else:
            for dy in (-0.05, 0.05):
                p.caixa("cromado", T(face_x - 0.01, dy, zc2 + 0.03), 0.02, 0.006, 0.006, 0.002)
        # porta-luvas (lado do passageiro)
        yg = -M["y_banco"]
        if estilo == "chapa":
            p.caixa("pintura_interna", T(face_x + 0.03, yg, zt - 0.20), 0.008, 0.26, 0.12, 0.004)
            p.cilindro("cromado", T(face_x + 0.024, yg, zt - 0.15) @ Ry(math.pi / 2), 0.008, 0.01, 16, 0.002)
            p.disco_uv("alto_falante", T(xp + 0.10, 0, zt + 0.002), 0.06)
        else:
            p.caixa("plastico", T(face_x + 0.022, yg, zt - 0.215), 0.022, 0.30, 0.13, 0.01)
            p.caixa("plastico_liso", T(face_x + 0.008, yg, zt - 0.165), 0.01, 0.06, 0.014, 0.003)
        # chave de ignição (na capa da coluna) e o joelho do motorista
        if estilo != "chapa":
            p.almofada("plastico", T(face_x + 0.06, yv, zt - 0.30), 0.10, 0.36, 0.10, 0.4, 0.4)

    def _ponteiro(self, p, x, y, z, r):
        a = math.radians(210)
        p.caixa("vermelho", T(x, y, z) @ Rx(a) @ T(0, 0, r * 0.38), 0.002, 0.004, r * 0.8, 0.0008, 1)
        p.cilindro("metal_preto", T(x, y, z) @ Ry(math.pi / 2), r * 0.12, 0.006, 16, 0.001)

    def _saidas(self, p, fx, zt, yd):
        e = self.e
        tipo = e["saidas"]
        lug = [(yd - 0.09, zt - 0.07), (-(yd - 0.09), zt - 0.07)]
        if self.e["painel"] != "chapa":
            lug += [(0.085, zt - 0.11), (-0.085, zt - 0.11)]
        if tipo == "fendas":
            # anos 70: fendas do desembaçador no topo acolchoado e grade lateral
            for (yy, zz) in lug:
                p.caixa("metal_preto", T(fx + 0.10, yy, zt + 0.003), 0.03, 0.12, 0.006, 0.002)
            return
        for (yy, zz) in lug:
            if tipo == "redondas":
                M0 = T(fx - 0.004, yy, zz) @ Ry(-math.pi / 2)
                p.toro("cromado", M0, 0.034, 0.006, 0.006, 32, 8)
                p.revolucao("metal_preto", M0 @ T(0, 0, 0.004), [(0.0, -0.02), (0.031, -0.02), (0.031, 0.004), (0, 0.004)], 28)
                for k in range(4):
                    p.caixa("plastico", M0 @ T(0, -0.021 + k * 0.014, 0.0), 0.058, 0.002, 0.012, 0.0008, 1)
            else:
                w, h = (0.11, 0.05)
                p.caixa("plastico_liso", T(fx - 0.004, yy, zz), 0.012, w + 0.016, h + 0.016, 0.004)
                p.caixa("metal_preto", T(fx - 0.006, yy, zz), 0.006, w, h, 0.002)
                for k in range(4):
                    p.caixa("plastico", T(fx - 0.012, yy, zz - h / 2 + h * (k + 0.5) / 4) @ Ry(math.radians(15)), 0.014, w - 0.004,
                            0.003, 0.001, 1)

    # ---------------------------------------------------------------------------------------------------------------- volante
    def volante(self):
        M, e = self.M, self.e
        p = self.nova("interior_volante", "habitaculo", nota="volante e coluna de direção")
        fx, fz = self.face_painel
        yv = M["y_banco"]
        incl = math.radians(24)                     # o plano do volante, inclinado da vertical
        dir_col = V(math.cos(incl), 0, -math.sin(incl))   # do volante para dentro do painel
        R = e["volante_raio"]
        cvol = V(M["x_painel"] - 0.20, yv, M["z_cintura"] - (0.15 if e["painel"] == "chapa" else 0.10))
        Mv = T(*cvol) @ alinhar_z(-dir_col)          # Z local = para o motorista
        # coluna e capa
        fim = V(M["x_painel"] + 0.20, yv, cvol.z - 0.40 * math.tan(incl) - 0.02)
        p.tubo("metal_preto", [cvol + dir_col * 0.03, fim], 0.022, seg=16, sub=1)
        Mc = T(*(cvol + dir_col * 0.15)) @ alinhar_z(-dir_col)
        p.almofada("plastico", Mc, 0.13, 0.10, 0.20, 0.35, 0.35)
        # alavancas (setas, limpador) e chave
        for s in (1, -1):
            a = Mc @ V(s * 0.05, 0.01, 0.03)
            b = Mc @ V(s * 0.15, 0.0, 0.03)
            p.tubo("plastico", [a, b], 0.006, seg=8, sub=1)
            p.almofada("plastico", T(*b) @ alinhar_z(b - a), 0.02, 0.02, 0.05, 0.4, 0.4)
        p.cilindro("cromado", Mc @ T(-0.055, 0.0, -0.03) @ Ry(math.pi / 2), 0.012, 0.02, 20, 0.003)
        # aro
        p.toro("vinil" if self.cfg["epoca"] == "70" else "plastico", Mv, R, e["volante_tubo"], e["volante_tubo"] * 1.25, 64, 12)
        # cubo e raios
        if self.cfg["epoca"] == "70":
            p.revolucao("cromado", Mv, [(0, -0.03), (0.045, -0.03), (0.05, 0.0), (0.035, 0.02), (0, 0.025)], 32)
            p.toro("cromado", Mv @ T(0, 0, 0.012), R * 0.62, 0.004, 0.004, 48, 8)
            angs = [math.radians(195), math.radians(-15)]
        elif self.cfg["epoca"] == "80":
            p.almofada("plastico", Mv @ T(0, -0.01, 0.0), 0.15, 0.12, 0.05, 0.25, 0.25)
            angs = [math.radians(a) for a in (200, 340, 150, 30)]
        elif self.cfg["epoca"] == "90":
            p.almofada("plastico", Mv @ T(0, -0.01, 0.005), 0.13, 0.10, 0.055, 0.35, 0.3)
            angs = [math.radians(a) for a in (190, 350, 270)]
        else:
            p.almofada("plastico", Mv @ T(0, 0.0, 0.01), 0.17, 0.17, 0.08, 0.32, 0.32)
            angs = [math.radians(a) for a in (200, 340, 240, 300)]
        for a in angs:
            c = Mv @ V(0.05 * math.cos(a), 0.05 * math.sin(a), -0.01)
            d = Mv @ V((R - 0.008) * math.cos(a), (R - 0.008) * math.sin(a), 0)
            if self.cfg["epoca"] == "70":
                p.tubo("cromado", [c, d], 0.006, seg=8, sub=1)
            else:
                p.fita("plastico", [c, (c + d) / 2, d], 0.032, 0.012, Mv.to_3x3() @ V(0, 0, 1))

    def pedais(self):
        M = self.M
        p = self.nova("interior_pedais", "habitaculo")
        yb = M["y_banco"]
        xp = M["x_painel"]
        zp = M["z_piso"]
        xs = M["x_corta_fogo"] - 0.12
        for k, (dy, alt) in enumerate(((0.11, 0.0), (-0.01, 0.0), (-0.13, 0.03))):
            y = yb + dy
            topo = V(xp + 0.18, y, M["z_painel"] - 0.20)
            pe = V(xs - 0.10, y, zp + 0.17 + alt)
            p.tubo("metal_preto", [topo, (topo + pe) / 2 + V(0.02, 0, 0), pe], 0.008, seg=8)
            larg = 0.05 if k == 2 else 0.075
            Mp = T(*pe) @ Ry(math.radians(-60))
            p.caixa("borracha", Mp, 0.012, larg, 0.07 if k != 2 else 0.11, 0.004)
            for r in range(4):
                p.caixa("borracha", Mp @ T(-0.007, 0, -0.025 + r * 0.017), 0.003, larg - 0.008, 0.004, 0.001, 1)
        # descanso do pé esquerdo
        p.caixa("borracha", T(xs - 0.02, yb + 0.25, zp + 0.10) @ Ry(math.radians(-45)), 0.015, 0.07, 0.16, 0.005)

    def cambio_freio_mao(self):
        M, e = self.M, self.e
        p = self.nova("interior_cambio", "habitaculo")
        xg = M["x_painel"] - (0.02 if e["cambio"] == "longo" else 0.06)
        tun_h = 0.13 if self.cfg["tracao"] == "dianteira" else 0.17
        zb = M["z_piso"] + tun_h + (0.0 if e["console"] in ("nenhum", "curto") else 0.06)
        alt = {"longo": 0.36, "medio": 0.26, "curto": 0.20}[e["cambio"]]
        # coifa sanfonada
        perf = [(0.07, 0.0)]
        for k in range(1, 9):
            r = 0.065 - 0.045 * k / 9 + (0.006 if k % 2 else 0.0)
            perf.append((r, 0.012 * k))
        perf.append((0.012, 0.11))
        p.revolucao("borracha" if e["banco"] != "vinil" else "vinil", T(xg, 0, zb), perf, 28)
        p.caixa("plastico", T(xg, 0, zb + 0.004), 0.16, 0.14, 0.012, 0.005)
        top = V(xg - 0.05, 0, zb + alt)
        p.tubo("cromado" if self.cfg["epoca"] in ("70", "80") else "metal_preto", [(xg, 0, zb + 0.08), (xg - 0.02, 0, zb + alt * 0.6), top],
               0.007, seg=10)
        if self.cfg["epoca"] == "70":
            p.revolucao("plastico_liso", T(*top), [(0, -0.02), (0.022, -0.012), (0.026, 0.006), (0.018, 0.022), (0, 0.027)], 24)
        else:
            p.almofada("plastico", T(*top) @ T(0, 0, 0.02), 0.05, 0.045, 0.06, 0.35, 0.4)
        # freio de mão
        q = self.nova("interior_freio_mao", "habitaculo")
        xh = M["x_encosto_d"] + 0.24
        zh = M["z_piso"] + tun_h + (0.07 if e["console"] in ("medio", "longo") else 0.01)
        q.caixa("plastico", T(xh, 0, zh), 0.18, 0.08, 0.02, 0.006)
        Ml = T(xh + 0.06, 0, zh + 0.02) @ Ry(math.radians(-20))
        q.caixa("metal_preto", Ml @ T(-0.11, 0, 0.015), 0.22, 0.022, 0.03, 0.006)
        q.almofada("plastico", Ml @ T(-0.20, 0, 0.022), 0.12, 0.034, 0.04, 0.35, 0.4)
        q.cilindro("cromado", Ml @ T(-0.268, 0, 0.022) @ Ry(math.pi / 2), 0.008, 0.012, 16, 0.002)

    def console(self):
        M, e = self.M, self.e
        tipo = e["console"]
        p = self.nova("interior_console", "habitaculo")
        tun_h = 0.13 if self.cfg["tracao"] == "dianteira" else 0.17
        zb = M["z_piso"] + tun_h
        if tipo == "nenhum":
            p.caixa("carpete", T(M["x_painel"] - 0.02, 0, zb + 0.005), 0.22, 0.20, 0.012, 0.004)
            return
        x1 = M["x_painel"] + 0.03
        x0 = {"curto": x1 - 0.30, "medio": M["x_encosto_d"] + 0.30, "longo": M["x_encosto_d"] + 0.02}[tipo]
        p.almofada("plastico", T((x0 + x1) / 2, 0, zb + 0.03), x1 - x0, 0.24, 0.10, 0.18, 0.18)
        if tipo == "longo":
            p.almofada("plastico", T(M["x_encosto_d"] + 0.12, 0, zb + 0.16), 0.30, 0.17, 0.10, 0.22, 0.3)
            for k in range(2):
                p.revolucao("metal_preto", T(M["x_encosto_d"] + 0.42 + k * 0.09, 0, zb + 0.082),
                            [(0.0, -0.06), (0.036, -0.06), (0.037, 0.0), (0.0, 0.0)], 24)
        # rampa até o painel
        p.almofada("plastico", T(x1 - 0.02, 0, (zb + M["z_painel"] - 0.28) / 2), 0.10, 0.22,
                   max(0.08, M["z_painel"] - 0.30 - zb), 0.25, 0.25)

    def cintos(self):
        M = self.M
        p = self.nova("interior_cintos", "habitaculo")
        for s in (1, -1):
            xb = M["coluna_b"] - 0.01
            zt = M["z_cintura"] + 0.30
            yt = self.lado_em(xb, zt, s, folga=0.03)
            ylow = self.lado_em(xb, M["z_piso"] + 0.12, s, folga=0.04)
            topo = V(xb, s * yt, zt)
            # presilha (anel em D) e o cinto descendo pela coluna até o retrator
            p.caixa("plastico", T(*topo) @ Rz(0), 0.05, 0.02, 0.04, 0.008)
            p.cilindro("cromado", T(*topo) @ Rx(math.pi / 2), 0.006, 0.024, 12, 0.002)
            pts = [topo + V(0.0, -s * 0.012, -0.02), V(xb - 0.01, s * (yt - 0.012), M["z_cintura"]),
                   V(xb - 0.01, s * (ylow - 0.01), M["z_piso"] + 0.16)]
            p.fita("cinto", pts, 0.048, 0.003, (0, s, 0))
            p.caixa("plastico", T(xb - 0.01, s * (ylow - 0.02), M["z_piso"] + 0.10), 0.07, 0.05, 0.12, 0.012)
            # lingueta parada a meia altura
            p.caixa("cromado", T(xb - 0.005, s * (yt - 0.03), M["z_cintura"] - 0.12), 0.03, 0.006, 0.05, 0.003)
        # traseiros: subabdominais no assento
        zs = M["z_assento_t"] + 0.03
        for yy in (-0.38, 0.0, 0.38):
            a = V(M["x_encosto_t"] + 0.02, yy - 0.05, zs + 0.01)
            b = V(M["x_encosto_t"] + 0.20, yy + 0.05, zs + 0.015)
            p.fita("cinto", [a, (a + b) / 2 + V(0, 0, 0.01), b], 0.045, 0.003, (0, 0, 1))
            p.caixa("cromado", T(*b) @ Rz(math.radians(30)), 0.05, 0.03, 0.006, 0.002)

    def forro_teto(self):
        M = self.M
        p = self.nova("interior_forro_teto", "habitaculo")
        x0, x1 = M["x_teto_tras"] - 0.1, M["x_teto_frente"] + 0.1
        ym = M["meia_teto"]
        alturas = {}
        # limites do teto por faixa de y (o vidro da frente e o de trás fazem curva nos cantos)
        lim = {}
        for j in range(27):
            y = -ym + 2 * ym * j / 26
            xs = [x0 + (x1 - x0) * k / 60 for k in range(61)]
            ok = [x for x in xs if self.tem_teto(x, y)]
            lim[j] = (min(ok) + 0.025, max(ok) - 0.025) if ok else (M["x_teto_tras"], M["x_teto_frente"])

        lim_y = {}

        def y_max(x):
            k = round(x, 3)
            if k not in lim_y:
                y = ym
                while y > 0.2 and not (self.tem_teto(x, y) and self.tem_teto(x, -y)):
                    y -= 0.02
                lim_y[k] = max(0.2, y - 0.015)
            return lim_y[k]

        def ponto(u, v):
            j = int(round(v * 26))
            a, b = lim[j]
            x = a + (b - a) * u
            y = (-1 + 2 * v) * min(ym, y_max(x))
            k = (round(x, 4), round(y, 4))
            if k not in alturas:
                alturas[k] = self.teto_em(x, y) - 0.012
            z = alturas[k]
            borda = min(u, 1 - u, v, 1 - v)
            if borda < 0.04:
                z -= 0.025 * (1 - borda / 0.04) ** 2
            return V(x, y, z)
        p.grade("forro_teto", 30, 26, ponto, 0.01, normal_fn=lambda u, v: (0, 0, -1))
        # luz de teto
        xl = (x0 + x1) / 2 + 0.1
        zl = self.teto_em(xl, 0) - 0.02
        p.almofada("plastico_claro", T(xl, 0, zl), 0.13, 0.07, 0.025, 0.3, 0.3)
        p.almofada("lente", T(xl, 0, zl - 0.009), 0.09, 0.045, 0.012, 0.3, 0.3)
        # alças de teto (lado do passageiro e de trás)
        for (xx, s) in ((M["x_encosto_d"] + 0.15, -1), (M["x_encosto_t"] + 0.2, 1), (M["x_encosto_t"] + 0.2, -1)):
            yy = s * (min(ym, y_max(xx)) - 0.02)
            zz = self.teto_em(xx, yy) - 0.03
            p.tubo("plastico", [(xx - 0.1, yy, zz), (xx - 0.08, yy - s * 0.03, zz - 0.06), (xx + 0.08, yy - s * 0.03, zz - 0.06),
                                (xx + 0.1, yy, zz)], 0.011, seg=10)

    def quebra_sois_retrovisor(self):
        M = self.M
        p = self.nova("interior_quebra_sois", "habitaculo")
        xf = M["x_teto_frente"] - 0.03
        for s in (1, -1):
            y = s * M["y_banco"]
            z = self.teto_em(xf - 0.12, y) - 0.03
            Ms = T(xf - 0.10, y, z) @ Ry(math.radians(8))
            p.almofada("forro_teto" if self.cfg["epoca"] != "70" else "vinil", Ms, 0.16, 0.36, 0.022, 0.15, 0.2)
            p.tubo("plastico", [Ms @ V(0.06, s * 0.185, 0.0), Ms @ V(0.07, s * 0.21, 0.02)], 0.006, seg=8, sub=1)
            p.caixa("plastico", Ms @ T(0.07, -s * 0.17, 0.015), 0.03, 0.02, 0.02, 0.005)
        q = self.nova("interior_retrovisor", "habitaculo")
        z = self.teto_em(xf, 0) - 0.015
        q.caixa("plastico", T(xf - 0.01, 0, z), 0.06, 0.05, 0.02, 0.008)
        a, b = V(xf - 0.02, 0, z - 0.01), V(xf - 0.05, 0, z - 0.07)
        q.tubo("plastico", [a, b], 0.007, seg=8, sub=1)
        Mm = T(xf - 0.07, 0, z - 0.09) @ Ry(math.radians(-8))
        q.almofada("plastico", Mm, 0.035, 0.25, 0.07, 0.25, 0.3)
        q.almofada("espelho", Mm @ T(-0.012, 0, 0), 0.012, 0.23, 0.055, 0.2, 0.2)

    def acabamentos(self):
        """Colunas A e B por dentro (acabamento), laterais traseiras abaixo da janela e o tampão do porta-malas."""
        M = self.M
        p = self.nova("interior_acabamento_colunas", "habitaculo")
        ws = M["ws"]
        for s in (1, -1):
            # coluna A: da cintura (na base do para-brisa) até o teto (no topo do para-brisa)
            z0a, z1a = ws[4] + 0.02, ws[5] - 0.04
            cacheA = {}

            def pa(u, v, s=s, z0a=z0a, z1a=z1a, cacheA=cacheA):
                z = z0a + (z1a - z0a) * u
                t = (z - ws[4]) / max(0.05, ws[5] - ws[4])
                xw = ws[1] + (ws[0] - ws[1]) * t - 0.02
                y_in = ws[3] - 0.12 - 0.06 * t
                if u not in cacheA:
                    yo = self.y_janela(xw - 0.14, z, s) - 0.03
                    cacheA[u] = max(y_in + 0.04, min(yo, M["W"] - 0.06))
                y_out = cacheA[u]
                y_in = max(y_in, y_out - 0.09)
                y = y_in + (y_out - y_in) * v
                return V(xw - 0.06 - 0.08 * v, s * y, z)
            p.grade("plastico", 10, 4, pa, 0.012, normal_fn=lambda u, v, s=s: (0.5, s * 0.85, 0))
            # coluna B
            xb = M["coluna_b"] - 0.02
            pts = []
            for k in range(6):
                z = M["z_cintura"] + (M["z_teto_int"] - 0.02 - M["z_cintura"]) * k / 5
                pts.append(V(xb, s * self.lado_em(xb, z, s, folga=0.02), z))
            p.fita("plastico", pts, 0.10, 0.02, (0, s, 0))
        # acabamento lateral dos pés (entre a coluna A e o corta-fogo), cobre a chapa
        for s in (1, -1):
            pf = M["portas"].get("f" + ("l" if s > 0 else "r"))
            if not pf:
                continue
            k = self.nova(f"interior_acabamento_pe_{'esq' if s > 0 else 'dir'}", "habitaculo")
            xa, xb = pf["x1"] - 0.01, M["x_corta_fogo"] - 0.02
            za, zb = M["z_piso"] + 0.01, M["z_painel"] - 0.14
            cache2 = {}

            def pk(u, v, s=s, xa=xa, xb=xb, za=za, zb=zb, cache2=cache2):
                x = xa + (xb - xa) * u
                z = za + (zb - za) * v
                kk = (round(x, 4), round(z, 4))
                if kk not in cache2:
                    cache2[kk] = min(self.lado_em(x, z, s, folga=0.02), M["W"] - 0.11)
                return V(x, s * cache2[kk], z)
            k.grade("plastico", 8, 6, pk, 0.012, normal_fn=lambda u, v, s=s: (0, s, 0))
        # laterais traseiras (abaixo da janela de trás), só onde não há porta
        portas = M["portas"]
        for s in (1, -1):
            lado = "l" if s > 0 else "r"
            if ("r" + lado) in portas:
                continue
            q = self.nova(f"interior_lateral_traseira_{'esq' if s > 0 else 'dir'}", "habitaculo")
            xa = M["x_encosto_t"] - 0.10
            xb = (portas.get("f" + lado) or {"x0": M["coluna_b"]})["x0"] - 0.03
            z0, z1 = M["z_piso"] + 0.06, M["z_cintura"] + 0.02
            cache = {}

            def ponto(u, v, s=s, xa=xa, xb=xb, z0=z0, z1=z1, cache=cache):
                x = xa + (xb - xa) * u
                z = z0 + (z1 - z0) * v
                k = (round(x, 4), round(z, 4))
                if k not in cache:
                    cache[k] = self.lado_em(x, z, s, folga=0.02)
                yy = min(cache[k], M["meia_interna"] + 0.06)
                return V(x, s * yy, z)
            q.grade("plastico", 16, 10, ponto, 0.015, normal_fn=lambda u, v, s=s: (0, s, 0))
            xm = (xa + xb) / 2 + 0.08
            yy = self.lado_em(xm, z1 - 0.17, s, folga=0.02)
            q.almofada("banco" if self.e["banco"] != "vinil" else "vinil", T(xm, s * (yy - 0.04), z1 - 0.17), 0.30, 0.07, 0.05, 0.3, 0.35)
            q.caixa("plastico_liso", T(xm + 0.2, s * (yy - 0.01), z1 - 0.10), 0.07, 0.012, 0.04, 0.004)

    # ================================================================================================================ PORTAS
    def portas(self):
        for pos, d in self.M["portas"].items():
            self.forro_porta(pos, d)
            self.vao_porta(pos, d)

    def _y_dentro_porta(self, pos, x, z, s):
        """Face de dentro da porta em (x, z); se o raio não pega a porta (borda), usa o ponto mais perto que pega."""
        M = self.M
        if self.casca:
            for dz, dx in ((0, 0), (-0.03, 0), (-0.06, 0), (0, 0.03), (0, -0.03), (-0.1, 0), (-0.15, 0), (0.03, 0), (-0.06, 0.05),
                           (-0.06, -0.05), (-0.2, 0)):
                h = self.casca.raio([f"door_{pos}"], (x + dx, s * 0.1, z + dz), (0, s, 0), 1.2)
                if h:
                    return abs(h[0].y)
        return M["W"] - 0.06

    def forro_porta(self, pos, d):
        M, e = self.M, self.e
        s = d["lado"]
        x0, x1 = d["x0"] + 0.03, d["x1"] - 0.03
        z0, z1 = d["z0"] + 0.03, min(d["z1"], M["z_cintura"] + 0.01) - 0.01
        L = x1 - x0
        segue = f"door_{pos}"
        cache = {}

        def yin(x, z):
            k = (round(x, 3), round(z, 3))
            if k not in cache:
                cache[k] = self._y_dentro_porta(pos, x, z, s)
            return cache[k]

        # chapa interna (aparece quando o forro solta): moldura com recortes, bordas da porta pintadas, máquina do vidro, fechadura
        c = self.nova(f"door_card_{pos}_chapa", "porta", segue, "chapa interna da porta (some o forro, fica ela)")
        ej = 0.012
        for (u0, u1, v0, v1) in ((0, 1, 0, 0.12), (0, 1, 0.84, 1.0), (0, 0.10, 0, 1), (0.90, 1, 0, 1), (0, 1, 0.46, 0.56),
                                 (0.46, 0.54, 0, 1)):
            xa, xb = x0 - 0.02 + (L + 0.04) * u0, x0 - 0.02 + (L + 0.04) * u1
            za, zb = z0 - 0.02 + (z1 - z0 + 0.03) * v0, z0 - 0.02 + (z1 - z0 + 0.03) * v1

            def ponto(u, v, xa=xa, xb=xb, za=za, zb=zb):
                x = xa + (xb - xa) * u
                z = za + (zb - za) * v
                return V(x, s * (yin(x, z) - 0.002), z)
            c.grade("pintura_interna", 4, 3, ponto, ej, normal_fn=lambda u, v: (0, s, 0))
        # bordas da porta (frente, trás, embaixo): dão a espessura de porta de verdade
        prof = 0.085
        for (xa, xb, za, zb) in ((d["x0"] + 0.003, d["x0"] + 0.012, d["z0"], z1 + 0.01),
                                 (d["x1"] - 0.012, d["x1"] - 0.003, d["z0"], z1 + 0.01),
                                 (d["x0"] + 0.003, d["x1"] - 0.003, d["z0"] + 0.002, d["z0"] + 0.012)):
            xm, zm = (xa + xb) / 2, (za + zb) / 2
            yy = yin(xm, zm) - prof / 2 + 0.004
            c.caixa("pintura_interna", T(xm, s * yy, zm), xb - xa, prof, zb - za, 0.003)
        # máquina do vidro: trilhos e cabo
        for xr in (x0 + 0.30 * L, x0 + 0.62 * L):
            c.caixa("aluminio", T(xr, s * (yin(xr, (z0 + z1) / 2) - 0.03), (z0 + z1) / 2 - 0.02), 0.025, 0.012, z1 - z0 - 0.12, 0.003)
        c.tubo("metal_preto", [(x0 + 0.30 * L, s * (yin(x0 + 0.3 * L, z0 + 0.1) - 0.035), z0 + 0.12),
                               (x0 + 0.46 * L, s * (yin(x0 + 0.46 * L, z0 + 0.2) - 0.04), (z0 + z1) / 2),
                               (x0 + 0.62 * L, s * (yin(x0 + 0.62 * L, z1 - 0.1) - 0.035), z1 - 0.10)], 0.003, seg=6)
        # fechadura na borda de trás e varetas
        c.caixa("metal_preto", T(d["x0"] + 0.035, s * (yin(x0, z1 - 0.15) - 0.04), z1 - 0.15), 0.05, 0.04, 0.09, 0.006)
        c.tubo("cromado", [(d["x0"] + 0.06, s * (yin(x0, z1 - 0.12) - 0.03), z1 - 0.12),
                           (x1 - 0.15, s * (yin(x1 - 0.15, z1 - 0.09) - 0.03), z1 - 0.09)], 0.0025, seg=6, sub=1)
        # metades das dobradiças na borda da frente
        for zz in (d["z0"] + 0.12, z1 - 0.12):
            c.caixa("metal_preto", T(d["x1"] + 0.004, s * (yin(x1, zz) - 0.04), zz), 0.012, 0.05, 0.07, 0.004)
            c.cilindro("aluminio", T(d["x1"] + 0.012, s * (yin(x1, zz) - 0.07), zz), 0.009, 0.08, 16, 0.002)
        if e.get("alto_falante_porta"):
            xf, zf = x1 - 0.13, z0 + 0.15
            c.cilindro("metal_preto", T(xf, s * (yin(xf, zf) - 0.03), zf) @ Rx(math.pi / 2), 0.045, 0.04, 24, 0.004)

        # forro
        f = self.nova(f"door_card_{pos}", "porta", segue, "forro interno da porta")
        bas = "plastico"
        esp = 0.022

        def ponto(u, v):
            x = x0 + L * u
            z = z0 + (z1 - z0) * v
            return V(x, s * (yin(x, z) - 0.018), z)
        f.grade(bas, 22, 14, ponto, esp, normal_fn=lambda u, v: (0, s, 0))
        # parte de tecido (ou vinil) no meio
        mio = "vinil" if e["banco"] == "vinil" else ("listrado" if self.cfg["epoca"] == "80" else "banco_miolo")
        za, zb = z0 + 0.20, z1 - 0.14
        xa, xb = x0 + 0.06, x1 - 0.07
        if zb > za + 0.05:
            def pm(u, v):
                x = xa + (xb - xa) * u
                z = za + (zb - za) * v
                bord = min(u, 1 - u, v, 1 - v)
                inch = 0.008 * min(1.0, bord / 0.08)
                return V(x, s * (yin(x, z) - 0.018 - esp - inch), z)
            f.grade(mio, 18, 8, pm, 0.004, normal_fn=lambda u, v: (0, s, 0))
        # capa de cima (friso da cintura) com a borracha do vidro
        xt0, xt1 = x0 - 0.01, x1 + 0.01
        n = 8
        pts = [V(xt0 + (xt1 - xt0) * k / n, 0, z1 - 0.012) for k in range(n + 1)]
        for q in pts:
            q.y = s * (yin(q.x, q.z) - 0.035)
        f.fita(bas, pts, 0.05, 0.035, (0, 0, 1))
        pts2 = [V(q.x, s * (abs(q.y) + 0.012), z1 + 0.008) for q in pts]
        f.fita("borracha", pts2, 0.008, 0.012, (0, 0, 1))
        # apoio de braço / puxador
        xm = x0 + 0.44 * L
        zm = z1 - 0.18
        ya = yin(xm, zm) - 0.018 - esp
        f.almofada(mio if e["banco"] == "vinil" else bas, T(xm, s * (ya - 0.035), zm), min(0.32, 0.5 * L), 0.075, 0.05, 0.3, 0.35)
        f.caixa("plastico", T(xm + 0.05, s * (ya - 0.03), zm - 0.045), 0.16, 0.05, 0.03, 0.01)
        if e.get("vidro_eletrico"):
            for k in range(2):
                f.caixa("plastico_liso", T(xm + 0.10 - k * 0.035, s * (ya - 0.045), zm + 0.027), 0.025, 0.018, 0.008, 0.003)
        # maçaneta interna em concha
        xh, zh = x1 - 0.17, z1 - 0.075
        yh = yin(xh, zh) - 0.018 - esp
        f.almofada("plastico_liso", T(xh, s * (yh - 0.004), zh), 0.12, 0.012, 0.045, 0.25, 0.25)
        f.caixa("cromado" if self.cfg["epoca"] in ("70", "80") else "plastico_liso", T(xh + 0.005, s * (yh - 0.012), zh),
                0.085, 0.01, 0.018, 0.004)
        # bolso de baixo
        xb0, xb1 = x0 + 0.06, x1 - (0.26 if e.get("alto_falante_porta") else 0.08)
        if xb1 - xb0 > 0.15:
            zb0, zb1 = z0 + 0.02, z0 + 0.14
            for (yy, w) in ((0.065, 0.012),):
                xc = (xb0 + xb1) / 2
                yb_ = yin(xc, zb0) - 0.018 - esp
                f.caixa(bas, T(xc, s * (yb_ - yy), (zb0 + zb1) / 2), xb1 - xb0, w, zb1 - zb0, 0.005)
                f.caixa(bas, T(xc, s * (yb_ - yy / 2), zb0 + 0.006), xb1 - xb0, yy, 0.012, 0.004)
                for xx in (xb0, xb1):
                    f.caixa(bas, T(xx, s * (yb_ - yy / 2), (zb0 + zb1) / 2), 0.012, yy, zb1 - zb0, 0.004)
        # alto-falante
        if e.get("alto_falante_porta"):
            xf, zf = x1 - 0.13, z0 + 0.15
            yf = yin(xf, zf) - 0.018 - esp
            Mf = T(xf, s * (yf - 0.002), zf) @ Rx(s * math.pi / 2)
            f.toro("plastico", Mf, 0.068, 0.008, 0.005, 36, 8)
            f.disco_uv("alto_falante", Mf @ T(0, 0, 0.001), 0.064)
        # manivela
        if e.get("manivela"):
            xm2, zm2 = x0 + 0.62 * L, z1 - 0.26
            ym = yin(xm2, zm2) - 0.018 - esp
            Mr = T(xm2, s * ym, zm2) @ Rx(s * math.pi / 2)
            f.revolucao("plastico_liso", Mr, [(0, 0), (0.03, 0), (0.028, 0.006), (0.012, 0.012), (0, 0.014)], 24)
            braco = [Mr @ V(0, 0, 0.012), Mr @ V(0.05, -0.04, 0.02), Mr @ V(0.085, -0.07, 0.022)]
            f.tubo("cromado", braco, 0.006, seg=8)
            f.revolucao("plastico_liso", T(*braco[-1]) @ alinhar_z(Mr.to_3x3() @ V(0, 0, 1)),
                        [(0, 0), (0.011, 0.002), (0.012, 0.03), (0.009, 0.04), (0, 0.042)], 16)
        # pino da trava
        if e.get("pino_trava"):
            xp_ = x0 + 0.06
            f.revolucao("cromado" if self.cfg["epoca"] == "70" else "plastico_liso", T(xp_, s * (yin(xp_, z1) - 0.04), z1 + 0.01),
                        [(0, 0), (0.0045, 0), (0.0045, 0.035), (0.0055, 0.04), (0.0035, 0.046), (0, 0.047)], 12)

    def vao_porta(self, pos, d):
        """Soleira, colunas por dentro, teto da porta, borracha, dobradiças e batente, no carro (ficam quando a porta sai)."""
        M = self.M
        s = d["lado"]
        x0, x1 = d["x0"], d["x1"]
        zs = M["z_saia"]
        zc = min(d["z1"], M["z_cintura"])
        zj = d["z_janela"] + 0.01
        frente = pos[0] == "f"
        incl = M["inclinacao_para_brisa"] * 0.85
        if frente:
            xa_top = _limitar(x1 - incl * (zj - zc), d["x_vidro"][0] + 0.25, x1 - 0.04)
            xb_top = x0
        else:
            xa_top = x1
            xb_top = x0 + 0.08
        g = f"jamb_{pos}"
        W = M["W"]
        # soleira
        p = self.nova(f"{g}_soleira", "vao_porta")
        ys = self.lado_em((x0 + x1) / 2, zs - 0.05, s, folga=0.0)
        ys = min(ys, W - 0.005)
        p.caixa("pintura_interna", T((x0 + x1) / 2, s * (ys - 0.05), zs - 0.045), x1 - x0 + 0.02, 0.10, 0.09, 0.012)
        p.caixa("plastico", T((x0 + x1) / 2 - 0.02, s * (ys - 0.112), zs - 0.035), x1 - x0 + 0.06, 0.03, 0.11, 0.01)
        p.caixa("plastico" if self.cfg["epoca"] != "70" else "aluminio", T((x0 + x1) / 2, s * (ys - 0.075), zs + 0.004),
                x1 - x0 - 0.04, 0.10, 0.008, 0.004)
        for k in range(6):
            p.caixa("borracha", T(x0 + 0.06 + (x1 - x0 - 0.12) * k / 5, s * (ys - 0.075), zs + 0.009), 0.012, 0.08, 0.003, 0.001, 1)
        # coluna da frente (A ou B) e de trás (B ou C), pintadas por dentro, com a parte inclinada acima da cintura
        q = self.nova(f"{g}_colunas", "vao_porta")
        prof = 0.13
        for (xx, sinal) in ((x1 + 0.006, 1), (x0 - 0.006, -1)):
            yy = self.lado_em(xx + sinal * 0.02, (zs + zc) / 2, s, folga=0.0)
            yy = min(yy, W - 0.005)
            q.caixa("pintura_interna", T(xx, s * (yy - prof / 2), (zs + zc) / 2), 0.012, prof, zc - zs, 0.004)
        # parte de cima: inclinada na frente (coluna A) ou reta (B), e o friso do teto
        ya = min(self.lado_em(x1, zc + 0.05, s), W - 0.02)
        a, b = V(x1 + 0.006, s * (ya - 0.05), zc), V(xa_top + 0.006, s * (min(self.y_janela(xa_top, zj - 0.03, s, pos), W - 0.06) - 0.05), zj)
        q.fita("pintura_interna", [a, b], 0.10, 0.012, (1, 0, -incl * 0.5) if frente else (1, 0, 0))
        a2 = V(x0 - 0.006, s * (min(self.lado_em(x0, zc, s), W - 0.02) - 0.05), zc)
        b2 = V(xb_top - 0.006, s * (min(self.y_janela(xb_top, zj - 0.03, s, pos), W - 0.06) - 0.05), zj)
        q.fita("pintura_interna", [a2, b2], 0.10, 0.012, (1, 0, 0))
        topo = [V(xb_top + (xa_top - xb_top) * k / 6, 0, zj + 0.008) for k in range(7)]
        for t in topo:
            t.y = s * (min(self.y_janela(t.x, zj - 0.03, s, pos), W - 0.06) - 0.04)
        q.fita("pintura_interna", topo, 0.09, 0.012, (0, 0, 1))
        # borracha de vedação em volta do vão
        r = self.nova(f"{g}_borracha", "vao_porta")
        contorno = [V(x0 + 0.02, 0, zs + 0.02), V(x1 - 0.02, 0, zs + 0.02), V(x1 - 0.015, 0, zc),
                    V(xa_top - 0.01, 0, zj - 0.01), V(xb_top + 0.02, 0, zj - 0.01), V(x0 + 0.015, 0, zc), V(x0 + 0.02, 0, zs + 0.02)]
        dens = []
        for i in range(len(contorno) - 1):
            a, b = contorno[i], contorno[i + 1]
            n = max(2, int((b - a).length / 0.05))
            for k in range(n):
                dens.append(a.lerp(b, k / n))
        dens.append(contorno[-1])
        for t in dens:
            if t.z > zc + 0.01:
                t.y = s * (min(self.y_janela(t.x, t.z, s, pos), W - 0.01) - 0.03)
            else:
                t.y = s * (min(self.lado_em(t.x, t.z, s), W - 0.01) - 0.035)
        r.tubo("borracha", dens, 0.011, seg=10, sub=1, tampa=False)
        # dobradiças (na coluna da frente do vão), limitador e batente (na coluna de trás)
        h = self.nova(f"{g}_dobradicas", "vao_porta")
        for zz in (zs + 0.12, zc - 0.12):
            yy = min(self.lado_em(x1, zz, s), W - 0.01) - 0.035
            h.caixa("metal_preto", T(x1 + 0.012, s * yy, zz), 0.012, 0.05, 0.075, 0.004)
            h.cilindro("aluminio", T(x1 + 0.004, s * (yy + 0.012), zz), 0.009, 0.085, 16, 0.002)
            h.caixa("metal_preto", T(x1 + 0.004, s * (yy + 0.03), zz), 0.03, 0.012, 0.06, 0.003)
        zl = (zs + zc) / 2
        yy = min(self.lado_em(x1, zl, s), W - 0.01) - 0.05
        h.caixa("metal_preto", T(x1 - 0.02, s * yy, zl), 0.06, 0.018, 0.022, 0.005)
        b = self.nova(f"{g}_batente", "vao_porta")
        zt = zc - 0.13
        yy = min(self.lado_em(x0, zt, s), W - 0.01) - 0.05
        b.caixa("aluminio", T(x0 - 0.010, s * yy, zt), 0.006, 0.04, 0.07, 0.002)
        b.tubo("cromado", [(x0 - 0.010, s * (yy - 0.012), zt - 0.018), (x0 + 0.012, s * (yy - 0.012), zt - 0.018),
                           (x0 + 0.012, s * (yy - 0.012), zt + 0.018), (x0 - 0.010, s * (yy - 0.012), zt + 0.018)], 0.0045, seg=8, sub=2)
        for zz in (zt - 0.028, zt + 0.028):
            b.cilindro("cromado", T(x0 - 0.014, s * yy, zz) @ Ry(math.pi / 2), 0.007, 0.006, 6, 0.001)

    # ================================================================================================================ PORTA-MALAS
    def porta_malas(self):
        M = self.M
        frente = M["motor_traseiro"]
        if frente:
            self.porta_malas_frente()
            return
        p = self.nova("interior_portamalas_carpete", "porta_malas")
        x0, x1 = M["x_mala_tras"], M["x_mala_frente"]
        ym = M["W"] - 0.16
        zm = M["z_mala"]
        Rs = M["R"] * 0.96
        estepe = self.cfg["estepe"]
        cx_e = x0 + Rs + 0.10
        poco = estepe == "poco"

        def ponto(u, v):
            x = x0 + (x1 - x0) * u
            y = -ym + 2 * ym * v
            z = zm
            if poco:
                r = math.hypot(x - cx_e, y)
                if r < Rs + 0.04:
                    z -= 0.17
                elif r < Rs + 0.10:
                    z -= 0.17 * (0.5 + 0.5 * math.cos(math.pi * (r - Rs - 0.04) / 0.06))
            return V(x, y, z)
        p.grade("carpete", 36, 28, ponto, 0.012, normal_fn=lambda u, v: (0, 0, 1))
        # laterais (com a caixa de roda) e parede do fundo
        for s in (1, -1):
            def pl(u, v, s=s):
                x = x0 + (x1 - x0) * u
                z = zm + (M["z_cintura"] - 0.04 - zm) * v
                y = ym + 0.01
                dx = abs(x - M["xt"])
                if dx < M["R"] + 0.12 and z < M["R"] * 2 + 0.12:
                    k = 1 - dx / (M["R"] + 0.12)
                    y -= 0.12 * min(1, k * 2.5) * (1 - max(0, (z - zm - 0.16) / 0.25)) if z > zm else 0
                return V(x, s * y, z)
            p.grade("carpete", 20, 8, pl, 0.012, normal_fn=lambda u, v, s=s: (0, -s, 0))
        zf = M["z_tampa_tras_borda"]
        p.caixa("pintura_interna", T(x0 - 0.01, 0, (zm + zf) / 2), 0.02, 2 * ym, zf - zm, 0.006)
        p.caixa("plastico", T(x0, 0, zf + 0.005), 0.05, 2 * ym - 0.02, 0.012, 0.005)
        p.tubo("cromado", [(x0 - 0.005, -0.03, zf + 0.01), (x0 + 0.02, -0.03, zf + 0.03), (x0 + 0.02, 0.03, zf + 0.03),
                           (x0 - 0.005, 0.03, zf + 0.01)], 0.005, seg=8, sub=2)
        # estepe
        e = self.nova("interior_portamalas_estepe", "porta_malas")
        if poco:
            Me = T(cx_e, 0, zm - 0.17 + 0.09)
        elif estepe == "lateral":
            Me = T(x0 + Rs + 0.15, ym - 0.12, zm + Rs + 0.02) @ Rx(math.pi / 2)
        else:
            Me = T(cx_e, 0, zm + 0.10)
        self._roda_estepe(e, Me, Rs)
        if estepe == "lateral":
            e.fita("borracha", [Me @ V(0, Rs + 0.02, -0.06), Me @ V(0, Rs + 0.02, 0.1), Me @ V(0.0, 0.0, 0.1)], 0.03, 0.004, (1, 0, 0))
        # lanternas por dentro
        self._lanternas_dentro()
        # tampão (hatch) ou prateleira fixa (sedã)
        t = self.nova("interior_portamalas_tampao", "porta_malas")
        rg = M["rg"]
        xa = M["x_encosto_t"] - 0.10
        xb = rg[0] + 0.05 if self.cfg["carroceria"] != "hatch" else max(rg[0] + 0.12, x0 + 0.12)
        zt = M["z_cintura"] + 0.02
        t.caixa("plastico" if self.cfg["carroceria"] == "hatch" else "carpete", T((xa + xb) / 2, 0, zt), xa - xb,
                2 * (M["W"] - 0.17), 0.014, 0.006)
        if self.cfg["carroceria"] != "hatch":
            for s in (1, -1):
                t.disco_uv("alto_falante", T((xa + xb) / 2 - 0.05, s * 0.45, zt + 0.0075), 0.07)

    def _roda_estepe(self, p, Me, R):
        """Estepe: pneu e roda de aço (deitado no Z local)."""
        lr = 0.165 * R / 0.29
        L = 0.17 * R / 0.29
        perfil = [(R * 0.62, -L / 2), (R * 0.80, -L / 2 - 0.01), (R * 0.95, -L / 2 + 0.005), (R, -L / 2 + 0.03), (R, L / 2 - 0.03),
                  (R * 0.95, L / 2 - 0.005), (R * 0.80, L / 2 + 0.01), (R * 0.62, L / 2)]
        perfil = perfil + [(R * 0.62, -L / 2)]
        p.revolucao("borracha", Me, perfil, 48)
        p.revolucao("metal_preto", Me, [(R * 0.63, -L / 2 + 0.01), (lr, -L / 2 + 0.02), (lr * 0.9, -0.01), (lr * 0.55, 0.0),
                                        (lr * 0.35, 0.02), (0.03, 0.025), (0, 0.025)], 40)
        for k in range(4):
            a = 2 * math.pi * k / 4
            p.cilindro("cromado", Me @ T(0.05 * math.cos(a), 0.05 * math.sin(a), 0.028), 0.009, 0.012, 6, 0.002)

    def _lanternas_dentro(self):
        M = self.M
        p = self.nova("interior_portamalas_lanternas", "porta_malas")
        cx, _ = caixas_do_mapa({"parts": self._mapa_parts})
        for nome in ("taillight_left", "taillight_right"):
            b = cx.get(nome)
            if not b:
                continue
            xc, yc, zc = b[1] + 0.03, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2
            yc = math.copysign(min(abs(yc), M["W"] - 0.20), yc)
            p.caixa("metal_preto", T(xc + 0.03, yc, zc), 0.06, min(0.30, b[3] - b[2]), max(0.08, b[5] - b[4]), 0.01)
            for k in range(3):
                yy = yc + (k - 1) * 0.06
                p.cilindro("plastico_liso", T(xc + 0.07, yy, zc) @ Ry(math.pi / 2), 0.014, 0.03, 16, 0.003)
            p.tubo("metal_preto", [(xc + 0.08, yc, zc), (xc + 0.15, yc * 0.92, zc + 0.05), (xc + 0.35, yc * 0.85, zc + 0.08)],
                   0.004, seg=6)

    def porta_malas_frente(self):
        """Motor traseiro: porta-malas na frente, sob a tampa da frente, com estepe inclinado, tanque e reservatórios."""
        M = self.M
        p = self.nova("interior_portamalas_carpete", "porta_malas")
        x0, x1 = M["x_corta_fogo"] + 0.02, M["x_frente"] - 0.25
        yb = M["y_caixa_d"] - 0.02
        zf = M["z_piso"] + 0.02
        p.caixa("carpete", T((x0 + x1) / 2, 0, zf), x1 - x0, 2 * yb, 0.02, 0.008)
        for s in (1, -1):
            p.caixa("pintura_interna", T((x0 + x1) / 2, s * yb, zf + 0.20), x1 - x0, 0.015, 0.40, 0.006)
        p.caixa("pintura_interna", T(x0, 0, (zf + M["z_capo_tras"]) / 2), 0.015, 2 * yb, M["z_capo_tras"] - zf, 0.006)
        e = self.nova("interior_portamalas_estepe", "porta_malas")
        Rs = M["R"] * 0.96
        Me = T(x1 - 0.12, 0, zf + Rs * 0.85) @ Ry(math.radians(-62))
        self._roda_estepe(e, Me, Rs)
        t = self.nova("under_tanque", "embaixo", nota="tanque na frente (motor traseiro)")
        t.almofada("metal_preto", T(x0 + 0.20, 0, zf + 0.18), 0.32, 2 * yb - 0.15, 0.30, 0.15, 0.2)
        t.tubo("metal_preto", [(x0 + 0.20, 0.18, zf + 0.33), (x0 + 0.24, 0.30, zf + 0.42), (x0 + 0.30, 0.35, M["z_capo_tras"] - 0.04)],
               0.022, seg=12)
        t.cilindro("metal_preto", T(x0 + 0.30, 0.35, M["z_capo_tras"] - 0.04), 0.04, 0.03, 20, 0.006)
        r = self.nova("engine_reservatorios", "motor", nota="reservatórios do freio e do limpador no porta-malas da frente")
        r.almofada("reservatorio", T(x0 + 0.06, 0.32, zf + 0.30), 0.08, 0.10, 0.12, 0.25, 0.3)
        r.cilindro("metal_preto", T(x0 + 0.06, 0.32, zf + 0.37), 0.022, 0.025, 16, 0.004)
        r.almofada("reservatorio", T(x0 + 0.08, -0.30, zf + 0.15), 0.12, 0.10, 0.22, 0.25, 0.3)
        r.cilindro("plastico", T(x0 + 0.08, -0.30, zf + 0.27), 0.02, 0.03, 16, 0.004)
        self._lanternas_dentro()

    # ================================================================================================================ MOTOR
    def vao_motor(self):
        M = self.M
        if M["motor_traseiro"]:
            self.motor_boxer()
            return
        xf, xr = M["x_corta_fogo"], M["x_radiador"]
        yb = M["y_caixa_d"]
        zfundo = max(0.16, M["R"] * 0.70)
        zcap_t = self.capo_em(xf + 0.06, 0)
        zcap_f = self.capo_em(xr - 0.05, 0)

        def zcap(x):
            t = _limitar((x - xf) / max(0.1, xr - xf), 0, 1)
            return zcap_t + (zcap_f - zcap_t) * t
        # para-lamas internos com torres
        for s in (1, -1):
            p = self.nova(f"engine_paralama_interno_{'esq' if s > 0 else 'dir'}", "motor")

            def pw(u, v, s=s):
                x = xf + (xr - xf) * u
                z = zfundo + (zcap(x) - 0.05 - zfundo) * v
                dx = abs(x - M["xd"])
                y = yb
                if dx < M["R"] + 0.10 and z < M["R"] * 2 + 0.05:
                    y -= 0.06 * (1 - dx / (M["R"] + 0.10))
                return V(x, s * y, z)
            p.grade("pintura_interna", 24, 8, pw, 0.012, normal_fn=lambda u, v, s=s: (0, -s, 0))
            zt = zcap(M["xd"]) - 0.09
            self.topo_torre = zt
            Mt = T(M["xd"], s * (yb - 0.075), zt)
            a0, a1 = (math.pi, 2 * math.pi) if s > 0 else (0.0, math.pi)
            p.revolucao("pintura_interna", Mt @ T(0, s * 0.075, -0.30) @ Rz(0), [(0.0, 0.0), (0.13, 0.0), (0.12, 0.24), (0.10, 0.29),
                                                                                  (0.05, 0.30), (0, 0.30)], 24, a0=a0, a1=a1)
            p.revolucao("borracha", Mt, [(0, 0.0), (0.04, 0.0), (0.04, 0.025), (0, 0.03)], 20)
            p.cilindro("aluminio", Mt @ T(0, 0, 0.04), 0.008, 0.03, 8, 0.002)
            for k in range(3):
                a = 2 * math.pi * k / 3
                p.cilindro("aluminio", Mt @ T(0.07 * math.cos(a), 0.07 * math.sin(a), 0.012), 0.009, 0.012, 6, 0.002)
            # aba de cima
            pts = [V(xf + (xr - xf) * k / 8, s * (yb + 0.02), zcap(xf + (xr - xf) * k / 8) - 0.045) for k in range(9)]
            p.fita("pintura_interna", pts, 0.05, 0.01, (0, 0, 1))
            # longarina
            q = self.nova(f"engine_longarina_{'esq' if s > 0 else 'dir'}", "motor")
            q.caixa("chassi", T((xf - 0.1 + M["x_frente"] - 0.10) / 2, s * (yb - 0.12), zfundo + 0.05),
                    M["x_frente"] - 0.10 - xf + 0.1, 0.07, 0.10, 0.012)
        # corta-fogo e a caixa de ar embaixo do para-brisa
        c = self.nova("engine_corta_fogo", "motor")
        c.caixa("pintura_interna", T(xf + 0.006, 0, (zfundo + zcap_t) / 2), 0.012, 2 * yb, zcap_t - zfundo, 0.006)
        c.caixa("plastico", T(xf + 0.06, 0, zcap_t - 0.03), 0.12, 2 * yb - 0.04, 0.012, 0.005)
        c.cilindro("metal_preto", T(xf + 0.06, -0.35, zcap_t - 0.07) @ Rx(math.pi / 2), 0.04, 0.10, 20, 0.008)
        # servo-freio e cilindro mestre com reservatório (lado do motorista)
        yb_ = M["y_banco"]
        Ms = T(xf + 0.10, yb_, zcap_t - 0.18) @ Ry(math.pi / 2)
        c.revolucao("metal_preto", Ms, [(0, -0.09), (0.11, -0.085), (0.12, -0.04), (0.12, 0.04), (0.11, 0.085), (0, 0.09)], 36)
        c.cilindro("aluminio", Ms @ T(0, 0, 0.16), 0.03, 0.14, 20, 0.004)
        c.almofada("reservatorio", T(xf + 0.25, yb_, zcap_t - 0.10), 0.07, 0.09, 0.07, 0.3, 0.3)
        c.cilindro("amarelo", T(xf + 0.25, yb_, zcap_t - 0.058), 0.02, 0.02, 16, 0.004)
        # travessa da frente, radiador e ventoinha
        t = self.nova("engine_travessa", "motor")
        t.caixa("pintura_interna", T(xr + 0.03, 0, zcap_f - 0.06), 0.06, 2 * yb, 0.05, 0.01)
        t.caixa("pintura_interna", T(xr + 0.03, 0, zfundo + 0.06), 0.06, 2 * yb, 0.05, 0.01)
        for s in (1, -1):
            t.caixa("pintura_interna", T(xr + 0.03, s * (yb - 0.05), (zcap_f + zfundo) / 2), 0.05, 0.08, zcap_f - zfundo, 0.01)
        t.caixa("metal_preto", T(xr + 0.01, 0, zcap_f - 0.05), 0.04, 0.08, 0.05, 0.006)
        rad = self.nova("engine_radiador", "motor")
        hr = zcap_f - zfundo - 0.17
        wr = 2 * yb - 0.24
        zr = (zcap_f + zfundo) / 2 - 0.01
        rad.caixa("radiador", T(xr, 0, zr), 0.035, wr - 0.10, hr, 0.004)
        for s in (1, -1):
            rad.caixa("plastico", T(xr, s * (wr / 2 - 0.03), zr), 0.05, 0.06, hr + 0.02, 0.008)
        rad.cilindro("metal_preto", T(xr, wr / 2 - 0.03, zr + hr / 2 + 0.03), 0.025, 0.03, 20, 0.004)
        v = self.nova("engine_ventoinha", "motor")
        Mv = T(xr - 0.05, -0.10, zr) @ Ry(-math.pi / 2)
        rv = min(0.17, hr / 2 - 0.01)
        v.revolucao("plastico", Mv, [(rv + 0.02, -0.02), (rv + 0.03, -0.02), (rv + 0.025, 0.04), (rv + 0.008, 0.045), (rv + 0.008, -0.015)], 40)
        v.cilindro("metal_preto", Mv @ T(0, 0, 0.06), 0.045, 0.06, 24, 0.006)
        for k in range(7):
            a = 2 * math.pi * k / 7
            v.caixa("plastico", Mv @ Rz(a) @ T(rv / 2 + 0.025, 0, 0.012) @ Rx(math.radians(28)), rv - 0.04, 0.05, 0.004, 0.0015, 1)
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            v.caixa("plastico", Mv @ Rz(a) @ T(rv / 2 + 0.03, 0, 0.05), rv - 0.02, 0.012, 0.012, 0.003)
        # motor
        if self.cfg["motor"] == "v8_longitudinal":
            pos = self.motor_v8(xf, xr, zfundo, zcap, yb)
        else:
            pos = self.motor_l4(xf, xr, zfundo, zcap, yb, transversal=self.cfg["motor"] == "l4_transversal")
        # bateria, reservatórios, filtro de ar e mangueiras
        self.bateria(T(xr - 0.18, yb - 0.17, zfundo + 0.18))
        r = self.nova("engine_reservatorios", "motor")
        xa = xr - 0.12
        r.almofada("reservatorio", T(xf + 0.20, -(yb - 0.12), zcap(xf + 0.2) - 0.17), 0.16, 0.10, 0.14, 0.25, 0.3)
        r.cilindro("metal_preto", T(xf + 0.20, -(yb - 0.12), zcap(xf + 0.2) - 0.095), 0.025, 0.025, 20, 0.004)
        r.almofada("reservatorio", T(xa, -(yb - 0.10), zfundo + 0.20), 0.12, 0.10, 0.22, 0.25, 0.3)
        r.cilindro("plastico", T(xa, -(yb - 0.10), zfundo + 0.32), 0.018, 0.03, 16, 0.004)
        m = self.nova("engine_mangueiras", "motor")
        m.tubo("borracha", [(xr - 0.02, wr / 2 - 0.10, zr + hr / 2 - 0.03), (xr - 0.15, wr / 2 - 0.15, zr + hr / 2),
                            pos["termostato"]], 0.019, seg=12)
        m.tubo("borracha", [(xr - 0.02, -(wr / 2 - 0.10), zr - hr / 2 + 0.04), (xr - 0.12, -(wr / 2 - 0.2), zr - hr / 2 + 0.02),
                            pos["bomba"]], 0.02, seg=12)
        for dy in (-0.05, 0.05):
            m.tubo("borracha", [pos["aquecedor"] + V(0, dy, 0), (xf + 0.12, dy - 0.1, pos["aquecedor"][2] + 0.05),
                                (xf + 0.01, dy - 0.15, zcap_t - 0.20)], 0.009, seg=8)
        m.tubo("borracha", [pos["filtro_saida"], pos["admissao"]], 0.035, seg=16)
        m.tubo("metal_preto", [(xr - 0.12, yb - 0.08, zfundo + 0.33), (xf + 0.2, yb - 0.05, zcap_t - 0.10), (xf + 0.05, yb - 0.1, zcap_t - 0.12)],
               0.008, seg=6)

    def bateria(self, Mb):
        b = self.nova("engine_bateria", "motor")
        b.caixa("bateria", Mb, 0.17, 0.24, 0.19, 0.01)
        b.caixa("bateria", Mb @ T(0, 0, 0.1), 0.15, 0.22, 0.012, 0.004)
        for k, cor in ((-1, "vermelho"), (1, "metal_preto")):
            b.cilindro("fundido", Mb @ T(0.05, k * 0.08, 0.115), 0.009, 0.02, 12, 0.002)
            b.caixa(cor, Mb @ T(0.05, k * 0.08, 0.125), 0.03, 0.04, 0.012, 0.004)
        b.caixa("metal_preto", Mb @ T(0, 0, 0.102), 0.02, 0.26, 0.008, 0.002)
        for k in range(6):
            b.cilindro("bateria", Mb @ T(-0.04, -0.09 + k * 0.036, 0.109), 0.008, 0.006, 10, 0.001)
        b.tubo("vermelho", [Mb @ V(0.05, -0.08, 0.13), Mb @ V(0.10, -0.12, 0.16), Mb @ V(0.15, -0.30, 0.10)], 0.007, seg=8)

    def motor_l4(self, xf, xr, zf, zcap, yb, transversal=True):
        p = self.nova("engine_motor", "motor", nota="motor de 4 cilindros, câmbio, coletores, alternador")
        xc = (xf + xr) / 2 - 0.02
        if transversal:
            Mm = T(xc, -0.10, zf + 0.25) @ S(1.12, 1.1, 1.12)
        else:
            Mm = T(xc, 0, zf + 0.25) @ Rz(math.pi / 2) @ S(1.12, 1.1, 1.12)
        # bloco (comprimento no Y local), cabeçote, tampa de válvulas
        p.caixa("fundido", Mm, 0.26, 0.42, 0.26, 0.015)
        p.caixa("fundido", Mm @ T(0, 0, 0.16), 0.22, 0.40, 0.08, 0.012)
        tampa = "metal_preto" if self.cfg["epoca"] in ("90", "2000") else "motor_pintado"
        p.almofada(tampa, Mm @ T(0, 0, 0.215), 0.18, 0.40, 0.06, 0.18, 0.18)
        for k in range(5):
            p.caixa(tampa, Mm @ T(0, -0.16 + k * 0.08, 0.24), 0.16, 0.012, 0.012, 0.004)
        p.cilindro("amarelo" if self.cfg["epoca"] != "70" else "metal_preto", Mm @ T(0.03, 0.10, 0.25), 0.022, 0.02, 20, 0.004)
        # cárter
        p.caixa("metal_preto", Mm @ T(0.0, 0, -0.17), 0.24, 0.40, 0.09, 0.012)
        # coletor de admissão (para trás) e de escape (para a frente)
        for k in range(4):
            yk = -0.15 + k * 0.10
            p.tubo("aluminio", [Mm @ V(-0.11, yk, 0.15), Mm @ V(-0.18, yk, 0.17), Mm @ V(-0.21, yk * 0.4, 0.22)], 0.018, seg=10)
            p.tubo("ferro", [Mm @ V(0.11, yk, 0.13), Mm @ V(0.16, yk, 0.10), Mm @ V(0.19, yk * 0.3, 0.0)], 0.017, seg=10)
        p.almofada("aluminio", Mm @ T(-0.23, 0, 0.23), 0.08, 0.26, 0.08, 0.3, 0.3)
        p.cilindro("aluminio", Mm @ T(-0.23, 0.17, 0.23) @ Rx(math.pi / 2), 0.035, 0.07, 24, 0.004)
        # alternador, polias e correia (lado da distribuição, -Y local)
        p.cilindro("aluminio", Mm @ T(0.10, -0.24, 0.06) @ Rx(math.pi / 2), 0.055, 0.09, 24, 0.008)
        p.cilindro("metal_preto", Mm @ T(0.0, -0.23, -0.08) @ Rx(math.pi / 2), 0.07, 0.025, 28, 0.004)
        p.cilindro("metal_preto", Mm @ T(0.10, -0.29, 0.06) @ Rx(math.pi / 2), 0.03, 0.022, 20, 0.004)
        p.fita("borracha", [Mm @ V(-0.0, -0.245, -0.15), Mm @ V(0.07, -0.25, -0.05), Mm @ V(0.13, -0.245, 0.09), Mm @ V(0.07, -0.245, 0.09),
                            Mm @ V(-0.07, -0.245, -0.03), Mm @ V(-0.0, -0.245, -0.15)], 0.018, 0.005, Mm.to_3x3() @ V(0, 1, 0))
        p.almofada("metal_preto", Mm @ T(0, -0.235, 0.12), 0.20, 0.05, 0.22, 0.25, 0.25)
        # vareta de óleo
        p.tubo("metal_preto", [Mm @ V(0.10, 0.05, -0.05), Mm @ V(0.14, 0.05, 0.20), Mm @ V(0.15, 0.05, 0.26)], 0.005, seg=6)
        p.toro("amarelo", Mm @ T(0.15, 0.05, 0.28) @ Rx(math.pi / 2), 0.015, 0.004, 0.004, 16, 6)
        # câmbio (do lado +Y local no transversal; atrás no longitudinal)
        if transversal:
            p.revolucao("aluminio", Mm @ T(0, 0.21, -0.03) @ Rx(-math.pi / 2), [(0.15, 0), (0.15, 0.04), (0.13, 0.12), (0.10, 0.28),
                                                                                (0.05, 0.30), (0, 0.30)], 32)
        else:
            p.revolucao("aluminio", Mm @ T(0, 0.21, -0.03) @ Rx(-math.pi / 2), [(0.16, 0), (0.15, 0.10), (0.09, 0.22), (0.075, 0.55),
                                                                                (0.04, 0.60), (0, 0.60)], 32)
        # filtro de ar
        if self.cfg["epoca"] == "70":
            Mf = Mm @ T(-0.20, 0.0, 0.33)
            p.revolucao("metal_preto", Mf, [(0, -0.04), (0.16, -0.04), (0.17, -0.02), (0.17, 0.03), (0.15, 0.045), (0, 0.045)], 40)
            p.cilindro("cromado", Mf @ T(0, 0, 0.05), 0.02, 0.012, 6, 0.002)
            saida = Mf @ V(0, 0, -0.04)
            adm = Mf @ V(0, 0, -0.06)
        else:
            Mf = T(xr - 0.22, -(yb - 0.20), zf + 0.38)
            p.caixa("plastico", Mf, 0.22, 0.28, 0.13, 0.02)
            for k in range(4):
                p.caixa("metal_preto", Mf @ T(0.115, -0.1 + k * 0.066, 0.0), 0.01, 0.015, 0.05, 0.003)
            saida = Mf @ V(-0.12, 0.05, 0.0)
            adm = Mm @ V(-0.23, 0.20, 0.23)
        # coxins
        for dy in (-0.18, 0.18):
            p.cilindro("borracha", Mm @ T(0.0, dy, -0.05) @ Ry(math.pi / 2), 0.035, 0.04, 16, 0.006)
        return {"termostato": Mm @ V(0.05, -0.20, 0.17), "bomba": Mm @ V(0.06, -0.21, -0.02), "aquecedor": Mm @ V(-0.12, 0.18, 0.05),
                "filtro_saida": saida, "admissao": adm, "escape": Mm @ V(0.19, 0, -0.04), "cambio": Mm @ V(0, 0.4, -0.05)}

    def motor_v8(self, xf, xr, zf, zcap, yb):
        p = self.nova("engine_motor", "motor", nota="V8 longitudinal: bloco, bancadas, coletor, carburador e filtro redondo, distribuidor")
        xc = (xf + xr) / 2 - 0.05
        Mm = T(xc, 0, zf + 0.20)
        p.caixa("motor_pintado", Mm, 0.55, 0.30, 0.28, 0.02)
        p.caixa("metal_preto", Mm @ T(0, 0, -0.18), 0.52, 0.28, 0.10, 0.015)
        for s in (1, -1):
            Mb = Mm @ T(0, s * 0.13, 0.14) @ Rx(-s * math.radians(45))
            p.caixa("motor_pintado", Mb, 0.52, 0.16, 0.14, 0.015)
            p.almofada("cromado" if self.cfg["epoca"] == "70" else "motor_pintado", Mb @ T(0, 0, 0.10), 0.50, 0.14, 0.06, 0.18, 0.2)
            p.cilindro("metal_preto", Mb @ T(0.17, 0, 0.14), 0.018, 0.02, 16, 0.004)
            for k in range(4):
                xk = -0.18 + k * 0.12
                p.tubo("ferro", [Mm @ V(xk, s * 0.24, 0.08), Mm @ V(xk, s * 0.30, 0.02), Mm @ V(xk * 0.5 - 0.1, s * 0.32, -0.10)], 0.018, seg=10)
                p.tubo("borracha", [Mb @ V(xk, s * 0.07, 0.04), Mb @ V(xk, s * 0.10, 0.08), Mm @ V(-0.30, s * 0.05, 0.42)], 0.0045, seg=6)
        p.caixa("aluminio", Mm @ T(0, 0, 0.27), 0.40, 0.18, 0.10, 0.02)
        p.caixa("aluminio", Mm @ T(0, 0, 0.34), 0.10, 0.10, 0.06, 0.01)
        Mf = Mm @ T(0, 0, 0.40)
        p.revolucao("metal_preto" if self.cfg["epoca"] != "70" else "cromado", Mf,
                    [(0, -0.03), (0.19, -0.03), (0.20, -0.01), (0.20, 0.04), (0.18, 0.06), (0, 0.06)], 48)
        p.cilindro("cromado", Mf @ T(0, 0, 0.07), 0.025, 0.012, 6, 0.002)
        # distribuidor atrás
        p.cilindro("metal_preto", Mm @ T(-0.30, 0, 0.36), 0.04, 0.08, 20, 0.006)
        # alternador, polias, ventoinha mecânica não (há a elétrica do radiador)
        p.cilindro("aluminio", Mm @ T(0.30, 0.17, 0.12) @ Rx(math.pi / 2), 0.06, 0.09, 24, 0.008)
        p.cilindro("metal_preto", Mm @ T(0.30, 0, -0.08) @ Ry(math.pi / 2), 0.08, 0.03, 28, 0.004)
        p.cilindro("metal_preto", Mm @ T(0.32, 0, 0.10) @ Ry(math.pi / 2), 0.06, 0.03, 28, 0.004)
        p.fita("borracha", [Mm @ V(0.31, 0, -0.16), Mm @ V(0.31, 0.12, 0.05), Mm @ V(0.31, 0.17, 0.18), Mm @ V(0.31, 0.06, 0.16),
                            Mm @ V(0.31, -0.06, 0.04), Mm @ V(0.31, 0, -0.16)], 0.02, 0.005, (1, 0, 0))
        # câmbio para trás (no túnel)
        p.revolucao("aluminio", Mm @ T(-0.27, 0, -0.04) @ Ry(-math.pi / 2), [(0.17, 0), (0.15, 0.12), (0.09, 0.24), (0.08, 0.60),
                                                                              (0.04, 0.64), (0, 0.64)], 32)
        for dy in (-0.16, 0.16):
            p.cilindro("borracha", Mm @ T(0.05, dy, -0.08) @ Rx(math.pi / 2), 0.035, 0.04, 16, 0.006)
        p.tubo("metal_preto", [Mm @ V(0.15, 0.10, -0.05), Mm @ V(0.20, 0.10, 0.30), Mm @ V(0.22, 0.10, 0.36)], 0.005, seg=6)
        p.toro("amarelo", Mm @ T(0.22, 0.10, 0.38) @ Rx(math.pi / 2), 0.015, 0.004, 0.004, 16, 6)
        return {"termostato": Mm @ V(0.25, 0, 0.20), "bomba": Mm @ V(0.30, 0.05, -0.02), "aquecedor": Mm @ V(-0.15, 0.20, 0.15),
                "filtro_saida": Mf @ V(0.19, 0.0, 0.0), "admissao": Mf @ V(0.19, 0.0, 0.0), "escape": Mm @ V(-0.1, 0, -0.15),
                "cambio": Mm @ V(-0.9, 0, -0.05)}

    def motor_boxer(self):
        """Motor traseiro arrefecido a ar (4 cilindros opostos), sob a tampa de trás; a ventoinha fica na carcaça de cima."""
        M = self.M
        xa = M["x_encosto_t"] - 0.12
        xb = M["x_tras"] + 0.15
        yb = M["y_caixa_t"]
        zf = max(0.18, M["R"] * 0.70)
        p = self.nova("engine_motor", "motor", nota="4 cilindros opostos arrefecidos a ar, carcaça da ventoinha, carburador")
        xc = (xa + xb) / 2 - 0.02
        Mm = T(xc, 0, zf + 0.13)
        # cárter (bloco central) e cilindros com aletas
        p.caixa("aluminio", Mm, 0.34, 0.24, 0.26, 0.03)
        for s in (1, -1):
            for dx in (-0.08, 0.08):
                Mc = Mm @ T(dx, s * 0.12, 0.0) @ Rx(-s * math.pi / 2)
                perf = []
                for k in range(10):
                    perf += [(0.052, 0.012 * k), (0.068, 0.012 * k + 0.003), (0.068, 0.012 * k + 0.008), (0.052, 0.012 * k + 0.011)]
                perf = [(0, 0)] + perf + [(0, 0.12)]
                p.revolucao("fundido", Mc, perf, 24)
            p.caixa("fundido", Mm @ T(0, s * 0.27, 0.0), 0.30, 0.06, 0.16, 0.02)
            p.caixa("metal_preto", Mm @ T(0, s * 0.27, 0.12), 0.30, 0.10, 0.08, 0.02)
            for dx in (-0.08, 0.08):
                p.tubo("ferro", [Mm @ V(dx, s * 0.27, -0.09), Mm @ V(dx * 0.8, s * 0.24, -0.16), Mm @ V(-0.18, s * 0.18, -0.20)],
                       0.018, seg=10)
        # carcaça da ventoinha (em cima), dínamo e polia
        Mv = Mm @ T(0.02, 0, 0.20)
        p.almofada("metal_preto", Mv, 0.24, 0.62, 0.18, 0.2, 0.25)
        p.cilindro("metal_preto", Mv @ T(-0.06, 0, 0.12) @ Ry(math.pi / 2), 0.13, 0.12, 36, 0.01)
        p.cilindro("aluminio", Mv @ T(-0.09, 0, 0.15) @ Ry(math.pi / 2), 0.055, 0.17, 24, 0.008)
        p.cilindro("metal_preto", Mv @ T(-0.19, 0, 0.15) @ Ry(math.pi / 2), 0.05, 0.02, 24, 0.004)
        p.cilindro("metal_preto", Mm @ T(-0.20, 0, -0.06) @ Ry(math.pi / 2), 0.075, 0.025, 28, 0.004)
        p.fita("borracha", [Mm @ V(-0.205, 0, -0.14), Mm @ V(-0.205, 0.05, 0.10), Mm @ V(-0.205, 0, 0.40), Mm @ V(-0.205, -0.05, 0.10),
                            Mm @ V(-0.205, 0, -0.14)], 0.015, 0.005, (1, 0, 0))
        # carburador e filtro de ar em banho de óleo
        p.cilindro("aluminio", Mm @ T(0.10, 0.0, 0.36), 0.035, 0.08, 20, 0.006)
        Mf = Mm @ T(0.10, 0.20, 0.36) @ Rx(math.pi / 2)
        p.revolucao("metal_preto", Mf, [(0, -0.07), (0.10, -0.07), (0.11, -0.05), (0.11, 0.05), (0.10, 0.07), (0, 0.07)], 36)
        p.tubo("aluminio", [Mm @ V(0.06, 0, 0.36), Mm @ V(0.06, 0.12, 0.30), Mm @ V(0.06, 0.20, 0.10)], 0.016, seg=10)
        # câmbio (na frente do motor, entre as rodas de trás)
        p.revolucao("aluminio", Mm @ T(0.20, 0, -0.02) @ Ry(math.pi / 2), [(0.15, 0), (0.15, 0.06), (0.12, 0.20), (0.07, 0.30),
                                                                            (0, 0.32)], 32)
        # vareta
        p.tubo("metal_preto", [Mm @ V(-0.12, -0.05, -0.08), Mm @ V(-0.14, -0.05, 0.25)], 0.005, seg=6, sub=1)
        p.toro("amarelo", Mm @ T(-0.14, -0.05, 0.27) @ Rx(math.pi / 2), 0.015, 0.004, 0.004, 16, 6)
        # chapas laterais do vão e a parede do banco
        c = self.nova("engine_vao_traseiro", "motor")
        c.caixa("pintura_interna", T(xa, 0, (zf + M["z_cintura"]) / 2), 0.015, 2 * yb, M["z_cintura"] - zf, 0.006)
        for s in (1, -1):
            c.caixa("pintura_interna", T((xa + xb) / 2, s * yb, zf + 0.30), xa - xb, 0.015, 0.40, 0.006)
        self.bateria(T(xa - 0.12, yb - 0.17, zf + 0.12))
        m = self.nova("engine_mangueiras", "motor", nota="cabos de vela e mangueira de combustível")
        for s in (1, -1):
            for dx in (-0.08, 0.08):
                m.tubo("borracha", [Mm @ V(dx, s * 0.30, 0.05), Mm @ V(dx, s * 0.20, 0.30), Mm @ V(0.12, 0, 0.36)], 0.0045, seg=6)
        m.tubo("borracha", [Mm @ V(0.10, 0.0, 0.42), Mm @ V(0.30, 0.15, 0.30), (xa + 0.02, 0.2, zf + 0.10)], 0.004, seg=6)
        self.motor_traseiro_escape = Mm

    # ================================================================================================================ EMBAIXO
    def embaixo(self):
        M = self.M
        p = self.nova("under_assoalho", "embaixo")
        x0 = M["x_tras"] + 0.22
        x1 = M["x_corta_fogo"] + 0.02
        ym = M["W"] - 0.12
        zb = M["z_piso"] - 0.035
        tun_h = 0.13 if self.cfg["tracao"] == "dianteira" else 0.17

        def ponto(u, v):
            x = x0 + (x1 - x0) * u
            y = -ym + 2 * ym * v
            z = zb
            ay = abs(y)
            if ay < 0.19:
                z += tun_h * math.cos(ay / 0.19 * math.pi / 2) ** 1.5
            # nervuras
            if 0.25 < ay < ym - 0.1:
                z += 0.006 * max(0.0, math.sin(x * 2 * math.pi / 0.18)) ** 2
            # sobe sobre o eixo de trás e no porta-malas
            if x < M["x_encosto_t"] + 0.5:
                z += (M["z_mala"] - M["z_piso"] + 0.02) * _limitar((M["x_encosto_t"] + 0.5 - x) / 0.25, 0, 1)
            if ay > ym - 0.05:
                z -= 0.03 * (ay - (ym - 0.05)) / 0.05
            return V(x, y, z)
        p.grade("chassi", 60, 30, ponto, 0.01, normal_fn=lambda u, v: (0, 0, 1))
        # escapamento
        self.escapamento()
        self.tanque()
        self.suspensao()

    def escapamento(self):
        M = self.M
        p = self.nova("under_escapamento", "embaixo")
        zb = M["z_piso"] - 0.10
        if M["motor_traseiro"]:
            Mm = self.motor_traseiro_escape
            xq = M["x_tras"] + 0.22
            Ms = T(xq, 0, zb + 0.18) @ Rx(math.pi / 2)
            p.revolucao("ferro", Ms, [(0, -0.40), (0.085, -0.40), (0.10, -0.37), (0.10, 0.37), (0.085, 0.40), (0, 0.40)], 28)
            for s in (1, -1):
                p.tubo("ferro", [Mm @ V(-0.18, s * 0.18, -0.20), (xq + 0.08, s * 0.25, zb + 0.15), (xq, s * 0.30, zb + 0.18)], 0.02, seg=10)
                p.tubo("cromado", [(xq - 0.02, s * 0.12, zb + 0.12), (xq - 0.18, s * 0.12, zb + 0.10)], 0.019, seg=12, sub=1)
            return
        n = 2 if self.cfg["motor"] == "v8_longitudinal" else 1
        for k in range(n):
            y = 0.0 if n == 1 else (0.13 if k == 0 else -0.13)
            xm = (M["xd"] + M["x_corta_fogo"]) / 2 + 0.15
            x_muf = M["xt"] - 0.40 if self.cfg["tracao"] == "dianteira" else M["xt"] - 0.55
            x_ponta = M["x_tras"] + 0.08
            ys = -0.45 if n == 1 else (0.45 if k == 0 else -0.45)
            pts = [(xm + 0.15, y, M["z_piso"] + 0.05), (xm, y, zb + 0.04), (M["x_corta_fogo"] - 0.30, y, zb), (M["x_encosto_t"] + 0.45, y, zb),
                   (M["xt"] + 0.15, y * 1.6 - 0.06, zb + 0.04), (x_muf + 0.25, ys * 0.6, zb + 0.07)]
            p.tubo("ferro", pts, 0.022, seg=12)
            # catalisador (90/2000) e abafador do meio
            if self.cfg["epoca"] in ("90", "2000"):
                Mc = T(M["x_corta_fogo"] - 0.15, y, zb + 0.005) @ Ry(math.pi / 2)
                p.revolucao("ferro", Mc @ S(1, 0.7, 1), [(0, -0.16), (0.04, -0.16), (0.075, -0.10), (0.075, 0.10), (0.04, 0.16), (0, 0.16)], 24)
            Mr = T((M["x_corta_fogo"] - 0.3 + M["x_encosto_t"] + 0.45) / 2 - 0.1, y, zb) @ Ry(math.pi / 2)
            p.revolucao("ferro", Mr, [(0, -0.15), (0.045, -0.15), (0.06, -0.12), (0.06, 0.12), (0.045, 0.15), (0, 0.15)], 24)
            # silencioso traseiro (transversal) e ponteira
            Ms = T(x_muf, ys * 0.55, zb + 0.08) @ Rx(math.pi / 2) @ S(1.35, 1, 1)
            p.revolucao("ferro", Ms, [(0, -0.22), (0.075, -0.22), (0.09, -0.20), (0.09, 0.20), (0.075, 0.22), (0, 0.22)], 28)
            p.tubo("cromado" if self.cfg["epoca"] == "70" else "ferro", [(x_muf - 0.05, ys * 0.85, zb + 0.08), (x_ponta + 0.06, ys * 0.85, zb + 0.10),
                                                                       (x_ponta - 0.03, ys * 0.85, zb + 0.10)], 0.024, seg=12, sub=2)
            # suportes de borracha
            for xx in (M["x_encosto_t"] + 0.4, x_muf + 0.1):
                p.cilindro("borracha", T(xx, y if xx > M["xt"] else ys * 0.55, zb + 0.06), 0.012, 0.05, 10, 0.003)

    def tanque(self):
        M = self.M
        onde = self.cfg["tanque"]
        if onde == "frente":
            return
        p = self.nova("under_tanque", "embaixo")
        zb = M["z_piso"] - 0.05
        if onde == "sob_banco_traseiro":
            xc = M["xt"] + 0.42
            Mt = T(xc, 0.12, zb - 0.09)
            p.almofada("metal_preto", Mt, 0.42, 0.70, 0.17, 0.12, 0.15)
            for dx in (-0.12, 0.12):
                p.fita("metal_preto", [Mt @ V(dx, -0.36, 0.09), Mt @ V(dx, -0.36, -0.09), Mt @ V(dx, 0.36, -0.09), Mt @ V(dx, 0.36, 0.09)],
                       0.03, 0.003, (1, 0, 0))
            bocal = [Mt @ V(-0.1, 0.30, 0.05), V(M["xt"] - 0.05, M["W"] - 0.18, M["z_piso"] + 0.12), V(M["xt"] - 0.25, M["W"] - 0.06, M["z_cintura"] - 0.20)]
        else:
            xc = M["xt"] - 0.48
            Mt = T(xc, 0, M["z_mala"] - 0.14)
            p.almofada("metal_preto", Mt, 0.38, 0.85, 0.20, 0.12, 0.15)
            bocal = [Mt @ V(0.0, 0.38, 0.08), V(xc - 0.05, M["W"] - 0.10, M["z_mala"] + 0.10)]
        p.tubo("borracha", bocal, 0.022, seg=12)

    def suspensao(self):
        M = self.M
        tr = self.cfg["tracao"]
        motor = self.cfg["motor"]
        # dianteira: McPherson (bandeja, manga, amortecedor com mola, barra de direção) por lado + berço e caixa de direção
        b = self.nova("under_berco", "embaixo")
        xd = M["xd"]
        zr = M["R"]
        yi = M["y_pneu_dentro_d"]
        b.caixa("metal_preto", T(xd - 0.05, 0, zr - 0.13), 0.12, 2 * (yi - 0.14), 0.07, 0.015)
        b.cilindro("metal_preto", T(xd - 0.13, 0, zr - 0.02) @ Rx(math.pi / 2), 0.028, 2 * (yi - 0.20), 20, 0.004)
        for s in (1, -1):
            b.revolucao("borracha", T(xd - 0.13, s * (yi - 0.23), zr - 0.02) @ Rx(-s * math.pi / 2),
                        [(0.03, 0)] + [(0.032 + 0.008 * (k % 2), 0.008 * k) for k in range(1, 9)] + [(0.015, 0.075), (0, 0.075)], 20)
        for s in (1, -1):
            lado = "esq" if s > 0 else "dir"
            q = self.nova(f"under_suspensao_dianteira_{lado}", "embaixo")
            yw = s * (yi - 0.05)
            # manga (gira com a direção, não com a roda)
            q.almofada("fundido", T(xd, yw - s * 0.01, zr), 0.08, 0.06, 0.24, 0.3, 0.3)
            # bandeja em A
            pj = V(xd + 0.0, yw - s * 0.02, zr - 0.13)
            for dx in (0.17, -0.12):
                q.tubo("metal_preto", [pj, V(xd + dx, s * (yi - 0.30), zr - 0.12)], 0.016, seg=10, sub=1)
            q.revolucao("borracha", T(*pj), [(0, -0.02), (0.025, -0.02), (0.025, 0.02), (0, 0.02)], 16)
            # amortecedor com mola até a torre
            base = V(xd - 0.02, yw - s * 0.06, zr + 0.06)
            topo = V(xd, s * (M["y_caixa_d"] + 0.02), getattr(self, "topo_torre", zr + 0.50) - 0.06 if not M["motor_traseiro"] else zr + 0.45)
            dirm = (topo - base)
            q.tubo("metal_preto", [base, base + dirm * 0.55], 0.028, seg=14, sub=1)
            q.tubo("cromado", [base + dirm * 0.5, topo], 0.012, seg=10, sub=1)
            Mmola = T(*(base + dirm * 0.30)) @ alinhar_z(dirm)
            q.helice("vermelho" if self.cfg["epoca"] in ("90", "2000") else "metal_preto", Mmola, 0.065, 0.0085, dirm.length * 0.40, 5)
            # barra de direção
            q.tubo("aluminio", [V(xd - 0.13, s * (yi - 0.26), zr - 0.02), V(xd - 0.11, yw - s * 0.03, zr - 0.02)], 0.011, seg=10, sub=1)
            # semieixo (tração dianteira) com coifas
            if tr == "dianteira":
                a = V(xd + 0.0, s * 0.14, zr - 0.02)
                c = V(xd, yw - s * 0.04, zr)
                q.tubo("aluminio", [a, c], 0.016, seg=12, sub=1)
                for (pt, dirv) in ((a, c - a), (c, a - c)):
                    Mcf = T(*pt) @ alinhar_z(dirv)
                    q.revolucao("borracha", Mcf, [(0.045, 0.0)] + [(0.03 + 0.012 * (k % 2) - 0.0015 * k, 0.012 * k) for k in range(1, 8)] +
                                [(0.018, 0.095), (0, 0.095)], 20)
            # caixa de roda interna
            self.caixa_roda("f" + ("l" if s > 0 else "r"))
        # traseira
        xt = M["xt"]
        yi_t = M["y_pneu_dentro_t"]
        q = self.nova("under_eixo_traseiro", "embaixo")
        if tr == "dianteira":
            # eixo de torção: travessa em U, braços arrastados, molas e amortecedores
            xb = xt + 0.22
            q.caixa("metal_preto", T(xb, 0, zr - 0.04), 0.09, 2 * (yi_t - 0.10), 0.07, 0.02)
            for s in (1, -1):
                y = s * (yi_t - 0.08)
                q.tubo("metal_preto", [(xt + 0.48, y * 0.92, zr + 0.03), (xb, y, zr - 0.01), (xt, y, zr)], 0.03, seg=12)
                q.revolucao("borracha", T(xt + 0.48, y * 0.92, zr + 0.03) @ Rx(math.pi / 2), [(0, -0.03), (0.04, -0.03), (0.04, 0.03), (0, 0.03)], 16)
                q.helice("metal_preto", T(xt + 0.10, y - s * 0.02, zr + 0.02), 0.06, 0.009, 0.24, 5)
                q.tubo("metal_preto", [(xt - 0.08, y, zr - 0.02), (xt - 0.10, y * 0.97, zr + 0.36)], 0.022, seg=12, sub=1)
        elif motor == "boxer_traseiro":
            # semieixos oscilantes com braços arrastados
            for s in (1, -1):
                y = s * (yi_t - 0.05)
                q.tubo("metal_preto", [(xt + 0.12, s * 0.20, zr + 0.02), (xt, y, zr)], 0.04, seg=14, sub=1)
                q.fita("metal_preto", [(xt + 0.55, s * (yi_t - 0.12), zr + 0.04), (xt + 0.05, y, zr)], 0.08, 0.008, (0, 1, 0))
                q.tubo("metal_preto", [(xt - 0.07, y, zr - 0.02), (xt - 0.09, y * 0.95, zr + 0.34)], 0.022, seg=12, sub=1)
            q.tubo("metal_preto", [(xt + 0.55, -(yi_t - 0.06), zr + 0.04), (xt + 0.55, yi_t - 0.06, zr + 0.04)], 0.035, seg=14, sub=1)
        else:
            # eixo rígido com diferencial, braços, molas e cardã
            q.tubo("metal_preto", [(xt, -(yi_t - 0.04), zr), (xt, yi_t - 0.04, zr)], 0.04, seg=16, sub=1)
            Md = T(xt + 0.02, 0, zr) @ Ry(math.pi / 2)
            q.revolucao("ferro", Md, [(0, -0.12), (0.08, -0.12), (0.14, -0.04), (0.14, 0.05), (0.10, 0.10), (0.05, 0.16), (0, 0.16)], 32)
            q.revolucao("metal_preto", Md @ T(0, 0, -0.14), [(0, 0), (0.13, 0), (0.12, 0.02), (0, 0.02)], 32)
            for s in (1, -1):
                y = s * (yi_t - 0.14)
                q.tubo("metal_preto", [(xt + 0.55, y * 0.9, zr - 0.05), (xt, y, zr - 0.06)], 0.022, seg=10, sub=1)
                q.helice("metal_preto", T(xt + 0.06, y, zr + 0.04), 0.065, 0.01, 0.24, 5)
                q.tubo("metal_preto", [(xt - 0.10, y, zr - 0.02), (xt - 0.13, y * 0.97, zr + 0.34)], 0.022, seg=12, sub=1)
            xcam = M["x_encosto_d"] + 0.2
            q.tubo("metal_preto", [(xcam, 0, M["z_piso"] - 0.02), (xt + 0.17, 0, zr)], 0.035, seg=16, sub=1)
            for xx in (xcam, xt + 0.17):
                q.cilindro("fundido", T(xx, 0, M["z_piso"] - 0.02 if xx == xcam else zr) @ Ry(math.pi / 2), 0.045, 0.05, 20, 0.006)
        for pos in ("rl", "rr"):
            self.caixa_roda(pos)

    def caixa_roda(self, pos):
        M = self.M
        r = M["rodas"].get(pos)
        if not r:
            return
        s = r["lado"]
        p = self.nova(f"under_caixa_roda_{pos}", "embaixo", nota="para-lama interno (dentro da caixa de roda escura do corte)")
        R = M["R"] + 0.035
        y0, y1 = r["y_dentro"] - 0.025, r["y_fora"] - 0.01
        cx, cz = r["x"], r["z"]

        def ponto(u, v):
            a = math.radians(-20 + 220 * u)
            y = y0 + (y1 - y0) * v
            return V(cx + R * math.cos(a), s * y, cz + R * math.sin(a))
        p.grade("plastico", 32, 4, ponto, 0.006, normal_fn=lambda u, v: (-math.cos(math.radians(-20 + 220 * u)), 0,
                                                                         -math.sin(math.radians(-20 + 220 * u))))

    # ================================================================================================================ FREIOS
    def freios(self):
        M = self.M
        for pos, r in M["rodas"].items():
            s = r["lado"]
            frente = pos[0] == "f"
            tambor = (not frente) and self.e.get("freio_traseiro") == "tambor"
            R = M["R"]
            rd = 0.41 * R
            yin = r["y_dentro"]
            C = V(r["x"], 0, r["z"])
            # Z local = para fora do carro
            Mr = T(C.x, s * (yin + 0.035), C.z) @ Rx(-s * math.pi / 2)
            gira = f"wheel_{pos} (gira com a roda)"
            fixa = f"wheel_{pos} (manga: não gira)"
            cubo = self.nova(f"brake_{pos}_cubo", "freios", gira)
            cubo.revolucao("aluminio", Mr @ T(0, 0, 0.035), [(0, 0.0), (0.05, 0.0), (0.075, 0.004), (0.075, 0.012), (0.045, 0.016),
                                                            (0.03, 0.045), (0, 0.045)], 32)
            for k in range(4):
                a = 2 * math.pi * k / 4 + math.pi / 4
                cubo.cilindro("cromado", Mr @ T(0.05 * math.cos(a), 0.05 * math.sin(a), 0.05), 0.0055, 0.04, 8, 0.0015)
            if tambor:
                d = self.nova(f"brake_{pos}_tambor", "freios", gira)
                rt = 0.36 * R
                perf = [(0, 0.035), (rt - 0.01, 0.035), (rt, 0.03)]
                for k in range(5):
                    perf += [(rt + 0.008, 0.024 - k * 0.012), (rt, 0.018 - k * 0.012)]
                perf += [(rt + 0.004, -0.04), (rt - 0.01, -0.045), (rt - 0.012, -0.03), (0.04, 0.025), (0, 0.025)]
                d.revolucao("ferro", Mr, perf, 40)
                pl = self.nova(f"brake_{pos}_espelho", "freios", fixa, "espelho do tambor")
                pl.revolucao("metal_preto", Mr @ T(0, 0, -0.05), [(0, 0), (rt + 0.01, 0.0), (rt + 0.012, 0.012), (0.04, 0.01), (0, 0.01)], 32)
                pl.cilindro("metal_preto", Mr @ T(0.0, rt * 0.6, -0.06), 0.012, 0.03, 12, 0.003)
                continue
            d = self.nova(f"brake_{pos}_disco", "freios", gira)
            ventilado = self.cfg["epoca"] in ("90", "2000") and frente
            e = 0.022 if ventilado else 0.012
            d.revolucao("disco", Mr, [(rd * 0.55, -e / 2), (rd, -e / 2), (rd + 0.002, -e / 2 + 0.002), (rd + 0.002, e / 2 - 0.002), (rd, e / 2),
                                      (rd * 0.55, e / 2), (rd * 0.55, -e / 2)], 56)
            d.revolucao("ferro", Mr, [(rd * 0.56, e / 2), (rd * 0.50, e / 2 + 0.002), (rd * 0.46, 0.035), (0.03, 0.035), (0.03, 0.03),
                                      (rd * 0.44, 0.03), (rd * 0.50, e / 2), (rd * 0.56, e / 2)], 40)
            if ventilado:
                d.revolucao("ferro", Mr, [(rd * 0.56, -e / 2 + 0.006), (rd - 0.003, -e / 2 + 0.006), (rd - 0.003, e / 2 - 0.006),
                                          (rd * 0.56, e / 2 - 0.006), (rd * 0.56, -e / 2 + 0.006)], 40)
            # pinça (atrás e acima do cubo) com o suporte e a mangueira
            pc = self.nova(f"brake_{pos}_pinca", "freios", fixa)
            ang = math.radians(150 if frente else 120)
            Mp = Mr @ Rz(ang) @ T(rd - 0.025, 0, 0)
            pc.almofada("pinca", Mp @ T(0.0, 0, -e / 2 - 0.022), 0.06, 0.11, 0.035, 0.3, 0.3)
            pc.almofada("pinca", Mp @ T(0.0, 0, e / 2 + 0.014), 0.05, 0.09, 0.022, 0.3, 0.3)
            pc.caixa("pinca", Mp @ T(0.035, 0, 0), 0.02, 0.09, e + 0.07, 0.006)
            pc.cilindro("aluminio", Mp @ T(-0.01, 0.04, -e / 2 - 0.045), 0.006, 0.02, 8, 0.002)
            pc.tubo("borracha", [Mp @ V(0.02, 0.05, -e / 2 - 0.04), Mp @ V(0.08, 0.10, -e / 2 - 0.10), Mr @ V(0.10, 0.18, -0.16)], 0.005, seg=8)
            sh = self.nova(f"brake_{pos}_protecao", "freios", fixa, "chapa de proteção do disco")
            sh.revolucao("metal_preto", Mr @ T(0, 0, -e / 2 - 0.012), [(0.04, 0), (rd + 0.005, 0), (rd + 0.01, 0.01), (rd + 0.008, 0.012),
                                                                    (rd + 0.002, 0.003), (0.04, 0.003)], 40, a0=math.radians(-60),
                         a1=math.radians(220))


# ================================================================================================================================
# Blender: finalizar, LOD, exportar, prévias
# ================================================================================================================================

def finalizar(peca, mats):
    import bmesh
    import bpy
    bm = peca.bm
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    uv = peca.uv
    for f in bm.faces:
        if f[peca.fix]:
            continue
        lad = mats.get(peca.mats[f.material_index])["ladrilho_m"]
        n = f.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        for lp in f.loops:
            c = lp.vert.co
            if ax == 0:
                u, v = c.y * math.copysign(1, n.x), c.z
            elif ax == 1:
                u, v = -c.x * math.copysign(1, n.y), c.z
            else:
                u, v = c.x, c.y * math.copysign(1, n.z)
            lp[uv].uv = (u / lad, v / lad)
    me = bpy.data.meshes.new(peca.nome)
    bm.to_mesh(me)
    bm.free()
    for nm in peca.mats:
        me.materials.append(mats.get(nm))
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    try:
        me.set_sharp_from_angle(angle=math.radians(38))
    except Exception:
        pass
    me.validate()
    ob = bpy.data.objects.new(peca.nome, me)
    ob["grupo"] = peca.grupo
    if peca.segue:
        ob["segue"] = peca.segue
    return ob


def triangulos(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def fazer_lod1(ob, razao=LOD1_RAZAO):
    import bpy
    mod = ob.modifiers.new("lod1", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = razao
    mod.use_collapse_triangulate = True
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev)
    ob.modifiers.remove(mod)
    me.name = ob.name + "_LOD1"
    lod = bpy.data.objects.new(ob.name + "_LOD1", me)
    for k in ("grupo", "segue"):
        if k in ob.keys():
            lod[k] = ob[k]
    return lod


def exportar(objs, caminho):
    import bpy
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=caminho, export_format="GLB", use_selection=True, export_apply=True,
                              export_image_format="AUTO", export_extras=True, export_yup=True)


def importar_corte(glb, M):
    """Importa o carro do corte; tira a casca escura (MI_DNVao) dentro dos vãos do kit. Devolve {nome: objeto}."""
    import bmesh
    import bpy
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    objs = {o.name: o for o in bpy.data.objects if o not in antes and o.type == "MESH"}
    for o in objs.values():
        vi = [i for i, m in enumerate(o.data.materials) if m and m.name == "MI_DNVao"]
        if not vi and o.name not in M["fundo"]["pecas"]:
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        mw = o.matrix_world
        tira = [f for f in bm.faces if f.material_index in vi and _dentro_vaos(mw @ f.calc_center_median(), M["vaos"])]
        if o.name in M["fundo"]["pecas"]:
            fz = M["fundo"]
            tira += [f for f in bm.faces if f.normal.z < fz["normal_z_max"] and _dentro(mw @ f.calc_center_median(), fz["caixa"])
                     and f.material_index not in vi]
        bmesh.ops.delete(bm, geom=tira, context="FACES")
        bm.to_mesh(o.data)
        bm.free()
    return objs


def preparar_cena(amostras):
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
    cena.cycles.max_bounces = 6
    cena.view_settings.view_transform = "AgX" if "AgX" in [i.identifier for i in
                                                            cena.view_settings.bl_rna.properties["view_transform"].enum_items] else "Standard"
    cena.render.resolution_x, cena.render.resolution_y = 1280, 800
    cena.render.image_settings.file_format = "JPEG"
    cena.render.image_settings.quality = 88
    mundo = bpy.data.worlds.new("previa")
    mundo.use_nodes = True
    bg = mundo.node_tree.nodes["Background"]
    sky = mundo.node_tree.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "HOSEK_WILKIE"
    except Exception:
        pass
    mundo.node_tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.6
    cena.world = mundo
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 3.5
    sol.data.angle = math.radians(8)
    sol.rotation_euler = (math.radians(50), math.radians(-10), math.radians(-35))
    cena.collection.objects.link(sol)
    chao = bpy.data.meshes.new("chao")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=30)
    bm.to_mesh(chao)
    ob = bpy.data.objects.new("chao", chao)
    m = bpy.data.materials.new("chao")
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.18, 0.18, 0.18, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.85
    chao.materials.append(m)
    cena.collection.objects.link(ob)
    return cena, ob, sol


def camera(cena, loc, alvo, lente=28):
    import bpy
    from mathutils import Vector
    cam = cena.camera
    if cam is None:
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        cena.collection.objects.link(cam)
        cena.camera = cam
    cam.location = loc
    cam.data.lens = lente
    cam.data.clip_start = 0.02
    d = Vector(alvo) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return cam


def luz_area(cena, nome, loc, alvo, energia, tam=1.0):
    import bpy
    from mathutils import Vector
    lz = bpy.data.objects.new(nome, bpy.data.lights.new(nome, "AREA"))
    lz.data.energy = energia
    lz.data.size = tam
    lz.location = loc
    lz.rotation_euler = (Vector(alvo) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    cena.collection.objects.link(lz)
    return lz


def previas(M, cfg, corte, kit_objs, out, cid, amostras):
    """As prévias pedidas: porta dianteira esquerda arrancada (lado, 1,5 m), cabine pelo para-brisa, capô aberto, por baixo."""
    import bpy
    from mathutils import Matrix
    cena, chao, sol = preparar_cena(amostras)
    for o in kit_objs:
        cena.collection.objects.link(o) if o.name not in cena.collection.objects else None
    # vidros do corte: transparentes (como vidro de verdade)
    for o in corte.values():
        for i, m in enumerate(o.data.materials):
            if m and m.name.startswith("vidro"):
                nt = m.node_tree
                b = nt.nodes.get("Principled BSDF")
                if b:
                    for l in list(b.inputs["Base Color"].links):
                        nt.links.remove(l)
                    b.inputs["Base Color"].default_value = (0.85, 0.9, 0.9, 1)
                    b.inputs["Transmission Weight"].default_value = 1.0
                    b.inputs["Roughness"].default_value = 0.02
                    b.inputs["Alpha"].default_value = 1.0
    for o in corte.values():
        for m in o.data.materials:
            if m and m.name in ("chassi", "MI_DNVao") and m.use_nodes:
                b = m.node_tree.nodes.get("Principled BSDF")
                if b:
                    for l in list(b.inputs["Base Color"].links):
                        m.node_tree.links.remove(l)
                    b.inputs["Base Color"].default_value = (0.025, 0.025, 0.025, 1)
                    b.inputs["Roughness"].default_value = 0.8
    saidas = []
    por_nome = dict(corte)
    por_nome.update({o.name: o for o in kit_objs})

    def esconder(nomes, h=True):
        for n in nomes:
            o = por_nome.get(n)
            if o:
                o.hide_render = h

    def render(nome):
        cena.render.filepath = os.path.join(out, f"{cid}_{nome}.jpg")
        bpy.ops.render.render(write_still=True)
        saidas.append(cena.render.filepath)

    pf = M["portas"].get("fl")
    # 1. porta dianteira esquerda arrancada, vista de lado a 1,5 m
    if pf:
        tira = ["door_fl", "glass_door_fl"] + [o.name for o in kit_objs if o.name.startswith("door_card_fl")]
        esconder(tira)
        xc = (pf["x0"] + pf["x1"]) / 2
        camera(cena, (xc - 0.05, M["W"] + 1.5, 1.05), (xc - 0.05, 0, 0.78), 22)
        lz = luz_area(cena, "luz_porta", (xc + 0.6, M["W"] + 1.2, 1.6), (xc, 0, 0.7), 120, 1.2)
        render("porta")
        esconder(tira, False)
        bpy.data.objects.remove(lz)
        # 1b. a porta arrancada no chão, por dentro
        do = [por_nome[n] for n in por_nome if n == "door_fl" or n == "glass_door_fl" or n.startswith("door_card_fl")]
        mostrar = set(do)
        ocultos = [o for o in por_nome.values() if o not in mostrar and not o.hide_render]
        for o in ocultos:
            o.hide_render = True
        piv = bpy.data.objects.new("piv_porta", None)
        cena.collection.objects.link(piv)
        piv.location = (xc, 0.0, 0.0)
        bpy.context.view_layer.update()
        for o in do:
            o.parent = piv
            o.matrix_parent_inverse = piv.matrix_world.inverted()
        piv.location = (xc, 3.2, 0.0)
        bpy.context.view_layer.update()
        alvo = (xc, 3.2 + M["W"] - 0.08, 0.70)
        camera(cena, (xc - 0.35, alvo[1] - 1.5, 1.05), alvo, 26)
        lz2 = luz_area(cena, "luz_solta", (xc + 0.5, alvo[1] - 1.3, 1.8), alvo, 120, 1.5)
        render("porta_solta")
        bpy.data.objects.remove(lz2)
        for o in do:
            o.parent = None
            o.matrix_world = Matrix.Identity(4)
        bpy.data.objects.remove(piv)
        for o in ocultos:
            o.hide_render = False
    # 2. cabine pelo para-brisa. Onde o corte deixou pedaços do para-brisa na carroceria (faces no plano do vidro, dentro da
    #    caixa dele), só nesta prévia eles saem junto com o vidro
    ws = M["ws"]
    esconder(["glass_windshield"])
    body = por_nome.get("body")
    if body:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(body.data)
        dx, dz = ws[0] - ws[1], ws[5] - ws[4]
        nrm = math.hypot(dx, dz)

        def no_vidro(c):
            if not (ws[4] + 0.02 < c.z < ws[5] - 0.02 and abs(c.y) < ws[3] - 0.07):
                return False
            return abs((c.x - ws[1]) * dz - (c.z - ws[4]) * dx) / nrm < 0.05
        tira = [f for f in bm.faces if no_vidro(f.calc_center_median())]
        bmesh.ops.delete(bm, geom=tira, context="FACES")
        bm.to_mesh(body.data)
        bm.free()
    camera(cena, (ws[1] + 0.55, -0.12, ws[5] + 0.04), (M["x_encosto_d"] + 0.15, 0.10, M["z_assento"] + 0.05), 19)
    lz = luz_area(cena, "luz_cab", (ws[1] + 0.8, 0.5, ws[5] + 0.8), (M["x_painel"], 0, M["z_painel"]), 90, 1.0)
    render("cabine")
    bpy.data.objects.remove(lz)
    # 2b. painel visto de dentro (entre os bancos da frente)
    camera(cena, (M["x_encosto_d"] - 0.05, -0.06, M["z_cintura"] + 0.24), (M["x_painel"] + 0.05, M["y_banco"] * 0.45, M["z_painel"] - 0.12), 17)
    lz = luz_area(cena, "luz_dentro", (M["x_encosto_d"] + 0.3, 0, M["z_teto_int"] - 0.08), (M["x_painel"], 0, M["z_piso"]), 25, 0.5)
    render("painel")
    bpy.data.objects.remove(lz)
    esconder(["glass_windshield"], False)
    # 3. capô aberto (tampa da frente: vão do motor ou, no motor traseiro, o porta-malas da frente)
    tampa = por_nome.get("hood")
    eixo_x = M["x_corta_fogo"] + 0.02
    ang = math.radians(55)
    vis = (M["x_frente"] + 1.25, 0.85, M["H"] + 0.75)
    alvo = ((M["x_corta_fogo"] + M["x_radiador"]) / 2, 0, M["z_saia"] + 0.15)
    piv = None
    if tampa and M["motor_traseiro"]:
        # mesma ressalva da tampa de trás: no Besouro o capô do corte é estreito e a casca segue por baixo dele
        import bmesh
        body = por_nome.get("body")
        b = M["tampa_frente"]
        if body:
            bm = bmesh.new()
            bm.from_mesh(body.data)
            caixa = [b[0] - 0.02, b[1] + 0.02, b[2] - 0.02, b[3] + 0.02, M["z_capo_frente"] - 0.10, M["H"]]
            tira = [f for f in bm.faces if _dentro(f.calc_center_median(), caixa)]
            bmesh.ops.delete(bm, geom=tira, context="FACES")
            bm.to_mesh(body.data)
            bm.free()
    if tampa:
        piv = bpy.data.objects.new("piv_tampa", None)
        cena.collection.objects.link(piv)
        piv.location = (eixo_x, 0, M["z_capo_tras"] + 0.03)
        bpy.context.view_layer.update()
        tampa.parent = piv
        tampa.matrix_parent_inverse = piv.matrix_world.inverted()
        piv.rotation_euler = (0, -ang, 0)
        bpy.context.view_layer.update()
    camera(cena, vis, alvo, 22)
    lz = luz_area(cena, "luz_motor", (vis[0], vis[1] - 0.4, vis[2] + 0.6), alvo, 150, 1.5)
    render("motor" if not M["motor_traseiro"] else "capo")
    bpy.data.objects.remove(lz)
    if tampa:
        tampa.parent = None
        tampa.matrix_world = Matrix.Identity(4)
        bpy.data.objects.remove(piv)
    # 3b. motor traseiro: tampa de trás fora. A tampa do corte não abre o vão inteiro (a casca segue por baixo dela), então
    #     só nesta prévia a casca sai na caixa da tampa (faces viradas para cima ou para trás)
    if M["motor_traseiro"]:
        import bmesh
        tr = por_nome.get("trunk")
        if tr:
            tr.hide_render = True
        b = M["tampa_tras"]
        body = por_nome.get("body")
        if body:
            bm = bmesh.new()
            bm.from_mesh(body.data)
            caixa = [b[0] - 0.05, b[1] + 0.02, b[2] - 0.02, b[3] + 0.02, M["z_tampa_tras_borda"] - 0.05, M["H"]]
            tira = [f for f in bm.faces if _dentro(f.calc_center_median(), caixa)]
            bmesh.ops.delete(bm, geom=tira, context="FACES")
            bm.to_mesh(body.data)
            bm.free()
        vis = (b[0] - 1.1, 0.75, M["H"] + 0.65)
        alvo = ((b[0] + b[1]) / 2, 0, M["z_saia"] + 0.2)
        camera(cena, vis, alvo, 22)
        lz = luz_area(cena, "luz_motor", (vis[0], vis[1] - 0.4, vis[2] + 0.6), alvo, 150, 1.5)
        render("motor")
        bpy.data.objects.remove(lz)
        if tr:
            tr.hide_render = False
    # 4. por baixo (carro tombado de lado no ar: câmera embaixo, olhando para cima)
    chao.hide_render = True
    camera(cena, (0.1, -0.75, -1.75), (0.0, 0.0, 0.25), 15)
    l1 = luz_area(cena, "luz_baixo", (0.8, -0.8, -1.8), (0, 0, 0.3), 350, 3.0)
    l2 = luz_area(cena, "luz_baixo2", (-1.6, 0.9, -1.2), (0, 0, 0.3), 180, 2.0)
    render("baixo")
    for l in (l1, l2):
        bpy.data.objects.remove(l)
    chao.hide_render = False
    return saidas


# ================================================================================================================================
# Principal
# ================================================================================================================================

def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(prog="carro_completo.py")
    p.add_argument("--corte", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--glb", default=None)
    p.add_argument("--dados", default=DADOS)
    p.add_argument("--epoca", choices=EPOCAS, default=None)
    p.add_argument("--motor", choices=MOTORES, default=None)
    p.add_argument("--amostras", type=int, default=24)
    p.add_argument("--sem-previa", action="store_true")
    p.add_argument("--so-medidas", action="store_true")
    p.add_argument("--sufixo", default="", help="sufixo nos arquivos de saída (ex.: _2000 para testar outra época)")
    return p.parse_args(argv)


def principal(argv):
    a = parse_args(argv)
    dados = ler_dados(a.dados)
    cfg, estilo, avisos = config_carro(dados, a.id, a.epoca, a.motor)
    corte = ler_corte(a.corte, a.id)
    M = medidas(corte, cfg)
    print(resumo(M))
    for av in avisos:
        print("AVISO:", av)
    if a.so_medidas:
        return 0
    if not a.out:
        print("falta --out")
        return 2
    import bpy
    os.makedirs(a.out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    glb = a.glb or os.path.join(a.corte, f"{a.id}.glb")
    corte_objs = None
    casca = None
    if os.path.isfile(glb):
        corte_objs = importar_corte(glb, M)
        casca = Casca({n: o for n, o in corte_objs.items() if not n.startswith(("wheel", "hubcap"))}, M["vaos"])
        print(f"casca: {glb} ({len(corte_objs)} peças)")
    else:
        avisos.append(f"sem o GLB do corte ({glb}): peças pelas medidas, sem assentar na casca e sem prévias")
    pint = (0.45, 0.45, 0.45)
    if corte.get("pecas") and "textura" in corte["pecas"]:
        pint = tuple(corte["pecas"]["textura"].get("pintura_rgb", pint))
    mats = Materiais(estilo, pint)
    kit = Kit(M, cfg, estilo, mats, casca)
    kit._mapa_parts = corte["mapa"]["parts"]
    kit.habitaculo()
    kit.portas()
    kit.porta_malas()
    kit.vao_motor()
    kit.embaixo()
    kit.freios()
    objs = []
    col = bpy.data.collections.new("kit_completo")
    bpy.context.scene.collection.children.link(col)
    for p in kit.pecas:
        ob = finalizar(p, mats)
        col.objects.link(ob)
        objs.append(ob)
    lods = []
    col1 = bpy.data.collections.new("kit_LOD1")
    bpy.context.scene.collection.children.link(col1)
    for ob in objs:
        l1 = fazer_lod1(ob)
        col1.objects.link(l1)
        lods.append(l1)
    base = os.path.join(a.out, f"{a.id}_completo{a.sufixo}")
    exportar(objs + lods, base + ".glb")
    for l1 in lods:
        l1.hide_render = True
        l1.hide_set(True)
    rel = {"id": a.id, "gerado_por": "acervo-3d/ferramentas/carro_completo.py", "licenca": "CC0 (próprio do estúdio; sem marca, logo nem texto)",
           "convencao": "metros; frente +X, ESQUERDA +Y, cima +Z; chão em z = 0; origem entre os eixos (a mesma do corte do carro_quebravel)",
           "epoca": cfg["epoca"], "estilo": estilo["descricao"], "motor": cfg["motor"], "tracao": cfg["tracao"],
           "carroceria": cfg.get("carroceria"), "glb_do_corte": os.path.basename(glb) if corte_objs else None,
           "vaos_a_tirar_do_corte": {k: [round(x, 3) for x in v] for k, v in M["vaos"].items()},
           "vaos_nota": "faces com o material MI_DNVao do corte cujo centro cai numa destas caixas saem quando o kit entra (a casca escura atrás do vidro, das portas, do capô e da tampa)",
           "fundo_a_tirar_do_corte": {"caixa": [round(x, 3) for x in M["fundo"]["caixa"]], "normal_z_max": M["fundo"]["normal_z_max"],
                                      "pecas": M["fundo"]["pecas"], "nota": "o fundo liso da casca (faces viradas para baixo nesta caixa) sai: o assoalho do kit fica no lugar"},
           "medidas": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in M.items() if k not in ("portas", "rodas", "vaos", "fundo")},
           "portas": M["portas"], "avisos": avisos + M["avisos"], "pecas": []}
    tot0 = tot1 = 0
    for ob, l1 in zip(objs, lods):
        t0, t1 = triangulos(ob.data), triangulos(l1.data)
        tot0 += t0
        tot1 += t1
        bb = [ob.matrix_world @ __import__("mathutils").Vector(c) for c in ob.bound_box]
        cx = [min(v.x for v in bb), max(v.x for v in bb), min(v.y for v in bb), max(v.y for v in bb), min(v.z for v in bb), max(v.z for v in bb)]
        rel["pecas"].append({"nome": ob.name, "grupo": ob.get("grupo"), "segue": ob.get("segue"), "triangulos": t0, "triangulos_lod1": t1,
                             "caixa_m": [round(c, 3) for c in cx], "materiais": [m.name for m in ob.data.materials]})
    rel["triangulos"] = {"lod0": tot0, "lod1": tot1}
    por_grupo = {}
    for pc in rel["pecas"]:
        por_grupo[pc["grupo"]] = por_grupo.get(pc["grupo"], 0) + pc["triangulos"]
    rel["triangulos_por_grupo"] = por_grupo
    rel["materiais"] = sorted(mats.cache)
    print(f"peças: {len(objs)}; triângulos LOD0 {tot0}, LOD1 {tot1}; por grupo {por_grupo}")
    if corte_objs and not a.sem_previa:
        rel["previas"] = [os.path.basename(s) for s in previas(M, cfg, corte_objs, objs, a.out, a.id + a.sufixo, a.amostras)]
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(rel, f, ensure_ascii=False, indent=1)
    for av in rel["avisos"]:
        print("AVISO:", av)
    return 0


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(principal(argv))


if __name__ == "__main__":
    main()
