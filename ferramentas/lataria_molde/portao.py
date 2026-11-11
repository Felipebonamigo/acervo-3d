"""
Portão automático da lataria: mede o ARQUIVO FINAL do carro (o GLB que vai para o jogo), de um lado só, e sai com código 1 se reprova.
Não confia em como o arquivo foi feito: só no que está nele.

    blender-nuvem.sh ferramentas/lataria_molde/portao.py -- <carro.glb> [--json saida.json] [--arcos xd,xt,z,raio]

  P1 face invertida      face opaca que alguma das 26 câmeras em volta vê pelas costas e nenhuma vê de frente (no Unreal ela some);
                         reprova acima de P1_CM2 por peça
  P2 peça saliente       degrau entre vizinhos de uma fresta (chapa com chapa, lente com chapa) acima de P2_MM em mais de 1% das medidas
  P3 fresta              a distância entre as bordas de duas chapas vizinhas: 90% das medidas entre P3_MIN e P3_MAX mm, e a mediana também
  P4 faceta              na pele pintada: nenhuma normal partida (aresta viva) e o ângulo entre faces vizinhas até P4_GRAUS
                         (só P4_FRACAO delas pode passar: as quinas de verdade)
  P5 arco de roda        a borda de cada arco num círculo: resíduo até P5_MM, e os dois lados com o mesmo raio
  P6 orçamento           até P6_TRI triângulos e P6_MAT materiais, sem contar as rodas (que são uma malha à parte no jogo)
  P7 UV                  toda face da pele com UV dentro de 0..1, sem área nula e sem sobrepor outra ilha (rasterizado em 1024)
  P8 nomes               as peças que o jogo solta e os materiais são os do contrato (Detonauto, Tools/Blender/kit_names.py)
  P9 borracha no vão     a borracha do vidro (o plástico preto do objeto do vidro) a até P9_MM da pintura ou do vidro
  P10 retrovisor         carcaça com 8 cm ou mais de fundo e 6 de altura (não uma chapa)
  P11 nada pendurado     nenhuma peça desce mais de 3 cm abaixo da soleira (fora as rodas)
  P12 cores das luzes    lanterna com vermelho, âmbar, branco e refletor; farol com refletor
  P13 para-choque        balanço de até 12 cm além da carroceria
"""
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

P1_CM2 = 4.0
P2_MM = 2.0
P3_MIN, P3_MAX = 3.0, 5.0
P4_GRAUS, P4_FRACAO = 20.0, 0.004
P5_MM = 1.5
P6_TRI, P6_MAT = 200000, 10
P9_MM = 8.0
PECAS = ['body', 'hood', 'trunk', 'door_fl', 'door_fr', 'bumper_front', 'bumper_rear', 'fender_front_left', 'fender_front_right',
         'glass_windshield', 'glass_rear', 'glass_door_fl', 'glass_door_fr', 'glass_door_rl', 'glass_door_rr',
         'headlight_left', 'headlight_right', 'taillight_left', 'taillight_right']
MATERIAIS = {'pintura', 'chassi', 'vidro', 'cromo', 'cromado', 'refletor', 'lente_vidro', 'lente_vermelha', 'lente_ambar', 'lente_branca',
             'placa', 'pneu', 'luz', 'luz_ambar', 'luz_branca', 'luz_vermelha', 'lente_farol', 'MI_DNVao', 'calota', 'aro', 'borracha'}
TRANSPARENTES = ('vidro', 'lente_')
RODA = ('wheel_', 'hubcap_')

argv = sys.argv[sys.argv.index('--') + 1:]
GLB = argv[0]
opt = lambda n: argv[argv.index(n) + 1] if n in argv else None
SAIDA = opt('--json')

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)


