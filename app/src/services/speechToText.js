import axios from 'axios';

const API_URL =
  import.meta.env.VITE_VOICE_TO_TEXT_URL || "http://localhost:8051/transcribe";

export const speechToText = async (audioData) => {
  const formData = new FormData();
  formData.append("file", audioData, "audio.wav");

  try {
    const response = await axios.post(API_URL, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data.text;
  } catch (error) {
    console.error("Error calling Speech-to-text API:", error);
    const errorMessage = error.response ? JSON.stringify(error.response.data) : error.message;
    throw new Error(`Speech-to-text API error: ${errorMessage}`);
  }
};
