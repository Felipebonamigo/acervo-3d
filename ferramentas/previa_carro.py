"""
Prévia de um carro do acervo como ele fica no Detonauto (29/10/2026): o corte quebrável + o kit completo + as rodas de kit, a pintura
como o jogo faz (a textura de desgaste x a cor de Data/Paints.csv, com o acabamento de Data/PaintFinishes.csv) e, com HDRI, uma rua de
verdade em volta para o verniz e o cromo terem o que refletir. Foi o script das prévias do Gol Quadrado (Cuiabano).

    ID=<id> CORTE=<pasta do corte>/ KIT=<pasta do kit>/ [HDRI=<rua.hdr> HDRI_ROT=270] [ACAB=solida|metalica|perolizada|fosca|acetinada]
    [CAM="x,y,z,alvo_x,alvo_y,alvo_z,lente"] [SEMKIT=1] [RODAS=aro_aco14,pneu_p185_60,calota14] [GLB=<outro glb no lugar do corte>] [DETONAUTO=<repo do Detonauto>]
    [ESCADA=veiculos/proprios/escada-aluminio.glb ESCADA_AVANCO=0.25]
    python -I ferramentas/previa_carro.py -- <saida.png> <textura da pintura (o _desgaste.png)> Ok <cor linear r,g,b> "" foto|tras|perto

A cor vai em linear (sRGB 172,22,20 -> 0.4125,0.0080,0.0070). HDRI usado nas prévias do Gol: "Wide Street 01" (Poly Haven, CC0),
https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/wide_street_01_2k.hdr, com HDRI_ROT=270 (lateral ao sol); fica fora do acervo.
Precisa do repositório do Detonauto ao lado (../detonauto, ou DETONAUTO=): usa o Tools/Blender/kit_to_detonauto.py e o Data/.
Rode no máximo 5 em paralelo (18 de uma vez estouraram a memória).
"""
import bpy, sys, json, math, bmesh
import os
DN = os.environ.get('DETONAUTO', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'detonauto'))
from mathutils import Vector
sys.path.insert(0, os.path.join(DN, 'Tools', 'Blender'))
import kit_to_detonauto as kd
A = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'veiculos')
import os
corte = os.environ.get('CORTE', A + '/meshy-conta/quebravel/hatch-quadrado-v2/')
kitd = os.environ.get('KIT', A + '/meshy-conta/completo/hatch-quadrado-v2/')
rod = A + '/proprios/rodas/'
out = sys.argv[sys.argv.index('--') + 1]
paint_png = sys.argv[sys.argv.index('--') + 2]
bpy.ops.wm.read_factory_settings(use_empty=True)
c = bpy.context.scene

def imp(f):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=f)
    return [o for o in bpy.data.objects if o not in before]

carro = imp(os.environ.get('GLB', corte + os.environ.get('ID','hatch-quadrado-v2') + '.glb'))
kit = [] if os.environ.get('SEMKIT') else [o for o in imp(kitd + os.environ.get('ID','hatch-quadrado-v2') + '_completo.glb') if not o.name.endswith('_LOD1')]
for o in list(bpy.data.objects):
    if o.name.endswith('_LOD1'): bpy.data.objects.remove(o)
# rodas do Meshy saem; vãos escuros e fundo da carroceria saem onde o kit entra
for o in list(carro):
    if o.name.startswith(('wheel_', 'hubcap_')):
        bpy.data.objects.remove(o); carro.remove(o)
kj = json.load(open(kitd + os.environ.get('ID','hatch-quadrado-v2') + '_completo.json'))
for o in carro:
    if o.type != 'MESH': continue
    o.data.transform(o.matrix_world); o.matrix_world.identity()
    if not os.environ.get('SIMPLES'): n = kd.drop_kit_bays(o, kj, o.name == 'body')
if not os.environ.get('SIMPLES'):
    pm_ = bpy.data.materials.get('pintura'); pm_.name = 'MI_DNPinturaCuiabano'
    print('FRISO', kd.paint_borders_to_body('Cuiabano', None))
    pm_.name = 'pintura'
    carro = [o for o in bpy.data.objects if o.type == 'MESH']
    body = [o for o in carro if o.name == 'body'][0]
    print('INTERNAS', kd.drop_faces(body, kd.hidden_paint_faces(body, [o for o in carro if o.type == 'MESH'], kj)))