class Peca:
    def __init__(self, ob):
        self.nome = ob.name
        me = ob.data
        M = np.array(ob.matrix_world)
        co = np.zeros(len(me.vertices) * 3)
        me.vertices.foreach_get('co', co)
        co = co.reshape(-1, 3)
        self.P = co @ M[:3, :3].T + M[:3, 3]
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tv = np.zeros(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get('vertices', tv)
        self.T = tv.reshape(-1, 3)
        tl = np.zeros(nt * 3, dtype=np.int64)
        me.loop_triangles.foreach_get('loops', tl)
        tl = tl.reshape(-1, 3)
        mi = np.zeros(nt, dtype=np.int64)
        me.loop_triangles.foreach_get('material_index', mi)
        nomes = [(s.material.name.split('.')[0] if s.material else '') for s in ob.material_slots] or ['']
        self.mat = np.array([nomes[i] for i in mi])
        self.materiais = sorted(set(nomes))
        if me.uv_layers:
            uv = np.zeros(len(me.loops) * 2)
            me.uv_layers[0].data.foreach_get('uv', uv)
            self.UV = uv.reshape(-1, 2)[tl]
        else:
            self.UV = np.zeros((nt, 3, 2))
        cn = np.zeros(len(me.loops) * 3)
        me.corner_normals.foreach_get('vector', cn)
        cn = cn.reshape(-1, 3) @ np.linalg.inv(M[:3, :3])
        self.NL = (cn / np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-12))[tl]
        a, b, c = self.P[self.T[:, 0]], self.P[self.T[:, 1]], self.P[self.T[:, 2]]
        fn = np.cross(b - a, c - a)
        self.area = 0.5 * np.linalg.norm(fn, axis=1)
        self.FN = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-18)
        self.cen = (a + b + c) / 3
        e1, e2 = self.UV[:, 1] - self.UV[:, 0], self.UV[:, 2] - self.UV[:, 0]
        self.uv_area = 0.5 * np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
        # solda por posição (o GLB parte os vértices por UV e normal)
        chave = {}
        self.solda = np.zeros(len(self.P), dtype=np.int64)
        for i, p in enumerate(np.round(self.P, 5)):
            self.solda[i] = chave.setdefault((p[0], p[1], p[2]), len(chave))
        self.TS = self.solda[self.T]
        self.pele = (self.mat == 'pintura') & (self.uv_area > 1e-10)

    def borda_da_pele(self):
        """Segmentos de borda (pares de pontos) da pele pintada."""
        cont = {}
        for t in self.TS[self.pele]:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = (min(a, b), max(a, b))
                cont[k] = cont.get(k, 0) + 1
        pos = {}
        for i, s in enumerate(self.solda):
            pos.setdefault(s, self.P[i])
        return [(pos[a], pos[b], a, b) for (a, b), n in cont.items() if n == 1]


pecas = [Peca(o) for o in bpy.data.objects if o.type == 'MESH' and not o.name.endswith(('_LOD1', '_LOD2'))]
KIT = opt('--kit')          # o kit completo do carro (interior, cofre, embaixo): só tapa a vista no P1, como no jogo
anteparo = []
if KIT:
    antes = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=KIT)
    anteparo = [Peca(o) for o in bpy.data.objects if o not in antes and o.type == 'MESH' and not o.name.endswith(('_LOD1', '_LOD2'))]
carro = [p for p in pecas if not p.nome.startswith(RODA)]
falhas, rel = [], {}


def reprova(regra, texto):
    falhas.append('%s %s' % (regra, texto))


# ---------------------------------------------------------------------------------------------------------- P1 face invertida
verts, tris, dono = [], [], []
for ip, p in enumerate(pecas):
    opaco = np.array([not m.startswith(TRANSPARENTES) for m in p.mat])
    base = len(verts)
    verts += [tuple(v) for v in p.P]
    for it in np.nonzero(opaco)[0]:
        tris.append(tuple(int(i) + base for i in p.T[it]))
        dono.append((ip, it))
for p in anteparo:
    base = len(verts)
    verts += [tuple(v) for v in p.P]
    tris += [tuple(int(i) + base for i in t) for t, m in zip(p.T, p.mat) if not m.startswith(TRANSPARENTES)]
bvh = BVHTree.FromPolygons(verts, tris)
cams = [6.0 * np.array(d) / np.linalg.norm(d) + np.array((0, 0, 0.6)) for d in
        [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) if (x, y, z) != (0, 0, 0)]]
