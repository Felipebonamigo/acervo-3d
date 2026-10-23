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
        if papel == "wheel":
            d.y += 0.7 * (1 if c.y >= 0 else -1)
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