# rodas de kit: aço 13 + 175/70 + calota
mapa = json.load(open(corte + os.environ.get('ID','hatch-quadrado-v2') + '_mapa.json'))
def rodaglb(nome, obj):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=rod + nome + '.glb')
    new = [o for o in bpy.data.objects if o not in before]
    keep = [o for o in new if o.name.split('.')[0] == obj]
    for o in new:
        if o not in keep and o.type == 'MESH': bpy.data.objects.remove(o)
    return keep[0]
pneus = {}
cantos = [(p['name'].split('_')[1], p['centro'][0], p['centro'][2], p['lado'], p['y']) for p in mapa['parts']
          if p.get('take') == 'roda' and p.get('papel') == 'wheel']
if not cantos:
    # rodas cortadas por material (Sagui, 30/10/2026): os cantos vêm da lista "rodas" do mapa
    cantos = [(r['nome'], r['cx'], r['cz'], r['lado'], (r['y_dentro'], r['y_fora'])) for r in mapa.get('rodas', [])]
for pos, cx, cz, s, ys in cantos:
    if True:
        y = s * (ys[0] + ys[1]) / 2
        estado = sys.argv[sys.argv.index('--') + 3] if pos == 'fl' else 'Ok'
        # RODAS="aro,pneu,calota" (os de Data/CarWheels.csv do carro; Sagui: aro_aco14,pneu_p185_60,calota14); padrão o do Cuiabano
        aro_, pneu_, calota_ = os.environ.get('RODAS', 'aro_aco13,pneu_p175_70,calota13').split(',')
        for nome, obj in ((aro_, aro_), (pneu_, pneu_ + '_' + estado), (calota_, calota_)):
            if nome in ('', '-'):
                continue        # roda de liga sem calota (Tropeiro: RODAS=aro_liga15,pneu_p205_60,; Barão: ...,-)
            o = rodaglb(nome, obj)
            o.location = (cx, y, cz)
            o.rotation_mode = 'XYZ'; o.rotation_euler = (0, 0, 0 if s > 0 else math.pi)
            if nome.startswith('pneu') and estado != 'Ok':
                o.location.z = cz  # o pivô é o cubo
