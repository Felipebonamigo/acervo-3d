"""
Testes da parte de medidas do carro_completo.py (não precisam do Blender):

    python3 -m unittest ferramentas/test_carro_completo.py      (na raiz do acervo)
"""

import os
import sys
import unittest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import carro_completo as cc  # noqa: E402

QUEBRAVEL = os.path.join(AQUI, "..", "veiculos", "meshy-conta", "quebravel")


def _medidas(cid, **kw):
    dados = cc.ler_dados()
    cfg, estilo, avisos = cc.config_carro(dados, cid, **kw)
    return cc.medidas(cc.ler_corte(os.path.join(QUEBRAVEL, cid), cid), cfg), cfg, estilo, avisos


class TestMedidas(unittest.TestCase):
    def test_entre_eixos_e_raio_vem_do_wheels_json(self):
        M, *_ = _medidas("hatch-quadrado")
        self.assertAlmostEqual(M["entre_eixos"], 2.3182, places=3)
        self.assertAlmostEqual(M["R"], 0.288, places=3)
        self.assertAlmostEqual(M["xd"], 1.1591, places=3)

    def test_bitola_pelas_rodas_do_mapa(self):
        M, *_ = _medidas("hatch-quadrado")
        # centro da banda: (0.594 + 0.8) / 2 = 0.697 de cada lado
        self.assertAlmostEqual(M["bitola_d"], 2 * (0.594 + 0.8 + 0.59 + 0.797) / 4, places=3)
        self.assertLess(M["y_pneu_dentro_d"], M["W"])

    def test_cabine_dentro_da_caixa_dos_vidros(self):
        for cid in ("hatch-quadrado", "besouro", "gaucho-v8"):
            M, *_ = _medidas(cid)
            ws = M["ws"]
            # painel atrás da base do para-brisa, corta-fogo na base, encostos em ordem, teto acima do assento
            self.assertLess(M["x_painel"], ws[1], cid)
            self.assertLess(M["x_encosto_d"], M["x_painel"] - 0.55, cid)
            self.assertLess(M["x_encosto_t"], M["x_encosto_d"] - 0.7, cid)
            self.assertGreater(M["z_teto_int"] - M["z_assento"], 0.8, cid)
            self.assertLess(M["z_piso"], M["z_saia"], cid)
            self.assertEqual(M["avisos"], [], cid)

    def test_portas_por_lado(self):
        M, *_ = _medidas("gaucho-v8")
        self.assertEqual(sorted(M["portas"]), ["fl", "fr", "rl", "rr"])
        self.assertEqual(M["portas"]["fl"]["lado"], 1)
        self.assertEqual(M["portas"]["rr"]["lado"], -1)
        M2, *_ = _medidas("hatch-quadrado")
        self.assertEqual(sorted(M2["portas"]), ["fl", "fr"])
        for p in M2["portas"].values():
            self.assertGreater(p["z_janela"], p["z1"])

    def test_vao_do_motor_pelo_capo(self):
        M, *_ = _medidas("hatch-quadrado")
        self.assertGreater(M["x_radiador"], M["x_corta_fogo"] + 0.6)
        self.assertLess(M["y_caixa_d"], M["y_pneu_dentro_d"])
        self.assertFalse(M["motor_traseiro"])
        Mb, cfg, *_ = _medidas("besouro")
        self.assertTrue(Mb["motor_traseiro"])
        self.assertEqual(cfg["estepe"], "frente_inclinado")

    def test_porta_malas_pela_tampa(self):
        M, *_ = _medidas("gaucho-v8")
        self.assertLess(M["x_mala_tras"], M["x_mala_frente"])
        self.assertGreaterEqual(M["z_mala"], M["z_piso"])

    def test_vaos_cobrem_cabine_e_pontas(self):
        M, *_ = _medidas("hatch-quadrado")
        cab = M["vaos"]["cabine"]
        self.assertTrue(cc._dentro((0.0, 0.5, 1.0), cab))
        self.assertFalse(cc._dentro((0.0, 0.5, 0.1), cab))       # abaixo da soleira: a saia fica
        self.assertTrue(cc._dentro_vaos((1.4, 0.0, 0.7), M["vaos"]))  # sob o capô


class TestDados(unittest.TestCase):
    def test_epoca_por_carro_e_forcada(self):
        _, cfg, estilo, _ = _medidas("besouro")
        self.assertEqual(cfg["epoca"], "70")
        self.assertTrue(estilo["manivela"])
        _, cfg, estilo, _ = _medidas("hatch-quadrado", epoca="2000")
        self.assertEqual(cfg["epoca"], "2000")
        self.assertTrue(estilo["vidro_eletrico"])

    def test_carro_fora_da_tabela_usa_padrao_com_aviso(self):
        cfg, estilo, avisos = cc.config_carro(cc.ler_dados(), "carro-inexistente")
        self.assertEqual(cfg["epoca"], cc.ler_dados()["padrao"]["epoca"])
        self.assertTrue(avisos)

    def test_epoca_invalida_recusada(self):
        with self.assertRaises(ValueError):
            cc.config_carro(cc.ler_dados(), "besouro", epoca="60")

    def test_todas_as_epocas_tem_as_chaves(self):
        dados = cc.ler_dados()
        chaves = set(dados["epocas"]["90"])
        for ep in cc.EPOCAS:
            self.assertEqual(set(dados["epocas"][ep]) - {"nota"}, chaves - {"nota"}, ep)


if __name__ == "__main__":
    unittest.main()
