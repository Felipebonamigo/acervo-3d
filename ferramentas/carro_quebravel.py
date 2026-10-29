"""
Carro quebrável: transforma um carro em peças (GLB do Sketchfab, como a série modular de Daniel Zhabotinsky) num kit de peças com
nomes padronizados, pronto para o pipeline de dano do Detonauto (Tools/Blender/split_car_parts.py e make_damage_morphs.py).

Uso (Blender 5.2 ou o módulo bpy num venv):

    blender -b --python-exit-code 1 -P ferramentas/carro_quebravel.py -- --entrada <carro.glb> --out <pasta> [opções]
    python -I ferramentas/carro_quebravel.py -- --entrada <carro.glb> --out <pasta>

Opções
    --id <nome>          id do carro (padrão: o nome do arquivo até o "__", ex. sedan-kiri-10)
    --escala <fator>     força o fator de escala (padrão: automático, pelo diâmetro das rodas e pelo comprimento)
    --amostras <n>       amostras do Cycles na prévia (padrão 24)
    --sem-previa         não renderiza
    --sem-fbx            não grava os FBX por peça

Saída em --out:
    <id>.glb                 todas as peças, com os nomes padronizados (objeto = peça, material = nome padrão)
    <id>_pecas/<peca>.fbx    uma por peça, opções de FBX iguais às do Detonauto (make_street_light.py / export_fbx_batch.py)
    <id>_texturas/           as texturas que os FBX referenciam
    <id>_pecas.json          peças com papel, lado, caixa em metros, pivô, triângulos, materiais, a peça do Detonauto e a origem
    <id>_wheels.json         eixos e raio da roda em cm, no formato que make_damage_morphs.py/split_car_parts.py leem (--wheels)
    <id>_previa.png          prévia explodida (esquerda: materiais; direita: cor por papel, com rótulos), Cycles na CPU

Convenções (as do Detonauto, docs de Tools/Blender/parts/*.json): metros, eixos do Blender, frente +X, ESQUERDA +Y, cima +Z; pivô do
carro no chão (base dos pneus), no centro entre os eixos em X e no meio da largura em Y. As peças ficam no espaço do carro (pivô do
carro), menos as rodas, que têm o pivô no centro do cubo (o JSON guarda onde ele fica).

Malha única (carros do Meshy: um objeto só, vidro e luzes pintados na textura): entra sozinho quando o arquivo tem um objeto só
(--malha-unica força, --em-pecas desliga). Acha rodas (pneu, aro, calota) pela geometria, vidros, faróis, lanternas, placas e grade pela
textura e corta capô, tampa, para-choques, portas, para-lamas, saias e retrovisores por planos a partir de <id>_mapa.json (gerado
pelas proporções; edite e passe com --mapa). Opções: --frente +x|-x, --portas 2|4, --detonauto <raiz> (prévia amassada com o
make_damage_morphs.py de lá), --debug-classes. Detalhes no ferramentas/README.md.

Regras do acervo: tira emblemas e placas (objetos com Badges/Numberplate), mesmo de marca fictícia. Nada de marca no jogo.
"""

import json
import math
import os
import re
import sys

# --------------------------------------------------------------------------------------------------------------------------------
# Tabelas (edite aqui). Os padrões valem sobre o nome do objeto em minúsculas, já sem o prefixo do modelo (Kiri10_, UTLTRUCK90_...).
# --------------------------------------------------------------------------------------------------------------------------------

# Exceções: conferidas antes das regras gerais. (padrão, papel). Papel "remover" apaga o objeto.
EXCECOES = [
    (r"steering", "interior"),                   # volante ("Steering_Wheel" casaria com a regra das rodas)
    (r"front_plate_badges", "remover"),          # Fairheaven LT80: emblema na grade
    (r"front_plate", "body"),                    # Fairheaven LT80: "Front_Plate" é o painel da frente (grade), não a placa
    (r"bullbar", "outros"),                      # Lightbody 90: quebra-mato, peça própria que solta
    (r"reardoor", "trunk"),                      # LCT3000: portas do baú (lado pela posição)
    (r"truckbed", "body"),                       # Lightbody 90: caçamba fixa na carroceria (sem tampa separada)
    (r"stockkit|stock_trim|grand_trim", "body"),  # kits e frisos da carroceria
]

# Regras gerais, na ordem. A primeira que casa vence.
REGRAS = [
    (r"badge|emblem|logo|numberplate|license|licence", "remover"),
    (r"wheel|tire|tyre|hubcap|(?:^|_)rims?(?:_|$)", "wheel"),
    (r"windshield|windscreen", "glass_windshield"),
    (r"head_?lights?|head_?lamp", "headlight"),
    (r"tail_?lights?|brake_?lights?|reverse|tail_?lamp", "taillight"),
    (r"blinker|indicator|marker|turn_?signal", "luz_auxiliar"),
    (r"glass_?rear|rear_?glass|back_?glass|rear_?window", "glass_rear"),
    (r"glass|window", "glass_door"),
    (r"hood|bonnet", "hood"),
    (r"trunk|boot|tailgate|liftgate|hatch", "trunk"),
    (r"bumper", "bumper"),                        # frente ou traseira pelo nome, senão pela posição
    (r"interior|steering|seat|dash", "interior"),
    (r"bottom|under|suspension|chassis|exhaust|axle", "underbody"),
    (r"\bbody\b|body_|_body|shell|chassi_body", "body"),
    (r"door", "door"),
    (r"mirror", "mirror"),
]

# Material: padrão sobre o nome do material original em minúsculas -> nome padrão. A primeira que casa vence.
MATERIAIS = [
    (r"transp|glass_clear|vidro", "vidro"),
    (r"light|lamp|luz", "luz"),
    (r"tire|tyre|wheel|(?:^|_)rims?(?:_|$)|pneu", "pneu"),
    (r"interior", "interior"),
    (r"chrome|cromad|metal", "cromado"),
    (r"bottom|chassi|under|plastic", "chassi"),
    (r"body|paint|pintura|carpaint", "pintura"),
]

# Peça do Detonauto (enum EDNDamagePart / EDNGlass, nomes do Tools/Blender/parts/*.json) para cada peça padronizada.
DETONAUTO = {
    "body": "Body (carroceria; portas e para-lamas ainda fundidos: cortar com split_car_parts.py)",
    "hood": "Hood", "trunk": "Trunk", "trunk_left": "Trunk (porta esquerda do baú)", "trunk_right": "Trunk (porta direita do baú)",
    "bumper_front": "BumperFront", "bumper_rear": "BumperRear",
    "glass_windshield": "Glass_Windshield", "glass_rear": "Glass_Rear",
    "glass_door_fl": "Glass_SideLeft", "glass_door_rl": "Glass_SideLeft",
    "glass_door_fr": "Glass_SideRight", "glass_door_rr": "Glass_SideRight",
    "headlight_left": "Glass_HeadlightLeft", "headlight_right": "Glass_HeadlightRight",
    "taillight_left": "Glass_TaillightLeft", "taillight_right": "Glass_TaillightRight",
    "wheel_fl": "roda FL do Chaos Vehicle", "wheel_fr": "roda FR do Chaos Vehicle",
    "wheel_rl": "roda RL do Chaos Vehicle", "wheel_rr": "roda RR do Chaos Vehicle",
    "interior": None, "underbody": None,
}

# Cores da prévia por papel (RGB 0-1).
CORES = {
    "body": (0.55, 0.62, 0.72), "hood": (0.85, 0.20, 0.15), "trunk": (0.95, 0.55, 0.10), "bumper_front": (0.95, 0.85, 0.15),
    "bumper_rear": (0.75, 0.75, 0.10), "glass_windshield": (0.20, 0.80, 0.95), "glass_rear": (0.10, 0.55, 0.85),
    "glass_door": (0.40, 0.90, 0.80), "headlight": (1.0, 1.0, 0.85), "taillight": (0.75, 0.0, 0.10), "wheel": (0.12, 0.12, 0.12),
    "interior": (0.50, 0.33, 0.20), "underbody": (0.30, 0.30, 0.30), "door": (0.30, 0.45, 0.95), "mirror": (0.6, 0.3, 0.9),
    "outros": (0.95, 0.10, 0.85),
}

# Fração do comprimento, a partir de cada ponta, onde uma ilha de luz conta como farol/lanterna; no meio vira luz lateral (carroceria).
FRACAO_PONTA = 0.25
# Escalas tentadas quando a original não é plausível (m, cm, mm, polegada, pé, dm).
ESCALAS = (1.0, 0.01, 0.001, 0.0254, 0.3048, 0.1, 100.0, 10.0)
DIAMETRO_RODA = (0.45, 1.30)   # metros, plausível para carro, picape e caminhão leve
COMPRIMENTO = (2.4, 12.0)
NORMAL_ATTR = "cq_normal"


class Erro(RuntimeError):
    pass


def log(msg):
    print("[carro_quebravel] " + msg, flush=True)


def parse_args(argv):
    import argparse
    p = argparse.ArgumentParser(prog="carro_quebravel.py")
    p.add_argument("--entrada", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--id", default=None)
    p.add_argument("--escala", type=float, default=None)
    p.add_argument("--amostras", type=int, default=24)
    p.add_argument("--sem-previa", action="store_true")
    p.add_argument("--sem-fbx", action="store_true")
    # malha única: mantém as normais que vieram no arquivo (a casca alisada pelo alisar_lataria.py); sem a opção, a solda recalcula as
    # normais pelos triângulos, como sempre foi
    p.add_argument("--manter-normais", action="store_true")
    # malha única (Meshy): automático quando o arquivo tem um objeto só
    p.add_argument("--malha-unica", action="store_true", help="força o modo malha única")
    p.add_argument("--em-pecas", action="store_true", help="força o modo em peças mesmo com um objeto só")
    p.add_argument("--frente", choices=("+x", "-x"), default=None, help="malha única: onde está a frente no arquivo")
    p.add_argument("--portas", type=int, choices=(2, 4), default=None, help="malha única: portas do carro (padrão: pelas janelas)")
    p.add_argument("--mapa", default=None, help="malha única: mapa de peças editado (<id>_mapa.json de uma rodada anterior)")
    p.add_argument("--detonauto", default=os.environ.get("DETONAUTO", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                                                                    "Detonauto")),
                   help="raiz do repositório do Detonauto (lê Tools/Blender/make_damage_morphs.py para a prévia amassada)")
    p.add_argument("--debug-classes", action="store_true", help="malha única: grava <id>_classes.png com as classes de textura")
    # malha única com mapa à mão (carros do Sketchfab com pintura clara, 29/10/2026): não classifica nada pela cor da textura; os
    # vidros vêm do material 'vidro' já marcado no arquivo (take: material) e o resto das caixas do mapa
    p.add_argument("--sem-rotulos", action="store_true", help="malha única: ignora a classificação pela textura (rótulos só do mapa)")
    return p.parse_args(argv)


# --------------------------------------------------------------------------------------------------------------------------------
# Classificação
# --------------------------------------------------------------------------------------------------------------------------------

def nome_limpo(nome, prefixo):
    n = nome
    if prefixo and n.startswith(prefixo):
        n = n[len(prefixo):]
    n = re.sub(r"\.\d+$", "", n)
    return n.lower()


def prefixo_comum(nomes):
    """O prefixo do modelo (Kiri10_, Fairheaven_LT80_): o maior prefixo terminado em '_' comum a quase todos os objetos."""
    if not nomes:
        return ""
    cont = {}
    for n in nomes:
        partes = n.split("_")
        for i in range(1, min(3, len(partes))):
            pre = "_".join(partes[:i]) + "_"
            cont[pre] = cont.get(pre, 0) + 1
    bons = [p for p, c in cont.items() if c >= 0.8 * len(nomes)]
    return max(bons, key=len) if bons else ""


def papel_do_nome(nome_obj):
    for pad, papel in EXCECOES:
        if re.search(pad, nome_obj):
            return papel, "exceção /%s/" % pad
    for pad, papel in REGRAS:
        if re.search(pad, nome_obj):
            return papel, "regra /%s/" % pad
    return None, "sem regra"


def papel_do_material(nome_mat):
    """Último recurso: objeto sem regra pelo nome, mas com material conhecido."""
    m = nome_mat.lower()
    if re.search(r"badge|numberplate", m):
        return "remover"
    if re.search(r"tire|tyre", m):
        return "wheel"
    if re.search(r"interior", m):
        return "interior"
    return None


def material_padrao(nome_mat):
    m = nome_mat.lower()
    for pad, padrao in MATERIAIS:
        if re.search(pad, m):
            return padrao
    return None


# --------------------------------------------------------------------------------------------------------------------------------
# Blender
# --------------------------------------------------------------------------------------------------------------------------------

def caixa_pontos(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]


def caixa_obj(obj):
    if not obj.data.vertices:
        return None
    return caixa_pontos([v.co for v in obj.data.vertices])


def uniao(caixas):
    caixas = [c for c in caixas if c]
    return [min(c[0] for c in caixas), max(c[1] for c in caixas), min(c[2] for c in caixas), max(c[3] for c in caixas),
            min(c[4] for c in caixas), max(c[5] for c in caixas)]


def centro(c):
    return ((c[0] + c[1]) / 2.0, (c[2] + c[3]) / 2.0, (c[4] + c[5]) / 2.0)


def importar(caminho):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ext = os.path.splitext(caminho)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=caminho)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=caminho)
    else:
        raise Erro("Formato não suportado: %s (use .glb, .gltf ou .fbx)" % ext)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise Erro("Nenhuma malha em %s" % caminho)
    return meshes


def guardar_normais(me):
    """A normal de cada canto num atributo: atravessa transformações e o bmesh (as normais personalizadas não)."""
    if NORMAL_ATTR in me.attributes:
        me.attributes.remove(me.attributes[NORMAL_ATTR])
    attr = me.attributes.new(NORMAL_ATTR, "FLOAT_VECTOR", "CORNER")
    buf = [0.0] * (len(me.loops) * 3)
    me.corner_normals.foreach_get("vector", buf)
    attr.data.foreach_set("vector", buf)


def restaurar_normais(me):
    from mathutils import Vector
    attr = me.attributes.get(NORMAL_ATTR)
    if attr is None:
        return
    ns = []
    for d in attr.data:
        v = Vector(d.vector)
        ns.append(v.normalized() if v.length > 1e-8 else Vector((0.0, 0.0, 1.0)))
    me.normals_split_custom_set(ns)
    me.attributes.remove(me.attributes[NORMAL_ATTR])


def assar_transformacoes(meshes):
    """Aplica a matriz do mundo na malha (com as normais, inclusive escala não uniforme e espelho), solta dos pais e apaga os vazios."""
    import bpy
    from mathutils import Matrix
    for o in meshes:
        me = o.data
        if me.users > 1:
            o.data = me = me.copy()
        mw = o.matrix_world.copy()
        guardar_normais(me)
        nmat = mw.to_3x3().inverted_safe().transposed()
        attr = me.attributes[NORMAL_ATTR]
        for d in attr.data:
            d.vector = (nmat @ d.vector).normalized()
        me.transform(mw)
        if mw.determinant() < 0.0:
            me.flip_normals()
            # flip_normals inverte a ordem dos cantos; o atributo de canto acompanha a ordem, então a normal guardada continua valendo
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
        restaurar_normais(me)
    for o in list(bpy.data.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)


def transformar_tudo(meshes, mat):
    for o in meshes:
        me = o.data
        guardar_normais(me)
        rot = mat.to_3x3().normalized()
        attr = me.attributes[NORMAL_ATTR]
        for d in attr.data:
            d.vector = (rot @ d.vector).normalized()
        me.transform(mat)
        restaurar_normais(me)


def ilhas_faces(me):
    """Grupos de índices de polígono conectados por vértice."""
    pai = list(range(len(me.vertices)))

    def achar(a):
        while pai[a] != a:
            pai[a] = pai[pai[a]]
            a = pai[a]
        return a
    for p in me.polygons:
        vs = p.vertices
        r0 = achar(vs[0])
        for v in vs[1:]:
            r = achar(v)
            if r != r0:
                pai[r] = r0
    grupos = {}
    for p in me.polygons:
        grupos.setdefault(achar(p.vertices[0]), []).append(p.index)
    return list(grupos.values())


def separar(obj, atribuicao, prefixo_nome):
    """Divide obj em vários objetos, um por valor de atribuicao[face]. Devolve {valor: objeto}."""
    import bmesh
    import bpy
    valores = sorted(set(atribuicao))
    if len(valores) == 1:
        return {valores[0]: obj}
    guardar_normais(obj.data)
    out = {}
    for val in valores:
        me = obj.data.copy()
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        apagar = [f for f in bm.faces if atribuicao[f.index] != val]
        bmesh.ops.delete(bm, geom=apagar, context="FACES")
        bm.to_mesh(me)
        bm.free()
        novo = bpy.data.objects.new("%s__%s" % (prefixo_nome, val), me)
        bpy.context.scene.collection.objects.link(novo)
        restaurar_normais(me)
        out[val] = novo
    bpy.data.objects.remove(obj, do_unlink=True)
    return out


