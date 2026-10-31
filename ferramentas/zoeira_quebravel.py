"""
Veículo de zoeira do Detonauto (docs/veiculos-zoeira.md: ônibus, colheitadeira, máquina de lavar, caminhão, trio elétrico...) -> o corte
padronizado que a cadeia do Detonauto lê (make_crush_channels.py, kit_to_detonauto.py, glb_texturas.py), sem as regras de carro de
passeio do carro_quebravel.py (portas, cintura, faróis pela cor). Tudo vem de um <id>_config.json escrito à mão:

    python -I ferramentas/zoeira_quebravel.py -- veiculos/zoeira/quebravel/<id>/<id>_config.json <pasta de saída> [--tamanho 2048]
        [--amostras 1] [--sem-previa]

O config (caminhos relativos à raiz do acervo):
    {"id": "ceifa-tudo", "fonte": "veiculos/sketchfab/<arquivo>.glb", "frente": "+x|-x|+y|-y" (para onde a frente aponta no arquivo),
     "comprimento": 9.5 (ou "escala": 0.85), "tirar_objetos": "regex", "tirar_materiais": "regex" (emblemas, placas),
     "rodas": "regex dos objetos das rodas" (as ilhas vão para o canto pela posição: fl, fr, rl, rr),
     "pecas": [{"nome": "bumper_front", "objetos": "regex"} | {"nome": "hood", "caixa": [x0, x1, y0, y1, z0, z1]}],
     "vidros": [{"nome": "glass_windshield", "objetos": "regex"} ...],
     "materiais": {"regex do material do arquivo": "chassi|luz|cromado|pneu|pintura"} (sem regra: pintura),
     "pintura_rgb": [r, g, b] (0 a 1, sRGB; sem: a mediana da cor assada nas faces de pintura),
     "medidas": {"linha_de_cintura": ..., "coluna_a": ..., "topo_da_saia": ...} (opcional; o resto sai da caixa e das rodas),
     "notas": "..."}
"caixa" é no espaço final (metros, frente +X, esquerda +Y, cima +Z, chão em z = 0, origem entre os eixos) e leva as ilhas inteiras do
corpo cuja maior parte está dentro. Peças por objeto vêm primeiro, na ordem da lista; o que sobra é "body".

Saída em <pasta>: <id>.glb (uma malha por peça com os nomes do kit do acervo; rodas wheel_<canto>_tire e wheel_<canto>_rim com o pivô
no cubo), <id>_mapa.json (medidas no formato do carro_quebravel), <id>_wheels.json, <id>_pecas.json (peças, caixas, triângulos e a cor
da pintura para o glb_texturas.py) e <id>_previa.png. Textura: a cor do autor assada no Cycles num atlas só (embutida
no GLB), porque o jogo lê uma textura de cor por veículo (T_<Modelo>_C). Materiais: pintura, chassi, luz, cromado, pneu (todos com o
atlas) e vidro (liso).
"""
import sys
import os
import re
import json
import math

import bpy
import bmesh
from mathutils import Vector, Matrix

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
CFG_PATH, OUT = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


TAM = opt("--tamanho", 2048)
AMOSTRAS = opt("--amostras", 1)
PREVIA = "--sem-previa" not in args
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cfg = json.load(open(CFG_PATH, encoding="utf-8"))
CID = cfg["id"]
os.makedirs(OUT, exist_ok=True)
avisos = []

bpy.ops.wm.read_factory_settings(use_empty=True)
if cfg["fonte"].endswith(".blend"):
    # .blend (o Teimoso, 31/10/2026): a cor procedural (ruído, sujeira) não sobrevive ao glTF, então o modelo feito por script vem
    # no arquivo do Blender e o bake abaixo lê os nós de cor
    bpy.ops.wm.open_mainfile(filepath=os.path.join(RAIZ, cfg["fonte"]))
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o)
else:
    bpy.ops.import_scene.gltf(filepath=os.path.join(RAIZ, cfg["fonte"]))
cena = bpy.context.scene


def malhas():
    return [o for o in bpy.data.objects if o.type == "MESH"]


# 1. Tudo no espaço do mundo, sem pais, e os objetos e faces que saem
for o in malhas():
    if o.data.users > 1:
        o.data = o.data.copy()
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o)
if cfg.get("tirar_objetos"):
    for o in [o for o in malhas() if re.search(cfg["tirar_objetos"], o.name)]:
        bpy.data.objects.remove(o)
