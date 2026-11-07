"""
Folha do catálogo de rodas (06/11/2026, Detonauto/docs/rodas-trocaveis.md): cada família de aro com o pneu e a calota do kit, de frente
para a câmera, com o acabamento de Data/RimFinishes.csv do Detonauto aplicado como o jogo faz (cor, metal e aspereza no aro; no
diamantado, a face torneada à parte; poeira de freio escura perto do cubo; pneu quase preto com pó marrom claro no flanco).

    python -I ferramentas/catalogo_rodas.py -- <saida.jpg> [--rodas veiculos/proprios/rodas] [--detonauto ../detonauto] [--hdri rua.hdr]
        [--itens "aro_liga5r14:pneu_p185_60::diamantado,aro_aco13:pneu_p175_70:calota13:aco-prata,..."] [--colunas 5] [--amostras 24]

Cada item é aro:pneu:calota:acabamento (calota vazia = sem). Sem --itens, sai a folha das famílias em 14" (13" e 15" onde a família não tem
14"). Chão neutro, luz de dia; HDRI opcional (Poly Haven, CC0, fora do acervo).
"""
import csv
import math
import os
import sys

import bpy
from mathutils import Vector

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, ".."))

PADRAO = ("aro_aco14:pneu_p185_60:calota14:aco-prata,aro_aco14:pneu_p185_60:calotaraiada14:aco-prata,"
          "aro_aco14:pneu_p185_60:calotaturbina14:aco-prata,aro_aco14:pneu_p185_60:calotameia14:aco-preto,"
          "aro_aco14:pneu_p185_60:tampinha:cor-do-carro,aro_liga4f14:pneu_p185_60::prata,aro_liga14:pneu_p185_60::grafite,"
          "aro_liga5r14:pneu_p185_60::diamantado,aro_liga6r14:pneu_p185_60::prata,aro_multi14:pneu_p185_60::cromado,"
          "aro_colmeia14:pneu_p185_60::prata,aro_estrela14:pneu_p185_60::preto-fosco,aro_liga13:pneu_p175_70::prata,"
          "aro_fundo14:pneu_p185_70::cromado,aro_picape16:pneu_p215_70::aco-preto,aro_van16:pneu_p205_70::aco-prata")


def args():
    a = sys.argv[sys.argv.index("--") + 1:]
    out = {"saida": a[0], "rodas": os.path.join(RAIZ, "veiculos", "proprios", "rodas"), "itens": PADRAO, "colunas": "4",
           "amostras": "24", "hdri": "", "cor": "0.4125,0.0080,0.0070"}
    for d in (os.path.join(RAIZ, "..", "detonauto"), os.path.join(RAIZ, "..", "Detonauto")):
        if os.path.isdir(d):
            out["detonauto"] = d
    i = 1
    while i < len(a):
        out[a[i][2:]] = a[i + 1]
        i += 2
    return out


def srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def acabamentos(detonauto):
    with open(os.path.join(detonauto, "Data", "RimFinishes.csv"), encoding="utf-8") as f:
        return {r["Id"]: r for r in csv.DictReader(f)}


def importar(caminho, nome):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=caminho)
    novos = [o for o in bpy.data.objects if o not in antes]
    alvo = None
    for o in novos:
        if o.name.split(".")[0] == nome:
            alvo = o
        else:
            bpy.data.objects.remove(o, do_unlink=True)
    return alvo


