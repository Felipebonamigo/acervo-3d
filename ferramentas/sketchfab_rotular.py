"""Carro do Sketchfab que não vem separado em carroceria / vidros / rodas (um .3ds convertido, materiais misturados, triângulos soltos):
rotula cada ilha de faces por regras de caixa e grava os 3 objetos que o sketchfab_preparar.py espera, com os nossos materiais
(pintura, vidro, luz, chassi, cromado, pneu). Rode o preparo depois com --manter-materiais.

    python -I ferramentas/sketchfab_rotular.py -- <scene.gltf> <saida.glb> <regras.json>

regras.json (coordenadas do arquivo como o Blender importa: z para cima; vale a primeira regra que casa):
    {"juntar_mm": 1.0,
     "padrao": {"Object_4": "pintura", "Object_7": "pneu", "*": "fora"},
     "regras": [{"objeto": "Object_5", "caixa": [xmin, xmax, ymin, ymax, zmin, zmax], "por": "ilha"|"face", "material": "vidro"}, ...]}
"vidro_min_faces": 30 (opcional) ilha de vidro menor que isso vira chassi.
"cortes": [{"objeto": "Object_5", "ponto": [x, y, z], "normal": [nx, ny, nz]}] (opcional) corta a malha por planos antes de
rotular, para a borda entre duas regiões de uma mesma chapa (lanterna e vidro traseiro pintados na textura perdida) sair reta.
"normal": [nx, ny, nz, mínimo] (opcional) só casa a face cuja normal tem produto escalar >= mínimo com a dada (o vidro traseiro
que dobra para a lateral vira acabamento preto da coluna, e a borracha do vidro não sai solta no canto).
"por": "ilha" (padrão) testa o centro da caixa da ilha ligada; "face" testa o centro de cada face (para separar uma ilha que junta
vidro traseiro e lanternas). "material": "fora" apaga (emblemas, letreiros, placas com número, a grade-assinatura).
Saída: objetos carroceria (pintura, luz, chassi, cromado), vidros (vidro) e rodas (pneu), nessa ordem; imprime quantas faces de cada."""
import bpy, bmesh, sys, json, numpy as np
from mathutils import Matrix

a = sys.argv[sys.argv.index("--") + 1:]
ent, out, regras = a[0], a[1], json.load(open(a[2]))
MATS = ("pintura", "vidro", "luz", "chassi", "cromado", "pneu")
DESTINO = {"pintura": "carroceria", "luz": "carroceria", "chassi": "carroceria", "cromado": "carroceria", "vidro": "vidros", "pneu": "rodas"}
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)


def dentro(p, cx):
    return cx[0] <= p[0] <= cx[1] and cx[2] <= p[1] <= cx[3] and cx[4] <= p[2] <= cx[5]


def material_de(nome_obj, centro_ilha, centro_face, normal_face):
    for r in regras.get("regras", []):
        if r.get("objeto", nome_obj) != nome_obj:
            continue
        p = centro_face if r.get("por", "ilha") == "face" else centro_ilha
        if "normal" in r and float(np.dot(normal_face, r["normal"][:3])) < r["normal"][3]:
            continue
        if dentro(p, r["caixa"]):
            return r["material"]
    pad = regras.get("padrao", {})
    return pad.get(nome_obj, pad.get("*", "pintura"))


partes = {k: bmesh.new() for k in ("carroceria", "vidros", "rodas")}
conta = {}
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=regras.get("juntar_mm", 1.0) / 1000.0)
    for c in regras.get("cortes", []):
        if c.get("objeto", o.name) == o.name:
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=c["ponto"], plane_no=c["normal"])
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.faces.ensure_lookup_table()
    rot = {}
    visto = set()
    for f0 in bm.faces:
        if f0.index in visto:
            continue
        pilha, ilha = [f0], []
        visto.add(f0.index)
        while pilha:
            f = pilha.pop()
            ilha.append(f)
            for e in f.edges:
                for h in e.link_faces:
                    if h.index not in visto:
                        visto.add(h.index)
                        pilha.append(h)
        P = np.array([v.co[:] for f in ilha for v in f.verts])
        ci = 0.5 * (P.min(0) + P.max(0))
        for f in ilha:
            rot[f.index] = material_de(o.name, ci, np.array(f.calc_center_median()[:]), np.array(f.normal[:]))
    # pedacinho de vidro solto (sobra de um corte por plano no canto do vidro): vira acabamento preto, senão o carro_quebravel o
    # toma por aba de caixilho e tira, deixando um furo
    minimo = regras.get("vidro_min_faces", 0)
    if minimo:
        visto = set()
        for f0 in bm.faces:
            if f0.index in visto or rot[f0.index] != "vidro":
                continue
            pilha, ilha = [f0], []
            visto.add(f0.index)
            while pilha:
                f = pilha.pop()
                ilha.append(f)
                for e in f.edges:
                    for h in e.link_faces:
                        if h.index not in visto and rot[h.index] == "vidro":
                            visto.add(h.index)
                            pilha.append(h)
            if len(ilha) < minimo:
                for f in ilha:
                    rot[f.index] = "chassi"
    for destino in partes:
        sel = [f for f in bm.faces if rot[f.index] != "fora" and DESTINO[rot[f.index]] == destino]
        if not sel:
            continue
        # copia as faces escolhidas para o bmesh do destino, com o material no índice da lista MATS
        mapa_v = {}
        alvo = partes[destino]
        for f in sel:
            vs = []
            for v in f.verts:
                if v.index not in mapa_v:
                    mapa_v[v.index] = alvo.verts.new(v.co)
                vs.append(mapa_v[v.index])
            try:
                nf = alvo.faces.new(vs)
            except ValueError:
                continue
            nf.material_index = MATS.index(rot[f.index])
            conta[(o.name, rot[f.index])] = conta.get((o.name, rot[f.index]), 0) + 1
    for f in bm.faces:
        if rot[f.index] == "fora":
            conta[(o.name, "fora")] = conta.get((o.name, "fora"), 0) + 1
    bm.free()
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
mats = []
for nome in MATS:
    m = bpy.data.materials.get(nome) or bpy.data.materials.new(nome)
    m.use_nodes = True
    mats.append(m)
for nome, bm in partes.items():
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0001)
    me = bpy.data.meshes.new(nome)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(nome, me)
    bpy.context.scene.collection.objects.link(ob)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB")
for (obj, mat), n in sorted(conta.items()):
    print(f"{obj:12s} {mat:8s} {n:6d}")