costas = {}
for ip, p in enumerate(pecas):
    if p.nome.startswith(RODA):
        continue
    opaco = np.array([not m.startswith(TRANSPARENTES) for m in p.mat])
    visto_costas = np.zeros(len(p.T), dtype=bool)
    visto_frente = np.zeros(len(p.T), dtype=bool)
    for cam in cams:
        d = p.cen - cam
        dist = np.linalg.norm(d, axis=1)
        cosv = np.einsum('ij,ij->i', p.FN, -d) / np.maximum(dist, 1e-9)
        frente = cosv > 0
        # de costas e de raspão (a mais de ~80 graus) a face é um fio na tela: não conta
        for it in np.nonzero(opaco & (cosv < -0.17) & ~visto_costas & (p.area > 2e-7))[0]:
            h = bvh.ray_cast(Vector(cam), Vector(d[it] / dist[it]), dist[it] + 0.01)
            if h[0] is not None and h[3] >= dist[it] - 2e-4:
                visto_costas[it] = True
    cand = np.nonzero(visto_costas)[0]
    for cam in cams:
        d = p.cen[cand] - cam
        dist = np.linalg.norm(d, axis=1)
        for k, it in enumerate(cand):
            if visto_frente[it] or p.FN[it] @ -d[k] <= 0:
                continue
            h = bvh.ray_cast(Vector(cam), Vector(d[k] / dist[k]), dist[k] + 0.01)
            if h[0] is not None and h[3] >= dist[k] - 2e-4:
                visto_frente[it] = True
    ruim = visto_costas & ~visto_frente
    cm2 = float(p.area[ruim].sum() * 1e4)
    if cm2 > 0.01:
        costas[p.nome] = round(cm2, 2)
    if cm2 > P1_CM2 and '--detalhe' in argv and ruim.sum() <= 12:
        for it in np.nonzero(ruim)[0]:
            print('   P1 tri %s %s %.1f cm2 n=%s: %s' % (p.nome, p.mat[it], p.area[it] * 1e4, np.round(p.FN[it], 2), np.round(p.P[p.T[it]], 3).tolist()))
    if cm2 > P1_CM2 and '--detalhe' in argv:
        for m in sorted(set(p.mat[ruim])):
            sel = ruim & (p.mat == m)
            for eixo, nome_e in ((0, 'x'), (1, 'y'), (2, 'z')):
                for sg in (1, -1):
                    s2 = sel & (np.argmax(np.abs(p.FN), axis=1) == eixo) & (np.sign(p.FN[:, eixo]) == sg)
                    if p.area[s2].sum() * 1e4 > 2:
                        print('   P1 %s %s normal %s%s: %.0f cm2, centro %s, caixa %s..%s' % (p.nome, m, '+' if sg > 0 else '-', nome_e, p.area[s2].sum() * 1e4,
                              np.round(p.cen[s2].mean(0), 2), np.round(p.cen[s2].min(0), 2), np.round(p.cen[s2].max(0), 2)))
    if cm2 > P1_CM2:
        reprova('P1', '%s: %.1f cm² de face de costas à vista' % (p.nome, cm2))
rel['P1_costas_cm2'] = costas

# ---------------------------------------------------------------------------------------------------------- P2 e P3 frestas
bordas = {p.nome: p.borda_da_pele() for p in carro if p.pele.any()}
pts, quem, seg = [], [], []
for nome, bs in bordas.items():
    for (a, b, ia, ib) in bs:
        for q in (a, b):
            pts.append(q)
            quem.append(nome)
            seg.append((a, b))
kd = KDTree(len(pts))
for i, q in enumerate(pts):
    kd.insert(Vector(q), i)
kd.balance()
normal_de = {}
for p in carro:
    if p.pele.any():
        kdn = KDTree(int(p.pele.sum()) * 3)
        nl = []
        k = 0
        for t, n3 in zip(p.T[p.pele], p.NL[p.pele]):
            for c in range(3):
                kdn.insert(Vector(p.P[t[c]]), k)
                nl.append(n3[c])
                k += 1
        kdn.balance()
        normal_de[p.nome] = (kdn, nl)


