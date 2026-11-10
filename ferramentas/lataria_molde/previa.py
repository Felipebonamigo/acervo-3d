"""
Prévia em Cycles do ARQUIVO FINAL do carro (o GLB do corte), de UM LADO SÓ: a face de costas para a câmera fica transparente, como no
Unreal. Face invertida ou peça aberta aparece como buraco, do jeito que o jogador vê. Mesmas câmeras e mesma luz para qualquer carro,
para a folha "hoje x nova".

    blender-nuvem.sh ferramentas/lataria_molde/previa.py -- <carro.glb> <pasta> <prefixo> [--amostras 48] [--largura 1100] [--vistas geral,frente,traseira,roda]
"""
import bpy, math, os, sys
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
GLB, PASTA, PREFIXO = argv[:3]
opt = lambda n, d: argv[argv.index(n) + 1] if n in argv else d
AMOSTRAS = int(opt('--amostras', 48)); LARGURA = int(opt('--largura', 1100))
VISTAS = opt('--vistas', 'geral,frente,traseira,roda').split(',')
os.makedirs(PASTA, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
cena = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=GLB)
KIT = opt('--kit', None)                 # o kit completo (interior, cofre, embaixo), como o jogo monta
if KIT:
    bpy.ops.import_scene.gltf(filepath=KIT)
RODAS = opt('--rodas', None)             # aro,pneu,calota,raio,cubo_y,x_dianteiro,x_traseiro: troca as rodas do arquivo pelas de kit (as do jogo)
if RODAS:
    aro, pneu, calota, raio, cubo, xd, xt = RODAS.split(',')
    for o in [o for o in bpy.data.objects if o.name.startswith(('wheel_', 'hubcap_'))]:
        bpy.data.objects.remove(o)
    pasta_r = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'veiculos', 'proprios', 'rodas')
    for nome, xa, lado in (('fl', float(xd), 1), ('fr', float(xd), -1), ('rl', float(xt), 1), ('rr', float(xt), -1)):
        for arq, marca, final in ((aro, None, 'wheel_%s_rim'), (pneu, '_Ok', 'wheel_%s_tire'), (calota, None, 'hubcap_%s')):
            antes = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=os.path.join(pasta_r, arq + '.glb'))
            novos = [o for o in bpy.data.objects if o not in antes]
            alvo = next(o for o in novos if o.type == 'MESH' and not o.name.split('.')[0].endswith(('_LOD1', '_Flat', '_Torn')) and (marca is None or marca in o.name))
            for o in novos:
                if o is not alvo:
                    bpy.data.objects.remove(o)
            alvo.parent = None
            alvo.name = final % nome
            alvo.location = (xa, lado * float(cubo), float(raio))
            alvo.rotation_mode = 'XYZ'
            alvo.rotation_euler = (0, 0, 0 if lado > 0 else math.pi)
malhas = [o for o in bpy.data.objects if o.type == 'MESH' and not o.name.split('.')[0].endswith(('_LOD1', '_LOD2'))]
for o in bpy.data.objects:
    if o.type == 'MESH' and o not in malhas:
        o.hide_render = True

# acabamento por nome de material, para o arquivo sem textura (o do molde); o que traz textura fica como veio
PADRAO = {
    'pintura': dict(cor=(0.42, 0.012, 0.012), metal=0.0, asp=0.32, verniz=1.0),
    'chassi': dict(cor=(0.03, 0.03, 0.032), metal=0.0, asp=0.5),
    'borracha': dict(cor=(0.01, 0.01, 0.01), metal=0.0, asp=0.7),
    'MI_DNVao': dict(cor=(0.004, 0.004, 0.004), metal=0.0, asp=0.9),
    'cromo': dict(cor=(0.9, 0.9, 0.9), metal=1.0, asp=0.08),
    'cromado': dict(cor=(0.75, 0.75, 0.75), metal=1.0, asp=0.2),
    'refletor': dict(cor=(0.9, 0.9, 0.9), metal=1.0, asp=0.12),
    'pneu': dict(cor=(0.02, 0.02, 0.02), metal=0.0, asp=0.85),
    'placa': dict(cor=(0.8, 0.8, 0.8), metal=0.0, asp=0.4),
    'vidro': dict(cor=(0.75, 0.85, 0.82), vidro=True, asp=0.0, alfa=0.25),
    'lente_vidro': dict(cor=(1, 1, 1), vidro=True, asp=0.02, alfa=0.12),
    'lente_vermelha': dict(cor=(0.75, 0.01, 0.01), vidro=True, asp=0.05, alfa=0.75),
    'lente_ambar': dict(cor=(1.0, 0.35, 0.0), vidro=True, asp=0.05, alfa=0.75),
    'lente_branca': dict(cor=(0.95, 0.95, 0.95), vidro=True, asp=0.05, alfa=0.6),
    'interior': dict(cor=(0.03, 0.03, 0.035), metal=0.0, asp=0.8),
}


