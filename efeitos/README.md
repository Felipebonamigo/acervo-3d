# Efeitos em flipbook (fogo e fumaça)

Biblioteca própria do estúdio de flipbooks de fogo e fumaça para partículas (Niagara no Unreal),
feita por simulação física de gás (Mantaflow) e renderizada em Cycles, tudo pelo módulo `bpy` do
Blender, sem janela. Serve ao Detonauto (carro pegando fogo, fumaça preta de motor, vapor de
radiador, explosão, poeira de batida), ao AO VIVO (incêndio urbano) e ao TDFende e ao Age of Earth
(fogo e fumaça de cerco).

**Licença:** conteúdo próprio do estúdio. Nada de IA, nada de asset ou textura de terceiros: a
imagem sai inteira da simulação e do render feitos pela ferramenta `ferramentas/flipbook_fluido.py`.
Pode ser usado em qualquer jogo do estúdio e redistribuído junto com ele. `gerado_por_ia = não`
(não entra na declaração de IA da Steam).

## Presets

| Pasta | O que é | Quadro (m) | Loop | fps |
| --- | --- | --- | --- | --- |
| `fogo_carro/` | Chamas de 1,5 a 2 m saindo do vão do motor (10 focos que pulsam), fuligem preta por cima | 2,2 | sim | 24 |
| `fumaca_preta/` | Coluna de fumaça preta densa de motor ou pneu, ~4 m, pendendo com vento leve | 4,4 | sim | 18 |
| `fumaca_branca/` | Vapor branco de radiador furado, jato curto que se desfaz | 1,6 | sim | 24 |
| `explosao/` | **RASCUNHO, não aprovado (24/10/2026):** bola de fogo de ~3 m (7 bolsões de combustível) que se apaga rápido e vira fumaça escura; a silhueta ainda é um ovo e a fumaça vira um bloco que encosta nas laterais, em vez de subir em cogumelo | 4,6 | não | 24 |
| `poeira/` | Nuvem baixa de poeira de impacto que cresce em cúpula e assenta | 2,6 | não | 24 |

Cada pasta tem:

- `<preset>_atlas.png`: atlas 8 x 8 quadros; 4096 x 4096 com quadros de 512 px no `fogo_carro` e na
  `explosao` (são vistos de perto), 2048 x 2048 com quadros de 256 px nos outros (`lado_quadro_px` no
  JSON), RGBA com **alfa reto** (não
  pré-multiplicado) e cor em sRGB. Ordem: da esquerda para a direita, de cima para baixo (a mesma do
  SubUV do Unreal). Nos presets com fogo o próprio RGBA já traz a chama (o alfa cobre a chama), então
  ele funciona sozinho num material translúcido.
- `<preset>_emissao.png` (só `fogo_carro` e `explosao`): a emissão da chama em RGB sobre preto, no
  mesmo arranjo 8 x 8, para somar no Emissive (ou num segundo sprite aditivo) com o brilho que a cena
  pedir.
- `<preset>_6way_a.png` e `<preset>_6way_b.png` (só `fumaca_preta`, `fumaca_branca` e `explosao`):
  luz de 6 direções, ver abaixo.
- `<preset>.json`: quadros, linhas, colunas, `fps_sugerido`, `loop`, `escala_quadro_m` (lado do
  quadro em metros: é o tamanho do sprite no mundo), `base_do_quadro_m` (onde está o chão em relação à
  borda de baixo do quadro), parâmetros da simulação e tempos medidos.
- `<preset>_folha.png` (folha de contato 1024 px sobre um céu de conferência) e `<preset>.gif`, só
  para olhar. Não vão para o jogo.

Os quadros têm o alfa apagado suavemente nos 10 % de cima e dos lados, para a fumaça que sai do
enquadramento não terminar numa linha reta. Embaixo não: o emissor fica rente à borda de baixo.
A câmera é ortográfica e de frente (a poeira tem 10° de elevação), com sol de cima e da esquerda e
contraluz fraca da direita; por isso a fumaça tem um lado claro e sombra própria.

Os presets com loop emendam o fim no começo por um cruzamento de 16 quadros (a simulação roda mais
16 quadros e o fim é misturado com eles). A explosão e a poeira não fazem loop e apagam o alfa nos
últimos quadros.

## Luz de 6 direções (six-way lightmap)

Fumaça com a luz "assada" no atlas de cor só fica certa com a luz da captura (sol de cima e da
esquerda). Para a fumaça receber a luz da cena do jogo, `fumaca_preta`, `fumaca_branca` e `explosao`
trazem também o par de atlas de 6 direções, no padrão usado pelo VFX Graph do Unity e pelos materiais
"six-way" do Niagara:

