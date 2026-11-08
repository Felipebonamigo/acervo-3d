"""
Auditoria peça por peça de um carro do acervo (08/11/2026, pedido do Felipe pela central: "parece que ficou cortado alguma parte, ou que
está faltando um pedaço do farol"; régua: nenhum defeito visível a 1 m da câmera). Sem render: só a malha.

    python -I ferramentas/auditar_carro.py -- <carro.glb> <saida.json> [--kit <completo.glb>] [--buraco-cm2 2] [--id nome]

Por peça (um objeto do GLB do corte quebrável, com os nomes padronizados de carro_quebravel.py):
  - bordas soltas: arestas com uma face só (malha aberta), quantas e o comprimento somado, com os vértices a até 0,2 mm soldados antes;
  - buracos: os laços de bordas soltas, com a área do laço (fórmula de Newell); os acima de --buraco-cm2 entram na lista, maiores primeiro.
    Uma chapa de um lado só (o capô, a porta) tem um laço grande na própria borda: o maior laço de cada ilha é a borda dela e não conta
    como buraco. Buraco tapado por outra peça (o vão da janela pelo vidro, o da lanterna pela lente, o da caixa de roda pelo kit completo,
    --kit) não é defeito: de 5 pontos do buraco (o meio e 4 a meio caminho da borda), raios de até 15 cm dos dois lados da normal; tapado
    se 4 acertam outra peça. Só os descobertos entram em "buracos"; as rodas (wheel_*) ficam de fora (o jogo põe as rodas de kit);
  - faces invertidas: arestas entre duas faces com a ordem dos vértices trocada (a normal de uma aponta para o lado errado da outra);
  - faróis e lanternas (headlight*, taillight*, fog*, indicator*): a profundidade (a espessura ao longo da normal média, em cm), as ilhas
    (lente, refletor, miolo e moldura costumam ser ilhas separadas) e os materiais; "chapada" se a profundidade passa de menos de 1 cm
    (a lanterna que parece adesivo) e "incompleta" se tem menos de 2 ilhas.
Saída: o JSON com tudo e um resumo na tela; o código de saída é 0 sempre (a auditoria aponta, quem decide é quem lê).
"""
import bpy
import bmesh
import json
import math
import os
import sys
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
entrada, saida = argv[0], argv[1]
BURACO_CM2 = float(argv[argv.index('--buraco-cm2') + 1]) if '--buraco-cm2' in argv else 2.0
CARRO = argv[argv.index('--id') + 1] if '--id' in argv else os.path.splitext(os.path.basename(entrada))[0]
LUZES = ('headlight', 'taillight', 'fog', 'indicator', 'light_')
KIT = argv[argv.index('--kit') + 1] if '--kit' in argv else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=entrada)
pecas_corte = {o.name for o in bpy.data.objects if o.type == 'MESH'}
if KIT:
    bpy.ops.import_scene.gltf(filepath=KIT)
# o mundo de cada peça, para os raios: todas as malhas menos a própria (as do kit entram só como tampa)
MUNDO = {}
for o in bpy.data.objects:
    if o.type != 'MESH' or o.name.endswith('_LOD1'):
        continue
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    MUNDO[o.name] = b


def arvore_sem(nome):
    junto = bmesh.new()
    for n, b in MUNDO.items():
        if n == nome:
            continue
        m = bpy.data.meshes.new('tmp')
        b.to_mesh(m)
        junto.from_mesh(m)
        bpy.data.meshes.remove(m)
    arv = BVHTree.FromBMesh(junto)
    junto.free()
    return arv