def refazer(mat, p):
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    b = nt.nodes.new('ShaderNodeBsdfPrincipled')
    b.inputs['Base Color'].default_value = (*p['cor'], 1)
    b.inputs['Roughness'].default_value = p['asp']
    b.inputs['Metallic'].default_value = p.get('metal', 0.0)
    if p.get('verniz'):
        b.inputs['Coat Weight'].default_value = 1.0
        b.inputs['Coat Roughness'].default_value = 0.03
    if p.get('vidro'):
        b.inputs['Alpha'].default_value = p['alfa']
        b.inputs['Roughness'].default_value = p['asp']
    nt.links.new(b.outputs[0], out.inputs[0])


def um_lado(mat):
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
    if not out or not out.inputs[0].links:
        return
    src = out.inputs[0].links[0].from_socket
    geo = nt.nodes.new('ShaderNodeNewGeometry'); tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(geo.outputs['Backfacing'], mix.inputs[0]); nt.links.new(src, mix.inputs[1]); nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs[0])


COR = opt('--pintura', None)             # r,g,b: a cor da tinta (para comparar dois carros na mesma cor)
if COR:
    PADRAO['pintura'] = dict(PADRAO['pintura'], cor=tuple(float(v) for v in COR.split(',')))
for mat in bpy.data.materials:
    nome = mat.name.split('.')[0]
    tem_tex = mat.use_nodes and any(n.type == 'TEX_IMAGE' for n in mat.node_tree.nodes)
    if nome in PADRAO and not tem_tex:
        refazer(mat, PADRAO[nome])
    if mat.use_nodes:
        um_lado(mat)

# chão, céu e sol: os mesmos para todo carro
bpy.ops.mesh.primitive_plane_add(size=60)
chao = bpy.context.object
mc = bpy.data.materials.new('chao'); mc.use_nodes = True
bs = mc.node_tree.nodes['Principled BSDF']; bs.inputs['Base Color'].default_value = (0.3, 0.3, 0.31, 1); bs.inputs['Roughness'].default_value = 0.6
chao.data.materials.append(mc)
mundo = bpy.data.worlds.new('m'); cena.world = mundo; mundo.use_nodes = True
nt = mundo.node_tree; nt.nodes.clear()
o = nt.nodes.new('ShaderNodeOutputWorld'); bg = nt.nodes.new('ShaderNodeBackground')
# estúdio claro: degradê do horizonte (claro) ao alto (um pouco mais escuro), igual para todo carro
tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); rampa = nt.nodes.new('ShaderNodeValToRGB')
rampa.color_ramp.elements[0].position = 0.0; rampa.color_ramp.elements[0].color = (0.85, 0.86, 0.88, 1)
rampa.color_ramp.elements[1].position = 0.6; rampa.color_ramp.elements[1].color = (0.42, 0.47, 0.55, 1)
nt.links.new(tc.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['Z'], rampa.inputs[0])
bg.inputs[1].default_value = 0.6
nt.links.new(rampa.outputs[0], bg.inputs[0]); nt.links.new(bg.outputs[0], o.inputs[0])
sol = bpy.data.lights.new('sol', 'SUN'); sol.energy = 2.4; sol.angle = math.radians(3)
so = bpy.data.objects.new('sol', sol); cena.collection.objects.link(so)
so.rotation_euler = (math.radians(52), 0, math.radians(125))
# uma faixa de luz comprida no alto, para o reflexo correr na lataria e mostrar a faceta
fx = bpy.data.lights.new('faixa', 'AREA'); fx.shape = 'RECTANGLE'; fx.size = 9; fx.size_y = 0.5; fx.energy = 500
fo = bpy.data.objects.new('faixa', fx); cena.collection.objects.link(fo); fo.location = (0, 3.5, 3.2)
fo.rotation_euler = (math.radians(-45), 0, 0)

