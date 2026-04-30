import { useState, useEffect } from 'react';

const AudioFilePicker = ({ onFileSelect, disabled }) => {
  const [selectedFile, setSelectedFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);

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
      onFileSelect(file, file.name);
    }
  };

  return (
    <div className="card card-file-picker">
      <h2>Bilgisayardan ses</h2>
      <input type="file" accept="audio/*" onChange={handleChange} disabled={disabled} />
      {selectedFile && (
        <>
          <div className="meta-row file-meta">
            <span className="meta-label">Seçilen</span>
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
                Tarayıcınız ses oynatmayı desteklemiyor.
              </audio>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default AudioFilePicker;
