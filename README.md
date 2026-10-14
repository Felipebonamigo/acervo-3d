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
(bichos e torres em FBX) e `SpeedTche/art/` (carros). Repositório privado, sem LFS.

## Pastas

`<categoria>/<fonte>/<arquivo>`

| Categoria | O que tem |
| --- | --- |
| `animais/` | Bichos do TDFende (com animação), javalis e cervos do Age of Earth |
| `criaturas/` | As 19 criaturas míticas do Age of Earth |
| `personagens-e-unidades/` | Soldados gregos, aldeãs, Héracles, cerco |
| `edificios/` | Edifícios e maravilhas do Age of Earth; torres, fortaleza e acampamento do TDFende (`torres-tdfende/`) |
| `natureza/` | Árvores, arbustos, rochas, veios de ouro, tocos |
| `veiculos/` | Galeão, o carro Falcão do Kenney e os 13 moldes de carroceria do Speed Tchê |

| Fonte | Licença | Condição |
| --- | --- | --- |
| `meshy-galeria/` | CC0 | Nenhuma |
| `sketchfab/` | CC BY 4.0 | Crédito ao autor na tela de créditos de cada jogo |
| `meshy-conta/` | Gerado na conta do Felipe | No plano grátis vale CC BY 4.0 com crédito ao Meshy; no Pro (ativado em 03/10/2026 às 23h11) é do Felipe. Javali, tigre e 1ª Torre de Canhão: plano a confirmar |
| `kenney/` | CC0 | Nenhuma |
| `speed-tche-moldes/` | Própria | Nenhuma |

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
3. Licença aceita: CC0, CC BY 4.0 com crédito, gerado na conta do Meshy, próprio. Nunca NC, ND,
   "uso pessoal" ou origem não comprovada.
4. Nenhum arquivo acima de 50 MB (o GitHub recusa acima de 100 MB). Sem LFS, para não gastar a cota
   do Detonauto.
5. Ao levar um modelo para outro jogo, acrescente o jogo em `usado_em` e o crédito na tela de créditos
   dele (`CREDITOS.md`).
6. Commits em português, no imperativo.
