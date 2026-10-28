"""Detalhes paramétricos da carroceria limpa: para-choques de plástico, maçanetas e palhetas do limpador (bmesh)."""
import numpy as np
import bmesh
from mathutils import Vector


def perfil_arredondado(prof, alt, r, n=4):
    """Retângulo de cantos redondos no plano (s = para fora, t = para cima), centrado; devolve pontos (s, t) em ordem."""
    pts = []
    cx, cy = prof / 2 - r, alt / 2 - r
    for k, (sx, sy, a0) in enumerate(((1, 1, 0), (-1, 1, np.pi / 2), (-1, -1, np.pi), (1, -1, 3 * np.pi / 2))):
        for i in range(n + 1):
            a = a0 + (np.pi / 2) * i / n
            pts.append((sx * cx + r * np.cos(a), sy * cy + r * np.sin(a)))
    return np.array(pts)


def varrer(bm, caminho, perfil, z0, material, fechar_pontas=True):
    """Varre um perfil (s, t) ao longo de um caminho em planta (x, y) na altura z0; s = normal horizontal para fora do caminho."""
    P = np.asarray(caminho, float)
    T = np.gradient(P, axis=0)
    T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
    N = np.stack([-T[:, 1], T[:, 0]], 1)               # para a esquerda do sentido (caminho anti-horário: para fora)
    aneis = []
    for i in range(len(P)):
        anel = [bm.verts.new(Vector((P[i, 0] + N[i, 0] * s, P[i, 1] + N[i, 1] * s, z0 + t))) for s, t in perfil]
        aneis.append(anel)
    faces = []
    for i in range(len(P) - 1):
        a, b = aneis[i], aneis[i + 1]
        for j in range(len(perfil)):
            f = bm.faces.new((a[j], b[j], b[(j + 1) % len(perfil)], a[(j + 1) % len(perfil)]))
            f.material_index = material
            f.smooth = True
            faces.append(f)
    if fechar_pontas:
        for anel in (aneis[0][::-1], aneis[-1]):
            f = bm.faces.new(anel)
            f.material_index = material
            faces.append(f)
    return faces


def caminho_parachoque(x_face, y_lado, x_fim, sinal, n=40, r=0.14):
    """Planta da linha de centro do para-choque: lado esquerdo, canto, reta na face, canto, lado direito (anti-horário visto de cima:
    a normal da varredura fica para fora). sinal +1 frente, -1 trás."""
    def frente(xf, yl, xe):
        pts = [(xe + (xf - r - xe) * t, yl) for t in np.linspace(0, 1, 8)]
        pts += [(xf - r + r * np.cos(a), yl - r + r * np.sin(a)) for a in np.linspace(np.pi / 2, 0, 10)[1:]]
        pts += [(xf, (yl - r) - 2 * (yl - r) * t) for t in np.linspace(0, 1, n)[1:]]
        pts += [(xf - r + r * np.cos(a), -(yl - r) + r * np.sin(a)) for a in np.linspace(0, -np.pi / 2, 10)[1:]]
        pts += [(xf - r + (xe - (xf - r)) * t, -yl) for t in np.linspace(0, 1, 8)[1:]]
        return np.array(pts)
    if sinal > 0:
        return frente(x_face, y_lado, x_fim)
    P = frente(-x_face, y_lado, -x_fim)
    P[:, 0] *= -1
    return P[::-1]


def parachoque(bm, x_face, y_lado, x_fim, sinal, material, z_topo=0.49, alt=0.12, prof=0.075):
    perfil = perfil_arredondado(prof, alt, 0.022)
    cam = caminho_parachoque(x_face - sinal * prof / 2, y_lado - prof / 2, x_fim, sinal)
    return varrer(bm, cam, perfil, z_topo - alt / 2, material)


def caixa(bm, centro, dx, dy, dz, material, r=0.004):
    bmesh.ops.create_cube(bm, size=1.0)
    novos = [v for v in bm.verts if not v.tag]
    for v in novos:
        v.co = Vector((centro[0] + v.co.x * dx, centro[1] + v.co.y * dy, centro[2] + v.co.z * dz))
        v.tag = True
    faces = [f for f in bm.faces if all(v in novos for v in f.verts)]
    for f in faces:
        f.material_index = material
    return faces


