"""
Textura de desgaste assada para um corte limpo (Gol Quadrado do Sketchfab, 29/10/2026): o modelo vem com a UV colapsada e uma
textura quase branca; o que faz um carro de jogo parecer de verdade à distância é a textura (oclusão nas frestas e nos cantos,
sujeira embaixo, variação leve), não a geometria. Este passo:

1. desdobra de novo todas as peças da casca (Smart UV, ilhas empacotadas juntas num atlas só), menos rodas e vidros;
2. assa no Cycles (CPU) a oclusão ambiente e a posição de cada texel;
3. compõe a cor: branco-tinta x oclusão (frestas e cantos escuros) x sujeira que sobe do chão (mais forte na saia, nos
   para-choques e atrás das rodas) x ruído fino; grava <id>_desgaste.png (2048 px) e a põe como textura de cor dos materiais
   pintados, do plástico preto e das lentes.

    python -I ferramentas/assar_desgaste.py -- <corte>.glb <saida>.glb [--tamanho 2048] [--amostras 32] [--sujeira 0.35]

No jogo (glb_texturas.py -> T_<Modelo>_C) a tinta multiplica essa textura: a cor trocável continua, com o desgaste por cima.
A prévia com a textura: montagem2 sem LISO, passando o PNG como a tinta.
"""
import sys
import numpy as np
import bpy
import bmesh
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


TAM = opt("--tamanho", 2048)
AMOSTRAS = opt("--amostras", 32)
ESTADO = opt("--estado", "novo")   # novo: carro de concessionária (só a sombra das frestas); usado: sujeira embaixo e grão
SUJEIRA = opt("--sujeira", 0.16 if ESTADO == "usado" else 0.03)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
sc = bpy.context.scene
objs = [o for o in bpy.data.objects if o.type == "MESH"]
casca = [o for o in objs if not o.name.startswith(("wheel_", "hubcap_", "glass_"))]
print("[assar_desgaste] peças na textura:", len(casca))

# 0. faces viradas (algumas da chapa de fora têm a normal para dentro e assavam escuras, em manchas): a face cuja normal entra
# na folga da chapa dupla (o raio pela normal bate em algo a menos de 2,5 cm) está virada; a pele de dentro, que olha para a
# cabine, bate longe e fica como está. Depois, normais por ângulo de novo (30°, como no preparo)
import math as _m
from mathutils.bvhtree import BVHTree
for o in casca:
    me = o.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(o.matrix_world)
    arv = BVHTree.FromBMesh(bm)
    virar = []
    for f in bm.faces:
        c = f.calc_center_median()
        # virada = a normal bate perto (entra na folga) E o sentido contrário sai livre; a chapa sob um friso ou uma maçaneta
        # bate perto nos dois sentidos (o friso na frente, a pele de dentro atrás) e não é virada
        h = arv.ray_cast(c + f.normal * 0.0015, f.normal, 0.025)
        if h[0] is not None:
            h2 = arv.ray_cast(c - f.normal * 0.0015, -f.normal, 0.025)
            if h2[0] is None:
                virar.append(f)
    if virar:
        bmesh.ops.reverse_faces(bm, faces=virar)
        bm.transform(o.matrix_world.inverted())
        bm.to_mesh(me)
        me.update()
        with bpy.context.temp_override(object=o, active_object=o, selected_objects=[o], selected_editable_objects=[o]):
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        me.shade_smooth()
        b2 = bmesh.new()
        b2.from_mesh(me)
        vivas = [False] * len(me.edges)
        for e in b2.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > _m.radians(30):
                vivas[e.index] = True
        b2.free()
        at = me.attributes.get("sharp_edge") or me.attributes.new("sharp_edge", "BOOLEAN", "EDGE")
        at.data.foreach_set("value", vivas)
        me.update()
        print("[assar_desgaste] %s: %d faces viradas corrigidas" % (o.name, len(virar)))
    bm.free()

