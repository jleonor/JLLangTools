import os
from huggingface_hub import snapshot_download

# List of Hugging Face model repositories to download.
model_repos = [
    "openai/whisper-medium.en",
    "bofenghuang/whisper-medium-french",
    "openai/whisper-large-v2",
    "zuazo/whisper-medium-es",
    "openai/whisper-medium"
]

# Destination directory ("Whisper") in the current working directory.
destination_dir = "Whisper"
os.makedirs(destination_dir, exist_ok=True)

# Loop through each model repo and download it to its own subfolder.
for repo in model_repos:
    # Create a unique folder name for each model by replacing "/" with "_".
    local_path = os.path.join(destination_dir, repo.replace("/", "_"))

    # Check if the folder already exists, skip if it does.
    if os.path.exists(local_path):
        print(f"Skipping {repo}, already exists in {local_path}.\n")
        continue

    print(f"Downloading {repo} into {local_path}...")
    snapshot_download(repo_id=repo, local_dir=local_path)
    print(f"Finished downloading {repo}.\n")