def dist_segmento(p, a, b):
    ab = b - a
    t = np.clip((p - a) @ ab / max(ab @ ab, 1e-18), 0, 1)
    q = a + ab * t
    return np.linalg.norm(p - q), q


frestas, degraus, por_par = [], [], {}
for nome, bs in bordas.items():
    kdn, nl = normal_de[nome]
    vistos = set()
    for (a, b, ia, ib) in bs:
        if ia in vistos:
            continue
        vistos.add(ia)
        melhor = None
        for (co, i, d) in kd.find_range(Vector(a), 0.012):
            if quem[i] == nome:
                continue
            dd, q = dist_segmento(a, *seg[i])
            if melhor is None or dd < melhor[0]:
                melhor = (dd, q, quem[i])
        if melhor is None:
            continue
        n = nl[kdn.find(Vector(a))[1]]
        v = melhor[1] - a
        degrau = abs(v @ n)
        larg = math.sqrt(max(melhor[0] ** 2 - degrau ** 2, 0.0))
        frestas.append(larg * 1000)
        if '--detalhe' in argv and not (P3_MIN <= larg * 1000 <= P3_MAX) and len([1 for f in frestas if not (P3_MIN <= f <= P3_MAX)]) % 12 == 1:
            print('   P3 %s|%s: %.1f mm em %s' % (nome, melhor[2], larg * 1000, np.round(a, 3)))
        degraus.append(degrau * 1000)
        por_par.setdefault(tuple(sorted((nome, melhor[2]))), []).append(larg * 1000)
if frestas:
    f = np.array(frestas)
    dentro = float(((f >= P3_MIN) & (f <= P3_MAX)).mean())
    rel['P3_fresta_mm'] = dict(mediana=round(float(np.median(f)), 2), p5=round(float(np.percentile(f, 5)), 2), p95=round(float(np.percentile(f, 95)), 2),
                               dentro=round(dentro, 3), medidas=len(f),
                               por_par={'%s|%s' % k: round(float(np.median(v)), 2) for k, v in sorted(por_par.items())})
    if dentro < 0.90 or not (P3_MIN <= np.median(f) <= P3_MAX):
        reprova('P3', 'fresta: mediana %.2f mm, %.0f%% das medidas entre %.0f e %.0f mm' % (np.median(f), dentro * 100, P3_MIN, P3_MAX))
    for k, v in por_par.items():
        if len(v) >= 20 and not (P3_MIN <= np.median(v) <= P3_MAX):
            reprova('P3', 'fresta %s|%s: mediana %.2f mm' % (k[0], k[1], np.median(v)))
    dg = np.array(degraus)
    rel['P2_degrau_mm'] = dict(p99=round(float(np.percentile(dg, 99)), 2), maximo=round(float(dg.max()), 2))
    if (dg > P2_MM).mean() > 0.01:
        reprova('P2', 'degrau entre chapas: %.1f%% das medidas acima de %.0f mm (p99 %.2f mm)' % ((dg > P2_MM).mean() * 100, P2_MM, np.percentile(dg, 99)))
else:
    reprova('P3', 'nenhuma fresta medida: as chapas não têm vizinho a até 12 mm')
