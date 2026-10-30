# Ferramentas do acervo

- `meshy_lote.py`: lote do Meshy pela API com teto de créditos e livro-caixa (`meshy/livro-caixa.md`). Fases `preview`,
  `status` (ou `olhar`, sem esperar), `refine`, `baixar`, `registrar`. Manifesto por lote em `meshy/lote-<ano-mes>.json`
  (prompt, categoria, jogo alvo, polycount, `aprovado` para o refine). As miniaturas das prévias ficam em
  `meshy/previas/<lote>/` para o Felipe olhar antes de pagar a textura.
- `limpar_ia.py`: limpeza de modelo gerado ou baixado dentro do Blender (`blender -b -P ferramentas/limpar_ia.py -- ...`):
  escala em metros, pivô na base, frente em +X, LODs por Decimate, GLB e FBX; `--sem-soltos` apaga ilhas com menos de 0,5 % dos vértices (só quando a miniatura mostra lixo: num poste, isoladores pequenos são ilhas legítimas). Não faz remesh nem bake. Testado na nuvem com o módulo `bpy` 5.2.3 (`pip install bpy` num venv).
  `--frente` diz para onde a frente aponta no arquivo de entrada: os carros do Meshy (multi-image-to-3d) chegam com a frente
  em -X, então use `--frente=-x` neles (com `=`, senão o argparse lê o `-x` como opção). Até 23/10/2026 o giro não era
  aplicado (o glTF importa a rotação em quaternion); os carros de `veiculos/meshy-conta/` foram reexportados com a frente em +X.
- `apagar_letreiro.py`: apaga letreiro, logo ou texto que o gerador pintou na textura (`--caixa x0,x1,y0,y1,z0,z1` em metros e
  `--normal` do lado de onde se olha). Lança raios sobre a caixa, monta a vista de fora da pintura, acha o que destoa do entorno
  e repinta só os texels acertados; `--previa` salva antes e depois. Letreiro denso pode pedir uma segunda passada com
  `--limiar` menor. Usado no capô do Furgãozinho da Firma.

Regras: nenhuma geração sem o Felipe aprovar o lote com o número de créditos; tudo gerado entra em `catalogo.csv` com
`gerado_por_ia` nas notas e na aba "Modelos 3D" do doc do estúdio no mesmo dia; licença CC0 ou CC BY só para o que
vem da comunidade; o que a conta do Felipe gera no plano Pro é dele.

## carro_quebravel.py

Transforma um carro que já vem em peças (a série modular de Daniel Zhabotinsky em `veiculos/sketchfab/`, CC BY 4.0, e outros GLB, glTF
ou FBX com um objeto por peça) num kit de peças padronizado para o pipeline de dano do Detonauto (`Tools/Blender/split_car_parts.py` e
`make_damage_morphs.py`).

```
blender -b --python-exit-code 1 -P ferramentas/carro_quebravel.py -- --entrada veiculos/sketchfab/sedan-kiri-10__<uid>.glb --out <pasta>
python -I ferramentas/carro_quebravel.py -- --entrada <carro.glb> --out <pasta> [--id nome] [--escala 0.01] [--amostras 24] [--sem-previa] [--sem-fbx] [--em-pecas]
```

Leva ~45 s por carro na CPU (quase tudo é a prévia). Saída em `--out`:

| Arquivo | O que é |
| --- | --- |
| `<id>.glb` | todas as peças, um objeto por peça com o nome padronizado, materiais renomeados |
| `<id>_pecas/<peca>.fbx` | uma por peça, com as opções de FBX do Detonauto (as do `make_street_light.py`); o pivô da peça vai na origem do FBX |
| `<id>_texturas/` | as texturas do GLB, que os FBX referenciam por caminho absoluto (o Detonauto troca os materiais pelos dele no Unreal) |
| `<id>_pecas.json` | por peça: papel, lado, `caixa_m` no formato `box` dos mapas do Detonauto, pivô, triângulos, materiais, a peça do Detonauto, os objetos de origem e a conferência da malha; no topo, dimensões, escala, orientação, material original → padrão, papel → materiais, removidos, `outros` e avisos |
| `<id>_wheels.json` | eixos e raio da roda em cm, no formato que `make_damage_morphs.py` e `split_car_parts.py` leem em `--wheels` |
| `<id>_previa.png` | prévia explodida em Cycles: à esquerda os materiais, à direita a cor por papel com o nome de cada peça |

O que ele faz:

- **Convenção do Detonauto:** metros, frente em +X, esquerda em +Y, cima em +Z; pivô do carro no chão (base dos pneus), no meio entre
  os eixos. As peças ficam no espaço do carro; as rodas têm o pivô no centro do cubo (`pivo_m` no JSON). A escala sai das rodas
  (diâmetro de 0,45 a 1,30 m) e do comprimento (2,4 a 12 m), testando m, cm, mm, polegada e pé; `--escala` força. A frente é achada
  pelos faróis e para-brisa contra lanternas e vidro traseiro; comprimento em Y gira 90°.
- **Papéis por regras:** regex sobre o nome do objeto (sem o prefixo do modelo, como `Kiri10_`), com a tabela `EXCECOES` no topo do
  script antes das `REGRAS` gerais e, sem regra, o material. Vocabulário: `body`, `hood`, `trunk`, `bumper_front`, `bumper_rear`,
  `glass_windshield`, `glass_rear`, `glass_door_fl/fr/rl/rr`, `headlight_left/right`, `taillight_left/right`, `wheel_fl/fr/rl/rr`,
  `interior`, `underbody` e `outros_<nome>` (não reconhecido, listado no relatório e no JSON).
- **Posição manda no lado:** rodas e vidros de porta levam o lado e a ponta pela posição, e um nome que contradiz a posição vira aviso (o
  Fairheaven tem as rodas RL e RR trocadas; o LCT3000 tem dois `Glass_Driver` e dois `WheelStock_FR`). Objetos com os dois lados juntos
  (os dois faróis num objeto, os vidros de trás) são divididos por ilha; ilha de luz no meio do carro (pisca lateral, lanterna lateral
  do baú) vai para a carroceria.
- **Tira emblemas e placas** (`Badges`, `Numberplate`, `logo`), mesmo de marca fictícia.
- **Materiais padronizados:** `pintura`, `vidro`, `luz`, `pneu`, `interior`, `chassi` (plástico escuro de baixo; o nome casa com o
  material escuro que o `split_car_parts.py` procura) e `cromado`; sem regra vira `outro` e entra nos avisos.
- **Malha validada:** faces degeneradas, vértices e arestas soltos, NaN; as normais do arquivo são preservadas (atributo de canto, como
  no `split_car_parts.py`), faces com a ordem contra a normal do arquivo são viradas, e vidro de uma face virado para dentro é virado.

### Resultados (23/10/2026)

| Carro | Comprimento | Entre-eixos | Peças | Outros |
| --- | --- | --- | --- | --- |
| `sedan-kiri-10` | 4,35 m | 2,70 m | 21 | nenhum |
| `sedan-fairheaven-lt80` | 5,00 m | 2,65 m | 21 | nenhum |
| `hatch-milano-95` | 3,85 m | 2,42 m | 20 (sem `trunk`: a tampa traseira vem fundida no `body`) | nenhum |
| `picape-lightbody-90` | 5,36 m | 3,16 m | 19 | `outros_bullbar_b` (quebra-mato) |
| `caminhao-bau-lct3000-07` | 5,86 m | 3,35 m | 18 (`trunk_left/right` = portas do baú) | nenhum |

Todos já vinham em metros e com a frente em +X. A picape e o caminhão não têm vidros de porta traseira; a caçamba da
picape é `body` e o caminhão não tem capô.

### Modo malha única (carros do Meshy, 23/10/2026)

Os carros nacionais gerados no Meshy (`veiculos/meshy-conta/`: `hatch-quadrado`, `besouro`, `pao-de-forma`, `tupiniquim`, `barao`) chegam
como **uma malha só** (~79 mil triângulos, textura PBR 2K, vidro e luzes só pintados). Com um objeto só no arquivo o script entra
sozinho no modo malha única (`--malha-unica` força; `--em-pecas` desliga):

```
python -I ferramentas/carro_quebravel.py -- --entrada veiculos/meshy-conta/barao__01a16960.glb --out <pasta> --portas 4 [--frente -x]
    [--mapa <pasta>/barao_mapa.json] [--detonauto ../Detonauto] [--debug-classes] [--sem-previa] [--sem-fbx] [--amostras 12]
```

~2,5 min por carro na CPU (metade é a prévia). Mesma saída do modo em peças, mais:

| Arquivo | O que é |
| --- | --- |
| `<id>_mapa.json` | o mapa de peças gerado pelas proporções (caixas, normais, espessura, vão); edite e rode de novo com `--mapa` |
| `<id>_amassada.png` | intacto, frente + esquerda em 1,0 e traseira + direita + teto em 1,0, com o campo do `make_damage_morphs.py` do Detonauto (lido como biblioteca, nada gravado lá); o `_pecas.json` traz o menor determinante por zona e a fresta medida na costura depois de amassar |
| `<id>_classes.png` | (`--debug-classes`) a classe de textura de cada face: vidro por janela, faróis, lanternas, placas, grade, retrovisores |

Como funciona:

1. **Solda** os vértices repetidos das costuras de UV (a malha do Meshy é uma ilha por ilha de UV; os UVs ficam nos cantos, nada
   estica) e guarda a normal de cada canto, que atravessa os cortes.
2. **Frente** pelos retrovisores (pico estreito de largura acima da cintura, na metade da frente); os cinco vinham com a frente em -X e
   foram girados 180°. `--frente` força. Origem no chão, entre os eixos.
3. **Rodas** pela geometria: contato com o chão nas quatro pontas, raio pela banda de rodagem (faces a um raio R do cubo com a normal
   para fora dele), aro onde a face externa deixa de ser borracha escura, calota onde o miolo avança para fora. Saem `wheel_<pos>_tire`,
   `wheel_<pos>_rim` e `hubcap_<pos>`, com pivô no cubo; atrás de cada roda a carroceria ganha uma **caixa de roda escura** (arco +
   parede de dentro), nunca um buraco.
4. **Vidros** pela textura (cor na UV de cada face): pouco saturado e diferente da pintura (mais escuro, menos saturado ou de outro
   matiz), mais as regiões cercadas pela borracha (rugosidade alta e metal zero); cada janela é o fecho convexo dos pedaços acima da
   cintura (o para-brisa e o vidro traseiro, espelhados em Y), separada em `glass_windshield`, `glass_rear`, `glass_door_fl/fr` e
   `glass_door_rl/rr` (janela de trás ou do vigia). Nos carros de 4 portas com a coluna B preta, corta na faixa mais escura do meio.
5. **Faróis, lanternas, placas e grade** pela textura nas pontas (claro / vermelho-âmbar / branco no meio / escuro entre os faróis);
   pedaço pequeno demais fica no corpo, com aviso.
6. **Painéis por planos** (como o `split_car_parts.py`): para-choques, capô (largura do para-brisa), tampa traseira (vertical no hatch e
   na van, deck no sedã e no besouro), saias laterais, portas (uma ou duas por lado; na van a da cabine), para-lamas dianteiros e
   traseiros, retrovisores. Cada seleção passa por um fechamento e fica só com as partes conexas grandes (sem fiapos).
7. Cada peça sai **fechada** (espessura, lado de dentro em `chassi`) e deixa um **vão** escuro (`MI_DNVao`) na carroceria; atrás dos
   vidros o vão é a casca escura de interior (35 cm). Materiais: `pintura` (o do Meshy), cópias com a mesma textura `vidro`, `luz`,
   `pneu`, `cromado`; sem textura `chassi` e `MI_DNVao`.

Peças que o vocabulário do Detonauto ainda não tem (listadas em `fora_do_vocabulario_do_detonauto` no `_pecas.json`): `door_rl/rr`
(porta traseira), `side_skirt_*`, `mirror_*`, `grille`, `plate_*`, `wheel_*_tire/rim` e `hubcap_*` (a roda hoje é inteira do Chaos).

Limites conhecidos: corte reto por caixa (não segue o vinco do Meshy); placa da van branca não sai (pintura branca); faróis redondos da
van e do besouro e as lanternas do besouro não se separam da pintura pela cor; escapamento, antena e limpadores são só pintura ou
fundidos no assoalho (ficam no corpo); em amassado forte de lado, a casca de interior de 30 cm atrás do vidro da porta pode aparecer
pela janela.

### Os 13 carros nacionais cortados (23/10/2026)

`veiculos/meshy-conta/quebravel/<carro>/` guarda o que repete o corte igual: o mapa de peças (`_mapa.json`), o relatório
(`_pecas.json`), as rodas (`_wheels.json`) e uma prévia explodida e amassada (`_previa.jpg`). O GLB e os FBX das peças
(~40 MB por carro) não entram no acervo: saem de novo em ~2,5 min com
`carro_quebravel.py -- --entrada veiculos/meshy-conta/<carro>__<id>.glb --out <pasta> --portas N --mapa veiculos/meshy-conta/quebravel/<carro>/<carro>_mapa.json`.
De 28 a 40 peças por carro; fresta zero ao amassar nos 13. Em 27/10/2026 o mapa do Besouro foi acertado à mão (porta de -0,33 a 0,62 m, capô e tampa do motor mais largos, para-brisa por
planos e oito caixas com `"papel": "remover"`, que tiram da carroceria a casca de dentro que o Meshy fez atrás dos vidros, da porta e
das tampas, sem virar peça nem vão) e o do Trilheiro (porta de -0,66 a 0,29 m, para-lamas da frente, vidros e capô por planos com
`"ignorar_rotulos": true`, porque a cor oliva confundia a classe de vidro). No Pampeiro, no Furgãozinho e no Trilheiro o para-brisa não sai
pela cor, então o capô (e no jipe o para-choque dianteiro) foi posto à mão no mapa, pelo perfil do teto. O bagageiro do
Furgãozinho sai como peça (`roof_rack`, de 1,53 m para cima) para soltar junto com a escada; no Besouro as tampas (capô e
motor) foram limitadas a ~85 cm de largura e o para-choque traseiro à lâmina da ponta, para não levar os para-lamas.

### O que falta para o pipeline de dano do Detonauto

1. **Portas e para-lamas estão fundidos no `body`** (nesta série, só capô, porta-malas, para-choques, vidros, luzes e rodas são objetos
   próprios). **O corte por planos do `split_car_parts.py` resolve**, testado no Kiri: com `body.fbx` + `underbody.fbx` como `--inputs`
   (o `underbody` traz o material `chassi`, que o script exige para o lado de dentro e os vãos) e o `<id>_wheels.json` como `--wheels`,
   um mapa com `DoorLeft`, `FenderFrontLeft` e `FenderRearLeft` (espelhados) saiu limpo, com borda reta e vão escuro. Duas condições:
   cada caixa precisa de `"material": "pintura"` (sem isso a caixa leva junto a caixa de roda e a suspensão do `underbody`), e as caixas
   são medidas à mão por carro a partir de `caixa_m` dos vidros e rodas no `_pecas.json` (o mapa de teste do Kiri está no rascunho da
   sessão; o do Detonauto vai em `Tools/Blender/parts/<Carro>.json`). O corte é reto: não segue o vinco da porta do modelo.
2. **Tampa do hatch:** no Milano a tampa traseira também precisa de caixa (`Trunk`) no mapa.
3. **Sedã de 4 portas:** o contrato (`docs/regras-pecas.md`) tem uma porta por lado. A porta de trás fica na carroceria, ou o contrato
   ganha `DoorRearLeft/Right` (mudança no enum `EDNDamagePart`, `Data/CarParts.csv` e testes).
4. **Peças já separadas entram como peças do mapa** com `"take": "islands"` (capô, porta-malas, para-choques e lentes), ou o `split`
   ganha uma opção para receber peças prontas em vez de recortar. Hoje ele espera a carroceria inteira num FBX só.
5. **Retrovisores e frisos** estão dentro do `underbody` (objeto `Bottom` do modelo). Para soltar o retrovisor (regra do contrato), é preciso
   mais uma caixa no mapa.
6. **Unreal:** as rodas viram as rodas do Chaos Vehicle (pivô no cubo já pronto, raio no `_wheels.json`); os vidros e lentes ligam aos
   materiais de trinca; as linhas de `Data/CarParts.csv` e `Data/CarGlass.csv` do carro novo, o `CarId` e a captura de aprovação
   (`aprovar-visual`) ainda faltam. O crédito CC BY do autor entra na tela de créditos e o modelo em `docs/licencas.csv`.

## Scripts pequenos do lote de 24/10/2026

Todos rodam com o módulo `bpy` no Python (`python ferramentas/<script>.py ...`, num venv com `pip install bpy pillow numpy`).

| Script | Para quê | Uso |
| --- | --- | --- |
| `decimar.py` | reduzir um GLB que o Meshy entregou sem remesh (multi-image e image-to-3d chegaram com 0,1 a 2,5 milhões de triângulos) antes do `limpar_ia.py`; Decimate por colapso, UV mantida | `decimar.py <ent.glb> <sai.glb> <triângulos>` |
| `closes.py` | tira de closes (frente, traseira, 3/4, lado) para olhar antes de afirmar algo visual; `--perto` faz só frente e traseira de perto, para achar letreiro e placa | `closes.py <glb> <png> [largura] [--perto]` |
| `cortar_base.py` | cortar o monte de areia ou chão que o gerador pôs debaixo de um objeto (usado no posto de salva-vidas) e pôr o chão em z = 0 | `cortar_base.py <ent> <sai> <altura_do_corte_m>` |
| `tirar_pneu.py` | apagar a borracha dos pneus de um carro queimado e assentá-lo no aro, pelas rodas do mapa de corte (`quebravel/<carro>/<carro>_mapa.json`) | `tirar_pneu.py <ent.glb> <mapa.json> <sai.glb>` |

O `tirar_pneu.py` limita o aro a 55 a 65 % do raio do pneu: no Lambari o corte achou um aro pequeno demais (0,12 m) e no
Trilheiro um do tamanho do pneu; sem esse limite o primeiro perdeu o aro e o segundo ficou com pneu.

Retexture e malha: o retexture do Meshy (10 créditos, `enable_original_uv`) mantém malha e UV, então o mapa de corte do carro
original vale; mas não cria geometria (a caixa de teto do táxi foi posta no Blender) e, por texto, tende a pintar número em
placa. O que funcionou para o fogo foi passar a foto aprovada como `image_style_url`.

## carro_completo.py

Gera, para um carro já cortado pelo `carro_quebravel.py`, as partes que faltam para ele ficar completo por dentro e por baixo
(pedido do Felipe de 26/10/2026, `Detonauto/docs/pedido-carro-completo.md`), encaixadas nas medidas daquele carro. Tudo é
geometria e textura feitas pelo script: licença CC0 do estúdio, sem marca, sem logo, sem texto de marca, sem IA.

```
python -I ferramentas/carro_completo.py -- --corte <pasta do corte> --id <carro> --out veiculos/meshy-conta/completo/<carro> \
    [--epoca 70|80|90|2000] [--motor ...] [--amostras 24] [--sem-previa] [--sem-sujeira]
python -I ferramentas/carro_completo.py -- --corte veiculos/meshy-conta/quebravel/<carro> --id <carro> --so-medidas
python3 -m unittest ferramentas/test_carro_completo.py     # medidas e dados dos 13, sem Blender
```

A pasta do corte precisa do `<carro>.glb` do `carro_quebravel.py` (não fica no acervo, ~20 MB): sai em ~1 min com
`carro_quebravel.py -- --entrada veiculos/meshy-conta/<carro>__<id>.glb --out <pasta> --portas N --mapa
quebravel/<carro>/<carro>_mapa.json --sem-previa --sem-fbx`. Sem ele o kit sai só pelas medidas dos JSON (sem assentar na
casca, sem sujeira com a casca e sem prévias). ~1 min para o kit (com a sujeira assada) e ~2 min de prévias por carro, na CPU.

### v2 (27/10/2026)

