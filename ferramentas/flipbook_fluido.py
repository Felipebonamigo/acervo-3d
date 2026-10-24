"""Flipbooks de fogo e fumaça por simulação Mantaflow (Blender como módulo `bpy`).

Gera, por preset, uma simulação curta de gás no Mantaflow, renderiza em Cycles com fundo
transparente uma sequência de quadros e monta um atlas flipbook 8x8 (64 quadros) para o
SubUV do Niagara. Conteúdo próprio do estúdio, sem IA e sem asset de terceiros.

Uso (sem Blender instalado, só o módulo bpy):

    python -I ferramentas/flipbook_fluido.py -- --preset fogo_carro --saida efeitos/fogo_carro
    python -I ferramentas/flipbook_fluido.py -- --preset todos --saida efeitos

Opções: --res N (resolução do domínio no eixo maior), --amostras N (Cycles), --rapido
(domínio pequeno e poucas amostras, só para conferir enquadramento), --cache DIR,
--so-montar (reaproveita os EXR já renderizados no cache).

Saída em <saida>/<preset>/: <preset>_atlas.png (RGBA, alfa reto, cor em sRGB),
<preset>_emissao.png (só fogo: emissão RGB para somar no material, preto onde não há
fogo), <preset>.json (quadros, linhas, colunas, fps, loop, escala em metros) e
<preset>_folha.png / <preset>.gif (para olhar).

Observação sobre o bpy do pip (5.2.3): as classes Python do Mantaflow nascem sem a
classe-base (o LevelsetGrid não herda setConst do Grid<Real>) e o domínio de gás falha
com "AttributeError: 'LevelsetGrid' object has no attribute 'setConst'". `consertar_manta()`
reconstrói a herança (tp_mro/tp_bases) por ctypes antes de o script do Mantaflow rodar.
"""

import argparse
import ctypes
import json
import math
import os
import random
import shutil
import sys
import time

import bpy
from mathutils import Matrix, Vector
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Conserto da herança das classes do Mantaflow no bpy do pip
# ---------------------------------------------------------------------------

_PAI_MANTA = {
    'FluidSolver': 'PbClass', 'GridBase': 'PbClass',
    'Grid_Real': 'GridBase', 'Grid_int': 'GridBase', 'Grid_Vec3': 'GridBase',
    'MACGrid': 'Grid_Vec3', 'FlagGrid': 'Grid_int', 'LevelsetGrid': 'Grid_Real',
    'Grid4dBase': 'PbClass', 'Grid4d_Real': 'Grid4dBase', 'Grid4d_int': 'Grid4dBase',
    'Grid4d_Vec3': 'Grid4dBase', 'Grid4d_Vec4': 'Grid4dBase',
    'ParticleBase': 'PbClass',
    'ParticleSystem_BasicParticleData': 'ParticleBase',
    'ParticleSystem_ParticleIndexData': 'ParticleBase',
    'ParticleSystem_TurbulenceParticleData': 'ParticleBase',
    'ParticleSystem_VortexParticleData': 'ParticleBase',
    'BasicParticleSystem': 'ParticleSystem_BasicParticleData',
    'ParticleIndexSystem': 'ParticleSystem_ParticleIndexData',
    'TurbulenceParticleSystem': 'ParticleSystem_TurbulenceParticleData',
    'VortexParticleSystem': 'ParticleSystem_VortexParticleData',
    'ParticleDataBase': 'PbClass', 'ParticleDataImpl_Real': 'ParticleDataBase',
    'ParticleDataImpl_int': 'ParticleDataBase', 'ParticleDataImpl_Vec3': 'ParticleDataBase',
    'Mesh': 'PbClass', 'VortexSheetMesh': 'Mesh', 'MeshDataBase': 'PbClass',
    'MeshDataImpl_Real': 'MeshDataBase', 'MeshDataImpl_int': 'MeshDataBase',
    'MeshDataImpl_Vec3': 'MeshDataBase',
    'Shape': 'PbClass', 'NullShape': 'Shape', 'Box': 'Shape', 'Sphere': 'Shape',
    'Cylinder': 'Shape', 'Slope': 'Shape',
    'MovingObstacle': 'PbClass', 'WaveletNoiseField': 'PbClass', 'Timings': 'PbClass',
}
_GUARDA = []  # mantém vivas as tuplas apontadas pelos tipos


def _offset_ponteiro(obj, alvo):
    for off in range(0, 512, 8):
        if ctypes.c_void_p.from_address(id(obj) + off).value == id(alvo):
            return off
    raise RuntimeError('campo não achado no PyTypeObject')


def _consertar_tipos(tipos):
    lv = tipos['LevelsetGrid']
    off_mro = _offset_ponteiro(lv, lv.__mro__)
    off_bases = _offset_ponteiro(lv, lv.__bases__)
    for nome, pai in _PAI_MANTA.items():
        t = tipos.get(nome)
        if t is None or pai not in tipos or t.__mro__[1] is not object:
            continue
        cadeia, n = [t], nome
        while n in _PAI_MANTA and _PAI_MANTA[n] in tipos:
            n = _PAI_MANTA[n]
            cadeia.append(tipos[n])
        mro = tuple(cadeia) + (object,)
        bases = (tipos[pai],)
        _GUARDA.extend([mro, bases])
        ctypes.c_void_p.from_address(id(t) + off_mro).value = id(mro)
        ctypes.c_void_p.from_address(id(t) + off_bases).value = id(bases)
        ctypes.pythonapi.PyType_Modified(ctypes.py_object(t))


def consertar_manta():
    """Instala um gancho que conserta os tipos do Mantaflow cada vez que um solver nasce.

    O Blender cria tipos novos a cada inicialização do Mantaflow e roda o script dele na
    thread principal, então um sys.setprofile basta. Precisa ser chamado antes de criar
    o modificador Fluid."""
    def perfil(frame, evento, arg):
        lv = frame.f_globals.get('LevelsetGrid')
        if isinstance(lv, type) and lv.__mro__[1] is object:
            _consertar_tipos({k: v for k, v in frame.f_globals.items() if isinstance(v, type)})
    sys.setprofile(perfil)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
# Unidades em metros. O domínio começa no chão (z = 0). "quadro" é o lado do quadrado que
# a câmera ortográfica enxerga; "centro" é o meio desse quadrado.

