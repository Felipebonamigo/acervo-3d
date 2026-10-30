"""
Grade própria no lugar da grade do modelo (Lambari, 30/10/2026): a grade de barras do carro real é detalhe de assinatura, e a ficha e o
CLAUDE.md do Detonauto mandam trocá-la. Apaga, na peça `grille`, na carroceria e no para-choque da frente, toda face de cromo, cromado, chassi ou luz com o
centro dentro da caixa da grade (o corte deixava parte das barras na carroceria) e faz na peça `grille`:

- moldura cromada de 1,2 cm na boca, com 1,5 cm de fundo;
- fundo preto recuado (--fundo 0.05) com as paredes;
- colmeia preta de células largas (--colunas 9 --linhas 3), palhetas de 6 mm;
- uma barra cromada no meio, de ponta a ponta (--sem-barra tira).

    python -I ferramentas/grade_propria.py -- <corte>.glb <saida>.glb --caixa 1.70,1.83,-0.462,0.462,0.557,0.682 --xf 1.79

`--caixa` = x0,x1,y0,y1,z0,z1 do que sai (metros, espaço do corte); a boca da grade nova vai de y0 a y1 e de z0 a z1, com a face em
`--xf`. Materiais: `cromo` (no jogo MI_DNCromoCoupe) e `chassi`. Roda antes do assar_desgaste.py (a UV é refeita lá).
"""
import sys
import bpy
import bmesh
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
ent, sai = args[0], args[1]