def tapado(arv, laco):
    pts = [v.co.copy() for v in laco]
    centro = sum(pts, Vector()) / len(pts)
    n = Vector((0.0, 0.0, 0.0))
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        n += Vector(((p.y - q.y) * (p.z + q.z), (p.z - q.z) * (p.x + q.x), (p.x - q.x) * (p.y + q.y)))
    if n.length == 0:
        return True
    n.normalize()
    amostras = [centro] + [centro.lerp(pts[(k * len(pts)) // 4], 0.5) for k in range(4)]
    acertos = 0
    for a in amostras:
        if arv.ray_cast(a, n, 0.15)[0] is not None or arv.ray_cast(a, -n, 0.15)[0] is not None:
            acertos += 1
    return acertos >= 4


def lacos_de_borda(bm):
    """Os laços de arestas soltas (cada um, a lista de vértices em ordem). Arestas soltas que não fecham laço entram como abertas."""
    soltas = {e for e in bm.edges if len(e.link_faces) == 1}
    vizinhas = {}
    for e in soltas:
        for v in e.verts:
            vizinhas.setdefault(v, []).append(e)
    usadas = set()
    lacos = []
    for e0 in soltas:
        if e0 in usadas:
            continue
        usadas.add(e0)
        laco = [e0.verts[0], e0.verts[1]]
        atual = e0
        while True:
            v = laco[-1]
            prox = [e for e in vizinhas.get(v, []) if e not in usadas]
            if not prox:
                break
            atual = prox[0]
            usadas.add(atual)
            w = atual.other_vert(v)
            if w == laco[0]:
                break
            laco.append(w)
        lacos.append(laco)
    return lacos, soltas


def area_newell(pontos):
    n = Vector((0.0, 0.0, 0.0))
    for i, p in enumerate(pontos):
        q = pontos[(i + 1) % len(pontos)]
        n.x += (p.y - q.y) * (p.z + q.z)
        n.y += (p.z - q.z) * (p.x + q.x)
        n.z += (p.x - q.x) * (p.y + q.y)
    return 0.5 * n.length


def ilhas(bm):
    vistas = set()
    grupos = []
    for f in bm.faces:
        if f in vistas:
            continue
        pilha, grupo = [f], []
        vistas.add(f)
        while pilha:
            g = pilha.pop()
            grupo.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in vistas:
                        vistas.add(h)
                        pilha.append(h)
        grupos.append(grupo)
    return grupos


relatorio = {'carro': CARRO, 'entrada': entrada, 'buraco_cm2': BURACO_CM2, 'pecas': []}
for o in sorted([o for o in bpy.data.objects if o.type == 'MESH' and o.name in pecas_corte], key=lambda o: o.name):
    if o.name.endswith('_LOD1') or o.name.startswith(('wheel_', 'hubcap_')):
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    # vértices coincidentes (até 0,2 mm) soldados antes de contar: os vidros e algumas peças vêm em "sopa de triângulos", e a costura
    # entre dois triângulos colados não é buraco na tela
    invertidas = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)  # antes da solda (que junta a casca de dentro com a de fora)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0002)
    bm.normal_update()
    lacos, soltas = lacos_de_borda(bm)
    comprimento = sum(e.calc_length() for e in soltas)
    # o maior laço de cada ilha é a borda da chapa; o resto, buraco
    vert_ilha = {}
    grupos = ilhas(bm)
    for i, g in enumerate(grupos):
        for f in g:
            for v in f.verts:
                vert_ilha[v] = i
    por_ilha = {}
    for laco in lacos:
        a = area_newell([v.co for v in laco]) * 1e4  # cm²
        centro = sum((v.co for v in laco), Vector()) / len(laco)
        por_ilha.setdefault(vert_ilha.get(laco[0], -1), []).append((a, centro, len(laco), laco))
    buracos = []
    tapados = 0
    arv = None
    for i, ls in por_ilha.items():
        ls.sort(key=lambda t: -t[0])
        for a, c, n, laco in ls[1:]:
            if a < BURACO_CM2:
                continue
            arv = arv or arvore_sem(o.name)
            if tapado(arv, laco):
                tapados += 1
                continue
            buracos.append({'area_cm2': round(a, 1), 'centro_m': [round(c.x, 3), round(c.y, 3), round(c.z, 3)], 'vertices': n})
    buracos.sort(key=lambda b: -b['area_cm2'])
    peca = {
        'nome': o.name,
        'triangulos': sum(len(f.verts) - 2 for f in bm.faces),
        'ilhas': len(grupos),
        'bordas_soltas': len(soltas),
        'bordas_soltas_m': round(comprimento, 2),
        'buracos': buracos[:20],
        'buracos_total': len(buracos),
        'buracos_tapados': tapados,
        'arestas_invertidas': invertidas,
        'materiais': [s.material.name if s.material else '' for s in o.material_slots],
    }
    if o.name.startswith(LUZES):
        normal = sum((f.normal * f.calc_area() for f in bm.faces), Vector())
        normal = normal.normalized() if normal.length > 0 else Vector((1, 0, 0))
        prof = [v.co.dot(normal) for v in bm.verts]
        profundidade = (max(prof) - min(prof)) * 100 if prof else 0.0
        peca['luz'] = {
            'profundidade_cm': round(profundidade, 2),
            'normal': [round(normal.x, 2), round(normal.y, 2), round(normal.z, 2)],
            'chapada': profundidade < 1.0,
            'incompleta': len(grupos) < 2,
        }
    relatorio['pecas'].append(peca)
    bm.free()

os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)
json.dump(relatorio, open(saida, 'w'), ensure_ascii=False, indent=1)
for p in relatorio['pecas']:
    marca = []
    if p['buracos_total']:
        marca.append(f"{p['buracos_total']} buraco(s), o maior {p['buracos'][0]['area_cm2']} cm²")
    if p['arestas_invertidas']:
        marca.append(f"{p['arestas_invertidas']} aresta(s) invertida(s)")
    if 'luz' in p:
        L = p['luz']
        marca.append(f"luz {L['profundidade_cm']} cm de fundo, {p['ilhas']} ilha(s)" + (' CHAPADA' if L['chapada'] else '') + (' INCOMPLETA' if L['incompleta'] else ''))
    if marca:
        print(f"AUDITORIA {CARRO} {p['nome']}: " + '; '.join(marca))
print(f"AUDITORIA {CARRO}: {len(relatorio['pecas'])} peça(s) em {saida}")