# pintura: a tinta em branco vezes a cor
cor = [float(x) for x in sys.argv[sys.argv.index('--') + 4].split(',')]
img = bpy.data.images.load(paint_png)
for m in bpy.data.materials:
    if m.name.startswith('pintura_interna') and m.node_tree:
        b = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'][0]
        for l in list(b.inputs['Base Color'].links): m.node_tree.links.remove(l)
        b.inputs['Base Color'].default_value = cor + [1]
        continue
    if m.name.startswith('pintura') and m.node_tree:
        nt = m.node_tree; b = [n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'][0]
        src = b.inputs['Base Color'].links[0].from_node if b.inputs['Base Color'].links else None
        t = nt.nodes.new('ShaderNodeTexImage'); t.image = img
        if src is not None and src.type == 'TEX_IMAGE' and src.inputs[0].links: nt.links.new(src.inputs[0].links[0].from_socket, t.inputs[0])
        mul = nt.nodes.new('ShaderNodeMix'); mul.data_type = 'RGBA'; mul.blend_type = 'MULTIPLY'; mul.inputs[0].default_value = 1
        nt.links.new(t.outputs[0], mul.inputs[6]); mul.inputs[7].default_value = cor + [1]
        if os.environ.get('LISO'):
            for l in list(b.inputs['Base Color'].links): nt.links.remove(l)
            b.inputs['Base Color'].default_value = cor + [1]
        else:
            nt.links.new(mul.outputs[2], b.inputs['Base Color'])
        b.inputs['Coat Weight'].default_value = 1.0; b.inputs['Coat Roughness'].default_value = 0.03; b.inputs['Roughness'].default_value = 0.16
        if os.environ.get('ACAB'):
            # acabamento de Data/PaintFinishes.csv, como o ADNVehicle manda ao material do jogo
            import csv
            f = {r['Id']: r for r in csv.DictReader(open(os.path.join(DN, 'Data', 'PaintFinishes.csv')))}[os.environ['ACAB']]
            b.inputs['Metallic'].default_value = float(f['Metallic']); b.inputs['Roughness'].default_value = float(f['Roughness'])
            b.inputs['Coat Weight'].default_value = float(f['ClearCoat']); b.inputs['Coat Roughness'].default_value = float(f['ClearCoatRoughness'])
            pr = float(f['Pearl'])
            if pr > 0 and b.inputs['Base Color'].links:
                lw = nt.nodes.new('ShaderNodeLayerWeight'); lw.inputs[0].default_value = 0.35
                pt = [((int(f[k]) / 255) / 12.92 if int(f[k]) / 255 <= 0.04045 else ((int(f[k]) / 255 + 0.055) / 1.055) ** 2.4) for k in ('PearlR', 'PearlG', 'PearlB')]
                mp = nt.nodes.new('ShaderNodeMix'); mp.data_type = 'RGBA'; mp.blend_type = 'MULTIPLY'; mp.inputs[0].default_value = 1
                nt.links.new(t.outputs[0], mp.inputs[6]); mp.inputs[7].default_value = pt + [1]
                fac = nt.nodes.new('ShaderNodeMath'); fac.operation = 'MULTIPLY'; fac.inputs[1].default_value = pr
                nt.links.new(lw.outputs['Facing'], fac.inputs[0])
                mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'
                nt.links.new(fac.outputs[0], mx.inputs[0]); nt.links.new(b.inputs['Base Color'].links[0].from_socket, mx.inputs[6]); nt.links.new(mp.outputs[2], mx.inputs[7])
                nt.links.new(mx.outputs[2], b.inputs['Base Color'])
# vidro como o do jogo (GlassOpacity 0,12): transparente por alfa, a luz passa reto e ilumina a cabine e o refletor do farol
for m in bpy.data.materials:
    if m.name.startswith('vidro') and m.node_tree:
        bb = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
        if not bb: continue
        b = bb[0]
        for l in list(b.inputs['Base Color'].links): m.node_tree.links.remove(l)
        for l in list(b.inputs['Alpha'].links): m.node_tree.links.remove(l)
        b.inputs['Base Color'].default_value = (0.80, 0.86, 0.86, 1) if not os.environ.get('HDRI') else (0.02, 0.025, 0.025, 1); b.inputs['Roughness'].default_value = 0.02
        b.inputs['Transmission Weight'].default_value = 0.0; b.inputs['Alpha'].default_value = float(os.environ.get('VIDRO_ALFA', '0.15'))
        b.inputs['Coat Weight'].default_value = 1.0; b.inputs['Coat Roughness'].default_value = 0.0
# refletor do farol e da lanterna com os valores do jogo (MI_DNRefletor<Modelo> do import_kit_car.py: prata acetinado, pouco metal, aceso
# pela luz que passa a lente). Nada de truque só na prévia: uma lente clarinha aqui escondeu que no jogo o farol saía preto (29/10)
for m in bpy.data.materials:
    if m.name.split('.')[0] == 'refletor' and m.node_tree:
        bb = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
        if bb:
            for l in list(bb[0].inputs['Base Color'].links): m.node_tree.links.remove(l)
            bb[0].inputs['Base Color'].default_value = (0.62, 0.63, 0.64, 1)
            bb[0].inputs['Metallic'].default_value = 0.35; bb[0].inputs['Roughness'].default_value = 0.35
if os.environ.get('ESCADA'):
    # a escada de alumínio do jogo (veiculos/proprios/escada-aluminio.glb) no bagageiro, pela regra do montar_escada_no_teto.py do
    # Detonauto: piso do bagageiro = a faixa de 1 cm com mais vértices nos 20 cm de cima do carro, centrada nas barras, 25 cm à frente
    from collections import Counter
    pts_ = [o.matrix_world @ vv.co for o in bpy.data.objects if o.type == 'MESH' and o.name.split('.')[0] in ('roof_rack', 'body') for vv in o.data.vertices]
    teto_ = max(q.z for q in pts_)
    piso_ = Counter(round(q.z * 100) for q in pts_ if q.z > teto_ - 0.20).most_common(1)[0][0]
    barras_ = [q for q in pts_ if round(q.z * 100) == piso_]
    antes_ = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.environ['ESCADA'])
    esc_ = [o for o in bpy.data.objects if o not in antes_]
    for o in esc_:
        if o.parent is None or o.parent not in esc_:
            o.location += Vector(((min(q.x for q in barras_) + max(q.x for q in barras_)) / 2 + float(os.environ.get('ESCADA_AVANCO', '0.25')),
                                  (min(q.y for q in barras_) + max(q.y for q in barras_)) / 2, piso_ / 100 + 0.015))
tirar = sys.argv[sys.argv.index('--') + 5].split(',') if len(sys.argv) > sys.argv.index('--') + 5 else []
for o in list(bpy.data.objects):
    base = o.name.split('.')[0]
    if any(base == t or base.startswith(t) for t in tirar if t):
        bpy.data.objects.remove(o)
