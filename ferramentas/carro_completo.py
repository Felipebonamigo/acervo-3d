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
CARROCERIAS = ("hatch", "sedan", "furgao", "cabine_avancada", "jipe")
TEX = 1024             # lado das texturas de cor dos materiais grandes (px); aspereza e relevo em meia resolução
LOD1_RAZAO = 0.3       # fração dos triângulos no LOD1
JPEG_QUALIDADE = 82    # as texturas vão em JPEG dentro do GLB (cada GLB < 50 MB, regra do acervo)
ATRIBUTO_SUJEIRA = "sujeira"   # oclusão assada nos vértices: escurece frestas e cantos (sujeira de uso); vai no COLOR_0
# variante de sujeira por grupo: o vão do motor empoeirado, o embaixo e os freios com graxa, óleo e barro
VARIANTE_GRUPO = {"motor": "po", "embaixo": "graxa", "freios": "graxa"}
SUJAVEIS = {"po": {"aluminio_fundido", "metal_preto", "pintura_interna", "fundido", "aluminio", "plastico", "borracha", "chassi", "motor_pintado", "bateria",
                   "reservatorio", "ferro", "chicote", "isolante", "plastico_liso"},
            "graxa": {"aluminio_fundido", "metal_preto", "chassi", "ferro", "fundido", "aluminio", "borracha", "pinca", "plastico", "pintura_interna"}}


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
    if cfg.get("carroceria", "hatch") not in CARROCERIAS:
        raise ValueError(f"carroceria {cfg.get('carroceria')} fora de {CARROCERIAS}")
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
    cfg["corrigir"] troca medidas do mapa ou caixas de peça medidas à mão; cfg["corrigir"]["derivadas"] troca medidas daqui.
    """
    cfg = cfg or {}
    mapa = corte["mapa"]
    med = dict(mapa["medidas"])
    cx, rodas = caixas_do_mapa(mapa)
    # correções medidas à mão nas vistas do carro: a antena, o bagageiro ou um vidro mal achado pela cor não estragam a cabine
    corr = cfg.get("corrigir", {})
    for k, v in corr.items():
        if k in ("derivadas", "nota"):
            continue
        if k in med or not isinstance(v, list):
            med[k] = v
        else:
            cx[k] = v
    D = corr.get("derivadas", {})
    carroc = cfg.get("carroceria", "hatch")
    W = med["meia_largura"]
    H = med["altura"]
    R = med["raio_roda"]
    xd, xt = med["eixo_dianteiro"], med["eixo_traseiro"]
    wh = corte.get("wheels")
    if wh:
        xd, xt = wh["front_axle_cm"] / 100.0, wh["rear_axle_cm"] / 100.0
        R = wh["wheel_radius_cm"] / 100.0
    M = {"id": mapa.get("car"), "W": W, "H": H, "R": R, "xd": xd, "xt": xt, "entre_eixos": xd - xt,
         "comprimento": med["comprimento"], "portas": med.get("portas", 2), "carroceria": carroc}

    def d(k, v):
        M[k] = D.get(k, v)
        return M[k]

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
    d("x_frente", (bf[1] - 0.05) if bf else xd + 0.45 * med["comprimento"] / 2)
    d("x_tras", (bt[0] + 0.05) if bt else xt - 0.45 * med["comprimento"] / 2)

    # alturas
    d("z_saia", med["topo_da_saia"])
    d("z_cintura", med["linha_de_cintura"])
    # o piso fica ~13 cm abaixo do topo da soleira (a caixa da soleira é um perfil fechado de ~15 cm)
    d("z_piso", _limitar(M["z_saia"] - 0.13, 0.62 * R, M["z_saia"] - 0.04))
    M["z_teto"] = H

    # vidros: para-brisa, traseiro, laterais
    ws = cx.get("glass_windshield") or [xd - 0.95, xd - 0.30, -W + 0.15, W - 0.15, M["z_cintura"], H - 0.05]
    rg = cx.get("glass_rear") or [xt - 0.55, xt + 0.10, -W + 0.2, W - 0.2, M["z_cintura"], H - 0.08]
    M["ws"], M["rg"] = ws, rg
    if carroc == "cabine_avancada":      # o motorista vai sobre o eixo: a parede da frente é o corta-fogo, sem capô
        d("x_corta_fogo", M["x_frente"] - 0.10)
        d("prof_painel", 0.36)
        d("x_painel", ws[1] - 0.06 - M["prof_painel"])
        d("z_painel", ws[4] - 0.03)
    else:
        d("x_corta_fogo", ws[1] - 0.03)
        d("prof_painel", _limitar(0.30 + 0.25 * (ws[1] - ws[0]), 0.36, 0.55))
        d("x_painel", ws[1] - M["prof_painel"])
        d("z_painel", ws[4] - 0.005)
    d("meia_interna", W - 0.13)
    d("meia_teto", W - 0.22)
    d("z_teto_int", H - 0.05)
    M["x_teto_frente"] = ws[0] + 0.02
    M["x_teto_tras"] = rg[1] - 0.02
    M["inclinacao_para_brisa"] = (ws[1] - ws[0]) / max(0.05, ws[5] - ws[4])

    # bancos (assento a ~0,27 m do piso e encosto a ~0,62 m do assento: medidas típicas de carro pequeno, ver dados "medidas_reais")
    cb = med.get("coluna_b", xt + 0.4 * M["entre_eixos"])
    M["coluna_b"] = cb
    M["coluna_a"] = med.get("coluna_a", ws[1] - 0.2)
    d("x_encosto_d", min(cb + 0.02, M["x_corta_fogo"] - 1.05))
    d("x_encosto_t", _limitar(xt + 0.05, rg[0] + 0.12, M["x_encosto_d"] - 0.75))
    d("y_banco", max(0.27, M["meia_interna"] - 0.36))
    d("z_assento", M["z_piso"] + 0.27)
    d("z_assento_t", M["z_piso"] + 0.25)

    # portas: caixa do corte, vidro da mesma posição para a altura da janela
    portas = {}
    for nome, b in cx.items():
        if nome.startswith("door_") and len(nome) == 7:
            pos = nome[5:]
            vid = cx.get("glass_door_" + pos)
            portas[pos] = {"x0": b[0], "x1": b[1], "z0": max(b[4], M["z_saia"]), "z1": b[5], "lado": 1 if pos[1] == "l" else -1,
                           "z_janela": (min(vid[5], H - 0.04) if vid else H - 0.08),
                           "x_vidro": ([vid[0], vid[1]] if vid else [b[0], b[1]])}
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
    d("z_capo_tras", ws[4] - 0.03)
    d("z_capo_frente", max(z_frente_topo, med.get("topo_para_choque_dianteiro", 0.45) + 0.12))
    d("x_radiador", M["x_frente"] - 0.20)
    tl = cx.get("taillight_left") or cx.get("taillight_right")
    d("z_tampa_tras_borda", (tl[4] - 0.02) if tl else med.get("topo_para_choque_traseiro", 0.5) + 0.05)
    if carroc in ("hatch", "furgao", "jipe"):
        d("z_mala", M["z_piso"] + 0.08)
    elif carroc == "cabine_avancada":
        d("z_mala", M["z_piso"])
    else:
        d("z_mala", min(M["z_piso"] + 0.15, med.get("topo_para_choque_traseiro", 0.5) - 0.03))
    d("x_mala_frente", M["x_encosto_t"] - 0.10)
    d("x_mala_tras", M["x_tras"] + 0.14)

    # caixas onde a casca escura do corte (MI_DNVao) sai quando o kit entra
    vaos = {"cabine": [M["x_encosto_t"] - 0.30, M["x_corta_fogo"] + 0.03, -W - 0.06, W + 0.06, M["z_saia"] - 0.03, H + 0.05]}
    vaos["traseira"] = [M["x_tras"] - 0.05, M["x_encosto_t"] - 0.30, -W - 0.06, W + 0.06, M["z_mala"] - 0.05, H + 0.05]
    if carroc == "cabine_avancada":
        vaos["cabine"][1] = M["x_frente"] + 0.05
    else:
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


def _base(ex, ey, ez):
    """Matriz cujas colunas são os eixos locais X, Y e Z dados no espaço do carro."""
    from mathutils import Matrix
    m = Matrix.Identity(4)
    for i in range(3):
        m[i][0], m[i][1], m[i][2] = ex[i], ey[i], ez[i]
    return m


def _moldura(w, h, borda, cantos=None):
    """Retângulo de cantos arredondados w x h (polígono anti-horário no plano local), para chapas e bases."""
    r = min(cantos if cantos is not None else borda, 0.49 * min(w, h))
    pts = []
    for (cx, cy, a0) in ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)):
        for k in range(5):
            a = math.radians(a0 + 90 * k / 4)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


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
# Blender: materiais (texturas procedurais assadas em numpy, ladrilháveis)
# ================================================================================================================================

def _srgb_lin(c):
    return tuple((x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def _suave(a, b, x):
    np = _np()
    t = np.clip((x - a) / max(1e-6, b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _np():
    import numpy
    return numpy


class Texturas:
    """Ruídos ladrilháveis em n x n: valor, fbm, Voronoi (F1 e F2), riscos e manchas."""

    def __init__(self, n=TEX, semente=7):
        np = _np()
        self.np = np
        self.n = n
        self.rng = np.random.default_rng(semente)
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
            fk = int(f * 2 ** k)
            fyk = int((fy or f) * 2 ** k)
            if max(fk, fyk) > self.n // 2:
                if k > 0:
                    break
                fk, fyk = min(fk, self.n // 2), min(fyk, self.n // 2)   # detalhe menor que o pixel: fica no limite
            t = t + amp * self.ruido(max(1, fk), max(1, fyk))
            s += amp
            amp *= ganho
        return t / s

    def celulas(self, k, ky=None, f2=False):
        """Voronoi ladrilhável, k x ky células: distância F1 (e F2) em unidades de célula. Vetorizado pelos 3 x 3 vizinhos."""
        np = self.np
        ky = ky or k
        pts = self.rng.random((ky, k, 2))
        x, y = self.u * k, self.v * ky
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        d1 = np.full(x.shape, 9.0)
        d2 = np.full(x.shape, 9.0)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cx, cy = ix + dx, iy + dy
                p = pts[cy % ky, cx % k]
                d = (x - cx - p[..., 0]) ** 2 + (y - cy - p[..., 1]) ** 2
                d2 = np.where(d < d1, d1, np.minimum(d2, d))
                d1 = np.minimum(d1, d)
        return (np.sqrt(d1), np.sqrt(d2)) if f2 else np.sqrt(d1)

    def riscos(self, quantos, comp_px, larg_px=1.0, angulo=None, abertura=math.pi, curvos=0.0):
        """Máscara 0-1 de riscos finos (segmentos com ponta afinada), ladrilhável: micro-riscos de metal, plástico e pintura."""
        np = self.np
        n = self.n
        m = np.zeros((n, n))
        for _ in range(quantos):
            x0, y0 = self.rng.random(2) * n
            a = (angulo if angulo is not None else 0.0) + (self.rng.random() - 0.5) * abertura
            L = comp_px * (0.3 + self.rng.random())
            passos = max(2, int(L * 1.5))
            t = np.linspace(0, 1, passos)
            curva = curvos * (self.rng.random() - 0.5) * 2
            xs = x0 + np.cos(a + curva * t) * L * t
            ys = y0 + np.sin(a + curva * t) * L * t
            peso = np.sin(np.pi * t) ** 0.6 * (0.4 + 0.6 * self.rng.random())
            for o in range(int(math.ceil(larg_px))):
                np.maximum.at(m, ((ys.astype(int) + o) % n, xs.astype(int) % n), peso)
        return m

    def manchas(self, f, limiar, suave=0.08, oit=4):
        """Manchas grandes (máscara 0-1) por fbm com limiar: sujeira, mancha de carpete, ferrugem."""
        return _suave(limiar, limiar + suave, self.fbm(f, oit))

    def borrar(self, h, r=1):
        np = self.np
        out = h.copy()
        for _ in range(r):
            out = (out + np.roll(out, 1, 0) + np.roll(out, -1, 0) + np.roll(out, 1, 1) + np.roll(out, -1, 1)) / 5.0
        return out

    def normal(self, h, forca):
        np = self.np
        dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * forca
        dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * forca
        n = np.stack([-dx, -dy, np.ones_like(h)], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        return n * 0.5 + 0.5


def _superficie(tx, tipo, lad):
    """
    Superfície de um tipo de material: (altura 0-1, cor multiplicadora (n, n) ou (n, n, 3), aspereza absoluta (n, n) ou None).
    lad é o lado do ladrilho em metros: os detalhes têm tamanho físico (mm), não fração da imagem.
    """
    np = tx.np
    n = tx.n
    u, v = tx.u, tx.v
    ppm = n / lad                          # pixels por metro

    def ciclos(passo_m):                    # número inteiro de repetições no ladrilho (para ladrilhar)
        return max(2, int(round(lad / passo_m)))

    if tipo in ("tecido", "tecido_estampa", "listras"):
        k = ciclos(0.0016)                  # fio de ~1,6 mm (tecido de banco, trama aberta)
        fu, fv = (u * k) % 1.0, (v * k) % 1.0
        pu = np.cos((fu - 0.5) * math.pi) ** 2
        pv = np.cos((fv - 0.5) * math.pi) ** 2
        xadrez = ((np.floor(u * k) + np.floor(v * k)) % 2).astype(bool)
        h = np.where(xadrez, pu, pv) * 0.75 + tx.fbm(ciclos(0.004), 2) * 0.25
        fio = 0.9 + 0.2 * tx.ruido(k, k)                 # cada fio um pouco diferente
        bolinhas = (tx.celulas(ciclos(0.006)) < 0.18) * (tx.fbm(ciclos(0.05), 3) > 0.55)   # pilling
        cor = fio * (0.92 + 0.16 * tx.fbm(ciclos(0.12), 3)) * (1 + 0.25 * bolinhas)
        if tipo == "tecido_estampa":         # miolo dos anos 90: trama + pontinhos em losango de ~8 mm
            kk = ciclos(0.008)
            a = np.abs(((u * kk) % 1.0) - 0.5) + np.abs(((v * kk) % 1.0) - 0.5)
            pont = _suave(0.16, 0.10, a)
            cor = cor * (1 + 0.45 * pont)
            h = h * (1 - 0.3 * pont) + 0.3 * pont
        if tipo == "listras":                # anos 80: listras finas de cor
            kk = ciclos(0.012)
            lis = (np.sin(v * 2 * math.pi * kk) > 0.55).astype(float)
            cor = cor * (0.85 + 0.45 * lis)
        rug = 0.88 + 0.1 * tx.fbm(ciclos(0.05), 2)
        return h, cor, rug
    if tipo == "vinil":
        c1, c2 = tx.celulas(ciclos(0.0011), f2=True)     # grão de couro sintético ~1 mm
        grao = np.clip((c2 - c1) * 2.2, 0, 1) ** 0.5
        # vincos: vales finos e longos (o vinil dobra onde senta)
        w = tx.fbm(ciclos(0.06), 4, fy=ciclos(0.15))
        vinco = 1 - _suave(0.0, 0.035, np.abs(w - 0.5))
        h = grao * 0.55 + (1 - vinco) * 0.45
        cor = 0.94 + 0.10 * tx.fbm(ciclos(0.08), 3) - 0.12 * vinco
        rug = 0.42 + 0.10 * tx.fbm(ciclos(0.03), 3) - 0.06 * grao + 0.08 * vinco
        return h, cor, rug
    if tipo == "plastico":
        c1 = tx.celulas(ciclos(0.0007))      # granulado fino de ~0,7 mm (plástico texturizado de painel)
        h = np.clip(c1, 0, 1) ** 0.7 * 0.6 + tx.fbm(ciclos(0.002), 2) * 0.4
        ris = tx.riscos(int(18 * lad / 0.2), 0.03 * ppm, 1.0)
        cor = 0.96 + 0.06 * tx.fbm(ciclos(0.1), 3) + 0.10 * ris
        rug = 0.62 + 0.05 * tx.fbm(ciclos(0.05), 3) - 0.18 * ris
        return h, cor, rug
    if tipo == "plastico_liso":
        h = tx.fbm(ciclos(0.003), 2) * 0.4
        ris = tx.riscos(int(30 * lad / 0.2), 0.02 * ppm, 1.0)
        cor = 0.97 + 0.05 * tx.fbm(ciclos(0.1), 3) + 0.12 * ris
        rug = 0.38 + 0.06 * tx.fbm(ciclos(0.05), 3) + 0.15 * ris
        return h, cor, rug
    if tipo == "borracha":
        h = tx.fbm(ciclos(0.0015), 3)
        po = tx.manchas(ciclos(0.15), 0.55, 0.2)
        cor = (0.9 + 0.12 * tx.fbm(ciclos(0.04), 2)) * (1 + 0.9 * po)
        rug = 0.86 + 0.08 * po
        return h, cor, rug
    if tipo == "carpete":
        fib = tx.fbm(ciclos(0.0012), 2)
        laco = tx.celulas(ciclos(0.0018))     # laços do carpete agulhado
        h = fib * 0.35 + (1 - np.clip(laco, 0, 1)) * 0.45 + tx.fbm(ciclos(0.01), 2) * 0.2
        mancha = tx.manchas(ciclos(0.25), 0.66, 0.06)          # manchas escuras (café, barro)
        gasto = tx.manchas(ciclos(0.35), 0.6, 0.15)            # áreas pisadas, mais claras e lisas
        cor = (0.82 + 0.3 * fib) * (0.92 + 0.12 * tx.fbm(ciclos(0.05), 3)) * (1 - 0.45 * mancha) * (1 + 0.25 * gasto)
        h = h * (1 - 0.5 * gasto)
        rug = np.full((n, n), 1.0) - 0.08 * mancha
        return h, cor, rug
    if tipo == "feltro":
        h = tx.fbm(ciclos(0.004), 3) * 0.7 + tx.rng.random((n, n)) * 0.3
        amarelo = tx.manchas(ciclos(0.4), 0.62, 0.15)
        cor = (0.95 + 0.07 * tx.fbm(ciclos(0.06), 3))[..., None] * (1 - amarelo[..., None] * np.array([0.05, 0.12, 0.3]))
        return h, cor, np.full((n, n), 0.95)
    if tipo == "escovado":
        h = tx.fbm(2, 3, fy=ciclos(0.0006))
        ris = tx.riscos(int(160 * lad / 0.3), 0.05 * ppm, 1.0)
        cor = 0.93 + 0.08 * tx.fbm(2, 2, fy=ciclos(0.004)) - 0.05 * ris
        rug = 0.26 + 0.08 * tx.fbm(ciclos(0.05), 3) + 0.25 * ris
        return np.clip(h - 0.3 * ris, 0, 1), cor, rug
    if tipo == "fundido":
        h = tx.fbm(ciclos(0.004), 4) * 0.7 - (tx.celulas(ciclos(0.003)) < 0.12) * 0.3
        cor = 0.82 + 0.25 * tx.fbm(ciclos(0.05), 3)
        rug = 0.55 + 0.15 * tx.fbm(ciclos(0.02), 3)
        return h - h.min(), cor, rug
    if tipo == "pintura":
        h = tx.fbm(ciclos(0.003), 2) * 0.5      # casca de laranja leve
        ris = tx.riscos(int(25 * lad / 0.5), 0.06 * ppm, 1.0)
        cor = 0.97 + 0.04 * tx.fbm(ciclos(0.2), 2) + 0.12 * ris
        rug = 0.32 + 0.06 * tx.fbm(ciclos(0.1), 3) + 0.25 * ris
        return h, cor, rug
    if tipo == "chassi":                     # antirruído emborrachado embaixo do carro
        b = tx.celulas(ciclos(0.004))
        h = (1 - np.clip(b, 0, 1)) * 0.6 + tx.fbm(ciclos(0.01), 3) * 0.4
        cor = 0.8 + 0.35 * tx.fbm(ciclos(0.15), 3)
        return h, cor, 0.8 + 0.1 * tx.fbm(ciclos(0.05), 2)
    if tipo == "ferro":                       # aço com ferrugem em placas
        f = tx.fbm(ciclos(0.12), 5)
        ferr = _suave(0.48, 0.62, f)
        pits = tx.celulas(ciclos(0.003)) < 0.2
        h = tx.fbm(ciclos(0.004), 3) * 0.6 + ferr * 0.3 + pits * ferr * 0.1
        base = np.array([0.36, 0.34, 0.33])
        ferrugem = np.array([1.25, 0.72, 0.42])
        cor = (0.8 + 0.4 * tx.fbm(ciclos(0.03), 3))[..., None] * (base + (ferrugem - base) * ferr[..., None]) / 0.36
        rug = 0.5 + 0.4 * ferr
        return h, cor, rug
    if tipo == "radiador":
        aleta = np.abs(np.sin(u * math.pi * ciclos(0.0016)))
        tubo = (np.sin(v * math.pi * ciclos(0.011)) > 0.72)
        h = np.where(tubo, 1.0, aleta * 0.6)
        suj = tx.manchas(ciclos(0.15), 0.5, 0.2)
        return h, np.where(tubo, 1.0, 0.45 + 0.4 * aleta) * (1 - 0.35 * suj), 0.45 + 0.3 * suj
    if tipo == "alto_falante":
        k = ciclos(0.004)
        furo = (np.sin(u * 2 * math.pi * k) * np.sin(v * 2 * math.pi * k)) > 0.55
        h = np.where(furo, 0.0, 1.0)
        return h, np.where(furo, 0.15, 1.0), None
    if tipo == "cinto":                      # sarja diagonal do cadarço do cinto
        k = ciclos(0.0012)
        h = 0.5 + 0.5 * np.sin((u + v) * 2 * math.pi * k)
        return h, 0.92 + 0.1 * h + 0.06 * tx.fbm(ciclos(0.05), 2), 0.7 + 0.1 * h
    if tipo == "liso":
        return np.zeros((n, n)), np.ones((n, n)), None
    return np.zeros((n, n)), np.ones((n, n)), None


# variantes de uso: (mistura com a cor, cor da sujeira sRGB, aspereza somada, quanto alisa o relevo, escala da mancha em m)
SUJEIRA = {
    "po": (0.55, (0.47, 0.42, 0.35), 0.22, 0.45, 0.25),        # pó nas superfícies de cima do vão do motor
    "graxa": (0.6, (0.035, 0.03, 0.025), -0.25, 0.2, 0.35),    # graxa, óleo e barro embaixo
    "gasto": (0.45, None, -0.12, 0.6, 0.12),                   # banco e volante gastos: claro e liso onde se apoia
}


def _mostrador(tipo, n=512, epoca="90"):
    """Mostrador com números genéricos (sem marca nem texto de marca): velocímetro, conta-giros, combustível, temperatura."""
    np = _np()
    from PIL import Image, ImageDraw, ImageFont
    esc = 4
    N = n * esc
    im = Image.new("RGB", (N, N), (6, 6, 7))
    d = ImageDraw.Draw(im)
    c = N / 2
    branco = (225, 225, 220) if epoca != "70" else (230, 226, 205)
    try:
        fonte = ImageFont.load_default(size=int(N * 0.085))
        fpeq = ImageFont.load_default(size=int(N * 0.045))
    except TypeError:
        fonte = fpeq = ImageFont.load_default()
    d.ellipse([N * 0.03, N * 0.03, N * 0.97, N * 0.97], outline=(70, 70, 72), width=int(N * 0.012))
    if tipo in ("velocimetro", "conta_giros"):
        a0, a1 = math.radians(225), math.radians(-45)   # 270° no sentido horário
        if tipo == "velocimetro":
            vmax = 160 if epoca == "70" else (200 if epoca in ("80", "90") else 220)
            grossas, finas, rotulo = vmax // 20, vmax // 10, lambda i: str(i * 20)
            unidade = "km/h"
        else:
            vmax = 7 if epoca != "2000" else 8
            grossas, finas, rotulo = vmax, vmax * 5, lambda i: str(i)
            unidade = "x1000 rpm"
        for i in range(finas + 1):
            t = i / finas
            a = a0 + (a1 - a0) * t
            grossa = (i % (finas // grossas)) == 0
            r1, r0 = N * 0.44, N * (0.36 if grossa else 0.40)
            cor = branco
            if tipo == "conta_giros" and t > (vmax - 1.2) / vmax:
                cor = (200, 30, 25)
            d.line([(c + r0 * math.cos(a), c - r0 * math.sin(a)), (c + r1 * math.cos(a), c - r1 * math.sin(a))], fill=cor,
                   width=int(N * (0.012 if grossa else 0.006)))
        for i in range(grossas + 1):
            a = a0 + (a1 - a0) * i / grossas
            r = N * 0.30
            txt = rotulo(i)
            bb = d.textbbox((0, 0), txt, font=fonte)
            d.text((c + r * math.cos(a) - (bb[2] - bb[0]) / 2, c - r * math.sin(a) - (bb[3] - bb[1]) / 2 - bb[1]), txt, fill=branco, font=fonte)
        bb = d.textbbox((0, 0), unidade, font=fpeq)
        d.text((c - (bb[2] - bb[0]) / 2, c + N * 0.14), unidade, fill=(170, 170, 165), font=fpeq)
        if tipo == "velocimetro":            # hodômetro
            w, h = N * 0.30, N * 0.075
            d.rectangle([c - w / 2, c + N * 0.24, c + w / 2, c + N * 0.24 + h], fill=(18, 18, 18), outline=(90, 90, 90))
            txt = "0 8 4 2 1 7"
            bb = d.textbbox((0, 0), txt, font=fpeq)
            d.text((c - (bb[2] - bb[0]) / 2, c + N * 0.24 + (h - (bb[3] - bb[1])) / 2 - bb[1]), txt, fill=(210, 210, 200), font=fpeq)
        # luzes-espia genéricas (pontos coloridos apagados)
        for k, cor in enumerate(((120, 25, 20), (25, 90, 30), (130, 100, 20))):
            x = c - N * 0.12 + k * N * 0.12
            d.ellipse([x - N * 0.02, c + N * 0.04, x + N * 0.02, c + N * 0.08], fill=cor)
    else:
        a0, a1 = math.radians(150), math.radians(30)
        for i in range(9):
            t = i / 8
            a = a0 + (a1 - a0) * t
            grossa = i % 4 == 0
            r1, r0 = N * 0.44, N * (0.34 if grossa else 0.39)
            cor = (200, 30, 25) if (tipo == "combustivel" and t < 0.15) or (tipo == "temperatura" and t > 0.85) else branco
            d.line([(c + r0 * math.cos(a), c - r0 * math.sin(a)), (c + r1 * math.cos(a), c - r1 * math.sin(a))], fill=cor,
                   width=int(N * (0.016 if grossa else 0.009)))
        rot = ("0", "1/2", "1") if tipo == "combustivel" else ("50", "90", "130")
        for i, txt in enumerate(rot):
            a = a0 + (a1 - a0) * i / 2
            r = N * 0.25
            bb = d.textbbox((0, 0), txt, font=fonte)
            d.text((c + r * math.cos(a) - (bb[2] - bb[0]) / 2, c - r * math.sin(a) - (bb[3] - bb[1]) / 2 - bb[1]), txt, fill=branco, font=fonte)
        # ícone genérico: bomba (retângulo com bico) ou termômetro (haste e bulbo)
        if tipo == "combustivel":
            d.rectangle([c - N * 0.05, c + N * 0.10, c + N * 0.03, c + N * 0.24], outline=branco, width=int(N * 0.012))
            d.line([(c + N * 0.03, c + N * 0.13), (c + N * 0.08, c + N * 0.16), (c + N * 0.08, c + N * 0.22)], fill=branco, width=int(N * 0.01))
        else:
            d.line([(c, c + N * 0.08), (c, c + N * 0.20)], fill=branco, width=int(N * 0.02))
            d.ellipse([c - N * 0.035, c + N * 0.19, c + N * 0.035, c + N * 0.26], fill=branco)
    im = im.resize((n, n), Image.LANCZOS)
    arr = np.asarray(im).astype(float) / 255.0
    return arr[::-1].copy()   # a imagem do Blender começa por baixo


class Materiais:
    """Os materiais do kit, criados uma vez por carro (cores da época e a cor da pintura do carro)."""

    TIPOS = {
        # nome: (tipo de superfície, metálico, aspereza (se a superfície não diz), força do relevo, ladrilho em m, lado da textura)
        "banco": ("tecido", 0.0, 0.9, 1.2, 0.25, TEX), "banco_miolo": ("tecido_estampa", 0.0, 0.92, 1.2, 0.25, TEX),
        "vinil": ("vinil", 0.0, 0.42, 0.8, 0.30, TEX), "vinil_2": ("vinil", 0.0, 0.42, 0.8, 0.30, TEX),
        "listrado": ("listras", 0.0, 0.9, 1.2, 0.25, TEX),
        "plastico": ("plastico", 0.0, 0.62, 0.5, 0.20, TEX), "plastico_claro": ("plastico", 0.0, 0.6, 0.5, 0.20, TEX),
        "plastico_liso": ("plastico_liso", 0.0, 0.38, 0.3, 0.30, TEX // 2), "carpete": ("carpete", 0.0, 1.0, 2.2, 0.60, TEX),
        "tapete": ("borracha", 0.0, 0.85, 1.0, 0.40, TEX // 2),
        "forro_teto": ("feltro", 0.0, 0.95, 0.3, 0.50, TEX // 2), "borracha": ("borracha", 0.0, 0.85, 0.8, 0.25, TEX // 2),
        "cinto": ("cinto", 0.0, 0.7, 1.0, 0.06, TEX // 4), "cromado": ("escovado", 1.0, 0.12, 0.15, 0.30, TEX // 2),
        "aluminio": ("escovado", 1.0, 0.32, 0.6, 0.30, TEX // 2),
        "aluminio_fundido": ("fundido", 1.0, 0.58, 1.0, 0.40, TEX // 2), "fundido": ("fundido", 1.0, 0.55, 1.4, 0.40, TEX),
        "pintura_interna": ("pintura", 0.0, 0.32, 0.1, 0.60, TEX // 2), "chassi": ("chassi", 0.0, 0.8, 0.5, 0.80, TEX // 2),
        "ferro": ("ferro", 0.6, 0.75, 1.2, 0.50, TEX // 2), "metal_preto": ("pintura", 0.4, 0.55, 0.15, 0.40, TEX // 2),
        "radiador": ("radiador", 1.0, 0.45, 2.0, 0.12, TEX // 2), "alto_falante": ("alto_falante", 0.0, 0.7, 1.5, 0.08, TEX // 4),
        "reservatorio": ("plastico_liso", 0.0, 0.45, 0.3, 0.25, TEX // 4), "espelho": ("liso", 1.0, 0.03, 0.0, 1.0, 64),
        "bateria": ("plastico", 0.0, 0.55, 0.5, 0.20, TEX // 4), "vermelho": ("plastico_liso", 0.0, 0.5, 0.3, 0.2, TEX // 8),
        "amarelo": ("plastico_liso", 0.0, 0.5, 0.3, 0.2, TEX // 8), "azul": ("plastico_liso", 0.0, 0.5, 0.3, 0.2, TEX // 8),
        "laranja": ("plastico_liso", 0.0, 0.5, 0.3, 0.2, TEX // 8),
        "motor_pintado": ("fundido", 0.3, 0.45, 0.8, 0.40, TEX // 2), "lente": ("liso", 0.0, 0.1, 0.0, 0.3, 64),
        "pinca": ("fundido", 0.2, 0.5, 1.0, 0.20, TEX // 4), "disco": ("escovado", 1.0, 0.35, 0.5, 0.20, TEX // 4),
        "chicote": ("borracha", 0.0, 0.7, 0.6, 0.10, TEX // 4), "volante": ("vinil", 0.0, 0.5, 0.6, 0.15, TEX // 2),
        "isolante": ("feltro", 0.0, 0.95, 0.6, 0.40, TEX // 4), "madeira": ("fundido", 0.0, 0.7, 0.6, 0.6, TEX // 2),
        "fio": ("liso", 0.0, 0.5, 0.0, 0.1, 64),
        "instrumentos_velocimetro": ("mostrador", 0.0, 0.3, 0.0, 1.0, 512),
        "instrumentos_conta_giros": ("mostrador", 0.0, 0.3, 0.0, 1.0, 512),
        "instrumentos_combustivel": ("mostrador", 0.0, 0.3, 0.0, 1.0, 256),
        "instrumentos_temperatura": ("mostrador", 0.0, 0.3, 0.0, 1.0, 256),
    }

    def __init__(self, estilo, pintura_rgb, epoca="90"):
        import bpy
        self.bpy = bpy
        self.epoca = epoca
        e = estilo
        self.cores = {
            "banco": e["cor_banco"], "banco_miolo": e["cor_banco_2"], "vinil": e["cor_banco"], "vinil_2": e["cor_banco_2"],
            "listrado": e["cor_banco_2"], "plastico": e["cor_plastico"],
            "plastico_claro": tuple(min(1, c * 2.6 + 0.08) for c in e["cor_plastico"]),
            "plastico_liso": e["cor_plastico"], "carpete": e["cor_carpete"], "forro_teto": e["cor_teto"],
            "tapete": (0.035, 0.035, 0.035), "volante": (0.04, 0.04, 0.042) if epoca != "70" else e["cor_banco"],
            "borracha": (0.03, 0.03, 0.03), "cinto": (0.06, 0.06, 0.065), "cromado": (0.92, 0.92, 0.92),
            "aluminio": (0.72, 0.72, 0.70), "aluminio_fundido": (0.60, 0.60, 0.58), "fundido": (0.50, 0.50, 0.48), "pintura_interna": pintura_rgb,
            "chassi": (0.07, 0.07, 0.065), "ferro": (0.36, 0.34, 0.33), "metal_preto": (0.035, 0.035, 0.035),
            "radiador": (0.30, 0.30, 0.31), "alto_falante": (0.02, 0.02, 0.02), "reservatorio": (0.80, 0.78, 0.70),
            "espelho": (0.95, 0.95, 0.95), "bateria": (0.10, 0.10, 0.11), "vermelho": (0.55, 0.04, 0.03),
            "amarelo": (0.85, 0.6, 0.02), "azul": (0.05, 0.18, 0.55), "laranja": (0.9, 0.35, 0.03),
            "motor_pintado": (0.10, 0.12, 0.16), "lente": (0.9, 0.9, 0.85), "pinca": (0.28, 0.27, 0.26), "disco": (0.45, 0.44, 0.43),
            "chicote": (0.02, 0.02, 0.02), "isolante": (0.08, 0.075, 0.07), "madeira": (0.32, 0.22, 0.13), "fio": (0.03, 0.03, 0.03),
        }
        self.cache = {}
        self.sup = {}
        self.imgs = {}

    def nome_base(self, nome):
        for suf in SUJEIRA:
            if nome.endswith("_" + suf):
                return nome[: -len(suf) - 1], suf
        return nome, None

    def get(self, nome):
        if nome in self.cache:
            return self.cache[nome]
        import zlib
        bpy = self.bpy
        np = _np()
        base_nome, var = self.nome_base(nome)
        tipo, metal, rug0, forca, lad, n = self.TIPOS[base_nome]
        mat = bpy.data.materials.new(nome)
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if tipo == "mostrador":
            cor = _mostrador(base_nome.split("_", 1)[1], n, self.epoca)
            h = h_rel = np.zeros((n, n))
            rug = np.full((n, n), 0.35)
        else:
            chave = (tipo, lad, n)
            if chave not in self.sup:      # uma superfície por tipo e ladrilho, com semente própria: materiais do mesmo tipo dividem o relevo
                tx = Texturas(n, zlib.crc32(f"{tipo}{lad}".encode()))
                self.sup[chave] = (tx,) + _superficie(tx, tipo, lad)
            tx, h, var_cor, rug_s = self.sup[chave]
            h_rel = h
            rug = rug_s if rug_s is not None else np.full((n, n), rug0)
            if rug_s is not None and abs(rug0 - float(np.mean(rug_s))) > 0.05:
                rug = rug_s - float(np.mean(rug_s)) + rug0     # a aspereza média do material manda; a superfície dá a variação
            base = np.array(_srgb_lin(self.cores[base_nome]))
            vc = var_cor if var_cor.ndim == 3 else var_cor[..., None]
            cor = np.clip(base[None, None, :] * vc, 0, 1)
            if var:
                cor, rug, h = self._sujar(tx, cor, rug, h, var, lad, zlib.crc32(nome.encode()))
            cor = np.power(cor, 1 / 2.2)   # a imagem de cor é sRGB
        if var and n >= 512:
            cor = cor.reshape(n // 2, 2, n // 2, 2, 3).mean((1, 3))
        rgba = np.concatenate([cor, np.ones(cor.shape[:2] + (1,))], -1)
        img = self._img(f"T_{nome}_cor", rgba, "sRGB")
        tc = nt.nodes.new("ShaderNodeTexImage")
        tc.image = img
        # a cor da textura vezes a sujeira por oclusão assada nos vértices (atributo "sujeira", vira o COLOR_0 do glTF)
        ca = nt.nodes.new("ShaderNodeVertexColor")
        ca.layer_name = ATRIBUTO_SUJEIRA
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        nt.links.new(tc.outputs["Color"], mix.inputs[6])
        nt.links.new(ca.outputs["Color"], mix.inputs[7])
        nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
        # ORM: R oclusão (1), G aspereza, B metálico
        hn = (h - h.min()) / max(1e-6, (h.max() - h.min()))
        r = np.clip(rug + (0.5 - hn) * 0.06, 0.02, 1.0)
        # a aspereza vai em meia resolução (varia devagar) e as variantes de sujeira também levam a cor em meia resolução
        r2 = r.reshape(n // 2, 2, n // 2, 2).mean((1, 3)) if n >= 128 else r
        m2 = r2.shape[0]
        orm = np.stack([np.ones((m2, m2)), r2, np.full((m2, m2), metal), np.ones((m2, m2))], -1)
        io = self._img(f"T_{nome}_orm", orm, "Non-Color")
        to = nt.nodes.new("ShaderNodeTexImage")
        to.image = io
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(to.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        if forca > 0:
            chave = ("nor", "tecido" if tipo in ("tecido", "tecido_estampa", "listras") else tipo, lad, n, forca)    # o relevo é do tipo: variantes e cores dividem a mesma imagem
            if chave not in self.imgs:
                hb = (h_rel - h_rel.min()) / max(1e-6, (h_rel.max() - h_rel.min()))
                nn = n
                if n >= 512:                       # normal em meia resolução: o detalhe fino fica na cor, o relevo médio aqui
                    hb = hb.reshape(n // 2, 2, n // 2, 2).mean((1, 3))
                    nn = n // 2
                nm = _normal_np(hb, forca * 0.0004 * nn / lad)    # relevo de ~0,4 mm x força, na escala física do ladrilho
                self.imgs[chave] = self._img(f"T_{nome}_nor", np.concatenate([nm, np.ones((nn, nn, 1))], -1), "Non-Color")
            tn = nt.nodes.new("ShaderNodeTexImage")
            tn.image = self.imgs[chave]
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nt.links.new(tn.outputs["Color"], nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        if base_nome == "reservatorio":
            bsdf.inputs["Transmission Weight"].default_value = 0.2
        mat["ladrilho_m"] = lad
        self.cache[nome] = mat
        return mat

    def _sujar(self, tx, cor, rug, h, var, lad, semente):
        """Pó (claro, áspero, em manchas), graxa (escura, oleosa, com respingos) ou gasto (desbotado e liso) por cima da cor."""
        np = _np()
        mix, cs, drug, alisa, esc = SUJEIRA[var]
        t2 = Texturas(tx.n, semente)
        k = max(2, int(round(lad / esc)))
        m = t2.fbm(k, 5)
        if var == "po":
            mask = _suave(0.35, 0.8, m) * mix + 0.12
            fino = t2.fbm(max(2, int(round(lad / 0.002))), 2) * 0.2
            alvo = np.array(_srgb_lin(cs))[None, None, :] * (0.8 + fino[..., None] + 0.3 * m[..., None])
        elif var == "graxa":
            # escorridos: manchas finas e compridas (fbm esticado em z) e borrões grandes
            esc = t2.fbm(max(2, int(round(lad / 0.03))), 4, fy=max(2, int(round(lad / 0.008))))
            resp = _suave(0.62, 0.7, esc)
            mask = np.clip(_suave(0.35, 0.75, m) * mix + resp * 0.5 + 0.15, 0, 1)
            alvo = np.array(_srgb_lin(cs))[None, None, :] * (0.8 + 0.4 * m[..., None])
            rug = rug + drug * mask * (m > 0.55) + 0.15 * mask * (m <= 0.55)
            mask3 = mask[..., None]
            return cor * (1 - mask3) + alvo * mask3, np.clip(rug, 0.05, 1.0), h * (1 - alisa * mask)
        else:  # gasto
            mask = _suave(0.38, 0.72, m) * mix
            alvo = np.clip(cor * 1.7 + 0.015, 0, 1)
        mask3 = mask[..., None]
        cor = cor * (1 - mask3) + alvo * mask3
        rug = np.clip(rug + drug * mask, 0.05, 1.0)
        h = h * (1 - alisa * mask)
        return cor, rug, h

    def _img(self, nome, arr, cs):
        bpy = self.bpy
        n = arr.shape[0]
        img = bpy.data.images.new(nome, arr.shape[1], n, alpha=False)
        img.colorspace_settings.name = cs
        img.pixels.foreach_set(arr.astype("float32").ravel())
        img.file_format = "JPEG"
        img.pack()
        return img


def _normal_np(h, forca):
    np = _np()
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * forca
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * forca
    n = np.stack([-dx, -dy, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n * 0.5 + 0.5


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

    def _tem_peca_corte(self, nome):
        return any(p["name"] == nome for p in self._mapa_parts)

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
        carroc = self.M["carroceria"]
        self.carpete()
        self.tapetes()
        for s in (1, -1):
            self.banco_dianteiro(s)
        if carroc in ("hatch", "sedan", "jipe"):
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
        if carroc in ("furgao", "cabine_avancada"):
            self.area_de_carga()
        if carroc == "jipe":
            self.santantonio()

    @property
    def tun_h(self):
        """Altura do túnel central: tração dianteira baixo, traseira e 4x4 alto, cabine avançada sem túnel."""
        if self.M["carroceria"] == "cabine_avancada":
            return 0.0
        return {"dianteira": 0.13, "traseira": 0.17, "4x4": 0.20}.get(self.cfg["tracao"], 0.15)

    def x_particao(self):
        """Furgão: divisória atrás dos bancos da frente (fim da cabine, começo da carga)."""
        return self.M["x_encosto_d"] - 0.16

    def z_carpete(self, x, y):
        """Altura de cima do carpete em (x, y): túnel, degrau do banco de trás, rampa dos pés e subida da soleira."""
        M = self.M
        zp = M["z_piso"] + 0.012
        yi = M["W"] - 0.15
        ay = abs(y)
        z = zp
        if ay < 0.17 and self.tun_h > 0:
            z += self.tun_h * math.cos(ay / 0.17 * math.pi / 2) ** 1.5
        if M["carroceria"] in ("hatch", "sedan", "jipe"):
            x_degrau = M["x_encosto_t"] + 0.50
            if x < x_degrau:
                z += 0.10 * _limitar((x_degrau - x) / 0.06, 0, 1)
        xa = M["x_corta_fogo"] - 0.30
        if x > xa and M["carroceria"] != "cabine_avancada":
            z += 0.24 * ((x - xa) / max(0.05, M["x_corta_fogo"] - 0.01 - xa)) ** 1.4
        if ay > yi - 0.07:
            z += (M["z_saia"] - 0.02 - M["z_piso"]) * ((ay - (yi - 0.07)) / 0.07) ** 2
        return z

    def carpete(self):
        M = self.M
        p = self.nova("interior_carpete", "habitaculo")
        x0 = M["x_encosto_t"] - 0.14 if M["carroceria"] in ("hatch", "sedan", "jipe") else self.x_particao() - 0.02
        x1 = M["x_corta_fogo"] - 0.01
        yi = M["W"] - 0.15

        def ponto(u, v):
            x = x0 + (x1 - x0) * u
            y = -yi + 2 * yi * v
            return V(x, y, self.z_carpete(x, y) - 0.012)
        p.grade("carpete", 52, 34, ponto, 0.012, normal_fn=lambda u, v: (0, 0, 1))
        # acabamento da borda do carpete na soleira (friso de plástico)
        for s in (1, -1):
            pts = [V(x0 + (x1 - 0.3 - x0) * k / 10, s * (yi - 0.005), M["z_saia"] - 0.01) for k in range(11)]
            p.fita("plastico", pts, 0.035, 0.006, (0, s, 0.4))

    def tapetes(self):
        """Tapetes de borracha nos pés (o do motorista com o calcanhar gasto) e atrás."""
        M = self.M
        p = self.nova("interior_tapetes", "habitaculo", nota="tapetes de borracha soltos sobre o carpete")
        xs = M["x_corta_fogo"] - 0.30
        lugares = []
        for s in (1, -1):
            yc = s * M["y_banco"]
            lugares.append((M["x_encosto_d"] + 0.42, xs + 0.02, yc - 0.22, yc + 0.22, s > 0))
        if M["carroceria"] in ("hatch", "sedan", "jipe"):
            for s in (1, -1):
                yc = s * M["y_banco"]
                lugares.append((M["x_encosto_t"] + 0.56, M["x_encosto_d"] - 0.10, yc - 0.20, yc + 0.20, False))
        for (xa, xb, ya, yb, motorista) in lugares:
            if xb - xa < 0.15:
                continue
            nu, nv = 10, 6

            def ponto(u, v, xa=xa, xb=xb, ya=ya, yb=yb):
                x = xa + (xb - xa) * u
                y = ya + (yb - ya) * v
                return V(x, y, self.z_carpete(x, y) + 0.004)
            p.grade("tapete", nu, nv, ponto, 0.007, normal_fn=lambda u, v: (0, 0, 1))
            # frisos do tapete (nervuras transversais) e o calcanhar
            for k in range(1, 9):
                x = xa + (xb - xa) * k / 9
                y0, y1 = ya + 0.03, yb - 0.03
                z = max(self.z_carpete(x, y0), self.z_carpete(x, y1)) + 0.0095
                p.caixa("tapete", T(x, (y0 + y1) / 2, z), 0.008, y1 - y0, 0.004, 0.0015, 1)
            if motorista:
                xc = xb - 0.10
                yc = (ya + yb) / 2 + 0.04
                p.almofada("borracha", T(xc, yc, self.z_carpete(xc, yc) + 0.012), 0.16, 0.14, 0.006, 0.3, 0.3)

    # ---------------------------------------------------------------------------------------------------------------- bancos
    def _vivo(self, p, M0, sx, sy, z, e=0.3, r=0.0035, n=40, mat=None):
        """Vivo (cordão costurado na borda do estofado): tubo fino na volta de uma superelipse sx x sy, à altura z (local)."""
        pts = []
        for k in range(n + 1):
            u = -math.pi + 2 * math.pi * k / n
            pts.append(M0 @ V(sx / 2 * _se(math.cos(u), e), sy / 2 * _se(math.sin(u), e), z))
        p.tubo(mat or "plastico", pts, r, seg=6, sub=1, tampa=False)

    def _estofado(self, p, M0, larg, comp, esp, gasto=False):
        """Assento ou encosto estofado no plano XY local (X = comprimento, Y = largura, Z = espessura para cima)."""
        e = self.e
        vinil = e["banco"] == "vinil"
        mat1 = "vinil" if vinil else "banco"
        mat2 = "vinil_2" if vinil else ("listrado" if self.cfg["epoca"] == "80" else "banco_miolo")
        mat_gasto = mat1 + "_gasto" if gasto else mat1
        vivo = "vinil" if vinil else "plastico"
        # base estofada
        p.almofada(mat1, M0 @ T(0, 0, esp * 0.35), comp, larg, esp * 0.7, 0.25, 0.25)
        if e["abas_laterais"]:
            for s in (1, -1):
                p.almofada(mat_gasto if s > 0 else mat1, M0 @ T(0, s * (larg / 2 - 0.055), esp * 0.62), comp * 0.96, 0.12, esp * 0.62,
                           0.3, 0.35)
                # costura entre a aba e o miolo
                p.tubo(vivo, [M0 @ V(-comp * 0.46, s * (larg / 2 - 0.115), esp * 0.80), M0 @ V(comp * 0.46, s * (larg / 2 - 0.115),
                                                                                               esp * 0.80)], 0.003, seg=6, sub=1)
            n = max(1, e["gomos"])
            mio = larg - 0.20
            for k in range(n):
                cx = -comp / 2 + comp * (k + 0.5) / n
                p.almofada(mat2, M0 @ T(cx * 0.92, 0, esp * 0.55), comp * 0.92 / n - 0.008, mio, esp * 0.42, 0.22, 0.25)
                if k > 0:   # costura transversal entre gomos
                    xk = -comp / 2 + comp * k / n
                    p.tubo(vivo, [M0 @ V(xk * 0.92, -mio / 2, esp * 0.74), M0 @ V(xk * 0.92, mio / 2, esp * 0.74)], 0.0025, seg=6, sub=1)
        else:
            n = max(1, e["gomos"])
            for k in range(n):
                cy = -larg / 2 + 0.05 + (larg - 0.10) * (k + 0.5) / n
                m = mat2 if k % 2 else (mat_gasto if (gasto and k == n - 1) else mat1)
                p.almofada(m, M0 @ T(0, cy, esp * 0.62), comp * 0.94, (larg - 0.10) / n - 0.004, esp * 0.45, 0.3, 0.3)
        # vivo na volta de cima
        self._vivo(p, M0, comp * 0.995, larg * 0.995, esp * 0.62, 0.28, 0.0045, 48, vivo)

    def _encosto_cabeca(self, p, topo, h, y0=0.0, larg=0.26, alt=0.19, prof=0.10, mat=None):
        """Encosto de cabeça com as duas hastes cromadas e as guias de plástico no alto do encosto."""
        e = self.e
        mat = mat or ("vinil" if e["banco"] == "vinil" else "banco")
        Mh = topo @ T(0.005, y0, h + 0.05 + alt / 2)
        p.almofada(mat, Mh, prof, larg, alt, 0.3, 0.3)
        self._vivo(p, Mh @ Ry(math.pi / 2), alt * 0.99, larg * 0.99, 0.0, 0.3, 0.003, 36, "plastico")
        for dy in (-0.07, 0.07):
            a = topo @ V(-0.005, y0 + dy, h - 0.03)
            b = topo @ V(-0.005, y0 + dy, h + 0.07)
            p.tubo("cromado", [a, b], 0.0065, seg=10, sub=1)
            p.cilindro("plastico", topo @ T(-0.005, y0 + dy, h + 0.004), 0.011, 0.014, 12, 0.003)

    def banco_dianteiro(self, s):
        M, e = self.M, self.e
        lado = "esq" if s > 0 else "dir"
        p = self.nova(f"interior_banco_dianteiro_{lado}", "habitaculo")
        motorista = s > 0
        banco_inteirico = (not motorista) and M["carroceria"] == "cabine_avancada"
        larg = 0.50 if not banco_inteirico else min(0.92, 2 * M["meia_interna"] - 0.62)
        y = s * M["y_banco"] if not banco_inteirico else -(M["meia_interna"] - 0.05 - larg / 2)
        xb = M["x_encosto_d"]
        zs = M["z_assento"]
        comp = 0.50
        # trilhos (com a barra de ajuste na frente) e base
        for dy in (-0.17, 0.17):
            for k, dz in enumerate((0.0, 0.03)):
                p.caixa("aluminio" if k else "metal_preto", T(xb + 0.25, y + dy, M["z_piso"] + 0.02 + dz), 0.62 - 0.1 * k, 0.03, 0.022, 0.004)
            for xx in (xb - 0.04, xb + 0.54):
                p.cilindro("metal_preto", T(xx, y + dy, M["z_piso"] + 0.02), 0.009, 0.02, 6, 0.002)
        if not banco_inteirico:
            p.tubo("metal_preto", [(xb + 0.53, y - 0.15, M["z_piso"] + 0.06), (xb + 0.58, y - 0.08, M["z_piso"] + 0.07),
                                   (xb + 0.58, y + 0.08, M["z_piso"] + 0.07), (xb + 0.53, y + 0.15, M["z_piso"] + 0.06)], 0.006, seg=8)
        p.caixa("plastico", T(xb + 0.26, y, (M["z_piso"] + zs - 0.08) / 2 + 0.02), comp - 0.08, larg - 0.06,
                zs - 0.08 - M["z_piso"], 0.02)
        # assento, levemente inclinado (frente mais alta)
        Ms = T(xb + 0.28, y, zs - 0.07) @ Ry(-math.radians(6))
        self._estofado(p, Ms, larg, comp, 0.13, gasto=motorista)
        # encosto: articulado no fundo do assento, reclinado 17°
        h = 0.60
        Mb = T(xb + 0.02, y, zs - 0.03) @ Ry(math.radians(-17)) @ T(0, 0, h / 2) @ Ry(math.radians(90)) @ Rz(math.pi)
        self._estofado(p, Mb @ T(0, 0, -0.06), larg - 0.02, h, 0.12, gasto=motorista)
        # costas do encosto (plástico; vinil nos anos 70) com o bolso nas épocas novas
        topo = T(xb + 0.02, y, zs - 0.03) @ Ry(math.radians(-17))
        costas = "vinil" if e["banco"] == "vinil" else "plastico"
        p.caixa(costas, topo @ T(-0.065, 0, h / 2), 0.03, larg - 0.06, h - 0.04, 0.012)
        if self.cfg["epoca"] in ("90", "2000") and not banco_inteirico:
            p.caixa("plastico", topo @ T(-0.083, 0, h * 0.32), 0.012, larg - 0.14, 0.20, 0.006)
            p.caixa("plastico_liso", topo @ T(-0.088, 0, h * 0.32 + 0.10), 0.006, larg - 0.13, 0.012, 0.003)
        # encosto de cabeça com hastes (os anos 70 têm o encosto alto, sem o de cabeça separado só no banco inteiriço)
        if banco_inteirico:
            for yy in (-larg * 0.25, larg * 0.25):
                self._encosto_cabeca(p, topo, h, yy)
        else:
            self._encosto_cabeca(p, topo, h)
        # alavanca de reclinar e capa lateral (lado de fora)
        p.caixa("plastico", T(xb + 0.12, y + s * (larg / 2 + 0.01), zs - 0.10), 0.20, 0.02, 0.09, 0.008)
        p.almofada("plastico_liso", T(xb + 0.04, y + s * (larg / 2 + 0.03), zs - 0.06) @ Ry(math.radians(20)), 0.12, 0.022, 0.03, 0.3, 0.3)
        # fivela do cinto (lado de dentro): cabo de aço com capa, fivela com o botão vermelho
        yb = y - s * (larg / 2 + 0.015)
        p.tubo("cinto", [(xb + 0.05, yb, M["z_piso"] + 0.10), (xb + 0.08, yb, zs - 0.02)], 0.01, seg=6, sub=1)
        Mf = T(xb + 0.09, yb, zs + 0.035) @ Ry(math.radians(-20))
        p.almofada("plastico_liso", Mf, 0.035, 0.028, 0.08, 0.3, 0.3)
        p.caixa("vermelho", Mf @ T(0.012, 0, 0.022), 0.012, 0.022, 0.016, 0.003)
        p.caixa("metal_preto", Mf @ T(0, 0, 0.041), 0.022, 0.006, 0.004, 0.001)

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
                self._encosto_cabeca(p, topo, h, yy, 0.24, 0.15, 0.09)
        # trava do encosto rebatível (hatch) e as fivelas no vão do assento
        if self.cfg["carroceria"] in ("hatch", "jipe"):
            for s in (1, -1):
                p.caixa("vermelho" if self.cfg["epoca"] == "2000" else "plastico", topo @ T(0.0, s * (larg / 2 - 0.03), h - 0.02),
                        0.03, 0.025, 0.015, 0.004)
        for yy in (-0.30, -0.05, 0.05, 0.30):
            p.almofada("plastico_liso", T(xb + 0.06, yy, zs - 0.02) @ Ry(math.radians(-30)), 0.03, 0.025, 0.07, 0.3, 0.3)

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
        self.yd_painel = yd
        # perfil lateral (x, z) do painel: topo até o para-brisa, face, parte de baixo e corta-fogo
        if estilo == "chapa":
            # anos 70: rolo acolchoado no topo e chapa pintada na frente (aberto embaixo)
            pa = [(xf + 0.05, zt - 0.05), (xf + 0.05, zt + 0.004), (xp + 0.12, zt), (xp + 0.03, zt - 0.015), (xp, zt - 0.045),
                  (xp + 0.02, zt - 0.07), (xp + 0.10, zt - 0.07)]
            p.prisma("vinil", T(0, -yd, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), pa, 2 * yd, ch=0.012, seg=3)
            chapa = [(xp + 0.01, zt - 0.07), (xp + 0.04, zt - 0.07), (xp + 0.05, zt - 0.30), (xp + 0.02, zt - 0.30)]
            p.prisma("pintura_interna", T(0, -yd + 0.02, 0) @ Rx(math.pi / 2) @ S(1, 1, -1), chapa, 2 * yd - 0.04, ch=0.006)
            # friso cromado na chapa
            p.caixa("cromado", T(xp + 0.008, 0, zt - 0.075), 0.006, 2 * yd - 0.06, 0.008, 0.002)
            face_x = xp + 0.012
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
        self.face_painel = (face_x, zt - 0.12)
        yv = M["y_banco"]
        # grade do desembaçador no topo (frestas) junto ao para-brisa
        for yy in (-yd * 0.55, 0.0, yd * 0.55):
            p.caixa("plastico", T(xf - 0.01, yy, zt + 0.003), 0.07, 0.26, 0.006, 0.002)
            for k in range(7):
                p.caixa("metal_preto", T(xf - 0.01, yy - 0.11 + k * 0.0366, zt + 0.0065), 0.05, 0.012, 0.002, 0.0008, 1)
        # quadro de instrumentos
        mostr = e["mostradores"]
        if estilo == "chapa":
            zc = zt - 0.13
            r0 = mostr[0][0]
            p.revolucao("cromado", T(face_x + 0.002, yv, zc) @ Ry(-math.pi / 2), [(r0 + 0.014, 0), (r0 + 0.014, 0.010), (r0 + 0.006, 0.016),
                                                                                    (r0 - 0.002, 0.016), (r0 - 0.002, 0.004)], 48)
            p.disco_uv("instrumentos_velocimetro", T(face_x - 0.001, yv, zc) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), r0)
            self._ponteiro(p, face_x - 0.004, yv, zc, r0)
            r1 = mostr[1][0]
            for k, dy in enumerate((-0.14, 0.14)):
                p.revolucao("cromado", T(face_x + 0.002, yv + dy, zc + 0.01) @ Ry(-math.pi / 2),
                            [(r1 + 0.009, 0), (r1 + 0.009, 0.008), (r1 + 0.004, 0.012), (r1 - 0.002, 0.012), (r1 - 0.002, 0.004)], 32)
                nome = "instrumentos_combustivel" if k == 0 else "instrumentos_temperatura"
                p.disco_uv(nome, T(face_x - 0.001, yv + dy, zc + 0.01) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), r1)
                self._ponteiro(p, face_x - 0.004, yv + dy, zc + 0.01, r1, math.radians(120))
            # botões de puxar (luz, limpador, afogador) em fila embaixo dos mostradores
            for k in range(4):
                yy = yv - 0.15 + k * 0.10
                p.cilindro("cromado", T(face_x - 0.004, yy, zt - 0.235) @ Ry(math.pi / 2), 0.004, 0.012, 10, 0.001)
                p.revolucao("plastico_liso", T(face_x - 0.012, yy, zt - 0.235) @ Ry(-math.pi / 2),
                            [(0, 0), (0.012, 0), (0.013, 0.006), (0.011, 0.016), (0, 0.018)], 16)
        else:
            larg_q = 0.40 if len(mostr) > 2 else 0.32
            zc = zt - 0.02
            xs = face_x - 0.035
            # capuz em arco sobre o quadro, aberto para o motorista
            a, b, ee = larg_q / 2 + 0.03, 0.135, 0.022
            arco = [(a * math.cos(math.pi * k / 18), b * math.sin(math.pi * k / 18)) for k in range(19)]
            arco += [((a - ee) * math.cos(math.pi * k / 18), (b - ee) * math.sin(math.pi * k / 18)) for k in range(18, -1, -1)]
            p.prisma("plastico", T(face_x - 0.11, yv, zc - 0.07) @ Ry(math.pi / 2) @ Rz(math.pi / 2), arco, 0.13, ch=0.006, seg=2)
            # fundo do quadro, um pouco à frente da face do painel, com moldura chanfrada
            p.caixa("plastico_liso", T(face_x - 0.012, yv, zc - 0.005), 0.03, 2 * a - 0.02, 0.125, 0.006)
            if len(mostr) == 2:
                lugares = [(yv + 0.075, zc, mostr[0][0], "velocimetro"), (yv - 0.075, zc, mostr[1][0], "conta_giros")]
            else:
                lugares = [(yv + 0.07, zc, mostr[0][0], "velocimetro"), (yv - 0.07, zc, mostr[1][0], "conta_giros"),
                           (yv + 0.165, zc - 0.015, mostr[2][0], "combustivel"), (yv - 0.165, zc - 0.015, mostr[3][0], "temperatura")]
            for (yy, zz, rr, tipo) in lugares:
                p.revolucao("cromado" if self.cfg["epoca"] == "80" else "plastico_liso", T(xs + 0.006, yy, zz) @ Ry(-math.pi / 2),
                            [(rr + 0.007, 0), (rr + 0.007, 0.005), (rr + 0.003, 0.009), (rr - 0.001, 0.009), (rr - 0.001, 0.002)], 40)
                p.disco_uv("instrumentos_" + tipo, T(xs + 0.005, yy, zz) @ Ry(-math.pi / 2) @ Rz(math.pi / 2), rr)
                self._ponteiro(p, xs + 0.002, yy, zz, rr, math.radians(225) if tipo in ("velocimetro", "conta_giros") else math.radians(120))
            # interruptores dos dois lados do quadro (faróis, desembaçador, pisca-alerta)
            for k, dy in enumerate((-a - 0.035, a + 0.035)):
                Mi = T(face_x - 0.004, yv + dy, zc - 0.03)
                p.caixa("plastico_liso", Mi, 0.012, 0.035, 0.07, 0.004)
                for j in range(2):
                    p.caixa("plastico", Mi @ T(-0.007, 0, -0.018 + j * 0.036), 0.008, 0.026, 0.024, 0.003)
        # saídas de ar
        self._saidas(p, face_x, zt, yd)
        # centro: pisca-alerta, rádio, controles do ar, acendedor e cinzeiro
        zr = zt - (0.20 if estilo != "chapa" else 0.22)
        Mr = T(face_x + 0.006, 0, zr)
        p.caixa("plastico_liso", Mr, 0.012, 0.19, 0.06, 0.004)                       # frente do rádio (padrão DIN)
        p.caixa("metal_preto", Mr @ T(-0.007, 0, 0.012), 0.004, 0.11, 0.016, 0.002)  # janela do dial
        p.caixa("laranja" if self.cfg["epoca"] in ("70", "80") else "plastico", Mr @ T(-0.009, 0.01, 0.012), 0.002, 0.002, 0.012, 0.0005)
        if self.cfg["epoca"] in ("80", "90"):
            p.caixa("metal_preto", Mr @ T(-0.007, 0, -0.012), 0.004, 0.10, 0.012, 0.002)     # boca do toca-fitas
        for dy in (-0.075, 0.075):
            p.cilindro("plastico_liso", Mr @ T(-0.018, dy, 0.0) @ Ry(math.pi / 2), 0.012, 0.022, 20, 0.003)
            p.cilindro("cromado", Mr @ T(-0.030, dy, 0.0) @ Ry(math.pi / 2), 0.009, 0.004, 16, 0.001)
        for k in range(5):
            p.caixa("plastico", Mr @ T(-0.008, -0.04 + k * 0.02, -0.022), 0.008, 0.014, 0.008, 0.002)
        if estilo != "chapa":   # pisca-alerta: botão com o triângulo vermelho acima do rádio
            p.caixa("plastico_liso", T(face_x - 0.004, 0, zr + 0.055), 0.014, 0.034, 0.026, 0.005)
            p.prisma("vermelho", T(face_x - 0.012, 0, zr + 0.055) @ Ry(-math.pi / 2), [(-0.008, -0.006), (0.008, -0.006), (0.0, 0.008)],
                     0.003)
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
        # acendedor e cinzeiro
        zc3 = zc2 - 0.055
        p.caixa("plastico_liso", T(face_x + 0.004, -0.03, zc3), 0.01, 0.09, 0.035, 0.004)
        p.caixa("cromado", T(face_x - 0.002, -0.03, zc3 + 0.008), 0.003, 0.06, 0.004, 0.001)
        p.cilindro("cromado", T(face_x - 0.004, 0.05, zc3) @ Ry(math.pi / 2), 0.012, 0.01, 16, 0.002)
        p.cilindro("plastico", T(face_x - 0.010, 0.05, zc3) @ Ry(math.pi / 2), 0.010, 0.008, 16, 0.002)
        # porta-luvas (lado do passageiro): tampa com a fresta em volta e a fechadura
        yg = -M["y_banco"]
        if estilo == "chapa":
            p.caixa("pintura_interna", T(face_x + 0.03, yg, zt - 0.20), 0.008, 0.26, 0.12, 0.004)
            p.cilindro("cromado", T(face_x + 0.024, yg, zt - 0.15) @ Ry(math.pi / 2), 0.008, 0.01, 16, 0.002)
            p.disco_uv("alto_falante", T(xp + 0.10, 0, zt + 0.002), 0.06)
        else:
            p.caixa("metal_preto", T(face_x + 0.026, yg, zt - 0.215), 0.016, 0.305, 0.135, 0.004)       # fresta
            p.caixa("plastico", T(face_x + 0.020, yg, zt - 0.215), 0.022, 0.30, 0.13, 0.01)
            p.caixa("plastico_liso", T(face_x + 0.006, yg, zt - 0.165), 0.01, 0.06, 0.014, 0.003)
            p.cilindro("cromado", T(face_x + 0.004, yg + 0.05, zt - 0.165) @ Ry(math.pi / 2), 0.007, 0.006, 12, 0.001)
        # capa da coluna e o joelho do motorista
        if estilo != "chapa":
            p.almofada("plastico", T(face_x + 0.06, yv, zt - 0.30), 0.10, 0.36, 0.10, 0.4, 0.4)
            # alavanca de abrir o capô sob o painel
            p.caixa("plastico", T(face_x + 0.05, M["W"] - 0.22, zt - 0.34), 0.05, 0.04, 0.025, 0.006)

    def _quadro(self, p, mat, M0, w, h, borda, prof, ch=0.003):
        """Moldura retangular chanfrada no plano YZ local (X = profundidade): quatro réguas em volta de um vão w x h."""
        for s in (1, -1):
            p.caixa(mat, M0 @ T(0, s * (w - borda) / 2, 0), prof, borda, h, ch)
            p.caixa(mat, M0 @ T(0, 0, s * (h - borda) / 2), prof, w - 2 * borda + 0.002, borda, ch)

    def _ponteiro(self, p, x, y, z, r, a=math.radians(225)):
        """Ponteiro em repouso (no começo da escala) e o miolo."""
        p.caixa("laranja", T(x, y, z) @ Rx(a - math.pi / 2) @ T(0, 0, r * 0.38), 0.002, 0.004, r * 0.8, 0.0008, 1)
        p.cilindro("metal_preto", T(x, y, z) @ Ry(math.pi / 2), r * 0.12, 0.006, 16, 0.001)

    def _saidas(self, p, fx, zt, yd):
        e = self.e
        tipo = e["saidas"]
        lug = [(yd - 0.09, zt - 0.07), (-(yd - 0.09), zt - 0.07)]
        if self.e["painel"] != "chapa":
            lug += [(0.085, zt - 0.11), (-0.085, zt - 0.11)]
        if tipo == "fendas":
            # anos 70: grade lateral com aletas cromadas
            for (yy, zz) in lug:
                p.caixa("metal_preto", T(fx + 0.10, yy, zt + 0.003), 0.03, 0.12, 0.006, 0.002)
                p.cilindro("cromado", T(fx - 0.004, yy, zz - 0.02) @ Ry(math.pi / 2), 0.03, 0.01, 24, 0.003)
                p.cilindro("metal_preto", T(fx - 0.008, yy, zz - 0.02) @ Ry(math.pi / 2), 0.025, 0.006, 24, 0.002)
                for k in range(3):
                    p.caixa("cromado", T(fx - 0.012, yy, zz - 0.035 + k * 0.015), 0.003, 0.045, 0.003, 0.001, 1)
            return
        for (yy, zz) in lug:
            if tipo == "redondas":
                M0 = T(fx - 0.004, yy, zz) @ Ry(-math.pi / 2)
                p.toro("cromado", M0, 0.034, 0.006, 0.006, 32, 8)
                p.revolucao("metal_preto", M0 @ T(0, 0, 0.004), [(0.0, -0.02), (0.031, -0.02), (0.031, 0.004), (0, 0.004)], 28)
                for k in range(4):
                    p.caixa("plastico", M0 @ T(0, -0.021 + k * 0.014, 0.0), 0.058, 0.002, 0.012, 0.0008, 1)
                p.caixa("plastico_liso", M0 @ T(0.0, 0.0, 0.006), 0.012, 0.006, 0.01, 0.002)
            else:
                w, h = (0.11, 0.05)
                self._quadro(p, "plastico_liso", T(fx - 0.008, yy, zz), w + 0.024, h + 0.024, 0.012, 0.012)
                p.caixa("metal_preto", T(fx - 0.002, yy, zz), 0.006, w, h, 0.002)
                for k in range(4):
                    p.caixa("plastico", T(fx - 0.010, yy, zz - h / 2 + h * (k + 0.5) / 4) @ Ry(math.radians(15)), 0.014, w - 0.004,
                            0.003, 0.001, 1)
                p.caixa("plastico_liso", T(fx - 0.018, yy, zz), 0.008, 0.014, 0.008, 0.002)

    # ---------------------------------------------------------------------------------------------------------------- volante
    def volante(self):
        M, e = self.M, self.e
        p = self.nova("interior_volante", "habitaculo", nota="volante, coluna, alavancas de seta e limpador, chave")
        fx, fz = self.face_painel
        yv = M["y_banco"]
        incl = math.radians(24 if M["carroceria"] != "cabine_avancada" else 55)   # o plano do volante, inclinado da vertical
        dir_col = V(math.cos(incl), 0, -math.sin(incl))   # do volante para dentro do painel
        R = e["volante_raio"] * (1.12 if M["carroceria"] == "cabine_avancada" else 1.0)
        cvol = V(M["x_painel"] - 0.20, yv, M["z_cintura"] - (0.15 if e["painel"] == "chapa" else 0.10))
        Mv = T(*cvol) @ alinhar_z(-dir_col)          # Z local = para o motorista
        # coluna e capa
        fim = V(M["x_painel"] + 0.20, yv, cvol.z - 0.40 * math.tan(incl) - 0.02)
        p.tubo("metal_preto", [cvol + dir_col * 0.03, fim], 0.022, seg=16, sub=1)
        Mc = T(*(cvol + dir_col * 0.15)) @ alinhar_z(-dir_col)
        p.almofada("plastico", Mc, 0.13, 0.10, 0.20, 0.35, 0.35)
        # alavancas: seta à esquerda, limpador à direita (haste afinando e a ponta com anel)
        for s in (1, -1):
            a = Mc @ V(s * 0.05, 0.01, 0.03)
            b = Mc @ V(s * 0.17, -0.005, 0.04)
            p.tubo("plastico", [a, (a + b) / 2, b], 0.0065, seg=10, raios=[0.009, 0.0065, 0.0055])
            dirb = (b - a).normalized()
            p.cilindro("plastico_liso", T(*b) @ alinhar_z(dirb), 0.0075, 0.03, 12, 0.002)
            p.cilindro("cromado" if self.cfg["epoca"] in ("70", "80") else "plastico", T(*(b + dirb * 0.018)) @ alinhar_z(dirb), 0.0078,
                       0.004, 12, 0.001)
            p.caixa("plastico", Mc @ T(s * 0.05, 0.0, 0.03), 0.025, 0.03, 0.04, 0.006)
        # comutador de ignição com a chave e o chaveiro
        Mk = Mc @ T(-0.06, 0.0, -0.035) @ Ry(math.pi / 2)
        p.cilindro("cromado", Mk, 0.013, 0.02, 20, 0.003)
        p.cilindro("metal_preto", Mk @ T(0, 0, 0.011), 0.006, 0.004, 12, 0.001)
        p.caixa("aluminio", Mk @ T(0, 0, 0.022), 0.004, 0.009, 0.025, 0.001)
        p.almofada("plastico_liso", Mk @ T(0, 0, 0.045), 0.012, 0.03, 0.028, 0.3, 0.3)
        p.toro("cromado", Mk @ T(0, -0.022, 0.06) @ Rx(math.pi / 2), 0.012, 0.0015, 0.0015, 16, 6)
        p.tubo("aluminio", [Mk @ V(0, -0.03, 0.065), Mk @ V(0.01, -0.07, 0.04), Mk @ V(0.012, -0.08, 0.0)], 0.0025, seg=6)
        # aro (vinil gasto onde as mãos pegam: 10 e 2 horas)
        aro = "volante" if self.cfg["epoca"] != "70" else "vinil"
        tubo = e["volante_tubo"]
        p.toro(aro, Mv, R, tubo, tubo * 1.25, 72, 12, a0=math.radians(-40), a1=math.radians(220))
        p.toro(aro + "_gasto", Mv, R, tubo, tubo * 1.25, 30, 12, a0=math.radians(220), a1=math.radians(320))
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
            p.almofada("plastico", Mv @ T(0, 0.0, 0.05), 0.15, 0.15, 0.012, 0.25, 0.25)       # costura da bolsa (tampa)
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
        p = self.nova("interior_pedais", "habitaculo", nota="embreagem, freio e acelerador com as borrachas")
        yb = M["y_banco"]
        xp = M["x_painel"]
        zp = M["z_piso"]
        xs = M["x_corta_fogo"] - 0.12
        for k, (dy, alt) in enumerate(((0.11, 0.0), (-0.01, 0.0), (-0.13, 0.03))):
            y = yb + dy
            topo = V(xp + 0.18, y, M["z_painel"] - 0.20)
            pe = V(xs - 0.10, y, zp + 0.17 + alt)
            p.tubo("metal_preto", [topo, (topo + pe) / 2 + V(0.02, 0, 0), pe], 0.008, seg=8, raios=[0.010, 0.008, 0.007])
            larg = 0.05 if k == 2 else 0.075
            Mp = T(*pe) @ Ry(math.radians(-60))
            p.caixa("metal_preto", Mp @ T(0.005, 0, 0), 0.006, larg - 0.004, (0.07 if k != 2 else 0.11) - 0.004, 0.002)
            p.caixa("borracha", Mp @ T(-0.004, 0, 0), 0.010, larg, 0.07 if k != 2 else 0.11, 0.004)
            for r in range(5):
                p.caixa("borracha", Mp @ T(-0.010, 0, -0.028 + r * 0.014), 0.003, larg - 0.010, 0.004, 0.001, 1)
        # mola de retorno e o batente do freio (interruptor da luz de freio)
        p.helice("metal_preto", T(xp + 0.18, yb - 0.01, M["z_painel"] - 0.26) @ Ry(math.radians(70)), 0.006, 0.0012, 0.06, 8, 6)
        p.cilindro("plastico", T(xp + 0.20, yb - 0.01, M["z_painel"] - 0.17), 0.008, 0.03, 10, 0.002)
        # descanso do pé esquerdo
        p.caixa("borracha", T(xs - 0.02, yb + 0.25, zp + 0.10) @ Ry(math.radians(-45)), 0.015, 0.07, 0.16, 0.005)

    def cambio_freio_mao(self):
        M, e = self.M, self.e
        p = self.nova("interior_cambio", "habitaculo")
        xg = M["x_painel"] - (0.02 if e["cambio"] == "longo" else 0.06)
        zb = self.z_carpete(xg, 0.0) + (0.0 if e["console"] in ("nenhum", "curto") else 0.06)
        alt = {"longo": 0.36, "medio": 0.26, "curto": 0.20}[e["cambio"]]
        # coifa sanfonada
        perf = [(0.07, 0.0)]
        for k in range(1, 9):
            r = 0.065 - 0.045 * k / 9 + (0.006 if k % 2 else 0.0)
            perf.append((r, 0.012 * k))
        perf.append((0.012, 0.11))
        p.revolucao("borracha" if e["banco"] != "vinil" else "vinil", T(xg, 0, zb), perf, 28)
        p.prisma("plastico", T(xg, 0, zb - 0.002), _moldura(0.17, 0.15, 0.03, cantos=0.02), 0.014, ch=0.004, seg=2)
        top = V(xg - 0.05, 0, zb + alt)
        p.tubo("cromado" if self.cfg["epoca"] in ("70", "80") else "metal_preto", [(xg, 0, zb + 0.08), (xg - 0.02, 0, zb + alt * 0.6), top],
               0.007, seg=10)
        if self.cfg["epoca"] == "70":
            p.revolucao("plastico_liso", T(*top), [(0, -0.02), (0.022, -0.012), (0.026, 0.006), (0.018, 0.022), (0, 0.027)], 24)
        else:
            p.almofada("plastico", T(*top) @ T(0, 0, 0.02), 0.05, 0.045, 0.06, 0.35, 0.4)
            p.cilindro("plastico_liso", T(*top) @ T(0, 0, 0.052), 0.016, 0.003, 20, 0.001)
        if self.cfg["tracao"] == "4x4":    # alavanca da reduzida ao lado
            t2 = V(xg - 0.10, -0.07, zb + alt * 0.75)
            p.revolucao("borracha", T(xg - 0.06, -0.06, zb), [(0.04, 0.0), (0.032, 0.03), (0.035, 0.05), (0.01, 0.07)], 20)
            p.tubo("metal_preto", [(xg - 0.06, -0.06, zb + 0.04), t2], 0.006, seg=8, sub=1)
            p.revolucao("vermelho", T(*t2), [(0, -0.01), (0.017, -0.006), (0.018, 0.01), (0, 0.02)], 16)
        # freio de mão
        q = self.nova("interior_freio_mao", "habitaculo")
        xh = M["x_encosto_d"] + 0.24
        zh = self.z_carpete(xh, 0.0) + (0.07 if e["console"] in ("medio", "longo") else 0.01)
        q.caixa("plastico", T(xh, 0, zh), 0.18, 0.08, 0.02, 0.006)
        Ml = T(xh + 0.06, 0, zh + 0.02) @ Ry(math.radians(-20))
        q.caixa("metal_preto", Ml @ T(-0.11, 0, 0.015), 0.22, 0.022, 0.03, 0.006)
        q.almofada("plastico", Ml @ T(-0.20, 0, 0.022), 0.12, 0.034, 0.04, 0.35, 0.4)
        q.cilindro("cromado", Ml @ T(-0.268, 0, 0.022) @ Ry(math.pi / 2), 0.008, 0.012, 16, 0.002)
        q.revolucao("borracha", T(xh + 0.04, 0, zh + 0.008), [(0.03, 0.0), (0.024, 0.015), (0.026, 0.025), (0.012, 0.04)], 16)

    def console(self):
        M, e = self.M, self.e
        tipo = e["console"]
        p = self.nova("interior_console", "habitaculo")
        zb = self.z_carpete(M["x_painel"], 0.0)
        if tipo == "nenhum" or M["carroceria"] == "cabine_avancada":
            p.caixa("carpete", T(M["x_painel"] - 0.02, 0, zb + 0.005), 0.22, 0.20, 0.012, 0.004)
            return
        x1 = M["x_painel"] + 0.03
        x0 = {"curto": x1 - 0.30, "medio": M["x_encosto_d"] + 0.30, "longo": M["x_encosto_d"] + 0.02}[tipo]
        p.almofada("plastico", T((x0 + x1) / 2, 0, zb + 0.03), x1 - x0, 0.24, 0.10, 0.18, 0.18)
        if tipo == "longo":
            p.almofada("plastico", T(M["x_encosto_d"] + 0.12, 0, zb + 0.16), 0.30, 0.17, 0.10, 0.22, 0.3)
            p.almofada("vinil", T(M["x_encosto_d"] + 0.12, 0, zb + 0.212), 0.28, 0.15, 0.02, 0.22, 0.3)   # tampa estofada
            for k in range(2):
                p.revolucao("metal_preto", T(M["x_encosto_d"] + 0.42 + k * 0.09, 0, zb + 0.082),
                            [(0.0, -0.06), (0.036, -0.06), (0.037, 0.0), (0.0, 0.0)], 24)
        # moedeiro e interruptores no console (vidro elétrico de trás nos anos 2000)
        if tipo in ("medio", "longo"):
            p.caixa("metal_preto", T(x1 - 0.18, 0, zb + 0.081), 0.08, 0.10, 0.004, 0.002)
        # rampa até o painel
        p.almofada("plastico", T(x1 - 0.02, 0, (zb + M["z_painel"] - 0.28) / 2), 0.10, 0.22,
                   max(0.08, M["z_painel"] - 0.30 - zb), 0.25, 0.25)

    def cintos(self):
        M = self.M
        p = self.nova("interior_cintos", "habitaculo", nota="cintos de 3 pontos na frente (presilha, cadarço, lingueta, retrator e trilho nas de 2 portas)")
        for s in (1, -1):
            xb = M["coluna_b"] - 0.01
            zt = M["z_cintura"] + 0.30
            yt = self.lado_em(xb, zt, s, folga=0.03)
            ylow = self.lado_em(xb, M["z_piso"] + 0.12, s, folga=0.04)
            topo = V(xb, s * yt, zt)
            # presilha (anel em D) com o parafuso e a tampa, e o cinto descendo pela coluna até o retrator
            p.almofada("plastico", T(*topo) @ Rx(s * math.pi / 2), 0.05, 0.045, 0.018, 0.3, 0.3)
            p.cilindro("cromado", T(*topo) @ Rx(math.pi / 2), 0.009, 0.026, 12, 0.002)
            pts = [topo + V(0.0, -s * 0.014, -0.02), V(xb - 0.01, s * (yt - 0.012), M["z_cintura"]),
                   V(xb - 0.01, s * (ylow - 0.01), M["z_piso"] + 0.16)]
            p.fita("cinto", pts, 0.048, 0.003, (0, s, 0))
            p.caixa("plastico", T(xb - 0.01, s * (ylow - 0.02), M["z_piso"] + 0.10), 0.07, 0.05, 0.12, 0.012)
            # lingueta parada a meia altura (metal com a capa de plástico) e o botão que segura ela
            Ml = T(xb - 0.005, s * (yt - 0.03), M["z_cintura"] - 0.12)
            p.caixa("cromado", Ml @ T(0, 0, -0.022), 0.024, 0.004, 0.032, 0.002)
            p.almofada("plastico", Ml @ T(0, 0, 0.008), 0.05, 0.012, 0.03, 0.3, 0.3)
            p.cilindro("plastico", Ml @ T(0, 0, 0.04) @ Rx(math.pi / 2), 0.006, 0.012, 10, 0.002)
            # trilho do cinto (carros de 2 portas): barra de aço na soleira por onde a ponta de baixo corre
            if M["portas"] == 2 and M["carroceria"] != "cabine_avancada":
                xa = M["x_encosto_d"] - 0.25
                yy = self.lado_em(xa + 0.2, M["z_saia"] - 0.03, s, folga=0.06)
                p.tubo("cromado", [(xa, s * yy, M["z_saia"] - 0.03), (xb - 0.02, s * yy, M["z_saia"] - 0.03)], 0.007, seg=10, sub=1)
                for xx in (xa, xb - 0.02):
                    p.caixa("metal_preto", T(xx, s * (yy + 0.008), M["z_saia"] - 0.03), 0.02, 0.012, 0.03, 0.004)
                p.caixa("metal_preto", T(xa + 0.18, s * (yy - 0.004), M["z_saia"] - 0.03), 0.04, 0.012, 0.018, 0.003)
        # traseiros: subabdominais no assento
        if M["carroceria"] in ("hatch", "sedan", "jipe"):
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
            # vincos transversais leves do forro moldado
            z -= 0.003 * max(0.0, math.sin(x * 2 * math.pi / 0.30)) ** 8
            return V(x, y, z)
        p.grade("forro_teto", 40, 26, ponto, 0.01, normal_fn=lambda u, v: (0, 0, -1))
        self._lim_teto = (lim, y_max)
        # luz de teto
        xl = (x0 + x1) / 2 + 0.1
        zl = self.teto_em(xl, 0) - 0.02
        p.almofada("plastico_claro", T(xl, 0, zl), 0.13, 0.07, 0.025, 0.3, 0.3)
        p.almofada("lente", T(xl, 0, zl - 0.009), 0.09, 0.045, 0.012, 0.3, 0.3)
        p.caixa("plastico", T(xl + 0.055, 0, zl - 0.012), 0.012, 0.016, 0.008, 0.003)
        # alças de teto (lado do passageiro e de trás) com as tampas dos parafusos
        for (xx, s) in ((M["x_encosto_d"] + 0.15, -1), (M["x_encosto_t"] + 0.2, 1), (M["x_encosto_t"] + 0.2, -1)):
            yy = s * (min(ym, y_max(xx)) - 0.02)
            zz = self.teto_em(xx, yy) - 0.03
            p.tubo("plastico", [(xx - 0.1, yy, zz), (xx - 0.08, yy - s * 0.03, zz - 0.06), (xx + 0.08, yy - s * 0.03, zz - 0.06),
                                (xx + 0.1, yy, zz)], 0.011, seg=10)
            for dx in (-0.1, 0.1):
                p.almofada("plastico", T(xx + dx, yy, zz + 0.005), 0.03, 0.025, 0.02, 0.3, 0.3)

    def quebra_sois_retrovisor(self):
        M = self.M
        p = self.nova("interior_quebra_sois", "habitaculo")
        xf = M["x_teto_frente"] - 0.03
        for s in (1, -1):
            y = s * M["y_banco"]
            z = self.teto_em(xf - 0.12, y) - 0.03
            Ms = T(xf - 0.10, y, z) @ Ry(math.radians(8))
            mat = "forro_teto" if self.cfg["epoca"] != "70" else "vinil"
            p.almofada(mat, Ms, 0.16, 0.36, 0.022, 0.15, 0.2)
            self._vivo(p, Ms, 0.158, 0.358, 0.0, 0.15, 0.0025, 40, "plastico")
            p.tubo("plastico", [Ms @ V(0.06, s * 0.185, 0.0), Ms @ V(0.07, s * 0.21, 0.02)], 0.006, seg=8, sub=1)
            p.caixa("plastico", Ms @ T(0.07, -s * 0.17, 0.015), 0.03, 0.02, 0.02, 0.005)
            if s < 0 and self.cfg["epoca"] in ("90", "2000"):     # espelho de cortesia do passageiro
                p.caixa("plastico", Ms @ T(-0.01, 0, -0.012), 0.08, 0.14, 0.004, 0.002)
                p.caixa("espelho", Ms @ T(-0.01, 0, -0.0145), 0.06, 0.12, 0.002, 0.001)
        q = self.nova("interior_retrovisor", "habitaculo")
        z = self.teto_em(xf, 0) - 0.015
        q.caixa("plastico", T(xf - 0.01, 0, z), 0.06, 0.05, 0.02, 0.008)
        a, b = V(xf - 0.02, 0, z - 0.01), V(xf - 0.05, 0, z - 0.07)
        q.tubo("plastico", [a, b], 0.007, seg=8, sub=1)
        Mm = T(xf - 0.07, 0, z - 0.09) @ Ry(math.radians(-8))
        q.almofada("plastico", Mm, 0.035, 0.25, 0.07, 0.25, 0.3)
        q.almofada("espelho", Mm @ T(-0.012, 0, 0), 0.012, 0.23, 0.055, 0.2, 0.2)
        q.caixa("plastico_liso", Mm @ T(0.0, 0, -0.035), 0.02, 0.02, 0.012, 0.004)     # alavanca dia/noite

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
            if ("r" + lado) in portas or M["carroceria"] in ("furgao", "cabine_avancada"):
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

    # ---------------------------------------------------------------------------------------------------------------- carga
    def area_de_carga(self):
        """Furgão: divisória atrás dos bancos, piso de carga, laterais de chapa com nervuras, caixas de roda e ganchos."""
        M = self.M
        cab = M["carroceria"] == "cabine_avancada"
        xp = self.x_particao()
        ym = M["W"] - 0.17
        p = self.nova("interior_carga", "habitaculo", nota="área de carga do furgão")
        if cab:
            x_deck = M["x_tras"] + 0.80
            z_deck = M["z_piso"] + 0.30
            x0, zc = x_deck, M["z_piso"] + 0.012
            mat_piso = "madeira"
        else:
            x0, zc = M["x_tras"] + 0.16, M["z_mala"] + 0.012
            mat_piso = "tapete"
        # piso de carga (compensado com frisos de alumínio, ou manta de borracha nervurada)
        p.caixa(mat_piso, T((x0 + xp) / 2, 0, zc - 0.009), xp - x0, 2 * ym, 0.018, 0.004)
        n = max(3, int((2 * ym) / 0.12))
        for k in range(n + 1):
            y = -ym + 0.04 + (2 * ym - 0.08) * k / n
            p.caixa("aluminio" if cab else "tapete", T((x0 + xp) / 2, y, zc + 0.002), xp - x0 - 0.04, 0.018 if cab else 0.008,
                    0.004, 0.0015)
        # ganchos de amarração
        for xx in (x0 + 0.15, xp - 0.15):
            for s in (1, -1):
                Mg = T(xx, s * (ym - 0.06), zc + 0.004)
                p.caixa("metal_preto", Mg, 0.05, 0.03, 0.006, 0.002)
                p.toro("cromado", Mg @ T(0, 0, 0.018) @ Rx(math.pi / 2), 0.016, 0.004, 0.004, 20, 6)
        # deque do motor (cabine avançada: o motor fica sob o piso de trás)
        if cab:
            p.caixa("carpete", T((M["x_tras"] + 0.12 + x_deck) / 2, 0, z_deck), x_deck - M["x_tras"] - 0.12, 2 * ym, 0.02, 0.006)
            p.caixa("pintura_interna", T(x_deck, 0, (zc + z_deck) / 2), 0.015, 2 * ym, z_deck - zc, 0.005)
            p.caixa("aluminio", T(x_deck - 0.01, 0, z_deck + 0.012), 0.03, 2 * ym, 0.006, 0.002)
        # laterais: chapa pintada com nervuras estampadas, do piso à cintura
        for s in (1, -1):
            xa, xb = x0 + 0.02, xp - 0.02
            z0, z1 = zc, M["z_cintura"] + 0.02
            cache = {}

            def ponto(u, v, s=s, xa=xa, xb=xb, z0=z0, z1=z1, cache=cache):
                x = xa + (xb - xa) * u
                z = z0 + (z1 - z0) * v
                k = (round(x, 4), round(z, 4))
                if k not in cache:
                    cache[k] = min(self.lado_em(x, z, s, folga=0.015), M["W"] - 0.05)
                nerv = 0.008 * max(0.0, math.sin((x - xa) * 2 * math.pi / 0.22)) ** 6 * (1 if 0.12 < v < 0.9 else 0)
                return V(x, s * (cache[k] - nerv), z)
            p.grade("pintura_interna", 40, 10, ponto, 0.008, normal_fn=lambda u, v, s=s: (0, s, 0))
            # caixa de roda de trás por dentro
            xr = M["xt"]
            R = M["R"] + 0.07
            yw0 = M["y_pneu_dentro_t"] - 0.05
            if xa < xr < xb:
                def pr(u, v, s=s, xr=xr, R=R, yw0=yw0):
                    a = math.pi * u
                    return V(xr - R * math.cos(a), s * (yw0 + (M["W"] - 0.06 - yw0) * v), M["R"] + R * math.sin(a) * 0.9)
                p.grade("pintura_interna", 16, 3, pr, 0.01, normal_fn=lambda u, v: (-math.cos(math.pi * u), 0, math.sin(math.pi * u)))
                p.grade("pintura_interna", 16, 1, lambda u, v, s=s, xr=xr, R=R, yw0=yw0: V(xr - R * math.cos(math.pi * u), s * yw0,
                                                                                      zc + (M["R"] + R * 0.9 * math.sin(math.pi * u) - zc) * v),
                        0.01, normal_fn=lambda u, v, s=s: (0, -s, 0))
        # divisória atrás dos bancos
        q = self.nova("interior_divisoria", "habitaculo", nota="divisória entre a cabine e a carga")
        z0 = self.z_carpete(xp, 0.3)
        zt = self.teto_em(xp, 0.0) - 0.04
        yy = M["meia_interna"] - 0.02
        if cab:   # chapa até a cintura e grade em cima
            q.caixa("pintura_interna", T(xp, 0, (z0 + M["z_cintura"]) / 2), 0.012, 2 * yy, M["z_cintura"] - z0, 0.004)
            zb = M["z_cintura"]
        else:
            zb = z0
        q.tubo("metal_preto", [(xp, -yy, zb), (xp, -yy, zt - 0.05), (xp, -yy + 0.05, zt), (xp, yy - 0.05, zt), (xp, yy, zt - 0.05),
                               (xp, yy, zb)], 0.012, seg=10)
        q.tubo("metal_preto", [(xp, -yy, zb + 0.01), (xp, yy, zb + 0.01)], 0.010, seg=8, sub=1)
        nb = int(2 * yy / 0.07)
        for k in range(1, nb):
            y = -yy + 2 * yy * k / nb
            q.tubo("metal_preto", [(xp, y, zb + 0.01), (xp, y, zt - 0.005)], 0.0035, seg=6, sub=1)
        for z in (zb + (zt - zb) * 0.33, zb + (zt - zb) * 0.66):
            q.tubo("metal_preto", [(xp - 0.006, -yy, z), (xp - 0.006, yy, z)], 0.0035, seg=6, sub=1)
        # luz da carga
        xl = (x0 + xp) / 2
        q.almofada("plastico_claro", T(xl, 0, self.teto_em(xl, 0.0) - 0.02), 0.16, 0.06, 0.025, 0.3, 0.3)

    def santantonio(self):
        """Jipe: santo-antônio (arco de proteção) atrás dos bancos da frente, com as pernas até as caixas de roda de trás."""
        M = self.M
        p = self.nova("interior_santantonio", "habitaculo", nota="santo-antônio (arco de proteção) do jipe")
        x = M["x_encosto_d"] - 0.20
        yy = M["meia_interna"] - 0.05
        zf = self.z_carpete(x, yy - 0.05)
        zt = min(self.teto_em(x, 0.0), self.teto_em(x, yy - 0.15)) - 0.07
        r = 0.026
        arco = [(x, -yy, zf), (x, -yy, zt - 0.12), (x, -yy + 0.04, zt - 0.03), (x, -yy + 0.12, zt), (x, yy - 0.12, zt),
                (x, yy - 0.04, zt - 0.03), (x, yy, zt - 0.12), (x, yy, zf)]
        p.tubo("metal_preto", arco, r, seg=14, sub=4)
        p.tubo("metal_preto", [(x, -yy + 0.02, zf + 0.12), (x, yy - 0.10, zt - 0.02)], 0.02, seg=12, sub=1)    # diagonal
        for s in (1, -1):
            p.caixa("metal_preto", T(x, s * yy, zf + 0.004), 0.10, 0.08, 0.008, 0.003)
            for dx in (-0.03, 0.03):
                p.cilindro("cromado", T(x + dx, s * yy + s * 0.025, zf + 0.012), 0.008, 0.008, 6, 0.002)
            # perna de trás até a caixa de roda
            xb = M["xt"] - 0.05
            zb = M["R"] * 2 + 0.06
            p.tubo("metal_preto", [(x - 0.02, s * (yy - 0.02), zt - 0.10), (xb + 0.3, s * (yy - 0.02), zt - 0.25), (xb, s * (yy - 0.03), zb)],
                   0.022, seg=12)
            p.caixa("metal_preto", T(xb, s * (yy - 0.03), zb - 0.01), 0.10, 0.08, 0.008, 0.003)
        # espuma de proteção na travessa de cima
        p.tubo("borracha", [(x, -0.35, zt), (x, 0.35, zt)], 0.042, seg=16, sub=1)
        for yb in (-0.36, 0.36):
            p.cilindro("borracha", T(x, yb, zt) @ Rx(math.pi / 2), 0.044, 0.01, 16, 0.003)

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
        """
        Forro da porta com as proporções de um carro de verdade (medidas em carro_completo_dados.json, "medidas_reais"): capa de cima
        na linha da janela, painel moldado, miolo de tecido ou vinil com moldura chanfrada e vivo, apoio de braço a ~22 cm acima do
        assento, maçaneta em concha na frente, manivela, bolso embaixo, alto-falante de 6,5" e o refletor no canto de trás.
        Por baixo, a chapa interna (fica quando o forro solta).
        """
        M, e = self.M, self.e
        s = d["lado"]
        epoca = self.cfg["epoca"]
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
        # furos de dreno na borda de baixo
        for k in range(3):
            xx = x0 + L * (0.2 + 0.3 * k)
            c.cilindro("metal_preto", T(xx, s * (yin(xx, d["z0"]) - 0.04), d["z0"] + 0.0135), 0.007, 0.002, 10, 0.0005)
        # máquina do vidro: trilhos e cabo
        for xr in (x0 + 0.30 * L, x0 + 0.62 * L):
            c.caixa("aluminio", T(xr, s * (yin(xr, (z0 + z1) / 2) - 0.03), (z0 + z1) / 2 - 0.02), 0.025, 0.012, z1 - z0 - 0.12, 0.003)
        c.tubo("metal_preto", [(x0 + 0.30 * L, s * (yin(x0 + 0.3 * L, z0 + 0.1) - 0.035), z0 + 0.12),
                               (x0 + 0.46 * L, s * (yin(x0 + 0.46 * L, z0 + 0.2) - 0.04), (z0 + z1) / 2),
                               (x0 + 0.62 * L, s * (yin(x0 + 0.62 * L, z1 - 0.1) - 0.035), z1 - 0.10)], 0.003, seg=6)
        if e.get("vidro_eletrico"):
            xm_ = x0 + 0.46 * L
            c.cilindro("metal_preto", T(xm_, s * (yin(xm_, z0 + 0.15) - 0.04), z0 + 0.15) @ Rx(math.pi / 2), 0.04, 0.05, 20, 0.004)
        # fechadura na borda de trás e varetas
        c.caixa("metal_preto", T(d["x0"] + 0.035, s * (yin(x0, z1 - 0.15) - 0.04), z1 - 0.15), 0.05, 0.04, 0.09, 0.006)
        c.tubo("cromado", [(d["x0"] + 0.06, s * (yin(x0, z1 - 0.12) - 0.03), z1 - 0.12),
                           (x1 - 0.15, s * (yin(x1 - 0.15, z1 - 0.09) - 0.03), z1 - 0.09)], 0.0025, seg=6, sub=1)
        c.tubo("cromado", [(d["x0"] + 0.05, s * (yin(x0, z1 - 0.12) - 0.035), z1 - 0.12),
                           (d["x0"] + 0.06, s * (yin(x0, z1) - 0.035), z1 + 0.005)], 0.0022, seg=6, sub=1)
        # metades das dobradiças na borda da frente
        for zz in (d["z0"] + 0.12, z1 - 0.12):
            c.caixa("metal_preto", T(d["x1"] + 0.004, s * (yin(x1, zz) - 0.04), zz), 0.012, 0.05, 0.07, 0.004)
            c.cilindro("aluminio", T(d["x1"] + 0.012, s * (yin(x1, zz) - 0.07), zz), 0.009, 0.08, 16, 0.002)
        if e.get("alto_falante_porta"):
            xf, zf = x1 - 0.14, z0 + 0.15
            c.cilindro("metal_preto", T(xf, s * (yin(xf, zf) - 0.03), zf) @ Rx(math.pi / 2), 0.045, 0.04, 24, 0.004)

        # ------------------------------------------------------------------------------------------------------------ forro
        f = self.nova(f"door_card_{pos}", "porta", segue, "forro interno da porta")
        bas = "plastico" if epoca != "70" else "vinil"
        esp = 0.022
        recuo = 0.018

        def face(x, z):            # |y| da face do painel do forro
            return yin(x, z) - recuo - esp

        def ponto(u, v):
            x = x0 + L * u
            z = z0 + (z1 - z0) * v
            return V(x, s * (yin(x, z) - recuo), z)
        f.grade(bas, 24, 16, ponto, esp, normal_fn=lambda u, v: (0, s, 0))
        # parte de baixo em carpete (anos 80 e 90), com o friso que separa
        z_carp = z0 + 0.13
        if epoca in ("80", "90"):
            def pc(u, v):
                x = x0 + 0.01 + (L - 0.02) * u
                z = z0 + 0.01 + (z_carp - z0 - 0.01) * v
                return V(x, s * (face(x, z) - 0.002), z)
            f.grade("carpete", 16, 3, pc, 0.006, normal_fn=lambda u, v: (0, s, 0))
            f.fita("plastico", [V(x0 + L * k / 8, s * (face(x0 + L * k / 8, z_carp) - 0.006), z_carp) for k in range(9)], 0.012, 0.008,
                   (0, s, 0))
        # apoio de braço na altura certa: ~22 cm acima do assento (e nunca acima da capa de cima)
        z_braco = _limitar(M["z_assento"] + 0.22, z0 + 0.20, z1 - 0.12)
        # miolo de tecido (ou vinil plissado) entre o braço e a capa de cima, com moldura chanfrada e vivo
        mio = "vinil" if e["banco"] == "vinil" else ("listrado" if epoca == "80" else "banco_miolo")
        za, zb = z_braco + 0.035, z1 - 0.075
        xa, xb = x0 + 0.06, x1 - 0.07
        if zb > za + 0.05:
            def pm(u, v):
                x = xa + (xb - xa) * u
                z = za + (zb - za) * v
                bord = min(u * (xb - xa), (1 - u) * (xb - xa), v * (zb - za), (1 - v) * (zb - za))
                inch = 0.008 * min(1.0, bord / 0.03)
                if epoca == "70":    # vinil plissado: gomos horizontais de 4 cm
                    inch += 0.005 * abs(math.sin((z - za) * math.pi / 0.04))
                return V(x, s * (face(x, z) - inch), z)
            f.grade(mio, 30, 12 if epoca != "70" else 24, pm, 0.004, normal_fn=lambda u, v: (0, s, 0))
            # moldura: régua chanfrada em volta do miolo
            cont = [(xa, za), (xb, za), (xb, zb), (xa, zb), (xa, za)]
            for i in range(4):
                (pa, pb) = cont[i], cont[i + 1]
                n = max(2, int(math.hypot(pb[0] - pa[0], pb[1] - pa[1]) / 0.05))
                pts = [V(pa[0] + (pb[0] - pa[0]) * k / n, 0, pa[1] + (pb[1] - pa[1]) * k / n) for k in range(n + 1)]
                for q in pts:
                    q.y = s * (face(q.x, q.z) - 0.003)
                f.fita(bas, pts, 0.014, 0.009, (0, s, 0))
                pts2 = [V(q.x, s * (abs(q.y) - 0.006), q.z) for q in pts]
                f.tubo("plastico" if epoca != "70" else "cromado", pts2, 0.0022, seg=6, sub=1, tampa=False)
        # capa de cima (friso da cintura) com a borracha (escova) do vidro
        xt0, xt1 = x0 - 0.01, x1 + 0.01
        n = 10
        pts = [V(xt0 + (xt1 - xt0) * k / n, 0, z1 - 0.012) for k in range(n + 1)]
        for q in pts:
            q.y = s * (yin(q.x, q.z) - 0.035)
        f.fita(bas, pts, 0.055, 0.04, (0, 0, 1))
        pts2 = [V(q.x, s * (abs(q.y) + 0.014), z1 + 0.010) for q in pts]
        f.fita("borracha", pts2, 0.008, 0.014, (0, 0, 1))
        if epoca == "70":
            f.fita("cromado", [V(q.x, s * (abs(q.y) - 0.021), z1 - 0.03) for q in pts], 0.008, 0.003, (0, s, 0))
        # apoio de braço: perfil em L (tampo e face) puxado ao longo da porta, com o puxador
        xm = x0 + 0.44 * L
        Lb = min(0.36, 0.55 * L)
        yb_ = face(xm, z_braco)
        perfil = [(0.0, 0.0), (0.075, 0.0), (0.085, -0.012), (0.08, -0.05), (0.03, -0.09), (0.0, -0.10)]
        # o prisma é feito no plano XY local: X local = para dentro do carro, Y local = altura, Z local = ao longo da porta
        Mb = T(xm - Lb / 2, s * yb_, z_braco) @ _base(V(0, -s, 0), V(0, 0, 1), V(1, 0, 0))
        f.prisma(mio if e["banco"] == "vinil" else bas, Mb, perfil, Lb, ch=0.008, seg=3)
        if epoca in ("80", "90", "2000"):
            # puxador: alça fechada em cima do apoio (80/90) ou concha no tampo (2000)
            if epoca == "2000":
                f.almofada("metal_preto", T(xm + Lb * 0.25, s * (yb_ - 0.045), z_braco + 0.002), 0.09, 0.04, 0.012, 0.3, 0.3)
            else:
                f.tubo(bas, [(xm - 0.08, s * (yb_ - 0.01), z_braco - 0.005), (xm - 0.06, s * (yb_ - 0.07), z_braco + 0.06),
                             (xm + 0.08, s * (yb_ - 0.07), z_braco + 0.06), (xm + 0.10, s * (yb_ - 0.01), z_braco - 0.005)], 0.011, seg=10)
        if e.get("vidro_eletrico"):
            for k in range(2 if pos[0] == "f" else 1):
                xs_ = xm + Lb * 0.36 - k * 0.04
                f.caixa("plastico", T(xs_, s * (yb_ - 0.05), z_braco + 0.004), 0.034, 0.03, 0.006, 0.002)
                f.caixa("plastico_liso", T(xs_, s * (yb_ - 0.05), z_braco + 0.010), 0.024, 0.018, 0.008, 0.003)
        # maçaneta interna em concha (na frente) com a alavanca
        xh, zh = x1 - 0.17, z1 - 0.085
        yh = face(xh, zh)
        f.almofada("plastico_liso", T(xh, s * (yh - 0.004), zh), 0.13, 0.012, 0.05, 0.25, 0.25)
        f.almofada("metal_preto", T(xh, s * (yh - 0.006), zh), 0.10, 0.008, 0.032, 0.25, 0.25)
        f.caixa("cromado" if epoca in ("70", "80") else "plastico_liso", T(xh + 0.005, s * (yh - 0.013), zh), 0.085, 0.01, 0.018, 0.004)
        # bolso de baixo (porta-garrafa nos anos 2000)
        xb0, xb1 = x0 + 0.06, x1 - (0.27 if e.get("alto_falante_porta") else 0.08)
        if xb1 - xb0 > 0.15:
            zb0, zb1 = z0 + 0.02, z0 + 0.15
            xc = (xb0 + xb1) / 2
            yb2 = face(xc, zb0)
            yy, w = 0.065, 0.012
            f.caixa(bas, T(xc, s * (yb2 - yy), (zb0 + zb1) / 2), xb1 - xb0, w, zb1 - zb0, 0.005)
            f.caixa(bas, T(xc, s * (yb2 - yy / 2), zb0 + 0.006), xb1 - xb0, yy, 0.012, 0.004)
            for xx in (xb0, xb1):
                f.caixa(bas, T(xx, s * (yb2 - yy / 2), (zb0 + zb1) / 2), 0.012, yy, zb1 - zb0, 0.004)
            f.fita(bas, [V(xb0, s * (yb2 - yy - 0.006), zb1), V(xb1, s * (yb2 - yy - 0.006), zb1)], 0.016, 0.01, (0, s, 0))
            if epoca == "2000":
                f.cilindro(bas, T(xb1 - 0.05, s * (yb2 - 0.04), zb0 + 0.06), 0.04, 0.10, 24, 0.004)
        # alto-falante de 6,5" com grade e moldura
        if e.get("alto_falante_porta"):
            xf, zf = x1 - 0.14, z0 + 0.15
            yf = face(xf, zf)
            Mf = T(xf, s * (yf - 0.002), zf) @ Rx(s * math.pi / 2)
            f.toro("plastico", Mf, 0.085, 0.009, 0.006, 40, 8)
            f.disco_uv("alto_falante", Mf @ T(0, 0, 0.002), 0.08)
        # manivela
        if e.get("manivela"):
            xm2, zm2 = x0 + 0.62 * L, min(z1 - 0.13, z_braco + 0.10)
            ym = face(xm2, zm2)
            Mr = T(xm2, s * ym, zm2) @ Rx(s * math.pi / 2)
            f.revolucao("plastico_liso", Mr, [(0, 0), (0.03, 0), (0.028, 0.006), (0.012, 0.012), (0, 0.014)], 24)
            braco = [Mr @ V(0, 0, 0.012), Mr @ V(0.05, -0.04, 0.02), Mr @ V(0.085, -0.07, 0.022)]
            f.tubo("cromado", braco, 0.006, seg=8)
            f.revolucao("plastico_liso", T(*braco[-1]) @ alinhar_z(Mr.to_3x3() @ V(0, 0, 1)),
                        [(0, 0), (0.011, 0.002), (0.012, 0.03), (0.009, 0.04), (0, 0.042)], 16)
        # pino da trava
        if e.get("pino_trava"):
            xp_ = x0 + 0.06
            f.revolucao("cromado" if epoca == "70" else "plastico_liso", T(xp_, s * (yin(xp_, z1) - 0.04), z1 + 0.01),
                        [(0, 0), (0.0045, 0), (0.0045, 0.035), (0.0055, 0.04), (0.0035, 0.046), (0, 0.047)], 12)
        # refletor vermelho no canto de baixo de trás (anos 80 em diante)
        if epoca != "70":
            xr_, zr_ = x0 + 0.04, z0 + 0.03
            f.caixa("vermelho", T(xr_, s * (face(xr_, zr_) - 0.003), zr_), 0.05, 0.006, 0.02, 0.003)

    def vao_porta(self, pos, d):
        """Soleira, colunas por dentro, teto da porta, borracha, dobradiças, limitador, interruptor da luz e batente (ficam quando a porta sai)."""
        M = self.M
        s = d["lado"]
        x0, x1 = d["x0"], d["x1"]
        zs = M["z_saia"]
        zc = min(d["z1"], M["z_cintura"])
        zj = d["z_janela"] + 0.01
        frente = pos[0] == "f"
        incl = M["inclinacao_para_brisa"] * 0.85
        if frente and M["carroceria"] != "cabine_avancada":
            xa_top = _limitar(x1 - incl * (zj - zc), d["x_vidro"][0] + 0.25, x1 - 0.04)
            xb_top = x0
        else:
            xa_top = x1
            xb_top = x0 + (0.08 if not frente else 0.0)
        g = f"jamb_{pos}"
        W = M["W"]
        # soleira: caixa pintada, a borracha-friso de pisar e o friso de alumínio (anos 70)
        p = self.nova(f"{g}_soleira", "vao_porta")
        ys = self.lado_em((x0 + x1) / 2, zs - 0.05, s, folga=0.0)
        ys = min(ys, W - 0.005)
        p.caixa("pintura_interna", T((x0 + x1) / 2, s * (ys - 0.05), zs - 0.045), x1 - x0 + 0.02, 0.10, 0.09, 0.012)
        p.caixa("plastico", T((x0 + x1) / 2 - 0.02, s * (ys - 0.112), zs - 0.035), x1 - x0 + 0.06, 0.03, 0.11, 0.01)
        p.caixa("plastico" if self.cfg["epoca"] != "70" else "aluminio", T((x0 + x1) / 2, s * (ys - 0.075), zs + 0.004),
                x1 - x0 - 0.04, 0.10, 0.008, 0.004)
        for k in range(8):
            p.caixa("borracha", T(x0 + 0.06 + (x1 - x0 - 0.12) * k / 7, s * (ys - 0.075), zs + 0.009), 0.010, 0.08, 0.003, 0.001, 1)
        for xx in (x0 + 0.05, x1 - 0.05):
            p.cilindro("cromado", T(xx, s * (ys - 0.075), zs + 0.009), 0.005, 0.003, 10, 0.001)
        # coluna da frente (A ou B) e de trás (B ou C), pintadas por dentro, com a parte inclinada acima da cintura
        q = self.nova(f"{g}_colunas", "vao_porta")
        prof = 0.13
        for (xx, sinal) in ((x1 + 0.006, 1), (x0 - 0.006, -1)):
            yy = self.lado_em(xx + sinal * 0.02, (zs + zc) / 2, s, folga=0.0)
            yy = min(yy, W - 0.005)
            q.caixa("pintura_interna", T(xx, s * (yy - prof / 2), (zs + zc) / 2), 0.012, prof, zc - zs, 0.004)
            # furos de serviço na coluna (tampados com borracha)
            for zz in ((zs + zc) / 2 - 0.08, (zs + zc) / 2 + 0.10):
                q.cilindro("borracha", T(xx - sinal * 0.007, s * (yy - prof / 2), zz) @ Ry(math.pi / 2), 0.011, 0.004, 12, 0.001)
        ya = min(self.lado_em(x1, zc + 0.05, s), W - 0.02)
        a, b = V(x1 + 0.006, s * (ya - 0.05), zc), V(xa_top + 0.006, s * (min(self.y_janela(xa_top, zj - 0.03, s, pos), W - 0.06) - 0.05), zj)
        q.fita("pintura_interna", [a, b], 0.10, 0.012, (1, 0, -incl * 0.5) if (frente and M["carroceria"] != "cabine_avancada") else (1, 0, 0))
        a2 = V(x0 - 0.006, s * (min(self.lado_em(x0, zc, s), W - 0.02) - 0.05), zc)
        b2 = V(xb_top - 0.006, s * (min(self.y_janela(xb_top, zj - 0.03, s, pos), W - 0.06) - 0.05), zj)
        q.fita("pintura_interna", [a2, b2], 0.10, 0.012, (1, 0, 0))
        topo = [V(xb_top + (xa_top - xb_top) * k / 6, 0, zj + 0.008) for k in range(7)]
        for t in topo:
            t.y = s * (min(self.y_janela(t.x, zj - 0.03, s, pos), W - 0.06) - 0.04)
        q.fita("pintura_interna", topo, 0.09, 0.012, (0, 0, 1))
        # interruptor da luz de cortesia na coluna de trás
        zi = zs + 0.25
        yi = min(self.lado_em(x0 - 0.02, zi, s), W - 0.02) - 0.06
        q.cilindro("plastico", T(x0 - 0.012, s * yi, zi) @ Ry(math.pi / 2), 0.011, 0.006, 14, 0.002)
        q.cilindro("borracha", T(x0 - 0.018, s * yi, zi) @ Ry(math.pi / 2), 0.006, 0.012, 12, 0.002)
        # borracha de vedação em volta do vão
        r = self.nova(f"{g}_borracha", "vao_porta")
        contorno = [V(x0 + 0.02, 0, zs + 0.02), V(x1 - 0.02, 0, zs + 0.02), V(x1 - 0.015, 0, zc),
                    V(xa_top - 0.01, 0, zj - 0.01), V(xb_top + 0.02, 0, zj - 0.01), V(x0 + 0.015, 0, zc), V(x0 + 0.02, 0, zs + 0.02)]
        dens = []
        for i in range(len(contorno) - 1):
            a, b = contorno[i], contorno[i + 1]
            n = max(2, int((b - a).length / 0.04))
            for k in range(n):
                dens.append(a.lerp(b, k / n))
        dens.append(contorno[-1])
        for t in dens:
            if t.z > zc + 0.01:
                t.y = s * (min(self.y_janela(t.x, t.z, s, pos), W - 0.01) - 0.03)
            else:
                t.y = s * (min(self.lado_em(t.x, t.z, s), W - 0.01) - 0.035)
        r.tubo("borracha", dens, 0.011, seg=10, sub=1, tampa=False)
        # dobradiças (na coluna da frente do vão), limitador com o braço e batente (na coluna de trás)
        h = self.nova(f"{g}_dobradicas", "vao_porta")
        for zz in (zs + 0.12, zc - 0.12):
            yy = min(self.lado_em(x1, zz, s), W - 0.01) - 0.035
            h.caixa("metal_preto", T(x1 + 0.012, s * yy, zz), 0.012, 0.05, 0.075, 0.004)
            h.cilindro("aluminio", T(x1 + 0.004, s * (yy + 0.012), zz), 0.009, 0.085, 16, 0.002)
            h.caixa("metal_preto", T(x1 + 0.004, s * (yy + 0.03), zz), 0.03, 0.012, 0.06, 0.003)
            for dz in (-0.022, 0.022):
                h.cilindro("cromado", T(x1 + 0.019, s * yy, zz + dz) @ Ry(math.pi / 2), 0.007, 0.006, 6, 0.001)
        zl = (zs + zc) / 2
        yy = min(self.lado_em(x1, zl, s), W - 0.01) - 0.05
        h.caixa("metal_preto", T(x1 - 0.02, s * yy, zl), 0.06, 0.018, 0.022, 0.005)
        h.caixa("metal_preto", T(x1 + 0.010, s * yy, zl), 0.02, 0.03, 0.04, 0.004)
        # chicote passando da coluna para a porta (sanfona de borracha) quando há vidro elétrico
        if self.e.get("vidro_eletrico"):
            za_ = zl + 0.10
            ya_ = min(self.lado_em(x1, za_, s), W - 0.01) - 0.06
            perf = [(0.014 + 0.004 * (k % 2), 0.008 * k) for k in range(10)]
            h.revolucao("borracha", T(x1 + 0.01, s * ya_, za_) @ Ry(-math.pi / 2), perf, 12)
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
        carroc = M["carroceria"]
        if M["motor_traseiro"]:
            if carroc != "cabine_avancada":
                self.porta_malas_frente()
            else:
                self._lanternas_dentro()
                self._estepe_carga()
            return
        if carroc == "furgao":
            self._lanternas_dentro()
            if self.cfg["estepe"] not in ("vao_motor", "externo"):
                self._estepe_carga()
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
        p.grade("carpete", 40, 30, ponto, 0.012, normal_fn=lambda u, v: (0, 0, 1))
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
        # macaco e chave de roda presos na lateral
        Mj = T(x0 + 0.35, ym - 0.04, zm + 0.10)
        p.caixa("metal_preto", Mj, 0.26, 0.05, 0.03, 0.006)
        p.tubo("metal_preto", [Mj @ V(-0.12, 0, 0.02), Mj @ V(0, 0, 0.08), Mj @ V(0.12, 0, 0.02)], 0.01, seg=8)
        p.tubo("ferro", [Mj @ V(-0.15, -0.03, 0.10), Mj @ V(0.12, -0.03, 0.12)], 0.009, seg=8, sub=1)
        # estepe (no vão do motor ou por fora, nos carros assim, ele não fica aqui)
        if estepe in ("vao_motor", "externo"):
            poco = False
        e = self.nova("interior_portamalas_estepe", "porta_malas") if estepe not in ("vao_motor", "externo") else Peca("_descarte", "x")
        if poco:
            Me = T(cx_e, 0, zm - 0.17 + 0.09)
        elif estepe == "lateral":
            Me = T(x0 + Rs + 0.15, ym - 0.12, zm + Rs + 0.02) @ Rx(math.pi / 2)
        else:
            Me = T(cx_e, 0, zm + 0.10)
        self._roda_estepe(e, Me, Rs)
        if estepe == "lateral":
            e.fita("borracha", [Me @ V(0, Rs + 0.02, -0.06), Me @ V(0, Rs + 0.02, 0.1), Me @ V(0.0, 0.0, 0.1)], 0.03, 0.004, (1, 0, 0))
        else:
            e.cilindro("metal_preto", Me @ T(0, 0, 0.06), 0.03, 0.02, 6, 0.004)     # borboleta que prende
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

    def _estepe_carga(self):
        """Estepe em pé na área de carga, preso na divisória (furgão)."""
        M = self.M
        e = self.nova("interior_portamalas_estepe", "porta_malas")
        Rs = M["R"] * 0.96
        x = self.x_particao() - 0.12
        y = -(M["meia_interna"] - 0.18)
        z = (M["z_mala"] if M["carroceria"] == "furgao" else M["z_piso"]) + Rs + 0.02
        Me = T(x, y, z) @ Ry(math.pi / 2)
        self._roda_estepe(e, Me, Rs)
        e.fita("borracha", [Me @ V(-Rs - 0.02, 0.0, 0.10), Me @ V(0.0, 0.0, 0.10), Me @ V(Rs + 0.02, 0.0, 0.10)], 0.03, 0.004, (1, 0, 0))

    def _roda_estepe(self, p, Me, R):
        """Estepe: pneu com a banda e roda de aço com os furos (deitado no Z local)."""
        lr = 0.165 * R / 0.29
        L = 0.17 * R / 0.29
        perfil = [(R * 0.62, -L / 2), (R * 0.80, -L / 2 - 0.01), (R * 0.95, -L / 2 + 0.005), (R, -L / 2 + 0.03), (R, L / 2 - 0.03),
                  (R * 0.95, L / 2 - 0.005), (R * 0.80, L / 2 + 0.01), (R * 0.62, L / 2)]
        perfil = perfil + [(R * 0.62, -L / 2)]
        p.revolucao("borracha", Me, perfil, 64)
        for k in range(36):     # sulcos da banda
            a = 2 * math.pi * k / 36
            p.caixa("borracha", Me @ Rz(a) @ T(R + 0.002, 0, 0), 0.006, 0.02, L - 0.07, 0.002, 1)
        p.revolucao("metal_preto", Me, [(R * 0.63, -L / 2 + 0.01), (lr, -L / 2 + 0.02), (lr * 0.9, -0.01), (lr * 0.55, 0.0),
                                        (lr * 0.35, 0.02), (0.03, 0.025), (0, 0.025)], 48)
        for k in range(4):
            a = 2 * math.pi * k / 4
            p.cilindro("cromado", Me @ T(0.05 * math.cos(a), 0.05 * math.sin(a), 0.028), 0.009, 0.012, 6, 0.002)
            b = a + math.pi / 4
            p.cilindro("fio", Me @ T(lr * 0.72 * math.cos(b), lr * 0.72 * math.sin(b), 0.001), 0.016, 0.004, 12, 0.001)

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
            p.tubo("chicote", [(xc + 0.08, yc, zc), (xc + 0.15, yc * 0.92, zc + 0.05), (xc + 0.35, yc * 0.85, zc + 0.08)], 0.005, seg=6)

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
            self._soldas(p, V(x0 + 0.05, s * (yb - 0.008), zf + 0.395), V(x1 - 0.05, s * (yb - 0.008), zf + 0.395), (0, -s, 0))
        p.caixa("pintura_interna", T(x0, 0, (zf + M["z_capo_tras"]) / 2), 0.015, 2 * yb, M["z_capo_tras"] - zf, 0.006)
        e = self.nova("interior_portamalas_estepe", "porta_malas")
        Rs = M["R"] * 0.96
        Me = T(x1 - 0.12, 0, zf + Rs * 0.85) @ Ry(math.radians(-62))
        self._roda_estepe(e, Me, Rs)
        t = self.nova("under_tanque", "embaixo", nota="tanque na frente (motor traseiro)")
        t.almofada("metal_preto", T(x0 + 0.20, 0, zf + 0.18), 0.32, 2 * yb - 0.15, 0.30, 0.15, 0.2)
        for dx in (-0.08, 0.08):
            t.fita("metal_preto", [(x0 + 0.20 + dx, -yb + 0.1, zf + 0.34), (x0 + 0.20 + dx, yb - 0.1, zf + 0.34)], 0.025, 0.003, (0, 0, 1))
        t.tubo("metal_preto", [(x0 + 0.20, 0.18, zf + 0.33), (x0 + 0.24, 0.30, zf + 0.42), (x0 + 0.30, 0.35, M["z_capo_tras"] - 0.04)],
               0.022, seg=12)
        t.cilindro("metal_preto", T(x0 + 0.30, 0.35, M["z_capo_tras"] - 0.04), 0.04, 0.03, 20, 0.006)
        t.tubo("borracha", [(x0 + 0.05, -0.15, zf + 0.10), (x0 - 0.02, -0.15, zf + 0.02)], 0.005, seg=6, sub=1)
        r = self.nova("engine_reservatorios", "motor", nota="reservatórios do freio e do limpador no porta-malas da frente")
        r.almofada("reservatorio", T(x0 + 0.06, 0.32, zf + 0.30), 0.08, 0.10, 0.12, 0.25, 0.3)
        r.cilindro("amarelo", T(x0 + 0.06, 0.32, zf + 0.37), 0.022, 0.025, 16, 0.004)
        r.tubo("borracha", [(x0 + 0.06, 0.32, zf + 0.24), (x0 + 0.02, 0.30, zf + 0.10), (x0 - 0.01, 0.30, zf + 0.05)], 0.004, seg=6)
        r.almofada("reservatorio", T(x0 + 0.08, -0.30, zf + 0.15), 0.12, 0.10, 0.22, 0.25, 0.3)
        r.cilindro("azul", T(x0 + 0.08, -0.30, zf + 0.27), 0.02, 0.03, 16, 0.004)
        self._lanternas_dentro()

    # ================================================================================================================ MOTOR
    def _abracadeira(self, p, ponto, direcao, r):
        """Abraçadeira de mangueira: fita de aço em volta e o parafuso de aperto."""
        Mz = T(*ponto) @ alinhar_z(direcao)
        p.toro("aluminio", Mz, r + 0.002, 0.0025, 0.0015, 20, 4)
        p.caixa("aluminio", Mz @ T(r + 0.006, 0, 0), 0.008, 0.01, 0.006, 0.002)
        p.cilindro("aluminio", Mz @ T(r + 0.006, 0.0, 0.0) @ Rx(math.pi / 2), 0.003, 0.02, 8, 0.0008)

    def _mangueira(self, p, pts, r, mat="borracha", abracadeiras=True):
        p.tubo(mat, pts, r, seg=14)
        if abracadeiras:
            from mathutils import Vector
            P = [Vector(q) for q in pts]
            self._abracadeira(p, P[0] + (P[1] - P[0]).normalized() * 0.02, P[1] - P[0], r)
            self._abracadeira(p, P[-1] + (P[-2] - P[-1]).normalized() * 0.02, P[-1] - P[-2], r)

    def _chicote(self, p, pts, r=0.009, clipes=0.14):
        """Chicote elétrico: conduíte corrugado (anéis a cada 8 mm), com presilhas de plástico ao longo do caminho."""
        from mathutils import Vector
        P = [Vector(q) for q in pts]
        L = sum((P[i + 1] - P[i]).length for i in range(len(P) - 1))
        n = max(4, int(L / 0.008))
        # reamostra a polilinha com passo uniforme
        Q = []
        seg_l = [(P[i + 1] - P[i]).length for i in range(len(P) - 1)]
        for k in range(n + 1):
            t = L * k / n
            i = 0
            while i < len(seg_l) - 1 and t > seg_l[i]:
                t -= seg_l[i]
                i += 1
            Q.append(P[i].lerp(P[i + 1], min(1.0, t / max(1e-6, seg_l[i]))))
        raios = [r if k % 2 else r * 0.86 for k in range(len(Q))]
        p.tubo("chicote", Q, r, seg=8, sub=1, raios=raios)
        nc = max(1, int(L / clipes))
        for k in range(1, nc):
            q = Q[int(len(Q) * k / nc)]
            d = Q[min(len(Q) - 1, int(len(Q) * k / nc) + 1)] - q
            Mz = T(*q) @ alinhar_z(d)
            p.toro("plastico", Mz, r + 0.0015, 0.0015, 0.0025, 12, 4)
            p.caixa("plastico", Mz @ T(r + 0.004, 0, 0), 0.008, 0.012, 0.010, 0.002)

    def _soldas(self, p, a, b, normal, passo=0.035, mat="pintura_interna"):
        """Pontos de solda numa aba (de a até b): discos rasos virados para 'normal'."""
        from mathutils import Vector
        a, b = Vector(a), Vector(b)
        n = max(1, int((b - a).length / passo))
        for k in range(n + 1):
            q = a.lerp(b, k / n)
            p.cilindro(mat, T(*q) @ alinhar_z(normal), 0.0045, 0.0016, 8, 0.0006)

    def _furo(self, p, M0, rx, ry):
        """Furo oval na chapa (no plano XY local, virado para +Z): o fundo escuro e a borda repuxada."""
        p.disco_uv("fio", M0 @ S(1, ry / rx, 1), rx, 20)
        p.toro("pintura_interna", M0 @ S(1, ry / rx, 1), rx + 0.003, 0.003, 0.002, 20, 4)

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
        self.zcap = zcap
        # ------------------------------------------------------------------------------------------------ estrutura
        for s in (1, -1):
            lado = "esq" if s > 0 else "dir"
            p = self.nova(f"engine_paralama_interno_{lado}", "motor", nota="para-lama interno com a torre da suspensão")

            def pw(u, v, s=s):
                x = xf + (xr - xf) * u
                z = zfundo + (zcap(x) - 0.05 - zfundo) * v
                dx = abs(x - M["xd"])
                y = yb
                if dx < M["R"] + 0.10 and z < M["R"] * 2 + 0.05:
                    y -= 0.06 * (1 - dx / (M["R"] + 0.10))
                return V(x, s * y, z)
            p.grade("pintura_interna", 30, 10, pw, 0.012, normal_fn=lambda u, v, s=s: (0, -s, 0))
            zt = zcap(M["xd"]) - 0.09
            self.topo_torre = zt
            Mt = T(M["xd"], s * (yb - 0.075), zt)
            a0, a1 = (math.pi, 2 * math.pi) if s > 0 else (0.0, math.pi)
            p.revolucao("pintura_interna", Mt @ T(0, s * 0.075, -0.30), [(0.0, 0.0), (0.13, 0.0), (0.12, 0.24), (0.10, 0.29),
                                                                       (0.05, 0.30), (0, 0.30)], 28, a0=a0, a1=a1)
            p.revolucao("borracha", Mt, [(0, 0.0), (0.045, 0.0), (0.045, 0.02), (0.03, 0.03), (0, 0.032)], 24)
            p.cilindro("aluminio", Mt @ T(0, 0, 0.045), 0.008, 0.03, 8, 0.002)
            p.cilindro("metal_preto", Mt @ T(0, 0, 0.035), 0.013, 0.012, 6, 0.002)
            for k in range(3):
                a = 2 * math.pi * k / 3 + math.pi / 6
                p.cilindro("aluminio", Mt @ T(0.07 * math.cos(a), 0.07 * math.sin(a), 0.012), 0.009, 0.012, 6, 0.002)
                p.cilindro("aluminio", Mt @ T(0.07 * math.cos(a), 0.07 * math.sin(a), 0.026), 0.004, 0.02, 8, 0.001)
            # aba de cima com os pontos de solda
            pts = [V(xf + (xr - xf) * k / 10, s * (yb + 0.02), zcap(xf + (xr - xf) * k / 10) - 0.045) for k in range(11)]
            p.fita("pintura_interna", pts, 0.05, 0.01, (0, 0, 1))
            for k in range(10):
                self._soldas(p, pts[k] + V(0, 0, 0.0055), pts[k + 1] + V(0, 0, 0.0055), (0, 0, 1))
            # furos de passagem (tampados ou abertos) no para-lama interno
            for (xx, zz, rr) in ((xr - 0.12, zfundo + 0.10, 0.025), ((xf + M["xd"]) / 2, zfundo + 0.14, 0.018)):
                self._furo(p, T(xx, s * (yb - 0.013), zz) @ Rx(s * math.pi / 2), rr * 1.4, rr)
            # longarina com os furos e as soldas na aba
            q = self.nova(f"engine_longarina_{lado}", "motor", nota="longarina (perfil fechado com furos e pontos de solda)")
            xl0, xl1 = xf - 0.1, M["x_frente"] - 0.10
            yl = s * (yb - 0.12)
            q.caixa("chassi", T((xl0 + xl1) / 2, yl, zfundo + 0.05), xl1 - xl0, 0.07, 0.10, 0.012)
            q.caixa("chassi", T((xl0 + xl1) / 2, yl + s * 0.045, zfundo + 0.098), xl1 - xl0, 0.02, 0.004, 0.0015)
            self._soldas(q, V(xl0 + 0.05, yl + s * 0.045, zfundo + 0.1012), V(xl1 - 0.05, yl + s * 0.045, zfundo + 0.1012), (0, 0, 1),
                         mat="chassi")
            for k in range(3):
                xx = xl0 + (xl1 - xl0) * (0.25 + 0.25 * k)
                self._furo(q, T(xx, yl - s * 0.0355, zfundo + 0.05) @ Rx(-s * math.pi / 2), 0.022 if k != 1 else 0.012, 0.012)
        # corta-fogo com a manta, a caixa de ar e o motor do limpador
        c = self.nova("engine_corta_fogo", "motor", nota="corta-fogo com manta, caixa de ar, servo-freio e cilindro-mestre")
        c.caixa("pintura_interna", T(xf + 0.006, 0, (zfundo + zcap_t) / 2), 0.012, 2 * yb, zcap_t - zfundo, 0.006)
        c.caixa("isolante", T(xf + 0.016, -0.05, (zfundo + zcap_t) / 2 + 0.02), 0.012, 2 * yb - 0.40, zcap_t - zfundo - 0.12, 0.01)
        c.caixa("plastico", T(xf + 0.06, 0, zcap_t - 0.03), 0.12, 2 * yb - 0.04, 0.012, 0.005)
        for k in range(9):
            c.caixa("metal_preto", T(xf + 0.06, -0.3 + k * 0.075, zcap_t - 0.0235), 0.08, 0.012, 0.002, 0.0008, 1)
        Mw = T(xf + 0.05, -0.30, zcap_t - 0.075) @ Rx(math.pi / 2)
        c.cilindro("metal_preto", Mw, 0.04, 0.10, 20, 0.008)
        c.caixa("metal_preto", Mw @ T(0, 0, 0.07), 0.07, 0.06, 0.05, 0.008)
        c.tubo("aluminio", [(xf + 0.05, -0.30, zcap_t - 0.035), (xf + 0.03, -0.10, zcap_t - 0.03), (xf + 0.03, 0.25, zcap_t - 0.03)],
               0.005, seg=6)
        for (yy, zz) in ((0.15, zfundo + 0.25), (-0.10, zfundo + 0.30), (0.30, zfundo + 0.18)):
            c.revolucao("borracha", T(xf + 0.013, yy, zz) @ Ry(-math.pi / 2), [(0.0, 0.0), (0.025, 0.0), (0.022, 0.01), (0.012, 0.018),
                                                                               (0.0, 0.018)], 14)
        # servo-freio e cilindro-mestre com o reservatório (lado do motorista) e as linhas de freio descendo
        yb_ = M["y_banco"]
        Ms = T(xf + 0.10, yb_, zcap_t - 0.18) @ Ry(math.pi / 2)
        c.revolucao("metal_preto", Ms, [(0, -0.09), (0.11, -0.085), (0.12, -0.04), (0.12, 0.04), (0.11, 0.085), (0, 0.09)], 40)
        c.toro("metal_preto", Ms, 0.118, 0.006, 0.006, 40, 6)
        c.cilindro("aluminio", Ms @ T(0, 0, 0.16), 0.03, 0.14, 24, 0.004)
        c.cilindro("aluminio", Ms @ T(0, 0, 0.10), 0.05, 0.012, 24, 0.002)
        c.almofada("reservatorio", T(xf + 0.25, yb_, zcap_t - 0.10), 0.07, 0.09, 0.07, 0.3, 0.3)
        c.cilindro("amarelo", T(xf + 0.25, yb_, zcap_t - 0.058), 0.02, 0.02, 16, 0.004)
        c.tubo("borracha", [(xf + 0.12, yb_ - 0.12, zcap_t - 0.18), (xf + 0.08, yb_ - 0.14, zcap_t - 0.10)], 0.008, seg=8)  # vácuo
        for dy in (-0.012, 0.012):
            c.tubo("aluminio", [(xf + 0.22, yb_ + dy, zcap_t - 0.20), (xf + 0.25, yb_ + dy + 0.05, zcap_t - 0.26),
                                (xf + 0.20, yb - 0.04, zcap_t - 0.30), (xf + 0.25, yb - 0.03, zfundo + 0.05)], 0.0028, seg=6)
        # manta antirruído por baixo do capô (vai com o capô) e os reforços estampados
        if self._tem_peca_corte("hood"):
            mc = self.nova("hood_manta", "motor", "hood", "manta antirruído e reforços por baixo do capô")
            cx, _ = caixas_do_mapa({"parts": self._mapa_parts})
            hb = cx["hood"]
            yh = min(hb[3], yb) - 0.06
            xa_, xb_ = max(hb[0], xf) + 0.08, min(hb[1], xr + 0.05) - 0.10

            def ph(u, v):
                x = xa_ + (xb_ - xa_) * u
                y = -yh + 2 * yh * v
                return V(x, y, self.capo_em(x, y) - 0.004)
            mc.grade("isolante", 16, 12, ph, 0.012, normal_fn=lambda u, v: (0, 0, -1))
            for k in range(3):
                x = xa_ + (xb_ - xa_) * (0.2 + 0.3 * k)
                mc.fita("pintura_interna", [V(x, y_, self.capo_em(x, y_) - 0.02) for y_ in (-yh, -yh / 2, 0, yh / 2, yh)], 0.04, 0.02,
                        (0, 0, 1))
        # travessa da frente (com a fechadura do capô), radiador e ventoinha
        t = self.nova("engine_travessa", "motor", nota="painel dianteiro (travessas, fechadura do capô, buzina, fundo dos faróis)")
        t.caixa("pintura_interna", T(xr + 0.03, 0, zcap_f - 0.06), 0.06, 2 * yb, 0.05, 0.01)
        t.caixa("pintura_interna", T(xr + 0.03, 0, zfundo + 0.06), 0.06, 2 * yb, 0.05, 0.01)
        self._soldas(t, V(xr + 0.03, -yb + 0.05, zcap_f - 0.034), V(xr + 0.03, yb - 0.05, zcap_f - 0.034), (0, 0, 1), passo=0.05)
        for s in (1, -1):
            t.caixa("pintura_interna", T(xr + 0.03, s * (yb - 0.05), (zcap_f + zfundo) / 2), 0.05, 0.08, zcap_f - zfundo, 0.01)
        t.caixa("metal_preto", T(xr + 0.01, 0, zcap_f - 0.05), 0.04, 0.08, 0.05, 0.006)
        t.helice("metal_preto", T(xr + 0.0, 0.03, zcap_f - 0.10), 0.008, 0.0015, 0.05, 6, 6)
        t.tubo("metal_preto", [(xr + 0.0, 0.05, zcap_f - 0.06), (xr - 0.05, 0.20, zcap_f - 0.07), (xf + 0.1, yb - 0.08, zcap_t - 0.10)],
               0.003, seg=6)       # cabo de abrir o capô
        t.cilindro("metal_preto", T(xr + 0.05, -yb + 0.20, zfundo + 0.18) @ Ry(math.pi / 2), 0.045, 0.03, 24, 0.006)   # buzina
        cx, _ = caixas_do_mapa({"parts": self._mapa_parts})
        for nome in ("headlight_left", "headlight_right"):
            b = cx.get(nome)
            if b:
                yc = (b[2] + b[3]) / 2
                yc = math.copysign(min(abs(yc), yb - 0.12), yc)
                zc_ = min((b[4] + b[5]) / 2, zcap_f - 0.08)
                t.caixa("plastico", T(b[0] - 0.04, yc, zc_), 0.08, min(0.28, b[3] - b[2]), min(0.14, b[5] - b[4] + 0.02), 0.012)
                t.revolucao("borracha", T(b[0] - 0.08, yc, zc_) @ Ry(-math.pi / 2), [(0.0, 0.0), (0.045, 0.0), (0.04, 0.03), (0.0, 0.035)], 20)
                t.tubo("chicote", [(b[0] - 0.11, yc, zc_), (b[0] - 0.15, yc * 0.9, zc_ - 0.05)], 0.005, seg=6, sub=1)
        # radiador: colmeia, caixas laterais, bocais e a ventoinha com a carenagem
        rad = self.nova("engine_radiador", "motor", nota="radiador (colmeia, caixas, bocais, tampa)")
        hr = zcap_f - zfundo - 0.17
        wr = 2 * yb - 0.24
        zr = (zcap_f + zfundo) / 2 - 0.01
        rad.caixa("radiador", T(xr, 0, zr), 0.035, wr - 0.10, hr, 0.004)
        tanque = "plastico" if self.cfg["epoca"] in ("90", "2000") else "metal_preto"
        for s in (1, -1):
            rad.caixa(tanque, T(xr, s * (wr / 2 - 0.03), zr), 0.05, 0.06, hr + 0.02, 0.008)
            for dz in (-hr / 2 + 0.02, hr / 2 - 0.02):
                rad.cilindro("borracha", T(xr + 0.03, s * (wr / 2 - 0.03), zr + dz) @ Ry(math.pi / 2), 0.012, 0.02, 10, 0.003)
        bocal_sup = V(xr - 0.035, wr / 2 - 0.03, zr + hr / 2 - 0.03)
        bocal_inf = V(xr - 0.035, -(wr / 2 - 0.03), zr - hr / 2 + 0.04)
        for bo in (bocal_sup, bocal_inf):
            rad.cilindro(tanque, T(*bo) @ Ry(math.pi / 2), 0.018, 0.05, 16, 0.003)
        if self.cfg["epoca"] in ("70", "80"):
            rad.cilindro(tanque, T(xr, wr / 2 - 0.03, zr + hr / 2 + 0.02), 0.02, 0.03, 16, 0.004)
            rad.cilindro("cromado", T(xr, wr / 2 - 0.03, zr + hr / 2 + 0.04), 0.026, 0.012, 20, 0.004)
        v = self.nova("engine_ventoinha", "motor")
        Mv = T(xr - 0.05, -0.10, zr) @ Ry(-math.pi / 2)
        rv = min(0.17, hr / 2 - 0.01)
        v.revolucao("plastico", Mv, [(rv + 0.02, -0.02), (rv + 0.03, -0.02), (rv + 0.025, 0.04), (rv + 0.008, 0.045), (rv + 0.008, -0.015)], 48)
        v.cilindro("metal_preto", Mv @ T(0, 0, 0.06), 0.045, 0.06, 24, 0.006)
        v.cilindro("plastico", Mv @ T(0, 0, 0.015), 0.035, 0.03, 20, 0.004)
        for k in range(7):
            a = 2 * math.pi * k / 7
            v.caixa("plastico", Mv @ Rz(a) @ T(rv / 2 + 0.025, 0, 0.012) @ Rx(math.radians(28)), rv - 0.04, 0.05, 0.004, 0.0015, 1)
        for k in range(4):
            a = math.pi / 4 + k * math.pi / 2
            v.caixa("plastico", Mv @ Rz(a) @ T(rv / 2 + 0.03, 0, 0.05), rv - 0.02, 0.012, 0.012, 0.003)
        v.tubo("chicote", [Mv @ V(0.03, 0.03, 0.09), Mv @ V(0.12, 0.10, 0.10), (xr - 0.12, -yb + 0.10, zfundo + 0.22)], 0.004, seg=6)
        # motor
        if self.cfg["motor"] == "v8_longitudinal":
            pos = self.motor_v8(xf, xr, zfundo, zcap, yb)
        else:
            pos = self.motor_l4(xf, xr, zfundo, zcap, yb, transversal=self.cfg["motor"] == "l4_transversal")
        # bateria, reservatórios, mangueiras, chicote, bobina e cabos de vela
        Mb = T(xr - 0.18, yb - 0.17, zfundo + 0.16)
        self.bateria(Mb, alvo_pos=pos["partida"], alvo_massa=V(xr - 0.10, yb - 0.04, zfundo + 0.12))
        r = self.nova("engine_reservatorios", "motor", nota="expansão do arrefecimento, lavador do para-brisa")
        xa = xr - 0.12
        Mx = T(xf + 0.22, -(yb - 0.12), zcap(xf + 0.22) - 0.17)
        r.almofada("reservatorio", Mx, 0.16, 0.10, 0.14, 0.25, 0.3)
        for dz in (-0.03, 0.03):     # marcas de nível em relevo
            r.caixa("reservatorio", Mx @ T(0.0, 0.051, dz), 0.05, 0.003, 0.004, 0.001)
        r.cilindro("azul" if self.cfg["epoca"] in ("90", "2000") else "metal_preto", Mx @ T(0.03, 0, 0.075), 0.026, 0.025, 20, 0.004)
        for k in range(12):
            a = 2 * math.pi * k / 12
            r.caixa("azul" if self.cfg["epoca"] in ("90", "2000") else "metal_preto", Mx @ T(0.03 + 0.026 * math.cos(a),
                                                                                              0.026 * math.sin(a), 0.075) @ Rz(a),
                    0.004, 0.006, 0.02, 0.001, 1)
        self._mangueira(r, [Mx @ V(-0.02, 0.0, -0.07), Mx @ V(-0.05, 0.08, -0.12), pos["bomba"] + V(0.0, 0.0, 0.03)], 0.007)
        Mlav = T(xa, -(yb - 0.10), zfundo + 0.20)
        r.almofada("reservatorio", Mlav, 0.12, 0.10, 0.22, 0.25, 0.3)
        r.cilindro("azul", Mlav @ T(0, 0, 0.12), 0.02, 0.03, 16, 0.004)
        r.cilindro("metal_preto", Mlav @ T(0.04, 0.0, -0.08) @ Ry(math.pi / 2), 0.012, 0.04, 12, 0.002)
        r.tubo("borracha", [Mlav @ V(0.06, 0, -0.08), (xr - 0.2, -(yb - 0.05), zcap_f - 0.08), (xf + 0.07, -(yb - 0.06), zcap_t - 0.05)],
               0.0035, seg=6)
        m = self.nova("engine_mangueiras", "motor", nota="mangueiras do radiador e do aquecedor com abraçadeiras, cabo do acelerador")
        self._mangueira(m, [bocal_sup + V(-0.03, 0, 0), bocal_sup + V(-0.12, -0.02, 0.01), pos["termostato"] + V(0.03, 0, 0.02),
                            pos["termostato"]], 0.019)
        self._mangueira(m, [bocal_inf + V(-0.03, 0, 0), bocal_inf + V(-0.10, 0.08, -0.02), pos["bomba"] + V(0.06, 0, -0.04), pos["bomba"]],
                        0.02)
        for dy in (-0.05, 0.05):
            self._mangueira(m, [pos["aquecedor"] + V(0, dy, 0), (xf + 0.12, dy - 0.1, pos["aquecedor"][2] + 0.05),
                                (xf + 0.015, dy - 0.15, zcap_t - 0.20)], 0.009)
        if pos.get("filtro_saida") is not None:
            self._mangueira(m, [pos["filtro_saida"], (pos["filtro_saida"] + pos["admissao"]) / 2 + V(0, 0, 0.04), pos["admissao"]], 0.035)
        m.tubo("metal_preto", [(xf + 0.02, yb_ - 0.18, zcap_t - 0.15), (xf + 0.12, yb_ - 0.25, zcap_t - 0.12), pos["acelerador"]],
               0.0028, seg=6)
        h = self.nova("engine_chicote", "motor", nota="chicote elétrico em conduíte com presilhas, caixa de fusíveis, bobina")
        self._chicote(h, [(xf + 0.03, yb - 0.10, zcap_t - 0.12), (xf + 0.20, yb - 0.035, zcap(xf + 0.2) - 0.10),
                          (M["xd"] + 0.15, yb - 0.035, zcap(M["xd"]) - 0.12), (xr - 0.18, yb - 0.06, zfundo + 0.38),
                          (xr - 0.08, yb - 0.10, zfundo + 0.25)], 0.010)
        self._chicote(h, [(xf + 0.03, -yb + 0.10, zcap_t - 0.12), (xf + 0.15, -yb + 0.035, zcap(xf + 0.15) - 0.10),
                          (xr - 0.15, -yb + 0.035, zcap(xr - 0.15) - 0.12), (xr - 0.08, -yb + 0.12, zfundo + 0.25)], 0.008)
        self._chicote(h, [(M["xd"] + 0.10, yb - 0.04, zcap(M["xd"]) - 0.12), pos["centro"] + V(0, 0.15, 0.30)], 0.007, 0.12)
        if self.cfg["epoca"] in ("90", "2000"):
            Mfu = T(xf + 0.22, yb - 0.10, zcap(xf + 0.22) - 0.12)
            h.caixa("metal_preto", Mfu, 0.18, 0.12, 0.09, 0.012)
            h.caixa("metal_preto", Mfu @ T(0, 0, 0.05), 0.17, 0.11, 0.02, 0.008)
            for dx in (-0.06, 0.06):
                h.caixa("plastico", Mfu @ T(dx, 0.061, 0.03), 0.02, 0.006, 0.012, 0.002)
        if pos.get("distribuidor") is not None:
            Mbob = T(xf + 0.30, yb - 0.05, zcap(xf + 0.3) - 0.20) @ Rx(math.radians(-10))
            h.cilindro("metal_preto", Mbob, 0.032, 0.13, 20, 0.006)
            h.cilindro("plastico", Mbob @ T(0, 0, 0.075), 0.028, 0.02, 16, 0.004)
            h.cilindro("plastico", Mbob @ T(0, 0, 0.09), 0.008, 0.015, 10, 0.002)
            h.caixa("metal_preto", Mbob @ T(0, -0.035, 0), 0.04, 0.01, 0.10, 0.003)
            h.tubo("fio", [Mbob @ V(0, 0, 0.09), (Mbob @ V(0, 0, 0.09) + pos["distribuidor"]) / 2 + V(0, 0, 0.06), pos["distribuidor"]],
                   0.0035, seg=6)
        # estepe no vão do motor (como nos micros da época), deitado sobre o motor, na frente
        if self.cfg["estepe"] == "vao_motor":
            e = self.nova("interior_portamalas_estepe", "porta_malas", nota="estepe no vão do motor")
            Rs = M["R"] * 0.94
            Me = T(xr - Rs - 0.06, -yb + Rs + 0.12, zcap(xr - Rs) - 0.13) @ Ry(math.radians(-18))
            self._roda_estepe(e, Me, Rs)
            e.tubo("metal_preto", [Me @ V(0, 0, 0.03), Me @ V(0, 0, -0.12), (xr - 0.05, -yb + Rs + 0.12, zfundo + 0.12)], 0.006, seg=8)

    def bateria(self, Mb, alvo_pos=None, alvo_massa=None):
        """Bateria na bandeja, com o grampo, as tampas das células, os bornes com os terminais e os cabos."""
        b = self.nova("engine_bateria", "motor", nota="bateria, bandeja, grampo, terminais e cabos")
        b.caixa("metal_preto", Mb @ T(0, 0, -0.098), 0.20, 0.27, 0.012, 0.004)              # bandeja
        b.caixa("bateria", Mb, 0.17, 0.24, 0.19, 0.008)
        for k in range(5):    # nervuras da caixa
            b.caixa("bateria", Mb @ T(0.086, -0.10 + k * 0.05, 0.0), 0.003, 0.01, 0.17, 0.001)
        b.caixa("bateria", Mb @ T(0, 0, 0.1), 0.16, 0.23, 0.012, 0.004)
        for k in range(6):
            b.cilindro("metal_preto", Mb @ T(-0.035, -0.09 + k * 0.036, 0.108), 0.009, 0.006, 12, 0.0015)
        b.caixa("metal_preto", Mb @ T(-0.0, 0, 0.11), 0.025, 0.25, 0.012, 0.003)                # grampo
        for s in (1, -1):
            b.tubo("aluminio", [Mb @ V(0, s * 0.125, 0.11), Mb @ V(0, s * 0.135, 0.0), Mb @ V(0, s * 0.135, -0.09)], 0.004, seg=6, sub=1)
        ancoras = {}
        for k, cor in ((-1, "vermelho"), (1, "metal_preto")):
            b.cilindro("fundido", Mb @ T(0.05, k * 0.08, 0.115), 0.009, 0.02, 12, 0.002)
            b.caixa("aluminio", Mb @ T(0.05, k * 0.08, 0.125), 0.024, 0.03, 0.012, 0.003)
            b.cilindro("aluminio", Mb @ T(0.05, k * 0.08 + 0.02, 0.135) @ Rx(math.pi / 2), 0.004, 0.02, 6, 0.001)
            if k < 0:
                b.almofada("vermelho", Mb @ T(0.05, k * 0.08, 0.13), 0.04, 0.045, 0.03, 0.3, 0.3)       # capa do positivo
            ancoras[k] = Mb @ V(0.06, k * 0.08 - 0.015, 0.13)
        if alvo_pos is not None:
            b.tubo("vermelho", [ancoras[-1], ancoras[-1] + V(0.06, -0.05, 0.02), (ancoras[-1] + alvo_pos) / 2 + V(0, 0, 0.08), alvo_pos],
                   0.007, seg=8)
        if alvo_massa is not None:
            b.tubo("metal_preto", [ancoras[1], ancoras[1] + V(0.05, 0.03, 0.0), alvo_massa], 0.007, seg=8)
            b.cilindro("aluminio", T(*alvo_massa), 0.012, 0.004, 10, 0.001)

    def _belt(self, p, polias, y, normal_y, larg=0.018):
        """Correia em volta das polias (x, z, r) no plano local XZ a y: o fecho convexo dos círculos."""
        pts = []
        for (x, z, r) in polias:
            for k in range(24):
                a = 2 * math.pi * k / 24
                pts.append((x + (r + 0.003) * math.cos(a), z + (r + 0.003) * math.sin(a)))
        # fecho convexo (monotone chain)
        pts = sorted(set(pts))

        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
        lo, hi = [], []
        for q in pts:
            while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
                lo.pop()
            lo.append(q)
        for q in reversed(pts):
            while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0:
                hi.pop()
            hi.append(q)
        casco = lo[:-1] + hi[:-1]
        return casco

    def motor_l4(self, xf, xr, zf, zcap, yb, transversal=True):
        """
        4 cilindros em linha (no referencial local: virabrequim no Y, distribuição em -Y, escape em +X, admissão em -X, origem no
        centro do virabrequim). Bloco com nervuras e selos, cabeçote, tampa de válvulas com parafusos e bocal de óleo, capa da
        correia dentada, polias e correia, alternador, motor de partida, filtro de óleo, coletores, distribuidor e cabos (até os
        anos 90) ou bobinas individuais (2000), carburador com filtro redondo (70/80), monoponto (90) ou corpo de borboleta com
        caixa de filtro e duto (2000), vareta, coxins e câmbio.
        """
        M = self.M
        ep = self.cfg["epoca"]
        p = self.nova("engine_motor", "motor", nota="motor de 4 cilindros, câmbio, coletores, alternador, partida")
        xc = _limitar(M["xd"] + 0.02, xf + 0.32, xr - 0.40)
        zcr = max(zf + 0.20, M["R"] + 0.04)                           # altura do virabrequim
        topo_local = 0.56 if ep in ("70", "80") else 0.46               # o que fica acima do virabrequim (filtro redondo é alto)
        esc = _limitar((zcap(xc) - 0.05 - zcr) / topo_local, 0.78, 1.08)
        inclina = math.radians(12) if transversal else 0.0               # transversal: o bloco tomba para trás
        if transversal:
            Mm = T(xc, -0.08, zcr) @ Ry(-inclina) @ S(esc, esc, esc)
        else:
            Mm = T(xc, 0, zcr) @ Rz(math.pi / 2) @ S(esc, esc, esc)
        L = lambda x, y, z: Mm @ V(x, y, z)          # noqa: E731
        ys = (-0.15, -0.05, 0.05, 0.15)
        # cárter com a flange e o bujão
        p.caixa("metal_preto", Mm @ T(0, 0, -0.145), 0.24, 0.38, 0.13, 0.015)
        p.caixa("metal_preto", Mm @ T(0, 0, -0.078), 0.27, 0.41, 0.012, 0.004)
        p.cilindro("aluminio_fundido", Mm @ T(0.0, 0.10, -0.212), 0.01, 0.01, 6, 0.002)
        # bloco (comprimento no Y local) com nervuras e selos de água
        p.caixa("fundido", Mm @ T(0, 0, 0.075), 0.25, 0.42, 0.30, 0.012)
        for s in (1, -1):
            for y in ys:
                p.caixa("fundido", Mm @ T(s * 0.127, y + 0.05, 0.06), 0.008, 0.012, 0.22, 0.003)
        for y in ys[:3]:
            p.cilindro("aluminio_fundido", Mm @ T(0.128, y + 0.05, 0.10) @ Ry(math.pi / 2), 0.016, 0.005, 16, 0.001)
        # cabeçote, junta e tampa de válvulas
        p.caixa("fundido", Mm @ T(0, 0, 0.278), 0.235, 0.41, 0.10, 0.01)
        p.caixa("metal_preto", Mm @ T(0, 0, 0.226), 0.25, 0.415, 0.006, 0.002)
        tampa = "metal_preto" if ep in ("90", "2000") else "motor_pintado"
        p.almofada(tampa, Mm @ T(0, 0.0, 0.355), 0.20, 0.40, 0.07, 0.18, 0.18)
        p.caixa(tampa, Mm @ T(0, 0, 0.332), 0.215, 0.415, 0.014, 0.005)
        for k in range(5):
            p.caixa(tampa, Mm @ T(0, -0.16 + k * 0.08, 0.392), 0.16, 0.012, 0.012, 0.004)
        for k in range(5):
            for s in (1, -1):
                p.cilindro("aluminio_fundido", Mm @ T(s * 0.104, -0.18 + k * 0.09, 0.342), 0.006, 0.012, 6, 0.001)
        p.cilindro("amarelo" if ep != "70" else "metal_preto", Mm @ T(0.03, 0.12, 0.395), 0.024, 0.022, 20, 0.004)
        p.tubo("borracha", [L(-0.05, 0.17, 0.38), L(-0.12, 0.20, 0.40), L(-0.20, 0.10, 0.40)], 0.008, seg=8)    # respiro
        # capa da correia dentada, polias, correia e alternador (lado -Y)
        p.almofada("plastico", Mm @ T(-0.01, -0.232, 0.13), 0.22, 0.045, 0.42, 0.2, 0.2)
        polias = [(0.0, 0.0, 0.07), (0.035, 0.13, 0.055), (0.155, 0.08, 0.033)]
        p.cilindro("metal_preto", Mm @ T(0.0, -0.268, 0.0) @ Rx(math.pi / 2), 0.07, 0.025, 32, 0.004)
        p.cilindro("aluminio_fundido", Mm @ T(0.0, -0.283, 0.0) @ Rx(math.pi / 2), 0.02, 0.008, 6, 0.002)
        p.cilindro("aluminio_fundido", Mm @ T(0.035, -0.265, 0.13) @ Rx(math.pi / 2), 0.055, 0.02, 32, 0.004)
        for k in range(4):
            a = 2 * math.pi * k / 4
            p.cilindro("aluminio_fundido", Mm @ T(0.035 + 0.025 * math.cos(a), -0.277, 0.13 + 0.025 * math.sin(a)) @ Rx(math.pi / 2), 0.005,
                       0.006, 6, 0.001)
        casco = self._belt(p, polias, -0.268, 1)
        p.fita("borracha", [L(x, -0.268, z) for (x, z) in casco + [casco[0]]], 0.018, 0.006, Mm.to_3x3() @ V(0, 1, 0))
        Ma = Mm @ T(0.155, -0.18, 0.08) @ Rx(math.pi / 2)
        p.cilindro("aluminio_fundido", Ma, 0.062, 0.13, 32, 0.008)
        for k in range(6):
            p.toro("aluminio_fundido", Ma @ T(0, 0, -0.05 + k * 0.02), 0.062, 0.003, 0.003, 32, 4)
        p.cilindro("metal_preto", Mm @ T(0.155, -0.268, 0.08) @ Rx(math.pi / 2), 0.033, 0.022, 24, 0.004)
        p.cilindro("plastico", Mm @ T(0.155, -0.11, 0.08) @ Rx(math.pi / 2), 0.03, 0.01, 16, 0.003)
        p.caixa("aluminio_fundido", Mm @ T(0.13, -0.15, 0.02), 0.05, 0.03, 0.10, 0.005)          # suporte
        # coletor de admissão (-X) e carburação
        if ep in ("70", "80", "90"):
            base = L(-0.21, 0.0, 0.40)
            for y in ys:
                p.tubo("aluminio_fundido", [L(-0.115, y, 0.27), L(-0.17, y * 0.85, 0.30), L(-0.20, y * 0.35, 0.36), base], 0.018, seg=12)
            p.caixa("aluminio_fundido", Mm @ T(-0.21, 0.0, 0.42), 0.09, 0.11, 0.07, 0.006)
            p.cilindro("aluminio_fundido", Mm @ T(-0.21, 0.06, 0.42) @ Rx(math.pi / 2), 0.012, 0.03, 12, 0.002)      # eixo da borboleta
            Mf = Mm @ T(-0.21, 0.0, 0.50)
            if ep == "90":     # monoponto: filtro oval de plástico
                p.almofada("plastico", Mf @ S(1.0, 1.3, 1.0), 0.20, 0.20, 0.08, 0.25, 0.25)
                p.cilindro("plastico", Mf @ T(0.12, 0, 0) @ Ry(math.pi / 2), 0.035, 0.08, 20, 0.004)
                saida = Mf @ V(0.17, 0, 0)
            else:
                p.revolucao("metal_preto" if ep == "80" else "cromado", Mf, [(0, -0.035), (0.15, -0.035), (0.16, -0.02), (0.16, 0.03),
                                                                             (0.145, 0.045), (0, 0.045)], 48)
                p.revolucao("metal_preto", Mf, [(0.161, -0.025), (0.163, -0.022), (0.163, 0.022), (0.161, 0.025)], 48)
                p.cilindro("cromado", Mf @ T(0, 0, 0.055), 0.022, 0.012, 6, 0.002)
                p.caixa("cromado", Mf @ T(0, 0, 0.062), 0.05, 0.008, 0.012, 0.002)
                p.cilindro("metal_preto", Mf @ T(0.17, 0, 0.0) @ Ry(math.pi / 2), 0.03, 0.06, 20, 0.004)   # bocal
                saida = None
            adm = L(-0.21, 0.0, 0.47)
            acel = L(-0.21, 0.07, 0.42)
        else:
            plenum = Mm @ T(-0.26, 0.0, 0.33) @ Rx(math.pi / 2)
            for y in ys:
                p.tubo("plastico", [L(-0.115, y, 0.27), L(-0.19, y, 0.31), L(-0.25, y * 0.9, 0.36), L(-0.27, y * 0.9, 0.33)], 0.022, seg=12)
            p.cilindro("plastico", plenum, 0.055, 0.40, 24, 0.012)
            p.cilindro("aluminio_fundido", Mm @ T(-0.26, 0.23, 0.33) @ Rx(math.pi / 2), 0.04, 0.05, 24, 0.004)       # corpo de borboleta
            p.caixa("metal_preto", Mm @ T(-0.21, 0.24, 0.33), 0.03, 0.03, 0.04, 0.005)
            adm = L(-0.26, 0.26, 0.33)
            acel = L(-0.23, 0.24, 0.33)
            saida = None
            # caixa do filtro de ar no canto da frente, com as presilhas
            Mfx = T(xr - 0.24, -(yb - 0.19), zf + 0.40)
            p.caixa("plastico", Mfx, 0.24, 0.30, 0.10, 0.02)
            p.caixa("plastico", Mfx @ T(0, 0, 0.065), 0.25, 0.31, 0.03, 0.01)
            for k in range(4):
                p.caixa("metal_preto", Mfx @ T(0.126, -0.11 + k * 0.073, 0.05), 0.008, 0.018, 0.05, 0.003)
            p.cilindro("plastico", Mfx @ T(0.15, 0.0, -0.01) @ Ry(math.pi / 2), 0.04, 0.06, 20, 0.004)
            saida = Mfx @ V(-0.13, 0.08, 0.02)
        # escape (+X): coletor, protetor de calor (90/2000) e o tubo descendo
        col = L(0.205, 0.0, 0.02)
        for y in ys:
            p.tubo("ferro", [L(0.115, y, 0.26), L(0.165, y, 0.24), L(0.20, y * 0.5, 0.12), col], 0.018, seg=12)
        p.tubo("ferro", [col, L(0.20, 0.0, -0.10), L(0.16, 0.02, -0.26)], 0.024, seg=12)
        if ep in ("90", "2000"):
            def pp(u, v):
                y = -0.20 + 0.40 * u
                a = math.radians(-20 + 110 * v)
                return L(0.17 + 0.07 * math.cos(a), y, 0.12 + 0.12 * math.sin(a))
            p.grade("aluminio_fundido", 10, 6, pp, 0.002, normal_fn=None)
        # velas: cabos do distribuidor (até os anos 90) ou bobinas individuais (2000)
        velas = [L(-0.095, y, 0.33) for y in ys]
        dist = None
        if ep in ("70", "80", "90"):
            Md = Mm @ T(-0.06, 0.245, 0.27)
            p.cilindro("aluminio_fundido", Md, 0.032, 0.08, 20, 0.004)
            p.revolucao("metal_preto", Md @ T(0, 0, 0.04), [(0, 0), (0.045, 0), (0.046, 0.03), (0.035, 0.05), (0, 0.055)], 24)
            torres = []
            for k in range(5):
                a = 2 * math.pi * k / 5
                rr = 0.028 if k else 0.0
                tp = Md @ V(rr * math.cos(a), rr * math.sin(a), 0.10)
                p.cilindro("metal_preto", T(*tp), 0.007, 0.02, 10, 0.002)
                torres.append(tp)
            for k, v_ in enumerate(velas):
                p.tubo("fio", [torres[k + 1], (torres[k + 1] + v_) / 2 + V(0, 0, 0.07), v_ + V(0, 0, 0.04)], 0.0038, seg=6)
                p.cilindro("fio", T(*(v_ + V(0, 0, 0.025))), 0.009, 0.04, 10, 0.002)          # cachimbo
            dist = torres[0]
        else:
            for v_ in velas:
                Mc = T(*(v_ + V(0.0, 0.0, 0.07)))
                p.caixa("plastico", Mc, 0.045, 0.06, 0.05, 0.008)
                p.caixa("cinto", Mc @ T(-0.03, 0, 0.0), 0.02, 0.02, 0.02, 0.004)
            self._chicote(p, [L(-0.14, -0.18, 0.43), L(-0.14, 0.18, 0.43), L(-0.20, 0.25, 0.30)], 0.006, 0.1)
        # vareta de óleo, filtro de óleo, partida, coxins
        p.tubo("metal_preto", [L(0.12, 0.05, -0.05), L(0.15, 0.05, 0.25), L(0.16, 0.05, 0.40)], 0.005, seg=6)
        p.toro("amarelo", Mm @ T(0.16, 0.05, 0.42) @ Rx(math.pi / 2), 0.016, 0.004, 0.004, 16, 6)
        p.cilindro("azul", Mm @ T(0.17, 0.12, -0.03) @ Ry(math.pi / 2), 0.042, 0.10, 24, 0.006)
        Mp = Mm @ T(-0.135, 0.25, -0.02) @ Rx(math.pi / 2)
        p.cilindro("metal_preto", Mp, 0.045, 0.17, 24, 0.006)
        p.cilindro("aluminio_fundido", Mp @ T(0.0, 0.0, -0.10), 0.04, 0.04, 20, 0.004)
        p.cilindro("metal_preto", Mp @ T(-0.055, 0.0, 0.0), 0.025, 0.10, 16, 0.004)          # solenoide
        partida = Mp @ V(-0.075, 0.0, 0.03)
        for dy in (-0.18, 0.18):
            p.cilindro("borracha", Mm @ T(0.0, dy, -0.05) @ Ry(math.pi / 2), 0.035, 0.04, 16, 0.006)
        # câmbio (do lado +Y local no transversal; atrás no longitudinal) com os cabos de engate e da embreagem
        if transversal:
            Mc = Mm @ T(0, 0.21, -0.03) @ Rx(-math.pi / 2)
            p.revolucao("aluminio_fundido", Mc, [(0.17, 0), (0.17, 0.03), (0.15, 0.10), (0.13, 0.16), (0.13, 0.30), (0.10, 0.34),
                                         (0.05, 0.35), (0, 0.35)], 40)
            for k in range(6):
                p.cilindro("aluminio_fundido", Mc @ T(0.16 * math.cos(k), 0.16 * math.sin(k), 0.02), 0.007, 0.02, 6, 0.002)
            topo = L(-0.04, 0.40, 0.14)
            p.caixa("aluminio_fundido", Mm @ T(-0.04, 0.40, 0.12), 0.08, 0.08, 0.05, 0.008)
            for dy in (-0.02, 0.02):
                p.tubo("metal_preto", [topo + V(0, dy, 0), (topo + V(xf + 0.02 - topo.x, dy, 0)) * 0.5 + topo * 0.5 + V(0, 0, 0.08),
                                       V(xf + 0.02, topo.y + dy, topo.z + 0.05)], 0.005, seg=8)
            p.tubo("metal_preto", [L(-0.10, 0.25, 0.14), V(xf + 0.03, M["y_banco"] + 0.10, zcap(xf) - 0.20)], 0.004, seg=6, sub=1)
            cambio = L(0, 0.50, -0.05)
        else:
            Mc = Mm @ T(0, 0.21, -0.03) @ Rx(-math.pi / 2)
            p.revolucao("aluminio_fundido", Mc, [(0.16, 0), (0.15, 0.10), (0.09, 0.22), (0.075, 0.55), (0.04, 0.60), (0, 0.60)], 40)
            cambio = L(0, 0.8, -0.05)
        return {"termostato": L(0.07, 0.215, 0.28), "bomba": L(0.06, -0.20, 0.06), "aquecedor": L(-0.12, 0.20, 0.10),
                "filtro_saida": saida, "admissao": adm, "escape": L(0.16, 0.02, -0.26), "cambio": cambio, "partida": partida,
                "acelerador": acel, "distribuidor": dist, "centro": L(0, 0, 0)}

    def motor_v8(self, xf, xr, zf, zcap, yb):
        """V8 longitudinal: bloco, bancadas a 90°, tampas de válvulas, coletor de admissão no V com carburador de corpo quádruplo e
        filtro redondo, coletores de escape de ferro, distribuidor atrás com os 8 cabos, alternador, bomba da direção, ventoinha
        mecânica com a embreagem viscosa, correias e câmbio no túnel."""
        M = self.M
        ep = self.cfg["epoca"]
        p = self.nova("engine_motor", "motor", nota="V8 longitudinal: bloco, bancadas, coletores, carburador e filtro redondo, distribuidor e cabos")
        xc = (xf + xr) / 2 - 0.05
        zcr = max(zf + 0.20, M["R"] + 0.04)
        esc = _limitar((zcap(xc) - 0.05 - zcr) / 0.58, 0.8, 1.05)
        Mm = T(xc, 0, zcr) @ S(esc, esc, esc)
        L = lambda x, y, z: Mm @ V(x, y, z)          # noqa: E731
        p.caixa("motor_pintado", Mm @ T(0, 0, 0.05), 0.60, 0.32, 0.30, 0.02)
        p.caixa("metal_preto", Mm @ T(0, 0, -0.16), 0.55, 0.30, 0.12, 0.015)
        p.caixa("metal_preto", Mm @ T(0, 0, -0.098), 0.58, 0.33, 0.012, 0.004)
        xs = (-0.18, -0.06, 0.06, 0.18)
        velas = []
        for s in (1, -1):
            Mb = Mm @ T(0, s * 0.14, 0.20) @ Rx(-s * math.radians(45))
            p.caixa("motor_pintado", Mb, 0.56, 0.18, 0.16, 0.015)
            tv = "cromado" if ep == "70" else "motor_pintado"
            p.almofada(tv, Mb @ T(0, 0, 0.11), 0.52, 0.15, 0.07, 0.18, 0.2)
            for k in range(6):
                p.cilindro("aluminio_fundido", Mb @ T(-0.22 + k * 0.088, s * 0.07, 0.085), 0.006, 0.012, 6, 0.001)
            p.cilindro("metal_preto", Mb @ T(0.18, 0, 0.15), 0.02, 0.025, 16, 0.004)        # respiro
            for k, xk in enumerate(xs):
                xk2 = xk + s * 0.03
                # coletor de escape de ferro (tipo tronco) por fora da bancada
                p.tubo("ferro", [L(xk2, s * 0.25, 0.14), L(xk2, s * 0.31, 0.08), L(xk2 * 0.6 - 0.05, s * 0.33, -0.04)], 0.02, seg=12)
                velas.append(L(xk2 + 0.04, s * 0.27, 0.20))
            p.tubo("ferro", [L(-0.2, s * 0.33, -0.04), L(0.2, s * 0.33, -0.04)], 0.035, seg=14, sub=1)
            p.tubo("ferro", [L(-0.2, s * 0.33, -0.04), L(-0.35, s * 0.30, -0.18), L(-0.6, s * 0.22, -0.25)], 0.03, seg=12)
        # coletor de admissão no V, carburador e filtro de ar
        p.caixa("aluminio_fundido", Mm @ T(0, 0, 0.29), 0.44, 0.18, 0.10, 0.02)
        for k in range(4):
            for s in (1, -1):
                p.tubo("aluminio_fundido", [L(xs[k], s * 0.02, 0.32), L(xs[k], s * 0.10, 0.28)], 0.02, seg=10, sub=1)
        p.caixa("aluminio_fundido", Mm @ T(0, 0, 0.36), 0.11, 0.11, 0.07, 0.01)
        Mf = Mm @ T(0, 0, 0.43)
        p.revolucao("metal_preto" if ep != "70" else "cromado", Mf,
                    [(0, -0.03), (0.19, -0.03), (0.20, -0.01), (0.20, 0.04), (0.18, 0.06), (0, 0.06)], 56)
        p.revolucao("metal_preto", Mf, [(0.201, -0.02), (0.203, -0.017), (0.203, 0.035), (0.201, 0.038)], 56)
        p.cilindro("cromado", Mf @ T(0, 0, 0.07), 0.025, 0.012, 6, 0.002)
        p.cilindro("metal_preto", Mf @ T(0.20, 0.0, 0.0) @ Ry(math.pi / 2), 0.04, 0.08, 20, 0.004)
        # distribuidor atrás com os 8 cabos indo para as velas, nos suportes
        Md = Mm @ T(-0.30, 0, 0.32)
        p.cilindro("metal_preto", Md, 0.04, 0.08, 20, 0.006)
        p.revolucao("metal_preto", Md @ T(0, 0, 0.04), [(0, 0), (0.06, 0), (0.062, 0.03), (0.045, 0.055), (0, 0.06)], 28)
        torres = [Md @ V(0.05 * math.cos(2 * math.pi * k / 8), 0.05 * math.sin(2 * math.pi * k / 8), 0.09) for k in range(8)]
        for k, v_ in enumerate(velas):
            t_ = torres[k]
            meio = L(-0.10 + 0.05 * (k % 4), (0.20 if v_.y > Mm.translation.y else -0.20), 0.38)
            p.tubo("fio", [t_, meio, v_ + V(0, 0, 0.04)], 0.0042, seg=6)
            p.cilindro("fio", T(*(v_ + V(0, 0, 0.02))), 0.01, 0.04, 10, 0.002)
        for s in (1, -1):
            for xx in (-0.05, 0.10):
                p.caixa("plastico", Mm @ T(xx, s * 0.20, 0.38), 0.02, 0.03, 0.015, 0.003)
        # frente: bomba d'água, ventoinha mecânica, polias, alternador e bomba da direção
        p.caixa("aluminio_fundido", Mm @ T(0.31, 0, 0.10), 0.05, 0.16, 0.16, 0.012)
        Mv = Mm @ T(0.40, 0, 0.10) @ Ry(math.pi / 2)
        p.cilindro("aluminio_fundido", Mv @ T(0, 0, -0.04), 0.05, 0.05, 20, 0.006)
        rv = 0.20
        for k in range(5):
            a = 2 * math.pi * k / 5
            p.caixa("metal_preto", Mv @ Rz(a) @ T(rv / 2 + 0.03, 0, 0.0) @ Rx(math.radians(30)), rv, 0.055, 0.004, 0.0015, 1)
        p.cilindro("metal_preto", Mv @ T(0, 0, 0.02), 0.04, 0.03, 20, 0.004)
        polias = [(0.0, -0.08, 0.085), (0.0, 0.10, 0.065), (0.17, 0.12, 0.035), (-0.17, 0.10, 0.05)]
        for (yy, zz, rr) in polias:
            p.cilindro("metal_preto", Mm @ T(0.345, yy, zz) @ Ry(math.pi / 2), rr, 0.025, 28, 0.004)
        casco = self._belt(p, [(yy, zz, rr) for (yy, zz, rr) in polias], 0.345, 1)
        p.fita("borracha", [L(0.345, y_, z_) for (y_, z_) in casco + [casco[0]]], 0.018, 0.006, (1, 0, 0))
        Ma = Mm @ T(0.28, 0.17, 0.12) @ Ry(math.pi / 2)
        p.cilindro("aluminio_fundido", Ma, 0.065, 0.12, 28, 0.008)
        for k in range(5):
            p.toro("aluminio_fundido", Ma @ T(0, 0, -0.045 + k * 0.022), 0.065, 0.003, 0.003, 28, 4)
        p.cilindro("metal_preto", Mm @ T(0.28, -0.17, 0.10) @ Ry(math.pi / 2), 0.055, 0.10, 24, 0.008)        # bomba da direção
        p.cilindro("metal_preto", Mm @ T(0.24, -0.17, 0.17), 0.03, 0.04, 16, 0.004)
        # câmbio para trás (no túnel), coxins, vareta, partida
        p.revolucao("aluminio_fundido", Mm @ T(-0.30, 0, -0.04) @ Ry(-math.pi / 2), [(0.19, 0), (0.18, 0.04), (0.15, 0.12), (0.09, 0.24),
                                                                              (0.08, 0.62), (0.04, 0.66), (0, 0.66)], 40)
        for dy in (-0.16, 0.16):
            p.cilindro("borracha", Mm @ T(0.05, dy, -0.08) @ Rx(math.pi / 2), 0.035, 0.04, 16, 0.006)
        p.tubo("metal_preto", [L(0.15, 0.13, -0.05), L(0.20, 0.13, 0.30), L(0.22, 0.13, 0.36)], 0.005, seg=6)
        p.toro("amarelo", Mm @ T(0.22, 0.13, 0.38) @ Rx(math.pi / 2), 0.015, 0.004, 0.004, 16, 6)
        Mp = Mm @ T(-0.25, -0.17, -0.10) @ Ry(math.pi / 2)
        p.cilindro("metal_preto", Mp, 0.05, 0.18, 24, 0.006)
        p.cilindro("metal_preto", Mp @ T(-0.06, 0, 0.0), 0.028, 0.11, 16, 0.004)
        return {"termostato": L(0.30, 0.0, 0.30), "bomba": L(0.33, 0.06, 0.02), "aquecedor": L(-0.15, 0.20, 0.15),
                "filtro_saida": None, "admissao": None, "escape": L(-0.6, 0.22, -0.25), "cambio": L(-0.9, 0, -0.05),
                "partida": Mp @ V(-0.06, 0, 0.06), "acelerador": L(0.0, 0.08, 0.36), "distribuidor": Md @ V(0, 0, 0.09),
                "centro": L(0, 0, 0)}

    def motor_boxer(self):
        """
        Motor traseiro arrefecido a ar (4 cilindros opostos), visto pela tampa de trás: carenagem da ventoinha, gerador no pedestal
        com a polia e a correia, carburador no meio com o filtro em banho de óleo, coletor em Y, distribuidor, bobina na carenagem,
        bocal de óleo, chapas defletoras dos cilindros, trocadores de calor embaixo, e a vedação de borracha em volta do vão.
        """
        M = self.M
        cab = M["carroceria"] == "cabine_avancada"
        xa = M["x_encosto_t"] - 0.12 if not cab else M["x_tras"] + 0.80
        xb = M["x_tras"] + 0.15
        yb = M["y_caixa_t"]
        zf = max(0.18, M["R"] * 0.70)
        p = self.nova("engine_motor", "motor", nota="4 cilindros opostos arrefecidos a ar, carenagem da ventoinha, gerador, carburador")
        xc = (xa + xb) / 2 - 0.02
        Mm = T(xc, 0, zf + 0.13)
        L = lambda x, y, z: Mm @ V(x, y, z)          # noqa: E731
        # cárter (bloco central) e cilindros com aletas, cabeçotes e tampas de válvulas
        p.caixa("aluminio_fundido", Mm, 0.34, 0.24, 0.26, 0.03)
        for k in range(4):
            p.caixa("aluminio_fundido", Mm @ T(-0.12 + k * 0.08, 0, -0.135), 0.012, 0.22, 0.012, 0.004)
        for s in (1, -1):
            for dx in (-0.08, 0.08):
                Mc = Mm @ T(dx, s * 0.12, 0.0) @ Rx(-s * math.pi / 2)
                perf = []
                for k in range(10):
                    perf += [(0.052, 0.012 * k), (0.068, 0.012 * k + 0.003), (0.068, 0.012 * k + 0.008), (0.052, 0.012 * k + 0.011)]
                perf = [(0, 0)] + perf + [(0, 0.12)]
                p.revolucao("fundido", Mc, perf, 24)
            p.caixa("fundido", Mm @ T(0, s * 0.27, 0.0), 0.30, 0.06, 0.16, 0.02)
            p.almofada("metal_preto", Mm @ T(0, s * 0.315, 0.0), 0.26, 0.04, 0.12, 0.2, 0.2)
            p.caixa("metal_preto", Mm @ T(0, s * 0.27, 0.12), 0.30, 0.10, 0.08, 0.02)        # chapa defletora
            for dx in (-0.08, 0.08):
                p.tubo("ferro", [Mm @ V(dx, s * 0.27, -0.09), Mm @ V(dx * 0.8, s * 0.24, -0.16), Mm @ V(-0.18, s * 0.18, -0.20)],
                       0.018, seg=10)
            # trocador de calor (aquecimento) sob os cilindros
            p.cilindro("ferro", Mm @ T(0.0, s * 0.22, -0.20) @ Ry(math.pi / 2), 0.05, 0.30, 20, 0.008)
            p.tubo("ferro", [L(0.15, s * 0.22, -0.20), L(0.30, s * 0.20, -0.18)], 0.03, seg=12, sub=1)
        # carenagem da ventoinha (em cima), gerador no pedestal, polias e correia
        Mv = Mm @ T(0.02, 0, 0.20)
        p.almofada("metal_preto", Mv, 0.26, 0.64, 0.18, 0.2, 0.25)
        p.cilindro("metal_preto", Mv @ T(-0.06, 0, 0.12) @ Ry(math.pi / 2), 0.13, 0.12, 40, 0.01)
        p.caixa("metal_preto", Mv @ T(0.02, 0, 0.16), 0.10, 0.10, 0.06, 0.01)                # pedestal
        Mg = Mv @ T(-0.09, 0, 0.17) @ Ry(math.pi / 2)
        p.cilindro("aluminio_fundido" if self.cfg["epoca"] != "70" else "metal_preto", Mg, 0.055, 0.17, 28, 0.008)
        p.toro("metal_preto", Mg @ T(0, 0, 0.0), 0.058, 0.008, 0.008, 28, 6)                  # cinta do gerador
        p.cilindro("metal_preto", Mv @ T(-0.19, 0, 0.17) @ Ry(math.pi / 2), 0.05, 0.02, 28, 0.004)
        p.cilindro("metal_preto", Mm @ T(-0.20, 0, -0.06) @ Ry(math.pi / 2), 0.075, 0.025, 32, 0.004)
        p.fita("borracha", [Mm @ V(-0.205, 0, -0.14), Mm @ V(-0.205, 0.05, 0.10), Mm @ V(-0.205, 0, 0.42), Mm @ V(-0.205, -0.05, 0.10),
                            Mm @ V(-0.205, 0, -0.14)], 0.015, 0.005, (1, 0, 0))
        # bobina presa na carenagem e o distribuidor
        Mbob = Mv @ T(0.05, -0.22, 0.10) @ Ry(math.pi / 2)
        p.cilindro("metal_preto", Mbob, 0.03, 0.12, 20, 0.006)
        Md = Mm @ T(0.10, -0.12, 0.30)
        p.cilindro("metal_preto", Md, 0.03, 0.06, 20, 0.004)
        p.revolucao("metal_preto", Md @ T(0, 0, 0.03), [(0, 0), (0.042, 0), (0.044, 0.025), (0.03, 0.045), (0, 0.048)], 24)
        torres = [Md @ V(0.026 * math.cos(2 * math.pi * k / 4), 0.026 * math.sin(2 * math.pi * k / 4), 0.075) for k in range(4)]
        k = 0
        for s in (1, -1):
            for dx in (-0.08, 0.08):
                vela = Mm @ V(dx, s * 0.30, 0.05)
                p.tubo("fio", [torres[k], (torres[k] + vela) / 2 + V(0, 0, 0.12), vela], 0.0038, seg=6)
                p.cilindro("fio", T(*vela) @ Rx(s * math.pi / 2), 0.009, 0.04, 10, 0.002)
                k += 1
        p.tubo("fio", [Md @ V(0, 0, 0.075), Mbob @ V(0, 0, 0.07)], 0.0038, seg=6, sub=1)
        # carburador e filtro de ar em banho de óleo, coletor em Y
        p.cilindro("aluminio_fundido", Mm @ T(0.10, 0.0, 0.36), 0.035, 0.08, 20, 0.006)
        p.caixa("aluminio_fundido", Mm @ T(0.10, 0.0, 0.34), 0.07, 0.09, 0.05, 0.008)
        Mf = Mm @ T(0.10, 0.20, 0.38) @ Rx(math.pi / 2)
        p.revolucao("metal_preto", Mf, [(0, -0.07), (0.10, -0.07), (0.11, -0.05), (0.11, 0.05), (0.10, 0.07), (0, 0.07)], 40)
        p.cilindro("metal_preto", Mf @ T(0.0, 0.11, 0.0) @ Rx(math.pi / 2), 0.03, 0.10, 16, 0.004)        # tomada de ar
        p.tubo("aluminio_fundido", [Mm @ V(0.06, 0, 0.36), Mm @ V(0.06, 0.12, 0.30), Mm @ V(0.06, 0.20, 0.10)], 0.016, seg=10)
        for s in (1, -1):
            p.tubo("aluminio_fundido", [L(0.10, 0.0, 0.32), L(0.10, s * 0.14, 0.28), L(0.06, s * 0.22, 0.15)], 0.018, seg=12)
        # bocal de óleo e vareta
        p.cilindro("metal_preto", Mm @ T(-0.12, 0.10, 0.25), 0.03, 0.12, 16, 0.004)
        p.cilindro("metal_preto", Mm @ T(-0.12, 0.10, 0.32), 0.04, 0.02, 20, 0.004)
        p.tubo("metal_preto", [Mm @ V(-0.12, -0.05, -0.08), Mm @ V(-0.14, -0.05, 0.25)], 0.005, seg=6, sub=1)
        p.toro("amarelo", Mm @ T(-0.14, -0.05, 0.27) @ Rx(math.pi / 2), 0.015, 0.004, 0.004, 16, 6)
        # câmbio (na frente do motor, entre as rodas de trás)
        p.revolucao("aluminio_fundido", Mm @ T(0.20, 0, -0.02) @ Ry(math.pi / 2), [(0.15, 0), (0.15, 0.06), (0.12, 0.20), (0.07, 0.30),
                                                                            (0, 0.32)], 40)
        # o vão: parede do banco (ou do deque), laterais e a borracha da tampa
        c = self.nova("engine_vao_traseiro", "motor", nota="vão do motor traseiro: paredes, vedação de borracha")
        ztop = M["z_cintura"] if not cab else M["z_piso"] + 0.30
        c.caixa("pintura_interna", T(xa, 0, (zf + ztop) / 2), 0.015, 2 * yb, ztop - zf, 0.006)
        for s in (1, -1):
            c.caixa("pintura_interna", T((xa + xb) / 2, s * yb, zf + 0.30), xa - xb, 0.015, 0.40, 0.006)
            self._soldas(c, V(xb + 0.05, s * (yb - 0.008), zf + 0.495), V(xa - 0.05, s * (yb - 0.008), zf + 0.495), (0, -s, 0))
        if cab:
            self.bateria(T(xa - 0.14, yb - 0.17, zf + 0.12), alvo_pos=Mm @ V(0.15, -0.20, -0.05), alvo_massa=V(xa - 0.04, yb - 0.04, zf + 0.1))
        m = self.nova("engine_mangueiras", "motor", nota="mangueira de combustível, cabo do acelerador, dutos do aquecimento")
        m.tubo("borracha", [Mm @ V(0.10, 0.0, 0.42), Mm @ V(0.30, 0.15, 0.30), (xa + 0.02, 0.2, zf + 0.10)], 0.004, seg=6)
        for s in (1, -1):
            m.tubo("borracha", [L(0.20, s * 0.22, -0.18), L(0.35, s * 0.30, -0.10), (xa + 0.05, s * (yb - 0.06), zf + 0.05)], 0.028, seg=14)
        m.tubo("metal_preto", [L(0.12, 0.05, 0.34), (xa + 0.02, 0.05, zf + 0.20)], 0.0025, seg=6, sub=1)
        self.motor_traseiro_escape = Mm

    # ================================================================================================================ EMBAIXO
    def embaixo(self):
        M = self.M
        p = self.nova("under_assoalho", "embaixo")
        x0 = M["x_tras"] + 0.22
        x1 = M["x_corta_fogo"] + 0.02
        ym = M["W"] - 0.12
        zb = M["z_piso"] - 0.035
        tun_h = self.tun_h
        x_sobe = M["x_encosto_t"] + 0.5 if M["carroceria"] in ("hatch", "sedan", "jipe") else -99.0
        if M["carroceria"] == "cabine_avancada":
            x1 = M["x_frente"] - 0.15

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
            if x < x_sobe:
                z += (M["z_mala"] - M["z_piso"] + 0.02) * _limitar((x_sobe - x) / 0.25, 0, 1)
            if ay > ym - 0.05:
                z -= 0.03 * (ay - (ym - 0.05)) / 0.05
            return V(x, y, z)
        p.grade("chassi", 60, 30, ponto, 0.01, normal_fn=lambda u, v: (0, 0, 1))
        # pontos de macaco reforçados nas pontas da soleira
        for s in (1, -1):
            for xx in (M["xd"] - M["R"] - 0.25, M["xt"] + M["R"] + 0.25):
                p.caixa("chassi", T(xx, s * (ym - 0.03), zb - 0.025), 0.10, 0.05, 0.03, 0.006)
        # linhas de freio e de combustível ao longo do túnel, presas por grampos
        l = self.nova("under_linhas", "embaixo", nota="linhas de freio (aço) e de combustível ao longo do assoalho")
        for k, (yy, r) in enumerate(((0.22, 0.0035), (0.235, 0.0035), (0.26, 0.005))):
            xa_, xb_ = M["x_corta_fogo"] - 0.05, M["xt"] + 0.25
            pts = [V(xa_ + (xb_ - xa_) * j / 12, yy, zb - 0.012 - 0.002 * math.sin(j)) for j in range(13)]
            l.tubo("aluminio" if k < 2 else "metal_preto", pts, r, seg=6, sub=1)
            if k == 0:
                for j in range(1, 12, 3):
                    l.caixa("plastico", T(pts[j].x, 0.24, zb - 0.010), 0.02, 0.07, 0.012, 0.003)
        if M["carroceria"] == "jipe" or self.cfg["tracao"] == "4x4":
            self.chassi_escada()
        self.escapamento()
        self.tanque()
        self.suspensao()

    def chassi_escada(self):
        """Jipe: chassi de longarinas com travessas, sob a carroceria, com os furos e os suportes da carroceria."""
        M = self.M
        p = self.nova("under_chassi", "embaixo", nota="chassi de longarinas (jipe)")
        y = M["y_pneu_dentro_d"] - 0.24
        z = M["z_piso"] - 0.13
        x0, x1 = M["x_tras"] + 0.10, M["x_frente"] - 0.08
        for s in (1, -1):
            p.caixa("chassi", T((x0 + x1) / 2, s * y, z), x1 - x0, 0.06, 0.12, 0.008)
            for k in range(8):
                xx = x0 + 0.2 + (x1 - x0 - 0.4) * k / 7
                self._furo(p, T(xx, s * (y + 0.031), z) @ Rx(-s * math.pi / 2), 0.02, 0.012)
            for xx in (M["xd"] - 0.45, (M["xd"] + M["xt"]) / 2, M["xt"] + 0.45):
                p.caixa("borracha", T(xx, s * (y + 0.06), z + 0.07), 0.05, 0.05, 0.03, 0.006)
                p.caixa("chassi", T(xx, s * (y + 0.05), z + 0.04), 0.06, 0.08, 0.008, 0.002)
        for xx in (x1 - 0.05, M["xd"] - 0.55, (M["xd"] + M["xt"]) / 2, M["xt"] + 0.35, x0 + 0.05):
            p.caixa("chassi", T(xx, 0, z), 0.06, 2 * y, 0.08, 0.008)

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
        elif onde == "atras":
            # furgão de motor traseiro: tanque sobre o câmbio, na frente do motor, sob o piso de carga
            xc = M["xt"] + 0.35
            Mt = T(xc, 0.0, M["z_piso"] - 0.06)
            p.almofada("metal_preto", Mt, 0.30, 0.90, 0.16, 0.12, 0.15)
            bocal = [Mt @ V(0.0, 0.40, 0.05), V(xc - 0.10, M["W"] - 0.10, M["z_cintura"] - 0.35)]
        else:
            xc = M["xt"] - 0.48
            Mt = T(xc, 0, M["z_mala"] - 0.14)
            p.almofada("metal_preto", Mt, 0.38, 0.85, 0.20, 0.12, 0.15)
            bocal = [Mt @ V(0.0, 0.38, 0.08), V(xc - 0.05, M["W"] - 0.10, M["z_mala"] + 0.10)]
        p.tubo("borracha", bocal, 0.022, seg=12)
        p.tubo("aluminio", [bocal[0] + V(0.03, -0.1, -0.02), V(M["x_corta_fogo"] - 0.1, 0.26, M["z_piso"] - 0.05)], 0.004, seg=6, sub=1)

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
        if tr == "4x4":
            # eixo rígido na frente com o diferencial, a caixa de transferência e o cardã dianteiro
            f4 = self.nova("under_eixo_dianteiro", "embaixo", nota="eixo rígido dianteiro, diferencial, caixa de transferência, cardã")
            f4.tubo("metal_preto", [(xd, -(yi - 0.06), zr), (xd, yi - 0.06, zr)], 0.042, seg=16, sub=1)
            Md = T(xd - 0.02, 0.10, zr) @ Ry(-math.pi / 2)
            f4.revolucao("ferro", Md, [(0, -0.12), (0.08, -0.12), (0.14, -0.04), (0.14, 0.05), (0.10, 0.10), (0.05, 0.16), (0, 0.16)], 32)
            f4.revolucao("metal_preto", Md @ T(0, 0, -0.14), [(0, 0), (0.13, 0), (0.12, 0.02), (0, 0.02)], 32)
            xtc = M["x_encosto_d"] + 0.35
            f4.caixa("aluminio", T(xtc, 0.10, M["z_piso"] - 0.10), 0.24, 0.22, 0.20, 0.03)
            f4.tubo("metal_preto", [(xtc + 0.12, 0.12, M["z_piso"] - 0.12), (xd - 0.17, 0.10, zr)], 0.03, seg=14, sub=1)
            for xx in (xtc + 0.13, xd - 0.18):
                f4.cilindro("fundido", T(xx, 0.115, M["z_piso"] - 0.12 if xx > xd - 0.5 else zr) @ Ry(math.pi / 2), 0.04, 0.05, 20, 0.006)
            for s in (1, -1):
                f4.tubo("metal_preto", [(xd - 0.50, s * (yi - 0.30), zr + 0.05), (xd, s * (yi - 0.20), zr - 0.03)], 0.022, seg=10, sub=1)
        if M["carroceria"] == "cabine_avancada":
            # eixo dianteiro de tubos com barras de torção (furgão de cabine avançada)
            f2 = self.nova("under_eixo_dianteiro", "embaixo", nota="eixo dianteiro de dois tubos com barras de torção")
            for dx in (-0.09, 0.09):
                f2.tubo("metal_preto", [(xd + dx, -(yi - 0.12), zr + 0.06), (xd + dx, yi - 0.12, zr + 0.06)], 0.035, seg=14, sub=1)
            for s in (1, -1):
                f2.caixa("metal_preto", T(xd, s * (yi - 0.12), zr + 0.06), 0.30, 0.06, 0.09, 0.01)
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
    var = VARIANTE_GRUPO.get(peca.grupo)
    for nm in peca.mats:
        if var and nm in SUJAVEIS[var]:
            nm = f"{nm}_{var}"
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


def recolher_na_casca(objs, corte_objs, folga=0.006, alcance=0.04, grupos=("habitaculo", "porta", "porta_malas")):
    """
    Peças de dentro que encostam ou passam da chapa (o teto e o para-lama do Meshy têm calombos de 1 a 2 cm, e o forro, o quebra-sol e o
    painel apareciam por fora em manchas): cada vértice a menos de `alcance` da face de fora da casca (tinta e vidro) e a menos de
    `folga` por dentro dela vai para `folga` por dentro, pela normal da chapa. Devolve quantos vértices andaram, por peça.
    """
    import bpy
    import bmesh
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    for nome, ob in corte_objs.items():
        if nome.startswith(("wheel", "hubcap")):
            continue
        b = bmesh.new()
        b.from_mesh(ob.data)
        b.transform(ob.matrix_world)
        mats = ob.data.materials

        def de_fora(f):
            # tinta e vidro; e o plástico escuro acima da cintura (borrachas dos vidros e aba do teto), que o forro atravessava nos cantos
            if not (f.material_index < len(mats) and mats[f.material_index]):
                return False
            mn = mats[f.material_index].name
            return mn.startswith(("pintura", "vidro")) or (mn == "chassi" and f.calc_center_median().z > 0.9)
        fora = [f for f in b.faces if not de_fora(f)]
        bmesh.ops.delete(b, geom=fora, context="FACES")
        me = bpy.data.meshes.new("_casca_fora")
        b.to_mesh(me)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        b.free()
    arv = BVHTree.FromBMesh(bm)
    bm.free()
    andou = {}
    for ob in objs:
        if ob.get("grupo") not in grupos:
            continue
        M, Mi = ob.matrix_world, ob.matrix_world.inverted()
        n = 0
        for v in ob.data.vertices:
            w = M @ v.co
            loc, nor, _, d = arv.find_nearest(w, alcance)
            if loc is None:
                continue
            s_ = (w - loc).dot(nor)
            if s_ > -folga:
                v.co = Mi @ (w - nor * (s_ + folga))
                n += 1
        if n:
            ob.data.update()
            andou[ob.name] = n
    return andou


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
                              export_image_format="JPEG", export_jpeg_quality=JPEG_QUALIDADE, export_extras=True, export_yup=True,
                              export_vertex_color="MATERIAL")


def assar_sujeira(objs, amostras=16, distancia=0.22):
    """
    Oclusão ambiente (Cycles, com a casca do carro na cena) assada nos vértices de cada peça, no atributo "sujeira": frestas,
    cantos e o que fica embaixo de outra peça escurecem (pó e encardido de uso). O vão do motor e o embaixo escurecem mais.
    """
    import bpy
    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = amostras
    mundo = bpy.data.worlds.new("ao")
    mundo.light_settings.distance = distancia
    antes = cena.world
    cena.world = mundo
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        a = o.data.color_attributes.get(ATRIBUTO_SUJEIRA) or o.data.color_attributes.new(ATRIBUTO_SUJEIRA, "BYTE_COLOR", "CORNER")
        o.data.color_attributes.active_color = a
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
    import numpy as np
    for o in objs:
        a = o.data.color_attributes[ATRIBUTO_SUJEIRA]
        buf = np.empty(len(a.data) * 4, dtype=np.float32)
        a.data.foreach_get("color", buf)
        c = buf.reshape(-1, 4)
        ao = np.clip(c[:, 0], 0.0, 1.0)
        forca = 0.55 if o.get("grupo") in ("motor", "embaixo", "freios") else 0.40
        v = 1.0 - forca * (1.0 - ao) ** 1.2
        c[:, 0] = c[:, 1] = c[:, 2] = v
        c[:, 3] = 1.0
        a.data.foreach_set("color", c.ravel())
    cena.world = antes
    bpy.data.worlds.remove(mundo)


def sujeira_branca(objs):
    """Sem o cozimento (--sem-sujeira): o atributo existe e é branco, para a cor não ficar preta."""
    import numpy as np
    for o in objs:
        a = o.data.color_attributes.get(ATRIBUTO_SUJEIRA) or o.data.color_attributes.new(ATRIBUTO_SUJEIRA, "BYTE_COLOR", "CORNER")
        a.data.foreach_set("color", np.ones(len(a.data) * 4, dtype=np.float32))


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
    bg.inputs["Strength"].default_value = 0.9
    cena.world = mundo
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 4.5
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
        M["previa_faces_do_para_brisa_tiradas"] = len(tira)
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
    tampa = por_nome.get("hood") if M["carroceria"] != "cabine_avancada" else None
    eixo_x = M["x_corta_fogo"] + 0.02
    ang = math.radians(55)
    vis = (M["x_frente"] + 1.25, 0.85, M["H"] + 0.75)
    alvo = ((M["x_corta_fogo"] + M["x_radiador"]) / 2, 0, M["z_saia"] + 0.15)
    piv = None
    if tampa:
        piv = bpy.data.objects.new("piv_tampa", None)
        cena.collection.objects.link(piv)
        piv.location = (eixo_x, 0, M["z_capo_tras"] + 0.03)
        bpy.context.view_layer.update()
        juntos = [tampa] + [o for o in kit_objs if o.get("segue") == "hood"]
        for o in juntos:
            o.parent = piv
            o.matrix_parent_inverse = piv.matrix_world.inverted()
        piv.rotation_euler = (0, -ang, 0)
        bpy.context.view_layer.update()
    if M["carroceria"] != "cabine_avancada":      # na cabine avançada não há capô: a frente é a cabine
        camera(cena, vis, alvo, 22)
        lz = luz_area(cena, "luz_motor", (vis[0], vis[1] - 0.4, vis[2] + 0.6), alvo, 150, 1.5)
        render("motor" if not M["motor_traseiro"] else "capo")
        bpy.data.objects.remove(lz)
    if tampa:
        for o in juntos:
            o.parent = None
            o.matrix_world = Matrix.Identity(4)
        bpy.data.objects.remove(piv)
    # 3b. motor traseiro: tampa de trás fora (o mapa do corte do Besouro foi acertado à mão: a casca não segue por baixo dela)
    if M["motor_traseiro"]:
        tr = por_nome.get("trunk")
        if tr:
            tr.hide_render = True
        b = M["tampa_tras"]
        if M["carroceria"] == "cabine_avancada":     # o motor fica baixo, sob o deque: olhar de trás, quase na altura dele
            vis = (b[0] - 1.3, 0.55, M["z_piso"] + 0.45)
            alvo = (b[0] + 0.45, 0, M["z_piso"] - 0.10)
        else:
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
    p.add_argument("--sem-sujeira", action="store_true", help="não assa a oclusão nos vértices (mais rápido; cor sem encardido)")
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
    mats = Materiais(estilo, pint, cfg["epoca"])
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
        if not len(p.bm.faces):        # peça vazia (o carro não tem a lanterna no mapa, por exemplo)
            continue
        ob = finalizar(p, mats)
        col.objects.link(ob)
        objs.append(ob)
    if corte_objs:
        andou = recolher_na_casca(objs, corte_objs)
        print("dentro da casca (vértices recolhidos):", andou)
    if a.sem_sujeira:
        sujeira_branca(objs)
    else:
        assar_sujeira(objs)
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
        rel["previa_faces_do_para_brisa_tiradas"] = M.get("previa_faces_do_para_brisa_tiradas", 0)
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
