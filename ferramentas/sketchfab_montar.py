"""
Monta um carro do Sketchfab que vem "de jogo" (rodas soltas no centro, materiais de molde com cores trocadas pelo jogo, peças em
vários objetos) nos 3 objetos que o sketchfab_preparar.py espera: carroceria, vidros, rodas. Tudo por uma receita JSON:

    python -I ferramentas/sketchfab_montar.py -- <scene.gltf> <saida.glb> <receita.json>

Receita (exemplo em veiculos/sketchfab/quebravel/sagui/sagui_montagem.json):
- "comprimento_no_eixo": "y" | "x"  e  "frente": -1 | 1   (onde está o comprimento e a frente no arquivo)
- "remover_objetos": nomes (prefixo) de objetos que saem (volante solto, por exemplo)
- "materiais": {nome do material no arquivo (sem o sufixo da peça): papel}. Papéis: pintura, vidro, pneu, chassi, luz, cromado,
  luz_vermelha, luz_ambar, luz_branca, lente_farol, refletor, "remover". Material sem papel na lista vira pintura (e é avisado).
- "regras": [{"objeto": prefixo, "material": nome, "caixa": [x0, x1, y0, y1, z0, z1] no arquivo, "papel": ..., "nota": ...}]: valem
  antes do papel do material, a primeira que pega a face manda (a lente da frente e a de trás têm o mesmo material, por exemplo)
- papel "achatar_<papel>" (Sagui): a ilha é achatada sobre a base e fica com <papel> (o relevo do emblema vira chapa lisa)
- papel "alisar_<papel>" (Sagui): a região vai para o plano ajustado pela borda dela (some o rebaixo em volta do emblema); com
  "plano": nome na regra, todas as regiões do nome usam um plano só, ajustado pela borda de fora das que têm "plano_borda": true, e
  "afastar": metros põe à frente dele a ilha que vai inteira; "tapar": true fecha com chapa no plano o furo que fica dentro da região
- regra com "refazer": true e "caixa": as faces da caixa saem e o furo vira uma chapa nova presa à borda de fora (oval do Sagui)
- "caixas": [{"centro", "tamanho", "papel", "nota"}] no referencial do arquivo: geometria nova na carroceria (as barras lisas da grade)
- "vidros": objetos (prefixo) que são os vidros das janelas (vão para o objeto de vidro)
- "roda": {"objetos": [...], "eixos": [eixo da frente, eixo de trás] no eixo do comprimento do arquivo, "z": z do cubo, "y_fora":
  meia-largura da face de fora das rodas montadas, "face_de_fora": 1 | -1 (lado da face de fora na roda solta, no eixo lateral do
  arquivo)}: a roda solta (cubo na origem) é copiada para os 4 cantos; a do outro lado gira 180 graus em z
- "alongar": {"arcos": [[a1, a2], [b1, b2]], "comprimento": m, "entre_eixos": m}: as caixas de roda andam inteiras (ficam
  redondas), o meio entre elas estica até o entre-eixos e os balanços até o comprimento
- "baixar_acima_de": {"z": z0, "altura": m}: o que está acima de z0 (acima do topo dos arcos) encolhe até o teto ficar na altura
  pedida, medida do chão (base do pneu)

Cada face sai com um material de nome igual ao papel (o preparo e o corte levam o papel adiante com --manter-materiais e
--cores-do-arquivo) e com a cor de prévia do papel. Grava <saida>_montagem.json com o que foi feito.
"""
import json
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Matrix

a = sys.argv[sys.argv.index("--") + 1:]
ent, sai, rec = a[0], a[1], json.load(open(a[2], encoding="utf-8"))