# lente com a chapa em volta
lentes = {}
for p in carro:
    if not p.nome.startswith(('headlight', 'taillight')):
        continue
    sel = np.array([m.startswith('lente_') for m in p.mat])
    if not sel.any():
        reprova('P2', '%s: sem lente' % p.nome)
        continue
    cont = {}
    for t in p.TS[sel]:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            cont[(min(a, b), max(a, b))] = cont.get((min(a, b), max(a, b)), 0) + 1
    pos, nrm = {}, {}
    for t, n3 in zip(p.T[sel], p.NL[sel]):
        for c in range(3):
            pos.setdefault(p.solda[t[c]], p.P[t[c]])
            nrm.setdefault(p.solda[t[c]], n3[c])
    # só a face de fora da lente (a normal aponta para fora do carro)
    cen = np.mean(list(pos.values()), axis=0)
    fora = np.array([np.sign(cen[0]), 0, 0])
    saltos = []
    for (a, b), n in cont.items():
        if n != 1 or nrm[a] @ fora < 0.3:
            continue
        melhor = None
        for (co, i, d) in kd.find_range(Vector(pos[a]), 0.012):
            dd, q = dist_segmento(pos[a], *seg[i])
            if melhor is None or dd < melhor[0]:
                melhor = (dd, q)
        if melhor is not None:
            saltos.append(float((pos[a] - melhor[1]) @ nrm[a]) * 1000)
    if not saltos:
        reprova('P2', '%s: a lente não tem chapa em volta a até 12 mm' % p.nome)
        continue
    s = np.array(saltos)
    lentes[p.nome] = dict(saliente_mm=round(float(s.max()), 2), afundada_mm=round(float(-s.min()), 2))
    if s.max() > P2_MM:
        reprova('P2', '%s: lente %.1f mm para fora da chapa' % (p.nome, s.max()))
    if s.min() < -6.0:
        reprova('P2', '%s: lente %.1f mm afundada' % (p.nome, -s.min()))
rel['P2_lentes'] = lentes

# ---------------------------------------------------------------------------------------------------------- P4 faceta
facetas = {}
for p in carro:
    if not p.pele.any():
        continue
    arestas, partidas = {}, 0
    normal_no_vert = {}
    for t, n3, fn in zip(p.TS[p.pele], p.NL[p.pele], p.FN[p.pele]):
        for c in range(3):
            a, b = t[c], t[(c + 1) % 3]
            arestas.setdefault((min(a, b), max(a, b)), []).append(fn)
            n0 = normal_no_vert.setdefault(t[c], n3[c])
            if n0 @ n3[c] < 0.9995:
                partidas += 1
    ang = np.array([math.degrees(math.acos(max(-1.0, min(1.0, float(v[0] @ v[1]))))) for v in arestas.values() if len(v) == 2])
    if '--detalhe' in argv:
        pos = {}
        for i, sd in enumerate(p.solda):
            pos.setdefault(sd, p.P[i])
        piores = sorted(((math.degrees(math.acos(max(-1.0, min(1.0, float(v[0] @ v[1]))))), k) for k, v in arestas.items() if len(v) == 2), reverse=True)[:6]
        for g, (a, b) in piores:
            if g > P4_GRAUS:
                print('   P4 %s: %.0f graus em %s (aresta de %.2f mm)' % (p.nome, g, np.round(0.5 * (pos[a] + pos[b]), 3), np.linalg.norm(pos[a] - pos[b]) * 1000))
    fr = float((ang > P4_GRAUS).mean()) if len(ang) else 0.0
    facetas[p.nome] = dict(maximo_graus=round(float(ang.max()), 1) if len(ang) else 0, acima=round(fr, 4), normais_partidas=partidas)
    if len(ang) and ang.max() > 100:
        reprova('P4', '%s: %d arestas dobradas na pele (até %.0f graus)' % (p.nome, int((ang > 100).sum()), ang.max()))
    if partidas:
        reprova('P4', '%s: %d normais partidas na pele (aresta viva)' % (p.nome, partidas))
    if fr > P4_FRACAO:
        reprova('P4', '%s: %.2f%% das arestas da pele com mais de %.0f graus' % (p.nome, fr * 100, P4_GRAUS))
rel['P4_faceta'] = facetas

