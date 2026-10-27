# Acervo 3D

Cópia única dos modelos 3D que os jogos do Felipe (Detonauto, Age of Earth, Speed Tchê e TDFende)
usam ou já baixaram, para reaproveitar um modelo em outro jogo sem baixar de novo e sem depender de o
autor manter o modelo no ar.

- **Índice para pessoas:** aba "Modelos 3D" do doc do estúdio,
  https://claude.ai/artifact/72KXW2Tve5gB65BHD1CDp6 (documento do Claude Docs, lido pelo conector).
- **Índice para máquina:** `catalogo.csv`, uma linha por arquivo, com fonte, autor, licença, link do
  original, jogo que usa, caminho no repositório do jogo e texto de crédito.
- **Créditos obrigatórios:** `CREDITOS.md` (CC BY 4.0 e modelos gerados na conta do Meshy).

Montado em 14/10/2026 a partir de `AgeOfEarth/art/meshy/` (81 GLB), `TDFende/Assets/Resources/TDFende/`
(bichos e torres em FBX) e `SpeedTche/art/` (carros). Repositório público, sem LFS: só entra o que a
licença deixa redistribuir (CC0, CC BY 4.0 com o crédito em `CREDITOS.md`, gerado na conta do Felipe ou
próprio).

## Pastas

`<categoria>/<fonte>/<arquivo>`

| Categoria | O que tem |
| --- | --- |
| `animais/` | Bichos do TDFende (com animação), javalis e cervos do Age of Earth |
| `criaturas/` | As 19 criaturas míticas do Age of Earth |
| `personagens-e-unidades/` | Soldados gregos, aldeãs, Héracles, cerco |
| `edificios/` | Edifícios e maravilhas do Age of Earth; torres, fortaleza e acampamento do TDFende (`torres-tdfende/`) |
| `natureza/` | Árvores, arbustos, rochas, veios de ouro, tocos; a amendoeira de orla do Detonauto (`proprios/`, por script) |
| `veiculos/` | Galeão, o carro Falcão do Kenney, os 13 moldes de carroceria do Speed Tchê, os veículos genéricos do Sketchfab (sem marca), os carros nacionais do Meshy com o corte em peças (`meshy-conta/quebravel/`) e o kit de carro completo por dentro e por baixo (`meshy-conta/completo/`) |
| `mobiliario-urbano/` | Postes, lixeiras, telefones públicos, bueiro, ponto de ônibus, cone, barreira, banco de praça, caçamba, carrinho de pipoca (Detonauto e AO VIVO); a rede aérea (poste de concreto e fios) do Detonauto em `proprios/` |
| `marcos/` | Pontos turísticos em domínio público: Theatro Municipal do Rio (Sketchfab), Arcos da Lapa, relevo do Pão de Açúcar, roda-gigante genérica e estátua estilizada de braços abertos (`proprios/`, feitos por script no Detonauto) |
| `cidade/` | Peças de cidade feitas por script no Detonauto (`detonauto-script/`) |

| Fonte | Licença | Condição |
| --- | --- | --- |
| `meshy-galeria/` | CC0 | Nenhuma |
| `sketchfab/` | CC BY 4.0 ou CC0 (coluna `licenca`) | CC BY 4.0: crédito ao autor na tela de créditos de cada jogo; CC0: nenhuma |
| `meshy-conta/` | Gerado na conta do Felipe | No plano grátis vale CC BY 4.0 com crédito ao Meshy; no Pro (ativado em 03/10/2026 às 23h11) é do Felipe. Javali, tigre e 1ª Torre de Canhão: plano a confirmar |
| `kenney/` | CC0 | Nenhuma |
| `speed-tche-moldes/` | Própria | Nenhuma |
| `proprios/` | Própria (geometria por script de um jogo do estúdio) ou dados públicos do governo dos EUA (USGS SRTM, NOAA ETOPO1) com crédito pedido | Dado público: o crédito do USGS/NOAA na tela de créditos do jogo (coluna `credito` do catálogo) |

## Lote do Sketchfab (22/10/2026)

Passo 2 do plano de realismo: modelos realistas com textura PBR baixados pela Download API do Sketchfab,
só CC0 e CC BY 4.0, cada um em `<categoria>/sketchfab/<slug>__<uid>.glb` (o `uid` é o do Sketchfab; a
página do original é `https://sketchfab.com/3d-models/<uid>`). Os GLB são os que o próprio Sketchfab
gera (texturas em 1024 px). A coluna `notas` do catálogo traz triângulos, animações e tamanho; `usado_em`
diz o jogo alvo ("reserva" quando ainda não entrou em jogo nenhum). Os modelos do kenchoo são
reconstruções de modelos CC BY de outros autores: o crédito cita os dois.

## Formatos