# 1. UV nova, um atlas para todas as peças: projeção em caixa (cada face vai para o plano da sua normal dominante), uma carta
# por peça e eixo, cartas empacotadas em prateleiras na mesma densidade de texels (os operadores de UV do Blender não rodam
# fora do editor com várias peças)
EIXOS = {0: ((1, 2), (1, 1)), 1: ((0, 2), (1, 1)), 2: ((0, 1), (1, 1))}
cartas = []
for o in casca:
    me = o.data
    mw = o.matrix_world
    while len(me.uv_layers) > 1:
        me.uv_layers.remove(me.uv_layers[-1])
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    co = np.array([list(mw @ v.co) for v in me.vertices], np.float32)
    nrm = np.array([list(mw.to_3x3() @ p.normal) for p in me.polygons], np.float32)
    cen = np.array([list(mw @ p.center) for p in me.polygons], np.float32)
    eixo = np.argmax(np.abs(nrm), axis=1)
    sinal = np.sign(nrm[np.arange(len(nrm)), eixo])
    # a casca tem pele de dentro (o Gol é de chapa dupla): a face que olha para o meio do carro vai para uma carta à parte,
    # senão ela se sobrepõe à de fora do outro lado no atlas e a oclusão de dentro suja a chapa de fora
    meio = np.array([np.clip(cen[:, 0], -1.2, 1.2), np.zeros(len(cen)), np.full(len(cen), 0.6)], np.float32).T
    rel = cen - meio
    dentro = np.einsum("ij,ij->i", nrm, rel) < -0.35 * np.linalg.norm(rel, axis=1)   # só o que olha claramente para o meio
    for ax in range(3):
        for sg in (1, -1):
          for lado_dentro in (False, True):
            idx_todos = [i for i in range(len(me.polygons)) if eixo[i] == ax and sinal[i] == sg and dentro[i] == lado_dentro]
            if not idx_todos:
                continue
            # ilhas ligadas por aresta: faces em profundidades diferentes (o friso sobre a porta, a chapa atrás de outra) não se
            # projetam umas sobre as outras na mesma carta (era isso que fazia os retângulos escuros)
            conj = set(idx_todos)
            por_aresta = {}
            for i in idx_todos:
                for ek in me.polygons[i].edge_keys:
                    por_aresta.setdefault(ek, []).append(i)
            visto = set()
            ilhas = []
            for i0 in idx_todos:
                if i0 in visto:
                    continue
                pilha, ilha = [i0], []
                visto.add(i0)
                while pilha:
                    i = pilha.pop()
                    ilha.append(i)
                    for ek in me.polygons[i].edge_keys:
                        for j in por_aresta[ek]:
                            if j not in visto:
                                visto.add(j)
                                pilha.append(j)
                ilhas.append(ilha)
            for idx in ilhas:
                u_ax, v_ax = EIXOS[ax][0]
                pts = []
                for i in idx:
                    p = me.polygons[i]
                    for li in p.loop_indices:
                        c = co[me.loops[li].vertex_index]
                        u = c[u_ax] * (sg if ax != 1 else -sg)      # espelha para a carta não ficar invertida
                        pts.append((li, u, c[v_ax]))
                arr = np.array([(u, v) for _, u, v in pts], np.float32)
                mn, mx = arr.min(0), arr.max(0)
                zs = co[[me.loops[li].vertex_index for li, _, _ in pts], 2]
                cartas.append({"obj": o, "loops": [li for li, _, _ in pts], "uv": arr - mn, "tam": mx - mn, "eixo": ax,
                               "z0": float(mn[1]) if ax != 2 else float(zs.mean()), "dentro": lado_dentro})
# prateleiras: cartas por altura decrescente; escala única para caber no quadrado
area = sum(float(c["tam"][0] * c["tam"][1]) for c in cartas)
escala = 0.80 / np.sqrt(area)                     # 80% de ocupação, o resto é margem
for tent in range(80):
    cartas.sort(key=lambda c: -c["tam"][1])
    marg = 4.0 / TAM
    x = y = 0.0
    alt_pr = 0.0
    ok = True
    for c in cartas:
        w_, h_ = c["tam"][0] * escala, c["tam"][1] * escala
        if x + w_ + marg > 1.0:
            x = 0.0
            y += alt_pr + marg
            alt_pr = 0.0
        if y + h_ + marg > 1.0:
            ok = False
            break
        c["pos"] = (x + marg / 2, y + marg / 2)
        x += w_ + marg
        alt_pr = max(alt_pr, h_)
    if ok:
        break
    escala *= 0.97
print("[assar_desgaste] atlas: %d cartas, escala %.3f (%.0f texels por metro)" % (len(cartas), escala, escala * TAM))
for c in cartas:
    uv = c["obj"].data.uv_layers[0].data
    for k, li in enumerate(c["loops"]):
        uv[li].uv = (c["pos"][0] + c["uv"][k, 0] * escala, c["pos"][1] + c["uv"][k, 1] * escala)
for o in casca:
    o.data.update()

