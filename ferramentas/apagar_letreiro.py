"""Apaga letreiro, logo ou texto que o gerador de IA pintou na textura de um modelo (regra do estúdio: nenhum texto de marca).

Roda no Blender (ou com o módulo bpy, numpy e Pillow):
  blender -b -P ferramentas/apagar_letreiro.py -- --entrada carro.glb --saida carro.glb --caixa x0,x1,y0,y1,z0,z1
          [--normal +z] [--passo 0.002] [--limiar 0.08] [--entorno 0.06] [--previa antes_depois.png]

--caixa: a região do modelo em metros (eixos do arquivo) onde está o letreiro, por exemplo o capô junto ao para-brisa.
--normal: de que lado se olha a região (+z = de cima, +x = de frente...).
Só a textura: quando o Meshy também esculpe o emblema na malha, o relevo fica (sem cor ele vira um friso qualquer).
Aplainar a malha não deu certo (23/10/2026): as UVs do Meshy separam os vértices em costuras e a malha racha.

Como as UVs do Meshy espalham uma mesma superfície pela textura inteira, o script não trabalha na textura direto: lança
raios do lado de --normal sobre a caixa, num passo de --passo metros, e monta uma imagem "vista de fora" da pintura. Nessa
imagem acha o que difere da cor do entorno (mediana numa janela de --entorno metros, maior que a mancha) por mais de --limiar, e repinta com a
cor do entorno os texels de todos os triângulos da caixa (inclusive faces duplicadas) que caem nesses pontos, em todas as texturas do material (cor, rugosidade e o mapa de normais, onde o
letreiro costuma estar também em relevo). Sujeira grande e sombra suave ficam; traço fino de letra some. Com --previa,
salva uma linha por textura com a vista antes (esquerda) e depois (direita); a imagem sai com +Y para cima.
"""
import sys, argparse, os, tempfile

try:
    import bpy
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    from PIL import Image, ImageFilter
except ImportError:
    print("este script roda dentro do Blender (blender -b -P ...) ou com bpy, numpy e Pillow instalados"); sys.exit(2)

EIXOS = {"+x": (0, 1, 2, 1), "-x": (0, 1, 2, -1), "+y": (1, 0, 2, 1), "-y": (1, 0, 2, -1), "+z": (2, 0, 1, 1), "-z": (2, 0, 1, -1)}

def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", required=True); p.add_argument("--saida", required=True)
    p.add_argument("--caixa", required=True, help="x0,x1,y0,y1,z0,z1 em metros")
    p.add_argument("--normal", default="+z", choices=list(EIXOS))
    p.add_argument("--passo", type=float, default=0.002)
    p.add_argument("--limiar", type=float, default=0.08)
    p.add_argument("--entorno", type=float, default=0.06, help="largura da janela da cor do entorno [m]; maior que a mancha")
    p.add_argument("--previa")
    return p.parse_args(argv)