def macaneta(bm, x, y_chapa, z, lado, material):
    """Puxador: base chata e alça; para fora da chapa em y."""
    caixa(bm, (x, y_chapa + lado * 0.006, z), 0.13, 0.012, 0.03, material)
    caixa(bm, (x + 0.015, y_chapa + lado * 0.017, z + 0.004), 0.085, 0.012, 0.012, material)


def limpador(bm, base, ponta, normal, material, largura=0.03, esp=0.012):
    """Braço + palheta: caixa fina deitada na superfície, da base à ponta (3D), levantada 8 mm pela normal."""
    base = np.array(base, float)
    ponta = np.array(ponta, float)
    e1 = ponta - base
    L = np.linalg.norm(e1)
    e1 /= L
    n = np.array(normal, float)
    n /= np.linalg.norm(n)
    e2 = np.cross(n, e1)
    e2 /= np.linalg.norm(e2)
    e3 = np.cross(e1, e2)
    m = 0.5 * (base + ponta) + e3 * (esp / 2 + 0.008)
    bmesh.ops.create_cube(bm, size=1.0)
    novos = [v for v in bm.verts if not v.tag]
    for v in novos:
        v.co = Vector(m + e1 * (v.co.x * L) + e2 * (v.co.y * largura) + e3 * (v.co.z * esp))
        v.tag = True
    for f in [f for f in bm.faces if all(v in novos for v in f.verts)]:
        f.material_index = material


def lanterna(bm, sinal, box, mats, segmentos=None):
    """Lente retangular no bolso: moldura cromada de 8 mm e a lente (convexa de leve), em segmentos verticais por material."""
    x0, x1, y0, y1, z0, z1 = box
    xf = (x1 - 0.004) if sinal > 0 else (x0 + 0.004)          # face de fora, logo dentro da boca do bolso
    prof = 0.03
    m_crom, m_lente = mats[0], mats[1]
    seg = segmentos or [(0.0, 1.0, m_lente)]
    # moldura: anel chato entre o bolso e a lente
    ins = 0.003
    e = 0.008
    def quad(p, mat):
        f = bm.faces.new([bm.verts.new(Vector(q)) for q in p])
        f.material_index = mat
        f.smooth = False
        return f
    Y0, Y1, Z0, Z1 = y0 + ins, y1 - ins, z0 + ins, z1 - ins
    anel_ext = [(xf, Y0, Z0), (xf, Y1, Z0), (xf, Y1, Z1), (xf, Y0, Z1)]
    anel_int = [(xf, Y0 + e, Z0 + e), (xf, Y1 - e, Z0 + e), (xf, Y1 - e, Z1 - e), (xf, Y0 + e, Z1 - e)]
    for k in range(4):
        a, b = anel_ext[k], anel_ext[(k + 1) % 4]
        c, dd = anel_int[(k + 1) % 4], anel_int[k]
        quad([a, b, c, dd] if sinal > 0 else [dd, c, b, a], m_crom)
    # lente: segmentos ao longo de y, levantada 6 mm no meio
    xl = xf + sinal * 0.004
    for (u0, u1, mat) in seg:
        ya, yb = Y0 + e + (Y1 - Y0 - 2 * e) * u0, Y0 + e + (Y1 - Y0 - 2 * e) * u1
        p = [(xl, ya, Z0 + e), (xl, yb, Z0 + e), (xl, yb, Z1 - e), (xl, ya, Z1 - e)]
        quad(p if sinal > 0 else p[::-1], mat)
    # fundo e paredes da lente para trás (tapa o bolso)
    xb = xf - sinal * prof
    paredes = [((xl, Y0 + e, Z0 + e), (xl, Y1 - e, Z0 + e), (xb, Y1 - e, Z0 + e), (xb, Y0 + e, Z0 + e)),
               ((xl, Y1 - e, Z1 - e), (xl, Y0 + e, Z1 - e), (xb, Y0 + e, Z1 - e), (xb, Y1 - e, Z1 - e)),
               ((xl, Y0 + e, Z1 - e), (xl, Y0 + e, Z0 + e), (xb, Y0 + e, Z0 + e), (xb, Y0 + e, Z1 - e)),
               ((xl, Y1 - e, Z0 + e), (xl, Y1 - e, Z1 - e), (xb, Y1 - e, Z1 - e), (xb, Y1 - e, Z0 + e))]
    for p in paredes:
        quad(list(p) if sinal > 0 else list(p)[::-1], m_crom)
