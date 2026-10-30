# Tropeiro (picape aventureira): pedido para a sessão local do PC (30/10/2026)

Texto pronto para o Felipe colar na sessão local do Claude no PC, que tem o Detonauto, o Unreal e o compilador. A sessão da nuvem
fez o carro no acervo, mas não conseguiu anexar o repositório do Detonauto. Por isso o que mexe nele ficou para cá.

---

Faça o carro novo **Tropeiro** (picape de cabine simples, versão aventureira) entrar no Detonauto. O carro já está pronto no
acervo-3d (`git pull` no acervo ao lado do Detonauto):

- corte quebrável: `veiculos/sketchfab/quebravel/tropeiro/` (34 peças, `tropeiro.glb`, mapa, `_wheels.json`, textura de desgaste);
- kit completo: `veiculos/sketchfab/completo/tropeiro/` (81 peças, carroceria `picape`, grupo novo `cacamba` com
  `cargo_protetor`, `cargo_ganchos` e `cargo_santantonio`);
- modelo de origem: `veiculos/sketchfab/picape-cabine-simples-ramon__2b5c1ffec3b545168ab5280296cd5ffa.glb`, CC BY 4.0. Crédito:
  `This work is based on "Saveiro G3" (https://sketchfab.com/3d-models/saveiro-g3-2b5c1ffec3b545168ab5280296cd5ffa) by
  Ramon.Dos.Santos (https://sketchfab.com/Ramon.Dos.Santos) licensed under CC-BY-4.0`. No jogo o carro só se chama Tropeiro.

Passos:

1. **Registro:** acrescente o crédito acima no `docs/licencas.csv` e no `Data/Credits.csv`, sem apagar as linhas das outras
   sessões.
2. **Classe `picape`:** se `FDNGarageClass::All()` não tem `picape`, acrescente-a, com o teste de automação ao lado dos que já
   existem para as outras classes, e compile.
3. **`Data/Garage.csv`:** uma linha nova para o Tropeiro, copiando as colunas da linha do Cuiabano. Valores:
   - classe `picape`, carro de 2 portas, época 2000;
   - rodas: aro de liga de 14" (`aro_liga14`) com pneu 185/60 (`pneu_p185_60`), raio físico 30,8 cm;
   - entre-eixos 253,4 cm;
   - centro do cubo: `hub_y_cm` pelo `tropeiro_wheels.json`.

   Para dirigir, a picape é mais alta e mais leve atrás que o Cuiabano: comece com a massa uns 10% acima e o centro de massa uns
   4 cm mais alto, e ajuste jogando.
4. **Cadeia de conferência:** `make_crush_channels.py`, `kit_to_detonauto.py`, `glb_texturas.py` e `kit_completo_to_detonauto.py`
   com o id `tropeiro`. Confira se o grupo novo `cacamba` do kit é aceito. Ele segue a carroceria (sem `segue`) e fica fora de
   portas e tampas; se o conversor só conhece os grupos antigos, trate `cacamba` como `porta_malas`, sem recolher na casca.
5. **Prévias fiéis ao jogo:** `previa_carro.py` com `ID=tropeiro CORTE=.../quebravel/tropeiro/ KIT=.../completo/tropeiro/`, nas
   cores de `Data/Paints.csv` e nos acabamentos de `Data/PaintFinishes.csv`. Grave em `veiculos/sketchfab/previas/tropeiro/`
   (as de lá hoje são de trabalho, com materiais aproximados). Olhe cada imagem antes de dizer que ficou bom.
6. **Importar e montar no Unreal:** `Tools/Unreal/montar-cuiabano-completo.ps1 -Id tropeiro -Fonte sketchfab`. Esse script já
   aceita `-Id` e `-Fonte`; se faltar algo para a picape, generalize por parâmetro sem mudar o caminho do Cuiabano.
7. **Compilar e jogar:** dirija o Tropeiro na pista de sempre, bata de frente, de lado e de ré.
8. **Capturas no jogo, para o Felipe:**
   - 3/4 da frente e 3/4 de trás, parado;
   - de lado;
   - close da frente: grade preta, faróis, faróis de milha e placa;
   - close da traseira: lanternas em três faixas e placa no para-choque;
   - a caçamba de cima, com protetor, ganchos e santo-antônio;
   - a porta arrancada, para ver o vão e o forro;
   - o carro amassado depois de uma batida forte.

   Compare com fotos da picape real de referência: o veredito visual é a captura do jogo, não a prévia.

O que pode aparecer e onde mexer, no acervo:
- o santo-antônio atravessando o vidro de trás ou o teto: `carro_completo.py`, método `cacamba`;
- o alargador ou o protetor descolado da chapa: `detalhes_na_casca.py --protecoes`;
- a caçamba escura por dentro: o vão da lateral da caçamba (`pocket` do `fender_rear_*` no `tropeiro_mapa.json`).
