"""
Gabarito do HATCH de 2 portas: uma gaiola de quadriláteros com os laços dos vãos já no desenho (vidros, portas, capô, tampa, arcos,
faróis, lanternas). Sem bpy: só contas. Quem subdivide e corta é construir.py.

Três remendos costurados (meio carro, y >= 0; frente +X, esquerda +Y, cima +Z, metros, chão em z = 0, origem entre os eixos):
  L  lateral baixa, da soleira ao ombro: 22 colunas (c0 na frente .. c21 atrás) x 8 fiadas (r0 soleira .. r7 ombro de dentro);
     os dois arcos de roda são buracos redondos com um anel de quadriláteros em volta;
  G  lateral da cabine, do ombro à calha do teto: colunas c7..c21 x 5 fiadas (0 cintura .. 4 calha);
  T  a faixa de cima: sobe a frente, capô, para-brisa, teto, vidro traseiro e desce a traseira; 6 colunas (k0 no meio .. k5 na borda,
     que é a própria borda de L e G).
Cada face leva a região (a peça de que faz parte) e as coordenadas de molde (u, v) para o UV.

Todas as cotas vêm da ficha do carro (fichas/<carro>.json): nenhuma geometria de terceiros entra aqui.
"""
import math

NR = 8          # fiadas de L
NG = 5          # fiadas de G
NK = 6          # colunas de T
ARCO_F = 1      # primeira coluna do grupo do arco dianteiro (c1..c7)
ARCO_T = 14     # idem, traseiro (c14..c20)
POLO = 7        # coluna do pé da coluna A


