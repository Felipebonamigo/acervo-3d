"""
Conserto dos defeitos que a auditar_carro.py acha (08/11/2026), no GLB do corte quebrável, no lugar:
  - faces invertidas (só com --normais): em cada peça com --min-invertidas ou mais arestas entre faces de ordem trocada, as normais são refeitas de forma
    coerente (bmesh recalc_face_normals, por ilha). No Unreal a pintura é de um lado só: a face invertida some ("parece que ficou cortado
    alguma parte", o Felipe em 08/11). Fica atrás da opção porque, na prévia de um lado só (auditar_previa.py --um-lado), as 346 arestas
    invertidas do Barão não abrem buraco visível: estão por dentro, e refazer as normais de uma casca aberta pode virar a face certa;
  - buracos nos vidros (glass_*, só com --tapar-vidros): os laços de borda solta de até --vidro-max-cm2 que não são a borda da peça viram face (o buraco no vidro
    tira o reflexo num círculo, visível a 1 m). Fica atrás da opção: os vidros dos cortes vêm em "sopa de triângulos", e os "buracos"
    deles eram as costuras entre triângulos colados (a auditoria solda antes de contar e não acha nenhum); tapar costura empilha face;
  - vidro que falta (--vidro-vao x,y,z:peca, repetível): o vão da carroceria (body) cujo meio fica a até 10 cm do ponto [m, espaço do
    GLB] ganha uma face de vidro na peça de vidro dada (o vidro fixo da coluna de trás do Furgãozinho não existia: via-se a cabine pelo
    buraco). A face vai com o primeiro material da peça.
  - chapa ondulada (--alisar peca[:níveis], repetível, 09/11/2026): a peça é soldada (0,2 mm), subdividida em Catmull-Clark (1 nível) e
    cada vértice de borda volta ao contorno de antes (a peça não encolhe nem abre fresta). A tampa do Pampeiro (hatch-redondo-5p, trunk)
    era grossa, com triângulos de 3 a 4 cm, e o horizonte refletido quebrava em faixas serrilhadas: "mancha serrilhada, faixa";
  - borda em dente de serra (--borda-baixo peca, repetível): na faixa de baixo da peça (o quarto de baixo da altura), uma curva lisa
    (grau 4) pelos vales dos dentes e as pontas que descem abaixo dela sobem até ela (o vidro traseiro do Pampeiro).
  - antena grossa (--afinar-antena, 09/11/2026, "o retrovisor e a antena estão grossos" no Cuiabano do menu): a ilha fina e alta da
    carroceria (soldada; mais de 30 cm de altura, menos de 3 cm de lado e menos de 400 vértices) afina em volta do próprio eixo: 45 % na base até 20 % na ponta;
  - peça grande demais (--escala peca:fator, repetível): a peça diminui a partir da borda presa à carroceria (o lado mais perto do meio
    do carro em Y), o retrovisor menor sem soltar da porta.
  - sobra na caixa (--apagar peca:x0,x1,y0,y1,z0,z1, repetível, 10/11/2026: no Cuiabano, a casca pintada do retrovisor antigo ficou na
    carroceria quando o retrovisor diminuiu, e saía como uma chapa vermelha amassada ao lado dele): as faces da peça com o centro na
    caixa [m] saem; y0,y1 é em |y|, valendo para os dois lados.
Não mexe em mais nada (materiais, nomes, UV e texturas voltam como vieram, pelo exportador glTF do Blender).

    python -I ferramentas/consertar_carro.py -- <carro.glb> [--normais] [--min-invertidas 20] [--vidro-vao x,y,z:peca ...] [--vidro-max-cm2 300]
        [--alisar peca[:níveis] ...] [--borda-baixo peca ...] [--afinar-antena] [--escala peca:fator ...] [--apagar peca:x0,x1,y0,y1,z0,z1 ...]
        [--saida outro.glb]
"""
import bpy
import bmesh
import os
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
entrada = argv[0]
MIN_INV = int(argv[argv.index('--min-invertidas') + 1]) if '--min-invertidas' in argv else 20
VIDRO_MAX = float(argv[argv.index('--vidro-max-cm2') + 1]) if '--vidro-max-cm2' in argv else 300.0
saida = argv[argv.index('--saida') + 1] if '--saida' in argv else entrada

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=entrada)


