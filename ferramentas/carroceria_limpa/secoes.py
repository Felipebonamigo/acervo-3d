"""Das medidas (campos.npz) para a carroceria limpa: campos preenchidos e alisados, seções transversais por raio e malha em loft."""
import numpy as np

C = 0.01


def gauss1d(a, sigma_cells, axis):
    if sigma_cells <= 0:
        return a
    k = np.arange(-int(3 * sigma_cells), int(3 * sigma_cells) + 1)
    g = np.exp(-0.5 * (k / sigma_cells) ** 2)
    g /= g.sum()
    a = np.moveaxis(a, axis, 0)
    pad = len(k) // 2
    ap = np.concatenate([np.repeat(a[:1], pad, 0), a, np.repeat(a[-1:], pad, 0)], 0)
    out = np.zeros_like(a)
    for w, kk in zip(g, k):
        out += w * ap[pad + kk: pad + kk + len(a)]
    return np.moveaxis(out, 0, axis)


def fill_nan_1d(v):
    """Preenche NaN por interpolação linear ao longo do vetor (constante nas pontas)."""
    v = v.copy()
    ok = np.isfinite(v)
    if ok.sum() == 0:
        return v
    idx = np.arange(len(v))
    v[~ok] = np.interp(idx[~ok], idx[ok], v[ok])
    return v


def disk(r):
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r + 0.5


def erode(m, k):
    r = k.shape[0] // 2
    p = np.pad(m, r, constant_values=False)
    out = np.ones_like(m)
    for i in range(k.shape[0]):
        for j in range(k.shape[1]):
            if k[i, j]:
                out &= p[i:i + m.shape[0], j:j + m.shape[1]]
    return out


def dilate(m, k):
    r = k.shape[0] // 2
    p = np.pad(m, r, constant_values=False)
    out = np.zeros_like(m)
    for i in range(k.shape[0]):
        for j in range(k.shape[1]):
            if k[i, j]:
                out |= p[i:i + m.shape[0], j:j + m.shape[1]]
    return out


def abrir(m, r):
    k = disk(r)
    return dilate(erode(m, k), k)


