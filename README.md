# skill-video-editor

Skill do [Claude Code](https://claude.com/claude-code) para editar screencasts
de programação (VS Code, Eclipse ADT, terminal...) usando Python + FFmpeg.

O que ela faz:

- **16:9 → 9:16 (vertical)**: extrai screenshots do vídeo, o Claude analisa as
  imagens e identifica a região mais relevante da tela em cada momento (código
  sendo editado, terminal com output, diálogo em foco), e um script renderiza o
  vídeo retrato com pan/zoom animado entre as regiões — sempre preenchendo o
  quadro inteiro, sem barras, para ficar legível no celular (Shorts/Reels/TikTok).
- **Câmera (facecam) com efeitos**: sobrepõe o vídeo da câmera no vídeo final
  como um card com cantos arredondados, borda e sombra (ou círculo, ou chroma
  key), na posição e tamanho que você quiser.
- **Sincronia e áudio**: detecta automaticamente o offset entre a gravação da
  tela e a da câmera (por correlação de áudio) e mixa as duas trilhas.
- **Remoção de silêncios (opcional)**: detecta pausas na fala e corta os
  trechos mortos do vídeo final antes da entrega, mantendo um respiro
  configurável em volta de cada fala — sempre mostrando antes quanto tempo
  seria removido, para você aprovar.

## Requisitos do sistema

Em qualquer sistema operacional:

| Dependência | Versão | Para quê |
|---|---|---|
| Python | 3.10 ou superior | executa os scripts |
| FFmpeg (com ffprobe) | 5.0 ou superior | decodificação, encodificação e filtros |
| Pacotes Python | `requirements.txt` | numpy, opencv-python-headless, pillow |

### Linux

Debian/Ubuntu:

```bash
sudo apt update
sudo apt install ffmpeg python3 python3-pip
pip3 install -r requirements.txt
```

Fedora: `sudo dnf install ffmpeg python3 python3-pip` (habilite o RPM Fusion se
o ffmpeg não for encontrado). Arch: `sudo pacman -S ffmpeg python python-pip`.

### Windows

1. **Python 3.10+**: instale de [python.org/downloads](https://www.python.org/downloads/)
   e marque **"Add Python to PATH"** no instalador (ou instale pela Microsoft
   Store).
2. **FFmpeg** (escolha uma opção):
   - `winget install Gyan.FFmpeg` (recomendado; já configura o PATH), ou
   - `choco install ffmpeg` (Chocolatey), ou `scoop install ffmpeg` (Scoop), ou
   - baixe de [gyan.dev/ffmpeg/builds](https://www.gyan.dev/ffmpeg/builds/),
     extraia e adicione a pasta `bin` ao PATH manualmente.
3. **Pacotes Python**: `pip install -r requirements.txt`
4. Feche e reabra o terminal, e confirme que tudo funciona:

```powershell
python --version
ffmpeg -version
ffprobe -version
```

### Aceleração por GPU (opcional)

Os scripts que re-encodam vídeo (`render_vertical.py`, `compose_camera.py`,
`cut_silence.py`) aceitam `--encoder` para usar a GPU:

| Valor | Encoder usado |
|---|---|
| `cpu` (padrão) | libx264 — melhor qualidade por tamanho para texto de tela |
| `amd` | AMF (`h264_amf`) no Windows, VAAPI (`h264_vaapi`) no Linux |
| `nvidia` | NVENC (`h264_nvenc`) |
| `intel` | Quick Sync (`h264_qsv`) ou VAAPI |
| `auto` | detecta e usa a primeira GPU que funcionar |

Se o encoder pedido não existir no seu FFmpeg ou o teste de hardware falhar,
o script avisa e continua na CPU — nunca quebra por falta de GPU.

Pré-requisitos para **AMD**:

- **Windows**: driver AMD Adrenalin instalado e um build completo do FFmpeg
  (o do `winget install Gyan.FFmpeg` já vem com `h264_amf`). Confirme com
  `ffmpeg -encoders | findstr amf`.
- **Linux**: driver Mesa com VA-API (`sudo apt install mesa-va-drivers
  vainfo`), seu usuário nos grupos `video` e `render`
  (`sudo usermod -aG video,render $USER`, relogue depois) e o dispositivo
  `/dev/dri/renderD128` presente. Confirme com `vainfo` e
  `ffmpeg -encoders | grep vaapi`.

Nota de qualidade: encoders de GPU são muito mais rápidos, mas para conteúdo
de tela (texto de código) o libx264 rende melhor qualidade no mesmo tamanho —
por isso a CPU continua sendo o padrão. Use GPU quando a velocidade importar
mais (vídeos longos, iterações de ajuste).

### Observações

- Reserve espaço em disco temporário (~o tamanho do vídeo de entrada) para os
  arquivos intermediários.
- Formatos de entrada: qualquer coisa que o FFmpeg leia (mp4, mkv, mov, webm...).
  A saída é MP4 (H.264 + AAC), pronta para upload.

## Instalação da skill

Copie (ou clone) este repositório para a pasta de skills pessoais do Claude Code:

```bash
# Linux/macOS
git clone https://github.com/carlosribeirodev/skill-video-editor.git \
    ~/.claude/skills/video-editor
```

```powershell
# Windows
git clone https://github.com/carlosribeirodev/skill-video-editor.git `
    $env:USERPROFILE\.claude\skills\video-editor
```

Pronto — em qualquer sessão do Claude Code, peça algo como:

> converte o video screen.mp4 para 9:16 e acomoda a camera do camera.mp4

e a skill é acionada automaticamente. Você também pode invocá-la com
`/video-editor`.

## Como funciona

```
screen.mp4 ──► probe.py ──► extract_frames.py ──► Claude analisa os frames
                                                        │
                                                   plan.json (regiões relevantes)
                                                        │
                                              render_vertical.py ──► vertical.mp4
camera.mp4 ──► sync_offset.py (offset) ──► compose_camera.py ──► mix_audio.py ──► final.mp4
                                                                                      │
                                                     cut_silence.py (opcional) ◄─────┘
```

A parte "inteligente" (decidir o que enquadrar) é feita pelo próprio Claude
olhando os frames; os scripts Python fazem o trabalho determinístico:

| Script | Função |
|---|---|
| `scripts/probe.py` | resolução, fps, duração e trilhas de áudio dos vídeos |
| `scripts/extract_frames.py` | screenshots a cada N segundos + manifest com timestamps |
| `scripts/render_vertical.py` | renderiza o 9:16 com pan/zoom suave a partir do plan.json |
| `scripts/compose_camera.py` | card da câmera (arredondado/círculo/chroma key) sobre o vídeo |
| `scripts/mix_audio.py` | mixa/seleciona o áudio das duas gravações |
| `scripts/sync_offset.py` | detecta o offset entre tela e câmera por correlação de áudio |
| `scripts/cut_silence.py` | remove silêncios/pausas do vídeo final (com modo de análise prévia) |

Todos os scripts têm `--help` e também podem ser usados manualmente, sem o
Claude.

## Licença

[MIT](LICENSE)