if cfg.get("tirar_materiais"):
    rx = re.compile(cfg["tirar_materiais"])
    for o in malhas():
        bm = bmesh.new(); bm.from_mesh(o.data)
        fora = [f for f in bm.faces if o.material_slots and f.material_index < len(o.material_slots)
                and o.material_slots[f.material_index].material and rx.search(o.material_slots[f.material_index].material.name)]
        if fora:
            bmesh.ops.delete(bm, geom=fora, context="FACES")
            bm.to_mesh(o.data)
        bm.free()
    for o in [o for o in malhas() if not o.data.polygons]:
        bpy.data.objects.remove(o)

# 2. Frente em +X e a escala
giro = {"+x": 0.0, "-x": math.pi, "+y": -math.pi / 2, "-y": math.pi / 2}[cfg.get("frente", "+x")]
R = Matrix.Rotation(giro, 4, "Z")
for o in malhas():
    o.data.transform(R)


def caixa(objs):
    mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
    for o in objs:
        for v in o.data.vertices:
            mn = Vector(map(min, mn, v.co)); mx = Vector(map(max, mx, v.co))
    return mn, mx


mn, mx = caixa(malhas())
esc = cfg.get("escala") or (cfg["comprimento"] / (mx.x - mn.x) if cfg.get("comprimento") else 1.0)
for o in malhas():
    o.data.transform(Matrix.Scale(esc, 4))

# 2b. Rodas geradas (a máquina de lavar não tem): rodízios de borracha com miolo claro nos 4 cantos; o corpo sobe "elevar" metros
gen = cfg.get("rodas_geradas")
if gen:
    mn, mx = caixa(malhas())
    sobe = gen.get("elevar", 0.0) - mn.z
    for o in malhas():
        o.data.transform(Matrix.Translation(Vector(((mn.x + mx.x) / -2, (mn.y + mx.y) / -2, sobe))))
    r_, w_ = gen["raio"], gen["largura"]
    mat_pneu = bpy.data.materials.new("dn_borracha"); mat_pneu.use_nodes = True
    mat_pneu.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.025, 0.025, 0.025, 1)
    mat_aro = bpy.data.materials.new("dn_aro"); mat_aro.use_nodes = True
    mat_aro.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.56, 0.58, 1)
    for sx in (1, -1):
        for sy in (1, -1):
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=r_, radius2=r_, depth=w_)
            aro = bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.55 * r_, radius2=0.55 * r_, depth=w_ * 1.08)
            me = bpy.data.meshes.new("dn_roda"); bm.to_mesh(me); bm.free()
            me.materials.append(mat_pneu); me.materials.append(mat_aro)
            n_aro = len(aro["verts"])
            for p in me.polygons:
                if all(v >= len(me.vertices) - n_aro for v in p.vertices):
                    p.material_index = 1
            me.transform(Matrix.Rotation(math.pi / 2, 4, "X"))
            me.transform(Matrix.Translation((sx * gen["x"], sy * gen["y"], r_)))
            o = bpy.data.objects.new("dn_roda_%d%d" % (sx, sy), me); cena.collection.objects.link(o)
    cfg["rodas"] = "^dn_roda_"
    cfg.setdefault("materiais", {})["^dn_borracha"] = "pneu"
    cfg["materiais"]["^dn_aro"] = "cromado"

# 3. Rodas: as ilhas dos objetos das rodas, por canto
rx_rodas = re.compile(cfg["rodas"])
rodas_obj = [o for o in malhas() if rx_rodas.search(o.name)]
if not rodas_obj:
    raise SystemExit("nenhum objeto de roda casa com %r" % cfg["rodas"])
ilhas = []   # (objeto, [faces], centro)
for o in rodas_obj:
    bm = bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table()
    visto = set()
    for f in bm.faces:
        if f.index in visto:
            continue
        pilha, grupo = [f], []
        visto.add(f.index)
        while pilha:
            g = pilha.pop(); grupo.append(g.index)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in visto:
                        visto.add(h.index); pilha.append(h)
        pts = [v.co for i in grupo for v in bm.faces[i].verts]
        c = sum(pts, Vector()) / len(pts)
        ilhas.append((o, grupo, c))
    bm.free()