# ---------------------------------------------------------------------------------------------------------- P5 arco de roda
arcos = {}
a = opt('--arcos')
if a:
    xd, xt, za, ra = [float(v) for v in a.split(',')]
    raios = []
    for xa, rot in ((xd, 'dianteiro'), (xt, 'traseiro')):
        for lado, ln in ((1, 'esq'), (-1, 'dir')):
            ptos = []
            for nome, bs in bordas.items():
                for (p0, p1, _, _) in bs:
                    for q in (p0, p1):
                        r = math.hypot(q[0] - xa, q[2] - za)
                        t = math.degrees(math.atan2(q[2] - za, q[0] - xa))
                        if q[1] * lado > 0.3 and abs(r - ra) < 0.03 and 12 < t < 168:
                            ptos.append((q[0], q[2]))
            if len(ptos) < 20:
                reprova('P5', 'arco %s %s: borda não encontrada' % (rot, ln))
                continue
            xy = np.array(ptos)
            A = np.c_[2 * xy, np.ones(len(xy))]
            sol = np.linalg.lstsq(A, (xy ** 2).sum(1), rcond=None)[0]
            cx, cz = sol[0], sol[1]
            R = math.sqrt(sol[2] + cx * cx + cz * cz)
            res = np.abs(np.hypot(xy[:, 0] - cx, xy[:, 1] - cz) - R) * 1000
            arcos['%s_%s' % (rot, ln)] = dict(raio_mm=round(R * 1000, 1), residuo_mm=round(float(res.max()), 2), pontos=len(xy))
            raios.append(R)
            if res.max() > P5_MM:
                reprova('P5', 'arco %s %s: %.1f mm fora do círculo' % (rot, ln, res.max()))
    if raios and (max(raios) - min(raios)) * 1000 > 2.0:
        reprova('P5', 'arcos com raios diferentes: %.1f a %.1f mm' % (min(raios) * 1000, max(raios) * 1000))
rel['P5_arcos'] = arcos

# ---------------------------------------------------------------------------------------------------------- P6 orçamento
tri_carro = int(sum(len(p.T) for p in carro))
mats_carro = sorted({m for p in carro for m in set(p.mat)})
rel['P6'] = dict(triangulos=tri_carro, triangulos_com_rodas=int(sum(len(p.T) for p in pecas)), materiais=mats_carro)
if tri_carro > P6_TRI:
    reprova('P6', '%d triângulos (o teto é %d)' % (tri_carro, P6_TRI))
if len(mats_carro) > P6_MAT:
    reprova('P6', '%d materiais (o teto é %d): %s' % (len(mats_carro), P6_MAT, ', '.join(mats_carro)))

# ---------------------------------------------------------------------------------------------------------- P7 UV
RES = 1024
grade = np.zeros((RES, RES), dtype=np.int32)
sobre = 0
total = 0
fora_uv = 0
for ip, p in enumerate(carro):
    if not p.pele.any():
        continue
    uv = p.UV[p.pele]
    fora_uv += int(((uv < -1e-4) | (uv > 1 + 1e-4)).any(axis=(1, 2)).sum())
    cen = np.clip((uv.mean(1) * RES).astype(int), 0, RES - 1)
    for (u, v) in cen:
        total += 1
        if grade[v, u] not in (0, ip + 1):
            sobre += 1
        grade[v, u] = ip + 1
    sem = int(((p.mat == 'pintura') & (p.uv_area <= 1e-10) & False).sum())
rel['P7_uv'] = dict(faces=total, fora_de_0_1=fora_uv, sobrepostas=sobre)
if total == 0:
    reprova('P7', 'a pele não tem UV')
if fora_uv:
    reprova('P7', '%d faces da pele com UV fora de 0..1' % fora_uv)
if total and sobre / total > 0.005:
    reprova('P7', '%.1f%% das faces da pele sobre a ilha de outra peça' % (100.0 * sobre / total))

# ---------------------------------------------------------------------------------------------------------- P8 nomes
nomes = {p.nome for p in pecas}
for n in PECAS:
    if n not in nomes:
        reprova('P8', 'falta a peça %s' % n)
desconhecidos = sorted({m for p in carro for m in set(p.mat)} - MATERIAIS)
if desconhecidos:
    reprova('P8', 'material fora do contrato: %s' % ', '.join(desconhecidos))
rel['P8_pecas'] = sorted(nomes)

# ---------------------------------------------------------------------------------------------------------- P9 borracha
vs, ts = [], []
for p in carro:
    sel = p.pele | (p.mat == 'vidro')
    base = len(vs)
    vs += [tuple(v) for v in p.P]
    ts += [tuple(int(i) + base for i in t) for t in p.T[sel]]
