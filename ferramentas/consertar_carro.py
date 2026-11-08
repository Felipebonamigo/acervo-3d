"""
Conserto dos defeitos que a auditar_carro.py acha (08/11/2026), no GLB do corte quebrável, no lugar:
  - faces invertidas (só com --normais): em cada peça com --min-invertidas ou mais arestas entre faces de ordem trocada, as normais são refeitas de forma
    coerente (bmesh recalc_face_normals, por ilha). No Unreal a pintura é de um lado só: a face invertida some ("parece que ficou cortado
    alguma parte", o Felipe em 08/11). Fica atrás da opção porque, na prévia de um lado só (auditar_previa.py --um-lado), as 346 arestas
    invertidas do Barão não abrem buraco visível: estão por dentro, e refazer as normais de uma casca aberta pode virar a face certa;
  - buracos nos vidros (glass_*): os laços de borda solta de até --vidro-max-cm2 que não são a borda da peça viram face (o buraco no vidro
    tira o reflexo num círculo, visível a 1 m).
Não mexe em mais nada (materiais, nomes, UV e texturas voltam como vieram, pelo exportador glTF do Blender).

    python -I ferramentas/consertar_carro.py -- <carro.glb> [--normais] [--min-invertidas 20] [--vidro-max-cm2 300] [--saida outro.glb]
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
    if o.name.startswith('glass_'):
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