cx = [c.x for _, _, c in ilhas]
meio_x = (min(cx) + max(cx)) / 2
cantos = {"fl": [], "fr": [], "rl": [], "rr": []}
for o, grupo, c in ilhas:
    cantos[("f" if c.x > meio_x else "r") + ("l" if c.y > 0 else "r")].append((o, grupo))
for k, v in cantos.items():
    if not v:
        raise SystemExit("canto %s sem roda" % k)


def separa(o, faces_idx, nome):
    """Uma cópia do objeto o só com as faces faces_idx (índices do o original)."""
    n = o.copy(); n.data = o.data.copy(); n.name = nome; n.data.name = nome
    cena.collection.objects.link(n)
    bm = bmesh.new(); bm.from_mesh(n.data); bm.faces.ensure_lookup_table()
    manter = set(faces_idx)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in manter], context="FACES")
    bm.to_mesh(n.data); bm.free()
    return n


def junta(objs, nome):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    r = bpy.context.view_layer.objects.active
    r.name = nome; r.data.name = nome
    return r


rodas = {}
for k, v in cantos.items():
    partes = [separa(o, grupo, "tmp_%s_%d" % (k, i)) for i, (o, grupo) in enumerate(v)]
    rodas[k] = junta(partes, "roda_" + k)
for o in rodas_obj:
    bpy.data.objects.remove(o)
cubo, raio = {}, {}
for k, o in rodas.items():
    a, b = caixa([o])
    cubo[k] = (a + b) / 2
    raio[k] = (b.z - a.z) / 2
eixo_f = (cubo["fl"].x + cubo["fr"].x) / 2
eixo_t = (cubo["rl"].x + cubo["rr"].x) / 2
chao = min(cubo[k].z - raio[k] for k in cubo)
mn, mx = caixa(malhas())
origem = Vector(((eixo_f + eixo_t) / 2, (mn.y + mx.y) / 2, chao))
for o in malhas():
    o.data.transform(Matrix.Translation(-origem))
for k in cubo:
    cubo[k] = cubo[k] - origem
if abs(raio["fl"] - raio["rl"]) > 0.03:
    avisos.append("rodas da frente (%.2f m) e de trás (%.2f m) de raios diferentes: o jogo usa uma roda só (a dianteira direita)"
                  % (raio["fl"], raio["rl"]))

# 3b. Anexos: GLBs feitos por script (o palco do trio elétrico), já no espaço final (metros, frente +X, chão em z = 0, entre os eixos)
for an in cfg.get("anexos", []):
    antes = set(o.name for o in bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(RAIZ, an))
    for o in [o for o in bpy.data.objects if o.name not in antes]:
        if o.type != "MESH":
            continue
        if o.data.users > 1:
            o.data = o.data.copy()
        o.data.transform(o.matrix_world); o.parent = None; o.matrix_world = Matrix.Identity(4)
    for o in [o for o in bpy.data.objects if o.name not in antes and o.type != "MESH"]:
        bpy.data.objects.remove(o)

# 4. Peças e vidros por objeto (o objeto inteiro) e por caixa (ilhas do que sobrou)
papel_obj = {}
for item in cfg.get("pecas", []) + cfg.get("vidros", []):
    if "objetos" in item:
        rx = re.compile(item["objetos"])
        for o in malhas():
            if o.name not in papel_obj and not o.name.startswith("roda_") and rx.search(o.name):
                papel_obj[o.name] = item["nome"]
grupos = {}
for o in malhas():
    if o.name.startswith("roda_"):
        continue
    grupos.setdefault(papel_obj.get(o.name, "body"), []).append(o)
pecas = {nome: junta(objs, nome if nome != "body" else "body_tmp") for nome, objs in grupos.items()}
if "body_tmp" in [o.name for o in malhas()]:
    pecas["body"] = bpy.data.objects["body_tmp"]; pecas["body"].name = "body"
