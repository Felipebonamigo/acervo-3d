"""Closes de um GLB limpo (frente em +X, chão em z=0): frente, traseira, 3/4 dianteiro e lado, numa tira PNG; com --perto, só
frente e traseira de perto, para procurar letreiro, emblema e placa. Cycles na CPU, ~12 s por modelo.
uso: python closes.py <entrada.glb> <saida.png> [largura] [--perto]   (com bpy e Pillow no Python)"""
import sys, math, bpy
from mathutils import Vector

ent, sai = sys.argv[1], sys.argv[2]
L = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 480
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=ent)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
mn = Vector((1e9,) * 3); mx = Vector((-1e9,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c); mn = Vector(map(min, mn, w)); mx = Vector(map(max, mx, w))
centro = (mn + mx) / 2; tam = max(mx - mn)
cena = bpy.context.scene
cena.render.engine = "CYCLES"; cena.cycles.samples = 24; cena.cycles.device = "CPU"
cena.render.resolution_x = L; cena.render.resolution_y = int(L * 0.75); cena.render.film_transparent = False
mundo = bpy.data.worlds.new("m"); cena.world = mundo; mundo.use_nodes = True
mundo.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.77, 0.8, 1); mundo.node_tree.nodes["Background"].inputs[1].default_value = 0.8
sol = bpy.data.objects.new("sol", bpy.data.lights.new("sol", "SUN")); sol.data.energy = 3
sol.rotation_euler = (math.radians(40), math.radians(15), math.radians(30)); cena.collection.objects.link(sol)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); cena.collection.objects.link(cam); cena.camera = cam
cam.data.lens = 50
vistas = {"frente": (1, 0, 0.25), "traseira": (-1, 0, 0.25), "3-4": (0.8, 0.7, 0.35), "lado": (0, 1, 0.12)}
if "--perto" in sys.argv:  # só frente e traseira, de perto (procurar letreiro e placa)
    vistas = {"frente": (1, 0, 0.12), "traseira": (-1, 0, 0.12)}
import tempfile, os
from PIL import Image
tiras = []
for nome, d in vistas.items():
    dirv = Vector(d).normalized()
    perto = (mx.x - mn.x) / 2 * abs(dirv.x) + max(mx.y - mn.y, mx.z - mn.z) * 2.4
    cam.location = centro + dirv * (perto if "--perto" in sys.argv else tam * 2.2)
    cam.rotation_euler = (centro - cam.location).to_track_quat("-Z", "Y").to_euler()
    f = os.path.join(tempfile.gettempdir(), f"close_{nome}.png"); cena.render.filepath = f
    bpy.ops.render.render(write_still=True); tiras.append(Image.open(f).convert("RGB"))
W = Image.new("RGB", (sum(t.width for t in tiras), tiras[0].height))
x = 0
for t in tiras: W.paste(t, (x, 0)); x += t.width
W.save(sai); print("closes:", sai, [round(v, 2) for v in (mx - mn)])