def area_newell(pts):
    n = Vector((0.0, 0.0, 0.0))
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n += Vector(((p.y - q.y) * (p.z + q.z), (p.z - q.z) * (p.x + q.x), (p.x - q.x) * (p.y + q.y)))
    return 0.5 * n.length


def lacos(bm):
    soltas = {e for e in bm.edges if len(e.link_faces) == 1}
    viz = {}
    for e in soltas:
        for v in e.verts:
            viz.setdefault(v, []).append(e)
    usadas, out = set(), []
    for e0 in soltas:
        if e0 in usadas:
            continue
        usadas.add(e0)
        laco_e, laco_v = [e0], [e0.verts[0], e0.verts[1]]
        fechou = False
        while True:
            prox = [e for e in viz.get(laco_v[-1], []) if e not in usadas]
            if not prox:
                break
            e = prox[0]
            usadas.add(e)
            w = e.other_vert(laco_v[-1])
            laco_e.append(e)
            if w == laco_v[0]:
                fechou = True
                break
            laco_v.append(w)
        if fechou:
            out.append((laco_e, laco_v))
    return out


def ilha_de(bm):
    marca, n = {}, 0
    for f in bm.faces:
        if f in marca:
            continue
        pilha = [f]
        marca[f] = n
        while pilha:
            g = pilha.pop()
            for e in g.edges:
                for h in e.link_faces:
                    if h not in marca:
                        marca[h] = n
                        pilha.append(h)
        n += 1
    return marca


relatorio = []
VAOS = []
for i, a in enumerate(argv):
    if a == '--vidro-vao':
        ponto, peca = argv[i + 1].split(':')
        VAOS.append((Vector(tuple(float(x) for x in ponto.split(','))), peca))
body = bpy.data.objects.get('body')
for ponto, peca in VAOS:
    alvo = bpy.data.objects.get(peca)
    if not body or not alvo:
        relatorio.append(f'vidro no vão {tuple(round(v, 3) for v in ponto)}: falta body ou {peca}')
        continue
    bb = bmesh.new()
    bb.from_mesh(body.data)
    bb.transform(body.matrix_world)
    bmesh.ops.remove_doubles(bb, verts=bb.verts[:], dist=0.0002)
    melhor = None
    for le, lv in lacos(bb):
        meio = sum((v.co for v in lv), Vector()) / len(lv)
        d = (meio - ponto).length
        if d < 0.10 and (melhor is None or d < melhor[0]):
            melhor = (d, [v.co.copy() for v in lv])
    bb.free()
    if not melhor:
        relatorio.append(f'vidro no vão {tuple(round(v, 3) for v in ponto)}: nenhum vão a até 10 cm')
        continue
    bm = bmesh.new()
    bm.from_mesh(alvo.data)
    inv = alvo.matrix_world.inverted()
    novos = [bm.verts.new(inv @ c) for c in melhor[1]]
    face = bm.faces.new(novos)
    face.material_index = 0
    bmesh.ops.triangulate(bm, faces=[face])
    bm.normal_update()
    bm.to_mesh(alvo.data)
    alvo.data.update()
    bm.free()
    relatorio.append(f'{peca}: vidro novo no vão de {len(melhor[1])} vértices perto de {tuple(round(v, 3) for v in ponto)}')
def alisar(o, niveis):
    from mathutils import kdtree
    from mathutils.geometry import intersect_point_line
    me = o.data
    antes = len(me.polygons)
    b = bmesh.new()
    b.from_mesh(me)
    bmesh.ops.remove_doubles(b, verts=b.verts[:], dist=0.0002)
    segs = [(e.verts[0].co.copy(), e.verts[1].co.copy()) for e in b.edges if e.is_boundary]
    b.to_mesh(me)
    b.free()
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    if me.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
    m = o.modifiers.new('alisar', 'SUBSURF')
    m.levels = m.render_levels = niveis
    m.boundary_smooth = 'PRESERVE_CORNERS'
    bpy.ops.object.modifier_apply(modifier=m.name)
    kd = kdtree.KDTree(len(segs))
    for i, (p, q) in enumerate(segs):
        kd.insert((p + q) / 2, i)
    kd.balance()
    b = bmesh.new()
    b.from_mesh(me)
    for v in b.verts:
        if not v.is_boundary:
            continue
        melhor = None
        for _, i, _ in kd.find_n(v.co, 8):
            p, q = segs[i]
            _, t = intersect_point_line(v.co, p, q)
            c = p.lerp(q, min(max(t, 0.0), 1.0))
            if melhor is None or (c - v.co).length < (melhor - v.co).length:
                melhor = c
        if melhor is not None:
            v.co = melhor
    b.to_mesh(me)
    b.free()
    for p in me.polygons:
        p.use_smooth = True
    me.update()
    return antes, len(me.polygons)


