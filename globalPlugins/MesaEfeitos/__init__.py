import globalPluginHandler
import scriptHandler
import inputCore
import ui
import config
import gui
import wx
import os
import datetime
import threading
import queue
import winsound
import wave
import contextlib
import ctypes
from logHandler import log

# ---------------------------------------------------------------------------
# DIRETÓRIOS E CONFIGURAÇÕES
# ---------------------------------------------------------------------------
SONS_MESA_DIR = os.path.join(os.path.dirname(__file__), "sons")
MUSICAS_MESA_DIR = os.path.join(os.path.dirname(__file__), "musicas")
SONS_RELOGIO_DIR = os.path.join(os.path.dirname(__file__), "sounds")

# Unificando as especificações de configuração do NVDA
config.conf.spec["MesaEfeitos"] = {
    "pagina_atual": "integer(default=1)",
}

config.conf.spec["relogioSonoro"] = {
    "interval": "integer(default=0)",
    "timeFormat": "string(default='12h')",
    "voice": "string(default='default')",
    "chime": "string(default='Chime.wav')",
    "playChime": "boolean(default=True)",
    "playVoice": "boolean(default=True)"
}

# ---------------------------------------------------------------------------
# WORKERS DE SINAL / ÁUDIO (Gerenciamento de Threads Independentes)
# ---------------------------------------------------------------------------
class MesaSoundWorker(threading.Thread):
    """Trabalhador de som exclusivo para a Mesa de Efeitos"""
    def __init__(self, sounds_dir):
        super().__init__(daemon=True)
        self.sounds_dir = sounds_dir
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.start()

    def play(self, filename):
        self.stop_event.clear()
        self.queue.put(filename)

    def stop_playback(self):
        self.stop_event.set()
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except queue.Empty:
            pass
        winsound.PlaySound(None, winsound.SND_PURGE)

    def run(self):
        while True:
            filename = self.queue.get()
            if filename is None:
                break

            if self.stop_event.is_set():
                self.queue.task_done()
                continue

            full_path = os.path.join(self.sounds_dir, filename)
            if os.path.exists(full_path):
                try:
                    winsound.PlaySound(full_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                except Exception as e:
                    log.error(f"MesaEfeitos Erro: {e}")

            self.queue.task_done()


class RelogioSoundWorker(threading.Thread):
    """Trabalhador de som sequencial exclusivo para o Relógio Sonoro"""
    def __init__(self, sounds_dir):
        super().__init__(daemon=True)
        self.sounds_dir = sounds_dir
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.start()

    def play(self, sequence):
        self.stop_event.clear()
        for filename in sequence:
            self.queue.put(filename)

    def stop_playback(self):
        self.stop_event.set()
        try:
            while True:
                self.queue.get_nowait()
                self.queue.task_done()
        except queue.Empty:
            pass
        winsound.PlaySound(None, winsound.SND_PURGE)

    def run(self):
        while True:
            filename = self.queue.get()
            if filename is None:
                break
            
            if self.stop_event.is_set():
                self.queue.task_done()
                continue

            full_path = os.path.join(self.sounds_dir, filename)
            if os.path.exists(full_path):
                duration = 0
                try:
                    with contextlib.closing(wave.open(full_path, 'r')) as f:
                        frames = f.getnframes()
                        rate = f.getframerate()
                        duration = frames / float(rate)
                except Exception as e:
                    log.debug(f"Relógio Sonoro: Could not determine duration for {filename}, playing synchronously. Error: {e}")
                
                if duration > 0:
                    try:
                        winsound.PlaySound(full_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        if self.stop_event.wait(duration):
                            winsound.PlaySound(None, winsound.SND_PURGE)
                    except Exception as e:
                         log.error(f"Relógio Sonoro: Error playing async {filename}: {e}")
                else:
                    try:
                        winsound.PlaySound(full_path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                    except Exception as e:
                        log.error(f"Relógio Sonoro: Error playing sync {filename}: {e}")
            else:
                log.debug(f"Relógio Sonoro: File not found, skipping: {filename}")
            
            self.queue.task_done()

# ---------------------------------------------------------------------------
# INTERFACE VISUAL DO RELÓGIO SONORO
# ---------------------------------------------------------------------------
class RelogioSonoroSettingsPanel(gui.SettingsPanel):
    title = "Bem-vindos ao Relógio Sonoro - Português do Brasil"

    def makeSettings(self, settingsSizer):
        sHelper = gui.guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
        
        intervals = [
            ("Desativado", 0),
            ("5 minutos", 5),
            ("15 minutos", 15),
            ("30 minutos", 30),
            ("1 hora", 60)
        ]
        self.intervalChoices = [x[0] for x in intervals]
        self.intervalValues = [x[1] for x in intervals]
        
        currentInterval = config.conf["relogioSonoro"]["interval"]
        try:
            selection = self.intervalValues.index(currentInterval)
        except ValueError:
            selection = 0
            
        self.intervalList = sHelper.addLabeledControl(
            "Intervalo de anúncio automático:",
            wx.Choice,
            choices=self.intervalChoices
        )
        self.intervalList.SetSelection(selection)

        formats = [
            ("Formato de 12 horas", "12h"),
            ("Formato de 24 horas", "24h")
        ]
        self.formatChoices = [x[0] for x in formats]
        self.formatValues = [x[1] for x in formats]

        currentFormat = config.conf["relogioSonoro"]["timeFormat"]
        try:
            formatSelection = self.formatValues.index(currentFormat)
        except ValueError:
            formatSelection = 0

        self.formatList = sHelper.addLabeledControl(
            "Formato de hora:",
            wx.Choice,
            choices=self.formatChoices
        )
        self.formatList.SetSelection(formatSelection)

        base_dir = os.path.dirname(__file__)
        sounds_dir = os.path.join(base_dir, "sounds")
        voices_dir = os.path.join(sounds_dir, "voices")
        chimes_dir = os.path.join(sounds_dir, "chimes")

        self.voiceChoices = []
        if os.path.isdir(voices_dir):
            self.voiceChoices = [d for d in os.listdir(voices_dir) if os.path.isdir(os.path.join(voices_dir, d))]
        self.voiceChoices.sort()
        
        currentVoice = config.conf["relogioSonoro"]["voice"]
        if currentVoice not in self.voiceChoices and self.voiceChoices:
             if "default" in self.voiceChoices:
                 currentVoice = "default"
             else:
                 currentVoice = self.voiceChoices[0]
        
        self.voiceList = sHelper.addLabeledControl(
            "Voz:",
            wx.Choice,
            choices=self.voiceChoices
        )
        try:
            self.voiceList.SetStringSelection(currentVoice)
        except:
             if self.voiceChoices:
                 self.voiceList.SetSelection(0)

        self.chimeFiles = []
        self.chimeChoices = []
        self.chimes_dir = chimes_dir
        if os.path.isdir(chimes_dir):
            self.chimeFiles = [f for f in os.listdir(chimes_dir) if os.path.isfile(os.path.join(chimes_dir, f)) and f.lower().endswith('.wav')]
            self.chimeFiles.sort()
            self.chimeChoices = [os.path.splitext(f)[0] for f in self.chimeFiles]

        if not self.chimeChoices:
            self.chimeChoices.append("Nenhum som encontrado")

        currentChime = config.conf["relogioSonoro"]["chime"]
        if currentChime not in self.chimeFiles:
             if "Chime.wav" in self.chimeFiles:
                 currentChime = "Chime.wav"
             elif self.chimeFiles:
                 currentChime = self.chimeFiles[0]

        self.chimeList = sHelper.addLabeledControl(
            "Som de aviso:",
            wx.Choice,
            choices=self.chimeChoices
        )
        try:
            if currentChime in self.chimeFiles:
                self.chimeList.SetSelection(self.chimeFiles.index(currentChime))
        except:
            if self.chimeChoices:
                self.chimeList.SetSelection(0)

        self.chimeList.Bind(wx.EVT_CHOICE, self.onChimeSelection)
        self.ms_dir = os.path.join(sounds_dir, "ms")
        self.voiceList.Bind(wx.EVT_CHOICE, self.onVoiceSelection)

        self.playVoiceCheckbox = sHelper.addItem(
            wx.CheckBox(self, label="Reproduzir voz")
        )
        self.playVoiceCheckbox.SetValue(config.conf["relogioSonoro"]["playVoice"])

        self.playChimeCheckbox = sHelper.addItem(
            wx.CheckBox(self, label="Reproduzir som de aviso")
        )
        self.playChimeCheckbox.SetValue(config.conf["relogioSonoro"]["playChime"])

    def onChimeSelection(self, evt):
        try:
            selection = self.chimeList.GetSelection()
            if selection >= 0 and hasattr(self, "chimeFiles"):
                fullPath = os.path.join(self.chimes_dir, self.chimeFiles[selection])
                winsound.PlaySound(None, winsound.SND_PURGE)
                winsound.PlaySound(fullPath, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            log.error(f"Relógio Sonoro: Erro ao reproduzir prévia: {e}")
        evt.Skip()

    def onVoiceSelection(self, evt):
        try:
            voz = self.voiceChoices[self.voiceList.GetSelection()]
            audio = os.path.join(self.ms_dir, f"{voz}.wav")
            if os.path.exists(audio):
                winsound.PlaySound(None, winsound.SND_PURGE)
                winsound.PlaySound(audio, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            log.error(f"Relógio Sonoro: Erro ao reproduzir voz: {e}")
        evt.Skip()

    def onSave(self):
        config.conf["relogioSonoro"]["interval"] = self.intervalValues[self.intervalList.GetSelection()]
        config.conf["relogioSonoro"]["timeFormat"] = self.formatValues[self.formatList.GetSelection()]
        
        if self.voiceChoices:
            config.conf["relogioSonoro"]["voice"] = self.voiceChoices[self.voiceList.GetSelection()]
        
        if self.chimeChoices:
            selection = self.chimeList.GetSelection()
            selected_chime = self.chimeFiles[selection]
            if selected_chime != "Nenhum som encontrado":
                config.conf["relogioSonoro"]["chime"] = selected_chime
            
        config.conf["relogioSonoro"]["playVoice"] = self.playVoiceCheckbox.GetValue()
        config.conf["relogioSonoro"]["playChime"] = self.playChimeCheckbox.GetValue()

        try:
            somConfirmacao = os.path.join(os.path.dirname(__file__), "sounds", "config.wav")
            winsound.PlaySound(somConfirmacao, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except:
            pass

# ---------------------------------------------------------------------------
# GLOBAL PLUGIN UNIFICADO (Mesa de Efeitos + Relógio Sonoro)
# ---------------------------------------------------------------------------
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    
    # --- DICIONÁRIO DE ATALHOS PADRÕES DO NVDA ---
    # Isso garante que todos os comandos sejam aceitos imediatamente ao instalar o plugin!
    __gestures = {
        "kb:ctrl+h": "announceTime",
        "kb:alt+h": "ler_manual",
        "kb:alt+g": "openSettings",
        "kb:alt+v": "toggle_mesa",
        "kb:alt+,": "parar",
        "kb:alt+m": "toggle_musica",
        "kb:alt+n": "proxima_musica",
        "kb:alt+b": "musica_anterior",
        # Atalhos das Páginas
        "kb:alt+1": "pag1", "kb:alt+2": "pag2", "kb:alt+3": "pag3", "kb:alt+4": "pag4", "kb:alt+5": "pag5",
        "kb:alt+6": "pag6", "kb:alt+7": "pag7", "kb:alt+8": "pag8", "kb:alt+9": "pag9", "kb:alt+0": "pag10",
        # Teclado Superior
        "kb:1": "som1_sup", "kb:2": "som2_sup", "kb:3": "som3_sup", "kb:4": "som4_sup", "kb:5": "som5_sup",
        "kb:6": "som6_sup", "kb:7": "som7_sup", "kb:8": "som8_sup", "kb:9": "som9_sup", "kb:0": "som10_sup",
        # Teclado Numérico
        "kb:numpad1": "som1_num", "kb:numpad2": "som2_num", "kb:numpad3": "som3_num", "kb:numpad4": "som4_num", "kb:numpad5": "som5_num",
        "kb:numpad6": "som6_num", "kb:numpad7": "som7_num", "kb:numpad8": "som8_num", "kb:numpad9": "som9_num", "kb:numpad0": "som10_num",
    }

    def __init__(self):
        super(GlobalPlugin, self).__init__()
        
        # --- Inicialização do Relógio Sonoro ---
        gui.NVDASettingsDialog.categoryClasses.append(RelogioSonoroSettingsPanel)
        self.soundsDir_relogio = os.path.join(os.path.dirname(__file__), "sounds")
        self.relogio_worker = RelogioSoundWorker(self.soundsDir_relogio)
        self.lastAnnouncedTime = None
        
        self.timer = wx.Timer()
        self.timer.Bind(wx.EVT_TIMER, self.onTimer)
        self.timer.Start(5000)

        # --- Inicialização da Mesa de Efeitos ---
        self.ativo = False
        try:
            self.pagina_atual = config.conf["MesaEfeitos"]["pagina_atual"]
        except:
            self.pagina_atual = 1
        
        self.vinheta_worker = MesaSoundWorker(SONS_MESA_DIR)
        
        # Player de música da Mesa - MCI (winmm.dll)
        self.winmm = ctypes.windll.winmm
        self.musica_tocando = False
        self.musicas_lista = []
        self.musica_index = 0
        self.alias_mci = "mymusicplayer"
        
        self.atualizar_lista_musicas()

    def terminate(self):
        # Parando recursos do Relógio
        self.timer.Stop()
        self.relogio_worker.stop_playback()
        gui.NVDASettingsDialog.categoryClasses.remove(RelogioSonoroSettingsPanel)
        
        # Parando recursos da Mesa
        self.vinheta_worker.stop_playback()
        self.fechar_mci()
        
        super(GlobalPlugin, self).terminate()

    # -----------------------------------------------------------------------
    # MÉTODOS DO RELÓGIO SONORO
    # -----------------------------------------------------------------------
    def onTimer(self, evt):
        interval = config.conf["relogioSonoro"]["interval"]
        if interval == 0:
            return

        now = datetime.datetime.now()
        current_time = (now.day, now.hour, now.minute)
        if current_time != self.lastAnnouncedTime and (now.minute % interval == 0):
            self.lastAnnouncedTime = current_time
            self.announceTime()

    def get_wav_sequence(self):
        now = datetime.datetime.now()
        fmt = config.conf["relogioSonoro"]["timeFormat"]
        voice = config.conf["relogioSonoro"]["voice"]
        chime = config.conf["relogioSonoro"]["chime"]
        play_chime = config.conf["relogioSonoro"]["playChime"]
        play_voice = config.conf["relogioSonoro"]["playVoice"]

        sequence = []
        if play_chime:
            sequence.append(os.path.join("chimes", chime))

        if play_voice:
            sequence.append(os.path.join("voices", voice, "Start.wav"))
            hour = now.hour
            minute = now.minute

            if fmt == "12h":
                display_hour = hour
                if display_hour == 0:
                    display_hour = 12
                elif display_hour > 12:
                    display_hour -= 12
                sequence.append(os.path.join("voices", voice, "hours", f"{display_hour}.wav"))
            else:
                sequence.append(os.path.join("voices", voice, "hours", f"{hour}.wav"))

            sequence.append(os.path.join("voices", voice, "minutes", f"{minute}.wav"))

            if fmt == "12h":
                if hour >= 12:
                    sequence.append(os.path.join("voices", voice, "PM.wav"))
                else:
                    sequence.append(os.path.join("voices", voice, "AM.wav"))
        return sequence

    def announceTime(self):
        sequence = self.get_wav_sequence()
        log.info(f"Relógio Sonoro: Announcing time with sequence: {sequence}")
        self.relogio_worker.play(sequence)

    @scriptHandler.script(description="Anuncia a hora atual usando o Relógio Sonoro.", category="Relógio Sonoro")
    def script_announceTime(self, gesture):
        self.relogio_worker.stop_playback()
        self.announceTime()

    @scriptHandler.script(description="Abre o painel de configurações do Relógio Sonoro.", category="Relógio Sonoro")
    def script_openSettings(self, gesture):
        gui.mainFrame.prePopup()
        d = gui.NVDASettingsDialog(gui.mainFrame, initialCategory=RelogioSonoroSettingsPanel)
        d.Show()
        gui.mainFrame.postPopup()

    # -----------------------------------------------------------------------
    # SCRIPT PARA LER O MANUAL (Alt+H)
    # -----------------------------------------------------------------------
    @scriptHandler.script(description="Abre o manual de instruções do Addon.", category="Mesa de Efeitos")
    def script_ler_manual(self, gesture):
        caminho_manual = os.path.join(os.path.dirname(__file__), "leia.txt")
        if os.path.exists(caminho_manual):
            try:
                os.startfile(caminho_manual)
                ui.message("Abrindo o manual")
            except Exception as e:
                ui.message(f"Erro ao abrir arquivo: {str(e)}")
        else:
            ui.message("Erro: O arquivo leia.txt nao foi encontrado")

    # -----------------------------------------------------------------------
    # MÉTODOS DA MESA DE EFEITOS
    # -----------------------------------------------------------------------
    def enviar_mci(self, comando):
        buffer = ctypes.create_string_buffer(255)
        resultado = self.winmm.mciSendStringA(comando.encode('latin1'), buffer, 254, 0)
        return resultado, buffer.value.decode('latin1')

    def fechar_mci(self):
        self.enviar_mci(f"close {self.alias_mci}")

    def atualizar_lista_musicas(self):
        if os.path.exists(MUSICAS_MESA_DIR):
            self.musicas_lista = [f for f in os.listdir(MUSICAS_MESA_DIR) if f.lower().endswith(('.wav', '.mp3'))]
            self.musicas_lista.sort()

    def disparar_som(self, numero_tecla, gesture=None):
        if not self.ativo:
            if gesture:
                gesture.send()
            return

        indice_som = ((self.pagina_atual - 1) * 10) + numero_tecla
        nome_arquivo = f"{indice_som}.wav"
        
        full_path = os.path.join(SONS_MESA_DIR, nome_arquivo)
        if not os.path.exists(full_path):
            ui.message(f"Efeito {indice_som} não encontrado")
            return

        self.vinheta_worker.stop_playback()
        self.vinheta_worker.play(nome_arquivo)

    def alterar_pagina(self, numero, gesture=None):
        if not self.ativo:
            if gesture:
                gesture.send()
            return
            
        self.pagina_atual = numero
        config.conf["MesaEfeitos"]["pagina_atual"] = numero
        
        som_inicio = ((numero - 1) * 10) + 1
        som_fim = numero * 10
        ui.message(f"Página {numero} - Efeitos {som_inicio} a {som_fim}")

    def tocar_musica_mci(self, caminho):
        self.fechar_mci()
        buffer_caminho = ctypes.create_string_buffer(260)
        ctypes.windll.kernel32.GetShortPathNameA(caminho.encode('latin1'), buffer_caminho, 260)
        caminho_curto = buffer_caminho.value.decode('latin1')

        res_open, _ = self.enviar_mci(f"open {caminho_curto} alias {self.alias_mci}")
        if res_open == 0:
            res_play, _ = self.enviar_mci(f"play {self.alias_mci} repeat")
            if res_play == 0:
                return True
        return False

    @scriptHandler.script(description="Parar efeito")
    def script_parar(self, gesture):
        if not self.ativo:
            if gesture:
                gesture.send()
            return
        self.vinheta_worker.stop_playback()
        ui.message("Efeito parado")

    @scriptHandler.script(description="Ligar/desligar música")
    def script_toggle_musica(self, gesture):
        if not self.ativo:
            if gesture: gesture.send()
            return

        self.atualizar_lista_musicas()
        if not self.musicas_lista:
            ui.message("Nenhuma música na pasta 'musicas'")
            return

        if self.musica_tocando:
            self.fechar_mci()
            self.musica_tocando = False
            ui.message("Música desligada")
        else:
            if self.musica_index >= len(self.musicas_lista):
                self.musica_index = 0
            
            caminho = os.path.abspath(os.path.join(MUSICAS_MESA_DIR, self.musicas_lista[self.musica_index]))
            if not os.path.exists(caminho):
                ui.message("Arquivo não encontrado")
                return
            
            if self.tocar_musica_mci(caminho):
                self.musica_tocando = True
                ui.message(f"Tocando: {self.musicas_lista[self.musica_index]}")
            else:
                ui.message("Erro ao reproduzir")

    @scriptHandler.script(description="Próxima música")
    def script_proxima_musica(self, gesture):
        if not self.ativo:
            if gesture: gesture.send()
            return

        self.atualizar_lista_musicas()
        if not self.musicas_lista:
            ui.message("Nenhuma música")
            return

        self.musica_index = (self.musica_index + 1) % len(self.musicas_lista)
        if self.musica_tocando:
            caminho = os.path.abspath(os.path.join(MUSICAS_MESA_DIR, self.musicas_lista[self.musica_index]))
            self.tocar_musica_mci(caminho)
            ui.message(f"Próxima: {self.musicas_lista[self.musica_index]}")
        else:
            ui.message(f"Selecionada: {self.musicas_lista[self.musica_index]}")

    @scriptHandler.script(description="Música anterior")
    def script_musica_anterior(self, gesture):
        if not self.ativo:
            if gesture: gesture.send()
            return

        self.atualizar_lista_musicas()
        if not self.musicas_lista:
            ui.message("Nenhuma música")
            return

        self.musica_index = (self.musica_index - 1) % len(self.musicas_lista)
        if self.musica_tocando:
            caminho = os.path.abspath(os.path.join(MUSICAS_MESA_DIR, self.musicas_lista[self.musica_index]))
            self.tocar_musica_mci(caminho)
            ui.message(f"Anterior: {self.musicas_lista[self.musica_index]}")
        else:
            ui.message(f"Selecionada: {self.musicas_lista[self.musica_index]}")

    # --- MAPEAMENTO DOS ATALHOS DA MESA (DUPLO MODO ATIVO) ---
    @scriptHandler.script(description="Efeito 1 (Teclado Superior)")
    def script_som1_sup(self, gesture): self.disparar_som(1, gesture)
    
    @scriptHandler.script(description="Efeito 2 (Teclado Superior)")
    def script_som2_sup(self, gesture): self.disparar_som(2, gesture)
    
    @scriptHandler.script(description="Efeito 3 (Teclado Superior)")
    def script_som3_sup(self, gesture): self.disparar_som(3, gesture)
    
    @scriptHandler.script(description="Efeito 4 (Teclado Superior)")
    def script_som4_sup(self, gesture): self.disparar_som(4, gesture)
    
    @scriptHandler.script(description="Efeito 5 (Teclado Superior)")
    def script_som5_sup(self, gesture): self.disparar_som(5, gesture)
    
    @scriptHandler.script(description="Efeito 6 (Teclado Superior)")
    def script_som6_sup(self, gesture): self.disparar_som(6, gesture)
    
    @scriptHandler.script(description="Efeito 7 (Teclado Superior)")
    def script_som7_sup(self, gesture): self.disparar_som(7, gesture)
    
    @scriptHandler.script(description="Efeito 8 (Teclado Superior)")
    def script_som8_sup(self, gesture): self.disparar_som(8, gesture)
    
    @scriptHandler.script(description="Efeito 9 (Teclado Superior)")
    def script_som9_sup(self, gesture): self.disparar_som(9, gesture)
    
    @scriptHandler.script(description="Efeito 10 (Teclado Superior)")
    def script_som10_sup(self, gesture): self.disparar_som(10, gesture)

    @scriptHandler.script(description="Efeito 1 (Numpad)")
    def script_som1_num(self, gesture): self.disparar_som(1, gesture)
    
    @scriptHandler.script(description="Efeito 2 (Numpad)")
    def script_som2_num(self, gesture): self.disparar_som(2, gesture)
    
    @scriptHandler.script(description="Efeito 3 (Numpad)")
    def script_som3_num(self, gesture): self.disparar_som(3, gesture)
    
    @scriptHandler.script(description="Efeito 4 (Numpad)")
    def script_som4_num(self, gesture): self.disparar_som(4, gesture)
    
    @scriptHandler.script(description="Efeito 5 (Numpad)")
    def script_som5_num(self, gesture): self.disparar_som(5, gesture)
    
    @scriptHandler.script(description="Efeito 6 (Numpad)")
    def script_som6_num(self, gesture): self.disparar_som(6, gesture)
    
    @scriptHandler.script(description="Efeito 7 (Numpad)")
    def script_som7_num(self, gesture): self.disparar_som(7, gesture)
    
    @scriptHandler.script(description="Efeito 8 (Numpad)")
    def script_som8_num(self, gesture): self.disparar_som(8, gesture)
    
    @scriptHandler.script(description="Efeito 9 (Numpad)")
    def script_som9_num(self, gesture): self.disparar_som(9, gesture)
    
    @scriptHandler.script(description="Efeito 10 (Numpad)")
    def script_som10_num(self, gesture): self.disparar_som(10, gesture)

    # PÁGINAS DA MESA
    @scriptHandler.script(description="Página 1")
    def script_pag1(self, gesture): self.alterar_pagina(1, gesture)
    
    @scriptHandler.script(description="Página 2")
    def script_pag2(self, gesture): self.alterar_pagina(2, gesture)
    
    @scriptHandler.script(description="Página 3")
    def script_pag3(self, gesture): self.alterar_pagina(3, gesture)
    
    @scriptHandler.script(description="Página 4")
    def script_pag4(self, gesture): self.alterar_pagina(4, gesture)
    
    @scriptHandler.script(description="Página 5")
    def script_pag5(self, gesture): self.alterar_pagina(5, gesture)
    
    @scriptHandler.script(description="Página 6")
    def script_pag6(self, gesture): self.alterar_pagina(6, gesture)
    
    @scriptHandler.script(description="Página 7")
    def script_pag7(self, gesture): self.alterar_pagina(7, gesture)
    
    @scriptHandler.script(description="Página 8")
    def script_pag8(self, gesture): self.alterar_pagina(8, gesture)
    
    @scriptHandler.script(description="Página 9")
    def script_pag9(self, gesture): self.alterar_pagina(9, gesture)
    
    @scriptHandler.script(description="Página 10")
    def script_pag10(self, gesture): self.alterar_pagina(10, gesture)

    @scriptHandler.script(description="Ativar/desativar mesa")
    def script_toggle_mesa(self, gesture):
        self.ativo = not self.ativo
        if self.ativo:
            ui.message("Mesa de efeitos ligada")
        else:
            self.vinheta_worker.stop_playback()
            self.fechar_mci()
            self.musica_tocando = False
            ui.message("Mesa de efeitos desligada")

# --- Evento Adicional de Som ao Cancelar Configurações ---
_original_show = gui.NVDASettingsDialog.Show

def _show_with_cancel_sound(self):
    try:
        for child in self.GetChildren():
            if hasattr(child, "GetLabel") and child.GetLabel() == "&Cancelar":
                child.Bind(wx.EVT_BUTTON, _play_cancel_sound)
    except:
        pass
    return _original_show(self)

def _play_cancel_sound(evt):
    try:
        winsound.PlaySound(
            os.path.join(os.path.dirname(__file__), "sounds", "ms", "cancelar.wav"),
            winsound.SND_FILENAME | winsound.SND_ASYNC
        )
    except:
        pass
    evt.Skip()

gui.NVDASettingsDialog.Show = _show_with_cancel_sound
