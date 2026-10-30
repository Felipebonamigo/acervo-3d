# Tropeiro (picape aventureira): pedido para a sessão local do PC (30/10/2026)

Texto pronto para o Felipe colar na sessão local do Claude no PC, que tem o Unreal e o compilador. A sessão da nuvem já fez o carro
no acervo e os dados, o C++ e os testes no Detonauto (no `main` dos dois). Falta o que só o PC faz.

---

Monte o carro novo **Tropeiro** (picape de cabine simples, versão aventureira, classe nova `picape`) no Detonauto e jogue com ele.
Siga `docs/pedido-pc-tropeiro-completo.md` do Detonauto:

1. Atualize os dois repositórios: `git -C ..\acervo-3d pull` e `git pull`.
2. Feche o editor e rode:
   ```powershell
   .\Tools\Unreal\montar-cuiabano-completo.ps1 -Uproject .\Detonauto.uproject -Id tropeiro -Modelo Tropeiro
   ```
   O C++ mudou: `FDNGarageClass::All()` ganhou `picape`, e os testes contam o Tropeiro e o Besouro. O conferidor não achou erro, mas
   é preciso compilar com o editor fechado. Se um teste de `Detonauto.Dados` ou `Detonauto.Garagem` falhar, mande a linha.
3. Confira as capturas em `docs/img/carro-completo/tropeiro/` com a tabela do pedido e com fotos da picape real de referência
   (rotina `aprovar-visual`). Compare também com as prévias do Blender em `acervo-3d/veiculos/sketchfab/previas/tropeiro/`.
4. Jogue:
   ```powershell
   .\Tools\Unreal\vehicle-probe.ps1 -Uproject .\Detonauto.uproject -Row tropeiro -Play -ExtraArgs '-DNWheelProbe','-DNModel=Tropeiro'
   ```
   Bata de frente, de lado e de ré. A física é um ponto de partida (1080 kg, centro de massa 12 cm, traseira 0,92).
5. Capturas no jogo, para o Felipe:
   - 3/4 da frente e 3/4 de trás, parado, e de lado;
   - close da frente (grade preta, faróis, faróis de milha, placa) e da traseira (lanternas em três faixas, placa no para-choque);
   - a caçamba de cima, com protetor, ganchos e santo-antônio;
   - a porta arrancada, para ver o vão e o forro;
   - a tampa da caçamba depois de uma batida de ré: ela solta inteira, porque não há dobradiça de baixo;
   - o carro amassado depois de uma batida forte.
6. Anote o desempenho com 40 de tráfego (rotina `fechar-lote`): a casca tem ~281 mil triângulos e o kit ~223 mil.

O que pode aparecer e onde mexer, no acervo:
- o santo-antônio atravessando o vidro de trás ou o teto: `carro_completo.py`, método `cacamba`;
- o alargador ou o protetor descolado da chapa: `detalhes_na_casca.py --protecoes`;
- a caçamba escura por dentro: o `nao_virar` do `tropeiro_grupos.json` (as paredes da caçamba olham para dentro de propósito);
- algo pintado sob o para-choque da frente: `fundo_cofre_visivel` do Tropeiro em `carro_completo_dados.json`.