# 2. imagens-alvo e um nó de imagem ativo em cada material da casca
img_ao = bpy.data.images.new("bake_ao", TAM, TAM, alpha=False, float_buffer=True)
img_ao.colorspace_settings.name = "Non-Color"
nos = []
for o in casca:
    for slot in o.material_slots:
        m = slot.material
        if not m:
            continue
        m.use_nodes = True
        nt = m.node_tree
        n = nt.nodes.get("_bake") or nt.nodes.new("ShaderNodeTexImage")
        n.name = "_bake"
        n.image = img_ao
        nt.nodes.active = n
        nos.append(n)
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = AMOSTRAS
sc.render.bake.margin = 6
sc.render.bake.use_selected_to_active = False
sc.render.bake.use_clear = True
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
# chão para a oclusão de baixo (a saia e os para-choques ficam mais escuros perto do chão)
chao = bpy.data.objects.new("chao", bpy.data.meshes.new("chao"))
sc.collection.objects.link(chao)
bm = bmesh.new()
bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=12)
bm.to_mesh(chao.data)
bm.free()
chao.hide_render = False

def assar(tipo, img):
    """Uma peça de cada vez (com todas selecionadas, o bake de uma apagava o da anterior); o atlas acumula."""
    for n in nos:
        n.image = img
    for o in casca:
        for q in objs:
            q.select_set(q is o)
        bpy.context.view_layer.objects.active = o
        with bpy.context.temp_override(selected_objects=[o], selected_editable_objects=[o], active_object=o, object=o):
            bpy.ops.object.bake(type=tipo, margin=6, use_clear=False)
    return np.array(img.pixels[:], dtype=np.float32).reshape(TAM, TAM, 4)   # copiado já: o próximo bake descarta o buffer


ao = assar("AO", img_ao)[:, :, 0]
print("[assar_desgaste] oclusão assada; média nos texels usados %.3f" % float(ao[ao > 0.001].mean()))
# altura de cada texel pela carta (nas cartas de lado e de frente, v é z; nas de cima e de baixo, a média da carta)
z = np.full((TAM, TAM), 1.0, np.float32)
dentro_tx = np.zeros((TAM, TAM), bool)
vv = np.arange(TAM, dtype=np.float32)[:, None]
for c in cartas:
    u0, v0 = c["pos"]
    w_, h_ = c["tam"][0] * escala, c["tam"][1] * escala
    i0, i1 = max(int(v0 * TAM) - 2, 0), int((v0 + h_) * TAM) + 3
    j0, j1 = max(int(u0 * TAM) - 2, 0), int((u0 + w_) * TAM) + 3
    if c["eixo"] != 2:
        z[i0:i1, j0:j1] = c["z0"] + (vv[i0:i1] / TAM - v0) / escala
    else:
        z[i0:i1, j0:j1] = c["z0"]
    if c["dentro"]:
        dentro_tx[i0:i1, j0:j1] = True

# 3. composição
rng = np.random.default_rng(17)


