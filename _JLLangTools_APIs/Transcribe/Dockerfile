# Use the official PyTorch GPU image as base (includes CUDA, cuDNN, etc.)
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

# Install ffmpeg (for audio processing)
RUN apt-get update && apt-get install -y ffmpeg

# Set the working directory
WORKDIR /app

# Copy the application files (except large models)
COPY requirements.txt .
COPY app.py .
COPY download_Whisper.py .

# Install Python dependencies
RUN pip install --upgrade pip && pip install --no-cache-dir --ignore-installed -r requirements.txt

# Expose the Flask app port
EXPOSE 5000

# Download the models when the container starts, then launch the app
CMD ["bash", "-c", "python3 download_Whisper.py && python3 app.py"]