def juntar(objs, nome):
    import bpy
    for o in objs:
        guardar_normais(o.data)
    if len(objs) > 1:
        with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
            bpy.ops.object.join()
    o = objs[0]
    o.name = nome
    o.data.name = nome
    restaurar_normais(o.data)
    return o


def limpar_malha(obj):
    """Valida a malha: tira faces degeneradas e vértices soltos, confere NaN. Devolve um resumo."""
    import bmesh
    me = obj.data
    guardar_normais(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    nan = sum(1 for v in bm.verts if any(math.isnan(c) or math.isinf(c) for c in v.co))
    degeneradas = [f for f in bm.faces if f.calc_area() < 1e-10]
    nd = len(degeneradas)
    if degeneradas:
        bmesh.ops.delete(bm, geom=degeneradas, context="FACES_ONLY")
    soltos = [v for v in bm.verts if not v.link_faces]
    ns = len(soltos)
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    arestas_soltas = [e for e in bm.edges if not e.link_faces]
    if arestas_soltas:
        bmesh.ops.delete(bm, geom=arestas_soltas, context="EDGES")
    bm.to_mesh(me)
    bm.free()
    restaurar_normais(me)
    me.validate(clean_customdata=False)
    return {"faces_degeneradas_tiradas": nd, "vertices_soltos_tirados": ns, "vertices_nan": nan}


def conferir_normais(obj, papel, eixo):
    """
    Duas medidas: (1) cantos cuja normal (do arquivo) aponta contra a normal da face: face com a ordem dos vértices trocada;
    (2) área de faces viradas para FORA do carro: "fora" é a direção que se afasta do eixo central (segmento em X a meia altura, como o
    Core do split_car_parts.py); para a roda, do centro do cubo. Casca fechada dá ~0,5 a 1; interior e chassi dão menos, e está certo.
    Correções: mais da metade dos cantos contra a face -> vira as faces (a normal do arquivo manda); vidro com menos de 30 % da área
    para fora -> vidro de uma face só virado para dentro: vira as faces E as normais.
    """
    from mathutils import Vector
    me = obj.data
    if not me.polygons:
        return {"cantos_contra_face": 0.0, "area_para_fora": 0.0, "virada": False}

    def medir():
        cn = [0.0] * (len(me.loops) * 3)
        me.corner_normals.foreach_get("vector", cn)
        contra = 0
        for p in me.polygons:
            n = p.normal
            for li in p.loop_indices:
                if n.x * cn[3 * li] + n.y * cn[3 * li + 1] + n.z * cn[3 * li + 2] < 0.0:
                    contra += 1
        fora = total = 0.0
        if papel == "wheel":
            c0 = Vector(centro(caixa_obj(obj)))
        for p in me.polygons:
            if papel == "wheel":
                ref = c0
            else:
                a, b = eixo
                ab = b - a
                t = max(0.0, min(1.0, (p.center - a).dot(ab) / ab.length_squared))
                ref = a + ab * t
            total += p.area
            if (p.center - ref).dot(p.normal) > 0.0:
                fora += p.area
        return contra / max(1, len(me.loops)), (fora / total if total else 0.0)
    frac, fora = medir()
    virada = None
    if frac > 0.5:
        guardar_normais(me)
        me.flip_normals()
        restaurar_normais(me)
        virada = "faces (ordem dos vértices contra a normal do arquivo)"
        frac, fora = medir()
    elif papel.startswith("glass") and fora < 0.3:
        guardar_normais(me)
        attr = me.attributes[NORMAL_ATTR]
        for d in attr.data:
            d.vector = (-Vector(d.vector))
        me.flip_normals()
        restaurar_normais(me)
        virada = "faces e normais (vidro de uma face virado para dentro)"
        frac, fora = medir()
    return {"cantos_contra_face": round(frac, 3), "area_para_fora": round(fora, 3), "virada": virada}


def purgar():
    """Malhas órfãs seguram os materiais: sem isso, o material dos emblemas apagados continuaria no arquivo."""
    import bpy
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    for m in list(bpy.data.materials):
        if m.users == 0:
            bpy.data.materials.remove(m)


def triangulos(me):
    return sum(len(p.vertices) - 2 for p in me.polygons)


# --------------------------------------------------------------------------------------------------------------------------------
# Passos
# --------------------------------------------------------------------------------------------------------------------------------

def classificar(meshes, relatorio):
    """Papel por objeto (nome, depois material). Devolve [(obj, papel, motivo, nome_limpo)]."""
    import bpy
    pre = prefixo_comum([o.name for o in meshes])
    relatorio["prefixo"] = pre
    out = []
    for o in meshes:
        # nome do objeto do glTF do Sketchfab: <Nó>_<Material>_<n>; o nó pai (vazio) tem só o nome da peça
        base = o.name
        mats = [m.name for m in o.data.materials if m]
        for m in mats:
            base = base.replace("_" + m, "")
        base = re.sub(r"_\d+(\.\d+)?$", "", base)
        n = nome_limpo(base, pre)
        papel, motivo = papel_do_nome(n)
        if papel is None:
            for m in mats:
                papel = papel_do_material(m)
                if papel:
                    motivo = "material %s" % m
                    break
        if papel is None:
            papel, motivo = "outros", "não reconhecido"
        out.append((o, papel, motivo, n, o.name))
    removidos = [(nm, mot) for o, p, mot, n, nm in out if p == "remover"]
    for o, p, mot, n, nm in out:
        if p == "remover":
            bpy.data.objects.remove(o, do_unlink=True)
    purgar()
    relatorio["limpos"] = {nm: n for o, p, mot, n, nm in out}
    relatorio["removidos"] = [{"objeto": nm, "motivo": mot} for nm, mot in removidos]
    return [x for x in out if x[1] != "remover"]


def escolher_escala(itens, forcada, relatorio):
    rodas = [caixa_obj(o) for o, p, *_ in itens if p == "wheel"]
    tudo = uniao([caixa_obj(o) for o, *_ in itens])
    dims = sorted([tudo[1] - tudo[0], tudo[3] - tudo[2]], reverse=True)
    comp = dims[0]
    diam = None
    if rodas:
        diam = sum(max(c[1] - c[0], c[5] - c[4]) for c in rodas) / len(rodas)
    if forcada:
        relatorio["escala"] = {"fator": forcada, "motivo": "--escala"}
        return forcada

    def nota(f):
        ok_c = COMPRIMENTO[0] <= comp * f <= COMPRIMENTO[1]
        if diam:
            ok_d = DIAMETRO_RODA[0] <= diam * f <= DIAMETRO_RODA[1]
            return (ok_c and ok_d, ok_c or ok_d, -abs(math.log(diam * f / 0.68)))
        return (ok_c, ok_c, -abs(math.log(comp * f / 4.5)))
    fator = max(ESCALAS, key=nota)
    if not nota(fator)[1]:
        raise Erro("Escala implausível: comprimento %.3f, roda %s (unidades do arquivo). Use --escala." % (comp, diam))
    relatorio["escala"] = {"fator": fator, "comprimento_original": round(comp, 4), "roda_original": round(diam, 4) if diam else None,
                           "motivo": "automático (roda de %.2f a %.2f m, comprimento de %.1f a %.1f m)" % (DIAMETRO_RODA + COMPRIMENTO)}
    return fator


def orientar(itens, fator, relatorio):
    """Escala e gira (só em torno de Z) para a frente ficar em +X; pivô no chão, no meio entre os eixos."""
    from mathutils import Matrix
    meshes = [o for o, *_ in itens]
    tudo = uniao([caixa_obj(o) for o in meshes])
    passos = []
    rot = Matrix.Identity(4)
    if (tudo[3] - tudo[2]) > (tudo[1] - tudo[0]):
        rot = Matrix.Rotation(math.radians(-90.0), 4, "Z")  # comprimento em Y: +Y vira +X
        passos.append("90° em Z (comprimento estava em Y)")
    transformar_tudo(meshes, rot @ Matrix.Scale(fator, 4))

    def cx(papeis):
        cs = [caixa_obj(o) for o, p, *_ in itens if p in papeis]
        cs = [c for c in cs if c]
        return sum(centro(c)[0] for c in cs) / len(cs) if cs else None
    frente = cx(("headlight", "glass_windshield", "hood", "bumper_front"))
    tras = cx(("taillight", "glass_rear", "trunk"))
    volante = cx(("interior",))
    if frente is not None and tras is not None:
        ok = frente > tras
        motivo = "faróis/para-brisa x lanternas"
    else:
        ok = True
        motivo = "sem faróis e lanternas: mantida"
    if not ok:
        transformar_tudo(meshes, Matrix.Rotation(math.pi, 4, "Z"))
        passos.append("180° em Z (%s)" % motivo)
    del volante
    rodas = [caixa_obj(o) for o, p, *_ in itens if p == "wheel"]
    tudo = uniao([caixa_obj(o) for o in meshes])
    if rodas:
        xs = sorted(centro(c)[0] for c in rodas)
        meio = (tudo[0] + tudo[1]) / 2.0
        diant = [x for x in xs if x > meio] or xs[-1:]
        tras_ = [x for x in xs if x <= meio] or xs[:1]
        cx_ = (sum(diant) / len(diant) + sum(tras_) / len(tras_)) / 2.0
        chao = min(c[4] for c in rodas)
    else:
        cx_ = (tudo[0] + tudo[1]) / 2.0
        chao = tudo[4]
    cy = (tudo[2] + tudo[3]) / 2.0
    transformar_tudo(meshes, Matrix.Translation((-cx_, -cy, -chao)))
    relatorio["orientacao"] = passos or ["já estava com a frente em +X"]


def dividir_por_lado_e_posicao(itens, relatorio):
    """
    Peças que vêm juntas no arquivo (os dois faróis num objeto, vidros de trás dos dois lados, luzes espalhadas pelo carro) são divididas
    por ilha: lado pelo sinal de Y, ponta pela posição em X. Devolve [(obj, peça, papel, origem)].
    """
    meshes = [o for o, *_ in itens]
    tudo = uniao([caixa_obj(o) for o in meshes])
    comp = tudo[1] - tudo[0]
    x_frente = tudo[1] - FRACAO_PONTA * comp
    x_tras = tudo[0] + FRACAO_PONTA * comp
    larg = tudo[3] - tudo[2]
    out = []
    avisos = relatorio.setdefault("avisos", [])

    def lado_y(y):
        return "left" if y >= 0.0 else "right"

    for o, papel, motivo, n, orig in itens:
        me = o.data
        if papel in ("headlight", "taillight", "luz_auxiliar"):
            atr = [None] * len(me.polygons)
            for grupo in ilhas_faces(me):
                ys = [me.polygons[i].center.y for i in grupo]
                xs = [me.polygons[i].center.x for i in grupo]
                gx = sum(xs) / len(xs)
                gy = sum(ys) / len(ys)
                larg_ilha = max(ys) - min(ys)
                if gx >= x_frente:
                    base = "headlight"
                elif gx <= x_tras:
                    base = "taillight"
                else:
                    base = None
                for i in grupo:
                    if base is None:
                        atr[i] = "body"
                    elif larg_ilha > 0.5 * larg and abs(gy) < 0.1 * larg:  # ilha que atravessa o carro: corta pela face
                        atr[i] = "%s_%s" % (base, lado_y(me.polygons[i].center.y))
                    else:
                        atr[i] = "%s_%s" % (base, lado_y(gy))
            if papel != "luz_auxiliar" and any(a == "body" for a in atr):
                avisos.append("%s: ilhas de luz no meio do carro foram para a carroceria (luz lateral)" % orig)
            for val, ob in separar(o, atr, n).items():
                out.append((ob, val, val.split("_")[0] if val != "body" else "body", orig))
        elif papel in ("glass_door", "door", "trunk", "mirror"):
            c = caixa_obj(o)
            atravessa = c[2] < -0.25 * larg and c[3] > 0.25 * larg
            frente_tras = ""
            if papel in ("glass_door", "door"):
                eh_frente = bool(re.search(r"driver|passeng|passang|front", n))
                eh_tras = bool(re.search(r"rear|back|body|quarter", n)) or (n in ("glass", "window"))
                if not eh_frente and not eh_tras:
                    eh_frente = centro(c)[0] > 0.0
                frente_tras = "f" if eh_frente and not eh_tras else "r"
            if papel in ("trunk", "mirror") and atravessa:
                atravessa = False  # tampa inteira (porta-malas): não divide
                partes = {"centro": o}
            elif atravessa or papel in ("glass_door", "door"):
                atr = [lado_y(p.center.y) for p in me.polygons] if atravessa else [lado_y(centro(c)[1])] * len(me.polygons)
                partes = separar(o, atr, n)
            else:
                partes = {lado_y(centro(c)[1]): o}
            for lado, ob in partes.items():
                if papel in ("glass_door", "door"):
                    nome_lado = "%s_%s%s" % (papel, frente_tras, "l" if lado == "left" else "r")
                    # nome que contradiz a posição (Driver do lado direito): vale a posição
                    if re.search(r"driver", n) and lado == "right" or re.search(r"passeng|passang", n) and lado == "left":
                        avisos.append("%s: nome diz %s, a posição diz %s; valeu a posição" % (
                            orig, "motorista" if "driver" in n else "passageiro", "direita" if lado == "right" else "esquerda"))
                elif lado != "centro" and (papel == "trunk" and re.search(r"left|right", n) or papel == "mirror"):
                    nome_lado = "%s_%s" % (papel, lado)
                else:
                    nome_lado = papel
                out.append((ob, nome_lado, papel, orig))
        elif papel == "wheel":
            c = centro(caixa_obj(o))
            nome_pos = "wheel_%s%s" % ("f" if c[0] > 0.0 else "r", "l" if c[1] >= 0.0 else "r")
            m = re.search(r"(?:^|_)(fl|fr|rl|rr|lf|rf|lr)(?:_|$)", n)
            if m:
                dito = {"lf": "fl", "rf": "fr", "lr": "rl"}.get(m.group(1), m.group(1))
                if "wheel_" + dito != nome_pos:
                    avisos.append("%s: nome diz %s, a posição diz %s; valeu a posição" % (orig, dito.upper(), nome_pos[6:].upper()))
            out.append((o, nome_pos, "wheel", orig))
        elif papel == "bumper":
            if re.search(r"front", n):
                nb = "bumper_front"
            elif re.search(r"rear|back", n):
                nb = "bumper_rear"
            else:
                nb = "bumper_front" if centro(caixa_obj(o))[0] > 0.0 else "bumper_rear"
            out.append((o, nb, nb, orig))
        else:
            out.append((o, papel, papel, orig))
    return out


def padronizar_materiais(relatorio):
    import bpy
    mapa = {}
    usados = {}
    for m in sorted(bpy.data.materials, key=lambda m: m.name):
        if m.users == 0:
            continue
        pad = material_padrao(m.name)
        if pad is None:
            pad = "outro"
            relatorio.setdefault("avisos", []).append("material sem regra: %s (ficou 'outro')" % m.name)
        n = usados.get(pad, 0)
        usados[pad] = n + 1
        novo = pad if n == 0 else "%s_%d" % (pad, n + 1)
        mapa[m.name] = novo
    for m in list(bpy.data.materials):
        if m.name in mapa:
            m.name = "__tmp__" + mapa[m.name]
    for m in bpy.data.materials:
        if m.name.startswith("__tmp__"):
            m.name = m.name[len("__tmp__"):]
    relatorio["materiais"] = mapa
    return mapa


def salvar_texturas(pasta):
    import bpy
    os.makedirs(pasta, exist_ok=True)
    feitas = 0
    for img in bpy.data.images:
        if img.source != "FILE" or not (img.packed_file or img.has_data):
            continue
        nome = re.sub(r"[^A-Za-z0-9_.-]+", "_", img.name)
        ext = ".jpg" if img.file_format == "JPEG" else ".png"
        if not nome.lower().endswith(ext):
            nome = os.path.splitext(nome)[0] + ext
        destino = os.path.join(pasta, nome)
        try:
            if img.packed_file:
                with open(destino, "wb") as fh:
                    fh.write(img.packed_file.data)
            else:
                img.save(filepath=destino)
            img.filepath = destino
            img.filepath_raw = destino
            if img.packed_file:
                img.unpack(method="REMOVE")  # passa a ler do arquivo gravado (o FBX referencia este caminho)
            feitas += 1
        except Exception as exc:  # noqa: BLE001
            log("aviso: textura %s não gravada: %r" % (img.name, exc))
    return feitas


def exportar_fbx(obj, caminho):
    """Opções do Detonauto (Tools/Blender/make_street_light.py e export_fbx_batch.py). A peça vai com o pivô dela na origem do FBX."""
    import bpy
    loc = obj.location.copy()
    obj.location = (0.0, 0.0, 0.0)
    for o in bpy.context.scene.objects:
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.fbx(filepath=caminho, use_selection=True, object_types={"MESH"}, axis_forward="-Z", axis_up="Y",
                             apply_unit_scale=True, global_scale=1.0, apply_scale_options="FBX_SCALE_NONE",
                             bake_space_transform=True, use_mesh_modifiers=True, mesh_smooth_type="OFF",
                             add_leaf_bones=False, path_mode="AUTO")
    obj.location = loc


# --------------------------------------------------------------------------------------------------------------------------------
# Prévia explodida
# --------------------------------------------------------------------------------------------------------------------------------

def previa(pecas, caminho, amostras, comp):
    import bpy
    import numpy as np
    from mathutils import Vector
    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = amostras
    cena.cycles.use_denoising = True
    try:
        cena.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:  # noqa: BLE001
        pass
    cena.cycles.max_bounces = 4
    cena.render.resolution_x = 1100
    cena.render.resolution_y = 760
    cena.render.film_transparent = False
    cena.view_settings.view_transform = "Standard" if "Standard" in [i.identifier for i in
                                                            cena.view_settings.bl_rna.properties["view_transform"].enum_items] else "Standard"
    mundo = bpy.data.worlds.new("previa")
    mundo.use_nodes = True
    bg = mundo.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.82, 0.84, 0.88, 1.0)
    bg.inputs[1].default_value = 0.45
    cena.world = mundo

    # explode: cada peça se afasta do centro do carro; capô e teto sobem, rodas saem para o lado
    originais = {}
    for ob, info in pecas:
        originais[ob.name] = ob.location.copy()
        c = Vector(info["centro"])
        papel = info["papel"]
        d = Vector((c.x * 0.45, c.y * 1.6, 0.0))
        if papel in ("hood", "trunk", "glass_windshield", "glass_rear"):
            d.z += 0.55
        if papel in ("glass_door",):
            d.z += 0.35
            d.y += 0.35 * (1 if c.y >= 0 else -1)
        lado = 1 if c.y >= 0 else -1
        if papel == "wheel":
            d.y += 0.7 * lado
        if papel == "rim":
            d.y += 1.15 * lado
        if papel == "hubcap":
            d.y += 1.55 * lado
        if papel == "door":
            d.y += 0.45 * lado
        if papel == "fender":
            d.y += 0.35 * lado
            d.z += 0.15
        if papel == "side_skirt":
            d.y += 0.55 * lado
            d.z -= 0.35
        if papel == "mirror":
            d.y += 0.75 * lado
            d.z += 0.45
        if papel == "grille":
            d.x += 0.95
        if papel == "plate":
            d.x += 1.25 * (1 if c.x >= 0 else -1)
            d.z -= 0.15
        if papel in ("bumper_front", "bumper_rear", "headlight", "taillight"):
            d.x += 0.55 * (1 if c.x >= 0 else -1)
        if papel == "underbody":
            d.z -= 0.6
        if papel == "interior":
            d.z += 1.0
            d.y -= 1.4
        if papel == "outros":
            d.z += 0.9
        ob.location = ob.location + d

    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 2.2
    sol.data.angle = math.radians(8)
    sol.rotation_euler = (math.radians(40), math.radians(10), math.radians(150))
    cena.collection.objects.link(sol)
    chao = bpy.data.meshes.new("chao")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=comp * 3)
    bm.to_mesh(chao)
    bm.free()
    och = bpy.data.objects.new("chao", chao)
    och.location.z = -0.95
    mch = bpy.data.materials.new("chao_previa")
    mch.diffuse_color = (0.7, 0.7, 0.7, 1)
    och.data.materials.append(mch)
    cena.collection.objects.link(och)

    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    cena.collection.objects.link(cam)
    cena.camera = cam
    alvo = Vector((0.0, 0.0, 0.6))
    direcao = Vector((1.0, 0.95, 0.75)).normalized()
    cam.location = alvo + direcao * comp * 3.0
    cam.rotation_euler = (alvo - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = comp * 2.15
    cam.data.clip_end = comp * 10

    def render(arquivo):
        cena.render.filepath = arquivo
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(arquivo)
        px = np.array(img.pixels[:], dtype=np.float32).reshape(img.size[1], img.size[0], 4)
        bpy.data.images.remove(img)
        return px

    tmp1 = caminho + ".mat.png"
    tmp2 = caminho + ".pap.png"
    a = render(tmp1)

    # cor por papel + rótulos
    guardados = {}
    mats_papel = {}
    rotulos = []
    for ob, info in pecas:
        papel = info["papel"]
        cor = CORES.get(papel, CORES["outros"])
        if papel not in mats_papel:
            m = bpy.data.materials.new("papel_" + papel)
            m.use_nodes = True
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (cor[0], cor[1], cor[2], 1)
            bsdf.inputs["Roughness"].default_value = 0.6
            mats_papel[papel] = m
        guardados[ob.name] = [s.material for s in ob.material_slots]
        for s in ob.material_slots:
            s.material = mats_papel[papel]
        txt = bpy.data.curves.new("r_" + info["nome"], "FONT")
        txt.body = info["nome"]
        txt.size = comp * 0.032
        txt.align_x = "CENTER"
        ot = bpy.data.objects.new("r_" + info["nome"], txt)
        c = Vector(info["centro"]) + (ob.location - originais[ob.name])
        topo = info["caixa_m"][5] + (ob.location - originais[ob.name]).z
        ot.location = Vector((c.x, c.y, topo + 0.08)) + direcao * 1.5
        ot.rotation_euler = cam.rotation_euler
        mt = bpy.data.materials.new("rot_" + info["nome"])
        mt.use_nodes = True
        nt = mt.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs[0].default_value = (0.0, 0.0, 0.0, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(em.outputs[0], out.inputs[0])
        txt.materials.append(mt)
        cena.collection.objects.link(ot)
        rotulos.append(ot)
    b = render(tmp2)
    for ob, info in pecas:
        for s, m in zip(ob.material_slots, guardados[ob.name]):
            s.material = m
        ob.location = originais[ob.name]
    for ot in rotulos:
        bpy.data.objects.remove(ot, do_unlink=True)
    for o in (sol, och, cam):
        bpy.data.objects.remove(o, do_unlink=True)
    junto = np.concatenate([a, b], axis=1)
    h, w = junto.shape[:2]
    img = bpy.data.images.new("previa", w, h, alpha=True)
    img.pixels = junto.ravel().tolist()
    img.filepath_raw = caminho
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    for t in (tmp1, tmp2):
        os.remove(t)


# --------------------------------------------------------------------------------------------------------------------------------
# Modo malha única (carros do Meshy: uma malha só, textura PBR, vidro e luzes pintados na textura)
# --------------------------------------------------------------------------------------------------------------------------------
#
# A malha chega como "sopa" de ilhas de UV (cada ilha de UV é uma ilha de geometria). Ela é soldada por distância (os UVs ficam nos
# cantos, nada estica), orientada pelos retrovisores (que ficam na frente da metade do carro), e as peças saem por três regras:
#   roda     cilindro em torno do cubo, achado pela banda de rodagem (faces a um raio R do cubo, com a normal para fora do cubo);
#            pneu/aro/calota pelo raio e pela cor da face externa
#   textura  classe da face pela cor da textura nos UVs dela (vidro, farol, lanterna, placa, grade), com fechamento morfológico
#   faces    corte por planos de uma caixa (como o split_car_parts.py do Detonauto), com filtro de normal
# Cada peça sai fechada (casca com espessura, lado de dentro escuro) e deixa na carroceria um "vão" escuro (MI_DNVao); as rodas deixam
# uma caixa de roda escura. O mapa gerado (<id>_mapa.json) pode ser editado e passado de volta com --mapa.

# Classes de textura (atributo de face).
CL_NADA, CL_VIDRO, CL_FAROL, CL_LANTERNA, CL_PLACA, CL_GRADE = 0, 1, 2, 3, 4, 5
CLASSES = {"vidro": CL_VIDRO, "farol": CL_FAROL, "lanterna": CL_LANTERNA, "placa": CL_PLACA, "grade": CL_GRADE}

# Peças da malha única que o vocabulário do Detonauto (EDNDamagePart, EDNGlass, docs/regras-pecas.md) ainda não tem.
FORA_DO_DETONAUTO = ("door_rl", "door_rr", "side_skirt_left", "side_skirt_right", "mirror_left", "mirror_right", "grille",
                     "plate_front", "plate_rear", "wheel_*_tire / wheel_*_rim (a roda inteira é do Chaos Vehicle)", "hubcap_*")
DETONAUTO.update({
    "door_fl": "DoorLeft", "door_fr": "DoorRight", "door_rl": None, "door_rr": None,
    "fender_front_left": "FenderFrontLeft", "fender_front_right": "FenderFrontRight",
    "fender_rear_left": "FenderRearLeft", "fender_rear_right": "FenderRearRight",
    "side_skirt_left": None, "side_skirt_right": None, "mirror_left": None, "mirror_right": None, "grille": None,
    "plate_front": None, "plate_rear": None,
})
CORES.update({
    "fender": (0.55, 0.85, 0.35), "side_skirt": (0.35, 0.30, 0.65), "grille": (0.20, 0.20, 0.25), "plate": (0.98, 0.98, 0.98),
    "rim": (0.75, 0.75, 0.78), "hubcap": (0.95, 0.80, 0.30),
})
MAT_ESCURO = "chassi"      # lado de dentro das peças e caixa de roda (o split_car_parts.py procura "Chassi")
MAT_VAO = "MI_DNVao"       # vão deixado na carroceria (o Unreal liga ao MI_DNVao pelo nome)


def _arr(me, coll, attr, n, dtype=None):
    import numpy as np
    seq = getattr(me, coll)
    a = np.empty(len(seq) * n, dtype or np.float32)
    seq.foreach_get(attr, a)
    return a.reshape(-1, n) if n > 1 else a


def _faces_np(me):
    return _arr(me, "polygons", "center", 3), _arr(me, "polygons", "normal", 3), _arr(me, "polygons", "area", 1)


def _imagem_base(me):
    """A textura de cor base do material (a ligada à Base Color do Principled)."""
    for m in me.materials:
        if not m or not m.node_tree:
            continue
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                ent = n.inputs["Base Color"]
                if ent.is_linked and ent.links[0].from_node.type == "TEX_IMAGE":
                    return ent.links[0].from_node.image
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image:
                return n.image
    return None


def _amostrar(me, img):
    """Média da imagem nos 3 primeiros cantos, no 4º (quads) e no centro do UV de cada face (valores como gravados: sRGB)."""
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    ls = _arr(me, "polygons", "loop_start", 1, np.int64)
    lt = _arr(me, "polygons", "loop_total", 1, np.int64)
    pts = [uv[ls + k] for k in range(3)]
    pts.append(sum(pts) / 3.0)
    pts.append(uv[ls + np.minimum(3, lt - 1)])
    acc = np.zeros((len(ls), 4))
    for u in pts:
        ix = np.clip((u[:, 0] % 1.0) * w, 0, w - 1).astype(np.int64)
        iy = np.clip((u[:, 1] % 1.0) * h, 0, h - 1).astype(np.int64)
        acc += px[iy, ix]
    return acc / len(pts)


def _cores_faces(me):
    """Cor da textura de cor base em cada face."""
    import numpy as np
    img = _imagem_base(me)
    if img is None:
        return np.full((len(me.polygons), 3), 0.5)
    return _amostrar(me, img)[:, :3]


def _hsv(col):
    import numpy as np
    mx = col.max(1)
    mn = col.min(1)
    d = mx - mn
    s = np.where(mx > 1e-4, d / np.maximum(mx, 1e-4), 0.0)
    r, g, b = col[:, 0], col[:, 1], col[:, 2]
    dd = np.maximum(d, 1e-6)
    h = np.where(mx == r, ((g - b) / dd) % 6.0, np.where(mx == g, (b - r) / dd + 2.0, (r - g) / dd + 4.0)) / 6.0
    h = np.where(d < 1e-6, 0.0, h)
    return h, s, mx


def _vizinhos(me):
    """Pares (a, b) de faces que dividem uma aresta (as duas direções)."""
    import numpy as np
    le = _arr(me, "loops", "edge_index", 1, np.int64)
    ls = _arr(me, "polygons", "loop_start", 1, np.int64)
    lt = _arr(me, "polygons", "loop_total", 1, np.int64)
    lp = np.repeat(np.arange(len(ls)), lt)
    ordem = np.argsort(le, kind="stable")
    e = le[ordem]
    p = lp[ordem]
    mesma = e[1:] == e[:-1]
    a = p[:-1][mesma]
    b = p[1:][mesma]
    return np.concatenate([a, b]), np.concatenate([b, a])


def _dilatar(sel, viz, n, limite=None):
    import numpy as np
    a, b = viz
    for _ in range(n):
        novo = sel.copy()
        novo[b[sel[a]]] = True
        if limite is not None:
            novo &= limite
        sel = novo
    return sel


def _erodir(sel, viz, n):
    a, b = viz
    for _ in range(n):
        novo = sel.copy()
        novo[a[~sel[b]]] = False
        sel = novo
    return sel


def _componentes(sel, viz):
    """Rótulo de componente conexa (só entre faces selecionadas); -1 fora da seleção."""
    import numpy as np
    a, b = viz
    m = sel[a] & sel[b]
    a, b = a[m], b[m]
    lab = np.where(sel, np.arange(len(sel)), -1)
    while True:
        novo = lab.copy()
        np.minimum.at(novo, a, lab[b])
        # salto de ponteiro: acelera a convergência
        idx = np.where(sel)[0]
        novo[idx] = novo[novo[idx]]
        if np.array_equal(novo, lab):
            return lab
        lab = novo


def _soldar(obj, rel, manter_normais=False):
    """
    Solda os vértices repetidos das costuras de UV (os UVs ficam nos cantos) e marca arestas vivas acima de 50 graus. Com manter_normais,
    a normal de cada canto que veio no arquivo atravessa a solda (atributo de canto) e volta como normal personalizada.
    """
    import bmesh
    me = obj.data
    if manter_normais:
        guardar_normais(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    v0 = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    borda = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    lim = math.radians(50.0)
    for e in bm.edges:
        e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim)
    for f in bm.faces:
        f.smooth = True
    bm.to_mesh(me)
    bm.free()
    if "custom_normal" in me.attributes:
        me.attributes.remove(me.attributes["custom_normal"])
    if manter_normais:
        restaurar_normais(me)
    rel["solda"] = {"vertices_antes": v0, "vertices_depois": len(me.vertices), "arestas_de_borda": borda}


def _orientar_unica(obj, forcada, rel):
    """Escala (se precisar), frente em +X pelos retrovisores (picos de largura acima da cintura, na metade da frente)."""
    import numpy as np
    from mathutils import Matrix
    me = obj.data
    co = _arr(me, "vertices", "co", 3)
    dims = co.max(0) - co.min(0)
    passos = []
    if dims[1] > dims[0]:
        me.transform(Matrix.Rotation(math.radians(-90.0), 4, "Z"))
        passos.append("90° em Z (comprimento estava em Y)")
        co = _arr(me, "vertices", "co", 3)
        dims = co.max(0) - co.min(0)
    comp = dims[0]
    fator = 1.0
    if not (COMPRIMENTO[0] <= comp <= COMPRIMENTO[1]):
        fator = min(ESCALAS, key=lambda f: abs(math.log(max(comp * f, 1e-9) / 4.2)))
        me.transform(Matrix.Scale(fator, 4))
        co = co * fator
    rel["escala"] = {"fator": fator, "comprimento_original": round(float(comp), 4), "motivo": "malha única: pelo comprimento"}
    me.transform(Matrix.Translation((-(co[:, 0].max() + co[:, 0].min()) / 2.0, -(co[:, 1].max() + co[:, 1].min()) / 2.0, -co[:, 2].min())))
    co = _arr(me, "vertices", "co", 3)
    H = co[:, 2].max()
    xmin, xmax = co[:, 0].min(), co[:, 0].max()
    nb = 40
    bins = np.linspace(xmin, xmax, nb + 1)
    banda = (co[:, 2] > 0.55 * H) & (co[:, 2] < 0.9 * H)
    picos = []
    for s in (1.0, -1.0):
        sel = banda & (co[:, 1] * s > 0)
        perfil = np.zeros(nb)
        for i in range(nb):
            m = sel & (co[:, 0] >= bins[i]) & (co[:, 0] < bins[i + 1])
            perfil[i] = np.abs(co[m, 1]).max() if m.any() else 0.0
        for i in range(2, nb - 2):
            viz = np.concatenate([perfil[max(0, i - 5):i - 1], perfil[i + 2:i + 6]])
            viz = viz[viz > 0]
            estreito = perfil[i] - max(perfil[max(0, i - 3)], perfil[min(nb - 1, i + 3)]) > 0.04
            if viz.size and perfil[i] - np.median(viz) > 0.09 and estreito:
                picos.append(((bins[i] + bins[i + 1]) / 2.0, perfil[i] - np.median(viz)))
    frente_x = None
    if forcada:
        frente_x = 1.0 if forcada == "+x" else -1.0
        motivo = "--frente %s" % forcada
    elif picos:
        x = max(picos, key=lambda p: p[1])[0]
        frente_x = 1.0 if x > 0 else -1.0
        motivo = "retrovisores em x = %.2f m" % x
    else:
        frente_x = 1.0
        motivo = "sem retrovisores achados: mantida (use --frente)"
        rel["avisos"].append("frente não confirmada pelos retrovisores; confira a prévia ou use --frente")
    if frente_x < 0:
        me.transform(Matrix.Rotation(math.pi, 4, "Z"))
        passos.append("180° em Z (%s)" % motivo)
    else:
        passos.append("frente já em +X (%s)" % motivo)
    rel["orientacao"] = passos
    me.update()


def _achar_rodas(cen, nor, co, V):
    """As quatro rodas: contato com o chão nas quatro pontas, raio pela banda de rodagem, aro/calota pela face externa."""
    import numpy as np
    z0 = co[:, 2].min()
    baixo = co[co[:, 2] < z0 + 0.015]
    rodas = []
    for sx, fx in ((1, "f"), (-1, "r")):
        for sy, fy in ((1, "l"), (-1, "r")):
            q = baixo[(baixo[:, 0] * sx > 0) & (baixo[:, 1] * sy > 0)]
            if len(q) < 5:
                raise Erro("não achei o contato da roda %s%s com o chão" % (fx, fy))
            cx0 = float(np.median(q[:, 0]))
            yo = float(np.abs(q[:, 1]).max())
            yi = float(np.abs(q[:, 1]).min())
            banda = (cen[:, 1] * sy > yi - 0.05) & (cen[:, 1] * sy < yo + 0.02) & (np.abs(cen[:, 0] - cx0) < 0.6) & \
                    (cen[:, 2] < 1.0) & (np.abs(nor[:, 1]) < 0.5)
            cb, nb_ = cen[banda], nor[banda]
            melhor = None
            for dx in np.arange(-0.04, 0.0401, 0.01):
                for R in np.arange(0.18, 0.55, 0.004):
                    d = cb[:, [0, 2]] - np.array([cx0 + dx, z0 + R])
                    r = np.linalg.norm(d, axis=1)
                    rad = (nb_[:, 0] * d[:, 0] + nb_[:, 2] * d[:, 1]) / np.maximum(r, 1e-6)
                    s = int(((np.abs(r - R) < 0.012) & (rad > 0.9)).sum())
                    if melhor is None or s > melhor[0]:
                        melhor = (s, cx0 + dx, R)
            pontos, cx, R = melhor
            cz = z0 + R
            # perfil da face externa: cor e quanto avança para fora, por anel
            d = np.hypot(cen[:, 0] - cx, cen[:, 2] - cz)
            ext = (cen[:, 1] * sy > yi) & (nor[:, 1] * sy > 0.5) & (d < R)
            aneis = np.arange(0.0, R, 0.02)
            vmed, ymed = [], []
            for r0 in aneis:
                m = ext & (d >= r0) & (d < r0 + 0.02)
                vmed.append(float(np.median(V[m])) if m.any() else None)
                ymed.append(float(np.median(np.abs(cen[m, 1]))) if m.any() else None)
            # aro: do centro até o primeiro anel em que a face externa fica escura (borracha) até a borda
            r_aro = None
            for i, r0 in enumerate(aneis):
                resto = [v for v in vmed[i:] if v is not None]
                if resto and max(resto) < 0.32 and r0 > 0.25 * R:
                    r_aro = float(r0)
                    break
            # calota: o miolo que avança para fora mais que o resto do aro
            r_cal = None
            ys = [(r0, y) for r0, y in zip(aneis, ymed) if y is not None and (r_aro is None or r0 < r_aro)]
            if len(ys) >= 4:
                y_c = ys[0][1]
                y_min = min(y for _, y in ys)
                if y_c - y_min > 0.03:
                    lim = y_c - 0.6 * (y_c - y_min)
                    for r0, y in ys:
                        if y < lim:
                            r_cal = float(r0)
                            break
            nome = "%s%s" % (fx, fy)
            # alcance para fora: a calota pode passar da borracha
            ext_y = yo + 0.02
            m = (d < R * 0.95) & (cen[:, 1] * sy > yo - 0.02) & (cen[:, 1] * sy < yo + 0.15)
            if m.any():
                ext_y = max(ext_y, float(np.abs(cen[m, 1]).max()) + 0.005)
            rodas.append({"nome": nome, "lado": sy, "cx": round(cx, 4), "cz": round(float(cz), 4), "raio": round(float(R), 4),
                          "y_dentro": round(yi, 4), "y_fora": round(yo, 4), "y_alcance": round(ext_y, 4),
                          "raio_aro": round(r_aro, 4) if r_aro else None, "raio_calota": round(r_cal, 4) if r_cal else None,
                          "pontos_banda": pontos})
    return rodas


def _mr_faces(me):
    import numpy as np
    img = None
    for m in me.materials:
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                for nome in ("Roughness", "Metallic"):
                    e = n.inputs[nome]
                    if e.is_linked:
                        no = e.links[0].from_node
                        while no.type != "TEX_IMAGE" and no.inputs and no.inputs[0].is_linked:
                            no = no.inputs[0].links[0].from_node
                        if no.type == "TEX_IMAGE":
                            img = no.image
    F = len(me.polygons)
    if img is None:
        return np.full(F, 0.5), np.zeros(F)
    acc = _amostrar(me, img)
    return acc[:, 1], acc[:, 2]

def _casco2d(pts):
    """Fecho convexo (cadeia monótona) de pontos 2D: lista de vértices em sentido anti-horário."""
    pts = sorted(set((round(float(a), 4), round(float(b), 4)) for a, b in pts))
    if len(pts) < 3:
        return pts

    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    baixo, cima = [], []
    for p in pts:
        while len(baixo) >= 2 and cruz(baixo[-2], baixo[-1], p) <= 0:
            baixo.pop()
        baixo.append(p)
    for p in reversed(pts):
        while len(cima) >= 2 and cruz(cima[-2], cima[-1], p) <= 0:
            cima.pop()
        cima.append(p)
    return baixo[:-1] + cima[:-1]


def _dentro_casco(casco, P, folga=0.0):
    """P (N x 2) dentro do polígono convexo anti-horário, com folga (m) para fora."""
    import numpy as np
    ok = np.ones(len(P), bool)
    n = len(casco)
    if n < 3:
        return ~ok
    for i in range(n):
        a = np.array(casco[i])
        b = np.array(casco[(i + 1) % n])
        e = b - a
        ln = max(np.hypot(e[0], e[1]), 1e-9)
        # distância com sinal para fora (à direita da aresta)
        d = -(e[0] * (P[:, 1] - a[1]) - e[1] * (P[:, 0] - a[0])) / ln
        ok &= d <= folga
    return ok


def _comps_info(sel, viz, cen, area):
    """Componentes da seleção: lista de (índices, área, caixa [x0,x1,y0,y1,z0,z1])."""
    import numpy as np
    if not sel.any():
        return []
    lab = _componentes(sel, viz)
    idx = np.where(sel)[0]
    ordem = np.argsort(lab[idx], kind="stable")
    idx = idx[ordem]
    l = lab[idx]
    cortes = np.where(np.diff(l) != 0)[0] + 1
    out = []
    for g in np.split(idx, cortes):
        c = cen[g]
        out.append((g, float(area[g].sum()), [float(c[:, 0].min()), float(c[:, 0].max()), float(c[:, 1].min()), float(c[:, 1].max()),
                                              float(c[:, 2].min()), float(c[:, 2].max())]))
    return out


def _retrovisores(cen, co):
    """Caixas dos retrovisores: o pico de largura acima da cintura, na metade da frente, de cada lado."""
    import numpy as np
    H = float(co[:, 2].max())
    xmin, xmax = float(co[:, 0].min()), float(co[:, 0].max())
    nb = 60
    bins = np.linspace(xmin, xmax, nb + 1)
    out = {}
    banda = (co[:, 2] > 0.55 * H) & (co[:, 2] < 0.9 * H)
    for s, lado in ((1.0, "left"), (-1.0, "right")):
        sel = banda & (co[:, 1] * s > 0)
        perfil = np.zeros(nb)
        for i in range(nb):
            m = sel & (co[:, 0] >= bins[i]) & (co[:, 0] < bins[i + 1])
            perfil[i] = np.abs(co[m, 1]).max() if m.any() else 0.0
        melhor = None
        for i in range(nb // 3, nb - 2):  # frente: x > um terço do comprimento a partir de trás
            viz = np.concatenate([perfil[max(0, i - 8):max(0, i - 2)], perfil[i + 3:i + 9]])
            viz = viz[viz > 0]
            if not viz.size:
                continue
            exc = perfil[i] - np.median(viz)
            estreito = perfil[i] - max(perfil[max(0, i - 4)], perfil[min(nb - 1, i + 4)]) > 0.04  # retrovisor é um pico estreito
            if exc > 0.09 and estreito and (melhor is None or exc > melhor[1]):
                melhor = (i, exc, float(np.median(viz)))
        if melhor is None:
            continue
        i, exc, yref = melhor
        xc = (bins[i] + bins[i + 1]) / 2.0
        m = sel & (np.abs(co[:, 0] - xc) < 0.20) & (np.abs(co[:, 1]) > yref + 0.02)
        if m.sum() < 10:
            continue
        p = co[m]
        y0 = yref + 0.005
        caixa = [float(p[:, 0].min()) - 0.01, float(p[:, 0].max()) + 0.01, y0, float(np.abs(p[:, 1]).max()) + 0.02,
                 float(p[:, 2].min()) - 0.01, float(p[:, 2].max()) + 0.01]
        if s < 0:
            caixa[2], caixa[3] = -caixa[3], -caixa[2]
        out[lado] = caixa
    return out


def _dentro_caixa(cen, b, folga=0.0):
    return ((cen[:, 0] >= b[0] - folga) & (cen[:, 0] <= b[1] + folga) & (cen[:, 1] >= b[2] - folga) & (cen[:, 1] <= b[3] + folga) &
            (cen[:, 2] >= b[4] - folga) & (cen[:, 2] <= b[5] + folga))


def _classificar_textura(cen, nor, area, col, mr, viz, rodas, retros, portas, rel):
    """
    Classe de textura por face e as janelas. Devolve (classes, janelas, info); janelas = {nome: (índices, caixa)}.
    Vidro: pouco saturado e diferente da pintura (mais escuro, ou menos saturado que uma pintura colorida), acima da cintura; cada
    janela vira o fecho convexo dos pedaços achados (os reflexos pintados no vidro ficam dentro).
    """
    import numpy as np
    h, s, v = _hsv(col)
    F = len(cen)
    xmin, xmax = float(cen[:, 0].min()), float(cen[:, 0].max())
    meia = float(np.abs(cen[:, 1]).max())
    H = float(cen[:, 2].max())
    L = xmax - xmin
    na_roda = np.zeros(F, bool)
    for r in rodas:
        d = np.hypot(cen[:, 0] - r["cx"], cen[:, 2] - r["cz"])
        na_roda |= (d < r["raio"] + 0.04) & (cen[:, 1] * r["lado"] > r["y_dentro"] - 0.10)
    no_retro = np.zeros(F, bool)
    for b in retros.values():
        no_retro |= _dentro_caixa(cen, b, 0.02)
    teto = (nor[:, 2] > 0.9) & (cen[:, 2] > 0.88 * H) & (np.abs(cen[:, 0]) < 0.3 * L)
    pintura = np.median(col[teto], axis=0) if teto.sum() > 20 else np.median(col, axis=0)
    pv = float(pintura.max())
    ps = float((pintura.max() - pintura.min()) / max(pintura.max(), 1e-4))
    ps_teto = ps
    meio_lado = (np.abs(nor[:, 1]) > 0.8) & (cen[:, 2] > 0.3 * H) & (cen[:, 2] < 0.5 * H) & (np.abs(cen[:, 0]) < 0.3 * L)
    if meio_lado.sum() > 20:
        cl_ = np.median(col[meio_lado], axis=0)
        ps = max(ps, float((cl_.max() - cl_.min()) / max(cl_.max(), 1e-4)))
    dist = np.linalg.norm(col - pintura, axis=1)
    cl = np.zeros(F, np.int8)
    info = {"pintura_rgb": [round(float(c), 3) for c in pintura], "pintura_sat": round(ps, 3), "pintura_val": round(pv, 3)}

    def fechar(sel, limite, n=2):
        sel = _dilatar(sel, viz, n, limite)
        sel = _erodir(sel, viz, n)
        sel = _erodir(sel, viz, 1)
        return _dilatar(sel, viz, 1, limite)

    # ---- vidros
    alto = (cen[:, 2] > 0.40 * H) & (nor[:, 2] > -0.3) & ~na_roda & ~no_retro
    cand = (v < pv - 0.12) & (s < max(0.25, 0.65 * ps))
    if ps >= 0.12:
        cand |= (s < min(0.65 * ps, ps - 0.08)) & (dist > 0.08)
    ph = float(_hsv(pintura[None, :])[0][0])
    if ps_teto >= 0.08:
        dh = np.abs(((h - ph) + 0.5) % 1.0 - 0.5)
        cand |= (dh > 0.045) & (s < max(ps_teto, 0.1)) & (dist > 0.05)
    # regiões cercadas pela borracha das janelas (rugosa e não metálica na textura de rugosidade/metal)
    rough, metal = mr
    pr, pm = float(np.median(rough[teto])), float(np.median(metal[teto]))
    borracha = _dilatar((rough > pr + 0.15) & (metal < 0.5 * pm + 0.02), viz, 1)
    livre = alto & ~borracha
    alc = livre & ((cen[:, 2] < 0.52 * H) | ((nor[:, 2] > 0.9) & (cen[:, 2] > 0.95 * H)))
    a_, b_ = viz
    while True:
        n_ = alc.copy()
        n_[b_[alc[a_]]] = True
        n_ &= livre
        if n_.sum() == alc.sum():
            break
        alc = n_
    cercado = livre & ~alc
    info["cercado_pela_borracha"] = int(cercado.sum())
    cand = fechar(alto & (cand | cercado), alto, 2)
    lado_n = np.abs(nor[:, 1]) > 0.55
    dirs = {"left": lado_n & (nor[:, 1] > 0), "right": lado_n & (nor[:, 1] < 0),
            "front": ~lado_n & (nor[:, 0] > 0.15), "rear": ~lado_n & (nor[:, 0] < -0.15)}
    grupos = {}
    for dn, dm in dirs.items():
        comps = [c for c in _comps_info(cand & dm, viz, cen, area) if c[1] >= 0.004]
        # sementes: pedaços grandes acima da cintura; cada janela junta só os pedaços DENTRO da caixa da semente (sem corrente)
        def cz(c):
            return float(np.average(cen[c[0], 2], weights=area[c[0]]))
        sementes = [c for c in sorted(comps, key=lambda c: -c[1]) if c[1] >= 0.025 and cz(c) > 0.58 * H]
        juntos = []
        for c in sementes:
            b = c[2]
            if any(all(b[2 * k] >= J["bb"][2 * k] - 0.05 and b[2 * k + 1] <= J["bb"][2 * k + 1] + 0.05 for k in range(3)) for J in juntos):
                continue
            juntos.append({"idx": [c[0]], "area": c[1], "bb": list(b)})
        for J in juntos:
            jb = J["bb"]
            for g, a, b in comps:
                if g is J["idx"][0]:
                    continue
                if all(b[2 * k] >= jb[2 * k] - 0.06 and b[2 * k + 1] <= jb[2 * k + 1] + 0.06 for k in range(3)):
                    J["idx"].append(g)
                    J["area"] += a
        juntos = [J for J in juntos if J["area"] >= (0.05 if dn in ("left", "right") else 0.12)]
        eixo = (0, 2) if dn in ("left", "right") else (1, 2)
        out = []
        for J in juntos:
            g = np.concatenate(J["idx"])
            P = cen[g][:, list(eixo)]
            if dn in ("front", "rear"):
                P = np.concatenate([P, P * np.array([-1.0, 1.0])])  # para-brisa e vidro traseiro são simétricos: o reflexo de um lado completa o outro
            casco = _casco2d(P)
            base = alto & (dirs[dn] if dn in ("left", "right") else (dirs[dn] | (cand & ~lado_n)))
            if dn in ("left", "right"):
                ay = np.abs(cen[g, 1])
                prof = (np.abs(cen[:, 1]) >= np.percentile(ay, 3) - 0.04) & (np.abs(cen[:, 1]) <= np.percentile(ay, 97) + 0.02)
            else:
                ax = cen[g, 0]
                prof = (cen[:, 0] >= np.percentile(ax, 2) - 0.04) & (cen[:, 0] <= np.percentile(ax, 98) + 0.04)
            zmin = float(np.percentile(cen[g, 2], 1)) - 0.02
            dentro = base & prof & (cen[:, 2] >= zmin) & _dentro_casco(casco, cen[:, list(eixo)], 0.012)
            sel = np.where(dentro)[0]
            out.append({"idx": sel, "area": float(area[sel].sum()), "x0": float(cen[sel, 0].min()), "x1": float(cen[sel, 0].max())})
        # janelas que se sobrepõem (sementes vizinhas da mesma janela) viram uma só
        fundidos = []
        for J in sorted(out, key=lambda J: -J["area"]):
            sJ = set(J["idx"].tolist())
            for K in fundidos:
                inter = len(sJ & K["set"])
                if inter > 0.15 * min(len(sJ), len(K["set"])):
                    K["set"] |= sJ
                    break
            else:
                fundidos.append({"set": sJ})
        out = []
        for K in fundidos:
            sel = np.array(sorted(K["set"]), np.int64)
            out.append({"idx": sel, "area": float(area[sel].sum()), "x0": float(cen[sel, 0].min()), "x1": float(cen[sel, 0].max())})
        grupos[dn] = out
    janelas = {}

    def caixa_de(idx):
        c = cen[idx]
        return [round(float(c[:, 0].min()) - 0.01, 3), round(float(c[:, 0].max()) + 0.01, 3), round(float(c[:, 1].min()) - 0.01, 3),
                round(float(c[:, 1].max()) + 0.01, 3), round(float(c[:, 2].min()) - 0.01, 3), round(float(c[:, 2].max()) + 0.01, 3)]
    for dn, nome in (("front", "glass_windshield"), ("rear", "glass_rear")):
        if grupos[dn]:
            # para-brisa bipartido (Kombi): as metades grandes juntas
            maior = max(J["area"] for J in grupos[dn])
            janelas[nome] = np.unique(np.concatenate([J["idx"] for J in grupos[dn] if J["area"] >= 0.3 * maior]))
    lados = {}
    for dn, sfx in (("left", "l"), ("right", "r")):
        lados[sfx] = sorted(grupos[dn], key=lambda J: -J["x1"])
    if portas is None:
        ws = lados["l"] or lados["r"]
        if H > 1.75:
            portas = 2
        elif ws and len(ws) == 1 and ws[0]["x1"] - ws[0]["x0"] > 1.6:
            portas = 4
        elif len(ws) >= 2 and ws[0]["x1"] - ws[0]["x0"] < 0.95 and ws[1]["x1"] - ws[1]["x0"] >= 0.6 and L > 3.9:
            portas = 4
        else:
            portas = 2
        rel["avisos"].append("portas: %d por lado, estimado pelas janelas (confira; --portas força)" % (portas // 2))
    info["portas"] = portas
    juntas = [ws[0] for ws in lados.values() if ws and len(ws) == 1] if portas == 4 else []
    xb = None
    if juntas:
        # janelas da frente e de trás juntas (coluna B preta): corta na faixa mais escura do meio, a mesma dos dois lados
        idx = np.concatenate([J["idx"] for J in juntas])
        x0 = max(J["x0"] for J in juntas)
        x1 = min(J["x1"] for J in juntas)
        xs = cen[idx, 0]
        melhor = None
        for xc in np.arange(x0 + 0.3 * (x1 - x0), x0 + 0.7 * (x1 - x0), 0.02):
            m = np.abs(xs - xc) < 0.02
            if m.sum() < 8:
                continue
            med = float(np.median(v[idx[m]]))
            if melhor is None or med < melhor[0]:
                melhor = (med, float(xc))
        xb = melhor[1] if melhor else (x0 + x1) / 2.0
        info["coluna_b"] = round(xb, 3)
    for sfx, ws in lados.items():
        if not ws:
            continue
        if xb is not None and len(ws) == 1:
            J = ws[0]
            xs = cen[J["idx"], 0]
            ws = [{"idx": J["idx"][xs >= xb], "x0": xb, "x1": J["x1"]}, {"idx": J["idx"][xs < xb], "x0": J["x0"], "x1": xb}]
            lados[sfx] = ws
        janelas["glass_door_f" + sfx] = ws[0]["idx"]
        if len(ws) > 1:
            janelas["glass_door_r" + sfx] = np.concatenate([J["idx"] for J in ws[1:]])
    for nome, idx in janelas.items():
        cl[idx] = CL_VIDRO
    info["janelas_por_lado"] = {k: [[round(J["x0"], 2), round(J["x1"], 2)] for J in w] for k, w in lados.items()}
    info["_lados"] = lados

    # ---- placas: branco, perto do meio, nas pontas
    ponta = np.abs(cen[:, 0]) > (L / 2.0 - 0.45)
    pecas_tex = {}
    if not (pv > 0.62 and ps < 0.2):
        lim = ponta & (np.abs(cen[:, 1]) < 0.45) & (np.abs(nor[:, 0]) > 0.3) & (cl == 0)
        pla = fechar(lim & (v > 0.66) & (s < 0.22) & (dist > 0.15), lim, 1)
        for g, a, b in _comps_info(pla, viz, cen, area):
            larg, alt = b[3] - b[2], b[5] - b[4]
            if 0.012 <= a <= 0.2 and 0.18 <= larg <= 0.6 and 0.06 <= alt <= 0.3 and abs((b[2] + b[3]) / 2) < 0.15:
                nome = "plate_front" if b[0] > 0 else "plate_rear"
                if nome not in pecas_tex or a > area[pecas_tex[nome]].sum():
                    pecas_tex[nome] = g
        for nome, g in pecas_tex.items():
            cl[g] = CL_PLACA
    else:
        rel["avisos"].append("placas: pintura clara demais para separar a placa branca pela cor; ficaram no corpo")

    # ---- faróis: claros, na frente; lanternas: vermelho/âmbar saturado, atrás
    def luzes(regiao, cor, classe, base, larg_max):
        sel = fechar(regiao & cor, regiao, 1)
        achou = {}
        for g, a, b in _comps_info(sel, viz, cen, area):
            larg, alt = b[3] - b[2], b[5] - b[4]
            yc = (b[2] + b[3]) / 2.0
            if a < 0.003 or larg > larg_max or alt > 0.35 or abs(yc) < 0.25 * meia:
                continue
            lado = "left" if yc > 0 else "right"
            k = "%s_%s" % (base, lado)
            achou.setdefault(k, []).append((g, a))
        for k, gs in achou.items():
            # junta os pedaços do mesmo lado (lente com reflexo, pisca colado); lente menor que 80 cm² é fiapo: fica no corpo
            if sum(a for g, a in gs) < 0.008:
                rel["avisos"].append("%s: só um fiapo pela cor da textura (%.0f cm²); ficou no corpo" % (k, 1e4 * sum(a for g, a in gs)))
                continue
            pecas_tex[k] = np.concatenate([g for g, a in gs])
            cl[pecas_tex[k]] = classe
    frente = (cen[:, 0] > xmax - 0.32) & (nor[:, 0] > 0.2) & (cen[:, 2] > 0.18 * H) & (cen[:, 2] < 0.75 * H) & (cl == 0)
    luzes(frente, (v > max(0.42, pv + 0.10)) & (s < 0.35) & (dist > 0.15), CL_FAROL, "headlight", 0.45)
    tras = (cen[:, 0] < xmin + 0.32) & (nor[:, 0] < -0.2) & (cen[:, 2] > 0.18 * H) & (cen[:, 2] < 0.80 * H) & (cl == 0)
    ambar = (h >= 0.025) & (h <= 0.12) & (s > 0.45) & (v > 0.3)
    vermelho = ((h < 0.025) | (h > 0.92)) & (s > 0.45) & (v > 0.18)
    pint_verm = (pintura[0] > pintura[1] * 1.4) and ps > 0.3
    lim_d = 0.20 if pint_verm else 0.10
    luzes(tras, (ambar | vermelho) & (dist > lim_d), CL_LANTERNA, "taillight", 0.6)
    # ---- grade: escura, entre os faróis
    far = cl == CL_FAROL
    if far.any():
        zf = cen[far, 2]
        yf = np.abs(cen[far, 1])
        lim = (cen[:, 0] > xmax - 0.30) & (nor[:, 0] > 0.3) & (cen[:, 2] > zf.min() - 0.04) & (cen[:, 2] < zf.max() + 0.04) & \
              (np.abs(cen[:, 1]) < yf.min() - 0.01) & (cl == 0)
        gra = fechar(lim & (v < 0.25) & (dist > 0.10), lim, 2)
        comps = [c for c in _comps_info(gra, viz, cen, area) if c[1] >= 0.004]
        if comps and sum(c[1] for c in comps) >= 0.02:
            g = np.concatenate([c[0] for c in comps])
            P = cen[g][:, [1, 2]]
            casco = _casco2d(P)
            dentro = lim & _dentro_casco(casco, cen[:, [1, 2]], 0.005) & (cen[:, 0] > np.percentile(cen[g, 0], 2) - 0.03)
            pecas_tex["grille"] = np.where(dentro)[0]
            cl[dentro] = CL_GRADE
    info["faces"] = {k: int((cl == c).sum()) for k, c in CLASSES.items()}
    return cl, janelas, pecas_tex, info


def _render_debug(obj, cl, caminho):
    """Prévia rápida das classes de textura: trás, cima 3/4, lado e frente (Cycles)."""
    import bpy
    import numpy as np
    from mathutils import Vector
    me = obj.data
    cores = np.array([[0.6, 0.6, 0.6], [0.1, 0.8, 1.0], [1.0, 1.0, 0.3], [1.0, 0.0, 0.1], [1.0, 0.3, 1.0], [0.1, 0.6, 0.1],
                      [0.9, 0.5, 0.1], [0.5, 0.2, 0.9]], np.float32)
    if "dbg" in me.color_attributes:
        me.color_attributes.remove(me.color_attributes["dbg"])
    at = me.color_attributes.new("dbg", "FLOAT_COLOR", "CORNER")
    lt = _arr(me, "polygons", "loop_total", 1, np.int64)
    c = np.repeat(cores[cl % len(cores)], lt, axis=0)
    c4 = np.concatenate([c, np.ones((len(c), 1), np.float32)], 1)
    at.data.foreach_set("color", c4.ravel())
    m = bpy.data.materials.new("dbg")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    a = nt.nodes.new("ShaderNodeVertexColor")
    a.layer_name = "dbg"
    bs = nt.nodes.new("ShaderNodeBsdfDiffuse")
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(a.outputs[0], bs.inputs[0])
    nt.links.new(bs.outputs[0], o.inputs[0])
    velhos = list(me.materials)
    me.materials.clear()
    me.materials.append(m)
    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = 8
    cena.cycles.use_denoising = False
    cena.view_settings.view_transform = "Standard"
    cena.render.resolution_x, cena.render.resolution_y = 700, 360
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
    cena.world = w
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    cena.collection.objects.link(cam)
    cena.camera = cam
    imgs = []
    co = _arr(me, "vertices", "co", 3)
    L = co[:, 0].max() - co[:, 0].min()
    H = co[:, 2].max()
    for nome, d, esc in (("lado", Vector((0.0, 1.0, 0.0)), L * 1.08), ("frente", Vector((1.0, 0.0, 0.0)), max(L * 0.75, 2.0 * H)),
                         ("tras", Vector((-1.0, 0.0, 0.0)), max(L * 0.75, 2.0 * H)), ("cima34", Vector((0.6, 0.6, 0.9)).normalized(), L * 1.15)):
        alvo = Vector((0.0, 0.0, H * 0.5))
        cam.location = alvo + d * 10.0
        cam.rotation_euler = (alvo - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.ortho_scale = esc
        arq = caminho + "." + nome + ".png"
        cena.render.filepath = arq
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(arq)
        imgs.append(np.array(im.pixels[:], np.float32).reshape(im.size[1], im.size[0], 4))
        bpy.data.images.remove(im)
        os.remove(arq)
    grade = np.concatenate([np.concatenate(imgs[2:], 1), np.concatenate(imgs[:2], 1)], 0)
    im = bpy.data.images.new("dbgout", grade.shape[1], grade.shape[0], alpha=True)
    im.pixels = grade.ravel().tolist()
    im.filepath_raw = caminho
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    me.materials.clear()
    for mm in velhos:
        me.materials.append(mm)
    me.color_attributes.remove(me.color_attributes["dbg"])
    bpy.data.objects.remove(cam, do_unlink=True)


# ---- mapa por carro --------------------------------------------------------------------------------------------------------------

def _pct(a, q):
    import numpy as np
    return float(np.percentile(a, q))


def _gerar_mapa(cid, cen, nor, rodas, retros, janelas, pecas_tex, info, rel):
    """
    O mapa de peças do carro, pelas proporções: eixos e raio das rodas, linha de cintura (base das janelas laterais), coluna A (ponta
    da janela da frente) e B (fim da janela da porta), base do para-brisa e do vidro traseiro, faróis e lanternas. Ordem importa: a
    face levada por uma peça não entra nas seguintes.
    """
    import numpy as np
    xmin, xmax = float(cen[:, 0].min()), float(cen[:, 0].max())
    sem_retro = np.ones(len(cen), bool)
    for b in retros.values():
        sem_retro &= ~_dentro_caixa(cen, b, 0.03)
    W = _pct(np.abs(cen[sem_retro, 1]), 99.7)   # meia largura da carroceria (sem os retrovisores)
    H = float(cen[:, 2].max())
    L = xmax - xmin
    portas = info.get("portas", 2)
    van = H > 1.75
    fr = [r for r in rodas if r["nome"][0] == "f"]
    rr = [r for r in rodas if r["nome"][0] == "r"]
    xf = sum(r["cx"] for r in fr) / len(fr)
    xr = sum(r["cx"] for r in rr) / len(rr)
    R = sum(r["raio"] for r in rodas) / len(rodas)
    cz = sum(r["cz"] for r in rodas) / len(rodas)
    parts = []
    m = {"car": cid, "notes": "", "medidas": {}, "parts": parts}

    def r3(v):
        return [round(float(x), 3) for x in v]

    # rodas: calota, aro e pneu
    for r in rodas:
        s = r["lado"]
        y0, y1 = r["y_dentro"] - 0.04, r["y_alcance"]
        base = {"take": "roda", "centro": [r["cx"], 0.0, r["cz"]], "lado": s, "y": [round(y0, 3), round(y1, 3)], "thickness": 0.0,
                "pocket": 0.0}
        if r.get("raio_calota"):
            parts.append(dict(base, name="hubcap_" + r["nome"], papel="hubcap", raio=[0.0, r["raio_calota"]],
                              y=[round(r["y_fora"] - 0.03, 3), round(y1, 3)]))
        if r.get("raio_aro"):
            parts.append(dict(base, name="wheel_%s_rim" % r["nome"], papel="rim", raio=[0.0, r["raio_aro"]]))
        parts.append(dict(base, name="wheel_%s_tire" % r["nome"], papel="wheel", raio=[0.0, round(r["raio"] + 0.012, 3)]))

    # retrovisores
    for lado, b in sorted(retros.items()):
        parts.append({"name": "mirror_" + lado, "papel": "mirror", "take": "faces", "box": r3(b), "thickness": 0.004, "pocket": 0.015})

    # peças pela textura (o rótulo da face diz a peça; a caixa só restringe)
    def caixa(idx, folga=0.02):
        c = cen[idx]
        return r3([c[:, 0].min() - folga, c[:, 0].max() + folga, c[:, 1].min() - folga, c[:, 1].max() + folga,
                   c[:, 2].min() - folga, c[:, 2].max() + folga])
    esp = {"plate": (0.004, 0.012), "headlight": (0.004, 0.05), "taillight": (0.004, 0.05), "grille": (0.008, 0.08),
           "glass_windshield": (0.006, 0.35), "glass_rear": (0.006, 0.35), "glass_door": (0.006, 0.30)}
    for nome in ("plate_front", "plate_rear", "headlight_left", "headlight_right", "taillight_left", "taillight_right", "grille"):
        if nome in pecas_tex and len(pecas_tex[nome]):
            papel = nome.split("_")[0]
            t, p = esp[papel]
            parts.append({"name": nome, "papel": papel, "take": "textura", "box": caixa(pecas_tex[nome]), "thickness": t, "pocket": p})
    for nome in ("glass_door_fl", "glass_door_fr", "glass_door_rl", "glass_door_rr", "glass_windshield", "glass_rear"):
        if nome in janelas and len(janelas[nome]):
            papel = "glass_door" if nome.startswith("glass_door") else nome
            t, p = esp[papel]
            parts.append({"name": nome, "papel": papel, "take": "textura", "box": caixa(janelas[nome]), "thickness": t, "pocket": p})

    # medidas
    lado_l = [janelas[k] for k in ("glass_door_fl", "glass_door_rl") if k in janelas and len(janelas[k])]
    lado_r = [janelas[k] for k in ("glass_door_fr", "glass_door_rr") if k in janelas and len(janelas[k])]
    lados = lado_l + lado_r
    z_cint = min(_pct(cen[i, 2], 3) for i in lados) if lados else 0.55 * H
    if "glass_door_fl" in janelas:
        fl = janelas["glass_door_fl"]
    elif "glass_door_fr" in janelas:
        fl = janelas["glass_door_fr"]
    else:
        fl = None
    if fl is not None:
        x_a = _pct(cen[fl, 0], 99)       # ponta da janela da porta da frente (coluna A)
        x_b = _pct(cen[fl, 0], 1)        # fim dela (coluna B, ou o fim da porta no carro de 2 portas)
    else:
        x_a, x_b = xf - R - 0.25, (xf + xr) / 2.0
        rel["avisos"].append("sem janela lateral: portas pelas rodas (confira o mapa)")
    rl = janelas.get("glass_door_rl", janelas.get("glass_door_rr"))
    ws = janelas.get("glass_windshield")
    rg = janelas.get("glass_rear")
    x_ws = _pct(cen[ws, 0], 98) if ws is not None and len(ws) else None
    z_far = [cen[pecas_tex[k], 2] for k in ("headlight_left", "headlight_right") if k in pecas_tex]
    z_lan = [cen[pecas_tex[k], 2] for k in ("taillight_left", "taillight_right") if k in pecas_tex]
    z_pc_f = R + 0.20
    if z_far:
        z_pc_f = min(z_pc_f, min(float(z.min()) for z in z_far) - 0.01)
    z_pc_t = R + 0.20
    if z_lan:
        z_pc_t = min(z_pc_t, min(float(z.min()) for z in z_lan) - 0.01)
    z_saia = min(R + 0.03, 0.42 * z_cint)
    soleira = (cen[:, 0] > xr + R + 0.05) & (cen[:, 0] < xf - R - 0.05) & (np.abs(cen[:, 1]) > W - 0.12) & (np.abs(nor[:, 1]) > 0.3)
    if soleira.sum() > 20:
        z_saia = max(z_saia, _pct(cen[soleira, 2], 2) + 0.12)   # carro de assoalho alto (van): a saia é a faixa de baixo
    x_pcf = max(xf + R + 0.03, xmax - 0.35)
    x_pct = min(xr - R - 0.03, xmin + 0.35)
    m["medidas"] = {"comprimento": round(L, 3), "meia_largura": round(W, 3), "altura": round(H, 3), "eixo_dianteiro": round(xf, 3),
                    "eixo_traseiro": round(xr, 3), "raio_roda": round(R, 3), "linha_de_cintura": round(z_cint, 3),
                    "coluna_a": round(x_a, 3), "coluna_b": round(x_b, 3), "base_do_para_brisa": round(x_ws, 3) if x_ws else None,
                    "topo_para_choque_dianteiro": round(z_pc_f, 3), "topo_para_choque_traseiro": round(z_pc_t, 3),
                    "topo_da_saia": round(z_saia, 3), "portas": portas, "van": van}

    # para-choques
    parts.append({"name": "bumper_front", "papel": "bumper_front", "take": "faces", "fora_das_rodas": True,
                  "box": r3([x_pcf, xmax + 0.05, -W - 0.05, W + 0.05, -0.05, z_pc_f]), "thickness": 0.012, "pocket": 0.15})
    parts.append({"name": "bumper_rear", "papel": "bumper_rear", "take": "faces", "fora_das_rodas": True,
                  "box": r3([xmin - 0.05, x_pct, -W - 0.05, W + 0.05, -0.05, z_pc_t]), "thickness": 0.012, "pocket": 0.15})
    # capô
    y_capo = 0.78 * W
    if ws is not None and len(ws):
        y_capo = min(y_capo, 0.95 * _pct(np.abs(cen[ws, 1]), 98))
    if x_ws is not None and xmax - x_ws > 0.35:
        parts.append({"name": "hood", "papel": "hood", "take": "faces", "normal": [0.0, 0.0, 1.0, 0.3],
                      "box": r3([x_ws + 0.03, xmax + 0.02, -y_capo, y_capo, z_pc_f + 0.02, H]), "thickness": 0.012, "pocket": 0.12})
    else:
        rel["avisos"].append("sem capô: a frente é curta (van) ou o para-brisa não foi achado")
    # tampa traseira
    if rg is not None and len(rg):
        x_rg0 = _pct(cen[rg, 0], 2)
        y_rg = _pct(np.abs(cen[rg, 1]), 98)
        if x_rg0 < xmin + 0.40:
            # hatch e van: tampa vertical com o vidro (o vidro já saiu) até o para-choque
            parts.append({"name": "trunk", "papel": "trunk", "take": "faces", "normal": [-0.95, 0.0, 0.3, 0.35],
                          "box": r3([xmin - 0.05, _pct(cen[rg, 0], 98) + 0.04, -min(0.86 * W, y_rg + 0.08), min(0.86 * W, y_rg + 0.08),
                                     z_pc_t + 0.005, _pct(cen[rg, 2], 99) + 0.05]), "thickness": 0.012, "pocket": 0.12})
        else:
            parts.append({"name": "trunk", "papel": "trunk", "take": "faces", "normal": [-0.35, 0.0, 0.94, 0.25],
                          "box": r3([xmin - 0.05, x_rg0 - 0.02, -0.80 * W, 0.80 * W, z_pc_t + 0.03, H]), "thickness": 0.012,
                          "pocket": 0.12})
    # saias laterais e portas
    for s, lado, sf in ((1.0, "left", "l"), (-1.0, "right", "r")):
        def bx(x0, x1, z0, z1, y_in):
            b = [x0, x1, y_in, W + 0.05, z0, z1]
            if s < 0:
                b[2], b[3] = -b[3], -b[2]
            return r3(b)
        nrm = [0.0, s, 0.0, 0.3]
        parts.append({"name": "side_skirt_" + lado, "papel": "side_skirt", "take": "faces", "fora_das_rodas": True,
                      "normal": [0.0, s, 0.0, -0.3], "box": bx(xr + R + 0.04, xf - R - 0.04, -0.05, z_saia, W - 0.30),
                      "thickness": 0.012, "pocket": 0.08})
        x_df = min(x_a + 0.07, xf - R - 0.05) if not van else x_a + 0.03
        if van:
            z0 = z_saia
            if x_b - 0.03 < xf + R and x_df > xf - R:
                z0 = max(z0, cz + R + 0.06)
            portas_lado = [("door_f" + sf, x_b - 0.03, x_df, z0)]
        elif portas == 4:
            xb = info.get("coluna_b", x_b)
            x_tr = max(_pct(cen[rl, 0], 1) if rl is not None and len(rl) else xr + 0.3 * R, xr + 0.3 * R)
            portas_lado = [("door_f" + sf, xb + 0.02, x_df, z_saia), ("door_r" + sf, x_tr, xb - 0.02, z_saia)]
        else:
            portas_lado = [("door_f" + sf, x_b - 0.03, x_df, z_saia)]
        for nome, x0, x1, z0 in portas_lado:
            if x1 - x0 > 0.3:
                parts.append({"name": nome, "papel": "door", "take": "faces", "fora_das_rodas": True, "normal": nrm,
                              "box": bx(x0, x1, z0, z_cint + 0.015, W - 0.30), "thickness": 0.015, "pocket": 0.12})
        x_portas0 = min(p[1] for p in portas_lado)
        x_portas1 = max(p[2] for p in portas_lado)
        # para-lamas: da porta ao para-choque, por fora do capô
        if x_pcf - x_portas1 > 0.15:
            parts.append({"name": "fender_front_" + lado, "papel": "fender", "take": "faces", "fora_das_rodas": True,
                          "normal": [0.0, s, 0.0, -0.2], "box": bx(x_portas1, x_pcf, 0.05, z_cint + 0.03, 0.55 * W),
                          "thickness": 0.012, "pocket": 0.10})
        x_ft = x_portas0 if not van else min(x_portas0, xr + R + 0.25)
        if x_ft - x_pct > 0.15:
            parts.append({"name": "fender_rear_" + lado, "papel": "fender", "take": "faces", "fora_das_rodas": True,
                          "normal": [0.0, s, 0.0, -0.2], "box": bx(x_pct, x_ft, 0.05, z_cint + 0.03, 0.55 * W),
                          "thickness": 0.012, "pocket": 0.10})
    m["notes"] = ("Gerado por carro_quebravel.py (malha única) a partir das proporções; edite e rode de novo com --mapa. Metros, frente +X, "
                  "ESQUERDA +Y, cima +Z, chão em z = 0, origem entre os eixos. take: roda (cilindro: centro, raio [r0, r1], y [|y| "
                  "mínimo, máximo] do lado), textura (faces com o rótulo da peça, achado pela cor da textura, dentro da caixa), faces "
                  "(corte pelos planos da caixa, como Tools/Blender/split_car_parts.py do Detonauto, com 'normal' [nx, ny, nz, mínimo]). "
                  "fora_das_rodas: não leva faces da caixa de roda. ignorar_rotulos: leva também faces que a cor marcou como outra peça. thickness: espessura da peça; pocket: profundidade do vão escuro.")
    return m


# ---- corte -----------------------------------------------------------------------------------------------------------------------

class _Nucleo:
    """Eixo do carro (segmento em X a 45 % da altura): 'para dentro' de um ponto é rumo ao ponto mais próximo dele (split_car_parts)."""

    def __init__(self, xmin, xmax, H):
        from mathutils import Vector
        zc = 0.45 * H
        m = min(0.9, 0.3 * (xmax - xmin))
        self.a = Vector((xmin + m, 0.0, zc))
        self.b = Vector((xmax - m, 0.0, zc))

    def dentro(self, co):
        from mathutils import Vector
        ab = self.b - self.a
        t = max(0.0, min(1.0, (co - self.a).dot(ab) / ab.length_squared))
        d = (self.a + ab * t) - co
        return d.normalized() if d.length > 1e-6 else Vector((0.0, 0.0, -1.0))


def _na_caixa(co, b, folga=0.0):
    return (b[0] - folga <= co.x <= b[1] + folga and b[2] - folga <= co.y <= b[3] + folga and b[4] - folga <= co.z <= b[5] + folga)


def _cortar_caixa(bm, b):
    """Corta a casca pelos 6 planos da caixa, só perto dela: a borda da peça sai reta (bisect interpola UV e normal guardada)."""
    import bmesh
    from mathutils import Vector
    planos = [((b[0], 0, 0), (1, 0, 0)), ((b[1], 0, 0), (1, 0, 0)), ((0, b[2], 0), (0, 1, 0)), ((0, b[3], 0), (0, 1, 0)),
              ((0, 0, b[4]), (0, 0, 1)), ((0, 0, b[5]), (0, 0, 1))]
    for co, no in planos:
        faces = [f for f in bm.faces if any(_na_caixa(v.co, b, 0.05) for v in f.verts)]
        if not faces:
            continue
        geom = list({e for f in faces for e in f.edges}) + faces + list({v for f in faces for v in f.verts})
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-5, plane_co=Vector(co), plane_no=Vector(no), clear_inner=False, clear_outer=False)
    bm.faces.ensure_lookup_table()


def _escolher(bm, p, rodas, camada_peca, ids_peca, camada_mat=None):
    """As faces da peça p do mapa."""
    import math as _m
    from mathutils import Vector
    take = p.get("take", "faces")
    b = p.get("box")
    out = []
    if take == "material":
        # faces que vieram com esse material no arquivo (vidro marcado à mão). Cada ilha ligada desse material
        # (um vidro inteiro) vai para a caixa que contém a maior parte dela: a caixa do vidro traseiro não rouba
        # o canto do vidro de quarta, nem a de quarta o canto do traseiro.
        cod = {"vidro": 1, "pneu": 2, "chassi": 3, "luz": 4, "cromado": 5}[p.get("material", "vidro")]
        if camada_mat is None:
            return []
        if b is None:
            return [f for f in bm.faces if f[camada_mat] == cod]
        minimo = p.get("fracao_na_caixa", 0.5)
        visto = set()
        for f0 in bm.faces:
            if f0[camada_mat] != cod or f0 in visto:
                continue
            pilha, ilha = [f0], []
            visto.add(f0)
            while pilha:
                g = pilha.pop()
                ilha.append(g)
                for e in g.edges:
                    for h in e.link_faces:
                        if h[camada_mat] == cod and h not in visto:
                            visto.add(h)
                            pilha.append(h)
            dentro = sum(1 for g in ilha if _na_caixa(g.calc_center_median(), b, 0.01))
            if dentro >= minimo * len(ilha) and dentro > 0:
                out.append(ilha)
        if not out:
            return []
        # a maior ilha é o vidro; uma ilha pequena, paralela e afastada dela para dentro é a aba do caixilho que o autor
        # marcou como vidro (no Gol do Sketchfab, 1,5 cm atrás do vidro traseiro, passando a borda da tampa): sai do modelo
        maior = max(out, key=lambda il: sum(g.calc_area() for g in il))
        nm = sum((g.normal * g.calc_area() for g in maior), Vector())
        if nm.length > 1e-9:
            nm.normalize()
            cm = sum((g.calc_center_median() for g in maior), Vector()) / len(maior)
            area_maior = sum(g.calc_area() for g in maior)
            abas = []
            for il in out:
                if il is maior or sum(g.calc_area() for g in il) > 0.25 * area_maior:
                    continue
                ds = [(g.calc_center_median() - cm).dot(nm) for g in il]
                if min(abs(d) for d in ds) > 0.008:
                    abas.append(il)
            if abas:
                import bmesh
                print(f"[carro_quebravel]   {p['name']}: {len(abas)} aba(s) de caixilho marcada(s) como vidro tiradas do modelo")
                bmesh.ops.delete(bm, geom=[g for il in abas for g in il], context="FACES")
                out = [il for il in out if il not in abas]
        return [g for il in out for g in il]
    if take == "roda":
        cx, _, cz = p["centro"]
        s = p["lado"]
        r0, r1 = p["raio"]
        y0, y1 = p["y"]
        for f in bm.faces:
            c = f.calc_center_median()
            d = _m.hypot(c.x - cx, c.z - cz)
            if r0 <= d < r1 and y0 <= c.y * s <= y1:
                out.append(f)
        return out
    if take == "textura":
        alvo = ids_peca[p["name"]]
        for f in bm.faces:
            if f[camada_peca] == alvo and _na_caixa(f.calc_center_median(), b):
                out.append(f)
        return out
    _cortar_caixa(bm, b)
    nv = Vector(p["normal"][:3]).normalized() if p.get("normal") else None
    cand = set()
    for f in bm.faces:
        c = f.calc_center_median()
        if not _na_caixa(c, b):
            continue
        if f[camada_peca] > 0 and not p.get("ignorar_rotulos"):
            continue  # face de peça da textura que ficou de fora da caixa dela: não vai para a lataria
        if p.get("fora_das_rodas"):
            if any(_m.hypot(c.x - r["cx"], c.z - r["cz"]) < r["raio"] + 0.06 and c.y * r["lado"] > r["y_dentro"] - 0.10 for r in rodas):
                continue
        cand.add(f)
        if nv is None or f.normal.dot(nv) >= p["normal"][3]:
            out.append(f)
    return _limpar_selecao(out, cand)


def _viz_bm(f):
    return {g for e in f.edges for g in e.link_faces if g is not f}


def _limpar_selecao(faces, cand, n=2, fracao=0.25):
    """
    Fechamento (dilata n anéis dentro dos candidatos da caixa e erode n) e só as partes conexas grandes: tira os fiapos que o filtro de
    normal deixa numa chapa curva (o capô do besouro) e fecha os furos dentro da peça.
    """
    sel = set(faces)
    for _ in range(n):
        sel |= {g for f in sel for g in _viz_bm(f) if g in cand}
    borda = set(sel)
    for _ in range(n):
        borda = {f for f in borda if all(g in borda for g in _viz_bm(f) if g in cand) or f in faces}
    sel = borda
    comps = []
    vistos = set()
    for f in sel:
        if f in vistos:
            continue
        pilha, grupo = [f], []
        vistos.add(f)
        while pilha:
            a = pilha.pop()
            grupo.append(a)
            for g in _viz_bm(a):
                if g in sel and g not in vistos:
                    vistos.add(g)
                    pilha.append(g)
        comps.append((sum(x.calc_area() for x in grupo), grupo))
    if not comps:
        return []
    maior = max(a for a, _ in comps)
    return [f for a, g in comps if a >= max(fracao * maior, 0.004) for f in g]


def _borda(faces):
    fs = set(faces)
    return [e for f in faces for e in f.edges if sum(1 for lf in e.link_faces if lf in fs) == 1]


def _casca(src_bm, faces, prof, escuro, manter_fora, nucleo, mat_fora=None):
    """
    Nova bmesh com as faces e, atrás delas, uma cópia afundada 'prof' metros rumo ao eixo do carro, ligadas pela borda (split_car_parts).
    manter_fora=True: a peça fechada (fora com o material e os UVs dela; dentro e borda escuros). False: o vão (só a cópia afundada,
    virada para fora, e as paredes dos dois lados), todo escuro.
    """
    import bmesh
    bm = bmesh.new()
    uvs = [(src, bm.loops.layers.uv.new(nome)) for nome, src in src_bm.loops.layers.uv.items()]
    sn = src_bm.loops.layers.float_vector.get(NORMAL_ATTR)
    dn = bm.loops.layers.float_vector.new(NORMAL_ATTR)
    norm = {v: -nucleo.dentro(v.co) for f in faces for v in f.verts}
    fora, dentro = {}, {}
    for v in norm:
        fora[v] = bm.verts.new(v.co)
        dentro[v] = bm.verts.new(v.co - norm[v] * prof)
    for f in faces:
        if manter_fora:
            nf = bm.faces.new([fora[v] for v in f.verts])
            nf.material_index = f.material_index if mat_fora is None else mat_fora
            nf.smooth = f.smooth
            for ls, ld in zip(f.loops, nf.loops):
                for src, dst in uvs:
                    ld[dst].uv = ls[src].uv
                if sn is not None:
                    ld[dn] = ls[sn]
        else:
            nf = bm.faces.new([dentro[v] for v in f.verts])
            nf.material_index = escuro
    if manter_fora and prof <= 0.0:
        return bm
    if manter_fora:
        for f in faces:
            tr = bm.faces.new([dentro[v] for v in reversed(f.verts)])
            tr.material_index = escuro
    conj = set(faces)
    for e in _borda(faces):
        a, b = e.verts
        f = next(lf for lf in e.link_faces if lf in conj)
        lp = next(l for l in f.loops if l.edge == e)
        if lp.vert != a:
            a, b = b, a
        quad = [fora[b], fora[a], dentro[a], dentro[b]]
        try:
            w = bm.faces.new(quad)
            w.material_index = escuro
            if not manter_fora:
                w2 = bm.faces.new(list(reversed(quad)))
                w2.material_index = escuro
        except ValueError:
            pass
    return bm


def _caixa_de_roda(bm, r, escuro):
    """Caixa de roda escura atrás da roda: arco de cilindro (por cima do cubo) e a parede de dentro. Normais para o cubo."""
    import math as _m
    s = r["lado"]
    Rw = r["raio"] + 0.02
    y_in = (r["y_dentro"] - 0.03) * s
    y_out = (r["y_fora"] - 0.005) * s
    n = 28
    angs = [_m.radians(-25.0 + (230.0 * i) / n) for i in range(n + 1)]
    cx, cz = r["cx"], r["cz"]
    a_in = [bm.verts.new((cx + Rw * _m.cos(t), y_in, cz + Rw * _m.sin(t))) for t in angs]
    a_out = [bm.verts.new((cx + Rw * _m.cos(t), y_out, cz + Rw * _m.sin(t))) for t in angs]
    for i in range(n):
        q = [a_in[i], a_in[i + 1], a_out[i + 1], a_out[i]]
        # normal para o cubo: ordem conforme o lado
        f = bm.faces.new(q if s > 0 else list(reversed(q)))
        f.material_index = escuro
    centro = bm.verts.new((cx, y_in, cz - 0.2 * r["raio"]))
    for i in range(n):
        q = [centro, a_in[i + 1], a_in[i]]
        f = bm.faces.new(q if s > 0 else list(reversed(q)))
        f.material_index = escuro


def _executar_mapa(obj, mapa, rodas, rel):
    """Tira as peças da carroceria na ordem do mapa. Devolve {nome: (objeto, papel, origem)} e a carroceria."""
    import bmesh
    import bpy
    me = obj.data
    mats = list(me.materials)
    idx = {m.name: i for i, m in enumerate(mats)}
    escuro, vao = idx[MAT_ESCURO], idx[MAT_VAO]
    mat_papel = {"glass_windshield": idx["vidro"], "glass_rear": idx["vidro"], "glass_door": idx["vidro"], "headlight": idx["luz"],
                 "taillight": idx["luz"], "wheel": idx["pneu"], "rim": idx["cromado"], "hubcap": idx["cromado"]}
    nucleo = _Nucleo(min(v.co.x for v in me.vertices), max(v.co.x for v in me.vertices), max(v.co.z for v in me.vertices))
    bm = bmesh.new()
    bm.from_mesh(me)
    camada = bm.faces.layers.int.get("cq_peca")
    camada_mat = bm.faces.layers.int.get("cq_mat")
    ids = {n: i for i, n in enumerate(mapa.get("_rotulos", []), start=1)}
    vaos = []
    pecas = {}
    for p in mapa["parts"]:
        faces = _escolher(bm, p, rodas, camada, ids, camada_mat)
        if not faces:
            rel["avisos"].append("peça %s: nenhuma face (ficou no corpo)" % p["name"])
            continue
        papel = p.get("papel", p["name"])
        if papel == "remover":
            # casca de dentro (o Besouro do Meshy tem parede dupla atrás dos vidros, da porta e das tampas): sai da carroceria, sem
            # virar peça nem deixar vão
            rel.setdefault("faces_removidas", {})[p["name"]] = len(faces)
            bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
            bm.faces.ensure_lookup_table()
            continue
        nb = _casca(bm, faces, float(p.get("thickness", 0.0)), escuro, True, nucleo, mat_papel.get(papel))
        if float(p.get("pocket", 0.0)) > 0.0:
            vaos.append(_casca(bm, faces, float(p["pocket"]), vao, False, nucleo))
        nme = bpy.data.meshes.new(p["name"])
        nb.to_mesh(nme)
        nb.free()
        for m_ in mats:
            nme.materials.append(m_)
        o = bpy.data.objects.new(p["name"], nme)
        bpy.context.scene.collection.objects.link(o)
        pecas[p["name"]] = (o, papel, "%s: %s" % (p.get("take", "faces"), len(faces)))
        bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")
        soltos = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
        bm.faces.ensure_lookup_table()
    # vãos e caixas de roda na carroceria
    for vb in vaos:
        tmp = bpy.data.meshes.new("vao_tmp")
        vb.to_mesh(tmp)
        vb.free()
        bm2 = bmesh.new()
        bm2.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        mapa_v = {v.index: bm.verts.new(v.co) for v in bm2.verts}
        for f in bm2.faces:
            try:
                nf = bm.faces.new([mapa_v[v.index] for v in f.verts])
                nf.material_index = f.material_index
            except ValueError:
                pass
        bm2.free()
    for r in rodas:
        _caixa_de_roda(bm, r, escuro)
    bm.to_mesh(me)
    bm.free()
    return pecas


def _aplicar_normais(me):
    """A normal guardada por canto vira a normal personalizada; canto sem normal (vão, parede, lado de dentro) fica com a da face."""
    import numpy as np
    attr = me.attributes.get(NORMAL_ATTR)
    if attr is None or not len(me.loops):
        return
    buf = np.empty(len(me.loops) * 3, np.float32)
    attr.data.foreach_get("vector", buf)
    buf = buf.reshape(-1, 3)
    pn = _arr(me, "polygons", "normal", 3)
    lt = _arr(me, "polygons", "loop_total", 1, np.int64)
    pl = np.repeat(pn, lt, axis=0)
    ln = np.linalg.norm(buf, axis=1)
    buf = np.where((ln > 0.5)[:, None], buf / np.maximum(ln, 1e-9)[:, None], pl)
    for p in me.polygons:
        p.use_smooth = True
    me.normals_split_custom_set([tuple(v) for v in buf])
    me.attributes.remove(me.attributes[NORMAL_ATTR])


def _compactar_materiais(ob):
    """Só os materiais que a peça usa, na ordem original."""
    import numpy as np
    me = ob.data
    if not len(me.polygons):
        return
    mi = _arr(me, "polygons", "material_index", 1, np.int32)
    usados = sorted(set(mi.tolist()))
    mats = list(me.materials)
    novo = {old: i for i, old in enumerate(usados)}
    me.materials.clear()
    for old in usados:
        me.materials.append(mats[old])
    me.polygons.foreach_set("material_index", np.array([novo[i] for i in mi], np.int32))


def _materiais_unica(obj):
    """O material do Meshy vira 'pintura'; cópias com a mesma textura para vidro, luz, pneu e cromado; escuro e vão sem textura."""
    import bpy
    me = obj.data
    base = me.materials[0]
    base.name = "pintura"
    mats = [base]
    for nome in ("vidro", "luz", "pneu", "cromado"):
        c = base.copy()
        c.name = nome
        mats.append(c)
    for nome, cor in ((MAT_ESCURO, (0.025, 0.025, 0.028)), (MAT_VAO, (0.04, 0.038, 0.036))):
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (cor[0], cor[1], cor[2], 1.0)
        b.inputs["Roughness"].default_value = 0.85
        mats.append(m)
    me.materials.clear()
    for m in mats:
        me.materials.append(m)
    for p in me.polygons:
        p.material_index = 0


def _carregar_mdm(caminho):
    """make_damage_morphs.py do Detonauto como biblioteca (sem gravar __pycache__ lá)."""
    import importlib.util
    arq = os.path.join(caminho, "Tools", "Blender", "make_damage_morphs.py")
    if not os.path.isfile(arq):
        return None
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("make_damage_morphs_detonauto", arq)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def previa_amassada(infos, caminho, amostras, rodas_json, detonauto, rel):
    """
    Teste dos 5 alvos do Detonauto (make_damage_morphs.displacement, o mesmo campo espacial) na carroceria e em todas as peças menos as
    rodas: intacto, frente + esquerda em 1,0 e traseira + direita + teto em 1,0. Confere a costura: vértices de peça e de carroceria que
    coincidem andam juntos (fresta medida depois de amassar).
    """
    import bpy
    import numpy as np
    from mathutils import Vector, kdtree
    mdm = _carregar_mdm(detonauto)
    if mdm is None:
        rel["avisos"].append("prévia amassada: não achei %s/Tools/Blender/make_damage_morphs.py (use --detonauto)" % detonauto)
        return None
    objs = [(ob, i) for ob, i in infos if i["papel"] not in ("wheel", "rim", "hubcap")]
    pts = np.concatenate([np.array([v.co[:] for v in ob.data.vertices]) for ob, _ in objs])
    box = mdm.Box(float(pts[:, 0].min()), float(pts[:, 0].max()), float(np.abs(pts[:, 1]).max()), float(pts[:, 2].min()),
                  float(pts[:, 2].max()))
    box.set_wheels(rodas_json["front_axle_cm"] / 100.0, rodas_json["rear_axle_cm"] / 100.0, rodas_json["wheel_radius_cm"] / 100.0)
    ondas = mdm.ripples(17)
    det = {z: round(mdm.fold_check(k, box, ondas[k], steps=10), 3) for k, z in enumerate(mdm.ZONES)}
    orig = {ob.name: [v.co.copy() for v in ob.data.vertices] for ob, _ in objs}
    corpo = next(ob for ob, i in objs if i["nome"] == "body")
    kd = kdtree.KDTree(len(corpo.data.vertices))
    for v in corpo.data.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    costura = []
    for ob, i in objs:
        if ob is corpo:
            continue
        for v in ob.data.vertices:
            co, j, d = kd.find(v.co)
            if d < 1e-5:
                costura.append((ob, v.index, j))

    def amassar(zonas):
        for ob, _ in objs:
            for v, o in zip(ob.data.vertices, orig[ob.name]):
                d = [0.0, 0.0, 0.0]
                for z in zonas:
                    dz = mdm.displacement(z, box, ondas[z], o.x, o.y, o.z)
                    d = [d[0] + dz[0], d[1] + dz[1], d[2] + dz[2]]
                v.co = (o.x + d[0], o.y + d[1], o.z + d[2])
            ob.data.update()
        return max([(ob.data.vertices[a].co - corpo.data.vertices[b].co).length for ob, a, b in costura] or [0.0])

    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = amostras
    cena.cycles.use_denoising = True
    cena.render.resolution_x, cena.render.resolution_y = 760, 520
    cena.view_settings.view_transform = "Standard"
    mundo = bpy.data.worlds.new("amassada")
    mundo.use_nodes = True
    mundo.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.84, 0.88, 1.0)
    mundo.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    cena.world = mundo
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 2.5
    sol.rotation_euler = (math.radians(40), math.radians(10), math.radians(150))
    cena.collection.objects.link(sol)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 40
    cena.collection.objects.link(cam)
    cena.camera = cam
    L = box.length
    vistas = (("intacto", (), Vector((1.0, 0.9, 0.45))), ("frente+esquerda", (0, 2), Vector((1.0, 0.9, 0.45))),
              ("traseira+direita+teto", (1, 3, 4), Vector((-1.0, -0.9, 0.55))))
    imgs = []
    frestas = {}
    for nome, zonas, dirc in vistas:
        frestas[nome] = round(1000.0 * amassar(zonas), 4)
        alvo = Vector((0.0, 0.0, 0.55))
        cam.location = alvo + dirc.normalized() * L * 1.55
        cam.rotation_euler = (alvo - cam.location).to_track_quat("-Z", "Y").to_euler()
        arq = caminho + "." + nome + ".png"
        cena.render.filepath = arq
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(arq)
        imgs.append(np.array(im.pixels[:], np.float32).reshape(im.size[1], im.size[0], 4))
        bpy.data.images.remove(im)
        os.remove(arq)
    amassar(())
    junto = np.concatenate(imgs, axis=1)
    im = bpy.data.images.new("amassada", junto.shape[1], junto.shape[0], alpha=True)
    im.pixels = junto.ravel().tolist()
    im.filepath_raw = caminho
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)
    for o in (sol, cam):
        bpy.data.objects.remove(o, do_unlink=True)
    return {"determinante_minimo": det, "fresta_maxima_mm": frestas, "vertices_na_costura": len(costura),
            "zonas": "make_damage_morphs.displacement do Detonauto, semente 17"}


def principal_unica(args, meshes, cid, out, rel):
    """Modo malha única: análise, mapa, corte, saída igual à do modo em peças, mais o mapa e a prévia amassada."""
    import bpy
    import numpy as np
    from mathutils import Matrix, Vector
    if len(meshes) > 1:
        juntar(meshes, "malha")
    obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
    assar_transformacoes([obj])
    _soldar(obj, rel, getattr(args, "manter_normais", False))
    _orientar_unica(obj, args.frente, rel)
    me = obj.data
    cen, nor, area = _faces_np(me)
    co = _arr(me, "vertices", "co", 3)
    col = _cores_faces(me)
    h, s, v = _hsv(col)
    rodas = _achar_rodas(cen, nor, co, v)
    xm = (sum(r["cx"] for r in rodas if r["nome"][0] == "f") / 2.0 + sum(r["cx"] for r in rodas if r["nome"][0] == "r") / 2.0) / 2.0
    me.transform(Matrix.Translation((-xm, 0.0, 0.0)))
    me.update()
    for r in rodas:
        r["cx"] = round(float(r["cx"] - xm), 4)
    cen, nor, area = _faces_np(me)
    co = _arr(me, "vertices", "co", 3)
    viz = _vizinhos(me)
    retros = _retrovisores(cen, co)
    cl, janelas, pecas_tex, info = _classificar_textura(cen, nor, area, col, _mr_faces(me), viz, rodas, retros, args.portas, rel)
    info.pop("_lados", None)
    if getattr(args, "sem_rotulos", False):
        cl[:] = 0
        janelas, pecas_tex = {}, {}
        rel["avisos"].append("--sem-rotulos: nada classificado pela textura; vidros e peças só pelo mapa")
    # o material de cada face como veio no arquivo (vidro, pneu, chassi...), para o take 'material' do mapa
    nomes_mat = [(m.name.split(".")[0] if m else "") for m in me.materials]
    cod = {"vidro": 1, "pneu": 2, "chassi": 3, "luz": 4, "cromado": 5}
    if "cq_mat" in me.attributes:
        me.attributes.remove(me.attributes["cq_mat"])
    me.attributes.new("cq_mat", "INT", "FACE").data.foreach_set("value", [cod.get(nomes_mat[pg.material_index], 0) if pg.material_index < len(nomes_mat) else 0 for pg in me.polygons])
    for m_ in list(me.materials)[1:]:
        if m_ is not None and m_.name.split(".")[0] in cod or (m_ is not None and m_.name.split(".")[0] in (MAT_ESCURO, MAT_VAO)):
            m_.name = "entrada_" + m_.name          # os padrões (vidro, chassi...) são criados de novo em _materiais_unica
    if args.debug_classes:
        dbg = cl.copy()
        for k, idx in janelas.items():
            dbg[idx] = 6 if "_f" in k else (7 if "_r" in k and "door" in k else 1)
        for b in retros.values():
            dbg[_dentro_caixa(cen, b) & (dbg == 0)] = 5
        _render_debug(obj, dbg, os.path.join(out, "%s_classes.png" % cid))
    rotulos = sorted(set(pecas_tex) | set(janelas))
    if args.mapa:
        with open(args.mapa, encoding="utf-8") as fh:
            mapa = json.load(fh)
        rel["mapa"] = "lido de %s" % args.mapa
        if mapa.get("rodas"):
            # rodas escritas à mão no mapa (o detector pegava a caixa de roda como banda de rodagem no Gol do Sketchfab)
            rodas = [dict(nome=r["nome"], lado=r["lado"], cx=r["cx"], cz=r["cz"], raio=r["raio"], y_dentro=r["y_dentro"], y_fora=r["y_fora"],
                          y_alcance=r.get("y_alcance", r["y_fora"]), raio_aro=r.get("raio_aro"), raio_calota=r.get("raio_calota")) for r in mapa["rodas"]]
            rel["avisos"].append("rodas lidas do mapa (%d)" % len(rodas))
    else:
        mapa = _gerar_mapa(cid, cen, nor, rodas, retros, janelas, pecas_tex, info, rel)
        rel["mapa"] = "gerado pelas proporções"
    mapa["_rotulos"] = rotulos
    # rótulo das peças de textura na face e a normal de cada canto (atravessam o corte)
    rot = np.zeros(len(cen), np.int32)
    for i, n in enumerate(rotulos, start=1):
        rot[pecas_tex[n] if n in pecas_tex else janelas[n]] = i
    if "cq_peca" in me.attributes:
        me.attributes.remove(me.attributes["cq_peca"])
    me.attributes.new("cq_peca", "INT", "FACE").data.foreach_set("value", rot)
    guardar_normais(me)
    _materiais_unica(obj)
    pecas = _executar_mapa(obj, mapa, rodas, rel)
    obj.name = obj.data.name = "body"
    for nome_attr in ("cq_peca", "cq_mat"):
        if nome_attr in me.attributes:
            me.attributes.remove(me.attributes[nome_attr])
    finais = {"body": (obj, "body", ["malha única: o que sobrou, com os vãos e as caixas de roda"])}
    for nome, (o, papel, origem) in pecas.items():
        finais[nome] = (o, papel, ["malha única, " + origem + " faces"])
    with open(os.path.join(out, "%s_mapa.json" % cid), "w", encoding="utf-8") as fh:
        json.dump({k: v_ for k, v_ in mapa.items() if k != "_rotulos"}, fh, ensure_ascii=False, indent=1)

    rodas_por_nome = {r["nome"]: r for r in rodas}
    infos = []
    tudo = uniao([caixa_obj(o) for o, *_ in finais.values() if len(o.data.vertices)])
    comp0 = tudo[1] - tudo[0]
    zm = (tudo[4] + tudo[5]) / 2.0
    eixo = (Vector((tudo[0] + 0.25 * comp0, 0.0, zm)), Vector((tudo[1] - 0.25 * comp0, 0.0, zm)))
    for nome in sorted(finais):
        ob, papel, orig = finais[nome]
        _aplicar_normais(ob.data)
        _compactar_materiais(ob)
        val = limpar_malha(ob)
        nor_ = conferir_normais(ob, "wheel" if papel in ("rim", "hubcap") else papel, eixo)
        cx = caixa_obj(ob)
        piv = [0.0, 0.0, 0.0]
        m_ = re.match(r"(?:wheel_|hubcap_)(fl|fr|rl|rr)", nome)
        if m_:
            r = rodas_por_nome[m_.group(1)]
            c = (r["cx"], r["lado"] * (r["y_dentro"] + r["y_fora"]) / 2.0, r["cz"])
            piv = [round(c[0], 4), round(c[1], 4), round(c[2], 4)]
            transformar_tudo([ob], Matrix.Translation((-c[0], -c[1], -c[2])))
            ob.location = c
        mats = [m.name for m in ob.data.materials if m]
        infos.append((ob, {
            "nome": nome, "papel": papel, "detonauto": DETONAUTO.get(nome, DETONAUTO.get(papel)),
            "caixa_m": [round(x, 4) for x in cx], "centro": [round(x, 4) for x in centro(cx)], "pivo_m": piv,
            "triangulos": triangulos(ob.data), "materiais": mats, "origem": orig,
            "malha": dict(val, **nor_), "fbx": "%s_pecas/%s.fbx" % (cid, nome),
        }))
        if nor_["virada"]:
            rel["avisos"].append("%s: virei %s" % (nome, nor_["virada"]))
    fr = [r["cx"] for r in rodas if r["nome"][0] == "f"]
    rr = [r["cx"] for r in rodas if r["nome"][0] == "r"]
    raio = sum(r["raio"] for r in rodas) / len(rodas)
    rodas_json = {"front_axle_cm": round(100 * sum(fr) / len(fr), 2), "rear_axle_cm": round(100 * sum(rr) / len(rr), 2),
                  "wheel_radius_cm": round(100 * raio, 2),
                  "nota": "espaço do carro do carro_quebravel (frente +X, pivô entre os eixos); formato de Tools/Unreal/damage_body.py"}
    with open(os.path.join(out, "%s_wheels.json" % cid), "w", encoding="utf-8") as fh:
        json.dump(rodas_json, fh, ensure_ascii=False, indent=2)
    papel_material, pecas_por_papel = {}, {}
    for _, i in infos:
        papel_material.setdefault(i["papel"], set()).update(i["materiais"])
        pecas_por_papel.setdefault(i["papel"], []).append(i["nome"])
    comp = tudo[1] - tudo[0]
    nomes = {i["nome"] for _, i in infos}
    fora = sorted(n for n in nomes if n != "body" and DETONAUTO.get(n, DETONAUTO.get(re.sub(r"_(fl|fr|rl|rr|left|right)$", "", n))) is None
                  and not n.startswith(("glass_", "headlight", "taillight")))
    dados = {
        "id": cid, "entrada": rel["entrada"], "gerado_por": "acervo-3d/ferramentas/carro_quebravel.py (malha única)",
        "convencao": "metros; eixos do Blender: frente +X, ESQUERDA +Y, cima +Z; pivô do carro no chão, no centro entre os eixos; "
                     "caixa_m = [xmin, xmax, ymin, ymax, zmin, zmax] no espaço do carro; rodas, aros e calotas com pivô no centro do cubo",
        "dimensoes_m": {"comprimento": round(comp, 3), "largura": round(tudo[3] - tudo[2], 3), "altura": round(tudo[5] - tudo[4], 3),
                        "entre_eixos": round((rodas_json["front_axle_cm"] - rodas_json["rear_axle_cm"]) / 100.0, 3),
                        "raio_roda": round(raio, 3)},
        "escala": rel["escala"], "orientacao": rel["orientacao"], "solda": rel["solda"], "mapa": "%s_mapa.json (%s)" % (cid, rel["mapa"]),
        "textura": {k: v_ for k, v_ in info.items() if k != "faces"}, "faces_por_classe": info.get("faces"),
        "materiais": {"Material_0 (Meshy)": "pintura; cópias com a mesma textura: vidro, luz, pneu, cromado; sem textura: %s, %s" % (
            MAT_ESCURO, MAT_VAO)},
        "papel_material": {k: sorted(v_) for k, v_ in sorted(papel_material.items())},
        "pecas_por_papel": {k: sorted(v_) for k, v_ in sorted(pecas_por_papel.items())},
        "fora_do_vocabulario_do_detonauto": fora, "removidos": [], "outros": [],
        "faces_removidas": rel.get("faces_removidas", {}),
        "avisos": rel["avisos"], "rodas_cm": rodas_json, "rodas_achadas": rodas,
        "pecas": [i for _, i in infos],
    }
    for o in bpy.context.scene.objects:
        o.select_set(True)
    glb = os.path.join(out, "%s.glb" % cid)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False, export_yup=True, export_apply=False,
                              export_normals=True, export_extras=False)
    if not args.sem_fbx:
        tex = os.path.join(out, "%s_texturas" % cid)
        dados["texturas"] = "%s_texturas/ (%d arquivos)" % (cid, salvar_texturas(tex))
        pasta = os.path.join(out, "%s_pecas" % cid)
        os.makedirs(pasta, exist_ok=True)
        for ob, i in infos:
            exportar_fbx(ob, os.path.join(pasta, "%s.fbx" % i["nome"]))
    if not args.sem_previa:
        dados["amassada"] = previa_amassada(infos, os.path.join(out, "%s_amassada.png" % cid), args.amostras, rodas_json,
                                            args.detonauto, rel)
        previa(infos, os.path.join(out, "%s_previa.png" % cid), args.amostras, comp)
    with open(os.path.join(out, "%s_pecas.json" % cid), "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=2)
    d = dados["dimensoes_m"]
    log("%s (malha única): %.2f x %.2f x %.2f m, entre-eixos %s m, roda r=%s m; %s" % (
        cid, d["comprimento"], d["largura"], d["altura"], d["entre_eixos"], d["raio_roda"], "; ".join(rel["orientacao"])))
    tot = 0
    for _, i in infos:
        tot += i["triangulos"]
        log("  %-22s %6d tri  %s" % (i["nome"], i["triangulos"], ", ".join(i["materiais"])))
    log("total: %d triângulos em %d peças" % (tot, len(infos)))
    if dados.get("amassada"):
        log("amassada: %s" % dados["amassada"])
    for a in rel["avisos"]:
        log("aviso: " + a)
    log("gravado em %s" % out)
    return 0


# --------------------------------------------------------------------------------------------------------------------------------

def principal(argv):
    import bpy
    args = parse_args(argv)
    entrada = os.path.abspath(args.entrada)
    if not os.path.isfile(entrada):
        raise Erro("Arquivo não encontrado: %s" % entrada)
    cid = args.id or os.path.basename(entrada).split("__")[0].rsplit(".", 1)[0]
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    rel = {"id": cid, "entrada": os.path.basename(entrada), "avisos": []}

    meshes = importar(entrada)
    if args.malha_unica or (len(meshes) == 1 and not args.em_pecas):
        return principal_unica(args, meshes, cid, out, rel)
    assar_transformacoes(meshes)
    itens = classificar(meshes, rel)
    if not any(p == "wheel" for _, p, *_ in itens):
        rel["avisos"].append("nenhuma roda reconhecida: pivô pelo fundo da caixa")
    fator = escolher_escala(itens, args.escala, rel)
    orientar(itens, fator, rel)
    pecas = dividir_por_lado_e_posicao(itens, rel)

    # junta tudo o que tem o mesmo nome de peça
    por_nome = {}
    origem = {}
    papel_de = {}
    for ob, nome, papel, orig in pecas:
        por_nome.setdefault(nome, []).append(ob)
        origem.setdefault(nome, []).append(orig)
        papel_de[nome] = papel if nome != "body" else "body"
    outros = [n for n, p in papel_de.items() if p == "outros"]
    # "outros" um por objeto, com o nome dele
    finais = {}
    for nome, obs in por_nome.items():
        if papel_de[nome] == "outros":
            for ob, orig in zip(obs, origem[nome]):
                n2 = "outros_" + re.sub(r"[^a-z0-9]+", "_", rel["limpos"].get(orig, orig.lower())).strip("_")
                finais[n2] = (juntar([ob], n2), "outros", [orig])
        else:
            finais[nome] = (juntar(obs, nome), papel_de[nome], sorted(set(origem[nome])))
    del outros
    purgar()
    mapa_mat = padronizar_materiais(rel)

    # validação, pivô das rodas, medidas
    infos = []
    tudo = uniao([caixa_obj(o) for o, *_ in finais.values()])
    rodas = {}
    from mathutils import Vector
    comp0 = tudo[1] - tudo[0]
    zm = (tudo[4] + tudo[5]) / 2.0
    eixo = (Vector((tudo[0] + 0.25 * comp0, 0.0, zm)), Vector((tudo[1] - 0.25 * comp0, 0.0, zm)))
    for nome in sorted(finais):
        ob, papel, orig = finais[nome]
        val = limpar_malha(ob)
        nor = conferir_normais(ob, papel, eixo)
        cx = caixa_obj(ob)
        piv = [0.0, 0.0, 0.0]
        if papel == "wheel":
            c = centro(cx)
            piv = [round(c[0], 4), round(c[1], 4), round(c[2], 4)]
            from mathutils import Matrix
            transformar_tudo([ob], Matrix.Translation((-c[0], -c[1], -c[2])))
            ob.location = c
            rodas[nome] = (c, max(cx[1] - cx[0], cx[5] - cx[4]) / 2.0, cx[3] - cx[2])
        mats = [m.name for m in ob.data.materials if m]
        infos.append((ob, {
            "nome": nome, "papel": papel, "detonauto": DETONAUTO.get(nome, DETONAUTO.get(papel)),
            "caixa_m": [round(v, 4) for v in cx], "centro": [round(v, 4) for v in centro(cx)], "pivo_m": piv,
            "triangulos": triangulos(ob.data), "materiais": mats, "origem": orig,
            "malha": dict(val, **nor), "fbx": "%s_pecas/%s.fbx" % (cid, nome),
        }))
        if nor["virada"]:
            rel["avisos"].append("%s: virei %s" % (nome, nor["virada"]))
        if val["vertices_nan"]:
            rel["avisos"].append("%s: %d vértices com NaN" % (nome, val["vertices_nan"]))

    # rodas -> wheels.json do Detonauto (cm)
    rodas_json = None
    if rodas:
        fr = [v[0][0] for k, v in rodas.items() if k.startswith("wheel_f")]
        rr = [v[0][0] for k, v in rodas.items() if k.startswith("wheel_r")]
        raio = sum(v[1] for v in rodas.values()) / len(rodas)
        rodas_json = {"front_axle_cm": round(100 * sum(fr) / max(1, len(fr)), 2), "rear_axle_cm": round(100 * sum(rr) / max(1, len(rr)), 2),
                      "wheel_radius_cm": round(100 * raio, 2),
                      "nota": "espaço do carro do carro_quebravel (frente +X, pivô entre os eixos); formato de Tools/Unreal/damage_body.py"}
        with open(os.path.join(out, "%s_wheels.json" % cid), "w", encoding="utf-8") as fh:
            json.dump(rodas_json, fh, ensure_ascii=False, indent=2)
        if len(rodas) != 4:
            rel["avisos"].append("%d rodas (esperado 4): %s" % (len(rodas), sorted(rodas)))

    papel_material = {}
    for _, info in infos:
        papel_material.setdefault(info["papel"], set()).update(info["materiais"])
    pecas_por_papel = {}
    for _, info in infos:
        pecas_por_papel.setdefault(info["papel"], []).append(info["nome"])

    comp = tudo[1] - tudo[0]
    dados = {
        "id": cid, "entrada": rel["entrada"], "gerado_por": "acervo-3d/ferramentas/carro_quebravel.py",
        "convencao": "metros; eixos do Blender: frente +X, ESQUERDA +Y, cima +Z; pivô do carro no chão, no centro entre os eixos; "
                     "caixa_m = [xmin, xmax, ymin, ymax, zmin, zmax] no espaço do carro (o formato de 'box' em Detonauto/Tools/Blender/parts); "
                     "rodas com pivô no centro do cubo (pivo_m, no espaço do carro), as outras peças com o pivô do carro",
        "dimensoes_m": {"comprimento": round(comp, 3), "largura": round(tudo[3] - tudo[2], 3), "altura": round(tudo[5] - tudo[4], 3),
                        "entre_eixos": round((rodas_json["front_axle_cm"] - rodas_json["rear_axle_cm"]) / 100.0, 3) if rodas_json else None,
                        "raio_roda": round(rodas_json["wheel_radius_cm"] / 100.0, 3) if rodas_json else None},
        "escala": rel["escala"], "orientacao": rel["orientacao"], "prefixo_do_modelo": rel["prefixo"],
        "materiais": mapa_mat, "papel_material": {k: sorted(v) for k, v in sorted(papel_material.items())},
        "pecas_por_papel": {k: sorted(v) for k, v in sorted(pecas_por_papel.items())},
        "removidos": rel["removidos"], "outros": sorted(i["nome"] for _, i in infos if i["papel"] == "outros"),
        "avisos": rel["avisos"], "rodas_cm": rodas_json,
        "pecas": [i for _, i in infos],
    }

    # GLB com tudo
    for o in bpy.context.scene.objects:
        o.select_set(True)
    glb = os.path.join(out, "%s.glb" % cid)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=False, export_yup=True, export_apply=False,
                              export_normals=True, export_extras=False)
    # FBX por peça
    if not args.sem_fbx:
        tex = os.path.join(out, "%s_texturas" % cid)
        dados["texturas"] = "%s_texturas/ (%d arquivos)" % (cid, salvar_texturas(tex))
        pasta = os.path.join(out, "%s_pecas" % cid)
        os.makedirs(pasta, exist_ok=True)
        for ob, info in infos:
            exportar_fbx(ob, os.path.join(pasta, "%s.fbx" % info["nome"]))
    with open(os.path.join(out, "%s_pecas.json" % cid), "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=2)
    if not args.sem_previa:
        previa(infos, os.path.join(out, "%s_previa.png" % cid), args.amostras, comp)

    # relatório
    d = dados["dimensoes_m"]
    log("%s: %.2f x %.2f x %.2f m, entre-eixos %s m, roda r=%s m, escala x%s, %s" % (
        cid, d["comprimento"], d["largura"], d["altura"], d["entre_eixos"], d["raio_roda"], rel["escala"]["fator"], "; ".join(rel["orientacao"])))
    log("removidos (%d): %s" % (len(rel["removidos"]), ", ".join(r["objeto"] for r in rel["removidos"])))
    for papel, nomes in dados["pecas_por_papel"].items():
        log("  %-17s %s" % (papel, ", ".join(nomes)))
    log("outros (%d): %s" % (len(dados["outros"]), ", ".join(dados["outros"]) or "nenhum"))
    log("materiais: %s" % ", ".join("%s -> %s" % kv for kv in mapa_mat.items()))
    for _, i in infos:
        m = i["malha"]
        log("  %-17s %6d tri  caixa %s  normais contra a face %.0f%%, área p/ fora %.0f%%%s" % (
            i["nome"], i["triangulos"], [round(v, 2) for v in i["caixa_m"]], 100 * m["cantos_contra_face"], 100 * m["area_para_fora"],
            "  (virei %s)" % m["virada"] if m["virada"] else ""))
    for a in rel["avisos"]:
        log("aviso: " + a)
    log("gravado em %s" % out)
    return 0


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    try:
        return principal(argv)
    except Erro as exc:
        log("ERRO: %s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