def principled(m):
    return [n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"][0]


def poeira_freio(m, b, quanto):
    """Escurece perto do cubo e no fundo dos raios (pela distância ao eixo, com ruído), como o pó de pastilha acumulado."""
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    r = nt.nodes.new("ShaderNodeVectorMath")
    r.operation = "LENGTH"
    cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["X"], cmb.inputs["X"])
    nt.links.new(sep.outputs["Z"], cmb.inputs["Z"])
    nt.links.new(cmb.outputs[0], r.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = 0.05
    mr.inputs["From Max"].default_value = 0.17
    mr.inputs["To Min"].default_value = quanto
    mr.inputs["To Max"].default_value = quanto * 0.25
    nt.links.new(r.outputs["Value"], mr.inputs["Value"])
    ru = nt.nodes.new("ShaderNodeTexNoise")
    ru.inputs["Scale"].default_value = 60.0
    nt.links.new(tc.outputs["Object"], ru.inputs["Vector"])
    f = nt.nodes.new("ShaderNodeMath")
    f.operation = "MULTIPLY"
    nt.links.new(mr.outputs[0], f.inputs[0])
    nt.links.new(ru.outputs["Fac"], f.inputs[1])
    f2 = nt.nodes.new("ShaderNodeMath")
    f2.operation = "MULTIPLY"
    f2.inputs[1].default_value = 1.6
    nt.links.new(f.outputs[0], f2.inputs[0])
    mx = nt.nodes.new("ShaderNodeMix")
    mx.data_type = "RGBA"
    nt.links.new(f2.outputs[0], mx.inputs[0])
    mx.inputs[6].default_value = b.inputs["Base Color"].default_value
    mx.inputs[7].default_value = (0.045, 0.038, 0.032, 1)
    nt.links.new(mx.outputs[2], b.inputs["Base Color"])
    rr = nt.nodes.new("ShaderNodeMix")
    rr.data_type = "FLOAT"
    nt.links.new(f2.outputs[0], rr.inputs[0])
    rr.inputs[2].default_value = b.inputs["Roughness"].default_value
    rr.inputs[3].default_value = 0.8
    nt.links.new(rr.outputs[0], b.inputs["Roughness"])


def torno(m, b, quanto):
    """Marcas de torno da face diamantada (Torneado do M_DNRoda): anéis de ~3 mm e ~1,2 cm em volta do eixo Y, que escurecem um pouco
    e mexem na aspereza (o reflexo vira faixas, como no aro torneado de verdade)."""
    nt = m.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(sep.outputs["X"], cmb.inputs["X"])
    nt.links.new(sep.outputs["Z"], cmb.inputs["Z"])
    r = nt.nodes.new("ShaderNodeVectorMath")
    r.operation = "LENGTH"
    nt.links.new(cmb.outputs[0], r.inputs[0])

    def onda(freq, fase):
        mul = nt.nodes.new("ShaderNodeMath"); mul.operation = "MULTIPLY_ADD"
        mul.inputs[1].default_value = freq * 100.0; mul.inputs[2].default_value = fase   # r em metros; freq por cm
        nt.links.new(r.outputs["Value"], mul.inputs[0])
        sn = nt.nodes.new("ShaderNodeMath"); sn.operation = "SINE"
        nt.links.new(mul.outputs[0], sn.inputs[0])
        h = nt.nodes.new("ShaderNodeMath"); h.operation = "MULTIPLY_ADD"
        h.inputs[1].default_value = 0.5; h.inputs[2].default_value = 0.5
        nt.links.new(sn.outputs[0], h.inputs[0])
        return h
    fino, largo = onda(21.0, 0.0), onda(5.2, 1.3)
    escuro = nt.nodes.new("ShaderNodeMath"); escuro.operation = "MULTIPLY_ADD"
    escuro.inputs[1].default_value = -quanto * 0.10
    nt.links.new(fino.outputs[0], escuro.inputs[0])
    esc2 = nt.nodes.new("ShaderNodeMath"); esc2.operation = "MULTIPLY_ADD"
    esc2.inputs[1].default_value = -quanto * 0.14
    nt.links.new(largo.outputs[0], esc2.inputs[0])
    nt.links.new(escuro.outputs[0], esc2.inputs[2])
    escuro.inputs[2].default_value = 1.0
    src = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].links else None
    mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs[0].default_value = 1.0
    if src is not None:
        nt.links.new(src, mx.inputs[6])
    else:
        mx.inputs[6].default_value = b.inputs["Base Color"].default_value
    cv = nt.nodes.new("ShaderNodeCombineColor")
    for i in range(3):
        nt.links.new(esc2.outputs[0], cv.inputs[i])
    nt.links.new(cv.outputs[0], mx.inputs[7])
    nt.links.new(mx.outputs[2], b.inputs["Base Color"])
    rg = nt.nodes.new("ShaderNodeMath"); rg.operation = "MULTIPLY_ADD"
    rg.inputs[1].default_value = quanto * 0.10
    rsrc = b.inputs["Roughness"].links[0].from_socket if b.inputs["Roughness"].links else None
    if rsrc is not None:
        nt.links.new(rsrc, rg.inputs[2])
    else:
        rg.inputs[2].default_value = b.inputs["Roughness"].default_value
    nt.links.new(fino.outputs[0], rg.inputs[0])
    nt.links.new(rg.outputs[0], b.inputs["Roughness"])