CORES = {"pintura": (0.80, 0.80, 0.80), "vidro": (0.10, 0.12, 0.13), "pneu": (0.03, 0.03, 0.03), "chassi": (0.03, 0.03, 0.03),
         "luz": (0.85, 0.85, 0.85), "cromado": (0.60, 0.60, 0.62), "luz_vermelha": (0.80, 0.02, 0.015), "luz_ambar": (0.95, 0.42, 0.02),
         "luz_branca": (0.90, 0.90, 0.88), "lente_farol": (0.66, 0.68, 0.70), "refletor": (0.95, 0.95, 0.96)}
rel = {"avisos": [], "removidos": {}}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)


def raiz(o):
    while o.parent is not None and o.parent.type == "MESH":
        o = o.parent
    p = o
    while p.parent is not None and not p.parent.name.startswith(("Sketchfab", "Collada", "RootNode", "GLTF")):
        p = p.parent
    return p.name


def comeca(nome, lista):
    return any(nome.startswith(x) for x in lista)


# 1. tudo no mundo, sem pai; cada objeto de malha lembra a que peça do arquivo pertencia
pecas = []
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    dono = raiz(o)
    M = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
    o.data = o.data.copy()
    o.data.transform(M)
    pecas.append((o, dono))
for o in [o for o in bpy.data.objects if o.type == "EMPTY"]:
    bpy.data.objects.remove(o)

