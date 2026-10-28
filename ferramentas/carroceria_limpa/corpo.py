"""
Carroceria limpa por superfícies: cada região da casca do Meshy (lateral baixa, caixa de vidros, capô, para-brisa, teto, vidro
traseiro, frente, traseira) vira um polinômio de poucos termos ajustado por mínimos quadrados robustos aos campos medidos.
As seções transversais saem dessas superfícies e se encontram em vincos (fundo, cintura com o degrau do vidro, borda do teto ou
ombro do para-lama), cada vinco com o seu raio. Loft ao longo de x, tampas da frente e de trás pelos campos da frente e de trás.

    python corpo.py -- campos.npz mapa.json saida.npz
"""
import sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from secoes import Campos, gauss1d, fill_nan_1d, C

DX = 0.02
NA, NB, NC = 18, 14, 26


# ------------------------------------------------------------------------------------------------------------ ajuste robusto
def poly_terms(u, v, du, dv, even_v=False):
    cols = []
    for i in range(du + 1):
        for j in range(dv + 1):
            if even_v and j % 2:
                continue
            cols.append(u ** i * v ** j)
    return np.stack(cols, 1)


def fit_robusto(A, b, tol=0.02, voltas=4):
    w = np.ones(len(b))
    coef = None
    for _ in range(voltas):
        Aw = A * np.sqrt(w)[:, None]
        coef = np.linalg.lstsq(Aw, b * np.sqrt(w), rcond=None)[0]
        r = A @ coef - b
        w = 1.0 / (1.0 + (r / tol) ** 2)
    return coef


class Superficie:
    """h = poly(u, v) ajustada a amostras; even_v: só potências pares de v (simetria y)."""

    def __init__(self, U, V, H, du, dv, even_v=False, tol=0.02):
        ok = np.isfinite(H)
        self.du, self.dv, self.even_v = du, dv, even_v
        self.u0, self.us = U[ok].mean(), max(U[ok].std(), 1e-3)
        self.v0, self.vs = (0.0, 1.0) if even_v else (V[ok].mean(), max(V[ok].std(), 1e-3))
        A = poly_terms((U[ok] - self.u0) / self.us, (V[ok] - self.v0) / self.vs, du, dv, even_v)
        self.coef = fit_robusto(A, H[ok], tol)
        self.umin, self.umax = float(U[ok].min()), float(U[ok].max())
        self.vmin, self.vmax = float(V[ok].min()), float(V[ok].max())
        self.n = int(ok.sum())
        self.rms = float(np.sqrt(np.mean((A @ self.coef - H[ok]) ** 2)))

    def __call__(self, u, v):
        # fora da região medida o polinômio não vale: segura no valor da borda
        u = np.clip(np.asarray(u, float), self.umin, self.umax)
        v = np.clip(np.asarray(v, float), self.vmin, self.vmax)
        A = poly_terms((u - self.u0) / self.us, (v - self.v0) / self.vs, self.du, self.dv, self.even_v)
        return A @ self.coef


