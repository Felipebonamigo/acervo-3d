"""
Checagem automática de um carro do acervo, para o CI (10/11/2026; o Felipe viu o Cuiabano vermelho de trás, na rua: lanternas saltadas
para fora da lataria, borrachas dos vidros flutuando, faces quebradas no arco da roda, retrovisor e faróis com partes transparentes).
Sem render: a malha do corte (veiculos/sketchfab/quebravel/<id>/<id>.glb), com o kit completo como anteparo quando existe.

    python -I ferramentas/checar_carro.py -- <corte.glb> [--kit <completo.glb>] [--json saida.json] [--consertar saida.glb]

  C1 face de costas à vista: de 26 pontos em volta do carro (a 6 m), a face que a câmera enxerga pelo lado de trás e nunca pela frente.
     O Unreal desenha um lado só: essa face some (o "transparente" do retrovisor e do farol). Falha acima de C1_CM2 por peça.
     Com --consertar, essas faces viram de lado; a que também é vista
     de frente de dentro da cabine ganha uma cópia virada (os dois lados).
  C2 luz saltada: o farol e a lanterna não passam mais que C2_MM da lataria em volta (a carroceria e os para-choques numa faixa de 4 cm
     em volta da caixa da luz, na mesma altura), na direção da frente (farol) ou de trás (lanterna).
  C3 borracha flutuando: as faces de plástico preto (chassi) a até 2 cm da borda de um vidro ficam a no máximo C3_MM da pintura ou do
     vidro (a borracha deitada na chapa). Falha se mais de C3_FRACAO delas passa disso.
  C4 arco de roda: as faces da carroceria e dos para-lamas na faixa do arco de cada roda (de R a R + 12 cm do cubo, no lado de fora)
     sem face degenerada (área abaixo de 0,05 mm²; a "dobrada" pela normal das vizinhas ficou de fora: a face virada pelo C1
     ao lado de vizinhas escondidas parecia dobrada). Falha acima de C4_MAX. E a borda solta do arco sem dente de serra: o raio de cada vértice da borda
     contra a mediana dos vizinhos (C4_DENTE_MM, até C4_DENTES_MAX); com --consertar, a borda é puxada para a mediana, só no raio.
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
C2_MM = 12.0
C3_MM = 8.0
C3_FRACAO = 0.25
C4_MAX = 20
C4_DENTE_MM = 6.0
C4_DENTES_MAX = 6
LUZES = ('headlight', 'taillight')

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
entrada = argv[0]
opt = lambda n: argv[argv.index(n) + 1] if n in argv else None
KIT, SAIDA_JSON, CONSERTAR = opt('--kit'), opt('--json'), opt('--consertar')


def carregar(path):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o not in antes and o.type == 'MESH' and not o.name.endswith('_LOD1')]


bpy.ops.wm.read_factory_settings(use_empty=True)
corte = [o for o in carregar(entrada) if not o.name.startswith('wheel_')]
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


# ---------------------------------------------------------------------------------------------------------------- C1
viradas = {}
duplas = {}
for o in corte:
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
        falha('C1', o.name, '%d face(s) de costas à vista, %.1f cm² (some no Unreal; %d delas também vistas de frente de dentro)'
              % (len(costas) + len(dois_lados), cm2, len(dois_lados)))
        viradas[o.name] = [(b.faces[i].calc_center_median().copy(), b.faces[i].normal.copy()) for i in costas]
        duplas[o.name] = [(b.faces[i].calc_center_median().copy(), b.faces[i].normal.copy()) for i in dois_lados]

# ---------------------------------------------------------------------------------------------------------------- C2
lataria = [o for o in corte if o.name == 'body' or o.name.startswith(('bumper', 'fender', 'trunk', 'hood', 'tailgate', 'grille'))]
for o in corte:
    if not o.name.startswith(LUZES):
        continue
    b = BM[o.name]
    xs = [v.co.x for v in b.verts]
    ys = [v.co.y for v in b.verts]
    zs = [v.co.z for v in b.verts]
    frente = o.name.startswith('headlight')
    ponta = max(xs) if frente else min(xs)
    y0, y1, z0, z1 = min(ys), max(ys), min(zs), max(zs)
    anel = []
    for L in lataria:
        for v in BM[L.name].verts:
            p = v.co
            dentro = y0 <= p.y <= y1 and z0 <= p.z <= z1
            perto = (y0 - 0.04) <= p.y <= (y1 + 0.04) and (z0 - 0.04) <= p.z <= (z1 + 0.04)
            if perto and not dentro and abs(p.x - ponta) < 0.25:
                anel.append(p.x)
    if not anel:
        continue
    lat = max(anel) if frente else min(anel)
    saliente_mm = ((ponta - lat) if frente else (lat - ponta)) * 1000
    relatorio['pecas'].setdefault(o.name, {})['saliente_mm'] = round(saliente_mm, 1)
    if saliente_mm > C2_MM:
        falha('C2', o.name, 'a luz sai %.0f mm para fora da lataria em volta (máx. %.0f)' % (saliente_mm, C2_MM))

# ---------------------------------------------------------------------------------------------------------------- C3
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
            if hit[0] is None or hit[3] * 1000 > C3_MM:
                longe += 1
        if total >= 20:
            fr = longe / total
            relatorio['pecas'].setdefault(o.name, {})['borracha_longe'] = round(fr, 3)
            if fr > C3_FRACAO:
                falha('C3', o.name, '%.0f%% da borracha em volta do vidro a mais de %.0f mm da chapa (%d de %d faces)' % (fr * 100, C3_MM, longe, total))

# ---------------------------------------------------------------------------------------------------------------- C4
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
            falha('C4', o.name, 'borda do arco de roda em dente de serra: %d vértice(s) fogem mais de %.0f mm dos vizinhos (máx. %d)'
                  % (dentes, C4_DENTE_MM, C4_DENTES_MAX))
        relatorio['pecas'].setdefault(o.name, {})['arco_degeneradas'] = ruins
        if ruins > C4_MAX:
            falha('C4', o.name, '%d face(s) degeneradas no arco de roda (máx. %d)' % (ruins, C4_MAX))

# ---------------------------------------------------------------------------------------------------------------- saída
for f in relatorio['falhas']:
    print('FALHA %s %-22s %s' % (f['regra'], f['peca'], f['texto']))
print('CHECAGEM %s: %d falha(s)' % (relatorio['carro'], len(relatorio['falhas'])))
if SAIDA_JSON:
    json.dump(relatorio, open(SAIDA_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
ARCO = globals().get('ARCO', {})
if CONSERTAR and (viradas or ARCO):
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
    for o in kit:
        bpy.data.objects.remove(o)
    bpy.ops.export_scene.gltf(filepath=CONSERTAR, export_format='GLB', use_selection=False, export_apply=False)
    print('CONSERTO: %(viradas)d face(s) viradas, %(duplas)d com os dois lados, %(arco)d vértice(s) da borda do arco alisados' % feitos)
sys.exit(1 if relatorio['falhas'] else 0)