for item in cfg.get("pecas", []) + cfg.get("vidros", []):
    de = item.get("de", "body")
    if "caixa" not in item or de not in pecas:
        continue
    x0, x1, y0, y1, z0, z1 = item["caixa"]
    corpo = pecas[de]
    bm = bmesh.new(); bm.from_mesh(corpo.data); bm.faces.ensure_lookup_table()
    visto, levar = set(), []
    for f in bm.faces:
        if f.index in visto:
            continue
        pilha, grupo = [f], []
        visto.add(f.index)
        while pilha:
            g = pilha.pop(); grupo.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in visto:
                        visto.add(h.index); pilha.append(h)
        area_in = sum(g.calc_area() for g in grupo if x0 <= g.calc_center_median().x <= x1 and y0 <= g.calc_center_median().y <= y1
                      and z0 <= g.calc_center_median().z <= z1)
        if area_in > 0.5 * sum(g.calc_area() for g in grupo):
            levar.extend(g.index for g in grupo)
    bm.free()
    if not levar:
        avisos.append("caixa de %s não pegou nada" % item["nome"]); continue
    nova = separa(corpo, levar, item["nome"] + "_tmp")
    resto = separa(corpo, sorted(set(range(len(corpo.data.polygons))) - set(levar)), de + "_tmp2")
    bpy.data.objects.remove(corpo)
    resto.name = de; resto.data.name = de
    pecas[de] = resto
    if item["nome"] in pecas and pecas[item["nome"]].name in bpy.data.objects:
        nova = junta([pecas[item["nome"]], nova], item["nome"])
    nova.name = item["nome"]; nova.data.name = item["nome"]
    pecas[item["nome"]] = nova

# 5. Papel de cada face: o material do arquivo (regras do config) ou, na roda, banda de rodagem = pneu e o miolo = cromado
regras = [(re.compile(k), v) for k, v in cfg.get("materiais", {}).items()]
vidros = {item["nome"] for item in cfg.get("vidros", [])}
PAPEIS = ["pintura", "chassi", "luz", "cromado", "pneu", "vidro"]


def papel_do_material(nome):
    for rx, v in regras:
        if rx.search(nome):
            return v
    return "pintura"


todas = list(pecas.items()) + [("roda_" + k, o) for k, o in rodas.items()]
for nome, o in todas:
    me = o.data
    att = me.attributes.get("dn_papel") or me.attributes.new("dn_papel", "INT", "FACE")
    for p in me.polygons:
        if nome in vidros:
            r = "vidro"
        elif nome.startswith("roda_") and gen:
            m = o.material_slots[p.material_index].material
            r = "cromado" if m and m.name.startswith("dn_aro") else "pneu"
        elif nome.startswith("roda_"):
            k = nome[5:]
            c = p.center - cubo[k]
            r = "pneu" if math.hypot(c.x, c.z) > 0.62 * raio[k] else "cromado"
        else:
            m = o.material_slots[p.material_index].material if o.material_slots and p.material_index < len(o.material_slots) else None
            r = papel_do_material(m.name if m else "")
        att.data[p.index].value = PAPEIS.index(r)

# 6. Atlas: tudo menos os vidros numa malha só, UV nova, a cor difusa do autor assada, e de volta às peças
partes = [(nome, o) for nome, o in todas if nome not in vidros]
for i, (nome, o) in enumerate(partes):
    att = o.data.attributes.get("dn_parte") or o.data.attributes.new("dn_parte", "INT", "FACE")
    for p in o.data.polygons:
        att.data[p.index].value = i
copias = []
for nome, o in partes:
    c = o.copy(); c.data = o.data.copy(); cena.collection.objects.link(c); copias.append(c)