class Campos:
    def __init__(self, npz, arcos=(), sx=8, sz=2, st=8):
        d = np.load(npz)
        self.X, self.Y, self.Z = d["X"], d["Y"], d["Z"]
        mats = list(d["mats"])
        objs = list(d["objs"])
        self.mats, self.objs = mats, objs
        ruim_m = [mats.index(m) for m in ("pneu", "chassi", "MI_DNVao", "outro")]
        ruim_o = [i for i, o in enumerate(objs) if o.startswith(("wheel", "hubcap", "mirror", "bumper"))]
        # lateral: y(x, z) do lado esquerdo (+Y); o lado direito é espelho
        ys = 2.0 - d["lado_h"]
        bad = np.isin(d["lado_m"], ruim_m) | np.isin(d["lado_o"], ruim_o) | ~np.isfinite(ys)
        ys[bad] = np.nan
        self.lado_m, self.lado_o = d["lado_m"], d["lado_o"]
        zt = 2.5 - d["topo_h"]
        bad = np.isin(d["topo_m"], ruim_m) | np.isin(d["topo_o"], ruim_o) | ~np.isfinite(zt)
        zt[bad] = np.nan
        self.topo_m, self.topo_o = d["topo_m"], d["topo_o"]
        xf = 3.0 - d["frente_h"]
        bad = np.isin(d["frente_m"], ruim_m) | np.isin(d["frente_o"], ruim_o) | ~np.isfinite(xf)
        xf[bad] = np.nan
        xr = -3.0 + d["tras_h"]
        bad = np.isin(d["tras_m"], ruim_m) | np.isin(d["tras_o"], ruim_o) | ~np.isfinite(xr)
        xr[bad] = np.nan
        self.ys_raw, self.zt_raw, self.xf_raw, self.xr_raw = ys, zt, xf, xr
        # frente e traseira: x(y, z), preenchidos e alisados (para as tampas das pontas)
        xff = xf.copy()
        for j in range(xf.shape[1]):
            xff[:, j] = fill_nan_1d(xff[:, j])
        for i in range(xf.shape[0]):
            xff[i] = fill_nan_1d(xff[i])
        self.xf = gauss1d(gauss1d(xff, 3, 0), 3, 1)
        xrf = xr.copy()
        for j in range(xr.shape[1]):
            xrf[:, j] = fill_nan_1d(xrf[:, j])
        for i in range(xr.shape[0]):
            xrf[i] = fill_nan_1d(xrf[i])
        self.xr = gauss1d(gauss1d(xrf, 3, 0), 3, 1)
        # a lateral só vale do lado esquerdo e acima do fundo: y >= 0.3 descarta o que o raio pegou do outro lado
        ys = np.where(ys > 0.3, ys, np.nan)
        # fundo da lateral pintada por x (topo do para-choque na frente e atrás, saia no meio), sem as caixas de roda
        zb = np.full(len(self.X), np.nan)
        for i in range(len(self.X)):
            okz = np.isfinite(ys[i]) & (ys[i] > 0.3)
            if okz.any():
                zb[i] = self.Z[np.nonzero(okz)[0][0]]
        for (xe, ze, ra) in arcos:
            zb[np.abs(self.X - xe) < ra + 0.03] = np.nan
        zb = fill_nan_1d(zb)
        self.zb = gauss1d(zb, 3, 0)
        # caixas de roda: tudo abaixo do arco sai antes de preencher (senão o lábio de dentro puxa a lateral para dentro)
        if arcos:
            for (xe, ze, ra) in arcos:
                for i, x in enumerate(self.X):
                    if abs(x - xe) < ra:
                        zt_ = ze + np.sqrt(ra * ra - (x - xe) ** 2) + 0.02
                        ys[i, self.Z < zt_] = np.nan
        # buracos (caixa de roda, retrovisor, para-choque) preenchidos ao longo de z, depois de x
        ysf = ys.copy()
        for i in range(ys.shape[0]):
            ysf[i] = fill_nan_1d(ysf[i])
        for j in range(ys.shape[1]):
            ysf[:, j] = fill_nan_1d(ysf[:, j])
        self.ys = gauss1d(gauss1d(ysf, sx, 0), sz, 1)
        # o topo só vale onde o raio pegou chapa ou vidro
        ztf = zt.copy()
        for j in range(zt.shape[1]):
            ztf[:, j] = fill_nan_1d(ztf[:, j])
        self.zt_valid = np.isfinite(zt)
        self.zt = gauss1d(gauss1d(ztf, st, 0), 2, 1)

    def zb_at(self, x):
        i = np.clip(int(round((x - self.X[0]) / C)), 0, len(self.X) - 1)
        return self.zb[i]

    def ponta_at(self, campo, y, z):
        j = np.clip(int(round((abs(y) - self.Y[0]) / C)), 0, len(self.Y) - 1)
        i = np.clip(int(round((z - self.Z[0]) / C)), 0, len(self.Z) - 1)
        return campo[j, i]

    def ys_at(self, x):
        i = np.clip(int(round((x - self.X[0]) / C)), 0, len(self.X) - 1)
        return self.ys[i]

    def zt_at(self, x):
        i = np.clip(int(round((x - self.X[0]) / C)), 0, len(self.X) - 1)
        return self.zt[i], self.zt_valid[i]


def secao(campos, x, zb, r_canto=3, zc=None):
    """Meia seção em x: pontos (y, z) do fundo da saia até o meio do teto, por raios do centro (0, zc)."""
    Y, Z = campos.Y, campos.Z
    if zc is None:
        zc = zb + 0.005                  # raios de um ponto logo acima do fundo: a seção é estrelada vista de lá
    ys = campos.ys_at(x)                 # por z
    zt, ok = campos.zt_at(x)             # por y
    jy0 = int(round((0 - Y[0]) / C))
    inside = np.zeros((len(Z), len(Y)), bool)   # [z, y]
    yy = Y[None, :]
    zz = Z[:, None]
    ztop = np.where(ok, zt, -1.0)[None, :]
    inside = (yy >= 0) & (yy <= ys[:, None]) & (zz <= ztop) & (zz >= zb)
    inside = abrir(inside, r_canto)
    pts = []
    for ang in np.linspace(0, np.pi / 2, 400):
        dy, dz = np.cos(ang), np.sin(ang)
        t = np.arange(0, 1.7, 0.002)
        py = 0 + dy * t
        pz = zc + dz * t
        jy = np.round((py - Y[0]) / C).astype(int)
        iz = np.round((pz - Z[0]) / C).astype(int)
        okk = (jy >= 0) & (jy < len(Y)) & (iz >= 0) & (iz < len(Z))
        hit = np.zeros(len(t), bool)
        hit[okk] = inside[iz[okk], jy[okk]]
        if not hit.any():
            continue
        k = np.nonzero(hit)[0][-1]
        pts.append((py[k], pz[k]))
    return np.array(pts)
