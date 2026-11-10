"""
Mede o modelo-régua (o corte de hoje) por raios e imprime as cotas que a ficha do molde usa. O modelo só serve de régua: daqui saem
números (em cm, arredondados), nenhuma geometria.

    blender-nuvem.sh ferramentas/lataria_molde/medir_regua.py -- <corte.glb>
"""
import bpy, sys, bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree

glb = sys.argv[sys.argv.index('--') + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
FORA = ('wheel_', 'hubcap_', 'mirror_', 'plate_')
bm = bmesh.new()
for o in bpy.data.objects:
    if o.type == 'MESH' and not o.name.startswith(FORA):
        t = bmesh.new(); t.from_mesh(o.data); t.transform(o.matrix_world)
        me = bpy.data.meshes.new('t'); t.to_mesh(me); bm.from_mesh(me); t.free()
tree = BVHTree.FromBMesh(bm)


def raio(o, d):
    h = tree.ray_cast(Vector(o), Vector(d))
    return h[0]


f = lambda v: '  -  ' if v is None else '%5.1f' % (v * 100)
print('PERFIL DO MEIO (y=0 e y=30): z do topo e z de baixo por x')
for x in [i / 10 for i in range(-19, 20)]:
    a = raio((x, 0.0, 3), (0, 0, -1)); b = raio((x, 0.30, 3), (0, 0, -1)); c = raio((x, 0.55, 3), (0, 0, -1)); d = raio((x, 0.2, -1), (0, 0, 1))
    print('x=%5.0f  z0=%s z30=%s z55=%s  baixo=%s' % (x * 100, f(a and a.z), f(b and b.z), f(c and c.z), f(d and d.z)))
print('LARGURA (meia) por x, em várias alturas z')
zs = [0.30, 0.45, 0.60, 0.75, 0.88, 1.00, 1.10, 1.20, 1.28]
print('x     ' + ' '.join('z%3d ' % (z * 100) for z in zs))
for x in [i / 10 for i in range(-18, 20)]:
    print('%5.0f ' % (x * 100) + ' '.join(f((lambda h: h and h.y)(raio((x, 3, z), (0, -1, 0)))) for z in zs))
print('FRENTE: x por y, em várias alturas')
ys = [0.0, 0.2, 0.4, 0.55, 0.65, 0.70]
for z in [0.30, 0.40, 0.50, 0.58, 0.65, 0.72, 0.78, 0.85]:
    print('z=%3d ' % (z * 100) + ' '.join(f((lambda h: h and h.x)(raio((4, y, z), (-1, 0, 0)))) for y in ys))
print('TRASEIRA: x por y, em várias alturas')
for z in [0.30, 0.40, 0.50, 0.58, 0.65, 0.72, 0.80, 0.90, 1.00, 1.10, 1.20, 1.28]:
    print('z=%3d ' % (z * 100) + ' '.join(f((lambda h: h and h.x)(raio((-4, y, z), (1, 0, 0)))) for y in ys))