def montar(F):
    c = F['cotas']
    V, idx, faces = [], {}, []

    def vert(chave, p=None):
        if chave not in idx:
            idx[chave] = len(V)
            V.append(tuple(p))
        return idx[chave]

    # ------------------------------------------------------------------------------------------------ a lateral baixa (L)
    xs = c['colunas_x']                      # x de cada coluna na altura do ombro, c0..c21
    assert len(xs) == 22
    z_cint, z_larg, z_sol = c['z_cintura'], c['z_mais_largo'], c['z_soleira']

    def z_ombro(x):
        if x > c['x_porta_frente']:
            return z_cint - c['queda_capo'] * (x - c['x_porta_frente'])
        if x < c['x_porta_tras']:
            return z_cint + c['subida_tras'] * (c['x_porta_tras'] - x) / (c['x_porta_tras'] - xs[21])
        return z_cint

    def meia_largura(x):
        return c['meia_largura'] - c['afina_planta'] * (x / (0.5 * c['comprimento_casca'])) ** 2

    def y_lado(x, z):
        w, zo = meia_largura(x), z_ombro(x)
        if z <= z_larg:
            return w - c['recuo_soleira'] * ((z_larg - z) / (z_larg - z_sol)) ** 2
        # onde o ombro é baixo (na frente, sobre o capô) a lateral quase não recolhe: o recuo acompanha a altura do ombro
        rec = c['recuo_cintura'] * min(1.0, max(zo - z_larg, 0.0) / max(z_cint - z_larg, 1e-3)) ** 1.5
        return w - rec * min(1.0, (z - z_larg) / max(zo - z_larg, 1e-3)) ** 1.8

    def z_fiada(j, x, i):
        zo = z_ombro(x)
        if i == 0:
            return c['fiadas_frente'][j]
        if i == 21:
            return c['fiadas_tras'][j]
        base = [z_sol, c['z_base_porta'], c.get('z_fiada_2', 0.45), c['z_topo_para_choque'], c['z_friso'], 0, 0, 0]
        if j <= 4:
            return base[j]
        if j == 5:
            return c['z_friso'] + (zo - c['z_friso']) * 0.55
        return zo - (c['ombro_altura'] if j == 6 else 0.0)

    def arco(i):
        for nome, i0, xa in (('f', ARCO_F, c['eixo_dianteiro']), ('t', ARCO_T, c['eixo_traseiro'])):
            if i0 <= i <= i0 + 6:
                return nome, i - i0, xa
        return None

    R = c['raio_arco'] / 0.9746               # a curva da subdivisão passa a 97,46% do polígono de controle
    RF = c['raio_arco'] + c['anel_arco']
    za = c['z_centro_arco']
    t0 = math.degrees(math.asin((z_sol - za) / R))
    t0f = math.degrees(math.asin((z_sol - za) / RF))

    def ang_dentro(m, j):
        if m == 1:
            f = j / 10.0
        elif m == 5:
            f = 1.0 - j / 10.0
        else:
            f = (3 + (m - 1)) / 10.0
        return t0 + f * (180.0 - 2 * t0)

    def ang_fora(m, j):
        if m == 0:
            f = j / 14.0
        elif m == 6:
            f = 1.0 - j / 14.0
        else:
            f = (4 + m) / 14.0
        return t0f + f * (180.0 - 2 * t0f)

    def existe_L(i, j):
        a = arco(i)
        return not (a and 2 <= a[1] <= 4 and j <= 2)

    def PL(i, j):
        x = xs[i]
        a = arco(i)
        if a and j <= 4:
            _, m, xa = a
            if m in (0, 6) or j == 4:
                t = math.radians(ang_fora(m, j)); r = RF
            else:
                t = math.radians(ang_dentro(m, j)); r = R
            x, z = xa + r * math.cos(t), za + r * math.sin(t)
            return (x, y_lado(x, z), z)
        if a and j == 5:
            x4 = PL(i, 4)[0]
            x = 0.5 * (x4 + x)
        z = z_fiada(j, x, i)
        if j == 7:
            y = y_lado(x, z - c['ombro_altura']) - c['ombro_largura']
        else:
            y = y_lado(x, z)
        if i == 0:
            y -= c['canto_frente']
            x += c.get('dx_frente', [0.0] * NR)[j]      # a inclinação da frente, fiada por fiada
        if i == 21:
            y -= c['canto_tras']
            x += c.get('dx_tras', [0.0] * NR)[j]        # a inclinação da traseira
        return (x, y, z)

    for i in range(22):
        for j in range(NR):
            if existe_L(i, j):
                vert(('L', i, j), PL(i, j))

    def regiao_L(i, j):
        """célula [ci, ci+1] x [rj, rj+1]"""
        if i <= 7:
            return 'fender'
        if i <= 11:
            return 'body' if j == 0 else 'door'
        return 'body'

    def quad(chaves, reg, uv):
        faces.append(dict(v=[idx[k] for k in chaves], reg=reg, uv=uv))

    for i in range(21):
        for j in range(NR - 1):
            ks = [('L', i, j), ('L', i + 1, j), ('L', i + 1, j + 1), ('L', i, j + 1)]
            if all(k in idx for k in ks):
                quad(ks, regiao_L(i, j), [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)])

    # ------------------------------------------------------------------------------------------------ a cabine (G)
    xt = c['colunas_x_teto']                 # x de cada coluna c7..c21 na calha
    assert len(xt) == 15

    def z_teto_meio(x):
        return c['z_teto'] - c['queda_teto'] * ((x - c['x_teto_alto']) / 0.7) ** 2

    def z_calha(x):
        return z_teto_meio(x) - c['coroa_teto']

    def frac_G(i, j):
        if j == 1:
            a = max(0.0, (i - 13) / 8.0)
            return c['frac_meio_vidro'] * (1 - a) + c['frac_base_vidro_tras'] * a
        return [0.0, 0.0, c['frac_topo_vidro'], c['frac_topo_porta'], 1.0][j]

    def PG(i, j):
        b = V[idx[('L', i, 7)]]
        x1 = xt[i - 7]
        z1 = z_calha(x1)
        f = frac_G(i, j)
        return (b[0] + (x1 - b[0]) * f, b[1] + (c['y_calha'] - b[1]) * f ** 1.1, b[2] + (z1 - b[2]) * f)

    def kG(i, j):
        return ('L', i, 7) if j == 0 else ('G', i, j)

    for i in range(POLO, 22):
        for j in range(1, NG):
            vert(('G', i, j), PG(i, j))

    def regiao_G(i, j):
        if i == 7 or i == 12 or i == 20:
            return 'body'
        if 8 <= i <= 11:
            if j == 3:
                return 'body'
            if i in (8, 11) or j == 2:
                return 'door'
            return 'glass_door_f'
        return 'glass_door_r' if j <= 1 else 'body'      # 13..19

    for i in range(POLO, 21):
        for j in range(NG - 1):
            quad([kG(i, j), kG(i + 1, j), kG(i + 1, j + 1), kG(i, j + 1)], regiao_G(i, j),
                 [(i, 7 + j), (i + 1, 7 + j), (i + 1, 8 + j), (i, 8 + j)])

    # ------------------------------------------------------------------------------------------------ a faixa de cima (T)
    est = []                                 # (chave da borda, x do meio, z do meio, trecho)
    for j in range(NR):
        e = V[idx[('L', 0, j)]]
        est.append((('L', 0, j), e[0] + c['bojo_frente'], e[2], 'frente'))
    for i in range(1, 7):
        e = V[idx[('L', i, 7)]]
        est.append((('L', i, 7), e[0] + c['bojo_frente'] * (1 - i / 6.0) ** 2, e[2] + c['coroa_capo'], 'capo'))
    e = V[idx[('L', POLO, 7)]]
    est.append((('L', POLO, 7), e[0] + c['bojo_para_brisa'], e[2] + c['coroa_capo'] * 0.5, 'polo'))
    for j in range(1, NG):
        e = V[idx[('G', POLO, j)]]
        est.append((('G', POLO, j), e[0] + c['bojo_para_brisa'], e[2] + c['coroa_teto'] * frac_G(POLO, j) ** 1.5, 'brisa'))
    for i in range(POLO + 1, 22):
        e = V[idx[('G', i, 4)]]
        a = (i - POLO) / 14.0
        est.append((('G', i, 4), e[0] + c['bojo_para_brisa'] * (1 - a) - c['bojo_vidro_tras'] * a, e[2] + c['coroa_teto'], 'teto'))
    for j in range(NG - 2, -1, -1):
        e = V[idx[kG(21, j)]]
        est.append((kG(21, j), e[0] - c['bojo_vidro_tras'], e[2] + c['coroa_teto'] * frac_G(21, j) ** 1.5, 'tampa'))
    for j in range(NR - 2, -1, -1):
        e = V[idx[('L', 21, j)]]
        est.append((('L', 21, j), e[0] - c['bojo_tras'], e[2], 'tras'))

    EXP = {'frente': (4.0, 1.0), 'capo': (3.0, 2.5), 'polo': (2.0, 2.5), 'brisa': (2.0, 2.5), 'teto': (2.0, 3.0),
           'tampa': (2.0, 2.5), 'tras': (4.0, 1.0)}
    fr = c['fracoes_k']
    for s, (ke, cx, cz, trecho) in enumerate(est):
        e = V[idx[ke]]
        p, q = EXP[trecho]
        for k in range(NK - 1):
            u = fr[trecho][k] if trecho in fr else fr['padrao'][k]
            vert(('T', s, k), (cx + (e[0] - cx) * u ** p, e[1] * u, cz + (e[2] - cz) * u ** q))

    def kT(s, k):
        return est[s][0] if k == NK - 1 else ('T', s, k)

    S_BRISA, S_TETO, S_TAMPA, S_TRAS = 14, 18, 32, 36

    def regiao_T(s, k):
        if s <= 2:
            return 'body' if k <= 3 else 'fender'
        if s == 3:
            return ('grille', 'grille', 'headlight', 'headlight', 'fender')[k]
        if s <= 12:
            return 'hood' if k <= 3 else 'fender'
        if s == 13:
            return 'body'           # a faixa do pé do para-brisa, de ponta a ponta: nenhuma peça termina em bico no pé da coluna
        if s <= 16:
            return 'glass_windshield' if k <= 3 else 'body'
        if s <= S_TAMPA:
            return 'body'
        if s == 33:
            return 'trunk' if k <= 3 else 'body'
        if s == 34:
            return ('glass_rear', 'glass_rear', 'glass_rear', 'trunk', 'body')[k]
        if s <= 38:
            return 'trunk' if k <= 3 else 'body'
        if s == 39:
            return ('body', 'body', 'taillight', 'taillight', 'body')[k]
        return 'body'

    for s in range(len(est) - 1):
        for k in range(NK - 1):
            quad([kT(s, k), kT(s, k + 1), kT(s + 1, k + 1), kT(s + 1, k)], regiao_T(s, k),
                 [(100 + s, k), (100 + s, k + 1), (101 + s, k + 1), (101 + s, k)])

    # ---------------------------------------------------------------------------------------------- vincos (arestas mais vivas)
    vincos = []
    vc = c.get('vincos', {})

    def linha(chaves, w):
        if w:
            for a, b in zip(chaves, chaves[1:]):
                if a in idx and b in idx:
                    vincos.append((idx[a], idx[b], w))

    linha([('L', i, 6) for i in range(0, 6)], vc.get('ombro', 0.0))
    linha([('L', i, 6) for i in range(9, 22)], vc.get('ombro', 0.0))                       # a quina do ombro, de ponta a ponta
    linha([kT(s, NK - 1) for s in range(7, 13)], vc.get('borda_capo', 0.0))             # o encontro do capô com o para-lama
    linha([kT(7, k) for k in range(NK)], vc.get('frente_capo', 0.0))                    # a quina da frente do capô
    linha([('L', 0, j) for j in range(NR)], vc.get('canto_frente', 0.0))                # o canto da frente
    linha([('L', 21, j) for j in range(NR)], vc.get('canto_tras', 0.0))                 # o canto de trás
    linha([kT(S_TRAS, k) for k in range(NK)], vc.get('quina_tampa', 0.0))               # a quina entre o vidro traseiro e a traseira
    linha([kT(s, NK - 1) for s in range(S_TETO, S_TAMPA + 1)], vc.get('calha', 0.0))    # a calha do teto
    linha([kT(s, NK - 1) for s in range(S_BRISA + 2, S_TETO + 1)], vc.get('coluna_a', 0.0))
    linha([kT(s, NK - 1) for s in range(S_TAMPA, S_TRAS + 1)], vc.get('coluna_c', 0.0))
    linha([kT(S_TETO, k) for k in range(NK)], vc.get('testeira', 0.0))                  # o encontro do para-brisa com o teto
    linha([kT(S_TAMPA, k) for k in range(NK)], vc.get('fim_teto', 0.0))
    return dict(verts=V, faces=faces, idx=idx, estacoes=[e[3] for e in est], vincos=vincos)


