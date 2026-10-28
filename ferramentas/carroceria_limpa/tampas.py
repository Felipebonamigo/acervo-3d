"""Tampas da frente e de trás: grade (y, z) com linhas nas bordas dos bolsos (faróis, grade, lanternas, placa), costurada ao contorno
do loft por triângulos. Funções usadas pela malha.py (bmesh)."""
import numpy as np
from mathutils import Vector


def ponto_em_poligono(py, pz, poly):
    """Teste par-ímpar em (y, z)."""
    n = len(poly)
    dentro = False
    j = n - 1
    for i in range(n):
        yi, zi = poly[i]
        yj, zj = poly[j]
        if (zi > pz) != (zj > pz):
            yc = yi + (pz - zi) * (yj - yi) / (zj - zi + 1e-15)
            if py < yc:
                dentro = not dentro
        j = i
    return dentro


def mais_perto_no_contorno(py, pz, poly):
    """Ponto mais perto numa polilinha fechada e o índice do segmento."""
    best, bi, bt = None, 0, 0.0
    n = len(poly)
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        ab = b - a
        t = float(np.clip(np.dot(np.array([py, pz]) - a, ab) / max(np.dot(ab, ab), 1e-15), 0, 1))
        q = a + t * ab
        d = (q[0] - py) ** 2 + (q[1] - pz) ** 2
        if best is None or d < best:
            best, bi, bt = d, i, t
    return bi, bt


def tampa(bm, contorno3, sup, gy, gz, bolsos, sinal, mat_face, mat_bolso, x_face_max):
    """
    contorno3: pontos 3D do contorno fechado (fim das fileiras do loft), em ordem angular, já vértices do bmesh (lista de BMVert).
    sup: campo x(y, z) amostrado em (gy, gz). bolsos: [(sinal, x0, x1, y0, y1, z0, z1, fundo)].
    """
    P = np.array([(v.co.y, v.co.z) for v in contorno3])
    cy, cz = P[:, 0].mean(), P[:, 1].mean()
    # retângulo interno: 3 cm para dentro da caixa do contorno
    ymax = P[:, 0].max() - 0.035
    z0, z1 = P[:, 1].min() + 0.035, P[:, 1].max() - 0.035
    # linhas da grade: uniformes a ~3 cm, mais as bordas dos bolsos (e um degrau de 3 mm para dentro, para a parede ficar em pé)
    ys = set(np.round(np.linspace(-ymax, ymax, int(2 * ymax / 0.03) + 2), 4).tolist())
    zs = set(np.round(np.linspace(z0, z1, int((z1 - z0) / 0.03) + 2), 4).tolist())
    meus = [b for b in bolsos if b[0] == sinal]
    for b in meus:
        _, bx0, bx1, by0, by1, bz0, bz1, fundo = b
        for y in (by0, by1, by0 + 0.003, by1 - 0.003):
            if -ymax < y < ymax:
                ys.add(round(float(y), 4))
        for z in (bz0, bz1, bz0 + 0.003, bz1 - 0.003):
            if z0 < z < z1:
                zs.add(round(float(z), 4))
    ys = np.array(sorted(ys))
    zs = np.array(sorted(zs))
    # tira linhas coladas (< 2 mm) que não sejam de bolso
    def limpa(v, fixos):
        out = [v[0]]
        for a in v[1:]:
            if a - out[-1] < 0.002 and not any(abs(a - f) < 1e-6 for f in fixos):
                continue
            out.append(a)
        return np.array(out)
    fy = [y for b in meus for y in (b[3], b[4], b[3] + 0.003, b[4] - 0.003)]
    fz = [z for b in meus for z in (b[5], b[6], b[5] + 0.003, b[6] - 0.003)]
    ys, zs = limpa(ys, fy), limpa(zs, fz)

    def x_em(y, z):
        iy = int(np.clip(round((y - gy[0]) / (gy[1] - gy[0])), 0, len(gy) - 1))
        iz = int(np.clip(round((z - gz[0]) / (gz[1] - gz[0])), 0, len(gz) - 1))
        xv = float(sup[iy, iz])
        for b in meus:
            _, bx0, bx1, by0, by1, bz0, bz1, fundo = b
            if by0 + 0.0015 < y < by1 - 0.0015 and bz0 + 0.0015 < z < bz1 - 0.0015:
                return xv - sinal * float(fundo)           # fundo do bolso: a profundidade do mapa, a partir da face
        return xv
    nodes = {}
    for iy, y in enumerate(ys):
        for iz, z in enumerate(zs):
            nodes[(iy, iz)] = bm.verts.new(Vector((x_em(y, z), y, z)))
    faces = []
    for iy in range(len(ys) - 1):
        for iz in range(len(zs) - 1):
            q = (nodes[(iy, iz)], nodes[(iy + 1, iz)], nodes[(iy + 1, iz + 1)], nodes[(iy, iz + 1)])
            f = bm.faces.new(q if sinal > 0 else q[::-1])
            f.smooth = True
            cy_, cz_ = 0.5 * (ys[iy] + ys[iy + 1]), 0.5 * (zs[iz] + zs[iz + 1])
            em_bolso = any(b[3] < cy_ < b[4] and b[5] < cz_ < b[6] for b in meus)
            f.material_index = mat_bolso if em_bolso else mat_face
            faces.append(f)
    # costura: contorno externo (loft) e perímetro da grade, os dois em ordem angular, zipados por ângulo
    perim = [nodes[(iy, 0)] for iy in range(len(ys))] + [nodes[(len(ys) - 1, iz)] for iz in range(1, len(zs))] + \
            [nodes[(iy, len(zs) - 1)] for iy in range(len(ys) - 2, -1, -1)] + [nodes[(0, iz)] for iz in range(len(zs) - 2, 0, -1)]
    def ang(v):
        return np.arctan2(v.co.z - cz, v.co.y - cy)
    A = sorted(contorno3, key=ang)
    B = sorted(perim, key=ang)
    ia = ib = 0
    na, nb = len(A), len(B)
    aa = [ang(v) for v in A] + [ang(A[0]) + 2 * np.pi]
    bb = [ang(v) for v in B] + [ang(B[0]) + 2 * np.pi]
    while ia < na or ib < nb:
        if ib >= nb or (ia < na and aa[ia + 1] <= bb[ib + 1]):
            tri = (A[ia % na], A[(ia + 1) % na], B[ib % nb])
            ia += 1
        else:
            tri = (A[ia % na], B[(ib + 1) % nb], B[ib % nb])
            ib += 1
        if len(set(tri)) == 3:
            try:
                f = bm.faces.new(tri if sinal > 0 else tri[::-1])
                f.smooth = True
                f.material_index = mat_face
            except ValueError:
                pass
    return faces