def borda_baixo(o):
    import numpy as np
    M = o.matrix_world
    Mi = M.inverted()
    b = bmesh.new()
    b.from_mesh(o.data)
    bmesh.ops.remove_doubles(b, verts=b.verts[:], dist=0.0002)
    vs = list(b.verts)
    W = np.array([tuple(M @ v.co) for v in vs])
    zmin, zmax = W[:, 2].min(), W[:, 2].max()
    baixo = np.where(W[:, 2] < zmin + (zmax - zmin) * 0.25)[0]
    y, z = W[baixo, 1], W[baixo, 2]
    # o mais baixo de cada fatia de 1,5 cm (a ponta ou o vale) e, de cada 6 cm, o mais alto desses (o vale do dente)
    fatia = np.floor((y - y.min()) / 0.015).astype(int)
    pontas = {}
    for k, f in enumerate(fatia):
        if f not in pontas or z[k] < z[pontas[f]]:
            pontas[f] = k
    vales = {}
    for f, k in pontas.items():
        if f // 4 not in vales or z[k] > z[vales[f // 4]]:
            vales[f // 4] = k
    c = np.polyfit([y[k] for k in vales.values()], [z[k] for k in vales.values()], 4)
    zf = np.polyval(c, y)
    subir = (zf - z) > 0.002
    for i, ok, zz in zip(baixo, subir, zf):
        if ok:
            w = M @ vs[i].co
            w.z = zz
            vs[i].co = Mi @ w
    b.to_mesh(o.data)
    b.free()
    o.data.update()
    return int(subir.sum()), float((zf - z).max())


def afinar_antena(o):
    from mathutils import Vector
    b = bmesh.new()
    b.from_mesh(o.data)
    # soldada antes de procurar: em sopa de triângulos cada triângulo fino e alto da carroceria virava uma "antena" (46 no Cuiabano)
    bmesh.ops.remove_doubles(b, verts=b.verts[:], dist=0.0002)
    M = o.matrix_world
    Mi = M.inverted()
    vistas, n = set(), 0
    for f in b.faces:
        if f in vistas:
            continue
        pilha, vs = [f], set()
        vistas.add(f)
        while pilha:
            g = pilha.pop()
            vs.update(g.verts)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in vistas:
                        vistas.add(h)
                        pilha.append(h)
        P = [M @ v.co for v in vs]
        dx = max(p.x for p in P) - min(p.x for p in P)
        dy = max(p.y for p in P) - min(p.y for p in P)
        z0, z1 = min(p.z for p in P), max(p.z for p in P)
        if z1 - z0 > 0.3 and dx < 0.2 and dy < 0.03 and len(vs) < 400 and min(dx, dy) < 0.012:
            # o eixo: o centro de cada fatia em z (a antena pode ser inclinada)
            base = [p for p in P if p.z < z0 + 0.02]
            topo = [p for p in P if p.z > z1 - 0.02]
            cb = sum(base, Vector()) / len(base)
            ct = sum(topo, Vector()) / len(topo)
            for v in vs:
                w = M @ v.co
                t = (w.z - z0) / (z1 - z0)
                eixo = cb.lerp(ct, t)
                k = 0.45 + (0.20 - 0.45) * t
                w.x = eixo.x + (w.x - eixo.x) * k
                w.y = eixo.y + (w.y - eixo.y) * k
                v.co = Mi @ w
            n += 1
    b.to_mesh(o.data)
    b.free()
    o.data.update()
    return n


def escala_peca(o, fator):
    from mathutils import Vector, Matrix
    M = o.matrix_world
    P = [M @ v.co for v in o.data.vertices]
    ymeio = min(P, key=lambda p: abs(p.y))
    preso = [p for p in P if abs(abs(p.y) - abs(ymeio.y)) < 0.03]
    piv = sum(preso, Vector()) / len(preso)
    T = M.inverted() @ Matrix.Translation(piv) @ Matrix.Scale(fator, 4) @ Matrix.Translation(-piv) @ M
    o.data.transform(T)
    o.data.update()


for i, arg in enumerate(argv):
    if arg == '--afinar-antena':
        corpo = bpy.data.objects.get('body')
        n = afinar_antena(corpo) if corpo else 0
        relatorio.append(f'body: {n} antena(s) afinada(s)')
    elif arg == '--escala':
        peca, _, fator = argv[i + 1].partition(':')
        o = bpy.data.objects.get(peca)
        if not o:
            relatorio.append(f'escala: não achei {peca}')
            continue
        escala_peca(o, float(fator))
        relatorio.append(f'{peca}: escala {fator} a partir da borda presa')
    elif arg == '--apagar':
        peca, _, caixa = argv[i + 1].partition(':')
        o = bpy.data.objects.get(peca)
        if not o:
            relatorio.append(f'apagar: não achei {peca}')
            continue
        x0, x1, y0, y1, z0, z1 = (float(t) for t in caixa.split(','))
        M = o.matrix_world
        b = bmesh.new()
        b.from_mesh(o.data)
        fora = [f for f in b.faces if (lambda c: x0 <= c.x <= x1 and y0 <= abs(c.y) <= y1 and z0 <= c.z <= z1)(M @ f.calc_center_median())]
        bmesh.ops.delete(b, geom=fora, context='FACES')
        b.to_mesh(o.data)
        b.free()
        o.data.update()
        relatorio.append(f'{peca}: {len(fora)} face(s) apagadas na caixa {caixa}')
    elif arg == '--alisar':
        peca, _, nv = argv[i + 1].partition(':')
        o = bpy.data.objects.get(peca)
        if not o:
            relatorio.append(f'alisar: não achei {peca}')
            continue
        antes, depois = alisar(o, int(nv or 1))
        relatorio.append(f'{peca}: alisada, {antes} -> {depois} faces, borda de volta ao contorno')
    elif arg == '--borda-baixo':
        o = bpy.data.objects.get(argv[i + 1])
        if not o:
            relatorio.append(f'borda de baixo: não achei {argv[i + 1]}')
            continue
        n, mx = borda_baixo(o)
        relatorio.append(f'{o.name}: {n} ponta(s) da borda de baixo subidas, até {mx * 1000:.1f} mm')
for o in [o for o in bpy.data.objects if o.type == 'MESH']:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    mudou = False
    inv = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)
    if '--normais' in argv and inv >= MIN_INV:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        depois = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)
        relatorio.append(f'{o.name}: {inv} aresta(s) invertida(s) -> {depois}')
        mudou = True
    if '--tapar-vidros' in argv and o.name.startswith('glass_'):
        marca = ilha_de(bm)
        por_ilha = {}
        for le, lv in lacos(bm):
            # na escala do mundo (o GLB guarda a escala no objeto)
            a = area_newell([o.matrix_world @ v.co for v in lv]) * 1e4
            ilha = marca.get(next(iter(le[0].link_faces)), -1)
            por_ilha.setdefault(ilha, []).append((a, le))
        tapados = 0
        for ilha, ls in por_ilha.items():
            ls.sort(key=lambda t: -t[0])
            for a, le in ls[1:]:
                if a <= VIDRO_MAX:
                    bmesh.ops.holes_fill(bm, edges=le, sides=0)
                    tapados += 1
        if tapados:
            relatorio.append(f'{o.name}: {tapados} buraco(s) tapado(s)')
            mudou = True
    if mudou:
        bm.normal_update()
        bm.to_mesh(o.data)
        o.data.update()
    bm.free()

if relatorio:
    bpy.ops.export_scene.gltf(filepath=saida, export_format='GLB', use_selection=False, export_apply=False)
for linha in relatorio:
    print('CONSERTO ' + os.path.basename(entrada) + ' ' + linha)
print(f'CONSERTO {os.path.basename(entrada)}: {len(relatorio)} mudança(s)' + (f' em {saida}' if relatorio else ', nada a gravar'))