- **Vão do motor denso:** bloco com nervuras e selos, cabeçote, junta, tampa de válvulas com parafusos e bocal de óleo, capa da
  correia dentada, polias e correia (fecho das polias), alternador com aletas e suporte, motor de partida com solenoide, filtro
  de óleo, coletor de admissão (carburador e filtro redondo nos 70/80, monoponto nos 90, plenum, corpo de borboleta, caixa de
  filtro com presilhas e duto nos 2000), coletor de escape com protetor de calor (90/2000), distribuidor com tampa, torres e
  cabos de vela com cachimbo (até os 90) ou bobinas individuais (2000), bobina no para-lama, câmbio com cabos de engate e da
  embreagem; radiador com colmeia, caixas laterais, bocais, tampa (70/80), carenagem e ventoinha elétrica com o fio; mangueiras
  superior, inferior e do aquecedor com abraçadeiras; reservatório de expansão com marcas de nível e tampa, do freio e do
  lavador com a bomba e a mangueira; bateria na bandeja com grampo, tampas das células, bornes, terminais, capa do positivo e os
  cabos até a partida e a massa; chicote em conduíte corrugado com presilhas, caixa de fusíveis (90/2000); servo-freio,
  cilindro-mestre e as linhas de freio; corta-fogo com manta, passa-fios, caixa de ar com frestas e motor do limpador; torres
  com os prisioneiros, abas com pontos de solda, furos de passagem; longarinas com furos e soldas; painel dianteiro com a
  fechadura do capô, o cabo, a buzina e o fundo dos faróis; manta antirruído e reforços por baixo do capô (`hood_manta`, segue
  `hood`). Variantes: `l4_transversal` (bloco tombado 12° para trás, câmbio ao lado), `l4_longitudinal` (câmbio no túnel),
  `v8_longitudinal` (bancadas, coletores de ferro, carburador quádruplo, distribuidor com 8 cabos, ventoinha mecânica, bomba da
  direção) e `boxer_traseiro` (carenagem da ventoinha, gerador no pedestal com cinta, correia, carburador e filtro em banho de
  óleo, coletor em Y, chapas defletoras, trocadores de calor, bobina na carenagem). Estepe no vão do motor (`vao_motor`) nos
  micros da época.
- **Materiais:** cor em 1024 px (os grandes; detalhe pequeno em 512 ou menos), aspereza e relevo (normal) assados em meia
  resolução, tudo ladrilhável e na escala física (o fio do tecido tem ~1,6 mm, o granulado do plástico ~0,7 mm). Tecido com
  fio a fio e bolinhas, estampa em losango (90) e listras (80); vinil com grão e vincos; plástico com granulado e riscos;
  borracha fosca com pó; carpete com laços, manchas escuras e áreas pisadas; feltro do teto amarelado; metal escovado com
  micro-riscos; fundido com poros; ferro com placas de ferrugem; mostradores com números genéricos (km/h, x1000 rpm, 0 1/2 1,
  50 90 130), hodômetro e luzes-espia. Variantes de uso por grupo: o vão do motor `_po` (pó claro e áspero), embaixo e freios
  `_graxa` (graxa, óleo e escorridos), banco do motorista e aro do volante `_gasto` (desbotado e liso onde se apoia). E a
  **sujeira por oclusão** assada nos vértices (Cycles, com a casca do carro na cena) no atributo `sujeira`, que vai no `COLOR_0`
  e multiplica a cor base (no Blender e no glTF; no Unreal, o material do Detonauto multiplica pela Vertex Color). Imagens em
  JPEG (qualidade 82) dentro do GLB.
- **Habitáculo e portas com proporções de carro de verdade** (medidas em `carro_completo_dados.json`, `medidas_reais`, com as
  fontes): assento a 0,27 m do piso, encosto de 0,60 m, encosto de cabeça de 0,26 × 0,19 m com hastes e guias, vivos e
  costuras, apoio de braço da porta a 0,22 m acima do assento, forro com capa de cima e escova do vidro, miolo de tecido (ou
  vinil plissado nos 70) com moldura chanfrada e vivo, carpete embaixo (80/90), maçaneta em concha com alavanca, manivela,
  pino, bolso (com porta-garrafa nos 2000), alto-falante de 6,5", refletor; painel com mostradores numerados, capuz,
  interruptores, pisca-alerta, rádio com dial e toca-fitas, acendedor e cinzeiro, porta-luvas com fresta e fechadura, grade
  do desembaçador; volante com alavancas de seta e limpador (haste e ponta), comutador com a chave e o chaveiro, aro gasto
  nas 10 e 2 horas; pedais com borrachas nervuradas, mola e interruptor; cinto com presilha, lingueta, botão, retrator,
  fivela com o botão vermelho e o trilho na soleira (2 portas); tapetes de borracha (o do motorista com o calcanhar);
  quebra-sol com espelho de cortesia; alavanca dia/noite no retrovisor.
- **Carrocerias:** `hatch`, `sedan`, `furgao` (cabine de 2 lugares, divisória de grade, área de carga com manta nervurada,
  laterais de chapa com nervuras, caixas de roda e ganchos), `cabine_avancada` (motorista sobre o eixo da frente, banco
  inteiriço do passageiro, volante deitado, sem capô; piso de compensado, deque do motor traseiro, divisória de chapa e
  grade, eixo dianteiro de tubos) e `jipe` (santo-antônio com pernas até as caixas de roda e espuma, chassi de longarinas,
  eixo rígido na frente com diferencial, caixa de transferência, cardã dianteiro e a alavanca da reduzida).
- **Correções medidas à mão** (`corrigir` por carro): altura sem antena nem bagageiro, para-brisa e vidro de trás onde o
  mapa não tinha ou a cor errou, cintura e coluna B do jipe, piso da cabine avançada.

**Peças** (um objeto por peça, no espaço do carro do corte, nomes do kit de quebra; `segue` no JSON diz a peça do corte que
leva junto): habitáculo `interior_*` (carpete, tapetes, bancos, painel, volante, pedais, câmbio, freio de mão, console, cintos,
forro do teto, quebra-sóis, retrovisor, acabamentos, e `interior_carga`, `interior_divisoria`, `interior_santantonio`);
porta `door_card_<pos>` e `door_card_<pos>_chapa` (segue `door_<pos>`); vão da porta `jamb_<pos>_*`; porta-malas
`interior_portamalas_*`; motor `engine_*` e `hood_manta`; embaixo `under_*` (assoalho, linhas, chassi do jipe, escapamento,
tanque, berço, suspensões, eixos, caixas de roda); freios `brake_<pos>_*` (disco, tambor e cubo giram com a roda; pinça e
chapa vão na manga). LOD1 de cada peça (Decimate a 30 %, sufixo `_LOD1`) no mesmo GLB.

**O que o Detonauto faz ao usar o kit** (no `<carro>_completo.json`): tirar do corte a casca escura `MI_DNVao` nas caixas
`vaos_a_tirar_do_corte` e o fundo liso da casca do Meshy (`fundo_a_tirar_do_corte`), senão o interior fica escondido; prender
cada peça na que ela `segue`; multiplicar a cor base pela Vertex Color (sujeira); mostrar o interior só perto da câmera
(≤ 15 m, pedido) e medir com 40 carros de tráfego.

Prévias (Cycles na CPU): porta dianteira esquerda arrancada vista de lado a 1,5 m, a porta caída vista por dentro, cabine pelo
para-brisa, painel visto de dentro, capô aberto (no motor traseiro também a tampa de trás; na cabine avançada só a de trás) e
por baixo. Só a prévia da cabine tira do corpo as faces no plano do para-brisa que o corte deixou (o número vai no JSON,
`previa_faces_do_para_brisa_tiradas`); no Besouro a casca de dentro saiu de verdade pelo mapa (papel `remover`).

**Limites (v2):** o visual é de jogo de PC de uns 10 anos atrás, não de foto: a geometria é primitiva arredondada e chanfrada
(sem escultura), o tecido e o plástico ficam corretos de perto mas planos na luz difusa, os mostradores não têm vidro, e a
sujeira por vértice depende da densidade da malha (painéis grandes ficam limpos). Ainda falta a aprovação por captura ao
lado de foto real (`aprovar-visual` do Detonauto) e a medição no Unreal com 40 carros.

## rodas_kit.py (27/10/2026)

Rodas CC0 feitas do zero por geometria para o carro completo do Detonauto (lote 5 de `docs/carro-completo.md` lá): 4 aros (`aro_aco13`,
`aro_aco14`, `aro_liga13`, `aro_liga14`), 3 pneus (`pneu_p165_70`, `pneu_p175_70`, `pneu_p185_60`), cada um em 3 malhas (`_Ok`, `_Flat` com o
raio 6 cm menor no chão e `_Torn` estourado), e 2 calotas. Redondas de verdade (64 segmentos, desvio < 0,4 mm), pivô no cubo, face de fora em
+Y (roda esquerda; a direita gira 180° em Z), LOD1 no mesmo GLB, roda completa ≤ 9 mil triângulos. Saída em `veiculos/proprios/rodas/` com o
`rodas_kit.json` e a prévia. Aro e pneu são independentes: é o que deixa trocar um sem o outro.

    python -I ferramentas/rodas_kit.py -- [--out <pasta>] [--amostras 32] [--sem-previa]
    python -I ferramentas/test_rodas_kit.py -v

Falta melhorar: as tiras do pneu estourado parecem alças de lado; os sulcos da banda somem a 4 m.

## alisar_lataria.py (27/10/2026)

Deixa a lataria do Meshy com reflexo de carro novo. O Felipe comparou o Cuiabano com a foto de um carro de estúdio: "o outro parece massa
de modelar". O defeito é mais de sombreamento do que de forma. O Meshy faz triângulos grandes e tortos na chapa lisa, e a normal
interpolada entre eles quebra o reflexo.

- **Como funciona:** a chapa é vista de 9 direções: as duas laterais, o topo, a frente, a traseira e 4 diagonais. Em cada vista ela vira
  um relevo numa grade de 1 cm, alisado por um filtro longo no comprimento e curto na altura. A normal de cada ponto sai desse relevo
  alisado, e a forma anda no máximo 6 mm.
- **Vincos e bordas:** onde a chapa vira, ou onde o relevo alisado discorda da chapa em mais de 35°, fica a normal média.
- **Ordem:** rode na malha CHEIA e depois reduza com o `decimar.py`, que leva a normal nova para a malha reduzida. Corte com
  `carro_quebravel.py --manter-normais`; sem a opção, a solda recalcula as normais e desfaz o alisamento.

    python -I ferramentas/alisar_lataria.py -- <cheio.glb> <alisado.glb>
    python -I ferramentas/decimar.py <alisado.glb> <reduzido.glb> 120000
    python -I ferramentas/carro_quebravel.py -- --entrada <reduzido.glb> --out <pasta> --mapa <id>_mapa.json --manter-normais

Medida no teste do verniz (listras refletidas, `meshy/previas/cuiabano-v2/`): as listras da lateral passam de picotadas a retas e contínuas.
Tentativas que pioraram, para não repetir: alisamento ponto a ponto (Taubin) só na tinta ou em tudo, e filtro igual nos dois eixos.

## Acabamento da chapa depois do corte (27 e 28/10/2026)

Pedido do Felipe ("faça tudo até ficar perfeito", com a foto de um carro de estúdio como referência). São três passos no GLB do
`carro_quebravel.py`, nesta ordem, cada um gravando por cima:

    python -I ferramentas/fechar_rachas.py  -- <pasta>/<id>.glb <pasta>/<id>.glb
    python -I ferramentas/alisar_pecas.py   -- <pasta>/<id>.glb <pasta>/<id>_mapa.json <pasta>/<id>.glb
    python -I ferramentas/vedacao_vidros.py -- <pasta>/<id>.glb <pasta>/<id>.glb

Depois disso, refaça o kit (`carro_completo.py`) sobre o corte novo. Desde 28/10 (noite) a cadeia completa, com a cirurgia nas
bordas, está na seção `cirurgia_bordas.py` abaixo.

- **`fechar_rachas.py`:** a malha do Meshy tem costuras internas não soldadas, com duas fileiras de vértices a menos de 2 mm e a
  parede da espessura entre elas. De perto, viravam riscos pretos no meio do capô e do teto. O script solda os vértices de borda de
  material que têm par a menos de 2 mm. O contorno das peças não muda, porque lá os vizinhos ficam a ~1 cm. No Cuiabano v2, o capô
  tinha ~12 m de rachas para 4,5 m de contorno.
- **`alisar_pecas.py`:** todas as peças pintadas entram num conjunto só de pontos. Como a fresta é 0, a lateral inteira (para-lama,
  porta e lateral traseira) vira uma chapa só, e o reflexo atravessa as emendas reto; antes, a emenda da porta com a lateral traseira
  saía num vinco. A chapa é separada por 13 direções (incluindo as diagonais para baixo da saia), abaixo e acima da cintura, e por
  pedaço ligado. Cada pedaço recebe uma B-spline lisa, com um ponto de controle a cada 30 cm e penalidade de curvatura, e a normal sai
  dela. Pedaço com mais de 1,2 m e desvio mediano acima de 6 mm (a diagonal do ombro juntava capô, para-lama e coluna) é refeito em
  faixas no comprimento. Pontos a mais de 10 mm da superfície (maçaneta, friso, borda da caixa de roda) ficam com a normal de antes.
  Os vértices não andam (`--max-mm 0`), porque deslocar a forma abria rachas entre as peças.
- **`vedacao_vidros.py`:** o corte separa o vidro pelos triângulos, e a borda saía em escada (dentes brancos de 2 a 4 cm). O script
  rasteriza a face de fora de cada vidro numa grade de 3 mm, alisa a máscara (disco de ~2 cm, corte em 0,3) e tira o contorno por
  raios. Alisa a curva, a normal da chapa e a altura ao longo dela, e faz por cima uma borracha preta de perfil arredondado (material
  `chassi`). A largura, de 1,6 a 3,6 cm, vem do tamanho da escada. A borracha entra na peça que leva o vidro no jogo (porta, tampa
  traseira ou carroceria) e fica quando o vidro estoura.
- **`carro_completo.py`:** a função `recolher_na_casca` puxa para 6 mm por dentro da chapa os vértices do interior, das portas e do
  porta-malas que encostavam nela ou passavam dela. O teto do Meshy tem calombos, e o forro, o quebra-sol e o painel apareciam por fora
  em manchas. Desde 28/10 (noite) a casca de fora inclui o plástico escuro acima da cintura (as borrachas dos vidros e a aba do
  teto), a 6 cm de alcance: o forro atravessava as borrachas nos cantos dos vidros e as colunas.

Prévias em `meshy/previas/cuiabano-v2/`:
- `cuiabano-v2-acabamento-antes-depois.jpg`: de perto, antes à esquerda e depois à direita;
- `cuiabano-v2-chapa-por-painel-antes-depois.jpg`: no ângulo da foto de referência;
- `cuiabano-v2-verniz-chapa-por-painel.jpg`: teste das listras.

O que ainda falta é forma da malha, não reflexo: a saia das portas, o canto do para-lama perto do farol, a base do para-brisa
(palhetas e grade de ventilação) e as frestas, que não são retas.

## cirurgia_bordas.py, pele_de_dentro.py e a cadeia "Meshy sem borrões" (28/10/2026, noite)

O Felipe viu a carroceria limpa e preferiu o Meshy ("parece mais fiel ao modelo, só precisava tirar os borrões"). O que sobrava de
borrão no Meshy acabado era forma e lasca, não normal: bordas enroladas no fundo das portas e da saia, cantos amassados nos para-lamas
e nas caixas de roda, frestas tortas, a pele de dentro saindo por fora em toda borda, retalhos de chapa serrilhada em volta dos vidros,
vinco no vidro da porta. A cadeia completa fica (cada passo grava por cima do anterior):

    python -I ferramentas/fechar_rachas.py   -- <c>.glb <c>.glb
    python -I ferramentas/alisar_pecas.py    -- <c>.glb <mapa>.json <c>.glb --max-mm 25     # a forma anda até 25 mm
    python -I ferramentas/cirurgia_bordas.py -- <c>.glb <mapa>.json <c>.glb                 # bordas refeitas, sem pele
    python -I ferramentas/vedacao_vidros.py  -- <c>.glb <c>.glb --max-cm 1.5 --sigma 10     # vidro liso, ferro, borrachas
    python -I ferramentas/alisar_pecas.py    -- <c>.glb <mapa>.json <c>.glb                 # só a normal, por último
    python -I ferramentas/pele_de_dentro.py  -- <c>.glb <mapa>.json <c>.glb                 # pele de dentro, por último

- **`cirurgia_bordas.py`:** carroceria, portas, capô, tampa, para-lamas e saias viram uma casca pintada só (`remove_doubles` de 0,8 mm
  nas costuras dos cortes antigos). Saem as paredes de espessura do `carro_quebravel.py` (faces `chassi` coladas à borda da pintura)
  e o forro escuro do Meshy a menos de 1 cm por baixo da chapa e não paralelo a ela (dava riscos pretos no capô). Cortes por plano
  (`bisect_plane` nas faces da caixa, arestas marcadas): porta traseira e dianteira verticais até a cintura (o quadro da janela e as
  colunas ficam na carroceria, como no corte do Meshy); cintura do para-lama e cowl; lateral do capô; frente do para-lama na borda do
  farol, do chão ao capô; frente do capô 12 mm acima dos faróis; laterais da tampa, fundo no topo do para-choque e frente no vinco do
  teto. Cada face vai para a peça pela **região do centro** (separar por componente ligado vazava pelo poço da roda); `split_edges`
  entre peças; a borda marcada recua meia fresta (4 mm no total) e ganha a aba escura. Saia reta: some o que fica abaixo de z = 0,30
  entre as caixas de roda e entra uma tira pintada que segue a chapa, de 0,30 a 0,24, enrolando para dentro. Lábio das caixas de roda:
  meio tubo a raio da roda + 8,5 cm, 6 mm para fora e 12 mm para dentro. O UV e a orientação do Meshy ficam (um `recalc_face_normals`
  na casca aberta virou 82% da porta para dentro, manchas pretas); só as faces novas são orientadas pelo lado de fora.
- **`vedacao_vidros.py` (ganhou três coisas):** *vidro liso*, a face de fora de cada vidro recebe uma superfície cúbica ajustada
  (robusta, 6 mm) e todos os vértices do vidro vão para ela, a face de dentro na espessura mediana (classificados pela normal das faces,
  não pelo desvio: pelo desvio a face de fora amassada caía no nível da de dentro e o vidro virava cacos); *passar a ferro*, chapa que
  invade o vidro vai para a faixa debaixo da borracha (0,3 da meia largura), vidro que passa da curva volta para dentro, o que fica acima
  da borracha desce para baixo dela, e chapa pintada bem dentro do vidro (o divisor serrilhado que o Meshy pintou no vidro da porta) é
  apagada; *borracha larga nos vidros fixos* (`--max-cm-fixo 2.5`: para-brisa e vidro traseiro, 5 cm, a borda do Meshy ali tem escada de
  5,5 cm). Nivelar a faixa inteira em volta do vidro pela mediana achatava o friso da cintura e o reflexo mostrava manchas: não fazer.
  A projeção das colunas A e B numa superfície regrada entre as borrachas (`--colunas`) ficou desligada: de perto saía como adesivo.
- **`alisar_pecas.py`:** normal ajustada que vira mais de 60 graus da normal real não vale (num canto do teto aparecia uma mancha
  refletindo o chão); acima da cintura aceita desvio de 25 mm (`--robusto-cima`, colunas e quadros não têm detalhe a preservar); e as
  quatro diagonais do plano do chão (colunas A e C, cantos). Tem que rodar **depois** da vedação: a malha reconstruída não tem normais
  próprias, e normais calculadas antes de a vedação mexer na chapa viravam manchas escuras em volta dos vidros.
- **`pele_de_dentro.py`:** a chapa pintada duplicada 1,5 cm para dentro e virada (MI_DNVao), 2,5 cm longe de toda borda, só abaixo da
  cintura (o kit põe o forro em cima; nas colunas finas ela saía por fora como lasca escura, e isso era a maior parte dos borrões),
  sem as faces que viram com o deslocamento. É o último passo porque a vedação mexe na chapa.
- **Resultado no Cuiabano v2** (`meshy/previas/cuiabano-v2/cirurgia-*.jpg`): frestas retas nas portas, no capô e na tampa, saia reta,
  lábios limpos nas quatro caixas de roda, capô, portas, para-lamas e lateral lisos, vidros lisos. O que ainda é do Meshy e aparece de
  perto: os quadros dos vidros e as colunas A e B (retalhos entre duas borrachas), a base do para-brisa e a borda do teto.
  Próximo passo, se o Felipe ainda vir borrão: refazer só a parte de cima (colunas, quadros dos vidros e borda do teto) com superfícies
  limpas no estilo quadrado do Gol, mantendo o Meshy abaixo da cintura.

