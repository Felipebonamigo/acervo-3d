"""
Borracha de vedação pela borda real de cada vidro (modelos limpos, como o Gol Quadrado do Sketchfab, 29/10/2026): a face de fora do
vidro tem um contorno poligonal limpo, com cantos vivos; o cordão segue esse contorno para fora, sobre a chapa, com 3 fileiras
(perfil arredondado), sem alisar nada. O vedacao_vidros.py (raster + alisamento) é para a borda serrilhada do Meshy.

    python -I ferramentas/borracha_vidro.py -- <corte>.glb <saida>.glb [--largura-cm 1.6] [--largura-fixo-cm 2.4] [--dona vidro=peça] [--por-ilha]

A borracha entra na peça que leva o vidro no jogo (porta, tampa ou carroceria), material `chassi`.
"""
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


LARG = opt("--largura-cm", 1.6) / 100
LARG_FIXO = opt("--largura-fixo-cm", 2.4) / 100
POR_ILHA = "--por-ilha" in args
ALT = 0.004
DONA = {"glass_door_fl": "door_fl", "glass_door_fr": "door_fr", "glass_door_rl": "door_rl", "glass_door_rr": "door_rr", "glass_rear": "trunk"}
# --dona vidro=peça (repetível; Pão de Forma, 30/10/2026): no furgão de motor atrás a "trunk" é a tampa do motor, abaixo da janela,
# e o vidro de trás fica na carroceria (--dona glass_rear=body)
for i_, x_ in enumerate(args):
    if x_ == "--dona":
        k_, v_ = args[i_ + 1].split("=")
        DONA[k_] = v_

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]


def mat_names(o):
    return [s.material.name if s.material else "" for s in o.material_slots]


# BVH da chapa pintada e dos vidros (a borracha assenta em cima)
todos = bmesh.new()
for o in meshes:
    names = mat_names(o)
    if not any(n.startswith(("pintura", "vidro")) for n in names):
        continue
    b = bmesh.new()
    b.from_mesh(o.data)
    b.transform(o.matrix_world)
    fora = [f for f in b.faces if not (f.material_index < len(names) and names[f.material_index].startswith(("pintura", "vidro")))]
    bmesh.ops.delete(b, geom=fora, context="FACES")
    tmp = bpy.data.meshes.new("tmp")
    b.to_mesh(tmp)
    todos.from_mesh(tmp)
    bpy.data.meshes.remove(tmp)
    b.free()
bvh = BVHTree.FromBMesh(todos)