def espelhar(g):
    """O carro inteiro: o lado direito é o espelho (y -> -y), com as regiões de lado ganhando _left/_right e as faces viradas."""
    V = list(g['verts'])
    mapa = {}
    for i, p in enumerate(g['verts']):
        if abs(p[1]) < 1e-6:
            mapa[i] = i
        else:
            mapa[i] = len(V)
            V.append((p[0], -p[1], p[2]))
    LADO = {'fender': 'fender_front', 'door': 'door_f', 'glass_door_f': 'glass_door_f', 'glass_door_r': 'glass_door_r',
            'headlight': 'headlight', 'taillight': 'taillight'}
    SUF = {'fender_front': ('_left', '_right'), 'door_f': ('l', 'r'), 'glass_door_f': ('l', 'r'), 'glass_door_r': ('l', 'r'),
           'headlight': ('_left', '_right'), 'taillight': ('_left', '_right')}
    faces = []
    for f in g['faces']:
        base = LADO.get(f['reg'])
        e = base + SUF[base][0] if base else f['reg']
        d = base + SUF[base][1] if base else f['reg']
        faces.append(dict(v=f['v'], reg=e, uv=f['uv'], lado=1))
        faces.append(dict(v=[mapa[i] for i in reversed(f['v'])], reg=d, uv=list(reversed(f['uv'])), lado=-1))
    vincos = []
    for (i, j, w) in g.get('vincos', []):
        vincos.append((i, j, w))
        if (mapa[i], mapa[j]) != (i, j):
            vincos.append((mapa[i], mapa[j], w))
    return dict(verts=V, faces=faces, vincos=vincos)
