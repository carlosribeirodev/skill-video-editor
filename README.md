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

### Observações

- O re-encode usa CPU (libx264); vídeos longos levam alguns minutos. Se tiver
  GPU NVIDIA, dá para pedir ao Claude para usar NVENC nas etapas só-FFmpeg.
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

Todos os scripts têm `--help` e também podem ser usados manualmente, sem o
Claude.

## Licença

[MIT](LICENSE)
