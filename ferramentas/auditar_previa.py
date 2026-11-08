"""
Prévia da auditoria (08/11/2026): o carro do corte quebrável mais o kit completo em 6 ângulos, em Cycles, com os buracos descobertos que a
auditar_carro.py achou marcados por esferas vermelhas (o tamanho é o do buraco) e as peças com arestas invertidas pintadas de magenta.
As rodas originais saem (o jogo usa as de kit) e ficam cilindros cinza no lugar, só para a silhueta.

    python -I ferramentas/auditar_previa.py -- <carro.glb> <completo.glb> <auditoria.json> <pasta de saída> [--amostras 24] [--largura 960]
        [--um-lado] [--sufixo -antes] [--luzes]

--um-lado: as faces de costas para a câmera ficam transparentes, como no Unreal (a pintura de um lado só): a face invertida aparece como
buraco, do jeito que o jogador vê.

Saída: <pasta>/<id>-<vista>.png (frente, tras, lado, tres-quartos-frente, tres-quartos-tras, alto) e <id>-folha.png com as 6.
"""
import bpy
import json
import math
import os
import sys
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
corte, kit, aud_path, pasta = argv[:4]
AMOSTRAS = int(argv[argv.index('--amostras') + 1]) if '--amostras' in argv else 24
LARGURA = int(argv[argv.index('--largura') + 1]) if '--largura' in argv else 960
UM_LADO = '--um-lado' in argv
SUFIXO = argv[argv.index('--sufixo') + 1] if '--sufixo' in argv else ''
aud = json.load(open(aud_path)) if os.path.exists(aud_path) else {'carro': os.path.basename(os.path.normpath(corte)), 'pecas': []}
CID = aud['carro']
os.makedirs(pasta, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
cena = bpy.context.scene


def imp(f):
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=f)
    return [o for o in bpy.data.objects if o not in antes]


def imp_fbx_pasta(pasta_fbx):
    antes = set(bpy.data.objects)
    for f in sorted(os.listdir(pasta_fbx)):
        if f.lower().endswith('.fbx') and '_lod1' not in f.lower():
            bpy.ops.import_scene.fbx(filepath=os.path.join(pasta_fbx, f))
    novos = [o for o in bpy.data.objects if o not in antes]
    for o in novos:
        if o.type == 'ARMATURE':
            o.hide_render = True
    return [o for o in novos if o.type == 'MESH']


# o carro como o jogo recebe (as pastas pecas/ e kit/ da cadeia do montar-cuiabano-completo.ps1, em FBX) ou o corte do acervo (GLB)
carro = imp_fbx_pasta(corte) if os.path.isdir(corte) else imp(corte)
pecas_corte = {o.name for o in carro}
if kit and os.path.isdir(kit):
    imp_fbx_pasta(kit)
elif kit and os.path.exists(kit):
    imp(kit)
for o in list(bpy.data.objects):
    if o.name.endswith('_LOD1') or o.name.startswith(('wheel_', 'hubcap_')):
        bpy.data.objects.remove(o)

# um lado só: cada material do carro mistura com transparente onde a face está de costas (o Backfacing da Geometria)
if UM_LADO:
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        saida_no = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if not saida_no or not saida_no.inputs['Surface'].links:
            continue
        origem = saida_no.inputs['Surface'].links[0].from_socket
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        transp = nt.nodes.new('ShaderNodeBsdfTransparent')
        mix = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(geo.outputs['Backfacing'], mix.inputs['Fac'])
        nt.links.new(origem, mix.inputs[1])
        nt.links.new(transp.outputs['BSDF'], mix.inputs[2])
        nt.links.new(mix.outputs['Shader'], saida_no.inputs['Surface'])