def main():
    a = args()
    cx = [float(v) for v in a.caixa.split(",")]
    lo = Vector((cx[0], cx[2], cx[4])); hi = Vector((cx[1], cx[3], cx[5]))
    prof, ua, va, sinal = EIXOS[a.normal]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.entrada)
    obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
    me = obj.data; mw = obj.matrix_world; uvd = me.uv_layers.active.data
    me.calc_loop_triangles()
    tris = me.loop_triangles
    verts = [mw @ v.co for v in me.vertices]
    bvh = BVHTree.FromPolygons(verts, [t.vertices[:] for t in tris])
    # todas as texturas do material: o letreiro costuma estar na cor e também em relevo no mapa de normais
    nos = [n for n in me.materials[0].node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    pasta = tempfile.mkdtemp(); texs = []
    for k, n in enumerate(nos):
        caminho = os.path.join(pasta, f"t{k}.png")
        n.image.filepath_raw = caminho; n.image.file_format = "PNG"; n.image.save()
        texs.append(np.asarray(Image.open(caminho).convert("RGB")).copy())
    w, h = nos[0].image.size

    nu = int((hi[ua] - lo[ua]) / a.passo) + 1; nv = int((hi[va] - lo[va]) / a.passo) + 1
    acerto = np.full((nv, nu, 2), -1, np.int32)
    d = Vector((0, 0, 0)); d[prof] = -sinal
    for j in range(nv):
        for i in range(nu):
            o = Vector((0, 0, 0)); o[ua] = lo[ua] + i * a.passo; o[va] = lo[va] + j * a.passo
            o[prof] = (hi[prof] + 0.05) if sinal > 0 else (lo[prof] - 0.05)
            hit, _n, ti, _dist = bvh.ray_cast(o, d)
            if hit is None or not (lo[prof] <= hit[prof] <= hi[prof]): continue
            t = tris[ti]
            p = [verts[k] for k in t.vertices]; q = [Vector((*uvd[l].uv, 0)) for l in t.loops]
            uv = barycentric_transform(hit, p[0], p[1], p[2], q[0], q[1], q[2])
            acerto[j, i] = (min(w - 1, max(0, int(uv.x * w))), min(h - 1, max(0, int((1 - uv.y) * h))))
    ok = acerto[..., 0] >= 0
    if not ok.any(): raise SystemExit("nenhum raio acertou o modelo na caixa")
    janela = max(3, int(a.entorno / a.passo) // 2 * 2 + 1)
    vistas, fundos = [], []
    masc = np.zeros((nv, nu), bool)
    for tex in texs:
        vista = tex[acerto[..., 1].clip(0), acerto[..., 0].clip(0)] * ok[..., None].astype(np.uint8)
        fundo = np.asarray(Image.fromarray(vista).filter(ImageFilter.MedianFilter(janela))).astype(np.float32)
        masc |= (np.abs(vista.astype(np.float32) - fundo).max(axis=2) / 255 > a.limiar) & ok
        vistas.append(vista); fundos.append(fundo)
    masc = np.asarray(Image.fromarray((masc * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    masc &= ok
    # repinta pela malha, não pelo raio: rasteriza na textura cada triângulo da caixa virado para --normal e troca os
    # texels cuja posição 3D cai num ponto da máscara. Pega também as faces duplicadas (camadas coincidentes com outra
    # UV), que o raio não vê mas a renderização mostra.
    pintados = 0
    for t in tris:
        p = [verts[k] for k in t.vertices]
        c = (p[0] + p[1] + p[2]) / 3
        if not all(lo[k] - 0.01 <= c[k] <= hi[k] + 0.01 for k in range(3)): continue
        nrm = (p[1] - p[0]).cross(p[2] - p[0])
        if nrm.length == 0 or nrm[prof] * sinal / nrm.length < 0.3: continue
        q = [(uvd[l].uv.x * w, (1 - uvd[l].uv.y) * h) for l in t.loops]
        x0 = max(0, int(min(e[0] for e in q))); x1 = min(w - 1, int(max(e[0] for e in q)) + 1)
        y0 = max(0, int(min(e[1] for e in q))); y1 = min(h - 1, int(max(e[1] for e in q)) + 1)
        den = (q[1][1] - q[2][1]) * (q[0][0] - q[2][0]) + (q[2][0] - q[1][0]) * (q[0][1] - q[2][1])
        if abs(den) < 1e-9: continue
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                px, py = tx + 0.5, ty + 0.5
                l0 = ((q[1][1] - q[2][1]) * (px - q[2][0]) + (q[2][0] - q[1][0]) * (py - q[2][1])) / den
                l1 = ((q[2][1] - q[0][1]) * (px - q[2][0]) + (q[0][0] - q[2][0]) * (py - q[2][1])) / den
                l2 = 1 - l0 - l1
                if min(l0, l1, l2) < -0.02: continue
                pos = p[0] * l0 + p[1] * l1 + p[2] * l2
                i = int(round((pos[ua] - lo[ua]) / a.passo)); j = int(round((pos[va] - lo[va]) / a.passo))
                if 0 <= i < nu and 0 <= j < nv and masc[j, i]:
                    for tex, fundo in zip(texs, fundos):
                        tex[ty, tx] = fundo[j, i].astype(np.uint8)
                    pintados += 1
    if a.previa:
        linhas = []
        for vista, fundo in zip(vistas, fundos):
            depois = np.where(masc[..., None], fundo.astype(np.uint8), vista)
            linhas.append(np.concatenate([vista, np.zeros((nv, 4, 3), np.uint8), depois], axis=1)[::-1])
            linhas.append(np.zeros((4, nu * 2 + 4, 3), np.uint8))
        Image.fromarray(np.concatenate(linhas, axis=0)).save(a.previa)
    # imagens novas no lugar das embutidas (recarregar a embutida devolveria a original)
    for k, (n, tex) in enumerate(zip(nos, texs)):
        saida_png = os.path.join(pasta, f"t{k}_limpa.png")
        Image.fromarray(tex).save(saida_png)
        nova = bpy.data.images.load(saida_png); nova.colorspace_settings.name = n.image.colorspace_settings.name; nova.pack()
        n.image = nova
    bpy.ops.export_scene.gltf(filepath=a.saida, export_format="GLB", export_apply=True)
    print(f"apagado: {int(masc.sum())} pontos de {int(ok.sum())} acertos ({nu}x{nv} raios), {pintados} texels em {len(nos)} texturas; exportado {a.saida}")

main()