PRESETS = {
    'fogo_carro': dict(
        descricao='Chamas de ~1,5 m saindo do vão do motor de um carro, com fuligem preta.',
        # 10 blocos achatados espalhados pelo vão do motor, cada um pulsando no seu ritmo:
        # a base fica irregular e as línguas de fogo se soltam em vez de um lençol contínuo
        dominio=(2.4, 1.6, 2.8), res=128, ruido=2, quadro=2.2, centro=(0.0, 0.0, 1.18),
        elevacao=0.0, aquecimento=40, passo=1, loop=True, sobrepor=16, fps=24, lado=512,
        borda_base=0.12,
        emissor=dict(blocos=dict(n=10, regiao=(0.5, 0.28, 0.03), raio=(0.09, 0.2), achatar=0.45),
                     pos=(0.0, 0.0, 0.12), pulsos=(7, 0.35, 1.4),
                     tipo='BOTH', combustivel=1.6, densidade=0.3, temperatura=1.6,
                     cor_fumaca=(0.08, 0.07, 0.06), textura=0.18, contraste=2.5,
                     vel_textura=0.06, vel_normal=0.0, vel_z=1.0),
        dom=dict(vorticidade=0.4, alfa=0.0, beta=2.0, queima=0.65, fumaca_chama=1.2,
                 vort_chama=1.5, temp_max=2.6, dissolver=18, cor_fumaca_chama=(0.06, 0.055, 0.05),
                 ruido_forca=1.6, tempo=1.0),
        material=dict(densidade=26.0, cor=(0.04, 0.036, 0.032), fogo=True, brilho=16.0, exposicao=0.9, saturacao=1.7,
                      anisotropia=0.2),
        luz=dict(sol=2.5, contra=0.4, ambiente=0.12)),
    'fumaca_preta': dict(
        descricao='Coluna de fumaça preta densa de motor ou pneu queimando, ~4 m, pendendo com vento leve.',
        # blocos que pulsam soltam rolos que sobem, abrem e se desfazem; vento leve para +X
        dominio=(5.6, 3.2, 5.2), res=112, ruido=2, quadro=4.4, centro=(0.55, 0.0, 2.2),
        elevacao=0.0, aquecimento=110, passo=1, loop=True, sobrepor=16, fps=18, seis=True,
        emissor=dict(blocos=dict(n=5, regiao=(0.3, 0.25, 0.03), raio=(0.12, 0.25), achatar=0.5),
                     pos=(-0.7, 0.0, 0.12), pulsos=(10, 0.15, 1.5),
                     tipo='SMOKE', combustivel=0.0, densidade=1.0, temperatura=2.2,
                     cor_fumaca=(0.03, 0.03, 0.03), textura=0.4, contraste=2.0, vel_textura=0.05,
                     vel_normal=0.0, vel_z=1.5, vento=0.025, vento_ruido=0.2),
        dom=dict(vorticidade=0.3, alfa=0.0, beta=2.5, dissolver=150, ruido_forca=1.8,
                 tempo=1.0),
        # densidade alta: só a casca da coluna aparece, com novelos e sombra própria
        material=dict(densidade=22.0, cor=(0.11, 0.11, 0.11), fogo=False, anisotropia=0.3),
        luz=dict(sol=14.0, contra=1.0, ambiente=0.18)),
    'fumaca_branca': dict(
        descricao='Vapor branco de radiador furado: jato curto que se desfaz rápido.',
        dominio=(2.2, 1.4, 1.9), res=96, ruido=2, quadro=1.6, centro=(0.0, 0.0, 0.8),
        elevacao=0.0, aquecimento=45, passo=1, loop=True, sobrepor=16, fps=24, seis=True,
        emissor=dict(forma='caixa', tam=(0.32, 0.12, 0.06), pos=(0.0, 0.0, 0.08),
                     tipo='SMOKE', combustivel=0.0, densidade=1.0, temperatura=2.0,
                     cor_fumaca=(0.9, 0.9, 0.9), textura=0.08, vel_textura=0.03,
                     vel_normal=0.0, vel_z=2.5),
        dom=dict(vorticidade=0.35, alfa=0.0, beta=1.5, dissolver=20, ruido_forca=1.6,
                 tempo=1.0),
        material=dict(densidade=28.0, cor=(0.95, 0.95, 0.96), fogo=False, anisotropia=0.3,
                      exposicao=1.7),
        luz=dict(sol=7.0, contra=1.0, ambiente=0.5)),
    'explosao': dict(
        descricao='Bola de fogo de ~3 m, turbulenta desde o início, que se apaga rápido e sobe como fumaça escura.',
        # 7 bolsões de combustível defasados que crescem e se empurram: a bola nasce com
        # lóbulos e borda rasgada em vez de uma esfera lisa
        dominio=(4.8, 4.8, 5.0), res=72, ruido=3, quadro=4.6, centro=(0.0, 0.0, 2.25),
        elevacao=0.0, aquecimento=2, passo=1, loop=False, sobrepor=0, fps=24, lado=512, seis=True,
        emissor=dict(blocos=dict(n=7, regiao=(0.4, 0.4, 0.25), raio=(0.14, 0.3), atraso_max=3),
                     pos=(0.0, 0.0, 1.3), ligado=(1, 6), expandir=((4.4, 4.4, 4.0), 6), fator_vel=1.0,
                     tipo='BOTH', combustivel=3.0, densidade=0.7, temperatura=3.0,
                     cor_fumaca=(0.06, 0.05, 0.045), textura=0.16, contraste=3.0,
                     vel_textura=0.0, vel_normal=3.0, vel_z=0.0, volume=0.3),
        # grade base grossa (72) com vorticidade alta dá os lóbulos grandes; o ruído x3 põe o
        # detalhe fino. Na grade fina (112) a bola saía lisa como um ovo.
        dom=dict(passos_max=10, vorticidade=1.2, alfa=0.0, beta=0.45, queima=0.9, fumaca_chama=1.5,
                 vort_chama=2.0, temp_max=3.0, dissolver=110, cor_fumaca_chama=(0.07, 0.06, 0.055),
                 ruido_forca=2.5, tempo=1.0),
        material=dict(densidade=14.0, limiar=0.12, cor=(0.14, 0.13, 0.12), fogo=True, brilho=9.0, saturacao=1.7,
                      ruido_emissao=(0.9, 0.85), anisotropia=0.25),
        luz=dict(sol=6.0, contra=0.6, ambiente=0.25), sumir=10),
    'poeira': dict(
        descricao='Nuvem baixa de poeira de impacto que se espalha rente ao chão e assenta.',
        # cúpula achatada no chão soprando para cima e para fora por 4 quadros
        dominio=(5.0, 3.4, 2.8), res=100, ruido=2, quadro=2.6, centro=(0.0, 0.0, 1.1),
        elevacao=10.0, aquecimento=3, passo=1, loop=False, sobrepor=0, fps=24,
        emissor=dict(forma='esfera', raio=0.6, achatar=0.45, pos=(0.0, 0.0, 0.0), ligado=(1, 4),
                     tipo='SMOKE', combustivel=0.0, densidade=1.0, temperatura=0.8,
                     cor_fumaca=(0.5, 0.42, 0.32), textura=0.14, contraste=2.5,
                     vel_textura=0.0, vel_normal=7.0, vel_z=1.5, volume=0.4),
        dom=dict(passos_max=10, vorticidade=0.6, alfa=-0.05, beta=0.5, dissolver=70,
                 ruido_forca=1.8, tempo=1.0),
        material=dict(densidade=12.0, cor=(0.55, 0.47, 0.37), fogo=False, anisotropia=0.3),
        luz=dict(sol=5.0, contra=0.6, ambiente=0.35), sumir=12),
}

# Direção de onde a luz VEM -> vetor em que ela viaja. A câmera olha para +Y, então
# "frente" é a luz que vem do lado da câmera e "trás" a que vem de trás do volume.
DIRECOES_6 = [('direita', (-1, 0, 0)), ('cima', (0, 0, -1)), ('tras', (0, -1, 0)),
              ('esquerda', (1, 0, 0)), ('baixo', (0, 0, 1)), ('frente', (0, 1, 0))]
LUZ_6 = 3.0  # força de cada sol de medição (W/m²)

COLUNAS = LINHAS = 8
QUADROS = COLUNAS * LINHAS
LADO = 256
SEMENTE = 1717


# ---------------------------------------------------------------------------
# Cena
# ---------------------------------------------------------------------------