# marcas: magenta nas peças com arestas invertidas, esferas vermelhas nos buracos descobertos
magenta = bpy.data.materials.new('aud_invertida')
magenta.use_nodes = True
magenta.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (1, 0, 1, 1)
vermelho = bpy.data.materials.new('aud_buraco')
vermelho.use_nodes = True
bsdf = vermelho.node_tree.nodes['Principled BSDF']
bsdf.inputs['Base Color'].default_value = (1, 0, 0, 1)
bsdf.inputs['Emission Color'].default_value = (1, 0, 0, 1)
bsdf.inputs['Emission Strength'].default_value = 3.0
n_buracos = 0
for p in aud['pecas']:
    o = bpy.data.objects.get(p['nome'])
    if o and p['arestas_invertidas'] >= 20:
        for s in o.material_slots:
            s.material = magenta
    for b in p['buracos']:
        r = min(0.03, max(0.012, math.sqrt(b["area_cm2"] / math.pi) / 100.0))  # pequena: a esfera grande escondia o próprio buraco
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=b['centro_m'], segments=12, ring_count=8)
        bpy.context.object.data.materials.append(vermelho)
        n_buracos += 1

# caixa do carro para a câmera
mins = Vector((1e9, 1e9, 1e9))
maxs = Vector((-1e9, -1e9, -1e9))
for o in bpy.data.objects:
    if o.type == 'MESH' and o.name in pecas_corte:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mins = Vector(map(min, mins, w))
            maxs = Vector(map(max, maxs, w))
centro = (mins + maxs) / 2
tamanho = (maxs - mins).length

# chão, céu e sol
bpy.ops.mesh.primitive_plane_add(size=60, location=(centro.x, centro.y, mins.z - 0.005))
chao = bpy.data.materials.new('aud_chao')
chao.use_nodes = True
chao.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.35, 0.35, 0.35, 1)
bpy.context.object.data.materials.append(chao)
mundo = bpy.data.worlds.new('aud')
cena.world = mundo
mundo.use_nodes = True
mundo.node_tree.nodes['Background'].inputs['Color'].default_value = (0.75, 0.82, 0.95, 1)
mundo.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.9
bpy.ops.object.light_add(type='SUN', rotation=(math.radians(50), 0, math.radians(30)))
bpy.context.object.data.energy = 3.5

cena.render.engine = 'CYCLES'
cena.cycles.samples = AMOSTRAS
cena.cycles.use_denoising = True
cena.render.resolution_x = LARGURA
cena.render.resolution_y = LARGURA * 9 // 16
cena.view_settings.view_transform = 'AgX'
bpy.ops.object.camera_add()
cam = bpy.context.object
cena.camera = cam
cam.data.lens = 50

# +X é a frente (convenção do corte quebrável)
VISTAS = {
    'frente': (1, 0, 0.18),
    'tras': (-1, 0, 0.18),
    'lado': (0, -1, 0.12),
    'tres-quartos-frente': (0.75, -0.66, 0.3),
    'tres-quartos-tras': (-0.75, -0.66, 0.3),
    'alto': (0.2, -0.3, 1.0),
}
feitas = []
for nome, d in VISTAS.items():
    dirv = Vector(d).normalized()
    cam.location = centro + dirv * tamanho * 1.45
    cam.rotation_euler = (centro - cam.location).to_track_quat('-Z', 'Y').to_euler()
    saida = os.path.join(pasta, f'{CID}-{nome}{SUFIXO}.png')
    cena.render.filepath = saida
    bpy.ops.render.render(write_still=True)
    feitas.append(saida)
# --luzes: cada farol e lanterna a 1 m (a régua do Felipe: nenhum defeito visível a 1 m), de frente para a lente e um pouco de lado
if '--luzes' in argv:
    cam.data.lens = 50
    for o in [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith(('headlight', 'taillight'))]:
        cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
        meio = sum(cs, Vector()) / 8
        frente = Vector((1, 0, 0)) if o.name.startswith('headlight') else Vector((-1, 0, 0))
        lado = Vector((0, 1 if meio.y > 0 else -1, 0))
        cam.location = meio + (frente * 0.9 + lado * 0.35 + Vector((0, 0, 0.25))).normalized() * 1.0
        cam.rotation_euler = (meio - cam.location).to_track_quat('-Z', 'Y').to_euler()
        saida = os.path.join(pasta, f'{CID}-luz-{o.name}{SUFIXO}.png')
        cena.render.filepath = saida
        bpy.ops.render.render(write_still=True)
        feitas.append(saida)
print(f'PREVIA {CID}: {len(feitas)} vista(s), {n_buracos} buraco(s) marcado(s), em {pasta}')