## carroceria_limpa/ (28/10/2026)

Refaz a lataria de um carro do Meshy como **superfícies limpas**, usando o Meshy só como molde. Decisão do Felipe de 28/10/2026, depois
de três rodadas de remendo na malha do Meshy (alisar, soldar rachas, borracha nos vidros) que melhoravam o reflexo mas não a forma:
a malha do Meshy é uma escultura escaneada, com ondas de 30 a 50 cm, bordas em escada e frestas tortas, e remendo não chega a carro de
estúdio. Tudo o que sai daqui é geometria feita por script, CC0 do estúdio; do Meshy ficam só retrovisores, placas e rodas.

```
python -I ferramentas/carroceria_limpa/gerar.py -- --corte veiculos/meshy-conta/quebravel/<id> --id <id> --out <pasta>
```

Sai um `<id>.glb` no formato do corte do `carro_quebravel.py` (mesmos nomes de peça e de material), que entra direto no
`carro_completo.py` e na cadeia do Detonauto. ~3 min na CPU. Três passos, cada um um script da pasta:

1. **`medir.py`:** mede a casca do Meshy por raios numa grade de 1 cm nas 4 vistas (lateral, topo, frente e traseira), guardando
   a profundidade, o material e o objeto atingidos (`campos.npz`).
2. **`corpo.py`:** ajusta um polinômio de poucos termos (mínimos quadrados robustos, o que foge mais de 2 cm pesa pouco) a cada região:
   lateral baixa (x⁴ z³), caixa de vidros acima da cintura (x³ z²), capô, para-brisa, teto e vidro traseiro (x² y⁴, pares em y, com
   mistura suave de ±8 cm nas fronteiras), frente e traseira (z² y⁴). As fronteiras saem das caixas do mapa (para-brisa, vidro
   traseiro) e do próprio campo (bico do capô, vinco da traseira, linha de cintura pela base do vidro lateral). Cada seção transversal
   nasce dessas superfícies com os vincos no lugar: fundo (saia, topo do para-choque ou arco da caixa de roda), cintura com o degrau
   de 3 cm do vidro, borda do teto ou ombro do para-lama, cada um com o seu raio (1,2 cm, 2,5 cm, 4 cm). O loft ao longo de x tem
   seção a cada 2 cm e 56 pontos por meia seção, com os vincos em índices fixos; cada fileira termina onde encontra a superfície da
   frente ou de trás. Os vidros vêm das máscaras de material do Meshy (abertura de 10 cm na lateral, para a lasca do para-brisa vista de
   lado não entrar; casco convexo e alisamento de 4 cm), um contorno por janela.
3. **`malha.py`:** monta no Blender: loft espelhado; tampas da frente e de trás como grade (y, z) com linhas nas bordas dos bolsos dos
   faróis, lanternas, grade e placa (profundidade do mapa), costurada ao loft; vidros pela máscara, com a borda encaixada no contorno,
   rebaixo de 5 mm e borracha de 2,4 cm sobre a borda real; cortes dos painéis por planos limitados a uma região (`cortes.py`:
   portas com o quadro paralelo à coluna A, capô com a lateral no para-lama e a traseira no cowl, para-lamas até a cintura e o cowl,
   tampa traseira até o vinco do teto e as laterais a 60 cm do centro) com fresta de 4 mm e aba escura de 1,2 cm; pele de dentro de 1,5
   cm (`MI_DNVao`, que o `kit_to_detonauto.py` tira nos vãos do kit); UV simples; e os detalhes paramétricos (`detalhes.py`):
   para-choques de plástico varridos em planta, maçanetas, limpadores, faróis e lanternas com moldura cromada.

O que o Meshy ainda dá: as medidas e as caixas do mapa, os contornos dos vidros, retrovisores, placas e rodas. O resto do carro não
depende mais dele. Serve para os outros carros do lote: é só rodar sobre o corte de cada um (as caixas do mapa e as medidas vêm do
`carro_quebravel.py`); van, picape e sedã vão precisar de ajuste nas fronteiras das regiões do topo.

Prévias em `meshy/previas/cuiabano-v2/cuiabano-v2-carroceria-limpa-*.jpg`.


## Gol Quadrado do Sketchfab: a cadeia sem Meshy (29/10/2026)

O Felipe quer o carro de teste **perfeito** e parecido com o modelo brasileiro de referência; a cirurgia no Meshy chegou ao limite
(colunas e quadros dos vidros). O Cuiabano passou a ser um carro modelado por gente: **"Gol Quadrado" por coptrum (Sketchfab, CC BY
4.0)**, `veiculos/sketchfab/gol-quadrado-coptrum__93858a6f970043978ba798ad430871e9.glb` (1,2 MB, 3 objetos: carroceria, vidros,
rodas+assoalho; baixo polígono, chapa limpa, sem logo). O Meshy fica no acervo (`meshy-conta/quebravel/hatch-quadrado-v2/`).

    python -I ferramentas/sketchfab_preparar.py -- <scene.gltf> <pasta>/gol-quadrado.glb "Object_3,Object_5,Object_7" 3.81 1.36 0.06
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/gol-quadrado.glb --out <corte> --id gol-quadrado --portas 2 \
        --sem-rotulos --manter-normais --mapa veiculos/sketchfab/quebravel/gol-quadrado/gol-quadrado_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb
    python -I ferramentas/carro_completo.py -- --corte <corte> --id gol-quadrado --out <kit> --epoca 80

- **`sketchfab_preparar.py` (novo):** desparenta os objetos (matriz do mundo copiada), acha a frente e o eixo do carro por PCA, centra
  entre os eixos e em y, põe o chão em z=0, **estica a carroceria acima do eixo** até a altura real (1,36 m) para as rodas ficarem
  redondas, adensa (aresta máxima 6 cm) e junta num objeto só com os materiais `pintura`, `vidro`, `pneu` e `chassi` por ilha: as
  janelas por regra (ilha estreita e alta, acima de 0,75 m antes do estiramento, em pares espelhados) e as rodas por raio. Grava
  `<saida>_medidas.json` (vidros, rodas, retrovisores, peças soltas, eixos, caixa). Desde a noite de 29/10 recalcula as **normais por
  ângulo** (7º argumento, padrão 30°): aresta mais dobrada fica viva, o resto liso. Sem isso, o vinco da tampa sob o vidro traseiro
  e a saia refletiam o céu em manchas serrilhadas (o `bmesh` do adensamento perde as normais do arquivo); o corte precisa de
  `--manter-normais` para levá-las adiante.
- **`carro_quebravel.py` ganhou:** `--sem-rotulos` (a classificação pela textura não serve numa pintura clara: só o mapa manda);
  `take: "material"` com `material: vidro|pneu|chassi|luz|cromado` (atributo `cq_mat` criado dos materiais do arquivo; os materiais
  de entrada com nome igual aos nossos viram `entrada_<nome>`); `"rodas"` no mapa (centro, raio, y_dentro/y_fora, raio do aro) quando
  o detector erra; e, na noite de 29/10, o **vidro por ilha**: cada ilha ligada do material vai inteira para a caixa que contém a
  maior parte dela (a caixa do vidro traseiro roubava o canto do vidro de quarta e a borda saía em zigue-zague), e uma ilha pequena,
  paralela e 8 mm ou mais atrás da maior (a aba do caixilho que o autor pintou como vidro) sai do modelo.
- **`borracha_vidro.py` (novo):** borracha preta em volta de cada vidro a partir do **laço real da borda** da face de fora (não da
  rasterização, que arredondava os cantos): 3 fileiras ao longo da bissetriz no plano, projetadas na chapa pelo raio na normal do
  vidro, 1,5 mm acima e perfil de 4 mm; 1,6 cm nos vidros de porta, 2,4 cm nos fixos; dona é a porta, a tampa ou a carroceria;
  espigões de rachas internas (ida e volta no laço) são tirados. A `vedacao_vidros.py --so-borracha` faz só a borracha, sem alisar
  nem passar a ferro (no Gol o vidro já é limpo e o alisamento o estragava).
- **`carro_completo.py` ganhou** (tudo medido na casca, vale para qualquer carro): `z_casca(x, y)`; o encosto do banco de trás baixa
  até caber sob o vidro traseiro deitado, e os encostos de cabeça saem se não cabem (apareciam pelo vidro do hatch); a soleira fica
  rente à chapa logo acima dela (abaixo da porta a casca do Gol não existe); o bocal do tanque fica 4 cm por dentro da lateral; o forro
  da caixa de roda para 1,5 cm dentro do para-lama (o pneu do Gol passa 8 cm da lataria); `aparar_expostos` apaga, acima da cintura,
  toda face do kit de onde dois raios escapam sem bater na casca (colunas do vão e acabamento da coluna A saíam por fora de uma coluna
  mais estreita que a janela); **`saias()`**: chapa pintada sob cada para-choque (na borda de baixo dele, inclinada 12°), lateral até
  a caixa de roda e a soleira continuada fora do vão da porta; e `aparar_sob_a_saia` apaga o que ficou além desses planos abaixo da
  saia (radiador, travessa e assoalho do porta-malas apareciam por baixo).
- **No Detonauto:** `kit_to_detonauto.hidden_paint_faces` só apaga faces de pintura que olham para o meio da caixa do kit (a coluna A
  por fora olhava para o retrovisor e sumia); o `glb_texturas.py` trata tinta de pouca saturação (a do Gol é quase branca) como tinta
  trocável; `wheels.json` leva `hub_y_cm` (62,5 cm no Gol) e o `montar-cuiabano-completo.ps1` aceita `-Id` e `-Fonte`.
- **Saída (29/10):** `veiculos/sketchfab/quebravel/gol-quadrado/` (32 peças, ~253 mil triângulos, mapa feito à mão com as medidas
  do preparo: entre-eixos 2,386 m, roda 27,15 cm, cintura 0,907 m) e `veiculos/sketchfab/completo/gol-quadrado/` (kit época 80, 79
  peças). Prévias em `veiculos/sketchfab/previas/gol-quadrado/`.

### detalhes_na_casca.py (29/10/2026, tarde)

O Felipe aprovou o rumo ("está melhorando") e pediu os faróis, a grade e as lanternas da `carroceria_limpa/` nesta casca, e o que mais
desse para melhorar. O modelo baixo polígono trazia tudo isso como placa lisa. O passo roda depois da `borracha_vidro.py` e antes do kit:

    python -I ferramentas/detalhes_na_casca.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb [--sem-friso] [--sem-faixa]
        [--sem-limpador] [--sem-macaneta] [--sem-miudezas] [--z-friso 0.58] [--z-faixa 0.42]

- **Faróis e lanternas refeitos** na caixa medida das faces `luz` da peça: moldura preta de 8 mm na boca do bolso, lente 4 mm à
  frente (convexa de leve), paredes para trás tapando o bolso; a lanterna traseira em três segmentos (ré, seta, freio) separados por
  divisórias pretas. No jogo a lente inteira é o material da lanterna (`kit_names.py`), por isso só `luz` e `chassi`.
- **Grade:** moldura preta, fundo recuado 5 cm, 4 palhetas horizontais e 2 travessas verticais.
- **O que o modelo não tinha:** duas palhetas do limpador deitadas no para-brisa (paralelas, descansando para o lado do carona),
  maçanetas nas portas, friso lateral preto a 58 cm cortado por peça (o trecho da porta vai com a porta), faixa de borracha na face
  dos para-choques (desviando da placa da frente), retrovisores refeitos (caixa arredondada preta com o espelho atrás e a haste até a
  porta), tampa do tanque na quarta traseira direita e antena no para-lama esquerdo.
- **Normais:** as peças que só ganham geometria mantêm as normais de canto do corte; faróis, lanternas, grade e retrovisores são
  refeitos e recebem normais por ângulo (30°). Tudo entra nas peças que já existem, com os materiais do corte: a cadeia do Detonauto
  (amassado, `kit_to_detonauto.py`, kit) roda igual, conferida aqui.
- Prévias: `veiculos/sketchfab/previas/gol-quadrado/gol-quadrado-detalhes.jpg` e as 4 vistas refeitas.

#### Rodada "até o carro perfeito" (29/10/2026, tarde)

Pedido do Felipe: "faça o que ainda dá para melhorar". Entrou no `detalhes_na_casca.py`:

- **Frisos nas lentes:** barras de 1,5 mm (verticais no farol, horizontais na lanterna). A lente do jogo é opaca e brilhante, e um
  refletor por dentro não apareceria; o relevo é o que lê como farol.
- **Seta âmbar e ré branca de verdade:** os segmentos da lanterna saem nos materiais `luz_ambar` e `luz_branca` (cor de prévia no
  GLB). No Detonauto, `kit_names.py` mapeia para `MI_DNLanternaAmbar<Modelo>` e `MI_DNLanternaBranca<Modelo>`, que o
  `import_kit_car.py` cria da lente do cupê com outro tom; o freio continua `MI_DNLanternaTraseira<Modelo>`.
- **Para-choques de plástico preto** (o Gol quadrado de série), com os retalhos de chapa pintada da carroceria que ficam dentro do
  volume do para-choque também pretos (só faces inteiras dentro, 1,5 cm abaixo do topo: a borda de cima fica reta). A placa continua
  no material de placa. `--para-choque-pintado` mantém a cor do carro.
- **Suavização das facetas (testada e descartada):** `sketchfab_preparar.py` ganhou um 8º argumento, passos de Taubin nos vincos
  suaves (padrão 0). Com 3 e 12 passos, e com arestas vivas a 15° em vez de 30°, a quarta traseira e a coluna C ficaram iguais: a
  ondulação é um quadrilátero torcido do modelo (duas faces não coplanares com normais interpoladas), e só remodelar a região
  resolveria. Fica como está: no jogo, à distância da câmera, não aparece.

### assar_desgaste.py (29/10/2026, tarde): a textura que faltava

O Felipe mostrou um print com Gol, Fusca, Kombi e Palio "de verdade" e perguntou por que o nosso não chega lá. A resposta é a
textura: o que faz um carro de jogo parecer real à distância é a cor assada (oclusão nas frestas e nos cantos, sujeira que sobe
do chão, variação leve de chapa), não a geometria. O Gol do Sketchfab vinha com a UV colapsada (116 mil faces num texel) e uma
textura quase branca de 512 px. Este passo roda depois do `detalhes_na_casca.py`:

    python -I ferramentas/assar_desgaste.py -- <corte>/gol-quadrado.glb <corte>/gol-quadrado.glb [--tamanho 2048] [--amostras 32] [--sujeira 0.22]

1. **Faces viradas:** a face cuja normal entra na folga da chapa dupla (o raio pela normal bate em algo a menos de 2,5 cm) e cujo
   sentido contrário sai livre está virada e é invertida; a pele de dentro, que olha para a cabine, fica, e a chapa sob um friso ou
   uma maçaneta (bate perto nos dois sentidos) também: era ela que, virada por engano, assava escura em manchas (apontado pelo
   Felipe em 29/10). (O `recalc_face_normals` do bmesh virava metade da chapa
   e a oclusão saía em camuflagem.) Normais por ângulo de novo onde mexeu.
2. **UV nova, um atlas só:** projeção em caixa (cada face vai para o plano da sua normal dominante), uma carta por peça, eixo e
   lado (de fora / de dentro, para a pele de dentro não se sobrepor à chapa do outro lado), cartas empacotadas em prateleiras na
   mesma densidade (~180 texels por metro em 2K). Os operadores de UV do Blender não rodam fora do editor com várias peças.
3. **Oclusão assada no Cycles (CPU)**, peça por peça (com todas selecionadas o bake de uma apagava o da anterior), com um chão
   para a saia e os para-choques escurecerem perto do solo. A altura de cada texel sai da própria carta (v = z nas cartas de lado).
4. **Composição:** 0,96 x oclusão (0,70 + 0,30 x ao^1,2) x sujeira (até 16% entre 48 cm e 20 cm do chão, com manchas suaves) x
   grão fino; pele de dentro 30% mais escura. Sai `<id>_desgaste.png` (2048 px) e ela vira a cor de `pintura`, `luz`, `cromado`
   e das lentes; o `chassi` multiplica a mesma oclusão pelo preto.
5. No jogo, `glb_texturas.py` tira essa textura do GLB (`T_Cuiabano_C`) e a tinta trocável multiplica por cima: a cor continua
   livre, com o desgaste. O `Image_0.jpg` passou a ser reencodado (antes gravava os bytes PNG do GLB com nome .jpg).

O que ainda separa do print: lá os modelos têm textura pintada por gente (ou foto), com riscos, decalques e cada detalhe da
frente desenhado; aqui a textura é só oclusão + sujeira procedural. O próximo degrau seria uma textura pintada (Meshy retexture
custa créditos; a economia vai até 23/11) ou riscos e decalques procedurais.

#### Correções de 29/10 (noite): manchas e vidro vermelho

O Felipe apontou manchas que ainda sobravam e um vidro pintado com a cor do carro.

- **Vidro vermelho:** o Gol traz, no plano da janela da porta, uma chapa pintada do corpo a 2 ou 3 mm do vidro (na esquerda na
  frente dele, na direita atrás). O `detalhes_na_casca.py` agora apaga toda face pintada a menos de 1,5 cm de um vidro e em cima
  dele (a reta até o vidro segue a normal do vidro; a moldura em volta fica): 1 510 faces no corpo e 227 na tampa.
- **Manchas (retângulos escuros na porta e na quarta):** as cartas da UV juntavam todas as faces de uma peça com a mesma normal
  dominante; faces em profundidades diferentes (o friso sobre a porta, a chapa atrás de outra) caíam umas sobre as outras no atlas
  e o bake de uma escurecia a outra. Agora cada carta é uma ilha ligada por aresta (46 mil cartas, 107 texels por metro em 2K).
- **Faces dos detalhes:** o retrovisor direito e partes das maçanetas saíam com a normal invertida (o `recalc_face_normals` não
  orienta faces soltas). Toda face nova é orientada para longe de um ponto de dentro (o centro da caixa, o eixo do friso, o fundo
  do bolso do farol).

#### Carro novo, vidro de verdade, luzes e rodas (29/10/2026, noite)

Pedidos do Felipe: "falta a placa", "a saia vermelha embaixo era melhor sem", "teste com outra cor", "os vidros deveriam ser
mais transparentes (película depois, no jogo)", "não tem cara de carro novo, as cores estão opacas", "pneus, rodas, lanternas e
sinaleiras mais realistas" e "o vidro perto do retrovisor ainda está pintado".

- **Placa:** a face da frente de `plate_front` e `plate_rear` vira o material `placa` (no jogo, `MI_DNPlacaCoupe`), em branco e
  sem letras (placa real é proibida), com moldura preta de 1 cm e dois parafusos; o resto do suporte fica preto.
- **Saias:** no `carro_completo.py` elas passaram a ser `chassi_graxa` (escuras) e recuadas 6 cm da borda do para-choque: leem
  como a sombra do fundo e ainda tapam radiador e travessa.
- **Vidro de duas faces:** a espessura de 6 mm do vidro saía com a face de trás em `chassi`, preto opaco, e a janela parecia
  fumê fechado. A face `chassi` paralela a um vidro e até 1,2 cm atrás dele vira vidro (11 mil faces nos 6 vidros).
- **Quebra-vento:** o triângulo entre a janela da porta e a coluna A era chapa pintada. É cortado por planos (frente da janela,
  coluna A paralela à borda do para-brisa medida na chapa, cintura) e por outros 1,2 cm para dentro: o miolo vira vidro e o anel,
  borracha.
- **Faróis:** a lente passou a ser vidro com frisos, e atrás dela um refletor acetinado (`refletor`, pirâmide rasa) com a lâmpada.
  **Lanternas:** cada segmento (freio `luz_vermelha`, seta `luz_ambar`, ré `luz_branca`) tem refletor atrás e cor mais viva.
  **Sinaleiras:** piscas âmbar com moldura nas pontas da barra do para-choque da frente.
- **Carro novo:** `assar_desgaste.py --estado novo` (padrão; `--estado usado` volta ao desgaste anterior): a oclusão só escurece
  as frestas (0,80 a 1,0), sujeira 3%, sem grão; a pintura da prévia com verniz cheio (rugosidade 0,16, verniz 1,0) e as lentes
  lisas. A textura multiplica a cor de cada material em vez de substituí-la (as lentes eram brancas).
