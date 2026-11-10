"""
Checagem automática de um carro do acervo, para o CI (10/11/2026; o Felipe viu o Cuiabano vermelho de trás, na rua: lanternas saltadas
para fora da lataria, borrachas dos vidros flutuando, faces quebradas no arco da roda, retrovisor e faróis com partes transparentes).
Sem render: a malha do corte (veiculos/sketchfab/quebravel/<id>/<id>.glb), com o kit completo como anteparo quando existe.

    python -I ferramentas/checar_carro.py -- <corte.glb> [--kit <completo.glb>] [--json saida.json] [--consertar saida.glb [--so-c1] [--sem-luz] [--lente-de-lado]]

  O portão da revisão dos carros (Detonauto/docs/visual/revisao-carros.md, seção 5, 10/11/2026), sobre o arquivo final (o corte com o
  passe de detalhe junto) e com o kit de anteparo:
  C1 luz e borracha encostadas: o farol, a lanterna e a lente do pisca não passam C1_MM do envelope da lataria de lado (a meia largura da
     chapa em volta, 4 cm para cada lado) nem C1_PONTA_MM na ponta (a lente saliente é desenho); a lente virada para o lado na tampa do
     bloco que saía (a "tira acesa" de lado); a borracha do vidro deitada na chapa (era o C3). Com --consertar, a luz encolhe só de lado até
     o envelope e a tampa de lado vira plástico preto. --capsulas: as luzes em cápsula de propósito (o Besouro) ficam de fora;
     --sem-luz: só o vidro é consertado; --lente-de-lado: a tampa de lado das lanternas vira plástico mesmo sem o bloco sair.
  C2 retrovisor com carcaça de C2_CM ou mais de fundo (o retrovisor padrão do passe_detalhe.py tem 8,5 a 10 cm).
  C3 vidro sem camadas: até C3_FRACAO das faces com outra paralela a menos de 3 mm por cima (o risco branco do reflexo). Com --consertar,
     a camada de baixo sai.
  C4 pneu com o material pneu e albedo de C4_ALBEDO ou menos; roda com C4_RODA_CM ou mais de fundo.
  C5 material próprio: para-choque não pintado, farol e lanterna com lente, vidro com vidro (o carro "de gesso").
  C6 nada além de roda e ponteira a menos de C6_CHAO do chão (o tanque pendurado do Cuiabano).
  C7 lanterna vermelha, pisca âmbar, ré branca e farol com fundo.
  C8 balanço do para-choque de C8_CM ou menos.
  C9 face de costas à vista (era o C1): de 26 pontos em volta do carro (a 6 m), a face que a câmera enxerga pelo lado de trás e nunca
     pela frente. O Unreal desenha um lado só: essa face some. Com --consertar, vira de lado (ou ganha a cópia virada, vista de dentro).
  C10 arco de roda (era o C4): sem face degenerada nem borda em dente de serra; com --consertar, a borda é alisada no raio.
  --so-c1: o conserto só do que vai para os cortes do jogo (C1 e C3), sem virar faces nem alisar o arco.
Saída: um resumo por peça; o código de saída é 1 se alguma regra falha (é o que derruba o CI).
"""
import json
import math
import os
import sys

import bpy
import bmesh  # depois do bpy (no bpy do PyPI o bmesh só existe com ele carregado)
from mathutils import Vector
from mathutils.bvhtree import BVHTree

C1_CM2 = 4.0
C1_MM = 5.0        # revisão de 10/11/2026, C1: nada a mais de 5 mm para fora da lataria
C1_FRACAO = 0.01   # tolera 1 % dos vértices (o arredondamento da lente)
C1_TOLERA = 3
C1_JANELA = 2      # o envelope olha 4 cm em volta
C1_PONTA_MM = 40.0 # na ponta (frente e traseira) a lente saliente é desenho (envolvente, cápsula): só reprova acima de 4 cm, sem consertar
C2_CM = 8.0        # retrovisor: carcaça com 8 cm de profundidade
C3_FRACAO = 0.10   # vidro em camadas
C4_ALBEDO = 0.05
C4_RODA_CM = 3.0
C6_CHAO = 0.08     # nada além de roda e ponteira a menos de 8 cm do chão (o assoalho do kit fica a 9, atrás da saia)
C8_CM = 12.0       # balanço do para-choque
C1_LADO_CM2 = 6.0  # lente virada para o lado na borda de fora
C1_LONGE = 0.08    # passou disso, não há chapa em volta: a peça é a própria ponta
C1B_MM = 8.0
C1B_FRACAO = 0.25
C4_MAX = 20
C4_DENTE_MM = 6.0
C4_DENTES_MAX = 6
LUZES = ('headlight', 'taillight')

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
entrada = argv[0]
opt = lambda n: argv[argv.index(n) + 1] if n in argv else None
KIT, SAIDA_JSON, CONSERTAR = opt('--kit'), opt('--json'), opt('--consertar')
# --capsulas: o farol e a lanterna são cápsulas por fora da lataria de propósito (o Besouro, nos para-lamas): o C1 não mede nem mexe nelas
CAPSULAS = '--capsulas' in argv


IMPORTADOS = {}


def carregar(path):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    IMPORTADOS[path] = [o for o in bpy.data.objects if o not in antes]  # tudo, com os LOD1 e os vazios (o conserto tira o kit inteiro)
    return [o for o in IMPORTADOS[path] if o.type == 'MESH' and not o.name.endswith('_LOD1')]