if os.environ.get('MARCA'):
    # pinta de verde vivo o material MARCA (para achar quem aparece através da chapa)
    for m in bpy.data.materials:
        if m.name.startswith(os.environ['MARCA']) and m.node_tree:
            bb = [n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED']
            if bb:
                for l in list(bb[0].inputs['Base Color'].links): m.node_tree.links.remove(l)
                bb[0].inputs['Base Color'].default_value = (0, 1, 0, 1)
c.render.engine = 'CYCLES'; c.cycles.samples = 48; c.render.resolution_x = 1280; c.render.resolution_y = 760
w = bpy.data.worlds.new('w'); c.world = w; w.use_nodes = True
bg = w.node_tree.nodes['Background']; bg.inputs[0].default_value = (0.62, 0.66, 0.72, 1); bg.inputs[1].default_value = 0.9
if os.environ.get('HDRI'):
    # foto de rua (HDRI CC0 do Poly Haven): o verniz e o cromo refletem prédios, céu e chão como numa foto de verdade
    env = w.node_tree.nodes.new('ShaderNodeTexEnvironment'); env.image = bpy.data.images.load(os.environ['HDRI'])
    mp_ = w.node_tree.nodes.new('ShaderNodeMapping'); tc_ = w.node_tree.nodes.new('ShaderNodeTexCoord')
    mp_.inputs['Rotation'].default_value[2] = math.radians(float(os.environ.get('HDRI_ROT', '0')))
    w.node_tree.links.new(tc_.outputs['Generated'], mp_.inputs[0]); w.node_tree.links.new(mp_.outputs[0], env.inputs[0])
    w.node_tree.links.new(env.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = float(os.environ.get('HDRI_FORCA', '1.0'))
    try:
        c.view_settings.view_transform = 'AgX'; c.view_settings.look = 'AgX - Punchy'
    except Exception:
        pass
elif os.environ.get('CEU', '1') == '1':
    # céu de verdade (Nishita) para os reflexos: com o fundo cinza liso, verniz e cromo pareciam foscos
    sky = w.node_tree.nodes.new('ShaderNodeTexSky')
    try:
        sky.sky_type = 'NISHITA'; sky.sun_elevation = 0.75; sky.sun_rotation = 2.4; sky.altitude = 0
    except Exception:
        pass
    w.node_tree.links.new(sky.outputs[0], bg.inputs[0]); bg.inputs[1].default_value = float(os.environ.get('CEU_FORCA', '0.14'))
    try:
        c.view_settings.view_transform = 'AgX'; c.view_settings.look = 'AgX - Punchy'
    except Exception:
        pass
sun = bpy.data.objects.new('s', bpy.data.lights.new('s', 'SUN')); sun.data.energy = float(os.environ.get('SOL', '0.0' if os.environ.get('HDRI') else '3.2')); sun.data.angle = 0.1; c.collection.objects.link(sun); sun.rotation_euler = (0.75, 0.15, 2.4)
chao = bpy.data.objects.new('chao', bpy.data.meshes.new('chao')); c.collection.objects.link(chao)
bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=30); bm.to_mesh(chao.data)
mc = bpy.data.materials.new('asfalto'); mc.use_nodes = True; mc.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.09, 0.09, 0.09, 1); mc.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.85
chao.data.materials.append(mc)
if os.environ.get('HDRI'):
    chao.is_shadow_catcher = True   # o chão da foto aparece, com a sombra do carro por cima
cam = bpy.data.objects.new('c', bpy.data.cameras.new('c')); c.collection.objects.link(cam); c.camera = cam
v = sys.argv[sys.argv.index('--') + 6]
if v == 'foto':
    cam.data.lens = 50; cam.location = Vector((4.6, 5.2, 1.35)); alvo = Vector((0.15, 0, 0.62))
elif v == 'perto':
    pass
if v == 'tras':
    cam.data.lens = 45; cam.location = Vector((-4.6, -3.6, 1.7)); alvo = Vector((-0.6, 0, 0.7))
elif v == 'foto':
    pass
elif v == 'longe':
    cam.data.lens = 50; cam.location = Vector((4.2, 4.6, 1.6)); alvo = Vector((0.1, 0, 0.6))
else:
    cam.data.lens = 30; cam.location = Vector((2.6, 3.1, 1.75)); alvo = Vector((0.5, 0.2, 0.75))
if os.environ.get('CAM'):
    q = [float(x) for x in os.environ['CAM'].split(',')]
    cam.location = Vector(q[0:3]); alvo = Vector(q[3:6]); cam.data.lens = q[6]
cam.rotation_euler = (alvo - cam.location).to_track_quat('-Z', 'Y').to_euler()
c.render.filepath = out; bpy.ops.render.render(write_still=True)