# 2. eixos: comprimento em x, frente em +x, esquerda em +y (o resto da cadeia usa esse referencial)
eixo, frente = rec.get("comprimento_no_eixo", "x"), rec.get("frente", 1)
if eixo == "y":
    # (x, y, z) -> (frente * y, -frente * x, z): olhando para a frente, a esquerda fica em +y
    R = Matrix(((0, frente, 0, 0), (-frente, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
else:
    R = Matrix(((frente, 0, 0, 0), (0, frente, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))


for o, _ in pecas:
    o.data.transform(R)


def mat_base(m):
    return m.name.split("-material")[0].split(".")[0] if m else ""


# 3. papéis dos materiais; faces de papel "remover" e objetos removidos saem
papeis = rec.get("materiais", {})
mats = {}
for nome, cor in CORES.items():
    m = bpy.data.materials.new(nome)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*cor, 1.0)
    b.inputs["Roughness"].default_value = 0.4
    mats[nome] = m
sem_papel = set()
vivos = []
Rinv = R.inverted()


def papel_da_face(f, dono, origem, papel_slot):
    """O papel do material, ou o da primeira regra que pega a face (objeto, material e caixa no referencial do arquivo); e a regra."""
    p = papel_slot[f.material_index] if f.material_index < len(papel_slot) else "pintura"
    nm = origem[f.material_index] if f.material_index < len(origem) else ""
    for regra in rec.get("regras", []):
        if regra.get("objeto") and not dono.startswith(regra["objeto"]):
            continue
        if regra.get("material") and regra["material"] != nm:
            continue
        if regra.get("caixa"):
            c = Rinv @ f.center
            x0, x1, y0, y1, z0, z1 = regra["caixa"]
            if not (x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1):
                continue
        return regra["papel"], regra
    return p, None


# planos compartilhados do "alisar" (regra com "plano": nome): ajustados pela borda de fora das regiões marcadas com "plano_borda"
# (os vértices delas que tocam faces de fora da região, na chapa de verdade); todas as regiões do mesmo nome vão para ele. No Sagui, o
# rebaixo em anel do para-choque e o emblema, que são malhas separadas, num plano só (em dois, as superfícies brigavam no render)
pontos_plano = {}
tudo_c = np.concatenate([np.array([v.co[:] for v in o.data.vertices]) for o, _ in pecas if len(o.data.vertices)])
centro_carro = 0.5 * (tudo_c.min(0) + tudo_c.max(0))
for o, dono in pecas:
    me = o.data
    origem_ = [mat_base(m) for m in me.materials]
    slot_ = [papeis.get(nm, "pintura") for nm in origem_]
    marca = {}
    for f in me.polygons:
        _, rg = papel_da_face(f, dono, origem_, slot_)
        if rg and rg.get("plano") and rg.get("plano_borda"):
            marca[f.index] = rg["plano"]
    if not marca:
        continue
    vf = {}
    for f in me.polygons:
        for vi in f.vertices:
            vf.setdefault(vi, []).append(f.index)
    for vi, fs in vf.items():
        planos_v = {marca[i] for i in fs if i in marca}
        if planos_v and any(i not in marca for i in fs):
            for pl in planos_v:
                pontos_plano.setdefault(pl, []).append(me.vertices[vi].co[:])
planos = {}
for pl, pts in pontos_plano.items():
    B = np.array(pts)
    c0 = B.mean(0)
    n = np.linalg.svd(B - c0)[2][-1]
    if (c0 - centro_carro) @ n < 0:
        n = -n
    planos[pl] = (c0, n)
for o, dono in pecas:
    if comeca(dono, rec.get("remover_objetos", [])):
        rel["removidos"][dono] = rel["removidos"].get(dono, 0) + len(o.data.polygons)
        bpy.data.objects.remove(o)
        continue
    me = o.data
    origem = [mat_base(m) for m in me.materials]
    papel_slot = []
    for nm in origem:
        p = papeis.get(nm)
        if p is None:
            sem_papel.add(nm)
            p = "pintura"
        papel_slot.append(p)
    # papel por face: o do material, ou o da primeira regra que pega a face (objeto, material e caixa no referencial do arquivo)
    papel_face, regra_face = [], []
    for f in me.polygons:
        p, regra = papel_da_face(f, dono, origem, papel_slot)
        if regra:
            nota = regra.get("nota", regra["papel"])
            rel.setdefault("regras", {})[nota] = rel.get("regras", {}).get(nota, 0) + 1
        papel_face.append(p)
        regra_face.append(regra)
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    # papel "achatar_<papel>": cada ilha dessas faces é achatada sobre a própria base (o plano mais fundo na normal média dela) e
    # fica com <papel>; o relevo do emblema vira chapa lisa sem abrir buraco no para-choque
    achatar = [f for f in bm.faces if papel_face[f.index].startswith("achatar_")]
    visto = set()
    for f0 in achatar:
        if f0 in visto:
            continue
        ilha, pilha = [], [f0]
        visto.add(f0)
        while pilha:
            g = pilha.pop()
            ilha.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in visto and papel_face[h.index].startswith("achatar_"):
                        visto.add(h)
                        pilha.append(h)
        n = sum((g.normal * g.calc_area() for g in ilha), __import__("mathutils").Vector())
        if n.length < 1e-9:
            continue
        n.normalize()
        vs = {v for g in ilha for v in g.verts}
        base = min(v.co.dot(n) for v in vs)
        for v in vs:
            v.co -= n * (v.co.dot(n) - base)
        rel.setdefault("achatadas", 0)
        rel["achatadas"] += 1
    # papel "alisar_<papel>": a região é projetada no plano ajustado pela borda dela (os vértices que tocam faces de fora da região
    # ou a borda da malha); o rebaixo em anel em volta do emblema do Sagui some, a chapa fica lisa
    alisar = {f for f in bm.faces if papel_face[f.index].startswith("alisar_")}
    visto = set()
    for f0 in alisar:
        if f0 in visto:
            continue
        ilha, pilha = [], [f0]
        visto.add(f0)
        while pilha:
            g = pilha.pop()
            ilha.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h not in visto and h in alisar:
                        visto.add(h)
                        pilha.append(h)
        vs = {v for g in ilha for v in g.verts}
        rg = regra_face[ilha[0].index] or {}
        if rg.get("plano") in planos:
            # plano compartilhado: só os vértices na chapa de fora ficam; a ilha sem eles (o emblema) vai inteira, "afastar" metros à frente
            c0, n = planos[rg["plano"]]
            borda = {v for v in vs if any(h not in alisar for h in v.link_faces)}
            afastar = float(rg.get("afastar", 0.0))
        else:
            borda = {v for v in vs if v.is_boundary or any(h not in alisar for h in v.link_faces)}
            if len(borda) < 3:
                continue
            B = np.array([v.co[:] for v in borda])
            c0 = B.mean(0)
            n = np.linalg.svd(B - c0)[2][-1]
            afastar = 0.0
        for v in vs:
            if v in borda:
                continue
            q = np.array(v.co[:])
            v.co = q - n * (float((q - c0) @ n) - afastar)
        if rg.get("tapar"):
            # "tapar": o furo que o emblema cobria (borda da malha dentro da região) vira chapa no mesmo plano
            aberta = [e for e in bm.edges if e.is_boundary and all(v in vs for v in e.verts) and not all(v in borda for v in e.verts)]
            novas = bmesh.ops.holes_fill(bm, edges=aberta, sides=0)["faces"] if aberta else []
            bm.faces.index_update()
            bm.faces.ensure_lookup_table()
            for g in novas:
                g.material_index = ilha[0].material_index
            papel_face += [papel_face[ilha[0].index]] * len(novas)
            regra_face += [rg] * len(novas)
            rel.setdefault("tapadas", 0)
            rel["tapadas"] += len(novas)
        rel.setdefault("alisadas", 0)
        rel["alisadas"] += 1
    papel_face = [p[len("alisar_"):] if p.startswith("alisar_") else p for p in papel_face]
    papel_face = [p[len("achatar_"):] if p.startswith("achatar_") else p for p in papel_face]
    fora = [f for f in bm.faces if papel_face[f.index] == "remover"]
    if fora:
        rel["removidos"]["faces " + dono] = rel["removidos"].get("faces " + dono, 0) + len(fora)
        bmesh.ops.delete(bm, geom=fora, context="FACES_ONLY")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    if not len(me.polygons):
        bpy.data.objects.remove(o)
        continue
    ordem = [p for p in CORES]
    novo = [ordem.index(p) if p in ordem else 0 for p in papel_face if p != "remover"]
    me.materials.clear()
    for nome in ordem:
        me.materials.append(mats[nome])
    me.polygons.foreach_set("material_index", novo)
    me.update()
    # regra com "refazer": true (Sagui): as faces da caixa dela saem e o furo é fechado por uma chapa nova presa à borda de fora (que
    # está na lataria de verdade). Achatar o rebaixo do emblema deixava triângulos sem área e virados, que a sombra assada pintava de escuro
    for rg in rec.get("regras", []):
        if not rg.get("refazer") or (rg.get("objeto") and not dono.startswith(rg["objeto"])):
            continue
        x0, x1, y0, y1, z0, z1 = rg["caixa"]
        bm = bmesh.new()
        bm.from_mesh(me)
        regiao = [f for f in bm.faces if (lambda c: x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1)(Rinv @ f.calc_center_median())]
        if not regiao:
            bm.free()
            continue
        mi = regiao[0].material_index
        conj = set(regiao)
        borda = [e for e in {e for f in regiao for e in f.edges} if any(h not in conj for h in e.link_faces)]
        bmesh.ops.delete(bm, geom=regiao, context="FACES_ONLY")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        borda = [e for e in borda if e.is_valid]
        novas = bmesh.ops.holes_fill(bm, edges=borda, sides=0)["faces"]
        if novas:
            tri = bmesh.ops.triangulate(bm, faces=novas, quad_method="BEAUTY", ngon_method="BEAUTY")["faces"]
            for g in tri:
                g.material_index = mi
        bm.to_mesh(me)
        bm.free()
        me.update()
        rel.setdefault("refeitas", {})[rg.get("nota", "refazer")] = len(regiao)
    vivos.append((o, dono))
if sem_papel:
    rel["avisos"].append("materiais sem papel na receita (viraram pintura): %s" % sorted(sem_papel))

# 3b. caixas novas (no referencial do arquivo): "caixas": [{"centro": [x, y, z], "tamanho": [dx, dy, dz], "papel": ..., "nota": ...}];
# entram na carroceria (Sagui: as duas barras lisas da grade e o fundo preto atrás delas, no lugar da colmeia da marca)
for k, cx in enumerate(rec.get("caixas", [])):
    me = bpy.data.meshes.new("caixa_%d" % k)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=cx["tamanho"], verts=bm.verts)
    bmesh.ops.translate(bm, vec=cx["centro"], verts=bm.verts)
    bm.to_mesh(me)
    bm.free()
    me.transform(R)
    ordem = list(CORES)
    for nome in ordem:
        me.materials.append(mats[nome])
    me.polygons.foreach_set("material_index", [ordem.index(cx["papel"])] * len(me.polygons))
    o = bpy.data.objects.new("caixa_%d" % k, me)
    bpy.context.scene.collection.objects.link(o)
    vivos.append((o, "caixa_%d" % k))
    rel.setdefault("caixas", []).append(cx.get("nota", cx["papel"]))

# 4. rodas: a roda solta (no centro do arquivo) vai para os 4 cantos
r = rec.get("roda")
rodas = []
if r:
    soltas = [(o, d) for o, d in vivos if comeca(d, r["objetos"])]
    vivos = [(o, d) for o, d in vivos if not comeca(d, r["objetos"])]
    # o pneu do arquivo vem em metades soltas (costura sem solda): solda, para cada pneu ser uma ilha só (o preparo acha a roda
    # pela ilha redonda que toca o chão)
    for o, _ in soltas:
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.0005)
        bm.to_mesh(o.data)
        bm.free()
    # no referencial novo a roda solta tem o eixo em y, com o cubo na origem
    y_fora = abs(r["y_fora"])                        # |y| da face de fora da roda montada, no carro
    lado_fora = r.get("face_de_fora", 1)            # sinal da face de fora na roda solta (no arquivo, no eixo lateral)
    # a face de fora da roda solta, no referencial novo, fica do lado y de sinal -frente*lado_fora (x do arquivo -> -frente*y)
    s_fora = (-frente if eixo == "y" else frente) * lado_fora
    ext = max((abs(v.co.y) for o, _ in soltas for v in o.data.vertices if np.sign(v.co.y) == s_fora), default=0.0)
    for nome_r, xr, lado in (("fl", r["eixos"][0], 1), ("fr", r["eixos"][0], -1), ("rl", r["eixos"][1], 1), ("rr", r["eixos"][1], -1)):
        x_novo = (frente * xr) if eixo == "y" else frente * xr
        for o, d in soltas:
            c = o.copy()
            c.data = o.data.copy()
            bpy.context.scene.collection.objects.link(c)
            # a face de fora vai para o lado `lado`: se a roda solta olha para o outro, gira 180 graus em z
            if s_fora != lado:
                c.data.transform(Matrix.Rotation(np.pi, 4, "Z"))
            c.data.transform(Matrix.Translation((x_novo, lado * (y_fora - ext), r["z"])))
            vivos.append((c, "roda_" + nome_r))
        rodas.append(dict(nome=nome_r, centro=[round(x_novo, 4), round(lado * (y_fora - ext + 0.0), 4), r["z"]]))
    for o, _ in soltas:
        bpy.data.objects.remove(o)
    rel["rodas"] = rodas


# 5. alongar: arcos inteiros, meio e balanços esticados (x novo = comprimento, frente +x)
def mapa_x(xs, pontos):
    return np.interp(xs, [p[0] for p in pontos], [p[1] for p in pontos])


al = rec.get("alongar")
if al:
    todos = np.concatenate([np.array([v.co for v in o.data.vertices]) for o, _ in vivos if not _.startswith("roda_")])
    x0, x1 = float(todos[:, 0].min()), float(todos[:, 0].max())
    arcos = sorted([sorted([frente * v for v in arco]) if eixo == "y" else sorted(arco) for arco in al["arcos"]])
    (t0, t1), (f0, f1) = arcos                   # traseiro (x menor) e dianteiro
    ef = 0.5 * (f0 + f1)
    et = 0.5 * (t0 + t1)
    d_eixo = 0.5 * (al["entre_eixos"] - (ef - et))
    d_bal = 0.5 * (al["comprimento"] - (x1 - x0)) - d_eixo
    pontos = [(x0 - 10, x0 - 10 - d_eixo - d_bal), (x0, x0 - d_eixo - d_bal), (t0, t0 - d_eixo), (t1, t1 - d_eixo), (f0, f0 + d_eixo),
              (f1, f1 + d_eixo), (x1, x1 + d_eixo + d_bal), (x1 + 10, x1 + 10 + d_eixo + d_bal)]
    for o, d in vivos:
        me = o.data
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        if d.startswith("roda_"):
            co[:, 0] += d_eixo if d[5] == "f" else -d_eixo
        else:
            co[:, 0] = mapa_x(co[:, 0], pontos)
        me.vertices.foreach_set("co", co.ravel())
        me.update()
    for rr in rodas:
        rr["centro"][0] = round(rr["centro"][0] + (d_eixo if rr["nome"][0] == "f" else -d_eixo), 4)
    rel["alongar"] = dict(eixos_antes=[round(ef, 4), round(et, 4)], desloc_eixo=round(d_eixo, 4), desloc_balanco=round(d_bal, 4),
                          comprimento_antes=round(x1 - x0, 4))

# 6. baixar o teto: o que está acima de z0 encolhe
bx = rec.get("baixar_acima_de")
if bx:
    tudo = np.concatenate([np.array([v.co for v in o.data.vertices]) for o, _ in vivos])
    chao = float(tudo[:, 2].min())
    topo = float(np.concatenate([np.array([v.co for v in o.data.vertices]) for o, d in vivos if not d.startswith("roda_")])[:, 2].max()) \
        if not bx.get("topo") else bx["topo"]
    z0 = bx["z"]
    k = (chao + bx["altura"] - z0) / (topo - z0)
    for o, d in vivos:
        if d.startswith("roda_"):
            continue
        me = o.data
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        acima = co[:, 2] > z0
        co[acima, 2] = z0 + (co[acima, 2] - z0) * k
        me.vertices.foreach_set("co", co.ravel())
        me.update()
    rel["baixar"] = dict(chao=round(chao, 4), topo_antes=round(topo, 4), k=round(float(k), 4))

# 7. junta em 3 objetos: carroceria, vidros, rodas
grupos = {"carroceria": [], "vidros": [], "rodas": []}
for o, d in vivos:
    if d.startswith("roda_"):
        grupos["rodas"].append(o)
    elif comeca(d, rec.get("vidros", [])):
        grupos["vidros"].append(o)
    else:
        grupos["carroceria"].append(o)
for nome, lst in grupos.items():
    if not lst:
        rel["avisos"].append("grupo %s vazio" % nome)
        continue
    bpy.ops.object.select_all(action="DESELECT")
    for o in lst:
        o.select_set(True)
    bpy.context.view_layer.objects.active = lst[0]
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = nome
tudo = np.concatenate([np.array([v.co for v in o.data.vertices]) for o in bpy.data.objects if o.type == "MESH"])
rel["caixa"] = [round(float(v), 4) for v in (tudo[:, 0].min(), tudo[:, 0].max(), tudo[:, 1].min(), tudo[:, 1].max(), tudo[:, 2].min(),
                                              tudo[:, 2].max())]
rel["triangulos"] = sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in bpy.data.objects if o.type == "MESH")
# sem UV e sem normais: o exportador duplicaria os vértices nas costuras (o pneu saía em duas ilhas e o preparo não o achava); o
# preparo recalcula as normais por ângulo e a textura é refeita no assar_desgaste.py
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_texcoords=False, export_normals=False)
json.dump(rel, open(sai[:-4] + "_montagem.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(rel, ensure_ascii=False, indent=1))