def opt(name, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


X0, X1, Y0, Y1, Z0, Z1 = [float(v) for v in opt("--caixa", "1.70,1.83,-0.462,0.462,0.557,0.682").split(",")]
XF = opt("--xf", 1.79)
FUNDO = opt("--fundo", 0.05)
COLS, LINS = opt("--colunas", 9), opt("--linhas", 3)
SAEM = ("cromo", "cromado", "chassi", "luz")
FOLGA_Y = opt("--folga-y", 0.013)   # o que sai vai 1,3 cm além da boca nas pontas (sobrava a ponta cromada da grade antiga)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = {o.name: o for o in bpy.data.objects if o.type == "MESH"}
g = objs["grille"]


def nomes(o):
    return [s.material.name.split(".")[0] if s.material else "" for s in o.material_slots]


def slot(o, nome):
    ns = nomes(o)
    if nome in ns:
        return ns.index(nome)
    m = bpy.data.materials.get(nome) or bpy.data.materials.new(nome)
    o.data.materials.append(m)
    return len(o.data.materials) - 1


# cores de prévia do cromo, se o material veio sem (o jogo usa as suas)
if "cromo" not in [m.name.split(".")[0] for m in bpy.data.materials]:
    m = bpy.data.materials.new("cromo")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.8, 0.8, 0.82, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.15

# 1. sai a grade do modelo (na peça e na carroceria)
tirou = {}
for n in ("grille", "body", "bumper_front"):   # o corte pôs a barra de baixo da grade antiga no para-choque
    o = objs.get(n)
    if not o:
        continue
    ns = nomes(o)
    mw = o.matrix_world
    bm = bmesh.new()
    bm.from_mesh(o.data)
    fora = [f for f in bm.faces if f.material_index < len(ns) and ns[f.material_index] in SAEM and
            (lambda c: X0 <= c.x <= X1 and Y0 - FOLGA_Y <= c.y <= Y1 + FOLGA_Y and Z0 <= c.z <= Z1)(mw @ f.calc_center_median())]
    bmesh.ops.delete(bm, geom=fora, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    tirou[n] = len(fora)

# 2. a grade nova, na peça grille (no espaço do mundo: o pivô da peça pode não ser a origem)
mi_c, mi_p = slot(g, "cromo"), slot(g, "chassi")
inv = g.matrix_world.inverted()
bm = bmesh.new()
bm.from_mesh(g.data)
novas = []


def quad(pts, mi, ref):
    vs = [bm.verts.new(inv @ Vector(p)) for p in pts]
    f = bm.faces.new(vs)
    f.material_index = mi
    f.normal_update()
    c = sum((Vector(p) for p in pts), Vector()) / len(pts)
    if (g.matrix_world.to_3x3() @ f.normal).dot(c - ref) < 0:
        f.normal_flip()
    novas.append(f)


def caixa(c, dx, dy, dz, mi):
    x, y, z = c
    p = [(x + sx * dx / 2, y + sy * dy / 2, z + sz * dz / 2) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    for q in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        quad([p[i] for i in q], mi, Vector(c))


e, prof_mold = 0.012, 0.015
yc, zc = 0.5 * (Y0 + Y1), 0.5 * (Z0 + Z1)
atras = Vector((XF - 1.0, yc, zc))
# moldura: perfil abaulado (borda de fora, crista e borda de dentro, sombreado liso) e o lado de fora dele para trás. Chata, ela
# refletia o céu por igual e lia cinza acetinado ao lado do para-choque (30/10); a curva pega o reflexo como cromo de verdade
PERFIL = [(-0.004, 0.0), (0.0, 0.3 * e), (0.0, 0.55 * e), (-0.003, 0.85 * e), (-0.006, e)]   # (recuo em x, entrada na boca)
aneis = []
for dx, off in PERFIL:
    pts = [(XF + dx, Y0 + off, Z0 + off), (XF + dx, Y1 - off, Z0 + off), (XF + dx, Y1 - off, Z1 - off), (XF + dx, Y0 + off, Z1 - off)]
    aneis.append([bm.verts.new(inv @ Vector(p)) for p in pts])
curvas = []
for r in range(len(aneis) - 1):
    for k in range(4):
        vs = [aneis[r][k], aneis[r][(k + 1) % 4], aneis[r + 1][(k + 1) % 4], aneis[r + 1][k]]
        f = bm.faces.new(vs)
        f.material_index = mi_c
        f.normal_update()
        c = g.matrix_world @ f.calc_center_median()
        if (g.matrix_world.to_3x3() @ f.normal).dot(c - atras) < 0:
            f.normal_flip()
        f.smooth = True
        curvas.append(f)
x_ext = XF + PERFIL[0][0]
ext = [(x_ext, Y0, Z0), (x_ext, Y1, Z0), (x_ext, Y1, Z1), (x_ext, Y0, Z1)]
for k in range(4):
    a, b = ext[k], ext[(k + 1) % 4]
    quad([a, b, (b[0] - prof_mold, b[1], b[2]), (a[0] - prof_mold, a[1], a[2])], mi_c, Vector((XF - prof_mold / 2, yc, zc)))
# fundo recuado e paredes (pretos)
xb = XF - FUNDO
iy0, iy1, iz0, iz1 = Y0 + e, Y1 - e, Z0 + e, Z1 - e
centro_fundo = Vector((XF - FUNDO / 2, yc, zc))
for a, b in (((iy0, iz0), (iy1, iz0)), ((iy1, iz0), (iy1, iz1)), ((iy1, iz1), (iy0, iz1)), ((iy0, iz1), (iy0, iz0))):
    quad([(XF, a[0], a[1]), (XF, b[0], b[1]), (xb, b[0], b[1]), (xb, a[0], a[1])], mi_p, centro_fundo)
quad([(xb, iy0, iz0), (xb, iy1, iz0), (xb, iy1, iz1), (xb, iy0, iz1)], mi_p, Vector((xb + 1.0, yc, zc)))
# colmeia: palhetas verticais e horizontais pretas, 3 cm de fundo, 6 mm de espessura, face 4 mm atrás da moldura
pf, pe = 0.03, 0.006
xp = XF - 0.004 - pf / 2
for k in range(1, COLS):
    caixa((xp, iy0 + (iy1 - iy0) * k / COLS, zc), pf, pe, iz1 - iz0, mi_p)
for k in range(1, LINS):
    caixa((xp, yc, iz0 + (iz1 - iz0) * k / LINS), pf, iy1 - iy0, pe, mi_p)
# barra cromada do meio, um pouco à frente da colmeia
if "--sem-barra" not in args:
    # perfil abaulado como o da moldura (chata, lia cinza fosco), com as pontas fechadas
    hb = 0.014
    perfil = [(-0.012, -hb / 2), (-0.004, -hb / 2), (0.0, -hb / 4), (0.0, hb / 4), (-0.004, hb / 2), (-0.012, hb / 2)]
    fila = {}
    for lado, yy in (("a", iy0), ("b", iy1)):
        fila[lado] = [bm.verts.new(inv @ Vector((XF + dx, yy, zc + dz))) for dx, dz in perfil]
    for i in range(len(perfil) - 1):
        f = bm.faces.new([fila["a"][i], fila["b"][i], fila["b"][i + 1], fila["a"][i + 1]])
        f.material_index = mi_c
        f.normal_update()
        c = g.matrix_world @ f.calc_center_median()
        if (g.matrix_world.to_3x3() @ f.normal).dot(c - Vector((XF - 0.02, yc, zc))) < 0:
            f.normal_flip()
        f.smooth = 0 < i < len(perfil) - 2
        curvas.append(f)
    for lado, sinal in (("a", -1), ("b", 1)):
        f = bm.faces.new(fila[lado])
        f.material_index = mi_c
        f.normal_update()
        if (g.matrix_world.to_3x3() @ f.normal).y * sinal < 0:
            f.normal_flip()
        curvas.append(f)
bm.to_mesh(g.data)
bm.free()
me = g.data
# normais: a peça inteira por ângulo (a grade nova é de caixas; as normais guardadas do corte eram da grade antiga)
if "custom_normal" in me.attributes:
    me.attributes.remove(me.attributes["custom_normal"])
lisas = set()
for p in me.polygons:
    if p.use_smooth and p.material_index == mi_c and p.index >= len(me.polygons) - len(novas) - len(curvas):
        lisas.add(p.index)
for p in me.polygons:
    p.use_smooth = p.index in lisas
me.update()
bpy.ops.export_scene.gltf(filepath=sai, export_format="GLB", export_image_format="AUTO")
print("[grade_propria] faces da grade do modelo tiradas: %s; grade nova %.0f x %.0f cm, %d x %d células%s, face em x = %.3f" % (
    tirou, (Y1 - Y0) * 100, (Z1 - Z0) * 100, COLS, LINS, "" if "--sem-barra" in args else ", barra cromada no meio", XF))