def grade(U, V):
    return np.meshgrid(U, V, indexing="ij")


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------------------------------------------------ o corpo
class Corpo:
    def __init__(self, npz, mapa):
        med = json.load(open(mapa, encoding="utf-8"))
        self.med = med["medidas"]
        self.parts = {p["name"]: p for p in med["parts"]}
        M = self.med
        R = M["raio_roda"]
        self.arcos = [(M["eixo_dianteiro"], R, R + 0.09), (M["eixo_traseiro"], R, R + 0.09)]
        self.c = Campos(npz, self.arcos)
        c = self.c
        X, Y, Z = c.X, c.Y, c.Z
        XX, ZZ = grade(X, Z)
        XY, YY = grade(X, Y)
        mats = list(c.mats)
        VIDRO, PINT = mats.index("vidro"), mats.index("pintura")
        ys = c.ys_raw.copy()
        ys[ys < 0.3] = np.nan
        for (xe, ze, ra) in self.arcos:                       # sem as caixas de roda
            for i, x in enumerate(X):
                if abs(x - xe) < ra + 0.02:
                    ys[i, Z < ze + np.sqrt(max(0.0, (ra + 0.02) ** 2 - (x - xe) ** 2)) + 0.03] = np.nan
        # ---- linhas de referência em x
        bw = self.parts["glass_windshield"]["box"]
        br = self.parts["glass_rear"]["box"]
        self.x_cowl, self.x_ws_top = bw[1], bw[0]
        self.x_rg_top, self.x_rg_base = br[1], br[0]
        zt0 = c.zt_raw[:, int(round((0 - Y[0]) / C))]
        # bico do capô: primeiro x (da frente para trás) em que o topo no centro passa de 0,78
        ok = np.isfinite(zt0) & (zt0 > 0.78)
        self.x_bico = X[np.nonzero(ok)[0][-1]] - 0.01
        # vinco de trás (painel traseiro vertical até aqui): primeiro x atrás em que o topo passa de 0,95
        self.x_rabo = X[np.nonzero(ok & (zt0 > 0.95))[0][0]] + 0.005
        # ---- cintura: z mais baixo do vidro lateral por x, reta ajustada
        zw = np.full(len(X), np.nan)
        for i in range(len(X)):
            jv = np.nonzero((c.lado_m[i] == VIDRO) & (Z > 0.8) & (Z < 1.2))[0]
            if len(jv) > 3:
                zw[i] = Z[jv[0]]
        okw = np.isfinite(zw)
        self.zw_a, self.zw_b = np.polyfit(X[okw], zw[okw], 1)
        self.z_cintura = lambda x: (self.zw_a * np.asarray(x, float) + self.zw_b) - 0.012
        # ---- lateral baixa: y(x, z), z entre o fundo e a cintura
        zc = self.z_cintura(XX)
        sel = (ZZ < zc - 0.01) & (XX > -1.78) & (XX < 1.80)
        self.lado = Superficie(XX[sel], ZZ[sel], np.where(sel, ys, np.nan)[sel], 4, 3, tol=0.015)
        # ---- caixa de vidros: y(x, z) acima da cintura (vidro e colunas), da base do vidro traseiro ao cowl
        gm = (c.lado_m == VIDRO) | (c.lado_m == PINT)
        sel = (ZZ > zc + 0.02) & (XX > self.x_rg_base) & (XX < self.x_cowl) & gm & (ys > 0.45)
        self.vidros = Superficie(XX[sel], ZZ[sel], ys[sel], 3, 2, tol=0.015)
        # ---- topo por região: capô, para-brisa, teto, vidro traseiro
        zt = c.zt_raw.copy()
        self.topo = {}
        for nome, x0, x1 in (("capo", self.x_cowl, self.x_bico), ("parabrisa", self.x_ws_top, self.x_cowl),
                             ("teto", self.x_rg_top, self.x_ws_top), ("vidro_tras", self.x_rabo, self.x_rg_top)):
            sel = (XY > x0 + 0.03) & (XY < x1 - 0.03) & (np.abs(YY) < 0.78)
            du = 1 if nome in ("parabrisa", "vidro_tras") else 2
            self.topo[nome] = Superficie(XY[sel], YY[sel], zt[sel], du, 4, even_v=True, tol=0.02)
        self.topo_ordem = [("capo", self.x_bico, self.x_cowl), ("parabrisa", self.x_cowl, self.x_ws_top),
                           ("teto", self.x_ws_top, self.x_rg_top), ("vidro_tras", self.x_rg_top, self.x_rabo)]
        # ---- frente e traseira: x(y, z)
        YZy, YZz = grade(Y, Z)
        xf = c.xf_raw
        sel = (YZz > 0.56) & (YZz < 0.82) & (np.abs(YZy) < 0.76)
        self.frente = Superficie(YZz[sel], YZy[sel], xf[sel], 2, 4, even_v=True, tol=0.03)   # x(z, y), par em y
        xr = c.xr_raw
        sel = (YZz > 0.56) & (YZz < 0.95) & (np.abs(YZy) < 0.76)
        self.tras = Superficie(YZz[sel], YZy[sel], xr[sel], 2, 4, even_v=True, tol=0.03)
        # ---- fundo por x (saia, topo do para-choque), sem as caixas de roda
        self.zb = c.zb

    # ---------------------------------------------------------------------------------------------- superfícies compostas
    def z_topo(self, x, y, blend=0.08):
        """Topo no (x, y): a região de x, com mistura suave de ±blend nas fronteiras."""
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        out = np.zeros(np.broadcast(x, y).shape)
        wsum = np.zeros_like(out)
        for nome, xa, xb in self.topo_ordem:
            lo, hi = min(xa, xb), max(xa, xb)
            w = smoothstep(lo - blend, lo + blend, x) * (1 - smoothstep(hi - blend, hi + blend, x))
            if nome == "capo":                      # a da frente vale até a ponta
                w = smoothstep(lo - blend, lo + blend, x)
            if nome == "vidro_tras":                # a de trás também
                w = 1 - smoothstep(hi - blend, hi + blend, x)
            out += w * self.topo[nome](x, y)
            wsum += w
        return out / np.maximum(wsum, 1e-9)

    def tem_vidros(self, x):
        return self.x_rabo < x < self.x_cowl

    # ---------------------------------------------------------------------------------------------- seção
    def secao(self, x):
        """Meia seção (y, z) com os vincos, do fundo ao centro do teto, e os índices dos vincos."""
        zb = self.zb_em(x)
        zw = float(self.z_cintura(x))
        # lateral: do fundo até a cintura (ou até o ombro, onde não há caixa de vidros)
        zs = np.linspace(zb, zw, 40)
        ysd = self.lado(np.full_like(zs, x), zs)
        # onde a lateral fura o topo (ombro): z tal que z_topo(x, y_lado(z)) = z
        ztop_s = self.z_topo(np.full_like(zs, x), ysd)
        fura = np.nonzero(zs >= ztop_s)[0]
        if not self.tem_vidros(x):
            # ombro: lateral até o encontro com o topo, depois o topo até o centro
            k = fura[0] if len(fura) else len(zs) - 1
            if len(fura):
                t = (zs[k - 1] - ztop_s[k - 1]) / ((zs[k - 1] - ztop_s[k - 1]) - (zs[k] - ztop_s[k]) + 1e-12)
                ye = ysd[k - 1] + t * (ysd[k] - ysd[k - 1])
                ze = zs[k - 1] + t * (zs[k] - zs[k - 1])
            else:
                ye, ze = ysd[-1], zs[-1]
            lado = np.stack([ysd[:k], zs[:k]], 1)
            lado = np.vstack([lado, [ye, ze]])
            yy = np.linspace(ye, 0.0, 30)
            topo = np.stack([yy, self.z_topo(np.full_like(yy, x), yy)], 1)
            P = np.vstack([lado, topo[1:]])
            vincos = {"fundo": 0, "cintura": len(lado) - 1, "borda": len(lado) - 1}
            return P, vincos
        # com caixa de vidros: lateral até a cintura, degrau do vidro, vidro até a borda do teto, topo até o centro
        lado = np.stack([ysd, zs], 1)
        zg = np.linspace(zw, zw + 0.7, 80)
        yg = self.vidros(np.full_like(zg, x), zg)
        ztop_g = self.z_topo(np.full_like(zg, x), yg)
        fura = np.nonzero(zg >= ztop_g)[0]
        k = fura[0] if len(fura) else len(zg) - 1
        if len(fura) and k > 0:
            t = (zg[k - 1] - ztop_g[k - 1]) / ((zg[k - 1] - ztop_g[k - 1]) - (zg[k] - ztop_g[k]) + 1e-12)
            ye = yg[k - 1] + t * (yg[k] - yg[k - 1])
            ze = zg[k - 1] + t * (zg[k] - zg[k - 1])
        else:
            ye, ze = yg[k], zg[k]
        vidro = np.stack([yg[:k], zg[:k]], 1)
        vidro = np.vstack([vidro, [ye, ze]])
        yy = np.linspace(ye, 0.0, 30)
        topo = np.stack([yy, self.z_topo(np.full_like(yy, x), yy)], 1)
        P = np.vstack([lado, vidro, topo[1:]])
        vincos = {"fundo": 0, "cintura": len(lado) - 1, "borda": len(lado) + len(vidro) - 1}
        return P, vincos

    def zb_em(self, x):
        i = np.clip(int(round((x - self.c.X[0]) / C)), 0, len(self.c.X) - 1)
        zb = max(0.28, float(self.zb[i]))
        for (xe, ze, ra) in self.arcos:
            if abs(x - xe) < ra:
                zb = max(zb, ze + np.sqrt(ra * ra - (x - xe) ** 2))
        return zb