relatorio = []
for g in [o for o in meshes if o.name.startswith("glass_")]:
    gn = mat_names(g)
    bm = bmesh.new()
    bm.from_mesh(g.data)
    bm.transform(g.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    fv = [f for f in bm.faces if f.material_index < len(gn) and gn[f.material_index] == "vidro"]
    if not fv:
        bm.free()
        continue
    cen = sum((f.calc_center_median() for f in fv), Vector()) / len(fv)
    fora_dir = Vector((cen.x if abs(cen.x) > 1.0 else 0.0, cen.y if abs(cen.x) <= 1.0 else 0.0, 0.35)).normalized()
    # ilhas de faces de vidro; a de fora é a de maior área com a normal para fora
    visto = set()
    ilhas = []
    for f0 in fv:
        if f0.index in visto:
            continue
        pilha = [f0]
        visto.add(f0.index)
        g_ = []
        while pilha:
            f = pilha.pop()
            g_.append(f)
            for e in f.edges:
                for f2 in e.link_faces:
                    if f2.index not in visto and f2 in fv:
                        visto.add(f2.index)
                        pilha.append(f2)
        ilhas.append(g_)
    def pontos(il):
        n = sum((f.normal * f.calc_area() for f in il), Vector())
        return (n.dot(fora_dir), sum(f.calc_area() for f in il))
    ilhas.sort(key=lambda il: -pontos(il)[1])
    fora = max(ilhas[:2], key=lambda il: pontos(il)[0]) if len(ilhas) > 1 else ilhas[0]
    # --por-ilha (Barão, 30/10/2026): cada ilha de fora do vidro ganha a sua borracha (o vidro fixo de quarta vai na mesma peça que o
    # vidro da porta de trás e ficava sem); sem a opção, só a de fora maior, como antes
    alvos = [fora]
    if POR_ILHA:
        cand = [il for il in ilhas if pontos(il)[0] > 0.2 * pontos(il)[1] and pontos(il)[1] > 0.005]
        # a cópia que o corte põe 6 mm atrás de cada vidro também olha para fora: de duas ilhas com o mesmo centro (3 cm) e área
        # parecida, só a mais para fora ganha borracha
        def centro_(il):
            return sum((f.calc_center_median() for f in il), Vector()) / len(il)
        cand.sort(key=lambda il: -centro_(il).dot(fora_dir))
        alvos = []
        for il in cand:
            c_, a_ = centro_(il), pontos(il)[1]
            if not any((centro_(j) - c_).length < 0.03 and abs(pontos(j)[1] - a_) < 0.3 * a_ for j in alvos):
                alvos.append(il)
        alvos = alvos or [fora]
    for fora in alvos:
        sfora = set(fora)
        # borda da face de fora: arestas com uma face só na ilha, em laço ordenado
        borda = [e for e in bm.edges if sum(1 for f in e.link_faces if f in sfora) == 1]
        if not borda:
            # vidro modelado como placa fechada (frente e verso ligados pela borda, o primeiro candidato do Pampeiro, 30/10): a face de fora é a que olha para fora
            sfora = {f for f in fora if f.normal.dot(fora_dir) > 0.2}
            borda = [e for e in bm.edges if sum(1 for f in e.link_faces if f in sfora) == 1]
        if not borda:
            print(f"[borracha_vidro] {g.name}: sem borda na face de fora, sem borracha")
            continue
        viz = {}
        for e in borda:
            a, b = e.verts
            viz.setdefault(a, []).append(b)
            viz.setdefault(b, []).append(a)
        # o laço mais comprido é o contorno; um furo de uma face (o vidro de quarta esquerdo do Caipora) é outro laço, curto
        lacos, usados = [], set()
        for e0 in borda:
            inicio = e0.verts[0]
            if inicio in usados:
                continue
            laco = [inicio]
            ant, cur = None, inicio
            while True:
                prox = [v for v in viz[cur] if v is not ant]
                if not prox:
                    break
                nxt = prox[0]
                if nxt is inicio:
                    break
                laco.append(nxt)
                ant, cur = cur, nxt
                if len(laco) > 5000:
                    break
            usados.update(laco)
            lacos.append(laco)
        laco = max(lacos, key=len)
        P = np.array([list(v.co) for v in laco])
        # espigões: uma racha interna da malha entra no laço como ida e volta; some o vértice onde a direção inverte, até não ter mais
        mudou = True
        while mudou and len(P) > 4:
            mudou = False
            n_ = len(P)
            keep = np.ones(n_, bool)
            for i in range(n_):
                t1 = P[i] - P[i - 1]
                t2 = P[(i + 1) % n_] - P[i]
                if np.linalg.norm(t1) < 1e-6 or np.linalg.norm(t2) < 1e-6 or np.dot(t1, t2) / (np.linalg.norm(t1) * np.linalg.norm(t2)) < -0.9:
                    keep[i] = False
                    mudou = True
                    break
            P = P[keep]
        if len(P) < 4:
            continue
        # plano do vidro e direção para fora do contorno em cada vértice (bissetriz no plano), para fora = longe do centro
        nrm = sum((f.normal for f in fora), Vector()).normalized()
        if nrm.dot(fora_dir) < 0:
            nrm = -nrm
        c = P.mean(axis=0)
        n = len(P)
        hw = LARG_FIXO if g.name in ("glass_windshield", "glass_rear") else LARG
        rows = []
        for i in range(n):
            p = P[i]
            t1 = p - P[i - 1]
            t2 = P[(i + 1) % n] - p
            def lateral(t):
                t = t / max(np.linalg.norm(t), 1e-9)
                l = np.cross(np.array(nrm), t)
                if np.dot(l, p - c) < 0:
                    l = -l
                return l
            l1, l2 = lateral(t1), lateral(t2)
            bis = l1 + l2
            if np.linalg.norm(bis) < 1e-6:
                bis = l1
            bis /= np.linalg.norm(bis)
            # nos cantos a bissetriz tem que ser alongada para manter a largura
            esc = 1.0 / max(0.5, float(np.dot(bis, l1)))
            rows.append([p + bis * (hw * k * esc) for k in (0.0, 0.5, 1.0)])
        rows = np.array(rows)          # n x 3 x 3
        # assenta na chapa: cada ponto vai para a superfície mais perto (raio para dentro pela normal do vidro), levanta pelo perfil
        V = np.zeros_like(rows)
        for i in range(n):
            for j, s_ in enumerate((-1.0, 0.0, 1.0)):
                q = Vector(rows[i, j])
                hit = bvh.ray_cast(q + nrm * 0.06, -nrm, 0.12)
                base = hit[0] if hit[0] is not None else q
                V[i, j] = np.array(base) + np.array(nrm) * (0.0015 + ALT * (1 - s_ * s_))
        best = DONA.get(g.name, "body")
        if best not in bpy.data.objects:      # carro de 2 portas: o vidro de trás é da carroceria
            best = "body"
        dona = bpy.data.objects[best]
        inv = dona.matrix_world.inverted()
        me = dona.data
        names = mat_names(dona)
        if "chassi" not in names:
            me.materials.append(bpy.data.materials.get("chassi") or bpy.data.materials.new("chassi"))
            names = mat_names(dona)
        mi = names.index("chassi")
        bmd = bmesh.new()
        bmd.from_mesh(me)
        vs = [[bmd.verts.new(inv @ Vector(V[i, j])) for j in range(3)] for i in range(n)]
        up = inv.to_3x3()
        novas = []
        for i in range(n):
            a, b = vs[i], vs[(i + 1) % n]
            for j in range(2):
                try:
                    f = bmd.faces.new((a[j], b[j], b[j + 1], a[j + 1]))
                except ValueError:
                    continue
                f.material_index = mi
                f.smooth = True
                f.normal_update()
                if f.normal.dot((up @ nrm).normalized()) < 0:
                    f.normal_flip()
                novas.append(f)
        n_old = len(me.loops)
        cn = np.empty(n_old * 3)
        me.corner_normals.foreach_get("vector", cn)
        bmd.to_mesh(me)
        me.update()
        cn_new = np.empty(len(me.loops) * 3)
        me.corner_normals.foreach_get("vector", cn_new)
        cn_new[: n_old * 3] = cn
        me.normals_split_custom_set(cn_new.reshape(-1, 3).tolist())
        me.update()
        bmd.free()
        relatorio.append("%s -> %s: %d pontos na borda, borracha %.1f cm" % (g.name, best, n, hw * 100))
    bm.free()

bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
for linha in relatorio:
    print("[borracha_vidro]", linha)