bpy.ops.wm.read_factory_settings(use_empty=True)
_tudo = carregar(entrada)
corte = [o for o in _tudo if not o.name.startswith('wheel_')]
rodas = [o for o in _tudo if o.name.startswith('wheel_')]  # o pneu e o aro (C4 e o chão do C6)
kit = carregar(KIT) if KIT and os.path.exists(KIT) else []


def mundo(o):
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    b.faces.ensure_lookup_table()
    b.verts.ensure_lookup_table()
    return b


def nomes_mat(o):
    return [(s.material.name.split('.')[0] if s.material else '') for s in o.material_slots]


def e_vidro(o):
    return o.name.startswith('glass') or all(n == 'vidro' for n in nomes_mat(o) if n)


BM = {o.name: mundo(o) for o in corte + kit}
# o anteparo: tudo menos o vidro (o raio atravessa o vidro); o índice global da face diz a peça e a face local
verts, polys, dono = [], [], []
for o in corte + kit:
    if e_vidro(o):
        continue
    b = BM[o.name]
    base = len(verts)
    verts.extend(v.co.copy() for v in b.verts)
    for f in b.faces:
        polys.append([base + v.index for v in f.verts])
        dono.append((o.name, f.index))
ARV = BVHTree.FromPolygons(verts, polys, epsilon=0.0)
BM.update({o.name: mundo(o) for o in rodas})
todos = [v for b in BM.values() for v in b.verts]
lo = Vector((min(v.co.x for v in todos), min(v.co.y for v in todos), min(v.co.z for v in todos)))
hi = Vector((max(v.co.x for v in todos), max(v.co.y for v in todos), max(v.co.z for v in todos)))
centro = (lo + hi) / 2

# 26 câmeras: 3 alturas x 8 direções e o alto de cima, a 6 m do meio
CAMS = []
for el in (-0.15, 0.25, 0.65):
    for k in range(8):
        a = math.pi * 2 * k / 8 + 0.2
        CAMS.append(centro + Vector((math.cos(a) * math.cos(el), math.sin(a) * math.cos(el), math.sin(el))) * 6.0)
CAMS.append(centro + Vector((0, 0, 6)))
CAMS.append(centro + Vector((0.5, 0.3, 5.5)))
# de dentro da cabine (a vista do motorista e a do interior na garagem): a face vista de frente daqui e de costas de fora precisa dos
# dois lados (vira duas faces, uma para cada lado), em vez de só virar
ZCAB = lo.z + 0.72 * (hi.z - lo.z)
CAMS_DENTRO = [Vector((centro.x + dx, dy, ZCAB)) for dx in (-0.35, 0.25) for dy in (-0.28, 0.28)]

MEIA_LARGURA = (hi.y - lo.y) / 2
def soldada(b0):
    """Cópia soldada (0,2 mm): a malha do corte vem em triângulos soltos, e sem soldar toda aresta é borda."""
    b = b0.copy()
    bmesh.ops.remove_doubles(b, verts=b.verts, dist=0.0002)
    b.verts.ensure_lookup_table()
    return b