- **Rodas (`rodas_kit.py`):** aro de aço prata de fábrica (antes cinza chumbo), calota e liga mais espelhadas, pneu de borracha
  nova (preto fosco, não chapado). Testes do `test_rodas_kit.py` passando.
- **Cores:** as seis cores de `Data/Paints.csv` testadas com a `Paint.png` que o jogo usa (`gol-quadrado-cores.jpg`): a lataria
  inteira pega a cor, plásticos ficam pretos, placa branca, lentes nas suas cores.

#### Placa, para-lamas e pintura de carro novo (29/10/2026, noite)

Pedidos do Felipe: "a placa dianteira ainda está estranha, os para-lamas também, pesquise como é o modelo real" e "a pintura ainda
está opaca". Referência: fotos do Gol GL 1991-94 e do Gol 1985 (odg.com.br): placa de 40 x 13 cm no meio da face do para-choque, na
metade de baixo; caixas de roda redondas e rentes à lateral, sem alargador.

- **Caixas de roda redondas (`detalhes_na_casca.py`, `--r-arco 0.34`, `--sem-arco-redondo`):** o modelo trazia o arco como um
  polígono de 6 ou 7 lados, apertado na frente de baixo (2 cm do pneu) e com a borda saltada 2 a 4 cm para fora. Por ângulo em volta
  do cubo (do `_mapa.json`) mede-se a borda vista de lado e o plano da lateral 8 a 12 cm para fora dela; um campo de deslocamento
  leva a borda a um círculo de 34 cm e a pele que passa do plano da lateral volta para ele. O campo só depende da posição, então a
  costura entre peças fica fechada; nos vértices que andaram as normais passam a ser por ângulo (as do arquivo desenhavam o arco antigo).
- **Abas soltas:** tiras pretas da caixa de roda original desciam a 15 cm do chão e saíam 3 cm da lateral, na frente da roda da
  frente e atrás da de trás (de frente pareciam apara-barros pendurados): 72 faces fora.
- **Face do para-choque da frente (`--sem-face-para-choque`):** a barra tinha 8 cm e, embaixo, a chapa fugia 11 cm para trás em
  rampa. O campo empurra a parte de baixo até 1,2 cm atrás da barra, arredondando nos últimos 5,5 cm; o rebaixo da placa antiga usa
  a fileira de fora, e a mudança some no canto (0,58 a 0,72 m do meio). Normais por ângulo no plástico.
- **Placa da frente refeita (`--z-placa 0.355`, `--placa-original`):** era 40 x 10 cm (achatada) num suporte 10 cm fundo, e uma
  folha solta da carroceria logo abaixo fazia o "bloco escuro". Agora: placa de 40 x 13 cm em branco, centrada, de z 0,355 a 0,485,
  0,8 cm à frente da barra, sobre suporte preto que tapa o rebaixo antigo, com moldura e parafusos. A faixa do para-choque desvia dela.
- **Saias (`carro_completo.py`):** sem as laterais até a caixa de roda e a da frente 20 cm para dentro de cada lado (de lado
  penduravam como apara-barro).
- **Pintura "opaca":** duas causas. (1) A textura de carro novo escurecia 10 a 20% a chapa aberta: a lateral vê o chão e a oclusão
  dela fica perto de 0,5, abaixo do limite de 0,75; agora a chapa com oclusão de 0,40 para cima já sai com a cor cheia (portas,
  para-lamas e capô em 253 de 255). (2) As prévias refletiam só um céu liso e um chão vazio: o verniz não tinha o que mostrar. As
  prévias passaram a usar um HDRI de rua (Poly Haven, CC0) como numa foto.
- **Acabamentos:** o Detonauto ganhou `Data/PaintFinishes.csv` (sólida, metálica, perolizada, fosca, acetinada); as prévias
  `gol-quadrado-acabamentos.jpg` mostram cada um com os valores da tabela.

#### No jogo: placa gigante e farol preto (29/10/2026, noite)

O Felipe montou o Cuiabano no PC e viu a placa cobrindo a frente e a traseira e os faróis pretos, diferente das prévias.

- **Placa:** o `kit_to_detonauto.py` do Detonauto ainda fazia a "placa lisa" do Meshy: procurava o branco da placa na textura da lataria
  e crescia a placa até ele. Na textura de carro novo (tinta em branco, a cor vem do material) toda a lataria é branca: a placa saía
  com 91 x 32 cm na frente e 60 x 39 cm atrás. Placa modelada no acervo (material `placa`) agora passa como veio.
- **Farol:** a lente era vidro transparente na frente de um bolso escuro; no Unreal o bolso fica sem luz e o farol saía preto. A
  prévia escondia isso porque clareava a lente só nela. Agora a lente do farol é `lente_farol` (prata claro, um pouco metálica,
  envernizada, opaca, com os frisos; no jogo `MI_DNLenteFarol<Modelo>`) e o refletor é prata acetinado de pouco metal (no jogo
  também). **Regra:** a prévia usa os mesmos valores do jogo, sem truque só nela.
- **`previa_carro.py` (novo, era o rascunho das prévias):** o corte + o kit + as rodas de kit, a pintura como o jogo faz e, com
  `HDRI=`, uma rua em volta. Uso no cabeçalho do script.

## Trilheiro: jipe de capota rígida do Sketchfab (30/10/2026)

O Trilheiro (jipe 4x4 de 2 portas, capota rígida, estepe atrás) passa a ser um modelo feito por gente: o jipe de capota rígida do
**funassets (Sketchfab, CC BY 4.0)**, `veiculos/sketchfab/jipe-capota-funassets__fd41538dbb6744b38d7037c4cc8b058f.glb` (2,3 MB,
12.852 triângulos). Escolhido entre 5 candidatos por ter o estepe na tampa, 2 portas e polígono na faixa do Gol. O modelo vem em 7
objetos (carroceria, "exterior" com capota, plástico, luzes e o interior num atlas só, vidros e 4 pneus em triângulos soltos), e a
grade dele tem as 7 fendas verticais de uma marca: ela sai e entra uma grade de barras horizontais própria.

    python -I ferramentas/sketchfab_separar.py -- <scene.gltf> <pasta>/separado.glb veiculos/sketchfab/quebravel/jipe-capota/jipe-capota_separar.json
    python -I ferramentas/sketchfab_preparar.py -- <pasta>/separado.glb <pasta>/jipe.glb "carroceria,vidros,rodas" 3.528 1.87 0.06 30 0 0.05 1
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/jipe.glb --out <corte> --id jipe-capota --portas 2 --sem-rotulos \
        --manter-normais --manter-chassi --mapa veiculos/sketchfab/quebravel/jipe-capota/jipe-capota_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/jipe-capota.glb <corte>/jipe-capota.glb
    python -I ferramentas/detalhes_na_casca.py -- <corte>/jipe-capota.glb <corte>/jipe-capota.glb --sem-arco-redondo \
        --sem-face-para-choque --sem-quebra-vento --sem-friso --sem-faixa --sem-sinaleira --sem-macaneta --z-placa 0.40 \
        --farol-redondo --grade-limpa
    python -I ferramentas/assar_desgaste.py -- <corte>/jipe-capota.glb <corte>/jipe-capota.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id jipe-capota --out <kit> --epoca 2000 --aparar-mais --aparar-alto 0.12

- **`sketchfab_separar.py` (novo):** pré-passo para modelos que não vêm nos 3 objetos do Gol. Cada objeto vai para carroceria,
  vidros, rodas ou apagar por um pedaço do nome; o "exterior" é decidido ilha por ilha, por caixas (a cabine sai: bancos, painel,
  volante, forros, santo-antônio; o estepe e os faróis de neblina do para-choque vão com o plástico: claros, saíam na cor do carro,
  como ganchos verdes) e pela cor média da textura (ilha escura = plástico preto, que vai junto das rodas e vira `chassi` no preparo).
- **`sketchfab_preparar.py`:** 9º argumento, solda (unidades do arquivo): o pneu vinha em triângulos soltos e não virava ilha de roda
  (a solda tem que ser aqui, porque o glTF separa de novo os vértices na exportação); 10º argumento `1`: toda ilha do 2º objeto é
  vidro (as regras de janela são do Gol e o para-brisa do jipe é em pé). O comprimento de 3,528 m é o da carroceria sem para-choques,
  estepe e faróis de neblina: o carro fica com 3,955 m, como o Trilheiro do Meshy, e a altura vai a 1,87 m. Se a carroceria perder ou
  ganhar uma peça na ponta, esse número muda e o mapa deixa de bater (com 3,61 depois de tirar os faróis de neblina o carro saiu
  2,3% maior e o pneu dianteiro deixou uma "serra" verde fora da roda).
- **`carro_quebravel.py --manter-chassi`:** na malha única tudo o que o mapa não pegava por material virava `pintura`; com a opção,
  as faces que vieram `chassi` continuam pretas (alargador, estribo, moldura, estepe). Sem ela o alargador saía na cor do carro.
- **`detalhes_na_casca.py`:** `--farol-redondo` (círculo do tamanho da largura da caixa, moldura preta, lente clara convexa com
  frisos, refletor em cone e lâmpada; embaixo uma seta âmbar redonda; o resto da caixa volta a ser chapa pintada; plano = mediana das
  faces da frente + 1 cm, porque o x máximo pegava uma ponta 15 cm à frente); `--grade-limpa` (apaga as palhetas antigas e, na
  carroceria, as fendas até 15 cm atrás da grade, antes da grade de 4 palhetas horizontais e 2 travessas, no plano da face);
  `--z-macaneta`; retrovisor de plástico preto mede a caixa pelo `chassi`. No jipe a maçaneta do modelo fica (`--sem-macaneta`).
- **O Gol não muda:** a cadeia dele rodada com as ferramentas antigas e as novas dá o mesmo preparo byte a byte; no corte e nos
  detalhes mudam as mesmas peças que mudam entre duas rodadas das ferramentas antigas (o corte não é determinístico byte a byte),
  com os mesmos triângulos, as mesmas caixas e centróides a menos de 1 mm.
- **Saída (30/10):** `veiculos/sketchfab/quebravel/jipe-capota/` (32 peças, ~305 mil triângulos, 3,96 x 2,08 x 1,87 m, entre-eixos
  2,288 m, roda 35,3 cm) e `veiculos/sketchfab/completo/jipe-capota/` (kit época 2000, 83 peças, carroceria jipe, 4x4, estepe externo;
  entrada `jipe-capota` no `carro_completo_dados.json`, sem as correções do modelo do Meshy).
- **Kit aparado:** o jipe tem a grade 30 cm atrás da ponta do para-choque, e o kit punha a travessa do radiador, as colunas e o
  radiador na frente da grade (a prévia do jogo mostrou; a do corte sozinho não). Com `--aparar-mais --aparar-alto 0.12` tudo o que
  sai do envelope da casca no cofre some.
- **Rodas:** pneu novo 215/75 R15 no `rodas_kit.py` (35,16 cm de raio, o do corte; 21,5 cm de largura), no aro de aço 15 sem calota.
  Gerado à parte e copiado só ele (`pneu_p215_75.glb` + o item no `rodas_kit.json`): as outras rodas saem idênticas; testes passando.
- **Prévias com os materiais do jogo** (`previa_carro.py`, HDRI da rua, `RODAS=aro_aco15,pneu_p215_75,`): `veiculos/sketchfab/previas/
  jipe-capota/` (4 vistas, detalhes de frente, traseira e roda, 8 cores e 5 acabamentos de `Data/PaintFinishes.csv`). A quina chanfrada
  do capô reflete o céu e parece uma lasca clara: é reflexo, aparece igual com e sem o kit.
- **Detonauto (30/10):** cadeia de conferência passou (`make_crush_channels.py`, `kit_to_detonauto.py`, `glb_texturas.py`,
  `kit_completo_to_detonauto.py` com `--modelo Trilheiro`); dados, specs e o pedido para o PC (`docs/pedido-pc-trilheiro.md`) lá.
## Caipora do Sketchfab (30/10/2026)

O Caipora (hatch arredondado de 3 portas dos anos 90, nº 3 da ficha do Speed Tchê) deixou o Meshy pelo mesmo caminho do Gol. Entre 4
candidatos (CC BY, feitos por gente) o Felipe escolheu `veiculos/sketchfab/hatch-arredondado-jigglesticks__773b1c83b4a240f2ac415c351d3a65c6.glb`
(JiggleSticks, CC BY 4.0, crédito em `CREDITOS.md`): ~12 mil triângulos, 9 objetos separados por material, sem textura. Os três
Corsas detalhados do Sketchfab ficaram de fora por origem duvidosa (placa "HUMSTER3D", de loja de modelos pagos; uma cópia com o
mesmo número de triângulos; placas de mod de jogo).

    S=<pasta do download>/scene.gltf; P=<pasta>
    python -I ferramentas/sketchfab_preparar.py -- $S $P/caipora.glb "Car_Main Color_0,Car_Glass_0,Car Tires_Ruber Tires_0,Car Tires_Chrome_0,Car_Plastic Parts_0,Car_Lights Front_0,Car_Lights Back_0,Car_Lights Indicators Back_0" \
        3.669 1.39 0.06 45 0 --soldar 0.0005 --rodas-no-chao --remapear-z "-1.85,-1.64,-0.09,0.09,0.75,0.95=0.835,0.925" \
        --normais-da-original --ilha-maior "Plastic_Parts=pintura" --mat "Glass=vidro,Plastic_Parts=chassi,Lights_Front=luz,Lights_Back=luz,material_0=luz,Chrome=pneu"
    python -I ferramentas/carro_quebravel.py -- --entrada $P/caipora.glb --out $C --id caipora --portas 2 --sem-rotulos --manter-normais \
        --materiais-do-arquivo --mapa veiculos/sketchfab/quebravel/caipora/caipora_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- $C/caipora.glb $C/caipora.glb
    python -I ferramentas/detalhes_na_casca.py -- $C/caipora.glb $C/caipora.glb --sem-arco-redondo --sem-face-para-choque --sem-friso \
        --sem-faixa --sem-quebra-vento --antena -1.0,0.12 --z-placa-tras 0.695 --y-placa-tras -0.10 --farol-do-modelo \
        --lanterna-do-modelo "ambar=0.645,0.76,0.67,0.735;branca=0.585,0.633,0.736,0.784" --retrovisor-do-modelo --grade-do-modelo --placa-pela-face --para-choque-pintado
    python -I ferramentas/assar_desgaste.py -- $C/caipora.glb $C/caipora.glb --tamanho 2048 --amostras 32 --manter-normais
    python -I ferramentas/carro_completo.py -- --corte $C --id caipora --out veiculos/sketchfab/completo/caipora --epoca 90 --puxar-para-dentro

O que este modelo pediu, tudo como **opção nova** (sem ela o Gol sai igual: a cadeia dele foi refeita com as ferramentas antigas e as
novas sobre a mesma entrada e deu a mesma malha, as mesmas normais e a mesma textura, pixel a pixel):

- **`sketchfab_preparar.py`:** `--mat` leva cada objeto do arquivo para um dos nossos materiais pelo nome do material (o modelo já vem
  separado: plástico preto, lentes, rodas); `--soldar` junta os vértices (o sombreado chapado vinha com cada face solta e toda ilha
  era uma face), recalcula as normais para fora (a frente vinha virada para dentro: o filtro de normal do corte não achava grade nem
  placa) e tira a barbatana que o autor deixou no plano de simetria do para-brisa e do vidro traseiro; `--rodas-no-chao` desce a roda
  que flutua (a da frente, 2,5 cm: o corte não achava o contato e o carro ficava de nariz empinado); `--ilha-maior` leva a maior ilha de um material do arquivo para outro dos nossos (para-choques, arcos e saias do
  Caipora são uma peça só de plástico preto; no carro da referência do Felipe eles são da cor do carro); `--remapear-z` muda a altura de
  uma ilha (a fechadura da tampa descia até onde vai a placa brasileira de 13 cm; no carro real ela fica acima da placa);
  `--normais-da-original` dá a cada canto da malha adensada a normal lisa do triângulo de antes, por interpolação: os triângulos finos
  do adensamento faziam a lataria arredondada refletir enrugada (a transferência pela face mais perto errava nas dobras).
  Comprimento 3,669 m de lataria para 3,73 m com os para-choques (o do carro real); entre-eixos 2,413 m (real 2,443), bitola 1,375 m.
- **`carro_quebravel.py`:** nada novo: a `--materiais-do-arquivo` (da sessão do Furgãozinho) mantém o material que veio no arquivo em
  cada face, não só nas do `take: material` (sem ela, para-choques e molduras viravam pintura).
- **`borracha_vidro.py`:** o contorno é o laço de borda mais comprido (um furo de uma face no vidro de quarta esquerdo começava o laço
  e o vidro ficava sem borracha). No Gol o laço é o mesmo.
- **`detalhes_na_casca.py`:** `--farol-do-modelo`, `--lanterna-do-modelo` (regiões de |y| e z para a seta e a ré), `--retrovisor-do-modelo`
  e `--grade-do-modelo` mantêm a forma do modelo e só trocam os materiais pelos do jogo (refeitos em caixa, como no Gol quadrado,
  tiravam a cara de carro redondo); `--antena x,y` (no teto, como no carro real); `--z-placa-tras` e `--y-placa-tras` (a placa de trás na
  tampa, um pouco à direita); `--placa-pela-face` (a tampa abaulada passava pela placa); a placa ignora o raio que atravessa o vão da
  placa antiga e bate do outro lado do carro (dava 2,5 m). Caixas de roda, face do para-choque, friso, faixa e quebra-vento são do Gol
  e ficam desligados: neste modelo o plástico preto dos arcos e os frisos já existem.
- **`assar_desgaste.py`:** `--manter-normais`: a face virada só inverte as próprias normais, em vez de a peça inteira voltar às normais
  por ângulo (as facetas voltavam ao capô).
- **`carro_completo.py`:** `--puxar-para-dentro`: a recolha na casca inclui o vão da porta e o motor, alcança 10 cm, só conta a face da
  casca que olha para fora (a de trás do para-brisa enganava) e baixa a cabine e o motor à frente do para-brisa para baixo da chapa. Sem isso as
  colunas do vão furavam o teto arredondado nos cantos, a frente do painel aparecia por cima do capô e a travessa do radiador pela
  fresta do capô. As lentes também contam como casca: o para-lama interno do cofre furava o farol oval (um triângulo azul na lente).
- **No Detonauto:** `Tools/Unreal/montar-cuiabano-completo.ps1 -Id caipora -Modelo Caipora` (parâmetros novos `-Modelo`, `-Row` e
  `-BoneZ`, com o Cuiabano de padrão); linhas `caipora-*` em `Data/CarWheels.csv`, `CarAttach.csv`, `CarParts.csv` e `CarGlass.csv`
  (as mesmas peças e vidros do Cuiabano); o jogo abre o Caipora com `-DNModel=Caipora`.
- **Saída:** `veiculos/sketchfab/quebravel/caipora/` (32 peças, ~189 mil triângulos, textura de desgaste 2K) e
  `veiculos/sketchfab/completo/caipora/` (kit época 90, 79 peças). Prévias em `veiculos/sketchfab/previas/caipora/`.

## Receita: um carro do Sketchfab até o Detonauto (o caminho do Gol Quadrado, 29/10/2026)

Para cada carro nacional, uma sessão. Os passos, na ordem:

1. **Referência:** o carro real de cada nome do jogo está na ficha privada do Speed Tchê (`Felipebonamigo/SpeedTche`,
   `docs/CARROS-NACIONAIS.md`). O nome real nunca vai para tela, loja nem para o texto deste acervo, que é público (só o título que o
   autor deu ao modelo, no crédito que a licença pede). Fotos reais para comparar: frente, lado, traseira, detalhes (placa, arcos,
   faróis, lanternas, para-choques).