def ruido_suave(passo):
    """Manchas suaves: grid grosso interpolado (sem blocos)."""
    g = rng.normal(0, 1, (TAM // passo + 2, TAM // passo + 2)).astype(np.float32)
    ys = np.linspace(0, g.shape[0] - 1.001, TAM)
    xs = np.linspace(0, g.shape[1] - 1.001, TAM)
    y0, x0 = np.floor(ys).astype(int), np.floor(xs).astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    return (g[y0][:, x0] * (1 - fy) * (1 - fx) + g[y0 + 1][:, x0] * fy * (1 - fx) + g[y0][:, x0 + 1] * (1 - fy) * fx
            + g[y0 + 1][:, x0 + 1] * fy * fx)


ruido = ruido_suave(48)
ruido_fino = rng.normal(0, 1, (TAM, TAM)).astype(np.float32)


def suave(a, b, t):
    u = np.clip((t - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


# carro novo (29/10, "as cores estão meio opacas, não tem cara de carro novo"): a oclusão só escurece de verdade as frestas e
# os cantos fechados; a chapa aberta fica com a cor cheia
if ESTADO == "usado":
    ocl = 0.70 + 0.30 * np.clip(ao, 0, 1) ** 1.2                          # frestas e cantos escuros
else:
    ocl = 0.80 + 0.20 * suave(0.15, 0.75, np.clip(ao, 0, 1))
sub = 1.0 - SUJEIRA * (1.0 - suave(0.20, 0.48, z)) * (0.85 + 0.15 * np.clip(ruido * 0.5 + 0.5, 0, 1))   # sujeira que sobe do chão
grao = 1.0 + (0.012 * ruido_fino + 0.015 * ruido if ESTADO == "usado" else 0.003 * ruido_fino)   # variação leve de chapa
cor = (0.96 if ESTADO == "usado" else 1.0) * ocl * sub * grao
cor = np.where(dentro_tx, cor * 0.7, cor)                                   # pele de dentro mais escura
cor = np.clip(cor, 0, 1)
rgb = np.stack([cor, cor * 0.995, cor * 0.985], axis=2)                    # sujeira um pouco quente
out = np.ones((TAM, TAM, 4), np.float32)
out[:, :, :3] = rgb
img_fim = bpy.data.images.new("T_desgaste", TAM, TAM, alpha=False)   # o glb_texturas.py do Detonauto reconhece "desgaste" no nome
img_fim.pixels[:] = out.ravel().tolist()
png = sai[:-4] + "_desgaste.png"
img_fim.filepath_raw = png
img_fim.file_format = "PNG"
img_fim.save()
print("[assar_desgaste] textura", png, "oclusão média %.2f" % float(ao.mean()))

# 4. a textura entra como cor dos materiais da casca (os nós de bake saem)
bpy.data.objects.remove(chao)
for o in casca:
    for slot in o.material_slots:
        m = slot.material
        if not m or not m.node_tree:
            continue
        nt = m.node_tree
        n = nt.nodes.get("_bake")
        if n:
            nt.nodes.remove(n)
        b = next((k for k in nt.nodes if k.type == "BSDF_PRINCIPLED"), None)
        if not b:
            continue
        base = m.name.split(".")[0]
        # pintura: a textura sozinha (a cor trocável multiplica por cima no jogo); os outros: a textura vezes a cor própria
        # (antes as lentes recebiam a textura clara e o vermelho e o âmbar da lanterna sumiam)
        COR_FIXA = {"chassi": (0.05, 0.05, 0.052), "luz": (0.85, 0.85, 0.83), "cromado": (0.70, 0.70, 0.72),
                    "luz_ambar": (0.95, 0.42, 0.02), "luz_branca": (0.90, 0.90, 0.88), "luz_vermelha": (0.80, 0.02, 0.015)}
        if base == "vidro":
            # vidro claro (o Felipe: "os vidros deveriam ser mais transparentes"; película no jogo, depois)
            for l in list(b.inputs["Base Color"].links):
                nt.links.remove(l)
            # transparência por alfa (15%), como o jogo (GlassOpacity 0,12): a luz atravessa reto e ilumina a cabine e o refletor
            # do farol (com vidro refrativo o Cycles deixava tudo atrás dele na sombra e o farol lia preto)
            b.inputs["Base Color"].default_value = (0.80, 0.86, 0.86, 1)
            b.inputs["Roughness"].default_value = 0.02
            b.inputs["Transmission Weight"].default_value = 0.0
            b.inputs["Alpha"].default_value = 0.15
            b.inputs["Coat Weight"].default_value = 1.0
            b.inputs["Coat Roughness"].default_value = 0.0
            try:
                m.surface_render_method = "BLENDED"
            except Exception:
                pass
            continue
        if base == "refletor":
            # acetinado: espelhado demais, ele só refletia o escuro do bolso e o farol lia como lente preta
            b.inputs["Base Color"].default_value = (0.95, 0.95, 0.96, 1)
            b.inputs["Metallic"].default_value = 1.0
            b.inputs["Roughness"].default_value = 0.32
            continue
        if base != "pintura" and base not in COR_FIXA:
            continue
        for l in list(b.inputs["Base Color"].links):
            nt.links.remove(l)
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = img_fim
        # brilho de carro novo na prévia (o jogo tem o seu verniz): tinta e lentes lisas, refletor espelhado
        BRILHO = {"pintura": dict(r=0.16, coat=1.0), "luz": dict(r=0.06, coat=1.0), "luz_ambar": dict(r=0.06, coat=1.0, tr=0.35),
                  "luz_branca": dict(r=0.06, coat=1.0, tr=0.35), "luz_vermelha": dict(r=0.06, coat=1.0, tr=0.35),
                  "cromado": dict(r=0.10, metal=1.0), "chassi": dict(r=0.55)}
        if base in BRILHO:
            pr = BRILHO[base]
            b.inputs["Roughness"].default_value = pr["r"]
            if "coat" in pr:
                b.inputs["Coat Weight"].default_value = pr["coat"]
                b.inputs["Coat Roughness"].default_value = 0.03
            if "metal" in pr:
                b.inputs["Metallic"].default_value = pr["metal"]
            if "tr" in pr:
                b.inputs["Transmission Weight"].default_value = pr["tr"]
        if base in COR_FIXA:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs[0].default_value = 1.0
            mix.inputs[7].default_value = (*COR_FIXA[base], 1)
            nt.links.new(t.outputs[0], mix.inputs[6])
            nt.links.new(mix.outputs[2], b.inputs["Base Color"])
        else:
            nt.links.new(t.outputs[0], b.inputs["Base Color"])
for o in objs:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO", use_selection=True)
print("[assar_desgaste] gravado", sai)
