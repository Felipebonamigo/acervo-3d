"""Carro do Sketchfab em muitas peças -> os 3 objetos que o sketchfab_preparar.py espera (carroceria, vidros, rodas), com o material
de cada peça escolhido à mão (pintura, vidro, pneu, chassi, luz, cromado) e as peças de marca ou de sobra tiradas.

    python -I ferramentas/sketchfab_juntar.py -- <modelo.glb|scene.gltf> <saida.glb> <grupos.json>

grupos.json: {"tirar": [regex...], "carroceria": {regex: material}, "vidros": {regex: material}, "rodas": {regex: material}}.
Cada regex casa com o nome do objeto ou do pai dele (no GLB do Sketchfab a malha se chama Object_N e o nome do autor fica no pai).
Peça que não casa com nada para o script com erro: tudo tem dono. Depois rode o sketchfab_preparar.py com os objetos
"carroceria,vidros,rodas" e o 9º argumento 1 (manter os materiais daqui)."""
import bpy, bmesh, sys, json, re
from mathutils import Matrix, Vector

a = sys.argv[sys.argv.index("--") + 1:]
ent, out, grupos = a[0], a[1], json.load(open(a[2]))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)


def nomes(o):
    n = [o.name]
    p = o.parent
    while p is not None:
        n.append(p.name)
        p = p.parent
    return n


def casa(o, padroes):
    for rx, mat in padroes.items():
        if any(re.search(rx, n, re.I) for n in nomes(o)):
            return mat
    return None


mats = {}
for nome in ("pintura", "vidro", "pneu", "chassi", "luz", "cromado"):
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    mats[nome] = m
destino = {"carroceria": [], "vidros": [], "rodas": []}
tirados = []
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    if any(re.search(rx, n, re.I) for rx in grupos.get("tirar", []) for n in nomes(o)):
        tirados.append(nomes(o)[1] if len(nomes(o)) > 1 else o.name)
        bpy.data.objects.remove(o)
        continue
    for g in ("vidros", "rodas", "carroceria"):
        mat = casa(o, grupos.get(g, {}))
        if mat:
            break
    else:
        raise SystemExit("peça sem grupo: %s" % nomes(o))
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_parent_inverse = Matrix.Identity(4)
    o.matrix_world = Matrix.Identity(4)
    o.data = o.data.copy()
    o.data.transform(M)
    o.data.materials.clear()
    o.data.materials.append(mats[mat])
    for p in o.data.polygons:
        p.material_index = 0
    destino[g].append(o)
for o in list(bpy.data.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o)

# normais para fora: o autor deixou o teto do Furgãozinho com as faces viradas para dentro (o material é de duas faces, no Sketchfab
# não aparece), e o carro_completo.py empurrava o forro do teto para fora da chapa. Ordem dos vértices coerente em cada ilha e, se
# a ilha olha mais para o meio do carro do que para fora, ela é virada inteira
pts = [v.co.copy() for o in destino["carroceria"] for v in o.data.vertices]
lo = Vector([min(p[i] for p in pts) for i in range(3)])
hi = Vector([max(p[i] for p in pts) for i in range(3)])
centro = (lo + hi) / 2
lateral = 0 if (hi.x - lo.x) < (hi.y - lo.y) else 1      # o eixo horizontal mais curto
viradas = 0
for g, objs in destino.items():
    for o in objs:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        visto = set()
        for f0 in bm.faces:
            if f0 in visto:
                continue
            pilha, ilha = [f0], []
            visto.add(f0)
            while pilha:
                f = pilha.pop()
                ilha.append(f)
                for e in f.edges:
                    for h in e.link_faces:
                        if h not in visto:
                            visto.add(h)
                            pilha.append(h)
            meio = centro
            if g == "rodas":
                # roda: para fora é para o lado dela (y), não para longe do meio do carro
                cm = sum((f.calc_center_median() for f in ilha), Vector()) / len(ilha)
                meio = cm.copy()
                meio[lateral] = centro[lateral]
            s = sum(f.calc_area() * f.normal.dot(f.calc_center_median() - meio) for f in ilha)
            if s < 0:
                bmesh.ops.reverse_faces(bm, faces=ilha)
                viradas += 1
        bm.to_mesh(o.data)
        bm.free()
print("ilhas viradas para fora:", viradas)
for g, objs in destino.items():
    if not objs:
        raise SystemExit("grupo vazio: " + g)
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = g
    print("%s: %d faces, materiais %s" % (g, len(ob.data.polygons), sorted({ob.data.materials[p.material_index].name for p in ob.data.polygons})))
print("tirados:", tirados)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