def _linear(obj, caminho):
    ad = obj.animation_data
    if not ad or not ad.action:
        return
    for fc in _fcurves(ad.action):
        if fc.data_path.endswith(caminho):
            for k in fc.keyframe_points:
                k.interpolation = 'LINEAR'


def _fcurves(acao):
    if hasattr(acao, 'fcurves'):
        try:
            return list(acao.fcurves)
        except Exception:
            pass
    curvas = []  # ações em camadas (Blender 4.4+)
    for camada in getattr(acao, 'layers', []):
        for faixa in camada.strips:
            for bag in faixa.channelbags:
                curvas.extend(bag.fcurves)
    return curvas


def montar_cena(nome, p, res, cache, rng):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    cena = bpy.context.scene
    dx, dy, dz = p['dominio']
    e = p['emissor']
    d = p['dom']

    # Domínio
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, dz / 2))
    dom = bpy.context.object
    dom.name = 'Dominio'
    dom.scale = (dx, dy, dz)
    bpy.ops.object.transform_apply(scale=True)
    mod = dom.modifiers.new('Fluido', 'FLUID')
    mod.fluid_type = 'DOMAIN'
    ds = mod.domain_settings
    ds.domain_type = 'GAS'
    ds.resolution_max = res
    ds.cache_directory = cache
    ds.cache_type = 'ALL'
    ds.cache_data_format = 'OPENVDB'
    ds.openvdb_data_depth = '16'  # meia precisão: metade do disco, igual no render
    ds.vorticity = d['vorticidade']
    ds.alpha = d['alfa']
    ds.beta = d['beta']
    ds.time_scale = d.get('tempo', 1.0)
    ds.timesteps_max = d.get('passos_max', 4)  # mais subpassos para jato rápido (evita riscos)
    ds.use_collision_border_front = False
    ds.use_collision_border_back = False
    ds.use_collision_border_right = False
    ds.use_collision_border_left = False
    ds.use_collision_border_top = False
    ds.use_collision_border_bottom = True
    if d.get('dissolver'):
        ds.use_dissolve_smoke = True
        ds.dissolve_speed = int(d['dissolver'])
        ds.use_dissolve_smoke_log = True
    if e['tipo'] != 'SMOKE':
        ds.burning_rate = d['queima']
        ds.flame_smoke = d['fumaca_chama']
        ds.flame_vorticity = d['vort_chama']
        ds.flame_max_temp = d['temp_max']
        ds.flame_smoke_color = d['cor_fumaca_chama']
    if p['ruido'] > 1:
        ds.use_noise = True
        ds.noise_scale = p['ruido']
        ds.noise_strength = d['ruido_forca']
        ds.noise_pos_scale = 2.0
        ds.noise_time_anim = 0.1

    # Emissores: um objeto só ou vários blocos irregulares ('blocos'), cada um com o seu
    # próprio fluxo, atraso e pulsação, para a fonte não aparecer como forma geométrica.
    emissores = []
    if e.get('blocos'):
        bl = e['blocos']
        cx, cy, cz = e['pos']
        rx, ry, rz = bl['regiao']
        for i in range(bl['n']):
            pos = (cx + rng.uniform(-rx, rx), cy + rng.uniform(-ry, ry), cz + rng.uniform(-rz, rz))
            raio = rng.uniform(*bl['raio'])
            bpy.ops.mesh.primitive_ico_sphere_add(radius=raio, subdivisions=bl.get('subdiv', 3),
                                                  location=pos)
            em = bpy.context.object
            asp = bl.get('aspecto', (0.7, 1.4))
            # deforma a malha direto (sem transform_apply)
            esc = Matrix.Diagonal((rng.uniform(*asp), rng.uniform(*asp), bl.get('achatar', 1.0), 1.0))
            giro = Matrix.Rotation(rng.uniform(0.0, math.pi) if bl.get('girar', True) else 0.0, 4, 'Z')
            em.data.transform(giro @ esc)
            em.data.update()
            atraso = int(round(rng.uniform(0, bl.get('atraso_max', 0))))
            emissores.append((em, atraso))
    else:
        forma = e['forma']
        ex, ey, ez = e['pos']
        if forma == 'caixa':
            bpy.ops.mesh.primitive_cube_add(size=1, location=(ex, ey, ez))
            em = bpy.context.object
            em.scale = e['tam']
            bpy.ops.object.transform_apply(scale=True)
            sub = em.modifiers.new('sub', 'SUBSURF')  # o ruído da textura varia pela superfície
            sub.subdivision_type = 'SIMPLE'
            sub.levels = 4
            sub.render_levels = 4
        elif forma == 'esfera':
            bpy.ops.mesh.primitive_ico_sphere_add(radius=e['raio'], subdivisions=4,
                                                  location=(ex, ey, ez))
            em = bpy.context.object
            if e.get('achatar'):  # cúpula: esfera achatada meio enterrada no chão
                em.scale = (1.0, 1.0, e['achatar'])
                bpy.ops.object.transform_apply(scale=True)
        else:  # disco
            bpy.ops.mesh.primitive_cylinder_add(radius=e['raio'], depth=0.12, vertices=48,
                                                location=(ex, ey, ez))
            em = bpy.context.object
            sub = em.modifiers.new('sub', 'SUBSURF')
            sub.subdivision_type = 'SIMPLE'
            sub.levels = 3
            sub.render_levels = 3
        emissores.append((em, 0))

    tex = None
    if e.get('textura'):
        tex = bpy.data.textures.new('ruido_emissor', 'CLOUDS')
        tex.noise_scale = e['textura']
        tex.noise_depth = 3
        tex.noise_basis = 'IMPROVED_PERLIN'
        tex.contrast = e.get('contraste', 1.0)

    for i, (em, atraso) in enumerate(emissores):
        em.name = 'Emissor%02d' % i
        em.hide_render = True
        fm = em.modifiers.new('Fluido', 'FLUID')
        fm.fluid_type = 'FLOW'
        fs = fm.flow_settings
        fs.flow_type = e['tipo']
        fs.flow_behavior = 'INFLOW'
        fs.flow_source = 'MESH'
        fs.surface_distance = 1.5 * max(dx, dy, dz) / res
        fs.volume_density = e.get('volume', 1.0)  # quanto emite de dentro da malha fechada
        fs.subframes = 1 if e['tipo'] == 'SMOKE' else 2
        fs.density = e['densidade']
        fs.temperature = e['temperatura']
        fs.smoke_color = e['cor_fumaca']
        if e['tipo'] != 'SMOKE':
            fs.fuel_amount = e['combustivel']
        if e.get('vel_normal') or e.get('vel_z') or e.get('vel_x'):
            fs.use_initial_velocity = True
            fs.velocity_normal = e.get('vel_normal', 0.0)
            fs.velocity_coord = (e.get('vel_x', 0.0), 0.0, e.get('vel_z', 0.0))
            fs.velocity_random = 0.0
        if tex is not None:
            fs.use_texture = True
            fs.noise_texture = tex
            fs.texture_map_type = 'AUTO'
            fs.texture_size = 1.0
            inicio = rng.uniform(0.0, 10.0)
            fs.texture_offset = inicio
            fs.keyframe_insert('texture_offset', frame=1)
            fim = 400
            fs.texture_offset = inicio + e.get('vel_textura', 0.0) * (fim - 1)
            fs.keyframe_insert('texture_offset', frame=fim)
        if e.get('pulsos'):
            # emissão que pulsa (rolos que se soltam em vez de um jato constante)
            periodo, lo, hi = e['pulsos']
            q = 1 - rng.randint(0, periodo)
            while q < 400:
                f = rng.uniform(lo, hi)
                fs.density = e['densidade'] * f
                fs.keyframe_insert('density', frame=q)
                if e['tipo'] != 'SMOKE':
                    fs.fuel_amount = e['combustivel'] * f
                    fs.keyframe_insert('fuel_amount', frame=q)
                q += periodo + rng.randint(-periodo // 3, periodo // 3)
        _linear(em, 'texture_offset')
        if e.get('expandir'):
            # o emissor cresce depressa e empurra o gás para fora (velocidade do próprio objeto)
            escala, q_fim = e['expandir']
            em.scale = (1.0, 1.0, 1.0)
            em.keyframe_insert('scale', frame=1 + atraso)
            em.scale = escala
            em.keyframe_insert('scale', frame=q_fim + atraso)
            _linear(em, 'scale')
            fs.use_initial_velocity = True
            fs.velocity_factor = e.get('fator_vel', 1.0)
        if e.get('ligado'):
            a0, b0 = e['ligado']
            if a0 + atraso > 1:
                fs.use_inflow = False
                fs.keyframe_insert('use_inflow', frame=a0 + atraso - 1)
            fs.use_inflow = True
            fs.keyframe_insert('use_inflow', frame=a0 + atraso)
            fs.keyframe_insert('use_inflow', frame=b0 + atraso)
            fs.use_inflow = False
            fs.keyframe_insert('use_inflow', frame=b0 + atraso + 1)

    if e.get('vento'):
        # vento leve e constante de lado: a coluna pende em vez de subir como pilar
        bpy.ops.object.effector_add(type='WIND', location=(-dx / 2, 0, dz / 2))
        vento = bpy.context.object
        vento.rotation_euler = (0.0, math.pi / 2, 0.0)  # sopra para +X
        vento.field.strength = e['vento']
        vento.field.flow = 0.0
        vento.field.noise = e.get('vento_ruido', 0.0)
        vento.field.seed = SEMENTE % 128

    return cena, dom, emissores


def vestir(cena, dom, p):
    """Material do volume, câmera, luzes e mundo. Separado da simulação para poder
    refazer o visual sobre um bake guardado (--so-render)."""
    for o in [o for o in cena.objects if o.type in ('CAMERA', 'LIGHT')]:
        bpy.data.objects.remove(o)
    dom.data.materials.clear()
    # Material do volume
    mat = bpy.data.materials.new('Volume')
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    saida = nt.nodes.new('ShaderNodeOutputMaterial')
    pv = nt.nodes.new('ShaderNodeVolumePrincipled')
    m = p['material']
    pv.inputs['Color'].default_value = (*m['cor'], 1.0)
    pv.inputs['Anisotropy'].default_value = m['anisotropia']
    pv.inputs['Density Attribute'].default_value = ''
    a_den = nt.nodes.new('ShaderNodeAttribute')
    a_den.attribute_type = 'GEOMETRY'
    a_den.attribute_name = 'density'
    mult = nt.nodes.new('ShaderNodeMath')
    mult.operation = 'MULTIPLY'
    mult.inputs[1].default_value = m['densidade']
    if m.get('limiar'):
        # corta a névoa rala: só os novelos acima do limiar aparecem (silhueta recortada)
        corte = nt.nodes.new('ShaderNodeMath')
        corte.operation = 'SUBTRACT'
        corte.use_clamp = True
        corte.inputs[1].default_value = m['limiar']
        nt.links.new(a_den.outputs['Fac'], corte.inputs[0])
        nt.links.new(corte.outputs[0], mult.inputs[0])
    else:
        nt.links.new(a_den.outputs['Fac'], mult.inputs[0])
    nt.links.new(mult.outputs[0], pv.inputs['Density'])
    if m['fogo']:
        a_fl = nt.nodes.new('ShaderNodeAttribute')
        a_fl.attribute_type = 'GEOMETRY'
        a_fl.attribute_name = 'flame'
        rampa = nt.nodes.new('ShaderNodeValToRGB')
        cr = rampa.color_ramp
        cr.interpolation = 'B_SPLINE'
        paradas = [(0.0, (0.0, 0.0, 0.0)), (0.15, (0.18, 0.01, 0.0)),
                   (0.35, (0.75, 0.1, 0.005)), (0.6, (1.0, 0.38, 0.04)),
                   (0.82, (1.0, 0.66, 0.2)), (1.0, (1.0, 0.86, 0.55))]
        cr.elements[0].position, cr.elements[0].color = paradas[0][0], (*paradas[0][1], 1)
        cr.elements[1].position, cr.elements[1].color = paradas[-1][0], (*paradas[-1][1], 1)
        for pos, cor in paradas[1:-1]:
            el = cr.elements.new(pos)
            el.color = (*cor, 1)
        nt.links.new(a_fl.outputs['Fac'], rampa.inputs['Fac'])
        # força cresce com o quadrado da chama: pontas escuras, núcleo forte
        quad = nt.nodes.new('ShaderNodeMath')
        quad.operation = 'POWER'
        quad.inputs[1].default_value = 2.5
        nt.links.new(a_fl.outputs['Fac'], quad.inputs[0])
        forca = nt.nodes.new('ShaderNodeMath')
        forca.operation = 'MULTIPLY'
        forca.inputs[1].default_value = m['brilho']
        nt.links.new(quad.outputs[0], forca.inputs[0])
        nt.links.new(rampa.outputs['Color'], pv.inputs['Emission Color'])
        saida_forca = forca.outputs[0]
        if m.get('ruido_emissao'):
            # quebra a bola de fogo lisa: ruído 4D (o W anda com o tempo) modula a emissão
            # e a fuligem, como as dobras escuras de uma bola de fogo de verdade
            escala, forca_r = m['ruido_emissao']
            coord = nt.nodes.new('ShaderNodeTexCoord')
            ruido = nt.nodes.new('ShaderNodeTexNoise')
            ruido.noise_dimensions = '4D'
            ruido.inputs['Scale'].default_value = escala
            ruido.inputs['Detail'].default_value = 8.0
            ruido.inputs['Roughness'].default_value = 0.62
            ruido.inputs['W'].default_value = 0.0
            ruido.inputs['W'].keyframe_insert('default_value', frame=1)
            ruido.inputs['W'].default_value = 4.0
            ruido.inputs['W'].keyframe_insert('default_value', frame=81)
            for fc in _fcurves(nt.animation_data.action):
                for k in fc.keyframe_points:
                    k.interpolation = 'LINEAR'
            nt.links.new(coord.outputs['Object'], ruido.inputs['Vector'])
            faixa = nt.nodes.new('ShaderNodeMapRange')
            faixa.inputs['From Min'].default_value = 0.35
            faixa.inputs['From Max'].default_value = 0.65
            faixa.inputs['To Min'].default_value = 1.0 - forca_r
            faixa.inputs['To Max'].default_value = 1.0 + forca_r * 0.6
            nt.links.new(ruido.outputs['Fac'], faixa.inputs['Value'])
            mod_e = nt.nodes.new('ShaderNodeMath')
            mod_e.operation = 'MULTIPLY'
            nt.links.new(forca.outputs[0], mod_e.inputs[0])
            nt.links.new(faixa.outputs['Result'], mod_e.inputs[1])
            saida_forca = mod_e.outputs[0]
            inv = nt.nodes.new('ShaderNodeMath')  # fuligem mais grossa onde a chama é fraca
            inv.operation = 'SUBTRACT'
            inv.inputs[0].default_value = 2.0
            nt.links.new(faixa.outputs['Result'], inv.inputs[1])
            mod_d = nt.nodes.new('ShaderNodeMath')
            mod_d.operation = 'MULTIPLY'
            nt.links.new(mult.outputs[0], mod_d.inputs[0])
            nt.links.new(inv.outputs[0], mod_d.inputs[1])
            nt.links.new(mod_d.outputs[0], pv.inputs['Density'])
        nt.links.new(saida_forca, pv.inputs['Emission Strength'])
    nt.links.new(pv.outputs['Volume'], saida.inputs['Volume'])
    dom.data.materials.append(mat)

    # Câmera ortográfica
    cx, cy, cz = p['centro']
    el = math.radians(p['elevacao'])
    dist = 12.0
    cam_dado = bpy.data.cameras.new('Cam')
    cam_dado.type = 'ORTHO'
    cam_dado.ortho_scale = p['quadro']
    cam_dado.clip_end = 100
    cam = bpy.data.objects.new('Cam', cam_dado)
    cena.collection.objects.link(cam)
    cam.location = (cx, cy - dist * math.cos(el), cz + dist * math.sin(el))
    cam.rotation_euler = (math.pi / 2 - el, 0.0, 0.0)
    cena.camera = cam

    # Luzes: sol de cima e de lado (volume com sombra própria), contraluz fraca do outro lado
    lz = p['luz']
    sol = bpy.data.lights.new('Sol', 'SUN')
    sol.energy = lz['sol']
    sol.angle = math.radians(3)
    o_sol = bpy.data.objects.new('Sol', sol)
    cena.collection.objects.link(o_sol)
    # direção em que a luz viaja: da esquerda, de cima e um pouco da frente da câmera
    o_sol.rotation_euler = Vector((0.75, 0.35, -0.6)).to_track_quat('-Z', 'Y').to_euler()
    contra = bpy.data.lights.new('Contra', 'SUN')
    contra.energy = lz['contra']
    contra.color = (0.75, 0.82, 1.0)
    o_c = bpy.data.objects.new('Contra', contra)
    cena.collection.objects.link(o_c)
    # contraluz: de trás e da direita, para recortar a borda
    o_c.rotation_euler = Vector((-0.5, -0.75, -0.25)).to_track_quat('-Z', 'Y').to_euler()
    mundo = bpy.data.worlds.new('Mundo')
    bg = mundo.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (0.55, 0.62, 0.75, 1.0)
    bg.inputs['Strength'].default_value = lz['ambiente']
    cena.world = mundo

    vl = cena.view_layers[0]
    for g in list(vl.lightgroups):
        vl.lightgroups.remove(g)
    if p.get('seis'):
        # Luz de 6 direções: cada sol num grupo de luz do Cycles, que sai como passe
        # separado no MESMO render. A imagem bonita vem do grupo 'beleza' (sol, contraluz,
        # céu e a emissão do próprio volume), sem a soma dos 6 sóis de medição.
        vl.lightgroups.add(name='beleza')
        for o in (o_sol, o_c, dom):
            o.lightgroup = 'beleza'
        mundo.lightgroup = 'beleza'
        for nome_d, viagem in DIRECOES_6:
            luz = bpy.data.lights.new('L_' + nome_d, 'SUN')
            luz.energy = LUZ_6
            luz.angle = math.radians(3)
            o_l = bpy.data.objects.new('L_' + nome_d, luz)
            cena.collection.objects.link(o_l)
            o_l.rotation_euler = Vector(viagem).to_track_quat('-Z', 'Y').to_euler()
            vl.lightgroups.add(name='l_' + nome_d)
            o_l.lightgroup = 'l_' + nome_d


def configurar_render(cena, amostras, pasta_exr, fogo, seis=False):
    cena.render.engine = 'CYCLES'
    cy = cena.cycles
    cy.device = 'CPU'
    cy.samples = amostras
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    cy.denoiser = 'OPENIMAGEDENOISE'
    cy.seed = SEMENTE
    cy.max_bounces = 4
    cy.diffuse_bounces = 1
    cy.glossy_bounces = 0
    cy.transmission_bounces = 0
    cy.volume_bounces = 1
    cy.transparent_max_bounces = 8
    if hasattr(cy, 'volume_step_rate'):
        cy.volume_step_rate = 1.0
    cena.render.film_transparent = True
    cena.render.compositor_device = 'CPU'  # sem isso o compositor tenta abrir libEGL e o processo morre
    cena.render.resolution_x = LADO
    cena.render.resolution_y = LADO
    cena.render.resolution_percentage = 100
    cena.render.threads_mode = 'FIXED'
    cena.render.threads = os.cpu_count() or 4
    cena.render.use_persistent_data = False  # medido: sem persistência é mais rápido aqui
    cena.view_settings.view_transform = 'Standard'
    vl = cena.view_layers[0]
    vl.use_pass_emit = True

    # Compositor: grava Combined e Emit em EXR linear; montamos o atlas em numpy.
    arv = bpy.data.node_groups.new('Comp', 'CompositorNodeTree')
    cena.compositing_node_group = arv
    rl = arv.nodes.new('CompositorNodeRLayers')
    fo = arv.nodes.new('CompositorNodeOutputFile')
    fo.directory = pasta_exr
    fo.file_name = 'q####_'
    fo.format.media_type = 'IMAGE'
    fo.format.file_format = 'OPEN_EXR'
    fo.format.color_depth = '16'
    fo.format.color_mode = 'RGBA'
    fo.file_output_items.new('RGBA', 'comb')
    arv.links.new(rl.outputs['Image'], fo.inputs['comb'])
    if fogo:
        # o passe de emissão sai do Cycles sem denoise: passa pelo OIDN do compositor
        dn = arv.nodes.new('CompositorNodeDenoise')
        arv.links.new(rl.outputs['Emission'], dn.inputs['Image'])
        fo.file_output_items.new('RGBA', 'emit')
        arv.links.new(dn.outputs['Image'], fo.inputs['emit'])
    if seis:
        for nome_d in ['beleza'] + ['l_' + n for n, _ in DIRECOES_6]:
            dn = arv.nodes.new('CompositorNodeDenoise')
            arv.links.new(rl.outputs['Combined_' + nome_d], dn.inputs['Image'])
            fo.file_output_items.new('RGBA', nome_d)
            arv.links.new(dn.outputs['Image'], fo.inputs[nome_d])
    cena.render.image_settings.file_format = 'PNG'
    cena.render.filepath = os.path.join(pasta_exr, 'descartar_')


# ---------------------------------------------------------------------------
# Imagem
# ---------------------------------------------------------------------------

def ler_exr(caminho):
    img = bpy.data.images.load(caminho, check_existing=False)
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1].copy()  # de baixo para cima -> de cima para baixo


