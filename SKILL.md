---
name: video-editor
description: >
  Edita vídeos de screencast de programação (VS Code, Eclipse, terminal) com
  Python + FFmpeg. Converte 16:9 para 9:16 (vertical, Shorts/Reels/TikTok)
  com reenquadramento inteligente e pan/zoom animado, adiciona a câmera
  (facecam) com efeitos (card arredondado, círculo, chroma key), sincroniza e
  mixa o áudio das duas gravações. Use quando o usuário pedir para editar
  vídeo, converter para vertical/retrato, adicionar câmera/facecam, ou
  mencionar video editing, convert to 9:16, portrait, camera overlay.
---

# video-editor

Você edita screencasts de desenvolvimento de software. Os scripts em
`scripts/` fazem o trabalho mecânico (FFmpeg/OpenCV); **você** faz o trabalho
de direção: olhar os frames do vídeo e decidir qual região da tela merece o
foco em cada momento.

Requisitos: `ffmpeg`/`ffprobe` no PATH e `pip install -r requirements.txt`
(numpy, opencv-python-headless, pillow). Se algo faltar, o script avisa —
aponte o usuário para o README.

Trabalhe num diretório temporário para arquivos intermediários (frames,
plano de corte, vídeos parciais) e entregue só o vídeo final ao usuário.

## Fluxo A — Converter 16:9 em 9:16 (vertical)

### 1. Inspecionar os vídeos

```bash
python scripts/probe.py screen.mp4 [camera.mp4]
```

Anote resolução, fps, duração e se cada arquivo tem áudio.

### 2. Extrair frames para análise

```bash
python scripts/extract_frames.py screen.mp4 --out frames/ --interval 5
```

Gera JPEGs a cada 5 s (ajuste o intervalo: vídeos longos ou monótonos podem
usar 10–15 s) e um `manifest.json` com o timestamp de cada frame e a
resolução original. **Atenção**: os screenshots são reduzidos (largura padrão
1024 px) — as coordenadas do plano de corte devem estar na resolução
ORIGINAL do vídeo (`source_width`/`source_height` do manifest). Converta:
`coord_original = coord_no_screenshot * source_width / screenshot_width`.

### 3. Analisar os frames e montar o plano de corte

Leia os frames com a ferramenta Read (em lotes). Para cada momento,
identifique a região mais relevante da tela:

- o código sendo editado/digitado (cursor, linha destacada, trecho novo);
- o terminal quando há output novo ou um comando rodando;
- diálogos, popups, autocomplete, painéis de debug em uso;
- o navegador/app sendo demonstrado.

Escreva `plan.json`:

```json
{
  "keyframes": [
    {"time": 0.0,  "region": [180, 150, 900, 760], "label": "editor - função main", "anchor": "left"},
    {"time": 25.0, "region": [0, 620, 1100, 440],  "label": "terminal - build", "anchor": "left"}
  ]
}
```

`region` é `[x, y, largura, altura]` em pixels da resolução original. O
renderizador expande cada região para cobrir exatamente o aspecto 9:16
(nunca deixa barras), então marque o CONTEÚDO relevante e deixe a expansão
por conta dele. O `anchor` opcional (`left`/`right`/`top`/`bottom`; padrão
centro) diz qual lado da região preservar quando o corte final não couber
tudo.

Regras de direção:

- **A janela é uma coluna estreita**: um corte 9:16 em altura total de um
  vídeo 16:9 mostra no máximo `altura × 9/16` pixels de largura — em
  1920×1080, ~607 px (≈32% da largura da tela). Regiões mais largas que
  isso serão cortadas nas laterais; use `"anchor": "left"` em código e
  terminal para o começo das linhas nunca sumir.
- **Legibilidade**: quanto mais estreita a região, maior o zoom. Para
  código, entre ~20% e 32% da largura da tela costuma ficar legível num
  celular. Zoom demais corta o contexto; de menos, ninguém lê.
- **Estabilidade**: não troque de região a menos de ~8 s da anterior, a não
  ser que o foco claramente mudou. Se dois frames consecutivos mostram a
  mesma cena, não crie keyframe novo.
- **Cobertura total**: em cenas sem foco claro (slide, desktop, IDE inteira
  relevante), use uma região alta e centrada — o quadro 9:16 sempre será
  preenchido por completo.
- O primeiro keyframe deve ter `time: 0.0`.

### 4. Renderizar

```bash
python scripts/render_vertical.py screen.mp4 --plan plan.json --out vertical.mp4
```

Sai em 1080×1920 com transições suaves de 0.8 s (`--transition` para
ajustar). O áudio do vídeo original é mantido. É a etapa lenta do fluxo
(re-encoda frame a frame); avise o usuário em vídeos longos.

### 5. Conferir o resultado

Extraia 3–4 frames do vídeo final (início, durante uma transição, fim) com
`ffmpeg -ss T -i vertical.mp4 -frames:v 1 check.jpg`, olhe-os e ajuste o
plano se algum enquadramento ficou ruim. Ao entregar, resuma para o usuário
as decisões de enquadramento com timestamps, para ele poder pedir ajustes.

## Fluxo B — Acomodar a câmera no vídeo

Se o usuário enviou tela + câmera:

### 1. Sincronizar

Se o usuário não informou o offset entre as gravações:

```bash
python scripts/sync_offset.py screen.mp4 camera.mp4
```

Usa correlação de áudio. Confira o `confidence` (< 0.2 = duvidoso — pergunte
ao usuário ou compare eventos visuais). Offset positivo = câmera começou a
gravar antes.

### 2. Compor a câmera

```bash
python scripts/compose_camera.py base.mp4 camera.mp4 --out composed.mp4 \
    --offset OFFSET [--shape rounded|circle] [--position bottomright] [--size 0.30]
```

`base.mp4` é o vídeo de tela original (16:9) ou o `vertical.mp4` do Fluxo A.
Padrão: card retangular arredondado com borda branca e sombra, canto
inferior direito, 30% da largura.

Recomendações:

- **Saída 16:9**: `--size 0.22` a `0.30`, canto que não tampe código/terminal
  (olhe os frames antes de escolher `--position`).
- **Saída 9:16**: `--size 0.42` a `0.55`, `--position bottomcenter` e
  `--aspect 4:3` ou `1:1` funcionam bem; no Fluxo A, planeje regiões que
  deixem a área da câmera livre de conteúdo importante.
- Fundo verde: `--chroma-key 0x00FF00` (sobrepõe a pessoa recortada, sem card).

### 3. Mixar o áudio

```bash
python scripts/mix_audio.py composed.mp4 camera.mp4 --out final.mp4 --offset OFFSET
```

Padrão: mixa a trilha da base com o microfone da câmera (`--mode camera` ou
`base` para usar só uma; `--base-vol`/`--cam-vol` para balancear). O mesmo
offset da composição.

## Fluxo completo (tela + câmera → Shorts)

probe → extract_frames → analisar frames → plan.json → render_vertical →
sync_offset → compose_camera (sobre o vertical.mp4) → mix_audio → conferir
frames do resultado → entregar com resumo das decisões.

## Solução de problemas

- `ffmpeg not found`: instalar conforme o README (apt no Linux, winget no
  Windows) e reabrir o terminal.
- Render lento: `--preset fast` ou `--crf 21` no render_vertical; o tempo
  cresce linearmente com a duração.
- Texto ilegível no celular: regiões menores (mais zoom) no plan.json.
- Câmera fora de sincronia: refaça o sync_offset com `--window` maior ou
  ajuste o offset manualmente (positivo corta o início da câmera).