tudo = junta(copias, "atlas_tmp")
uv_orig = tudo.data.uv_layers[0].name if tudo.data.uv_layers else None
uv_novo = tudo.data.uv_layers.new(name="atlas")
tudo.data.uv_layers.active = uv_novo
bpy.ops.object.select_all(action="DESELECT"); tudo.select_set(True); bpy.context.view_layer.objects.active = tudo
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004, area_weight=0.0, scale_to_bounds=True)
bpy.ops.uv.pack_islands(margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")
img = bpy.data.images.new("%s_atlas" % CID, TAM, TAM, alpha=False)
for slot in tudo.material_slots:
    m = slot.material
    if m is None or not m.use_nodes:
        continue
    nt = m.node_tree
    # as texturas do autor seguem a UV original, mesmo com a do atlas ativa
    if uv_orig:
        for n in list(nt.nodes):
            if n.type == "TEX_IMAGE" and not n.inputs["Vector"].links:
                uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_orig
                nt.links.new(uvn.outputs["UV"], n.inputs["Vector"])
    alvo = nt.nodes.new("ShaderNodeTexImage"); alvo.image = img; alvo.name = "dn_alvo"
    nt.nodes.active = alvo
cena.render.engine = "CYCLES"; cena.cycles.device = "CPU"; cena.cycles.samples = AMOSTRAS
cena.render.bake.use_pass_direct = False; cena.render.bake.use_pass_indirect = False; cena.render.bake.use_pass_color = True
cena.render.bake.margin = 6
bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_clear=True, margin=6)
if cfg.get("apagar_vermelho"):
    # letreiro de marca pintado em vermelho na textura do autor (a máquina de lavar): o texel vermelho saturado vira a média dos vizinhos
    # que não são vermelhos (raio crescente), sem tocar no resto
    import numpy as np
    from PIL import Image as _I, ImageDraw as _D
    av = cfg["apagar_vermelho"]
    x0, x1, y0, y1, z0, z1 = av["caixa"]
    lim = av.get("limiar", 1.3)
    mascara = _I.new("L", (TAM, TAM), 0); dr = _D.Draw(mascara)
    uvt = tudo.data.uv_layers["atlas"]
    for p in tudo.data.polygons:
        c = p.center
        if x0 <= c.x <= x1 and y0 <= c.y <= y1 and z0 <= c.z <= z1:
            dr.polygon([(uvt.data[li].uv.x * TAM, uvt.data[li].uv.y * TAM) for li in p.loop_indices], fill=255)
    dentro = np.asarray(mascara) > 0
    px = np.array(img.pixels[:], dtype=np.float32).reshape(TAM, TAM, 4)
    r, g, b = px[..., 0], px[..., 1], px[..., 2]
    verm = dentro & (r > 0.3) & (r > lim * g) & (r > lim * b)
    # um texel de folga em volta (a borda antisserrilhada do letreiro)
    for _ in range(2):
        verm = verm | (dentro & (np.roll(verm, 1, 0) | np.roll(verm, -1, 0) | np.roll(verm, 1, 1) | np.roll(verm, -1, 1)) & (r > g * 1.08))
    n_verm = int(verm.sum())
    bom = ~verm
    for raio_ in (2, 4, 8, 16, 32):
        if not verm.any():
            break
        soma = np.zeros_like(px[..., :3]); cont = np.zeros((TAM, TAM), dtype=np.float32)
        for dy in range(-raio_, raio_ + 1, max(1, raio_ // 2)):
            for dx in range(-raio_, raio_ + 1, max(1, raio_ // 2)):
                m_ = np.roll(np.roll(bom, dy, 0), dx, 1)
                soma += np.roll(np.roll(px[..., :3], dy, 0), dx, 1) * m_[..., None]; cont += m_
        ok = verm & (cont > 0)
        px[..., :3][ok] = soma[ok] / cont[ok][:, None]
        verm &= ~ok; bom |= ok
    img.pixels.foreach_set(px.ravel())
    avisos.append("letreiro vermelho apagado do atlas: %d texels" % n_verm)
import tempfile
caminho_atlas = os.path.join(tempfile.gettempdir(), "%s_atlas.png" % CID)   # vai embutido no GLB; o PNG solto não fica no acervo
img.filepath_raw = caminho_atlas; img.file_format = "PNG"; img.save()
img.pack()

# os materiais nossos, todos com o atlas (o vidro, liso)
mats = {}
for r in PAPEIS:
    m = bpy.data.materials.new(r); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    if r == "vidro":
        b.inputs["Base Color"].default_value = (0.05, 0.07, 0.08, 1.0)
        b.inputs["Roughness"].default_value = 0.05
        b.inputs["Alpha"].default_value = 0.35
    else:
        t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = img
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = {"pintura": 0.4, "chassi": 0.75, "luz": 0.15, "cromado": 0.2, "pneu": 0.85}[r]
        b.inputs["Metallic"].default_value = 1.0 if r == "cromado" else 0.0
    mats[r] = m


def aplica_papeis(o):
    me = o.data
    me.materials.clear()
    usados = sorted({a.value for a in me.attributes["dn_papel"].data})
    for u in usados:
        me.materials.append(mats[PAPEIS[u]])
    for p in me.polygons:
        p.material_index = usados.index(me.attributes["dn_papel"].data[p.index].value)


# a peça i volta com a UV do atlas e os papéis
saida = {}
for i, (nome, o) in enumerate(partes):
    faces = [p.index for p in tudo.data.polygons if tudo.data.attributes["dn_parte"].data[p.index].value == i]
    n = separa(tudo, faces, nome + "_saida")
    for uv in [u for u in n.data.uv_layers if u.name != "atlas"]:
        n.data.uv_layers.remove(uv)
    n.data.uv_layers["atlas"].name = "UVMap"
    aplica_papeis(n)
    bpy.data.objects.remove(o)
    saida[nome] = n
bpy.data.objects.remove(tudo)
for nome in vidros:
    if nome in pecas:
        o = pecas[nome]
        while o.data.uv_layers:
            o.data.uv_layers.remove(o.data.uv_layers[0])
        o.data.uv_layers.new(name="UVMap")
        aplica_papeis(o)
        saida[nome] = o

# rodas: pneu e aro separados, pivô no cubo
final = {}
for nome, o in saida.items():
    if not nome.startswith("roda_"):
        o.name = nome; o.data.name = nome; final[nome] = o
        continue
    k = nome[5:]
    pp = o.data.attributes["dn_papel"].data
    pneu = [p.index for p in o.data.polygons if pp[p.index].value == PAPEIS.index("pneu")]
    aro = [p.index for p in o.data.polygons if pp[p.index].value != PAPEIS.index("pneu")]
    for nm, fs in (("wheel_%s_tire" % k, pneu), ("wheel_%s_rim" % k, aro)):
        if not fs:
            fs = [p.index for p in o.data.polygons]   # roda de uma cor só: o mesmo pedaço nos dois
            avisos.append("%s: sem faces próprias, vai a roda inteira" % nm)
        n = separa(o, fs, nm)
        n.data.transform(Matrix.Translation(-cubo[k]))
        n.location = cubo[k]
        aplica_papeis(n)
        final[nm] = n
    bpy.data.objects.remove(o)

for o in malhas():
    for nome in ("dn_parte",):
        if nome in o.data.attributes:
            o.data.attributes.remove(o.data.attributes[nome])

# 7. Medidas, JSONs e o GLB
mn, mx = caixa([o for n, o in final.items() if not n.startswith("wheel_")])
R0 = raio["fr"]
med = {"comprimento": round(mx.x - mn.x, 4), "meia_largura": round(max(-mn.y, mx.y), 4), "altura": round(mx.z, 4),
       "eixo_dianteiro": round(cubo["fr"].x, 4), "eixo_traseiro": round(cubo["rr"].x, 4), "raio_roda": round(R0, 4),
       "linha_de_cintura": round(0.55 * mx.z, 4), "topo_da_saia": round(R0 + 0.1, 4), "portas": 0, "van": False}
med.update(cfg.get("medidas", {}))

# cor da pintura: a do config ou a mediana do atlas nas faces de pintura
if cfg.get("pintura_rgb"):
    rgb = cfg["pintura_rgb"]
else:
    px = list(img.pixels)
    amostras = []
    for o in final.values():
        uv = o.data.uv_layers.get("UVMap")
        for p in o.data.polygons:
            if o.material_slots[p.material_index].material.name.split(".")[0] != "pintura" or not uv:
                continue
            u = sum(uv.data[li].uv.x for li in p.loop_indices) / len(p.loop_indices)
            v = sum(uv.data[li].uv.y for li in p.loop_indices) / len(p.loop_indices)
            ix = min(TAM - 1, max(0, int(u * TAM))); iy = min(TAM - 1, max(0, int(v * TAM)))
            j = (iy * TAM + ix) * 4
            lin = px[j:j + 3]
            amostras.append([c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in lin])
    rgb = [sorted(c)[len(c) // 2] for c in zip(*amostras)] if amostras else [0.5, 0.5, 0.5]
mxc, mnc = max(rgb), min(rgb)
info_pecas = []
for nome, o in sorted(final.items()):
    a, b = caixa([o]) if not nome.startswith("wheel_") else (o.location + caixa([o])[0], o.location + caixa([o])[1])
    info_pecas.append({"nome": nome, "caixa_m": [round(a.x, 3), round(b.x, 3), round(a.y, 3), round(b.y, 3), round(a.z, 3), round(b.z, 3)],
                       "triangulos": sum(len(p.vertices) - 2 for p in o.data.polygons),
                       "materiais": [s.material.name for s in o.material_slots if s.material],
                       "pivo_m": [round(c, 4) for c in o.location]})
pecas_json = {"id": CID, "entrada": cfg["fonte"], "gerado_por": "ferramentas/zoeira_quebravel.py",
              "convencao": "metros, frente +X, esquerda +Y, cima +Z, chão em z = 0, origem entre os eixos; rodas com o pivô no cubo",
              "dimensoes_m": [med["comprimento"], round(mx.y - mn.y, 4), med["altura"]], "escala": esc,
              "textura": {"pintura_rgb": [round(c, 4) for c in rgb], "pintura_sat": round((mxc - mnc) / mxc, 4) if mxc > 1e-4 else 0.0,
                          "pintura_val": round(mxc, 4), "atlas": os.path.basename(caminho_atlas), "tamanho": TAM},
              "pecas": info_pecas, "avisos": avisos, "notas": cfg.get("notas", "")}
json.dump(pecas_json, open(os.path.join(OUT, CID + "_pecas.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
mapa = {"car": CID, "notes": "Gerado por ferramentas/zoeira_quebravel.py a partir de %s_config.json (veículo de zoeira; peças por "
        "objeto do autor e por caixa). Metros, frente +X, ESQUERDA +Y, cima +Z, chão em z = 0, origem entre os eixos." % CID,
        "medidas": med, "parts": [{"name": p["nome"], "box": p["caixa_m"]} for p in info_pecas],
        "rodas": [{"nome": k, "lado": 1 if k[1] == "l" else -1, "cx": round(cubo[k].x, 4), "cz": round(cubo[k].z, 4), "raio": round(raio[k], 4)}
                  for k in ("fl", "fr", "rl", "rr")]}
json.dump(mapa, open(os.path.join(OUT, CID + "_mapa.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"front_axle_cm": round(cubo["fr"].x * 100, 2), "rear_axle_cm": round(cubo["rr"].x * 100, 2), "wheel_radius_cm": round(R0 * 100, 2),
           "nota": "espaço do carro do zoeira_quebravel (frente +X, pivô entre os eixos); formato de Tools/Unreal/damage_body.py"},
          open(os.path.join(OUT, CID + "_wheels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for m in list(bpy.data.materials):
    if m.users == 0:
        bpy.data.materials.remove(m)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, CID + ".glb"), export_format="GLB", export_yup=True, export_apply=False,
                          export_attributes=False)
tri = sum(p["triangulos"] for p in info_pecas)
print("[zoeira] %s: %.2f x %.2f x %.2f m, entre-eixos %.2f m, roda %.1f cm, %d peças, %d triângulos, pintura %s"
      % (CID, med["comprimento"], mx.y - mn.y, med["altura"], cubo["fr"].x - cubo["rr"].x, R0 * 100, len(final), tri, pecas_json["textura"]["pintura_rgb"]))
for a_ in avisos:
    print("[zoeira] aviso: " + a_)

# 8. Prévia: 3/4 de frente e de trás com o atlas
if PREVIA:
    import tempfile
    cena.cycles.samples = 24
    cena.render.resolution_x = 900; cena.render.resolution_y = 560
    w = bpy.data.worlds.new("w"); cena.world = w; w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.77, 0.8, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN")); sol.data.energy = 3.0
    sol.rotation_euler = (math.radians(40), math.radians(15), math.radians(30)); cena.collection.objects.link(sol)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); cam.data.lens = 40; cena.collection.objects.link(cam); cena.camera = cam
    centro = Vector((0, 0, med["altura"] * 0.45)); d = max(med["comprimento"], 2.2 * med["meia_largura"], med["altura"] * 1.6) * 1.55
    from PIL import Image
    quadros = []
    for k, dirv in enumerate(((0.75, 0.62, 0.32), (-0.75, -0.62, 0.32))):
        cam.location = centro + Vector(dirv).normalized() * d
        cam.rotation_euler = (centro - cam.location).to_track_quat("-Z", "Y").to_euler()
        f = os.path.join(tempfile.gettempdir(), "zoeira_previa_%d.png" % k); cena.render.filepath = f
        bpy.ops.render.render(write_still=True); quadros.append(Image.open(f).convert("RGB"))
    folha = Image.new("RGB", (1800, 560)); folha.paste(quadros[0], (0, 0)); folha.paste(quadros[1], (900, 0))
    folha.save(os.path.join(OUT, CID + "_previa.png"))