def dentes_do_arco(b, R, eixos):
    """
    A borda solta do arco (a beirada da chapa sobre a roda): o raio de cada vértice da borda (no plano XZ, do cubo mais perto) contra a
    mediana dos vizinhos de borda até 2 passos. Devolve (os índices que fogem mais de C4_DENTE_MM, {índice: (raio, mediana, x do eixo)}).
    """
    viz = {}
    for e in b.edges:
        if len(e.link_faces) == 1:
            a, c2 = e.verts
            viz.setdefault(a.index, []).append(c2.index)
            viz.setdefault(c2.index, []).append(a.index)
    raio = {}
    for i in viz:
        p = b.verts[i].co
        r, x = min((math.hypot(p.x - x, p.z - R), x) for x in eixos)
        if R - 0.02 <= r <= R + 0.15 and abs(p.y) > MEIA_LARGURA - 0.25 and p.z > 0.05:
            raio[i] = (r, x)
    alvo = {}
    for i, (r, x) in raio.items():
        anel = set(viz[i])
        for j in list(anel):
            anel.update(viz.get(j, []))
        anel.discard(i)
        rs = sorted(raio[j][0] for j in anel if j in raio)
        if len(rs) >= 3:
            alvo[i] = (r, rs[len(rs) // 2], x)
    return [i for i, (r, m, _) in alvo.items() if abs(r - m) * 1000 > C4_DENTE_MM], alvo


def alisar_arco(o, R, eixos, passadas=8):
    """C4 com --consertar: a borda do arco puxada para a mediana dos vizinhos, só no raio (o ângulo e o Y ficam), 8 passadas."""
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    bmesh.ops.remove_doubles(b, verts=b.verts, dist=0.0002)
    movidos = set()
    for _ in range(passadas):
        b.verts.ensure_lookup_table()
        _, alvo = dentes_do_arco(b, R, eixos)
        for i, (r, m, x) in alvo.items():
            if abs(r - m) * 1000 <= C4_DENTE_MM * 0.5 or r < 1e-6:
                continue
            p = b.verts[i].co
            k = (r + (m - r) * 0.5) / r  # metade do caminho por passada: o vértice não passa por cima dos vizinhos de dentro
            p.x = x + (p.x - x) * k
            p.z = R + (p.z - R) * k
            movidos.add(i)
    # a solda e o puxão deixam triângulos de área quase zero na beirada: saem (dissolvidos nos vizinhos)
    bmesh.ops.dissolve_degenerate(b, dist=0.0003, edges=b.edges[:])
    b.transform(o.matrix_world.inverted())
    b.to_mesh(o.data)
    b.free()
    o.data.update()
    return len(movidos)


relatorio = {'carro': os.path.basename(entrada), 'falhas': [], 'pecas': {}}


def falha(regra, peca, texto):
    relatorio['falhas'].append({'regra': regra, 'peca': peca, 'texto': texto})


# ---------------------------------------------------------------------------------------------------------------- C9 (era C1)
viradas = {}
duplas = {}
for o in (corte if '--so-c1' not in argv else []):  # o conserto só do C1 não precisa dos raios do C9
    b = BM[o.name]
    vidro = e_vidro(o)
    if vidro:
        continue  # o vidro do jogo tem os dois lados (M_DNDentGlass, two_sided)
    nm = nomes_mat(o)
    por_mat = {}
    costas = []
    dois_lados = []
    area = 0.0
    # a face que já tem a gêmea virada (o mesmo meio, a normal oposta) já tem os dois lados
    from mathutils.kdtree import KDTree
    kd_f = KDTree(len(b.faces))
    for f in b.faces:
        kd_f.insert(f.calc_center_median(), f.index)
    kd_f.balance()

    def tem_gemea(f, c):
        return any(j != f.index and b.faces[j].normal.dot(f.normal) < -0.9 for _, j, _ in kd_f.find_range(c, 0.0002))

    def visto_de(f, c, cams):
        fr = tr = 0
        for p in cams:
            d = c - p
            dist = d.length
            if dist < 1e-6:
                continue
            d /= dist
            hit = ARV.ray_cast(p, d, dist + 0.002)
            if hit[0] is None or not (dono[hit[2]] == (o.name, f.index) or (hit[0] - c).length < 0.001):
                continue
            if f.normal.dot(-d) >= 0:
                fr += 1
            else:
                tr += 1
        return fr, tr

    for f in b.faces:
        c = f.calc_center_median()
        n = f.normal
        frente = tras = 0
        for p in CAMS:
            d = c - p
            dist = d.length
            if dist < 1e-6:
                continue
            d /= dist
            hit = ARV.ray_cast(p, d, dist + 0.002)
            if hit[0] is None:
                continue
            if vidro:
                visivel = (hit[0] - p).length >= dist - 0.002  # nada opaco antes do vidro
            else:
                visivel = dono[hit[2]] == (o.name, f.index) or (hit[0] - c).length < 0.001
            if not visivel:
                continue
            if n.dot(-d) >= 0:
                frente += 1
            else:
                tras += 1
        if tras and not frente and nm[f.material_index if f.material_index < len(nm) else 0] != 'MI_DNVao' and not tem_gemea(f, c):
            (dois_lados if visto_de(f, c, CAMS_DENTRO)[0] else costas).append(f.index)
            area += f.calc_area()
            m = nm[f.material_index] if f.material_index < len(nm) else ''
            por_mat[m] = por_mat.get(m, 0.0) + f.calc_area() * 1e4
            if os.environ.get('CHK_DEBUG') == o.name:
                print('DBG', o.name, m, tuple(round(x, 3) for x in c), tuple(round(x, 2) for x in n), round(f.calc_area() * 1e4, 1))
    cm2 = area * 1e4
    relatorio['pecas'].setdefault(o.name, {})['costas_a_vista_cm2'] = round(cm2, 2)
    relatorio['pecas'][o.name]['costas_por_material_cm2'] = {k: round(v, 1) for k, v in por_mat.items()}
    if cm2 > C1_CM2:
        falha('C9', o.name, '%d face(s) de costas à vista, %.1f cm² (some no Unreal; %d delas também vistas de frente de dentro)'
              % (len(costas) + len(dois_lados), cm2, len(dois_lados)))
        viradas[o.name] = [(b.faces[i].calc_center_median().copy(), b.faces[i].normal.copy()) for i in costas]
        duplas[o.name] = [(b.faces[i].calc_center_median().copy(), b.faces[i].normal.copy()) for i in dois_lados]

# ---------------------------------------------------------------------------------------------------------------- C1
# luz, lente de canto, moldura e borracha encostadas na lataria (revisão de 10/11/2026, item 1: a sinaleira do Cuiabano saía 4 cm pela
# lateral, e a tampa branca do bloco virava uma tira acesa de lado; o C2 antigo só media para a frente ou para trás e não pegava). Para
# cada vértice dessas faces, a distância com sinal até a chapa (pintura das peças da lataria e os para-choques), com a normal da chapa
# virada para fora do carro (a casca do corte tem faces de costas, então o sinal não vem da ordem dos vértices)
CHAPA = ('body', 'bumper', 'fender', 'trunk', 'hood', 'tailgate', 'door_')
# o envelope da lataria em células de 2 cm: a meia largura de cada lado por (x, z) e a ponta da frente e de trás por (y, z). A luz entra num
# furo da chapa, então a chapa mais perto do vértice (o primeiro desenho) caía na borda do furo ou no capô e dobrava a peça no conserto; o
# envelope olha a chapa em volta (C1_JANELA células para cada lado), como o C2 antigo, mas vértice a vértice e também de lado
CEL = 0.02
LADO, PONTA = {}, {}
for o in corte:
    if not o.name.startswith(CHAPA):
        continue
    nm = nomes_mat(o)
    for f in BM[o.name].faces:
        m = nm[f.material_index] if nm and f.material_index < len(nm) else ''
        if m != 'pintura' and not o.name.startswith('bumper'):
            continue
        for v in f.verts:
            p = v.co
            k = (1 if p.y > 0 else -1, round(p.x / CEL), round(p.z / CEL))
            LADO[k] = max(LADO.get(k, 0.0), abs(p.y))
            k = (1 if p.x > centro.x else -1, round(p.y / CEL), round(p.z / CEL))
            PONTA[k] = max(PONTA.get(k, 0.0), abs(p.x - centro.x))
CHAPA_ARV = LADO or None
ENCOSTAR = {}


def envelope(tab, sinal, a, b):
    ia, ib = round(a / CEL), round(b / CEL)
    vals = [tab[k] for k in ((sinal, ia + da, ib + db) for da in range(-C1_JANELA, C1_JANELA + 1) for db in range(-C1_JANELA, C1_JANELA + 1))
            if k in tab]
    return max(vals) if vals else None


def fora_da_chapa(p):
    """Quanto o ponto passa do envelope da lataria de lado e na ponta (m; negativo = dentro; None = sem chapa em volta, ou a chapa a mais
    de C1_LONGE: ali a peça é a própria frente ou traseira, como o farol na grade, e não está saltada)."""
    sy = 1 if p.y > 0 else -1
    sx = 1 if p.x > centro.x else -1
    lat = envelope(LADO, sy, p.x, p.z)
    lon = envelope(PONTA, sx, p.y, p.z)
    dy = abs(p.y) - lat if lat is not None else None
    dx = abs(p.x - centro.x) - lon if lon is not None else None
    dy = dy if dy is not None and dy < C1_LONGE else None
    dx = dx if dx is not None and dx < C1_LONGE else None
    return dy, dx, sy, sx


def vertices_de_c1(o):
    """Os vértices que o C1 mede: a peça de luz inteira; no vidro, só a borracha (o plástico preto da borda)."""
    b = BM[o.name]
    if o.name.startswith(LUZES) and CAPSULAS:
        return []
    if o.name.startswith(LUZES):
        return list(b.verts)
    if e_vidro(o) or o.name.startswith('glass'):
        nm = nomes_mat(o)
        return list({v for f in b.faces if nm and f.material_index < len(nm) and nm[f.material_index] == 'chassi' for v in f.verts})
    if o.name.startswith('bumper'):
        nm = nomes_mat(o)
        # a lente do pisca no para-choque
        return list({v for f in b.faces if nm and f.material_index < len(nm) and nm[f.material_index].startswith('luz') for v in f.verts})
    return []


if CHAPA_ARV is not None:
    for o in corte:
        vs = vertices_de_c1(o)
        if len(vs) < 4:
            continue
        medidas = [(v,) + fora_da_chapa(v.co) for v in vs]
        # de lado, 5 mm (a revisão); na ponta, a lente pode ficar saliente como nas de verdade: 12 mm (o C2 antigo), contado como o que passa
        # disso somado aos 5 mm, para o limite ser um só
        vidro_c1 = o.name.startswith('glass')  # a borracha do vidro só de lado: na ponta o vidro fica acima da tampa, fora do envelope
        exc = [max(d for d in (dy, (dx - C1_PONTA_MM / 1000 + C1_MM / 1000) if dx is not None and not vidro_c1 else None) if d is not None)
               for _, dy, dx, _, _ in medidas if dy is not None or (dx is not None and not vidro_c1)]
        if not exc:
            continue
        fora = [e for e in exc if e > C1_MM / 1000]
        pior = max(exc) * 1000
        r = relatorio['pecas'].setdefault(o.name, {})
        r['fora_da_lataria_mm'] = round(pior, 1)
        r['fora_da_lataria_vertices'] = len(fora)
        if len(fora) > max(C1_TOLERA, C1_FRACAO * len(exc)):
            falha('C1', o.name, '%d vértice(s) a mais de %.0f mm para fora da lataria (pior: %.0f mm)' % (len(fora), C1_MM, pior))
            if o.name.startswith(LUZES):
                # o conserto: a peça de luz encolhe só no eixo em que sai (de lado ou na ponta), a partir do lado de dentro dela, até cada
                # vértice ficar a 1 mm do envelope. Escala positiva: nenhuma face vira (achatar vértice a vértice dobrava a peça)
                pv = [v.co for v in BM[o.name].verts]
                fat = {}
                for eixo, idx, sinal_i in (('y', 1, 3),):  # só de lado: o bloco que sai da lateral (10/11, o Cuiabano)
                    cs = [abs(v.co.y) if eixo == 'y' else abs(v.co.x - centro.x) for v in BM[o.name].verts]
                    dentro = min(cs)
                    k = 1.0
                    for m in medidas:
                        d = m[idx]
                        if d is not None and eixo == 'x':
                            d -= C1_PONTA_MM / 1000 - 0.002  # na ponta, encolhe só o que passa de 12 mm (fica a 10)
                        if d is None or d <= 0.001:
                            continue
                        c = abs(m[0].co.y) if eixo == 'y' else abs(m[0].co.x - centro.x)
                        if c - dentro > 0.005:
                            k = min(k, 1.0 - (d - 0.001) / (c - dentro))
                    if k < 1.0:
                        fat[eixo] = (max(k, 0.3), dentro, medidas[0][sinal_i])
                if fat:
                    ENCOSTAR[o.name] = fat

# C1, a lente de lado: a face de lente ou de refletor virada para o lado (normal com |y| > 0,7) na borda de fora do farol ou da lanterna é
# a "tira branca acesa" que o Felipe viu de lado (10/11/2026); a de verdade mostra só a carcaça escura. Com --consertar, vira plástico preto
LENTE_DE_LADO = {}
for o in corte:
    if not o.name.startswith(LUZES) or CAPSULAS:
        continue
    nm = nomes_mat(o)
    b = BM[o.name]
    borda = max(abs(v.co.y) for v in b.verts) - 0.015
    faces, area = [], 0.0
    for f in b.faces:
        m = nm[f.material_index] if nm and f.material_index < len(nm) else ''
        if not (m.startswith('luz') or m in ('refletor', 'lente_farol')):
            continue
        if abs(f.normal.y) > 0.7 and abs(f.calc_center_median().y) > borda and f.normal.y * f.calc_center_median().y > 0:
            faces.append((f.calc_center_median().copy(), f.normal.copy()))
            area += f.calc_area()
    relatorio['pecas'].setdefault(o.name, {})['lente_de_lado_cm2'] = round(area * 1e4, 1)
    # a lente envolvente rente à lateral é desenho (Barão, Caipora): só conta a da peça que saía pela lateral (a tampa do bloco)
    # --lente-de-lado: a tampa de lado das lanternas vira plástico mesmo sem o bloco sair (o Cuiabano, dos dois lados: 10/11/2026)
    if area * 1e4 > C1_LADO_CM2 and ('y' in ENCOSTAR.get(o.name, {}) or ('--lente-de-lado' in argv and o.name.startswith('taillight'))):
        falha('C1', o.name, 'lente de lado: %.0f cm² de lente virada para fora pela lateral (máx. %.0f); de lado ela acende como uma tira'
              % (area * 1e4, C1_LADO_CM2))
        LENTE_DE_LADO[o.name] = faces

# ---------------------------------------------------------------------------------------------------------------- C1, a borracha deitada (era C3)
bordas = []
for o in corte:
    if not e_vidro(o):
        continue
    for e in BM[o.name].edges:
        if len(e.link_faces) == 1:
            bordas.append((e.verts[0].co + e.verts[1].co) / 2)
if bordas:
    from mathutils.kdtree import KDTree
    kd = KDTree(len(bordas))
    for i, p in enumerate(bordas):
        kd.insert(p, i)
    kd.balance()
    # a chapa e o vidro (sem o plástico): onde a borracha tem de deitar
    pv, pp = [], []
    for o in corte:
        nm = nomes_mat(o)
        b = BM[o.name]
        for f in b.faces:
            m = nm[f.material_index] if nm and f.material_index < len(nm) else ''
            if m in ('pintura', 'vidro'):
                base = len(pv)
                pv.extend(v.co.copy() for v in f.verts)
                pp.append(list(range(base, base + len(f.verts))))
    chapa = BVHTree.FromPolygons(pv, pp, epsilon=0.0) if pp else None
    for o in corte:
        nm = nomes_mat(o)
        if 'chassi' not in nm or chapa is None:
            continue
        total = longe = 0
        for f in BM[o.name].faces:
            if nm[f.material_index] != 'chassi':
                continue
            c = f.calc_center_median()
            if kd.find(c)[2] > 0.02:
                continue
            total += 1
            hit = chapa.find_nearest(c, 0.05)
            if hit[0] is None or hit[3] * 1000 > C1B_MM:
                longe += 1
        if total >= 20:
            fr = longe / total
            relatorio['pecas'].setdefault(o.name, {})['borracha_longe'] = round(fr, 3)
            if fr > C1B_FRACAO:
                falha('C1', o.name, 'borracha flutuando: %.0f%% da borracha em volta do vidro a mais de %.0f mm da chapa (%d de %d faces)' % (fr * 100, C1B_MM, longe, total))

# ---------------------------------------------------------------------------------------------------------------- C10 (era C4)
rodas_json = os.path.join(os.path.dirname(entrada), os.path.splitext(os.path.basename(entrada))[0] + '_wheels.json')
if os.path.exists(rodas_json):
    W = json.load(open(rodas_json, encoding='utf-8'))
    R = W['wheel_radius_cm'] / 100
    ARCO = {}
    eixos = (W['front_axle_cm'] / 100, W['rear_axle_cm'] / 100)
    for o in corte:
        if not (o.name == 'body' or o.name.startswith('fender')):
            continue
        ruins = 0
        for f in BM[o.name].faces:
            c = f.calc_center_median()
            r = min(math.hypot(c.x - x, c.z - R) for x in eixos)
            if not (R <= r <= R + 0.12) or abs(c.y) < (hi.y - lo.y) / 2 - 0.25 or c.z < 0.02:
                continue
            area = f.calc_area()
            if area < 5e-8:
                ruins += 1
        dentes = len(dentes_do_arco(soldada(BM[o.name]), R, eixos)[0])
        relatorio['pecas'].setdefault(o.name, {})['arco_dentes'] = dentes
        if dentes > C4_DENTES_MAX:
            ARCO[o.name] = (R, eixos)
            falha('C10', o.name, 'borda do arco de roda em dente de serra: %d vértice(s) fogem mais de %.0f mm dos vizinhos (máx. %d)'
                  % (dentes, C4_DENTE_MM, C4_DENTES_MAX))
        relatorio['pecas'].setdefault(o.name, {})['arco_degeneradas'] = ruins
        if ruins > C4_MAX:
            falha('C10', o.name, '%d face(s) degeneradas no arco de roda (máx. %d)' % (ruins, C4_MAX))

# ---------------------------------------------------------------------------------------------------------------- C2 a C8 (revisão de 10/11/2026)
def faces_de(o, *mats):
    nm = nomes_mat(o)
    return [f for f in BM[o.name].faces if nm and f.material_index < len(nm) and nm[f.material_index] in mats]


def mats_de(o):
    nm = nomes_mat(o)
    return {nm[f.material_index] for f in BM[o.name].faces if nm and f.material_index < len(nm)}


por_nome = {o.name: o for o in corte}
# C2 retrovisor com volume: a carcaça com 8 cm ou mais de profundidade (no eixo do carro), vista de lado e de trás
espelhos = [o for o in corte if o.name.startswith('mirror')]
if not espelhos:
    falha('C2', '-', 'sem retrovisor')
for o in espelhos:
    xs = [v.co.x for v in BM[o.name].verts]
    prof = (max(xs) - min(xs)) * 100
    relatorio['pecas'].setdefault(o.name, {})['profundidade_cm'] = round(prof, 1)
    if prof < C2_CM:
        falha('C2', o.name, 'retrovisor de chapa: %.1f cm de profundidade (mín. %.0f)' % (prof, C2_CM))

CAMADAS = {}
# C3 vidro sem camadas: a face de vidro com outra paralela a menos de 3 mm por cima (o vigia do corte tem 4 mil faces em camadas) acende
# como risco branco no reflexo; o reflexo e o tom do vidro são do material (MI_DNVidro) e se conferem no render
for o in corte:
    if not o.name.startswith('glass'):
        continue
    fs = faces_de(o, 'vidro')
    if len(fs) < 10:
        continue
    from mathutils.kdtree import KDTree
    kd = KDTree(len(fs))
    for k, f in enumerate(fs):
        kd.insert(f.calc_center_median(), k)
    kd.balance()
    camada = 0
    de_baixo = []
    for k, f in enumerate(fs):
        c = f.calc_center_median()
        for _, j, d in kd.find_range(c, 0.006):
            if j != k and fs[j].normal.dot(f.normal) > 0.95 and 0.0003 < abs((fs[j].calc_center_median() - c).dot(f.normal)) < 0.003:
                camada += 1
                # a de baixo (a outra está mais para fora, pela normal desta) sai no conserto; fica a de cima
                if (fs[j].calc_center_median() - c).dot(f.normal) > 0:
                    de_baixo.append((c.copy(), f.normal.copy()))
                break
    fr = camada / len(fs)
    relatorio['pecas'].setdefault(o.name, {})['vidro_em_camadas'] = round(fr, 3)
    if fr > C3_FRACAO:
        CAMADAS[o.name] = de_baixo
        falha('C3', o.name, 'vidro em camadas: %.0f%% das faces com outra a menos de 3 mm por cima (riscos brancos no reflexo)' % (fr * 100))

CAMADAS = globals().get('CAMADAS', {})
# C4 pneu e roda: o pneu com o material pneu e escuro (albedo de 0,05 ou menos) e a roda com 3 cm ou mais de profundidade
for o in rodas:
    if not o.name.startswith('wheel'):
        continue
    if o.name.endswith('_tire'):
        nm = nomes_mat(o)
        if 'pneu' not in nm:
            falha('C4', o.name, 'pneu sem o material pneu (%s)' % ', '.join(sorted(set(nm))))
        for sl in o.material_slots:
            m = sl.material
            if m and m.use_nodes and m.name.split('.')[0] == 'pneu':
                b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if b and not b.inputs['Base Color'].links:
                    c = b.inputs['Base Color'].default_value
                    alb = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
                    if alb > C4_ALBEDO:
                        falha('C4', o.name, 'pneu claro: albedo %.2f (máx. %.2f)' % (alb, C4_ALBEDO))
    elif o.name.endswith('_rim'):
        ys = [v.co.y for v in BM[o.name].verts]
        prof = (max(ys) - min(ys)) * 100
        relatorio['pecas'].setdefault(o.name, {})['profundidade_cm'] = round(prof, 1)
        if prof < C4_RODA_CM:
            falha('C4', o.name, 'roda chapada: %.1f cm de profundidade (mín. %.0f)' % (prof, C4_RODA_CM))

# C5 material próprio: para-choque, farol, lanterna, pneu e vidro não podem ser só pintura (o carro "de gesso")
for o in corte:
    ms = mats_de(o)
    precisa = None
    if o.name.startswith('bumper'):
        n = len(BM[o.name].faces)
        pint = len(faces_de(o, 'pintura'))
        if n and pint / n > 0.5:
            falha('C5', o.name, 'para-choque pintado: %.0f%% das faces com a pintura' % (100 * pint / n))
        continue
    if o.name.startswith(LUZES):
        precisa = [m for m in ms if m.startswith('luz') or m in ('refletor', 'lente_farol')]
    elif o.name.startswith('glass'):
        precisa = [m for m in ms if m == 'vidro']
    if precisa is not None and not precisa:
        falha('C5', o.name, 'sem material próprio (só %s)' % ', '.join(sorted(ms)))

# C7 lentes: lanterna com vermelha, pisca âmbar e ré branca; farol com fundo (refletor ou lente de farol)
tl = set().union(*[mats_de(o) for o in corte if o.name.startswith('taillight')]) if any(o.name.startswith('taillight') for o in corte) else set()
todas = set().union(*[mats_de(o) for o in corte])
hl = set().union(*[mats_de(o) for o in corte if o.name.startswith('headlight')]) if any(o.name.startswith('headlight') for o in corte) else set()
for falta, texto in ((not tl, 'sem lanterna'), (tl and 'luz_vermelha' not in tl, 'lanterna sem a lente vermelha'),
                     ('luz_ambar' not in todas, 'sem pisca âmbar'), (tl and 'luz_branca' not in tl, 'lanterna sem a luz de ré branca'),
                     (not hl, 'sem farol'), (hl and not ({'refletor', 'lente_farol'} & hl), 'farol sem fundo (refletor ou lente)')):
    if falta:
        falha('C7', '-', texto)

# C6 nada abaixo da soleira além de roda e ponteira; C8 balanço do para-choque
rj = os.path.join(os.path.dirname(entrada), os.path.splitext(os.path.basename(entrada))[0] + '_wheels.json')
if os.path.exists(rj):
    W = json.load(open(rj, encoding='utf-8'))
    R = W['wheel_radius_cm'] / 100
    xf, xt = W['front_axle_cm'] / 100, W['rear_axle_cm'] / 100
    xa, xb = min(xf, xt) + R + 0.05, max(xf, xt) - R - 0.05
    # o chão é o pé do pneu; perto dele (C6_CHAO) só a roda e a ponteira. A soleira da lataria não serve de régua: o interior e o assoalho do
    # kit ficam abaixo dela por dentro, e o defeito do Cuiabano era o tanque pendurado (revisão de 10/11/2026, item 8)
    pneus = [v.co.z for o in rodas if o.name.endswith('_tire') for v in BM[o.name].verts]
    if pneus:
        chao = min(pneus)
        relatorio['chao_m'] = round(chao, 3)
        for o in corte + kit:
            n = o.name.lower()
            if n.startswith('wheel') or any(k in n for k in ('freio', 'ponteira', 'escap', 'roda', 'pneu', 'brake', 'exhaust')):
                continue
            baixos = [v.co for v in BM[o.name].verts if v.co.z < chao + C6_CHAO
                      and min(math.hypot(v.co.x - x, v.co.z - R) for x in (xf, xt)) > R + 0.03]
            if len(baixos) > 4:
                zmin = min(p.z for p in baixos)
                falha('C6', o.name, '%d vértice(s) a menos de %.0f cm do chão (o mais baixo a %.0f cm), fora da roda'
                      % (len(baixos), C6_CHAO * 100, (zmin - chao) * 100))
for nome, sx in (('bumper_front', 1), ('bumper_rear', -1)):
    if nome not in por_nome:
        continue
    bz = [v.co.z for v in BM[nome].verts]
    ponta_b = max(sx * v.co.x for v in BM[nome].verts)
    chapa = [sx * v.co.x for o in corte if o.name.startswith(('body', 'hood', 'trunk', 'fender', 'tailgate')) for f in faces_de(o, 'pintura')
             for v in f.verts if min(bz) - 0.05 < v.co.z < max(bz) + 0.15]
    if chapa:
        bal = (ponta_b - max(chapa)) * 100
        relatorio['pecas'].setdefault(nome, {})['balanco_cm'] = round(bal, 1)
        if bal > C8_CM:
            falha('C8', nome, 'para-choque em bloco: sai %.0f cm da lataria (máx. %.0f)' % (bal, C8_CM))

# ---------------------------------------------------------------------------------------------------------------- saída
for f in relatorio['falhas']:
    print('FALHA %s %-22s %s' % (f['regra'], f['peca'], f['texto']))
print('CHECAGEM %s: %d falha(s)' % (relatorio['carro'], len(relatorio['falhas'])))
if SAIDA_JSON:
    json.dump(relatorio, open(SAIDA_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ARCO = globals().get('ARCO', {})
if '--so-c1' in argv:
    # o conserto só do C1 (a luz e a lente de lado), sem virar faces nem alisar o arco: é o que vai para os cortes do jogo (10/11/2026)
    viradas, duplas, ARCO = {}, {}, {}
if '--sem-luz' in argv:
    # sem o conserto da luz (só o vidro do C3): na quina, o envelope da lataria não serve de régua e a lanterna envolvente encolhia e
    # deixava o buraco escuro à mostra (Barão, Furgãozinho, 10/11/2026); a luz desses carros fica para a revisão com render
    ENCOSTAR, LENTE_DE_LADO = {}, {}
if CONSERTAR and (viradas or ARCO or ENCOSTAR or LENTE_DE_LADO or CAMADAS):
    from mathutils.kdtree import KDTree
    feitos = {'arco': 0, 'viradas': 0, 'duplas': 0}
    for o in corte:
        if o.name not in viradas and o.name not in ARCO:
            continue
        # C4 primeiro (solda a peça e alisa a borda do arco); depois C1, achando cada face pelo meio e pela normal (mundo), porque a solda
        # muda os índices e apagaria a cópia virada de uma face (os mesmos vértices)
        if o.name in ARCO:
            feitos['arco'] += alisar_arco(o, *ARCO[o.name])
        alvo_v, alvo_d = viradas.get(o.name, []), duplas.get(o.name, [])
        if not alvo_v and not alvo_d:
            continue
        b = bmesh.new()
        b.from_mesh(o.data)
        b.transform(o.matrix_world)
        b.faces.ensure_lookup_table()
        kd = KDTree(len(b.faces))
        for f in b.faces:
            kd.insert(f.calc_center_median(), f.index)
        kd.balance()

        def achar(c, n):
            for _, k, _ in kd.find_range(c, 0.003):
                if b.faces[k].normal.dot(n) > 0.9:
                    return b.faces[k]
            return None
        vira = {f for f in (achar(c, n) for c, n in alvo_v) if f}
        dup = [f for f in (achar(c, n) for c, n in alvo_d) if f and f not in vira]
        bmesh.ops.reverse_faces(b, faces=list(vira))
        if dup:
            # vistas de dentro de frente e de fora de costas: uma cópia virada, para os dois lados aparecerem
            nova = bmesh.ops.duplicate(b, geom=dup)['geom']
            bmesh.ops.reverse_faces(b, faces=[g for g in nova if isinstance(g, bmesh.types.BMFace)])
        b.transform(o.matrix_world.inverted())
        b.to_mesh(o.data)
        b.free()
        o.data.update()
        feitos['viradas'] += len(vira)
        feitos['duplas'] += len(dup)
    # C1: a peça de luz encolhe no eixo em que sai, a partir do lado de dentro, até encostar no envelope da lataria
    feitos['encostados'] = 0
    for o in corte:
        fat = ENCOSTAR.get(o.name)
        if not fat:
            continue
        M, Mi = o.matrix_world, o.matrix_world.inverted()
        for v in o.data.vertices:
            w = M @ v.co
            if 'y' in fat:
                k, dentro, sy = fat['y']
                c = abs(w.y)
                if c > dentro:
                    w.y = (dentro + (c - dentro) * k) * (1 if w.y > 0 else -1)
            if 'x' in fat:
                k, dentro, sx = fat['x']
                c = abs(w.x - centro.x)
                if c > dentro:
                    w.x = centro.x + (dentro + (c - dentro) * k) * (1 if w.x > centro.x else -1)
            v.co = Mi @ w
        o.data.update()
        feitos['encostados'] += 1
    # C3: a camada de baixo do vidro sai (o risco branco do reflexo), achada pelo meio e pela normal
    feitos['camadas'] = 0
    for o in corte:
        alvo = CAMADAS.get(o.name)
        if not alvo:
            continue
        from mathutils.kdtree import KDTree
        b = bmesh.new()
        b.from_mesh(o.data)
        b.transform(o.matrix_world)
        b.faces.ensure_lookup_table()
        kd = KDTree(len(b.faces))
        for f in b.faces:
            kd.insert(f.calc_center_median(), f.index)
        kd.balance()
        sai = set()
        for c, n in alvo:
            for _, k, _ in kd.find_range(c, 0.0002):
                if b.faces[k].normal.dot(n) > 0.99:
                    sai.add(b.faces[k])
        bmesh.ops.delete(b, geom=list(sai), context='FACES_ONLY')
        b.transform(o.matrix_world.inverted())
        b.to_mesh(o.data)
        b.free()
        o.data.update()
        feitos['camadas'] += len(sai)
    # a lente de lado vira plástico preto (a carcaça), achada pelo meio e pela normal depois da escala (a escala só muda o y e o x)
    feitos['lente_de_lado'] = 0
    for o in corte:
        alvo = LENTE_DE_LADO.get(o.name)
        if not alvo:
            continue
        nm = nomes_mat(o)
        if 'chassi' not in nm:
            continue
        preto = nm.index('chassi')
        M = o.matrix_world
        lados = [(abs(n.y) > 0.7, c.y > 0) for c, n in alvo]
        borda = max(abs((M @ v.co).y) for v in o.data.vertices) - 0.015
        for f in o.data.polygons:
            m = nm[f.material_index] if f.material_index < len(nm) else ''
            if not (m.startswith('luz') or m in ('refletor', 'lente_farol')):
                continue
            n = (M.to_3x3() @ f.normal).normalized()
            c = M @ f.center
            if abs(n.y) > 0.7 and abs(c.y) > borda and n.y * c.y > 0:
                f.material_index = preto
                feitos['lente_de_lado'] += 1
        o.data.update()
    for o in IMPORTADOS.get(KIT, []) if KIT else []:
        bpy.data.objects.remove(o)
    bpy.ops.export_scene.gltf(filepath=CONSERTAR, export_format='GLB', use_selection=False, export_apply=False)
    print('CONSERTO: %(viradas)d face(s) viradas, %(duplas)d com os dois lados, %(arco)d vértice(s) da borda do arco alisados, %(encostados)d luz(es) encostadas na lataria, %(lente_de_lado)d face(s) de lente de lado em plástico preto, %(camadas)d face(s) da camada de baixo do vidro tiradas' % feitos)
sys.exit(1 if relatorio['falhas'] else 0)