2. **Modelo:** buscar na API do Sketchfab (`api.sketchfab.com/v3/search?type=models&downloadable=true&q=...`, a sessão da nuvem já
   tem a credencial pelo proxy) modelos **feitos por gente**, com licença **CC BY ou CC0** (nunca NC, ND nem "Standard"/pago), chapa
   limpa, vidros separados, sem logo, emblema, nome nem placa real. Mostrar 3 a 5 candidatos ao Felipe com miniatura, licença,
   autor e triângulos; **o Felipe escolhe**. Baixar por `/v3/models/<uid>/download`, guardar o `.glb`/zip original e o `license.txt`.
   Comprar, logar ou aceitar termos: só o Felipe. Meshy só em último caso, perguntando antes com o custo (economia até 23/11).
3. **Preparar e cortar:** `sketchfab_preparar.py` (objetos, comprimento e altura reais, frente +X, chão em z=0, normais por ângulo),
   um `_mapa.json` feito à mão (rodas, portas, capô, tampa, para-choques, vidros, luzes, placas) e `carro_quebravel.py --sem-rotulos
   --manter-normais --mapa ...`, depois `borracha_vidro.py`. Modelo com vidros, luzes e grade misturados num objeto só: rotular antes
   com `sketchfab_rotular.py` (seção do Tupiniquim, abaixo).
4. **Detalhes:** `detalhes_na_casca.py`. Várias medidas ali são do Gol (quebra-vento, sinaleiras no para-choque, antena, altura do
   friso e da faixa): use as opções que existem e ponha opção nova para o que mudar, **sem mudar o resultado do Gol** (rodar o Gol de
   novo e comparar). Arcos redondos, placa 40 x 13 cm, lente de farol clara e para-choques pretos servem para todos.
5. **Textura e kit:** `assar_desgaste.py --tamanho 2048 --amostras 32` e `carro_completo.py --corte ... --epoca <80|90|2000>`.
6. **Prévia e conferência:** `previa_carro.py` com o HDRI da rua, nas 4 vistas, closes de frente, lado e traseira, e as cores e
   acabamentos; comparar com as fotos reais e **olhar cada imagem antes de dizer que ficou bom**. No Detonauto, a cadeia de
   conferência (`make_crush_channels.py`, `kit_to_detonauto.py`, `glb_texturas.py`, `kit_completo_to_detonauto.py`).
7. **Registro:** `catalogo.csv`, `CREDITOS.md`, aba "Modelos 3D" do doc do estúdio e `docs/licencas.csv` do Detonauto, no mesmo dia.
   Arquivo nenhum acima de 50 MB.
8. **No jogo:** o que só o PC faz (importar, compilar, jogar) vai num texto pronto para o Felipe passar à sessão local, com as
   capturas pedidas; o veredito visual é a captura do jogo, não a prévia.
- **Placa de trás e luzes iguais (29/10, noite):** a placa de trás também passou a ser a brasileira de 40 x 13 cm no meio da tampa
  (era 30 x 12), pela mesma função da da frente (`--placa-tras-original` mantém a antiga). Faróis e lanternas de cada par usam a
  união das duas caixas, espelhada: no modelo a lanterna esquerda tinha 24 cm e a direita 28 (`--luzes-como-vieram` desliga).

## casca_impressao.py (30/10/2026)

Para modelo do Sketchfab que é só uma **casca maciça de impressão 3D** (STL com a lataria de ~3 cm de parede, janelas e caixas de roda
furadas, sem vidro, sem roda, sem assoalho e sem material). Entrega os 3 objetos que a `sketchfab_preparar.py` espera (`carroceria`,
`vidros`, `rodas`), com os materiais pelos nomes dos papéis, sem mexer na cadeia do Gol:

    python -I ferramentas/casca_impressao.py -- --entrada <scene.gltf> --out <pasta>/<id>_casca.glb --comp <m> [--razao 0.3]
        [--aro aro_liga14] [--pneu pneu_p185_60] [--frente -y] [--manter-parede] [--pele-direcoes 160] [--pele-passo 0.012] [--so-casca]
    VIDRO_TODO=1 python -I ferramentas/sketchfab_preparar.py -- <pasta>/<id>_casca.glb <prep>.glb "carroceria,vidros,rodas" <comp> <alt> \
        0.06 30 0 --sem-pca --meio-pela-caixa --soldar 0.0001 --manter-materiais

- Junta, solda, tira ilhas soltas, põe a frente em +X e reduz (colapso).
- **Vidros** por raios numa grade de 5 mm: janela lateral é o que o raio atravessa de lado a lado acima de 0,55 m; para-brisa e vidro
  traseiro, o que o raio de cima atravessa sem se ligar à borda da grade. A superfície de cada vidro é um polinômio ajustado ao anel
  de chapa em volta (robusto), 4 mm para dentro; a face de trás fica 5 mm atrás, em ilha separada (numa placa fechada o contorno da
  face de fora ramificava na borda e a `borracha_vidro.py` achava só 4 pontos).
- **Rodas** do `rodas_kit` no centro do círculo ajustado a cada caixa de roda, 2,5 cm por dentro da lataria; a casca sobe até o pneu
  tocar o chão. Assoalho plano entre as soleiras.
- **Pele de fora:** a parede de 3 cm dobrava a casca (o atlas da `assar_desgaste.py` caía a 84 texels por metro e o kit esbarrava na
  pele de dentro). Fica só o que se vê de fora: raios de 160 direções numa grade de 1,2 cm, com os vidros e uma chapa de chão de ponta a
  ponta tapando a cabine; furinhos fechados pelas vizinhas. No Barão, 188 mil -> 95 mil faces, sem buraco por fora (conferido com as
  faces de trás em verde).
- **Caixa de roda:** a parede de dentro dela (a soleira e o fundo do para-lama eram cheios) vai para `chassi`; pintada, aparecia como
  uma placa dentro do arco.
- Testado e descartado na casca do Barão, que tem ondas leves de modelagem: o `alisar_lataria.py` (com a camada de 3 cm mistura as
  duas peles; com 1,2 cm enruga) e Taubin na pele de fora (as emendas pioram). Com o verniz e o HDRI da rua as ondas leem como chapa de
  carro usado; a forma fica a do autor.

## Tupiniquim: hatch de 5 portas do Sketchfab, fora do acervo (29 e 30/10/2026)

O Felipe escolheu para o Tupiniquim um modelo do Sketchfab de **origem incerta**: o arquivo é um `.3ds` convertido, com materiais
de nome em português e texturas perdidas, publicado por um usuário que subiu dezenas de modelos com cara de tirados de jogos. Decisão
dele (30/10): o carro é feito pela receita, mas **nem o modelo nem o corte entram neste acervo público**; ficam no Detonauto (privado),
em `Art/Carros/tupiniquim/`, com a ressalva na linha do `docs/licencas.csv`. Aqui ficam só as ferramentas, que servem para qualquer
carro. Todas as mudanças são opções: sem elas o Gol Quadrado sai igual. Conferido com o código do `main` e o de agora sobre a
mesma entrada: preparo, borracha, detalhes e kit idênticos (0 peças diferentes). O `carro_quebravel.py` em si não é determinístico
(duas rodadas do mesmo código diferem em 5 ou 6 peças), então a cadeia inteira de ponta a ponta nunca sai byte a byte igual.

O modelo não vem em 3 objetos (carroceria, vidros, rodas) como o Gol: vidros, faróis, lanternas, grade, frisos e caixas de roda estão
misturados num objeto, e a malha é uma sopa de triângulos soltos. A cadeia ganhou um passo antes do preparo:

    python -I ferramentas/sketchfab_rotular.py -- <scene.gltf> <pasta>/rotulado.glb <regras.json>
    python -I ferramentas/sketchfab_preparar.py -- <pasta>/rotulado.glb <pasta>/<id>.glb "carroceria,vidros,rodas" 3.827 1.433 0.06 30 0 0.0001 1 \
        --manter-materiais
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/<id>.glb --out <corte> --id <id> --portas 4 --sem-rotulos \
        --cores-do-arquivo --manter-normais --mapa <mapa.json> --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/<id>.glb <corte>/<id>.glb
    python -I ferramentas/detalhes_na_casca.py -- <corte>/<id>.glb <corte>/<id>.glb --manter-luzes --grade-chassi --manter-retrovisores \
        --sem-friso --sem-faixa --sem-face-para-choque --sem-arco-redondo --para-choque-pintado --sem-sinaleira --sem-quebra-vento \
        --placa-nova --z-placa 0.365 --z-placa-tras 0.742 --z-macaneta 0.84 --antena-teto 0.05 --limpadores 0.30,0.50,-0.16,0.44 \
        --grade-recuo 0.03 --friso-lente
    python -I ferramentas/assar_desgaste.py -- <corte>/<id>.glb <corte>/<id>.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id <id> --out <kit> --epoca 2000 --aparar-mais 0.62 0.75 \
        --sem-saia-para-choque

- **`sketchfab_rotular.py` (novo):** junta os vértices (1 mm), corta por planos opcionais e rotula cada ilha de faces (ou cada face)
  por regras de caixa, na ordem, com filtro de normal: `pintura`, `vidro`, `luz`, `chassi`, `cromado`, `pneu` ou `fora` (emblemas,
  letreiros, placas com número e a moldura cromada da grade saem; a grade e as fendas do para-choque viram plástico preto). Os cortes
  por plano deixam reta a borda entre o vidro traseiro e a lanterna, que eram uma chapa só pintada na textura perdida; o vidro que
  dobra para a lateral vira o acabamento preto da coluna (filtro de normal), como no carro de referência. Ilha de vidro menor que
  `vidro_min_faces` vira preto (senão o corte a toma por aba de caixilho e deixa um furo). Grava os 3 objetos que o preparo espera.
- **Preparo e corte:** os do Sagui e do Trilheiro (30/10) já serviam: `--manter-materiais`, solda de 0,1 mm (o GLB separa os vértices
  nas costuras de normal) e vidro inteiro no preparo; `--cores-do-arquivo` no corte.
- **`carro_quebravel.py`:** `take: "ilha"` no mapa (com `material` opcional): o painel que o modelo já traz solto (porta, capô, tampa,
  para-choque) vai inteiro, e a borda da peça segue a fresta do modelo em vez do corte reto da caixa; `pocket_z_max` na peça limita
  o vão escuro à parte de baixo (a porta deste carro tem o quadro da janela, e o vão tapava a janela por dentro).
- **`borracha_vidro.py`:** o vidro da porta de trás é da porta de trás quando ela existe.
- **`detalhes_na_casca.py`:** `--manter-luzes` (a lente do modelo fica: farol em `lente_farol`, lanterna vermelha com a faixa de
  baixo branca), `--grade-chassi` (grade que veio preta é refeita lisa, com palhetas), `--manter-retrovisores` (forma do modelo,
  capa preta), `--placa-nova` (placas de 40 x 13 cm no rebaixo de um carro sem placa), `--z-macaneta` e maçanetas nas portas de
  trás, `--antena-teto` e `--limpadores`.
- **`carro_completo.py`:** a saia sob o para-choque acaba onde a borda dele recua (no para-choque de ponta arredondada ela saía pela
  curva como uma aba preta; no Gol, de ponta reta, nada muda); `--aparar-mais zf zt` tira o que sai da casca no motor e no
  porta-malas (a travessa do painel aparecia acima da grade e o carpete furava a lanterna), as colunas do vão vistas pela janela (a
  coluna B deste carro é inclinada e a do kit é reta), recolhe o kit também atrás das lentes e põe a travessa sob a borda mais baixa
  do capô.
- **Segunda rodada (30/10, noite):** `--grade-recuo` (a grade refeita recua atrás da borda do capô em vez de saltar como uma caixa) e
  `--sem-saia-para-choque` no kit (o para-choque deste carro desce até o piso e sobe nas pontas, e a chapa da saia aparecia por baixo
  da ponta como aba preta; o plano dela continua aparando o kit). Testada e descartada: moldura e refletor por faces na lente do farol
  (a lente é triangulada e a borda saía em dente de serra); no lugar, `--friso-lente` varre uma moldura preta de 12 x 4 mm rente ao
  contorno da lente (as arestas que só uma face dela usa, reamostradas a cada 1 cm e suavizadas): o farol passou a ler como farol. As lascas pretas nas colunas A da prévia do kit são da própria prévia, que
  tira o para-brisa e a chapa em volta; com o vidro, de dentro, a coluna é inteira.
- **Resultado (30/10):** 34 peças, ~125 mil triângulos, 3,83 m, entre-eixos de 2,39 m, roda de 29,6 cm; kit época 2000. As portas de
  trás e os para-lamas traseiros ficam na carroceria no jogo (uma porta por lado no contrato do Detonauto; o para-lama traseiro de
  carro real não solta). Prévias, mapa, regras e a cadeia em
  `Detonauto/Art/Carros/tupiniquim/`.
## Furgãozinho do Sketchfab: modelo em peças do autor (30/10/2026)

O Furgãozinho da Firma (nº 6 da ficha) passou do Meshy a um modelo feito por gente: **"Fiat Uno Com Escada" por ClrModels (Sketchfab,
CC BY 4.0)**, `veiculos/sketchfab/furgaozinho-clrmodels__36a3b33ef596443c9a780f3844f62fa1.glb` (2,8 MB, 44 objetos com nome, 7
materiais lisos, 5 portas, bagageiro de teto). Diferente do Gol (3 objetos), ele vem em peças: a receita ganhou um passo antes do
preparo e o corte passou a usar as juntas que o autor modelou.

    python -I ferramentas/sketchfab_juntar.py -- <original>.glb <tmp>/juntado.glb veiculos/sketchfab/quebravel/furgaozinho/furgaozinho_grupos.json
    python -I ferramentas/sketchfab_preparar.py -- <tmp>/juntado.glb <tmp>/furgaozinho.glb "carroceria,vidros,rodas" 3.64 1.56 0.06 30 0 \
        --manter-materiais --sem-pca --meio-pela-caixa
    python -I ferramentas/carro_quebravel.py -- --entrada <tmp>/furgaozinho.glb --out <corte> --id furgaozinho --portas 4 --sem-rotulos \
        --manter-normais --materiais-do-arquivo --mapa veiculos/sketchfab/quebravel/furgaozinho/furgaozinho_mapa.json --sem-fbx
    python -I ferramentas/detalhes_na_casca.py -- <corte>/furgaozinho.glb <tmp>/det.glb --sem-arco-redondo --sem-face-para-choque \
        --manter-grade --sem-macaneta --sem-friso --sem-faixa --sem-quebra-vento --sem-sinaleira --sem-tampa-tanque \
        --luzes-do-modelo --manter-chapa-dos-vidros --z-placa 0.36 --placa-tras-no-para-choque
    python -I ferramentas/assar_desgaste.py -- <tmp>/det.glb veiculos/sketchfab/quebravel/furgaozinho/furgaozinho.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte veiculos/sketchfab/quebravel/furgaozinho --id furgaozinho \
        --out veiculos/sketchfab/completo/furgaozinho --epoca 90

- **`sketchfab_juntar.py` (novo):** junta as peças do autor nos 3 objetos que o preparo espera (`carroceria`, `vidros`, `rodas`), com o
  material de cada peça escolhido à mão num `_grupos.json` (regex no nome do objeto ou do pai -> pintura, vidro, pneu, chassi, luz,
  cromado) e a lista do que sai (o símbolo de marca da grade, a escada do autor). Peça sem grupo para o script com erro. Também vira as
  normais para fora: o teto do autor tinha as faces para dentro (material de duas faces, não aparece no Sketchfab) e o
  `carro_completo.py` empurrava o forro do teto para fora da chapa. Deixa o comprimento em x. É o par do `sketchfab_montar.py` (do
  Sagui), que separa por material; o juntar separa por objeto.
- **`sketchfab_preparar.py`:** usa o `--manter-materiais` e o `--sem-pca` do Sagui, e ganhou `--meio-pela-caixa`: o meio em y vem da
  caixa da carroceria, não da média dos vértices (o bocal e o escape de um lado só puxavam o carro 1,3 cm; o centro pelas janelas não
  acontece quando elas não passam nas regras do Gol). Sem a opção, nada muda.
- **`carro_quebravel.py`:** `take: "ilha"` no mapa (cada ilha ligada vai inteira para a caixa que tem a maior parte da área dela,
  com filtro opcional de material e de normal): portas, capô, tampa, para-choques, faróis, lanternas, grade e bagageiro saem na fresta
  do autor, não num plano reto. `--materiais-do-arquivo`: o plástico preto, as luzes e as calotas ficam com o material do arquivo (sem
  ela, tudo que não é vidro, luz ou roda vira pintura, como no Gol).
- **`detalhes_na_casca.py`:** opções novas, todas desligadas por padrão: `--luzes-do-modelo` (faróis e lanternas que dão a volta no
  canto ficam com a forma do autor; farol em `lente_farol`, lanterna em três faixas, freio, seta e ré, de cima para baixo, com as divisas
  cortadas na malha; `--faixas-lanterna 0.45,0.25`; o `--manter-luzes` do Tupiniquim faz duas faixas), `--sem-tampa-tanque` (o modelo
  já tem a dele) e `--manter-chapa-dos-vidros` (a moldura do autor fica a menos de 1,5 cm do vidro e saía com furos). A grade e a placa
  de trás usam o `--manter-grade` e o `--placa-tras-no-para-choque` das outras sessões.
- **Gol inalterado (conferido em 30/10):** a cadeia do Gol rodada com as ferramentas de antes (`git archive HEAD ferramentas`) e as de
  agora: o preparo sai idêntico (hash dos vértices); no corte, os vidros, as rodas e os materiais de todas as peças saem idênticos, e
  as outras peças variam algumas dezenas de vértices, a mesma variação de duas rodadas seguidas do código antigo (o corte e a
  `borracha_vidro.py` não são deterministas nos vértices das bordas).
- **Saída (30/10):** `veiculos/sketchfab/quebravel/furgaozinho/` (35 peças, ~204 mil triângulos; entre-eixos 2,343 m, roda 26,2 cm,
  teto 1,38 m, 1,56 m com o bagageiro; o bagageiro é a peça `roof_rack`, onde a escada do jogo vai presa) e
  `veiculos/sketchfab/completo/furgaozinho/` (kit época 90 de furgão, 90 peças). O vidro de quarta fica na carroceria.
- **Prévias (30/10):** `veiculos/sketchfab/previas/furgaozinho/` (4 vistas, detalhes, 6 cores e os 5 acabamentos), com
  `previa_carro.py` no HDRI da rua, `RODAS=aro_aco13,pneu_p165_70,calota13` e a nova `ESCADA=veiculos/proprios/escada-aluminio.glb`
  (a escada no bagageiro pela regra do `montar_escada_no_teto.py` do Detonauto, apoiada nas barras a 1,445 m). O kit foi refeito com a
  porta de moldura do Jabuti: as colunas do vão não aparecem mais pela janela.
- **Cadeia do Detonauto (30/10, na nuvem):** amassado com 35 malhas, 19 malhas com esqueleto e a roda (cubo a 67 cm; portas de trás,
  bagageiro, grade e retrovisores na carroceria), textura e tinta, 11 malhas do kit. Dados, testes e pedido para o PC no Detonauto
  (`docs/pedido-pc-furgaozinho-completo.md`, `-Modelo Furgaozinho -Row furgaozinho-da-firma`).
- **Pendente:** a soleira do kit sob as portas (o modelo não tem chapa ali) sai na cor do carro sem a textura de desgaste, um tom mais
  claro que a lataria, no jogo e na prévia. A escada entra no jogo pelo kit (Detonauto: `kit_completo_to_detonauto.py --escada`,
  `SM_Furgaozinho_Kit_Escada` presa à carroceria), mas ainda não balança nem cai.

## Sagui do Sketchfab: carro "de jogo" montado por receita (30/10/2026)

