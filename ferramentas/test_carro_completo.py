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


NACIONAIS = ("hatch-quadrado", "tupiniquim", "caipora", "pampeiro", "barao", "furgaozinho-da-firma", "besouro", "pao-de-forma",
             "gaucho-v8", "trilheiro", "lambari", "jabuti", "sagui")


class TestNacionais(unittest.TestCase):
    def test_os_13_tem_dados_e_medidas_sem_aviso(self):
        for cid in NACIONAIS:
            M, cfg, _, avisos = _medidas(cid)
            self.assertEqual(avisos, [], cid)
            self.assertEqual(M["avisos"], [], cid)
            self.assertIn(cfg["carroceria"], cc.CARROCERIAS, cid)

    def test_proporcoes_reais_da_cabine(self):
        for cid in NACIONAIS:
            M, *_ = _medidas(cid)
            # assento a 0,27 m do piso e espaço para a cabeça de carro de verdade (0,8 a 1,15 m do assento ao forro; furgão e jipe
            # são altos, até 1,25 m)
            self.assertAlmostEqual(M["z_assento"] - M["z_piso"], 0.27, places=3)
            teto = 1.25 if M["carroceria"] in ("cabine_avancada", "jipe") else 1.15
            self.assertTrue(0.8 <= M["z_teto_int"] - M["z_assento"] <= teto, (cid, M["z_teto_int"] - M["z_assento"]))
            # piso abaixo da soleira e painel na frente do banco, com espaço para as pernas
            self.assertLess(M["z_piso"], M["z_saia"], cid)
            self.assertGreater(M["x_painel"] - M["x_encosto_d"], 0.55, cid)

    def test_antena_e_bagageiro_nao_entram_na_altura(self):
        for cid, alt in (("caipora", 1.49), ("sagui", 1.54), ("furgaozinho-da-firma", 1.48), ("pampeiro", 1.475)):
            M, *_ = _medidas(cid)
            self.assertAlmostEqual(M["z_teto"], alt, places=3)

    def test_cabine_avancada_sem_capo(self):
        M, cfg, *_ = _medidas("pao-de-forma")
        self.assertEqual(cfg["carroceria"], "cabine_avancada")
        self.assertTrue(M["motor_traseiro"])
        self.assertGreater(M["x_encosto_d"], M["xd"] - 0.5)          # o motorista vai perto do eixo da frente
        self.assertGreater(M["x_corta_fogo"], M["xd"] + 0.6)         # a parede da frente é o corta-fogo
        self.assertNotIn("frente", M["vaos"])

    def test_jipe_com_a_porta_no_lugar(self):
        M, cfg, *_ = _medidas("trilheiro")
        self.assertEqual(cfg["tracao"], "4x4")
        p = M["portas"]["fl"]
        self.assertLess(p["x0"], -0.6)                # porta acertada à mão no mapa (o corte tinha pego o para-lama)
        self.assertGreater(p["x1"], 0.2)
        self.assertGreater(p["z1"] - p["z0"], 0.6)

    def test_mapa_do_besouro_acertado(self):
        mapa = cc.ler_corte(os.path.join(QUEBRAVEL, "besouro"), "besouro")["mapa"]
        partes = {p["name"]: p for p in mapa["parts"]}
        self.assertAlmostEqual(partes["door_fl"]["box"][1], 0.62)
        self.assertEqual(partes["glass_windshield"]["take"], "faces")
        remover = [p for p in mapa["parts"] if p.get("papel") == "remover"]
        self.assertEqual(len(remover), 8)            # casca de dentro: 2 portas, 2 janelas de trás, para-brisa, vidro de trás, 2 tampas


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


class TestPicape(unittest.TestCase):
    """Carroceria picape (Tropeiro, 30/10/2026): cabine simples sem banco de trás e a caçamba fora dos vãos que saem do corte."""

    def setUp(self):
        dados = cc.ler_dados()
        self.cfg, _, self.avisos = cc.config_carro(dados, "tropeiro")
        pasta = os.path.join(AQUI, "..", "veiculos", "sketchfab", "quebravel", "tropeiro")
        self.M = cc.medidas(cc.ler_corte(pasta, "tropeiro"), self.cfg)

    def test_tropeiro_e_picape_sem_aviso(self):
        self.assertEqual(self.cfg["carroceria"], "picape")
        self.assertIn("picape", cc.CARROCERIAS)
        self.assertEqual(self.avisos, [])
        self.assertEqual(self.M["avisos"], [])

    def test_cabine_acaba_na_parede_de_tras(self):
        M = self.M
        # o encosto fica à frente da parede da cabine, e "banco de trás" é a própria parede
        self.assertGreater(M["x_encosto_d"], M["x_cabine_tras"] + 0.1)
        self.assertEqual(M["x_encosto_t"], M["x_cabine_tras"])
        self.assertGreater(M["x_cabine_tras"], M["xt"] + 0.5)

    def test_cacamba_nao_e_vao(self):
        M = self.M
        self.assertNotIn("traseira", M["vaos"])
        self.assertLessEqual(M["vaos"]["cabine"][0], M["x_cabine_tras"])
        # o assoalho da caçamba vem do mapa, acima do eixo
        self.assertAlmostEqual(M["z_mala"], 0.55, places=3)
        self.assertGreater(M["z_mala"], M["R"])

    def test_outras_carrocerias_nao_mudam(self):
        # a medida nova só existe na picape
        dados = cc.ler_dados()
        cfg, _, _ = cc.config_carro(dados, "caipora")
        M = cc.medidas(cc.ler_corte(os.path.join(QUEBRAVEL, "caipora"), "caipora"), cfg)
        self.assertNotIn("x_cabine_tras", M)
        self.assertIn("traseira", M["vaos"])


if __name__ == "__main__":
    unittest.main()