# ------------------------------------------------------------------------------------------------------------ loft
def resample(P, n):
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, P[:, k]) for k in range(P.shape[1])], 1)


def filetar(P, i, raio, n_arco=7):
    """Arredonda o canto no índice i: troca os pontos a menos de raio do canto por um arco (Bézier quadrática).
    Devolve a polilinha nova e os índices do começo, do meio e do fim do arco."""
    if raio <= 0 or i <= 0 or i >= len(P) - 1:
        return P, i, i, i
    a = P[i]

    def ponto_a(dist, sentido):
        acc = 0.0
        k = i
        while 0 < k < len(P) - 1:
            q0, q1 = P[k], P[k + sentido]
            d = np.linalg.norm(q1 - q0)
            if acc + d >= dist:
                return q0 + (q1 - q0) * (dist - acc) / max(d, 1e-12), (k + 1 if sentido > 0 else k - 1)
            acc += d
            k += sentido
        return P[k], k
    p0, k0 = ponto_a(raio, -1)
    p1, k1 = ponto_a(raio, +1)
    tt = np.linspace(0, 1, n_arco)[:, None]
    arco = (1 - tt) ** 2 * p0 + 2 * (1 - tt) * tt * a + tt ** 2 * p1
    Q = np.vstack([P[: k0 + 1], arco, P[k1:]])
    return Q, k0 + 1, k0 + 1 + n_arco // 2, k0 + n_arco