- Os GLB do Age of Earth já estão reduzidos (até ~90 mil triângulos, textura 1k). O original de cada
  um está no link da coluna `url`.
- Os FBX do TDFende foram convertidos para o Unity. Os `*_cor.bytes` e `*_normal.bytes` são texturas
  cruas do conversor (`TDFende/Tools/ConverterTorres/converte.py`); as dos bichos são JPG e PNG.
- O `falcao-kenney.glb` é a saída do conversor do Speed Tchê (`scripts/convert-car.ts`), não o original.

## O que não entra aqui

- **Epic** (City Sample, templates, Manny e Quinn): a licença só vale dentro de jogo feito no Unreal.
  Baixa de novo pelo Fab ou pelo Launcher.
- **Mixamo**: termos da Adobe; fica no PC.
- **Poly Haven**: CC0 e estável; baixa de novo pelo link `https://polyhaven.com/a/<id>` da aba Modelos 3D.
- **Originais acima de 50 MB**: ficam no PC, com cópia no D:.

## Regras

1. Antes de baixar ou gerar um modelo para qualquer jogo, procure aqui e na aba Modelos 3D.
2. Modelo novo entra no mesmo dia em três lugares: o arquivo em `<categoria>/<fonte>/`, a linha no
   `catalogo.csv` e a linha na aba Modelos 3D. O registro de licença do próprio jogo continua valendo
   (`docs/licencas.csv`, `art/meshy/catalogo.json`, `docs/licencas/manifesto.json` ou `docs/ARTE.md`).
3. Licença aceita: CC0, CC BY 4.0 com crédito, gerado na conta do Meshy, próprio, e dado público (domínio
   público do governo dos EUA, como o relevo SRTM/ETOPO1) com o crédito que o provedor pede. Nunca NC, ND,
   "uso pessoal" ou origem não comprovada.
4. Nenhum arquivo acima de 50 MB (o GitHub recusa acima de 100 MB). Sem LFS, para não gastar a cota
   do Detonauto.
5. Ao levar um modelo para outro jogo, acrescente o jogo em `usado_em` e o crédito na tela de créditos
   dele (`CREDITOS.md`).
6. Commits em português, no imperativo.

## Lote do Meshy (22/10/2026)

15 modelos gerados pela API na conta do Felipe (plano Pro: o modelo é dele), aprovados por ele em lote
("ok, siga", teto de 560 créditos; gastos 490, saldo 352). Text to 3D Meshy 7.1 com remesh, prévia olhada
antes de pagar a textura (PBR 2K, luz removida), limpos por `ferramentas/limpar_ia.py` (escala real em metros,
pivô na base, frente em +X). Pastas `<categoria>/meshy-conta/`; livro-caixa em `meshy/livro-caixa.md`; prévias
em `meshy/previas/2026-10/`; manifesto com prompts em `meshy/lote-2026-10.json`. Tudo é `gerado_por_ia` e entra
na declaração de IA da Steam do jogo que usar. Reprovados e não refinados: orelhão v1 (forma errada), banca de
jornal v1 (faces esticadas) e v2 (letreiro em relevo); a v3 ficou como reserva.

## Lote do Meshy (24/10/2026)

Lote 2026-10c, aprovado pelo Felipe com teto de 800 créditos (gastos 796, saldo 790). Antes de gerar, o que já existia de
graça entrou do Sketchfab (guarda-sol, cadeira e kit de praia, ducha de calçadão, caçamba de entulho). Prévias em
`meshy/previas/2026-10c/`, manifesto em `meshy/lote-2026-10c.json`.

- **Tráfego** (`veiculos/meshy-conta/`): picape pequena, moto de entrega 150 cc, ônibus urbano, caminhão baú leve e van de
  passageiros, pelo método das vistas com traseira (multi-image-to-3d PBR 2K). Chegaram sem remesh (0,6 a 2,5 milhões de
  triângulos) e foram reduzidos por Decimate (60 a 100 mil) antes do `limpar_ia.py --frente=-x`. O táxi é o Barão
  retexturizado com uma caixa de teto lisa posta no Blender. Corte em peças da picape (`quebravel/picape-pequena/`, mapa
  acertado à mão: 28 peças) e da van (`quebravel/van-passageiros/`, 31 peças, bruto). A van saiu do gerador com a frente
  1,5 cm acima do chão e foi nivelada (0,23°) para o `carro_quebravel.py` achar as quatro rodas.
- **Carcaças** (`veiculos/meshy-conta/carcacas/`): queimada e abandonada dos 13 carros nacionais, e abandonada das 2 reservas,
  por retexture com a UV original: a malha é a mesma do carro, então o mapa de `quebravel/<carro>/` vale. Os queimados por
  texto saíram cinza com manchas laranja e foram refeitos com a foto do Besouro queimado como estilo; as 2 reservas ficaram sem
  queimado. Nos queimados a borracha dos pneus foi apagada da malha (raio e posição das rodas do mapa de corte) e o carro
  assentou no aro chamuscado, 6 a 11 cm mais baixo. Nos abandonados, o retexture pintou números de placa e um nome de modelo: apagados com `apagar_letreiro.py`.