def achar_exr(pasta, item, quadro):
    alvo = '%04d' % quadro
    for nome in os.listdir(pasta):
        if nome.endswith('.exr') and item in nome and alvo in nome:
            return os.path.join(pasta, nome)
    raise FileNotFoundError('%s %s em %s' % (item, alvo, pasta))


def srgb(x):
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def compressor(x, joelho=0.7):
    """Linear até o joelho, depois aproxima 1 suavemente (destaque do fogo sem estourar)."""
    x = np.maximum(x, 0.0)
    acima = joelho + (1 - joelho) * (1 - np.exp(-(x - joelho) / (1 - joelho)))
    return np.where(x < joelho, x, acima)


def mascara_bordas(lado, margem=0.1, base=0.0):
    """Apaga o alfa suavemente perto das bordas do quadro (cima e lados; embaixo só se
    base=True), para a fumaça que sai do enquadramento não terminar numa linha reta."""
    t = np.linspace(0.0, 1.0, lado)
    def rampa(x):
        y = np.clip(x / margem, 0.0, 1.0)
        return y * y * (3 - 2 * y)
    horiz = rampa(t) * rampa(1 - t)
    vert = rampa(t)  # t = 0 é a borda de cima (imagem de cima para baixo)
    if base:  # embaixo: margem própria (pequena), para a base do fogo não ser uma linha
        yb = np.clip((1 - t) / base, 0.0, 1.0)
        vert = vert * (yb * yb * (3 - 2 * yb))
    return (vert[:, None] * horiz[None, :])[..., None].astype(np.float32)