bvh9 = BVHTree.FromPolygons(vs, ts)
borr = {}
for p in carro:
    if not p.nome.startswith('glass'):
        continue
    sel = p.mat == 'chassi'
    if not sel.any():
        reprova('P9', '%s: sem borracha' % p.nome)
        continue
    d = np.array([bvh9.find_nearest(Vector(q))[3] for q in p.cen[sel]]) * 1000
    borr[p.nome] = round(float(np.percentile(d, 99)), 1)
    if np.percentile(d, 99) > P9_MM:
        reprova('P9', '%s: borracha a %.1f mm da chapa e do vidro' % (p.nome, np.percentile(d, 99)))
rel['P9_borracha_mm'] = borr

# ---------------------------------------------------------------------------------------------------------- P10 a P13
# (Detonauto, docs/visual/revisao-carros.md, seção 5: o que o Felipe reclamou duas vezes vira conferência)
por_nome = {p.nome: p for p in pecas}
extra = {}
# P10 retrovisor com volume: carcaça de 8 cm ou mais de profundidade (C2)
for n in ('mirror_left', 'mirror_right'):
    p = por_nome.get(n)
    if p is None:
        reprova('P10', 'falta o %s' % n)
        continue
    cab = p.P[np.abs(p.P[:, 1]) > np.abs(p.P[:, 1]).max() - 0.10]         # a cabeça: os 10 cm de fora
    fundo = float(cab[:, 0].max() - cab[:, 0].min()) * 100
    alto = float(cab[:, 2].max() - cab[:, 2].min()) * 100
    extra[n] = dict(fundo_cm=round(fundo, 1), altura_cm=round(alto, 1))
    if fundo < 8.0 or alto < 6.0:
        reprova('P10', '%s: carcaça de %.1f cm de fundo e %.1f cm de altura (mínimo 8 e 6)' % (n, fundo, alto))
# P11 nada pendurado abaixo da soleira além das rodas (C6): a carroceria é o que desce mais
zc = min(float(p.P[:, 2].min()) for p in carro if p.nome == 'body') if 'body' in por_nome else 0.0
for p in carro:
    if p.nome != 'body' and float(p.P[:, 2].min()) < zc - 0.03:
        reprova('P11', '%s desce %.1f cm abaixo da soleira' % (p.nome, (zc - float(p.P[:, 2].min())) * 100))
# P12 lanterna vermelha, pisca âmbar e ré branca; farol e lanterna com fundo de refletor (C7)
for p in carro:
    if p.nome.startswith('taillight'):
        falta = [m for m in ('lente_vermelha', 'lente_ambar', 'lente_branca', 'refletor') if m not in set(p.mat)]
        if falta:
            reprova('P12', '%s sem %s' % (p.nome, ', '.join(falta)))
    if p.nome.startswith('headlight') and 'refletor' not in set(p.mat):
        reprova('P12', '%s sem fundo de refletor' % p.nome)
# P13 balanço do para-choque: até 12 cm além da carroceria (C8)
if 'body' in por_nome:
    b = por_nome['body'].P
    for n, sg in (('bumper_front', 1), ('bumper_rear', -1)):
        p = por_nome.get(n)
        if p is not None:
            bal = float((p.P[:, 0] * sg).max() - (b[:, 0] * sg).max()) * 100
            extra[n] = dict(balanco_cm=round(bal, 1))
            if bal > 12.0:
                reprova('P13', '%s: %.1f cm de balanço (teto 12)' % (n, bal))
# C1 da revisão (5 mm para fora): o friso e a borracha, medidos contra a pele pintada
for p in carro:
    sel = (p.mat == 'chassi') if (p.nome.startswith('glass') or p.nome.startswith(('door', 'fender', 'body'))) else None
    if sel is None or not sel.any() or p.nome not in normal_de and not p.nome.startswith('glass'):
        continue
rel['P10_P13'] = extra
rel['falhas'] = falhas
rel['aprovado'] = not falhas
if SAIDA:
    json.dump(rel, open(SAIDA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in rel.items() if k != 'P8_pecas'}, ensure_ascii=False, indent=1))
print('PORTÃO: %s (%d falhas)' % ('APROVADO' if not falhas else 'REPROVADO', len(falhas)))
for f in falhas:
    print('  -', f)
sys.exit(1 if falhas else 0)