def secao_param(P, vincos, raios):
    """Fileta os vincos e resampla cada trecho com um número fixo de pontos (os vincos ficam em índices fixos).
    Com caixa de vidros: A = fundo até a cintura, B = vidro, C = teto. Sem (capô): A = lateral, B = o arco do ombro, C = topo."""
    ic, ib = vincos["cintura"], vincos["borda"]
    if ib != ic:
        P, _, ib2, _ = filetar(P, ib, raios["borda"])
        n0 = len(P)
        P, _, ic2, _ = filetar(P, ic, raios["cintura"])
        ib2 += len(P) - n0
        A = resample(P[: ic2 + 1], NA)
        B = resample(P[ic2: ib2 + 1], NB)
        Cc = resample(P[ib2:], NC)
    else:
        P, k0, _, k1 = filetar(P, ic, raios["borda"], n_arco=NB)
        A = resample(P[: k0 + 1], NA)
        B = resample(P[k0: k1 + 1], NB)
        Cc = resample(P[k1:], NC)
    Q = np.concatenate([A, B[1:], Cc[1:]], 0)
    Q[-1, 0] = 0.0
    return Q


def rotular(m):
    """Componentes conexos (4-vizinhos) de uma máscara 2D; devolve rótulos (0 = fundo)."""
    from collections import deque
    lab = np.zeros(m.shape, np.int32)
    n = 0
    for i0, j0 in zip(*np.nonzero(m)):
        if lab[i0, j0]:
            continue
        n += 1
        q = deque([(i0, j0)])
        lab[i0, j0] = n
        while q:
            i, j = q.popleft()
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < m.shape[0] and 0 <= b < m.shape[1] and m[a, b] and not lab[a, b]:
                    lab[a, b] = n
                    q.append((a, b))
    return lab, n