O Sagui (micro do Detonauto) saiu do modelo **"Ford Ka MK2 2008-2016" por DEMON_SCARY1235** (Sketchfab, CC BY 4.0, escolhido pelo
Felipe entre 3 candidatos; o crédito está em `veiculos/sketchfab/sagui-demon-scary__d2b74e929d9745ea9d151f8e2b195b17.license.txt`).
É a versão europeia do carro de referência (mais curta e mais alta) e vem "de jogo": a roda solta no centro do arquivo, o pneu em
metades, a carroceria em 15 objetos e 29 materiais de molde, com cores trocadas (carroceria vermelha, vidro azul, cromo azul). O
`.glb` original **não** entra no acervo: traz emblemas e inscrição na geometria (baixar de novo pelo link do crédito).

    python -I ferramentas/sketchfab_montar.py -- <scene.gltf> <pasta>/montado.glb veiculos/sketchfab/quebravel/sagui/sagui_montagem.json
    python -I ferramentas/sketchfab_preparar.py -- <pasta>/montado.glb <pasta>/sagui.glb "carroceria,vidros,rodas" 3.836 1.5945 0.12 30 0 \
        --manter-materiais --sem-pca
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/sagui.glb --out <corte> --id sagui --portas 2 --sem-rotulos \
        --manter-normais --cores-do-arquivo --mapa veiculos/sketchfab/quebravel/sagui/sagui_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/sagui.glb <corte>/sagui.glb
    python -I ferramentas/detalhes_na_casca.py -- <corte>/sagui.glb <corte>/sagui.glb --sem-luzes --sem-retrovisor \
        --placa-tras-no-para-choque --sem-arco-redondo --sem-face-para-choque --sem-limpador --sem-macaneta --sem-friso --sem-faixa \
        --sem-quebra-vento --sem-sinaleira --sem-miudezas --para-choque-pintado --z-placa 0.38 --mapa veiculos/sketchfab/quebravel/sagui/sagui_mapa.json
    python -I ferramentas/assar_desgaste.py -- <corte>/sagui.glb <corte>/sagui.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id sagui --out <kit> --epoca 2000 --aparar-alto 0.55

- **`sketchfab_montar.py` (novo):** tudo por receita JSON (`sagui_montagem.json`). Objetos fora (o volante solto); um **papel por
  material** (`pintura`, `chassi`, `cromado`, `vidro`, `pneu`, `lente_farol`, `refletor`, `luz_vermelha`, `luz_ambar`,
  `luz_branca` ou `remover`) e **regras** por objeto, material e caixa antes dele (a lente do farol vira `lente_farol` opaca e clara,
  a lição do Cuiabano; a da lanterna sai e mostra o vermelho, o âmbar e o branco de dentro; a inscrição do modelo sai; o lugar do
  emblema fica pintado e liso; a maçaneta da tampa vira plástico preto, porque o cromado tinha o desenho da marca). A roda solta é
  soldada (o pneu vinha em metades) e copiada para os 4 cantos. **Alongar:** as caixas de roda andam inteiras (continuam redondas),
  o meio estica até o entre-eixos e os balanços até o comprimento da referência (de 3,62 para 3,836 m; entre-eixos de 2,30 para
  2,452 m). **Baixar:** o que fica acima do topo dos arcos encolhe até o teto ficar a 1,42 m do chão. Grava sem UV e sem normais
  (o exportador duplicava os vértices nas costuras e o preparo não achava o pneu).
- **`carro_completo_dados.json` (Sagui):** saiu a correção de altura de 1,54 m, que era do Sagui do Meshy (o mapa novo já mede
  1,42 m), e entrou `soleira_preta`: o modelo não tem chapa embaixo da porta e a caixa da soleira, em pintura interna sem verniz,
  lia como uma faixa mais clara que a lataria; agora é plástico preto (`carro_completo.py`, opção do carro).
- **`sketchfab_preparar.py`:** `--manter-materiais` (a face com material de nome igual a um papel fica com ele; sem textura, cada
  papel herda a cor de entrada) e `--sem-pca` (a PCA torcia o carro já alinhado em 0,2°). A renomeação dos materiais de entrada
  passou a iterar sobre uma cópia da lista (iterando a coleção, o `cromado` saía `entrada_entrada_cromado` e virava pintura).
- **`carro_quebravel.py`:** `--cores-do-arquivo` (cada face fica com o material do papel que veio no arquivo; o papel da peça não o
  troca: o farol em gota tem lente, refletor e seta; a roda tem aro e pneu) e os códigos `cq_mat` de 6 a 10 para as luzes;
  `take: material` aceita uma **lista** de materiais com caixa; a remoção da "aba de caixilho" só vale no vidro (num farol de
  várias ilhas, as "abas" eram o refletor). Vidro, pneu, cromado e luz, cópias da pintura, ganham a cor do papel.
- **`detalhes_na_casca.py`:** `--sem-luzes` (faróis e lanternas já modelados), `--sem-retrovisor` e `--placa-tras-no-para-choque`.
- **`carro_completo.py`:** `--aparar-alto Z` estende o `aparar_expostos` ao motor e ao porta-malas, de Z para cima, com um teste de
  envelope por vértice (um raio de cima, da frente ou de trás que só bate na casca depois do vértice, ou a menos de 1,5 cm dele,
  apaga a face). No Sagui, o capô curto e inclinado deixava a travessa do motor como uma barra na frente do capô, abas da coluna
  da travessa furando a lente do farol e espinhos das colunas no teto.
- **`previa_carro.py` e `carro_completo.py`:** sem roda cortada por raio, os cantos vêm da lista `rodas` do mapa (sem isso o kit
  saía sem freios e sem forro de caixa de roda); a prévia troca as rodas de kit pela variável `RODAS` (Sagui: aço 14, 185/60, calota 14).
- **O Gol sai igual:** a cadeia do Gol (preparo, corte, borracha, detalhes) rodou com o código antigo e com o novo; o preparo saiu
  idêntico e o resultado final tem os mesmos materiais por peça e os mesmos vértices a 1 mm (a cadeia antiga já varia a divisão
  de vértices entre duas rodadas).
- **Saída:** `veiculos/sketchfab/quebravel/sagui/` (31 peças, ~297 mil triângulos) e `veiculos/sketchfab/completo/sagui/` (kit
  época 2000, 81 peças, com freios e forros das caixas de roda). Prévias em `veiculos/sketchfab/previas/sagui/`.
- **Falta melhorar:** as vistas internas do kit (porta solta, cabine) têm lascas, como as do Gol; o modelo é a versão europeia, de
  rosto parecido mas não igual ao carro de referência; a calota do kit lê branca de longe.

## Lambari do Sketchfab: modelo com vários materiais texturizados (30/10/2026)

O Lambari (cupê de 2 portas dos anos 70, nº 11 da ficha) passou a ser **"Chevrolet Chevette sl 76" por Laerte.Hubaleque (Sketchfab,
CC BY 4.0)**, `veiculos/sketchfab/cupe-sl76-laerte__2322139894c545b6838000f08d853662.glb` (o GLB do autor sem os 2 emblemas da
marca), escolhido pelo Felipe entre 4 candidatos. Diferente do Gol (3 objetos e textura quase branca), o modelo vem com 36 objetos e
texturas PBR: lataria azul com o vão da porta e a borracha pintados na mesma textura, peças externas (cromo, lanternas, faróis,
grade) numa textura só, interior, painel e freios. A cadeia:

    python -I ferramentas/sketchfab_preparar_materiais.py -- <scene.gltf> <pasta>/lambari.glb veiculos/sketchfab/quebravel/lambari/lambari_regras.json
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/lambari.glb --out <corte> --id lambari --portas 2 --frente +x \
        --sem-rotulos --manter-normais --manter-materiais --mapa veiculos/sketchfab/quebravel/lambari/lambari_mapa.json --sem-fbx
    python -I ferramentas/placa_na_casca.py -- <corte>/lambari.glb <corte>/lambari.glb
    python -I ferramentas/grade_propria.py -- <corte>/lambari.glb <corte>/lambari.glb
    python -I ferramentas/assar_desgaste.py -- <corte>/lambari.glb <corte>/lambari.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id lambari --out <kit> --epoca 70

- **`sketchfab_preparar_materiais.py` (novo):** o `sketchfab_preparar.py` do Gol fica como está. Este lê um `_regras.json` por carro:
  objetos que saem (interior, emblemas, freios, escapamento: o kit põe os dele), o material nosso de cada objeto, direto ou **pela
  cor e pelo metal da textura na face** (mediana de amostras nos cantos e no centro da UV), com regras de matiz, saturação, valor e
  metal; ilhas pequenas de um material no meio de outro voltam para o de fora (as venezianas da coluna C desenhadas na textura viravam
  cacos pretos); frente, escala pelo comprimento, chão em z = 0, origem entre os eixos e **centro em y pelas rodas**. Grava o número
  da ilha original em cada vértice (`_ilha`, no GLB `_ILHA`) para o corte.
- **`carro_quebravel.py` ganhou** `--manter-materiais` (cada face fica com o material que veio, inclusive `cromo`, `lente_farol` e
  `luz_*`; o papel da peça não troca), no mapa `"ilhas": true` (cada chapa do autor vai inteira para a caixa que contém a maior parte
  dela, sem cortar pelo plano; a solda juntava o para-lama à frente e ele ficava na carroceria, por isso a ilha original manda),
  `"materiais": [...]` (só as faces desses materiais: o capô sem o friso cromado, o farol sem a beira do capô) e `"material"` na
  roda (o friso cromado do arco passa perto do pneu).
- **`placa_na_casca.py` (novo):** o modelo não tem placa. Cria `plate_front` e `plate_rear` (40 x 13 cm em branco, moldura,
  parafusos, suporte preto de 3 cm) na altura pedida (`--z-frente 0.335 --z-tras 0.345`, embaixo dos para-choques, como no carro
  real), 0,8 cm à frente do ponto mais saliente da carroceria atrás dela (o para-choque logo acima puxava a placa 15 cm para fora).
- **Cromo de verdade:** material `cromo` (para-choques, frisos dos arcos e da soleira, molduras dos vidros, aro dos faróis). No
  Detonauto `kit_names.py` o leva ao `MI_DNCromoCoupe` (prata, metal 1, aspereza 0,15, família do amassado) e o `assar_desgaste.py`
  põe esses valores na prévia, sem textura. O `cromado` de sempre (cromo pintado na textura do Meshy) continua `MI_DNPeca<Modelo>`.
- **Kit (opções da linha `lambari` de `carro_completo_dados.json`, o Gol não usa):** `aparar_por_vertice` (a fita da coluna A do vão
  tinha o centro dentro da casca e as pontas para fora da coluna A estreita: abas cor do carro em volta do para-brisa),
  `aparar_desde_a_saia` (testa de 3 cm acima da saia para cima), `aparar_motor`, `capo_pelas_pontas` (a travessa da frente passava o
  capô que cai nos cantos) e `corrigir.topo_da_saia` 0,31 (com 0,28 o raio da soleira passava por baixo da lateral e ela saía 4 cm
  para fora). As caixas dos vidros no mapa são as medidas dos vidros do modelo (+1 cm): o kit desenha as colunas por elas.
- **Gol inalterado:** com o código antes e depois, o corte e o kit do Gol saem com distância máxima 0,000000 m (32 e 158 objetos).
- **Rodas:** no jogo, aço 13 **sem calota** e pneu 175/70 (`Data/CarWheels.csv` do Detonauto); a calota cheia branca destoava da
  roda de aço com calotinha do carro real (`previas/lambari/lambari-rodas-calota.jpg`, com e sem).
- **Saída:** `quebravel/lambari/` (29 peças, 77,5 mil triângulos, fresta zero nos amassados), `completo/lambari/` (79 peças) e
  `previas/lambari/` (vistas, closes, as 14 cores e os 5 acabamentos com o HDRI de rua, a textura e o preparo dos materiais).
- **`grade_propria.py` (novo, 30/10, noite; "siga" do Felipe):** a grade de barras do carro real é detalhe de assinatura (a ficha
  pede "sem a grade de barras do modelo real" e o CLAUDE.md do Detonauto manda mudar o detalhe que chega perto demais). Apaga o
  cromo e o preto da grade antiga dentro da caixa (`--caixa`, 1,3 cm a mais nas pontas) na peça `grille`, na carroceria e no
  para-choque da frente (o corte tinha deixado barras nos dois) e faz a nossa: moldura cromada de 1,2 cm, fundo preto recuado 5 cm,
  colmeia preta de 9 x 3 células largas e uma barra cromada no meio (`--colunas`, `--linhas`, `--sem-barra`), face em x = 1,79 (a
  1,81 ela saltava à frente dos aros dos faróis como uma placa colada). As venezianas da coluna C (só desenho na textura) ficaram
  de fora de propósito pelo mesmo motivo.

## Pão de Forma do Sketchfab: furgão de passageiros, motor atrás (30/10/2026)

O Pão de Forma do Detonauto passou a ser o "VW T1 style Bus Free" de Libau Media (Sketchfab, CC BY 4.0, crédito em `CREDITOS.md`),
id `furgao-classico` no acervo. O do Meshy (`meshy-conta/pao-de-forma__*`) saiu sem o painel em V da frente e fica como reserva. O
original traz o emblema da marca modelado: ele não entra no acervo; o que fica é a saída do preparo, já sem o emblema
(`veiculos/sketchfab/furgao-classico-libau__c6dc0d2275524bb1a43ddc398d2be3bc.glb`). A cadeia:

    python -I ferramentas/sketchfab_preparar.py -- <scene.gltf do download> <prep>/pao-de-forma.glb x 4.50 1.95 0.06 30 0 \
        --juntar veiculos/sketchfab/quebravel/furgao-classico/furgao-classico_juntar.json
    python -I ferramentas/carro_quebravel.py -- --entrada <prep>/pao-de-forma.glb --out <corte> --id furgao-classico --portas 2 \
        --sem-rotulos --manter-normais --mapa veiculos/sketchfab/quebravel/furgao-classico/furgao-classico_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/furgao-classico.glb <corte>/furgao-classico.glb --dona glass_rear=body
    python -I ferramentas/detalhes_na_casca.py -- <corte>/furgao-classico.glb <corte>/furgao-classico.glb --mapa <o mapa> \
        --sem-arco-redondo --sem-face-para-choque --sem-friso --sem-macaneta --sem-faixa --sem-quebra-vento --sem-sinaleira \
        --sem-retrovisor --sem-miudezas --farol-redondo --sem-lanternas --sem-folha-solta --para-choque-pintado
    python -I ferramentas/assar_desgaste.py -- <corte>/furgao-classico.glb <corte>/furgao-classico.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id furgao-classico --out <kit>
    RODAS=aro_aco15,pneu_p165_95,calota15 ... python -I ferramentas/previa_carro.py -- ...     (prévias; CAM= para a van, 4,5 m)

- **`sketchfab_preparar.py --juntar <json>` (novo):** para modelo de muitos objetos, cada um com seus materiais. O JSON dá o material
  nosso de cada material do arquivo (`pintura`, `vidro`, `pneu`, `chassi`, `luz`, `cromado` ou `fora`), os objetos que são rodas,
  `fora_objetos` (volante e bancos: o kit põe o interior dele), `fora_caixas` (ilhas inteiras dentro de uma caixa saem: o emblema),
  `frente` (num furgão a frente e a traseira têm a mesma altura e a regra do Gol errava) e `vidros_raio` (a janela de trás veio
  aberta: raios de fora acham o vão e a moldura, e o vidro novo fica 8 mm para dentro dela). O arquivo vem com os vértices soltos nas
  costuras e o teto é um leque de triângulos finos: o preparo solda as costuras e, no fim, devolve as normais do arquivo (projetadas
  pela normal; o teto tem forro por dentro a 1 cm). Sem a opção o Gol sai idêntico (posições, materiais e normais conferidos).
- **Corte:** as portas da cabine vão pela ilha do modelo (`take: "ilha"`): a roda da frente fica embaixo da porta, e o recorte por
  caixa deixava dentes no arco; a caixa da porta começa em 0,80 m (acima do arco), senão o forro da porta do kit descia até a soleira
  e aparecia pelo arco como uma prateleira na cor do carro. A placa de trás fica em 0,61-0,74 m, acima da faixa preta do para-choque. O pneu do mapa vai até 37,2 cm do cubo e |y| 0,81: com 40 cm ele levava a borda do arco junto. Sem
  para-lamas e sem capô (cabine avançada); a `trunk` é a tampa do motor.
- **`borracha_vidro.py --dona vidro=peça`:** o vidro de trás fica na carroceria (a tampa de trás é a do motor, abaixo da janela).
- **`detalhes_na_casca.py`:** `--sem-lanternas` (as lanternas redondas pequenas do modelo ficam; a de 3 segmentos não cabe) e
  `--sem-folha-solta` (no furgão a "folha solta" do Gol é a frente da carroceria atrás do para-choque).
- **`carro_completo.py`:** o dado `passageiros` troca a divisória com grade da versão de carga por fileiras do banco de trás (pelas
  janelas se via uma gaiola); a derivada `y_vao_traseira` deixa o vão de trás por dentro das venezianas da lateral (as aletas que olham
  para dentro saíam e abriam um buraco); o estepe em pé da área de carga não sai mais pela lateral. Nos dados de `furgao-classico`,
  `x_frente` e `x_corta_fogo` vêm da chapa do nariz, não do para-choque (o painel e os acabamentos de pé saíam pela frente).
- **`rodas_kit.py`:** aro de aço 15, calota 15 e o pneu diagonal alto 165/95 (34,7 cm de raio; o perfil 95 é o máximo do validador
  do Detonauto); os itens que já existiam saem idênticos.
- **Saída (30/10):** `quebravel/furgao-classico/` (36 peças, ~412 mil triângulos, 4,50 x 1,95 x 1,95 m, entre-eixos 2,51 m),
  `completo/furgao-classico/` (68 peças, época 70, boxer traseiro, passageiros) e as prévias em `previas/furgao-classico/`. A cadeia de
  conferência do Detonauto (make_crush_channels, kit_to_detonauto, glb_texturas, kit_completo_to_detonauto) passou com
  `--modelo PaoDeForma`: 5 peças, 8 vidros (os 10 fixos da lateral ficam na carroceria), 8 malhas de kit, amassado em 512x512.

## Jabuti do Sketchfab: modelo em peças com material por objeto (30/10/2026)

O Jabuti (nº 12 da ficha, micro) passou do Meshy a um modelo feito por gente, escolhido pelo Felipe em 30/10: **"Fiat_147" por
lael.eugenio (Sketchfab, CC BY 4.0)**, `veiculos/sketchfab/jabuti-lael__6c643d284d144dcb8db46ab11285ec0b.glb` (5,3 MB, 52 objetos,
13 materiais lisos, interior do autor). Como o Furgãozinho, vem em peças (portas com a moldura da janela, capô, tampa, faróis,
lanternas, para-choques de lâmina), mas o mesmo material muda de papel conforme a peça (o branco é lente no farol e ré na lanterna; o
prata é cromo no para-choque e plástico na capa do retrovisor), então o preparo ganhou um arquivo com o material por objeto.

    python -I ferramentas/sketchfab_preparar.py -- <zip glTF>/scene.gltf <tmp>/jabuti.glb veiculos/sketchfab/quebravel/jabuti/jabuti_preparo.json \
        3.4925 1.35 0.10 30 0 0.00001
    python -I ferramentas/carro_quebravel.py -- --entrada <tmp>/jabuti.glb --out <corte> --id jabuti --portas 2 --sem-rotulos \
        --manter-normais --manter-materiais --mapa veiculos/sketchfab/quebravel/jabuti/jabuti_mapa.json --sem-fbx
    python -I ferramentas/detalhes_na_casca.py -- <corte>/jabuti.glb <corte>/jabuti.glb --sem-arco-redondo --sem-face-para-choque \
        --sem-limpador --sem-macaneta --sem-friso --sem-faixa --para-choque-pintado --sem-quebra-vento --sem-sinaleira \
        --lanternas-como-vieram --manter-retrovisores --z-placa 0.215 --z-barra-frente 0.42 --placa-na-propria-peca --suporte-max 0.04 \
        --mapa veiculos/sketchfab/quebravel/jabuti/jabuti_mapa.json
    python -I ferramentas/assar_desgaste.py -- <corte>/jabuti.glb <corte>/jabuti.glb --tamanho 2048 --amostras 32 --uv-smart
    python -I ferramentas/carro_completo.py -- --corte veiculos/sketchfab/quebravel/jabuti --id jabuti \
        --out veiculos/sketchfab/completo/jabuti --aparar-abaixo

O comprimento passado (3,4925) é o da carroceria do autor: os para-choques passam dela e o carro inteiro fica com os 3,62 m reais.

- **`sketchfab_preparar.py`, modo por preparo:** o 3º argumento pode ser um `<id>_preparo.json` (`corpo`, `rodas`, `materiais` gerais e
  `objetos` com a exceção de cada um; só os objetos listados ficam, o interior do autor sai). As rodas vêm dos objetos de roda (o pneu do
  autor é feito de fatias finas, que a regra de ilha do Gol não reconhecia) e os vidros das ilhas `vidro`. Convive com o `--juntar` do
  Pão de Forma, que só tem o mapa geral e seis materiais. A solda (9º argumento) é obrigatória neste modelo: o glTF chega com os vértices
  separados.