- **Orla e rua** (`mobiliario-urbano/meshy-conta/`): posto de salva-vidas (monte de areia cortado), placa de esquina em
  branco, cavalete de obra e papeleira laranja (image-to-3d).


Pendente: a van de passageiros tem buracos no para-brisa (na malha; repintar, aplainar e tapar no Blender não resolveram). O Felipe vai tentar o Free Retry no site do Meshy (sem crédito) na tarefa `01a16c1b-c8b8-7786-b239-2821820ef791`; a API não tem retry grátis. Se sair boa: baixar, Decimate para ~80 mil, `limpar_ia.py --maior 5.95 --frente=-x`, nivelar pelas rodas e `carro_quebravel.py --portas 2`, e trocar `veiculos/meshy-conta/van-passageiros__01a16c1b.glb`.

## Carro completo por dentro e por baixo (v2, 27/10/2026)

Pedido do Felipe (`Detonauto/docs/pedido-carro-completo.md`: "o carro tem que ser real, com as partes internas, externas, TUDO
COMPLETO"). `ferramentas/carro_completo.py` gera, encaixado nas medidas de cada carro cortado, o habitáculo, o forro e a chapa
interna de cada porta, o vão da porta, o porta-malas (ou a área de carga), o vão do motor, o embaixo e os freios. Próprio, CC0,
sem IA. Em `veiculos/meshy-conta/completo/<carro>/`: o GLB (LOD0 + LOD1), o JSON com as peças e o que tirar do corte, e as
prévias (porta arrancada a 1,5 m, porta caída por dentro, cabine pelo para-brisa, painel, capô aberto, motor de trás, embaixo).
A v2 trouxe o vão do motor denso por época e motor, materiais 1024 com sujeira de uso (pó, graxa, gasto) e oclusão nos vértices,
proporções reais no banco e no forro de porta, e as carrocerias de furgão, cabine avançada e jipe; detalhes e limites em
`ferramentas/README.md`. Comparação com a v1: `completo/hatch-quadrado/hatch-quadrado_v1_x_v2.jpg`.

| Carro | Época | Carroceria | Motor | Peças | Triângulos LOD0 / LOD1 | MB |
| --- | --- | --- | --- | --- | --- | --- |
| Cuiabano (`hatch-quadrado`) | 90 | hatch | l4_transversal | 78 | 243.372 / 72.955 | 21,5 |
| Tupiniquim (`tupiniquim`) | 90 | hatch | l4_transversal | 90 | 260.380 / 78.054 | 22,8 |
| Caipora (`caipora`) | 90 | hatch | l4_transversal | 78 | 242.796 / 72.780 | 21,5 |
| Pampeiro (`pampeiro`) | 2000 | hatch | l4_transversal | 92 | 278.608 / 83.515 | 24,1 |
| Barão (`barao`) | 2000 | sedan | l4_transversal | 92 | 282.036 / 84.545 | 24,3 |
| Furgãozinho da Firma (`furgaozinho-da-firma`) | 90 | furgao | l4_transversal | 75 | 229.216 / 68.710 | 20,6 |
| Besouro (`besouro`) | 70 | sedan | boxer_traseiro | 66 | 190.596 / 57.137 | 16,5 |
| Pão de Forma (`pao-de-forma`) | 70 | cabine_avancada | boxer_traseiro | 66 | 181.800 / 54.494 | 15,8 |
| Gaúcho V8 (`gaucho-v8`) | 80 | sedan | v8_longitudinal | 90 | 277.020 / 83.048 | 24,3 |
| Trilheiro (`trilheiro`) | 2000 | jipe | l4_longitudinal | 82 | 264.312 / 79.226 | 23,4 |
| Lambari (`lambari`) | 70 | sedan | l4_longitudinal | 78 | 240.088 / 71.971 | 21,1 |
| Jabuti (`jabuti`) | 70 | hatch | l4_transversal | 78 | 239.828 / 71.895 | 20,9 |
| Sagui (`sagui`) | 2000 | hatch | l4_transversal | 79 | 249.182 / 74.689 | 21,8 |

O mapa de corte do Besouro foi acertado à mão (porta até a dobradiça, capô e tampa na largura de verdade, para-brisa por
planos e a casca de dentro tirada com o papel `remover`), e o do Trilheiro também (a porta estava no para-lama). Ainda não foi
para o Unreal nem aprovado por captura ao lado de foto real (`aprovar-visual` do Detonauto).