def contorno(mask, U, V, passo=0.01, sigma=0.04):
    """Contorno fechado e liso de uma máscara (grade U x V), por raios do centro; pontos (u, v)."""
    ii, jj = np.nonzero(mask)
    cu, cv = U[ii].mean(), V[jj].mean()
    pts = []
    for ang in np.linspace(0, 2 * np.pi, 720, endpoint=False):
        t = np.arange(0, 1.5, 0.003)
        pu, pv = cu + np.cos(ang) * t, cv + np.sin(ang) * t
        iu = np.round((pu - U[0]) / C).astype(int)
        iv = np.round((pv - V[0]) / C).astype(int)
        ok = (iu >= 0) & (iu < len(U)) & (iv >= 0) & (iv < len(V))
        hit = np.zeros(len(t), bool)
        hit[ok] = mask[iu[ok], iv[ok]]
        if not hit.any():
            continue
        k = np.nonzero(hit)[0][-1]
        pts.append((pu[k], pv[k]))
    P = np.array(pts)
    # casco convexo (as janelas são trapézios de cantos redondos; a máscara do Meshy tem reentrâncias que não existem)
    P = P[np.argsort(np.arctan2(P[:, 1] - P[:, 1].mean(), P[:, 0] - P[:, 0].mean()))]
    def cruz(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    Ps = P[np.lexsort((P[:, 1], P[:, 0]))]
    lower = []
    for q in Ps:
        while len(lower) >= 2 and cruz(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper = []
    for q in Ps[::-1]:
        while len(upper) >= 2 and cruz(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    P = np.array(lower[:-1] + upper[:-1])
    Q = np.vstack([P, P[:1]])
    seg = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    sarc = np.concatenate([[0], np.cumsum(seg)])
    n = max(16, int(sarc[-1] / passo))
    tt = np.linspace(0, sarc[-1], n, endpoint=False)
    R = np.stack([np.interp(tt, sarc, Q[:, k]) for k in range(2)], 1)
    k = np.arange(-int(3 * sigma / passo), int(3 * sigma / passo) + 1)
    g = np.exp(-0.5 * (k * passo / sigma) ** 2)
    g /= g.sum()
    out = np.zeros_like(R)
    for w, kk in zip(g, k):
        out += w * np.roll(R, kk, axis=0)
    return out


def limpar_mascara(m, r=3, r_fecha=None):
    """Abertura (tira lascas mais finas que 2r) e fechamento (enche buracos menores que 2 r_fecha; a coluna B tem ~6 cm: fica)."""
    from secoes import abrir
    m = abrir(m, r)
    return ~abrir(~m, r_fecha if r_fecha is not None else r)


def construir(npz, mapa, saida):
    corpo = Corpo(npz, mapa)
    for nome, s in list(corpo.topo.items()) + [("lado", corpo.lado), ("vidros", corpo.vidros), ("frente", corpo.frente), ("tras", corpo.tras)]:
        print("  %-10s %6d amostras, rms %.1f mm" % (nome, s.n, s.rms * 1000))
    print("  x: rabo %.3f  vidro_tras %.3f  teto %.3f  parabrisa %.3f  cowl %.3f  bico %.3f" % (
        corpo.x_rabo, corpo.x_rg_top, corpo.x_ws_top, corpo.x_ws_top, corpo.x_cowl, corpo.x_bico))
    print("  cintura: z = %.4f x + %.4f" % (corpo.zw_a, corpo.zw_b))
    # seções planas, um pouco além das pontas (as superfícies extrapolam), para recortar pela frente e pela traseira
    XS = np.arange(corpo.x_rabo - 0.06, corpo.x_bico + 0.06 + 1e-9, DX)
    secs = []
    for x in XS:
        P, vincos = corpo.secao(x)
        raios = {"cintura": 0.012, "borda": 0.025 if corpo.tem_vidros(x) else 0.04}
        secs.append(secao_param(P, vincos, raios))
    S = np.array(secs)                                   # [nx, npts, 2]
    npts = S.shape[1]
    # cada fileira j (um ponto da seção ao longo de x) termina onde encontra a superfície da frente x_f(z, y) e a de trás
    def fim(j, sup, sinal):
        xs_ = XS if sinal > 0 else XS[::-1]
        Sj = S[:, j] if sinal > 0 else S[::-1, j]
        xf = sup(Sj[:, 1], Sj[:, 0])
        # acima da parte vertical (capô, teto), a fileira termina no vinco: x da face vertical no seu topo
        alto = Sj[:, 1] > sup.umax
        if alto.all():
            return float(sup(np.array([sup.umax]), Sj[-1:, 0])[0])
        dentro = (xs_ <= xf) if sinal > 0 else (xs_ >= xf)
        k = np.nonzero(~dentro)[0]
        if len(k) == 0 or k[0] == 0:
            return xs_[-1] if len(k) == 0 else xs_[0]
        k = k[0]
        d0, d1 = xs_[k - 1] - xf[k - 1], xs_[k] - xf[k]
        t = d0 / (d0 - d1 + 1e-12)
        return xs_[k - 1] + t * (xs_[k] - xs_[k - 1])
    x_fim_f = np.array([fim(j, corpo.frente, 1) for j in range(npts)])
    x_fim_r = np.array([fim(j, corpo.tras, -1) for j in range(npts)])
    NT = 200
    V = np.zeros((NT, npts, 3))
    for j in range(npts):
        xj = x_fim_r[j] + np.linspace(0, 1, NT) * (x_fim_f[j] - x_fim_r[j])
        V[:, j, 0] = xj
        V[:, j, 1] = np.interp(xj, XS, S[:, j, 0])
        V[:, j, 2] = np.interp(xj, XS, S[:, j, 1])
    # tampas: a malha monta; aqui vão as superfícies da frente e de trás amostradas numa grade (y, z) de 1 cm
    gy = np.arange(-0.9, 0.9001, 0.01)
    gz = np.arange(0.3, 1.2001, 0.01)
    GY, GZ = np.meshgrid(gy, gz, indexing="ij")
    tampa_frente = corpo.frente(GZ.ravel(), GY.ravel()).reshape(GY.shape)
    tampa_tras = corpo.tras(GZ.ravel(), GY.ravel()).reshape(GY.shape)
    bolsos = []
    for nome, p in corpo.parts.items():
        if p.get("papel") in ("headlight", "taillight", "grille", "plate") and "box" in p:
            b = p["box"]
            bolsos.append([{"headlight": 1, "grille": 1, "plate": 1, "taillight": -1}[p["papel"]] if p["papel"] != "plate" else (1 if b[0] > 0 else -1),
                           b[0], b[1], b[2], b[3], b[4], b[5], p.get("pocket", 0.03)])
    bolsos = np.array(bolsos, float)
    # ---- vidros: máscaras do Meshy (lateral: x,z; topo: x,y), por quadrilátero da malha, e os contornos para a borracha
    c = corpo.c
    mats = list(c.mats)
    VID = mats.index("vidro")
    m_lado = limpar_mascara(c.lado_m == VID, r=5, r_fecha=2)   # abertura de 10 cm tira a lasca do para-brisa vista de lado
    m_topo = limpar_mascara(c.topo_m == VID)
    # no topo só valem o para-brisa e o vidro traseiro (|y| pequeno): os laterais vistos de cima saem
    m_topo &= (np.abs(c.Y)[None, :] < 0.62)
    lab_l, nl = rotular(m_lado)
    lab_t, nt_ = rotular(m_topo)
    contornos = []
    for lab, n, U, Vv, tipo, minimo in ((lab_l, nl, c.X, c.Z, "lado", 400), (lab_t, nt_, c.X, c.Y, "topo", 1500)):
        for k in range(1, n + 1):
            mk = lab == k
            if mk.sum() < minimo:
                lab[mk] = 0
                continue
            contornos.append((tipo, contorno(mk, U, Vv)))
    m_lado = lab_l > 0
    m_topo = lab_t > 0
    # cada quadrilátero é vidro se o centro cai dentro do contorno liso (o mesmo da borracha), na vista certa pela normal
    def dentro(P, u, v):
        n = len(P)
        d_ = False
        j_ = n - 1
        for i_ in range(n):
            if (P[i_, 1] > v) != (P[j_, 1] > v):
                uc = P[i_, 0] + (v - P[i_, 1]) * (P[j_, 0] - P[i_, 0]) / (P[j_, 1] - P[i_, 1] + 1e-15)
                if u < uc:
                    d_ = not d_
            j_ = i_
        return d_
    quad_glass = np.zeros((NT - 1, npts - 1), bool)
    for i in range(NT - 1):
        for j in range(npts - 1):
            cq = 0.25 * (V[i, j] + V[i + 1, j] + V[i, j + 1] + V[i + 1, j + 1])
            nq = np.cross(V[i + 1, j] - V[i, j], V[i, j + 1] - V[i, j])
            nq /= max(np.linalg.norm(nq), 1e-12)
            # lateral: tudo que não é teto (o vidro lateral chega até a calha); topo: o que olha para cima
            testes = []
            if abs(nq[1]) > 0.3:
                testes.append(("lado", cq[0], cq[2]))
            if abs(nq[2]) > 0.3:
                testes.append(("topo", cq[0], cq[1]))
            for tipo, u, v in testes:
                for t_, P_ in contornos:
                    if t_ == tipo and P_[:, 0].min() - 0.02 < u < P_[:, 0].max() + 0.02 and dentro(P_, u, v):
                        quad_glass[i, j] = True
                        break
    ctipos = np.array([t for t, _ in contornos])
    np.savez(saida, V=V, x_bico=corpo.x_bico, x_rabo=corpo.x_rabo, tampa_frente=tampa_frente, tampa_tras=tampa_tras,
             tampa_gy=gy, tampa_gz=gz, bolsos=bolsos, quad_glass=quad_glass, zw=np.array([corpo.zw_a, corpo.zw_b]),
             door_x=np.array(corpo.parts["door_fl"]["box"][0:2]), y_capo=corpo.parts["hood"]["box"][3],
             x_cowl=corpo.x_cowl, x_rg_top=corpo.x_rg_top, x_ws_top=corpo.x_ws_top, x_rg_base=corpo.x_rg_base, j_borda=NA + NB - 2, contorno_tipos=ctipos, **{"contorno_%d" % k: p for k, (_, p) in enumerate(contornos)})
    print("  vidros: %d contornos (%s), %d quadriláteros de vidro" % (len(contornos), ", ".join(ctipos), quad_glass.sum()))
    print("  fim frente: %.3f..%.3f  fim tras: %.3f..%.3f" % (x_fim_f.min(), x_fim_f.max(), x_fim_r.min(), x_fim_r.max()))
    return corpo, XS, V


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    corpo, xs, S = construir(a[0], a[1], a[2])
    print("secoes", len(xs), "pontos", S.shape[1])