- **`carro_quebravel.py`:** usa o `--manter-materiais` do Lambari (cada face fica com o material do arquivo: `luz_ambar`,
  `luz_vermelha`, `luz_branca`, `cromo`); ganhou `extra` no mapa (caixas a mais sem filtro de normal: a
  grelha do capô, com as fendas olhando para os lados, vai com o capô) e `exceto_materiais` (o pisca âmbar que desce 1 cm na caixa do
  para-choque fica na carroceria). Caixas de placa precisam de 4 cm ou mais: a erosão da seleção apaga uma faixa de 1 cm.
- **`detalhes_na_casca.py`:** `--lanternas-como-vieram` (a lanterna do autor fica; a chapa pintada da caixa vira moldura),
  `--z-barra-frente` (a altura em que o raio mede a frente do para-choque; o 0,48 do Gol passava por cima), `--placa-na-propria-peca`
  (a placa de trás mede o fundo na chapa que a peça da placa levou; sem isso o raio atravessava o buraco e a placa saía a 2,7 m),
  `--suporte-max` (fundo máximo do suporte) e placa pendurada embaixo do para-choque sem chapa atrás (suporte de 3 cm).
- **`assar_desgaste.py --uv-smart`:** chapa lisa e densa partia a projeção em caixa em 88 mil cartas (74 texels por metro). Com a
  opção, os vértices são soldados, as ilhas saem do Smart UV do Blender (60°) e entram no mesmo empacotador (8,8 mil cartas, 153 texels
  por metro); a altura da sujeira vem de um bake da posição.
- **`carro_completo.py`:** porta com moldura (a caixa da porta passa 15 cm da cintura) não ganha as colunas do vão acima da cintura,
  e a coluna e a borda da chapa da porta param antes de onde a lateral dobra para dentro (apareciam pelo para-brisa e na base da
  coluna A; deve valer para o Furgãozinho, cuja falta é essa, mas não testei nele); `--aparar-abaixo` tira do porta-malas, do vão e da porta, da saia para cima, o que fica fora
  da casca (a caixa das lanternas furava a quina redonda de trás).
- **No Detonauto:** o cromo de verdade (para-choques de lâmina, frisos da grade, molduras das janelas) usa o material `cromo` do
  Lambari, que o `kit_names.py` já leva ao `MI_DNCromoCoupe`.
- **Gol inalterado (conferido em 30/10):** a cadeia do Gol com as ferramentas do `origin/main` e com as de agora: preparo, corte,
  borracha e detalhes a 0,0000 mm (vértice mais distante); na mesma entrada, o `assar_desgaste.py` dá a textura idêntica byte a byte
  e o `carro_completo.py` o kit a 0,0000 mm. O que muda de uma rodada para outra é só a ordem dos vértices (duas rodadas do código
  antigo também diferem nela).
- **Saída (30/10):** `veiculos/sketchfab/quebravel/jabuti/` (31 peças, ~364 mil triângulos; 3,62 x 1,58 x 1,35 m, entre-eixos 2,21 m,
  roda 28 cm) e `veiculos/sketchfab/completo/jabuti/` (kit época 70, 79 peças, LOD0 ~230 mil). Prévias com o HDRI da rua em
  `veiculos/sketchfab/previas/jabuti/`.
- **Falta / conhecido:** duas dobras leves, só de perto. A da quina de trás (tampa com a lateral) já vem do modelo do autor: aparece
  no preparo, antes do corte. A da quina da frente (para-lama com a frente, junto do farol) nasce no corte, onde a costura atravessa
  a curva; mudar a costura de lugar, as normais do corte (`--manter-normais` do assado, `--normais-da-original` no preparo) e a
  média das normais entre as peças na emenda não a tiraram, e as duas primeiras enrugam a lataria inteira com o verniz. O teste de
  face virada do assado erra neste modelo (19 mil faces "viradas" na porta: a chapa dupla do autor a menos de 2,5 cm do casco do
  corte), sem efeito visível. Pelo vidro de quarta aparece o forro lateral de trás do kit (vinil marrom da época 70). Adensar com
  aresta de 15 cm daria ~255 mil triângulos na casca, mas amassaria mais quadrado nas chapas grandes: ficou 10 cm (~364 mil);
  medir no PC.

## Tropeiro: picape aventureira do Sketchfab (30/10/2026)

A picape nova do Detonauto (cabine simples, versão aventureira: para-choques e proteções pretas, caçamba aberta com santo-antônio)
passou a ser um modelo feito por gente: a **picape do Ramon.Dos.Santos (Sketchfab, CC BY 4.0; o título do autor está no crédito)**,
`veiculos/sketchfab/picape-cabine-simples-ramon__2b5c1ffec3b545168ab5280296cd5ffa.glb`. Dos 4 candidatos mostrados ao Felipe ("siga
você"), os dois da geração certa eram extração de jogo: um mod convertido pelo SketchUp (materiais com nome de textura de mod, faces
duplicadas) e outro com os nomes internos de um jogo de corrida (`Ext_Plate_Mesh_Trigger`, `Glow_DRL`). Este é o único de origem limpa
(feito no Blender, objetos `Cube.005`, materiais em português), mas a frente é a da geração de 2000 a 2005, não a de 2010 da
referência. O original veio rebaixado, com rodas de tuning, interior, lona na caçamba e símbolos de marca: no acervo fica a versão sem
os símbolos, sem as texturas de placa, de logo e de um panfleto e sem o chão da cena, com os nomes do autor (o `_grupos.json` vale).

    python -I ferramentas/sketchfab_juntar.py -- veiculos/sketchfab/picape-cabine-simples-ramon__2b5c1ffec3b545168ab5280296cd5ffa.glb \
        <tmp>/juntado.glb veiculos/sketchfab/quebravel/tropeiro/tropeiro_grupos.json
    python -I ferramentas/sketchfab_preparar.py -- <tmp>/juntado.glb <tmp>/tropeiro.glb "carroceria,vidros,rodas" 4.38 1.42 0.12 30 0 \
        --manter-materiais --sem-pca --meio-pela-caixa
    python -I ferramentas/decimar.py -- <tmp>/tropeiro.glb <tmp>/tropeiro_red.glb 125000
    python -I ferramentas/carro_quebravel.py -- --entrada <tmp>/tropeiro_red.glb --out <corte> --id tropeiro --portas 2 --sem-rotulos \
        --manter-normais --materiais-do-arquivo --mapa veiculos/sketchfab/quebravel/tropeiro/tropeiro_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/tropeiro.glb <corte>/tropeiro.glb --dona glass_rear=body
    python -I ferramentas/detalhes_na_casca.py -- <corte>/tropeiro.glb <corte>/tropeiro.glb --sem-arco-redondo --sem-face-para-choque \
        --sem-quebra-vento --sem-sinaleira --sem-faixa --z-placa 0.435 --z-friso 0.605 --protecoes --z-saia 0.36 --z-protecao 0.46 \
        --luzes-do-modelo --manter-grade --grade-preta --placa-tras-no-para-choque --mapa veiculos/sketchfab/quebravel/tropeiro/tropeiro_mapa.json
    python -I ferramentas/assar_desgaste.py -- <corte>/tropeiro.glb <corte>/tropeiro.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id tropeiro --out <kit> --aparar-mais 0.6 0.65 --sem-saia-para-choque

- **`sketchfab_juntar.py`:** chaves opcionais no `_grupos.json`: `"erguer"` (sobe tudo menos pneus e aros; o modelo vinha rebaixado
  e a aventureira é alta: 5 cm reais), `"endireitar"` (as rodas da frente vinham esterçadas 18,9°: o eixo do pneu, pela menor
  dispersão no plano do chão, volta a ficar de lado, girando aro e cubo junto) e `"nao_virar"` (a virada de normais do Furgãozinho
  virava para fora as paredes da caçamba, que olham para dentro de propósito: elas iam para a lateral no corte e saíam pretas; aqui
  nada é virado, as normais do autor já estão certas). Material do arquivo com nome de papel nosso vira `entrada_<nome>` (o painel
  tinha um `vidro`, e o nosso saía `vidro.001`). Imprime as ilhas viradas por peça. Furgãozinho conferido: juntado igual (0 mm).
- **`decimar.py` antes do corte:** o modelo já é denso (225 mil triângulos); o corte dobra a malha (espessura e vão de cada peça) e
  passava de 600 mil. Reduzido a 125 mil (desvio p99 0,07 mm), o corte fica com ~281 mil, perto do Gol.
- **Mapa:** portas e tampa da caçamba por `take: "ilha"` (a porta é malha solta do autor, com o quadro da janela; pelo corte por
  planos sobravam o friso em relevo e as bordas cruzando o vão da porta aberta); `fender_rear_*` são as laterais da caçamba; o vidro
  fixo de trás da porta vai com a porta; `piso_cacamba` nas medidas. A fita preta lateral do autor sai no juntar (inteira, cruzava o
  vão da porta) e o friso do `detalhes_na_casca.py` entra por cima do friso em relevo dele.
- **`detalhes_na_casca.py`:** `--protecoes` (alargador preto em volta de cada caixa de roda e protetor da soleira, como geometria:
  uma tira de 4 mm sobre a chapa, por raios de lado, com 4 a 6 fileiras para acompanhar a curva da porta; a borda do arco é medida
  na chapa; cada trecho vai para a peça onde está; trocar o material das faces saía em serrote numa malha grossa) e `--grade-preta`
  (com `--manter-grade`: a grade do autor fica, em plástico preto, com as palhetas que o corte deixou na carroceria). Os faróis de
  milha vêm como `cromado` do juntar: como `luz`, no para-choque, viravam lente de lanterna.
- **`carro_completo.py`, carroceria `picape` (com teste):** cabine curta (`x_cabine_tras` na parede do vidro traseiro, encosto 14 cm à
  frente, sem banco de trás), acabamento de plástico na parede de trás da cabine, sem porta-malas e sem vão da traseira (a caçamba é
  chapa a céu aberto); o grupo novo `cacamba` (fora do `recolher_na_casca` e do `aparar_expostos`, que tomariam a caçamba aberta por
  "fora da casca") com o protetor estriado no assoalho, 4 ganchos de amarração e o santo-antônio sobre as bordas (o topo da borda é
  achado nas laterais da caçamba, que o `z_casca` não olhava); o estepe pendurado sob a caçamba atrás do eixo; na picape a saia de
  trás sobe o raio até o para-choque (passava por baixo dele e ia parar 60 cm para dentro, cortando o estepe). Nos dados do Tropeiro: `aparar_desde_a_saia`, `aparar_motor` e a chave nova `fundo_farol_rente` (o fundo dos faróis e a travessa
  de cima do painel dianteiro param abaixo do topo dos faróis: o capô da picape fica alguns cm acima deles e a ponta da travessa
  aparecia na fresta, sobre o canto de dentro de cada farol) e `fundo_cofre_visivel: 0.28` (o para-lama interno e a travessa
  começam no fundo do para-choque: na picape erguida o para-choque fica 6 cm acima do fundo do cofre, e as colunas pintadas da
  travessa apareciam por baixo dele na cor do carro; motor e longarinas ficam onde estavam). Na picape o assoalho sobe atrás da
  roda de trás até debaixo do piso da caçamba (reto, passava 20 cm abaixo do para-choque de trás e aparecia por baixo dele como
  aba escura), e o kit sai com `--sem-saia-para-choque` (a chapa da saia da frente pendurava sob o para-choque).
- **O Gol não muda (conferido em 30/10):** com as mesmas entradas, o `detalhes_na_casca.py` e o `carro_completo.py` de `main` e os
  daqui dão as mesmas 32 peças do corte e os mesmos 158 objetos do kit, a 0 mm (comparação por ponto mais perto, que não depende da
  ordem dos vértices; o corte do próprio código antigo muda a ordem e a solda de uma rodada para outra).
- **Saída (30/10):** `veiculos/sketchfab/quebravel/tropeiro/` (34 peças, ~281 mil triângulos, 4,38 x 1,70 x 1,42 m sem retrovisores,
  entre-eixos 2,534 m, roda 30,8 cm) e `veiculos/sketchfab/completo/tropeiro/` (kit época 2000 de picape, 81 peças, ~224 mil
  triângulos). Rodas do kit novas para ele: liga 15 de 8 furos ovais e pneu 205/60 R15 (`rodas_kit.py`), no lugar das de tuning.
  Prévias em `veiculos/sketchfab/previas/tropeiro/`, pelo `previa_carro.py` com os materiais e valores do jogo (cores de
  `Data/Paints.csv`, acabamentos de `Data/PaintFinishes.csv`, `RODAS=aro_liga15,pneu_p205_60,`: calota vazia, roda de liga).
- **Diferenças para a referência:** a referência (4,49 x 1,71 x 1,50 m, entre-eixos 2,75 m) é da geração seguinte; a largura bate, o
  comprimento e a altura ficam 11 e 8 cm menores, e a frente (faróis, grade) é a da geração de 2000. Esticar a casca para as medidas
  de 2010 deformaria as rodas e as portas; se o Felipe quiser a frente de 2010, só o Meshy (com custo) ou outro modelo.
- **Defeitos conhecidos:** reflexo ondulado na tampa da caçamba (malha do autor); borda serrilhada no quadro da janela atrás da
  porta; com o kit, uma haste clara na fresta da frente da porta. Visto de perto: fresta escura entre o para-choque da frente e a
  chapa, pontas retas do alargador encostando na chapa e dois cortes laranja no alto de cada farol (a chapa por um vão da lente).
- **No Detonauto (30/10):** classe `picape` em `FDNGarageClass::All()`, linhas do Tropeiro nos dados, grupo `cacamba` no
  `kit_completo_to_detonauto.py` e a cadeia do Blender conferida na nuvem. Falta o PC: `docs/pedido-pc-tropeiro-completo.md` do
  Detonauto (montar, compilar, testar, capturar e jogar). O veredito visual é a captura do jogo.
## Besouro do Sketchfab: clássico de motor atrás, separado pela textura (30/10/2026)

O Besouro do Detonauto deixou o Meshy pelo caminho do Cuiabano. Modelo escolhido pelo Felipe entre 5 candidatos: o de Matej Ondra
(Sketchfab, CC BY 4.0; crédito em `CREDITOS.md`), feito em Maya e Substance, 172 mil triângulos, cada peça numa ilha (portas, os quatro
para-lamas aparafusados, tampas, estribos, para-choques). Ele vem em 4 conjuntos de textura, sem objeto de vidro nem de roda: o vidro
só existe no mapa de transmissão. O original não entra no acervo (emblema no capô, logotipo nas calotas, placas com letras); a licença
fica em `veiculos/sketchfab/besouro-matej-ondra__3d166ec739cb440984cbcd17608675e0.license.txt` e o glTF se baixa de novo pela API.

    python -I ferramentas/sketchfab_reagrupar.py -- <scene.gltf> <pasta>/reagrupado.glb --config veiculos/sketchfab/quebravel/besouro/besouro_reagrupar.json
    python -I ferramentas/sketchfab_preparar.py -- <pasta>/reagrupado.glb <pasta>/besouro.glb "carroceria,vidros,rodas" 4.08 1.50 0.06 30 0 0 1 --manter-materiais
    python -I ferramentas/carro_quebravel.py -- --entrada <pasta>/besouro.glb --out <corte> --id besouro --portas 2 --sem-rotulos \
        --manter-normais --sem-solda --materiais-entrada --mapa veiculos/sketchfab/quebravel/besouro/besouro_mapa.json --sem-fbx
    python -I ferramentas/detalhes_na_casca.py -- <corte>/besouro.glb <corte>/besouro.glb --mapa veiculos/sketchfab/quebravel/besouro/besouro_mapa.json \
        --sem-arco-redondo --sem-face-para-choque --sem-limpador --sem-macaneta --sem-friso --sem-miudezas --para-choque-pintado \
        --sem-faixa --sem-quebra-vento --sem-sinaleira --luzes-modeladas --retrovisores-como-vieram \
        --piscas 1.15,1.28,0.54,0.62,0.835,0.89 --z-placa 0.32 --z-barra-frente 0.41 --placa-tras-colada
    python -I ferramentas/assar_desgaste.py -- <corte>/besouro.glb <corte>/besouro.glb --tamanho 2048 --amostras 32 --virar-so-para-dentro
    python -I ferramentas/carro_completo.py -- --corte <corte> --id besouro --out <kit>
    python -I ferramentas/rodas_kit.py -- --so p165_80          (só o pneu novo; os outros GLBs ficam)

- **`sketchfab_reagrupar.py` (novo):** modelo em várias malhas por conjunto de textura vira os 3 objetos do preparo (`carroceria`,
  `vidros`, `rodas`), por um JSON: ilha cuja transmissão na UV passa do limiar é vidro (as lentes dos faróis, em caixas `vidro_fora`,
  ficam na carroceria como `luz`); ilha dentro de um cilindro de roda ou abaixo de `assoalho_z` vai para as rodas; `tirar_objetos`
  (o interior de fábrica: o kit faz o nosso) e `apagar` (caixas: o emblema do capô e o logotipo das 4 calotas). Com `classes`, cada
  ilha da carroceria sai `cromado` (canal metálico da textura original), `chassi` (escura) ou `pintura`; vidro e roda saem `base`,
  que o preparo com `--manter-materiais` não sobrescreve. Assim frisos, para-choques, molduras, maçanetas e aros dos faróis chegam
  cromados ao jogo.
- **`carro_quebravel.py`:** `take: "ilhas"` (ilha inteira com 90% das faces na caixa, `n_min` e caixas `fora` de exclusão; o `ilha`
  das outras sessões, com 50%, continua igual), `--sem-solda` (a solda de 0,1 mm grudava o para-lama traseiro na lateral, vértice
  com vértice), `--materiais-entrada` (cromado, chassi e luz do arquivo voltam depois do `_materiais_unica`, e faróis e lanternas
  ficam com os materiais das faces: lente, aro cromado, caixa pintada) e `so_ilhas` no `take: "roda"` (o cilindro do pneu pegava em
  zigue-zague os triângulos da borda do para-lama; no jogo, com as rodas de kit, a borda ficava com dentes). Papel `remover` com
  `ilhas`: as garras e os tubos dos para-choques saem (o carro de referência, nacional dos anos 70-80, tem lâmina simples).
- **`detalhes_na_casca.py`:** `--luzes-modeladas` (nada refeito em caixa: farol em `lente_farol`; a lente pintada da lanterna vira seta
  em cima, freio no meio e ré embaixo), `--retrovisores-como-vieram` (o redondo cromado do modelo), `--piscas` (caixa espelhada em y:
  o pisca em cima do para-lama da frente vira âmbar), o `--z-barra-frente` do Jabuti (0,41: a lâmina é baixa) e
  `--placa-tras-colada` (a placa de trás no ponto mais saliente da tampa abaulada, com suporte de 3 cm; sem ela a placa sumia dentro
  do bojo).
- **`assar_desgaste.py --virar-so-para-dentro`:** a chapa simples sob o friso bate perto pela normal e sai livre para dentro; era
  "desvirada" e depois o `hidden_paint_faces` do Detonauto a apagava (dentes pretos sob o friso cromado). Só vira o que olha para o
  meio do carro.
- **`carro_completo.py`:** a sonda da saia só aceita o que fica além da roda (a lâmina alta deixava o raio bater no tubo do eixo
  traseiro, e a saia de trás caía no entre-eixos apagando o motor e o escapamento); por carro nos dados: `estepe_recuo` e
  `estepe_inclinacao` (o estepe da frente furava o bico da tampa), `saias: false` (a saia preta sob a lâmina aparecia como bloco) e o
  `aparar_desde_a_saia` das outras sessões (o painel lateral do banco de trás aparecia na fresta do para-lama) e `lateral_traseira_recuada`
  (0,08: a lateral traseira da cabine fica atrás da chapa de até 8 cm acima; rente à borda do para-lama aparafusado, ela aparecia em
  manchas cinza pela fresta da emenda, porque a carroceria acaba onde ele começa); as paredes do vão do
  motor boxer param onde a casca fica mais estreita que elas (saíam nos cantos da tampa do motor). `besouro` nos dados vale também para
  o Besouro do Meshy, que fica no acervo como estava.
