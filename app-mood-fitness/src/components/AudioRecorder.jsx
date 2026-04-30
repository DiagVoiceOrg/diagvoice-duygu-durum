import React, { useState, useRef, useCallback } from 'react';
import WaveSurfer from 'wavesurfer.js';
import RecordPlugin from 'wavesurfer.js/dist/plugins/record.esm.js';

const AudioRecorder = ({ onRecordingComplete, disabled }) => {
  const waveContainerRef = useRef(null);
  const wavesurferRef = useRef(null);
  const recordPluginRef = useRef(null);

  const [isRecording, setIsRecording] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioUrl, setAudioUrl] = useState('');

  const createWaveSurfer = useCallback(() => {
    if (wavesurferRef.current) {
      wavesurferRef.current.destroy();
    }
    return WaveSurfer.create({
      container: waveContainerRef.current,
      waveColor: '#A8A8A8',
      progressColor: '#0D9488',
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 80,
      cursorWidth: 1,
      cursorColor: 'transparent',
    });
  }, []);

  const startRecording = useCallback(async () => {
    setAudioUrl('');
    wavesurferRef.current = createWaveSurfer();

    const record = wavesurferRef.current.registerPlugin(
      RecordPlugin.create({ scrollingWaveform: true }),
    );
    recordPluginRef.current = record;

    record.on('record-end', (blob) => {
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
      onRecordingComplete(blob);
      record.destroy();
      wavesurferRef.current.load(url);
    });

    wavesurferRef.current.on('timeupdate', (currentTime) => {
      if (isRecording) record.render(currentTime);
    });

    try {
      await record.startRecording();
      setIsRecording(true);
    } catch (e) {
      console.error(e);
      alert('Mikrofon erişimi reddedildi veya bir hata oluştu.');
    }
  }, [createWaveSurfer, onRecordingComplete, isRecording]);

  const stopRecording = useCallback(() => {
    if (recordPluginRef.current) {
      recordPluginRef.current.stopRecording();
      setIsRecording(false);
    }
  }, []);

  const handlePlayPause = () => {
    if (wavesurferRef.current) {
      wavesurferRef.current.playPause();
      setIsPlaying(wavesurferRef.current.isPlaying());
    }
  };

  React.useEffect(() => {
    if (wavesurferRef.current && audioUrl) {
      wavesurferRef.current.on('play', () => setIsPlaying(true));
      wavesurferRef.current.on('pause', () => setIsPlaying(false));
    }
  }, [audioUrl]);

  return (
    <div className="card card-recorder">
      <h2>Mikrofon kaydı</h2>
      <div ref={waveContainerRef} className="waveform-container" />
      <div className="btn-row">
        {!isRecording ? (
          <button type="button" onClick={startRecording} disabled={disabled}>
            Kaydı başlat
          </button>
        ) : (
          <button type="button" onClick={stopRecording} disabled={!isRecording}>
            Kaydı durdur
          </button>
        )}
        {audioUrl && !isRecording && (
          <button type="button" onClick={handlePlayPause} className="secondary">
            {isPlaying ? 'Durdur' : 'Oynat'}
          </button>
        )}
      </div>
    </div>
  );
};

export default AudioRecorder;
