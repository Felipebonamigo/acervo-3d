"""Apaga letreiro, logo ou texto que o gerador de IA pintou na textura de um modelo (regra do estúdio: nenhum texto de marca).

Roda no Blender (ou com o módulo bpy, numpy e Pillow):
  blender -b -P ferramentas/apagar_letreiro.py -- --entrada carro.glb --saida carro.glb --caixa x0,x1,y0,y1,z0,z1
          [--normal +z] [--passo 0.002] [--limiar 0.08] [--previa antes_depois.png]

--caixa: a região do modelo em metros (eixos do arquivo) onde está o letreiro, por exemplo o capô junto ao para-brisa.
--normal: de que lado se olha a região (+z = de cima, +x = de frente...).

Como as UVs do Meshy espalham uma mesma superfície pela textura inteira, o script não trabalha na textura direto: lança
raios do lado de --normal sobre a caixa, num passo de --passo metros, e monta uma imagem "vista de fora" da pintura. Nessa
imagem acha o que difere da cor do entorno (mediana de uns 6 cm) por mais de --limiar, e repinta só os texels que esses
raios acertaram com a cor do entorno. Sujeira grande e sombra suave ficam; traço fino de letra some. Com --previa, salva a
vista de fora antes e depois, uma em cima da outra, para conferir.
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
    no_img = me.materials[0].node_tree.nodes["Principled BSDF"].inputs["Base Color"].links[0].from_node
    img = no_img.image
    w, h = img.size
    tmp = os.path.join(tempfile.mkdtemp(), "cor.png")
    img.filepath_raw = tmp; img.file_format = "PNG"; img.save()
    tex = np.asarray(Image.open(tmp).convert("RGB")).copy()

    nu = int((hi[ua] - lo[ua]) / a.passo) + 1; nv = int((hi[va] - lo[va]) / a.passo) + 1
    vista = np.zeros((nv, nu, 3), np.uint8); acerto = np.full((nv, nu, 2), -1, np.int32)
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
            tx = min(w - 1, max(0, int(uv.x * w))); ty = min(h - 1, max(0, int((1 - uv.y) * h)))
            vista[j, i] = tex[ty, tx]; acerto[j, i] = (tx, ty)
    ok = acerto[..., 0] >= 0
    if not ok.any(): raise SystemExit("nenhum raio acertou o modelo na caixa")
    raio = max(3, int(0.06 / a.passo) // 2 * 2 + 1)
    fundo = np.asarray(Image.fromarray(vista).filter(ImageFilter.MedianFilter(min(raio, 61)))).astype(np.float32)
    dif = np.abs(vista.astype(np.float32) - fundo).max(axis=2) / 255
    masc = (dif > a.limiar) & ok
    masc = np.asarray(Image.fromarray((masc * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(7))) > 0
    masc &= ok
    for j, i in zip(*np.nonzero(masc)):
        tx, ty = acerto[j, i]
        tex[max(0, ty - 1):ty + 2, max(0, tx - 1):tx + 2] = fundo[j, i].astype(np.uint8)
    if a.previa:
        depois = np.where(masc[..., None], fundo.astype(np.uint8), vista)
        lado = np.concatenate([vista, np.zeros((4, nu, 3), np.uint8), depois], axis=0)[::-1]
        Image.fromarray(lado).save(a.previa)
    # imagem nova no lugar da embutida (recarregar a embutida devolveria a original)
    saida_png = os.path.join(os.path.dirname(tmp), img.name.replace("/", "_") + "_limpa.png")
    Image.fromarray(tex).save(saida_png)
    nova = bpy.data.images.load(saida_png); nova.colorspace_settings.name = img.colorspace_settings.name; nova.pack()
    no_img.image = nova
    bpy.ops.export_scene.gltf(filepath=a.saida, export_format="GLB", export_apply=True)
    print(f"apagado: {int(masc.sum())} pontos de {int(ok.sum())} acertos ({nu}x{nv} raios); exportado {a.saida}")

main()