cena.render.engine = 'CYCLES'
cena.cycles.samples = AMOSTRAS
cena.cycles.use_denoising = True
cena.cycles.max_bounces = 6; cena.cycles.transparent_max_bounces = 12
cena.render.resolution_x = LARGURA; cena.render.resolution_y = int(LARGURA * 9 / 16)
for vt in ('Khronos PBR Neutral', 'Standard'):
    try:
        cena.view_settings.view_transform = vt
        break
    except Exception:
        pass
cena.render.image_settings.file_format = 'JPEG'; cena.render.image_settings.quality = 92

cam = bpy.data.cameras.new('c'); co = bpy.data.objects.new('c', cam); cena.collection.objects.link(co); cena.camera = co
# eixo dianteiro medido das rodas, se houver; senão, do tamanho
xs = [v for ob in malhas for v in (ob.matrix_world @ Vector(c) for c in ob.bound_box)]
x0, x1 = min(v.x for v in xs), max(v.x for v in xs)
rodas = [ob for ob in malhas if ob.name.startswith('wheel_fl')]
if rodas:
    cs = [ob.matrix_world @ Vector(c) for ob in rodas for c in ob.bound_box]
    rx = (min(c.x for c in cs) + max(c.x for c in cs)) / 2; ry = max(c.y for c in cs); rz = max(c.z for c in cs) / 2
else:
    rx, ry, rz = x1 - 0.72, 0.75, 0.3
CAMS = {
    'geral': ((4.3, 3.3, 1.55), (0.0, 0.0, 0.62), 55),
    'frente': ((x1 + 3.2, 0.9, 0.95), (x1 - 0.2, 0.0, 0.62), 50),
    'traseira': ((x0 - 3.0, 1.5, 1.05), (x0 + 0.2, 0.0, 0.68), 50),
    'roda': ((rx + 0.35, ry + 1.0, 0.62), (rx, ry, rz + 0.08), 30),
    'lado': ((0.0, 7.0, 0.9), (0.0, 0.0, 0.68), 70),
    'alto': ((2.6, 2.2, 3.6), (0.0, 0.0, 0.6), 50),
    'tq_tras': ((-4.1, 3.2, 1.6), (0.0, 0.0, 0.62), 55),
    'farol': ((x1 + 0.9, 1.0, 0.85), (x1 - 0.05, 0.5, 0.62), 40),
    'lanterna': ((x0 - 0.9, 1.0, 0.9), (x0 + 0.05, 0.5, 0.68), 40),
    'porta': ((0.3, 2.2, 1.15), (0.1, 0.7, 0.85), 40),
    'grade': ((x1 + 1.0, 0.35, 0.8), (x1, 0.25, 0.62), 40),
    'saia': ((x1 + 1.1, 1.0, 0.3), (x1 - 0.05, 0.52, 0.3), 45),
    'capo': ((x1 + 0.6, 0.0, 1.6), (x1 - 0.6, 0.0, 0.85), 40),
    'canto': ((1.5, 1.5, 1.25), (0.72, 0.62, 0.92), 60),
}
for v in VISTAS:
    pos, alvo, lente = CAMS[v]
    co.location = pos
    d = Vector(alvo) - Vector(pos)
    co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    cam.lens = lente
    cena.render.filepath = os.path.join(PASTA, '%s-%s.jpg' % (PREFIXO, v))
    bpy.ops.render.render(write_still=True)
    print('previa:', cena.render.filepath)