- **`rodas_kit.py`:** pneu 165/80 R15 (raio 32,2 cm, perto do 5.60-15 do carro real), no aro de aço 15 e na calota 15 do Pão de
  Forma, e `--so` para gerar só alguns itens juntando ao `rodas_kit.json` (os outros GLBs ficaram idênticos byte a byte;
  `test_rodas_kit.py` passa). Na prévia, `RODAS=aro_aco15,pneu_p165_80,calota15`.
- **Gol inalterado (conferido em 30/10, depois de juntar com o `main`):** preparo, detalhes, assado (textura byte a byte) e kit do Gol
  saem idênticos com as ferramentas de antes e as de agora; no corte, faces, materiais e área de cada peça iguais, com a variação de
  vértices das bordas que duas rodadas do código antigo já têm.
- **Saída:** `veiculos/sketchfab/quebravel/besouro/` (35 peças, ~261 mil triângulos; 4,14 x 1,54 x 1,50 m, entre-eixos 2,414 m) e
  `completo/besouro/` (kit época 70, motor boxer atrás, porta-malas com estepe inclinado e tanque na frente, 67 peças). Prévias em
  `veiculos/sketchfab/previas/besouro/` (4 vistas, detalhes, as 14 cores de `Data/Paints.csv` e os 5 acabamentos). A cadeia de
  conferência do Detonauto (`make_crush_channels.py`, `kit_to_detonauto.py`, `glb_texturas.py`, `kit_completo_to_detonauto.py`,
  `rodas_to_detonauto.py`) passa: 21 malhas com esqueleto e 8 do kit.

## Gaúcho V8 do Sketchfab: cupê hardtop em peças do autor (30/10/2026)

O Gaúcho V8 (nº 9 da ficha, muscle) passou do Meshy (que saiu sedã de 4 portas; a referência é um cupê de 2 portas sem coluna do
meio) a um modelo feito por gente, escolhido pelo Felipe em 30/10 entre 4 candidatos: **"Opala" por Chamicall fire / ClrModels
(Sketchfab, CC BY 4.0)**, `veiculos/sketchfab/gaucho-v8-clrmodels__94c57c65e64546f2ae5fd179e8580c11.glb` (16,2 MB, 98 objetos,
materiais lisos com o nome do papel, interior do autor). Como o Jabuti, vem em peças soltas (capô, tampa, as duas portas, para-choques
cromados, faróis redondos com aro, lanternas, molduras cromadas das janelas, retrovisores, maçanetas, palhetas), então segue o modo
por preparo.

    python -I ferramentas/sketchfab_preparar.py -- veiculos/sketchfab/gaucho-v8-clrmodels__<uid>.glb <tmp>/gaucho-v8.glb \
        veiculos/sketchfab/quebravel/gaucho-v8/gaucho-v8_preparo.json 4.47 1.38 0.10 30 0 0.00001
    python -I ferramentas/carro_quebravel.py -- --entrada <tmp>/gaucho-v8.glb --out <corte> --id gaucho-v8 --portas 2 --sem-rotulos \
        --manter-normais --manter-materiais --mapa veiculos/sketchfab/quebravel/gaucho-v8/gaucho-v8_mapa.json --sem-fbx
    python -I ferramentas/detalhes_na_casca.py -- <corte>/gaucho-v8.glb <corte>/gaucho-v8.glb --sem-luzes --sem-retrovisor \
        --manter-grade --sem-macaneta --sem-limpador --sem-friso --sem-faixa --para-choque-pintado --sem-quebra-vento --sem-sinaleira \
        --sem-arco-redondo --sem-tampa-tanque --z-placa 0.315 --z-placa-tras 0.68 --placa-na-propria-peca \
        --mapa veiculos/sketchfab/quebravel/gaucho-v8/gaucho-v8_mapa.json
    python -I ferramentas/assar_desgaste.py -- <corte>/gaucho-v8.glb <corte>/gaucho-v8.glb --tamanho 2048 --amostras 32 --uv-smart
    python -I ferramentas/carro_completo.py -- --corte veiculos/sketchfab/quebravel/gaucho-v8 --id gaucho-v8 \
        --out veiculos/sketchfab/completo/gaucho-v8 --epoca 70 --aparar-abaixo --z-aparar-abaixo 0.12 --aparar-mais 0.2 0.2 \
        --aparar-frente-abaixo 0.36
    RODAS=aro_liga14,pneu_p185_70, ... python -I ferramentas/previa_carro.py -- ...      (prévias; liga 14 sem calota)

O comprimento passado (4,47) é o da lataria do autor: os para-choques cromados passam dela e o carro inteiro fica com os 4,60 m da
ficha (4,60 x 1,81 x 1,38 m, entre-eixos 2,65 m, roda 32 cm). As proporções do autor já batiam com a ficha: a altura quase não estica.

- **Preparo:** fora o interior do autor (bancos, forros, painel, volante, botões e maçanetas de dentro) e um retalho de 2 triângulos no
  teto. O teto de vinil preto vai para `chassi` (o cupê da referência tem o teto escuro); o cromo de verdade (para-choques, frisos,
  molduras, retrovisores, maçanetas) para `cromo`; os faróis redondos para `lente_farol`, piscas `luz_ambar`, lanternas `luz_vermelha`.
  Com as luzes já no material do jogo, o `detalhes_na_casca.py` não refaz nada: só as placas 40 x 13 (a da frente pendurada sob o
  para-choque, a de trás no painel cromado entre as lanternas) e a antena no para-lama.
- **Corte:** portas, capô e tampa por `take: "ilha"` (o painel solto do autor vai inteiro, com a moldura cromada da janela na porta e
  a fresta na do modelo); o vidro da porta e o quebra-vento vão com a porta, o de quarta fica na carroceria. O pneu é só pelo material
  `pneu` (com a caixa de raio ele levava o friso cromado do arco e um anel da caixa de roda).
- **`rodas_kit.py`:** pneu 185/70 R14 (30,7 cm de raio), o do cupê da referência, gerado com `--so p185_70`; os outros itens não foram
  regravados.
- **`carro_completo.py`, opções novas (sem elas, nada muda):** `--aparar-frente-abaixo Z` corta no plano z o vão do motor à frente da
  roda dianteira e tira o que fica embaixo (a chapa da frente acaba a 34 cm e o para-lama interno e a travessa apareciam como dois
  postes laranja sob o para-choque; a face alta do para-lama interno tinha o centro acima de z, por isso o corte no plano);
  `--z-aparar-abaixo Z` dá a altura do `--aparar-abaixo` (padrão: o topo da saia; aqui 12 cm: a chapa acaba no friso cromado a 30 cm e
  o forro e a soleira da porta passavam embaixo dela). E a peça que um aparo esvazia inteira sai do kit (as longarinas ficavam à frente
  da chapa baixa; o bake de oclusão parava com "No faces found").
- **Gol inalterado (conferido em 30/10):** o kit do Gol com o `carro_completo.py` novo sai com as mesmas 79 peças e os mesmos 241.941 /
  72.499 triângulos; as opções novas só agem quando passadas, e o kit do Gol não tem peça vazia.
- **Saída (30/10):** `veiculos/sketchfab/quebravel/gaucho-v8/` (31 peças, ~393 mil triângulos, 107 mil deles nos pneus do autor, que o
  jogo troca pelas rodas de kit) e `veiculos/sketchfab/completo/gaucho-v8/` (kit época 70, V8 longitudinal e tração traseira pela
  entrada `gaucho-v8` do `carro_completo_dados.json`, 77 peças, LOD0 ~208 mil). Prévias com o HDRI da rua em
  `veiculos/sketchfab/previas/gaucho-v8/`.
- **Falta / conhecido:** embaixo da porta, de perto e de baixo, ainda aparece a borda escura do assoalho e da saia do kit (lê como
  o fundo do carro); o para-lama dianteiro sai pela face lateral e a borda de cima dele fica serrilhada quando ele solta; o aparo do
  vão do motor fatiou dois reservatórios e a bateria (só se vê com o capô aberto).

## Pampeiro do Sketchfab: hatch redondo de 5 portas (30/10/2026)

O Pampeiro (nº 4 da ficha do Speed Tchê) deixou o Meshy. O primeiro candidato, o mais parecido com a referência, era um hatch de
5 portas de ~5 mil triângulos, todo em casca dupla e com a textura de foto: a cadeia do Gol deixou a carroceria redonda facetada, os
faróis em zigue-zague e as caixas de roda serrilhadas, e nem a subdivisão Catmull-Clark resolveu (ondulava a lateral e serrilhava a
borda dos vidros). Ficou a reserva, com o "siga" do Felipe: o **"Hatchback" de MaG80** (Sketchfab, CC BY 4.0, crédito em
`CREDITOS.md`), hatch redondo de 5 portas de marca fictícia, um objeto por material, faróis e lanternas modelados, id
`hatch-redondo-5p` no acervo. A cadeia:

    python -I ferramentas/sketchfab_preparar.py -- <scene.gltf do download> <prep>/hatch-redondo-5p.glb x 3.835 1.43 0.06 30 0 0 1 \
        --juntar veiculos/sketchfab/quebravel/hatch-redondo-5p/hatch-redondo-5p_juntar.json
    python -I ferramentas/carro_quebravel.py -- --entrada <prep>/hatch-redondo-5p.glb --out <corte> --id hatch-redondo-5p --portas 4 \
        --sem-rotulos --manter-normais --mapa veiculos/sketchfab/quebravel/hatch-redondo-5p/hatch-redondo-5p_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/hatch-redondo-5p.glb <corte>/hatch-redondo-5p.glb
    python -I ferramentas/detalhes_na_casca.py -- <corte>/hatch-redondo-5p.glb <corte>/hatch-redondo-5p.glb --mapa <o mapa> \
        --manter-luzes --manter-grade --manter-retrovisores --sem-macaneta --placa-nova --z-placa 0.43 --z-placa-tras 0.66 \
        --antena-teto -0.9 --sem-quebra-vento --sem-sinaleira --sem-face-para-choque --sem-arco-redondo --para-choque-pintado \
        --z-friso 0.52 --sem-faixa
    python -I ferramentas/assar_desgaste.py -- <corte>/hatch-redondo-5p.glb <corte>/hatch-redondo-5p.glb --tamanho 2048 --amostras 32
    python -I ferramentas/carro_completo.py -- --corte <corte> --id hatch-redondo-5p --out <kit>

- **`sketchfab_preparar.py`:** a caixa de `fora_caixas` do `--juntar` aceita um 7º elemento, o material do arquivo: só as ilhas dele
  saem (os bancos e o painel de plástico ficam na mesma caixa que o para-brisa). O JSON tira a capa de vidro dos faróis e das
  lanternas (`LightGlass: fora`): com ela, o `--manter-luzes` fazia da capa uma lente lisa que escondia as lâmpadas redondas; sem
  ela, os refletores aparecem. Do primeiro candidato ficaram opções que servem a outros modelos: grupos com "+" no 3º argumento
  (junta objetos), `SOLDAR=`, `VIDRO_TODO=1` e `TIRAR_VERSO=1` (tira a chapa de dentro colada na de fora, a menos de 3 mm). A
  `borracha_vidro.py` trata o vidro em placa fechada (sem borda aberta: usa as faces viradas para fora).
- **Mapa:** o modelo não tem frestas de porta; as portas saem dos pilares, das maçanetas e das janelas (vistas ortográficas com grade).
  A meia-largura é a da lateral (0,845 m), não a dos retrovisores: com 0,955 os batentes e a soleira do kit saíam para fora.
  Faróis e lanternas saem pelo material `luz` do modelo (`take: "material"`, a caixa só escolhe o lado): com a caixa pegando faces,
  a chapa pintada em volta da lente ia para a peça do farol, ficava fora do atlas da textura e saía como um retângulo branco.
- **Kit (`carro_completo_dados.json`, `hatch-redondo-5p`):** as opções de aparar das outras sessões (por vértice, desde a saia, capô
  pelas pontas, cofre do motor, fundo do farol rente), a saia em 0,27 m e a soleira preta (`soleira_preta`, a do Sagui: pintada,
  a caixa da soleira lia como uma tira clara sob as portas e uma aba atrás do arco da frente); sem elas a travessa e os para-lamas internos passavam o
  capô baixo da frente, as colunas do vão passavam o teto e a soleira aparecia clara. A caixa da lanterna no mapa vai só até |y| 0,76:
  a caixa do porta-malas atrás dela saía pela coluna, como uma aleta preta.
- **Saída:** `veiculos/sketchfab/quebravel/hatch-redondo-5p/` (34 peças, ~245 mil triângulos; 3,835 x 1,69 x 1,43 m, entre-eixos
  2,411 m, roda 30,1 cm) e `completo/hatch-redondo-5p/` (kit época 2000, 93 peças). Prévias em `veiculos/sketchfab/previas/hatch-redondo-5p/`
  (4 vistas, detalhes, 6 cores e os 5 acabamentos). A cadeia de conferência do Detonauto (`make_crush_channels.py`,
  `kit_to_detonauto.py`, `glb_texturas.py`, `kit_completo_to_detonauto.py`) passa: 19 peças e a roda, 11 malhas do kit.
- **Fica para decidir:** o carro é um hatch redondo genérico, não o desenho da referência (farol "garra" alongado); a semelhança é de
  arquétipo. A volta para algo mais próximo seria outro modelo ou o Meshy, com o Felipe.

## Barão do Sketchfab: casca de impressão completada (30/10/2026)

O Barão (nº 5 da ficha, sedã) passou do Meshy a um modelo feito por gente, escolhido pelo Felipe entre 5 candidatos ("siga" na
recomendação): **o sedã de FreshCanidae1571 (Sketchfab, CC BY 4.0; o título do autor está no crédito)**,
`veiculos/sketchfab/barao-freshcanidae__0383ac51df544ef5ab97559f7a97a811.glb`. É o único com a forma da referência (entre-eixos
2,54 m e altura 1,41 m medidos batem), mas é um STL de impressão: uma malha só, lataria maciça de 3 cm, janelas e caixas de roda
furadas, sem vidro, roda, interior, material nem UV. O resto dos candidatos: um muito tosco, um genérico de outro desenho, uma perua
e um caricato. O do Meshy (`meshy-conta/barao__01a16960.glb`) fica no acervo.

    python -I ferramentas/casca_impressao.py -- --entrada <scene.gltf> --out <tmp>/barao_casca.glb --comp 4.39
    VIDRO_TODO=1 python -I ferramentas/sketchfab_preparar.py -- <tmp>/barao_casca.glb <tmp>/barao.glb "carroceria,vidros,rodas" \
        4.39 1.415 0.06 30 0 --sem-pca --meio-pela-caixa --soldar 0.0001 --manter-materiais
    python -I ferramentas/decimar.py -- <tmp>/barao.glb <tmp>/barao_red.glb 130000
    python -I ferramentas/carro_quebravel.py -- --entrada <tmp>/barao_red.glb --out <corte> --id barao --portas 4 --sem-rotulos \
        --manter-normais --mapa veiculos/sketchfab/quebravel/barao/barao_mapa.json --sem-fbx
    python -I ferramentas/borracha_vidro.py -- <corte>/barao.glb <corte>/barao.glb --dona glass_rear=body
    python -I ferramentas/detalhes_na_casca.py -- <corte>/barao.glb <corte>/barao.glb --mapa veiculos/sketchfab/quebravel/barao/barao_mapa.json \
        --sem-quebra-vento --sem-sinaleira --sem-face-para-choque --manter-chapa-dos-vidros --para-choque-pintado --sem-macaneta \
        --sem-retrovisor --z-friso 0.465 --z-faixa 0.47 --placa-nova --z-placa 0.30 --z-placa-tras 0.705 \
        --limpadores 0.25,0.55,-0.32,0.52 --sem-arco-redondo --luz-na-casca --luz-reta 0.02 --faixas-lanterna-y 0.10,0.22 \
        --friso-tampa 0.905,0.30 --manter-grade --grade-preta
    python -I ferramentas/assar_desgaste.py -- <corte>/barao.glb <corte>/barao.glb --tamanho 2048 --amostras 32 --uv-smart
    python -I ferramentas/carro_completo.py -- --corte <corte> --id barao --out <kit> --aparar-mais 0.55 0.6

- **Casca:** `casca_impressao.py` (seção acima): vidros por raios (3 por lado, para-brisa e traseiro), rodas liga 14 com 185/60 do
  kit, assoalho, só a pele de fora e a parede da caixa de roda em `chassi`.
- **Mapa à mão** pelas emendas da própria casca (resíduo do campo de profundidade de lado, de frente e de trás): portas de 0,83 a
  -0,21 e a -0,98 m (a de trás para no arco: o forro do kit é um retângulo e entrava na caixa de roda), cintura 0,92 m, saia 0,31 m;
  vidros e luzes com `papel` (`glass_door`, `headlight`, `taillight`: sem ele o corte não trocava o material), `manter_abas` nos
  vidros das portas de trás (o fixo de quarta vai com a porta); `grille` é a entrada de ar de baixo, em plástico preto.
- **`detalhes_na_casca.py`:** faróis e lanternas com `--luz-na-casca` (a lente segue a chapa; os faróis do autor são recuados nos
  cantos) e `--luz-reta` (a borda da peça é a do corte, em serrote: a lente fica num retângulo cortado por planos dentro da caixa,
  com moldura de 8 mm, e a sobra volta a pintura; as caixas do mapa crescem 2 cm); lanterna quase toda vermelha com a ré e a seta por
  dentro (`--faixas-lanterna-y`); friso cromado (`cromo`, o `MI_DNCromoCoupe` do jogo) de lado a lado na tampa, entre as lanternas
  (`--friso-tampa`); o friso lateral vai também nas portas de trás (antes só olhava as da frente). A grade de cima fica a do autor
  (as fendas); a reconstruída em caixa deixava blocos acima do para-choque. A `--luz-na-casca` tinha saído do arquivo num commit
  do Pampeiro (a função e a chamada sumiram sem menção): voltou.
- **Kit:** `fundo_farol_rente` e `x_radiador` 1,82 (a travessa do painel em `x_frente - 0,20` furava a lente do farol) e
  `--aparar-mais 0.55 0.6` (o carpete do porta-malas saía pelos cantos da traseira).
- **O Gol não muda (conferido em 30/10):** corte e detalhes do Gol com o código de `main` e com o daqui dão as mesmas 32 peças a 0 mm.
- **Saída (30/10):** `veiculos/sketchfab/quebravel/barao/` (38 peças, ~320 mil triângulos, 4,39 x 2,00 com retrovisores x 1,415 m,
  entre-eixos 2,539 m, roda 28,9 cm) e `veiculos/sketchfab/completo/barao/` (kit época 2000 de sedã, 93 peças). Prévias em
  `veiculos/sketchfab/previas/barao/`, com o HDRI da rua e as rodas do kit.
- **Comparado com fotos reais do sedã da referência:** silhueta, porta-malas alto, faróis finos com as fendas da grade no meio,
  entrada de ar preta embaixo da placa, faixa preta nos para-choques e friso lateral fino batem; a lanterna real é redonda nos
  cantos, a daqui é um retângulo na própria chapa com o friso cromado entre elas (o traço próprio da ficha).
- **Defeitos conhecidos:** a chapa do autor tem ondas leves na lateral traseira (de perto, com sol baixo); o vidro fixo de quarta não
  tem borracha; o retrovisor é o do autor, sem espelho.
- **Táxi (30/10/2026):** `taxi_do_corte.py` faz o táxi de tráfego do corte: malha estática branca com a textura de desgaste,
  vidros escuros opacos, caixa de teto lisa sem texto, ~90 mil triângulos (o do Meshy tinha ~79 mil),
  `veiculos/sketchfab/taxi-barao__0383ac51df544ef5ab97559f7a97a811.glb`; prévia em `previas/barao/barao-taxi.jpg`.
- **Beira dos arcos, saia e fundo (30/10):** a borda virada do alargador antigo tinha faces pretas que, achatadas, apareciam em
  serrote acima do arco: na beira do arco, na pele de fora, a chapa vira pintada. A saia sob os para-choques (`carro_completo.py`) tem
  7,5 cm em vez de descer até o piso (pendia como um queixo preto), e o que é pintura do kit abaixo dela, até 40 cm da frente e de
  trás (travessa, para-lama interno), vira a graxa escura do fundo: aparecia vermelho sob o para-choque.