def vestir(o, acab, cor_carro, k):
    """Copia os materiais do objeto e aplica o acabamento (o jogo faz igual: M_DNRoda com Cor, Metal, Aspereza e PoeiraFreio)."""
    for i, m in enumerate(o.data.materials):
        if m is None:
            continue
        base = m.name.split(".")[0]
        m2 = m.copy()
        m2.name = "%s_%d" % (base, k)
        o.data.materials[i] = m2
        b = principled(m2)
        for l in list(b.inputs["Base Color"].links):
            m2.node_tree.links.remove(l)
        if base in ("aro_aco", "aro_liga", "aro_face") and acab:
            face = base == "aro_face"
            if acab["UsePaint"] == "1":
                c = cor_carro
            else:
                c = [srgb(float(acab["FaceR" if face else "R"])), srgb(float(acab["FaceG" if face else "G"])),
                     srgb(float(acab["FaceB" if face else "B"]))]
            b.inputs["Base Color"].default_value = (c[0], c[1], c[2], 1)
            b.inputs["Metallic"].default_value = float(acab["FaceMetallic" if face else "Metallic"])
            b.inputs["Roughness"].default_value = float(acab["FaceRoughness" if face else "Roughness"])
            poeira_freio(m2, b, float(acab["BrakeDust"]))
            if face and float(acab.get("Lathe") or 0) > 0:
                torno(m2, b, float(acab["Lathe"]))
        elif base == "pneu":
            b.inputs["Base Color"].default_value = (0.022, 0.022, 0.024, 1)
            b.inputs["Roughness"].default_value = 0.8
        elif base == "calota":
            b.inputs["Base Color"].default_value = (0.56, 0.57, 0.58, 1)


def main():
    a = args()
    acabs = acabamentos(a["detonauto"])
    cor_carro = [float(x) for x in a["cor"].split(",")]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    itens = [x.split(":") for x in a["itens"].split(",") if x]
    col = int(a["colunas"])
    passo = 0.78
    for k, (aro, pneu, cal, acab) in enumerate(itens):
        x = -(k % col) * passo          # a câmera olha a face de fora (+Y): a ordem cresce para -X na tela
        z = -(k // col) * passo
        objs = [importar(os.path.join(a["rodas"], aro + ".glb"), aro),
                importar(os.path.join(a["rodas"], pneu + ".glb"), pneu + "_Ok")]
        if cal:
            nome = cal
            objs.append(importar(os.path.join(a["rodas"], cal + ".glb"), nome))
        for o in objs:
            if o is None:
                continue
            o.location = (x, 0, z)
            vestir(o, acabs.get(acab), cor_carro, k)
        # rótulo sob a roda
        bpy.ops.object.text_add(location=(x, 0.1, z - 0.36), rotation=(math.radians(90), 0, math.radians(180)))
        t = bpy.context.object
        t.data.body = "%s%s / %s" % (aro.replace("aro_", ""), (" + " + cal) if cal else "", acab)
        t.data.size = 0.032
        t.data.align_x = "CENTER"
        mt = bpy.data.materials.new("rotulo%d" % k)
        mt.use_nodes = True
        principled(mt).inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1)
        t.data.materials.append(mt)
    linhas = (len(itens) + col - 1) // col
    w = bpy.data.worlds.new("w")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    if a["hdri"]:
        env = w.node_tree.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(a["hdri"])
        w.node_tree.links.new(env.outputs[0], bg.inputs[0])
        bg.inputs[1].default_value = 1.4
    else:
        bg.inputs[0].default_value = (0.5, 0.52, 0.55, 1)
    sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN"))
    sol.data.energy = 4.0
    # sol de dia vindo de cima e de trás da câmera (as rodas olham para +Y)
    sol.rotation_euler = (Vector((0.35, 1.0, 0.9)) * -1).to_track_quat("-Z", "Y").to_euler()
    sc.collection.objects.link(sol)
    fundo = bpy.data.objects.new("fundo", bpy.data.meshes.new("fundo"))
    sc.collection.objects.link(fundo)
    L = 20
    fundo.data.from_pydata([(-L, -0.3, -L), (L, -0.3, -L), (L, -0.3, L), (-L, -0.3, L)], [], [(0, 1, 2, 3)])
    mf = bpy.data.materials.new("fundo")
    mf.use_nodes = True
    principled(mf).inputs["Base Color"].default_value = (0.11, 0.115, 0.12, 1)
    fundo.data.materials.append(mf)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    cx = -(col - 1) * passo / 2
    cz = -(linhas - 1) * passo / 2 - 0.03
    cam.location = (cx - 0.35, 3.0, cz + 0.25)
    cam.rotation_euler = (Vector((cx, 0, cz)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = max(col, linhas) * passo + 0.25
    sc.camera = cam
    sc.render.engine = "CYCLES"
    sc.cycles.samples = int(a["amostras"])
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 360 * col
    sc.render.resolution_y = int(360 * col * (linhas * passo + 0.1) / (col * passo + 0.1))
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.exposure = 0.6
    sc.render.filepath = a["saida"]
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 88
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
