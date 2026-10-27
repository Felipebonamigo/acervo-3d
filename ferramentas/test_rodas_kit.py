"""
Confere o kit de rodas que o rodas_kit.py gerou (lê os GLB de volta pelo importador glTF do Blender):
redondeza do aro e da banda, murcho 6 cm mais baixo, estourado com o aro quase no chão, pivô no cubo, orçamento de triângulos,
LOD1, materiais, tamanho dos arquivos e o rodas_kit.json contra os GLB.

    python -I ferramentas/test_rodas_kit.py [-v]          # com o módulo bpy (o mesmo Python do rodas_kit.py)
    RODAS_DIR=<pasta> python -I ferramentas/test_rodas_kit.py
"""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rodas_kit as rk  # noqa: E402

PASTA = os.environ.get("RODAS_DIR", rk.SAIDA)
TOL_REDONDO = 0.002          # desvio máximo da circunferência (m)
TOL_PIVO = 0.001             # centro da caixa em X e Z (m)


def _ler_glb(arq):
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=arq)
    objs = {}
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        mw = o.matrix_world
        vs = [tuple(mw @ v.co) for v in o.data.vertices]
        o.data.calc_loop_triangles()
        objs[o.name] = {"v": vs, "tri": len(o.data.loop_triangles), "mats": [m.name.split(".")[0] for m in o.data.materials if m]}
    return objs


def circulo(vs):
    """Desvio máximo de um anel de vértices (no plano XZ) em relação ao círculo, somando a flecha da corda entre vizinhos. Os
    vértices repetidos (o importador do glTF duplica na costura da UV e nas quinas) contam uma vez só, senão puxam o centro."""
    vs = list({(round(v[0], 6), round(v[1], 6), round(v[2], 6)): v for v in vs}.values())
    cx = sum(v[0] for v in vs) / len(vs)
    cz = sum(v[2] for v in vs) / len(vs)
    ds = [math.hypot(v[0] - cx, v[2] - cz) for v in vs]
    r = sum(ds) / len(ds)
    angulos = sorted({round(math.atan2(v[2] - cz, v[0] - cx), 4) for v in vs})
    passo = max(b - a for a, b in zip(angulos, angulos[1:] + [angulos[0] + 2 * math.pi]))
    flecha = r * (1 - math.cos(passo / 2))
    return max(abs(d - r) for d in ds) + flecha, len(angulos), (cx, cz)


def anel_externo(vs, faixa=0.0005):
    rmax = max(math.hypot(v[0], v[2]) for v in vs)
    return [v for v in vs if math.hypot(v[0], v[2]) >= rmax - faixa]


def caixa(vs):
    return [min(v[i] for v in vs) for i in range(3)], [max(v[i] for v in vs) for i in range(3)]