| Arquivo | R | G | B | A |
| --- | --- | --- | --- | --- |
| `<preset>_6way_a.png` | luz vinda da direita (+X) | de cima (+Z) | de trás (do lado oposto à câmera) | opacidade |
| `<preset>_6way_b.png` | luz vinda da esquerda (−X) | de baixo (−Z) | da frente (do lado da câmera) | emissão do fogo (explosão) ou 1 |

Como foi feito: no mesmo render de cada quadro há 6 sóis brancos de força igual (`LUZ_6`), um por
direção, cada um num grupo de luz do Cycles; cada grupo sai como passe próprio (com denoise). O valor
gravado é a luminância desse passe dividida pela opacidade (luz por unidade de cobertura), normalizada
pelo percentil 99,5 de todos os quadros (`arquivos.6way_escala` no JSON). **Valores lineares**: no
Unreal importe as duas texturas com **sRGB desligado** (compressão `Masks` ou `Default` sem sRGB).

No material (Unlit, Translucent): para cada luz da cena (ou só a direcional principal mais o céu),
com a direção da luz em espaço da partícula `L = (lx, ly, lz)` (x para a direita do sprite, y para
cima, z saindo da tela para a câmera):

```
luz = A.r*max(lx,0) + B.r*max(-lx,0) + A.g*max(ly,0) + B.g*max(-ly,0)
    + A.b*max(-lz,0) + B.b*max(lz,0)
cor = luz * CorDaLuz * CorDaFumaça + Ambiente * média(A.rgb, B.rgb) * CorDaFumaça
opacidade = A.a * Particle Color.a
```

Os dois atlas usam o mesmo SubUV 8 x 8 do atlas de cor. Na explosão, some a emissão (`B.a` ou o
`_emissao.png`, que é colorido) no Emissive.

## Volume em OpenVDB (para Sparse Volume Texture)

`--vdb <pasta>` guarda a simulação por quadro em OpenVDB: `<preset>_alta_NNN.vdb` (densidade e chama
na resolução alta, `density_noise`, `flame_noise`) e `<preset>_base_NNN.vdb` (resolução base, com
`heat`, a temperatura, `flame`, `fuel`, `density` e a velocidade), em meia precisão, mais
`<preset>_vdb.json` com o tamanho do domínio em metros, o canto mínimo, o tamanho do voxel e o fps.
São centenas de MB por preset: ficam **fora do git** (regra dos 50 MB). Na última geração ficaram em
a pasta de rascunho da sessão que gerou (`fogo_carro`: 64 quadros, ~4,1 GB; `fumaca_preta`: 64 quadros, ~2,4 GB), não no repositório; regenere com `--vdb`. Os VDB não têm o cruzamento do loop do atlas.

## Como usar no Niagara

1. Importe o `<preset>_atlas.png` como textura: compressão `Default` (BC7 se quiser o alfa limpo,
   `UserInterface2D` não), sRGB ligado, `Mip Gen Settings` = `FromTextureGroup` ou `NoMipmaps` se o
   sprite ficar sempre grande na tela. O `_emissao.png` também é sRGB, sem alfa.
2. Material: Domain `Surface`, Blend Mode `Translucent`, Shading Model `Unlit` (ou `Default Lit`
   com `Translucency Lighting Mode` volumétrico, para a fumaça receber a luz da cena). Use o nó
   **Particle SubUV** (ou `Flipbook`) com 8 x 8 ligado à textura; Base/Emissive Color = RGB vezes
   `Particle Color`, Opacity = A vezes o alfa da `Particle Color`. Para o fogo, some o
   `_emissao.png` (amostrado com o mesmo SubUV) no Emissive vezes um parâmetro de brilho (comece
   em 4 a 10); se preferir aditivo puro, faça um segundo material `Additive` só com a emissão.
   Ligue `Soft Particle` (Depth Fade) para não cortar no chão e nas paredes.
3. Emissor do Niagara: Sprite Renderer com `Sub UV` → `Sub Image Size` = (8, 8) e
   `Sub UV Blending Enabled` ligado (mistura um quadro no outro). No módulo `Sub UV Animation`
   escolha `Linear` com `Start Frame` 0 e `End Frame` 63; para os loops use `Play Rate` em
   quadros por segundo (`fps_sugerido` do JSON) e `Infinite Loop`; para explosão e poeira use
   `Linear` ao longo da vida da partícula (vida = 64 / `fps_sugerido` segundos, ~2,7 s). Ou,
   à mão, ponha `Particles.SubImageIndex` na curva que quiser.
4. Tamanho: `Sprite Size` = `escala_quadro_m` x 100 (centímetros). O emissor da simulação fica
   perto da borda de baixo do quadro: use `Pivot Offset` (0,5; 1,0 menos um pouco) ou desloque a
   partícula para cima metade do tamanho, para a chama nascer no capô e não no meio dele.