def saturar(x, fator):
    """Satura a cor linear em volta da luminância (a emissão somada de muitas camadas de
    chama tende ao creme; o fogo de verdade é laranja-amarelo saturado)."""
    if fator == 1.0:
        return x
    lum = (x * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=-1, keepdims=True)
    return np.maximum(lum + (x - lum) * fator, 0.0)


def loop_cruzado(quadros, n, sobrepor):
    """quadros tem n + sobrepor itens. Devolve n quadros cujo fim emenda no começo."""
    if sobrepor <= 0:
        return quadros[:n]
    saida = []
    for i in range(n):
        atual = quadros[i + sobrepor]
        if i >= n - sobrepor:
            t = (i - (n - sobrepor) + 1) / (sobrepor + 1)
            atual = (1 - t) * atual + t * quadros[i + sobrepor - n]
        saida.append(atual)
    return saida


def lum(x):
    return (x[..., :3] * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=-1)


def montar(nome, p, pasta_exr, saida, fogo, quadros_render):
    seis = bool(p.get('seis'))
    comb = [ler_exr(achar_exr(pasta_exr, 'comb', q)) for q in quadros_render]
    if seis:  # cor bonita só do grupo 'beleza' (sem os 6 sóis de medição); alfa do Combined
        for k, q in enumerate(quadros_render):
            bel = ler_exr(achar_exr(pasta_exr, 'beleza', q))
            comb[k] = np.concatenate([bel[..., :3], comb[k][..., 3:4]], axis=-1)
    alfas_brutos = [np.clip(c[..., 3], 0, 1) for c in comb]  # antes do cruzamento do loop
    emit = [ler_exr(achar_exr(pasta_exr, 'emit', q))[..., :3] for q in quadros_render] if fogo else None
    comb = loop_cruzado(comb, QUADROS, p['sobrepor'] if p['loop'] else 0)
    if fogo:
        emit = loop_cruzado(emit, QUADROS, p['sobrepor'] if p['loop'] else 0)
    sumir = p.get('sumir', 0)
    borda = mascara_bordas(LADO, base=p.get('borda_base', 0.0))
    expo = p['material'].get('exposicao', 1.0)
    sat = p['material'].get('saturacao', 1.0)
    atlas = np.zeros((LINHAS * LADO, COLUNAS * LADO, 4), dtype=np.float32)
    atlas_e = np.zeros((LINHAS * LADO, COLUNAS * LADO, 3), dtype=np.float32) if fogo else None
    for i in range(QUADROS):
        c = comb[i]
        rgb, a = c[..., :3] * expo, np.clip(c[..., 3:4], 0, 1)
        if fogo:
            rgb = saturar(rgb, sat)
            e = compressor(saturar(emit[i] * expo, sat))
            lum_e = np.clip(e.max(axis=2, keepdims=True), 0, 1)
            # fogo também no RGBA: o alfa cobre a chama para o atlas servir sozinho
            a2 = np.maximum(a, np.clip(lum_e * 1.15, 0, 1))
            rgb = compressor(rgb)
        else:
            a2 = a
            rgb = compressor(rgb, 0.85)
        fator = 1.0
        if sumir and i >= QUADROS - sumir:
            fator = (QUADROS - i) / (sumir + 1)
        reto = np.where(a2 > 1e-4, rgb / np.maximum(a2, 1e-4), 0.0)
        r, col = divmod(i, COLUNAS)
        ys, xs = r * LADO, col * LADO
        atlas[ys:ys + LADO, xs:xs + LADO, :3] = srgb(reto)
        atlas[ys:ys + LADO, xs:xs + LADO, 3:] = a2 * fator * borda
        if fogo:
            atlas_e[ys:ys + LADO, xs:xs + LADO] = srgb(e) * fator * borda
    os.makedirs(saida, exist_ok=True)
    arquivos = {}
    img = Image.fromarray((np.clip(atlas, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA')
    caminho = os.path.join(saida, '%s_atlas.png' % nome)
    img.save(caminho, optimize=True)
    arquivos['atlas'] = os.path.basename(caminho)
    if fogo:
        ie = Image.fromarray((np.clip(atlas_e, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')
        caminho_e = os.path.join(saida, '%s_emissao.png' % nome)
        ie.save(caminho_e, optimize=True)
        arquivos['emissao'] = os.path.basename(caminho_e)
    if seis:
        arquivos.update(montar_seis(nome, p, pasta_exr, saida, quadros_render, alfas_brutos, borda,
                                    atlas_e if fogo else None))
    folha_e_gif(nome, img, saida, p)
    arquivos['folha'] = '%s_folha.png' % nome
    arquivos['gif'] = '%s.gif' % nome
    return arquivos


def montar_seis(nome, p, pasta_exr, saida, quadros_render, alfas, borda, atlas_e):
    """Atlas de luz de 6 direções (padrão "six-way lightmap" do VFX Graph/Niagara):
    _6way_a.png RGB = luz vinda da direita, de cima e de trás; A = opacidade.
    _6way_b.png RGB = luz vinda da esquerda, de baixo e da frente; A = emissão (fogo) ou 1.
    Valores LINEARES (não sRGB), por unidade de opacidade, normalizados pelo percentil 99,5."""
    nomes = [n for n, _ in DIRECOES_6]
    canais = {}
    for n in nomes:
        lst = []
        for k, q in enumerate(quadros_render):
            a = alfas[k]
            l = lum(ler_exr(achar_exr(pasta_exr, 'l_' + n, q)))
            lst.append(np.where(a > 2e-3, l / np.maximum(a, 2e-3), 0.0).astype(np.float32))
        canais[n] = loop_cruzado(lst, QUADROS, p['sobrepor'] if p['loop'] else 0)
    # escala só onde a cobertura é boa: nas bordas finas a divisão pela opacidade estoura
    cobre = loop_cruzado(alfas, QUADROS, p['sobrepor'] if p['loop'] else 0)
    amostra = np.concatenate([canais[n][i][::4, ::4][cobre[i][::4, ::4] > 0.3]
                              for n in nomes for i in range(0, QUADROS, 4)])
    escala = float(np.percentile(amostra, 99.0)) if amostra.size else 1.0
    A = np.zeros((LINHAS * LADO, COLUNAS * LADO, 4), dtype=np.float32)
    B = np.zeros_like(A)
    sumir = p.get('sumir', 0)
    for i in range(QUADROS):
        r, col = divmod(i, COLUNAS)
        ys, xs = r * LADO, col * LADO
        fator = (QUADROS - i) / (sumir + 1) if sumir and i >= QUADROS - sumir else 1.0
        for j, n in enumerate(nomes[:3]):
            A[ys:ys + LADO, xs:xs + LADO, j] = canais[n][i] / escala
        for j, n in enumerate(nomes[3:]):
            B[ys:ys + LADO, xs:xs + LADO, j] = canais[n][i] / escala
    # alfa e emissão: os mesmos do atlas de cor
    cor = np.asarray(Image.open(os.path.join(saida, '%s_atlas.png' % nome))).astype(np.float32) / 255
    A[..., 3] = cor[..., 3]
    B[..., 3] = lum(atlas_e) if atlas_e is not None else 1.0
    arq = {}
    for rot, M in (('6way_a', A), ('6way_b', B)):
        caminho = os.path.join(saida, '%s_%s.png' % (nome, rot))
        Image.fromarray((np.clip(M, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGBA').save(caminho, optimize=True)
        arq[rot] = os.path.basename(caminho)
    arq['6way_escala'] = escala
    return arq


def previa(nome, p, pasta_exr, saida, fogo, quadros_render):
    """8 quadros a 256 px sobre o céu de conferência, em 4x2."""
    fundo = fundo_ceu(LADO)
    tela = np.zeros((2 * LADO, 4 * LADO, 3), dtype=np.float32)
    for i, q in enumerate(quadros_render[:8]):
        expo = p['material'].get('exposicao', 1.0)
        sat = p['material'].get('saturacao', 1.0)
        c = ler_exr(achar_exr(pasta_exr, 'comb', q))
        if p.get('seis'):
            c[..., :3] = ler_exr(achar_exr(pasta_exr, 'beleza', q))[..., :3]
        rgb, a = c[..., :3] * expo, np.clip(c[..., 3:4], 0, 1)
        if fogo:
            rgb = saturar(rgb, sat)
            e = compressor(saturar(ler_exr(achar_exr(pasta_exr, 'emit', q))[..., :3] * expo, sat))
            a = np.maximum(a, np.clip(e.max(axis=2, keepdims=True) * 1.15, 0, 1))
            rgb = compressor(rgb)
        else:
            rgb = compressor(rgb, 0.85)
        reto = np.where(a > 1e-4, rgb / np.maximum(a, 1e-4), 0.0)
        comp = srgb(reto) * a + fundo * (1 - a)
        r, col = divmod(i, 4)
        tela[r * LADO:(r + 1) * LADO, col * LADO:(col + 1) * LADO] = comp
    os.makedirs(saida, exist_ok=True)
    Image.fromarray((np.clip(tela, 0, 1) * 255).astype(np.uint8)).save(
        os.path.join(saida, '%s_previa.png' % nome))
    print('[%s] prévia em %s' % (nome, saida), flush=True)


def fundo_ceu(lado):
    """Fundo de conferência: céu de fim de tarde em degradê, para ver fumaça clara e escura."""
    y = np.linspace(0, 1, lado)[:, None]
    topo = np.array([0.42, 0.55, 0.72])
    base = np.array([0.78, 0.74, 0.66])
    g = topo * (1 - y) + base * y
    return np.repeat(g[:, None, :], lado, axis=1).reshape(lado, lado, 3)


def folha_e_gif(nome, atlas, saida, p):
    pequeno = 128
    a = np.asarray(atlas).astype(np.float32) / 255
    folha = np.zeros((LINHAS * pequeno, COLUNAS * pequeno, 3), dtype=np.float32)
    fundo = fundo_ceu(pequeno)
    quadros_gif = []
    for i in range(QUADROS):
        r, c = divmod(i, COLUNAS)
        q = a[r * LADO:(r + 1) * LADO, c * LADO:(c + 1) * LADO]
        q = np.asarray(Image.fromarray((q * 255).astype(np.uint8), 'RGBA')
                       .resize((pequeno, pequeno), Image.LANCZOS)).astype(np.float32) / 255
        comp = q[..., :3] * q[..., 3:] + fundo * (1 - q[..., 3:])
        folha[r * pequeno:(r + 1) * pequeno, c * pequeno:(c + 1) * pequeno] = comp
        quadros_gif.append(Image.fromarray((comp * 255).astype(np.uint8)).resize((192, 192), Image.LANCZOS))
    Image.fromarray((folha * 255).astype(np.uint8)).save(os.path.join(saida, '%s_folha.png' % nome), optimize=True)
    quadros_gif[0].save(os.path.join(saida, '%s.gif' % nome), save_all=True,
                        append_images=quadros_gif[1:], duration=int(1000 / p['fps']),
                        loop=0, optimize=True)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def renderizar(nome, cena, amostras, pasta_exr, fogo, quadros_render, tempos, seis=False):
    configurar_render(cena, amostras, pasta_exr, fogo, seis)
    t0 = time.time()
    for q in quadros_render:
        try:  # --continuar: pula quadro já renderizado
            achar_exr(pasta_exr, 'comb', q)
            if fogo:
                achar_exr(pasta_exr, 'emit', q)
            if seis:
                achar_exr(pasta_exr, 'l_frente', q)
            continue
        except FileNotFoundError:
            pass
        cena.frame_set(q)
        bpy.ops.render.render(write_still=False)
    tempos['render_s'] = round(time.time() - t0, 1)
    print('[%s] render: %.1f s (%d quadros, %d amostras)' %
          (nome, tempos['render_s'], len(quadros_render), amostras), flush=True)


def exportar_vdb(nome, p, cache, res, quadros, destino):
    """Copia o cache OpenVDB do Mantaflow (um arquivo por quadro) para uso como volume
    (Sparse Volume Texture no Unreal). 'noise' tem a densidade e a chama na resolução alta;
    'data' tem o calor (temperatura), a velocidade e a densidade na resolução base."""
    pasta = os.path.join(destino, nome)
    os.makedirs(pasta, exist_ok=True)
    total = 0
    lista = []
    for i, q in enumerate(quadros[:QUADROS]):
        for sub, prefixo, rot in (('noise', 'fluid_noise', 'alta'), ('data', 'fluid_data', 'base')):
            orig = os.path.join(cache, sub, '%s_%04d.vdb' % (prefixo, q))
            if not os.path.exists(orig):
                continue
            alvo = os.path.join(pasta, '%s_%s_%03d.vdb' % (nome, rot, i))
            if os.path.exists(alvo):
                os.remove(alvo)
            try:  # hardlink: não ocupa disco de novo quando a pasta fica no mesmo disco do cache
                os.link(orig, alvo)
            except OSError:
                shutil.copyfile(orig, alvo)
            total += os.path.getsize(alvo)
            lista.append(os.path.basename(alvo))
    dx, dy, dz = p['dominio']
    meta = {
        'preset': nome, 'quadros': min(len(quadros), QUADROS), 'fps': p['fps'], 'loop': p['loop'],
        'nota_loop': 'os VDB não têm o cruzamento do atlas: o loop do volume precisa de mistura no material',
        'unidade': 'metro (o Mantaflow grava a transformação em metros a partir do canto mínimo do domínio)',
        'dominio_m': [dx, dy, dz], 'canto_minimo_m': [-dx / 2, -dy / 2, 0.0],
        'resolucao_base': res, 'ruido_upres': p['ruido'], 'voxel_base_m': max(dx, dy, dz) / res,
        'voxel_alta_m': max(dx, dy, dz) / (res * max(1, p['ruido'])),
        'grids_alta': ['density_noise', 'flame_noise', 'color_r/g/b_noise'],
        'grids_base': ['density', 'heat (temperatura)', 'flame', 'fuel', 'velocity', '...'],
        'precisao': 'meia (half float)', 'bytes': total, 'arquivos': lista,
    }
    with open(os.path.join(pasta, '%s_vdb.json' % nome), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('[%s] VDB: %d arquivos, %.1f MB em %s' % (nome, len(lista), total / 1e6, pasta), flush=True)


def gerar(nome, args):
    global LADO
    p = dict(PRESETS[nome])
    LADO = args.lado or p.get('lado', 256)
    res = args.res or p['res']
    amostras = args.amostras or 128
    if args.rapido:
        res = args.res or min(res, 48)
        amostras = args.amostras or 48
        p['ruido'] = 1
    rng = random.Random(SEMENTE + sum(map(ord, nome)))
    raiz_cache = os.path.join(args.cache, nome)
    cache = os.path.join(raiz_cache, 'sim')
    pasta_exr = os.path.join(raiz_cache, 'exr')
    saida = os.path.join(args.saida, nome) if args.preset == 'todos' else args.saida
    n_render = QUADROS + (p['sobrepor'] if p['loop'] else 0)
    primeiro = p['aquecimento'] + 1
    quadros_render = [primeiro + i * p['passo'] for i in range(n_render)]
    ultimo = quadros_render[-1]
    if args.previa:  # só 8 quadros espalhados, para acertar o visual depressa
        quadros_render = quadros_render[::max(1, len(quadros_render) // 8)][:8]
    fogo = p['material']['fogo']
    tempos = {}

    blend = os.path.join(raiz_cache, 'cena.blend')
    if args.so_render:
        consertar_manta()
        bpy.ops.wm.open_mainfile(filepath=blend)
        cena = bpy.context.scene
        dom = cena.objects['Dominio']
        if not args.continuar:
            shutil.rmtree(pasta_exr, ignore_errors=True)
        os.makedirs(pasta_exr, exist_ok=True)
        vestir(cena, dom, p)
        renderizar(nome, cena, amostras, pasta_exr, fogo, quadros_render, tempos, bool(p.get('seis')))
    elif not args.so_montar:
        for pasta in (cache, pasta_exr):
            shutil.rmtree(pasta, ignore_errors=True)
            os.makedirs(pasta, exist_ok=True)
        consertar_manta()
        cena, dom, em = montar_cena(nome, p, res, cache, rng)
        vestir(cena, dom, p)
        cena.frame_start = 1
        cena.frame_end = ultimo
        ds = dom.modifiers['Fluido'].domain_settings
        ds.cache_frame_start = 1
        ds.cache_frame_end = ultimo
        t0 = time.time()
        bpy.context.view_layer.objects.active = dom
        with bpy.context.temp_override(object=dom, active_object=dom, scene=cena):
            r = bpy.ops.fluid.bake_all()
        if 'FINISHED' not in r:
            raise RuntimeError('bake falhou: %s' % r)
        tempos['simulacao_s'] = round(time.time() - t0, 1)
        print('[%s] simulação: %.1f s (domínio %d, ruído x%d, %d quadros)' %
              (nome, tempos['simulacao_s'], res, p['ruido'], ultimo), flush=True)
        if args.vdb:
            exportar_vdb(nome, p, cache, res, quadros_render, args.vdb)
        if args.manter_cache:
            bpy.ops.wm.save_as_mainfile(filepath=blend)
        renderizar(nome, cena, amostras, pasta_exr, fogo, quadros_render, tempos, bool(p.get('seis')))
        if not args.manter_cache:
            shutil.rmtree(cache, ignore_errors=True)

    if args.previa:
        previa(nome, p, pasta_exr, saida, fogo, quadros_render)
        return
    arquivos = montar(nome, p, pasta_exr, saida, fogo, quadros_render)
    meta = {
        'preset': nome,
        'descricao': p['descricao'],
        'quadros': QUADROS, 'linhas': LINHAS, 'colunas': COLUNAS,
        'lado_quadro_px': LADO, 'atlas_px': [COLUNAS * LADO, LINHAS * LADO],
        'fps_sugerido': p['fps'], 'loop': p['loop'],
        'escala_quadro_m': p['quadro'],
        'base_do_quadro_m': round(p['centro'][2] - p['quadro'] / 2, 3),
        'nota_base': 'altura (em metros) do chão em relação à borda de baixo do quadro é o negativo deste valor; 0 = o emissor está junto da borda de baixo',
        'elevacao_camera_graus': p['elevacao'],
        'alfa': 'reto (não pré-multiplicado); cor em sRGB',
        'emissao': fogo,
        'arquivos': arquivos,
        'simulacao': {'motor': 'Mantaflow (Blender %s, módulo bpy)' % bpy.app.version_string,
                      'dominio_m': list(p['dominio']), 'resolucao': res, 'ruido_upres': p['ruido'],
                      'quadros_simulados': ultimo, 'quadros_renderizados': quadros_render[0:1] + quadros_render[-1:],
                      'amostras_cycles': amostras, 'semente': SEMENTE},
        'tempos': tempos,
        'licenca': 'Conteúdo próprio do estúdio (gerado por simulação física, sem IA, sem asset de terceiros)',
        'gerado_por_ia': False,
        'ferramenta': 'acervo-3d/ferramentas/flipbook_fluido.py',
    }
    with open(os.path.join(saida, '%s.json' % nome), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('[%s] pronto em %s' % (nome, saida), flush=True)


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--preset', required=True, choices=list(PRESETS) + ['todos'])
    ap.add_argument('--saida', required=True)
    ap.add_argument('--res', type=int, default=0)
    ap.add_argument('--lado', type=int, default=0,
                    help='lado do quadro em px (256 -> atlas 2048; 512 -> atlas 4096); padrão do preset')
    ap.add_argument('--vdb', default='',
                    help='pasta onde copiar a simulação em OpenVDB por quadro (densidade, chama, calor)')
    ap.add_argument('--amostras', type=int, default=0)
    ap.add_argument('--rapido', action='store_true')
    ap.add_argument('--cache', default=os.path.join(os.environ.get('TMPDIR', '/tmp'), 'flipbook_fluido'))
    ap.add_argument('--so-montar', dest='so_montar', action='store_true')
    ap.add_argument('--previa', action='store_true',
                    help='renderiza só 8 quadros e grava <preset>_previa.png (sem atlas)')
    ap.add_argument('--so-render', dest='so_render', action='store_true',
                    help='refaz material, luz e render sobre o bake guardado por --manter-cache')
    ap.add_argument('--continuar', action='store_true',
                    help='com --so-render, mantém os EXR já feitos e renderiza só os que faltam')
    ap.add_argument('--manter-cache', dest='manter_cache', action='store_true')
    args = ap.parse_args(argv)
    nomes = list(PRESETS) if args.preset == 'todos' else [args.preset]
    for nome in nomes:
        gerar(nome, args)


if __name__ == '__main__':
    main()
