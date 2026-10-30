"""
Placas em branco para um corte que não tem placa (o Lambari do Sketchfab, 30/10/2026: o modelo vem sem nenhuma). Cria as peças
`plate_front` e `plate_rear` (o kit_names.py do Detonauto deixa a placa modelada como veio, material `placa`): placa brasileira de
40 x 13 cm em branco, sem letras (placa real é proibida), sobre um suporte preto encostado na chapa, com moldura de 1 cm e dois
parafusos. A altura de cada uma é opção; a posição em x sai de raios na chapa em volta (a placa fica 0,8 cm à frente do ponto mais
saliente atrás dela). O detalhes_na_casca.py refaz a placa de um corte que já tem a peça (o Gol Quadrado); este não mexe nele.

    python -I ferramentas/placa_na_casca.py -- <corte>.glb <saida>.glb [--z-frente 0.335] [--z-tras 0.345] [--sem-frente] [--sem-tras]
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


L, A = 0.40, 0.13
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}


def material(nome, cor, rug):
    m = bpy.data.materials.get(nome)
    if m is None:
        m = bpy.data.materials.new(nome)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (*cor, 1)
        b.inputs["Roughness"].default_value = rug
    return m


m_preto = material("chassi", (0.025, 0.025, 0.028), 0.8)
m_placa = material("placa", (0.85, 0.85, 0.83), 0.35)

# chapa onde a placa encosta: a carroceria (o para-choque logo acima puxava a placa 15 cm para fora)
todos = bmesh.new()
for n in ("body",):
    if n in objs:
        b = bmesh.new()
        b.from_mesh(objs[n].data)
        b.transform(objs[n].matrix_world)
        tmp = bpy.data.meshes.new("tmp")
        b.to_mesh(tmp)
        todos.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
        b.free()
bvh = BVHTree.FromBMesh(todos)


def caixa(bm, c, dx, dy, dz, mi):
    vs = [bm.verts.new((c[0] + sx * dx / 2, c[1] + sy * dy / 2, c[2] + sz * dz / 2)) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        f = bm.faces.new([vs[i] for i in q])
        f.material_index = mi
    return vs


def placa(nome, sinal, z0):
    z1 = z0 + A
    xs = []
    for yy in np.linspace(-0.22, 0.22, 9):
        for zz in np.linspace(z0 + 0.01, z1 - 0.01, 8):
            h = bvh.ray_cast(Vector((sinal * 3.0, yy, zz)), Vector((-sinal, 0, 0)), 4.0)
            if h[0] is not None:
                xs.append(h[0].x)
    if not xs:
        print("[placa_na_casca] %s: nenhuma chapa atrás da placa" % nome)
        return
    # a placa 0,8 cm à frente do ponto mais saliente da chapa atrás dela; o suporte vai até 3 cm atrás da placa, não
    # até o fundo de uma abertura (no Lambari o fundo das entradas de ar ficava 8 cm atrás e o suporte saía um bloco preto de lado)
    x_fora = max(xs) if sinal > 0 else min(xs)
    xp = x_fora + sinal * 0.008
    x_atras = xp - sinal * 0.03
    me = bpy.data.meshes.new(nome)
    me.materials.append(m_preto)
    me.materials.append(m_placa)
    bm = bmesh.new()
    zc = 0.5 * (z0 + z1)
    # suporte preto da chapa até a placa
    xa, xb = x_atras - sinal * 0.005, xp - sinal * 0.003
    caixa(bm, ((xa + xb) / 2, 0.0, zc), abs(xb - xa), L + 0.01, A + 0.01, 0)
    # a placa: chapa de 3 mm em branco
    caixa(bm, (xp - sinal * 0.0015, 0.0, zc), 0.003, L, A, 1)
    # moldura de 1 cm e dois parafusos
    xf, e = xp + sinal * 0.001, 0.010
    y0, y1 = -L / 2, L / 2
    ext = [(xf, y0 - 0.003, z0 - 0.003), (xf, y1 + 0.003, z0 - 0.003), (xf, y1 + 0.003, z1 + 0.003), (xf, y0 - 0.003, z1 + 0.003)]
    inn = [(xf, y0 + e, z0 + e), (xf, y1 - e, z0 + e), (xf, y1 - e, z1 - e), (xf, y0 + e, z1 - e)]
    for k in range(4):
        bm.faces.new([bm.verts.new(p) for p in (ext[k], ext[(k + 1) % 4], inn[(k + 1) % 4], inn[k])]).material_index = 0
    for yy in (y0 + 0.25 * L, y0 + 0.75 * L):
        caixa(bm, (xf + sinal * 0.002, yy, z1 - 0.022), 0.004, 0.012, 0.012, 0)
    # tudo virado para fora da placa (centro atrás dela)
    ref = Vector((xp - sinal * 1.0, 0.0, zc))
    bm.normal_update()
    for f in bm.faces:
        if (f.calc_center_median() - ref).dot(f.normal) < 0:
            f.normal_flip()
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    o = bpy.data.objects.new(nome, me)
    bpy.context.scene.collection.objects.link(o)
    print("[placa_na_casca] %s: placa %.0f x %.0f cm em z %.3f-%.3f, x %.3f (%.1f cm de suporte)" % (
        nome, 100 * L, 100 * A, z0, z1, xp, 100 * abs(xp - x_atras)))


for nome, sinal, chave, z in (("plate_front", 1, "--sem-frente", opt("--z-frente", 0.335)), ("plate_rear", -1, "--sem-tras", opt("--z-tras", 0.345))):
    if chave in args:
        continue
    if nome in objs:
        print("[placa_na_casca] %s já existe no corte: fica como está" % nome)
        continue
    placa(nome, sinal, z)
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
