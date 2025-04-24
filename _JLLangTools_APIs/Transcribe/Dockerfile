# Dockerfile
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

RUN apt-get update && apt-get install -y ffmpeg

WORKDIR /app

# Install Python deps first so they layer-cache
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --ignore-installed -r requirements.txt

# Copy your application code
COPY app.py .
COPY download_Whisper.py .

# Copy the pre-downloaded models into the image
COPY Whisper ./Whisper

EXPOSE 5000

# Download the models when the container starts, then launch the app
CMD ["bash", "-c", "python3 download_Whisper.py && python3 app.py"]
