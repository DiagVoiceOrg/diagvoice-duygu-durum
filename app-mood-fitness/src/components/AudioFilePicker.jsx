import { useState, useEffect } from 'react';

const AudioFilePicker = ({ onFileSelect, disabled, labels }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);

  const L = labels || {};

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const handleChange = (e) => {
    const file = e.target.files?.[0] ?? null;
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setSelectedFile(file);
    if (file) {
      const url = URL.createObjectURL(file);
      setPreviewUrl(url);
      onFileSelect(file);
    }
  };

  return (
    <div className="card card-file-picker">
      <h2>{L.title}</h2>
      <input type="file" accept="audio/*" onChange={handleChange} disabled={disabled} />
      {selectedFile && (
        <>
          <div className="meta-row file-meta">
            <span className="meta-label">{L.selected}</span>
            <span className="meta-value">{selectedFile.name}</span>
          </div>
          {previewUrl && (
            <div className="file-preview-wrap">
              <audio
                className="file-preview-audio"
                controls
                src={previewUrl}
                preload="metadata"
              >
                {L.audioUnsupported}
              </audio>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default AudioFilePicker;