5. Varie: 2 a 4 sprites por efeito com rotação inicial aleatória pequena (±10°, mais que isso a
   coluna entorta), tamanho ±20 % e quadro inicial aleatório nos loops (`Random Start Frame`).

## Como regenerar

Precisa só do Python com o módulo `bpy` 5.2 (o pacote `bpy` do pip; sem Blender instalado, só CPU).

```sh
python -I ferramentas/flipbook_fluido.py -- --preset todos --saida efeitos --amostras 160
python -I ferramentas/flipbook_fluido.py -- --preset fogo_carro --saida efeitos/fogo_carro --amostras 160
```

- `--previa --rapido --res 56`: só 8 quadros num domínio pequeno, em ~2 min, para acertar o visual
  (grava `<preset>_previa.png`).
- `--lado 512` muda o tamanho do quadro (atlas 4096); `--vdb <pasta>` grava os volumes OpenVDB.
- `--manter-cache` guarda o bake e a cena; depois `--so-render` refaz material, luz e render sobre o
  mesmo bake, e `--so-montar` remonta o atlas a partir dos EXR já renderizados.
- `--cache DIR` escolhe onde fica o bake (vários GB por preset na resolução final).
- Os presets ficam no dicionário `PRESETS` do script: domínio, emissor, flambagem, cor, luz,
  enquadramento, loop e fps.

A simulação é determinística na prática: mesmos parâmetros e mesma semente dão o mesmo bake (conferido
rodando duas vezes a prévia do fogo). O Mantaflow divide o trabalho em threads, então uma máquina
diferente pode mudar algum detalhe fino.

**Conserto necessário no `bpy` do pip:** nesse pacote as classes Python do Mantaflow nascem sem a
classe-base, e o domínio de gás falha com `AttributeError: 'LevelsetGrid' object has no attribute
'setConst'` (o processo morre logo depois). O script reconstrói a herança dessas classes por `ctypes`
antes de o Mantaflow rodar (`consertar_manta()`). Num Blender instalado normal isso não é preciso e
não atrapalha. Também é preciso `scene.render.compositor_device = 'CPU'`, senão o compositor tenta
abrir a `libEGL` e o processo morre.

## Tempos e tamanhos (23/10/2026, 4 núcleos, CPU)

Máquina de 4 núcleos dividida com outras sessões (carga de 10 a 35), então os tempos são altos e
variam; numa máquina livre caem bem.

| Preset | Domínio (base × ruído) | Quadros simulados | Simulação | Render | Atlas |
| --- | --- | --- | --- | --- | --- |
| `fogo_carro` | 128 × 2 | 120 | ~87 min | ~2 h (80 quadros, 512 px, 128 amostras) | 4096², ~29 MB + emissão ~7 MB |
| `fumaca_preta` | 112 × 2 | 190 | ~72 min | ~1 h 47 min (80 quadros, 6 direções) | 2048², ~7 MB + 6-way ~12 MB |
| `fumaca_branca` | 96 × 2 | 125 | ~17 min | ~1 h 55 min (80 quadros, 6 direções) | 2048², ~8 MB + 6-way ~14 MB |
| `explosao` | 72 × 3 | 66 | ~46 min | ~2 h 06 min (64 quadros, 512 px, 96 amostras, 6 direções) | 4096², ~17 MB + emissão ~1,6 MB + 6-way ~34 MB |
| `poeira` | 100 × 2 | 67 | ~8 min | ~10 min (64 quadros) | 2048², ~3 MB |

Teste inicial do Mantaflow no módulo `bpy`: domínio 48, 30 quadros, 13,9 s. Nenhum arquivo do acervo
passa de 30 MB (limite do repositório: 50 MB).

## O que ainda não está realista

- `explosao`: a fase de fogo ficou curta e com dobras de fuligem, mas a nuvem de fumaça depois cresce
  como uma bola grande e escura que ocupa quase o quadro todo, em vez de subir em cogumelo. Na grade
  fina a bola saía lisa; na grade grossa (72) com vorticidade alta ela tem lóbulos, mas exagera no
  volume de fumaça. Próximo passo: menos fuligem por chama (`fumaca_chama`), dissolver mais rápido e
  mais empuxo depois de apagar.
- `fogo_carro`: na resolução 128 as chamas sobem mais que 1,5 m e a fuligem sai pela borda de cima
  (esmaecida pela máscara). Para 1,5 m exatos: queima mais rápida ou quadro de 2,6 m.
- `fumaca_preta`: pende e rola, mas nos últimos quadros encosta na borda direita.
- `fumaca_branca`: corpo e sombra bons, mas lê mais como pluma de vapor alta do que como esguicho de
  radiador que se desfaz logo.
- `poeira`: cúpula de poeira plausível, mas lenta e de textura "peluda"; não tem o jato rasante do
  impacto nem 6 direções.