class TestRodasKit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(PASTA, rk.JSON_KIT), encoding="utf-8") as f:
            cls.kit = json.load(f)
        cls.itens = {it["id"]: it for it in cls.kit["itens"]}
        cls.glb = {}
        for it in cls.kit["itens"]:
            cls.glb[it["id"]] = _ler_glb(os.path.join(PASTA, it["arquivo"]))

    def esperados(self):
        return (["aro_" + r for r in rk.AROS] + ["pneu_" + p for p in rk.PNEUS] + list(rk.CALOTAS))

    def test_arquivos(self):
        self.assertEqual(sorted(self.itens), sorted(self.esperados()))
        for it in self.kit["itens"]:
            tam = os.path.getsize(os.path.join(PASTA, it["arquivo"]))
            self.assertLess(tam, 50 * 1024 * 1024, it["arquivo"])
        self.assertTrue(os.path.isfile(os.path.join(PASTA, rk.NORMAL_PNG)))

    def test_json_bate_com_glb(self):
        for iid, it in self.itens.items():
            g = self.glb[iid]
            self.assertEqual(sorted(g), sorted(it["objetos"]), iid)
            if it["tipo"] == "pneu":
                for nome, t in it["triangulos_por_objeto"].items():
                    self.assertEqual(g[nome]["tri"], t, nome)
                self.assertEqual(sum(g[n]["tri"] for n in g if not n.endswith("_LOD1")), it["triangulos_lod0"], iid)
                self.assertEqual(sum(g[n]["tri"] for n in g if n.endswith("_LOD1")), it["triangulos_lod1"], iid)
                ok = g[f"{iid}_Ok"]["v"]
            else:
                self.assertEqual(g[iid]["tri"], it["triangulos_lod0"], iid)
                self.assertEqual(g[iid + "_LOD1"]["tri"], it["triangulos_lod1"], iid)
                ok = g[iid]["v"]
            rmax = max(math.hypot(v[0], v[2]) for v in ok)
            self.assertAlmostEqual(rmax * 100, it["raio_externo_cm"], delta=0.05, msg=iid)
            lo, hi = caixa(ok)
            self.assertAlmostEqual((hi[1] - lo[1]) * 100, it["largura_cm"], delta=0.05, msg=iid)

    def test_redondeza_aro(self):
        for rid in rk.AROS:
            iid = "aro_" + rid
            desvio, n, c = circulo(anel_externo(self.glb[iid][iid]["v"]))
            self.assertGreaterEqual(n, 64, iid)
            self.assertLess(desvio, TOL_REDONDO, f"{iid}: desvio {desvio * 1000:.2f} mm")
            self.assertLess(math.hypot(*c), TOL_PIVO, iid)

    def test_redondeza_banda_ok(self):
        for pid in rk.PNEUS:
            iid = "pneu_" + pid
            desvio, n, c = circulo(anel_externo(self.glb[iid][iid + "_Ok"]["v"]))
            self.assertGreaterEqual(n, 64, iid)
            self.assertLess(desvio, TOL_REDONDO, f"{iid}: desvio {desvio * 1000:.2f} mm")
            self.assertLess(math.hypot(*c), TOL_PIVO, iid)

    def test_flat_6cm_mais_baixo(self):
        for pid in rk.PNEUS:
            g = self.glb["pneu_" + pid]
            lo_ok, hi_ok = caixa(g[f"pneu_{pid}_Ok"]["v"])
            lo_f, hi_f = caixa(g[f"pneu_{pid}_Flat"]["v"])
            queda = lo_f[2] - lo_ok[2]
            self.assertAlmostEqual(queda, 0.06, delta=0.005, msg=f"{pid}: queda {queda * 100:.2f} cm")
            self.assertAlmostEqual(hi_f[2], hi_ok[2], delta=0.005, msg=f"{pid}: o topo do Flat saiu do lugar (pivô)")
            self.assertLess(abs((lo_f[0] + hi_f[0]) / 2), 0.005, pid)
            # o flanco estufa para fora perto do chão
            self.assertGreater(hi_f[1] - lo_f[1], hi_ok[1] - lo_ok[1] + 0.02, pid)

    def test_torn_aro_quase_no_chao(self):
        for pid, (_, _, pol) in rk.PNEUS.items():
            g = self.glb["pneu_" + pid]
            aro = self.glb[f"aro_aco{pol}"][f"aro_aco{pol}"]["v"]
            r_aba = max(math.hypot(v[0], v[2]) for v in aro)
            lo_t, hi_t = caixa(g[f"pneu_{pid}_Torn"]["v"])
            folga = -lo_t[2] - r_aba
            self.assertTrue(0.005 < folga < 0.03, f"{pid}: aba do aro a {folga * 100:.1f} cm do chão")
            lo_ok, hi_ok = caixa(g[f"pneu_{pid}_Ok"]["v"])
            self.assertAlmostEqual(hi_t[2], hi_ok[2], delta=0.03, msg=f"{pid}: topo do Torn longe do Ok (pivô)")

    def test_pivo_no_cubo(self):
        for iid, g in self.glb.items():
            for nome, o in g.items():
                if nome.endswith("_LOD1") or nome.endswith(("_Flat", "_Torn")):
                    continue
                lo, hi = caixa(o["v"])
                self.assertLess(abs((lo[0] + hi[0]) / 2), TOL_PIVO, f"{nome} centro X")
                self.assertLess(abs((lo[2] + hi[2]) / 2), TOL_PIVO, f"{nome} centro Z")

    def test_orcamento_roda(self):
        conferidas = 0
        for rid, cfg in rk.AROS.items():
            t_aro = self.glb["aro_" + rid]["aro_" + rid]["tri"]
            for pid, (_, _, pol) in rk.PNEUS.items():
                if pol != cfg["pol"]:
                    continue
                t_ok = self.glb["pneu_" + pid][f"pneu_{pid}_Ok"]["tri"]
                t_cal = self.glb[f"calota{pol}"][f"calota{pol}"]["tri"] if cfg["tipo"] == "aco" else 0
                tot = t_aro + t_ok + t_cal
                self.assertLessEqual(tot, rk.ORCAMENTO_RODA, f"{rid} + {pid}: {tot}")
                conferidas += 1
        self.assertEqual(conferidas, len(self.kit["rodas_completas"]))
        for r in self.kit["rodas_completas"]:
            self.assertTrue(r["dentro_do_orcamento"], r)

    def test_lod1(self):
        for iid, g in self.glb.items():
            for nome, o in g.items():
                if nome.endswith("_LOD1"):
                    continue
                razao = g[nome + "_LOD1"]["tri"] / o["tri"]
                self.assertTrue(0.3 <= razao <= 0.5, f"{nome}: LOD1 com {razao:.2f}")

    def test_materiais(self):
        for iid, g in self.glb.items():
            mats = set(m for o in g.values() for m in o["mats"])
            tipo = self.itens[iid]["tipo"]
            if tipo == "aro":
                self.assertIn("aro_aco" if iid.startswith("aro_aco") else "aro_liga", mats)
                self.assertIn("parafuso", mats)
            else:
                self.assertIn("pneu" if tipo == "pneu" else "calota", mats)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a.startswith("-")])
